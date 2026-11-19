#!/usr/bin/env python3
"""Hook for AI coding agents: records what a session is doing.

Usage (from the agent's hook config): python3 agent_hook.py <process name>,
e.g. claude, codex, opencode, kiro-cli, kimi or mcode. The hook event arrives as JSON on
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
from pathlib import Path
import re
import shlex
import sqlite3
import sys
import time
import tempfile

try:
    from platform_support import is_windows, source_for, state_dir
except ImportError:
    # Copied without its companion file: a screensaver must never break the agent's turn.
    sys.exit(0)

STATE_DIR = state_dir()

# Background helpers are not sessions; their CPU counts for the parent session.
# Codex's app-server and OpenCode's `serve` run every window's hooks.
HELPER_ARGS = ("--chrome-native-host", "app-server", "serve")
# Extra process names an agent runs under -> the agent they belong to.
AGENT_PROCESSES = {"kiro-cli-chat": "kiro-cli", "minimax-code": "mcode"}
# Agents that run as a plain `node` process -> part of their script's path.
NODE_AGENTS = {"/@minimax-ai/code/": "mcode"}
# Hook event -> what the cat should do. Missing events are ignored.
EVENT_STATES = {
    "UserPromptSubmit": "work",
    "PreToolUse": "work",
    "PostToolUse": "work",
    "PostToolUseFailure": "work",
    "SubagentStart": "work",
    "PermissionRequest": "wait",
    "PermissionResult": "work",  # Kimi only: you answered its prompt
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


def agent_of(comm, args):
    """The agent a process belongs to, from its name or, for node, its script."""
    if comm == "node":
        return next((kind for part, kind in NODE_AGENTS.items()
                     if any(part in arg for arg in args[1:])), comm)
    return AGENT_PROCESSES.get(comm, comm)


def session_pid(kind, proc=None, start=None):
    """Pid of the session process running this hook, or 0 for a shared helper.

    The outermost process of that agent wins, as the screensaver counts an
    agent's own child processes (e.g. kiro-cli -> kiro-cli-chat) as one session.
    """
    source = source_for(proc)
    pid, found, seen = start or os.getppid(), 0, set()
    while pid > 1 and pid not in seen:  # Windows recycles pids: never walk in circles
        seen.add(pid)
        comm, args = source.name(pid), source.args(pid)
        if agent_of(comm, args) == kind:
            if not found and any(arg in HELPER_ARGS for arg in args):
                return 0
            found = pid
        pid = source.parent(pid)
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
        db = sqlite3.connect(f"{Path(OPENCODE_DB).absolute().as_uri()}?mode=ro", uri=True, timeout=0.5)
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


def short_label(value, limit=48):
    """One safe terminal line; never interpret names as terminal controls."""
    if not isinstance(value, str):
        return ""
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    value = " ".join(''.join(c for c in value if c.isprintable()).split())
    value = value.encode('ascii', 'replace').decode()
    return value[:limit]


def path_label(value):
    if not isinstance(value, str):
        return ""
    return short_label(value.replace('\\', '/').rstrip('/').rsplit('/', 1)[-1])


def tool_activity(event):
    """Describe a tool without copying commands, prompts or file contents."""
    tool = event.get('tool_name') or event.get('tool') or ''
    if not isinstance(tool, str):
        return ""
    tool = tool.rsplit('__', 1)[-1].rsplit('.', 1)[-1].lower()
    args = event.get('tool_input') or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if not isinstance(args, dict):
        args = {}
    filename = path_label(args.get('file_path') or args.get('filePath') or args.get('path') or args.get('file'))
    if tool in ('read', 'read_file', 'view_image'):
        return 'Reading' + (f' {filename}' if filename else ' a file')
    if tool in ('edit', 'multiedit', 'write', 'write_file', 'apply_patch'):
        return 'Editing' + (f' {filename}' if filename else ' files')
    if tool in ('grep', 'glob', 'search', 'rg'):
        return 'Searching files'
    if tool in ('bash', 'shell', 'exec_command', 'run_shell_command'):
        command = args.get('command') or args.get('cmd') or ''
        try:
            tokens = shlex.split(command) if isinstance(command, str) else []
        except ValueError:
            tokens = []
        if tokens and tokens[0] == 'env':
            tokens = tokens[1:]
        while tokens and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', tokens[0]):
            tokens = tokens[1:]
        executable = tokens[0].replace('\\', '/').rsplit('/', 1)[-1] if tokens else ''
        args = tokens[1:]
        if executable in ('uv', 'poetry') and args[:1] == ['run']:
            executable, args = (args[1], args[2:]) if len(args) > 1 else ('', [])
        python_test = executable.startswith('python') and len(args) > 1 and args[0] == '-m' and args[1] in ('pytest', 'unittest')
        runner = executable in ('npm', 'pnpm', 'yarn', 'bun', 'cargo', 'go', 'make')
        target = args[1] if args[:1] == ['run'] and len(args) > 1 else (args[0] if args else '')
        if python_test or executable in ('pytest', 'vitest', 'jest') or (runner and target in ('test', 'tests')):
            return 'Running tests'
        if executable == 'tsc' or (runner and target in ('build', 'compile')):
            return 'Building project'
        if executable == 'git':
            return 'Checking changes' if args[:1] in (['diff'], ['status'], ['log'], ['show']) else 'Git operation'
        return 'Running a command'
    if tool in ('task', 'agent', 'spawn_agent'):
        return 'Delegating work'
    return 'Using a tool' if tool else ''


def activity_context(event, state, old, now):
    """Metadata only: project basename and a coarse description of the last action."""
    old = old if isinstance(old, dict) else {}
    project = path_label(event.get('cwd') or event.get('directory') or event.get('worktree')) or old.get('project', '')
    hook = str(event.get('hook_event_name', ''))
    action = tool_activity(event)
    last_action = action or old.get('last_action', '')
    if hook.lower() in ('posttooluse', 'posttoolusefailure') and not event.get('tool_input'):
        last_action = old.get('last_action') or action
    if state == 'wait':
        activity = 'Needs approval'
    elif state == 'idle':
        activity = 'Idle'
    elif hook.lower() == 'userpromptsubmit':
        activity, last_action = 'Working on request', ''
    elif hook.lower() in ('pretooluse', 'permissionresult'):
        activity = action or 'Working'
    elif hook.lower() in ('posttooluse', 'posttoolusefailure'):
        activity = 'Tool failed' if hook.lower() == 'posttoolusefailure' else 'Thinking'
    elif hook.lower() == 'subagentstart':
        activity = 'Delegating work'
    else:
        activity = old.get('activity', '') or ('Working' if state == 'work' else '')
    return {key: value for key, value in {
        'project': project, 'activity': activity, 'last_action': last_action,
        'updated_at': now if state else old.get('updated_at'),
    }.items() if value not in ('', None)}


def replace(source, destination, attempts=20, pause=0.01):
    """os.replace, retried on Windows, where it fails while the screensaver has the file open."""
    for attempt in range(attempts):
        try:
            return os.replace(source, destination)
        except PermissionError:
            if not is_windows() or attempt == attempts - 1:
                raise
            time.sleep(pause)


def write(path, data):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    # Write then rename so the screensaver never reads half a file.
    fd, temporary = tempfile.mkstemp(prefix=".agent-park-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(data, file)
        replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


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
    # Kimi names its subagents but gives them no id.
    named = event.get("agent_name")
    agent = re.sub(r"[^A-Za-z0-9-]", "", str(event.get("agent_id") or named or ""))
    if agent and hook == "SubagentStart":
        write(os.path.join(state_dir, f"{base}.sub-{agent}.json"),
              {"type": event.get("agent_type") or named or "subagent", "time": now})
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
        previous_context = old.get('context')
        if (str(hook).lower() in ('sessionstart', 'agentspawn')
                or (event.get('session_id') and old.get('session_id')
                    and event['session_id'] != old['session_id'])):
            previous_context = None
        data['context'] = activity_context(event, state, previous_context, now)
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
