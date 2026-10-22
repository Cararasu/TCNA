# Roadmap: a complete Campaign for North Africa

The goal is the whole game as the rulebook defines it. Every case in Sections
6–58 is either carried out by the program or recorded as not needing
code. Every scenario (Sections 60–64) can be played in each combination the
rulebook allows:

- the Land Game alone, with abstract supply and air (32.0)
- Land + Logistics, with abstract air (58.0)
- Land + Air, with abstract logistics (47.0)
- all three games together

Case numbers below refer to the rulebook. The rulebook text itself stays local
(see the README).

## Where we are

| Have | Missing |
| --- | --- |
| Joined map: 7300 hexes with terrain, hexsides and landmarks. The map vocabulary covers every terrain and hexside row of the Terrain Effects Chart (8.37). | Map review: 0 of 7300 hexes are marked reviewed. Movement and combat costs are only as good as this data. |
| The engine (M0): games on a local server, saved as they are played, the sequence of play, the secret Set-up Stage, hot-seat and two-browser play. | Every rule of play: movement, combat, supply. |
| The unit data (M1): every OA unit with its TOE, ratings and morale; all 8 scenarios' set-ups expanded into them, with the tank tables; attachment, log sheets, and hidden strengths. | Reinforcements, organization, breakdown and the set-ups' upgrades (M4). Supplies, trucks, air forces, the fleet and Malta for each scenario. |

The rulebook transcription contains everything the rules need as Markdown
tables, so it can be parsed rather than typed in:

- the Organization at Arrival charts (4.44), giving each unit's ID code, TOE,
  weapon systems and arrival (extracted in M1)
- the unit, tank and gun characteristics (4.46–4.49) (extracted in M1)
- the reinforcement schedules (4.43)
- every combat results table and modifier chart
- the 45 worked examples, which become test cases

## Architecture

The rules run on the **server, in Python** (`cna/engine/`, `cna/rules/`). The
browser shows one player's view of the game and sends that player's orders. This
choice follows from three things the rulebook requires:

- **Hidden information.** Barrages and force assignment are plotted secretly and
  at the same time (11.0, 12.0, 14.0). Patrols and reconnaissance (16.0) reveal
  enemy units. Supply units can be dummies (32.18). A server can give each player
  only what that player may see.
- **Several players per side.** The rulebook expects separate roles on each
  side: logistics, air, rear-area and front-line commanders (2.3). All of them
  need to see one shared game.
- **Games that last hundreds of hours.** The game has to survive restarts and
  can be replayed for auditing.

The pieces:

- **State:** plain data, saved as JSON. It holds units and their log-sheet
  entries (TOE strength points, morale, attachments, supply), the place in the
  sequence of play, supplies, trucks and markers.
- **Commands → events:** every player action is a command. The rules check it
  and turn it into events, and applying the events changes the state. A saved
  game is its event log (plus snapshots), so it can be replayed exactly.
  Undo is possible until an action is committed.
- **Dice:** a seeded RNG, with every roll recorded as an event. Both sides can
  look up any roll afterwards.
- **Sequence of play** (5.2, 33.0, 48.0): the turn structure is stored as data,
  from Game-Turn and OpStage down to phase, segment and step. Which steps exist
  depends on which games are being played. A step lists the commands allowed in
  it and who may issue them.
- **Views:** a function from the state and a player to what that player may see.
- **Rule coverage:** each rule function names the cases it implements. A script
  checks those against every case number in the transcription and reports what
  is still missing. That report measures how close we are to "feature complete".
- **API:**
  - `GET /api/games/<id>/view` returns the player's view.
  - `POST /api/games/<id>/commands` submits an order.
  - Server-sent events push updates to the other players.
  - Hot-seat play is the same thing with players switched in one browser.
- **Client:** `web/game/board.js` stays as it is. `state.js` becomes a view
  model with no rules in it; its `newGame` moves to the server. Each phase gets
  its own UI panel, and the paper log sheets become panels too.

## Set-up

Setting up a scenario is a stage of its own, before Game-Turn 1, in which
the players make real choices (59.2–59.6). It runs on the same engine as play:
a **Set-up Stage** at the start of the sequence of play, with its own commands.
Both sides set up at the same time and in secret; the set-ups are revealed when
play begins. (The rulebook gives no order, and secret set-up suits fog of war.)

