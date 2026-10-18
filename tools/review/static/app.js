// CNA map review and correction.
//
// The server sends one map section's automatic extraction (hexes with their
// corners in scan pixels, hexsides keyed "HHHH|D" by the hex owning them as
// its E, NE or NW side) plus the hand corrections. What is shown and edited is
// the automatic data with the corrections laid over it; only the corrections
// are saved back, to data/map/corrections/<MAP>.json.
//
// Leaflet's CRS.Simple maps scan pixels to lat/lng at the scan's native zoom.

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
function sideGeom(key) {
  const [id, d] = key.split('|');
  const h = state.hexes.get(id);
  const [i, j] = SIDE_CORNERS[d];
  return [h.p[i], h.p[j]];
}
const sideExists = (key) => sideHexes(key).every((id) => state.hexes.has(id));

// ---------- state ----------

const map = L.map('map', {
  crs: L.CRS.Simple, minZoom: 0, maxZoom: 8, zoomSnap: 0.25, zoomDelta: 0.5,
  wheelPxPerZoomLevel: 90, attributionControl: false, doubleClickZoom: false,
});
const renderer = L.canvas({ padding: 0.5, tolerance: 3 });

const state = {
  mapId: null, data: null, zmax: 6, tiles: null,
  hexes: new Map(),        // id -> {id, c, p, t, u, coastal, mix}
  auto: new Map(),         // side key -> automatic side
  corr: { hexes: {}, sides: {} },
  groups: {},              // layer name -> L.layerGroup
  hexLayers: new Map(),    // hex id -> [layers]
  sideLayers: new Map(),   // side key -> [layers]
  selection: null,         // {kind: 'hex', id} | {kind: 'side', key}
  selectionLayers: [],
  hover: null,
  opacity: 1,
  undo: [],
  warnings: [],
  warnIndex: -1,
  warnTypes: { 'dead-end': true, 'river-end': true, uncertain: true },
};

const toLL = (p) => map.unproject(L.point(p[0], p[1]), state.zmax);
const fromLL = (ll) => map.project(ll, state.zmax);

// ---------- effective data (automatic + corrections) ----------

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
const sideOf = (key) => normSide(state.corr.sides[key] || state.auto.get(key));

function sameSide(a, b) {
  const canon = (s) => JSON.stringify({
    river: s.river, feature: s.feature, wadi: s.wadi, border: s.border,
    cross: s.cross.map((x) => x.k).sort(),
  });
  return canon(a) === canon(b);
}

function hexOf(id) {
  const h = state.hexes.get(id);
  const c = state.corr.hexes[id] || {};
  return {
    terrain: c.terrain || h.t,
    uncertain: c.terrain ? false : h.u,
    landmarks: c.landmarks || [],
    reviewed: !!c.reviewed,
    edited: !!(c.terrain || (c.landmarks && c.landmarks.length)),
  };
}
const isSea = (id) => state.hexes.has(id) && hexOf(id).terrain === 'sea';

// ---------- drawing ----------

const GROUPS = ['terrain', 'uncertain', 'rivers', 'features', 'crossings', 'landmarks',
                'reviewed', 'edited', 'outlines', 'hit', 'selection'];

function clearLayers(store, key) {
  for (const l of store.get(key) || []) l.remove();
  store.delete(key);
}

function drawHex(id) {
  clearLayers(state.hexLayers, id);
  const h = state.hexes.get(id);
  const e = hexOf(id);
  const op = state.opacity;
  const ring = h.p.map(toLL);
  const out = [];
  const add = (layer, group) => { layer.addTo(state.groups[group]); out.push(layer); };
  const t = TERRAIN[e.terrain];
  if (t && t.color) {
    add(L.polygon(ring, { renderer, stroke: false, fillColor: t.color, fillOpacity: 0.28 * op, interactive: false }), 'terrain');
  }
  if (e.uncertain) {
    add(L.polygon(ring, { renderer, color: '#ff8c00', weight: 2, dashArray: '6 5', opacity: 0.9 * op,
                          fill: false, interactive: false }), 'uncertain');
  }
  e.landmarks.forEach((lm, i) => {
    const def = LANDMARKS[lm.type] || { letter: '?', color: '#000' };
    const w = def.letter.length > 1 ? 24 : 18;
    const offset = (i - (e.landmarks.length - 1) / 2) * 26;
    const icon = L.divIcon({
      className: '',
      html: `<div class="landmark-icon" style="background:${def.color};width:${w}px;height:18px;opacity:${op}"
              title="${escapeHtml(lm.name || def.label)}">${def.letter}</div>`,
      iconSize: [w, 18], iconAnchor: [w / 2 - offset, 9],
    });
    add(L.marker(toLL(h.c), { icon, interactive: false, keyboard: false }), 'landmarks');
  });
  if (e.reviewed) {
    add(L.circleMarker(toLL([h.c[0], h.c[1] + 40]), { renderer, radius: 5, color: '#1b8a3a', weight: 2,
                                                      fillColor: '#3ccf6a', fillOpacity: 0.9 * op,
                                                      opacity: op, interactive: false }), 'reviewed');
  }
  if (e.edited) {
    add(L.circleMarker(toLL([h.c[0], h.c[1] - 40]), { renderer, radius: 4, color: '#b35900', weight: 2,
                                                      fillColor: '#ffb04a', fillOpacity: 0.9 * op,
                                                      opacity: op, interactive: false }), 'edited');
  }
  state.hexLayers.set(id, out);
}

