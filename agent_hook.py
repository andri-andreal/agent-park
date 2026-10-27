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
The state also names the session's model when the event or the agent's own
transcript tells it.
"""

import glob
import json
import os
import re
import sqlite3
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
# Where an agent keeps a session's transcript when its hook does not say.
TRANSCRIPTS = {
    "kiro-cli": "~/.kiro/sessions/cli/{session}.jsonl",
    "codex": "~/.codex/sessions/*/*/*/rollout-*-{session}.jsonl",
}
# OpenCode 2.x keeps each session's model in its database.
OPENCODE_DB = os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "opencode", "opencode.db")
# The last model a transcript names: Claude and Codex write "model", Kiro and
# Pi "modelId". Claude's "<synthetic>" messages come from no model at all.
MODEL_FIELD = re.compile(rb'"model(?:Id|ID)?"\s*:\s*"([^"<]+)"')
TRANSCRIPT_TAIL = 256 * 1024


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


def transcript_model(path):
    """The model of the newest reply in a transcript, read from its end."""
    try:
        with open(path, "rb") as file:
            file.seek(max(0, os.fstat(file.fileno()).st_size - TRANSCRIPT_TAIL))
            found = MODEL_FIELD.findall(file.read())
    except OSError:
        return None
    return found[-1].decode(errors="replace") if found else None


def opencode_model(session):
    try:
        db = sqlite3.connect(f"file:{OPENCODE_DB}?mode=ro", uri=True, timeout=0.5)
        try:
            row = db.execute("SELECT model FROM session_v2 WHERE id = ?", (session,)).fetchone()
        finally:
            db.close()
        return json.loads(row[0]).get("id") if row and row[0] else None
    except (sqlite3.Error, ValueError, AttributeError):
        return None


def model_of(kind, event):
    """The session's model: as the event names it, else from the agent's records."""
    model = event.get("model")
    if isinstance(model, dict):
        model = model.get("id") or model.get("modelID")
    if isinstance(model, str) and model:
        return model
    session = re.sub(r"[^A-Za-z0-9_-]", "", str(event.get("session_id") or ""))
    path = event.get("transcript_path")
    if not path and session and kind in TRANSCRIPTS:
        found = glob.glob(os.path.expanduser(TRANSCRIPTS[kind].format(session=session)))
        path = max(found, key=os.path.getmtime) if found else None
    if path:
        return transcript_model(path)
    if kind == "opencode" and session:
        return opencode_model(session)
    return None


def read(path):
    try:
        with open(path) as file:
            return json.load(file)
    except (OSError, ValueError):
        return {}


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
    else:
        # Events that only name the model (a model switch) keep the state.
        old = read(path)
        model = model_of(kind, event) or old.get("model")
        if not state and (not old or model == old.get("model")):
            return
        data = {"kind": kind, "state": state, "event": hook,
                "session_id": event.get("session_id"), "time": now}
        if not state:
            data.update({key: old.get(key) for key in ("state", "event", "time")})
        if model:
            data["model"] = model
        write(path, data)


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
