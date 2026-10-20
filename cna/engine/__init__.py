"""The game engine: the rules run here, on the server, and nowhere else.

  state     a game's state: plain data that can be saved as JSON
  events    what happened; only events change the state
  commands  what a player asks for: the registry, Refused, and running a command
  dice      rolls from the game's seed and the number of dice rolled so far
  sequence  the sequence of play as data, and the clock that walks it
  play      the commands that move a game along the sequence of play
  board     the map as the rules see it: hexes, section labels, off-map boxes
  setup     a new game's starting state from a scenario
  units     placing units in the Set-up Stage, sandbox moves, undo
  store     saving a game: its event log, snapshot and meta (saves/<id>/)
  seats     who plays which side: tokens and their keys
  views     what one seat may see, for showing and for previews
  games     open games: one lock each, commands saved before they are answered, waiting for changes
"""
from . import play, seats, units  # noqa: F401  register their commands
