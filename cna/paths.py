"""Where the project's data, caches and web front end live."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
MAP_DATA = DATA / 'map'
CORRECTIONS = MAP_DATA / 'corrections'
OFFMAP = MAP_DATA / 'offmap.json'
SCENARIOS = DATA / 'scenarios.json'
VOCAB = DATA / 'vocab.json'
RULEBOOK = ROOT / 'The Campaign for North Africa.md'  # local only, not in version control
CACHE = ROOT / '.cache' / 'server'
SAVES = ROOT / 'saves'  # saved games, one folder each; not in version control
WEB = ROOT / 'web'


def map_data(m):
    """A section's automatic extraction."""
    return MAP_DATA / f'{m}.json'


def map_tiles(m):
    """A section's tiled grid fit."""
    return MAP_DATA / f'tiles{m}.json'


def map_corrections(m):
    return CORRECTIONS / f'{m}.json'