function drawSide(key) {
  clearLayers(state.sideLayers, key);
  if (!state.hexes.has(key.split('|')[0])) return;
  const s = sideOf(key);
  const [pa, pb] = sideGeom(key);
  const a = toLL(pa), b = toLL(pb);
  const op = state.opacity;
  const out = [];
  const add = (layer, group) => { layer.addTo(state.groups[group]); out.push(layer); };
  const along = (f) => [pa[0] + (pb[0] - pa[0]) * f, pa[1] + (pb[1] - pa[1]) * f];

  if (s.river) {
    add(L.polyline([a, b], { renderer, color: RIVER, weight: s.river === 'major' ? 7 : 3, opacity: 0.95 * op,
                             interactive: false }), 'rivers');
  }
  if (s.wadi) {
    add(L.polyline([a, b], { renderer, color: WADI, weight: 5, dashArray: '10 4', opacity: 0.95 * op,
                             interactive: false }), 'rivers');
  }
  if (s.border) {
    add(L.polyline([a, b], { renderer, color: BORDER, weight: 3, dashArray: '12 4 2 4', opacity: op,
                             interactive: false }), 'features');
  }
  if (s.feature) {
    const col = FEATURE[s.feature.type];
    add(L.polyline([a, b], { renderer, color: col, weight: 5, opacity: 0.95 * op, interactive: false }), 'features');
    if (s.feature.down && state.hexes.has(s.feature.down)) {
      const m = along(0.5);
      const dc = state.hexes.get(s.feature.down).c;
      const v = [dc[0] - m[0], dc[1] - m[1]];
      const len = Math.hypot(v[0], v[1]);
      add(L.polyline([toLL(m), toLL([m[0] + v[0] / len * 30, m[1] + v[1] / len * 30])],
                     { renderer, color: col, weight: 4, opacity: 0.95 * op, interactive: false }), 'features');
    }
  }
  // Crossings: a coloured X per line type, spread evenly along the side.
  const arm = 9;  // half-width of the X, scan pixels
  s.cross.forEach((x, i) => {
    const m = along((i + 1) / (s.cross.length + 1));
    for (const sgn of [1, -1]) {
      const v = [arm, sgn * arm];  // screen-aligned diagonals, so it always reads as an X
      add(L.polyline([toLL([m[0] - v[0], m[1] - v[1]]), toLL([m[0] + v[0], m[1] + v[1]])],
                     { renderer, color: LINES[x.k].color, weight: 4, opacity: op, lineCap: 'round',
                       interactive: false }), 'crossings');
    }
  });
  if (state.corr.sides[key]) {
    add(L.circleMarker(toLL(along(0.5)), { renderer, radius: 3, color: '#b35900', weight: 1,
                                           fillColor: '#ffb04a', fillOpacity: op, opacity: op,
                                           interactive: false }), 'edited');
  }
  state.sideLayers.set(key, out);
}

function allSideKeys() {
  const keys = new Set(state.auto.keys());
  for (const k of Object.keys(state.corr.sides)) keys.add(k);
  return keys;
}

// Groups redrawn from the data. 'outlines' and 'hit' (the click/hover
// targets) are built once per map in buildStaticLayers and must survive.
const DYNAMIC_GROUPS = GROUPS.filter((g) => g !== 'outlines' && g !== 'hit');

function drawAll() {
  for (const g of DYNAMIC_GROUPS) state.groups[g].clearLayers();
  state.hexLayers.clear();
  state.sideLayers.clear();
  for (const id of state.hexes.keys()) drawHex(id);
  for (const key of allSideKeys()) drawSide(key);
  drawSelection();
}

function buildStaticLayers() {
  for (const name of GROUPS) {
    if (state.groups[name]) state.groups[name].remove();
    state.groups[name] = L.layerGroup();
  }
  for (const h of state.hexes.values()) {
    const ring = h.p.map(toLL);
    L.polygon(ring, { renderer, color: '#202020', weight: 1, opacity: 0.6, fill: false, interactive: false })
      .addTo(state.groups.outlines);
    const hit = L.polygon(ring, { renderer, stroke: false, fillOpacity: 0, fillColor: '#000' });
    hit.on('mousemove', (ev) => onHover(h.id, fromLL(ev.latlng)));
    hit.on('click', (ev) => onClick(h.id, fromLL(ev.latlng)));
    hit.addTo(state.groups.hit);
  }
}

