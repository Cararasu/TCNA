// CNA game page: the title screen, scenario selection with a new game, the
// saved games, joining a game, and the board of a game being played.
//
// The rules run on the server (cna/engine); client.js talks to it. This file
// draws one seat's view of a game (state.js reads it) and turns input into
// commands. A view is fetched again whenever the game's stream says it has
// moved on. board.js holds the map (/api/game/map, with the hand corrections
// applied); rulebook cases come from the local transcription
// (/api/rules/<case>) when it is there.

import { LANDMARKS, TERRAIN } from '../shared/vocab.js';
import { DIRS, DIR_NAMES, SIDE_CORNERS, neighbourId, sideSummary } from '../shared/hex.js';
import { $, escapeHtml, store } from '../shared/util.js';
import { JoinedLayer, drawLandmarks, drawSideFeatures, drawTerrain } from '../shared/draw.js';
import { Board } from './board.js';
import { ApiError, GameClient, createGame, joinGame, listGames, stepTitles, tokensFor } from './client.js';
import { locKey, parseLocKey, stacks, turnDate, turnText, unitList, unitsAt, unitsOf } from './state.js';
import { counterHtml } from './units.js';
import { markdown } from './markdown.js';

const SIDES = { axis: 'Axis', cw: 'Commonwealth' };
const SEATS = { ...SIDES, referee: 'Referee' };
const NATIONS = {
  it: 'Italian', de: 'German', uk: 'British', au: 'Australian', nz: 'New Zealand', sa: 'South African',
  in: 'Indian', fr: 'Free French', pl: 'Polish', cz: 'Czechoslovak', gr: 'Greek',
};
const ZONE_KINDS = { offmap: 'Off-map box', transit: 'In transit', holding: 'Holding box', airbase: 'Off-map air base' };
const LAYERS = ['terrain', 'rivers', 'features', 'crossings', 'landmarks'];

const ui = {
  catalog: null,     // /api/scenarios
  steps: null,       // /api/sequence: step id -> {title, case}
  board: null,       // Board, once loaded
  client: null,      // GameClient of the game shown
  view: null,        // its view, as the server sent it
  scenario: null,    // the game's scenario
  groups: {},        // layer name -> L.layerGroup
  selection: null,   // a loc, or {kind: 'pool', id: deployment index}
  placing: null,     // unit ids waiting for a click on the map, in the Set-up Stage
  hover: null,
  side: 'axis',      // the forces panel's tab: a side, or 'log'
};

const label = (id) => ui.board.label(id);
// The game's scenario as scenarios.json has it now, or null if it is gone
// from there: the game itself needs only its view.
const setup = () => (ui.scenario ? ui.catalog.setups[ui.scenario.setup] : null);
const deployments = () => ui.view.deployments;  // the game's own, kept from its scenario
const deployment = (i) => deployments()[i];
const seat = () => ui.view.seat;
const allowed = (type) => ui.view.now.allowed.includes(type);
const inSetup = () => ui.view.now.step === 'setup';

// ---------- messages ----------

let toastTimer = null;
function toast(text, kase) {
  const el = $('#toast');
  el.innerHTML = `${escapeHtml(text)}${kase ? ` <span class="muted">(Case ${escapeHtml(kase)})</span>` : ''}`;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 5000);
}

// Gives an order; a refusal is shown, not thrown. The view is fetched once
// it has the order's events, by this or by the stream, whichever comes first.
async function act(type, args) {
  try {
    const r = await ui.client.command(type, args);
    if (r.seq !== null) refresh(r.seq);
    return true;
  } catch (e) {
    toast(e.message, e instanceof ApiError ? e.case : null);
    if (!(e instanceof ApiError)) refresh();
    return false;
  }
}

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

