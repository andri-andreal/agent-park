#!/usr/bin/env python3
"""A tiny, unpredictable ASCII animal park. Standard library only."""

import curses
from dataclasses import dataclass
import json
import math
import os
import random
import re
import sys
import time
from urllib.parse import urlsplit

from agent_hook import AGENT_PROCESSES, HELPER_ARGS, STATE_DIR


# Artwork faces left; each animal is mirrored when walking right.
SPRITES = {
    "kucing": (
        (r" /\_/\ ", "( o.o )____", " > ^ <    )~", "  / /--/ /"),
        (r" /\_/\ ", "( o.o )____", " > ^ <    )~", "  \\ \\--\\ \\"),
    ),
    "anjing": (
        (" /\\__", "(o   /____", " /_ /     )~", "   / /--/ /"),
        (" /\\__", "(o   /____", " /_ /     )~", "   \\ \\--\\ \\"),
    ),
    "kelinci": (
        (" (\\(\\", " (o.o)___", " / >     )o", "  / /--/ /"),
        (" (\\(\\", " (o.o)___", " / >     )o", "  (_/  (_/"),
    ),
    "bebek": (
        ("  __", "<(o )___", " ( ._> /", "  /___/"),
        ("  __", "<(o )___", " ( ._> /", "   /_/"),
    ),
    "tikus": (
        ("  ()_()", " <'  . )__", "  (______ )~~", "   / / / /"),
        ("  ()_()", " <'  . )__", "  (______ )~~", "   \\ \\ \\ \\"),
    ),
}
# Subagents show up as babies of their parent's species; they are never
# picked for random spawns.
ART = {**SPRITES,
    "anak kucing": (
        (r" /\_/\ ", "( o.o )", ' (")(")'),
        (r" /\_/\ ", "( o.o )", '(")(") '),
    ),
    "anak anjing": (
        (r" /\_", "(o  /)~", ' (")(")'),
        (r" /\_", "(o  /)~", '(")(") '),
    ),
    "anak kelinci": (
        (" (\\(\\", " (o.o)", ' (")(")'),
        (" (\\(\\", " (o.o)", '(")(") '),
    ),
    "anak bebek": (
        ("  _", "<(o)_", " (__/"),
        ("  _", "<(o)_", "  (_/"),
    ),
    "anak tikus": (
        (" ()_()", "<'. )~", ' (")(")'),
        (" ()_()", "<'. )~", '(")(") '),
    ),
}
MIRROR = str.maketrans("/\\()<>[]", "\\/)(><][")
FIGHT_FRAMES = (
    ("   .-~~~~-.", "  ( # @ !  )", " ( ! * # @  )", "  `-~~~~~~-'"),
    ("   .-~~~~-.", " ( * ! # @  )", "  ( @ # *  )", "  `-~~~~~~-'"),
)
PLACES = ("Park", "Forest", "Beach", "Village")
PLACE_DURATION = 35.0
TREE = (r"   /\   ", r"  /^^\  ", r" /^^^^\ ", "   ||   ")
PALM = (r" \  |  / ", r"  \ | /  ", r" ---+--- ", "    |    ")
HOUSE = (r"   /\   ", r"  /__\  ", " | [] | ", " |__|_| ")
BENCH = ("|_______|", "|_______|", " ||   || ")
MONSTER = (r"  /\  /\  ", " ( >  < ) ", " /|####|\\ ", "  /    \\  ")
RAID_PHASES = (
    ("datang", 3.0, "LOOK OUT! A monster is coming! All animals, gather!"),
    ("tangkis", 6.0, "Stand together! BLOCK! No one gets hurt."),
    ("lawan", 11.0, "Now! All animals, strike back!"),
    ("menang", 14.0, "WE WON! The monster fled! Long live team animal!"),
)
# Monsters are real: a process started after the screensaver that hogs a
# core or a lot of memory. Each one attacks once; the park then rests.
MONSTER_CPU = 0.9  # cores, averaged over MONSTER_WINDOW seconds
MONSTER_RSS = 1 << 30  # bytes
MONSTER_WINDOW = 3
RAID_COOLDOWN = 30.0
# AI coding agents found in /proc each get their own animal. Process name ->
# (name, species, 256-colour shade, fallback on 8-colour terminals).
AGENTS = {
    "claude": ("Claude", "kucing", 208, curses.COLOR_RED),  # orange
    "codex": ("Codex", "anjing", 39, curses.COLOR_BLUE),
    "opencode": ("OpenCode", "kelinci", 141, curses.COLOR_MAGENTA),  # lilac
    "kiro-cli": ("Kiro", "tikus", 99, curses.COLOR_MAGENTA),  # violet
    "aider": ("Aider", "tikus", 114, curses.COLOR_GREEN),
    "goose": ("Goose", "bebek", 229, curses.COLOR_YELLOW),
    "crush": ("Crush", "kucing", 205, curses.COLOR_MAGENTA),  # pink
    "amp": ("Amp", "anjing", 203, curses.COLOR_RED),
    "pi": ("Pi", "bebek", 45, curses.COLOR_CYAN),  # pi sets its process title
    "strix": ("Strix", "anjing", 160, curses.COLOR_RED),  # dark red
}
# Working agent cats gather in an office on the right of the ground; the
# rest of the park is the playground everyone else (and idle cats) uses.
OFFICE_MIN_SCREEN = 72  # narrower screens share one big park instead
# Each working cat gets its own desk: the cat sits left, facing its computer.
COMPUTER = (".-------.", "|       |", "'-------'", "  _|_|_  ")
DESK_WIDTH = 23  # agent animal (<= 12) + gap + computer (9) + aisle
DESK_ROWS = 5  # a cat is 4 rows tall, plus room for its name
SCREEN_TEXT = (">_ make", "{ ok! }", "[###  ]", "[#### ]", "git add", "404?!..", ">_ test", "[#####]")
AGENT_POLL = 1.0
AGENT_WINDOW = 3  # seconds of CPU history averaged per verdict
AGENT_HOPS = 3  # unknown processes looked past between an agent and its own child
AGENT_BUSY_CPU = 0.025  # an idle TUI waiting for input stays below ~2%
# Hooks (agent_hook.py) report work/wait/idle exactly. Claude sends no event
# when you interrupt it, so a "work" report this old yields to an idle CPU.
HOOK_STALE = 90.0
# Working cats zoom around the park and change course often.
WORK_SPEED = 2.2
WORK_CHATTER = ("tik tak tuk!", "coding!!", "wooosh!", "busy busy!", "compile!", "full speed!")
# How agent cats arrive: (seconds, announcement). Picked at random per cat.
ENTRANCES = {
    "meteor": (3.0, "A METEOR fell into the park! Oh... it's {name}!"),
    "ufo": (3.5, "A UFO landed! {name} was lowered by a beam."),
    "portal": (3.0, "A portal opened! {name} jumped out."),
    "parasut": (3.5, "{name} parachuted into the park. Wheee!"),
    "teleport": (2.5, "Bzzt... {name} teleported into the park."),
}
KITTEN_ENTRANCE = ("pop", 0.8)
UFO = ("   _.---._   ", " (_o_o_o_o_) ")
PARACHUTE = ("  .-~~~-.  ", " /_______\\ ", "  \\  |  /  ")
NOISE = "#%@&$?!*+=~"
# The system panel (top right): a tiny btop with a cat keeping watch.
SYSTEM_BUSY = 0.6  # CPU fraction where the cat starts to worry
SYSTEM_ALARM = 0.85  # CPU fraction where it sounds the alarm
RAM_ALARM = 0.9
SYSTEM_HISTORY = 24  # CPU samples in the sparkline, one per poll
SYSTEM_WIDTH = 28
SPARK = "_.:-=+*#%@"
ROUTER = "ccx-router"  # local proxy started by ccx for OpenAI-compatible profiles
ROUTER_WIDTH = 28
ROUTER_SHOWN = 3  # more routers than this collapse into "+N more"
STATS_WIDTH = 22  # the park-stats box in the top-left when no router is shown
MODEL_WIDTH = 18  # longer model names are cut in labels
KITTENS_PER_CAT = 4  # more subagents than this would bury their parent
SUBAGENT_STALE = 1800.0  # a subagent whose stop event never came


def short_model(model):
    """"anthropic/claude-opus-4-20250514" -> "opus-4": fits a label."""
    model = model.rsplit("/", 1)[-1]
    model = re.sub(r"-\d{8}$", "", model)
    model = model.removeprefix("claude-")
    return model if len(model) <= MODEL_WIDTH else model[:MODEL_WIDTH - 1] + "~"


