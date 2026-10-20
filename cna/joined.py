"""The five map sections joined into one map, west to east.

The sections are laid long side by long side, A to E, each partly over the
one to its west, and a hex is always 33 hexes from the hex bearing the same
number on an adjacent section (rulebook, Determining Shortest Distance). So
hex RRCC of one section is hex RR(CC+33) of the section to its west: the two
easternmost columns in each section's data, which lie on the paper that the
next section covers, are the same hexes as that section's columns 01 and 02.

On the joined map a hex is numbered RR plus its column counted from Map A's
west edge (RRCC or RRCCC). Where sections overlap, the eastern section's copy
of a hex or hexside comes first: it lies on top, and the western section's
copy of its last column is extracted from blank paper.
"""
import json
import statistics
import threading

from .corrections import (auto_side, hex_correction, hex_effective, load_corrections, norm_side, normalize,
                          write_corrections, check_corrections)
from .hexgrid import TiledGrid, hex_id, neighbour, parse_id
from .paths import map_corrections, map_data, map_tiles
from .rules import implements

SECTIONS = 'ABCDE'
SHIFT = 33  # columns between a hex and the same number on the next section east
# Malta (M) is an inset on Map A's sheet with its own grid, not in scale or in
# place (Case 44.11). It sits apart on the joined map: its rows are numbered
# from MALTA_ROWS up, beyond any section's, so no hex there touches Africa.
MALTA = 'M'
MALTA_ROWS = 80
# Neighbours depend on whether a row is odd or even, so moving Malta's rows
# must keep each row's parity.
assert MALTA_ROWS % 2 == 0
MAPS = SECTIONS + MALTA  # everything with its own data and corrections
OWNED = ('E', 'NE', 'NW')
SAVE_LOCK = threading.Lock()


def _set(d, key, value):
    if value:
        d[key] = value
    else:
        d.pop(key, None)


