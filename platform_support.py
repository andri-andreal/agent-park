"""What differs between operating systems, in one place: where files live and how to
look at running processes. Standard library only, except for psutil on Windows and macOS.

Linux reads /proc directly, exactly as the screensaver always did. Windows and macOS have no
/proc, so they ask psutil, which is the only extra package Agent Park ever needs.
"""

import os
from pathlib import Path
import sys

APP = "agent-park"


def is_windows():
    return sys.platform == "win32"


def home():
    return Path.home()


def state_base():
    """Where hooks drop session state: a runtime dir on Linux, per-user app data on Windows."""
    if is_windows():
        return os.environ.get("LOCALAPPDATA") or str(home() / "AppData" / "Local")
    return os.environ.get("XDG_RUNTIME_DIR") or str(home() / ".cache")


def data_base():
    """Where files that must outlive the app (the integration copy hooks point at) live."""
    if is_windows():
        return os.environ.get("LOCALAPPDATA") or str(home() / "AppData" / "Local")
    return os.environ.get("XDG_DATA_HOME") or str(home() / ".local" / "share")


def config_base():
    """The per-user config dir, as the Rust `dirs::config_dir()` AI Limit Monitor uses sees it."""
    if is_windows():
        return os.environ.get("APPDATA") or str(home() / "AppData" / "Roaming")
    if sys.platform == "darwin":
        return str(home() / "Library" / "Application Support")
    return os.environ.get("XDG_CONFIG_HOME") or str(home() / ".config")


def state_dir():
    return os.path.join(state_base(), APP)


def data_dir():
    return os.path.join(data_base(), APP)


def python_command():
    """The interpreter name that agents' hook plugins should spawn."""
    return os.environ.get("AGENT_PARK_PYTHON") or ("python" if is_windows() else "python3")


# --- processes ----------------------------------------------------------------------------
#
# A process source answers the same few questions on every OS. Every method raises OSError for
# a process that is gone or not ours to inspect, so callers handle one kind of failure.
#
#   pids()        every pid, newest snapshot (raises OSError when processes cannot be listed)
#   name(pid)     the process name, without ".exe" and lower-cased on Windows
#   args(pid)     its command line as a list, with "/" separators on Windows
#   parent(pid)   its parent's pid
#   cpu_ticks(pid)   CPU time used so far, in units of 1 / ticks_per_second seconds
#   rss_pages(pid)   resident memory, in units of page_size bytes
#   system()      whole-machine CPU, RAM, swap and load, as a SystemSample


class SystemSample:
    """Cumulative CPU time (idle, total), RAM and swap as (used, total) bytes, and the load."""

    def __init__(self, idle, total, ram, swap, load):
        self.idle, self.total, self.ram, self.swap, self.load = idle, total, ram, swap, load


def stat_fields(text):
    """The fields of /proc/<pid>/stat after the command name, which may itself hold spaces."""
    return text.rsplit(")", 1)[1].split()


class ProcFS:
    """Linux: straight from /proc, or from a copy of its layout (tests build one)."""

    def __init__(self, root="/proc"):
        self.root = str(root)
        self.ticks_per_second = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self.page_size = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096

    def read(self, path, binary=False):
        with open(f"{self.root}/{path}", "rb" if binary else "r") as file:
            return file.read()

    def pids(self):
        return [int(name) for name in os.listdir(self.root) if name.isdigit()]

    def name(self, pid):
        return self.read(f"{pid}/comm").strip()

    def args(self, pid):
        return self.read(f"{pid}/cmdline", binary=True).decode(errors="replace").split("\0")

    def fields(self, pid):
        try:
            return stat_fields(self.read(f"{pid}/stat"))
        except IndexError as error:
            raise OSError(f"cannot parse stat of {pid}") from error

    def parent(self, pid):
        try:
            return int(self.fields(pid)[1])
        except (ValueError, IndexError) as error:
            raise OSError(f"cannot read parent of {pid}") from error

    def cpu_ticks(self, pid):
        fields = self.fields(pid)
        try:
            return int(fields[11]) + int(fields[12])
        except (ValueError, IndexError) as error:
            raise OSError(f"cannot read CPU time of {pid}") from error

    def rss_pages(self, pid):
        try:
            return int(self.fields(pid)[21])
        except (ValueError, IndexError) as error:
            raise OSError(f"cannot read memory of {pid}") from error

    def system(self):
        try:
            cpu = [int(value) for value in self.read("stat").splitlines()[0].split()[1:]]
            info = {line.split(":")[0]: int(line.split()[1]) * 1024 for line in self.read("meminfo").splitlines()}
            load = float(self.read("loadavg").split()[0])
            memory = info["MemTotal"]
        except (ValueError, IndexError, KeyError) as error:
            raise OSError("cannot read system statistics") from error
        swap = info.get("SwapTotal", 0)
        return SystemSample(
            idle=sum(cpu[3:5]),  # idle + iowait
            total=sum(cpu[:8]),  # guest time is already part of user
            ram=(memory - info.get("MemAvailable", info.get("MemFree", 0)), memory),
            swap=(swap - info.get("SwapFree", swap), swap),
            load=load)


