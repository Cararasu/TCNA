// The board: the joined map as the game sees it (/api/game/map, corrections
// already applied by the server) with the off-map boxes as zones. Read-only
// and free of drawing, so rules can ask it about hexes, neighbours and
// hexsides without a map on screen.
//
// A place on the board is a loc: {kind: 'hex', id} or {kind: 'zone', id}.

import { DIRS, neighbourId, normSide, sideKey, sideKeyBetween } from '../shared/hex.js';

export class Board {
  constructor(data) {
    this.width = data.width;
    this.height = data.height;
    this.zmax = data.zmax;
    this.sections = data.sections;
    this.hexes = new Map(data.hexes.map((h) => [h.id, h]));  // id -> {id, label, also, c, p, t, lm, coastal}
    this.sides = data.sides;                                    // side key -> side, only sides with something on them
    this.byLabel = new Map();                                   // section label (A4827) -> id
    for (const h of data.hexes) for (const l of [h.label, ...(h.also || [])]) this.byLabel.set(l, h.id);
    this.zones = new Map(data.zones.map((z) => [z.id, z]));
    this.holdFor = new Map();  // hex id -> the holding box its counters are kept in
    for (const z of data.zones) {
      if (!z.hex) continue;
      const id = this.hexOfLabel(z.hex);
      if (id) this.holdFor.set(id, z.id);
      else console.warn(`offmap.json: holding box ${z.id} names hex ${z.hex}, which is not on the map`);
    }
  }

  hex(id) { return this.hexes.get(id); }
  label(id) { return this.hexes.get(id)?.label || id; }
  hexOfLabel(l) { return this.byLabel.get(l.replace(/\s+/g, '')); }

  // The hexes next to id, with the direction to each.
  neighbours(id) {
    return DIRS.map((dir) => ({ dir, id: neighbourId(id, dir) })).filter((n) => this.hexes.has(n.id));
  }
  // A hexside's value (normSide form); an empty side if nothing is on it.
  side(id, dir) { return normSide(this.sides[sideKey(id, dir)]); }
  sideBetween(a, b) {
    const key = sideKeyBetween(a, b);
    return key ? normSide(this.sides[key]) : null;
  }

  // Where a loc's counters are shown: a hex with a holding box shows them in the box.
  shownAt(loc) {
    return loc.kind === 'hex' && this.holdFor.has(loc.id) ? { kind: 'zone', id: this.holdFor.get(loc.id) } : loc;
  }
  outline(loc) {
    return loc.kind === 'hex' ? this.hexes.get(loc.id).p : this.zones.get(loc.id).p;
  }
  centre(loc) {
    if (loc.kind === 'hex') return this.hexes.get(loc.id).c;
    const p = this.zones.get(loc.id).p;
    return [p.reduce((s, q) => s + q[0], 0) / p.length, p.reduce((s, q) => s + q[1], 0) / p.length];
  }
}
