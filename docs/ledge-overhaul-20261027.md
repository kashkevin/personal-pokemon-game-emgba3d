# Jump ledges, hills and ramps in 3D (the owner's Request C, 2026-10-27)

**Not in the 2026-10-27 package.** The package is the build verified before the deadline (engine `6320c77d`); this
work came after it, on engine `c212b61f` (branch `claude/feature-update-engine`), for a later build. Where a result
comes from: **L** this Linux machine (native Linux builds; the 3D view on Mesa's software OpenGL). Nothing here ran
on Windows, on a graphics card or on the owner's PCs.

## What was asked

Every jump ledge, hill, ramp and jumpable terrain in every region drawn with real 3D shape (edges, slopes, height,
the region's own materials, depth; no floating blocks, no flat stand-ins); which way a ledge is jumped shown by the
ground itself, without arrows; proper jump animations; every jump location audited from the map data, not a few
examples; the game's rules and multiplayer sync unchanged; each tested, with counts.

## The audit: every cell, from the map data

The compiled 3D rules hold a record for every cell of every layout (`src/data/diorama/diorama_rules.generated.c`);
the jump ledges and slopes among them are found by each cell's metatile behaviour in its tilesets (`MB_JUMP_*`,
`MB_BUMPY_SLOPE`, `MB_MUDDY_SLOPE`, `MB_SLIDE_*`). **1,099 cells in 46 layouts:**

* **1,007 jump ledges** in 42 layouts: jumped south 673, west 161, east 120, and 53 corners (south-west 31,
  south-east 22; the game jumps only the straight ones, `GetLedgeJumpDirection`). None is jumped north.
  * **959** of them, in 38 layouts, are terrain (below).
  * **48** are inside the four *modelled rooms* that have ledges (Fortree Gym 15, Lavaridge Gym 1F 7 and B1F 15, the
    Trick House's fourth puzzle 11): those rooms are models cut from their own drawing
    (`tools/diorama_buildings/battle_room_specs.py` `AUTO_ROOMS`), ledges included, and are not changed here.
* **47 ledges the game can never jump** (Rusturf Tunnel 35, Victory Road 1F 10, Granite Cave 1F 2) stand as the cave's
  rock (decided 2026-10-23; not changed).
* **45 slopes**: Route 111's muddy slopes (4 cells, in its two layouts 8) already rise between two levels as ramps;
  **37 lie flat**: Jagged Pass's 14 and the Safari Zone's 3 bumpy slopes, the muddy slopes of Routes 115 and 119,
  Granite Cave B1F and the Safari Zone (8), and Sootopolis Gym's 12 slides (in its modelled rooms).
* The Kanto maps are not reachable in play in this build and have no 3D rules; they were not counted.

What the ledges were in 3D, from the same data:

* A ledge's record stands it on its ground as high as its lip, so **every ledge was a block six voxels high** (a tile
  is 16), its top the ground under the lip and its sides the whole drawing squeezed into six rows: from the side it
  lands on a thin strip, from the side it is jumped from a low wall. The rock face the GBA draws on the landing half
  was not on its top at all.
* **81 on a lowered terrace** (Route 113 50, Route 118 24, Route 123 3, others 4) were a slab a voxel thick six voxels
  over their terrace.
* **66 stood on the upper level while the cells on both sides lay a level lower** (Route 118 35, Route 116 22, the
  Safari Zone's north 5, Route 123 4): walls 22 voxels high.
* Between the two cells each ledge joins: 912 have both on one level; **49 drop a level** (Route 113 19, Route 118 14,
  Route 123 6, Route 116 5, the Frontier 3, the Safari Zone 2); **46 land a level higher than they are jumped from**
  (Route 118 19, Route 123 18, Route 113 9): the 3D view's terrace levels disagree with the jump there. (Since engine
  `1291d718`: 19 land higher, all on Route 118, and 24 drop a level; see "The ledges that landed higher" below.)

| Layout (maps) | Ledges | S | W | E | SW | SE | Were walls | Were slabs | Drop a level | Land higher | Cave rock | Slopes (flat / ramp) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| BATTLE_FRONTIER_OUTSIDE_EAST (BattleFrontier_OutsideEast) | 3 | 2 | 0 | 0 | 0 | 1 | 0 | 1 | 3 | 0 | 0 | 0 / 0 |
| FORTREE_CITY_GYM *(modelled room)* (FortreeCity_Gym) | 15 | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| GRANITE_CAVE_1F (GraniteCave_1F) | 6 | 0 | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 / 0 |
| GRANITE_CAVE_B1F (GraniteCave_B1F) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 / 0 |
| GRANITE_CAVE_B2F (GraniteCave_B2F) | 4 | 1 | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| JAGGED_PASS (JaggedPass) | 96 | 81 | 3 | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 0 | 14 / 0 |
| LAVARIDGE_TOWN_GYM_1F *(modelled room)* (LavaridgeTown_Gym_1F) | 7 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| LAVARIDGE_TOWN_GYM_B1F *(modelled room)* (LavaridgeTown_Gym_B1F) | 15 | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| LILYCOVE_CITY (LilycoveCity) | 34 | 22 | 8 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| MAGMA_HIDEOUT_1F (MagmaHideout_1F) | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| METEOR_FALLS_1F_1R (MeteorFalls_1F_1R) | 34 | 34 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| METEOR_FALLS_1F_2R (MeteorFalls_1F_2R) | 54 | 54 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| PETALBURG_WOODS (PetalburgWoods) | 28 | 28 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| ROUTE101 (Route101) | 13 | 12 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| ROUTE102 (Route102) | 17 | 12 | 0 | 4 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| ROUTE103 (Route103) | 24 | 23 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| ROUTE104 (Route104) | 13 | 4 | 7 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| ROUTE110_TRICK_HOUSE_PUZZLE4 *(modelled room)* (Route110_TrickHousePuzzle4) | 11 | 11 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| ROUTE111 (Route111) | 31 | 29 | 0 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 / 4 |
| ROUTE111_NO_MIRAGE_TOWER (-) | 31 | 29 | 0 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 / 4 |
| ROUTE112 (Route112) | 41 | 2 | 0 | 38 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| ROUTE113 (Route113) | 72 | 31 | 13 | 21 | 3 | 4 | 0 | 50 | 19 | 9 | 0 | 0 / 0 |
| ROUTE114 (Route114) | 51 | 17 | 19 | 14 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| ROUTE115 (Route115) | 64 | 36 | 25 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 2 / 0 |
| ROUTE116 (Route116) | 29 | 18 | 9 | 0 | 2 | 0 | 22 | 2 | 5 | 0 | 0 | 0 / 0 |
| ROUTE118 (Route118) | 99 | 56 | 12 | 16 | 8 | 7 | 35 | 24 | 14 | 19 | 0 | 0 / 0 |
| ROUTE119 (Route119) | 4 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 / 0 |
| ROUTE120 (Route120) | 12 | 8 | 0 | 3 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| ROUTE123 (Route123) | 81 | 40 | 40 | 0 | 1 | 0 | 4 | 3 | 6 | 18 | 0 | 0 / 0 |
| RUSTURF_TUNNEL (RusturfTunnel) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 35 | 0 / 0 |
| SAFARI_ZONE_NORTH (SafariZone_North) | 6 | 4 | 1 | 1 | 0 | 0 | 5 | 1 | 2 | 0 | 0 | 3 / 0 |
| SAFARI_ZONE_NORTHEAST (SafariZone_Northeast) | 12 | 8 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| SAFARI_ZONE_SOUTH (SafariZone_South) | 12 | 10 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| SAFARI_ZONE_SOUTHWEST (SafariZone_Southwest) | 18 | 14 | 3 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 2 / 0 |
| SEAFLOOR_CAVERN_ROOM3 (SeafloorCavern_Room3) | 4 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| SEAFLOOR_CAVERN_ROOM4 (SeafloorCavern_Room4) | 13 | 9 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| SEAFLOOR_CAVERN_ROOM8 (SeafloorCavern_Room8) | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| SHOAL_CAVE_HIGH_TIDE_ENTRANCE_ROOM (ShoalCave_HighTideEntranceRoom) | 8 | 5 | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| SHOAL_CAVE_LOW_TIDE_ENTRANCE_ROOM (ShoalCave_LowTideEntranceRoom) | 8 | 5 | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| SHOAL_CAVE_LOW_TIDE_ICE_ROOM (ShoalCave_LowTideIceRoom) | 4 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| SHOAL_CAVE_LOW_TIDE_LOWER_ROOM (ShoalCave_LowTideLowerRoom) | 7 | 5 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| SOOTOPOLIS_CITY_GYM_1F *(modelled room)* (SootopolisCity_Gym_1F) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 / 0 |
| SOOTOPOLIS_CITY_GYM_B1F *(modelled room)* (SootopolisCity_Gym_B1F) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 / 0 |
| VICTORY_ROAD_1F (VictoryRoad_1F) | 5 | 3 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 10 | 0 / 0 |
| VICTORY_ROAD_B1F (VictoryRoad_B1F) | 10 | 0 | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| VICTORY_ROAD_B2F (VictoryRoad_B2F) | 5 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |
| **All 46 layouts** | **1007** | 673 | 161 | 120 | 31 | 22 | 66 | 81 | 49 | 46 | 47 | 37 / 8 |

(Walls, slabs, drops and "land higher" are counted for every ledge-shaped cell, the modelled rooms' included.)

## What changed (engine `f0f795f9`, `939d63a5`; PC only, the GBA ROM unchanged)

* **Each ledge is a bank across its cell** (`terrain_mesh.c` `DioramaTerrain_LedgeTop`): its grass rises from the
  ground of the cell it is jumped from to a crest across the middle, half a tile over the higher of the two grounds,
  and its rock face falls from the crest to the ground of the cell it lands in. The whole drawing lies on it (each
  region's own grass, ash, sand, cave floor and rock: Route 112's red rock, Route 113's ash, Meteor Falls' purple),
  each step's side in its own pixel's colour, so the rock face the GBA draws stands up as a face. Which way it is
  jumped is in the shape and the art: grass climbing from the side you jump from, a rock face dropping to the side
  you land on.
* **The grounds are the neighbours'** (`rules.c` `DioramaRules_LedgeGrounds`): a ledge on a lowered terrace stands
  on it (the 66 walls and 81 slabs are gone); one a level over its landing has its face down to it (49). The 46 that
  land higher keep the terrace levels they are given, the bank between the two (Route 113's and Route 123's 27 no
  longer land higher since engine `1291d718`: below).
* **Corners** are the higher of their two straight banks and meet the runs either side; **a run's end** shows its
  cross-section; ground on a higher level beside a bank hangs a side down to it, a pixel at a time.
* **Jumping**: the jump is the GBA's own arc. The walker's shadow lies on what is under it while it jumps a ledge (it
  went under the bank, and stood off the ground before it). Another player and their Pokemon are replayed across a
  ledge a step at a time (as in the 2D view): they now stand on the bank's crest, not two voxels into it.
* **Speed**: the fast terrain path draws banks directly, the same byte for byte as the per-pixel path (the tests
  check it). A chunk with a run of ledges builds in about 0.64 ms on this machine (0.19 ms as the old blocks, 6 ms
  through the per-pixel path).
* Nothing in the game's rules changed: collision, the jump and where a ledge can be jumped are the game's; the 2D
  view and the GBA ROM are the same (its hash unchanged).

## Tests

| Test | Result |
| --- | --- |
| `test_terrain_mesh`: the bank's profile jumped each way, corners, a ledge a level over its landing, one on a lowered terrace, the sides round one, both terrain paths the same byte for byte | Passed (L) |
| `test_sprite_frame`, `test_rules`, and `check-diorama` (every 3D test) on `1c081284` | Passed (L) |
| Every engine check target (48, `check-ability-items` included) and `check-diorama` on `1c081284` | **49 of 49 exit 0** (L) |
| GBA ROM rebuilt on `1c081284` | `f214735b...` unchanged (L) |
| 3D, Classic 2D and 3D test builds | Built (L) |
| The same 109 ledge and slope spots (45 maps), pictured before and after, the player three tiles from each | **108 pictured in both builds and compared one by one**: every terrain ledge in view a bank with its rock face, none floating, no gaps; Route 116's and 118's walls and Route 113's slabs gone (L, software OpenGL). Not seen: 6 spots in caves the picture shows only Flash's circle of (Granite Cave B1F and B2F, Victory Road B1F and B2F), 4 in modelled rooms (unchanged, as above), 1 that started a gym trainer's battle (Sootopolis Gym B1F, a slide). Shoal Cave's tide differs between the two runs (it follows the clock) |
| A jump over a ledge, frame by frame: Route 102 (south), Route 104 (west), Route 113 on a lowered terrace, Route 113 down a level, Route 123 up a level | The walker clears each bank with no clipping and lands where the game puts it (L) |
| Two games through a real world server (`two_ledge.py`, from the riding check): player B jumps Route 101's ledge, player A watches in 3D | B is replayed across the ledge's cell and stands on its crest, then steps down; B's Pokemon the same (L) |

## The ledges that landed higher: Route 113 and Route 123 (engine `1291d718`, 2026-10-28; MS-154)

**The cause.** The terrace solver (`tools/diorama_rules/terrace_topology.py` `solve_layout`) joins each run of the
General tileset's terrace art and the walkable ground it borders into one component and puts the component's highest
point on the top level (0). On Route 113 and Route 123 that highest point was only terrace art no one walks on (the
top of a cliff), so every walkable cell of the component lay a level below the top: Route 113's whole route (717
cells) and Route 123's tall grass under its mountain (79). Ground no terrace reaches lies on the top level, and there
it is the ground those ledges land on: Route 113's plateau east of its ledges at x 68 and the rest of Route 123. So
the 3D view showed every ledge from the sunken ground onto it rising a level (Route 113 9, Route 123 18), and 25
ledges the other way dropping a full level (Route 113 19, Route 123 6).

**The change.** Where a ledge leaves a component's walkable ground for ground no terrace reaches, the component's
highest walkable ground lies on the top level instead, the art's top a level over it (17 cliff cells: Route 113 11,
Route 123 6). The solver's answer changes on these two maps only (every layout compared, the committed solver and
the change: 813 entries), and so do the compiled rules (Route 113 1,088 records, Route 123 118: the ground, and the
trees and rock standing on it).

