"""Coverage marks that belong to no Python function: cases needing no code,
and cases carried out elsewhere (the map data, the browser)."""
from . import implements, not_needed

not_needed('1', why='introduction: what the game is about')
not_needed('2.1', '2.2', '2.4', why='how to read the rules, prepare a game, and how long it takes: advice to the players')
not_needed('3.1', why='definitions of terms; each is carried out by the rules that use it')
not_needed('3.5', why="the unit characteristics' definitions; the characteristics charts carry them (cna.engine.oa)")
not_needed('4.21', '4.23', '4.24', why='what the printed counters and markers show; the program draws its own')
not_needed('4.3', why='where the charts and tables are printed; the program holds them as data')
not_needed('4.51', why='how the log sheets are grouped: "a presentation decision" with no effect on play')
not_needed('4.6', why='the inventory of game parts')

implements('4.26', where='web/game/board.js Board.shownAt: counters in a hex with a Holding Box are shown in the box')
implements('4.45', where='tools/units/oa.py: the OA Charts read into data/units/, each unit with its sheet, '
                          'ID code, parent, TOE on arrival and arrival date')
