// Runs web/shared/hex.js on cases sent by tests/test_parity.py (JSON on
// stdin) and prints its answers as JSON, for comparison with the Python side.

import { pathToFileURL } from 'node:url';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

let text = '';
for await (const chunk of process.stdin) text += chunk;
const input = JSON.parse(text);
globalThis.CNA_VOCAB = input.vocab;  // vocab.js would otherwise ask the server

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const hex = await import(pathToFileURL(join(root, 'web', 'shared', 'hex.js')).href);

console.log(JSON.stringify({
  constants: { DIRS: hex.DIRS, OPPOSITE: hex.OPPOSITE, SIDE_CORNERS: hex.SIDE_CORNERS, NEIGHBOURS: hex.NEIGHBOURS },
  normSide: input.sides.map((s) => hex.normSide(s)),
  hexOf: input.hexes.map(([auto, corr]) => hex.hexOf(auto, corr)),
  neighbours: input.ids.map((id) => hex.DIRS.map((d) => hex.neighbourId(id, d))),
  sideKeys: input.ids.map((id) => hex.DIRS.map((d) => hex.sideKey(id, d))),
}));
