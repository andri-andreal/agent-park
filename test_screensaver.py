"""Simulation checks; no real terminal or waiting required."""

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import agent_hook
import park_state
from screensaver import (AgentMonitor, ENTRANCES, PLACE_DURATION, PLACES, RAID_COOLDOWN,
                         SPRITES, WORK_CHATTER, ProcessWatcher, RouterMonitor, SystemMonitor, World,
                         render)


class Screen:
    def __init__(self, height, width):
        self.height, self.width = height, width
        self.rows = [[" "] * width for _ in range(height)]

    def getmaxyx(self):
        return self.height, self.width

    def addstr(self, y, x, text, style):
        assert 0 <= y < self.height
        assert 0 <= x and x + len(text) <= self.width
        self.rows[y][x:x + len(text)] = text


class WorldTests(unittest.TestCase):
    def test_whole_team_defends_wins_and_returns_to_normal(self):
        world = World(100, 30, seed=2)
        world.spawn(species="bebek", visitor=True)
        world.animals[-1].state = "pass"
        world.animals[0].state = "sleep"
        world.start_encounter(*world.animals[1:3], "fight")
        animals = world.animals[:]
        place_timer, arrival = world.place_timer, world.arrival
        world.start_raid()
        self.assertFalse(world.encounters)
        raid = world.raid
        world.start_raid()
        self.assertIs(world.raid, raid)
        phases, states, health = set(), set(), []
        for _ in range(400):
            world.update(0.05, 8)
            self.assertEqual(world.animals, animals)
            if not world.raid:
                break
            phases.add(world.raid.phase)
            health.append(world.raid.health)
            states.update(a.state for a in animals)
            for animal in animals:
                self.assertGreaterEqual(animal.x, 1)
                self.assertGreaterEqual(animal.y, world.ground_top)
        self.assertIsNone(world.raid)
        self.assertEqual(phases, {"datang", "tangkis", "lawan", "menang"})
        self.assertEqual(states, {"rally", "guard", "attack", "cheer"})
        self.assertEqual(world.victories, 1)
        self.assertEqual(min(health), 0)
        self.assertEqual(health, sorted(health, reverse=True))
        self.assertEqual(world.place_timer, place_timer)
        self.assertEqual(world.arrival, arrival)
        for animal in animals:
            self.assertEqual(animal.state, "pass" if animal.visitor else "walk")
        self.assertEqual(world.raid_cooldown, RAID_COOLDOWN)

    def test_heavy_process_starts_a_raid_that_holds_place_and_population(self):
        world = World(100, 30, seed=4)
        self.assertTrue(world.threat("cargo-build-script", "CPU 180%"))
        self.assertEqual(world.raid.monster, "cargo-build-scr")
        self.assertIn("Monster cargo-build-scr (CPU 180%) datang", world.notice)
        self.assertFalse(world.threat("node", "RAM 2.0 GB"))  # one monster at a time
        place, population = world.place, len(world.animals)
        world.change_place()
        world.spawn(visitor=True)
        self.assertEqual(world.place, place)
        self.assertEqual(len(world.animals), population)
        while world.raid:
            world.update(0.1, 8)
        self.assertFalse(world.threat("node", "RAM 2.0 GB"))  # the park rests first
        for _ in range(int(RAID_COOLDOWN / 0.5) + 1):
            world.update(0.5, 8)
        self.assertTrue(world.threat("node", "RAM 2.0 GB"))

    def test_monster_name_shows_in_battle(self):
        world = World(80, 24, seed=4)
        world.threat("rustc", "CPU 95%")
        world.update(4, 8)
        screen = Screen(24, 80)
        render(screen, world, 8, False, dict.fromkeys(SPRITES, 0), [])
        text = "\n".join("".join(row) for row in screen.rows)
        self.assertIn("TANGKIS! Monster rustc:", text)
        self.assertEqual(text.count("rustc"), 2)  # banner and the name over its head

    def test_places_cycle_automatically_and_can_be_locked(self):
        world = World(80, 24, seed=8)
        seen = []
        for _ in PLACES:
            seen.append(world.place)
            world.place_timer = 0.01
            world.update(0.02, 8)
            self.assertEqual(world.place_timer, PLACE_DURATION)
        self.assertEqual(tuple(seen), PLACES)
        self.assertEqual(world.place, PLACES[0])
        world.auto_place = False
        world.place_timer = 0.01
        world.update(1, 8)
        self.assertEqual(world.place, PLACES[0])
        self.assertEqual(world.place_timer, 0.01)
        world.change_place()
        self.assertEqual(world.place, PLACES[1])
        self.assertFalse(world.auto_place)

    def test_changing_place_preserves_animals_and_active_encounters(self):
        world = World(80, 24, seed=2)
        animals = world.animals[:]
        world.start_encounter(*animals[:2], "fight")
        encounter = world.encounters[0]
        for _ in PLACES:
            world.change_place()
            world.update(0.04, 8)
            self.assertEqual(world.animals, animals)
            self.assertIs(world.encounters[0], encounter)
            for animal in animals:
                self.assertGreaterEqual(animal.y, world.ground_top)

    def test_all_places_render_at_small_and_fullscreen_sizes(self):
        for width, height in ((32, 12), (80, 24), (160, 50)):
            world = World(width, height, seed=3)
            for place in PLACES:
                with self.subTest(size=(width, height), place=place):
                    screen = Screen(height, width)
                    render(screen, world, 8, False, dict.fromkeys(SPRITES, 0),
                           [(0.3, 0.5, 1.0)] * 32)
                    self.assertIn(place.upper(), "".join(screen.rows[0]))
                    self.assertIn("q keluar", "".join(screen.rows[-1]))
                    self.assertTrue(any("".join(row).strip() for row in screen.rows[2:world.ground_top]))
                    world.start_raid()
                    for age, label in ((1, "AWAS!"), (4, "TANGKIS!"), (8, "SERBU!"), (12, "MENANG!")):
                        world.raid.age = age
                        world.update_raid(0)
                        render(screen, world, 8, False, dict.fromkeys(SPRITES, 0), [])
                        self.assertIn(label, "".join(screen.rows[2]))
                    world.update_raid(3)
                world.change_place()

    def test_visitors_cross_and_leave_in_both_directions(self):
        for direction in (-1, 1):
            with self.subTest(direction=direction):
                world = World(80, 24, seed=8)
                world.animals.clear()
                world.spawn(species="bebek", visitor=True)
                visitor = world.animals[0]
                visitor.vx = direction
                visitor.x = -visitor.width if direction > 0 else world.width
                world.arrival = 1000
                for _ in range(300):
                    world.update(0.05, 8)
                self.assertNotIn(visitor, world.animals)

    def test_neighbours_can_start_all_three_encounters(self):
        seen = set()
        for seed in range(60):
            world = World(80, 24, seed=seed)
            world.animals = world.animals[:2]
            for animal in world.animals:
                animal.x, animal.y = 20, 8
                animal.cooldown = 0
                animal.timer = 100
            world.update(0.04, 8)
            self.assertEqual(len(world.encounters), 1)
            seen.add(world.encounters[0].kind)
        self.assertEqual(seen, {"fight", "chase", "greet"})

    def test_encounters_release_both_animals(self):
        for kind in ("fight", "chase", "greet"):
            with self.subTest(kind=kind):
                world = World(80, 24, seed=4)
                first, second = world.animals[:2]
                world.start_encounter(first, second, kind)
                for _ in range(85):
                    world.update(0.05, 8)
                self.assertFalse(world.encounters)
                for animal in (first, second):
                    self.assertNotIn(animal.state, ("fight", "chase", "greet"))
                    self.assertGreater(animal.cooldown, 0)
                if kind == "fight":
                    self.assertLess(first.x, second.x)

    def test_residents_stay_visible_after_resize(self):
        world = World(160, 50, seed=3)
        world.width, world.height = 32, 12
        for _ in range(500):
            world.update(0.05, 24)
            for animal in world.animals:
                if not animal.visitor:
                    self.assertGreaterEqual(animal.x, 1)
                    self.assertLessEqual(animal.x + animal.width, 31)
                self.assertGreaterEqual(animal.y, 4)
                self.assertLessEqual(animal.y + 4, 10)

    def test_long_running_world_keeps_turnover_and_variety(self):
        world = World(100, 30, seed=42)
        species, states, encounters = set(), set(), set()
        departed = set()
        previous = set(world.animals)
        for _ in range(12000):
            world.update(0.05, 8)
            self.assertLessEqual(len(world.animals), world.capacity)
            self.assertIsNone(world.raid)  # monsters only come from real processes
            species.update(a.species for a in world.animals)
            states.update(a.state for a in world.animals)
            encounters.update(e.kind for e in world.encounters)
            current = set(world.animals)
            departed.update(previous - current)
            previous = current
        self.assertEqual(len(species), 5)
        self.assertTrue({"sleep", "groom", "hop", "sprint"} <= states)
        self.assertEqual(encounters, {"fight", "chase", "greet"})
        self.assertGreater(len(departed), 10)


