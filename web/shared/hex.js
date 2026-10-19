// Hex ids, neighbours, hexsides, and how corrections lie over the automatic
// data. No drawing and no DOM: the game's model and the editor both use it,
// and tests/parity.mjs runs it under Node against the Python side.
//
// Hex ids are RRCC (row counting north, column counting east; even rows sit
// half a column east). Hexsides are keyed "HHHH|D" by the hex owning them as
// its E, NE or NW side. Hex corners run counter-clockwise from east-south-east.
// Python has the same rules in cna/hexgrid.py and cna/corrections.py.

import { LINE_ORDER, LINES } from './vocab.js';

export const DIRS = ['E', 'NE', 'NW', 'W', 'SW', 'SE'];
export const OWNED = new Set(['E', 'NE', 'NW']);
export const OPPOSITE = { E: 'W', NE: 'SW', NW: 'SE', W: 'E', SW: 'NE', SE: 'NW' };
export const DIR_NAMES = { E: 'east', NE: 'north-east', NW: 'north-west', W: 'west', SW: 'south-west', SE: 'south-east' };
export const SIDE_CORNERS = { E: [0, 1], NE: [1, 2], NW: [2, 3], W: [3, 4], SW: [4, 5], SE: [5, 0] };
// Neighbour offsets (d_row, d_col); even rows sit half a column east.
export const NEIGHBOURS = {
  1: { E: [0, 1], NE: [1, 0], NW: [1, -1], W: [0, -1], SW: [-1, -1], SE: [-1, 0] },
  0: { E: [0, 1], NE: [1, 1], NW: [1, 0], W: [0, -1], SW: [-1, 0], SE: [-1, 1] },
};

const pad2 = (n) => String(n).padStart(2, '0');
export const parseId = (id) => [+id.slice(0, 2), +id.slice(2)];
export const hexId = (r, c) => pad2(r) + pad2(c);

export function neighbourId(id, d) {
  const [r, c] = parseId(id);
  const [dr, dc] = NEIGHBOURS[r % 2][d];
  return hexId(r + dr, c + dc);
}
export function sideKey(id, d) {
  return OWNED.has(d) ? `${id}|${d}` : `${neighbourId(id, d)}|${OPPOSITE[d]}`;
}
export function sideHexes(key) {
  const [id, d] = key.split('|');
  return [id, neighbourId(id, d)];
}
export function sideKeyBetween(a, b) {
  for (const d of DIRS) if (neighbourId(a, d) === b) return sideKey(a, d);
  return null;
}

// A hexside's value in the one form corrections store (norm_side in cna/corrections.py).
export function normSide(s) {
  s = s || {};
  return {
    river: s.river || null,
    feature: s.feature ? { ...s.feature } : null,
    wadi: !!s.wadi,
    border: !!s.border,
    // Which lines cross the side; where along it doesn't matter (Case 8.33).
    cross: LINE_ORDER.filter((k) => (s.cross || []).some((x) => x.k === k)).map((k) => ({ k })),
  };
}

export function sameSide(a, b) {
  const canon = (s) => JSON.stringify(normSide(s));
  return canon(a) === canon(b);
}

// A hex's value: its automatic data with its correction laid over it
// (hex_effective in cna/corrections.py). auto is {terrain, uncertain}.
export function hexOf(auto, corr) {
  const c = corr || {};
  return {
    terrain: c.terrain || auto.terrain,
    uncertain: c.terrain ? false : !!auto.uncertain,
    landmarks: c.landmarks || [],
    reviewed: !!c.reviewed,
  };
}

// A hexside in words; name gives a hex's name for the downhill side.
export function sideSummary(s, name = (id) => id) {
  const parts = [];
  if (s.river) parts.push(`${s.river} river`);
  if (s.wadi) parts.push('wadi');
  if (s.feature) parts.push(s.feature.down ? `${s.feature.type} (down to ${name(s.feature.down)})` : s.feature.type);
  for (const x of s.cross) parts.push(`${LINES[x.k].label.toLowerCase()} crossing`);
  if (s.border) parts.push('border');
  return parts.join(', ');
}