// A loc in words.
function placeName(loc) {
  if (loc.kind === 'pool') return 'the pool';
  if (loc.kind === 'zone') return ui.board.zones.get(loc.id)?.name || loc.id;
  const names = [...new Set(ui.board.hex(loc.id).lm.map((l) => l.name).filter(Boolean))];
  return `${names.length ? `${names.join(' / ')} ` : ''}${label(loc.id)}`;
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
    hit.on('click', (e) => clickLoc(loc, e));
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
    poly.on('click', (e) => clickLoc(loc, e));
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
  for (const [key, units] of stacks(ui.view)) {
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
  const flexShown = inSetup();
  for (const [key, units] of shown) {
    const loc = parseLocKey(key);
    const icon = L.divIcon({ className: '', iconSize: [0, 0],
                             html: counterHtml(units, { flex: flexShown && units.every((u) => u.flex) }) });
    const m = L.marker(toLL(ui.board.centre(loc)), { icon, keyboard: false, riseOnHover: true });
    m.on('click', (e) => clickLoc(loc, e));
    m.on('mouseover', () => hoverOn(loc));
    m.addTo(ui.groups.units);
  }
}

// ---------- clicks on the map ----------

// A click places the units being placed, Alt-click moves the selected stack
// (sandbox games), and any other click selects.
function clickLoc(loc, e) {
  if (!ui.view) return;
  if (ui.placing) { placeAt(loc); return; }
  if (e?.originalEvent?.altKey && allowed('move-unit') && ui.selection && ui.selection.kind !== 'pool') {
    moveTo(loc);
    return;
  }
  select(loc);
}

function startPlacing(ids) {
  ui.placing = ids;
  const names = ids.map((id) => ui.view.units[id].name);
  $('#mode').innerHTML = `Placing ${escapeHtml(names.length > 2 ? `${names.length} units` : names.join(' and '))}:
    click a hex or box. <button type="button" data-cancel>Cancel</button>`;
  $('#mode').hidden = false;
}
function stopPlacing() {
  ui.placing = null;
  $('#mode').hidden = true;
}
$('#mode').addEventListener('click', (ev) => { if (ev.target.closest('[data-cancel]')) stopPlacing(); });

async function placeAt(loc) {
  const ids = ui.placing;
  stopPlacing();
  await act('place-unit', { units: ids, loc });
}

async function moveTo(loc) {
  const units = selectedLocs(ui.selection).flatMap((l) => unitsAt(ui.view, l))
    .filter((u) => u.side === seat()).map((u) => u.id);
  if (!units.length) { toast('None of your units are in the selected place.'); return; }
  if (await act('move-unit', { units, to: loc })) select(loc);
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
  if (!ui.view) return;
  const key = locKey(loc);
  if (ui.hover === key) return;
  ui.hover = key;
  const panel = $('#hover');
  panel.className = 'panel';
  if (loc.kind === 'hex') {
    const h = ui.board.hex(loc.id);
    const also = h.also && h.also.length ? ` <span class="muted">= ${h.also.join(' = ')}</span>` : '';
    const n = unitsAt(ui.view, loc).length;
    panel.innerHTML = `<div class="hexid">${escapeHtml(hexTitle(loc.id))}${also}</div>
      <table>${hexFacts(loc.id)}${n ? `<tr><td>Units</td><td>${n}</td></tr>` : ''}</table>`;
  } else {
    const z = ui.board.zones.get(loc.id);
    panel.innerHTML = `<div class="hexid">${escapeHtml(z.name)}</div><div class="muted">${ZONE_KINDS[z.kind]}${z.hex ? ` for hex ${z.hex}` : ''}</div>`;
  }
}

// The places a selection stands for: a box with the hex whose counters it holds.
function selectedLocs(sel) {
  if (sel.kind !== 'zone') return [sel];
  const z = ui.board.zones.get(sel.id);
  const hexId = z.hex && ui.board.hexOfLabel(z.hex);
  return [sel, ...(hexId ? [{ kind: 'hex', id: hexId }] : [])];
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

// May this seat place the unit now (Set-up Stage, own flexible unit)?
const placeable = (u) => inSetup() && allowed('place-unit') && u.side === seat() && u.flex;

// One deployment's units, with where and by which case they set up, and the
// set-up buttons for the units the player may place.
function entryBlock(e, units) {
  const trucks = e.trucks && Object.entries(e.trucks).filter(([, n]) => n).map(([k, n]) => `${n} ${k}`).join(', ');
  const items = units.map((u) => {
    const buttons = placeable(u) ? `<div class="ubuttons"><button type="button" data-place="${u.id}">Place…</button>
      ${u.loc.kind !== 'pool' ? `<button type="button" data-unplace="${u.id}">To the pool</button>` : ''}</div>` : '';
    return `<li>${counterHtml([u])}
      <div><div class="uname">${escapeHtml(u.name)}</div>
        <div class="udetail">${escapeHtml(NATIONS[u.nat] || '')}${u.detail ? ` · ${escapeHtml(u.detail)}` : ''}</div>${buttons}</div></li>`;
  }).join('');
  const flex = inSetup() && units[0].flex && units[0].loc.kind !== 'pool';
  const pooled = units.filter((u) => u.loc.kind === 'pool' && placeable(u));
  return `<div class="note"><b>${SIDES[e.side]}</b> · ${escapeHtml(placeText(e.at))}${flex ? ' <span class="flex-tag">flexible</span>' : ''}
      · Case ${e.rule}${trucks ? `<br>Trucks: ${trucks}` : ''}${e.at.fix ? `<br>Hex corrected: ${escapeHtml(e.at.fix)}` : ''}
      ${e.note ? `<br>${escapeHtml(e.note)}` : ''}</div>
      ${pooled.length > 1 ? `<button type="button" class="place-all" data-place-all="${pooled.map((u) => u.id).join(',')}">Place all ${pooled.length} together…</button>` : ''}
      <ul class="units">${items}</ul>`;
}

// The units at these locs, grouped by deployment.
function unitsHtml(locs) {
  const keys = new Set(locs.map(locKey));
  const byDeployment = new Map();
  for (const u of unitList(ui.view)) {
    if (!keys.has(locKey(u.loc))) continue;
    if (!byDeployment.has(u.deployment)) byDeployment.set(u.deployment, []);
    byDeployment.get(u.deployment).push(u);
  }
  return [...byDeployment].map(([i, units]) => entryBlock(deployment(i), units)).join('');
}

function moveHint(locs) {
  if (!allowed('move-unit') || !locs.some((l) => unitsAt(ui.view, l).some((u) => u.side === seat()))) return '';
  return '<div class="note hint">Sandbox: Alt-click a hex or box to move your units from here to there.</div>';
}

function renderSelection() {
  const panel = $('#selection');
  const sel = ui.selection;
  if (!sel || !ui.view) { panel.hidden = true; return; }
  panel.hidden = false;
  let html;
  if (sel.kind === 'hex') {
    const box = ui.board.holdFor.get(sel.id);
    html = `<div class="kind">Hex</div><h3>${escapeHtml(hexTitle(sel.id))}</h3><table>${hexFacts(sel.id)}</table>
      ${box ? `<div class="note">Counters here are kept in the <a href="#" data-zone="${box}">${escapeHtml(ui.board.zones.get(box).name)}</a>.</div>` : ''}
      ${moveHint([sel])}${unitsHtml([sel])}`;
  } else if (sel.kind === 'zone') {
    const z = ui.board.zones.get(sel.id);
    const info = Object.entries(z.info || {}).map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(v)}</td></tr>`).join('');
    const locs = selectedLocs(sel);
    const hexId = locs[1]?.id;
    html = `<div class="kind">${ZONE_KINDS[z.kind]}${z.side ? ` · ${SIDES[z.side]}` : ''}</div><h3>${escapeHtml(z.name)}</h3>
      ${info ? `<table>${info}</table>` : ''}${z.text ? `<div class="note">${escapeHtml(z.text)}</div>` : ''}
      ${hexId ? `<div class="note">Stands for hex <a href="#" data-hex="${hexId}">${z.hex}</a>.</div>` : ''}
      ${moveHint(locs)}${unitsHtml(locs)}`;
  } else {
    const e = deployment(sel.id);
    const units = unitsOf(ui.view, sel.id).filter((u) => u.loc.kind === 'pool');
    if (!units.length) { select(null); return; }
    html = `<div class="kind">To be placed by the player</div><h3>${escapeHtml(e.at.area)}</h3>${entryBlock(e, units)}`;
  }
  $('#selection-body').innerHTML = html;
}

$('#selection').addEventListener('click', (ev) => {
  if (!ui.view) return;
  const a = ev.target.closest('a[data-zone], a[data-hex]');
  if (a) {
    ev.preventDefault();
    focusOn(a.dataset.zone ? { kind: 'zone', id: a.dataset.zone } : { kind: 'hex', id: a.dataset.hex });
  }
  const b = ev.target.closest('[data-place], [data-place-all], [data-unplace]');
  if (b?.dataset.place) startPlacing([b.dataset.place]);
  if (b?.dataset.placeAll) startPlacing(b.dataset.placeAll.split(','));
  if (b?.dataset.unplace) act('place-unit', { unit: b.dataset.unplace, loc: { kind: 'pool' } });
  if (ev.target.closest('.close')) select(null);
});
document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape' || $('#game').hidden || $('#briefing').open) return;
  if (ui.placing) stopPlacing(); else select(null);
});

function focusOn(sel) {
  if (sel.kind !== 'pool') map.flyTo(toLL(ui.board.centre(sel)), Math.max(map.getZoom(), zmax - 2.5), { duration: 0.5 });
  select(sel);
}

// ---------- the top bar ----------

const clockText = (c) => `${turnText(c)}${c.player ? ` · Player ${c.player}: ${SIDES[c.order[c.player]]}` : ''}${
  c.round > 1 ? ` · round ${c.round}` : ''}`;
const stepName = (id) => ui.steps?.[id]?.title || id;

function renderTopbar() {
  const v = ui.view;
  $('#game-turn').textContent = clockText(v.clock);
  $('#step-name').innerHTML = `${escapeHtml(v.now.title)}${v.now.case ? ` <span class="muted">(${escapeHtml(v.now.case)})</span>` : ''}`;
  const waiting = v.now.waiting;
  $('#step-wait').textContent = v.now.step === 'game-over' ? 'The game is over.'
    : waiting.includes(seat()) ? 'Your turn to act.'
      : waiting.length ? `Waiting for ${waiting.map((s) => SIDES[s]).join(' and ')}.` : '';
  $('#step-wait').classList.toggle('yours', waiting.includes(seat()));

  const buttons = [];
  if (allowed('set-order')) {
    buttons.push('<button type="button" data-act="set-order" data-player="A" title="Be Player A this OpStage (7.11)">Go first</button>',
                 '<button type="button" data-act="set-order" data-player="B" title="Be Player B this OpStage (7.11)">Go second</button>');
  }
  if (allowed('undo') && v.undo[seat()]?.length) buttons.push('<button type="button" data-act="undo">Undo</button>');
  if (allowed('repeat-loop')) {
    buttons.push('<button type="button" data-act="repeat-loop" title="Go round the Movement and Combat Phase again (5.2 III.G)">Move and fight again</button>');
  }
  if (allowed('end-step')) {
    const name = v.now.step === 'setup' ? 'Set-up done' : v.now.step === 'end-of-turn' ? 'End the Game-Turn' : 'Done';
    buttons.push(`<button type="button" class="primary" data-act="end-step">${name}</button>`);
  }
  if (allowed('resume-step')) buttons.push('<button type="button" data-act="resume-step">Not done yet</button>');
  $('#actions').innerHTML = buttons.join('');

  const held = ui.client.seats;
  $('#seat-switch').hidden = held.length < 2;
  $('#seat-switch select').innerHTML = held.map((s) => `<option value="${s}" ${s === seat() ? 'selected' : ''}>${SEATS[s]}</option>`).join('');
  $('#invite').hidden = !Object.keys(SIDES).some((s) => !v.seats[s]);
}

$('#actions').addEventListener('click', (ev) => {
  const b = ev.target.closest('[data-act]');
  if (!b || !ui.view) return;
  act(b.dataset.act, b.dataset.player ? { player: b.dataset.player } : {});
});

$('#seat-switch select').addEventListener('change', (ev) => {
  ui.client.seat = ev.target.value;
  store.set(`cna.seat.${ui.client.id}`, ui.client.seat);
  stopPlacing();
  // Until the new seat's view comes, nothing of the old one may be clicked:
  // its buttons would give the old seat's orders with the new seat's token.
  ui.view = null;
  $('#actions').innerHTML = '';
  $('#step-wait').textContent = '';
  $('#selection').hidden = true;
  ui.side = ui.client.seat in SIDES ? ui.client.seat : ui.side;
  listen();  // each seat has its own event numbers
  refresh();
});

$('#invite').addEventListener('click', () => {
  const free = Object.keys(SIDES).filter((s) => !ui.view.seats[s]);
  const links = free.map((s) => `${SIDES[s]}: ${location.origin}${location.pathname}#game/${ui.client.id}/join/${s}`);
  window.prompt(`Send the other player the link for their side:\n${links.join('\n')}`,
                links[0].slice(links[0].indexOf(': ') + 2));
});

// ---------- forces panel and log ----------

// Each deployment of the side with its units the view shows, split into
// those on the map and those still to be placed.
function deploymentsOf(side) {
  return deployments().map((e, i) => {
    const units = unitsOf(ui.view, i);
    return { e, i, placed: units.filter((u) => u.loc.kind !== 'pool'), pooled: units.filter((u) => u.loc.kind === 'pool') };
  }).filter((d) => d.e.side === side);
}

function renderForces() {
  if (!ui.view) return;
  for (const b of document.querySelectorAll('#forces .tabs button')) b.classList.toggle('on', b.dataset.side === ui.side);
  if (ui.side === 'log') { renderLog(); return; }
  const sel = ui.selection;
  const isOn = (d, units) => {
    if (!sel) return false;
    if (sel.kind === 'pool') return units === d.pooled && sel.id === d.i;
    return units === d.placed && units.some((u) => locKey(sel) === locKey(sel.kind === 'hex' ? u.loc : ui.board.shownAt(u.loc)));
  };
  const row = (d, units, pool) => `<div class="dep ${isOn(d, units) ? 'on' : ''}" data-entry="${d.i}" data-pool="${pool ? 1 : 0}">
      <div class="where">${escapeHtml(placeText(d.e.at))}${!pool && inSetup() && units[0].flex ? '<span class="flex-tag">flexible</span>' : ''}</div>
      <div class="who">${units.map((u) => escapeHtml(u.name)).join(' · ')}</div></div>`;
  const mine = deploymentsOf(ui.side);
  const placed = mine.filter((d) => d.placed.length);
  const pool = mine.filter((d) => d.pooled.length);
  const count = (ds, k) => ds.reduce((n, d) => n + d[k].length, 0);
  const hidden = inSetup() && seat() in SIDES && ui.side !== seat();
  const notes = setup()?.notes;
  $('#forces-body').innerHTML =
    (pool.length ? `<div class="forces-head">To be placed · ${count(pool, 'pooled')} units</div>${pool.map((d) => row(d, d.pooled, true)).join('')}` : '')
    + `<div class="forces-head">On the map · ${count(placed, 'placed')} units</div>${placed.map((d) => row(d, d.placed, false)).join('')}`
    + (hidden && ui.view.unseen ? `<div class="who">${ui.view.unseen} more unit${ui.view.unseen > 1 ? 's' : ''}, which this side
        places itself, stay${ui.view.unseen > 1 ? '' : 's'} hidden until both sides have set up.</div>` : '')
    + (notes ? `<div class="forces-head">Notes</div>${notes.map((n) => `<div class="who">${escapeHtml(n)}</div>`).join('<br>')}` : '');
}

$('#forces .tabs').addEventListener('click', (ev) => {
  const b = ev.target.closest('button[data-side]');
  if (b && ui.view) { ui.side = b.dataset.side; renderForces(); }
});
$('#forces-body').addEventListener('click', (ev) => {
  const d = ev.target.closest('[data-entry]');
  if (!d || !ui.view) return;
  const i = +d.dataset.entry;
  const units = unitsOf(ui.view, i).filter((u) => (u.loc.kind === 'pool') === (d.dataset.pool === '1'));
  if (!units.length) return;
  if (d.dataset.pool === '1') select({ kind: 'pool', id: i });
  else focusOn(ui.board.shownAt(units[0].loc));
});

const unitName = (id) => ui.view.units[id]?.name || 'a unit';

function movesText(moves) {
  const to = new Set(moves.map((m) => locKey(m.to)));
  if (moves.length > 2 && to.size === 1) return `${moves.length} units to ${placeName(moves[0].to)}`;
  return moves.map((m) => `${unitName(m.unit)} to ${placeName(m.to)}`).join(', ');
}

// An event in words.
function eventText(ev) {
  const who = SIDES[ev.by] || '';
  switch (ev.type) {
    case 'game-created': return 'The game was created.';
    case 'seat-taken': return `${ev.name} took the ${SEATS[ev.seat]} seat.`;
    case 'unit-placed': return `${who} placed ${movesText(ev.moves)}.`;
    case 'units-moved': return `${who} moved ${movesText(ev.moves)}.`;
    case 'move-undone': return `${who} took back a move.`;
    case 'side-done': return `${who} is done.`;
    case 'side-resumed': return `${who} is not done after all.`;
    case 'order-set': return `${SIDES[ev.order.A]} is Player A, ${SIDES[ev.order.B]} Player B.`;
    case 'clock-advanced':
      return `${stepName(ev.clock.step)} · ${clockText(ev.clock)}${ev.passed.length ? ` <span class="muted">(${ev.passed.length} steps with nothing to do passed)</span>` : ''}`;
    default: return escapeHtml(ev.type);
  }
}

function renderLog() {
  const items = [...ui.view.log].reverse().map((ev) => `<li><span class="seq">${ev.seq ?? ''}</span>
    <span class="${ev.type === 'clock-advanced' ? 'clock' : ''}">${ev.type === 'clock-advanced' ? eventText(ev) : escapeHtml(eventText(ev))}</span></li>`);
  $('#forces-body').innerHTML = `<ol class="log">${items.join('')}</ol>`;
}

// ---------- the game ----------

// Fetches the view again and redraws, unless the view shown already holds
// event number `seq` (by default it fetches anyway). Calls that come while it
// is fetching are folded into one more fetch.
// A fetch for a game or seat no longer shown is dropped, and the loop goes on
// with what the game shown now has asked for.
let refreshing = null;
let wanted = null;  // the event number the view must reach; null: nothing asked for
async function refresh(seq = Infinity) {
  wanted = Math.max(wanted ?? -Infinity, seq);
  if (refreshing) return;
  refreshing = (async () => {
    while (wanted !== null && ui.client) {
      const client = ui.client;
      const asked = client.seat;
      const want = wanted;
      wanted = null;
      if (ui.view && ui.view.seat === asked && ui.view.seq >= want) continue;
      let v;
      try {
        v = await client.view();
      } catch (e) {
        if (client === ui.client) { toast(e.message); return; }
        continue;
      }
      if (client !== ui.client || asked !== client.seat) continue;
      ui.view = v;
      render();
    }
  })();
  try { await refreshing; } finally { refreshing = null; }
}

function render() {
  drawUnits();
  renderTopbar();
  renderForces();
  renderSelection();
}

async function showGame(id, mapView) {
  const seats = Object.keys(tokensFor(id));
  if (!seats.length) { location.hash = '#games'; toast('This browser holds no seat in that game. Join it from the list.'); return; }
  if (ui.client?.id === id && ui.view) {  // the same game: only the map view changed
    show('game');
    if (mapView) map.setView(toLL([mapView.x, mapView.y]), mapView.z);
    return;
  }
  leaveGame();
  const remembered = store.get(`cna.seat.${id}`);
  const client = new GameClient(id, seats.includes(remembered) ? remembered : seats[0]);
  ui.client = client;
  clearGame();
  show('game');
  map.invalidateSize();
  if (!ui.board) {
    $('#loading').hidden = false;
    try { await loadBoard(); } finally { $('#loading').hidden = true; }
  }
  let cat;
  let view;
  try {
    [cat, ui.steps, view] = await Promise.all([catalog(), ui.steps || stepTitles(), client.view()]);
  } catch (e) {
    if (ui.client === client) { toast(e.message); location.hash = '#games'; }
    return;
  }
  if (ui.client !== client) return;  // the player went elsewhere meanwhile
  ui.view = view;
  ui.scenario = cat.scenarios.find((s) => s.id === view.scenario) || null;
  const name = ui.scenario ? ui.scenario.name : view.scenario;
  document.title = `${name} · Campaign for North Africa`;
  $('#game-name').textContent = name;
  ui.side = seat() in SIDES ? seat() : 'axis';
  select(null);
  render();
  if (mapView) map.setView(toLL([mapView.x, mapView.y]), mapView.z);
  else openingView();
  writeHash();
  listen();
}

// Follows the game's stream, from the view shown if it is the seat's.
function listen() {
  const after = ui.view && ui.view.seat === ui.client.seat ? ui.view.seq : -1;
  ui.client.listen((seq) => refresh(seq), after,
                   () => toast('Lost contact with the game: reload the page to see the moves to come.'));
}

// A hidden tab gives up its stream: browsers allow only a few connections to
// one server, and each open stream holds one.
document.addEventListener('visibilitychange', () => {
  if (!ui.client || !ui.view) return;
  if (document.hidden) ui.client.close();
  else listen();  // the stream says at once if the game moved on meanwhile
});

function leaveGame() {
  ui.client?.close();
  ui.client = null;
  ui.view = null;
  stopPlacing();
  clearGame();
}

// The game screen with nothing of a game on it, while one loads.
function clearGame() {
  for (const sel of ['#game-name', '#game-turn', '#step-wait', '#actions', '#forces-body']) $(sel).innerHTML = '';
  $('#step-name').textContent = 'Loading the game…';
  $('#seat-switch').hidden = true;
  $('#invite').hidden = true;
  ui.groups.units?.clearLayers();
  ui.groups.selection?.clearLayers();
  ui.selection = null;
  $('#selection').hidden = true;
}

// Open on the front: the stretch of map, about a section and a half wide,
// with the most units, so far garrisons don't zoom the map right out.
const FRONT_WIDTH = 9000;  // scan pixels
function openingView() {
  const pts = unitList(ui.view).filter((u) => u.loc.kind === 'hex').map((u) => ui.board.centre(u.loc)).sort((a, b) => a[0] - b[0]);
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

// The game and view in the URL (#game/<id>/x/y/zoom, scan pixels), so a reload returns here.
function writeHash() {
  if ($('#game').hidden || !ui.client) return;
  const p = fromLL(map.getCenter());
  history.replaceState(null, '', `#game/${ui.client.id}/${Math.round(p.x)}/${Math.round(p.y)}/${map.getZoom()}`);
}
map.on('moveend', writeHash);

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
    <dt>Initiative</dt><dd>${escapeHtml(su.initiative.text)}</dd></dl>`;
}

function openBriefing() {
  const s = ui.scenario;
  const su = setup();
  if (!s || !su) {
    $('#briefing-body').innerHTML = `<p>The scenario of this game, ${escapeHtml(ui.view.scenario)}, is no longer in
      data/scenarios.json, so there is no briefing to show. The game itself plays on as it was set up.</p>`;
    $('#briefing').showModal();
    return;
  }
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
  // The server counts them as a new game places them (setup.counts).
  const count = (side, pool) => su.counts[side][pool ? 'pool' : 'map'];
  $('#scenario-detail').innerHTML = `<h3>${escapeHtml(chosen.name)}</h3>
    <div class="sub">${escapeHtml(chosen.group)} · Case ${chosen.rule}</div>
    <p>${escapeHtml(chosen.summary)}</p>
    <div class="counts">
      <div><b>${count('axis', false)}</b>Axis units on the map${count('axis', true) ? `, ${count('axis', true)} to place` : ''}</div>
      <div><b>${count('cw', false)}</b>Commonwealth units on the map${count('cw', true) ? `, ${count('cw', true)} to place` : ''}</div>
    </div>
    ${newGameForm(chosen, su)}
    ${scenarioFacts(chosen)}
    <section class="rule"><h4>Victory conditions (Case ${chosen.victory})</h4><div id="detail-victory" class="muted">Loading…</div></section>`;
  fillRule($('#detail-victory'), chosen.victory);
  store.set('cna.scenario', chosen.id);
}

function newGameForm(s, su) {
  const prefs = store.get('cna.newgame', { name: '', play: 'axis', sandbox: false });
  const init = su.initiative;
  const radio = (v, text) => `<label><input type="radio" name="play" value="${v}" ${prefs.play === v ? 'checked' : ''}> ${text}</label>`;
  return `<form id="new-game" class="new-game" data-scenario="${s.id}">
    <div class="row"><label>Your name <input name="name" maxlength="40" value="${escapeHtml(prefs.name)}" placeholder="Player"></label></div>
    <div class="row"><span class="lbl">Play</span>${radio('axis', 'Axis')}${radio('cw', 'Commonwealth')}
      ${radio('both', 'Both sides <span class="muted">(hot-seat, in this browser)</span>')}</div>
    <div class="row"><label>Initiative at the start <select name="initiative">
      <option value="">As the scenario says: ${SIDES[init.side]}</option>
      <option value="${init.side === 'axis' ? 'cw' : 'axis'}">${SIDES[init.side === 'axis' ? 'cw' : 'axis']}</option>
      ${init.may_roll ? `<option value="roll">Roll for it (${escapeHtml(init.rule)}): the roll comes with the
        Initiative rules; until then ${SIDES[init.side]} keeps it</option>` : ''}</select></label></div>
    <div class="row"><span class="lbl">Games</span><label><input type="checkbox" checked disabled> Land</label>
      <label class="muted"><input type="checkbox" disabled> Air <i>later</i></label>
      <label class="muted"><input type="checkbox" disabled> Logistics <i>later</i></label></div>
    <div class="row"><label><input type="checkbox" name="sandbox" ${prefs.sandbox ? 'checked' : ''}> Sandbox:
      move units anywhere in your Movement Segment, until the movement rules arrive</label></div>
    <button class="start" type="submit">Start the game</button></form>`;
}

$('#scenario-detail').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const play = f.play.value;
  const prefs = { name: f.name.value.trim(), play, sandbox: f.sandbox.checked };
  store.set('cna.newgame', prefs);
  const seats = play === 'both' ? ['axis', 'cw'] : [play];
  f.querySelector('button[type=submit]').disabled = true;
  try {
    const id = await createGame({ scenario: f.dataset.scenario, sandbox: prefs.sandbox, initiative: f.initiative.value || null },
                                seats, prefs.name);
    location.hash = `#game/${id}`;
  } catch (e) {
    toast(e.message);
    f.querySelector('button[type=submit]').disabled = false;
  }
});