@dataclass(eq=False)
class Animal:
    species: str
    x: float
    y: float
    vx: float
    vy: float
    state: str = "walk"
    timer: float = 5.0
    cooldown: float = 3.0
    visitor: bool = False
    phase: float = 0.0
    agent: object = 0  # session pid, or "kind:session id" for shared Codex sessions
    agent_kind: str = ""
    name: str = ""
    status: str = "idle"  # work, wait (needs you) or idle
    model: str = ""  # the agent's model, when its hook knows it
    sub: str = ""  # subagent id: this kitten helps the cat whose session is `agent`
    entrance: str = ""  # arrival effect still playing (see ENTRANCES)
    entry: float = 0.0  # seconds of that effect left
    desk: int = -1  # office desk while working (see World.desks)
    seated: bool = False  # at that desk, typing

    @property
    def width(self):
        return max(len(line) for frame in ART[self.species] for line in frame)


@dataclass
class Encounter:
    kind: str
    first: Animal
    second: Animal
    timer: float


@dataclass
class Raid:
    age: float = 0.0
    monster: str = "misterius"

    @property
    def phase(self):
        return next((name for name, end, _ in RAID_PHASES if self.age < end), "selesai")

    @property
    def health(self):
        return round(100 * max(0, min(1, (11 - self.age) / 5)))


