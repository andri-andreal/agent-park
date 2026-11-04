"""Windows and macOS support, tested on any OS: a pretend psutil behaves like Windows does."""
from collections import namedtuple
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import agent_hook
import agent_park
import platform_support
from platform_support import NullSource, PsutilSource, ProcFS, default_source, source_for
from screensaver import AgentMonitor, ProcessWatcher, SystemMonitor

Times = namedtuple("Times", "user system idle interrupt dpc")
Memory = namedtuple("Memory", "total available")
Swap = namedtuple("Swap", "used total")
MemInfo = namedtuple("MemInfo", "rss")


class FakePsutil:
    """Just enough of psutil, with Windows habits: .exe names, backslashes, access denied."""
    __version__ = "9.9"

    class Error(Exception):
        pass

    class AccessDenied(Error):
        pass

    class NoSuchProcess(Error):
        pass

    def __init__(self):
        self.table = {}  # pid -> {"name", "ppid", "cmdline", "cpu", "rss", "denied"}
        self.times = Times(100.0, 50.0, 800.0, 5.0, 5.0)

    def add(self, pid, name, parent=4, cmdline=None, cpu=0.0, rss=0, denied=False):
        self.table[pid] = dict(name=name, ppid=parent, cmdline=cmdline or [name], cpu=cpu, rss=rss, denied=denied)

    def Process(self, pid):
        if pid not in self.table:
            raise self.NoSuchProcess(pid)
        return FakeProcess(self, pid)

    def process_iter(self, attrs=None):
        return [FakeProcess(self, pid) for pid in list(self.table)]

    def cpu_times(self):
        return self.times

    def virtual_memory(self):
        return Memory(16 << 30, 4 << 30)

    def swap_memory(self):
        return Swap(1 << 30, 8 << 30)

    def getloadavg(self):
        return (1.5, 1.0, 0.5)


class FakeProcess:
    def __init__(self, psutil, pid):
        self.psutil, self.pid, self.row = psutil, pid, psutil.table[pid]
        self.info = {"name": self.row["name"], "ppid": self.row["ppid"]}

    def guard(self):
        if self.pid not in self.psutil.table:
            raise self.psutil.NoSuchProcess(self.pid)
        if self.row["denied"]:
            raise self.psutil.AccessDenied(self.pid)

    def name(self):
        return self.row["name"]

    def ppid(self):
        return self.row["ppid"]

    def cmdline(self):
        self.guard()
        return self.row["cmdline"]

    def cpu_times(self):
        self.guard()
        return Times(self.row["cpu"], 0.0, 0.0, 0.0, 0.0)

    def memory_info(self):
        self.guard()
        return MemInfo(self.row["rss"])


def windows():
    """Pretend to be Windows for the names and paths platform_support builds."""
    return mock.patch.object(platform_support, "is_windows", return_value=True)