async function showGames() {
  show('games');
  const body = $('#games-body');
  body.innerHTML = '<p class="muted">Loading…</p>';
  let games;
  let cat;
  try {
    [games, cat] = await Promise.all([listGames(), catalog()]);
  } catch (e) {
    body.innerHTML = `<p>The saved games could not be loaded: ${escapeHtml(e.message)}</p>`;
    return;
  }
  if (!games.length) {
    body.innerHTML = '<p>No saved games yet. <a href="#scenarios">Start a new one.</a></p>';
    return;
  }
  const rows = games.map((g) => {
    const s = cat.scenarios.find((x) => x.id === g.scenario);
    const held = tokensFor(g.id);
    const offered = Object.keys(g.sandbox ? SEATS : SIDES);  // only sandbox games have a referee
    const seats = offered.map((k) => `${SEATS[k]}: ${g.seats[k] ? escapeHtml(g.seats[k].name) : '<i>free</i>'}`).join(' · ');
    let actions;
    if (g.old) actions = '<span class="muted">Saved by another version of the program; it cannot be opened.</span>';
    else {
      const free = offered.filter((k) => !g.seats[k] && !held[k]);
      actions = [Object.keys(held).length ? `<a class="button primary" href="#game/${g.id}">Continue</a>` : '',
                 ...free.map((k) => `<a class="button" href="#game/${g.id}/join/${k}">Join as ${SEATS[k]}</a>`)].join(' ');
    }
    return `<li><div class="name">${escapeHtml(s ? s.name : g.scenario)} <span class="muted">${escapeHtml(g.id)}</span></div>
      <div class="muted">${g.where.step === 'setup' ? 'Set-up' : turnText(g.where)} · ${escapeHtml(stepName(g.where.step))}
        · last played ${escapeHtml(new Date(g.updated || g.created).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }))}</div>
      <div>${seats}</div><div class="actions">${actions}</div></li>`;
  });
  body.innerHTML = `<ol class="game-list">${rows.join('')}</ol>`;
}

