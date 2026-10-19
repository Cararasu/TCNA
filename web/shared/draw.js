// Drawing the map with Leaflet, for both pages: hex terrain, landmarks,
// hexside features, and the joined map's scan tiles. Leaflet is loaded as a
// classic script before the modules and is the global L.

import { BORDER, FEATURES, LANDMARKS, LINES, RIVER, TERRAIN, WADI } from './vocab.js';
import { escapeHtml } from './util.js';

// ---------- drawing ----------

// Both pages draw the map data the same way. A draw context has toLL (scan
// pixels to LatLng), the canvas renderer, the overlay opacity op, and
// add(layer, group), which puts a layer in one of the toggled groups:
// terrain, landmarks, rivers, features (ridges, slopes, escarpments and
// borders) and crossings.

export function drawTerrain(ctx, ring, terrain) {
  const t = TERRAIN[terrain];
  if (t && t.color) {
    ctx.add(L.polygon(ring, { renderer: ctx.renderer, stroke: false, fillColor: t.color,
                              fillOpacity: 0.28 * ctx.op, interactive: false }), 'terrain');
  }
}

export function drawLandmarks(ctx, center, landmarks) {
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
export function drawSideFeatures(ctx, s, pa, pb, down) {
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
    const col = FEATURES[s.feature.type].color;
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

export const JoinedLayer = L.GridLayer.extend({
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
