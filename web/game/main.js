// CNA game page: the title screen, scenario selection, and the board with a
// scenario's initial deployment.
//
// The model is in board.js (the map, read-only) and state.js (the game as
// plain data); this file only draws them and handles input. The server sends
// the joined map with the hand corrections applied (/api/game/map) and the
// scenarios (/api/scenarios); rulebook cases quoted in the briefing come from
// the local transcription (/api/rules/<case>) when it is there.

import { LANDMARKS, TERRAIN } from '../shared/vocab.js';
import { DIRS, DIR_NAMES, SIDE_CORNERS, neighbourId, sideSummary } from '../shared/hex.js';
import { $, escapeHtml, store } from '../shared/util.js';
import { JoinedLayer, drawLandmarks, drawSideFeatures, drawTerrain } from '../shared/draw.js';
import { Board } from './board.js';
import { locKey, newGame, parseLocKey, stacks, turnDate, turnText, unitsAt, unitsOf } from './state.js';
import { counterHtml } from './units.js';
import { markdown } from './markdown.js';

const SIDES = { axis: 'Axis', cw: 'Commonwealth' };
const NATIONS = {
  it: 'Italian', de: 'German', uk: 'British', au: 'Australian', nz: 'New Zealand', sa: 'South African',
  in: 'Indian', fr: 'Free French', pl: 'Polish', cz: 'Czechoslovak', gr: 'Greek',
};
const ZONE_KINDS = { offmap: 'Off-map box', transit: 'In transit', holding: 'Holding box', airbase: 'Off-map air base' };
const LAYERS = ['terrain', 'rivers', 'features', 'crossings', 'landmarks'];

const ui = {
  catalog: null,     // /api/scenarios
  board: null,       // Board, once loaded
  scenario: null,    // the scenario being played
  game: null,        // state.js game
  groups: {},        // layer name -> L.layerGroup
  selection: null,   // a loc, or {kind: 'pool', id: deployment index}
  hover: null,
  side: 'axis',      // the forces panel's tab
};

const label = (id) => ui.board.label(id);
const setup = () => ui.catalog.setups[ui.scenario.setup];
const deployment = (i) => setup().deploy[i];

// ---------- rule text ----------

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

function placeText(at) {
  if (at.box) return ui.board?.zones.get(at.box)?.name || at.box;
  if (at.area) return at.area;
  const name = at.label ? `${at.label} ` : '';
  if (at.near) return `Within ${at.within} hex${at.within > 1 ? 'es' : ''} of ${name}(${at.near})`;
  if (at.hexes) return `${at.within ? `Within ${at.within} hex of ` : ''}${name}(${at.hexes.join(at.hexes.length > 2 ? ', ' : ' and/or ')})`;
  return at.label ? `${at.label} (${at.hex})` : at.hex;
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
    }).then((data) => buildBoard(new Board(data)));
  }
  return boardLoading;
}

