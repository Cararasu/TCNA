// The game server's API (cna/server.py): games, seats, views, commands,
// previews and the change stream. The rules run on the server only; the
// browser shows a seat's view and sends its orders.
//
// Joining a seat gives a token, kept per browser in localStorage. A browser
// that holds both sides' tokens of a game plays it hot-seat.

import { store } from '../shared/util.js';

const TOKENS = 'cna.tokens';  // {game id: {seat: token}}

export const tokensFor = (gameId) => store.get(TOKENS, {})[gameId] || {};

const NO_STORAGE = 'This browser does not let the page keep anything (a private window, or site data '
  + 'blocked), so it could not hold your seat. Allow site data for this page and try again.';

// A seat taken without its token kept is lost for good, so storage is tried
// before a seat is asked for.
function checkStorage() {
  if (!store.set(TOKENS, store.get(TOKENS, {}))) throw new Error(NO_STORAGE);
}

function keepToken(gameId, seat, token) {
  const all = store.get(TOKENS, {});
  all[gameId] = { ...(all[gameId] || {}), [seat]: token };
  if (!store.set(TOKENS, all)) throw new Error(NO_STORAGE);
}

// A refusal or error from the server: its message, and the case behind it.
export class ApiError extends Error {
  constructor(status, body) {
    super(body?.error || `The server answered ${status}.`);
    this.status = status;
    this.case = body?.case || null;
  }
}

async function call(method, path, body, token) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data);
  if (data === null) throw new ApiError(res.status, { error: 'The server\'s answer could not be read.' });
  return data;
}

export const listGames = () => call('GET', '/api/games').then((r) => r.games);
export const stepTitles = () => call('GET', '/api/sequence').then((r) => r.steps);

// A new game, with this browser in `seats`: one side, or both for hot-seat play.
export async function createGame(choices, seats, name) {
  checkStorage();
  const made = await call('POST', '/api/games', { ...choices, seat: seats[0], name });
  keepToken(made.id, made.seat, made.token);
  for (const seat of seats.slice(1)) await joinGame(made.id, seat, name);
  return made.id;
}

export async function joinGame(gameId, seat, name) {
  checkStorage();
  const r = await call('POST', `/api/games/${gameId}/join`, { seat, name });
  keepToken(gameId, r.seat, r.token);
  return r.seat;
}

const newId = () => (globalThis.crypto?.randomUUID
  ? crypto.randomUUID() : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`);

// One game, played from one of the seats this browser holds.
export class GameClient {
  constructor(gameId, seat) {
    this.id = gameId;
    this.seat = seat;
    this.source = null;
  }

  get token() { return tokensFor(this.id)[this.seat]; }
  get seats() { return Object.keys(tokensFor(this.id)); }

  view() { return call('GET', `/api/games/${this.id}/view`, undefined, this.token); }
  // The TOE Log Sheet of one of the seat's counters (cna/engine/logsheets.py).
  logSheet(unit) {
    const path = unit.split('/').map(encodeURIComponent).join('/');
    return call('GET', `/api/games/${this.id}/logsheet/${path}`, undefined, this.token);
  }

  // Gives an order. If the network fails it is sent once more with the same
  // id, which the server runs at most once.
  async command(type, args = {}) {
    const send = () => call('POST', `/api/games/${this.id}/commands`, body, this.token);
    const body = { id: newId(), type, args };
    try {
      return await send();
    } catch (e) {
      if (e instanceof ApiError) throw e;
      return send();
    }
  }

  // What an order would do, without giving it: {events}, or {dice} when it needs dice.
  preview(type, args = {}) {
    return call('POST', `/api/games/${this.id}/preview`, { type, args }, this.token);
  }

  // Calls onChange(event number) whenever the seat may know of events past
  // number `after` (the numbers are the seat's own: a view's seq). EventSource
  // reconnects by itself and says where it got to; it can't send headers, so
  // the token goes in the query. onLost() is called if it gives up for good,
  // as it does when the server refuses the stream.
  listen(onChange, after = -1, onLost = () => {}) {
    this.close();
    const source = new EventSource(`/api/games/${this.id}/stream?token=${encodeURIComponent(this.token)}&after=${after}`);
    source.addEventListener('changed', (ev) => onChange(Number(ev.data)));
    source.addEventListener('error', () => {
      if (source.readyState === EventSource.CLOSED && this.source === source) onLost();
    });
    this.source = source;
  }

  close() {
    if (this.source) this.source.close();
    this.source = null;
  }
}
