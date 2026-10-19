// The map's vocabulary: the names come from data/vocab.json (via /api/vocab,
// the same file the server checks corrections against); this file adds how
// each is drawn and, in the editor, its key.
//
// Tests (tests/parity.mjs) run without the server and set globalThis.CNA_VOCAB first.

const RAW = globalThis.CNA_VOCAB ?? await (await fetch('/api/vocab')).json();

const TERRAIN_STYLE = {
  clear: { color: null, key: '1' },
  gravel: { color: '#8d8d8d', key: '2' },
  rough: { color: '#9a6b2f', key: '3' },
  mountain: { color: '#5c3b12', key: '4' },
  desert: { color: '#e8a400', key: '5' },
  delta: { color: '#4f8f1f', key: '6' },
  saltmarsh: { color: '#c8d400', key: '7' },
  heavyveg: { color: '#2e7d32', key: '8' },
  swamp: { color: '#6a9fb5', key: '9' },
  sea: { color: '#1f6fd1', key: '0' },
};
const LANDMARK_STYLE = {
  majorcity: { letter: 'C', color: '#7a1fa2' },
  village: { letter: 'V', color: '#1565c0' },
  oasis: { letter: 'O', color: '#2e7d32' },
  port: { letter: 'P', color: '#00838f' },
  airfield: { letter: 'A', color: '#37474f' },
  fbbasin: { letter: 'FB', color: '#455a64' },
  fbalight: { letter: 'FA', color: '#607d8b' },
  training: { letter: 'T', color: '#6d4c41' },
};
const LINE_STYLE = {
  road: { color: '#e600a0', key: 'r' },
  track: { color: '#00a000', key: 't' },
  railroad: { color: '#0078ff', key: 'l' },
  unfinished_road: { color: '#ff7ad0', key: 'r', shift: true },
  unfinished_railroad: { color: '#7ab8ff', key: 'l', shift: true },
};
const FEATURE_STYLE = { ridge: '#c800c8', slope: '#e66e00', escarpment: '#dc0000' };

// Each vocabulary entry with its style; an entry without one still works,
// drawn in a fallback colour, but is reported so the style can be added.
function styled(names, styles, fallback) {
  return Object.fromEntries(Object.entries(names).map(([k, v]) => {
    if (!styles[k]) console.warn(`vocab: no style for ${k}`);
    return [k, { ...(typeof v === 'string' ? { label: v } : v), ...(styles[k] || fallback) }];
  }));
}

export const TERRAIN = styled(RAW.terrain, TERRAIN_STYLE, { color: '#ff00ff' });
export const LANDMARKS = styled(RAW.landmarks, LANDMARK_STYLE, { letter: '?', color: '#000' });
export const LINES = styled(RAW.lines, LINE_STYLE, { color: '#ff00ff' });
export const LINE_ORDER = Object.keys(RAW.lines);
// For continuity checks an unfinished road continues a road, and so on.
export const LINE_FAMILY = Object.fromEntries(Object.entries(RAW.lines).map(([k, v]) => [k, v.family]));
export const FEATURES = Object.fromEntries(Object.entries(RAW.features).map(([k, v]) => [k, { ...v, color: FEATURE_STYLE[k] || '#ff00ff' }]));
export const RIVERS = RAW.rivers;
export const UNIT_TYPES = RAW.unit_types;
export const UNIT_SIZES = RAW.unit_sizes;  // largest first
export const RIVER = '#00e0ff';
export const WADI = '#2f9e8f';
export const BORDER = '#111111';