function applyLayerToggles() {
  for (const box of document.querySelectorAll('#layers input[data-layer]')) {
    const g = state.groups[box.dataset.layer];
    if (!g) continue;
    if (box.checked) g.addTo(map); else g.remove();
  }
  state.groups.hit.addTo(map);
  state.groups.selection.addTo(map);
}

// ---------- picking ----------

function distToSegment(p, a, b) {
  const vx = b[0] - a[0], vy = b[1] - a[1];
  const t = Math.max(0, Math.min(1, ((p.x - a[0]) * vx + (p.y - a[1]) * vy) / (vx * vx + vy * vy)));
  return Math.hypot(p.x - (a[0] + t * vx), p.y - (a[1] + t * vy));
}

// Nearest side of a hex if the point is close to it, else null (= the hex).
function pickSide(id, p) {
  const h = state.hexes.get(id);
  const radius = Math.hypot(h.p[0][0] - h.c[0], h.p[0][1] - h.c[1]);
  let best = null, bestD = Infinity;
  for (const d of DIRS) {
    const [i, j] = SIDE_CORNERS[d];
    const dist = distToSegment(p, h.p[i], h.p[j]);
    if (dist < bestD) { bestD = dist; best = d; }
  }
  if (bestD > radius * 0.24) return null;
  const key = sideKey(id, best);
  return sideExists(key) ? key : null;
}

function onClick(id, p) {
  const key = pickSide(id, p);
  select(key ? { kind: 'side', key } : { kind: 'hex', id });
}

function onHover(id, p) {
  const key = pickSide(id, p);
  if (state.hover && state.hover.id === id && state.hover.key === key) return;
  state.hover = { id, key };
  showInfo(id, key);
}

// ---------- selection and editor ----------

function select(sel) {
  state.selection = sel;
  drawSelection();
  renderEditor();
  writeHash();
}

function drawSelection() {
  state.groups.selection.clearLayers();
  const sel = state.selection;
  if (!sel) return;
  if (sel.kind === 'hex') {
    if (!state.hexes.has(sel.id)) return;
    L.polygon(state.hexes.get(sel.id).p.map(toLL), { renderer, color: '#ffea00', weight: 4, fill: false,
                                                     interactive: false }).addTo(state.groups.selection);
  } else {
    const [pa, pb] = sideGeom(sel.key);
    for (const id of sideHexes(sel.key)) {
      L.polygon(state.hexes.get(id).p.map(toLL), { renderer, color: '#ffea00', weight: 1.5, fill: false,
                                                   dashArray: '4 4', interactive: false }).addTo(state.groups.selection);
    }
    L.polyline([toLL(pa), toLL(pb)], { renderer, color: '#ffea00', weight: 9, opacity: 0.85,
                                       interactive: false }).addTo(state.groups.selection);
  }
}

function choice(label, on, action, key) {
  const k = key ? ` <kbd>${key}</kbd>` : '';
  return `<button type="button" class="${on ? 'on' : ''}" data-action="${action}">${label}${k}</button>`;
}

