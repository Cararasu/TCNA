// A game in progress as plain data: which scenario, when it is, and where
// every unit is. It is what a saved game will hold (JSON.stringify(game)),
// so it refers to the scenario definitions (data/scenarios.json) and the
// board only by id and index, and never changes them.
//
// Rules that change the game belong here as functions from one state to the
// next, without the DOM or Leaflet; main.js draws the state and calls them.

export const SAVE_VERSION = 1;
const DEFAULT_NATION = { axis: 'it', cw: 'uk' };

// ---------- time ----------

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const WEEKS = ['I', 'II', 'III', 'IV'];

// Game-Turn 1 is the third week of September 1940; every month has four turns.
export function turnDate(t) {
  const k = t + 1;
  const m = 8 + Math.floor(k / 4);
  return `${MONTHS[m % 12]} ${WEEKS[k % 4]} ${1940 + Math.floor(m / 12)}`;
}
export const turnText = (p) => `Game-Turn ${p.turn}, OpStage ${p.stage} (${turnDate(p.turn)})`;

// ---------- places ----------

export const locKey = (loc) => (loc.kind === 'pool' ? 'pool' : `${loc.kind}:${loc.id}`);
export function parseLocKey(key) {
  const i = key.indexOf(':');
  return i < 0 ? { kind: key } : { kind: key.slice(0, i), id: key.slice(i + 1) };
}

// Where a deployment's 'at' puts its units: a hex or zone, or the pool of
// units the player places. flex: the units may be set up elsewhere nearby.
export function placement(at, board) {
  if (at.box) return { loc: { kind: 'zone', id: at.box }, flex: false };
  const ref = at.hex || (at.hexes && at.hexes[0]) || at.near || at.anchor;
  const id = ref && board.hexOfLabel(ref);
  if (!id) return { loc: { kind: 'pool' }, flex: true };
  return { loc: { kind: 'hex', id }, flex: !at.hex || !!at.within };
}

// ---------- a new game ----------

export function newGame(catalog, scenarioId, board) {
  const scenario = catalog.scenarios.find((s) => s.id === scenarioId);
  if (!scenario) throw new Error(`no scenario ${scenarioId}`);
  const units = [];
  catalog.setups[scenario.setup].deploy.forEach((e, i) => {
    const { loc, flex } = placement(e.at, board);
    e.units.forEach((u, k) => units.push({
      id: `${scenario.setup}.${i}.${k}`,
      deployment: i,  // index into the setup's deploy list
      side: e.side,
      nat: u.nat || e.nat || DEFAULT_NATION[e.side],
      name: u.name,
      type: u.type,
      size: u.size || '',
      ...(u.detail ? { detail: u.detail } : {}),
      loc: { ...loc },
      flex,
    }));
  });
  return { version: SAVE_VERSION, scenario: scenario.id, turn: scenario.start.turn, stage: scenario.start.stage, units };
}

// ---------- queries ----------

// The units at each place (the pool left out), in deployment order.
export function stacks(game) {
  const out = new Map();
  for (const u of game.units) {
    if (u.loc.kind === 'pool') continue;
    const k = locKey(u.loc);
    if (!out.has(k)) out.set(k, []);
    out.get(k).push(u);
  }
  return out;
}

export const unitsAt = (game, loc) => game.units.filter((u) => locKey(u.loc) === locKey(loc));
export const unitsOf = (game, deployment) => game.units.filter((u) => u.deployment === deployment);
