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
| `claude/battle-environments-2` | `claude/battle-environments-graphics8` (`9c1c6aef8`) | Round 3 (below): `claude/native-pc-n37-fix` merged in (N37-N40), the weakest places, the secret bases, the review; candidate `49c47919e` (later commits: tools and the review only) | **The integration candidate.** Not merged anywhere. Checkpoint `battle3d-env-wip-20261012-1`. |
| `claude/native-pc-n37-fix` | `claude/native-pc` `1579e7fd8` | N37, N38, N39, N40 and their selftests | Native crash fixes (`PORTABLE` and the PC sound driver only). Not merged into `claude/native-pc`. |

The merge candidate `e747ce106`, its checkpoint `battle3d-wip-20261010-4` and the pending
graphics-card tests in `battle3d-test-runs\wip-20261010-4` are untouched and independent of
this work: this branch goes in after the candidate (it is built on it). Compiled only with
`DIORAMA=1`; the GBA ROM is unchanged (`f214735b…3387`). Player builds have no debug menu
and no test driver. The native session moved `claude/native-graphics` on to `d799c4a8a`
(`native-wip-20261010-8`) while this ran; `claude/battle-environments-graphics8` is this work
on that tip, so the overworld's new detail objects are drawn in battles too (one object
library for the field and battles, as the directive asks).

## Results

(The first two rounds' results; round 3's are in its section below: **A 5, B 204, C 5, D 0**
of 214 reviewed maps, 4 untested.)

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

## Round 3: the weakest places, the untested maps, N37 to N40 (branch `claude/battle-environments-2`)

Recorded 2026-10-12. Owner directive: fix N37 first (its own branch, the smallest safe change,
a regression test, single, double and multi-trainer battles verified); then the weakest
environments (Route 111, Route 117, all 61 C maps: their recorded problems fixed, not
reclassified); then the 28 untested maps by safe test entry; the overworld's objects consistent
in battles; regression tests, before/after pictures, an integration candidate on the newest
verified graphics branch, nothing merged.

### Where it is