@implements('4.1')
class Joined:
    """Which hexes and hexsides of the sections are the same on the joined map."""

    def __init__(self):
        self.data = {}
        for m in MAPS:
            with open(map_data(m), encoding='utf-8') as f:
                self.data[m] = json.load(f)
        self.hexes = {}  # global id -> [(section, id)], eastern section first
        self.where = {}  # (section, id) -> global id
        for m in MAPS:
            for hid in self.data[m]:
                g = self.global_id(m, hid)
                self.hexes.setdefault(g, []).insert(0, (m, hid))
                self.where[(m, hid)] = g
        self.sides = {}  # global side key -> [(section, side key)], eastern section first
        self.side_where = {}  # (section, side key) -> global side key
        for g, inst in self.hexes.items():
            for d in OWNED:
                ng = hex_id(*neighbour(*parse_id(g), d))
                for m, hid in inst:
                    if self.local_id(m, ng) in self.data[m]:
                        gk, key = f'{g}|{d}', f'{hid}|{d}'
                        self.sides.setdefault(gk, []).append((m, key))
                        self.side_where[(m, key)] = gk

    @staticmethod
    def global_id(m, hid):
        r, c = parse_id(hid)
        if m == MALTA:
            return hex_id(r + MALTA_ROWS, c)
        return hex_id(r, c + SHIFT * SECTIONS.index(m))

    @staticmethod
    def local_id(m, g):
        r, c = parse_id(g)
        if (m == MALTA) != (r > MALTA_ROWS):
            return None
        if m == MALTA:
            return hex_id(r - MALTA_ROWS, c)
        c -= SHIFT * SECTIONS.index(m)
        return hex_id(r, c) if c >= 0 else None

    def shared(self):
        """Global ids of the hexes on more than one section."""
        return [g for g, inst in self.hexes.items() if len(inst) > 1]

    # Slopes and escarpments name their downhill hex, by section or global id.
    def side_to_global(self, m, s):
        if s and s.get('feature') and s['feature'].get('down'):
            s = {**s, 'feature': {**s['feature'], 'down': self.where.get((m, s['feature']['down']),
                                                                         s['feature']['down'])}}
        return s

    def side_to_local(self, m, s):
        if s and s.get('feature') and s['feature'].get('down'):
            s = {**s, 'feature': {**s['feature'], 'down': self.local_id(m, s['feature']['down'])}}
        return s

    def auto_side_local(self, m, key):
        hid, d = key.split('|')
        s = self.data[m][hid]['sides'].get(d)
        return auto_side(s) if s else None

    def auto_side_global(self, gk):
        m, key = self.sides[gk][0]
        return self.side_to_global(m, self.auto_side_local(m, key))

    def merged(self, corr):
        """The joined map's corrections, from each section's {section: corrections}.

        A shared hex takes its terrain and landmarks from the first copy that
        corrects them and is reviewed if any copy is; a shared hexside takes
        the first corrected copy, else the eastern copy's automatic data.
        Everything on one section only keeps its correction as it is.
        """
        hexes, sides = {}, {}
        for g, inst in self.hexes.items():
            if len(inst) == 1:
                m, h = inst[0]
                if h in corr[m]['hexes']:
                    hexes[g] = corr[m]['hexes'][h]
                continue
            cs = [corr[m]['hexes'].get(h) or {} for m, h in inst]
            terrain = next((c['terrain'] for c in cs if c.get('terrain')), None)
            m, h = inst[0]
            auto = self.data[m][h]
            eff = {'terrain': terrain or auto['terrain'], 'uncertain': not terrain and bool(auto.get('uncertain')),
                   'landmarks': next((c['landmarks'] for c in cs if c.get('landmarks')), []),
                   'reviewed': any(c.get('reviewed') for c in cs)}
            c = hex_correction(auto, eff)
            if c:
                hexes[g] = c
        for gk, inst in self.sides.items():
            if len(inst) == 1:
                m, key = inst[0]
                if key in corr[m]['sides']:
                    sides[gk] = self.side_to_global(m, corr[m]['sides'][key])
                continue
            s = next((self.side_to_global(m, norm_side(corr[m]['sides'][key]))
                      for m, key in inst if key in corr[m]['sides']), None)
            if s and s != norm_side(self.auto_side_global(gk)):
                sides[gk] = s
        return {'hexes': hexes, 'sides': sides}

    def _put_hex(self, out, m, h, eff):
        c = hex_correction(self.data[m][h], eff)
        if c:
            out[m]['hexes'][h] = c
        else:
            out[m]['hexes'].pop(h, None)

    def _put_side(self, out, m, key, eff):
        s = self.side_to_local(m, eff)
        if s != norm_side(self.auto_side_local(m, key)):
            out[m]['sides'][key] = s
        else:
            out[m]['sides'].pop(key, None)

    def split(self, joined, corr):
        """Each section's corrections for the joined map's corrections.

        Every copy of a shared hex or hexside gets the joined value; anything
        on one section only takes its joined correction as it is, and
        corrections of anything not on the joined map are kept.
        """
        out = {m: {'hexes': dict(corr[m]['hexes']), 'sides': dict(corr[m]['sides'])} for m in MAPS}
        for g, inst in self.hexes.items():
            m, h = inst[0]
            if len(inst) == 1:
                _set(out[m]['hexes'], h, joined['hexes'].get(g))
                continue
            eff = hex_effective(self.data[m][h], joined['hexes'].get(g))
            for m, h in inst:
                self._put_hex(out, m, h, eff)
        for gk, inst in self.sides.items():
            if len(inst) == 1:
                m, key = inst[0]
                _set(out[m]['sides'], key, self.side_to_local(m, joined['sides'].get(gk)))
                continue
            eff = norm_side(joined['sides'].get(gk) or self.auto_side_global(gk))
            for m, key in inst:
                self._put_side(out, m, key, eff)
        return out

    def propagate(self, m, new, corr):
        """All sections' corrections after section m's are replaced by new.

        Hexes and hexsides that changed on m and are also on another section
        get the same value there.
        """
        old = corr[m]
        out = {s: {'hexes': dict(corr[s]['hexes']), 'sides': dict(corr[s]['sides'])} for s in MAPS}
        out[m] = {'hexes': dict(new['hexes']), 'sides': dict(new['sides'])}
        for h in set(old['hexes']) | set(new['hexes']):
            if old['hexes'].get(h) == new['hexes'].get(h) or (m, h) not in self.where:
                continue
            eff = hex_effective(self.data[m][h], new['hexes'].get(h))
            for m2, h2 in self.hexes[self.where[(m, h)]]:
                if m2 != m:
                    self._put_hex(out, m2, h2, eff)
        for key in set(old['sides']) | set(new['sides']):
            if old['sides'].get(key) == new['sides'].get(key) or (m, key) not in self.side_where:
                continue
            gk = self.side_where[(m, key)]
            eff = self.side_to_global(m, norm_side(new['sides'].get(key) or self.auto_side_local(m, key)))
            for m2, key2 in self.sides[gk]:
                if m2 != m:
                    self._put_side(out, m2, key2, eff)
        return out

    def offsets(self):
        """Where each section's scan lies on the joined map, in scan pixels.

        Each section is placed so that its copies of shared hexes fall on the
        western section's copies (the median over the shared hexes).
        """
        grids = {m: TiledGrid.load(map_tiles(m)) for m in MAPS}
        off = {SECTIONS[0]: (0.0, 0.0), MALTA: (0.0, 0.0)}  # Malta is printed on Map A's sheet
        for west, east in zip(SECTIONS, SECTIONS[1:]):
            dx, dy = [], []
            for g in self.shared():
                inst = dict(self.hexes[g])
                if west in inst and east in inst:
                    pw = grids[west].center(*parse_id(inst[west]))
                    pe = grids[east].center(*parse_id(inst[east]))
                    dx.append(pw[0] - pe[0])
                    dy.append(pw[1] - pe[1])
            off[east] = (off[west][0] + statistics.median(dx), off[west][1] + statistics.median(dy))
        return off, grids