**Results (L).**

* The ledge count, as in the audit above: **19 land higher** (46 before), all on Route 118; Route 113 and Route 123
  none. The 25 that dropped a level now join ground on one level, as 912 others do; 24 drop a level.
* The seams: Route 113's ends now meet Fallarbor Town and Route 111 on one level (a level apart before: 26 pairs of
  cells). Across every seam, walkable cell pairs a level apart: 480 (506 before), none new.
* Neighbouring cells a level apart, before and after: Route 123 74 fewer, none new; Route 113 297 fewer and 8 new.
  Three of the new ones are flat cells inside the rock mass east of the route, holes 16 voxels deep before and now
  level with the rock's top (the count compares each cell's ground, and a rock cell's ground is below its top).
  The fourth is at a pocket of seven cells at (41-46, 15-16) with its own terrace art: it stays a level below that
  art, so it is now a level below the route. Pictured, it looks as it did.
* Pictures, the 3D test build before and after from the same places (software OpenGL): Route 123 at six (the
  grass, its pond, its west end, the path south of the grass, the grass's west side, the ground east of the pond) and
  Route 113 at nine (its ledges at x 68, the plateau from two places, both ends, the grass, the pocket, the rock,
  the south). Route 123: the dark walls where the grass met the route are gone; the ledges are banks; nothing else
  changed. Route 113: the steps at both ends are gone, and so are the grey see-through sides of the sunken route.
  The rock and the pocket look as before. The plateau is buried inside the rock mass in both builds (not changed
  here).
* Jumps frame by frame on both builds: Route 113 from the terrace at (22,3) and from the plateau at (75,6), south;
  Route 123 from (57,12) south and from (49,6) west. The walker clears each bank with no clipping and lands where the
  game puts it.
* Tests: `test_terrace_topology` (15 pass, 2 new): a cliff whose top no one walks on with a ledge from its low ground
  onto ground no terrace reaches (the ground on the top level, the cliff's top over it; with a wall for the ledge, as
  before); Route 113 and Route 123 (no ledge lands higher than it leaves, their ground on the top level, Route 113's
  ends at 0, the mountain's top a level over). Every engine check target and `check-diorama`: all 60 passed (5 builds,
  the ROM unchanged, the 54 targets, `check-diorama`); `test_compile_rules` (28) passes; `test_rules_parity` fails as
  before (KNOWN_ISSUES V2), with no new mismatch and 1,205 fewer (Route 113's and 123's records now agree with the C
  reader).

**Tried first and dropped.** Lowering the ground the ledges land on to the level they leave from instead (down
chains of ledges; a pond and a doorway inside it with it). It moved 638 walkable cells, and 1,208 records with the
trees and rock on them. The pictures showed terrace corner pieces left a level up like posts. They also showed the
forest along Route 123's north and south edges lowered while the area beyond a map's edge is drawn on the top level,
a step along each edge. Raising the terraces moves fewer cells and leaves the rest of each route, the map edges and
the neighbouring maps where they were.

## The stripes on a bank jumped west (engine `32d7bcd5`, 2026-10-28; MS-155)

The grass side of a ledge jumped west showed faint dark lines between its steps in the sun. The same spot on Route 104
pictured with the shadows off (`PKMN_DIORAMA_SHADOWS=0`) has none, so they were the sun's shadow: the sun is in the
west-north-west (`gl_shadow.c`), the grass of a bank jumped west faces away from it nearly along its rays (a few
degrees apart), and the bank's own voxel steps shaded the steps below them. A bank's faces now carry a mark
(`DIORAMA_TERRAIN_BANK_MASK`, in the vertex's reflection mask, under the reflection pass's 0.5), and the terrain
shader's sun shadow takes a bias of about 13 voxels along the sun for them (0.006 of the shadow map's depth; 0.0015
elsewhere, as before): a bank no longer shades itself, and trees and buildings, much taller, still shade it.

