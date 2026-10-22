"""A game's state: plain data that can be saved as JSON and sent as it is.

Dicts, lists, strings, numbers and None only, never classes, so the same data
is saved, sent and checked in tests. Only events change it (events.py).

  version     the event version the game was created with (EVENT_VERSION)
  id          the game's id; also the name of its folder under saves/
  scenario    the scenario's id in data/scenarios.json
  games       which games are played: {land, air, logistics}
  sandbox     whether stacks may be moved anywhere, for trying things out
  start, end  the scenario's first and last OpStage: {turn, stage}
  seats       who sits in each seat (SEATS): {name, key} or None; key is the
              hash of the player's token (seats.py)
  initiative  {side, through}: the side with the Initiative, fixed by the
              scenario through Game-Turn `through` (7.15)
  clock       the place in the sequence of play (sequence.py)
  dice        {seed, rolls}: the dice's seed and how many have been rolled (dice.py)
  units       unit id -> unit: one per unit of the log sheets, attached or not
              (setup.py). The charts' data (names, ID code, ratings) is not
              copied here but looked up by oa (oa.py), so that a fix in the
              data reaches games already started.
                id        the OA id, or <setup>.<deployment>.<listing> for a
                          unit with no OA entry
                oa        the OA id; None for those, which carry their own kind,
                          name, type and size
                side, nat
                toe       the TOE Strength Points it has now: {w, n} of a
                          weapons system, {n} of its own kind, {code, n} of
                          another ID code (oa.py)
                morale    {basic, current} (17.1, 17.3), or None
                parent    the formation it is assigned to, or None
                attached  the unit it is attached to and carried by, or None (4.25)
                loc       where its counter is; None while it is attached
                flex      whether the player places it in the Set-up Stage
                deployment, listing   the deployment and listing it came from
  deployments the scenario's deployments, with their listings' names and texts
              but not their units, by index: a unit's `deployment` and
              `listing` (setup.py). Only shown, never changed.
  undo       side -> the side's moves in the current step that it can take back (units.py)
  seq        the number of the last event applied
"""
EVENT_VERSION = 2  # 2: a unit per OA unit, attached or not (M1)
SIDES = ('axis', 'cw')
SIDE_NAMES = {'axis': 'Axis', 'cw': 'Commonwealth'}
SEATS = (*SIDES, 'referee')  # the referee sees everything and gives no orders


def other(side):
    """The opposing side."""
    return SIDES[1 - SIDES.index(side)]


def new(*, id, scenario, games, sandbox, start, end, initiative, clock, units, seed, deployments=()):
    """A game's state before its first event."""
    return {
        'version': EVENT_VERSION,
        'id': id,
        'scenario': scenario,
        'games': dict(games),
        'sandbox': bool(sandbox),
        'start': dict(start),
        'end': dict(end),
        'seats': {seat: None for seat in SEATS},
        'initiative': dict(initiative),
        'clock': clock,
        'dice': {'seed': seed, 'rolls': 0},
        'units': units,
        'deployments': list(deployments),
        'undo': {side: [] for side in SIDES},
        'seq': 0,
    }
