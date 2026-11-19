"""Check pixel art against the park's layout and terminal capabilities."""
import unittest
from unittest.mock import Mock

import terminal_pixels as pixels
from screensaver import AGENTS, ART, SPRITES, PLACES, World, render_place, render_office
from test_screensaver import Screen


class PixelTests(unittest.TestCase):
    def test_pixel_computer_keeps_desk_layout_and_screen_animation(self):
        curses = Mock(COLORS=256, COLOR_PAIRS=256)
        curses.color_pair.side_effect = lambda index: index
        shades = dict(zip(SPRITES, (208, 39, 141, 220, 245)))
        shades.update({kind: value[2] for kind, value in AGENTS.items()})
        styles = pixels.make_styles(curses, 40, -1, shades,
                                   {kind: value[1] for kind, value in AGENTS.items()},
                                   scenery=True)
        self.assertIsNotNone(styles)
        world = World(100, 32, wild=False)
        world.sync_agents({123: ('claude', 'work')})
        animal = world.animals[0]
        animal.desk = 0
        x, y = world.desks()[0]
        for seated, expected in ((False, 'boot'), (True, '>_ make')):
            animal.seated = seated
            screen = Screen(32, 100)
            render_office(screen, world, {'pixels': styles})
            self.assertIn(expected, ''.join(screen.rows[y + 1][x + 14:x + 21]))
            self.assertTrue(any(ch in '▀▄' for ch in screen.rows[y][x + 13:x + 22]))
        world.animals.clear()
        # Keep the HQ open while checking the now-vacant first desk.
        world.sync_agents({124: ('codex', 'idle')})
        screen = Screen(32, 100)
        render_office(screen, world, {'pixels': styles})
        self.assertIn('zz', ''.join(screen.rows[y + 1][x + 14:x + 21]))

    def test_pixel_scenery_renders_every_place_and_clips_on_resize(self):
        curses = Mock(COLORS=256, COLOR_PAIRS=256)
        curses.color_pair.side_effect = lambda index: index
        shades = dict(zip(SPRITES, (208, 39, 141, 220, 245)))
        shades.update({kind: value[2] for kind, value in AGENTS.items()})
        styles = pixels.make_styles(curses, 40, -1, shades,
                                   {kind: value[1] for kind, value in AGENTS.items()},
                                   scenery=True)
        self.assertIsNotNone(styles)
        for width, height in ((32, 12), (80, 24), (160, 48)):
            world = World(width, height, wild=False)
            for place in PLACES:
                with self.subTest(width=width, height=height, place=place):
                    screen = Screen(height, width)
                    for elapsed in (0, 3, 17):
                        world.elapsed = elapsed
                        render_place(screen, world, {'pixels': styles},
                                     [(0, 0, 0), (1, 1, 1), (.5, .5, 2)])
                    self.assertTrue(any('▀' in row or '▄' in row for row in screen.rows))
                    self.assertTrue(all(char == ' ' for row in screen.rows[:2] for char in row))
                    world.change_place()

    def test_all_sprites_fit_existing_layout_and_mirror(self):
        for species, frames in ART.items():
            grid = pixels.pixels(species)
            with self.subTest(species=species):
                self.assertEqual(len(grid) // 2, len(frames[0]))
                self.assertLessEqual(len(grid[0]), max(map(len, frames[0])))
                self.assertEqual(len({len(row) for row in grid}), 1)
                self.assertEqual(pixels.pixels(species, right=True),
                                 tuple(row[::-1] for row in grid))
                self.assertNotIn('E', ''.join(pixels.pixels(species, 'sleep')))

    def test_palette_covers_every_animation_and_agent(self):
        curses = Mock(COLORS=256, COLOR_PAIRS=65536)
        curses.color_pair.side_effect = lambda index: index
        shades = {species: 208 for species in pixels.SPRITES}
        shades.update({kind: value[2] for kind, value in AGENTS.items()})
        styles = pixels.make_styles(curses, 24, -1, shades)
        self.assertIsNotNone(styles)
        draw = Mock()
        for kind in shades:
            for species in ART:
                for state in ('sleep', 'walk', 'work', 'wait'):
                    for tick in (0, 1, 11):
                        pixels.render(draw, None, 0, 0, species, state, tick,
                                      True, kind, styles)
        self.assertTrue(draw.called)

    def test_low_color_or_pair_budget_falls_back_without_allocating(self):
        for colors, pairs in ((8, 256), (256, 65)):
            curses = Mock(COLORS=colors, COLOR_PAIRS=pairs)
            self.assertIsNone(pixels.make_styles(curses, 64, -1, {'kucing': 208}))
            curses.init_pair.assert_not_called()


if __name__ == '__main__':
    unittest.main()