class AgentMonitor:
    """Polls /proc for AI agent sessions and guesses if they are working."""

    def __init__(self, proc="/proc", state_dir=STATE_DIR, clock=time.time):
        self.proc, self.state_dir, self.clock = proc, state_dir, clock
        self.subagents = {}  # session key -> [(agent id, agent type)], set by poll
        self.models = {}  # session key -> model name its hook reported, set by poll
        self.ticks_per_second = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self.history = {}

    def read(self, pid):
        with open(f"{self.proc}/{pid}/comm") as file:
            kind = file.read().strip()
        kind = AGENT_PROCESSES.get(kind, kind)
        if kind not in AGENTS:
            return None
        with open(f"{self.proc}/{pid}/cmdline", "rb") as file:
            args = file.read().decode(errors="replace").split("\0")
        helper = any(arg in HELPER_ARGS for arg in args)
        with open(f"{self.proc}/{pid}/stat") as file:
            # The command name may contain spaces, so split after its ")".
            fields = file.read().rsplit(")", 1)[1].split()
        return kind, helper, int(fields[1]), int(fields[11]) + int(fields[12])

    def parent_of(self, pid):
        try:
            with open(f"{self.proc}/{pid}/stat") as file:
                return int(file.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            return 0

    def hook_status(self, pid, kind, busy):
        try:
            with open(f"{self.state_dir}/{pid}.json") as file:
                data = json.load(file)
        except (OSError, ValueError):
            return None
        if data.get("kind") != kind or data.get("state") not in ("work", "wait", "idle"):
            return None
        if data.get("model"):
            self.models[pid] = str(data["model"])
        if data["state"] == "work" and not busy and self.clock() - data.get("time", 0) > HOOK_STALE:
            return "idle"
        return data["state"]

    def shared_sessions(self, kind, windows):
        """Newest hook states written by a shared helper, one per open window."""
        try:
            names = [n for n in os.listdir(self.state_dir)
                     if n.startswith(f"{kind}-") and n.endswith(".json") and ".sub-" not in n]
        except OSError:
            return []
        sessions = []
        for name in names:
            path = f"{self.state_dir}/{name}"
            if not windows:
                try:
                    os.remove(path)  # every window is closed: nothing to show
                except OSError:
                    pass
                continue
            try:
                with open(path) as file:
                    data = json.load(file)
            except (OSError, ValueError):
                continue
            if data.get("state") in ("work", "wait", "idle"):
                sessions.append((data.get("time", 0), name[len(kind) + 1:-5], data["state"],
                                 str(data.get("model") or "")))
        return sorted(sessions, reverse=True)[:windows]

    def read_subagents(self, found):
        """Running subagents per session key, oldest first."""
        bases = {str(key).replace(":", "-", 1): key for key in found}
        try:
            names = os.listdir(self.state_dir)
        except OSError:
            names = []
        subagents = {}
        for name in names:
            if ".sub-" not in name or not name.endswith(".json"):
                continue
            base, agent = name[:-len(".json")].split(".sub-", 1)
            path = f"{self.state_dir}/{name}"
            try:
                with open(path) as file:
                    data = json.load(file)
            except (OSError, ValueError):
                continue
            if self.clock() - data.get("time", 0) > SUBAGENT_STALE:
                try:
                    os.remove(path)
                except OSError:
                    pass
            elif base in bases:
                subagents.setdefault(bases[base], []).append(
                    (data.get("time", 0), agent, str(data.get("type") or "subagent")))
        return {key: [(agent, kind) for _, agent, kind in sorted(subs)]
                for key, subs in subagents.items()}

    def forget_dead(self, pids):
        """Drop state files of sessions that ended without a SessionEnd hook."""
        try:
            names = os.listdir(self.state_dir)
        except OSError:
            return
        for name in names:
            stem = name.split(".", 1)[0]
            if name.endswith(".json") and stem.isdigit() and int(stem) not in pids:
                try:
                    os.remove(f"{self.state_dir}/{name}")
                except OSError:
                    pass

    def poll(self, now):
        """Return {pid: (kind, status)} for every running agent session."""
        try:
            pids = [int(name) for name in os.listdir(self.proc) if name.isdigit()]
        except OSError:
            return {}  # no /proc (e.g. macOS): no agent cats
        procs = {}
        for pid in pids:
            try:
                info = self.read(pid)
            except (OSError, ValueError, IndexError):
                continue  # process exited mid-read or is not ours to inspect
            if info:
                procs[pid] = info
        for pid, (kind, helper, parent, ticks) in procs.items():
            # Look past a few unknown middlemen, e.g. kiro-cli-chat -> bun -> kiro-cli-chat.
            hops = parent
            for _ in range(AGENT_HOPS):
                if hops in procs or hops <= 1:
                    break
                hops = self.parent_of(hops)
            if hops in procs:
                procs[pid] = kind, helper, hops, ticks
        sessions = {pid: [kind, ticks] for pid, (kind, helper, parent, ticks) in procs.items()
                    if not helper and parent not in procs}
        for pid, (kind, helper, parent, ticks) in procs.items():
            while parent in procs and parent not in sessions:
                parent = procs[parent][2]
            if pid not in sessions and parent in sessions:
                sessions[parent][1] += ticks
        found, self.models = {}, {}
        for pid, (kind, ticks) in sessions.items():
            samples = self.history.get(pid, [])[-AGENT_WINDOW:] + [(now, ticks)]
            self.history[pid] = samples
            (start, first), (end, last) = samples[0], samples[-1]
            busy = end > start and (last - first) / self.ticks_per_second / (end - start) >= AGENT_BUSY_CPU
            found[pid] = kind, self.hook_status(pid, kind, busy) or ("work" if busy else "idle")
        self.history = {pid: self.history[pid] for pid in found}
        self.forget_dead(set(pids))
        for kind in AGENTS:
            # Shared-helper sessions replace windows one for one; windows that
            # never sent a hook keep their CPU guess.
            windows = sorted(pid for pid, (k, _) in found.items() if k == kind)
            shared = self.shared_sessions(kind, len(windows))
            for pid in windows[:len(shared)]:
                del found[pid]
            for _, session, status, model in shared:
                found[f"{kind}:{session}"] = kind, status
                if model:
                    self.models[f"{kind}:{session}"] = model
        self.subagents = self.read_subagents(found)
        return found


class ProcessWatcher:
    """Spots processes started after the screensaver that turn heavy."""

    def __init__(self, proc="/proc"):
        self.proc = proc
        self.ticks_per_second = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self.page = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
        self.known = None  # {pid: name} running when we started: never monsters
        self.history = {}
        self.fought = set()

    def poll(self, now):
        """Return [(pid, name, detail)] of current monsters, heaviest first."""
        try:
            pids = {int(name) for name in os.listdir(self.proc) if name.isdigit()}
        except OSError:
            return []
        names = {}
        for pid in pids:
            try:
                with open(f"{self.proc}/{pid}/comm") as file:
                    names[pid] = file.read().strip()
            except OSError:
                pass
        if self.known is None:
            self.known = names
        # A process that exec()s another program (sh -c "cargo build") keeps
        # its pid but changes its name: from then on it counts as new.
        self.known = {pid: name for pid, name in self.known.items() if names.get(pid) == name}
        self.fought &= pids
        monsters = []
        for pid in names.keys() - self.known.keys() - self.fought - {os.getpid()}:
            name = names[pid]
            try:
                with open(f"{self.proc}/{pid}/stat") as file:
                    # The command name may contain spaces, so split after its ")".
                    fields = file.read().rsplit(")", 1)[1].split()
                ticks, rss = int(fields[11]) + int(fields[12]), int(fields[21]) * self.page
            except (OSError, ValueError, IndexError):
                continue
            if name in AGENTS or name in AGENT_PROCESSES or name == ROUTER:
                continue  # agents and their routers are the heroes, not the monsters
            samples = self.history.get(pid, [])[-MONSTER_WINDOW:] + [(now, ticks)]
            self.history[pid] = samples
            (start, first), (end, last) = samples[0], samples[-1]
            # Judge CPU over a few seconds so a busy start-up does not count.
            cpu = (last - first) / self.ticks_per_second / (end - start) if end - start >= 2 else 0
            if cpu >= MONSTER_CPU:
                monsters.append((1, cpu, pid, name, f"CPU {round(cpu * 100)}%"))
            elif rss >= MONSTER_RSS:
                monsters.append((0, rss, pid, name, f"RAM {rss / (1 << 30):.1f} GB"))
        self.history = {pid: self.history[pid] for pid in self.history if pid in pids}
        # Busy processes first: they are doing something right now.
        return [(pid, name, detail) for _, _, pid, name, detail in sorted(monsters, reverse=True)]


class SystemMonitor:
    """Whole-machine CPU, RAM, swap and load from /proc."""

    def __init__(self, proc="/proc"):
        self.proc = proc
        self.last = None  # (idle, total) jiffies at the previous poll
        self.cpu = None  # busy fraction since the previous poll
        self.history = []  # recent CPU fractions, oldest first
        self.ram = self.swap = (0, 0)  # (used, total) bytes
        self.load = 0.0

    def poll(self):
        try:
            with open(f"{self.proc}/stat") as file:
                fields = [int(value) for value in file.readline().split()[1:]]
            with open(f"{self.proc}/meminfo") as file:
                info = {line.split(":")[0]: int(line.split()[1]) * 1024 for line in file}
            with open(f"{self.proc}/loadavg") as file:
                self.load = float(file.read().split()[0])
            memory = info["MemTotal"]
        except (OSError, ValueError, IndexError, KeyError):
            return False  # no /proc (e.g. macOS): the panel stays hidden
        idle = sum(fields[3:5])  # idle + iowait
        total = sum(fields[:8])  # guest time is already part of user
        if self.last and total > self.last[1]:
            self.cpu = 1 - (idle - self.last[0]) / (total - self.last[1])
            self.history = (self.history + [self.cpu])[-SYSTEM_HISTORY:]
        self.last = idle, total
        self.ram = memory - info.get("MemAvailable", info.get("MemFree", 0)), memory
        swap = info.get("SwapTotal", 0)
        self.swap = swap - info.get("SwapFree", swap), swap
        return True

    @property
    def mood(self):
        """calm, busy or alarm: how worried the panel cat is."""
        cpu, (used, total) = self.cpu or 0, self.ram
        if cpu >= SYSTEM_ALARM or (total and used / total >= RAM_ALARM):
            return "alarm"
        return "busy" if cpu >= SYSTEM_BUSY else "calm"


@dataclass
class Router:
    pid: int
    profile: str
    port: int
    host: str
    age: float  # seconds running
    connections: int  # open client connections
    busy: bool  # used CPU since the previous poll
    client: int  # pid of the claude it serves, or 0


class RouterMonitor:
    """ccx-router processes: which ccx profile each serves and whether it talks."""

    def __init__(self, proc="/proc"):
        self.proc = proc
        self.ticks_per_second = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self.ticks = {}  # pid -> CPU ticks at the previous poll

    def read(self, path):
        with open(f"{self.proc}/{path}", "rb") as file:
            return file.read().decode(errors="replace")

    def connections(self):
        """{local port: established connections} from the TCP tables."""
        counts = {}
        for table in ("net/tcp", "net/tcp6"):
            try:
                lines = self.read(table).splitlines()[1:]
            except OSError:
                continue
            for line in lines:
                fields = line.split()
                if len(fields) > 3 and fields[3] == "01":  # ESTABLISHED
                    port = int(fields[1].rsplit(":", 1)[1], 16)
                    counts[port] = counts.get(port, 0) + 1
        return counts

    def profile(self, parent):
        """The profile name from the ccx script's command line: ccx <profile> ..."""
        try:
            args = self.read(f"{parent}/cmdline").split("\0")
        except OSError:
            return "?"
        for index, arg in enumerate(args[:-1]):
            if os.path.basename(arg) == "ccx":
                return args[index + 1] or "?"
        return "?"

    def client(self, parent, own):
        try:
            children = [int(pid) for pid in self.read(f"{parent}/task/{parent}/children").split()]
        except (OSError, ValueError):
            return 0
        for pid in children:
            try:
                if pid != own and self.read(f"{pid}/comm").strip() == "claude":
                    return pid
            except OSError:
                pass
        return 0

    def poll(self):
        """Return the running routers, oldest first."""
        try:
            pids = sorted(int(name) for name in os.listdir(self.proc) if name.isdigit())
            uptime = float(self.read("uptime").split()[0])
        except (OSError, ValueError, IndexError):
            return []
        routers, ticks, connections = [], {}, None
        for pid in pids:
            try:
                if self.read(f"{pid}/comm").strip() != ROUTER:
                    continue
                args = self.read(f"{pid}/cmdline").split("\0")
                # The command name may contain spaces, so split after its ")".
                fields = self.read(f"{pid}/stat").rsplit(")", 1)[1].split()
                parent, started = int(fields[1]), int(fields[19]) / self.ticks_per_second
                ticks[pid] = int(fields[11]) + int(fields[12])
            except (OSError, ValueError, IndexError):
                continue
            options = dict(zip(args, args[1:]))
            try:
                port = int(options.get("--port", 0))
            except ValueError:
                port = 0
            # Only the host: the upstream URL could carry credentials.
            host = urlsplit(options.get("--upstream-url", "")).hostname or "?"
            if connections is None:
                connections = self.connections()
            routers.append(Router(pid, self.profile(parent), port, host, max(0, uptime - started),
                                  connections.get(port, 0), ticks[pid] > self.ticks.get(pid, ticks[pid]),
                                  self.client(parent, pid)))
        self.ticks = ticks
        return routers


class World:
    def __init__(self, width, height, seed=None, wild=True):
        self.rng = random.Random(seed)
        self.wild = wild  # False: only animals backed by real processes
        self.width, self.height = width, height
        self.elapsed = 0.0
        self.place_index = 0
        self.place_timer = PLACE_DURATION
        self.auto_place = True
        self.raid = None
        self.raid_cooldown = 0.0
        self.victories = 0
        self.animals = []
        self.encounters = []
        self.arrival = 4.0
        self.notice = "The park is open. Who's going to cause a ruckus?"
        self.notice_timer = 5.0
        initial = ("kucing", "anjing", "kelinci")[:max(1, min(3, self.capacity - 1))]
        for species in initial if wild else ():
            self.spawn(species=species)

    @property
    def capacity(self):
        return max(2, min(8, self.width * self.height // 450))

    @property
    def place(self):
        return PLACES[self.place_index]

    @property
    def office_x(self):
        """Where the AI office would start on this screen, or None if too narrow."""
        if self.width < OFFICE_MIN_SCREEN:
            return None
        return self.width - max(26, min(40, self.width // 3))

    @property
    def office(self):
        """Left edge of the AI office, shown only while agent cats are around."""
        if not any(animal.agent and not animal.sub for animal in self.animals):
            return None
        return self.office_x

    def desks(self):
        """Top-left corner of each desk in the office, front rows first."""
        office = self.office
        if office is None:
            return []
        columns = max(1, (self.width - office - 2) // DESK_WIDTH)
        top = self.ground_top + 1  # leave the horizon row to the office sign
        rows = max(1, int(self.height - 6 - top) // DESK_ROWS + 1)
        return [(office + 2 + column * DESK_WIDTH, top + row * DESK_ROWS)
                for row in range(rows) for column in range(columns)]

    def desk_for(self, cat):
        """Keep a working cat at the same desk; None when every desk is taken."""
        desks = self.desks()
        if cat.desk >= len(desks):
            cat.desk = -1  # the screen shrank
        if cat.desk < 0:
            taken = {a.desk for a in self.animals if a is not cat and a.agent and a.status == "work"}
            free = [index for index in range(len(desks)) if index not in taken]
            if not free:
                return None
            cat.desk = free[0]
        return desks[cat.desk]

    def lane(self, animal):
        """x range an animal paces in: the office for working cats, the park otherwise."""
        office = self.office
        if office is None:
            return 1, self.width - animal.width - 1
        if animal.agent and animal.status == "work":
            return office + 2, self.width - animal.width - 1
        return 1, office - animal.width - 2

    @property
    def ground_top(self):
        return max(4, min(self.height - 6, self.height // 3 + 2))

    def change_place(self):
        if self.raid:
            return
        self.place_index = (self.place_index + 1) % len(PLACES)
        self.place_timer = PLACE_DURATION
        for animal in self.animals:
            self.constrain(animal)
        self.say(f"Moving to the {self.place.lower()}! Let's take a walk.")

    def say(self, message):
        self.notice, self.notice_timer = message, 4.0

    def spawn(self, species=None, visitor=False):
        # Agent cats come on top of the normal population.
        wild = [animal for animal in self.animals if not animal.agent]
        if self.raid or len(wild) >= self.capacity:
            return
        residents = sum(not animal.visitor for animal in wild)
        visitor = visitor or residents >= max(1, self.capacity - 1)
        species = species or self.rng.choice(tuple(SPRITES))
        direction = self.rng.choice((-1, 1))
        animal = Animal(
            species, self.rng.uniform(1, max(1, (self.office or self.width) - 15)),
            self.rng.uniform(self.ground_top, max(self.ground_top, self.height - 6)), direction,
            self.rng.uniform(-0.25, 0.25),
            timer=self.rng.uniform(3, 7), visitor=visitor,
            phase=self.rng.random() * 10,
        )
        if visitor:
            animal.x = -animal.width if direction > 0 else self.width
            animal.state = "pass"
            self.say(f"{species.capitalize()} numpang lewat dulu...")
        self.animals.append(animal)

    def sync_agents(self, sessions, subagents=None, models=None):
        """Match agent cats to {pid: (kind, status)} from AgentMonitor.poll,
        kittens to {pid: [(agent id, agent type)]} from its subagents and
        names to {pid: model} from its models."""
        models = models or {}
        for animal in self.animals:
            if animal.agent in sessions and not animal.sub:
                animal.model = short_model(models.get(animal.agent, ""))
                status = sessions[animal.agent][1]
                if status == "wait" and animal.status != "wait":
                    self.say(f"{animal.name} needs your approval!")
                animal.status = status
        if self.raid:
            return  # arrivals and goodbyes wait until the battle is over
        for animal in self.animals:
            if animal.agent and animal.agent not in sessions:
                # The session closed: the cat waves and walks off screen.
                animal.agent, animal.visitor, animal.state = 0, True, "pass"
                animal.vx = -1 if animal.x < self.width / 2 else 1
                self.say(f"{animal.name} finished working. Bye!")
        present = {animal.agent for animal in self.animals}
        for pid, (kind, status) in sorted(sessions.items(), key=lambda item: str(item[0])):
            if pid in present:
                continue
            taken = {a.name for a in self.animals if a.agent and not a.sub and a.agent_kind == kind}
            name = next(n for n in (AGENTS[kind][0] + (f" {i}" if i > 1 else "") for i in range(1, 99))
                        if n not in taken)
            entrance = self.rng.choice(tuple(ENTRANCES))
            duration, message = ENTRANCES[entrance]
            # Busy sessions land straight in the office, the rest in the park.
            office = self.office_x
            if office is None:
                low, high = 1, self.width - 15
            else:
                low, high = (office + 2, self.width - 13) if status == "work" else (1, office - 14)
            self.animals.append(Animal(
                AGENTS[kind][1], self.rng.uniform(low, max(low, high)),
                self.rng.uniform(self.ground_top, max(self.ground_top, self.height - 6)),
                self.rng.choice((-1, 1)), 0, phase=self.rng.random() * 10,
                agent=pid, agent_kind=kind, name=name, status=status,
                model=short_model(models.get(pid, "")),
                state="arrive", entrance=entrance, entry=duration,
            ))
            self.say(message.format(name=name))
        self.sync_kittens(subagents or {})

    def sync_kittens(self, subagents):
        # Kittens wait until their cat has landed.
        leaders = {a.agent: a for a in self.animals if a.agent and not a.sub and not a.entry}
        kittens = {(a.agent, a.sub): a for a in self.animals if a.agent and a.sub}
        wanted = {(key, agent): kind for key, subs in subagents.items() if key in leaders
                  for agent, kind in subs[:KITTENS_PER_CAT]}
        for pair, kitten in kittens.items():
            if pair not in wanted:
                leader = leaders.get(kitten.agent)
                kitten.agent, kitten.visitor, kitten.state = 0, True, "pass"
                kitten.vx = -1 if kitten.x < self.width / 2 else 1
                if leader:
                    self.say(f"{kitten.name} selesai bantu {leader.name}.")
        for (key, agent), kind in wanted.items():
            if (key, agent) in kittens:
                continue
            leader = leaders[key]
            name = kind if len(kind) <= 14 else kind[:13] + "~"
            self.animals.append(Animal(
                f"anak {leader.species}", leader.x, leader.y, leader.vx, 0, state="arrive",
                entrance=KITTEN_ENTRANCE[0], entry=KITTEN_ENTRANCE[1],
                phase=self.rng.random() * math.tau, agent=key, agent_kind=leader.agent_kind,
                name=name, sub=agent,
            ))
            self.say(f"{leader.name} called {name} to help out!")

    def follow(self, kitten, dt):
        """Kittens scamper in loops around the cat that called them."""
        leader = next((a for a in self.animals if a.agent == kitten.agent and not a.sub), None)
        if not leader:
            return
        rank = sum(1 for a in self.animals if a.sub and a.agent == kitten.agent
                   and self.animals.index(a) < self.animals.index(kitten))
        angle = self.elapsed * 0.9 + kitten.phase
        tx = leader.x + leader.width / 2 - kitten.width / 2 + math.sin(angle) * (12 + rank * 3)
        ty = leader.y + 1 + math.cos(angle) * 1.5
        step = (tx - kitten.x) * min(1, dt * 3)
        if abs(step) > 0.01:
            kitten.vx = 1 if step > 0 else -1
        kitten.x += step
        kitten.y += (ty - kitten.y) * min(1, dt * 3)
        self.constrain(kitten)

    def constrain(self, animal):
        if not animal.visitor:
            animal.x = max(1, min(self.width - animal.width - 1, animal.x))
        animal.y = max(self.ground_top, min(self.height - 6, animal.y))

    def start_encounter(self, first, second, kind):
        duration = {"fight": 2.5, "chase": 4.0, "greet": 2.0}[kind]
        self.encounters.append(Encounter(kind, first, second, duration))
        first.state = second.state = kind
        # Encounter timers own these states until both animals are released.
        first.cooldown = second.cooldown = duration + 6
        if kind == "chase":
            second.vx = 1 if second.x >= first.x else -1
        messages = {
            "fight": f"{first.species.capitalize()} & {second.species}: ribut! POOF!",
            "chase": f"{first.species.capitalize()} mengejar {second.species}. Tungguuu!",
            "greet": f"{first.species.capitalize()} & {second.species}: halo tetangga!",
        }
        self.say(messages[kind])

    def start_raid(self, monster="misterius", detail=""):
        if self.raid or not self.animals:
            return
        self.raid = Raid(monster=monster[:15])
        # Even sleeping animals and passing visitors join the same team.
        self.encounters.clear()
        for animal in self.animals:
            animal.state, animal.entry = "rally", 0  # landing can wait, the park can't
        detail = f" ({detail})" if detail else ""
        self.say(f"LOOK OUT! Monster {self.raid.monster}{detail} is coming! All animals, gather!")

    def threat(self, monster, detail):
        """A heavy new process showed up. Returns True if the park fights it."""
        if self.raid or self.raid_cooldown > 0 or not self.animals:
            return False
        self.start_raid(monster, detail)
        return True

    def formation(self, index):
        columns = min(len(self.animals), max(1, (self.width - 18) // 14))
        rows = math.ceil(len(self.animals) / columns)
        x = 1 + (index % columns) * 14
        span = max(0, self.height - 6 - self.ground_top)
        y = self.ground_top + (index // columns) * span / max(1, rows - 1)
        return x, y

    def update_raid(self, dt):
        raid = self.raid
        previous = raid.phase
        if raid.age < 11 <= raid.age + dt:
            self.victories += 1
        raid.age += dt
        phase = raid.phase
        if phase != previous:
            for name, _, message in RAID_PHASES:
                if name == phase:
                    self.say(message)
        if phase == "selesai":
            for animal in self.animals:
                animal.state = "pass" if animal.visitor else "walk"
                animal.vx = (-1 if animal.x < self.width / 2 else 1)
                animal.cooldown = 6
                animal.timer = self.rng.uniform(3, 6)
            self.raid = None
            self.raid_cooldown = RAID_COOLDOWN
            self.say("All clear again. Time to keep strolling!")
            return
        for index, animal in enumerate(self.animals):
            tx, ty = self.formation(index)
            animal.x += (tx - animal.x) * min(1, dt * 5)
            animal.y += (ty - animal.y) * min(1, dt * 5)
            # Visitors also stay on screen until the battle is over.
            animal.x = max(1, min(self.width - animal.width - 1, animal.x))
            self.constrain(animal)
            animal.vx = 1
            animal.state = {
                "datang": "rally", "tangkis": "guard",
                "lawan": "attack", "menang": "cheer",
            }[phase]

    def update(self, dt, speed):
        self.elapsed += dt
        self.notice_timer = max(0, self.notice_timer - dt)
        if self.raid:
            self.update_raid(dt)
            return
        self.raid_cooldown = max(0, self.raid_cooldown - dt)
        if self.auto_place:
            self.place_timer -= dt
            if self.place_timer <= 0:
                self.change_place()
        self.arrival -= dt
        if self.wild and self.arrival <= 0:
            self.spawn(visitor=self.rng.random() < 0.65)
            self.arrival = self.rng.uniform(5, 10)

        for animal in self.animals[:]:
            self.constrain(animal)
            animal.cooldown = max(0, animal.cooldown - dt)
            animal.timer -= dt
            if animal.state in ("fight", "greet", "chase"):
                continue
            if animal.entry > 0:
                animal.entry = max(0, animal.entry - dt)
                continue  # stay put through the landing frame too
            if animal.agent and animal.sub:
                animal.state = "follow"
                self.follow(animal, dt)
                continue
            if animal.agent and not animal.sub and animal.status != "work":
                animal.desk, animal.seated = -1, False
            desk = self.desk_for(animal) if animal.agent and animal.status == "work" else None
            if desk:
                # Run to its own computer, then sit and type.
                animal.state = "work"
                (tx, ty), step = desk, speed * WORK_SPEED * dt
                dx, dy = tx - animal.x, ty - animal.y
                distance = math.hypot(dx, dy * 2)  # rows are about twice as tall as columns
                animal.seated = distance <= step
                if animal.seated:
                    animal.x, animal.y, animal.vx = tx, ty, 1
                else:
                    animal.x += dx / distance * step
                    animal.y += dy / distance * step
                    if abs(dx) > 0.5:
                        animal.vx = 1 if dx > 0 else -1
                continue
            if animal.agent and animal.status == "work":
                # No desk free (or no office): zoom around instead.
                animal.state = "work"
                if animal.x < self.lane(animal)[0]:
                    animal.vx, animal.vy = 1, 0
                elif animal.timer <= 0:
                    animal.vx = self.rng.choice((-1, 1))
                    animal.vy = self.rng.uniform(-0.6, 0.6)
                    animal.timer = self.rng.uniform(0.6, 2.0)
                self.move(animal, dt, speed * WORK_SPEED)
                continue
            if animal.agent and animal.status == "wait":
                # Asking for approval: step out of the office and jump about.
                animal.state = "wait"
                if animal.x > self.lane(animal)[1]:
                    animal.vx, animal.vy = -1, 0
                    self.move(animal, dt, speed)
                continue
            if animal.agent and animal.state in ("work", "wait", "arrive"):
                # Done working: back to the park to play like everyone else.
                animal.state, animal.timer = "walk", self.rng.uniform(2, 5)
                animal.vx, animal.vy = -1, 0
            if not animal.visitor and animal.timer <= 0:
                animal.state = self.rng.choices(
                    ("walk", "sleep", "groom", "hop", "sprint"), (5, 2, 1, 2, 1)
                )[0]
                animal.timer = self.rng.uniform(2, 6)
                animal.vx = self.rng.choice((-1, 1))
                animal.vy = self.rng.uniform(-0.3, 0.3)
            if not animal.visitor and animal.x > self.lane(animal)[1]:
                animal.state, animal.vx = "walk", -1  # no napping in the office
            if animal.state in ("sleep", "groom"):
                continue
            multiplier = {"sprint": 2, "flee": 2, "pass": 1.3}.get(animal.state, 1)
            self.move(animal, dt, speed * multiplier)
            if animal.visitor and (
                (animal.vx > 0 and animal.x > self.width + 1)
                or (animal.vx < 0 and animal.x < -animal.width - 1)
            ):
                self.animals.remove(animal)

        for encounter in self.encounters[:]:
            encounter.timer -= dt
            first, second = encounter.first, encounter.second
            if encounter.kind == "chase":
                first.vx = 1 if second.x > first.x else -1
                first.y += max(-dt * 2, min(dt * 2, second.y - first.y))
                self.move(second, dt, speed * 1.7)
                self.move(first, dt, speed * 1.9)
            if encounter.timer <= 0:
                for animal, direction in ((first, -1), (second, 1)):
                    animal.state = "flee" if encounter.kind == "fight" else "walk"
                    animal.vx = direction
                    animal.timer = self.rng.uniform(2, 4)
                    animal.cooldown = self.rng.uniform(5, 9)
                self.encounters.remove(encounter)
                if encounter.kind == "fight":
                    self.say("Okay, okay... break it up! No one got hurt :)")

        ready = [a for a in self.animals if not a.visitor and not a.agent and a.cooldown <= 0
                 and a.state in ("walk", "hop", "sprint")]
        for index, first in enumerate(ready):
            for second in ready[index + 1:]:
                if first.cooldown or second.cooldown:
                    continue
                if abs((first.x + first.width / 2) - (second.x + second.width / 2)) < 11 and abs(first.y - second.y) < 2.5:
                    self.start_encounter(first, second, self.rng.choice(("fight", "chase", "greet")))
                    break

    def move(self, animal, dt, speed):
        animal.x += animal.vx * speed * dt
        animal.y += animal.vy * speed * dt
        if not animal.visitor:
            low, high = self.lane(animal)
            if animal.x <= low:
                animal.vx = 1
            elif animal.x >= high:
                animal.vx = -1
        if animal.y <= self.ground_top:
            animal.vy = abs(animal.vy)
        elif animal.y >= self.height - 6:
            animal.vy = -abs(animal.vy)
        self.constrain(animal)


def draw(screen, y, x, text, style=0):
    """Clip off-screen visitors and survive terminal resize races."""
    height, width = screen.getmaxyx()
    y, x = int(y), int(x)
    if y < 0 or y >= height or x >= width:
        return
    if x < 0:
        text, x = text[-x:], 0
    available = width - x - (y == height - 1)
    if available > 0:
        try:
            screen.addstr(y, x, text[:available], style)
        except curses.error:
            pass


def style_of(styles, animal):
    return styles.get(animal.agent_kind, styles.get(animal.species, curses.A_BOLD))


def render_place(screen, world, styles, particles):
    """Distant scenery ends at the horizon; animals roam on the ground."""
    height, width = screen.getmaxyx()
    horizon = world.ground_top - 1
    grass = (styles["bebek"] & ~curses.A_BOLD) | curses.A_DIM
    water = (styles["anjing"] & ~curses.A_BOLD) | curses.A_DIM
    wood = (styles["kucing"] & ~curses.A_BOLD) | curses.A_DIM
    sky = curses.A_DIM

    def art(x, lines, style):
        # On a short terminal show the lower part of the scenery.
        for row, line in enumerate(lines):
            y = horizon - len(lines) + row
            if y >= 2:
                draw(screen, y, x, line, style)

    if world.place == "Forest":
        for x in range(1, width - 5, 12):
            art(x, TREE, grass)
        if horizon >= 7:
            draw(screen, 2, width - 10, "( )", wood)
        # Fireflies blink gently above the forest floor.
        for sx, sy, phase in particles[:8]:
            if math.sin(world.elapsed * 1.5 + phase) > 0.4:
                draw(screen, 2 + int(sy * max(1, horizon - 3)), int(sx * (width - 1)), "*", wood)
    elif world.place == "Beach":
        art(2, PALM, grass)
        if width >= 60:
            art(width - 13, PALM, grass)
        draw(screen, 2, width // 2, r"\ | /", wood)
        if horizon >= 5:
            draw(screen, 3, width // 2, "- O -", wood)
        shift = int(world.elapsed * 3) % 8
        wave = ("~~  ~~~~" * (width // 8 + 2))[shift:shift + width]
        draw(screen, horizon - 1, 0, wave, water)
    elif world.place == "Village":
        for x in range(3, width - 7, 24):
            art(x, HOUSE, wood)
        if horizon >= 7:
            draw(screen, 2, width // 2, " .--.   .--.", sky)
            draw(screen, 3, width // 2, "(____) (____)", sky)
    else:
        art(2, TREE, grass)
        art(width // 2 - 4, BENCH, wood)
        if width >= 60:
            art(width - 11, TREE, grass)
        if horizon >= 6:
            cloud_x = int(world.elapsed * 0.7) % (width + 10) - 10
            draw(screen, 2, cloud_x, " .--. ", sky)
            draw(screen, 3, cloud_x, "(____)", sky)

    draw(screen, horizon, 0, ("~" if world.place == "Beach" else "_") * width,
         water if world.place == "Beach" else grass)
    # Sparse, stable ground detail keeps the walking area readable.
    for sx, sy, phase in particles[:max(4, min(24, width * height // 180))]:
        y = world.ground_top + int(sy * max(1, height - world.ground_top - 2))
        x = int(sx * (width - 1))
        if world.place == "Beach":
            text, style = ("." if phase < math.pi else "o"), wood
        elif world.place == "Village":
            text, style = ("." if phase < math.pi else ","), wood
        else:
            text, style = ("," if phase < math.pi else 'v'), grass
        draw(screen, y, x, text, style)
    if world.place == "Village" and width >= 60:
        draw(screen, height - 2, 0, "  -  " * (width // 5), wood)


def render_raid(screen, world, styles):
    raid = world.raid
    phase = raid.phase
    width, height = world.width, world.height
    enemy_style = styles.get("enemy", curses.A_BOLD)
    base_x = width - 12
    monster_x = base_x
    if phase == "datang":
        monster_x += (1 - raid.age / 3) * 14
    elif phase == "menang":
        monster_x += (raid.age - 11) * 16
    monster_y = world.ground_top + max(0, height - 6 - world.ground_top) / 2
    if phase == "lawan":
        monster_x += int(raid.age * 12) % 2
    for row, line in enumerate(MONSTER):
        if phase == "menang":
            line = line.replace(">", "x").replace("<", "x")
        draw(screen, monster_y + row, monster_x, " " * 11)
        draw(screen, monster_y + row, monster_x, line, enemy_style)
    draw(screen, monster_y - 1, monster_x + 5 - len(raid.monster) / 2, raid.monster, enemy_style)

    for index, animal in enumerate(world.animals):
        tip_x, tip_y = animal.x + animal.width + 1, animal.y + 1
        progress = (raid.age * 1.5 + index / max(1, len(world.animals))) % 1
        if phase == "tangkis":
            for row, shield in enumerate((")", "]", ")")):
                draw(screen, animal.y + row, tip_x, shield, style_of(styles, animal))
            px = monster_x + (tip_x - monster_x) * progress
            py = monster_y + 1 + (tip_y - monster_y - 1) * progress
            draw(screen, py, px, "<*" if progress < 0.8 else "*CLANG*", enemy_style)
        elif phase == "lawan":
            px = tip_x + (monster_x - tip_x) * progress
            py = tip_y + (monster_y + 1 - tip_y) * progress
            draw(screen, py, px, "*>" if progress < 0.8 else "POW!", style_of(styles, animal))

    if phase == "menang":
        for index in range(16):
            x = (index * 17 + int(raid.age * 4)) % width
            y = 3 + (index * 7 + int(raid.age * 5)) % max(1, height - 5)
            draw(screen, y, x, ("*", "+", "o")[index % 3], styles["kucing"])
        banner = f"WE WON! All {len(world.animals)} animals are safe! Hooray!"
    else:
        label = {"datang": "LOOK OUT!", "tangkis": "BLOCK!", "lawan": "CHARGE!"}[phase]
        banner = f"{label} Monster {raid.monster}: {raid.health}% | Team: {len(world.animals)} animals"
    draw(screen, 2, 0, " " * width)
    draw(screen, 2, 2, banner, curses.A_BOLD)


def sprite_lines(animal):
    lines = ART[animal.species][0]
    if animal.vx > 0:
        lines = [line.ljust(animal.width)[::-1].translate(MIRROR) for line in lines]
    return lines


def render_entrance(screen, world, animal, style):
    """Arrival effects; `progress` runs from 0 to 1 while the cat lands."""
    total = KITTEN_ENTRANCE[1] if animal.entrance == "pop" else ENTRANCES[animal.entrance][0]
    progress = 1 - animal.entry / total
    lines, x, y = sprite_lines(animal), animal.x, animal.y
    width, height = animal.width, len(lines)
    middle = x + width / 2
    bold = style | curses.A_BOLD

    def sprite(top, rows=None):
        for row, line in enumerate(lines):
            if rows is None or row in rows:
                draw(screen, top + row, x, " " * width)
                draw(screen, top + row, x, line, style)

    def label(text, top=None):
        if top is None:
            draw(screen, y - 1, x, text, bold)
        else:  # still airborne: talk from beside the cat
            draw(screen, top + 1, x + width + 1, text, bold)

    if animal.entrance == "meteor":
        if progress < 0.55:
            # A burning rock streaks in from the top-right corner.
            step = progress / 0.55
            hx = middle + (1 - step) * 40
            hy = 2 + (y + height - 3) * step
            for tail in range(1, 7):
                draw(screen, hy - tail * 0.6, hx + tail * 2, ("*", "~", ".")[min(2, tail // 2)], style)
            draw(screen, hy, hx - 1, "(@)", bold)
        elif progress < 0.8:
            blast = ("  \\ | /  ", "- KABOOM! -", "  / | \\  ") if int(progress * 20) % 2 else (
                " .  *  . ", "*  BOOM!  *", " '  *  ' ")
            for row, line in enumerate(blast):
                draw(screen, y + row, middle - len(line) / 2, line, bold)
        else:
            sprite(y)
            draw(screen, y + height, x - 1, "( ~ ~ ~ )"[: width + 2], curses.A_DIM)
            label(f"[{animal.name}] ugh, dizzy...")
    elif animal.entrance == "ufo":
        flight = min(1, progress / 0.35)
        ux = (middle - 6) * flight + (1 - flight) * -14
        uy = max(2, y - 6)
        if progress > 0.85:
            # Job done: the saucer zips off to the top-right.
            ux += (progress - 0.85) * 400
            uy -= (progress - 0.85) * 20
        for row, line in enumerate(UFO):
            draw(screen, uy + row, ux, line, bold)
        if 0.35 <= progress <= 0.85:
            for row in range(int(uy) + 2, int(y + height)):
                draw(screen, row, middle - 2, "\\   /" if row % 2 else " : : ", style)
            sprite(uy + 2 + (y - uy - 2) * (progress - 0.35) / 0.5)
        elif progress > 0.85:
            sprite(y)
            label(f"[{animal.name}] makasih, alien!")
    elif animal.entrance == "portal":
        if progress > 0.35:
            # The cat rises out of the swirl one row at a time.
            shown = min(height, int((progress - 0.35) / 0.4 * height) + 1)
            sprite(y, range(height - shown, height))
            if progress > 0.75:
                label(f"[{animal.name}] tada!")
        size = int(1 + 4 * math.sin(math.pi * progress))
        spin = "|/-\\"[int(progress * 24) % 4]
        ring = "(" * size + f" {spin} " + ")" * size
        draw(screen, y + height, middle - len(ring) / 2, ring, bold)
    elif animal.entrance == "parasut":
        top = 2 + (y - 2) * progress
        sway = math.sin(progress * 12) * 2
        if progress < 0.9:
            for row, line in enumerate(PARACHUTE):
                draw(screen, top - len(PARACHUTE) + row, x + sway - 2, line, style)
        sprite(top)
        if progress < 0.9:
            label(f"[{animal.name}] wiii~", top)
        else:
            label(f"[{animal.name}] landed!")
    elif animal.entrance == "teleport":
        # Noise settles into the cat, character by character.
        for row, line in enumerate(lines):
            text = "".join(
                char if (row * 31 + col * 17) % 97 / 97 < progress * 1.2 or char == " "
                else NOISE[(row + col + int(progress * 40)) % len(NOISE)]
                for col, char in enumerate(line))
            draw(screen, y + row, x, text, style)
        label(f"[{animal.name}] bzzt... {int(progress * 100)}%")
    else:  # "pop": kittens appear in a little puff
        puff = ("  .  *  .", "* POP! *", "  '  *  '") if progress < 0.5 else (" ", "*  .  *", " ")
        for row, line in enumerate(puff):
            draw(screen, y + row, x - 1, line, bold)
        if progress >= 0.5:
            sprite(y)


def meter(fraction, width):
    filled = round(max(0, min(1, fraction)) * width)
    return "|" * filled + "." * (width - filled)


def gigabytes(size):
    return f"{size / (1 << 30):.1f}G"


def render_system(screen, system, elapsed, styles):
    """A small btop-like box in the top-right corner, with a watch cat."""
    height, width = screen.getmaxyx()
    if system is None or system.cpu is None or width < 64 or height < 20:
        return
    left, top = width - SYSTEM_WIDTH - 1, 1
    calm, busy = styles.get("bebek", 0), styles.get("kucing", curses.A_BOLD)
    alarm = styles.get("enemy", curses.A_BOLD)

    def level(fraction, worry, panic):
        return alarm if fraction >= panic else busy if fraction >= worry else calm

    (ram_used, ram_total), (swap_used, swap_total) = system.ram, system.swap
    ram = ram_used / ram_total if ram_total else 0
    swap = swap_used / swap_total if swap_total else 0
    spark = "".join(SPARK[min(len(SPARK) - 1, int(cpu * len(SPARK)))] for cpu in system.history)
    rows = (
        ("CPU", system.cpu, level(system.cpu, SYSTEM_BUSY, SYSTEM_ALARM)),
        ("RAM", ram, level(ram, 0.75, RAM_ALARM)),
        ("SWP", swap, level(swap, 0.5, 0.8)) if swap_total else None,
    )
    inner = SYSTEM_WIDTH - 2
    lines = ["+- system " + "-" * (inner - 9) + "+"]
    lines += ["|" + " " * inner + "|"] * (sum(1 for row in rows if row) + 2)
    lines.append("+" + "-" * inner + "+")
    for row, line in enumerate(lines):
        draw(screen, top + row, left, line, curses.A_DIM)
    y = top + 1
    for row in rows:
        if not row:
            continue
        name, fraction, style = row
        draw(screen, y, left + 2, f"{name} [")
        draw(screen, y, left + 7, meter(fraction, 12), style)
        draw(screen, y, left + 19, f"] {round(fraction * 100):3d}%")
        y += 1
    draw(screen, y, left + 2, f"{gigabytes(ram_used)[:-1]}/{gigabytes(ram_total)} load {system.load:.2f}",
         curses.A_DIM)
    draw(screen, y + 1, left + 2, spark.rjust(SYSTEM_HISTORY), level(system.cpu, SYSTEM_BUSY, SYSTEM_ALARM))

    # The watch cat sits left of the box and frets as the machine heats up.
    mood = system.mood
    blink = int(elapsed * 2) % 7 == 0
    face = {"calm": "( -.- )" if blink else "( o.o )", "busy": "( o.O )", "alarm": "( O_O )"}[mood]
    flash = int(elapsed * 4) % 2
    shake = flash if mood == "alarm" else 0  # it trembles instead of jumping into the notice line
    cat_x = left - 10
    style = {"calm": busy, "busy": busy, "alarm": alarm}[mood]
    for row, line in enumerate((r" /\_/\ ", face, " > ^ < ")):
        draw(screen, top + 1 + row, cat_x - 1, " " * 10)
        draw(screen, top + 1 + row, cat_x + shake, line, style)
    if mood == "alarm":
        draw(screen, top + 1 + flash, cat_x + 8, "!", alarm)
        if system.cpu >= SYSTEM_ALARM:
            speech = f"WATCH OUT! CPU {round(system.cpu * 100)}%!" if flash else "hot hot!"
        else:
            speech = f"RAM {round(ram * 100)}%! so tight!" if flash else "RAM almost full!"
    elif mood == "busy":
        speech = "CPU is climbing..."
    else:
        speech = "chill~"
    draw(screen, top + 4, left - 2 - len(speech), f" {speech} ", style if mood != "calm" else curses.A_DIM)


def duration(seconds):
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds // 3600)}h"


def render_routers(screen, world, routers, styles, crowded):
    """A box in the top-left corner for each running ccx-router."""
    height, width = screen.getmaxyx()
    # The system box and its cat's speech take the right side on narrower screens.
    if not routers or width < (80 if crowded else 40) or height < 20:
        return
    left, top, inner = 1, 2, ROUTER_WIDTH - 2
    # Stay above the ground, keeping a row for "+N more".
    shown = routers[:max(1, min(ROUTER_SHOWN, (world.ground_top - top - 3) // 3))]
    rows = 3 * len(shown) + (len(routers) > len(shown))
    title = f"+- router ccx ({len(routers)}) "
    lines = [title + "-" * (ROUTER_WIDTH - 1 - len(title)) + "+"]
    lines += ["|" + " " * inner + "|"] * rows
    lines.append("+" + "-" * inner + "+")
    for row, line in enumerate(lines):
        draw(screen, top + row, left, line, curses.A_DIM)
    cats = {a.agent: a for a in world.animals if a.agent and not a.sub}
    for index, router in enumerate(shown):
        y, x = top + 1 + 3 * index, left + 2
        cat = cats.get(router.client)
        style = styles.get("claude", curses.A_BOLD)
        head = f"{router.profile[:inner - 10]} :{router.port}"
        draw(screen, y, x, head, style)
        age = duration(router.age)
        draw(screen, y, left + inner - len(age), age, curses.A_DIM)
        draw(screen, y + 1, x, f"-> {router.host}"[:inner - 2], curses.A_DIM)
        busy = router.busy or (cat is not None and cat.status == "work")
        if busy:
            # Packets running towards the upstream.
            step = int(world.elapsed * 8) % 3
            flow = "".join(">" if i % 3 == step else "-" for i in range(8))[::-1]
            status = f"{flow} send"
        else:
            status = "........ idle"
        draw(screen, y + 2, x, status, style if busy else curses.A_DIM)
        owner = (f"[{cat.name}]" if cat else f"{router.connections} conn")[:inner - 14]
        draw(screen, y + 2, left + inner - len(owner), owner,
             style_of(styles, cat) if cat else curses.A_DIM)
    if len(routers) > len(shown):
        draw(screen, top + rows, left + 2, f"+{len(routers) - len(shown)} more", curses.A_DIM)


def render_stats(screen, world, styles, crowded):
    """A small box in the top-left with at-a-glance park stats.

    Shares the corner with the ccx-router box, so it only shows when no
    router is drawn there. Everything comes from existing world state, so
    the box costs nothing extra to compute.
    """
    height, width = screen.getmaxyx()
    # Match render_routers' gating so the corner stays readable on small screens.
    # During a raid the banner owns the top rows, so step aside for it.
    if world.raid or width < (80 if crowded else 40) or height < 20:
        return
    left, top, inner = 1, 2, STATS_WIDTH - 2
    agents = [a for a in world.animals if a.agent and not a.sub]
    working = sum(1 for a in agents if a.status == "work")
    if world.auto_place:
        place_line = f"{world.place} ({max(1, math.ceil(world.place_timer))}s)"
    else:
        place_line = f"{world.place} (locked)"
    stats = (
        ("up", duration(world.elapsed)),
        ("animals", f"{len(world.animals)}/{world.capacity}"),
        ("agents", f"{working}/{len(agents)}"),
        ("wins", str(world.victories)),
        ("place", place_line),
    )
    title = "+- park "
    lines = [title + "-" * (STATS_WIDTH - 1 - len(title)) + "+"]
    lines += ["|" + " " * inner + "|"] * len(stats)
    lines.append("+" + "-" * inner + "+")
    for row, line in enumerate(lines):
        draw(screen, top + row, left, line, curses.A_DIM)
    accent = styles.get("claude", curses.A_BOLD)
    for row, (name, value) in enumerate(stats):
        y = top + 1 + row
        draw(screen, y, left + 2, name, curses.A_DIM)
        value = value[:inner - len(name) - 3]
        draw(screen, y, left + inner - len(value), value,
             accent if name == "wins" and world.victories else curses.A_DIM)


def render_office(screen, world, styles):
    """Fence off the AI office and show at a glance who is working."""
    left = world.office
    if left is None:
        return
    height, width = screen.getmaxyx()
    for y in range(world.ground_top, height - 1):
        draw(screen, y, left, "|" if y % 2 else ":", curses.A_DIM)
    users = {a.desk: a for a in world.animals if a.agent and not a.sub and a.status == "work" and a.desk >= 0}
    for index, (x, y) in enumerate(world.desks()):
        cat = users.get(index)
        style = style_of(styles, cat) if cat else curses.A_DIM
        for row, line in enumerate(COMPUTER):
            draw(screen, y + row, x + 13, line, style)
        if cat and cat.seated:
            text = SCREEN_TEXT[int(world.elapsed * 2 + index * 3) % len(SCREEN_TEXT)]
        elif cat:
            text = "boot" + "." * (int(world.elapsed * 4) % 4)  # its cat is on the way
        else:
            text = "  zz"  # screen saver of the screen saver
        draw(screen, y + 1, x + 14, text.ljust(7), style)
    busy = sum(1 for a in world.animals if a.agent and not a.sub and a.status == "work")
    sign = f"[ AI HQ: {busy} working ]" if busy else "[ AI HQ: empty ]"
    draw(screen, world.ground_top - 1, left + (width - left - len(sign)) // 2, sign,
         styles.get("claude", curses.A_BOLD) if busy else curses.A_DIM)


def render(screen, world, speed, paused, styles, stars, system=None, routers=()):
    height, width = screen.getmaxyx()
    if world.raid:
        mode = "location held"
    else:
        mode = f"next {max(1, math.ceil(world.place_timer))}s" if world.auto_place else "locked"
    header = f"AGENT PARK / {world.place.upper()} / {mode}"
    draw(screen, 0, 2, header, curses.A_BOLD)
    # A clock centred on the top row, between the header and the system panel.
    clock = time.strftime("%H:%M:%S")
    clock_x = (width - len(clock)) // 2
    right_edge = (width - SYSTEM_WIDTH - 1) if (system is not None and system.cpu is not None) else width
    if clock_x > 2 + len(header) + 1 and clock_x + len(clock) < right_edge - 1:
        draw(screen, 0, clock_x, clock, curses.A_DIM)
    if world.notice_timer > 0:
        draw(screen, 1, 2, world.notice, curses.A_DIM)
    render_place(screen, world, styles, stars)
    render_office(screen, world, styles)
    for animal in sorted(world.animals, key=lambda a: a.y):
        if animal.state == "fight":
            continue
        if animal.entry > 0:
            render_entrance(screen, world, animal, style_of(styles, animal))
            continue
        frame = ART[animal.species][int(world.elapsed * speed / 3 + animal.phase) % 2]
        if animal.state == "work":
            frame = ART[animal.species][int(world.elapsed * 6) % 2]
        elif animal.state in ("sleep", "groom", "greet", "wait"):
            frame = ART[animal.species][0]
        bouncy = {"hop": 5, "cheer": 5, "wait": 5, "work": 9}.get(animal.state)
        offset = -int((world.elapsed * bouncy + animal.phase) % 2) if bouncy else 0
        for row, line in enumerate(frame):
            if animal.state == "sleep":
                line = line.replace("o", "-").replace("'", "-")
            if animal.vx > 0:
                line = line.ljust(animal.width)[::-1].translate(MIRROR)
            draw(screen, animal.y + row + offset, animal.x, " " * animal.width)
            draw(screen, animal.y + row + offset, animal.x, line, style_of(styles, animal))
        if animal.state == "work" and animal.seated:
            # Keys clattering between the cat and its computer.
            flick = int(world.elapsed * 8) % 2
            draw(screen, animal.y + 2 + offset, animal.x + 12, ("*", "'")[flick], curses.A_BOLD)
        elif animal.state == "work":
            # Dust kicked up behind, sweat flying off the head.
            flick = int(world.elapsed * 8) % 2
            feet = animal.y + len(frame) - 1
            behind = animal.x + animal.width if animal.vx < 0 else animal.x - 5
            draw(screen, feet, behind, (". ~ '", "' . ~")[flick], curses.A_DIM)
            head = animal.x - 2 if animal.vx < 0 else animal.x + animal.width + 1
            draw(screen, animal.y + offset, head, ("*", "'")[flick], curses.A_BOLD)
        label = {
            "sleep": "z Z" if int(world.elapsed) % 2 else "z",
            "groom": "* lick *" if int(world.elapsed * 2) % 2 else "* preen fur *",
            "greet": "hello!", "chase": "!!", "flee": "run awaaay!", "sprint": "wooosh!",
            "rally": "ready!", "guard": "block!", "attack": "chaaarge!", "cheer": "yaaay!",
            "work": WORK_CHATTER[int(world.elapsed * 1.5 + animal.phase) % len(WORK_CHATTER)],
            "wait": "need you!" if int(world.elapsed * 2) % 2 else "hey? permission please!",
        }.get(animal.state)
        if animal.agent:
            # The name (and model) always shows so you can tell whose cat is
            # whose; slide it left at the right edge, where the office is.
            # Seated cats skip the chatter so labels stay within their desk.
            name = f"{animal.name} | {animal.model}" if animal.model and not animal.sub else animal.name
            chatter = "" if animal.seated else label or ""
            text = f"[{name}] {chatter}".rstrip()
            if animal.seated and len(text) > DESK_WIDTH - 1:
                text = text[:DESK_WIDTH - 3] + "~]"
            draw(screen, animal.y - 1, min(animal.x, width - len(text) - 1), text,
                 styles.get(animal.agent_kind, curses.A_BOLD))
        elif label:
            draw(screen, animal.y - 1, animal.x, label, curses.A_DIM)
    for encounter in world.encounters:
        if encounter.kind != "fight":
            continue
        x = max(0, min(width - 14, (encounter.first.x + encounter.second.x) / 2))
        y = (encounter.first.y + encounter.second.y) / 2
        for row, line in enumerate(FIGHT_FRAMES[int(world.elapsed * 9) % 2]):
            draw(screen, y + row, x, line, curses.A_BOLD)
        draw(screen, y - 1, x, "POW!" if int(world.elapsed * 6) % 2 else "BONK!", curses.A_BOLD)
    if world.raid:
        render_raid(screen, world, styles)
    render_system(screen, system, world.elapsed, styles)
    render_routers(screen, world, routers, styles, system is not None)
    if not routers:  # the stats box shares the top-left corner with routers
        render_stats(screen, world, styles, system is not None)
    if not world.animals and not world.raid:
        hint = "The park is quiet... run an AI agent (claude, codex, opencode, ...) and the animals will come."
        draw(screen, (world.ground_top + height) // 2, max(0, (width - len(hint)) // 2), hint, curses.A_DIM)
    footer = "q quit | r raid | l location | space pause | a auto | "
    footer += ("n animal | " if world.wild else "") + "s system | +/- speed"
    draw(screen, height - 1, 2, ("[PAUSED] " if paused else "") + footer, curses.A_DIM)


def main(screen, wild=False):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.nodelay(True)
    screen.keypad(True)
    styles = {species: curses.A_BOLD for species in SPRITES}
    if curses.has_colors():
        curses.start_color()
        try:
            curses.use_default_colors()
            background = -1
        except curses.error:
            background = curses.COLOR_BLACK
        colors = (curses.COLOR_YELLOW, curses.COLOR_CYAN, curses.COLOR_MAGENTA,
                  curses.COLOR_GREEN, curses.COLOR_WHITE)
        for index, (species, color) in enumerate(zip(SPRITES, colors), 1):
            curses.init_pair(index, color, background)
            styles[species] |= curses.color_pair(index)
        if curses.COLOR_PAIRS > 6:
            curses.init_pair(6, curses.COLOR_RED, background)
            styles["enemy"] = curses.color_pair(6) | curses.A_BOLD
        if curses.COLOR_PAIRS > 6 + len(AGENTS):
            # Each agent's own shade when 256 colours exist.
            rich = curses.COLORS >= 256
            for index, (kind, (_, _, shade, fallback)) in enumerate(AGENTS.items(), 7):
                curses.init_pair(index, shade if rich else fallback, background)
                styles[kind] = curses.color_pair(index) | curses.A_BOLD
    height, width = screen.getmaxyx()
    world = World(width, height, wild=wild)
    rng = random.Random(42)
    stars = [(rng.random(), rng.random(), rng.random() * math.tau) for _ in range(32)]
    paused, speed = False, 8.0
    monitor, watcher, next_poll = AgentMonitor(), ProcessWatcher(), 0.0
    system, show_system, mood = SystemMonitor(), True, "calm"
    router_monitor, routers = RouterMonitor(), []
    last_time = time.monotonic()
    while True:
        now = time.monotonic()
        dt, last_time = min(now - last_time, 0.1), now
        key = screen.getch()
        if key in (ord("q"), ord("Q"), 27):
            return
        if key == ord(" "):
            paused = not paused
        elif key in (ord("+"), ord("=")):
            speed = min(24, speed + 2)
        elif key == ord("-"):
            speed = max(2, speed - 2)
        elif key in (ord("l"), ord("L")):
            world.change_place()
        elif key in (ord("a"), ord("A")):
            world.auto_place = not world.auto_place
        elif key in (ord("s"), ord("S")):
            show_system = not show_system
        height, width = screen.getmaxyx()
        world.width, world.height = width, height
        screen.erase()
        if width < 32 or height < 12:
            draw(screen, 0, 0, "Terminal too small.")
            draw(screen, 1, 0, "Enlarge the window; q to quit.")
        else:
            if not paused:
                if key in (ord("n"), ord("N")) and world.wild:
                    world.spawn(visitor=True)
                elif key in (ord("r"), ord("R")):
                    world.start_raid()
                if now >= next_poll:
                    world.sync_agents(monitor.poll(now), monitor.subagents, monitor.models)
                    for pid, name, detail in watcher.poll(now):
                        if world.threat(name, detail):
                            watcher.fought.add(pid)
                            break
                    if system.poll():
                        if system.mood == "alarm" and mood != "alarm":
                            world.say("Guard cat: WATCH OUT! The computer is overheating!")
                        mood = system.mood
                    routers = router_monitor.poll()
                    next_poll = now + AGENT_POLL
                world.update(dt, speed)
            render(screen, world, speed, paused, styles, stars, system if show_system else None,
                   routers)
        screen.refresh()
        curses.napms(40)


if __name__ == "__main__":
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Jalankan langsung di terminal: python3 screensaver.py", file=sys.stderr)
        sys.exit(1)
    try:
        # Only agent cats by default; --semua brings back the wild animals too.
        curses.wrapper(main, "--semua" in sys.argv[1:])
    except KeyboardInterrupt:
        pass
    except curses.error as error:
        print(f"Terminal tidak mendukung animasi curses: {error}", file=sys.stderr)
        sys.exit(1)
