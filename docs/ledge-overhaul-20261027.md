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
  (Route 118 19, Route 123 18, Route 113 9): the 3D view's terrace levels disagree with the jump there.

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
  land higher keep the terrace levels they are given, the bank between the two.
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

## Not done

* **The 37 flat slopes**: both ends of each lie on one level in the 3D view's terrace levels, so there is no height for
  a slope to climb; the terrace solver (`tools/diorama_rules/terrace_topology.py`) has to split them first.
* **The 46 ledges that land a level higher** than they are jumped from: the same solver's levels.
* **The 48 ledges in modelled rooms** keep their rooms' models.
* The grass side of an east or west ledge shows faint lines between its steps in the sun (each step's shadow).
* Not run: a graphics card, Windows, the owner's PCs.
