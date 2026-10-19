"""One map section's hand corrections: their form, checks and storage.

A section's corrections (data/map/corrections/<MAP>.json) hold only the hexes
and hexsides changed by hand, so the automatic data can be regenerated
without losing them:

  {"hexes": {"RRCC": {"terrain": ..., "landmarks": [{"type", "name"?}], "reviewed": true}},
   "sides": {"RRCC|D": {"river", "feature", "wadi", "border", "cross"}}}

A hex correction lists only what it changes. A hexside correction is the
side's whole value (norm_side), keyed by the hex owning it as its E, NE or
NW side. The browser editor keeps the same rules in web/shared/hex.js
(normSide, hexOf); tests/test_parity.py checks the two agree.
"""
import json
import os
import re

from . import vocab
from .paths import CORRECTIONS, map_corrections

OWNED = ('E', 'NE', 'NW')
HEX_KEYS = {'terrain', 'landmarks', 'reviewed'}
SIDE_KEYS = {'river', 'feature', 'wadi', 'border', 'cross'}


# ---------- values ----------

def auto_side(s):
    """An extracted hexside (data/map/<MAP>.json) as corrections store it."""
    # A side is a river or a wadi, not both; blue water decides for the river.
    return norm_side({'river': s.get('river'), 'wadi': bool(s.get('wadi')) and not s.get('river'),
                      'border': bool(s.get('border')), 'feature': s.get('feature'),
                      'cross': [{'k': x['kind']} for x in s['crossings']]})


def norm_side(s):
    """A hexside's value in the one form corrections store (normSide in hex.js)."""
    s = s or {}
    kinds = {x['k'] for x in s.get('cross') or []}
    return {'river': s.get('river') or None, 'feature': dict(s['feature']) if s.get('feature') else None,
            'wadi': bool(s.get('wadi')), 'border': bool(s.get('border')),
            'cross': [{'k': k} for k in vocab.LINE_ORDER if k in kinds]}


def norm_hex(c):
    """A hex correction with only what it changes."""
    c = c or {}
    out = {}
    if c.get('terrain'):
        out['terrain'] = c['terrain']
    if c.get('landmarks'):
        out['landmarks'] = [{'type': lm['type'], **({'name': lm['name']} if lm.get('name') else {})}
                            for lm in c['landmarks']]
    if c.get('reviewed'):
        out['reviewed'] = True
    return out


def normalize(obj):
    """A section's corrections in stored form: sorted, every value normalized."""
    hexes = {k: norm_hex(v) for k, v in sorted(obj['hexes'].items())}
    return {'hexes': {k: v for k, v in hexes.items() if v},
            'sides': {k: norm_side(v) for k, v in sorted(obj['sides'].items())}}


def hex_effective(auto, corr):
    """A hex's value: its automatic data with its correction laid over it (hexOf in hex.js)."""
    corr = corr or {}
    return {'terrain': corr.get('terrain') or auto['terrain'],
            'uncertain': not corr.get('terrain') and bool(auto.get('uncertain')),
            'landmarks': corr.get('landmarks') or [], 'reviewed': bool(corr.get('reviewed'))}


def hex_correction(auto, eff):
    """The correction that gives a hex with this automatic data the value eff."""
    c = {}
    if eff['terrain'] != auto['terrain'] or (auto.get('uncertain') and not eff['uncertain']):
        c['terrain'] = eff['terrain']
    if eff['landmarks']:
        c['landmarks'] = eff['landmarks']
    if eff['reviewed']:
        c['reviewed'] = True
    return c


# ---------- checks ----------

def _fail(where, msg):
    raise ValueError(f'{where}: {msg}')


def check_hex(where, c):
    if not isinstance(c, dict):
        _fail(where, 'must be an object')
    if set(c) - HEX_KEYS:
        _fail(where, f'unknown fields {sorted(set(c) - HEX_KEYS)}')
    if 'terrain' in c and c['terrain'] not in vocab.TERRAIN:
        _fail(where, f'unknown terrain {c["terrain"]!r}')
    if 'reviewed' in c and not isinstance(c['reviewed'], bool):
        _fail(where, 'reviewed must be true or false')
    lms = c.get('landmarks', [])
    if not isinstance(lms, list):
        _fail(where, 'landmarks must be a list')
    for lm in lms:
        if not isinstance(lm, dict) or set(lm) - {'type', 'name'}:
            _fail(where, f'bad landmark {lm!r}')
        if lm.get('type') not in vocab.LANDMARKS:
            _fail(where, f'unknown landmark type {lm.get("type")!r}')
        if 'name' in lm and not isinstance(lm['name'], str):
            _fail(where, 'a landmark name must be text')


def check_side(where, s, id_pattern):
    if not isinstance(s, dict):
        _fail(where, 'must be an object')
    if set(s) - SIDE_KEYS:
        _fail(where, f'unknown fields {sorted(set(s) - SIDE_KEYS)}')
    if s.get('river') is not None and s['river'] not in vocab.RIVERS:
        _fail(where, f'unknown river {s["river"]!r}')
    for k in ('wadi', 'border'):
        if k in s and not isinstance(s[k], bool):
            _fail(where, f'{k} must be true or false')
    f = s.get('feature')
    if f is not None:
        if not isinstance(f, dict) or f.get('type') not in vocab.FEATURES:
            _fail(where, f'bad feature {f!r}')
        if f['type'] in vocab.DOWNHILL:
            if set(f) != {'type', 'down'} or not re.fullmatch(id_pattern, str(f['down'])):
                _fail(where, f'a {f["type"]} needs the id of its downhill hex')
        elif set(f) != {'type'}:
            _fail(where, f'a {f["type"]} has no downhill hex')
    cross = s.get('cross', [])
    if not isinstance(cross, list):
        _fail(where, 'cross must be a list')
    for x in cross:
        if not isinstance(x, dict) or set(x) != {'k'} or x['k'] not in vocab.LINE_ORDER:
            _fail(where, f'bad crossing {x!r}')


def check_corrections(obj, id_digits='4'):
    """Raise ValueError unless obj is a well-formed corrections object."""
    if not (isinstance(obj, dict) and isinstance(obj.get('hexes'), dict) and isinstance(obj.get('sides'), dict)):
        raise ValueError('corrections must be {"hexes": {...}, "sides": {...}}')
    id_pattern = rf'\d{{{id_digits}}}'
    for key, c in obj['hexes'].items():
        if not re.fullmatch(id_pattern, key):
            raise ValueError(f'bad hex id {key!r}')
        check_hex(f'hex {key}', c)
    for key, s in obj['sides'].items():
        if not re.fullmatch(rf'{id_pattern}\|({"|".join(OWNED)})', key):
            raise ValueError(f'bad side key {key!r}')
        check_side(f'side {key}', s, id_pattern)


# ---------- storage ----------

def load_corrections(map_id):
    path = map_corrections(map_id)
    if not path.exists():
        return {'hexes': {}, 'sides': {}}
    with open(path, encoding='utf-8') as f:
        return normalize(json.load(f))


def write_corrections(map_id, obj):
    """Write a section's corrections in stored form, atomically (temp file, then rename)."""
    CORRECTIONS.mkdir(parents=True, exist_ok=True)
    path = map_corrections(map_id)
    tmp = path.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(normalize(obj), f, indent=1, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, path)