_JOINED = None
_JOINED_KEY = None
_JOINED_LOCK = threading.Lock()


def joined():
    """The Joined index, rebuilt when a section's data file changes."""
    global _JOINED, _JOINED_KEY
    key = tuple(map_data(m).stat().st_mtime_ns for m in MAPS)
    with _JOINED_LOCK:
        if _JOINED_KEY != key:
            _JOINED, _JOINED_KEY = Joined(), key
        return _JOINED


def all_corrections():
    return {m: load_corrections(m) for m in MAPS}


def _write_changed(out, corr, always=()):
    for s in MAPS:
        out[s] = normalize(out[s])
        if out[s] != corr[s] or s in always:
            write_corrections(s, out[s])


def save_section(m, obj):
    """Save one section's corrections, copying changes to shared hexes and sides."""
    check_corrections(obj)
    with SAVE_LOCK:
        corr = all_corrections()
        _write_changed(joined().propagate(m, normalize(obj), corr), corr, always=m)


def save_joined(obj):
    """Save the joined map's corrections into every section that has a copy."""
    check_corrections(obj, '4,5')
    with SAVE_LOCK:
        corr = all_corrections()
        _write_changed(joined().split(normalize(obj), corr), corr)


def _differences(a, b):
    return sum(1 for m in MAPS for kind in ('hexes', 'sides')
               for k in set(a[m][kind]) | set(b[m][kind]) if a[m][kind].get(k) != b[m][kind].get(k))


def unsynced(j, corr):
    """How many section corrections differ from their copies on other sections."""
    return _differences(corr, {m: normalize(c) for m, c in j.split(j.merged(corr), corr).items()})


def sync_all():
    """Give every copy of a shared hex or hexside the joined value, and rewrite
    any corrections file not in stored form.

    Returns (how many corrections changed, the maps whose files were rewritten).
    """
    with SAVE_LOCK:
        j = joined()
        corr = all_corrections()
        out = {m: normalize(c) for m, c in j.split(j.merged(corr), corr).items()}
        written = []
        for m in MAPS:
            path = map_corrections(m)
            stale = path.exists() and json.loads(path.read_text(encoding='utf-8')) != corr[m]
            if out[m] != corr[m] or stale:
                write_corrections(m, out[m])
                written.append(m)
        return _differences(corr, out), written
