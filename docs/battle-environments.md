# Battle environments (every place a 3D battle is fought)

Recorded 2026-10-11. Owner directive: "COMPLETE 3D BATTLE ENVIRONMENT OVERHAUL — ALL HOENN
LOCATIONS": audit every battle environment in the game, make the flat ones dimensional in the
classic Emerald style (real geometry, depth, light; no unrelated asset packs, no generic
low-poly look), reuse the overworld's environmental object library, change no mechanics, and
prove it with screenshots of real battles, reviewed by eye.

## Where it is

| Engine branch | Base | Commits | What |
| --- | --- | --- | --- |
| `claude/battle-environments` | `e747ce106` (`claude/native-graphics-3d-battles-4`, the merge candidate) | `779695f93` first round (Elite Four and Champion rooms, 45 rooms read off their cells, cave walls, the survey); `923e63569` the environment interface for future systems; `0677813f1` second round (more rooms and caves, the light round the stage, staging checks); `226d62af8`, `083bc9754` the test driver's autopilot and timeout; `debd0fae7` the Battle Dome's and Battle Factory's halls, Verdanturf's Battle Tent; `3253670fd` the scenery mirrored past its edges; `4f308a4c7` the sea floor's rock, the test driver locks the field for trainer battles, `survey.py --at`; `4002eac1f` the stage at its battlers' feet, wrong-map pictures caught, the report page; `cd36c10fd` the Battle Palace's arena flat again; `1dfc62cbe` the test driver's key presses held for frames (the 1440p and 4K runs); `55d732298` Lavaridge Gym B1F; `f96f41833` the stage search sees walls that are all face; `acd96dabc` the review and the report | This overhaul. Nothing of it is merged anywhere. Checkpoint `battle3d-env-wip-20261011-1`. |
| `claude/battle-environments-graphics8` | `claude/battle-environments` merged with the overworld session's `d799c4a8a` (`graphics-wip-20261010-8`: detail objects, seventy more buildings, lit windows) | `6507a67ea` the merge, the objects drawn in battles and seen by the stage search; `c12f2f96a`, `4661fc8b5` the later battle-environment commits merged in; `69440aa02` the objects' art from the field's last steady frame; `9c1c6aef8` the review merged in (tools only) | The same work on the overworld's newest tip, with its object library in battles. Not merged anywhere. |

The merge candidate `e747ce106`, its checkpoint `battle3d-wip-20261010-4` and the pending
graphics-card tests in `battle3d-test-runs\wip-20261010-4` are untouched and independent of
this work: this branch goes in after the candidate (it is built on it). Compiled only with
`DIORAMA=1`; the GBA ROM is unchanged (`f214735b…3387`). Player builds have no debug menu
and no test driver. The native session moved `claude/native-graphics` on to `d799c4a8a`
(`native-wip-20261010-8`) while this ran; `claude/battle-environments-graphics8` is this work
on that tip, so the overworld's new detail objects are drawn in battles too (one object
library for the field and battles, as the directive asks).

## Results

236 maps where a battle can start, found in the game's own data (map headers, wild encounter
tables, trainer and scripted battles, legendaries). Of them:

* **190 reviewed**: a real battle photographed there with this branch's TEST build and the
  picture classed by looking at it (A complete 3D, B needs polish, C partially 3D, D broken or
  mostly flat). The class and what the picture shows are in `tools/battle_env/review.json`;
  every picture is in the report (checkpoint `report\index.html`).
* **0 tested only**: every picture taken was looked at.
* **28 untested**: no picture of a battle there - the 24 secret bases (the game does not resume
  inside one), the Union Room's and the Mystery Events house's link battles, two of the Battle
  Pike's rooms (outside a challenge they start no battle). Reasons per map below.
* **18 excluded**: the Battle Pyramid's 16 floor squares (pieces its floor is put together from
  at run time) and the Dome's and Factory's waiting rooms (their battles are fought in the
  battle rooms, which are reviewed).

