#!/usr/bin/env python3
"""Hook for AI coding agents: records what a session is doing.

Usage (from the agent's hook config): python3 agent_hook.py <process name>,
e.g. claude, codex, opencode or kiro-cli. The hook event arrives as JSON on
stdin; OpenCode has no command hooks, so opencode_plugin.js translates its
events into this format. The state is written to
STATE_DIR/<session pid>.json, where the screensaver picks it up. Codex runs
hooks inside its shared app-server, which serves every Codex window, so its
states go to STATE_DIR/codex-<session id>.json instead. Each running subagent
gets <that name>.sub-<agent id>.json so parallel subagents never share a file.
"""

import json
import os
import re
import sys
import time

STATE_DIR = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR") or os.path.expanduser("~/.cache"), "agent-park")

# Background helpers are not sessions; their CPU counts for the parent session.
# Codex's app-server and OpenCode's `serve` run every window's hooks.
HELPER_ARGS = ("--chrome-native-host", "app-server", "serve")
# Extra process names an agent runs under -> the agent they belong to.
AGENT_PROCESSES = {"kiro-cli-chat": "kiro-cli"}
# Hook event -> what the cat should do. Missing events are ignored.
EVENT_STATES = {
    "UserPromptSubmit": "work",
    "PreToolUse": "work",
    "PostToolUse": "work",
    "PostToolUseFailure": "work",
    "SubagentStart": "work",
    "PermissionRequest": "wait",
    "Stop": "idle",
    "StopFailure": "idle",
    "Interrupt": "idle",  # Codex only
    "SessionStart": "idle",
    "AgentSpawn": "idle",  # Kiro only
    "SessionEnd": "end",
}
# Claude's Notification event says why it is pinging you.
NOTIFICATION_STATES = {"permission_prompt": "wait", "elicitation_dialog": "wait",
                       "idle_prompt": "idle"}


def session_pid(kind, proc="/proc", start=None):
    """Pid of the session process running this hook, or 0 for a shared helper.

    The outermost process of that agent wins, as the screensaver counts an
    agent's own child processes (e.g. kiro-cli -> kiro-cli-chat) as one session.
    """
    pid, found = start or os.getppid(), 0
    while pid > 1:
        with open(f"{proc}/{pid}/comm") as file:
            comm = file.read().strip()
        if AGENT_PROCESSES.get(comm, comm) == kind:
            with open(f"{proc}/{pid}/cmdline", "rb") as cmdline:
                args = cmdline.read().decode(errors="replace").split("\0")
            if not found and any(arg in HELPER_ARGS for arg in args):
                return 0
            found = pid
        with open(f"{proc}/{pid}/stat") as file:
            # The command name may contain spaces, so split after its ")".
            pid = int(file.read().rsplit(")", 1)[1].split()[1])
    return found


def state_file(kind, event, pid):
    if pid:
        return f"{pid}.json"
    session = re.sub(r"[^A-Za-z0-9-]", "", str(event.get("session_id") or ""))
    return f"{kind}-{session}.json" if session else None


def state_for(event):
    name = event.get("hook_event_name", "")
    name = name[:1].upper() + name[1:]  # Kiro writes camelCase: userPromptSubmit
    if name == "Notification":
        return NOTIFICATION_STATES.get(event.get("notification_type", ""))
    return EVENT_STATES.get(name)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Write then rename so the screensaver never reads half a file.
    temporary = f"{path}.{os.getpid()}.tmp"
    with open(temporary, "w") as file:
        json.dump(data, file)
    os.replace(temporary, path)


def remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def record(kind, event, pid, state_dir=STATE_DIR, now=None):
    name = state_file(kind, event, pid)
    if not name:
        return
    now = now or time.time()
    base, path = name[:-len(".json")], os.path.join(state_dir, name)
    hook = event.get("hook_event_name")
    agent = re.sub(r"[^A-Za-z0-9-]", "", str(event.get("agent_id") or ""))
    if agent and hook == "SubagentStart":
        write(os.path.join(state_dir, f"{base}.sub-{agent}.json"),
              {"type": event.get("agent_type") or "subagent", "time": now})
    elif agent and hook == "SubagentStop":
        remove(os.path.join(state_dir, f"{base}.sub-{agent}.json"))
    state = state_for(event)
    if state == "end":
        remove(path)
        for other in os.listdir(state_dir) if os.path.isdir(state_dir) else ():
            if other.startswith(f"{base}.sub-"):
                remove(os.path.join(state_dir, other))
    elif state:
        write(path, {"kind": kind, "state": state, "event": hook,
                     "session_id": event.get("session_id"), "time": now})


def main():
    try:
        kind = sys.argv[1]
        event = json.load(sys.stdin)
        record(kind, event, session_pid(kind))
    except Exception:
        pass  # a screensaver must never break the agent's turn
    return 0


if __name__ == "__main__":
    sys.exit(main())
