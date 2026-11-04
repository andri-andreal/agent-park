# Agent Park

## Quick setup and diagnostics

Clone this repository to a permanent location, then run:

```sh
python3 agent_park.py doctor
python3 agent_park.py setup claude codex opencode pi mcode
```

When the terminal park or desktop app starts and finds supported agents without
integrations, it offers to configure them. You can skip and continue to the
park. In 3D, reopen the prompt from **Agents & alerts → Configure integrations**.
Desktop setup keeps its integration files in `$XDG_DATA_HOME/agent-park/integration`
(normally `~/.local/share/agent-park/integration`) so AppImage hooks remain
available after the app closes. Kiro and Kimi still need the manual steps below.

Choose only the integrations you use. Setup merges its own JSON hook entries
with existing settings and refuses to replace an existing plugin file. Run it
again safely after updating the project. Approve Codex hooks via `/hooks`;
restart OpenCode and Pi after installing their extensions. To remove the entries
or links installed by this checkout, run `python3 agent_park.py uninstall
claude codex opencode pi mcode`. Kiro and Kimi use the manual setup below.
Moving the checkout or changing Python paths requires removing the old entries
first. `doctor` checks configuration, not whether an agent has delivered an
event; it does not change your settings.

## Platforms

| | Linux | Windows | macOS |
|---|---|---|---|
| Process detection | `/proc`, nothing to install | `pip install psutil` | `pip install psutil` |
| Terminal park | built in | `pip install windows-curses` | built in |
| 3D app | DEB, AppImage | per-user `.exe` installer | not packaged |
| ccx router box | yes | no | no |

All the OS differences live in `platform_support.py`: where files go and how
processes are read (`/proc` or `psutil`). `python3 agent_park.py doctor` (`python`
on Windows) says which is in use and what is missing. Set `AGENT_PARK_PYTHON` to
make the 3D app and the OpenCode and Pi plugins use a specific interpreter.

On Windows the hook command is `python "C:/.../agent_hook.py" <agent>`: the script path
is double-quoted with forward slashes, and the interpreter is not quoted (a bare `python`
when that is the Python running setup, else its path). Claude Code runs hooks through
Git Bash, or PowerShell without it, and Codex through cmd or PowerShell; PowerShell
refuses a command that starts with a quoted path, the other shells accept both. The
OpenCode and Pi plugins are installed as a small file that loads the real plugin, because
symlinks need Developer Mode or elevation there. OpenCode reads `~/.config/opencode` on
Windows when that folder exists and `%APPDATA%\opencode` otherwise; setup follows it and
never creates the first next to an existing second.