function renderEditor() {
  const body = document.getElementById('editor-body');
  const sel = state.selection;
  if (!sel) {
    body.className = 'muted';
    body.innerHTML = 'Click inside a hex to edit it, or near a hexside to edit that side. <kbd>Esc</kbd> deselects.';
    return;
  }
  body.className = '';
  if (sel.kind === 'hex') {
    const id = sel.id;
    const h = state.hexes.get(id);
    const e = hexOf(id);
    const terrainButtons = Object.entries(TERRAIN)
      .map(([k, t]) => choice(t.label, e.terrain === k, `terrain:${k}`, t.key)).join('');
    const lms = e.landmarks.map((lm, i) => `
      <div class="landmark-row">
        <select data-lm-type="${i}">${Object.entries(LANDMARKS).map(([k, d]) =>
          `<option value="${k}" ${k === lm.type ? 'selected' : ''}>${d.label}</option>`).join('')}</select>
        <input type="text" data-lm-name="${i}" placeholder="name" value="${escapeHtml(lm.name || '')}">
        <button type="button" data-action="lm-remove:${i}" title="Remove">✕</button>
      </div>`).join('');
    const addButtons = Object.entries(LANDMARKS)
      .map(([k, d]) => `<button type="button" data-action="lm-add:${k}">+ ${d.label}</button>`).join('');
    const autoT = TERRAIN[h.t] ? TERRAIN[h.t].label : h.t;
    body.innerHTML = `
      <h3>Hex ${state.mapId}${id} ${e.edited ? '<span class="tag-edited">edited</span>' : ''}</h3>
      <div class="muted">Automatic: ${autoT}${h.u ? ' (uncertain)' : ''}</div>
      <div class="group"><div class="group-title">Terrain</div><div class="choices">${terrainButtons}</div></div>
      <div class="group"><div class="group-title">Landmarks</div>${lms || '<div class="muted">none</div>'}
        <div class="choices" style="margin-top:4px">${addButtons}</div></div>
      <div class="footer">
        <label><input type="checkbox" data-action="reviewed" ${e.reviewed ? 'checked' : ''}> Reviewed <kbd>X</kbd></label>
        <button type="button" data-action="revert" ${e.edited ? '' : 'disabled'}>Revert to automatic <kbd>U</kbd></button>
      </div>`;
  } else {
    const key = sel.key;
    const [ha, hb] = sideHexes(key);
    const [owner, d] = key.split('|');
    const s = sideOf(key);
    const f = s.feature;
    const featureButtons = [
      choice('None', !f, 'feature:none'),
      choice('Ridge', f && f.type === 'ridge', 'feature:ridge', 'G'),
      choice(`Slope ↓${ha}`, f && f.type === 'slope' && f.down === ha, `feature:slope:${ha}`),
      choice(`Slope ↓${hb}`, f && f.type === 'slope' && f.down === hb, `feature:slope:${hb}`),
      choice(`Escarpment ↓${ha}`, f && f.type === 'escarpment' && f.down === ha, `feature:escarpment:${ha}`),
      choice(`Escarpment ↓${hb}`, f && f.type === 'escarpment' && f.down === hb, `feature:escarpment:${hb}`),
    ].join('');
    const has = (k) => s.cross.some((x) => x.k === k);
    const crossButtons = Object.entries(LINES).map(([k, l]) => choice(l.label, has(k), `cross:${k}`, l.key && (l.shift ? '⇧' : '') + l.key.toUpperCase())).join('');
    const edited = !!state.corr.sides[key];
    body.innerHTML = `
      <h3>Hexside ${ha} | ${hb} ${edited ? '<span class="tag-edited">edited</span>' : ''}</h3>
      <div class="muted">${DIR_NAMES[d]} side of ${owner}</div>
      <div class="group"><div class="group-title">River <kbd>V</kbd></div><div class="choices">
        ${choice('None', !s.river, 'river:none')}${choice('Minor', s.river === 'minor', 'river:minor')}${choice('Major', s.river === 'major', 'river:major')}
        ${choice('Wadi', s.wadi, 'wadi', 'W')}</div></div>
      <div class="group"><div class="group-title">Hexside feature <span class="muted">(<kbd>S</kbd> slope, <kbd>E</kbd> escarpment cycle)</span></div>
        <div class="choices">${featureButtons}</div></div>
      <div class="group"><div class="group-title">Crossing the side</div><div class="choices">${crossButtons}</div></div>
      <div class="group"><div class="choices">${choice('Border', s.border, 'border', 'B')}</div></div>
      <div class="footer">
        <button type="button" data-action="clear">Clear side <kbd>Del</kbd></button>
        <button type="button" data-action="revert" ${edited ? '' : 'disabled'}>Revert to automatic <kbd>U</kbd></button>
      </div>`;
  }
}

document.getElementById('editor').addEventListener('click', (ev) => {
  const el = ev.target.closest('[data-action]');
  if (!el || el.tagName === 'INPUT') return;
  runAction(el.dataset.action);
});
document.getElementById('editor').addEventListener('change', (ev) => {
  const el = ev.target;
  if (el.dataset.action === 'reviewed') runAction('reviewed');
  if (el.dataset.lmType !== undefined) {
    const i = +el.dataset.lmType;
    editHex(state.selection.id, (c, e) => { c.landmarks = e.landmarks.map((lm, j) => (j === i ? { ...lm, type: el.value } : lm)); });
  }
  if (el.dataset.lmName !== undefined) {
    const i = +el.dataset.lmName;
    editHex(state.selection.id, (c, e) => {
      c.landmarks = e.landmarks.map((lm, j) => (j === i ? { ...lm, name: el.value.trim() || undefined } : lm));
    }, { keepEditor: true });
  }
});

function runAction(action) {
  const sel = state.selection;
  if (!sel) return;
  const [verb, arg, arg2] = action.split(':');
  if (sel.kind === 'hex') {
    const id = sel.id;
    if (verb === 'terrain') editHex(id, (c) => { c.terrain = arg; });
    else if (verb === 'lm-add') editHex(id, (c, e) => { c.landmarks = [...e.landmarks, { type: arg }]; });
    else if (verb === 'lm-remove') editHex(id, (c, e) => { c.landmarks = e.landmarks.filter((_, j) => j !== +arg); });
    else if (verb === 'reviewed') editHex(id, (c, e) => { c.reviewed = !e.reviewed; });
    else if (verb === 'revert') editHex(id, (c) => { delete c.terrain; delete c.landmarks; });
    return;
  }
  const key = sel.key;
  if (verb === 'river') editSide(key, (s) => { s.river = arg === 'none' ? null : arg; });
  else if (verb === 'wadi') editSide(key, (s) => { s.wadi = !s.wadi; });
  else if (verb === 'border') editSide(key, (s) => { s.border = !s.border; });
  else if (verb === 'feature') {
    editSide(key, (s) => {
      if (arg === 'none') s.feature = null;
      else if (arg === 'ridge') s.feature = s.feature && s.feature.type === 'ridge' ? null : { type: 'ridge' };
      else s.feature = { type: arg, down: arg2 };
    });
  } else if (verb === 'cross') {
    editSide(key, (s) => {
      if (s.cross.some((x) => x.k === arg)) s.cross = s.cross.filter((x) => x.k !== arg);
      else s.cross = LINE_ORDER.filter((k) => k === arg || s.cross.some((x) => x.k === k)).map((k) => ({ k }));
    });
  } else if (verb === 'clear') {
    editSide(key, (s) => { Object.assign(s, normSide({})); });
  } else if (verb === 'revert') {
    pushUndo();
    delete state.corr.sides[key];
    afterEdit([], [key]);
  }
}

