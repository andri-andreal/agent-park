import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import agent_park
import agent_hook


def can_symlink():
    with tempfile.TemporaryDirectory() as root:
        try:
            (Path(root) / "link").symlink_to(Path(root))
        except (OSError, NotImplementedError):
            return False
    return True


CAN_SYMLINK = can_symlink()


class SetupTests(unittest.TestCase):
    def test_launch_prompt_requires_opt_in(self):
        pending = [{"kind": "claude", "automatic": True, "configured": False}]
        with patch.object(agent_park, "integration_status", return_value=pending), patch.object(agent_park, "configure") as configure:
            agent_park.prompt_setup(input_fn=lambda _: "n", output=lambda _: None)
            configure.assert_not_called()
            agent_park.prompt_setup(input_fn=lambda _: "y", output=lambda _: None)
            configure.assert_called_once_with("claude")

    def test_desktop_setup_uses_persistent_files(self):
        with tempfile.TemporaryDirectory() as root:
            data = str(Path(root) / "data")
            env = dict(os.environ, HOME=root, USERPROFILE=root, XDG_DATA_HOME=data, LOCALAPPDATA=data)
            subprocess.run([sys.executable, str(agent_park.ROOT / "agent_park.py"), "onboarding-setup", "claude"],
                           env=env, check=True, capture_output=True, text=True)
            config = json.loads((Path(root) / ".claude/settings.json").read_text())
            command = config["hooks"]["Stop"][0]["hooks"][0]["command"]
            # Windows writes forward slashes into the command; elsewhere as_posix() changes nothing.
            self.assertIn((Path(root) / "data/agent-park/integration/agent_hook.py").as_posix(), command)
            self.assertTrue((Path(root) / "data/agent-park/integration/agent_hook.py").is_file())

    @unittest.skipIf(sys.platform == "win32", "POSIX permission bits do not exist on Windows")
    def test_hook_state_is_private(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / 'state'
            agent_hook.record('claude', {'hook_event_name': 'Stop'}, 42, str(state), now=100)
            self.assertEqual((state.stat().st_mode & 0o777), 0o700)
            self.assertEqual(((state / '42.json').stat().st_mode & 0o777), 0o600)

    def test_merge_is_idempotent_and_uninstall_preserves_other_hooks(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'settings.json'
            original = {'theme': 'dark', 'hooks': {'Stop': [{'matcher': 'x', 'hooks': [{'type': 'command', 'command': 'existing'}]}]}}
            path.write_text(json.dumps(original))
            with patch.dict(agent_park.EVENTS, {'claude': (path, ['Stop', 'PreToolUse'])}):
                agent_park.configure('claude')
                first = json.loads(path.read_text())
                agent_park.configure('claude')
                self.assertEqual(first, json.loads(path.read_text()))
                agent_park.configure('claude', remove=True)
                self.assertEqual(original, json.loads(path.read_text()))

    def test_invalid_configuration_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'settings.json'
            path.write_text('{ broken')
            with patch.dict(agent_park.EVENTS, {'claude': (path, ['Stop'])}):
                with self.assertRaises(ValueError):
                    agent_park.configure('claude')
            self.assertEqual('{ broken', path.read_text())

    def test_existing_manual_hook_is_not_duplicated_or_removed(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'settings.json'
            manual = {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': f'python3 {agent_park.ROOT}/agent_hook.py claude'}]}]}}
            path.write_text(json.dumps(manual))
            with patch.dict(agent_park.EVENTS, {'claude': (path, ['Stop'])}):
                agent_park.configure('claude')
                agent_park.configure('claude', remove=True)
            self.assertEqual(manual, json.loads(path.read_text()))

    def test_symlink_conflict_is_left_alone(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'plugin.js'
            path.write_text('user plugin')
            with patch.dict(agent_park.LINKS, {'pi': (path, Path(root) / 'target')}):
                with self.assertRaises(ValueError):
                    agent_park.configure('pi')
                self.assertEqual('user plugin', path.read_text())

    @unittest.skipUnless(CAN_SYMLINK, "creating symlinks needs Developer Mode or elevation on Windows")
    def test_symlink_uninstall_only_removes_our_link(self):
        with tempfile.TemporaryDirectory() as root:
            path, target = Path(root) / 'plugin.js', Path(root) / 'target'
            target.write_text('extension')
            with patch.dict(agent_park.LINKS, {'pi': (path, target)}):
                agent_park.configure('pi')
                self.assertEqual(path.resolve(), target)
                agent_park.configure('pi', remove=True)
                self.assertFalse(path.exists())
                self.assertTrue(target.exists())


class CommandParsingTests(unittest.TestCase):
    def test_windows_commands_keep_their_backslashes(self):
        windows = r'"C:\Program Files\Python312\python.exe" "C:\Users\a\agent_hook.py" claude'
        with patch.object(agent_park, "is_windows", return_value=True):
            self.assertEqual(agent_park.split_command(windows),
                             [r"C:\Program Files\Python312\python.exe", r"C:\Users\a\agent_hook.py", "claude"])
            self.assertEqual(agent_park.split_command("python C:/x/agent_hook.py claude"),
                             ["python", "C:/x/agent_hook.py", "claude"])
        with patch.object(agent_park, "is_windows", return_value=False):
            self.assertEqual(agent_park.split_command("'/a b/python' /x/agent_hook.py claude"),
                             ["/a b/python", "/x/agent_hook.py", "claude"])


class ProcessNameTests(unittest.TestCase):
    def test_mcode_is_recognised_under_both_of_its_process_names(self):
        # Older MCode runs as node with its script path, newer as a process titled minimax-code.
        self.assertEqual(agent_hook.agent_of("minimax-code", ["minimax-code"]), "mcode")
        self.assertEqual(agent_hook.agent_of("node", ["node", "/x/@minimax-ai/code/cli.js"]), "mcode")
        self.assertEqual(agent_hook.agent_of("node", ["node", "server.js"]), "node")


if __name__ == "__main__":
    unittest.main()
