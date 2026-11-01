#!/usr/bin/env python3
"""Set up and diagnose Agent Park integrations without replacing user settings."""
import argparse
import copy
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import subprocess

ROOT = Path(__file__).resolve().parent
HOME = Path.home()
EVENTS = {
    "claude": (HOME / ".claude/settings.json", "UserPromptSubmit PreToolUse PostToolUse PostToolUseFailure SubagentStart SubagentStop PermissionRequest Notification Stop StopFailure SessionStart SessionEnd".split()),
    "codex": (HOME / ".codex/hooks.json", "UserPromptSubmit PreToolUse PostToolUse SubagentStart SubagentStop PermissionRequest Stop Interrupt SessionStart SessionEnd".split()),
    "mcode": (HOME / ".minimax/hooks.json", "SessionStart SessionEnd UserPromptSubmit PreToolUse PermissionRequest PostToolUse SubagentStart SubagentStop Stop".split()),
}
LINKS = {"opencode": (HOME / ".config/opencode/plugins/agent-park.js", ROOT / "opencode_plugin.js"),
         "pi": (HOME / ".pi/agent/extensions/agent-park.ts", ROOT / "pi_extension.ts")}
COMMANDS = {"claude": "claude", "codex": "codex", "mcode": "mcode", "opencode": "opencode", "pi": "pi", "kiro": "kiro-cli", "kimi": "kimi"}
BIN_DIRS = {"opencode": HOME / ".opencode/bin", "mcode": HOME / ".minimax-code/bin", "kimi": HOME / ".kimi-code/bin"}


def find_agent(kind, binary):
    found = shutil.which(binary)
    if found:
        return found
    for directory in (HOME / ".local/bin", BIN_DIRS.get(kind, HOME / ".local/bin")):
        path = directory / binary
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def command(kind):
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(ROOT / 'agent_hook.py'))} {kind}"


def equivalent_hook(hook, kind):
    if not isinstance(hook, dict) or not isinstance(hook.get("command"), str):
        return False
    try:
        args = shlex.split(hook["command"])
        return (len(args) == 3 and Path(args[0]).name.startswith("python")
                and Path(args[1]).resolve() == ROOT / "agent_hook.py" and args[2] == kind)
    except ValueError:
        return False


def park_hook(hook, kind):
    """Recognize an existing live Agent Park checkout or installed integration."""
    if not isinstance(hook, dict) or not isinstance(hook.get("command"), str):
        return False
    try:
        args = shlex.split(hook["command"])
        path = Path(args[1]).expanduser() if len(args) == 3 else None
        return bool(path and Path(args[0]).name.startswith("python") and
                    path.name == "agent_hook.py" and path.is_file() and args[2] == kind)
    except (ValueError, OSError):
        return False


def integration_status():
    """Describe installed agents without changing configuration or state files."""
    result = []
    for kind, binary in COMMANDS.items():
        if not find_agent(kind, binary):
            continue
        if kind in EVENTS:
            path, events = EVENTS[kind]
            try:
                data = load(path)
                hooks = data.get("hooks", {})
                if not isinstance(hooks, dict):
                    raise ValueError("hooks must be an object")
                count = sum(any(park_hook(h, kind) for group in hooks.get(event, [])
                                if isinstance(group, dict) and isinstance(group.get("hooks"), list)
                                for h in group["hooks"]) for event in events)
                configured = count == len(events) and not (kind == "mcode" and data.get("enabled") is False)
                result.append({"kind": kind, "configured": configured, "automatic": True,
                               "detail": f"{count}/{len(events)} events configured"})
            except (OSError, ValueError, TypeError) as error:
                result.append({"kind": kind, "configured": False, "automatic": False, "detail": str(error)})
        elif kind in LINKS:
            path, target = LINKS[kind]
            configured = path.is_symlink() and path.exists() and path.resolve().name == target.name
            conflict = (path.exists() or path.is_symlink()) and not configured
            result.append({"kind": kind, "configured": configured, "automatic": not conflict,
                           "detail": "configured" if configured else ("plugin path already exists" if conflict else "not configured")})
        else:
            result.append({"kind": kind, "configured": False, "automatic": False,
                           "detail": "manual setup; see README"})
    return result


