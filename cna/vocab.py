"""The map's vocabulary, from data/vocab.json (shared with the browser)."""
import json

from .paths import VOCAB

with open(VOCAB, encoding='utf-8') as _f:
    RAW = json.load(_f)

TERRAIN = tuple(RAW['terrain'])
LANDMARKS = tuple(RAW['landmarks'])
LINE_ORDER = tuple(RAW['lines'])  # the order a hexside's crossings are stored in
LINE_FAMILY = {k: v['family'] for k, v in RAW['lines'].items()}
FEATURES = tuple(RAW['features'])
DOWNHILL = {k for k, v in RAW['features'].items() if v['downhill']}  # features that name their downhill hex
RIVERS = tuple(RAW['rivers'])
UNIT_TYPES = tuple(RAW['unit_types'])
UNIT_SIZES = tuple(RAW['unit_sizes'])
