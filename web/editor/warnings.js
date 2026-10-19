// Checks of the map data for the editor's warning list: things that are
// probably extraction mistakes. Pure: it reads the map through the accessors
// in m and returns the warnings, most serious first.
//
// m: {hexes (Map id -> hex), hexOf(id), sideOf(key), sideExists(key), allSideKeys(), label(id)}

import { LINE_FAMILY, TERRAIN } from '../shared/vocab.js';
import { DIRS, neighbourId, sideHexes, sideKey, sideKeyBetween } from '../shared/hex.js';

export const WARNING_TYPES = {
  conflict: 'River + wadi',
  'dead-end': 'Dead ends',
  'river-end': 'River ends',
  uncertain: 'Uncertain terrain',
};

export function computeWarnings(m) {
  const out = [];
  const { hexes, hexOf, sideOf, sideExists, label } = m;
  const isSea = (id) => hexes.has(id) && hexOf(id).terrain === 'sea';

  for (const id of hexes.keys()) {
    const e = hexOf(id);
    if (e.uncertain) out.push({ type: 'uncertain', hex: id, text: `${label(id)} uncertain terrain (${TERRAIN[e.terrain]?.label || e.terrain})` });
  }

  // Dead ends: a line family crossing exactly one side of a hex that has no
  // landmark and isn't on the map edge.
  const families = [...new Set(Object.values(LINE_FAMILY))];
  for (const id of hexes.keys()) {
    const e = hexOf(id);
    if (e.landmarks.length) continue;
    if (DIRS.some((d) => !hexes.has(neighbourId(id, d)))) continue;
    const counts = {};
    for (const d of DIRS) {
      for (const x of sideOf(sideKey(id, d)).cross) counts[LINE_FAMILY[x.k]] = (counts[LINE_FAMILY[x.k]] || 0) + 1;
    }
    for (const fam of families) {
      if (counts[fam] === 1) out.push({ type: 'dead-end', hex: id, text: `${label(id)} ${fam} dead end` });
    }
  }

  // River ends: at each end of a river side, another river side should meet
  // it, unless the corner touches the sea or the map edge.
  const seen = new Set();
  for (const key of m.allSideKeys()) {
    if (!sideOf(key).river || !sideExists(key)) continue;
    const [h, n] = sideHexes(key);
    const common = DIRS.map((d) => neighbourId(h, d)).filter((x) => DIRS.some((d) => neighbourId(n, d) === x));
    for (const x of common) {
      const corner = [h, n, x].sort().join('-');
      if (seen.has(corner)) continue;
      seen.add(corner);
      if (!hexes.has(x) || isSea(h) || isSea(n) || isSea(x)) continue;
      const s1 = sideOf(sideKeyBetween(h, x)), s2 = sideOf(sideKeyBetween(n, x));
      if (!s1.river && !s2.river) {
        out.push({ type: 'river-end', hex: h, side: key, text: `${label(h)}|${label(n)} river ends (corner ${label(x)})` });
      }
    }
  }

  // A hexside is a river or a wadi, never both (Terrain Effects Chart 8.37).
  for (const key of m.allSideKeys()) {
    const s = sideOf(key);
    if (s.river && s.wadi && sideExists(key)) {
      const [h, n] = sideHexes(key);
      out.push({ type: 'conflict', hex: h, side: key, text: `${label(h)}|${label(n)} both ${s.river} river and wadi` });
    }
  }

  const order = Object.keys(WARNING_TYPES);
  out.sort((a, b) => order.indexOf(a.type) - order.indexOf(b.type) || a.hex.localeCompare(b.hex));
  return out;
}