Classes after this work, all 190 reviewed maps: **A 5, B 122, C 61, D 2**. The 155 maps
photographed before the work as well: before **A 0, B 10, C 115, D 30**, after **A 5, B 108,
C 40, D 2**; 103 of them moved up a class or more, none down.

Every D and C indoors was worked on first: all five League rooms went from D to A; every Gym
floor, cave, hideout, tower, ship and Frontier room that had a picture is B. What stays C is
mostly outdoors and on the sea, where the flat parts are the overworld's own details; with the
overworld's detail objects drawn in battles (`claude/battle-environments-graphics8`, below) 22
outdoor maps move up to B. What stays D: Route 111's desert and Route 117 (the stage lands on
open sand or grass with nothing standing in view; Route 117 is C with the objects).

## What changed

### Rooms stand up (the shared model library)

The battle world is the overworld's: terrain, the 3DS trees and the modelled buildings
(`tools/diorama_buildings`, the 3DS project's generator: every model reproduces its own
drawing pixel for pixel in the GBA's projection). The rooms where battles are fought had no
models, so a battle in Sidney's room looked at the flat floor. Now they are models of the same
library - no model exists for battles only; the rooms stand in the field too:

* **The Elite Four's rooms and the Champion's room**, modelled piece by piece
  (`battle_room_specs.py`): the back wall with its lamps and door stands 40 rows on its foot,
  its light band laid back as its top; the long cases at the sides (Sidney's tiered seats,
  Phoebe's mossy stones, Glacia's ice, Drake's spikes) are boxes with their contents on top;
  the side walls, which the GBA never draws, are dressed with the back wall's panels. The
  Champion's hall is an octagon: the glass wall between the back corners, the corners
  chamfered at 45 degrees, the steps up to the Hall of Fame door, the side walls on to the front.
* **59 more rooms read off their cells** (`battle_room_auto.py`): a run of blocked cells whose
  top is the outside and whose foot is the floor is a wall's face (it stands its drawn height);
  blocked cells beside the outside are edges (a side wall's top seen from above); other blocked
  cells are furniture (statues, machines, maze blocks, graves) standing on their foot; where the
  floor reaches the map's edge a side wall closes the room. A blocked component that does not
  fill its rectangle (a maze, a ring of sand) is read as runs with one foot each. Gyms
  (Mauville, Lavaridge 1F and B1F, Fortree, Mossdeep, Sootopolis 1F and B1F), the Battle Frontier's
  and the Battle Tents' rooms, Team Aqua's hideout, Mt. Pyre (all six floors), Sky Pillar,
  Mirage Tower, the S.S. Tidal and the Abandoned Ship, New Mauville, the Trick House (1-4, 6, 7),
  the Space Center, the Weather Institute, the Oceanic Museum, the Seashore House, the link
  rooms. Dewford's, Petalburg's and Rustboro's Gyms were in the library already.
* **Proved before they go in** (`tools/battle_env/auto_rooms.py`): each model exact against
  its drawing, the room composed with every model standing in it the drawing again, pixel for
  pixel, and no walkable cells under a level surface half a tile up (a slab the GBA's camera
  cannot tell from the floor). A piece that fails is left out by name (`AUTO_DROP`) and the
  rest of the room stands; a room that fails is not listed. An auto room's pieces are reused
  only in the rooms proved with it.
* **And looked at from the battle's camera.** The proof sees the GBA's view only. The survey's
  picture of the Battle Palace showed what it cannot: the Palace's arena is impassable (the
  player watches from its edge), so its carpet was read as furniture and stood up as a block
  behind the battlers; its pieces are left out now (`cd36c10fd`) and the arena is the floor
  it is. Lavaridge Gym 1F's sand ridges (one slab over the room before the one-foot rule) were
  found the same way.
* A modelled building or room does not stand on a cell a script has redrawn
  (`DIORAMA_CELL_CHANGED`, `DioramaBuildings_Validate`): a Gym's barriers, an Elite Four door
  opening after a win.

### Caves get walls

Cave rock stands as cliffs one tile high: pins for the rules compiler
(`data/diorama/tilesets/cave.json`, `meteor_falls.json`, `rusturf_tunnel.json`,
`navel_rock.json`) chosen by `tools/battle_env/cave_pins.py` - impassable, no behaviour, in a
rock mass, not void, not showing the water's or the sky's blue. Granite Cave, Seafloor Cavern,
Shoal Cave, Cave of Origin, Victory Road, Meteor Falls, Rusturf Tunnel, the Desert Ruins, Island
Cave, the Ancient Tomb, Artisan Cave, Altering Cave, Terra and Marine Caves, Navel Rock, the
Desert Underpass. In the field too.

The sea floor's rock (`underwater.json`, `cave_pins.py --sea-floor`: under the sea the water's
blue is the floor every metatile is drawn over, so the water test is left out) stands the same
way: Underwater Routes 124 and 126 (the dive spots' seaweed battles) and diving in the field,
where the rock now walls the seaweed beds in.

### Light round the stage

`gl_battle.c` `DrawStageLight`: the battle's world darkens away from where the battlers stand,
a pool of light on the floor in the camera's perspective - an arena's light in a Gym and the
Frontier, a spotlight in the Elite Four's rooms and the Champion's tinted by the member's type
(Sidney crimson, Phoebe violet, Glacia deep blue, Drake ember, Wallace teal), the gloom of a
cave and of the sea floor, a little at night outdoors; none on a day outdoors or on the water.
Only the world: the Pokemon, the healthboxes and the text are drawn over it unchanged. The
kind of place comes from the backdrop the battle chose (map battle scene, Leader or Champion
class, Frontier). `PKMN_DIORAMA_BATTLE_LIGHT=0` turns it off, `_SCALE` scales it.

### Where the battlers stand

The stage search (`battle_stage.c`) puts the battle where both sides stand on fitting ground
and the camera sees no wall in front of them. It stood the battle at the height of the cell
under the camera's target - the point between the battlers - so a target on a bank or a rock
between two battlers on the water stood them a tile over the sea (Route 107, found by the
survey's staging check). The battle now stands at the height both sides' feet stand on when
they agree (`4002eac1f`, `test_battle_stage`); on flat ground nothing changes.

The search also read a room's walls from the models' heights as seen from above, and a wall
drawn all face (the back wall of the Abandoned Ship's lower cabins, in the middle of its deck)
has none: it stood the battle across that wall with both battlers inside it (the staging check
again: their pictures 100% and 64% behind the world). It now asks the models for an upright
face in the cell (`DioramaBuildings_FrontAt`, the walkers' occlusion test) at three heights
(`f96f41833`). Every indoor map was photographed again with it: in the ship the battle now
stands in the upper cabin, both battlers clear. In fifteen more rooms the stage moved (the
Space Center, the Museum, Mauville's, Mossdeep's and Petalburg's Gyms, the Battle Tower and its
multi room, the Factory, the Arena, the Pike, Verdanturf's tent, the colosseums, the Weather
Institute), mostly to stand before the room's back wall with more of the room upright in view;
in Mossdeep's Gym and on the Weather Institute's upper floor more of the GBA backdrop past the
room's edge shows than before (E7). Every other indoor battle stands where it stood.

### An interface for the systems to come (not wired to anything)

`include/diorama/battle_environment.h`, read on the render thread while a battle is drawn in
3D: each battler's ground point, view depth, pixels per tile, picture height in tiles and
attachment points (feet, centre, top, front); the camera with a column-major view-projection
matrix exactly as the scene shaders project; world <-> window; the light (fade and night tint,
haze, fog, indoor/cave/night); the kind of place; the window areas the battle's own interface
uses and a safe frame; a camera impulse (shake, push in) that leaves the battle's picture and
timing alone; passes drawn in the world after its terrain, buildings and trees (for props,
effects, animated sprites). Nothing registers a pass or asks for an impulse yet; with none, a
battle draws exactly as before. Checked by the test capture: each battler's ground taken back
to the window lands on its standing point, 0.0 px in single and double battles.

## The validation system

`tools/battle_env` (engine; `README.md` there): `inventory.py` (every battle-capable map from
the game's data: 236), `survey.py` (a real battle photographed on each map by a TEST build's
driver: `cap.png`, and `cap.json` with what the camera sees, the interface's check, each
battler's staging and the world's draw calls and frame times; `--at X,Y` to stand elsewhere;
a run whose game resumed on another map is marked `wrong map`, not taken as a picture),
`sheets.py` (contact sheets, before / after), `auto_rooms.py` (room proofs), `cave_pins.py`,
`perf.py` (1080p, 1440p, 4K), `report.py` (the per-map report: `report.md`, `report.json`,
and a page with every map's pictures and filters, `page/index.html`). Every class below comes
from looking at the pictures; the numbers in `cap.json` only point at a picture to look at.

The TEST driver (`-DDIORAMA_BATTLE_ENV_TEST`, never in a player build) presses through the
title, starts the battle the map is known for after 100 field frames, and saves the window at
the action menu. Since `4f308a4c7` a trainer battle locks the field first, as a trainer's
script does: before, on the slow maps a visible wild Pokémon could walk into the player or,
spawning, empty the trainer's party during the transition (N33; Mt. Pyre's and Magma
Hideout's first pictures showed it).

The two Windows player builds in the checkpoint (one per branch, stripped, debug menus off, the
test driver compiled out) were run as packed under Wine on the cloud computer's software
OpenGL: each started, continued a save, walked into a wild battle that drew in 3D (Granite
Cave 1F's rock walls; Route 102's tall grass standing on the second branch), ran from it and
came back to the 3D field. That shows the packages start and draw; it is not a graphics-card
measurement.

## The survey, place by place

### By kind of place

| Places | Maps | A | B | C | D | Photographed, not classed | No picture | Excluded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| League and Gyms | 15 | 5 | 10 | 0 | 0 | 0 | 0 | 0 |
| Battle Frontier and Tents | 42 | 0 | 13 | 8 | 0 | 0 | 3 | 18 |
| Caves and tunnels | 43 | 0 | 40 | 3 | 0 | 0 | 0 | 0 |
| Hideouts, towers, ships | 73 | 0 | 46 | 2 | 0 | 0 | 25 | 0 |
| Routes and land | 25 | 0 | 4 | 19 | 2 | 0 | 0 | 0 |
| Towns and cities | 8 | 0 | 4 | 4 | 0 | 0 | 0 | 0 |
| Sea, shore, underwater | 30 | 0 | 5 | 25 | 0 | 0 | 0 | 0 |

### Not photographed, and why

* secret base: the game does not resume inside one (the warp came back in Littleroot Town) (24): SECRET_BASE_BLUE_CAVE1, SECRET_BASE_BLUE_CAVE2, SECRET_BASE_BLUE_CAVE3, SECRET_BASE_BLUE_CAVE4, SECRET_BASE_BROWN_CAVE1, SECRET_BASE_BROWN_CAVE2, SECRET_BASE_BROWN_CAVE3, SECRET_BASE_BROWN_CAVE4, SECRET_BASE_RED_CAVE1, SECRET_BASE_RED_CAVE2, SECRET_BASE_RED_CAVE3, SECRET_BASE_RED_CAVE4, SECRET_BASE_SHRUB1, SECRET_BASE_SHRUB2, SECRET_BASE_SHRUB3, SECRET_BASE_SHRUB4, SECRET_BASE_TREE1, SECRET_BASE_TREE2, SECRET_BASE_TREE3, SECRET_BASE_TREE4, SECRET_BASE_YELLOW_CAVE1, SECRET_BASE_YELLOW_CAVE2, SECRET_BASE_YELLOW_CAVE3, SECRET_BASE_YELLOW_CAVE4
* the Battle Pike's rooms: outside a challenge the game does not come back in them (the final room returns to the lobby) or start a battle there (2): BATTLE_FRONTIER_BATTLE_PIKE_ROOM_FINAL, BATTLE_FRONTIER_BATTLE_PIKE_ROOM_NORMAL
* link battle: needs a partner (2): SOOTOPOLIS_CITY_MYSTERY_EVENTS_HOUSE_B1F, UNION_ROOM

### The other cameras, night, double battles (samples, looked at)

* **The Diorama camera** (`cameraMode=diorama`, 20 maps: routes, Petalburg Woods, the desert,
  Slateport's harbour, Sidney's and the Champion's rooms, Mauville's and Rustboro's Gyms, Granite
  Cave, Meteor Falls, Mt. Pyre, the Abandoned Ship, New Mauville, Sky Pillar, Aqua's hideout):
  the battle's own camera is the same in both field cameras, so the pictures match the Adventure
  camera's map for map; the field camera only changes the glide into the battle.
* **Night** (hour 23, 10 maps): outdoors the world takes the game's night tint and the stage's
  pool of light is a little stronger round the battlers; the Pokemon, healthboxes and text are
  not tinted and stay readable. Indoors and in caves the picture is the day's (the game has no
  night there).
* **Double battles** (two wild Pokemon, 5 maps: Route 101, Route 103, Petalburg Woods, Granite
  Cave 1F; Route 119's long grass is 2D, E2): all four battlers stand on the ground, the
  interface's ground points land on their feet (0.0 px for all four), no one stands in a wall
  (in Granite Cave the right-hand foe has rock half a tile behind it, not in front).
* **Staging** (every photographed battle, 340 battlers): the world's surface under each
  battler's feet and how much of the world stands in front of its picture. Flagged and looked
  at: Route 107 (both battlers a tile over the sea: the stage at a bank's height, fixed in
  `4002eac1f`), Dewford Town and Route 115 (the opponent's feet on a cliff's or a ledge's top
  behind it: it stands in front of the rock in the picture, correct), Fortree Gym (a hedge
  pillar beside the foe), Mt. Pyre 3F-6F (a grave's base under the player's Pokemon at the
  picture's lower edge). None stands inside a wall or floats in the pictures; the interface's
  check is 0.0 px for every battler on every map.

## With the overworld's detail objects (branch `claude/battle-environments-graphics8`)

While this work ran, the overworld session's checkpoint `native-wip-20261010-8` moved
`claude/native-graphics` to `d799c4a8a` (graphics overhaul part 3): tall grass, long grass,
flowers, signs, fences and posts, street lamps, rocks and boulders, market goods and hedges
stand in 3D (the props pass, `props.h`), about seventy more buildings are modelled, and lamps
and windows light up at night. That is the environmental object library the directive says
to reuse; its COORDINATION note asked the battle session to draw it in battles too, since its
terrain now leaves out the flat picture of every cell an object stands on.

`claude/battle-environments-graphics8` is `claude/battle-environments` merged with
`d799c4a8a` (one conflict, `gl_compositor.c` `DioramaGL_Init`: both inits kept, as the note
said), plus:

* `DioramaGL_DrawBattleWorld` draws the props after the 3DS trees (and their shadows in the
  sun's depth map), with the street lamps and lit windows round the stage at night - the
  same object library and the same draw as the field; nothing is modelled for battles alone.
* The stage search sees a standing object (sign, fence, lamp, rock, bush, goods) as tall as
  its art, so no battler is stood in one; grass and flowers do not count (a wild Pokemon
  comes out of them, and the battlers' pictures are drawn over them).
* `DioramaGL_GetBattleWorld` syncs the objects with the field's last steady frame, as it does
  the terrain, buildings and trees (`69440aa02`). The survey's first pictures on this branch
  showed every fence, sign and lamp black: their art had last been composed during the
  battle transition's fade.

It is a branch of its own: `claude/battle-environments`, the merge candidate and
`claude/native-graphics` are untouched. When `claude/native-graphics` (now `d799c4a8a`) takes
the 3D battles, this branch is the battle environments' side of it.

The battle survey photographed every outdoor battle map (59) with this branch's TEST build
(`69440aa02`), a sample of 13 rooms and caves, and 6 towns and routes at night:

* **Outdoors:** without the objects A 0, B 9, C 48, D 2; with them **B 30, C 28, D 1**. 22 maps
  moved up a class and none down: tall grass standing round the battlers on every grass route,
  in Petalburg Woods, on Mt. Pyre's summit and in the Safari Zone; Mauville's flower fences and
  sign, Slateport's fence posts, Rustboro's street lamp; Dewford's and Pacifidlog's houses (the
  overworld's new buildings). On Route 121 the stage moved off the blue fence (the stage search
  sees standing objects). The sea, the desert and Sootopolis's crater look as before (none of
  the objects stands there).
* **Rooms and caves:** the same pictures (13 of 13: the League, Gyms, caves, Mt. Pyre, the
  hideout, New Mauville, Sky Pillar, the Palace, the sea floor), apart from a boulder by Granite
  Cave's wall now standing as an object.
* **Night:** the objects take the night tint with the rest; in Rustboro the street lamp's head
  is lit and the Mart's window glows warm in the battle (the overworld's lamps and lit windows,
  turned on round the stage).

The class with the objects is each map's `props` in `review.json` and the "+" class and the
WITH OBJECTS picture in the report.

## Performance

**No graphics card was measured.** The cloud computer draws with Mesa's software renderer
(llvmpipe, 2 cores), which is limited by filling pixels, so its milliseconds compare window
sizes and places with one another and say nothing about how fast a graphics card is; claims
about frame rates on a real GPU wait for the owner's runs (below).

What a battle's world costs to draw, from the survey's own counters (`cap.json` `perf`, every
photographed map at 960x540):

* **Draw calls:** the terrain 15-33 (median 27: three per visible chunk - the picture and two
  stencil passes - and 9 of the 49 chunks in view), the modelled buildings and rooms 0-3. A
  room adds one or two calls whatever its size.
* **Geometry:** terrain 800-135 000 triangles (median about 2 600); buildings 0-60 000 vertices
  (median about 2 100). The heavy ones are the Lavaridge tileset's stepped relief (Magma
  Hideout 135 000 triangles, Route 112 123 000, Route 114 73 000) and the sea rocks' domes
  (Route 105 60 000 vertices) - the overworld's geometry, not this work's. The Elite Four's
  rooms are 1 600 vertices each.
* **Kept world:** while nothing in it moves the battle keeps the world's picture and redraws
  only the battle over it (the game's own behaviour since the 3D battles' third round), so
  most battle frames cost the same however big the world is.

The battles at 1080p, 1440p and 4K (`tools/battle_env/perf.py`; the window is a little smaller
than the screen it opens on, the 3D view is the window's size, no MSAA; "world redrawn every
frame" forces `PKMN_DIORAMA_BATTLE_KEEP=0`, the cost of a frame where the camera moves or the
water animates):

| Map | Window | 3D view | World redrawn every frame | Redrawn frame, ms (avg / max) | Kept frame, ms | Terrain draws | Building draws | Terrain triangles | Building vertices |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ROUTE101 | 1834x1032 | 1834x1032 | yes | 120 / 190 | 19.4 | 50 | 2 | 8330 | 7230 |
| EVER_GRANDE_CITY_SIDNEYS_ROOM | 1834x1032 | 1834x1032 | yes | 89 / 130 | 17.2 | 57 | 1 | 4770 | 1596 |
| GRANITE_CAVE_1F | 1834x1032 | 1834x1032 | yes | 102 / 146 | 21.3 | 51 | 0 | 4920 | 0 |
| ROUTE101 | 1834x1032 | 1834x1032 | no (the game's own) | 136 / 230 | 27.5 | 50 | 2 | 8330 | 7230 |
| EVER_GRANDE_CITY_SIDNEYS_ROOM | 1834x1032 | 1834x1032 | no (the game's own) | 116 / 208 | 37.5 | 57 | 1 | 4770 | 1596 |
| GRANITE_CAVE_1F | 1834x1032 | 1834x1032 | no (the game's own) | 128 / 170 | 28.6 | 51 | 0 | 4920 | 0 |
| ROUTE101 | 2474x1392 | 2474x1392 | yes | 214 / 321 | 38.9 | 48 | 2 | 6432 | 7230 |
| EVER_GRANDE_CITY_SIDNEYS_ROOM | 2474x1392 | 2474x1392 | yes | 156 / 239 | 37.6 | 36 | 1 | 3072 | 1596 |
| GRANITE_CAVE_1F | 2474x1392 | 2474x1392 | yes | 172 / 250 | 35.9 | 36 | 0 | 3656 | 0 |
| ROUTE101 | 3754x2112 | 3754x2112 | yes | 423 / 709 | 82.3 | 33 | 2 | 2920 | 7230 |
| EVER_GRANDE_CITY_SIDNEYS_ROOM | 3754x2112 | 3754x2112 | yes | 308 / 470 | 73.5 | 36 | 1 | 3072 | 1596 |
| GRANITE_CAVE_1F | 3754x2112 | 3754x2112 | yes | 374 / 685 | 74.1 | 36 | 0 | 3656 | 0 |

Reading it: with the game's own behaviour ("no"), a battle frame keeps the world's picture
while nothing in it moves - 27-38 ms a frame at 1080p on this software renderer, the battle's
own drawing and the copy - and the world is redrawn only while the camera glides in (those
frames are the "redrawn" column there). Forced to redraw every frame ("yes"), a frame costs
89-120 ms at 1080p, 156-214 ms at 1440p and 308-423 ms at 4K: it grows with the pixels, as a
fill-bound software renderer does. The draw calls and triangles stay in the tens and the
thousands at every size (they differ a little with how much of the world shows past the
battle's picture, which the window's whole-number scale decides; the void share of the
scenery band is 0 at every size, so nothing in view is culled). Nothing here points at a
geometry or draw-call cost a graphics card would feel, but that is a reading of software
numbers, not a measurement on one.

**On a graphics card:** the package in `claude-checkpoints\battle3d-test-runs\env-20261011-1`
(`run-all-tests.bat`: Sidney's room, a Gym, Granite Cave and Petalburg Woods at 1920x1080,
2560x1440 and 3840x2160, the game's own autopilot; each run's `cap.json` holds the same
counters and frame times) measures this branch (at `083bc9754`; the later commits add a few
rooms' models and change where the stage stands, not how the world is drawn). Its results go
in `results\` there; none were there when this was written (last looked 2026-10-12).

## Known issues

The entries are in `KNOWN_ISSUES.md` (N37, E1-E8); in short:

* **N37 (High, game logic, not fixed here):** a battle against two trainers at once aborts
  natively at its start (`BufferBattlePartyOrderBySide` writes one past an array: each
  trainer has a party of its own here). Found by the survey on four maps; reproduced on the
  merge candidate. The survey stands elsewhere on those maps (`--at`). A fix belongs on a
  branch of its own (mechanics are not this work's to change).
* **E1:** sea battles look through white gaps round the sea rocks (the overworld's props
  leave part of their water undrawn, in the field too).
* **E2:** Routes 119 and 120: in the long grass the field and its battles fall back to 2D.
* **E3:** caves: rock one tile high, one block per cell; upper floors level with the lower.
* **E4:** on `claude/battle-environments` outdoor details (tall grass, flowers, fences, signs,
  ledges) are flat, so most outdoor maps stay C; on `claude/battle-environments-graphics8` the
  overworld's detail objects stand in battles too (below); ledges stay flat on both.
* **E5:** rooms still flat: Trick House 8 (Trick House 5 has no battle), Sky Pillar's top;
  Magma Hideout stands as the overworld's relief, not a model; the Battle Pyramid's and
  Trainer Hill's floors are laid out at run time and were photographed as their layouts
  stand.
* **E6:** after a win in an Elite Four room the back wall's model is left out for the rest of
  the visit (a script redraws the door).
* **E7:** past a room's edge the battle shows the GBA's battle background (white or streaky
  in some rooms).
* **E8:** the Lavaridge tileset's relief (volcano, Magma Hideout) is heavy for software
  OpenGL; a graphics card was not measured.
* Not covered: secret bases (the game does not resume inside one: the survey's warp came
  back in Littleroot Town), the Union Room's and the Mystery Events house's link battles.

## Integration

Order: the merge candidate first, this branch after it.

1. The pending decision stands on its own: the 3D battles (candidate 4, `e747ce106`) go into
   `claude/native-graphics` when their graphics-card tests in `battle3d-test-runs\wip-20261010-4`
   pass. The native session has since moved `claude/native-graphics` on to `d799c4a8a`, so that
   step is now a merge of the candidate onto that tip (one conflict, `DioramaGL_Init`: keep both
   inits, the detail objects' then the battle's), no longer a fast-forward. This work does not
   change that decision or its build.
2. Then this work, as an ordinary merge into `claude/native-graphics`: on `d799c4a8a` or later
   (where it is now) that is `claude/battle-environments-graphics8`, which already contains both
   the candidate and `d799c4a8a`. Tried here on a scratch copy: the candidate merged onto
   `d799c4a8a` as in step 1, then `claude/battle-environments-graphics8` merged into that - no
   conflict, and the result is file for file `9c1c6aef8` (its code is what was built and
   surveyed).
   (`claude/battle-environments` is the same work for a tip without the overworld's detail
   objects.) Files another session may also have changed (the coordination note lists them):
   * `tools/diorama_buildings/voxel_building_specs.py`: one import and one line at its end
     (`SPECS = SPECS + battle_room_specs()`); keep both sides.
   * `tools/diorama_buildings/gen_voxel_buildings.py`: callable interior pieces, seam reliefs
     taller than a cell, `MAX_TEXTURE` 2048, `reuse_in`. Specs without these keys build exactly
     as before.
   * `data/diorama/tilesets/cave.json`, `meteor_falls.json`, `rusturf_tunnel.json`,
     `navel_rock.json`, `underwater.json` (new files): the cave and sea-floor rock pins. If the
     overworld's cliff or elevation work reaches caves, delete them (or rerun
     `tools/battle_env/cave_pins.py`, which writes only files it made).
   * `scene_snapshot.h/.c` (`DIORAMA_CELL_CHANGED`), `buildings.c/.h`
     (`DioramaBuildings_Validate`, `_PlacementStands`), `gl_building_renderer.c`.
   * `gl_battle.c`, `battle_capture.c`, `battle_scene.h` (the battles' files) and
     `include/diorama/battle_environment.h` (new).
3. Build as before (`make -f Makefile_pc DIORAMA=1 ...`): the rules compiler and the model
   generator run in the build (the library grows from 14.75 MB to about 33 MB of models, compiled
   into the exe). No new dependency; no change to the GBA ROM (`f214735b…3387`) or to a build
   without `DIORAMA=1`.
4. Check after the merge: `python3 tools/battle_env/auto_rooms.py build/battle_env/rooms`
   (every listed room proves, 0 px), then a survey of a sample with the TEST build (README in
   `tools/battle_env`), the pictures looked at against this report's.
5. What `claude/battle-environments-graphics8` adds over `claude/battle-environments`: the
   overworld's detail objects (`graphics-wip-20261010-8`) drawn in battles - the props pass and
   its shadows in `DioramaGL_DrawBattleWorld`, the lamps round the stage, `DioramaGLProps_Sync`
   in `DioramaGL_GetBattleWorld`, `StageCellAt` reading `DioramaProps_ForCell` - all in
   `gl_compositor.c`'s two battle functions and `gl_battle.c`.

Settings (environment variables, for testing; nothing to set in play):
`PKMN_DIORAMA_BATTLE_LIGHT=0` turns the light round the stage off, `PKMN_DIORAMA_BATTLE_LIGHT_SCALE`
scales it; `PKMN_DIORAMA_BATTLE_KEEP=0` redraws the battle's world every frame (measurements).