Creating a game means choosing a scenario, which games are played (Land; + Air;
+ Logistics), and who plays which side. The Set-up Stage then places every
fixed deployment and gives each player the rest:

| Set-up step | Rules | Comes with |
| --- | --- | --- |
| Place the fixed deployments; the player places the rest freely | 59.2 | M0 |
| Expand parent formations into their units from the OA charts, with the scenario's *Less*/*Assg*/*Det*/*Consists of*/*Att* changes | 59.2, 4.4 | M1 |
| Check placements: the units given several hexes may be split between them, and placements must keep to "within N hexes" and to stacking | 59.2, 9.0 | M2 |
| Reorganize the units in each hex (free attach and detach), within the formation limits | 59.2, 19.0 | M4 |
| Work out motorization points from the listed trucks; place supply units; load the starting supplies | 59.62–59.66, 32.0, 47.0 | M5 |
| Assign first-line trucks to the units in their hex; place second- and third-line trucks; place supply dumps, real and dummy | 59.4, 59.5, 53.0, 54.0 | M7 |
| Distribute planes among squadrons, assign pilots, place squadrons on air facilities | 59.3, 35.0, 36.0 | M8 |

The scenario data grows with it. Today `scenarios.json` holds the land
deployments and their first-line trucks. M5 adds each scenario's supply units,
M7 its supplies and second- and third-line trucks, and M8 its air forces,
Malta, and the forces in Sicily, Italy and Crete.

## Milestones

Each milestone ends in something playable and comes with tests: unit tests per
case, the rulebook's examples, and replays of scripted turns.

### M0 — Engine skeleton (no rules yet)

State, commands, events, dice, the sequence of play (Land Game, 5.2), player
views, saving and loading, the API with server-sent events, and the rule
coverage report. The browser loads a game from the server, shows the current
phase, and has an "end phase" button. Counters can be moved freely, for
debugging.

