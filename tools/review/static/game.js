// CNA game: the title screen, scenario selection, and the board with a
// scenario's initial deployment.
//
// The server sends the joined map with the hand corrections already applied
// (/api/game/map), the printed off-map boxes as zones, and the scenarios
// (/api/scenarios, from data/scenarios.json). Rulebook cases quoted in the
// briefing come from the local transcription (/api/rules/<case>) when it is
// there. Map drawing is shared with the editor (common.js).

const SIDES = { axis: 'Axis', cw: 'Commonwealth' };
const NATIONS = {
  it: 'Italian', de: 'German', uk: 'British', au: 'Australian', nz: 'New Zealand', sa: 'South African',
  in: 'Indian', fr: 'Free French', pl: 'Polish', cz: 'Czechoslovak', gr: 'Greek',
};
const ZONE_KINDS = { offmap: 'Off-map box', transit: 'In transit', holding: 'Holding box', airbase: 'Off-map air base' };
const LAYERS = ['terrain', 'rivers', 'features', 'crossings', 'landmarks'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const WEEKS = ['I', 'II', 'III', 'IV'];

// Game-Turn 1 is the third week of September 1940; every month has four turns.
function turnDate(t) {
  const k = t + 1;
  const m = 8 + Math.floor(k / 4);
  return `${MONTHS[m % 12]} ${WEEKS[k % 4]} ${1940 + Math.floor(m / 12)}`;
}
const turnText = (p) => `Game-Turn ${p.turn}, OpStage ${p.stage} (${turnDate(p.turn)})`;

const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};

const state = {
  catalog: null,            // /api/scenarios
  board: null,              // /api/game/map once loaded
  hexes: new Map(),         // id -> hex
  byLabel: new Map(),       // A4827 etc. -> id
  zones: new Map(),         // id -> zone
  holdFor: new Map(),       // hex id -> holding box zone id
  groups: {},
  scenario: null,
  stacks: new Map(),        // 'h:<id>' | 'z:<id>' -> [{entry, unit}]
  pool: [],                 // deployments the player places
  markers: new Map(),       // stack key -> marker
  selection: null,          // {kind: 'hex'|'zone'|'pool', id}
  side: 'axis',
};

// ---------- small helpers ----------

const $ = (sel) => document.querySelector(sel);
const label = (id) => state.hexes.get(id)?.label || id;
const hexOfLabel = (l) => state.byLabel.get(l.replace(/\s+/g, ''));

function inline(s) {
  return escapeHtml(s.replace(/\\\*/g, '\u0001'))
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/\*(.+?)\*/g, '<i>$1</i>')
    .replace(/\u0001/g, '*');
}

// Just enough Markdown for the rulebook transcription: headings, tables, paragraphs.
function markdown(text) {
  const out = [];
  let table = null, para = [];
  const flushPara = () => { if (para.length) out.push(`<p>${inline(para.join(' '))}</p>`); para = []; };
  const flushTable = () => {
    if (!table) return;
    const rows = table.filter((r) => !/^\|[\s|:-]+\|$/.test(r));
    const cells = (r) => r.replace(/^\||\|$/g, '').split('|').map((c) => inline(c.trim()));
    out.push(`<table>${rows.map((r, i) => `<tr>${cells(r).map((c) => (i ? `<td>${c}</td>` : `<th>${c}</th>`)).join('')}</tr>`).join('')}</table>`);
    table = null;
  };
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (line.startsWith('|')) { flushPara(); (table = table || []).push(line); continue; }
    flushTable();
    if (!line) { flushPara(); continue; }
    const h = line.match(/^#+\s+(.*)/);
    if (h) { flushPara(); out.push(`<h5>${inline(h[1])}</h5>`); continue; }
    para.push(line);
  }
  flushPara();
  flushTable();
  return `<div class="md">${out.join('')}</div>`;
}

const ruleCache = new Map();
function fetchRule(c) {
  if (!ruleCache.has(c)) {
    ruleCache.set(c, fetch(`/api/rules/${c}`).then((r) => (r.ok ? r.json() : null)).then((j) => j && j.text).catch(() => null));
  }
  return ruleCache.get(c);
}
async function fillRule(el, c) {
  const text = await fetchRule(c);
  el.classList.remove('muted');
  el.innerHTML = text ? markdown(text)
    : `<p class="muted">Case ${c} is in the rulebook. (Its text is shown here when the rulebook transcription is in the project folder.)</p>`;
}

