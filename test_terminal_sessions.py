"""Mouse selection and Konsole routing never type into an agent session."""
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from screensaver import AgentMonitor, World, clicked_agent, animal_offset
from terminal_sessions import terminal_for_pid, focus_terminal
import agent_hook


class TerminalTests(unittest.TestCase):
    def test_routes_only_accept_konsole_environment_fields(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / '42'
            path.mkdir()
            environment = path / 'environ'
            environment.write_bytes(b'SECRET=hidden\0KONSOLE_DBUS_SERVICE=:1.86\0KONSOLE_DBUS_SESSION=/Sessions/3\0')
            target = terminal_for_pid(42, root)
            self.assertEqual(target, {'kind': 'konsole', 'service': ':1.86', 'session': '/Sessions/3', 'pid': 42})
            self.assertNotIn('hidden', str(target))
            environment.write_bytes(b'TMUX_PANE=%1\0KONSOLE_DBUS_SERVICE=:1.86\0KONSOLE_DBUS_SESSION=/Sessions/3\0')
            self.assertIsNone(terminal_for_pid(42, root))
            environment.write_bytes(b'KONSOLE_DBUS_SERVICE=--help\0KONSOLE_DBUS_SESSION=/Sessions/3\0')
            self.assertIsNone(terminal_for_pid(42, root))
            self.assertIsNone(terminal_for_pid(999, root))

    def test_focus_finds_moved_tab_and_preserves_maximized_window(self):
        target = {'kind': 'konsole', 'service': ':1.86', 'session': '/Sessions/3', 'pid': 42}
        calls = []
        def run(*args):
            calls.append(args)
            if len(args) == 2:
                return '/Windows/1\n/Windows/2\n/konsole/MainWindow_7'
            if args[-1].endswith('sessionList'):
                return '1\n2' if args[2] == '/Windows/1' else '3\n4'
            if args[-1].endswith('minimized'):
                return 'false'
            return ''
        ok, _ = focus_terminal(target, run=run, which=lambda _: 'qdbus6', verify=lambda _: target)
        self.assertTrue(ok)
        self.assertIn(('qdbus6', ':1.86', '/Windows/2', 'org.kde.konsole.Window.setCurrentSession', '3'), calls)
        self.assertFalse(any('showNormal' in str(call) or 'sendText' in str(call) or 'runCommand' in str(call) for call in calls))

    def test_closed_and_unavailable_sessions_fail_without_switching(self):
        target = {'kind': 'konsole', 'service': ':1.86', 'session': '/Sessions/3', 'pid': 42}
        def fail(*args):
            raise subprocess.TimeoutExpired(args, 2)
        for candidate, run, which, verify in (
            (None, fail, lambda _: 'qdbus6', lambda _: target),
            (target, fail, lambda _: None, lambda _: target),
            (target, fail, lambda _: 'qdbus6', lambda _: None),
            (target, fail, lambda _: 'qdbus6', lambda _: target),
            (target, lambda *a: '', lambda _: 'qdbus6', lambda _: target),
        ):
            self.assertFalse(focus_terminal(candidate, run=run, which=which, verify=verify)[0])

    def test_duplicate_window_titles_do_not_raise_a_guessed_window(self):
        target = {'kind': 'konsole', 'service': ':1.86', 'session': '/Sessions/3', 'pid': 42}
        calls = []
        def run(*args):
            calls.append(args)
            if len(args) == 2:
                return '/Windows/2\n/konsole/MainWindow_1\n/konsole/MainWindow_2'
            if args[-1].endswith('sessionList'):
                return '3'
            return 'project : claude'
        ok, message = focus_terminal(target, run=run, which=lambda _: 'qdbus6', verify=lambda _: target)
        self.assertTrue(ok)
        self.assertIn('bring its Konsole window', message)
        self.assertFalse(any(call[-1].endswith('.raise') for call in calls))

    def test_shared_servers_only_use_unique_or_explicit_session_matches(self):
        for count in (1, 2):
            with tempfile.TemporaryDirectory() as root:
                pids = list(range(10, 10 + count))
                for i, pid in enumerate(pids):
                    path = Path(root) / str(pid)
                    path.mkdir()
                    path.joinpath('environ').write_bytes(
                        f'KONSOLE_DBUS_SERVICE=:1.86\0KONSOLE_DBUS_SESSION=/Sessions/{i+1}\0'.encode())
                    agent_hook.record('codex', {'hook_event_name': 'UserPromptSubmit', 'session_id': str(i)},
                                      0, root + '/state', now=1000)
                source = SimpleNamespace(root=root, ticks_per_second=100, pids=lambda: pids,
                                         name=lambda _: 'codex', args=lambda _: ['codex'],
                                         parent=lambda _: 1, cpu_ticks=lambda _: 0)
                monitor = AgentMonitor(source, root + '/state', clock=lambda: 1000)
                monitor.poll(1)
                self.assertEqual(len(monitor.terminals), 1 if count == 1 else 0)
                if count == 2:
                    source.args = lambda pid: ['codex', 'resume', str(pid - 10)]
                    monitor.poll(2)
                    self.assertEqual(monitor.terminals['codex:0']['pid'], 10)
                    self.assertEqual(monitor.terminals['codex:1']['pid'], 11)

    def test_hit_test_follows_bounce_layering_and_helper_parent(self):
        world = World(100, 30, wild=False)
        world.sync_agents({1: ('claude', 'work')})
        cat = world.animals[0]
        cat.entry, cat.x, cat.y, cat.phase, cat.state = 0, 10, 15, 1, 'work'
        for pixel_mode in (False, True):
            top = int(cat.y + animal_offset(world, cat))
            self.assertIs(clicked_agent(world, 12, top, pixel_mode), cat)
            self.assertIsNone(clicked_agent(world, 90, 25, pixel_mode))
        world.sync_kittens({1: [('kid', 'Explore')]})
        kitten = world.animals[1]
        kitten.entry, kitten.x, kitten.y = 0, 40, 20
        self.assertIs(clicked_agent(world, 42, 21, True), cat)
        cat.entry = 1
        self.assertIsNone(clicked_agent(world, 12, 15, True))


if __name__ == '__main__':
    unittest.main()
