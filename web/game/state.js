// Reading a game's view: what the server sends one seat of a game
// (/api/games/<id>/view, cna/engine/views.py). The view has the shape of the
// game's state; its units are {id: unit}, each at a loc. The rules are on the
// server, so nothing here changes a game.

// ---------- time ----------

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const WEEKS = ['I', 'II', 'III', 'IV'];

// Game-Turn 1 is the third week of September 1940; every month has four turns.
export function turnDate(t) {
  const k = t + 1;
  const m = 8 + Math.floor(k / 4);
  return `${MONTHS[m % 12]} ${WEEKS[k % 4]} ${1940 + Math.floor(m / 12)}`;
}
// A Game-Turn and OpStage ({turn, stage}; stage is null before the first OpStage of a turn).
export const turnText = (p) => `Game-Turn ${p.turn}${p.stage ? `, OpStage ${p.stage}` : ''} (${turnDate(p.turn)})`;

// ---------- places ----------

export const locKey = (loc) => (loc.kind === 'pool' ? 'pool' : `${loc.kind}:${loc.id}`);
export function parseLocKey(key) {
  const i = key.indexOf(':');
  return i < 0 ? { kind: key } : { kind: key.slice(0, i), id: key.slice(i + 1) };
}

// ---------- queries ----------

export const unitList = (view) => Object.values(view.units);

// The units at each place (the pool left out), in deployment order.
export function stacks(view) {
  const out = new Map();
  for (const u of unitList(view)) {
    if (u.loc.kind === 'pool') continue;
    const k = locKey(u.loc);
    if (!out.has(k)) out.set(k, []);
    out.get(k).push(u);
  }
  return out;
}

export const unitsAt = (view, loc) => unitList(view).filter((u) => locKey(u.loc) === locKey(loc));
export const unitsOf = (view, deployment) => unitList(view).filter((u) => u.deployment === deployment);