// ---------- units ----------

const unitNat = (u, e) => u.nat || e.nat || (e.side === 'axis' ? 'it' : 'uk');
const BRITISH_STYLE = new Set(['uk', 'au', 'nz', 'sa', 'in', 'fr', 'pl', 'cz', 'gr']);

function unitType(u) {
  if (u.type) return u.type;
  const n = u.name;
  if (/\b(Arty|RHA|Artillery|AR)\b/.test(n)) return 'Ar';
  if (/\b(AT|Anti-?tank|Panzerjaeger)\b/i.test(n)) return 'AT';
  if (/\bAA\b|Flak/.test(n)) return 'AA';
  if (/RTR|Panzer|Armou?red|Tank/.test(n)) return 'T';
  if (/Recce|Aufklarungs|Hussars|Cavalry|Dragoon|Lancers|Armou?red Car/.test(n)) return 'R';
  return 'I';
}

// Echelon mark above the unit symbol.
function unitSize(u, nat) {
  const n = u.name;
  if (/\bDiv(ision)?\b/.test(n)) return 'XX';
  if (/\b(Bde|Brigade|Support Group|Raggruppamento)\b/.test(n)) return 'X';
  if (/\b(Coy|Company|Det|Squadron)\b/.test(n)) return 'I';
  if (/\b(Bn|Battalion|RTR|Hussars|RHA|Lancers|Dragoon)\b/.test(n)) return 'II';
  if (/\b(Regt|Regiment|Corps Arty)\b/.test(n)) return BRITISH_STYLE.has(nat) ? 'II' : 'III';
  return '';
}
const SIZE_RANK = { XX: 5, X: 4, III: 3, II: 2, I: 1, '': 0 };

// A NATO-style unit symbol, 60 x 36.
function unitSymbol(type) {
  const box = '<rect x="2" y="2" width="56" height="32" fill="none" stroke="currentColor" stroke-width="3"/>';
  const marks = {
    I: '<path d="M2 2L58 34M58 2L2 34" stroke="currentColor" stroke-width="3"/>',
    T: '<ellipse cx="30" cy="18" rx="18" ry="9" fill="none" stroke="currentColor" stroke-width="3"/>',
    R: '<path d="M2 34L58 2" stroke="currentColor" stroke-width="3"/>',
    Ar: '<circle cx="30" cy="18" r="6" fill="currentColor"/>',
    AT: '<path d="M8 32L30 6L52 32" fill="none" stroke="currentColor" stroke-width="3"/>',
    AA: '<path d="M8 32Q30 2 52 32" fill="none" stroke="currentColor" stroke-width="3"/>',
    E: '<path d="M14 28V12H46V28M30 12V28" fill="none" stroke="currentColor" stroke-width="3"/>',
    HQ: '<text x="30" y="27" text-anchor="middle" font-size="20" font-weight="700" fill="currentColor">HQ</text>',
    TR: '<text x="30" y="27" text-anchor="middle" font-size="18" font-weight="700" fill="currentColor">REC</text>',
  };
  return `<svg viewBox="0 0 60 36">${box}${marks[type] || ''}</svg>`;
}

function shortName(n) {
  return n.replace(/New Zealand/g, 'NZ').replace(/South African?/g, 'SA').replace(/Australian/g, 'Aus')
    .replace(/Armou?red/g, 'Arm').replace(/Indian/g, 'In').replace(/Infantry|Inf\b/g, 'Inf')
    .replace(/\b(Division|Div|Brigade|Regiment|Battalion)\b\.?/g, '').replace(/\s+/g, ' ').trim();
}

// The counter for one unit, or for a stack shown by its biggest unit.
function counterHtml(items, opts = {}) {
  const top = items.reduce((a, b) => (SIZE_RANK[unitSize(b.unit, unitNat(b.unit, b.entry))]
    > SIZE_RANK[unitSize(a.unit, unitNat(a.unit, a.entry))] ? b : a));
  const { unit, entry } = top;
  const nat = unitNat(unit, entry);
  const second = items.find((x) => x !== top);
  const cls = ['ctr'];
  if (items.length > 1) cls.push('stacked');
  if (opts.flex) cls.push('flex');
  if (opts.sel) cls.push('sel');
  const style = `--nat:var(--n-${nat});--side:var(--${entry.side});${second ? `--nat2:var(--n-${unitNat(second.unit, second.entry)})` : ''}`;
  return `<div class="${cls.join(' ')}" style="${style}" title="${escapeHtml(items.map((x) => x.unit.name).join(', '))}">
    <span class="side-strip"></span>
    <span class="size">${unitSize(unit, nat)}</span>${unitSymbol(unitType(unit))}
    <span class="nm">${escapeHtml(shortName(unit.name))}</span>
    ${items.length > 1 ? `<span class="n">${items.length}</span>` : ''}</div>`;
}