// ---------- editing ----------

function pushUndo() {
  state.undo.push(JSON.stringify(state.corr));
  if (state.undo.length > 300) state.undo.shift();
  document.getElementById('undo').disabled = false;
}

function undo() {
  if (!state.undo.length) return;
  state.corr = JSON.parse(state.undo.pop());
  document.getElementById('undo').disabled = !state.undo.length;
  drawAll();
  refreshAfterChange();
}

function editSide(key, fn) {
  pushUndo();
  const s = sideOf(key);
  fn(s);
  const auto = normSide(state.auto.get(key));
  if (sameSide(s, auto)) delete state.corr.sides[key];
  else state.corr.sides[key] = s;
  afterEdit([], [key]);
}

function editHex(id, fn, opts = {}) {
  pushUndo();
  const c = { ...(state.corr.hexes[id] || {}) };
  fn(c, hexOf(id));
  if (c.terrain === state.hexes.get(id).t && !state.hexes.get(id).u) delete c.terrain;
  if (c.landmarks && !c.landmarks.length) delete c.landmarks;
  if (!c.reviewed) delete c.reviewed;
  if (Object.keys(c).length) state.corr.hexes[id] = c; else delete state.corr.hexes[id];
  afterEdit([id], [], opts);
}

function afterEdit(hexIds, sideKeys, opts = {}) {
  for (const id of hexIds) drawHex(id);
  for (const key of sideKeys) drawSide(key);
  drawSelection();
  refreshAfterChange(opts);
}

function refreshAfterChange(opts = {}) {
  if (!opts.keepEditor) renderEditor();
  computeWarnings();
  renderProgress();
  scheduleSave();
  if (state.hover) showInfo(state.hover.id, state.hover.key);
}

// ---------- saving ----------

let saveTimer = null;
function scheduleSave() {
  const status = document.getElementById('save-status');
  status.className = 'muted';
  status.textContent = 'Unsaved changes…';
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, 400);
}

async function save() {
  const status = document.getElementById('save-status');
  const mapId = state.mapId;
  try {
    const res = await fetch(`/api/corrections/${mapId}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(state.corr),
    });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    status.className = 'muted';
    status.textContent = `Saved ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    status.className = 'error';
    status.textContent = `Save failed: ${err.message}`;
  }
}

window.addEventListener('beforeunload', (ev) => {
  if (saveTimer && document.getElementById('save-status').textContent.startsWith('Unsaved')) {
    ev.preventDefault();
    ev.returnValue = '';
  }
});

// ---------- warnings ----------

function computeWarnings() {
  const out = [];
  const hexes = state.hexes;

  for (const id of hexes.keys()) {
    const e = hexOf(id);
    if (e.uncertain) out.push({ type: 'uncertain', hex: id, text: `${id} uncertain terrain (${TERRAIN[e.terrain]?.label || e.terrain})` });
  }

  // Dead ends: a line family crossing exactly one side of a hex that has no
  // landmark and isn't on the map edge.
  for (const id of hexes.keys()) {
    const e = hexOf(id);
    if (e.landmarks.length) continue;
    if (DIRS.some((d) => !hexes.has(neighbourId(id, d)))) continue;
    const counts = {};
    for (const d of DIRS) {
      const s = sideOf(sideKey(id, d));
      for (const x of s.cross) counts[LINE_FAMILY[x.k]] = (counts[LINE_FAMILY[x.k]] || 0) + 1;
    }
    for (const fam of ['road', 'track', 'railroad']) {
      if (counts[fam] === 1) {
        out.push({ type: 'dead-end', hex: id, text: `${id} ${fam} dead end` });
      }
    }
  }

  // River ends: at each end of a river side, another river side should meet
  // it, unless the corner touches the sea or the map edge.
  const seen = new Set();
  for (const key of allSideKeys()) {
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
        out.push({ type: 'river-end', hex: h, side: key, text: `${h}|${n} river ends (corner ${x})` });
      }
    }
  }

  const order = { 'dead-end': 0, 'river-end': 1, uncertain: 2 };
  out.sort((a, b) => order[a.type] - order[b.type] || a.hex.localeCompare(b.hex));
  state.warnings = out;
  renderWarnings();
}

function visibleWarnings() {
  return state.warnings.filter((w) => state.warnTypes[w.type]);
}

