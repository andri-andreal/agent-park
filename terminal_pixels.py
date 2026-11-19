"""Small hand-drawn sprites: two square pixels per terminal cell.

All adults fit the existing four-row park layout. Dots are transparent;
F/L/S are fur, highlight and shade, C cream, E eyes and P pink.
"""

SPRITES = {
    'kucing': (
        '..L...L.....', '..FF.FF.....', '.LFFFFFS....', '.FEFCEFSL...',
        '.LCPCCFS..LF', '..SFFFFFSLFF', '...FCSFFFSF.', '...LC..LC...',
    ),
    'anjing': (
        '..SS........', '.SFFS.......', 'LFFFFFS.....', 'FECFFFS.....',
        'ECCFFFFFSLF.', '.CCFFFFFSSF.', '...FCSFFFS..', '...LC..LC...',
    ),
    'kelinci': (
        '..LP.LP....', '..FP.FP....', '.LFFFFFS...', '.FEFCEFS...',
        '.LCPCCFS...', '..SFFFFFSL.', '...FCSFFFC.', '...LC..LC..',
    ),
    'bebek': (
        '..LL....', '.LFFS...', '.FEFS...', 'PPFFS...',
        '.LFFFFFL', '.FCLFFFS', '..SFFFS.', '..P..P..',
    ),
    'tikus': (
        '.LL..LL.....', '.LPFFPL.....', '.LFFFFS.....', 'PEFCFFS.....',
        '.LCCFFFFS...', '..SFFFFFFSPP', '...FCSFFFS.P', '...LC..LC.PP',
    ),
}

# Scenery shares a restrained palette so the moving animals stay readable.
SCENERY_COLORS = {'.': -1, 'g': 65, 'l': 107, 'h': 151, 's': 23,
                  'b': 94, 't': 137, 'w': 255, 'c': 110, 'r': 173,
                  'y': 223, 'a': 67}
SCENERY = {
    'tree': ('....ll....', '...lhll...', '..lhllgg..', '.lhllgggs.',
             'lhlllgggss', '.ggggggss.', '....tb....', '....bb....'),
    'pine': ('....h.....', '...hll....', '..hllgg...', '...llg....',
             '.hlllggg..', 'hlllggggs.', '....tb....', '....bb....'),
    'palm': ('ll....ll....', '.lll.lll.ll.', '..llhlllll..', 'llllbtlll...',
             '....tb..ll..', '....bt......', '.....tb.....', '.....bb.....'),
    'bench': ('tttttttttt', 'bbbbbbbbbb', '..........', 'tttttttttt',
              '.bb....bb.', '.bb....bb.'),
    'house': ('.....rr.....', '....ryrr....', '...ryrrrr...', '..ryrrrrrr..',
              '.rrrrrrrrrr.', '..yyyyyyyb..', '..yawyybbb..', '..yaayybtb..',
              '..yyyyybtb..', '..bbbbbbbb..'),
    'cloud': ('...www....', '.wwwwwww..', 'wwwwwwwwww', '.cccccccc.'),
    'sun': ('..yyyy..', '.yyyyyy.', 'yyyyyyyy', 'yyyyyyyy', '.yyyyyy.', '..yyyy..'),
    'moon': ('..wwww..', '.wwww...', 'wwww....', 'wwww....', '.wwww...', '..wwww..'),
    'grass': ('.l.l.', 'ggggg'),
    'flower': ('..r..', '.ryr.', '..t..', '.gtg.'),
    'sand': ('..y..', '.t...'),
    'wave': ('..cc..cc', 'ccwwccww'),
    'shore': ('aaaaaaaa', 'cccccccc'),
    'bank': ('lglglglg', 'ssssssss'),
    'computer': ('.ccccccc.', 'csssssssc', 'csssssssc', 'csssssssc',
                 '.ccccccc.', '....c....', 'ttttttttt', 'bb.....bb'),
}


def pixels(species, state='walk', tick=0, right=False):
    """Return a rectangular pixel grid, facing left unless requested."""
    baby = species.startswith('anak ')
    rows = SPRITES[species.removeprefix('anak ')]
    if baby:
        # Retain ears and eyes, with a shorter body and smaller silhouette.
        rows = tuple(row[:7] for row in rows[:5]) + ('..LCL..',)
        if species == 'anak bebek':
            rows = ('.LL..', 'LEFS.', 'PPFS.', '.LFFL', '.FCFS', '..PP.')
    grid = [list(row) for row in rows]
    for y, row in enumerate(grid):
        for x, color in enumerate(row):
            if color == 'E' and (state == 'sleep' or tick % 12 == 11):
                row[x] = 'S'
    if state in ('walk', 'pass', 'sprint', 'chase', 'flee', 'work', 'attack') and tick % 2:
        grid[-1] = grid[-1][1:] + ['.']
    if right:
        grid = [row[::-1] for row in grid]
    return tuple(''.join(row) for row in grid)


def cell(top, bottom):
    """Transparent half pixels use the terminal background."""
    if top == bottom == '.':
        return ' ', '.', '.'
    if top == '.':
        return '▄', bottom, '.'
    return '▀', top, bottom