// ---------- deployments ----------

// Where a deployment goes: a hex or zone to draw it at, or the pool.
function resolve(at) {
  if (at.box) return { kind: 'zone', id: at.box, flex: false };
  const ref = at.hex || (at.hexes && at.hexes[0]) || at.near || at.anchor;
  const id = ref && hexOfLabel(ref);
  if (!id) return { kind: 'pool', flex: true };
  return { kind: 'hex', id, flex: !at.hex || !!at.within };
}

function placeText(at) {
  if (at.box) return state.zones.get(at.box)?.name || at.box;
  if (at.area) return at.area;
  const name = at.label ? `${at.label} ` : '';
  if (at.near) return `Within ${at.within} hex${at.within > 1 ? 'es' : ''} of ${name}(${at.near})`;
  if (at.hexes) return `${at.within ? `Within ${at.within} hex of ` : ''}${name}(${at.hexes.join(at.hexes.length > 2 ? ', ' : ' and/or ')})`;
  return at.label ? `${at.label} (${at.hex})` : at.hex;
}

const stackKey = (r) => (r.kind === 'zone' ? `z:${r.id}` : `h:${r.id}`);
// Hexes with a holding box show their counters in the box.
const shownAt = (key) => (key.startsWith('h:') && state.holdFor.has(key.slice(2)) ? `z:${state.holdFor.get(key.slice(2))}` : key);

function deploy(scenario) {
  const setup = state.catalog.setups[scenario.setup];
  state.stacks = new Map();
  state.pool = [];
  setup.deploy.forEach((e, i) => {
    e.index = i;
    e.where = resolve(e.at);
    if (e.where.kind === 'pool') { state.pool.push(e); return; }
    const key = stackKey(e.where);
    if (!state.stacks.has(key)) state.stacks.set(key, []);
    for (const u of e.units) state.stacks.get(key).push({ entry: e, unit: u });
  });
}

// ---------- the board ----------

const map = L.map('map', {
  crs: L.CRS.Simple, minZoom: 0, maxZoom: 8, zoomSnap: 0.25, zoomDelta: 0.5,
  wheelPxPerZoomLevel: 90, attributionControl: false, doubleClickZoom: false, zoomControl: false,
});
L.control.zoom({ position: 'bottomright' }).addTo(map);
const renderer = L.canvas({ padding: 0.5, tolerance: 3 });
let zmax = 6;
const toLL = (p) => map.unproject(L.point(p[0], p[1]), zmax);
const fromLL = (ll) => map.project(ll, zmax);

let boardLoading = null;
function loadBoard() {
  if (!boardLoading) {
    boardLoading = fetch('/api/game/map').then((r) => {
      if (!r.ok) throw new Error(`map: ${r.status}`);
      return r.json();
    }).then(buildBoard);
  }
  return boardLoading;
}

