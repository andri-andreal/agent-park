#!/usr/bin/env python3
"""The park's live state as JSON lines, for views other than the terminal.

Prints one JSON object per line, every AGENT_POLL seconds, built from the same
monitors the terminal screensaver uses. The 3D app (park3d/) runs this as a
child process and reads its stdout. Standard library only.

Usage: python3 park_state.py [--once]
"""

from dataclasses import asdict
import json
import os
import sys
import time

from screensaver import (AGENT_POLL, AGENTS, AgentMonitor, ProcessWatcher, RouterMonitor,
                         SystemMonitor, short_model)


def xterm_hex(index):
    """#rrggbb of a 256-colour terminal shade, so both views share colours."""
    if index < 16:
        base = ("000000", "800000", "008000", "808000", "000080", "800080", "008080", "c0c0c0",
                "808080", "ff0000", "00ff00", "ffff00", "0000ff", "ff00ff", "00ffff", "ffffff")
        return "#" + base[index]
    if index < 232:
        index -= 16
        steps = [0, 95, 135, 175, 215, 255]
        red, green, blue = steps[index // 36], steps[index // 6 % 6], steps[index % 6]
        return f"#{red:02x}{green:02x}{blue:02x}"
    grey = 8 + (index - 232) * 10
    return f"#{grey:02x}{grey:02x}{grey:02x}"


class State:
    def __init__(self, proc="/proc", agents=None, system=None, watcher=None, routers=None):
        self.agents = agents or AgentMonitor(proc)
        self.system = system or SystemMonitor(proc)
        self.watcher = watcher or ProcessWatcher(proc)
        self.routers = routers or RouterMonitor(proc)
        self.names = {}  # session key -> name, kept while the session lives
        self.started = None  # first poll time, for an uptime the view can show
        self.monsters_seen = 0  # heavy processes announced so far

    def name(self, key, kind, sessions):
        """"Claude", then "Claude 2" and so on, like the terminal names its cats."""
        self.names = {k: n for k, n in self.names.items() if k in sessions}
        if key not in self.names:
            taken = {n for k, n in self.names.items() if sessions[k][0] == kind}
            label = AGENTS[kind][0]
            self.names[key] = next(n for n in (label + (f" {i}" if i > 1 else "") for i in range(1, 99))
                                   if n not in taken)
        return self.names[key]

    def poll(self, now):
        sessions = self.agents.poll(now)
        agents = []
        for key, (kind, status) in sorted(sessions.items(), key=lambda item: str(item[0])):
            label, species, shade, _ = AGENTS[kind]
            agents.append({
                "id": str(key), "kind": kind, "name": self.name(key, kind, sessions),
                "species": species, "color": xterm_hex(shade), "status": status,
                "model": short_model(self.agents.models.get(key, "")),
                "subagents": [{"id": agent, "type": kind}
                              for agent, kind in self.agents.subagents.get(key, [])],
            })
        system = None
        if self.system.poll() and self.system.cpu is not None:
            system = {"cpu": self.system.cpu, "ram": list(self.system.ram),
                      "swap": list(self.system.swap), "load": self.system.load,
                      "history": list(self.system.history), "mood": self.system.mood}
        # Each heavy newcomer is announced once; the view decides when to fight.
        monsters = []
        for pid, name, detail in self.watcher.poll(now):
            if pid not in self.watcher.fought:
                self.watcher.fought.add(pid)
                monsters.append({"pid": pid, "name": name, "detail": detail})
        if self.started is None:
            self.started = now
        self.monsters_seen += len(monsters)
        stats = {
            "uptime": now - self.started,
            "agents": len(agents),
            "working": sum(1 for agent in agents if agent["status"] == "work"),
            "subagents": sum(len(agent["subagents"]) for agent in agents),
            "monsters_seen": self.monsters_seen,
        }
        return {"time": now, "agents": agents, "system": system, "monsters": monsters,
                "routers": [asdict(router) for router in self.routers.poll()], "stats": stats}


def main(argv=sys.argv[1:]):
    state = State()
    try:
        while True:
            print(json.dumps(state.poll(time.time())), flush=True)
            if "--once" in argv:
                return 0
            time.sleep(AGENT_POLL)
    except KeyboardInterrupt:
        return 0
    except BrokenPipeError:
        # The app closed our stdout: time to go, without a traceback on exit.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0


if __name__ == "__main__":
    sys.exit(main())
