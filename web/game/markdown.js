// Just enough Markdown for the rulebook transcription: headings, tables,
// paragraphs, bold and italics. Everything else is escaped.

import { escapeHtml } from '../shared/util.js';

function inline(s) {
  return escapeHtml(s.replace(/\\\*/g, '\u0001'))
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/\*(.+?)\*/g, '<i>$1</i>')
    .replace(/\u0001/g, '*');
}

export function markdown(text) {
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