**Status of Windows and macOS.** They have not been run on a real machine. The
Python side is tested against a simulated Windows `psutil`, and against `/proc` on
live Linux to show both give the same answers; the Rust side compiles for the
Windows target. How the agents run hooks and where they load plugins comes from their
documentation and reports, not from a Windows run:
[Claude Code hooks](https://code.claude.com/docs/en/hooks) name Git Bash and PowerShell;
Codex's [hooks](https://developers.openai.com/codex/hooks) offer a `commandWindows` override
and have open Windows reports (one says no hook command runs in Codex Desktop); the OpenCode
folder rule comes from third-party reports, not its own docs; Pi's `~/.pi/agent/extensions`
is assumed to sit under the user profile. Still unknown: how the terminal park looks in
Windows Terminal, and whether the Windows CI job passes (it is not required until it has).

**Checking it on Windows.** Install Python 3, then `pip install psutil windows-curses`, and from
the checkout run:

1. `python agent_park.py doctor` should say `Process detection: available (psutil ...)`.
2. `python park_state.py --once` should print one JSON line whose `agents` lists any
   running agent (start one first) and whose `system` is not `null`.
3. `python -m unittest` runs the whole suite; failures are the thing to report.
4. `python agent_park.py setup claude`, start Claude Code, send a prompt, and look in
   `%LOCALAPPDATA%\agent-park` for a `<pid>.json` file: that proves the hook ran.
5. `python screensaver.py` in Windows Terminal shows the terminal park.

## Usage limits

A **limits** box in the top-right, left of the system box (in the corner when the
system box is hidden), shows how much of your Claude, Codex, MiniMax and Kimi
limits is already used: a bar per window (`5h`, `7d`, ...), the percentage, and
the time until it resets. A small cat per provider worries as the limit fills;
bars turn yellow from 70% and pulse red from 90%. The 3D app has the same panel.
`old 15m` marks a sample older than 15 minutes. When the terminal is too short,
only the providers that fit are shown, followed by `+N more`.

Kimi only records its 5h window, and MiniMax its worst model's interval window.
The numbers are read, read-only, from the history database of
[AI Limit Monitor](https://github.com/andri-andreal/ai-limit-monitor)
(`~/.config/ai-limit-monitor/history.db`, or the path in `AGENT_PARK_USAGE_DB`),
so that app must be running to keep them fresh. Agent Park never contacts a
provider and never reads a token or cookie. Without the database, nothing is shown.

The AI agents you are running (Claude Code, Codex, OpenCode, Kiro, Pi, Kimi, MCode, ...)
live as animals in a park: they go to the office when working, jump when they
need your approval, and play when idle. Available as a terminal screensaver and
as a 3D app.

![Agent Park in the terminal: Claude and Codex working at their own desks, OpenCode asking for permission, Kiro and Pi playing in the park](docs/terminal.png)

By default, the park is only populated by animals belonging to running
Claude Code, Codex, and OpenCode sessions (see **AI cats** below), their
children for subagents, and monsters from heavy processes. If there are no
sessions yet, the park is empty with the text `The park is quiet...`. Run with
`--semua` (Indonesian for "all") to also spawn the wild animals listed below.

ASCII cats, dogs, rabbits, ducks, and mice with random behavior.
Some stroll leisurely, sleep, groom themselves, jump, or suddenly dash off.
When they meet, they may greet each other, chase one another, or get into a
cartoon fight with dust clouds and POW/BONK text, then flee in opposite
directions.

New animals occasionally enter from the edge of the screen; some just pass
through and leave again. The number of animals adjusts to the screen size
(up to eight). Runs with Python 3 and no extra packages on Linux; Windows and macOS
need `psutil` (see **Platforms**).

There are four places that switch automatically every 35 seconds:

- **Park**: trees, a bench, grass, and moving clouds.
- **Forest**: rows of trees and fireflies.
- **Beach**: coconut trees, the sun, sand, and moving waves.
- **Village**: houses and a road.

Animals walk on the ground area below the scenery. Changing location does not
remove the animals or stop interactions. When paused, the countdown for
switching places also stops.

Monsters attack whenever a heavy process newly appears on the computer! All
animals, including those sleeping and those just passing through, stop their
activity to gather, block the attack with shields, then strike back together.
The monster always loses and flees; the animals celebrate their victory with
jumps and confetti before returning to their activities. No animal gets hurt.

Monsters do not appear at random. A monster is a process started after the
screensaver was opened (including a shell that `exec`s another program) that
then uses on average at least 90% of one CPU core for 3 seconds or at least
1 GB of RAM. For example, `cargo build` or a test run by an agent. The
monster's name is taken from its process name, e.g. "Monster cargo (CPU 180%)".
Processes already running before the screensaver was opened, as well as the AI
agents themselves, never become monsters. Each process only attacks once, and
after a battle there is a 30-second cooldown. The thresholds can be changed via
`MONSTER_CPU`, `MONSTER_RSS`, and `RAID_COOLDOWN`. Press `r` to trigger an
attack manually. One event lasts about 14 seconds. Location changes and the
arrival of new animals wait until the battle is over; the pause key still
works.

System panel: in the top-right corner there is a small btop-style box
containing CPU, RAM, swap (if any), load average, and a graph of the last
24 seconds of CPU. Next to it sits a guard cat. If CPU goes above 60%, the cat
starts to worry (`CPU is climbing...`). If CPU goes above 85% or RAM above 90%,
the cat panics, trembles, and shouts `WATCH OUT! CPU 93%!`. The panel only
appears in terminals at least 64x20, and only where Agent Park can read the machine
(see **Platforms**).

The top row shows `AGENT PARK / <PLACE> / <mode>` on the left and, when the
terminal is wide enough, a live clock (`HH:MM:SS`) centred between it and the
system panel. A small **park stats** box sits in the top-left corner (unless a
ccx router box is there, or a monster raid is on): park uptime, the number of
animals and AI agents, monsters defeated (`wins`), and the current place with
its countdown.

AI cats: every running **Claude Code**, **Codex CLI**, or **OpenCode** session
gets its own animal: an orange cat `[Claude]`, a blue dog `[Codex]`, or a
light purple rabbit `[OpenCode]`. For simplicity, they are all called
"AI cats" below. The provider or model used does not matter: OpenCode with
DeepSeek, Gemini, or a local model is still an `[OpenCode]` rabbit.
The second and subsequent sessions are numbered, e.g. `[Claude 2]`. Status is
read from `/proc` every second based on average CPU usage over the last
3 seconds: if the session is working, the cat runs to **AI HQ**, a fenced area
on the right side of the ground containing a row of computers. Each cat gets
its own desk, sits facing its computer, then types frantically while shouting
`tik tak tuk!`, `ngoding!!`, and the like, while its computer screen shows
`>_ make`, a progress bar, and so on. An empty computer shows `zz`. If all
desks are taken, the remaining cats run around inside the HQ. The sign above
the HQ shows how many are currently working. Once a session stops, its cat
leaves the HQ and plays in the park like the other animals (but does not join
the fights). Ordinary animals do not enter the HQ. The HQ only appears if there
are AI cats and the terminal is at least 72 columns wide; on narrow screens the
cats work across the whole park. Once a session is closed, its cat says goodbye
and walks off the screen. AI cats do not join the fights, but they do join in
fighting the monsters. This needs process information: built in on Linux, through
`psutil` elsewhere (see **Platforms**).

Without extra configuration, the work status is only an estimate from CPU. For
accuracy, install a hook that calls `agent_hook.py`. This script writes the
session status to `$XDG_RUNTIME_DIR/agent-park/<pid>.json`, which the
screensaver then reads:

- `work`: you sent a prompt or the agent is using a tool. The cat sits at its computer in the HQ and types.
- `wait`: the agent is asking for permission. The cat jumps around with the
  label `need you!`.
- `idle`: the turn is finished or stopped. The cat leaves the HQ and plays in the park.

The hook also records the model used by the session, and that model then
appears on the animal's label, e.g. `[Claude | opus-5-5]`. The sources:

The 3D **Agents & alerts** panel shows each agent's status, how long the view
has observed that status, its source (hook or CPU estimate), and the age of the
last hook event. Shared Codex/OpenCode sessions are matched to windows by
recency, so their window association is uncertain. A stale work event may fall
back to CPU detection; an estimate cannot establish that approval is needed.
Optional desktop notifications trigger when an agent enters `wait`; alerts can
be filtered by agent type and rate-limited, and sound is optional. Linux
desktop notifications require `notify-send` and a notification service. Alert
settings are stored locally by the 3D view. Notifications are off by default.

| Agent | Model source |
| --- | --- |
| Claude Code | the last reply in the transcript (`transcript_path` from the hook) |
| Codex | `~/.codex/sessions/.../rollout-*-<session>.jsonl` |
| Kiro | `~/.kiro/sessions/cli/<session>.jsonl`; Auto mode is only recorded as `auto` |
| OpenCode | sent by the plugin; its fallback is the `session_v2.model` column in the OpenCode database (opened read-only) |
| Pi | `ctx.model` from the extension, including when using `/model` or Ctrl+P |

A new model appears after that session's first hook runs. Agents without a hook
do not display a model.

AI cats do not just walk in plainly. Their entrance is chosen at random: they
fall as a **meteor** (KABOOM!), get lowered by a **UFO** with a beam, come out
of a **portal**, **parachute** in, or get **teleported** from a random
character. If a monster attacks while a cat is landing, the cat immediately
joins the defense. Subagent children appear with a "POP!" effect after their
parent has landed.

Subagents appear as **children** of their parent animal (kitten, puppy, or
baby rabbit) labeled with their type (e.g. `[Explore]`). These children run
around their parent and leave when the subagent finishes. At most 4 children
per parent. A child whose `SubagentStop` event never arrives is removed after
30 minutes.

Claude Code (`~/.claude/settings.json`), one entry per event
`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`,
`SubagentStart`, `SubagentStop`, `PermissionRequest`, `Notification`, `Stop`,
`StopFailure`, `SessionStart`, `SessionEnd`:

```json
{"hooks": {"Stop": [{"hooks": [{"type": "command", "timeout": 5,
  "command": "python3 /path/to/screensaver/agent_hook.py claude"}]}]}}
```

Codex CLI (`~/.codex/hooks.json`) uses the same format with the argument
`codex`, for the events `UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
`SubagentStart`, `SubagentStop`, `PermissionRequest`, `Stop`, `Interrupt`,
`SessionStart`, `SessionEnd`. Approve the hook once via `/hooks` in Codex.

Codex runs hooks from a single background process (`codex app-server`) that
serves all Codex windows, so it is not known which window owns a given session.
Because of this, Codex status is stored per session
(`codex-<session_id>.json`), and Codex cats are taken from the most recent
sessions, as many as there are open Codex windows. Windows that have not yet
sent an event use the CPU estimate.

If the [ccx](../ccx) profile uses a router (`ccx-router`), a **ccx router** box
appears in the top-left. It contains the profile name, local port, upstream
host (without path or credentials), uptime, and the Claude cat using it. The
arrow `>-->` moves when the router or its cat is working; otherwise it shows
`idle` and the number of open connections. At most three routers are shown, and
the rest are summarized as `+N more`. A router never becomes a monster. The
router box is Linux-only, like ccx itself.

OpenCode has no command-based hooks, so its status is sent via the
`opencode_plugin.js` plugin. This plugin turns OpenCode session events (busy,
asking for permission or asking a question, finished) into Claude-style events,
then calls `agent_hook.py opencode`. OpenCode subagents (e.g. `@explore`)
appear as baby rabbits. This plugin supports OpenCode 1.x and 2.x. Install it
with a symlink:

```sh
mkdir -p ~/.config/opencode/plugins
ln -s "$PWD/opencode_plugin.js" ~/.config/opencode/plugins/agent-park.js
opencode service restart   # OpenCode 2.x; on 1.x just reopen OpenCode
```

Starting with OpenCode 2.x, all windows are served by a single background
process (`opencode serve --service`), and the plugin runs there. That
background process itself is not counted as a session. Like Codex, status is
stored per session (`opencode-<session_id>.json`) and shared with the open
OpenCode windows.

List of recognized agents:

| Agent | Process | Animal | Accurate status |
| --- | --- | --- | --- |
| Claude Code | `claude` | orange cat | hook (above) |
| Codex CLI | `codex` | blue dog | hook (above) |
| OpenCode | `opencode` | light purple rabbit | plugin (above) |
| Kiro CLI | `kiro-cli`, `kiro-cli-chat` | purple mouse | hook (below) |
| Aider | `aider` | green mouse | CPU estimate |
| Goose | `goose` | yellow duck | CPU estimate |
| Crush | `crush` | pink cat | CPU estimate |
| Amp | `amp` | red dog | CPU estimate |
| Pi | `pi` | light blue duck | extension (below) |
| Strix | `strix` | dark red dog | CPU estimate |
| Kimi Code | `kimi` | white rabbit | hook (below) |
| MCode (MiniMax) | `node` running `@minimax-ai/code` | coral duck | hook (below) |

Pi runs on top of Node but renames its process to `pi`, so it is still
detected. Its status is sent via the `pi_extension.ts` extension: starting and
finishing answering a prompt (including Esc), and exiting. Pi has no built-in
permission prompt or subagents, so there is no `need you!` or baby ducks.
Install it with a symlink, then reopen Pi:

```sh
mkdir -p ~/.pi/agent/extensions
ln -s "$PWD/pi_extension.ts" ~/.pi/agent/extensions/agent-park.ts
```

Kiro CLI only supports hooks in custom agents. The safest way is to copy the
built-in agent so that all tools stay active. After that, add the `hooks`
section below to `~/.kiro/agents/agent-park.json`, validate it, then make it
the default:

```sh
EDITOR=true kiro-cli agent create agent-park --from kiro_default
kiro-cli agent validate --path ~/.kiro/agents/agent-park.json
kiro-cli agent set-default agent-park
```

An agent that only contains `hooks` may lose access to tools. Kiro event names
use camelCase, and `agent_hook.py` accepts them as-is. Kiro only has these five
events and has no event for when it asks for permission, so its animal cannot
display `need you!`.

```json
{"hooks": {
  "agentSpawn": [{"command": "python3 /path/to/screensaver/agent_hook.py kiro-cli"}],
  "userPromptSubmit": [{"command": "python3 /path/to/screensaver/agent_hook.py kiro-cli"}],
  "preToolUse": [{"command": "python3 /path/to/screensaver/agent_hook.py kiro-cli"}],
  "postToolUse": [{"command": "python3 /path/to/screensaver/agent_hook.py kiro-cli"}],
  "stop": [{"command": "python3 /path/to/screensaver/agent_hook.py kiro-cli"}]
}}
```

Kimi Code reads hooks from `~/.kimi-code/config.toml`, one `[[hooks]]` table
per event, with the argument `kimi`. Its events are named like Claude's:
`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`,
`PermissionRequest`, `PermissionResult`, `SubagentStart`, `SubagentStop`,
`Stop`, `StopFailure`, `Interrupt`, `SessionStart`, `SessionEnd`.
`PermissionResult` (you answered its prompt) sends the rabbit back to work.
Kimi gives subagents a name but no id, so the name is used for both.

```toml
[[hooks]]
event = "Stop"
command = "python3 /path/to/screensaver/agent_hook.py kimi"
timeout = 5
```

MCode runs as a plain `node` process, so it is recognised by its script path
(`NODE_AGENTS` in `agent_hook.py`), and its heavy moments never become
monsters. Its user hooks live in `~/.minimax/hooks.json` (or add them with
`/hooks` inside MCode), in Claude's format plus `"enabled": true`, with the
argument `mcode`, for the events `SessionStart`, `SessionEnd`,
`UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`,
`SubagentStart`, `SubagentStop`, `Stop`:

```json
{"enabled": true, "hooks": {"Stop": [{"hooks": [{"type": "command", "timeout": 5,
  "command": "python3 /path/to/screensaver/agent_hook.py mcode"}]}]}}
```

Other agents can be added to the `AGENTS` table in `screensaver.py` (process
name, name, animal type, color). Their animal can also be changed in that
table, e.g. `"bebek"` (duck) or `"tikus"` (mouse). A detected agent without a
hook uses the CPU estimate. The requirement is that its process name in
`/proc/<pid>/comm` must be distinctive. An agent running as a plain `node`
needs an entry in `NODE_AGENTS` instead, naming part of its script's path.

Claude does not send an event when you press Esc. Because of this, a `work`
status older than 90 seconds is read from CPU again.

Run from the project folder:

```sh
python3 screensaver.py          # AI cats only
python3 screensaver.py --semua  # plus wild animals
```

Enable fullscreen from your terminal application (usually **F11** on Linux).
The animation automatically follows the terminal size, including after a
resize.

| Key | Function |
| --- | --- |
| `q` / `Esc` | Quit |
| `Space` | Pause / resume |
| `+` / `-` | Increase / decrease speed |
| `n` | Bring in a passing animal, if the screen is not yet full (only with `--semua`) |
| `l` | Move to the next location |
| `r` | Trigger a monster attack; all animals cooperate until they win |
| `a` | Toggle automatic location switching (stay in the current place) |
| `s` | Show / hide the system panel |
| `Ctrl+C` | Quit |

On exit, the terminal display and cursor are restored to how they were. This is
a manually run animation; it is not yet connected to the system screensaver
settings.

## Agent Park 3D

![Agent Park 3D: Pi and OpenCode working in the office, Claude asking for permission together with an Explore subagent child, Codex and Kiro playing in the park](docs/park3d.png)

`park3d/` contains a 3D version of this park as a desktop app
([Tauri](https://tauri.app) with Three.js). The terminal can still be used as
usual. The agent detection logic stays in Python: the app runs
`park_state.py`, which prints the park status as one line of JSON per second
(agents, subagents, CPU/RAM, monsters, and a `stats` block with uptime and
counts), and the 3D world then moves its own animals based on that status. New
agents only need to be added to the `AGENTS` table, and both views get them
right away.

Like the terminal, the 3D HUD shows a live clock in the top-left along with a
one-line park-stats summary (uptime, working/total agents, subagents, and the
number of heavy processes seen) built from the `stats` block.

```sh
cd park3d
pnpm install
pnpm tauri dev                 # run while developing
pnpm tauri build --no-bundle   # binary: src-tauri/target/release/park3d
```

Display options, as app arguments (`park3d --low --fps`) or in the browser URL
(`?low&fps`):

| Option | Function |
| --- | --- |
| `--low` | No shadows or antialiasing, 1× resolution. Lightest |
| `--fps` | Show FPS and draw call count in the top-left corner |
| `--cap=N` | FPS cap (default 30; `--cap=0` for no cap) |
| `--smooth` | 60 FPS, same as `--cap=0` |

Requires Rust, Node, pnpm, and `webkit2gtk-4.1`. `python3 park_state.py --once`
shows a single status snapshot, and `pnpm dev` followed by opening
`http://localhost:1420/?demo` shows the 3D world with sample agents in a regular
browser. On Wayland, the app sets `WEBKIT_DISABLE_DMABUF_RENDERER=1` so that
WebGL is not black. The location of the status script can be changed via
`PARK_STATE`.

Release bundles include the Python backend scripts; Python 3 remains a runtime
requirement (a Linux desktop with WebKitGTK on Linux; WebView2, which ships with
Windows 10 and 11, on Windows). The GitHub Actions packages workflow can be run
manually or by pushing a `v*` tag and publishes the DEB and AppImage files and a
per-user Windows installer (NSIS `.exe`) as workflow artifacts. It does not publish
a GitHub release. The CI workflow runs Python tests, builds the 3D frontend, and
checks the Rust backend, on Linux and, not yet required to pass, on Windows.

### Local data and limitations

Hooks write status, session identifiers, timestamps, and model names to
`$XDG_RUNTIME_DIR/agent-park` (or `~/.cache/agent-park`; `%LOCALAPPDATA%\agent-park`
on Windows). They may read the tail
of local transcripts or the OpenCode database to determine the model; prompt
and response text is not copied into state files. Session-end events and the
monitor clean up state files, but abrupt shutdowns can leave files until a later
monitor run. Remove the directory manually when Agent Park is stopped if needed.
Agent detection and CPU estimates read Linux `/proc`, or `psutil` on Windows and
macOS (see **Platforms**). Without either, the animation still runs but finds no sessions.

Test the interaction simulation, passing animals, and resize with:

```sh
python3 -m unittest -v
```