function buildBoard(board) {
  ui.board = board;
  zmax = board.zmax;
  const bounds = L.latLngBounds(toLL([0, board.height]), toLL([board.width, 0]));
  new JoinedLayer({ tileSize: 256, minZoom: 0, maxNativeZoom: zmax, maxZoom: zmax + 2, noWrap: true, bounds,
                    keepBuffer: 4, sections: board.sections, zmax }).addTo(map);
  map.setMaxZoom(zmax + 2);
  map.setMaxBounds(bounds.pad(0.15));

  for (const g of [...LAYERS, 'hit', 'zones', 'selection', 'units']) ui.groups[g] = L.layerGroup();
  const ctx = { toLL, renderer, op: 1, add: (layer, group) => layer.addTo(ui.groups[group]) };
  for (const h of board.hexes.values()) {
    const ring = h.p.map(toLL);
    drawTerrain(ctx, ring, h.t);
    drawLandmarks(ctx, h.c, h.lm);
    const loc = { kind: 'hex', id: h.id };
    const hit = L.polygon(ring, { renderer, stroke: false, fillOpacity: 0, fillColor: '#000' });
    hit.on('mousemove', () => hoverOn(loc));
    hit.on('click', () => select(loc));
    hit.addTo(ui.groups.hit);
  }
  for (const [key, s] of Object.entries(board.sides)) {
    const [id, d] = key.split('|');
    const h = board.hex(id);
    if (!h || !board.hexes.has(neighbourId(id, d))) continue;
    const [i, j] = SIDE_CORNERS[d];
    const down = s.feature && s.feature.down && board.hex(s.feature.down);
    drawSideFeatures(ctx, s, h.p[i], h.p[j], down && down.c);
  }
  for (const z of board.zones.values()) {
    const loc = { kind: 'zone', id: z.id };
    const poly = L.polygon(z.p.map(toLL), { renderer, color: '#d9b45a', weight: 0, opacity: 0,
                                            fillColor: '#d9b45a', fillOpacity: 0 });
    poly.on('mouseover', () => { poly.setStyle({ weight: 3, opacity: 0.9, fillOpacity: 0.12 }); hoverOn(loc); });
    poly.on('mouseout', () => poly.setStyle({ weight: 0, opacity: 0, fillOpacity: 0 }));
    poly.on('click', () => select(loc));
    poly.addTo(ui.groups.zones);
  }
  const shown = store.get('cna.layers', {});
  for (const box of document.querySelectorAll('#layers input[data-layer]')) {
    if (shown[box.dataset.layer] === false) box.checked = false;
    box.addEventListener('change', applyLayers);
  }
  applyLayers();
  for (const g of ['hit', 'zones', 'units', 'selection']) ui.groups[g].addTo(map);
  map.on('zoomend', sizeCounters);
  map.fitBounds(bounds);
  sizeCounters();
}

function applyLayers() {
  const shown = {};
  for (const box of document.querySelectorAll('#layers input[data-layer]')) {
    shown[box.dataset.layer] = box.checked;
    if (box.checked) ui.groups[box.dataset.layer].addTo(map); else ui.groups[box.dataset.layer].remove();
  }
  store.set('cna.layers', shown);
}

// Counters scale with the hexes, in steps.
function sizeCounters() {
  const h = ui.board.hexes.values().next().value;
  const hexPx = Math.hypot(h.p[0][0] - h.p[3][0], h.p[0][1] - h.p[3][1]) * 2 ** (map.getZoom() - zmax);
  const step = hexPx < 16 ? 0 : hexPx < 34 ? 1 : hexPx < 60 ? 2 : hexPx < 90 ? 3 : 4;
  const el = $('#map');
  el.className = el.className.replace(/\bcz-\d\b/g, '').trim();
  el.classList.add(`cz-${step}`);
}

function drawUnits() {
  ui.groups.units.clearLayers();
  const shown = new Map();  // where drawn -> units
  for (const [key, units] of stacks(ui.game)) {
    const loc = parseLocKey(key);
    const at = locKey(ui.board.shownAt(loc));
    if (!shown.has(at)) shown.set(at, []);
    shown.get(at).push(...units);
    if (at !== key) {  // a small tag in the hex points at its holding box
      const icon = L.divIcon({ className: '', iconSize: [0, 0],
                               html: `<div class="hold-link" title="Counters in the holding box">▣ ${units.length}</div>` });
      const m = L.marker(toLL(ui.board.centre(loc)), { icon, keyboard: false });
      m.on('click', () => select(parseLocKey(at)));
      m.addTo(ui.groups.units);
    }
  }
  for (const [key, units] of shown) {
    const loc = parseLocKey(key);
    const icon = L.divIcon({ className: '', iconSize: [0, 0], html: counterHtml(units, { flex: units.every((u) => u.flex) }) });
    const m = L.marker(toLL(ui.board.centre(loc)), { icon, keyboard: false, riseOnHover: true });
    m.on('click', () => select(loc));
    m.on('mouseover', () => hoverOn(loc));
    m.addTo(ui.groups.units);
  }
}

// ---------- hover and selection ----------