async function showJoin(id, seatId) {
  show('join');
  const body = $('#join-body');
  body.innerHTML = '<p class="muted">Loading…</p>';
  let games;
  let cat;
  try {
    [games, cat] = await Promise.all([listGames(), catalog()]);
  } catch (e) {
    body.innerHTML = `<p>The game could not be loaded: ${escapeHtml(e.message)}</p>`;
    return;
  }
  const g = games.find((x) => x.id === id);
  if (!g || !(SIDES[seatId] || (seatId === 'referee' && g.sandbox))) {
    body.innerHTML = '<p>There is no such game or seat. <a href="#games">See the games.</a></p>';
    return;
  }
  if (tokensFor(id)[seatId]) { location.hash = `#game/${id}`; return; }
  const s = cat.scenarios.find((x) => x.id === g.scenario);
  const seatWords = (k) => (k === 'referee' ? 'the referee' : `the ${SIDES[k]} side`);
  if (g.seats[seatId]) {
    body.innerHTML = `<p>${escapeHtml(g.seats[seatId].name)} already plays ${seatWords(seatId)} of this game. <a href="#games">See the games.</a></p>`;
    return;
  }
  const others = Object.keys(SEATS).filter((k) => k !== seatId && g.seats[k])
    .map((k) => `${escapeHtml(g.seats[k].name)} plays ${seatWords(k)}.`).join(' ');
  body.innerHTML = `<h3>${escapeHtml(s ? s.name : g.scenario)}</h3>
    <div class="sub">${others}</div>
    <form id="join-form" class="new-game">
      <div class="row"><label>Your name <input name="name" maxlength="40" value="${escapeHtml(store.get('cna.newgame', {}).name || '')}" placeholder="Player"></label></div>
      <button class="start" type="submit">${seatId === 'referee' ? 'Watch as the referee' : `Play ${SIDES[seatId]}`}</button></form>`;
  $('#join-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try {
      await joinGame(id, seatId, ev.target.name.value.trim());
      store.set(`cna.seat.${id}`, seatId);
      location.hash = `#game/${id}`;
    } catch (e) {
      toast(e.message);
    }
  });
}

async function route() {
  const h = location.hash;
  let m;
  if ((m = h.match(/^#game\/([a-z0-9-]+)\/join\/(\w+)/))) { leaveGame(); showJoin(m[1], m[2]); return; }
  if ((m = h.match(/^#game\/([a-z0-9-]+)(?:\/(-?\d+)\/(-?\d+)\/([\d.]+))?/))) {
    showGame(m[1], m[2] ? { x: +m[2], y: +m[3], z: +m[4] } : null);
    return;
  }
  leaveGame();
  if ((m = h.match(/^#play\/([\w-]+)/))) location.hash = `#scenarios/${m[1]}`;  // the old link form
  else if (h === '#games') { ui.steps = ui.steps || await stepTitles().catch(() => null); showGames(); }
  else if ((m = h.match(/^#scenarios(?:\/([\w-]+))?/))) showScenarios(m[1]);
  else { show('title'); document.title = 'Campaign for North Africa'; }
}
window.addEventListener('hashchange', route);
route();
