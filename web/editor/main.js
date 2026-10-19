// CNA map review and correction.
//
// The server sends one map section's automatic extraction (hexes with their
// corners in scan pixels, hexsides keyed "HHHH|D" by the hex owning them as
// its E, NE or NW side) plus the hand corrections. What is shown and edited is
// the automatic data with the corrections laid over it; only the corrections
// are saved back, to data/map/corrections/<MAP>.json.
//
// Leaflet's CRS.Simple maps scan pixels to lat/lng at the scan's native zoom.

import { BORDER, FEATURES, LANDMARKS, LINES, LINE_ORDER, RIVER, TERRAIN, WADI } from '../shared/vocab.js';
import { DIRS, DIR_NAMES, SIDE_CORNERS, hexOf as layHex, normSide, sameSide, sideHexes, sideKey, sideSummary } from '../shared/hex.js';
import { escapeHtml } from '../shared/util.js';
import { JoinedLayer, drawLandmarks, drawSideFeatures, drawTerrain } from '../shared/draw.js';
import { WARNING_TYPES, computeWarnings } from './warnings.js';

// ---------- hex helpers ----------

// On the joined map (ALL) ids are RR plus the column counted from Map A's west
// edge; each hex carries its section number(s) as label (and also).
const label = (id) => state.hexes.get(id)?.label || `${state.mapId}${id}`;
const alsoText = (id) => {
  const also = state.hexes.get(id)?.also;
  return also && also.length ? ` <span class="muted">= ${also.join(' = ')}</span>` : '';
};

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

const UNDO_LIMIT = 1000;

const state = {
  mapId: null, data: null, zmax: 6, tiles: null,
  hexes: new Map(),        // id -> {id, c, p, t, u, coastal, mix}
  auto: new Map(),         // side key -> automatic side
  corr: { hexes: {}, sides: {} },
  groups: {},              // layer name -> L.layerGroup
  hexLayers: new Map(),    // hex id -> [layers]
  sideLayers: new Map(),   // side key -> [layers]
  selection: null,         // {kind: 'hex', id} | {kind: 'side', key}
  hover: null,
  opacity: 1,
  undo: [],                // [{kind: 'hexes'|'sides', key, before}], the correction before each edit
  warnings: [],
  warnIndex: -1,
  warnTypes: Object.fromEntries(Object.keys(WARNING_TYPES).map((k) => [k, true])),
};

const toLL = (p) => map.unproject(L.point(p[0], p[1]), state.zmax);
const fromLL = (ll) => map.project(ll, state.zmax);

// ---------- effective data (automatic + corrections) ----------

const sideOf = (key) => normSide(state.corr.sides[key] || state.auto.get(key));