function hexFacts(id) {
  const h = ui.board.hex(id);
  const t = TERRAIN[h.t] ? TERRAIN[h.t].label : h.t;
  const lm = h.lm.map((l) => `${LANDMARKS[l.type]?.label || l.type}${l.name ? ` “${escapeHtml(l.name)}”` : ''}`).join(', ');
  const sides = DIRS.map((d) => {
    const txt = sideSummary(ui.board.side(id, d), label);
    return txt ? `<tr><td>${DIR_NAMES[d]}</td><td>${txt}</td></tr>` : '';
  }).join('');
  return `<tr><td>Terrain</td><td>${t}${h.coastal ? ', coastal' : ''}</td></tr>
    ${lm ? `<tr><td>Landmarks</td><td>${lm}</td></tr>` : ''}${sides}`;
}
const hexTitle = (id) => {
  const h = ui.board.hex(id);
  const names = h.lm.map((l) => l.name).filter(Boolean);
  return `${[...new Set(names)].join(' / ')}${names.length ? ' · ' : ''}Hex ${h.label}`;
};

function hoverOn(loc) {
  const key = locKey(loc);
  if (ui.hover === key) return;
  ui.hover = key;
  const panel = $('#hover');
  panel.className = 'panel';
  if (loc.kind === 'hex') {
    const h = ui.board.hex(loc.id);
    const also = h.also && h.also.length ? ` <span class="muted">= ${h.also.join(' = ')}</span>` : '';
    const n = unitsAt(ui.game, loc).length;
    panel.innerHTML = `<div class="hexid">${escapeHtml(hexTitle(loc.id))}${also}</div>
      <table>${hexFacts(loc.id)}${n ? `<tr><td>Units</td><td>${n}</td></tr>` : ''}</table>`;
  } else {
    const z = ui.board.zones.get(loc.id);
    panel.innerHTML = `<div class="hexid">${escapeHtml(z.name)}</div><div class="muted">${ZONE_KINDS[z.kind]}${z.hex ? ` for hex ${z.hex}` : ''}</div>`;
  }
}

function select(sel) {
  ui.selection = sel;
  drawSelection();
  renderSelection();
  renderForces();
}

function drawSelection() {
  ui.groups.selection.clearLayers();
  const sel = ui.selection;
  if (!sel || sel.kind === 'pool') return;
  L.polygon(ui.board.outline(sel).map(toLL), { renderer, color: '#ffe14a', weight: 4, fill: false, interactive: false })
    .addTo(ui.groups.selection);
}

// One deployment's units, with where and by which case they set up.
function entryBlock(e, units) {
  const trucks = e.trucks && Object.entries(e.trucks).filter(([, n]) => n).map(([k, n]) => `${n} ${k}`).join(', ');
  const items = units.map((u) => `<li>${counterHtml([u])}
    <div><div class="uname">${escapeHtml(u.name)}</div>
      <div class="udetail">${escapeHtml(NATIONS[u.nat] || '')}${u.detail ? ` · ${escapeHtml(u.detail)}` : ''}</div></div></li>`).join('');
  const flex = units[0].flex && units[0].loc.kind !== 'pool';
  return `<div class="note"><b>${SIDES[e.side]}</b> · ${escapeHtml(placeText(e.at))}${flex ? ' <span class="flex-tag">flexible</span>' : ''}
      · Case ${e.rule}${trucks ? `<br>Trucks: ${trucks}` : ''}${e.at.fix ? `<br>Hex corrected: ${escapeHtml(e.at.fix)}` : ''}
      ${e.note ? `<br>${escapeHtml(e.note)}` : ''}</div><ul class="units">${items}</ul>`;
}

// The units at these locs, grouped by deployment.
function unitsHtml(locs) {
  const keys = new Set(locs.map(locKey));
  const byDeployment = new Map();
  for (const u of ui.game.units) {
    if (!keys.has(locKey(u.loc))) continue;
    if (!byDeployment.has(u.deployment)) byDeployment.set(u.deployment, []);
    byDeployment.get(u.deployment).push(u);
  }
  return [...byDeployment].map(([i, units]) => entryBlock(deployment(i), units)).join('');
}

