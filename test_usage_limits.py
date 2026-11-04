from datetime import datetime, timezone
from types import SimpleNamespace
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from screensaver import LIMITS_WIDTH, SPEECH_ROOM, SPRITES, World, render
from usage_limits import STALE_AFTER, UsageMonitor, mood_face, until
from test_screensaver import Screen, land

NOW = 1_800_000_000.0


def make_db(path, claude=True, minimax=True, codex=True, kimi=True, windows=False):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE snapshots (ts INTEGER PRIMARY KEY, five_hour REAL, seven_day REAL, raw_json TEXT)")
    db.execute("CREATE TABLE provider_snapshots (provider TEXT, ts INTEGER, pct REAL, value REAL)")
    db.execute("CREATE TABLE codex_snapshots (account_id TEXT, ts INTEGER, primary_pct REAL, "
               "secondary_pct REAL, credits_balance REAL, raw_json TEXT)")
    if claude:
        raw = json.dumps({"five_hour": {"resets_at": datetime.fromtimestamp(NOW + 3900, timezone.utc).isoformat()},
                          "seven_day": {"resets_at": "not a date"}})
        db.execute("INSERT INTO snapshots VALUES (?, 1, 2, '{}')", (int((NOW - 9999) * 1000),))
        db.execute("INSERT INTO snapshots VALUES (?, 4.0, 12.4, ?)", (int((NOW - 60) * 1000), raw))
    if minimax:
        db.execute("INSERT INTO provider_snapshots VALUES ('minimax', ?, 0.0, NULL)", (int((NOW - STALE_AFTER - 5) * 1000),))
        db.execute("INSERT INTO provider_snapshots VALUES ('minimax', ?, NULL, NULL)", (int(NOW * 1000),))
    if codex:
        raw = json.dumps({"email": "someone@example.com", "rate_limit": {
            "primary_window": {"limit_window_seconds": 18000, "reset_at": NOW + 3900},
            "secondary_window": {"limit_window_seconds": 604800, "reset_at": NOW + 2 * 86400 + 20 * 3600 + 60}}})
        db.execute("INSERT INTO codex_snapshots VALUES ('default', ?, 90, 99, NULL, '{}')", (int((NOW - 9999) * 1000),))
        db.execute("INSERT INTO codex_snapshots VALUES ('default', ?, 5.0, 46.0, NULL, ?)", (int((NOW - 30) * 1000), raw))
    if kimi:
        db.execute("INSERT INTO provider_snapshots VALUES ('kimi', ?, 33.0, NULL)", (int((NOW - 30) * 1000),))
    if windows:  # what a newer AI Limit Monitor also stores: every window, with its reset
        db.execute("CREATE TABLE provider_windows (provider TEXT, name TEXT, ts INTEGER, pct REAL, "
                   "resets_at INTEGER, PRIMARY KEY (provider, name))")
        recent = int((NOW - 10) * 1000)
        db.executemany("INSERT INTO provider_windows VALUES (?, ?, ?, ?, ?)", [
            ("minimax", "5h", recent, 18.0, NOW + 4000), ("minimax", "1d", recent, 0.0, NOW + 40000),
            ("minimax", "7d", recent, 10.0, NOW + 500000),
            ("kimi", "5h", recent, 33.0, NOW + 9000), ("kimi", "7d", recent, 61.0, NOW + 300000),
            ("kimi", "1mo", recent, 7.5, None)])
    db.commit()
    db.close()


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "history.db")
        self.addCleanup(self.dir.cleanup)

    def test_reads_latest_claude_and_minimax(self):
        make_db(self.path)
        limits = UsageMonitor(self.path, clock=lambda: NOW).poll()
        self.assertEqual([limit["provider"] for limit in limits], ["claude", "codex", "minimax", "kimi"])
        claude, codex, minimax, kimi = limits
        self.assertEqual([w["pct"] for w in claude["windows"]], [4.0, 12.4])  # newest row only
        self.assertFalse(claude["stale"])
        self.assertIsNotNone(claude["windows"][0]["resets_at"])
        self.assertIsNone(claude["windows"][1]["resets_at"])  # bad date is tolerated
        # Codex: newest row only, windows named from their length, resets from the raw reply.
        self.assertEqual([(w["name"], w["pct"]) for w in codex["windows"]], [("5h", 5.0), ("7d", 46.0)])
        self.assertEqual([w["resets_at"] for w in codex["windows"]], [NOW + 3900, NOW + 2 * 86400 + 20 * 3600 + 60])
        self.assertNotIn("someone@example.com", json.dumps(codex))  # account details stay out
        # Kimi only records its 5h window.
        self.assertEqual([(w["name"], w["pct"], w["resets_at"]) for w in kimi["windows"]], [("5h", 33.0, None)])
        self.assertTrue(minimax["stale"])  # the newer row has no percentage, so the old one stays

    def test_missing_or_foreign_database_shows_nothing(self):
        self.assertEqual(UsageMonitor(os.path.join(self.dir.name, "none.db")).poll(), [])
        sqlite3.connect(self.path).close()  # a database without our tables
        self.assertEqual(UsageMonitor(self.path).poll(), [])
        with open(self.path, "w") as handle:
            handle.write("not sqlite")
        self.assertEqual(UsageMonitor(self.path).poll(), [])

    def test_provider_without_rows_is_skipped_and_reads_are_throttled(self):
        make_db(self.path, minimax=False, codex=False, kimi=False)
        times = iter([NOW, NOW + 5, NOW + 100])
        monitor = UsageMonitor(self.path, clock=lambda: next(times))
        first = monitor.poll()
        self.assertEqual([limit["provider"] for limit in first], ["claude"])
        self.assertIs(monitor.poll(), first)  # within USAGE_POLL: the same list, no new read
        self.assertIsNot(monitor.poll(), first)

    def test_minimax_and_kimi_show_every_window_when_the_monitor_stores_them(self):
        make_db(self.path, windows=True)
        limits = {l["provider"]: l for l in UsageMonitor(self.path, clock=lambda: NOW).poll()}
        self.assertEqual([(w["name"], w["pct"]) for w in limits["minimax"]["windows"]],
                         [("5h", 18.0), ("1d", 0.0), ("7d", 10.0)])
        self.assertEqual(limits["minimax"]["windows"][0]["resets_at"], NOW + 4000)
        self.assertFalse(limits["minimax"]["stale"])  # the stored windows are newer than the old headline
        self.assertEqual([w["name"] for w in limits["kimi"]["windows"]], ["5h", "7d", "1mo"])
        self.assertIsNone(limits["kimi"]["windows"][2]["resets_at"])

    def test_older_monitor_without_the_windows_table_still_works(self):
        make_db(self.path)  # no provider_windows table at all
        limits = {l["provider"]: l for l in UsageMonitor(self.path, clock=lambda: NOW).poll()}
        self.assertEqual([w["name"] for w in limits["minimax"]["windows"]], ["interval"])
        self.assertEqual([w["name"] for w in limits["kimi"]["windows"]], ["5h"])

    def test_codex_without_a_readable_raw_reply_still_shows_both_windows(self):
        make_db(self.path, codex=False)
        db = sqlite3.connect(self.path)
        db.execute("INSERT INTO codex_snapshots VALUES ('default', ?, 7, 8, NULL, 'not json')", (int(NOW * 1000),))
        db.commit()
        db.close()
        codex = next(l for l in UsageMonitor(self.path, clock=lambda: NOW).poll() if l["provider"] == "codex")
        self.assertEqual([(w["name"], w["pct"], w["resets_at"]) for w in codex["windows"]],
                         [("5h", 7, None), ("7d", 8, None)])

    def test_never_writes_to_the_database(self):
        make_db(self.path)
        before = os.stat(self.path).st_mtime_ns
        UsageMonitor(self.path, clock=lambda: NOW).poll()
        self.assertEqual(os.stat(self.path).st_mtime_ns, before)
        self.assertEqual(sorted(os.listdir(self.dir.name)), ["history.db"])  # no -wal/-journal left behind

    def test_stats_box_lists_limits(self):
        make_db(self.path)
        usage = UsageMonitor(self.path, clock=lambda: NOW).poll()
        world = World(100, 30, seed=1)
        land(world)
        screen = Screen(30, 100)
        render(screen, world, 8, False, {**dict.fromkeys(SPRITES, 0), "enemy": 0}, [], None, [], usage)
        with patch("screensaver.time.time", return_value=NOW):
            render(screen, world, 8, False, {**dict.fromkeys(SPRITES, 0), "enemy": 0}, [], None, [], usage)
        text = "\n".join("".join(row) for row in screen.rows)
        self.assertIn("+- limits", text)
        self.assertIn("5h", text)
        self.assertIn("12%", text)
        self.assertIn("1h05m", text)  # the 5h window resets in an hour and five minutes
        self.assertIn("7d", text)
        self.assertIn("claude (=^.^=)", text)  # 12% is nothing to worry about
        self.assertIn("interval", text)  # MiniMax's window is named, not just "used"
        self.assertIn("old 15m", text)  # its sample is older than the staleness limit
        lines = text.splitlines()
        start = next(i for i, line in enumerate(lines) if "+- limits" in line)
        column = lines[start].index("+- limits")
        self.assertEqual(column + LIMITS_WIDTH, 99)  # flush with the right edge when there is no system box
        end = next(i for i in range(start + 1, len(lines)) if "+------------------------------+" in lines[i])
        for line in lines[start:end + 1]:
            self.assertIn(line[column + LIMITS_WIDTH - 1], "|+")  # every row ends on the right border
        self.assertIn("codex (=^.^=)", text)
        self.assertIn("2d20h", text)  # Codex's weekly reset
        self.assertIn("kimi (=^.^=)", text)

    def test_limits_box_sits_left_of_the_system_box_and_its_cat(self):
        make_db(self.path)
        usage = UsageMonitor(self.path, clock=lambda: NOW).poll()
        system = SimpleNamespace(cpu=0.2, ram=(400, 1000), swap=(0, 0), load=1.5, history=[0.2] * 24, mood="calm")
        styles = {**dict.fromkeys(SPRITES, 0), "enemy": 0}

        def shown(width):
            world = World(width, 30, seed=1)
            land(world)
            screen = Screen(30, width)
            with patch("screensaver.time.time", return_value=NOW):
                render(screen, world, 8, False, styles, [], system, [], usage)
            return "\n".join("".join(row) for row in screen.rows).splitlines()

        lines = shown(150)
        limits = next(line for line in lines if "+- limits" in line).index("+- limits")
        box = next(line for line in lines if "+- system" in line).index("+- system")
        self.assertLessEqual(limits + LIMITS_WIDTH, box - SPEECH_ROOM)  # the cat and its speech stay clear
        self.assertTrue(any("( o.o )" in line for line in lines))  # the watch cat is still there
        self.assertTrue(any("chill~" in line for line in lines))
        self.assertGreater(limits, 23)  # and the park stats keep the top-left
        self.assertFalse(any("+- limits" in line for line in shown(100)))  # no room: it steps aside

    def test_limits_box_stays_during_a_raid_without_hiding_the_banner_or_monster(self):
        make_db(self.path)
        usage = UsageMonitor(self.path, clock=lambda: NOW).poll()
        styles = {**dict.fromkeys(SPRITES, 0), "enemy": 0}
        for rows, system in ((30, None), (22, None), (30, SimpleNamespace(
                cpu=0.2, ram=(400, 1000), swap=(0, 0), load=1.5, history=[0.2] * 24, mood="calm"))):
            with self.subTest(rows=rows, system=system is not None):
                world = World(150, rows, seed=1)
                land(world)
                world.start_raid(monster="firefox")
                world.raid.age = 4.0  # block phase: the monster stands at the right edge
                screen = Screen(rows, 150)
                with patch("screensaver.time.time", return_value=NOW):
                    render(screen, world, 8, False, styles, [], system, [], usage)
                lines = ["".join(row) for row in screen.rows]
                self.assertTrue(any("+- limits" in line for line in lines))  # still there
                self.assertIn("BLOCK! Monster firefox", lines[2])  # the banner row is untouched
                self.assertTrue(any("firefox" in line for line in lines[4:]))  # the monster's label...
                self.assertTrue(any("|####|" in line for line in lines))  # ...and body are not covered
                self.assertFalse(any("+- park" in line for line in lines))  # the stats box still yields

    def test_cat_worries_as_the_limit_fills(self):
        self.assertEqual([mood_face(pct) for pct in (0, 49, 50, 79, 80, 94, 95, 100)],
                         ["(=^.^=)", "(=^.^=)", "(=o.o=)", "(=o.o=)", "(=O.O=)", "(=O.O=)", "(=x.x=)", "(=x.x=)"])

    def test_until_reads_the_time_left(self):
        self.assertEqual(until(None, NOW), "")
        self.assertEqual(until(NOW - 1, NOW), "now")
        self.assertEqual(until(NOW + 30, NOW), "1m")
        self.assertEqual(until(NOW + 45 * 60, NOW), "45m")
        self.assertEqual(until(NOW + 3900, NOW), "1h05m")
        self.assertEqual(until(NOW + 2 * 86400 + 20 * 3600 + 60, NOW), "2d20h")

    def test_limits_box_shows_what_fits_and_counts_the_rest(self):
        make_db(self.path)
        usage = UsageMonitor(self.path, clock=lambda: NOW).poll()
        styles = {**dict.fromkeys(SPRITES, 0), "enemy": 0}

        def shown(rows):
            world = World(100, rows, seed=1)
            land(world)
            screen = Screen(rows, 100)
            with patch("screensaver.time.time", return_value=NOW):
                render(screen, world, 8, False, styles, [], None, [], usage)
            return "\n".join("".join(row) for row in screen.rows)

        self.assertNotIn("more", shown(20))  # four providers fit in a short terminal
        usage = usage * 3  # a dozen providers do not
        text = shown(20)
        self.assertIn("claude", text)
        self.assertIn("+7 more", text)  # five providers fit, seven are counted

if __name__ == "__main__":
    unittest.main()