class PathTests(unittest.TestCase):
    def test_each_os_keeps_its_files_where_that_os_expects_them(self):
        env = {"LOCALAPPDATA": r"C:\Users\a\AppData\Local", "APPDATA": r"C:\Users\a\AppData\Roaming",
               "XDG_RUNTIME_DIR": "/run/user/1", "XDG_DATA_HOME": "/data", "XDG_CONFIG_HOME": "/conf"}
        with mock.patch.dict(os.environ, env), mock.patch.object(sys, "platform", "win32"):
            self.assertEqual(platform_support.state_dir(), os.path.join(env["LOCALAPPDATA"], "agent-park"))
            self.assertEqual(platform_support.data_dir(), os.path.join(env["LOCALAPPDATA"], "agent-park"))
            self.assertEqual(platform_support.config_base(), env["APPDATA"])
            self.assertEqual(platform_support.python_command(), "python")
        with mock.patch.dict(os.environ, env), mock.patch.object(sys, "platform", "linux"):
            self.assertEqual(platform_support.state_dir(), "/run/user/1/agent-park")
            self.assertEqual(platform_support.data_dir(), "/data/agent-park")
            self.assertEqual(platform_support.config_base(), "/conf")
            self.assertEqual(platform_support.python_command(), "python3")
        with mock.patch.dict(os.environ, env), mock.patch.object(sys, "platform", "darwin"):
            self.assertTrue(platform_support.config_base().endswith("Library/Application Support"))
        with mock.patch.dict(os.environ, {"AGENT_PARK_PYTHON": "py"}):
            self.assertEqual(platform_support.python_command(), "py")

    def test_missing_variables_fall_back_to_the_home_folder(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(sys, "platform", "win32"), \
                mock.patch.object(Path, "home", return_value=Path("/h")):
            self.assertEqual(Path(platform_support.state_base()), Path("/h/AppData/Local"))
            self.assertEqual(Path(platform_support.config_base()), Path("/h/AppData/Roaming"))


class SourceChoiceTests(unittest.TestCase):
    def test_what_a_monitor_is_given_becomes_a_source(self):
        self.assertIsInstance(source_for("/some/proc"), ProcFS)
        self.assertIsInstance(source_for(Path("/some/proc")), ProcFS)
        fake = NullSource()
        self.assertIs(source_for(fake), fake)

    def test_default_prefers_proc_then_psutil_then_nothing(self):
        with mock.patch("os.path.isdir", return_value=True):
            self.assertIsInstance(default_source(), ProcFS)
        with mock.patch("os.path.isdir", return_value=False):
            with mock.patch.dict(sys.modules, {"psutil": FakePsutil()}):
                self.assertIsInstance(default_source(), PsutilSource)
            with mock.patch.dict(sys.modules, {"psutil": None}):  # import psutil -> ImportError
                self.assertIsInstance(default_source(), NullSource)

    def test_describe_tells_doctor_what_to_do(self):
        self.assertIn("/proc", platform_support.describe(ProcFS("/proc")))
        self.assertIn("psutil 9.9", platform_support.describe(PsutilSource(FakePsutil())))
        self.assertIn("pip install psutil", platform_support.describe(NullSource()))


class PsutilSourceTests(unittest.TestCase):
    def setUp(self):
        self.psutil = FakePsutil()
        self.source = PsutilSource(self.psutil)

    def test_windows_names_lose_their_exe_and_their_case(self):
        self.psutil.add(10, "Claude.EXE", cmdline=[r"C:\Tools\claude.exe", "--x"])
        with windows():
            self.assertEqual(self.source.pids(), [10])
            self.assertEqual(self.source.name(10), "claude")
            self.assertEqual(self.source.args(10), ["C:/Tools/claude.exe", "--x"])  # "/" like everywhere else
        self.psutil.add(11, "Claude.EXE")
        with mock.patch.object(platform_support, "is_windows", return_value=False):
            self.source.pids()
            self.assertEqual(self.source.name(11), "Claude.EXE")  # elsewhere names are left alone

    def test_pid_zero_is_skipped_and_failures_become_oserror(self):
        self.psutil.add(0, "System Idle Process")
        self.psutil.add(4, "System", denied=True)
        self.assertEqual(self.source.pids(), [4])
        with self.assertRaises(OSError):
            self.source.cpu_ticks(4)  # access denied
        with self.assertRaises(OSError):
            self.source.args(999)  # gone

    def test_cpu_and_memory_use_seconds_and_bytes(self):
        self.psutil.add(10, "cargo", cpu=12.5, rss=3 << 30)
        self.source.pids()
        self.assertEqual((self.source.ticks_per_second, self.source.page_size), (1, 1))
        self.assertEqual(self.source.cpu_ticks(10), 12.5)
        self.assertEqual(self.source.rss_pages(10), 3 << 30)

    def test_system_sample(self):
        sample = self.source.system()
        self.assertEqual((sample.idle, sample.total), (800.0, 960.0))  # user+system+idle+interrupt+dpc
        self.assertEqual(sample.ram, ((16 << 30) - (4 << 30), 16 << 30))
        self.assertEqual((sample.swap, sample.load), ((1 << 30, 8 << 30), 1.5))
        del FakePsutil.getloadavg
        try:
            self.assertEqual(self.source.system().load, 0.0)  # no load average on this OS
        finally:
            FakePsutil.getloadavg = lambda self: (1.5, 1.0, 0.5)


class MonitorTests(unittest.TestCase):
    """The same monitors the terminal and the 3D app use, fed by the Windows-like source."""

    def setUp(self):
        self.psutil = FakePsutil()
        self.source = PsutilSource(self.psutil)
        self.state = tempfile.TemporaryDirectory()
        self.addCleanup(self.state.cleanup)
        patcher = windows()
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_agents_are_found_by_their_windows_names(self):
        self.psutil.add(10, "claude.exe", parent=2, cpu=0.0)
        self.psutil.add(11, "minimax-code.exe", parent=2, cpu=0.0)
        self.psutil.add(12, "node.exe", parent=2, cpu=0.0,
                        cmdline=[r"C:\Program Files\nodejs\node.exe", r"C:\x\node_modules\@minimax-ai\code\cli.js"])
        self.psutil.add(13, "node.exe", parent=2, cmdline=["node.exe", r"C:\x\server.js"])
        self.psutil.add(14, "chrome.exe", parent=2)
        monitor = AgentMonitor(self.source, state_dir=self.state.name)
        self.assertEqual(monitor.poll(0), {10: ("claude", "idle"), 11: ("mcode", "idle"), 12: ("mcode", "idle")})
        self.psutil.table[10]["cpu"] = 1.0  # a second of CPU in a second: working
        self.assertEqual(monitor.poll(1)[10], ("claude", "work"))

    def test_hook_state_still_wins_over_the_cpu_guess(self):
        self.psutil.add(10, "claude.exe", parent=2)
        with open(os.path.join(self.state.name, "10.json"), "w") as file:
            json.dump({"kind": "claude", "state": "wait", "time": 1}, file)
        monitor = AgentMonitor(self.source, state_dir=self.state.name, clock=lambda: 2)
        self.assertEqual(monitor.poll(0), {10: ("claude", "wait")})

    def test_a_session_that_is_gone_is_dropped(self):
        self.psutil.add(10, "claude.exe", parent=2)
        monitor = AgentMonitor(self.source, state_dir=self.state.name)
        self.assertEqual(list(monitor.poll(0)), [10])
        del self.psutil.table[10]
        self.assertEqual(monitor.poll(1), {})

    def test_heavy_new_processes_become_monsters(self):
        self.psutil.add(20, "explorer.exe", cpu=0.0)  # running before: never a monster
        watcher = ProcessWatcher(self.source)
        self.assertEqual(watcher.poll(0), [])
        self.psutil.add(21, "cargo.exe", cpu=0.0)
        self.psutil.add(22, "claude.exe", cpu=0.0, rss=9 << 30)  # an agent is a hero, not a monster
        self.psutil.add(23, "sleep.exe", cpu=0.0)
        self.assertEqual(watcher.poll(1), [])
        self.psutil.table[21]["cpu"] = 4.0
        self.psutil.table[22]["cpu"] = 4.0
        self.assertEqual(watcher.poll(3), [(21, "cargo", "CPU 200%")])
        self.psutil.add(24, "chrome.exe", rss=2 << 30)
        self.assertIn((24, "chrome", "RAM 2.0 GB"), watcher.poll(4))

    def test_system_panel_works(self):
        system = SystemMonitor(self.source)
        self.assertTrue(system.poll())
        self.assertIsNone(system.cpu)  # needs two samples
        self.psutil.times = Times(150.0, 75.0, 900.0, 5.0, 5.0)  # idle grew by 100 of 175
        self.assertTrue(system.poll())
        self.assertAlmostEqual(system.cpu, 1 - 100 / 175)
        self.assertEqual((system.ram, system.load), (((12 << 30), 16 << 30), 1.5))

    def test_without_a_source_everything_is_simply_empty(self):
        null = NullSource()
        self.assertEqual(AgentMonitor(null, state_dir=self.state.name).poll(0), {})
        self.assertEqual(ProcessWatcher(null).poll(0), [])
        self.assertFalse(SystemMonitor(null).poll())


class HookTests(unittest.TestCase):
    def test_session_is_found_through_the_windows_source(self):
        psutil = FakePsutil()
        psutil.add(30, "powershell.exe", parent=20)
        psutil.add(20, "claude.exe", parent=10)
        psutil.add(10, "claude.exe", parent=4)  # the outermost one is the session
        psutil.add(4, "explorer.exe", parent=0)
        source = PsutilSource(psutil)
        with windows():
            source.pids()
            self.assertEqual(agent_hook.session_pid("claude", source, start=30), 10)
            self.assertEqual(agent_hook.session_pid("codex", source, start=30), 0)

    def test_a_loop_of_recycled_pids_ends(self):
        psutil = FakePsutil()
        psutil.add(30, "cmd.exe", parent=31)
        psutil.add(31, "cmd.exe", parent=30)
        with windows():
            self.assertEqual(agent_hook.session_pid("claude", PsutilSource(psutil), start=30), 0)

    def test_replace_retries_while_the_screensaver_holds_the_file(self):
        calls = []

        def flaky(source, destination):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("in use")

        with mock.patch.object(agent_hook, "is_windows", return_value=True), \
                mock.patch("os.replace", flaky), mock.patch("time.sleep"):
            agent_hook.replace("a", "b")
        self.assertEqual(len(calls), 3)
        calls.clear()
        with mock.patch.object(agent_hook, "is_windows", return_value=False), mock.patch("os.replace", flaky):
            with self.assertRaises(PermissionError):  # elsewhere that is a real error
                agent_hook.replace("a", "b")
        self.assertEqual(len(calls), 1)


class SetupTests(unittest.TestCase):
    def windows_command(self, executable, on_path):
        with mock.patch.object(agent_park, "is_windows", return_value=True), \
                mock.patch.object(sys, "executable", executable), \
                mock.patch("shutil.which", return_value=on_path), \
                mock.patch.object(agent_park, "ROOT", Path("/opt/agent park")):
            return agent_park.command("claude")

    def test_windows_hook_command_never_starts_with_a_quoted_path(self):
        # PowerShell treats a leading "quoted path" as an expression; Git Bash and cmd accept either.
        exe = r"C:\Python312\python.exe"
        bare = self.windows_command(exe, on_path=exe)  # this is the python on PATH
        self.assertEqual(bare, 'python "/opt/agent park/agent_hook.py" claude')
        plain = self.windows_command(exe, on_path=None)  # not on PATH, but no spaces to quote
        self.assertEqual(plain, 'C:/Python312/python.exe "/opt/agent park/agent_hook.py" claude')
        spaced = self.windows_command(r"C:\Program Files\Python312\python.exe", on_path=None)
        self.assertEqual(spaced.count('"'), 4)  # a space leaves no choice but quotes; Git Bash and cmd cope
        self.assertNotIn("\\", spaced)

    def test_windows_hook_commands_are_recognised_again(self):
        for executable, on_path in ((r"C:\Python312\python.exe", r"C:\Python312\python.exe"),
                                    (r"C:\Python312\python.exe", None),
                                    (r"C:\Program Files\Python312\python.exe", None)):
            line = self.windows_command(executable, on_path)
            with mock.patch.object(agent_park, "is_windows", return_value=True), \
                    mock.patch.object(agent_park, "ROOT", Path("/opt/agent park")):
                hook = {"type": "command", "command": line}
                self.assertTrue(agent_park.equivalent_hook(hook, "claude"), line)
                self.assertFalse(agent_park.equivalent_hook(hook, "codex"), line)

    def test_opencode_config_is_never_split_across_two_folders_on_windows(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            appdata = home / "AppData/Roaming"
            env = {"APPDATA": str(appdata)}
            with mock.patch.object(agent_park, "HOME", home), mock.patch.dict(os.environ, env), \
                    mock.patch.object(agent_park, "is_windows", return_value=True):
                self.assertEqual(agent_park.opencode_plugin_path(), home / ".config/opencode/plugins/agent-park.js")
                (appdata / "opencode").mkdir(parents=True)  # the user's real config lives here
                self.assertEqual(agent_park.opencode_plugin_path(), appdata / "opencode/plugins/agent-park.js")
                (home / ".config/opencode").mkdir(parents=True)  # OpenCode prefers this when it exists
                self.assertEqual(agent_park.opencode_plugin_path(), home / ".config/opencode/plugins/agent-park.js")
            with mock.patch.object(agent_park, "HOME", home), mock.patch.dict(os.environ, env), \
                    mock.patch.object(agent_park, "is_windows", return_value=False):
                (home / ".config/opencode").rmdir()
                self.assertEqual(agent_park.opencode_plugin_path(), home / ".config/opencode/plugins/agent-park.js")

    def test_hook_command_on_linux_is_unchanged(self):
        with mock.patch.object(agent_park, "is_windows", return_value=False), \
                mock.patch.object(sys, "executable", "/usr/bin/python3"), \
                mock.patch.object(agent_park, "ROOT", Path("/opt/agent-park")):
            self.assertEqual(agent_park.command("claude"), "/usr/bin/python3 /opt/agent-park/agent_hook.py claude")

    def test_plugin_falls_back_to_a_wrapper_where_symlinks_are_not_allowed(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            target = root / "opencode_plugin.js"
            target.write_text("export default {}\n")
            link = root / "plugins" / "agent-park.js"
            with mock.patch.dict(agent_park.LINKS, {"opencode": (link, target)}), \
                    mock.patch.object(Path, "symlink_to", side_effect=OSError("privilege not held")):
                self.assertIn("installed", agent_park.configure("opencode"))
                self.assertFalse(link.is_symlink())
                text = link.read_text()
                self.assertIn(target.resolve().as_uri(), text)  # loads the real plugin, so it finds agent_hook.py
                self.assertIn("export { default }", text)
                self.assertEqual(agent_park.link_state(link, target), "wrapped")
                self.assertEqual(agent_park.configure("opencode"), "already installed")
                self.assertEqual(agent_park.configure("opencode", remove=True), "removed")
                self.assertFalse(link.exists())

    def test_a_file_that_is_not_ours_is_left_alone(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            target = root / "pi_extension.ts"
            target.write_text("x")
            link = root / "agent-park.ts"
            link.write_text("somebody else's extension")
            with mock.patch.dict(agent_park.LINKS, {"pi": (link, target)}):
                with self.assertRaises(ValueError):
                    agent_park.configure("pi")
                self.assertEqual(agent_park.link_state(link, target), "")
                self.assertEqual(link.read_text(), "somebody else's extension")

    def test_agents_are_found_with_their_windows_suffixes(self):
        with tempfile.TemporaryDirectory() as root:
            bin_dir = Path(root)
            (bin_dir / "claude.exe").write_text("")
            (bin_dir / "claude.exe").chmod(0o755)  # Windows counts any file as runnable; Linux needs this
            with mock.patch.object(agent_park, "HOME", bin_dir), mock.patch.object(agent_park, "BIN_DIRS", {"claude": bin_dir}), \
                    mock.patch("shutil.which", return_value=None):
                with mock.patch.object(agent_park, "is_windows", return_value=False):
                    self.assertIsNone(agent_park.find_agent("claude", "claude"))
                with mock.patch.object(agent_park, "is_windows", return_value=True):
                    self.assertEqual(agent_park.find_agent("claude", "claude"), str(bin_dir / "claude.exe"))


@unittest.skipUnless(os.path.isdir("/proc/self"), "needs Linux /proc to compare with")
class LiveComparisonTests(unittest.TestCase):
    """On a real machine /proc and psutil must tell the same story."""

    @classmethod
    def setUpClass(cls):
        try:
            import psutil
        except ImportError:
            raise unittest.SkipTest("psutil is not installed")
        cls.proc, cls.psutil = ProcFS(), PsutilSource(psutil)

    def test_this_process_looks_the_same_through_both(self):
        pid = os.getpid()
        self.proc.pids(), self.psutil.pids()
        self.assertEqual(self.proc.name(pid), self.psutil.name(pid))
        self.assertEqual(self.proc.parent(pid), self.psutil.parent(pid))
        self.assertEqual(self.proc.args(pid)[:-1] or self.proc.args(pid), self.psutil.args(pid))
        seconds = self.proc.cpu_ticks(pid) / self.proc.ticks_per_second
        self.assertAlmostEqual(seconds, self.psutil.cpu_ticks(pid), delta=1.0)
        rss = self.proc.rss_pages(pid) * self.proc.page_size
        self.assertAlmostEqual(rss, self.psutil.rss_pages(pid), delta=rss * 0.3)

    def test_the_two_agree_on_which_processes_exist(self):
        proc, psutil = set(self.proc.pids()), set(self.psutil.pids())
        self.assertLess(len(proc ^ psutil), max(10, len(proc) // 5))  # a few come and go while we look

    def test_the_machine_looks_the_same_through_both(self):
        a, b = self.proc.system(), self.psutil.system()
        self.assertEqual(a.ram[1], b.ram[1])
        self.assertAlmostEqual(a.ram[0], b.ram[0], delta=a.ram[1] * 0.05)
        self.assertEqual(a.swap[1], b.swap[1])

    def test_a_monitor_gets_the_same_agents_either_way(self):
        with tempfile.TemporaryDirectory() as state:
            by_proc = AgentMonitor(self.proc, state_dir=state).poll(0)
            by_psutil = AgentMonitor(self.psutil, state_dir=state).poll(0)
        self.assertEqual({pid: kind for pid, (kind, _) in by_proc.items()},
                         {pid: kind for pid, (kind, _) in by_psutil.items()})


if __name__ == "__main__":
    unittest.main()
