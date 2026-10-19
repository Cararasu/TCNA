// How a unit looks: its counter, NATO-style symbol and short name. Takes the
// units of a game (state.js).

import { UNIT_SIZES } from '../shared/vocab.js';
import { escapeHtml } from '../shared/util.js';

const SIZE_ORDER = Object.keys(UNIT_SIZES);  // largest first
const sizeRank = (u) => (u.size ? SIZE_ORDER.length - SIZE_ORDER.indexOf(u.size) : 0);

// A NATO-style unit symbol, 60 x 36.
export function unitSymbol(type) {
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

export function shortName(n) {
  return n.replace(/New Zealand/g, 'NZ').replace(/South African?/g, 'SA').replace(/Australian/g, 'Aus')
    .replace(/Armou?red/g, 'Arm').replace(/Indian/g, 'In').replace(/Infantry|Inf\b/g, 'Inf')
    .replace(/\b(Division|Div|Brigade|Regiment|Battalion)\b\.?/g, '').replace(/\s+/g, ' ').trim();
}

// The counter for one unit, or for a stack shown by its biggest unit.
export function counterHtml(units, opts = {}) {
  const top = units.reduce((a, b) => (sizeRank(b) > sizeRank(a) ? b : a));
  const second = units.find((x) => x !== top);
  const cls = ['ctr'];
  if (units.length > 1) cls.push('stacked');
  if (opts.flex) cls.push('flex');
  if (opts.sel) cls.push('sel');
  const style = `--nat:var(--n-${top.nat});--side:var(--${top.side});${second ? `--nat2:var(--n-${second.nat})` : ''}`;
  return `<div class="${cls.join(' ')}" style="${style}" title="${escapeHtml(units.map((x) => x.name).join(', '))}">
    <span class="side-strip"></span>
    <span class="size">${top.size}</span>${unitSymbol(top.type)}
    <span class="nm">${escapeHtml(shortName(top.name))}</span>
    ${units.length > 1 ? `<span class="n">${units.length}</span>` : ''}</div>`;
}