function buildBoard(data) {
  state.board = data;
  zmax = data.zmax;
  for (const h of data.hexes) {
    state.hexes.set(h.id, h);
    for (const l of [h.label, ...(h.also || [])]) state.byLabel.set(l, h.id);
  }
  for (const z of data.zones) {
    state.zones.set(z.id, z);
    if (z.hex) state.holdFor.set(hexOfLabel(z.hex), z.id);
  }
  const bounds = L.latLngBounds(toLL([0, data.height]), toLL([data.width, 0]));
  new JoinedLayer({ tileSize: 256, minZoom: 0, maxNativeZoom: zmax, maxZoom: zmax + 2, noWrap: true, bounds,
                    keepBuffer: 4, sections: data.sections, zmax }).addTo(map);
  map.setMaxZoom(zmax + 2);
  map.setMaxBounds(bounds.pad(0.15));

  for (const g of [...LAYERS, 'hit', 'zones', 'selection', 'units']) state.groups[g] = L.layerGroup();
  const ctx = { toLL, renderer, op: 1, add: (layer, group) => layer.addTo(state.groups[group]) };
  for (const h of data.hexes) {
    const ring = h.p.map(toLL);
    drawTerrain(ctx, ring, h.t);
    drawLandmarks(ctx, h.c, h.lm);
    const hit = L.polygon(ring, { renderer, stroke: false, fillOpacity: 0, fillColor: '#000' });
    hit.on('mousemove', () => hoverHex(h.id));
    hit.on('click', () => select({ kind: 'hex', id: h.id }));
    hit.addTo(state.groups.hit);
  }
  for (const [key, s] of Object.entries(data.sides)) {
    const [id, d] = key.split('|');
    const h = state.hexes.get(id);
    if (!h || !state.hexes.has(neighbourId(id, d))) continue;
    const [i, j] = SIDE_CORNERS[d];
    const down = s.feature && s.feature.down && state.hexes.get(s.feature.down);
    drawSideFeatures(ctx, s, h.p[i], h.p[j], down && down.c);
  }
  for (const z of data.zones) {
    const poly = L.polygon(z.p.map(toLL), { renderer, color: '#d9b45a', weight: 0, opacity: 0,
                                            fillColor: '#d9b45a', fillOpacity: 0 });
    poly.on('mouseover', () => { poly.setStyle({ weight: 3, opacity: 0.9, fillOpacity: 0.12 }); hoverZone(z.id); });
    poly.on('mouseout', () => poly.setStyle({ weight: 0, opacity: 0, fillOpacity: 0 }));
    poly.on('click', () => select({ kind: 'zone', id: z.id }));
    poly.addTo(state.groups.zones);
  }
  const shown = store.get('cna.layers', {});
  for (const box of document.querySelectorAll('#layers input[data-layer]')) {
    if (shown[box.dataset.layer] === false) box.checked = false;
    box.addEventListener('change', applyLayers);
  }
  applyLayers();
  for (const g of ['hit', 'zones', 'units', 'selection']) state.groups[g].addTo(map);
  map.on('zoomend', sizeCounters);
  map.fitBounds(bounds);
  sizeCounters();
}

function applyLayers() {
  const shown = {};
  for (const box of document.querySelectorAll('#layers input[data-layer]')) {
    shown[box.dataset.layer] = box.checked;
    if (box.checked) state.groups[box.dataset.layer].addTo(map); else state.groups[box.dataset.layer].remove();
  }
  store.set('cna.layers', shown);
}

// Counters scale with the hexes, in steps.
function sizeCounters() {
  const h = state.board.hexes[0];
  const hexPx = Math.hypot(h.p[0][0] - h.p[3][0], h.p[0][1] - h.p[3][1]) * 2 ** (map.getZoom() - zmax);
  const step = hexPx < 16 ? 0 : hexPx < 34 ? 1 : hexPx < 60 ? 2 : hexPx < 90 ? 3 : 4;
  const el = $('#map');
  el.className = el.className.replace(/\bcz-\d\b/g, '').trim();
  el.classList.add(`cz-${step}`);
}

function centerOf(key) {
  if (key.startsWith('z:')) {
    const p = state.zones.get(key.slice(2)).p;
    return [p.reduce((s, q) => s + q[0], 0) / p.length, p.reduce((s, q) => s + q[1], 0) / p.length];
  }
  return state.hexes.get(key.slice(2)).c;
}

function drawUnits() {
  state.groups.units.clearLayers();
  state.markers.clear();
  const shown = new Map();  // where drawn -> items
  for (const [key, items] of state.stacks) {
    const at = shownAt(key);
    if (!shown.has(at)) shown.set(at, []);
    shown.get(at).push(...items);
    if (at !== key) {  // a small tag in the hex points at its holding box
      const icon = L.divIcon({ className: '', iconSize: [0, 0],
                               html: `<div class="hold-link" title="Counters in the holding box">▣ ${items.length}</div>` });
      const m = L.marker(toLL(centerOf(key)), { icon, keyboard: false });
      m.on('click', () => select({ kind: 'zone', id: at.slice(2) }));
      m.addTo(state.groups.units);
    }
  }
  for (const [at, items] of shown) {
    const flex = items.every((x) => x.entry.where.flex);
    const icon = L.divIcon({ className: '', iconSize: [0, 0], html: counterHtml(items, { flex }) });
    const m = L.marker(toLL(centerOf(at)), { icon, keyboard: false, riseOnHover: true });
    m.on('click', () => select(at.startsWith('z:') ? { kind: 'zone', id: at.slice(2) } : { kind: 'hex', id: at.slice(2) }));
    m.on('mouseover', () => (at.startsWith('z:') ? hoverZone(at.slice(2)) : hoverHex(at.slice(2))));
    m.addTo(state.groups.units);
    state.markers.set(at, { marker: m, items, flex });
  }
}

