"""Play breaks respect agent status, raids and the park's layout."""
import unittest
from unittest.mock import Mock, patch

import terminal_pixels
from screensaver import AGENTS, PLAY_STATES, SPRITES, World, render
from test_screensaver import Screen


class PlayTests(unittest.TestCase):
    def resident(self):
        world = World(120, 34, seed=7, wild=False)
        world.sync_agents({1: ('claude', 'idle')})
        animal = world.animals[0]
        animal.entry, animal.state = 0, 'walk'
        animal.x, animal.y = 20, 20
        return world, animal

    def test_every_game_moves_or_rests_then_returns_to_walking(self):
        for game in PLAY_STATES:
            world, animal = self.resident()
            self.assertTrue(world.start_play(animal, game))
            x, y = animal.x, animal.y
            animal.timer = 10
            for _ in range(40):
                world.update(.1, 8)
                low, high = world.lane(animal)
                self.assertGreaterEqual(animal.x, low)
                self.assertLessEqual(animal.x, high)
                self.assertEqual(animal.state, game)
            if game == 'box':
                self.assertEqual((animal.x, animal.y), (x, y))
            else:
                self.assertNotEqual(animal.x, x)
            animal.timer = 0
            with patch.object(world.rng, 'choices', return_value=['walk']):
                world.update(.1, 8)
            self.assertEqual(animal.state, 'walk')

    def test_idle_residents_can_choose_games_automatically(self):
        for game in PLAY_STATES:
            world, animal = self.resident()
            animal.timer = 0
            with patch.object(world.rng, 'choices', return_value=[game]):
                world.update(.1, 8)
            self.assertEqual(animal.state, game)
            self.assertIsNotNone(animal.play_home)
            self.assertGreater(animal.timer, 6)

    def test_work_and_permission_interrupt_every_game(self):
        for game in PLAY_STATES:
            for status in ('work', 'wait'):
                world, animal = self.resident()
                world.start_play(animal, game)
                world.sync_agents({1: ('claude', status)})
                world.update(.1, 8)
                self.assertEqual(animal.state, status)
                self.assertFalse(world.start_play(animal, game))

    def test_break_skips_visitors_helpers_arrivals_and_encounters(self):
        for attr, value in (('visitor', True), ('sub', 'helper'), ('entry', 1),
                            ('state', 'greet'), ('state', 'chase'), ('state', 'fight')):
            world, animal = self.resident()
            setattr(animal, attr, value)
            self.assertEqual(world.play_break(), 0)
        world, animal = self.resident()
        self.assertEqual(world.play_break(), 1)
        world.start_raid()
        self.assertEqual(world.play_break(), 0)
        world.update(.1, 8)
        self.assertEqual(animal.state, 'rally')

    def test_games_render_and_survive_resize_in_pixels_and_ascii(self):
        curses = Mock(COLORS=256, COLOR_PAIRS=256)
        curses.color_pair.side_effect = lambda index: index
        shades = dict(zip(SPRITES, (208, 39, 141, 220, 245)))
        shades.update({kind: value[2] for kind, value in AGENTS.items()})
        pixels = terminal_pixels.make_styles(
            curses, 40, -1, shades, {kind: value[1] for kind, value in AGENTS.items()},
            scenery=True)
        self.assertIsNotNone(pixels)
        for game in PLAY_STATES:
            for pixel_mode in (False, True):
                world, animal = self.resident()
                world.start_play(animal, game)
                styles = dict.fromkeys(SPRITES, 0)
                if pixel_mode:
                    styles['pixels'] = pixels
                for width, height in ((120, 34), (40, 12), (80, 24)):
                    world.width, world.height = width, height
                    world.update(.1, 8)
                    screen = Screen(height, width)
                    render(screen, world, 8, False, styles, [])
                    self.assertTrue(any(char != ' ' for row in screen.rows for char in row))


if __name__ == '__main__':
    unittest.main()
