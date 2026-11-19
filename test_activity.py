"""Observed activity survives hooks and session matching without storing content."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import agent_hook
from screensaver import AgentMonitor, World, SPRITES, brief_activity, render_agent_info
from test_screensaver import Screen


class ActivityTests(unittest.TestCase):
    def source(self, kinds):
        return SimpleNamespace(ticks_per_second=100, pids=lambda: list(kinds),
                               name=lambda pid: kinds[pid], args=lambda pid: [kinds[pid]],
                               parent=lambda pid: 1, cpu_ticks=lambda pid: 0)

    def test_record_keeps_metadata_but_never_prompt_contents_or_commands(self):
        with tempfile.TemporaryDirectory() as root:
            event = {'hook_event_name': 'PreToolUse', 'cwd': '/private/projects/screensaver',
                     'prompt': 'SECRET PROMPT', 'tool_name': 'Edit',
                     'tool_input': {'file_path': '/private/projects/screensaver/agent_hook.py',
                                    'old_string': 'SECRET CONTENT', 'new_string': 'SECRET NEW'}}
            agent_hook.record('claude', event, 10, root, now=1000)
            path = Path(root) / '10.json'
            data = json.loads(path.read_text())
            self.assertEqual(data['context'], {'project': 'screensaver', 'activity': 'Editing agent_hook.py',
                                              'last_action': 'Editing agent_hook.py', 'updated_at': 1000})
            self.assertNotIn('SECRET', path.read_text())
            self.assertNotIn('/private', path.read_text())
            agent_hook.record('claude', {'hook_event_name': 'PostToolUse', 'tool_name': 'Edit'}, 10, root, now=1001)
            context = json.loads(path.read_text())['context']
            self.assertEqual(context['activity'], 'Thinking')
            self.assertEqual(context['last_action'], 'Editing agent_hook.py')
            agent_hook.record('claude', {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
                              'tool_input': {'command': 'TOKEN=SECRET python3 -m unittest'}}, 10, root, now=1002)
            self.assertEqual(json.loads(path.read_text())['context']['activity'], 'Running tests')
            self.assertNotIn('SECRET', path.read_text())
            agent_hook.record('claude', {'hook_event_name': 'Stop'}, 10, root, now=1003)
            self.assertEqual(json.loads(path.read_text())['context']['activity'], 'Idle')
            agent_hook.record('claude', {'hook_event_name': 'UserPromptSubmit'}, 10, root, now=1004)
            self.assertNotIn('last_action', json.loads(path.read_text())['context'])
            agent_hook.record('claude', {'hook_event_name': 'SessionStart'}, 10, root, now=1005)
            self.assertNotIn('project', json.loads(path.read_text())['context'])

    def test_activity_is_attached_to_its_session_and_cleared_when_hooks_end(self):
        with tempfile.TemporaryDirectory() as root:
            source = self.source({10: 'claude', 11: 'codex', 12: 'codex'})
            for kind, pid, session, project, tool in (
                ('claude', 10, '', 'park', 'Edit'),
                ('codex', 0, 'a', 'api', 'Read'),
                ('codex', 0, 'b', 'ui', 'Bash')):
                agent_hook.record(kind, {'hook_event_name': 'PreToolUse', 'session_id': session,
                    'cwd': '/projects/' + project, 'tool_name': tool,
                    'tool_input': {'file_path': 'app.py', 'command': 'npm test'}}, pid, root, now=1000)
            monitor = AgentMonitor(source, root, clock=lambda: 1000)
            sessions = monitor.poll(1)
            self.assertEqual({key: data['project'] for key, data in monitor.contexts.items()},
                             {10: 'park', 'codex:a': 'api', 'codex:b': 'ui'})
            world = World(120, 34, wild=False)
            world.sync_agents(sessions, contexts=monitor.contexts)
            self.assertEqual({a.agent: a.context['project'] for a in world.animals},
                             {10: 'park', 'codex:a': 'api', 'codex:b': 'ui'})
            with patch('screensaver.time.time', return_value=1001):
                self.assertEqual(brief_activity(world.animals[0]), 'Editing app.py')
            agent_hook.record('claude', {'hook_event_name': 'SessionEnd'}, 10, root, now=1001)
            monitor.poll(2)
            self.assertNotIn(10, monitor.contexts)

    def test_stale_context_is_not_presented_as_current_work(self):
        with tempfile.TemporaryDirectory() as root:
            agent_hook.record('claude', {'hook_event_name': 'PreToolUse', 'tool_name': 'Edit'},
                              10, root, now=1000)
            monitor = AgentMonitor(self.source({10: 'claude'}), root, clock=lambda: 1200)
            sessions = monitor.poll(1)
            self.assertEqual(sessions[10][1], 'idle')
            self.assertTrue(monitor.contexts[10]['stale'])
            world = World(80, 24, wild=False)
            world.sync_agents(sessions, contexts=monitor.contexts)
            self.assertEqual(brief_activity(world.animals[0]), '')
            screen = Screen(24, 80)
            with patch('screensaver.time.time', return_value=1200):
                render_agent_info(screen, world, dict.fromkeys(SPRITES, 0))
            self.assertIn('Last observed:', '\n'.join(''.join(row) for row in screen.rows))

    def test_safe_windows_names_and_malformed_tool_inputs(self):
        self.assertEqual(agent_hook.path_label(r'C:\work\project\app.py'), 'app.py')
        self.assertEqual(agent_hook.short_label('\x1b[31mhello\n\x00'), 'hello')
        for args in (None, [], '{broken', 123):
            self.assertEqual(agent_hook.tool_activity({'tool_name': 'Read', 'tool_input': args}), 'Reading a file')
        for command, expected in (('npm run build', 'Building project'), ('git diff --stat', 'Checking changes'),
                                  ('echo test', 'Running a command'), ('pip install pytest', 'Running a command'),
                                  ('curl https://example.com/SECRET', 'Running a command')):
            self.assertEqual(agent_hook.tool_activity({'tool_name': 'exec_command',
                              'tool_input': {'cmd': command}}), expected)

    def test_info_panel_scrolls_and_clips_with_missing_context(self):
        world = World(120, 34, wild=False)
        world.sync_agents({pid: ('claude', 'work') for pid in range(1, 13)})
        styles = dict.fromkeys(SPRITES, 0)
        for width, height in ((32, 12), (80, 24), (120, 34)):
            world.width, world.height = width, height
            for offset in (0, 5, 99):
                screen = Screen(height, width)
                render_agent_info(screen, world, styles, offset)
                self.assertIn('agents', '\n'.join(''.join(row) for row in screen.rows))

    @unittest.skipUnless(shutil.which('node'), 'needs node to load the OpenCode plugin')
    def test_opencode_tool_observations_keep_project_and_skip_helper_sessions(self):
        script = '''
          const { createTracker } = await import(process.argv[1]);
          const sent = [], on = createTracker(e => sent.push(e));
          await on({event: {type: "session.created", data: {id: "a", directory: "/projects/api"}}});
          await on({event: {type: "session.created", data: {id: "b", directory: "/projects/ui"}}});
          await on({event: {type: "session.created", data: {id: "kid", parentID: "a"}}});
          on.tool("PreToolUse", "a", "edit", {filePath: "/projects/api/app.py"});
          on.tool("PreToolUse", "b", "bash", {command: "npm test"});
          on.tool("PreToolUse", "kid", "read", {filePath: "helper.py"});
          on.tool("PostToolUse", "a", "edit");
          console.log(JSON.stringify(sent));
        '''
        plugin = Path(__file__).resolve().parent / 'opencode_plugin.js'
        result = subprocess.run(['node', '--input-type=module', '-e', script, plugin.as_uri()],
                                capture_output=True, text=True, check=True)
        events = json.loads(result.stdout)
        self.assertEqual([(e['session_id'], e['cwd']) for e in events],
                         [('a', '/projects/api'), ('b', '/projects/ui'), ('a', '/projects/api')])
        self.assertEqual(agent_hook.tool_activity(events[0]), 'Editing app.py')
        self.assertEqual(agent_hook.tool_activity(events[1]), 'Running tests')


if __name__ == '__main__':
    unittest.main()
