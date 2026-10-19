# The Campaign for North Africa

A computer version of SPI's *The Campaign for North Africa* (1979), built on the
map sheets of the original game. So far it has two parts: a hand-checked digital
map, made by extracting the five scanned map sections, and a browser front end
that shows the joined board with each scenario's starting deployment.

## Running it

You need Python 3.8 or later and `pdfimages` (from Poppler or Xpdf) on `PATH`:

```
python -m pip install -r requirements.txt
start-game.cmd        # title screen and scenarios:  http://127.0.0.1:8765/
start-editor.cmd      # map editor:                  http://127.0.0.1:8765/editor.html
```

Both scripts start the same server, `python -m cna.server --port 8765`, run from
the project folder. On first start the server downloads the original rulebook
PDF from the Internet Archive (about 134 MB), pulls out the map scans, and builds
zoom levels under `.cache/server/`. This happens only once. The server listens
on localhost only.

## Tests

```
python -m unittest
```

The tests cover the hex geometry, the corrections checks and the joining of the
sections, and check that the data files agree with the vocabulary and with each
other. If Node.js is on `PATH`, they also check that the browser's hex rules give
the same results as the Python ones.

## Layout

| Path | What it is |
| --- | --- |
| `cna/` | The Python package. It holds the hex geometry, corrections, the joined map, the scans and tiles, the server's map data, and the HTTP server. `cna/__init__.py` lists the modules. |
| `web/` | The front end: ES modules with no build step, and Leaflet in `web/vendor/`. |
| `web/shared/` | Code both pages use. `vocab.js` holds the vocabulary plus colours and keys, `hex.js` has pure hex rules, `draw.js` does the Leaflet drawing, and `util.js` has small helpers. |
| `web/game/` | The game. `board.js` is the map, read-only. `state.js` is the game as plain, saveable data. `main.js` draws the board and the state and handles input. |
| `web/editor/` | The map editor. `warnings.js` checks the data; `main.js` is the editing UI. |
| `data/vocab.json` | Every terrain, landmark, line, hexside feature, river, and unit type and size, with its name. The server checks against this file and the browser loads it. |
| `data/map/<M>.json` | Automatic extraction for each map section (A–E, M = Malta inset): terrain for each hex, plus the features on its E/NE/NW hexsides. |
| `data/map/grid<M>.json`, `tiles<M>.json` | The hex grid fitted to each scan: a seed fit, then a piecewise (tiled) fit. |
| `data/map/corrections/<M>.json` | Hand corrections made in the editor. These hold **only** the differences from the automatic data, so the extraction can be rerun without losing them. |
| `data/map/offmap.json` | The off-map boxes printed on the sheets (Tunis, Tripoli, holding boxes, …). |
| `data/scenarios.json` | The scenarios (rulebook 59–64) and their initial land deployments. |
| `tools/map/` | Extraction pipeline: `fit_grid.py` → `fit_tiles.py` → `extract.py`, with `overlay.py` / `check_crop.py` for checking by eye and `find_symbols.py` for landmark candidates. Needs SciPy. |

## Map conventions

- Hex ids are `RRCC`: the row counts north and the column counts east. Even rows
  sit half a column east.
- Each hexside is stored once, under the hex that has it as its E, NE or NW side,
  using the key `"RRCC|D"`.
- Hex corners run counter-clockwise, starting from east-south-east. Side E is
  corners 0–1, NE is 1–2, and so on.
- On the joined map a hex is numbered by its column counted from Map A's west
  edge. Hex `RRCC` on one section is `RR(CC+33)` on the section to its west.
  Malta's rows start at 80.
- A hex or hexside on two sections has a copy in each section's corrections.
  The server keeps the copies identical: on start, and on every save. After
  editing correction files by hand, run `python -m cna.sync`.

## Not in version control

The rulebook PDF/EPUB and its Markdown transcription
(`The Campaign for North Africa.md`) stay local, since the transcription is
copyrighted. When the transcription is present, the game shows the text of the
rulebook cases it cites. Rendered scans and tile caches live in `.cache/`.