| Engine branch | Base | What |
| --- | --- | --- |
| `claude/native-pc-n37-fix` | `1579e7fd8` (`claude/native-pc`'s tip at the time) | `7127b587e` the N37 selftest, `a49b89b15` the N37 fix, `3aed6f03a` the N38 selftest, `479a58aac` the N38 fix, `b26a90096` the N39 selftest, `8af5b8769` the N39 fix, `1521aefc8` the N40 selftest, `ab4c6ac1c` the N40 fix, `1a26af882` the selftest's memory from the heap. `PORTABLE` and the PC sound driver only. |
| `claude/battle-environments-2` | `claude/battle-environments-graphics8` (`9c1c6aef8`, on `d799c4a8a`) | `claude/native-pc-n37-fix` merged in (`3783b7e5c`, `92f479812`, `f0e0e4723`, `06a972aed`, `49c47919e`); the environment work below (`26c30cadf` ... `584204caa`); the test driver and report tools. **The integration candidate, `49c47919e`** (`1bc4bacd9`, `c9ac33cc4`, `719e16c78` after it: a survey fix, the review, the tools' README). |

Nothing is merged into `claude/native-graphics` or `claude/native-pc`. The newest verified
graphics tip is still `d799c4a8a` (`native-wip-20261010-8`); another session's
`claude/graphics-overhaul` `00fd30ca7` (`perf-benchmark-20261011`) is a performance test build,
not verified, and was not used; the native UI session's `claude/native-ui`
(`ui-native-wip-20261012-1`) starts from `d799c4a8a` too (Integration, below).

### N37: a battle against two trainers at once (fixed)

`BufferBattlePartyOrderBySide` (`party_menu.c`) lists a side's six party places for the battle:
its two battlers' party indexes first, then the others. Against two opponent trainers each
trainer has a party of its own (`gParties[B_TRAINER_OPPONENT_A]`, `_B`), so both opponents are
party index 0 and the loop found seven indexes for six places: the GBA writes the seventh one
byte past the array, into its stack frame; natively the stack protector aborted the battle as
it started. Upstream pokeemerald-expansion has the same loop.

The fix is the smallest one, `PORTABLE` only: the loop stops when the six places are full. The
six kept are exactly the six the game kept before, so party order, switching, double and Multi
battles, saves and link data are unchanged; the GBA ROM is byte for byte the same
(`f214735b…3387`).

The regression test, `make -f Makefile_pc check-party-order` (`--selftest-party-order`,
`native_selftest.c`), runs the game's own `BufferBattlePartyCurrentOrderBySide` and
`BufferBattlePartyCurrentOrder` for single, double, two-opponent, Multi and link (half teams)
battles with every pair of party indexes, and checks each order against the one the game has
always given (the six indexes the GBA keeps in bounds), so the fix is shown to change no
battle. The battle N37 was found in goes first: on the commit before the fix the selftest
aborts exactly as the game did ("stack smashing detected"); with the fix, 1119 checks, 0
failed, also in an AddressSanitizer build.

Fought through on the fixed build with a strong party (`PKMN_TEST_STRONG=1`, every battle to
its end): the four two-trainer spots (Sootopolis Gym B1F, Victory Road 1F, the Abandoned Ship's
rooms, the Trick House's seventh puzzle; the trainers see the player and start their own
battle) - all won; a single battle (Roxanne), a double (Tate and Liza), a Multi with a partner
(Mossdeep's Space Center, Steven) and a wild double - all won. Again on the integration
candidate: see Validation.

### N38: a battle message naming two trainers (found and fixed)

Found while fighting the Multi battle through: Mossdeep's Space Center battle aborted
("stack smashing detected") as it began. `BattleStringExpandPlaceholders` puts each
placeholder's name together in a 32-byte buffer from where the previous one ended
(`textStart`), so "You are challenged by {B_TRAINER1_NAME_WITH_CLASS} and
{B_TRAINER2_NAME_WITH_CLASS}!" wrote the second class-and-name past the buffer. The fix,
`PORTABLE` only: each placeholder's text starts at the buffer's start (it is copied out before
the next), so the message is the same. `make -f Makefile_pc check-battle-names`
(`--selftest-battle-names`): every trainer's class and name against the longest, both
placeholders together against each alone, Maxie and Tabitha's Multi; it aborts before the fix
(ASan: stack-buffer-overflow) and passes after it (1724 checks, 0 failed). The Multi battle was
then fought through and won.

### N39: a trainer's double battle right after continuing a save (found and fixed)

Found by this round's regression survey once N37 let the two-trainer battles start: started
straight from the field after a continued save, Sootopolis Gym B1F's, Victory Road 1F's and
the Abandoned Ship's two-trainer battles crashed natively (segmentation fault) as the
opponents' Pokemon came out, and so did Tate and Liza's. A double battle's send-out stops the
cry playing before the doubles' cries (`Task_PlayCryWhenReleasedFromBall`,
`StopCryAndClearCrySongs`); with no cry played since the game started the cry player
`gMPlay_PokemonCry` is still NULL and `m4aMPlayStop`, the PC's own sound driver
(`m4a_pc.c`), read through it (the GBA reads its BIOS there and does nothing). The fix is in
the driver only: `m4aMPlayStop` returns for a NULL player, as `IsPokemonCryPlaying` already
did. No game code changed; the GBA build does not compile the file. `make -f Makefile_pc
check-cry-stop` (`--selftest-cry-stop`) crashes on the commit before the fix and passes after
it (5 checks); the four battles were photographed again with the fix (and fought through,
Validation).

### N40: a move animation's shake (found and fixed)

Found by N37's verification: the candidate's fight-through of Mossdeep's Space Center Multi
battle crashed as a Pokemon's move shook the background. The animation behind Rock Throw's,
Rock Slide's, Metal Claw's, Dragon Claw's, Ancient Power's, Superpower's, Snore's... shake
(`AnimShakeMonOrBattlePlatforms`, `battle_anim_normal.c`) keeps the address of what it shakes
(`gBattle_BG3_X`/`_Y`, `gSpriteCoordOffsetX`/`_Y`) in two s16 sprite fields and puts it back
together as `lo | hi << 16`. On the GBA those variables are in IWRAM, whose addresses never
have bit 15 set; natively they can (all four in the 3D build), the negative low half
sign-extends over the high one and the animation read and wrote through 0xFFFFxxxx. Whether a
build crashed depended on where its linker put the four. The fix, `PORTABLE` only: the low
half is read unsigned, as `SetCallbackToStoredInData6` already does; the shake is the same.
`make -f Makefile_pc check-shake-anim` (`--selftest-shake-anim`) shakes each of the four and a
value at an address with bit 15 set in any layout: it crashes before the fix, 11 checks pass
after it.

### What changed in the environments

Every change is in the shared scene (terrain, rules, the scene's passes over the cells, the
props catalogue, the weather picture), so the field shows it exactly as the battles do: one
world, one object library. Field screenshots with the round's builds: checkpoint
`report\field\` (Route 111's dunes, Mt. Chimney's crater, Pacifidlog's decks, Lilycove's
harbour, Dewford's pier, Route 119's long grass, Southern Island's stone, the Frontier's bushes,
a Battle Pyramid floor).

* **Steps down stand their faces** (`terrain_mesh.c` `ColumnBottom`, `occupancy.c`): flat ground
  is a slab one voxel thick, so where a neighbour was lower (the sea lowered round an islet, a
  pond below its bank, Route 113's and Route 116's lowered terraces) nothing stood between the
  slab and the lower surface and the sky showed through (E1's white gaps and pale bands). A
  column now stands down to its lowest neighbour's top; the part below its own slab shows the
  cell's lower layer (the ground, not a tree or rock painted on it), a raised cell's side goes on
  down as itself. A ledge's side reads its own art's rows per band (Route 113's sky band).
  `test_terrain_mesh` checks it on both mesh paths (it fails on the old code).
* **The sea at one level** (`buildings.c`): each body of water's level is worked out once per
  layout from the whole layout - the lowest level the terrace solver gave any of its cells, and
  outdoors the sea a level below the land at the most - so the shoals round the islets and the
  harbours (walked through at the land's elevation) lie at the sea's level, a town's sea meets a
  route's at the seam, and nothing moves as the view does (before, the levelling ran over the
  cells in view and the sea in sight could drop as the player walked). Rocks drawn on the water
  and one-cell sandbars stand in it at its level.
* **Decks, piers and walkways stand on wood** (`gl_terrain_renderer.c`): the side of a cell
  drawn over the water shows the whole cell (Pacifidlog's floating decks and log walkways,
  Dewford's pier), not the water under it.
* **Route 111's dunes** (`buildings.c` `RaiseDunes`): the deep sand rises in steps of 3/16 of a
  tile from each patch's rim, three at most; the player, trainers and battlers stand on them.
  **A sandstorm as thick as the GBA's** (`gl_compositor.c`): the old picture hardly showed in
  the 3D view's sand haze.
* **Mt. Chimney's crater** (`buildings.c` `SinkLava`): the lava lake (and the Magma Hideout's
  pools) lies a level down, the rock over its edge rimming it, so the battle stands on the
  summit's rock, not on the lava.
* **Cave water below the floor** (`SinkCavePools`): underground, pools, channels and tidal
  shallows lie 6/16 below the floor (the Seafloor Cavern, the Shoal Cave, Meteor Falls).
* **Secret bases walled** (rules data `secret_base_*.json`): the bases' walls stand one tile
  high, as the caves' rock does.
* **New objects in the shared catalogue** (`props.c`): Mauville's flower beds (Route 117) as
  swaying cards, Mt. Pyre's graves as reliefs, Sky Pillar's rubble as low heaps, the Trick
  House's boulders, the Trainer Hill's blocks, Southern Island's mossy stone (where Latias or
  Latios is met), the Battle Frontier's round bushes, the Battle Pyramid's maze walls (its
  floors are laid out from the squares at run time, so the walls are found by their metatile:
  a rules pin on the floor's layout cannot reach them).
* **Walkers in long grass stay 3D (E2)** (`sprite_frame.c`, `scene_snapshot.c`): in Routes
  119's and 120's long grass the game splits a walker's sprite into rows, its lower rows drawn
  behind the grass, and the 3D view refused such a sprite: the field cut to 2D, and so did any
  battle started there. A subsprite table whose parts put the frame together whole is now drawn
  as the whole frame, and the long grass objects stand in front of the legs; the battles in
  the long grass are 3D. `test_sprite_frame` checks the game's own tables.
* **A redrawn cell keeps its level** (`rules.c`): a cell a script redrew (Route 113's ash
  brushed off) kept the flat ground's level, a block at the player's feet; it keeps the terrace
  solver's level now.
* **The field's sky, air and weather over battles** (`gl_compositor.c`, `gl_battle.c`,
  `battle_capture.c`): outdoors a battle's world fades into the sky's haze where it ends (no more
  white or striped GBA background past the map), the field's air (dust, rays, bloom, fog banks)
  is drawn over it, and rain, snow, sand, ash and fog fall over the battle as over the field
  (the battle's weather once it has taken it, the place's before). How the game looks only: the
  battle's weather is untouched.
  A room's fog (the Lavaridge Gym's steam) is left out of its battles (`584204caa`): the
  battle's low camera saw the whole room through it, a white veil over every wall (the
  regression survey caught it), and the GBA's battles show none there.

### The 28 untested maps

The test driver can now warp in game before the battle (`PKMN_TEST_WARP`, `survey.py
--warp-in`), as the debug menu's "Warp to map warp" does: in memory only, no save written,
TEST builds only. Used where the game does not resume on a map but a player can walk in.

* **The 24 secret bases: photographed and classed.** The game does not resume inside a base
  (it comes back in Littleroot Town), so the survey warps in from the field. Every base (red,
  brown, blue and yellow caves, trees, shrubs; four layouts each) was photographed in a wild
  battle and is classed (below). The bases' walls now stand (rules pins); a base's decorations
  are the player's own and are not in the test save.
* **Cannot be tested safely (4), documented:**
  * **Union Room:** its battles are link battles between two players' games over the wireless
    adapter. On the PC there is no adapter (`IsWirelessAdapterConnected` returns false), so the
    game's own entrance (the Pokemon Center attendant) never lets a player in. Warping in
    anyway is a state the game cannot reach: the room's task then reads partner data that is
    not there and the game stops (`Rfu_GetCompatiblePlayerData`). Not a reachable crash; not
    pursued further.
  * **Sootopolis's Mystery Events house B1F:** its battle is against an e-Reader trainer. The
    stairs open only when the save holds a valid e-Reader trainer (`frontier_checkvisittrainer`
    on 1F); the test save has none (it takes the e-Reader and link hardware). Warping in anyway
    starts that battle with no trainer data and the game stops (stack protector). Not reachable
    in play; not pursued.
  * **Battle Pike, normal room and final room:** a battle there needs a running Pike challenge
    (the rooms' scripts start it). Outside one the normal room starts no battle (the run timed
    out) and the game sends the player from the final room back to the lobby (`wrong map`).
    Forcing a challenge's state would be an invalid save state, so they stay untested.

### Results

236 battle maps, as before. **214 reviewed** (a real battle photographed with the
round's TEST build and the picture classed by looking at it; 190 before this round: the 24
secret bases are photographed and classed for the first time), **4 untested** (the
four above), **18 excluded** (unchanged). All 214 were looked at again this round, on
pictures taken with its builds: every map the round's work could reach and the rest as a
regression check (Validation).

**Classes now, all 214 reviewed maps: A 5, B 204, C 5, D 0.** Before this round (the class with
the overworld's objects where that was looked at, else after the first rounds), the 190 then
reviewed: A 5, B 143, C 41, D 1.

* **Route 111** (D before; the desert's sand flat to the horizon): **B** - the deep sand rises
  in dunes round the battle, the rocks stand behind, the sandstorm blows across it. The dunes
  are low steps, not smooth slopes, and read faintly in the sandstorm's haze: the polish left.
* **Route 117** (D before, C with the objects; open sand and grass): **B** - the flower beds
  stand and sway, the ponds lie a step below their banks, the fence and the trees behind.
* **The 61 C maps** (after the first rounds): **56 are B now, 5 stay C.** Of the B, 21
  were B already with the overworld's objects drawn in battles (the tall grass routes, Petalburg
  Woods, the Safari Zone, Dewford, Pacifidlog, Slateport) and were photographed again with this
  round's changes as well; the other 35 moved up by this round's work: the sea routes and
  harbour towns (no white bands, the sea at one level with its shoals and rocks, decks on wood),
  Route 113 (the terraces' faces, the ash falling), Sootopolis and Ever Grande (the haze past the
  map instead of the backdrop), Mt. Chimney (its crater), Mt. Pyre (the graves), Sky Pillar's
  top (the rubble), Routes 119 and 120 (the long grass, now 3D), Southern Island (the stone, at
  Latias's battle), the Frontier's east side (the bushes), Faraway Island (its long grass),
  Trick House 8 (the boulders), the Trainer Hill's floors (the blocks), a Battle Pyramid floor
  (the maze walls), the Seafloor Cavern's entrance (the pool below its banks). Each map's note
  in `review.json` (`now_notes`) says what changed in its picture.
* **What stays C (5), and why:** Birth Island (an open meadow; its three round trees,
  three and four cells wide, are drawn flat - a joined mound cannot stand a fully covered
  middle cell), the Battle Pyramid's top (the layout draws its sky and setting sun as cells:
  they lie as a painted floor past the bricks), the Trainer Hill's roof (an open roof; its
  railing posts are drawn into the floor's own picture, with no clean art of a post to stand
  up), Shoal Cave's low-tide entrance (one sheet of shallow water, on the GBA too) and inner
  room (the raised floor behind the battle stays level with it, E3). None of them is
  reclassified: each picture is as before.
* **No map is D.** 37 maps moved up a class this round (36 from C to B, Route 111 from D to
  B), none down; the 24 secret bases are B.

The class before, after the first rounds, with the objects and now are each map's `before`,
`after`, `props` and `now` in `tools/battle_env/review.json`; the report (checkpoint
`report\index.html`) shows the pictures side by side, the NOW one from this round.

### Validation

At the candidate `49c47919e` (`1bc4bacd9` adds a test-tool change only):

* **Builds:** Linux 3D and 2D, Windows 3D and 2D (MinGW), the GBA ROM byte-identical
  (`f214735b…3387`). The player builds carry no test driver (no "Battle env test" string)
  and no debug menu (`DEBUG_OVERWORLD_MENU`, `DEBUG_BATTLE_MENU` FALSE).
* **Selftests, Linux 3D and 2D:** `check-party-order` 1119, `check-battle-names` 1724,
  `check-cry-stop` 5, `check-shake-anim` 11 checks, 0 failed; `check-game-sections` (Linux
  3D and 2D, Windows 3D), `check-decompress` 7469 assets, `check-native` 176 checks and 9
  pictures, `check-abi` 172 types, all passing.
* **`check-diorama`:** every suite passes (the terrain mesh with the risers, the props'
  3184 checks, the sprite frames with the long grass's tables, the rules with the secret
  bases' pins, the battle stage with the surfing landing, the compositor goldens over 18318
  metatiles, `validate_rules`, `compile_rules --check`). The rules tools' tests
  (`check-diorama-tools`) pass but for the two failures already in KNOWN_ISSUES (V2's parity
  case, V4's mountains flag), the same as before this round.
* **Fought through** on the candidate's TEST build with a strong party, each to its end: the
  four two-trainer spots (Sootopolis Gym B1F, Victory Road 1F, the Abandoned Ship's rooms, the
  Trick House's seventh puzzle; the trainers see the player and start their own battle),
  Roxanne (single), Tate and Liza (double), the Space Center Multi with Steven, a wild double
  - **all won**. (The first fight-through on the candidate found N40 in the Multi battle.)
* **Regression survey:** the 94 reviewed maps this round's work did not otherwise
  photograph again (rooms, caves, Gyms, the League, the Frontier, ships, towers) were
  photographed with the candidate's TEST build and compared side by side with their earlier
  pictures. It found N39 (three two-trainer maps crashed), the Lavaridge Gym's steam drawn
  over its battles as a white veil (fixed: `584204caa`) and a test-tool fault under water
  (fixed); the rest look as before or better (cave water below the floor, the haze). Every
  class held.
* **Field screenshots** with the candidate's build (checkpoint `report\field\`): Route 111's
  dunes, Mt. Chimney's crater, Pacifidlog's decks, Lilycove's harbour, Dewford's pier, Route
  119's long grass, Southern Island's stone, the Frontier's bushes, a Pyramid floor.
* **Windows player build** (packed, stripped, `49c47919e`) under Wine (software OpenGL, a
  1280x720 window): it started, continued a save and drew a wild battle in 3D in Granite Cave
  1F and in Route 102's tall grass by its pond, ran from each and came back to the 3D field;
  in Route 119's long grass the field stayed 3D (no sprite refused, nothing drawn in 2D). Not
  a graphics-card run.

### Integration

Order, as before: the merge candidate first, this work after it; nothing is merged here.

1. The 3D battles (candidate 4, `e747ce106`) go into `claude/native-graphics` when their
   graphics-card tests in `battle3d-test-runs\wip-20261010-4` pass, merged onto `d799c4a8a`
   (one conflict, `DioramaGL_Init`: keep both inits). This round does not change that step.
2. Then `claude/battle-environments-2` (`49c47919e` or later) as an ordinary merge. It holds
   `claude/battle-environments-graphics8` (the candidate and `d799c4a8a` already merged, as
   in step 1), this round's work and `claude/native-pc-n37-fix`. The newest verified
   graphics tip is still `d799c4a8a`; the overworld session's `claude/graphics-overhaul`
   `00fd30ca7` (`perf-benchmark-20261011`) is a performance test build, not used.
3. `claude/native-pc-n37-fix` can go into `claude/native-pc` on its own (the native
   session's call): a trial merge onto its tip `aa2841d7a` has no conflict.
4. The native UI session's `claude/native-ui` (`ui-native-wip-20261012-1`) and this branch
   meet in two places, both mechanical (git merge-tree, nothing merged): `gl_compositor.c`
   `DioramaGL_Present` (its "&& !(pictureFlags & DIORAMA_PICTURE_HIDE_ALL)" goes on the
   battles' 2D-picture condition and the border's, after this branch's `sDrewField3D` line)
   and `sdl2.c`'s key filter (both blocks kept, the UI's first). The checkpoint's
   COORDINATION.txt has the details.
5. Files this round changes that another session may also change (COORDINATION.txt lists
   each change): `terrain_mesh.c`, `occupancy.c`, `buildings.c`, `rules.c`/`rules.h`,
   `gl_terrain_renderer.c`, `gl_compositor.c` (the battle functions; the sandstorm),
   `props.c` (new entries only), `sprite_frame.c`/`.h`, `scene_snapshot.c`
   (`HasUnsupportedSubsprites`), `battle_capture.c`, `gl_battle.c`, the rules data
   (`secret_base_*.json`, new), and the native fixes' `party_menu.c`, `battle_message.c`,
   `battle_anim_normal.c`, `m4a_pc.c`, `native_selftest.c`, `sdl2.c`, `Makefile_pc`.
6. After the merge: `make -f Makefile_pc check-diorama`, the four selftests above, then a
   survey of a sample with the TEST build (`tools/battle_env/README.md`) and the pictures
   looked at against the report's.

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

The entries are in `KNOWN_ISSUES.md` (N37-N40, E1-E10); in short (round 3's state):

* **N37, N38, N39, N40 (High, native crashes): fixed** on `claude/native-pc-n37-fix`, each
  with a selftest (round 3, above); not merged into `claude/native-pc`.
* **E1:** sea battles looked through white gaps round the sea rocks: **fixed** in round 3
  (steps down stand their faces, the sea at one level, the haze past the map).
* **E2:** Routes 119 and 120: in the long grass the field and its battles fell back to 2D:
  **fixed** in round 3 (a walker's split sprite drawn whole).
* **E3:** caves: rock one tile high, one block per cell; upper floors level with the lower.
* **E4:** on `claude/battle-environments` outdoor details (tall grass, flowers, fences, signs,
  ledges) are flat, so most outdoor maps stay C; on `claude/battle-environments-graphics8` the
  overworld's detail objects stand in battles too (below), and round 3 adds more objects;
  ledges, Route 113's ash grass and Birth Island's round trees stay flat.
* **E5:** rooms flat in the first rounds (Trick House 8, Sky Pillar's top, the Battle Pyramid's
  and the Trainer Hill's floors): their objects stand since round 3; still flat: the Pyramid's
  top, the Trainer Hill's roof floor, Birth Island's meadow, Shoal Cave's tidal flat.
* **E6:** after a win in an Elite Four room the back wall's model is left out for the rest of
  the visit (a script redraws the door).
* **E7:** past a room's edge the battle shows the GBA's battle background (white or streaky
  in some rooms).
* **E8:** the Lavaridge tileset's relief (volcano, Magma Hideout) is heavy for software
  OpenGL; a graphics card was not measured.
* **E9:** Magma Hideout 2F's second room: the room's machines are drawn flat on the floor, and
  a battler can stand on one.
* **E10:** Dewford's water battle: the player's side stands on the water just behind the beach,
  a level higher (looked at: not visible as a fault).
* Not covered: the Union Room's and the Mystery Events house's link and e-Reader battles, the
  Battle Pike's normal and final rooms (round 3, above). The secret bases are covered since
  round 3.

## Integration

**Round 3 supersedes this section's step 2:** merge `claude/battle-environments-2` (it holds
`claude/battle-environments-graphics8`); its own Integration steps are in the round 3 section
above. The rest stands as written for the first rounds.

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