def land(world):
    """Skip the arrival animations."""
    for animal in world.animals:
        animal.entry = 0


class AgentTests(unittest.TestCase):
    def fake_proc(self, root, pid, comm, ticks, args=(), parent=1, rss=0):
        os.makedirs(f"{root}/{pid}", exist_ok=True)
        with open(f"{root}/{pid}/comm", "w") as file:
            file.write(comm + "\n")
        with open(f"{root}/{pid}/cmdline", "wb") as file:
            file.write("\0".join((comm, *args)).encode() + b"\0")
        with open(f"{root}/{pid}/stat", "w") as file:
            file.write(f"{pid} ({comm} x) S {parent} 2 3 4 5 6 7 8 9 10 {ticks} 0 0 0 20 0 1 0 0 0 {rss}\n")

    def test_monitor_finds_sessions_and_tells_busy_from_idle(self):
        with tempfile.TemporaryDirectory() as root:
            monitor = AgentMonitor(root, state_dir=f"{root}/state")
            monitor.ticks_per_second = 100
            self.fake_proc(root, 10, "claude", 0)
            self.fake_proc(root, 11, "codex", 0)
            self.fake_proc(root, 12, "claude", 0, ("--chrome-native-host",))
            self.fake_proc(root, 13, "bash", 0)
            self.fake_proc(root, 14, "codex", 0, ("app-server",), parent=11)
            self.fake_proc(root, 15, "codex", 50, ("app-server",), parent=99)
            os.makedirs(f"{root}/self")
            self.assertEqual(monitor.poll(0), {10: ("claude", "idle"), 11: ("codex", "idle")})
            self.fake_proc(root, 10, "claude", 10)  # 10% CPU: working
            self.fake_proc(root, 11, "codex", 1)  # 1% CPU: waiting for input
            self.fake_proc(root, 15, "codex", 90, ("app-server",), parent=99)
            self.assertEqual(monitor.poll(1), {10: ("claude", "work"), 11: ("codex", "idle")})
            # Codex's app-server child does the work for its session.
            self.fake_proc(root, 14, "codex", 20, ("app-server",), parent=11)
            self.assertEqual(monitor.poll(2), {10: ("claude", "work"), 11: ("codex", "work")})
            for pid in (10, 11, 12, 13, 14, 15):
                for name in ("comm", "cmdline", "stat"):
                    os.remove(f"{root}/{pid}/{name}")
            self.assertEqual(monitor.poll(3), {})
            self.assertEqual(monitor.history, {})
        self.assertEqual(AgentMonitor("/no/such/proc").poll(0), {})

    def test_agent_cats_follow_sessions(self):
        world = World(100, 30, seed=5)
        world.arrival = 1000
        for pid in range(1, 20):
            world.spawn()
        wild = len(world.animals)
        world.sync_agents({7: ("claude", "work"), 8: ("claude", "idle"), 9: ("codex", "idle")})
        cats = {a.agent: a for a in world.animals if a.agent}
        self.assertEqual(len(world.animals), wild + 3)
        self.assertEqual({a.name for a in cats.values()}, {"Claude", "Claude 2", "Codex"})
        for _ in range(100):
            world.update(0.05, 8)
        # Busy cats dash around the office; idle ones play in the park.
        office = world.office
        self.assertIsNotNone(office)
        before = (cats[7].x, cats[7].y)
        for _ in range(20):
            world.update(0.05, 8)
            self.assertEqual(cats[7].state, "work")
            self.assertGreater(cats[7].x, office)
            for pid in (8, 9):
                self.assertNotIn(cats[pid].state, ("work", "wait"))
                self.assertLess(cats[pid].x, office)
        self.assertNotEqual((cats[7].x, cats[7].y), before)
        # Wild animals never settle in the office either.
        self.assertTrue(all(a.x < office for a in world.animals if not a.agent and not a.visitor))
        world.sync_agents({7: ("claude", "idle"), 8: ("claude", "work"), 9: ("codex", "idle")})
        world.update(0.05, 8)
        self.assertEqual((cats[7].state, cats[7].vx, cats[8].state), ("walk", -1, "work"))
        for _ in range(100):
            world.update(0.05, 8)
        self.assertLess(cats[7].x, office)  # clocked out, back to the park
        self.assertGreater(cats[8].x, office)  # clocked in
        world.sync_agents({8: ("claude", "work")})
        for cat in (cats[7], cats[9]):
            self.assertEqual((cat.agent, cat.visitor, cat.state), (0, True, "pass"))
        for _ in range(400):
            world.update(0.05, 8)
        self.assertNotIn(cats[7], world.animals)
        self.assertIn(cats[8], world.animals)

    def test_agent_cats_join_raids_and_arrive_after_them(self):
        world = World(100, 30, seed=6)
        world.sync_agents({7: ("claude", "work")})
        cat = next(a for a in world.animals if a.agent)
        world.start_raid()
        world.sync_agents({7: ("claude", "idle"), 8: ("codex", "work")})
        world.update(4, 8)
        self.assertEqual(cat.state, "guard")
        self.assertEqual(cat.status, "idle")
        self.assertFalse(any(a.agent == 8 for a in world.animals))
        while world.raid:
            world.update(0.1, 8)
        world.update(0.05, 8)
        self.assertEqual(cat.state, "walk")  # idle: off to play
        world.sync_agents({7: ("claude", "idle"), 8: ("codex", "work")})
        self.assertTrue(any(a.agent == 8 for a in world.animals))

    def test_hook_states_override_cpu_guess(self):
        with tempfile.TemporaryDirectory() as root:
            clock = [1000.0]
            state = f"{root}/state"
            monitor = AgentMonitor(root, state_dir=state, clock=lambda: clock[0])
            monitor.ticks_per_second = 100
            self.fake_proc(root, 10, "claude", 0)
            self.fake_proc(root, 11, "codex", 0)
            monitor.poll(0)
            hook = lambda pid, kind, event, **extra: agent_hook.record(
                kind, {"hook_event_name": event, **extra}, pid, state, now=clock[0])
            hook(10, "claude", "PermissionRequest")
            hook(11, "codex", "UserPromptSubmit")
            hook(77, "claude", "UserPromptSubmit")  # a session that died without SessionEnd
            hook(10, "claude", "Notification", notification_type="auth_success")  # ignored
            self.assertEqual(monitor.poll(1), {10: ("claude", "wait"), 11: ("codex", "work")})
            self.assertFalse(os.path.exists(f"{state}/77.json"))
            # Claude sends nothing on Esc: a stale "work" gives way to idle CPU...
            clock[0] += 100
            self.assertEqual(monitor.poll(2)[11], ("codex", "idle"))
            # ...but not while the process is still busy.
            self.fake_proc(root, 11, "codex", 100)
            self.assertEqual(monitor.poll(3)[11], ("codex", "work"))
            hook(10, "claude", "Stop")
            hook(11, "codex", "Interrupt")
            self.assertEqual(monitor.poll(4), {10: ("claude", "idle"), 11: ("codex", "idle")})
            hook(10, "claude", "Notification", notification_type="permission_prompt")
            self.assertEqual(monitor.poll(5)[10], ("claude", "wait"))
            hook(10, "claude", "SessionEnd")
            self.assertEqual(os.listdir(state), [f"11.json"])
            with open(f"{state}/11.json", "w") as file:
                file.write("{broken")
            self.assertEqual(monitor.poll(6)[11], ("codex", "idle"))

    def test_hook_finds_its_session_process(self):
        with tempfile.TemporaryDirectory() as root:
            # claude (10) -> bash (30): the hook belongs to that claude window.
            self.fake_proc(root, 5, "fish", 0, parent=1)
            self.fake_proc(root, 10, "claude", 0, parent=5)
            self.fake_proc(root, 30, "bash", 0, parent=10)
            self.assertEqual(agent_hook.session_pid("claude", root, start=30), 10)
            self.assertEqual(agent_hook.session_pid("codex", root, start=30), 0)
            # codex window (11) -> shared app-server (20) -> sh (31): no single window.
            self.fake_proc(root, 11, "codex", 0, parent=5)
            self.fake_proc(root, 20, "codex", 0, ("app-server",), parent=11)
            self.fake_proc(root, 31, "sh", 0, parent=20)
            self.assertEqual(agent_hook.session_pid("codex", root, start=31), 0)
            self.assertEqual(agent_hook.state_file("codex", {"session_id": "ab-1/.."}, 0), "codex-ab-1.json")
            self.assertIsNone(agent_hook.state_file("codex", {}, 0))
            # opencode (12) -> python3 (32): its plugin runs the hook as a child.
            self.fake_proc(root, 12, "opencode", 0, parent=5)
            self.fake_proc(root, 32, "python3", 0, parent=12)
            self.assertEqual(agent_hook.session_pid("opencode", root, start=32), 12)

    def test_kiro_and_other_agents_get_their_own_animals(self):
        with tempfile.TemporaryDirectory() as root:
            state = f"{root}/state"
            monitor = AgentMonitor(root, state_dir=state, clock=lambda: 1000.0)
            monitor.ticks_per_second = 100
            # kiro-cli (12) -> kiro-cli-chat (13) -> sh (33): one session, the outer one.
            self.fake_proc(root, 12, "kiro-cli", 0)
            self.fake_proc(root, 13, "kiro-cli-chat", 0, parent=12)
            self.fake_proc(root, 33, "sh", 0, parent=13)
            for pid, comm in ((20, "aider"), (21, "goose"), (22, "crush"), (23, "amp")):
                self.fake_proc(root, pid, comm, 0)
            self.assertEqual(agent_hook.session_pid("kiro-cli", root, start=33), 12)
            # Its TUI runs on bun, which starts one more kiro-cli-chat: same session.
            self.fake_proc(root, 14, "bun", 0, parent=13)
            self.fake_proc(root, 15, "kiro-cli-chat", 0, ("acp",), parent=14)
            self.fake_proc(root, 35, "sh", 0, parent=15)
            self.assertEqual(agent_hook.session_pid("kiro-cli", root, start=35), 12)
            self.assertEqual(monitor.poll(0), {12: ("kiro-cli", "idle"), 20: ("aider", "idle"),
                                               21: ("goose", "idle"), 22: ("crush", "idle"),
                                               23: ("amp", "idle")})
            # Kiro's hooks speak camelCase.
            agent_hook.record("kiro-cli", {"hook_event_name": "userPromptSubmit"}, 12, state, now=1000.0)
            self.assertEqual(monitor.poll(1)[12], ("kiro-cli", "work"))
            agent_hook.record("kiro-cli", {"hook_event_name": "stop"}, 12, state, now=1000.0)
            self.assertEqual(monitor.poll(2)[12], ("kiro-cli", "idle"))
            world = World(120, 40, seed=4)
            world.sync_agents(monitor.poll(3))
            self.assertEqual(sorted((a.name, a.species) for a in world.animals if a.agent), [
                ("Aider", "tikus"), ("Amp", "anjing"), ("Crush", "kucing"),
                ("Goose", "bebek"), ("Kiro", "tikus")])

    def test_pi_and_strix_get_their_own_animals(self):
        with tempfile.TemporaryDirectory() as root:
            state = f"{root}/state"
            monitor = AgentMonitor(root, state_dir=state, clock=lambda: 1000.0)
            monitor.ticks_per_second = 100
            # pi runs on node but renames itself; its extension runs the hook as a child.
            self.fake_proc(root, 12, "pi", 0, ("/usr/bin/node", "/x/pi-coding-agent/dist/cli.js"))
            self.fake_proc(root, 32, "python3", 0, parent=12)
            self.fake_proc(root, 13, "strix", 0)
            self.fake_proc(root, 14, "strix", 0, parent=13)  # a child of its own: same session
            self.assertEqual(agent_hook.session_pid("pi", root, start=32), 12)
            agent_hook.record("pi", {"hook_event_name": "UserPromptSubmit"}, 12, state, now=1000.0)
            self.assertEqual(monitor.poll(0), {12: ("pi", "work"), 13: ("strix", "idle")})
            world = World(100, 30, seed=5)
            world.sync_agents(monitor.poll(1))
            self.assertEqual(sorted((a.name, a.species) for a in world.animals if a.agent),
                             [("Pi", "bebek"), ("Strix", "anjing")])

    @unittest.skipUnless(shutil.which("node"), "needs node to load the pi extension")
    def test_pi_extension_maps_agent_events(self):
        script = """
            const handlers = {}
            const { default: extension } = await import(process.argv[1])
            extension({ on: (name, handler) => { handlers[name] = handler } })
            console.log(JSON.stringify(Object.keys(handlers).sort()))
        """
        extension = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pi_extension.ts")
        result = subprocess.run(["node", "--input-type=module", "-e", script, extension],
                                capture_output=True, text=True)
        if result.returncode and "Unknown file extension" in result.stderr:
            self.skipTest("this node cannot strip TypeScript types")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         ["agent_end", "agent_start", "session_shutdown", "session_start"])

    def test_state_lines_describe_agents_for_other_views(self):
        with tempfile.TemporaryDirectory() as root:
            agents = AgentMonitor(root, state_dir=f"{root}/state", clock=lambda: 1000.0)
            agents.ticks_per_second = 100
            state = park_state.State(root, agents=agents)
            self.fake_proc(root, 10, "claude", 0)
            self.fake_proc(root, 11, "claude", 0)
            self.fake_proc(root, 12, "codex", 0)
            agent_hook.record("claude", {"hook_event_name": "SubagentStart", "agent_id": "a1",
                                         "agent_type": "Explore"}, 11, f"{root}/state", now=1000.0)
            snapshot = json.loads(json.dumps(state.poll(0)))
            self.assertEqual([(a["id"], a["name"], a["species"], a["color"], a["status"])
                              for a in snapshot["agents"]], [
                ("10", "Claude", "kucing", "#ff8700", "idle"),
                ("11", "Claude 2", "kucing", "#ff8700", "work"),
                ("12", "Codex", "anjing", "#00afff", "idle")])
            self.assertEqual(snapshot["agents"][1]["subagents"], [{"id": "a1", "type": "Explore"}])
            # Names stick to their session: when the first Claude leaves, the second keeps its name.
            for name in ("comm", "cmdline", "stat"):
                os.remove(f"{root}/10/{name}")
            self.assertEqual([a["name"] for a in state.poll(1)["agents"]], ["Claude 2", "Codex"])
            self.assertEqual(park_state.xterm_hex(208), "#ff8700")
            self.assertEqual(park_state.xterm_hex(244), "#808080")

    def test_opencode_gets_its_own_cat(self):
        with tempfile.TemporaryDirectory() as root:
            state = f"{root}/state"
            monitor = AgentMonitor(root, state_dir=state, clock=lambda: 1000.0)
            monitor.ticks_per_second = 100
            self.fake_proc(root, 12, "opencode", 0)
            self.assertEqual(monitor.poll(0), {12: ("opencode", "idle")})
            hook = lambda event, **extra: agent_hook.record(
                "opencode", {"hook_event_name": event, **extra}, 12, state, now=1000.0)
            hook("SubagentStart", agent_id="ses_x1", agent_type="explore")
            hook("PermissionRequest")
            self.assertEqual(monitor.poll(1), {12: ("opencode", "wait")})
            self.assertEqual(monitor.subagents, {12: [("sesx1", "explore")]})
            world = World(100, 30, seed=3)
            world.sync_agents(monitor.poll(2), monitor.subagents)
            self.assertEqual([(a.name, a.agent_kind) for a in world.animals if a.agent],
                             [("OpenCode", "opencode")])
            self.assertEqual(world.animals[-1].species, "kelinci")

    @unittest.skipUnless(shutil.which("node"), "needs node to load the OpenCode plugin")
    def test_opencode_plugin_translates_session_events(self):
        script = """
            const { createTracker, subagentType } = await import(process.argv[1])
            const sent = [], on = createTracker((event) => sent.push(event))
            const status = (sessionID, type) => on({ event: { type: "session.status", properties: { sessionID, status: { type } } } })
            await status("main", "busy")
            await status("main", "busy")  // no change, no hook
            await on({ event: { type: "session.created", properties: { info: { id: "kid", parentID: "main", title: "Look (@explore subagent)" } } } })
            await status("kid", "busy")
            await on({ event: { type: "permission.asked", properties: { sessionID: "kid" } } })
            await on({ event: { type: "permission.replied", properties: { sessionID: "kid" } } })
            await status("kid", "idle")
            await status("main", "idle")
            await on({ event: { type: "session.idle", properties: { sessionID: "main" } } })
            console.log(JSON.stringify({ sent, plain: subagentType("Chat") }))
        """
        plugin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opencode_plugin.js")
        result = subprocess.run(["node", "--input-type=module", "-e", script, plugin],
                                capture_output=True, text=True, check=True)
        output = json.loads(result.stdout)
        events = [(e["hook_event_name"], e.get("session_id"), e.get("agent_id"), e.get("agent_type"))
                  for e in output["sent"]]
        self.assertEqual(events, [
            ("UserPromptSubmit", "main", None, None),
            ("SubagentStart", "main", "kid", "explore"),
            ("PermissionRequest", "main", None, None),
            ("UserPromptSubmit", "main", None, None),
            ("SubagentStop", "main", "kid", "explore"),
            ("Stop", "main", None, None),
        ])
        self.assertEqual(output["plain"], "subagent")

    @unittest.skipUnless(shutil.which("node"), "needs node to load the OpenCode plugin")
    def test_opencode_2_plugin_reports_each_session(self):
        script = """
            const { createTracker } = await import(process.argv[1])
            const sent = [], on = createTracker((event) => sent.push(event))
            const ev = (type, data) => on({ event: { type, data } })
            await ev("session.execution.started", { sessionID: "a" })
            await ev("session.execution.started", { sessionID: "b" })
            await ev("session.created", { sessionID: "kid", parentID: "a", agent: "explore" })
            await ev("session.execution.started", { sessionID: "kid" })
            await ev("form.created", { form: { id: "f1", sessionID: "kid" } })
            await ev("form.replied", { id: "f1", sessionID: "kid" })
            await ev("session.execution.succeeded", { sessionID: "kid" })
            await ev("permission.asked", { id: "per_1", sessionID: "b" })
            await ev("permission.replied", { sessionID: "b", requestID: "per_1", reply: "reject" })
            await ev("session.execution.interrupted", { sessionID: "b", reason: "user" })
            await ev("permission.asked", { id: "per_2", sessionID: "a" })
            await ev("session.execution.failed", { sessionID: "a" })  // never left waiting
            console.log(JSON.stringify(sent))
        """
        plugin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opencode_plugin.js")
        result = subprocess.run(["node", "--input-type=module", "-e", script, plugin],
                                capture_output=True, text=True, check=True)
        events = [(e["hook_event_name"], e.get("session_id"), e.get("agent_type"))
                  for e in json.loads(result.stdout)]
        self.assertEqual(events, [
            ("UserPromptSubmit", "a", None),
            ("UserPromptSubmit", "b", None),
            ("SubagentStart", "a", "explore"),
            ("PermissionRequest", "a", None),
            ("UserPromptSubmit", "a", None),
            ("SubagentStop", "a", "explore"),
            ("PermissionRequest", "b", None),
            ("UserPromptSubmit", "b", None),
            ("Stop", "b", None),
            ("PermissionRequest", "a", None),
            ("Stop", "a", None),
        ])

    def test_opencode_serve_is_a_shared_helper(self):
        with tempfile.TemporaryDirectory() as root:
            state = f"{root}/state"
            monitor = AgentMonitor(root, state_dir=state, clock=lambda: 1000.0)
            monitor.ticks_per_second = 100
            # The background service alone is no session...
            self.fake_proc(root, 40, "opencode", 0, ("serve", "--service"))
            self.fake_proc(root, 41, "python3", 0, parent=40)
            self.assertEqual(monitor.poll(0), {})
            self.assertEqual(agent_hook.session_pid("opencode", root, start=41), 0)
            # ...but its per-session states fill the open windows.
            self.fake_proc(root, 12, "opencode", 0)
            agent_hook.record("opencode", {"hook_event_name": "UserPromptSubmit", "session_id": "ses_a"},
                              0, state, now=1000.0)
            self.assertEqual(monitor.poll(1), {"opencode:sesa": ("opencode", "work")})

    def test_shared_codex_sessions_fill_open_windows(self):
        with tempfile.TemporaryDirectory() as root:
            state = f"{root}/state"
            monitor = AgentMonitor(root, state_dir=state)
            self.fake_proc(root, 10, "codex", 0)
            self.fake_proc(root, 11, "codex", 0)
            self.fake_proc(root, 20, "codex", 0, ("app-server",))
            hook = lambda session, event, now: agent_hook.record(
                "codex", {"hook_event_name": event, "session_id": session}, 0, state, now=now)
            hook("a", "PermissionRequest", 2)
            self.assertEqual(monitor.poll(0), {"codex:a": ("codex", "wait"), 11: ("codex", "idle")})
            hook("old", "Stop", 1)
            hook("b", "UserPromptSubmit", 3)
            self.assertEqual(monitor.poll(1), {"codex:a": ("codex", "wait"), "codex:b": ("codex", "work")})
            hook("a", "SessionEnd", 4)
            self.assertEqual(monitor.poll(2), {"codex:b": ("codex", "work"), "codex:old": ("codex", "idle")})
            for pid in (10, 11):
                os.remove(f"{root}/{pid}/comm")
            self.assertEqual(monitor.poll(3), {})
            self.assertEqual(os.listdir(state), [])

    def test_subagents_get_their_own_state_files(self):
        with tempfile.TemporaryDirectory() as root:
            clock = [5000.0]
            state = f"{root}/state"
            monitor = AgentMonitor(root, state_dir=state, clock=lambda: clock[0])
            self.fake_proc(root, 10, "claude", 0)
            self.fake_proc(root, 11, "codex", 0)
            self.fake_proc(root, 20, "codex", 0, ("app-server",))
            hook = lambda kind, pid, event, **extra: agent_hook.record(
                kind, {"hook_event_name": event, "session_id": "s1", **extra}, pid, state, now=clock[0])
            hook("claude", 10, "SubagentStart", agent_id="a1", agent_type="Explore")
            clock[0] += 1
            hook("claude", 10, "SubagentStart", agent_id="a2", agent_type="Plan")
            hook("codex", 0, "SubagentStart", agent_id="c1", agent_type=None)
            hook("claude", 10, "SubagentStart")  # no agent id: parent state only
            sessions = monitor.poll(0)
            self.assertEqual(sessions[10], ("claude", "work"))
            self.assertEqual(monitor.subagents, {
                10: [("a1", "Explore"), ("a2", "Plan")], "codex:s1": [("c1", "subagent")]})
            hook("claude", 10, "SubagentStop", agent_id="a1")
            monitor.poll(1)
            self.assertEqual(monitor.subagents[10], [("a2", "Plan")])
            clock[0] += 3600  # a stop event that never came
            monitor.poll(2)
            self.assertEqual(monitor.subagents, {})
            self.assertEqual(sorted(os.listdir(state)), ["10.json", "codex-s1.json"])
            hook("codex", 0, "SubagentStart", agent_id="c2", agent_type="worker")
            hook("codex", 0, "SessionEnd")
            self.assertEqual(os.listdir(state), ["10.json"])

    def test_kittens_follow_their_cat_and_leave_when_done(self):
        world = World(100, 30, seed=9)
        world.arrival = 1000
        subagents = {7: [(f"a{i}", "general-purpose-agent") for i in range(6)],
                     99: [("x", "Orphan")]}
        world.sync_agents({7: ("claude", "work")}, subagents)
        self.assertFalse(any(a.sub for a in world.animals))  # cat still landing
        land(world)
        world.sync_agents({7: ("claude", "work")}, subagents)
        land(world)
        cat = next(a for a in world.animals if a.agent and not a.sub)
        kittens = [a for a in world.animals if a.sub]
        self.assertEqual(len(kittens), 4)
        self.assertEqual({k.name for k in kittens}, {"general-purpo~"})
        self.assertIn("memanggil", world.notice)
        for _ in range(200):
            world.update(0.05, 8)
            for kitten in kittens:
                self.assertEqual(kitten.state, "follow")
                self.assertLess(abs(kitten.x - cat.x), 30)
        self.assertEqual(cat.state, "work")
        world.sync_agents({7: ("claude", "idle")}, {7: [("a1", "general-purpose-agent")]})
        gone = [k for k in kittens if k.sub != "a1"]
        for kitten in gone:
            self.assertEqual((kitten.agent, kitten.visitor, kitten.state), (0, True, "pass"))
        self.assertIn("selesai bantu Claude", world.notice)
        for _ in range(600):
            world.update(0.05, 8)
        for kitten in gone:
            self.assertNotIn(kitten, world.animals)
        world.sync_agents({}, {})
        self.assertFalse(any(a.agent for a in world.animals))
        screen = Screen(30, 100)
        render(screen, world, 8, False, dict.fromkeys(SPRITES, 0), [])

    def test_kittens_render_with_their_role(self):
        world = World(80, 24, seed=7)
        world.sync_agents({7: ("claude", "work")})
        land(world)
        world.sync_agents({7: ("claude", "work")}, {7: [("a1", "Explore")]})
        world.start_raid()
        world.raid.age = 4
        world.update_raid(0)
        screen = Screen(24, 80)
        render(screen, world, 8, False, dict.fromkeys(SPRITES, 0), [])
        world.raid = None
        world.update(0.05, 8)
        screen = Screen(24, 80)
        render(screen, world, 8, False, dict.fromkeys(SPRITES, 0), [])
        self.assertIn("[Explore]", "\n".join("".join(row) for row in screen.rows))

    def test_every_entrance_plays_then_lands(self):
        for entrance, (duration, message) in ENTRANCES.items():
            with self.subTest(entrance=entrance):
                world = World(80, 24, seed=1)
                world.arrival = 1000
                world.rng.choice = lambda options, pick=entrance: (
                    pick if pick in options else options[0])
                world.sync_agents({7: ("claude", "work")}, {7: [("a1", "Explore")]})
                cat = next(a for a in world.animals if a.agent)
                self.assertEqual((cat.entrance, cat.state), (entrance, "arrive"))
                self.assertEqual(world.notice, message.format(name="Claude"))
                frames = set()
                while cat.entry:
                    screen = Screen(24, 80)
                    render(screen, world, 8, False, dict.fromkeys(SPRITES, 0), [])
                    frames.add("\n".join("".join(row) for row in screen.rows))
                    x = cat.x
                    world.update(0.1, 8)
                    self.assertEqual(cat.x, x)  # no wandering mid-landing
                self.assertGreater(len(frames), 5)
                world.update(0.05, 8)
                self.assertEqual(cat.state, "work")
                world.sync_agents({7: ("claude", "work")}, {7: [("a1", "Explore")]})
                kitten = next(a for a in world.animals if a.sub)
                self.assertEqual((kitten.entrance, kitten.state), ("pop", "arrive"))
                for _ in range(20):
                    screen = Screen(24, 80)
                    render(screen, world, 8, False, dict.fromkeys(SPRITES, 0), [])
                    world.update(0.05, 8)
                self.assertEqual(kitten.state, "follow")

    def test_monster_interrupts_a_landing(self):
        world = World(80, 24, seed=2)
        world.sync_agents({7: ("claude", "idle")})
        cat = next(a for a in world.animals if a.agent)
        world.start_raid()
        self.assertEqual((cat.entry, cat.state), (0, "rally"))

    def test_only_new_heavy_processes_become_monsters(self):
        with tempfile.TemporaryDirectory() as root:
            watcher = ProcessWatcher(root)
            watcher.ticks_per_second, watcher.page = 100, 4096
            self.fake_proc(root, 10, "firefox", 0)  # was already running: never a monster
            self.fake_proc(root, 11, "sh", 0)
            self.assertEqual(watcher.poll(0), [])
            self.fake_proc(root, 11, "rustc", 0, rss=(2 << 30) // 4096)  # sh exec()'d rustc
            self.assertEqual(watcher.poll(0.5), [(11, "rustc", "RAM 2.0 GB")])
            shutil.rmtree(f"{root}/11")
            self.fake_proc(root, 20, "cargo", 0)
            self.fake_proc(root, 21, "sleep", 0)
            self.fake_proc(root, 22, "claude", 0)
            self.fake_proc(root, 23, "node", 0, rss=(3 << 30) // 4096)
            self.assertEqual(watcher.poll(1), [(23, "node", "RAM 3.0 GB")])
            for pid, ticks in ((10, 900), (20, 180), (21, 1), (22, 300)):
                self.fake_proc(root, pid, ("firefox", "cargo", "sleep", "claude")[pid % 10], ticks)
            # One second of history is too short to judge CPU.
            self.assertEqual(watcher.poll(2), [(23, "node", "RAM 3.0 GB")])
            self.fake_proc(root, 20, "cargo", 360)
            self.assertEqual(watcher.poll(3), [(20, "cargo", "CPU 180%"), (23, "node", "RAM 3.0 GB")])
            watcher.fought.update({20, 23})
            self.assertEqual(watcher.poll(4), [])
            shutil.rmtree(f"{root}/20")  # cargo finished
            watcher.poll(5)
            self.assertNotIn(20, watcher.fought)
            self.assertNotIn(20, watcher.history)
        self.assertEqual(ProcessWatcher("/no/such/proc").poll(0), [])

    def test_router_box_shows_profile_upstream_and_its_cat(self):
        with tempfile.TemporaryDirectory() as root:
            routers = RouterMonitor(root)
            routers.ticks_per_second = 100
            with open(f"{root}/uptime", "w") as file:
                file.write("750.00 100.00\n")
            os.makedirs(f"{root}/net")
            with open(f"{root}/net/tcp", "w") as file:
                file.write("  sl  local_address rem_address   st\n"
                           "   0: 0100007F:A0B2 0100007F:D431 01\n"  # router side, established
                           "   1: 0100007F:D431 0100007F:A0B2 01\n"  # claude side
                           "   2: 0100007F:A0B2 00000000:0000 0A\n")  # listening
            self.fake_proc(root, 30, "bash", 0, ("/home/me/.local/bin/ccx", "deepseek", "-c"))
            self.fake_proc(root, 31, "ccx-router", 5, ("--port", "41138", "--upstream-url",
                                                       "https://user:secret@api.deepseek.com/v1"), parent=30)
            self.fake_proc(root, 32, "claude", 0, parent=30)
            os.makedirs(f"{root}/30/task/30")
            with open(f"{root}/30/task/30/children", "w") as file:
                file.write("31 32 ")
            [router] = routers.poll()
            self.assertEqual((router.profile, router.port, router.host, router.client, router.connections),
                             ("deepseek", 41138, "api.deepseek.com", 32, 1))
            self.assertAlmostEqual(router.age, 750)
            self.assertFalse(router.busy)  # nothing to compare with yet
            self.fake_proc(root, 31, "ccx-router", 9, ("--port", "41138"), parent=30)
            self.assertTrue(routers.poll()[0].busy)
            self.assertFalse(routers.poll()[0].busy)
            # A router never turns into a monster.
            watcher = ProcessWatcher(root)
            watcher.ticks_per_second = 100
            watcher.known = {}
            self.fake_proc(root, 31, "ccx-router", 9, parent=30, rss=(2 << 30) // 4096)
            self.assertEqual(watcher.poll(0), [])

            world = World(100, 30, seed=1)
            world.sync_agents({32: ("claude", "work")})
            land(world)
            screen = Screen(30, 100)
            render(screen, world, 8, False, {**dict.fromkeys(SPRITES, 0), "enemy": 0}, [], None, [router])
            text = "\n".join("".join(row) for row in screen.rows)
            self.assertIn("+- router ccx (1)", text)
            self.assertIn("deepseek :41138", text)
            self.assertIn("-> api.deepseek.com", text)
            self.assertNotIn("secret", text)
            self.assertIn("kirim", text)  # its cat is working
            self.assertIn("[Claude]", text.splitlines()[5])
        self.assertEqual(RouterMonitor("/no/such/proc").poll(), [])

    def test_hook_script_never_fails(self):
        for argv, stdin in ((["agent_hook.py"], "{}"), (["agent_hook.py", "claude"], "not json")):
            with mock.patch("sys.argv", argv), mock.patch("sys.stdin", io.StringIO(stdin)):
                self.assertEqual(agent_hook.main(), 0)

    def test_waiting_cat_asks_for_attention(self):
        world = World(80, 24, seed=7)
        world.sync_agents({7: ("claude", "work")})
        land(world)
        world.sync_agents({7: ("claude", "wait")})
        self.assertIn("butuh persetujuan", world.notice)
        world.update(0.05, 8)
        cat = next(a for a in world.animals if a.agent)
        self.assertEqual(cat.state, "wait")
        screen = Screen(24, 80)
        render(screen, world, 8, False, dict.fromkeys(SPRITES, 0), [])
        self.assertIn("[Claude] ", "\n".join("".join(row) for row in screen.rows))

    def test_agent_names_render_above_their_cats(self):
        world = World(80, 24, seed=7)
        world.sync_agents({7: ("claude", "work"), 9: ("codex", "idle")})
        land(world)
        world.update(0.05, 8)
        screen = Screen(24, 80)
        render(screen, world, 8, False, dict.fromkeys(SPRITES, 0), [])
        text = "\n".join("".join(row) for row in screen.rows)
        self.assertTrue(any(f"[Claude] {chatter}" in text for chatter in WORK_CHATTER), text)
        self.assertIn("[Codex]", text)
        self.assertIn("[ MARKAS AI: 1 kerja ]", text)

    def test_working_cats_sit_at_their_own_computers(self):
        world = World(100, 28, seed=4)
        world.arrival = 1000
        sessions = {pid: ("claude", "work") for pid in range(1, 6)}
        world.sync_agents(sessions)
        land(world)
        desks = world.desks()
        self.assertEqual(len(desks), 3)
        for _ in range(100):
            world.update(0.05, 8)
        cats = {a.agent: a for a in world.animals if a.agent}
        seated = [cat for cat in cats.values() if cat.seated]
        self.assertEqual(sorted(cat.desk for cat in seated), [0, 1, 2])
        for cat in seated:
            self.assertEqual((cat.x, cat.y, cat.vx), (*desks[cat.desk], 1))  # facing the screen
        # No desk left: the other two still work, running around the office.
        spare = [cat for cat in cats.values() if not cat.seated]
        self.assertEqual([(cat.state, cat.desk) for cat in spare], [("work", -1)] * 2)
        screen = Screen(28, 100)
        render(screen, world, 8, False, dict.fromkeys(SPRITES, 0), [])
        text = "\n".join("".join(row) for row in screen.rows)
        self.assertIn("[ MARKAS AI: 5 kerja ]", text)
        # Clocking out frees the desk for a colleague.
        leaver = next(cat for cat in seated if cat.desk == 0)
        sessions[leaver.agent] = ("claude", "idle")
        world.sync_agents(sessions)
        for _ in range(100):
            world.update(0.05, 8)
        self.assertEqual((leaver.desk, leaver.seated), (-1, False))
        self.assertLess(leaver.x, world.office)
        self.assertTrue(any(cat.desk == 0 and cat.seated for cat in spare))

    def test_without_wild_animals_only_agent_cats_live_here(self):
        world = World(100, 30, seed=2, wild=False)
        screen = Screen(30, 100)
        render(screen, world, 8, False, dict.fromkeys(SPRITES, 0), [])
        text = "\n".join("".join(row) for row in screen.rows)
        self.assertIn("Taman sepi", text)
        self.assertNotIn("n hewan", text)
        for _ in range(400):  # 20 s: plenty of time for arrivals
            world.update(0.05, 8)
        self.assertEqual(world.animals, [])
        world.sync_agents({7: ("claude", "work")}, {7: [("a1", "Explore")]})
        land(world)
        world.sync_agents({7: ("claude", "work")}, {7: [("a1", "Explore")]})
        for _ in range(100):
            world.update(0.05, 8)
        self.assertEqual(sorted(a.species for a in world.animals), ["anak kucing", "kucing"])
        # Every agent has its own animal, and its subagents are that animal's babies.
        sessions = {7: ("claude", "work"), 8: ("codex", "work"), 9: ("opencode", "idle")}
        subagents = {8: [("b1", "explore")], 9: [("c1", "general")]}
        world.sync_agents(sessions, subagents)
        land(world)
        world.sync_agents(sessions, subagents)
        self.assertEqual(sorted((a.name, a.species) for a in world.animals), [
            ("Claude", "kucing"), ("Codex", "anjing"), ("Explore", "anak kucing"),
            ("OpenCode", "kelinci"), ("explore", "anak anjing"), ("general", "anak kelinci")])
        render(screen, world, 8, False, dict.fromkeys(SPRITES, 0), [])
        self.assertTrue(world.threat("cargo", "CPU 100%"))  # monsters still come

    def test_office_only_opens_on_wide_screens_with_agents(self):
        world = World(100, 30, seed=3)
        self.assertIsNone(world.office)  # no agents: the whole ground is the park
        world.sync_agents({7: ("claude", "wait")})
        self.assertEqual(world.office, 100 - 33)
        land(world)
        world.update(0.05, 8)
        self.assertEqual(world.animals[-1].state, "wait")
        narrow = World(60, 30, seed=3)
        narrow.sync_agents({7: ("claude", "work")})
        self.assertIsNone(narrow.office)
        land(narrow)
        for _ in range(20):
            narrow.update(0.05, 8)
        self.assertEqual(narrow.animals[-1].state, "work")


class SystemPanelTests(unittest.TestCase):
    def fake_proc(self, root, busy, idle, available):
        with open(os.path.join(root, "stat"), "w") as file:
            file.write(f"cpu  {busy} 0 0 {idle} 0 0 0 0 0 0\ncpu0 1 2 3 4\n")
        with open(os.path.join(root, "meminfo"), "w") as file:
            file.write(f"MemTotal: 1000 kB\nMemFree: 100 kB\nMemAvailable: {available} kB\n"
                       "SwapTotal: 0 kB\nSwapFree: 0 kB\n")
        with open(os.path.join(root, "loadavg"), "w") as file:
            file.write("1.50 1.00 0.50 1/100 42\n")

    def panel(self, system):
        world = World(100, 30, seed=1)
        screen = Screen(30, 100)
        render(screen, world, 8, False, {**dict.fromkeys(SPRITES, 0), "enemy": 0}, [], system)
        return "\n".join("".join(row) for row in screen.rows)

    def test_cpu_ram_and_a_calm_cat(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        system = SystemMonitor(root)
        self.fake_proc(root, 100, 900, 600)
        self.assertTrue(system.poll())
        self.assertIsNone(system.cpu)  # needs two samples
        self.assertNotIn("+- sistem", self.panel(system))
        self.fake_proc(root, 120, 980, 600)  # 20 of 100 jiffies busy
        system.poll()
        self.assertAlmostEqual(system.cpu, 0.2)
        self.assertEqual((system.ram, system.swap, system.load), ((400 * 1024, 1000 * 1024), (0, 0), 1.5))
        self.assertEqual(system.mood, "calm")
        text = self.panel(system)
        for part in ("+- sistem", "CPU [", " 20%", "RAM [", " 40%", "load 1.50", "santai~"):
            self.assertIn(part, text)
        self.assertNotIn("SWP", text)  # no swap configured

    def test_cat_warns_when_cpu_or_ram_climbs(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        system = SystemMonitor(root)
        self.fake_proc(root, 0, 0, 600)
        system.poll()
        self.fake_proc(root, 70, 30, 600)
        system.poll()
        self.assertEqual(system.mood, "busy")
        self.assertIn("CPU naik", self.panel(system))
        self.fake_proc(root, 165, 35, 600)
        system.poll()
        self.assertEqual(system.mood, "alarm")
        text = self.panel(system)
        self.assertTrue("AWAS! CPU 95%!" in text or "panas panas!" in text, text)
        self.fake_proc(root, 175, 125, 50)  # quiet CPU, RAM 95% used
        system.poll()
        self.assertEqual(system.mood, "alarm")
        self.assertTrue("RAM 95%" in self.panel(system) or "RAM hampir" in self.panel(system))

    def test_no_proc_or_small_screen_hides_the_panel(self):
        system = SystemMonitor("/nonexistent")
        self.assertFalse(system.poll())
        self.assertNotIn("+- sistem", self.panel(system))
        system.cpu = 0.5
        screen = Screen(16, 60)
        render(screen, World(60, 16, seed=1), 8, False, dict.fromkeys(SPRITES, 0), [], system)
        self.assertNotIn("+- sistem", "\n".join("".join(row) for row in screen.rows))


if __name__ == "__main__":
    unittest.main()