function renderSelection() {
  const panel = $('#selection');
  const sel = ui.selection;
  if (!sel) { panel.hidden = true; return; }
  panel.hidden = false;
  let html;
  if (sel.kind === 'hex') {
    const box = ui.board.holdFor.get(sel.id);
    html = `<div class="kind">Hex</div><h3>${escapeHtml(hexTitle(sel.id))}</h3><table>${hexFacts(sel.id)}</table>
      ${box ? `<div class="note">Counters here are kept in the <a href="#" data-zone="${box}">${escapeHtml(ui.board.zones.get(box).name)}</a>.</div>` : ''}
      ${unitsHtml([sel])}`;
  } else if (sel.kind === 'zone') {
    const z = ui.board.zones.get(sel.id);
    const info = Object.entries(z.info || {}).map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(v)}</td></tr>`).join('');
    const hexId = z.hex && ui.board.hexOfLabel(z.hex);
    const locs = [sel, ...(hexId ? [{ kind: 'hex', id: hexId }] : [])];
    html = `<div class="kind">${ZONE_KINDS[z.kind]}${z.side ? ` · ${SIDES[z.side]}` : ''}</div><h3>${escapeHtml(z.name)}</h3>
      ${info ? `<table>${info}</table>` : ''}${z.text ? `<div class="note">${escapeHtml(z.text)}</div>` : ''}
      ${hexId ? `<div class="note">Stands for hex <a href="#" data-hex="${hexId}">${z.hex}</a>.</div>` : ''}
      ${unitsHtml(locs)}`;
  } else {
    const e = deployment(sel.id);
    html = `<div class="kind">Placed by the player</div><h3>${escapeHtml(e.at.area)}</h3>
      ${entryBlock(e, unitsOf(ui.game, sel.id))}`;
  }
  $('#selection-body').innerHTML = html;
}

$('#selection').addEventListener('click', (ev) => {
  const a = ev.target.closest('a[data-zone], a[data-hex]');
  if (a) {
    ev.preventDefault();
    focusOn(a.dataset.zone ? { kind: 'zone', id: a.dataset.zone } : { kind: 'hex', id: a.dataset.hex });
  }
  if (ev.target.closest('.close')) select(null);
});
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && !$('#game').hidden && !$('#briefing').open) select(null);
});

function focusOn(sel) {
  if (sel.kind !== 'pool') map.flyTo(toLL(ui.board.centre(sel)), Math.max(map.getZoom(), zmax - 2.5), { duration: 0.5 });
  select(sel);
}

// ---------- forces panel ----------

// Each deployment of the shown side with its units; a deployment's units
// set up together, so its first unit says where.
function deploymentsOf(side) {
  return setup().deploy.map((e, i) => ({ e, i, units: unitsOf(ui.game, i) })).filter((d) => d.e.side === side);
}

function renderForces() {
  if (!ui.game) return;
  for (const b of document.querySelectorAll('#forces .tabs button')) b.classList.toggle('on', b.dataset.side === ui.side);
  const sel = ui.selection;
  const isOn = ({ i, units }) => {
    if (!sel) return false;
    const loc = units[0].loc;
    if (sel.kind === 'pool') return sel.id === i;
    if (loc.kind === 'pool') return false;
    return locKey(sel) === locKey(sel.kind === 'hex' ? loc : ui.board.shownAt(loc));
  };
  const row = (d) => `<div class="dep ${isOn(d) ? 'on' : ''}" data-entry="${d.i}">
      <div class="where">${escapeHtml(placeText(d.e.at))}${d.units[0].flex && d.units[0].loc.kind !== 'pool' ? '<span class="flex-tag">flexible</span>' : ''}</div>
      <div class="who">${d.units.map((u) => escapeHtml(u.name)).join(' · ')}</div></div>`;
  const mine = deploymentsOf(ui.side);
  const placed = mine.filter((d) => d.units[0].loc.kind !== 'pool');
  const pool = mine.filter((d) => d.units[0].loc.kind === 'pool');
  const count = (ds) => ds.reduce((n, d) => n + d.units.length, 0);
  const notes = setup().notes;
  $('#forces-body').innerHTML =
    `<div class="forces-head">On the map · ${count(placed)} units</div>${placed.map(row).join('')}`
    + (pool.length ? `<div class="forces-head">Placed by the player · ${count(pool)} units</div>${pool.map(row).join('')}` : '')
    + (notes ? `<div class="forces-head">Notes</div>${notes.map((n) => `<div class="who">${escapeHtml(n)}</div>`).join('<br>')}` : '');
}

$('#forces .tabs').addEventListener('click', (ev) => {
  const b = ev.target.closest('button[data-side]');
  if (b) { ui.side = b.dataset.side; renderForces(); }
});
$('#forces-body').addEventListener('click', (ev) => {
  const d = ev.target.closest('[data-entry]');
  if (!d) return;
  const i = +d.dataset.entry;
  const loc = unitsOf(ui.game, i)[0].loc;
  if (loc.kind === 'pool') select({ kind: 'pool', id: i });
  else focusOn(ui.board.shownAt(loc));
});

// ---------- briefing ----------

function scenarioFacts(s) {
  const su = ui.catalog.setups[s.setup];
  const turns = s.end.turn - s.start.turn + 1;
  return `<dl class="facts">
    <dt>Starts</dt><dd>${turnText(s.start)}</dd>
    <dt>Ends</dt><dd>after ${turnText(s.end)}</dd>
    <dt>Length</dt><dd>${turns} Game-Turn${turns > 1 ? 's' : ''} (${turns * 3 - (s.start.stage - 1) - (3 - s.end.stage)} OpStages)</dd>
    <dt>Playing time</dt><dd>${s.hours} hours</dd>
    <dt>Set-up</dt><dd>${escapeHtml(su.name)} (Case ${su.rule})</dd>
    <dt>Initiative</dt><dd>${escapeHtml(su.initiative)}</dd></dl>`;
}

function openBriefing() {
  const s = ui.scenario;
  const su = setup();
  const groups = [['Victory conditions', [s.victory]], ...(s.special ? [['Campaign adjustments', [s.special]]] : []),
                  ...Object.entries(su.rules)];
  $('#briefing-body').innerHTML = `<h3 class="display" style="margin:0;font-size:28px;text-transform:uppercase">${escapeHtml(s.name)}</h3>
    <div class="sub muted" style="color:var(--sheet-muted)">${escapeHtml(s.group)} · Case ${s.rule}</div>
    <p>${escapeHtml(s.summary)}</p>${scenarioFacts(s)}
    ${(su.notes || []).map((n) => `<p>${escapeHtml(n)}</p>`).join('')}
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
  if (!ui.catalog) ui.catalog = await (await fetch('/api/scenarios')).json();
  return ui.catalog;
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
  const su = cat.setups[chosen.setup];
  // The board may not be loaded yet, so this goes by the 'at' alone.
  const count = (side, pool) => su.deploy.filter((e) => e.side === side && !!(e.at.area && !e.at.anchor && !e.at.near) === pool)
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
  if (!ui.board) {
    $('#loading').hidden = false;
    try { await loadBoard(); } finally { $('#loading').hidden = true; }
  }
  ui.scenario = s;
  ui.game = newGame(cat, s.id, ui.board);
  store.set('cna.scenario', s.id);
  document.title = `${s.name} · Campaign for North Africa`;
  $('#game-name').textContent = s.name;
  $('#game-turn').textContent = `${turnText(s.start)} · ends after Game-Turn ${s.end.turn}, OpStage ${s.end.stage}`;
  drawUnits();
  ui.side = 'axis';
  select(null);
  if (view) map.setView(toLL([view.x, view.y]), view.z);
  else openingView();
  writeHash();
}

// Open on the front: the stretch of map, about a section and a half wide,
// with the most units, so far garrisons don't zoom the map right out.
const FRONT_WIDTH = 9000;  // scan pixels
function openingView() {
  const pts = ui.game.units.filter((u) => u.loc.kind === 'hex').map((u) => ui.board.centre(u.loc)).sort((a, b) => a[0] - b[0]);
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
  if ($('#game').hidden || !ui.scenario) return;
  const p = fromLL(map.getCenter());
  history.replaceState(null, '', `#play/${ui.scenario.id}/${Math.round(p.x)}/${Math.round(p.y)}/${map.getZoom()}`);
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
