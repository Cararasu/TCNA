// Shared by the map editor (app.js) and the game (game.js): the map
// vocabulary, hex and hexside helpers, and the joined map's tile layer.
//
// Hex ids are RRCC (row counting north, column counting east; even rows sit
// half a column east). Hexsides are keyed "HHHH|D" by the hex owning them as
// its E, NE or NW side. Hex corners run counter-clockwise from east-south-east.

// ---------- vocabulary ----------

const TERRAIN = {
  clear: { label: 'Clear', color: null, key: '1' },
  gravel: { label: 'Rock/Gravel', color: '#8d8d8d', key: '2' },
  rough: { label: 'Rough', color: '#9a6b2f', key: '3' },
  mountain: { label: 'Mountain', color: '#5c3b12', key: '4' },
  desert: { label: 'Desert', color: '#e8a400', key: '5' },
  delta: { label: 'Delta', color: '#4f8f1f', key: '6' },
  saltmarsh: { label: 'Salt Marsh', color: '#c8d400', key: '7' },
  heavyveg: { label: 'Heavy Vegetation', color: '#2e7d32', key: '8' },
  swamp: { label: 'Swamp', color: '#6a9fb5', key: '9' },
  sea: { label: 'Sea', color: '#1f6fd1', key: '0' },
};
const LANDMARKS = {
  majorcity: { label: 'Major City', letter: 'C', color: '#7a1fa2' },
  village: { label: 'Village/Bir', letter: 'V', color: '#1565c0' },
  oasis: { label: 'Oasis', letter: 'O', color: '#2e7d32' },
  port: { label: 'Port', letter: 'P', color: '#00838f' },
  airfield: { label: 'Airfield', letter: 'A', color: '#37474f' },
  fbbasin: { label: 'Flying Boat Basin', letter: 'FB', color: '#455a64' },
  fbalight: { label: 'Flying Boat Alighting Area', letter: 'FA', color: '#607d8b' },
  training: { label: 'Training Area', letter: 'T', color: '#6d4c41' },
};
const LINES = {
  road: { label: 'Road', color: '#e600a0', key: 'r' },
  track: { label: 'Track', color: '#00a000', key: 't' },
  railroad: { label: 'Railroad', color: '#0078ff', key: 'l' },
  unfinished_road: { label: 'Unfinished road', color: '#ff7ad0', key: 'r', shift: true },
  unfinished_railroad: { label: 'Unfinished railroad', color: '#7ab8ff', key: 'l', shift: true },
};
const LINE_ORDER = Object.keys(LINES);
// For continuity checks an unfinished road continues a road, and so on.
const LINE_FAMILY = { road: 'road', unfinished_road: 'road', track: 'track',
                      railroad: 'railroad', unfinished_railroad: 'railroad' };
const FEATURE = { ridge: '#c800c8', slope: '#e66e00', escarpment: '#dc0000' };
const RIVER = '#00e0ff';
const WADI = '#2f9e8f';
const BORDER = '#111111';

const DIRS = ['E', 'NE', 'NW', 'W', 'SW', 'SE'];
const OWNED = new Set(['E', 'NE', 'NW']);
const OPPOSITE = { E: 'W', NE: 'SW', NW: 'SE', W: 'E', SW: 'NE', SE: 'NW' };
const DIR_NAMES = { E: 'east', NE: 'north-east', NW: 'north-west', W: 'west', SW: 'south-west', SE: 'south-east' };
const SIDE_CORNERS = { E: [0, 1], NE: [1, 2], NW: [2, 3], W: [3, 4], SW: [4, 5], SE: [5, 0] };
// Neighbour offsets (d_row, d_col); even rows sit half a column east.
const NEIGHBOURS = {
  1: { E: [0, 1], NE: [1, 0], NW: [1, -1], W: [0, -1], SW: [-1, -1], SE: [-1, 0] },
  0: { E: [0, 1], NE: [1, 1], NW: [1, 0], W: [0, -1], SW: [-1, 0], SE: [-1, 1] },
};

// ---------- hex helpers ----------