Creating a game (choosing the scenario, the games played and the sides) and the
Set-up Stage (see [Set-up](#set-up)). Fixed deployments are placed
automatically; the player places the flexible ones anywhere, with no checks yet.
**Done when** two browser windows can create the Graziani game, set up both
sides and play several turns, and a reload or server restart continues where
they left off.

### M1 — Unit data

- **OA charts and characteristics.** The organization charts and the
  characteristics charts become `data/units/` (formations, units, ID codes,
  weapon systems, arrivals) and `data/tables/`.
- **Scenario links.** Each scenario deployment names its OA units instead of
  free-text names. A deployment's own composition, given in parentheses
  (59.2), overrides the chart.
- **Log-sheet model.** Each unit has TOE strength points, morale, attached
  units, and a parent formation.

**Done when** every unit in every set-up resolves to its OA entry with its full
characteristics, checked by a test.

Done. What the set-ups say that a later milestone carries out is listed under
`later` in `data/scenarios.json`.

### M2 — Land movement

- Capability points (6.0)
- Initiative (7.0)
- Land movement (8.0): terrain costs from the Terrain Effects Chart, roads and
  tracks, continual movement (8.2), reaction, rail (8.7), and the off-map boxes
  (8.8)
- Stacking (9.0, 32.9)
- Zones of control (10.0)
- Reserve status (18.0)
- Weather (29.0)

In the UI: the possible moves highlighted on the map, and the capability-point
cost of a path before it is committed.
**Done when** a whole turn of movement follows the rules, including reaction by
the other side.

### M3 — Land combat

- The combat system (11.0), including position determination
- Barrage (12.0)
- Retreat before assault (13.0)
- Anti-armor combat (14.0)
- Close assault (15.0)
- Patrols and reconnaissance (16.0), which turns on fog of war
- Morale (17.0)
- Prisoners (28.0)

Secret plotting and simultaneous resolution come from the engine.
**Done when** every combat table reproduces the rulebook's examples, and a
battle in a scenario plays out by the rules.

### M4 — Forces over time

- Organization and reorganization (19.0)
- Reinforcements, replacements and withdrawals (20.0), including Commonwealth
  production (20.78)
- Training (17.6)
- Breakdown (21.0) and repair (22.0)
- Rommel (31.0)

**Done when** units arrive and leave on schedule, and their strength rises and
falls with combat, breakdown and repair, all recorded on their log sheets.

### M5 — Abstract supply and victory: **the Land Game is playable**

- Supply units, motorization points, simplified Axis convoys and bombardment of
  the Commonwealth fleet (32.0)
- The abstractions each scenario lists for play without the Air and Logistics
  Games (59.12g)
- Initiative and special rules for each scenario
- Victory conditions (60.8, 61.8, …)

**Done when** *The Race for Tobruk*, which the rulebook recommends as the
first game to try (59.0), and *Graziani's Offensive* can be played from start to
victory as the Land Game.

### M6 — The rest of the Land Game

- Engineers (23.0)
- Construction (24.0)
- Fortifications (25.0)
- Minefields (26.0)
- Desert raiders and commandos (27.0), including the raid on Rommel and SAS
  raids
- The Mediterranean Fleet (30.0)

**Done when** all scenario groups, including the campaign game (64.0), are
playable as the Land Game and the coverage report shows Sections 6–32 complete.

### M7 — Logistics Game

- The logistics sequence of play (48.0)
- Fuel (49.0), ammunition (50.0), stores (51.0) and water (52.0, including
  wells and poisoning)
- Trucks and transport (53.0): first-, second- and third-line trucks
- Supply coordination and dumps (54.0)
- Ports (55.0)
- The Axis naval convoy system (56.0)
- The Commonwealth supply base (57.0)
- Abstract air (58.0)
- Each scenario's supplies and trucks

The UI is the logistics commander's work: dumps, convoys and truck assignments.
This is the paperwork the program takes over.
**Done when** the scenarios play as Land + Logistics.

### M8 — Air Game

- The air sequence of play (33.0)
- Aircraft and pilots (34.0, 38.0)
- Squadron ground support units (35.0) and air facilities (36.0)
- Flight (37.0) and missions (39.0)
- Fighter combat (40.0), bombing (41.0) and non-combat missions (42.0)
- The Italian-Aegean air bases (43.0) and Malta (44.0)
- Air-to-air combat (45.0) and flak (46.0)
- Abstract logistics (47.0)
- Data: the aircraft characteristics charts, pilot and plane arrival tables, and
  each scenario's air forces

**Done when** the scenarios play as Land + Air.

### M9 — The full game

All three games together, with their sequences of play interleaved, and the
campaign game in full. This also needs performance work, since the campaign is
111 Game-Turns of 3 OpStages each, and compaction of saved games.
**Done when** the coverage report shows Sections 6–58 complete and the campaign
game runs in full mode.

Logistics comes before air because supply is the core of CNA's design. The
abstract air rules (58.0) are small, while abstract logistics (32.0) is almost a
game of its own.

## Running alongside

- **Map review** in the editor, best finished before M2: movement costs depend
  on it.
- **Roles** (2.3): giving each player on a side a role with its own
  permissions. Possible any time after M0; until then, one player per side.
- **Rule text everywhere:** each prompt and each refused order names the case
  behind it. `/api/rules/<case>` already serves the text.
- **Rulebook errors:** where the rulebook contradicts itself, the decision is
  recorded with its case number, in the same way the `fix` notes in
  `scenarios.json` are.

## Not planned

- A computer opponent.
- Hosting on the internet: accounts, matchmaking.

## Decisions to make

1. **How it is played.** Hot-seat and local-network play come with the server
   design. A computer opponent would be a separate, very large project.
2. **Order after the Land Game.** This plan puts logistics before air.

Decided:

- **Data drawn from the rulebook is committed.** The unit charts, combat
  tables and schedules are extracted from the transcription by scripts under
  `tools/`, and the results are committed with them, as `scenarios.json` is.
  The game can't run without them. The transcription itself, and any rule
  text, stay local.

- **The rules run only on the server**, in Python, for play across browsers.
  The browser has no rule code. To show what an order would do, it asks the
  server for a preview, worked out from what that player can see, and the
  server checks the order again when it is given.
- **Saved games** are not promised to keep loading across versions until the
  rules settle.