function hexOf(id) {
  const h = state.hexes.get(id);
  const c = state.corr.hexes[id];
  return { ...layHex({ terrain: h.t, uncertain: h.u }, c), edited: !!(c && (c.terrain || (c.landmarks && c.landmarks.length))) };
}

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
  const ctx = { toLL, renderer, op, add };
  drawTerrain(ctx, ring, e.terrain);
  if (e.uncertain) {
    add(L.polygon(ring, { renderer, color: '#ff8c00', weight: 2, dashArray: '6 5', opacity: 0.9 * op,
                          fill: false, interactive: false }), 'uncertain');
  }
  drawLandmarks(ctx, h.c, e.landmarks);
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
  const op = state.opacity;
  const out = [];
  const add = (layer, group) => { layer.addTo(state.groups[group]); out.push(layer); };
  const down = s.feature && s.feature.down && state.hexes.get(s.feature.down);
  drawSideFeatures({ toLL, renderer, op, add }, s, pa, pb, down && down.c);
  if (state.corr.sides[key]) {
    const mid = [(pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2];
    add(L.circleMarker(toLL(mid), { renderer, radius: 3, color: '#b35900', weight: 1,
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

function choice(text, on, action, key) {
  const k = key ? ` <kbd>${key}</kbd>` : '';
  return `<button type="button" class="${on ? 'on' : ''}" data-action="${action}">${text}${k}</button>`;
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
      <h3>Hex ${label(id)}${alsoText(id)} ${e.edited ? '<span class="tag-edited">edited</span>' : ''}</h3>
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
      choice(`Slope ↓${label(ha)}`, f && f.type === 'slope' && f.down === ha, `feature:slope:${ha}`),
      choice(`Slope ↓${label(hb)}`, f && f.type === 'slope' && f.down === hb, `feature:slope:${hb}`),
      choice(`Escarpment ↓${label(ha)}`, f && f.type === 'escarpment' && f.down === ha, `feature:escarpment:${ha}`),
      choice(`Escarpment ↓${label(hb)}`, f && f.type === 'escarpment' && f.down === hb, `feature:escarpment:${hb}`),
    ].join('');
    const has = (k) => s.cross.some((x) => x.k === k);
    const crossButtons = Object.entries(LINES).map(([k, l]) => choice(l.label, has(k), `cross:${k}`, l.key && (l.shift ? '⇧' : '') + l.key.toUpperCase())).join('');
    const edited = !!state.corr.sides[key];
    body.innerHTML = `
      <h3>Hexside ${label(ha)} | ${label(hb)} ${edited ? '<span class="tag-edited">edited</span>' : ''}</h3>
      <div class="muted">${DIR_NAMES[d]} side of ${label(owner)}</div>
      <div class="group"><div class="group-title">River or wadi <kbd>V</kbd> <span class="muted">(one of them)</span></div><div class="choices">
        ${choice('None', !s.river && !s.wadi, 'river:none')}${choice('Minor river', s.river === 'minor' && !s.wadi, 'river:minor')}${choice('Major river', s.river === 'major' && !s.wadi, 'river:major')}${choice('Wadi', s.wadi && !s.river, 'river:wadi', 'W')}</div></div>
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
  // River and wadi are one choice: a hexside is at most one of them.
  if (verb === 'river') {
    editSide(key, (s) => {
      s.wadi = arg === 'wadi';
      s.river = arg === 'minor' || arg === 'major' ? arg : null;
    });
  }
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
    pushUndo('sides', key);
    delete state.corr.sides[key];
    afterEdit([], [key]);
  }
}

// ---------- editing ----------

// Each edit changes one hex's or one side's correction; undo puts back what it was.
function pushUndo(kind, key) {
  const before = state.corr[kind][key];
  state.undo.push({ kind, key, before: before === undefined ? undefined : structuredClone(before) });
  if (state.undo.length > UNDO_LIMIT) state.undo.shift();
  document.getElementById('undo').disabled = false;
}

function undo() {
  const step = state.undo.pop();
  if (!step) return;
  const { kind, key, before } = step;
  if (before === undefined) delete state.corr[kind][key]; else state.corr[kind][key] = before;
  document.getElementById('undo').disabled = !state.undo.length;
  afterEdit(kind === 'hexes' ? [key] : [], kind === 'sides' ? [key] : []);
}

function editSide(key, fn) {
  pushUndo('sides', key);
  const s = sideOf(key);
  fn(s);
  if (sameSide(s, state.auto.get(key))) delete state.corr.sides[key];
  else state.corr.sides[key] = normSide(s);
  afterEdit([], [key]);
}

function editHex(id, fn, opts = {}) {
  pushUndo('hexes', id);
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
  if (!opts.keepEditor) renderEditor();
  refreshWarnings();
  renderProgress();
  scheduleSave();
  if (state.hover) showInfo(state.hover.id, state.hover.key);
}

// ---------- saving ----------

// Every edit bumps seq; a save sends the corrections as they are then. Saves
// go one at a time, in order, so an older one never lands after a newer one.
const saving = { seq: 0, sent: 0, saved: 0, timer: null, chain: Promise.resolve() };
const unsaved = () => saving.saved !== saving.seq;

function setStatus(text, error = false) {
  const status = document.getElementById('save-status');
  status.className = error ? 'error' : 'muted';
  status.textContent = text;
}

function scheduleSave() {
  saving.seq++;
  setStatus('Unsaved changes…');
  clearTimeout(saving.timer);
  saving.timer = setTimeout(saveNow, 400);
}

// Send anything not yet sent; resolves once the server has it (or refused it).
function saveNow() {
  clearTimeout(saving.timer);
  saving.timer = null;
  if (saving.sent !== saving.seq) {
    const seq = saving.seq, mapId = state.mapId, body = JSON.stringify(state.corr);
    saving.sent = seq;
    saving.chain = saving.chain.then(() => put(seq, mapId, body));
  }
  return saving.chain;
}

async function put(seq, mapId, body) {
  try {
    const res = await fetch(`/api/corrections/${mapId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    saving.saved = Math.max(saving.saved, seq);
    if (!unsaved()) setStatus(`Saved ${new Date().toLocaleTimeString()}`);
  } catch (err) {
    // Still unsaved: leaving the page warns, and the next edit sends it again.
    if (saving.sent === seq) saving.sent = saving.saved;
    setStatus(`Save failed: ${err.message}`, true);
  }
}

window.addEventListener('beforeunload', (ev) => {
  if (unsaved()) {
    saveNow();
    ev.preventDefault();
    ev.returnValue = '';
  }
});

// ---------- warnings ----------

function refreshWarnings() {
  state.warnings = computeWarnings({ hexes: state.hexes, hexOf, sideOf, sideExists, allSideKeys, label });
  renderWarnings();
}

function visibleWarnings() {
  return state.warnings.filter((w) => state.warnTypes[w.type]);
}

function renderWarnings() {
  const counts = Object.fromEntries(Object.keys(WARNING_TYPES).map((k) => [k, 0]));
  for (const w of state.warnings) counts[w.type]++;
  document.getElementById('warn-filters').innerHTML = Object.entries(WARNING_TYPES).map(([k, n]) =>
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
    <div class="hexid">${label(id)}${alsoText(id)}${e.reviewed ? ' <span style="color:#1b8a3a">✓</span>' : ''}</div>
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
  for (const f of Object.values(FEATURES)) {
    rows.push(`<div class="legend-row"><span class="swatch line" style="background:${f.color}"></span>${f.label}${f.downhill ? ' (tick = down side)' : ''}</div>`);
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
    <div><kbd>V</kbd> none / minor river / major river / wadi, <kbd>W</kbd> wadi on/off, <kbd>B</kbd> border</div>
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
      const s = sideOf(sel.key);
      const cur = s.wadi && !s.river ? 'wadi' : s.river || 'none';
      const next = { none: 'minor', minor: 'major', major: 'wadi', wadi: 'none' }[cur];
      runAction(`river:${next}`);
    } else if (k === 'w') {
      const s = sideOf(sel.key);
      runAction(`river:${s.wadi && !s.river ? 'none' : 'wadi'}`);
    }
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
  // Finish saving this map's edits before its corrections are replaced.
  await saveNow();
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

  state.byLabel = new Map();
  for (const h of data.hexes) {
    for (const l of [h.label, ...(h.also || [])]) if (l) state.byLabel.set(l, h.id);
  }

  const bounds = L.latLngBounds(toLL([0, data.height]), toLL([data.width, 0]));
  const tileOpts = { tileSize: 256, minZoom: 0, maxNativeZoom: data.zmax, maxZoom: data.zmax + 2,
                     noWrap: true, bounds, keepBuffer: 4 };
  state.tiles = (data.sections ? new JoinedLayer({ ...tileOpts, sections: data.sections, zmax: data.zmax })
    : L.tileLayer(`/tiles/${data.image}/{z}/{x}/{y}.jpg?v=${data.v}`, tileOpts)).addTo(map);
  map.setMaxZoom(data.zmax + 2);
  map.setMaxBounds(bounds.pad(0.15));
  buildStaticLayers();
  drawAll();
  applyLayerToggles();
  refreshWarnings();
  renderProgress();
  renderEditor();
  // The server keeps the copies of shared hexes in sync on start and on
  // every save; a difference here means a corrections file changed since.
  setStatus(data.unsynced ? `${data.unsynced} corrections differ between the sections' copies of shared hexes; `
    + 'the next edit here, a server restart or python -m cna.sync makes them agree.' : '');

  document.getElementById('map-select').value = id;
  if (view && view.x != null) map.setView(toLL([view.x, view.y]), view.z);
  else if (data.focus) map.fitBounds(L.latLngBounds(toLL(data.focus.slice(0, 2)), toLL(data.focus.slice(2))));
  else map.fitBounds(bounds);
  if (view && view.sel) {
    const ok = view.sel.kind === 'hex' ? state.hexes.has(view.sel.id) : sideExists(view.sel.key);
    if (ok) select(view.sel);
  }
}

function gotoHex(text) {
  const msg = document.getElementById('goto-msg');
  msg.textContent = '';
  const m = text.trim().toUpperCase().match(/^([A-EM])?\s*(\d{4})$/);
  if (!m) { msg.textContent = 'Use a 4-digit hex number, optionally with the map letter (E3002).'; return; }
  const joinedMap = state.mapId === 'ALL';
  if (joinedMap && !m[1]) { msg.textContent = 'On all maps, add the map letter (E3002).'; return; }
  const go = () => {
    const h = state.hexes.get(joinedMap ? state.byLabel.get(m[1] + m[2]) : m[2]);
    if (!h) { msg.textContent = `Hex ${m[1] || state.mapId}${m[2]} is not on the map.`; return; }
    map.flyTo(toLL(h.c), Math.max(map.getZoom(), state.zmax - 1), { duration: 0.6 });
    select({ kind: 'hex', id: h.id });
    showInfo(h.id, null);
  };
  if (m[1] && m[1] !== state.mapId && !joinedMap) loadMap(m[1]).then(go); else go();
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
  const m = location.hash.match(/^#(ALL|[A-EM])(?:\/(\d+)\/(\d+)\/([\d.]+)(?:\/(\d{4,5})(?:\.(E|NE|NW))?)?)?/);
  if (!m) return null;
  const view = m[2] ? { id: m[1], x: +m[2], y: +m[3], z: +m[4] } : { id: m[1] };
  if (m[5]) view.sel = m[6] ? { kind: 'side', key: `${m[5]}|${m[6]}` } : { kind: 'hex', id: m[5] };
  return view;
}

// ---------- start ----------

async function start() {
  buildLegend();
  const maps = await (await fetch('/api/maps')).json();
  const sel = document.getElementById('map-select');
  for (const m of maps) {
    const o = document.createElement('option');
    o.value = m.id;
    const name = { ALL: 'All maps', M: 'Malta' }[m.id] || `Map ${m.id}`;
    o.textContent = m.hasData ? name : `${name} (no data yet)`;
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