function renderWarnings() {
  const counts = { 'dead-end': 0, 'river-end': 0, uncertain: 0 };
  for (const w of state.warnings) counts[w.type]++;
  const names = { 'dead-end': 'Dead ends', 'river-end': 'River ends', uncertain: 'Uncertain terrain' };
  document.getElementById('warn-filters').innerHTML = Object.entries(names).map(([k, n]) =>
    `<label><input type="checkbox" data-warn="${k}" ${state.warnTypes[k] ? 'checked' : ''}> ${n} (${counts[k]})</label>`).join('');
  const vis = visibleWarnings();
  document.getElementById('warn-count').textContent = `${vis.length}`;
  const shown = vis.slice(0, 400);
  document.getElementById('warn-list').innerHTML = shown.map((w, i) =>
    `<li data-warn-index="${i}" class="${i === state.warnIndex ? 'current' : ''}">${escapeHtml(w.text)}</li>`).join('')
    + (vis.length > shown.length ? `<li class="muted">… ${vis.length - shown.length} more</li>` : '');
}

function gotoWarning(i) {
  const vis = visibleWarnings();
  if (!vis.length) return;
  state.warnIndex = ((i % vis.length) + vis.length) % vis.length;
  const w = vis[state.warnIndex];
  const h = state.hexes.get(w.hex);
  map.flyTo(toLL(h.c), Math.max(map.getZoom(), state.zmax - 1.5), { duration: 0.4 });
  select(w.side ? { kind: 'side', key: w.side } : { kind: 'hex', id: w.hex });
  renderWarnings();
  const li = document.querySelector(`#warn-list li[data-warn-index="${state.warnIndex}"]`);
  if (li) li.scrollIntoView({ block: 'nearest' });
}

document.getElementById('warn-list').addEventListener('click', (ev) => {
  const li = ev.target.closest('[data-warn-index]');
  if (li) gotoWarning(+li.dataset.warnIndex);
});
document.getElementById('warn-filters').addEventListener('change', (ev) => {
  const k = ev.target.dataset.warn;
  if (k) { state.warnTypes[k] = ev.target.checked; state.warnIndex = -1; renderWarnings(); }
});
document.getElementById('warn-next').addEventListener('click', () => gotoWarning(state.warnIndex + 1));

function renderProgress() {
  const total = state.hexes.size;
  const reviewed = [...state.hexes.keys()].filter((id) => state.corr.hexes[id]?.reviewed).length;
  const edits = Object.keys(state.corr.sides).length
    + Object.values(state.corr.hexes).filter((c) => c.terrain || c.landmarks).length;
  document.getElementById('progress').textContent =
    `Reviewed ${reviewed} / ${total} hexes · ${edits} edits`;
}

// ---------- hover info ----------

function sideSummary(s) {
  const parts = [];
  if (s.river) parts.push(`${s.river} river`);
  if (s.wadi) parts.push('wadi');
  if (s.feature) parts.push(s.feature.down ? `${s.feature.type} (down to ${s.feature.down})` : s.feature.type);
  for (const x of s.cross) parts.push(`${LINES[x.k].label.toLowerCase()} crossing`);
  if (s.border) parts.push('border');
  return parts.join(', ');
}

function showInfo(id, nearKey) {
  const h = state.hexes.get(id);
  if (!h) return;
  const e = hexOf(id);
  const t = TERRAIN[e.terrain] ? TERRAIN[e.terrain].label : e.terrain;
  const mix = Object.entries(h.mix)
    .filter(([k]) => !['dark', 'blue'].includes(k))
    .sort((p, q) => q[1] - p[1])
    .map(([k, v]) => `${k} ${Math.round(v * 100)}%`).join(', ');
  const rows = DIRS.map((d) => {
    const key = sideKey(id, d);
    const txt = sideSummary(sideOf(key));
    const mark = key === nearKey ? ' style="background:#fff7b0"' : '';
    return txt || key === nearKey ? `<tr${mark}><td>${DIR_NAMES[d]}</td><td>${txt || '<span class="muted">–</span>'}</td></tr>` : '';
  }).join('');
  const lm = e.landmarks.map((l) => `${LANDMARKS[l.type]?.label || l.type}${l.name ? ` “${escapeHtml(l.name)}”` : ''}`).join(', ');
  document.getElementById('info-body').innerHTML = `
    <div class="hexid">${state.mapId}${id}${e.reviewed ? ' <span style="color:#1b8a3a">✓</span>' : ''}</div>
    <table>
      <tr><td>Terrain</td><td>${t}${e.uncertain ? ' <b style="color:#d97700">(uncertain)</b>' : ''}${h.coastal ? ', coastal' : ''}</td></tr>
      ${lm ? `<tr><td>Landmarks</td><td>${lm}</td></tr>` : ''}
      <tr><td>Colours</td><td class="muted">${mix || '–'}</td></tr>
      ${rows || '<tr><td>Hexsides</td><td class="muted">nothing</td></tr>'}
    </table>`;
}

// ---------- legend ----------