// ---------- hover and selection ----------

function hexFacts(id) {
  const h = state.hexes.get(id);
  const t = TERRAIN[h.t] ? TERRAIN[h.t].label : h.t;
  const lm = h.lm.map((l) => `${LANDMARKS[l.type]?.label || l.type}${l.name ? ` “${escapeHtml(l.name)}”` : ''}`).join(', ');
  const sides = DIRS.map((d) => {
    const s = state.board.sides[sideKey(id, d)];
    const txt = s && sideSummary(s, label);
    return txt ? `<tr><td>${DIR_NAMES[d]}</td><td>${txt}</td></tr>` : '';
  }).join('');
  return `<tr><td>Terrain</td><td>${t}${h.coastal ? ', coastal' : ''}</td></tr>
    ${lm ? `<tr><td>Landmarks</td><td>${lm}</td></tr>` : ''}${sides}`;
}
const hexTitle = (id) => {
  const h = state.hexes.get(id);
  const names = h.lm.map((l) => l.name).filter(Boolean);
  return `${[...new Set(names)].join(' / ')}${names.length ? ' · ' : ''}Hex ${h.label}`;
};

function hoverHex(id) {
  if (state.hover === `h:${id}`) return;
  state.hover = `h:${id}`;
  const h = state.hexes.get(id);
  const also = h.also && h.also.length ? ` <span class="muted">= ${h.also.join(' = ')}</span>` : '';
  const n = (state.stacks.get(`h:${id}`) || []).length;
  $('#hover').className = 'panel';
  $('#hover').innerHTML = `<div class="hexid">${escapeHtml(hexTitle(id))}${also}</div>
    <table>${hexFacts(id)}${n ? `<tr><td>Units</td><td>${n}</td></tr>` : ''}</table>`;
}

function hoverZone(id) {
  if (state.hover === `z:${id}`) return;
  state.hover = `z:${id}`;
  const z = state.zones.get(id);
  $('#hover').className = 'panel';
  $('#hover').innerHTML = `<div class="hexid">${escapeHtml(z.name)}</div><div class="muted">${ZONE_KINDS[z.kind]}${z.hex ? ` for hex ${z.hex}` : ''}</div>`;
}

function select(sel) {
  state.selection = sel;
  drawSelection();
  renderSelection();
  renderForces();
}

function drawSelection() {
  state.groups.selection.clearLayers();
  const sel = state.selection;
  if (!sel || sel.kind === 'pool') return;
  const ring = sel.kind === 'hex' ? state.hexes.get(sel.id).p : state.zones.get(sel.id).p;
  L.polygon(ring.map(toLL), { renderer, color: '#ffe14a', weight: 4, fill: false, interactive: false })
    .addTo(state.groups.selection);
}

function entryBlock(e, items) {
  const trucks = e.trucks && Object.entries(e.trucks).filter(([, n]) => n).map(([k, n]) => `${n} ${k}`).join(', ');
  const units = items.map(({ unit }) => `<li>${counterHtml([{ unit, entry: e }])}
    <div><div class="uname">${escapeHtml(unit.name)}</div>
      <div class="udetail">${escapeHtml(NATIONS[unitNat(unit, e)] || '')}${unit.detail ? ` · ${escapeHtml(unit.detail)}` : ''}</div></div></li>`).join('');
  const flex = e.where.flex && e.where.kind !== 'pool';
  return `<div class="note"><b>${SIDES[e.side]}</b> · ${escapeHtml(placeText(e.at))}${flex ? ' <span class="flex-tag">flexible</span>' : ''}
      · Case ${e.rule}${trucks ? `<br>Trucks: ${trucks}` : ''}${e.at.fix ? `<br>Hex corrected: ${escapeHtml(e.at.fix)}` : ''}
      ${e.note ? `<br>${escapeHtml(e.note)}` : ''}</div><ul class="units">${units}</ul>`;
}

function unitsHtml(keys) {
  const byEntry = new Map();
  for (const key of keys) {
    for (const it of state.stacks.get(key) || []) {
      if (!byEntry.has(it.entry)) byEntry.set(it.entry, []);
      byEntry.get(it.entry).push(it);
    }
  }
  return [...byEntry].map(([e, items]) => entryBlock(e, items)).join('');
}