const pad2 = (n) => String(n).padStart(2, '0');
const parseId = (id) => [+id.slice(0, 2), +id.slice(2)];
const hexId = (r, c) => pad2(r) + pad2(c);

function neighbourId(id, d) {
  const [r, c] = parseId(id);
  const [dr, dc] = NEIGHBOURS[r % 2][d];
  return hexId(r + dr, c + dc);
}
function sideKey(id, d) {
  return OWNED.has(d) ? `${id}|${d}` : `${neighbourId(id, d)}|${OPPOSITE[d]}`;
}
function sideHexes(key) {
  const [id, d] = key.split('|');
  return [id, neighbourId(id, d)];
}
function sideKeyBetween(a, b) {
  for (const d of DIRS) if (neighbourId(a, d) === b) return sideKey(a, d);
  return null;
}

// A hexside's value as the editor shows and the corrections store it.
function normSide(s) {
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

// ---------- drawing ----------

// Both pages draw the map data the same way. A draw context has toLL (scan
// pixels to LatLng), the canvas renderer, the overlay opacity op, and
// add(layer, group), which puts a layer in one of the toggled groups:
// terrain, landmarks, rivers, features (ridges, slopes, escarpments and
// borders) and crossings.

function drawTerrain(ctx, ring, terrain) {
  const t = TERRAIN[terrain];
  if (t && t.color) {
    ctx.add(L.polygon(ring, { renderer: ctx.renderer, stroke: false, fillColor: t.color,
                              fillOpacity: 0.28 * ctx.op, interactive: false }), 'terrain');
  }
}

function drawLandmarks(ctx, center, landmarks) {
  landmarks.forEach((lm, i) => {
    const def = LANDMARKS[lm.type] || { letter: '?', color: '#000' };
    const w = def.letter.length > 1 ? 24 : 18;
    const offset = (i - (landmarks.length - 1) / 2) * 26;
    const icon = L.divIcon({
      className: '',
      html: `<div class="landmark-icon" style="background:${def.color};width:${w}px;height:18px;opacity:${ctx.op}"
              title="${escapeHtml(lm.name || def.label)}">${def.letter}</div>`,
      iconSize: [w, 18], iconAnchor: [w / 2 - offset, 9],
    });
    ctx.add(L.marker(ctx.toLL(center), { icon, interactive: false, keyboard: false }), 'landmarks');
  });
}

// One hexside from scan point pa to pb; down is the centre of the hex a
// slope or escarpment falls towards, if known.
function drawSideFeatures(ctx, s, pa, pb, down) {
  const { renderer, op } = ctx;
  const a = ctx.toLL(pa), b = ctx.toLL(pb);
  const along = (f) => [pa[0] + (pb[0] - pa[0]) * f, pa[1] + (pb[1] - pa[1]) * f];
  if (s.river) {
    ctx.add(L.polyline([a, b], { renderer, color: RIVER, weight: s.river === 'major' ? 7 : 3, opacity: 0.95 * op,
                                 interactive: false }), 'rivers');
  }
  if (s.wadi) {
    ctx.add(L.polyline([a, b], { renderer, color: WADI, weight: 5, dashArray: '10 4', opacity: 0.95 * op,
                                 interactive: false }), 'rivers');
  }
  if (s.border) {
    ctx.add(L.polyline([a, b], { renderer, color: BORDER, weight: 3, dashArray: '12 4 2 4', opacity: op,
                                 interactive: false }), 'features');
  }
  if (s.feature) {
    const col = FEATURE[s.feature.type];
    ctx.add(L.polyline([a, b], { renderer, color: col, weight: 5, opacity: 0.95 * op, interactive: false }), 'features');
    if (down) {
      const m = along(0.5);
      const v = [down[0] - m[0], down[1] - m[1]];
      const len = Math.hypot(v[0], v[1]);
      ctx.add(L.polyline([ctx.toLL(m), ctx.toLL([m[0] + v[0] / len * 30, m[1] + v[1] / len * 30])],
                         { renderer, color: col, weight: 4, opacity: 0.95 * op, interactive: false }), 'features');
    }
  }
  // Crossings: a coloured X per line type, spread evenly along the side.
  const arm = 9;  // half-width of the X, scan pixels
  s.cross.forEach((x, i) => {
    const m = along((i + 1) / (s.cross.length + 1));
    for (const sgn of [1, -1]) {
      const v = [arm, sgn * arm];  // screen-aligned diagonals, so it always reads as an X
      ctx.add(L.polyline([ctx.toLL([m[0] - v[0], m[1] - v[1]]), ctx.toLL([m[0] + v[0], m[1] + v[1]])],
                         { renderer, color: LINES[x.k].color, weight: 4, opacity: op, lineCap: 'round',
                           interactive: false }), 'crossings');
    }
  });
}

// A hexside in words; name gives a hex's name for the downhill side.
function sideSummary(s, name = (id) => id) {
  const parts = [];
  if (s.river) parts.push(`${s.river} river`);
  if (s.wadi) parts.push('wadi');
  if (s.feature) parts.push(s.feature.down ? `${s.feature.type} (down to ${name(s.feature.down)})` : s.feature.type);
  for (const x of s.cross) parts.push(`${LINES[x.k].label.toLowerCase()} crossing`);
  if (s.border) parts.push('border');
  return parts.join(', ');
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

// ---------- the joined map's tiles ----------

// The joined map's scan: each section's own tiles drawn at its place, west to
// east, so each section lies over the one before it as on the table. Each is
// clipped to its scan, since edge tiles are padded out to the full tile size.
// Options: sections (from the server) and zmax, the scan's native zoom.
function loadImage(src) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

const JoinedLayer = L.GridLayer.extend({
  createTile(coords, done) {
    const tile = document.createElement('canvas');
    tile.width = tile.height = 256;
    const s = 2 ** (coords.z - this.options.zmax);
    const x0 = coords.x * 256, y0 = coords.y * 256;  // tile origin, zoom-z pixels
    const parts = [];
    for (const sec of this.options.sections) {
      const sx = Math.round(sec.x * s), sy = Math.round(sec.y * s);
      const sw = Math.floor(sec.width * s), sh = Math.floor(sec.height * s);
      const ax = Math.max(x0, sx), ay = Math.max(y0, sy);
      const bx = Math.min(x0 + 256, sx + sw), by = Math.min(y0 + 256, sy + sh);
      if (ax >= bx || ay >= by) continue;
      const imgs = [];
      for (let ty = Math.floor((ay - sy) / 256); ty * 256 < by - sy; ty++) {
        for (let tx = Math.floor((ax - sx) / 256); tx * 256 < bx - sx; tx++) {
          imgs.push({ x: sx + tx * 256 - x0, y: sy + ty * 256 - y0,
                      img: loadImage(`/tiles/${sec.id}/${coords.z}/${tx}/${ty}.jpg?v=${sec.v}`) });
        }
      }
      // Hexes of the section to the west that this section's paper covers.
      const cut = sec.cut.map((poly) => poly.map(([px, py]) => [px * s - x0, py * s - y0]))
        .filter((poly) => poly.some(([px]) => px > 0) && poly.some(([px]) => px < 256)
                          && poly.some(([, py]) => py > 0) && poly.some(([, py]) => py < 256));
      parts.push({ clip: [ax - x0, ay - y0, bx - ax, by - ay], cut, imgs });
    }
    Promise.all(parts.flatMap((p) => p.imgs.map((i) => i.img))).then((loaded) => {
      const ctx = tile.getContext('2d');
      let k = 0;
      for (const p of parts) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(...p.clip);
        ctx.clip();
        if (p.cut.length) {
          // Rectangle minus the hexes: each hex adds one more crossing.
          ctx.beginPath();
          ctx.rect(0, 0, 256, 256);
          for (const poly of p.cut) {
            ctx.moveTo(...poly[0]);
            for (const pt of poly.slice(1)) ctx.lineTo(...pt);
            ctx.closePath();
          }
          ctx.clip('evenodd');
        }
        for (const i of p.imgs) {
          const img = loaded[k++];
          if (img) ctx.drawImage(img, i.x, i.y);
        }
        ctx.restore();
      }
      done(null, tile);
    });
    return tile;
  },
});
