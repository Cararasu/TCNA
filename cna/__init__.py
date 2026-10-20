"""The Campaign for North Africa: map data, scans and the local server.

  paths        where data, caches and the web front end live
  vocab        the map's vocabulary (data/vocab.json)
  hexgrid      hex ids, neighbours and grid geometry fitted to the scans
  corrections  one section's hand corrections: their form, checks and storage
  joined       the five sections joined into one map, shared hexes kept in sync
  scans        the scanned map sheets: download, zoom levels, tiles
  mapdata      what the server sends: map overlays, the game board, the title image
  rulebook     rule text from the local rulebook transcription
  engine       the game engine: state, events, commands, dice, the sequence of play
  rules        rule coverage marks: implements(...) and not_needed(...)
  server       the HTTP server (python -m cna.server)
  sync         copy each shared hex's corrections to all its copies (python -m cna.sync)
"""