def load(path):
    if not path.exists():
        return {}
    with path.open() as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return data


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".agent-park-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def configure(kind, remove=False):
    if kind in LINKS:
        path, target = LINKS[kind]
        if path.is_symlink() and path.resolve() == target:
            if remove:
                path.unlink()
            return "removed" if remove else "already installed"
        if remove:
            return "not installed by this checkout"
        if path.exists() or path.is_symlink():
            raise ValueError(f"{path} already exists; left unchanged")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
        return "installed"
    path, events = EVENTS[kind]
    if path.is_symlink():
        raise ValueError(f"{path} is a symlink; configure it manually to preserve the link")
    if remove and not path.exists():
        return "not installed"
    data = load(path)
    original = copy.deepcopy(data)
    if remove and "hooks" not in data:
        return "not installed"
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{path}: hooks must be an object")
    for event in events:
        groups = hooks.get(event, [])
        if not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get("hooks"), list) for g in groups):
            raise ValueError(f"{path}: unexpected {event} hook format; left unchanged")
        if remove:
            retained = []
            for group in groups:
                before = group["hooks"]
                after = [h for h in before if not isinstance(h, dict) or h.get("command") != command(kind)]
                if after or len(after) == len(before):
                    group["hooks"] = after
                    retained.append(group)
            if event in hooks:
                if retained:
                    hooks[event] = retained
                else:
                    del hooks[event]
        elif not any(park_hook(h, kind) for g in groups for h in g["hooks"]):
            groups.append({"hooks": [{"type": "command", "timeout": 5, "command": command(kind)}]})
            hooks[event] = groups
    if kind == "mcode" and not remove:
        data.setdefault("enabled", True)
    if data != original:
        save(path, data)
    if kind == "mcode" and not remove and data.get("enabled") is False:
        return "installed, but hooks are disabled in the existing configuration"
    return "removed" if remove else "installed"


def doctor():
    print(f"Agent Park: {ROOT}\nPython: {sys.executable}")
    print(f"Process detection: {'available' if Path('/proc/self/stat').exists() else 'unavailable (Linux /proc required)'}")
    for kind, binary in COMMANDS.items():
        installed = find_agent(kind, binary)
        if kind in EVENTS:
            try:
                data = load(EVENTS[kind][0])
                hooks = data.get("hooks", {})
                count = sum(any(park_hook(h, kind)
                                for g in hooks.get(event, []) if isinstance(g, dict)
                                for h in g.get("hooks", []) if isinstance(g.get("hooks"), list)) for event in EVENTS[kind][1])
                integration = f"{count}/{len(EVENTS[kind][1])} events configured"
                if kind == "mcode" and data.get("enabled") is False:
                    integration += "; hooks disabled"
            except (OSError, ValueError, TypeError) as error:
                integration = f"cannot read configuration: {error}"
        elif kind in LINKS:
            path, target = LINKS[kind]
            integration = "configured" if path.is_symlink() and path.exists() and path.resolve().name == target.name else "not configured"
        else:
            integration = "manual setup: see README"
        print(f"{kind}: {'found at ' + installed if installed else 'not found on PATH'}; {integration}")
    print("Codex hooks must also be approved in /hooks. Restart OpenCode or Pi after setup.")


def prompt_setup(input_fn=input, output=print):
    agents = integration_status()
    pending = [a for a in agents if a["automatic"] and not a["configured"]]
    if not pending:
        return
    output("Agent Park found agents that have not been configured: " + ", ".join(a["kind"] for a in pending))
    output("Setup adds hooks or plugin links to your user configuration; existing settings are kept.")
    try:
        answer = input_fn("Set them up now? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        output("Setup skipped.")
        return
    if answer not in ("y", "yes"):
        return
    for agent in pending:
        try:
            output(f"{agent['kind']}: {configure(agent['kind'])}")
        except (OSError, ValueError, TypeError) as error:
            output(f"{agent['kind']}: {error}")
    output("Approve Codex hooks in /hooks; restart OpenCode and Pi after setup.")
    try:
        input_fn("Press Enter to open the park... ")
    except (EOFError, KeyboardInterrupt):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("doctor", help="check dependencies and integration configuration")
    sub.add_parser("onboarding-status", help=argparse.SUPPRESS)
    gui = sub.add_parser("onboarding-setup", help=argparse.SUPPRESS)
    gui.add_argument("agents", nargs="+", choices=sorted((*EVENTS, *LINKS)))
    for action in ("setup", "uninstall"):
        p = sub.add_parser(action, help=f"{action} selected integrations")
        p.add_argument("agents", nargs="+", choices=sorted((*EVENTS, *LINKS)), help="agents to configure")
    args = parser.parse_args()
    if args.action == "doctor":
        doctor()
        return 0
    if args.action == "onboarding-status":
        print(json.dumps(integration_status()))
        return 0
    if args.action == "onboarding-setup":
        # A packaged AppImage is extracted to a temporary directory. Integrations
        # must point at persistent files after the desktop app has exited.
        root = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share") / "agent-park/integration"
        root.mkdir(parents=True, exist_ok=True)
        for name in ("agent_park.py", "agent_hook.py", "opencode_plugin.js", "pi_extension.ts"):
            source, destination = ROOT / name, root / name
            if source.resolve() != destination.resolve():
                fd, temporary = tempfile.mkstemp(prefix=".agent-park-", dir=root)
                os.close(fd)
                try:
                    shutil.copy2(source, temporary)
                    os.replace(temporary, destination)
                finally:
                    Path(temporary).unlink(missing_ok=True)
        return subprocess.call([sys.executable, str(root / "agent_park.py"), "setup", *args.agents])
    failed = False
    for kind in dict.fromkeys(args.agents):
        try:
            print(f"{kind}: {configure(kind, args.action == 'uninstall')}")
        except (OSError, ValueError, TypeError) as error:
            print(f"{kind}: {error}", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