function buildLegend() {
  const rows = [];
  for (const t of Object.values(TERRAIN)) {
    if (t.color) rows.push(`<div class="legend-row"><span class="swatch" style="background:${t.color};opacity:.6"></span>${t.label}</div>`);
  }
  rows.push(`<div class="legend-row"><span class="swatch dashed" style="border-color:#ff8c00"></span>Uncertain terrain</div>`);
  rows.push(`<div class="legend-row"><span class="swatch line" style="background:${RIVER};height:6px"></span>Major river</div>`);
  rows.push(`<div class="legend-row"><span class="swatch line" style="background:${RIVER};height:2px"></span>Minor river</div>`);
  rows.push(`<div class="legend-row"><span class="swatch dashed" style="border-color:${WADI}"></span>Wadi</div>`);
  for (const [k, c] of Object.entries(FEATURE)) {
    rows.push(`<div class="legend-row"><span class="swatch line" style="background:${c}"></span>${k[0].toUpperCase() + k.slice(1)} (tick = down side)</div>`);
  }
  rows.push(`<div class="legend-row"><span class="swatch dashed" style="border-color:${BORDER}"></span>Border</div>`);
  for (const l of Object.values(LINES)) {
    rows.push(`<div class="legend-row"><span class="swatch cross" style="color:${l.color}">✕</span>${l.label} crossing</div>`);
  }
  for (const d of Object.values(LANDMARKS)) {
    rows.push(`<div class="legend-row"><span class="swatch" style="background:${d.color}"></span>${d.letter} ${d.label}</div>`);
  }
  rows.push(`<div class="legend-row"><span class="swatch dot" style="border-color:#1b8a3a;background:#3ccf6a"></span>Reviewed hex</div>`);
  rows.push(`<div class="legend-row"><span class="swatch dot" style="border-color:#b35900;background:#ffb04a"></span>Edited by hand</div>`);
  rows.push(`<div class="legend-keys">
    <div><b>Keys</b> (with a hexside selected)</div>
    <div><kbd>R</kbd> road, <kbd>T</kbd> track, <kbd>L</kbd> railroad crossing; <kbd>Shift</kbd>+<kbd>R</kbd> / <kbd>Shift</kbd>+<kbd>L</kbd> unfinished road / railroad</div>
    <div><kbd>V</kbd> river none/minor/major, <kbd>W</kbd> wadi, <kbd>B</kbd> border</div>
    <div><kbd>G</kbd> ridge, <kbd>S</kbd> slope, <kbd>E</kbd> escarpment (repeat to flip/clear)</div>
    <div><kbd>Del</kbd> clear side, <kbd>U</kbd> revert to automatic</div>
    <div><b>Keys</b> (with a hex selected)</div>
    <div><kbd>1</kbd>–<kbd>9</kbd>, <kbd>0</kbd> terrain, <kbd>X</kbd> reviewed, <kbd>U</kbd> revert</div>
    <div><b>Always</b>: <kbd>N</kbd> next warning, <kbd>Ctrl</kbd>+<kbd>Z</kbd> undo, <kbd>Esc</kbd> deselect</div>
  </div>`);
  document.getElementById('legend-body').innerHTML = rows.join('');
}

// ---------- keyboard ----------

function cycleFeature(key, type) {
  const [ha, hb] = sideHexes(key);
  editSide(key, (s) => {
    const f = s.feature;
    if (!f || f.type !== type) s.feature = { type, down: ha };
    else if (f.down === ha) s.feature = { type, down: hb };
    else s.feature = null;
  });
}

document.addEventListener('keydown', (ev) => {
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'z') { ev.preventDefault(); undo(); return; }
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const k = ev.key.toLowerCase();
  if (k === 'escape') { select(null); return; }
  if (k === 'n') { gotoWarning(state.warnIndex + 1); return; }
  const sel = state.selection;
  if (!sel) return;
  if (sel.kind === 'hex') {
    const terr = Object.entries(TERRAIN).find(([, t]) => t.key === ev.key);
    if (terr) runAction(`terrain:${terr[0]}`);
    else if (k === 'x') runAction('reviewed');
    else if (k === 'u') runAction('revert');
    else return;
  } else {
    const line = Object.entries(LINES).find(([, l]) => l.key === k && !!l.shift === ev.shiftKey);
    if (line) runAction(`cross:${line[0]}`);
    else if (k === 'v') {
      const r = sideOf(sel.key).river;
      runAction(`river:${r === null ? 'minor' : r === 'minor' ? 'major' : 'none'}`);
    } else if (k === 'w') runAction('wadi');
    else if (k === 'b') runAction('border');
    else if (k === 'g') runAction('feature:ridge');
    else if (k === 's') cycleFeature(sel.key, 'slope');
    else if (k === 'e') cycleFeature(sel.key, 'escarpment');
    else if (k === 'delete' || k === 'backspace') runAction('clear');
    else if (k === 'u') runAction('revert');
    else return;
  }
  ev.preventDefault();
});

// ---------- map loading and navigation ----------