Tests (L): `test_terrain_mesh` (a bank's faces carry the mark, a chunk without ledges none; both terrain paths the
same); 21 ledge spots pictured before and after (11 jumped east or west, 10 south, the player three tiles south of each as
in the audit): the stripes are gone on those jumped west, one very faint line left along the bank's foot; banks jumped east,
north and south, and the ground and tree shadows round them, as before. Every engine check target and
`check-diorama`: all 60 passed (5 builds, the ROM unchanged, the 54 targets, `check-diorama`).

## Where maps meet: Route 118 and Route 116 (engine `723d7506`, 2026-10-28; MS-162)

Each layout's levels are solved alone, its top level 0, so a map whose top is its cliffs' tops lay under its
neighbours: Route 118's route a level under Mauville City, Route 119 and Route 123, a step along each seam, and Route
116 a level under Rustboro City. Counted from the compiled rules there were 23 such seams; 15 of them are the open sea
on both sides, which the renderer lays at one level whatever the rules say (pictured level at Routes 104/105 and
Slateport/Route 134), so 8 were real steps, all land.

The rules compiler now solves every layout, then moves a map's ground to meet the next map's
(`terrace_topology.py` `seam_shifts`, `compile_rules.py` `_seam_pairs`) and solves the layouts that move again. Ground
moves in groups that keep their levels to each other: a terrace component; the components a walkable pair or a jump
ledge joins; the ground round one mountain (Route 116's grass, its east plateau and the top of its mountain, whose
stairs and boulders stand on it); water with its banks (Route 118's lake and its plateau), but not the sea the next maps
share. A group moves only when every land cell pair it has with other ground, across the seams and in its own map,
asks the same, and no ledge between it and other ground would then jump up. Ground no terrace reaches (a town) is
where the others move to, and a group a mountain or water ties to it stays. Doorways of the game's "any level" take
their level from the ground they are entered from afterwards (Rusturf Tunnel's mouth on Route 116's grass).

Moved a level up: Route 118 and Route 116. Level now: Route 118 with Mauville City, Route 119 and Route 123, Route 116
with Rustboro City. Route 118's ledges that landed higher than they are jumped from: 19 → 6 (13 face its sea, which now
lies under the route, or are level banks; the 6 left stand by its lake's plateau, rock behind each, and none can be
jumped). Still a level apart: Mauville City and Route 111 (the lake at Route 111's south end touches ground the
terrace solver cannot level, so that end stays), the Battle Frontier's halves (the west walkway's terrace area also
lies flat with the plaza north of it, which meets the east half at its own level: moving it would open a step across
that plaza) and the Safari Zone's two.