def make_styles(curses, first_pair, background, shades, species_by_kind=None, scenery=False):
    """Allocate shared 256-color pairs, or fall back atomically to ASCII."""
    import locale
    if curses.COLORS < 256 or 'utf' not in locale.getpreferredencoding(False).lower():
        return None
    palettes = {}
    combinations = set()
    for kind, fur in shades.items():
        # Darken in the xterm color cube; the warm cream adds readable contrast.
        shadow = max(16, fur - 36) if 16 <= fur <= 231 else 240
        palette = {'.': background, 'F': fur, 'L': 230, 'S': shadow,
                   'C': 223, 'E': 234, 'P': 211}
        palettes[kind] = palette
        species_names = ((species_by_kind or {}).get(kind),) if kind in (species_by_kind or {}) else (
            (kind,) if kind in SPRITES else tuple(SPRITES))
        for species in species_names:
            for name in (species, 'anak ' + species):
                for state in ('walk', 'sleep'):
                    for tick in (0, 1, 11):
                        grid = pixels(name, state, tick)
                        for y in range(0, len(grid), 2):
                            for a, b in zip(grid[y], grid[y + 1]):
                                _, fg, bg = cell(a, b)
                                combinations.add((palette[fg], palette[bg]))
    if scenery:
        palette = dict(SCENERY_COLORS, **{'.': background})
        palettes['scenery'] = palette
        for grid in SCENERY.values():
            for y in range(0, len(grid), 2):
                for a, b in zip(grid[y], grid[y + 1]):
                    _, fg, bg = cell(a, b)
                    combinations.add((palette[fg], palette[bg]))
        combinations.add((palette['w'], palette['s']))  # text on the monitor
    # Python curses attributes are portable for the first 256 pair IDs.
    if first_pair + len(combinations) > min(256, curses.COLOR_PAIRS):
        return None
    pairs = {}
    try:
        for index, pair in enumerate(sorted(combinations), first_pair):
            curses.init_pair(index, *pair)
            pairs[pair] = curses.color_pair(index)
    except curses.error:
        return None
    return palettes, pairs


def render_computer(draw, screen, y, x, text, styles):
    """A shaded monitor, stand and wooden desk in the existing 9x4 space."""
    palette, pairs = styles[0]['scenery'], styles[1]
    grid = SCENERY['computer']
    for row in range(len(grid) // 2):
        for col, (a, b) in enumerate(zip(grid[row * 2], grid[row * 2 + 1])):
            char, fg, bg = cell(a, b)
            draw(screen, y + row, x + col, char, pairs[palette[fg], palette[bg]])
    draw(screen, y + 1, x + 1, text[:7].ljust(7), pairs[palette['w'], palette['s']])


def render_scenery(draw, screen, world, styles, particles):
    """Layer compact scenery above the horizon, with sparse ground details."""
    import math
    palette, pairs = styles[0]['scenery'], styles[1]
    height, width = screen.getmaxyx()
    horizon = world.ground_top - 1

    def art(name, x, top=None):
        grid = SCENERY[name]
        top = horizon - len(grid) // 2 if top is None else top
        for row in range(len(grid) // 2):
            if top + row < 2 or top + row >= height - 1:
                continue
            for col, (a, b) in enumerate(zip(grid[2 * row], grid[2 * row + 1])):
                if a == b == '.':
                    continue
                char, fg, bg = cell(a, b)
                draw(screen, top + row, x + col, char, pairs[palette[fg], palette[bg]])

    if world.place == 'Forest':
        for x in range(1, width - 5, 12):
            art('pine', x)
        if horizon >= 7:
            art('moon', width - 12, 2)
        for sx, sy, phase in particles[:8]:
            if math.sin(world.elapsed * 1.5 + phase) > .4:
                draw(screen, 2 + int(sy * max(1, horizon - 3)), int(sx * (width - 1)),
                     '▪', pairs[palette['y'], palette['y']])
    elif world.place == 'Beach':
        art('palm', 2)
        if width >= 60:
            art('palm', width - 14)
        if horizon >= 6:
            art('sun', width // 2, 2)
        shift = int(world.elapsed * 3) % 8
        for x in range(-8 + shift, width, 8):
            art('shore', x, horizon - 2)
            art('wave', x, horizon - 1)
    elif world.place == 'Village':
        for x in range(3, width - 7, 24):
            art('house', x)
        if horizon >= 8:
            art('cloud', width // 2, 2)
    else:
        art('tree', 2)
        art('bench', width // 2 - 5)
        if width >= 60:
            art('tree', width - 12)
        if horizon >= 7:
            art('cloud', int(world.elapsed * .7) % (width + 10) - 10, 2)
    for x in range(0, width, 8):
        art('shore' if world.place == 'Beach' else 'bank', x, horizon)
    for sx, sy, phase in particles[:max(4, min(24, width * height // 180))]:
        y = world.ground_top + int(sy * max(1, height - world.ground_top - 3))
        x = int(sx * (width - 1))
        name = 'sand' if world.place in ('Beach', 'Village') else (
            'flower' if phase < 1 else 'grass')
        art(name, x, y)


def render(draw, screen, y, x, species, state, tick, right, kind, styles, rows=None):
    palettes, pairs = styles
    palette = palettes.get(kind, palettes[species.removeprefix('anak ')])
    grid = pixels(species, state, tick, right)
    for row in range(len(grid) // 2):
        if rows is not None and row not in rows:
            continue
        for col, (a, b) in enumerate(zip(grid[row * 2], grid[row * 2 + 1])):
            char, fg, bg = cell(a, b)
            draw(screen, y + row, x + col, char, pairs[palette[fg], palette[bg]])