# psutil's cpu_times() fields, whichever of them this OS has.
CPU_FIELDS = ("user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal", "interrupt", "dpc")


class PsutilSource:
    """Windows and macOS (and Linux without /proc): the same answers through psutil."""

    ticks_per_second = 1  # cpu_ticks() is in seconds
    page_size = 1  # rss_pages() is in bytes

    def __init__(self, psutil=None):
        if psutil is None:
            import psutil
        self.psutil = psutil
        self.procs = {}

    def process(self, pid):
        try:
            return self.procs.get(pid) or self.psutil.Process(pid)
        except self.psutil.Error as error:
            raise OSError(str(error)) from error

    def call(self, pid, method):
        try:
            return getattr(self.process(pid), method)()
        except self.psutil.Error as error:
            raise OSError(str(error)) from error

    def pids(self):
        self.procs = {}
        try:
            for proc in self.psutil.process_iter(["name", "ppid"]):
                if proc.pid:  # 0 is the idle pseudo-process
                    self.procs[proc.pid] = proc
        except self.psutil.Error as error:
            raise OSError(str(error)) from error
        return list(self.procs)

    @staticmethod
    def clean(name):
        if is_windows():
            name = name.lower()
            if name.endswith(".exe"):
                name = name[:-4]
        return name

    def name(self, pid):
        known = (getattr(self.procs.get(pid), "info", None) or {}).get("name")
        return self.clean(known or self.call(pid, "name"))

    def args(self, pid):
        args = self.call(pid, "cmdline")
        return [arg.replace("\\", "/") for arg in args] if is_windows() else list(args)

    def parent(self, pid):
        known = (getattr(self.procs.get(pid), "info", None) or {}).get("ppid")
        return known if known is not None else self.call(pid, "ppid")

    def cpu_ticks(self, pid):
        times = self.call(pid, "cpu_times")
        return times.user + times.system

    def rss_pages(self, pid):
        return self.call(pid, "memory_info").rss

    def system(self):
        psutil = self.psutil
        try:
            times = psutil.cpu_times()
            memory, swap = psutil.virtual_memory(), psutil.swap_memory()
            try:
                load = float(psutil.getloadavg()[0])
            except (AttributeError, OSError):
                load = 0.0
        except psutil.Error as error:
            raise OSError(str(error)) from error
        return SystemSample(
            idle=times.idle + getattr(times, "iowait", 0),
            total=sum(getattr(times, field, 0) for field in CPU_FIELDS),
            ram=(memory.total - memory.available, memory.total),
            swap=(swap.used, swap.total),
            load=load)


class NullSource:
    """No way to look at processes here: every monitor simply finds nothing."""

    ticks_per_second = 100
    page_size = 4096

    def pids(self):
        raise OSError("no process source: install psutil (pip install psutil)")

    system = name = args = parent = cpu_ticks = rss_pages = lambda self, *_: self.pids()


def default_source():
    """/proc where there is one, else psutil if it is installed, else nothing."""
    if os.path.isdir("/proc/self"):
        return ProcFS()
    try:
        return PsutilSource()
    except ImportError:
        return NullSource()


def source_for(proc=None):
    """A process source for what a monitor was given: None, a /proc-style directory or a source."""
    if proc is None:
        return default_source()
    if isinstance(proc, (str, os.PathLike)):
        return ProcFS(proc)
    return proc


def describe(source=None):
    """One line for `doctor`: what processes are read through."""
    source = source or default_source()
    if isinstance(source, ProcFS):
        return f"available (Linux {source.root})"
    if isinstance(source, PsutilSource):
        return f"available (psutil {getattr(source.psutil, '__version__', '?')})"
    return "unavailable: install psutil (pip install psutil)"