function renderSelection() {
  const panel = $('#selection');
  const sel = state.selection;
  if (!sel) { panel.hidden = true; return; }
  panel.hidden = false;
  let html;
  if (sel.kind === 'hex') {
    const box = state.holdFor.get(sel.id);
    html = `<div class="kind">Hex</div><h3>${escapeHtml(hexTitle(sel.id))}</h3><table>${hexFacts(sel.id)}</table>
      ${box ? `<div class="note">Counters here are kept in the <a href="#" data-zone="${box}">${escapeHtml(state.zones.get(box).name)}</a>.</div>` : ''}
      ${unitsHtml([`h:${sel.id}`])}`;
  } else if (sel.kind === 'zone') {
    const z = state.zones.get(sel.id);
    const info = Object.entries(z.info || {}).map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(v)}</td></tr>`).join('');
    const keys = [`z:${z.id}`];
    if (z.hex) keys.push(`h:${hexOfLabel(z.hex)}`);
    html = `<div class="kind">${ZONE_KINDS[z.kind]}${z.side ? ` · ${SIDES[z.side]}` : ''}</div><h3>${escapeHtml(z.name)}</h3>
      ${info ? `<table>${info}</table>` : ''}${z.text ? `<div class="note">${escapeHtml(z.text)}</div>` : ''}
      ${z.hex ? `<div class="note">Stands for hex <a href="#" data-hex="${hexOfLabel(z.hex)}">${z.hex}</a>.</div>` : ''}
      ${unitsHtml(keys)}`;
  } else {
    const e = state.catalog.setups[state.scenario.setup].deploy[sel.id];
    html = `<div class="kind">Placed by the player</div><h3>${escapeHtml(e.at.area)}</h3>
      ${entryBlock(e, e.units.map((unit) => ({ unit, entry: e })))}`;
  }
  $('#selection-body').innerHTML = html;
}

$('#selection').addEventListener('click', (ev) => {
  const a = ev.target.closest('a[data-zone], a[data-hex]');
  if (a) {
    ev.preventDefault();
    if (a.dataset.zone) focusOn({ kind: 'zone', id: a.dataset.zone });
    else focusOn({ kind: 'hex', id: a.dataset.hex });
  }
  if (ev.target.closest('.close')) select(null);
});
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && !$('#game').hidden && !$('#briefing').open) select(null);
});

function focusOn(sel) {
  if (sel.kind !== 'pool') {
    const c = centerOf(sel.kind === 'zone' ? `z:${sel.id}` : `h:${sel.id}`);
    map.flyTo(toLL(c), Math.max(map.getZoom(), zmax - 2.5), { duration: 0.5 });
  }
  select(sel);
}

// ---------- forces panel ----------

function renderForces() {
  if (!state.scenario) return;
  for (const b of document.querySelectorAll('#forces .tabs button')) b.classList.toggle('on', b.dataset.side === state.side);
  const setup = state.catalog.setups[state.scenario.setup];
  const mine = setup.deploy.filter((e) => e.side === state.side);
  const sel = state.selection;
  const isOn = (e) => sel && (sel.kind === 'pool' ? sel.id === e.index
    : e.where.kind !== 'pool' && (sel.kind === 'hex' ? `h:${sel.id}` === stackKey(e.where)
      : `z:${sel.id}` === shownAt(stackKey(e.where))));
  const row = (e) => `<div class="dep ${isOn(e) ? 'on' : ''}" data-entry="${e.index}">
      <div class="where">${escapeHtml(placeText(e.at))}${e.where.flex && e.where.kind !== 'pool' ? '<span class="flex-tag">flexible</span>' : ''}</div>
      <div class="who">${e.units.map((u) => escapeHtml(u.name)).join(' · ')}</div></div>`;
  const placed = mine.filter((e) => e.where.kind !== 'pool');
  const pool = mine.filter((e) => e.where.kind === 'pool');
  const count = (es) => es.reduce((n, e) => n + e.units.length, 0);
  $('#forces-body').innerHTML =
    `<div class="forces-head">On the map · ${count(placed)} units</div>${placed.map(row).join('')}`
    + (pool.length ? `<div class="forces-head">Placed by the player · ${count(pool)} units</div>${pool.map(row).join('')}` : '')
    + (setup.notes ? `<div class="forces-head">Notes</div>${setup.notes.map((n) => `<div class="who">${escapeHtml(n)}</div>`).join('<br>')}` : '');
}

$('#forces .tabs').addEventListener('click', (ev) => {
  const b = ev.target.closest('button[data-side]');
  if (b) { state.side = b.dataset.side; renderForces(); }
});
$('#forces-body').addEventListener('click', (ev) => {
  const d = ev.target.closest('[data-entry]');
  if (!d) return;
  const e = state.catalog.setups[state.scenario.setup].deploy[+d.dataset.entry];
  if (e.where.kind === 'pool') { select({ kind: 'pool', id: e.index }); return; }
  const at = shownAt(stackKey(e.where));
  focusOn(e.where.kind === 'zone' || at.startsWith('z:') ? { kind: 'zone', id: at.slice(2) } : { kind: 'hex', id: e.where.id });
});

// ---------- briefing ----------

function scenarioFacts(s) {
  const setup = state.catalog.setups[s.setup];
  const turns = s.end.turn - s.start.turn + 1;
  return `<dl class="facts">
    <dt>Starts</dt><dd>${turnText(s.start)}</dd>
    <dt>Ends</dt><dd>after ${turnText(s.end)}</dd>
    <dt>Length</dt><dd>${turns} Game-Turn${turns > 1 ? 's' : ''} (${turns * 3 - (s.start.stage - 1) - (3 - s.end.stage)} OpStages)</dd>
    <dt>Playing time</dt><dd>${s.hours} hours</dd>
    <dt>Set-up</dt><dd>${escapeHtml(setup.name)} (Case ${setup.rule})</dd>
    <dt>Initiative</dt><dd>${escapeHtml(setup.initiative)}</dd></dl>`;
}

function openBriefing() {
  const s = state.scenario;
  const setup = state.catalog.setups[s.setup];
  const groups = [['Victory conditions', [s.victory]], ...(s.special ? [['Campaign adjustments', [s.special]]] : []),
                  ...Object.entries(setup.rules)];
  $('#briefing-body').innerHTML = `<h3 class="display" style="margin:0;font-size:28px;text-transform:uppercase">${escapeHtml(s.name)}</h3>
    <div class="sub muted" style="color:var(--sheet-muted)">${escapeHtml(s.group)} · Case ${s.rule}</div>
    <p>${escapeHtml(s.summary)}</p>${scenarioFacts(s)}
    ${(setup.notes || []).map((n) => `<p>${escapeHtml(n)}</p>`).join('')}
    ${groups.map(([name, cases], i) => `<details class="rule" ${i === 0 ? 'open' : ''} data-cases="${cases.join(' ')}">
      <summary>${escapeHtml(name)} <span>(${cases.join(', ')})</span></summary><div class="body"></div></details>`).join('')}`;
  for (const d of document.querySelectorAll('#briefing details.rule')) {
    const load = () => {
      if (d.dataset.loaded) return;
      d.dataset.loaded = '1';
      const body = d.querySelector('.body');
      body.innerHTML = d.dataset.cases.split(' ').map((c) => `<div data-case="${c}" class="muted">Loading ${c}…</div>`).join('');
      for (const el of body.querySelectorAll('[data-case]')) fillRule(el, el.dataset.case);
    };
    if (d.open) load();
    d.addEventListener('toggle', load);
  }
  $('#briefing').showModal();
}
$('#open-briefing').addEventListener('click', openBriefing);

// ---------- screens ----------

function show(id) {
  for (const s of document.querySelectorAll('.screen')) s.hidden = s.id !== id;
}

async function catalog() {
  if (!state.catalog) state.catalog = await (await fetch('/api/scenarios')).json();
  return state.catalog;
}

async function showScenarios(id) {
  show('scenarios');
  const cat = await catalog();
  const chosen = cat.scenarios.find((s) => s.id === id) || cat.scenarios.find((s) => s.id === store.get('cna.scenario')) || cat.scenarios[0];
  let group = null;
  $('#scenario-list').innerHTML = cat.scenarios.map((s) => {
    const head = s.group !== group ? `<li class="group">${escapeHtml((group = s.group))}</li>` : '';
    return `${head}<li><a href="#scenarios/${s.id}" class="${s === chosen ? 'on' : ''}">
      <div class="name">${escapeHtml(s.name)}</div>
      <div class="when">${turnDate(s.start.turn)} – ${turnDate(s.end.turn)} · ${s.hours} h</div></a></li>`;
  }).join('');
  const setup = cat.setups[chosen.setup];
  const count = (side, pool) => setup.deploy.filter((e) => e.side === side && !!(e.at.area && !e.at.anchor && !e.at.near) === pool)
    .reduce((n, e) => n + e.units.length, 0);
  $('#scenario-detail').innerHTML = `<h3>${escapeHtml(chosen.name)}</h3>
    <div class="sub">${escapeHtml(chosen.group)} · Case ${chosen.rule}</div>
    <p>${escapeHtml(chosen.summary)}</p>
    <div class="counts">
      <div><b>${count('axis', false)}</b>Axis units on the map${count('axis', true) ? `, ${count('axis', true)} to place` : ''}</div>
      <div><b>${count('cw', false)}</b>Commonwealth units on the map${count('cw', true) ? `, ${count('cw', true)} to place` : ''}</div>
    </div>
    <button class="start" type="button" data-play="${chosen.id}">Start scenario</button>
    ${scenarioFacts(chosen)}
    <section class="rule"><h4>Victory conditions (Case ${chosen.victory})</h4><div id="detail-victory" class="muted">Loading…</div></section>`;
  fillRule($('#detail-victory'), chosen.victory);
  store.set('cna.scenario', chosen.id);
}

$('#scenario-detail').addEventListener('click', (ev) => {
  const b = ev.target.closest('[data-play]');
  if (b) location.hash = `#play/${b.dataset.play}`;
});