Tests (L): the terrace solver's tests (19, 4 new: a component's shift, the ground meeting the next map's, a move that
would make a ledge jump up refused, the ground round a mountain moving together); the compiled rules' (a new test: the
four seams level, no ledge of Route 118's jumping up between walkable cells; Route 116's mountain a level up, its
tunnel mouth on the grass); the seams recounted from the compiled rules (land: 8 → 4, the sea's unchanged and leveled by
the renderer); the compiled rules compared with the last build's: only Route 116 and Route 118 change. Pictured before
and after in the 3D test build (12 spots): the four seams level (a step along each before), Route 116's mountain, its
tunnel mouth and its stairs as before a level up, Route 118's ledges and its corner by Mauville; Route 118's lake plateau
now stands two levels over the sea round it (one before: that water is the sea's to the renderer).

## Slopes and hills: where the next session starts (read from the map data, nothing changed)

Each slope run, its foot and its top (scratchpad `slopes/classify.py`: the region at its top flood-filled without the
slope, the GBA's walking rules: one elevation or an "any level" cell, a ledge one way only):

| Slope | Top / foot in the 3D view | The region at its top | What it needs |
| --- | --- | --- | --- |
| Route 111 (2 runs, muddy) | 16 / 0 | 213 cells, reached only up the slope | nothing: already a ramp to its plateau |
| Route 115 (28,8-9), muddy | 0 / 0 | 86 cells, only up the slope | the top region raised a level, the slope a ramp, its rock raised round it |
| Granite Cave B1F (9,9-10), muddy | 0 / 0 | 135 cells, only up the slope | the same |
| Safari Zone Southwest (8,2-3), muddy | 0 / 0 | 8 cells, then the map's north edge (the next Safari area) | a level across two maps: left flat |
| Route 119 (6,54-55), muddy | -1 / -1 | reached another way (1,858 cells) | the level change sits a row north of it (the GBA's elevations 3 and 4 meet there): the slope stays a shortcut |
| Safari Zone North (22,21-23), bumpy | -1 / -2 | reached another way | a mound ringed by ledges on three sides: its levels need the ledges (below) |
| Jagged Pass (5 runs, bumpy) | 0 / 0 | 3 reached another way, 2 only up the slope | the whole pass lies on one level (below) |

Jagged Pass (no map connections: it is reached by warps, so no seam to match): its walkable regions cut by its ledges
and slopes, each ledge asking its take-off region to stand a level over its landing and each slope its top over its
foot (`slopes/ledge_graph.py`), solve to a staircase of six levels from the Mt. Chimney end down to the Lavaridge end,
with 54 of the 76 asks contradicting at the small islands ringed by ledges (rows 9-11, 14-16, 22-33), where the GBA's art
has no single height. A level solver for such a pass (ledges as "at least as high", the islands' contradictions
resolved by the fewest steps), its rock walls raised with the terraces and the pictures checked spot by spot is the next
session's work. Route 113's and Route 123's ledges that landed higher are fixed (above), and 13 of Route 118's 19; its
6 left, which the player cannot jump, stand by its lake's plateau.

## Not done

* **The 37 flat slopes**: both ends of each lie on one level in the 3D view's terrace levels, so there is no height for
  a slope to climb; the terrace solver (`tools/diorama_rules/terrace_topology.py`) has to split them first.
* **Route 118's 6 ledges that land a level higher** than they are jumped from (MS-154): none of them can be jumped
  (rock behind each, by its lake's plateau). Its seams with Mauville City, Route 119 and Route 123 are level since
  MS-162 (above); four other land seams are still a level apart (Mauville City and Route 111, the Battle Frontier's
  halves, the Safari Zone's two).
* **The 48 ledges in modelled rooms** keep their rooms' models.
* Not run: a graphics card, Windows, the owner's PCs.