async function loadMap(id, view) {
  const res = await fetch(`/api/map/${id}`);
  if (!res.ok) { alert(`Could not load map ${id}: ${res.status}`); return; }
  const data = await res.json();
  if (state.tiles) state.tiles.remove();
  state.mapId = id;
  state.data = data;
  state.zmax = data.zmax;
  state.hexes = new Map(data.hexes.map((h) => [h.id, h]));
  state.auto = new Map(Object.entries(data.sides));
  state.corr = data.corrections || { hexes: {}, sides: {} };
  state.corr.hexes = state.corr.hexes || {};
  state.corr.sides = state.corr.sides || {};
  state.undo = [];
  document.getElementById('undo').disabled = true;
  state.selection = null;
  state.hover = null;
  state.warnIndex = -1;

  const bounds = L.latLngBounds(toLL([0, data.height]), toLL([data.width, 0]));
  state.tiles = L.tileLayer(`/tiles/${id}/{z}/{x}/{y}.jpg`, {
    tileSize: 256, minZoom: 0, maxNativeZoom: data.zmax, maxZoom: data.zmax + 2,
    noWrap: true, bounds, keepBuffer: 4,
  }).addTo(map);
  map.setMaxZoom(data.zmax + 2);
  map.setMaxBounds(bounds.pad(0.15));
  buildStaticLayers();
  drawAll();
  applyLayerToggles();
  computeWarnings();
  renderProgress();
  renderEditor();
  document.getElementById('save-status').textContent = '';

  document.getElementById('map-select').value = id;
  if (view && view.x != null) map.setView(toLL([view.x, view.y]), view.z);
  else map.fitBounds(bounds);
  if (view && view.sel) {
    const ok = view.sel.kind === 'hex' ? state.hexes.has(view.sel.id) : sideExists(view.sel.key);
    if (ok) select(view.sel);
  }
}

function gotoHex(text) {
  const msg = document.getElementById('goto-msg');
  msg.textContent = '';
  const m = text.trim().toUpperCase().match(/^([A-E])?\s*(\d{4})$/);
  if (!m) { msg.textContent = 'Use a 4-digit hex number, optionally with the map letter (E3002).'; return; }
  const go = () => {
    const h = state.hexes.get(m[2]);
    if (!h) { msg.textContent = `Hex ${m[2]} is not on map ${state.mapId}.`; return; }
    map.flyTo(toLL(h.c), Math.max(map.getZoom(), state.zmax - 1), { duration: 0.6 });
    select({ kind: 'hex', id: h.id });
    showInfo(h.id, null);
  };
  if (m[1] && m[1] !== state.mapId) loadMap(m[1]).then(go); else go();
}

// Position and selection in the URL: #E/x/y/zoom[/3002 or /3002.E] (scan
// pixels), so a reload returns here and a link can point at a hex or side.
function writeHash() {
  if (!state.mapId) return;
  const p = fromLL(map.getCenter());
  const sel = state.selection;
  const token = !sel ? '' : sel.kind === 'hex' ? `/${sel.id}` : `/${sel.key.replace('|', '.')}`;
  history.replaceState(null, '', `#${state.mapId}/${Math.round(p.x)}/${Math.round(p.y)}/${map.getZoom()}${token}`);
}

function readHash() {
  const m = location.hash.match(/^#([A-E])(?:\/(\d+)\/(\d+)\/([\d.]+)(?:\/(\d{4})(?:\.(E|NE|NW))?)?)?/);
  if (!m) return null;
  const view = m[2] ? { id: m[1], x: +m[2], y: +m[3], z: +m[4] } : { id: m[1] };
  if (m[5]) view.sel = m[6] ? { kind: 'side', key: `${m[5]}|${m[6]}` } : { kind: 'hex', id: m[5] };
  return view;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

// ---------- start ----------

async function start() {
  buildLegend();
  const maps = await (await fetch('/api/maps')).json();
  const sel = document.getElementById('map-select');
  for (const m of maps) {
    const o = document.createElement('option');
    o.value = m.id;
    o.textContent = m.hasData ? `Map ${m.id}` : `Map ${m.id} (no data yet)`;
    o.disabled = !m.hasData;
    sel.appendChild(o);
  }
  sel.addEventListener('change', () => loadMap(sel.value));
  document.getElementById('goto').addEventListener('submit', (e) => {
    e.preventDefault();
    gotoHex(document.getElementById('goto-hex').value);
  });
  document.getElementById('undo').addEventListener('click', undo);
  for (const box of document.querySelectorAll('#layers input[data-layer]')) {
    box.addEventListener('change', applyLayerToggles);
  }
  document.getElementById('opacity').addEventListener('change', (e) => {
    state.opacity = e.target.value / 100;
    drawAll();
  });
  map.on('moveend', writeHash);

  const view = readHash();
  const first = (view && maps.find((m) => m.id === view.id && m.hasData)) ? view.id
    : (maps.find((m) => m.hasData) || {}).id;
  if (first) await loadMap(first, view && view.id === first ? view : null);
}

start();