async function showGame(id, view) {
  const cat = await catalog();
  const s = cat.scenarios.find((x) => x.id === id);
  if (!s) { location.hash = '#scenarios'; return; }
  show('game');
  map.invalidateSize();
  if (!state.board) {
    $('#loading').hidden = false;
    try { await loadBoard(); } finally { $('#loading').hidden = true; }
  }
  state.scenario = s;
  store.set('cna.scenario', s.id);
  document.title = `${s.name} · Campaign for North Africa`;
  $('#game-name').textContent = s.name;
  $('#game-turn').textContent = `${turnText(s.start)} · ends after Game-Turn ${s.end.turn}, OpStage ${s.end.stage}`;
  deploy(s);
  drawUnits();
  state.side = 'axis';
  select(null);
  if (view) map.setView(toLL([view.x, view.y]), view.z);
  else openingView();
  writeHash();
}

// Open on the front: the stretch of map, about a section and a half wide,
// with the most units, so far garrisons don't zoom the map right out.
const FRONT_WIDTH = 9000;  // scan pixels
function openingView() {
  const pts = [...state.stacks].filter(([k]) => k.startsWith('h:'))
    .flatMap(([k, items]) => items.map(() => centerOf(k))).sort((a, b) => a[0] - b[0]);
  if (!pts.length) return;
  let best = [0, 0];
  for (let i = 0, j = 0; j < pts.length; j++) {
    while (pts[j][0] - pts[i][0] > FRONT_WIDTH) i++;
    if (j - i > best[1] - best[0]) best = [i, j];
  }
  const core = pts.slice(best[0], best[1] + 1);
  // Keep clear of the panels (narrow windows put the forces list at the bottom).
  const narrow = window.innerWidth <= 900;
  map.fitBounds(L.latLngBounds(core.map(toLL)).pad(0.15), {
    paddingTopLeft: narrow ? [10, 100] : [320, 70],
    paddingBottomRight: narrow ? [10, window.innerHeight * 0.34 + 20] : [260, 20],
  });
}

// The scenario and view in the URL (#play/<id>/x/y/zoom, scan pixels), so a reload returns here.
function writeHash() {
  if ($('#game').hidden || !state.scenario) return;
  const p = fromLL(map.getCenter());
  history.replaceState(null, '', `#play/${state.scenario.id}/${Math.round(p.x)}/${Math.round(p.y)}/${map.getZoom()}`);
}
map.on('moveend', writeHash);

function route() {
  const h = location.hash;
  let m;
  if ((m = h.match(/^#play\/([\w-]+)(?:\/(\d+)\/(\d+)\/([\d.]+))?/))) showGame(m[1], m[2] ? { x: +m[2], y: +m[3], z: +m[4] } : null);
  else if ((m = h.match(/^#scenarios(?:\/([\w-]+))?/))) showScenarios(m[1]);
  else { show('title'); document.title = 'Campaign for North Africa'; }
}
window.addEventListener('hashchange', route);
route();
