# 3D map sweep: the coverage of every map (2026-11-05, MS-98)

The automated 3D map sweep after KNOWN_ISSUES MS-98's work (the owner's directive of 2026-11-05: "Finish the
automated 3D map sweep and coverage reporting"): which maps of the game the sweep looks at, how it gets there, why it
leaves the others out, and what this run found. The sweep is `tools/qa/geometry_check.py` with the geometry probe of
the 3D test build (the checks: `docs/3d-world-geometry-20261029.md`, phase B; the last full sweep's defect list:
`docs/3d-geometry-report-20261030.md`). Engine: `claude/feature-update-engine` `1cd6cf13`, `dc83fc66`, `2feffcba`, `8765e3ac`, `f99a691f`, `ddb390db`, `14187f20` (cherry-picked from branch
`claude/ms98-sweep` on `b270e14a`; the last three are that branch's `48f34993`, `b8a2107e` and `90be7182`); the run's 3D
test build is that C code. Linux, the 3D test build, Mesa's software OpenGL (llvmpipe) under `xvfb-run -a`. Not run on
Windows.

## What changed

* **The Battle Tower's multi partner room and the Battle Pike's room are entered through their facilities**, as a
  player enters them, not warped to (MS-98: "the next sweep should enter them through their facilities"). The probe
  stands in front of the attendant with three level-50 Pokemon (Charizard, Blastoise, Venusaur) and goes in with test
  inputs: A through every line and question (CHALLENGE, LV. 50, YES to the save), the frontier's party screen filled
  from the first Pokemon (as many as the challenge asks, then CONFIRM), and on the field the talk to the attendant and,
  in the Pike's room of three paths, the walk to the door the room's hint points to (another door when the hinted room
  is the wild Pokemon's, a map of its own: the other two doors cannot hide it). The cells and the pictures are taken
  on the first frame the field is free in the room, as for a warp; the room's own event (the Pike's trainer) waits
  until they are taken.
  * **Tower:** the lobby's multi battle attendant (CHALLENGE, LV. 50, two Pokemon, the save), the elevator, the
    partner room's welcome: in the room at (10,2) after 2,327 game frames.
  * **Pike:** its attendant (CHALLENGE, LV. 50, three Pokemon, the save), the corridor, the room of three paths, the
    door, the room: at (4,7) after 2,863 game frames (its hint put the wild Pokemon's room behind the centre door, so the probe took the left one: a trainer with a Pokemon beside it).
* **Found on the way: the multi partner room stopped the PC game in play, not only after a warp.** Entered through
  the facility, the game still faulted as the room loaded (`battle_tower.c` 1200, `LoadMultiPartnerCandidatesData`):
  the original game sets the Frontier's trainer and Pokemon tables there first (pret pokeemerald:
  `level = SetFacilityPtrsGetLevel()`), the expansion dropped that call with its unused result (still missing upstream,
  master and upcoming), and nothing on a multi battle challenge's way in sets them, so in a session without an earlier
  Frontier battle they were NULL - the GBA reads its BIOS there and carries on with junk partners, the PC stopped. Every
  multi battle challenge with a computer partner started in a fresh session would have closed the game. Fixed under
  `PORTABLE` (engine `1cd6cf13`: the call again); the GBA object of `battle_tower.c` is byte-identical before and
  after, and to the one in the ROM `f214735b...3387`; `check_gba_lines` 0 moved.
* **The maps no player reaches on PC are left out of the sweep, each with the code's reason** (below: "Not reachable
  on PC: why"), instead of warping into them: the Union Room (its attendant lets a player in only when
  `IsWirelessAdapterConnected`, which is FALSE on PC: "The Wireless Adapter isn't connected"; warped in, its wireless
  partner search faults), the Trade Center, Record Corner and both colosseums (a link cable's link-up only), the
  Mystery Events house's B1F (an e-Reader trainer only), the truck (the PC's short introduction starts in Littleroot)
  and the contest halls' shared events map (nothing leads there). The 2026-10-30 sweep had warped into seven of these
  eight (all but the Union Room, which stopped it).
* The tools: `geometry_check.py tour --sample N` (every N-th map, the facility rooms always), `run --minutes M` (no new
  game process after M minutes), the results' lines say how each place was reached and where the player stood, and
  `tools/qa/map_coverage.py` writes this report from the check's manifest (engine `dc83fc66`, `2feffcba`, `8765e3ac`;
  a later run into the same folder goes on with only the places that have no result: `f99a691f`).

## This run

* **One game process at a time** (`--jobs 1`) on a 4-core machine shared with other sessions' builds and games (load
  average 20 to 35 at first, about 12 at the end): about 35 seconds a place at first, 9 to 14 later. The whole tour
  (529 places) did not fit the run's 2 hours, so it went: (1) the two facility rooms; (2) a 1-in-7 sample of the tour's
  maps in its order (`tour --sample 7`: 73 maps, 81 places with the two rooms - 44 rooms, 15 caves, 9 outdoor maps, 3
  secret bases, 2 underwater, the whole tour's mix); (3) the rest of the tour, its maps interleaved (a scratch list: the
  other six 1-in-7 shares in turn) so that a stop leaves a spread, under a time budget (`run --minutes`), then a short
  top-up. 19:53 to 22:05 UTC (2 h 12 min; a first
  start of the whole tour at 19:42 was stopped after 7 minutes when the machine's load showed it could not fit, and its
  10 places were dropped).
* **490 of the tour's 529 places done**, every one "ok" (drawn in 3D, its scene settled); **456 of the tour's 495
  maps wholly inspected**, the two rooms among them through their facilities, none partly. 39 maps (one place each)
  were left when the budget ran out: the table below names them, each with what the 2026-10-30 sweep made of it (it
  had inspected all 39 wholly). No game crashed. At 19 places a game ended after the place's pictures, its own script then
  holding the field (a battle room's opponent coming in, a map's own scene), and the next game went on from the next
  place; 17 of those places did the same in the 10-30 sweep, two are new (the Battle Frontier's reception gate,
  Sootopolis Gym B1F). 45 game processes; a first top-up captured 37 finished places a second time (same code: the check keeps the last) before the
  tool's resume fix (engine `f99a691f`).
* **Against the 2026-10-30 sweep** (engine `5ea03aec`): of the 455 maps both looked at, 387 give exactly the same
  numbers and 68 differ - the 3D world's work merged since (79 engine commits: the Safari Zone's terraces, Sootopolis's
  streets, Routes 119 to 121's hills, the ramps and stairs, Ever Grande's halls, the Battle Frontier's halves on one
  level, the Pyramid's top, Jagged Pass, the trees, rock sides). On those 455 maps: fin 1,630 -> 1,273, spike
  858 -> 807, flat-blocked 12,691 -> 13,737, walk-step 63 -> 50, seam 54 -> 0, water-wall 24 -> 24, water-drop
  1,422 -> 1,417, hole 9 -> 10 places (Faraway Island's gone; Lavaridge Town's and Route 119's new, each in the 15-degree
  view with 48 and 59 sky pixels, just over the check's 40).
* **This run's totals** (456 maps): fin 1,273, spike 807, flat-blocked 13,783, walk-step 50, water-wall 24, water-drop
  1,417, hole 10 places. Outdoors (60 maps): fin 538, spike 465, flat-blocked 3,937, walk-step 7, water-wall 24,
  water-drop 1,357, hole 8; caves (95): fin 715, spike 337, flat-blocked 2,888, walk-step 40, water-drop 58, hole 1;
  underwater (11): fin 20, spike 5, flat-blocked 18; rooms (266): flat-blocked 6,902, walk-step 3, water-drop 2, hole 1;
  secret bases (24): flat-blocked 38. Each map's own numbers are in the table below; the check's full report and
  manifest (the cells of each finding, the pictures) stay with the run (`report.md`, `manifest.json`).

## The two rooms: what the checks found

* **Battle Tower multi partner room** (26.15): 315 of 315 cells; flat-blocked 46, nothing else; no sky in any of its four
  pictures. The 46: the back wall's two rows across the room (y 0-1, x 0-20: the wall's metatiles 0x209 and 0x211,
  18 each, and the elevator door's frame, 0x206, 0x20e, 0x21e, 0x21f, 0x226, 0x227) and four cells of the front row
  (y 14, x 0, 1, 19, 20: 0x267 three times, 0x276), all read as flat ground. In the pictures the room stands whole, the
  back wall a band along its top edge, its candidate partners and the attendant in place. The first look at this room:
  every sweep before stopped there.
* **Battle Pike room** (26.37): 72 of 72 cells; flat-blocked 13 (the curtained stage behind the room's people, y 0-3 x
  3-5, metatiles 0x2a2 to 0x2bc, and the two cells (2,7) and (6,7), 0x22d); no sky in its pictures. The same 13 cells
  the 10-30 sweep counted after its warp with the battle number set by hand: entered through the facility, the room
  is drawn the same way.

As the 10-30 report says, a flagged cell is a cell to look at, not always a fault.

## For KNOWN_ISSUES MS-98

Suggested for the MS-98 row (the main session owns KNOWN_ISSUES): **Fixed 2026-11-05.** The sweep enters both rooms
through their facilities (`tools/qa/geometry_check.py` FACILITY_ENTRIES; engine `dc83fc66`, `2feffcba`) and leaves out the
Union Room and the other maps no PC player reaches, each with the code's reason (this report). Its explanation of the
multi partner room was wrong: entered through the facility, the room still stopped the game - in play, in any session
without an earlier Frontier battle - because the expansion dropped the original's `SetFacilityPtrsGetLevel()` call;
fixed under PORTABLE (`1cd6cf13`). That crash deserves a row of its own (every Battle Tower multi battle challenge with
a computer partner closed the PC game as the partner room loaded; fixed; Linux only, not run on Windows).

## How this report is made

From the engine checkout, the 3D test build (`make -f Makefile_pc NATIVE_LINUX=1 DIORAMA=1 BFX_TEST=1`) and a display (Linux: `xvfb-run -a`):

```sh
tools/qa/geometry_check.py tour --out build/qa/geo/tour.txt
xvfb-run -a -s "-screen 0 1280x720x24 -nolisten tcp" tools/qa/geometry_check.py run \
    --exe ./pokeemerald-mp-diorama-bfxtest --make-save build/qa/geo/new.sav --tour build/qa/geo/tour.txt \
    --out build/qa/geo --jobs 1
tools/qa/geometry_check.py check --out build/qa/geo --tour build/qa/geo/tour.txt
tools/qa/map_coverage.py --sweep build/qa/geo --out <this report> --intro <its introduction> \
    --previous <app>/docs/3d-geometry-report-20261030.md --previous-label "the 2026-10-30 sweep" --not-run-note <the note below>
```

The pictures and the cell dumps the sweep writes (`shots/`, `cells/`) are the game's art and stay out of the repositories.

## Totals

| Status | Maps |
| --- | --- |
| inspected | 454 |
| entered through its facility | 2 |
| not reachable on PC | 440 |
| not inspected | 39 |
| all (the map list, `data/maps/map_groups.json`) | 935 |

Of the 456 maps looked at, 456 were wholly seen (every cell of the map in some place's scene).

The Emerald game's 503 maps by kind (the other 432 of the list are FireRed/LeafGreen maps this build leaves out, and unused ones):

| Kind | inspected | entered through its facility | not reachable on PC | not inspected |
| --- | --- | --- | --- | --- |
| outdoor | 60 | 0 | 0 | 7 |
| cave | 95 | 0 | 0 | 4 |
| underwater | 11 | 0 | 0 | 3 |
| indoor | 264 | 2 | 8 | 25 |
| secret_base | 24 | 0 | 0 | 0 |
| all | 454 | 2 | 8 | 39 |

## Not reachable on PC: why

* **FireRed/LeafGreen: not in this build** (417): a FireRed/LeafGreen map in the data: the Emerald build leaves it out (tools/mapjson: a map whose layout is not Emerald's is not assembled; the Kanto map groups are NULL in gMapGroups, data/maps/groups.inc), so no warp of the game can reach it (KNOWN_ISSUES M14). Maps: BattleColosseum_2P_Frlg, TradeCenter_Frlg, RecordCorner_Frlg, BattleColosseum_4P_Frlg, UnionRoom_Frlg, ViridianForest_Frlg ... (417 maps)
* **unused: nothing leads there** (15): in the data and the build, but no warp, map connection or script of the game leads there (tools/qa/inventory.py's reachability from Littleroot Town: the Ruby/Sapphire prototypes, the unused contest halls and mart). Maps: LilycoveCity_UnusedMart, CaveOfOrigin_UnusedRubySapphireMap1, CaveOfOrigin_UnusedRubySapphireMap2, CaveOfOrigin_UnusedRubySapphireMap3, AquaHideout_UnusedRubyMap1, AquaHideout_UnusedRubyMap2, AquaHideout_UnusedRubyMap3, UnusedContestHall1, UnusedContestHall2, UnusedContestHall3, UnusedContestHall4, UnusedContestHall5, UnusedContestHall6, Route104_Prototype, Route104_PrototypePrettyPetalFlowerShop
* **no link cable on PC** (4): a link room: entered only after a link-up with another GBA over the link cable (data/scripts/cable_club.inc: TryBattleLinkup, TryTradeLinkup or TryRecordMixLinkup has to succeed; src/cable_club.c Task_LinkupAwaitConnection waits for a second linked player) or from the Union Room (src/union_room.c WarpForCableClubActivity). The PC has no link cable and no Wireless Adapter; its own trades and battles between players never use this room. Maps: BattleColosseum_2P, TradeCenter, RecordCorner, BattleColosseum_4P
* **no e-Reader trainer on PC** (1): its stairs open only while an e-Reader trainer is stored (SootopolisCity_MysteryEventsHouse_1F's OnTransition: frontier_checkvisittrainer, then setmaplayoutindex ..._STAIRS_UNBLOCKED), and that trainer comes only from an e-Reader card over the link cable (src/mystery_event_script.c) or a Mystery Gift over wireless (src/mystery_gift_client.c): a PC receives neither (no link cable; the Mystery Gift's wireless search says the Wireless Adapter isn't connected, src/union_room.c). Maps: SootopolisCity_MysteryEventsHouse_B1F
* **nothing leads there** (1): no warp, script or C code leads to MAP_CONTEST_HALL: it holds the events and scripts the five contest halls of each category share (their map.json shared_events_map), and those are the halls a contest enters (LilycoveCity_ContestLobby: setwarp MAP_CONTEST_HALL_COOL and the others). Maps: ContestHall
* **the PC's short introduction** (1): the original introduction's first room: the PC game starts a new character in Littleroot Town through its short introduction (src/multiplayer_rival.c MultiplayerIntro_IsEnabled: the truck only with PKMN_ORIGINAL_INTRO=1, a development switch). Maps: InsideOfTruck
* **no Wireless Adapter on PC** (1): the Union Room attendant (data/scripts/cable_club.inc CableClub_EventScript_UnionRoomAttendant) lets a player in only when IsWirelessAdapterConnected, which is FALSE on PC (src/link.c: no GBA Wireless Adapter): "The Wireless Adapter isn't connected". Her warpspinenter is the room's only way in (the Pokemon Centers' Union Room scan is off on PC too: src/link.c ShouldCheckForUnionRoom). Warped in directly, the room's wireless partner search faults (KNOWN_ISSUES MS-98). Maps: UnionRoom

## Not inspected: why

The run's time budget (about 2 hours on a loaded machine; see "This run" above) ran out with 39 of the tour's 529 places left, one place each of these maps. Each row shows the 2026-10-30 sweep's result for its map.

* **this run did not get to it** (39): Maps: MauvilleCity, LittlerootTown, Route101, Route108, Route115, Route122, VerdanturfTown_BattleTentBattleRoom, PacifidlogTown_PokemonCenter_1F, PetalburgCity_WallysHouse, SlateportCity_SternsShipyard_1F, SlateportCity_House, MauvilleCity_GameCorner, RustboroCity_DevonCorp_3F, RustboroCity_Flat1_2F, RustboroCity_House3, FortreeCity_House3, LilycoveCity_House1, LilycoveCity_DepartmentStore_4F, MossdeepCity_PokemonCenter_1F, MossdeepCity_SpaceCenter_2F, SootopolisCity_Mart, SootopolisCity_House7, EverGrandeCity_ChampionsRoom, EverGrandeCity_HallOfFame, Route111_OldLadysRestStop, Route117_PokemonDayCare, Underwater_SootopolisCity, MtChimney, MtPyre_5F, Underwater_SeafloorCavern, SeafloorCavern_Room6, VictoryRoad_1F, ShoalCave_HighTideEntranceRoom, AbandonedShip_Corridors_B1F, AbandonedShip_Underwater2, BattleFrontier_BattlePyramidTop, BattleFrontier_BattlePikeRoomFinal, TrainerHill_3F, TrainerHill_Elevator
  * the 2026-10-30 sweep: 39 of these 39 wholly inspected, 0 not wholly; each map's row below says which

**The 39 inspected on 2026-11-06** (the same tool, the 3D test build of engine `0397596d`, which this run's tour had left; one game process at a time, 02:01-02:10 UTC, under the same machine's load): **39 of 39 places done, every one "ok", the 39 maps wholly inspected; no game crashed.** Four games ended between places as this run's did (Verdanturf's Battle Tent battle room starting its trainer's battle in 3D; the probe's "the field was not free after place N" after Rustboro's Devon Corp 3F, the Champion's Room and the Hall of Fame), the next going on from the next place. Against the 2026-10-30 sweep: 36 of the 39 maps give exactly the same numbers; Mauville City's 10 seams are gone (MS-162), Route 115 fin 23 -> 22, spike 14 -> 12, flat-blocked 19 -> 25, the Hall of Fame flat-blocked 34 -> 32 (the 3D world's work merged since, as for the other maps above). The 39 maps' totals: fin 126, spike 59, flat-blocked 1,375, walk-step 9, water-drop 77, no seam, hole, water-wall or not-3d. **With them every one of the tour's 529 places (495 maps, the two facility rooms through their facilities) has been inspected in the 3D game in November**: 490 by this run, 39 on 2026-11-06. L only (Mesa's software OpenGL); the pictures and cell dumps stay out of the repositories.

## Entered through their facilities

* **BattleFrontier_BattleTowerMultiPartnerRoom** (315/315 cells; flat-blocked 46): a Battle Tower multi battle challenge (Lv. 50, two Pokemon) from the lobby's multi battle attendant: her questions, the party screen, the save, the elevator, then the partner room's welcome
* **BattleFrontier_BattlePikeRoomNormal** (72/72 cells; flat-blocked 13): a Battle Pike challenge (Lv. 50, three Pokemon) from its attendant: her questions, the party screen, the save, the corridor, the room of three paths and the door its hint points to (another one when the hinted room is the wild Pokemon's, a map of its own); the pictures as the player steps in, before the room's event (a trainer, a healer, a Pokemon's status move) starts

## Every map

In the map list's order (group.number). Cells: those of the map the sweep's scenes held, of all. Found: the geometry checks' cells (places for hole and not-3d; `tools/qa/geometry_check.py`, the app's docs/3d-world-geometry-20261029.md). Note: why a map is not looked at (the reasons above), or how.

| Map | # | Kind | Status | Cells | Found | Note |
| --- | --- | --- | --- | --- | --- | --- |
| PetalburgCity | 0.0 | outdoor | inspected | 900/900 | flat-blocked 10 |  |
| SlateportCity | 0.1 | outdoor | inspected | 2400/2400 | spike 1, flat-blocked 63, water-drop 36 |  |
| MauvilleCity | 0.2 | outdoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 800/800) |
| RustboroCity | 0.3 | outdoor | inspected | 2400/2400 | flat-blocked 36, water-drop 4 |  |
| FortreeCity | 0.4 | outdoor | inspected | 800/800 | flat-blocked 63, hole 1 |  |
| LilycoveCity | 0.5 | outdoor | inspected | 3200/3200 | fin 24, spike 13, flat-blocked 179, water-drop 81 |  |
| MossdeepCity | 0.6 | outdoor | inspected | 3200/3200 | fin 19, spike 18, flat-blocked 112, water-wall 24, water-drop 72 |  |
| SootopolisCity | 0.7 | outdoor | inspected | 3600/3600 | fin 56, spike 73, flat-blocked 172, water-drop 45 |  |
| EverGrandeCity | 0.8 | outdoor | inspected | 3200/3200 | fin 14, spike 21, flat-blocked 16, water-drop 1 |  |
| LittlerootTown | 0.9 | outdoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 400/400) |
| OldaleTown | 0.10 | outdoor | inspected | 400/400 |  |  |
| DewfordTown | 0.11 | outdoor | inspected | 400/400 | fin 3, spike 1, flat-blocked 9, water-drop 17 |  |
| LavaridgeTown | 0.12 | outdoor | inspected | 400/400 | fin 21, spike 2, flat-blocked 12, hole 1 |  |
| FallarborTown | 0.13 | outdoor | inspected | 400/400 | flat-blocked 55 |  |
| VerdanturfTown | 0.14 | outdoor | inspected | 400/400 | flat-blocked 15 |  |
| PacifidlogTown | 0.15 | outdoor | inspected | 800/800 | fin 37, water-drop 97, hole 1 |  |
| Route101 | 0.16 | outdoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 400/400) |
| Route102 | 0.17 | outdoor | inspected | 1000/1000 | flat-blocked 2 |  |
| Route103 | 0.18 | outdoor | inspected | 1760/1760 | flat-blocked 18, water-drop 23 |  |
| Route104 | 0.19 | outdoor | inspected | 3200/3200 | spike 2, flat-blocked 31, water-drop 4 |  |
| Route105 | 0.20 | outdoor | inspected | 3200/3200 | fin 4, spike 10, flat-blocked 10, water-drop 69 |  |
| Route106 | 0.21 | outdoor | inspected | 1600/1600 | spike 1, flat-blocked 14, water-drop 51 |  |
| Route107 | 0.22 | outdoor | inspected | 1200/1200 | fin 4, water-drop 9 |  |
| Route108 | 0.23 | outdoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 1200/1200) |
| Route109 | 0.24 | outdoor | inspected | 2520/2520 | spike 1, flat-blocked 1, water-drop 108, hole 2 |  |
| Route110 | 0.25 | outdoor | inspected | 4000/4000 | spike 12, flat-blocked 174, water-drop 208 |  |
| Route111 | 0.26 | outdoor | inspected | 5600/5600 | fin 22, spike 29, flat-blocked 67 |  |
| Route112 | 0.27 | outdoor | inspected | 2400/2400 | fin 6, spike 19, flat-blocked 38 |  |
| Route113 | 0.28 | outdoor | inspected | 2000/2000 | fin 3, spike 8, flat-blocked 82 |  |
| Route114 | 0.29 | outdoor | inspected | 3200/3200 | spike 6, flat-blocked 59, water-drop 123 |  |
| Route115 | 0.30 | outdoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 3200/3200) |
| Route116 | 0.31 | outdoor | inspected | 2000/2000 | flat-blocked 10 |  |
| Route117 | 0.32 | outdoor | inspected | 1200/1200 | fin 3, flat-blocked 29 |  |
| Route118 | 0.33 | outdoor | inspected | 1600/1600 | spike 4, flat-blocked 88, water-drop 39 |  |
| Route119 | 0.34 | outdoor | inspected | 5600/5600 | fin 10, spike 24, flat-blocked 435, water-drop 77, hole 1 |  |
| Route120 | 0.35 | outdoor | inspected | 4000/4000 | spike 12, flat-blocked 524 |  |
| Route121 | 0.36 | outdoor | inspected | 1600/1600 | fin 3, spike 5, flat-blocked 68, water-drop 4 |  |
| Route122 | 0.37 | outdoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 1600/1600) |
| Route123 | 0.38 | outdoor | inspected | 2800/2800 | spike 2, flat-blocked 34, water-drop 34 |  |
| Route124 | 0.39 | outdoor | inspected | 6400/6400 | fin 16, spike 11, flat-blocked 16, water-drop 21, hole 1 |  |
| Route125 | 0.40 | outdoor | inspected | 3200/3200 | fin 8, spike 12, flat-blocked 24, water-drop 8 |  |
| Route126 | 0.41 | outdoor | inspected | 6400/6400 | fin 6, spike 7, flat-blocked 43, water-drop 2 |  |
| Route127 | 0.42 | outdoor | inspected | 6400/6400 | spike 32, flat-blocked 6 |  |
| Route128 | 0.43 | outdoor | inspected | 4800/4800 | fin 7, spike 10, flat-blocked 10, water-drop 1 |  |
| Route129 | 0.44 | outdoor | inspected | 3200/3200 | spike 4, flat-blocked 10 |  |
| Route130 | 0.45 | outdoor | inspected | 3200/3200 | fin 4, spike 7, flat-blocked 4 |  |
| Route131 | 0.46 | outdoor | inspected | 2400/2400 | fin 7, spike 2, flat-blocked 2, water-drop 10, hole 1 |  |
| Route132 | 0.47 | outdoor | inspected | 3200/3200 | fin 14, spike 5, water-drop 17 |  |
| Route133 | 0.48 | outdoor | inspected | 3200/3200 |  |  |
| Route134 | 0.49 | outdoor | inspected | 3200/3200 | fin 28, spike 2, water-drop 12 |  |
| Underwater_Route124 | 0.50 | underwater | inspected | 6400/6400 |  |  |
| Underwater_Route126 | 0.51 | underwater | inspected | 6400/6400 | fin 5 |  |
| Underwater_Route127 | 0.52 | underwater | inspected | 6400/6400 |  |  |
| Underwater_Route128 | 0.53 | underwater | inspected | 4800/4800 |  |  |
| Underwater_Route129 | 0.54 | underwater | inspected | 3200/3200 |  |  |
| Underwater_Route105 | 0.55 | underwater | inspected | 3200/3200 |  |  |
| Underwater_Route125 | 0.56 | underwater | inspected | 3200/3200 |  |  |
| LittlerootTown_BrendansHouse_1F | 1.0 | indoor | inspected | 99/99 |  |  |
| LittlerootTown_BrendansHouse_2F | 1.1 | indoor | inspected | 72/72 |  |  |
| LittlerootTown_MaysHouse_1F | 1.2 | indoor | inspected | 99/99 |  |  |
| LittlerootTown_MaysHouse_2F | 1.3 | indoor | inspected | 72/72 |  |  |
| LittlerootTown_ProfessorBirchsLab | 1.4 | indoor | inspected | 169/169 |  |  |
| OldaleTown_House1 | 2.0 | indoor | inspected | 90/90 |  |  |
| OldaleTown_House2 | 2.1 | indoor | inspected | 88/88 |  |  |
| OldaleTown_PokemonCenter_1F | 2.2 | indoor | inspected | 126/126 |  |  |
| OldaleTown_PokemonCenter_2F | 2.3 | indoor | inspected | 140/140 |  |  |
| OldaleTown_Mart | 2.4 | indoor | inspected | 88/88 |  |  |
| DewfordTown_House1 | 3.0 | indoor | inspected | 80/80 | flat-blocked 4 |  |
| DewfordTown_PokemonCenter_1F | 3.1 | indoor | inspected | 126/126 |  |  |
| DewfordTown_PokemonCenter_2F | 3.2 | indoor | inspected | 140/140 |  |  |
| DewfordTown_Gym | 3.3 | indoor | inspected | 504/504 | flat-blocked 72 |  |
| DewfordTown_Hall | 3.4 | indoor | inspected | 153/153 | flat-blocked 17 |  |
| DewfordTown_House2 | 3.5 | indoor | inspected | 90/90 | flat-blocked 6 |  |
| LavaridgeTown_HerbShop | 4.0 | indoor | inspected | 88/88 | flat-blocked 33 |  |
| LavaridgeTown_Gym_1F | 4.1 | indoor | inspected | 323/323 | flat-blocked 21 |  |
| LavaridgeTown_Gym_B1F | 4.2 | indoor | inspected | 323/323 | flat-blocked 53 |  |
| LavaridgeTown_House | 4.3 | indoor | inspected | 80/80 | flat-blocked 4 |  |
| LavaridgeTown_Mart | 4.4 | indoor | inspected | 88/88 |  |  |
| LavaridgeTown_PokemonCenter_1F | 4.5 | indoor | inspected | 126/126 |  |  |
| LavaridgeTown_PokemonCenter_2F | 4.6 | indoor | inspected | 140/140 |  |  |
| FallarborTown_Mart | 5.0 | indoor | inspected | 88/88 |  |  |
| FallarborTown_BattleTentLobby | 5.1 | indoor | inspected | 130/130 | flat-blocked 60 |  |
| FallarborTown_BattleTentCorridor | 5.2 | indoor | inspected | 40/40 | flat-blocked 9 |  |
| FallarborTown_BattleTentBattleRoom | 5.3 | indoor | inspected | 90/90 | flat-blocked 7 |  |
| FallarborTown_PokemonCenter_1F | 5.4 | indoor | inspected | 126/126 |  |  |
| FallarborTown_PokemonCenter_2F | 5.5 | indoor | inspected | 140/140 |  |  |
| FallarborTown_CozmosHouse | 5.6 | indoor | inspected | 90/90 |  |  |
| FallarborTown_MoveRelearnersHouse | 5.7 | indoor | inspected | 88/88 |  |  |
| VerdanturfTown_BattleTentLobby | 6.0 | indoor | inspected | 130/130 | flat-blocked 60 |  |
| VerdanturfTown_BattleTentCorridor | 6.1 | indoor | inspected | 40/40 | flat-blocked 9 |  |
| VerdanturfTown_BattleTentBattleRoom | 6.2 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 117/117) |
| VerdanturfTown_Mart | 6.3 | indoor | inspected | 88/88 |  |  |
| VerdanturfTown_PokemonCenter_1F | 6.4 | indoor | inspected | 126/126 |  |  |
| VerdanturfTown_PokemonCenter_2F | 6.5 | indoor | inspected | 140/140 |  |  |
| VerdanturfTown_WandasHouse | 6.6 | indoor | inspected | 136/136 | flat-blocked 5 |  |
| VerdanturfTown_FriendshipRatersHouse | 6.7 | indoor | inspected | 88/88 |  |  |
| VerdanturfTown_House | 6.8 | indoor | inspected | 90/90 |  |  |
| PacifidlogTown_PokemonCenter_1F | 7.0 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 126/126) |
| PacifidlogTown_PokemonCenter_2F | 7.1 | indoor | inspected | 140/140 |  |  |
| PacifidlogTown_House1 | 7.2 | indoor | inspected | 90/90 | flat-blocked 5 |  |
| PacifidlogTown_House2 | 7.3 | indoor | inspected | 90/90 | flat-blocked 4 |  |
| PacifidlogTown_House3 | 7.4 | indoor | inspected | 90/90 | flat-blocked 5 |  |
| PacifidlogTown_House4 | 7.5 | indoor | inspected | 90/90 | flat-blocked 4 |  |
| PacifidlogTown_House5 | 7.6 | indoor | inspected | 90/90 | flat-blocked 5 |  |
| PetalburgCity_WallysHouse | 8.0 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 88/88) |
| PetalburgCity_Gym | 8.1 | indoor | inspected | 1008/1008 | flat-blocked 4 |  |
| PetalburgCity_House1 | 8.2 | indoor | inspected | 90/90 |  |  |
| PetalburgCity_House2 | 8.3 | indoor | inspected | 80/80 |  |  |
| PetalburgCity_PokemonCenter_1F | 8.4 | indoor | inspected | 126/126 |  |  |
| PetalburgCity_PokemonCenter_2F | 8.5 | indoor | inspected | 140/140 |  |  |
| PetalburgCity_Mart | 8.6 | indoor | inspected | 88/88 |  |  |
| SlateportCity_SternsShipyard_1F | 9.0 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 315/315) |
| SlateportCity_SternsShipyard_2F | 9.1 | indoor | inspected | 255/255 | flat-blocked 115 |  |
| SlateportCity_BattleTentLobby | 9.2 | indoor | inspected | 130/130 | flat-blocked 60 |  |
| SlateportCity_BattleTentCorridor | 9.3 | indoor | inspected | 40/40 | flat-blocked 9 |  |
| SlateportCity_BattleTentBattleRoom | 9.4 | indoor | inspected | 90/90 | flat-blocked 7 |  |
| SlateportCity_NameRatersHouse | 9.5 | indoor | inspected | 80/80 |  |  |
| SlateportCity_PokemonFanClub | 9.6 | indoor | inspected | 154/154 | flat-blocked 46 |  |
| SlateportCity_OceanicMuseum_1F | 9.7 | indoor | inspected | 180/180 | flat-blocked 60 |  |
| SlateportCity_OceanicMuseum_2F | 9.8 | indoor | inspected | 180/180 |  |  |
| SlateportCity_Harbor | 9.9 | indoor | inspected | 360/360 | flat-blocked 97 |  |
| SlateportCity_House | 9.10 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 88/88) |
| SlateportCity_PokemonCenter_1F | 9.11 | indoor | inspected | 126/126 |  |  |
| SlateportCity_PokemonCenter_2F | 9.12 | indoor | inspected | 140/140 |  |  |
| SlateportCity_Mart | 9.13 | indoor | inspected | 88/88 |  |  |
| MauvilleCity_Gym | 10.0 | indoor | inspected | 210/210 | flat-blocked 22 |  |
| MauvilleCity_BikeShop | 10.1 | indoor | inspected | 108/108 | flat-blocked 2 |  |
| MauvilleCity_House1 | 10.2 | indoor | inspected | 88/88 |  |  |
| MauvilleCity_GameCorner | 10.3 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 242/242) |
| MauvilleCity_House2 | 10.4 | indoor | inspected | 90/90 |  |  |
| MauvilleCity_PokemonCenter_1F | 10.5 | indoor | inspected | 126/126 |  |  |
| MauvilleCity_PokemonCenter_2F | 10.6 | indoor | inspected | 140/140 |  |  |
| MauvilleCity_Mart | 10.7 | indoor | inspected | 88/88 |  |  |
| RustboroCity_DevonCorp_1F | 11.0 | indoor | inspected | 171/171 |  |  |
| RustboroCity_DevonCorp_2F | 11.1 | indoor | inspected | 171/171 | flat-blocked 18 |  |
| RustboroCity_DevonCorp_3F | 11.2 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 171/171) |
| RustboroCity_Gym | 11.3 | indoor | inspected | 220/220 | flat-blocked 4 |  |
| RustboroCity_PokemonSchool | 11.4 | indoor | inspected | 132/132 | flat-blocked 14 |  |
| RustboroCity_PokemonCenter_1F | 11.5 | indoor | inspected | 126/126 |  |  |
| RustboroCity_PokemonCenter_2F | 11.6 | indoor | inspected | 140/140 |  |  |
| RustboroCity_Mart | 11.7 | indoor | inspected | 88/88 |  |  |
| RustboroCity_Flat1_1F | 11.8 | indoor | inspected | 112/112 | flat-blocked 4 |  |
| RustboroCity_Flat1_2F | 11.9 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 112/112) |
| RustboroCity_House1 | 11.10 | indoor | inspected | 104/104 | flat-blocked 6 |  |
| RustboroCity_CuttersHouse | 11.11 | indoor | inspected | 99/99 | flat-blocked 4 |  |
| RustboroCity_House2 | 11.12 | indoor | inspected | 108/108 | flat-blocked 4 |  |
| RustboroCity_Flat2_1F | 11.13 | indoor | inspected | 126/126 | flat-blocked 4 |  |
| RustboroCity_Flat2_2F | 11.14 | indoor | inspected | 126/126 | flat-blocked 2 |  |
| RustboroCity_Flat2_3F | 11.15 | indoor | inspected | 126/126 |  |  |
| RustboroCity_House3 | 11.16 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 108/108) |
| FortreeCity_House1 | 12.0 | indoor | inspected | 48/48 | flat-blocked 4 |  |
| FortreeCity_Gym | 12.1 | indoor | inspected | 500/500 | flat-blocked 111 |  |
| FortreeCity_PokemonCenter_1F | 12.2 | indoor | inspected | 126/126 |  |  |
| FortreeCity_PokemonCenter_2F | 12.3 | indoor | inspected | 140/140 |  |  |
| FortreeCity_Mart | 12.4 | indoor | inspected | 88/88 |  |  |
| FortreeCity_House2 | 12.5 | indoor | inspected | 48/48 | flat-blocked 6 |  |
| FortreeCity_House3 | 12.6 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 48/48) |
| FortreeCity_House4 | 12.7 | indoor | inspected | 48/48 | flat-blocked 6 |  |
| FortreeCity_House5 | 12.8 | indoor | inspected | 48/48 | flat-blocked 4 |  |
| FortreeCity_DecorationShop | 12.9 | indoor | inspected | 48/48 | flat-blocked 14 |  |
| LilycoveCity_CoveLilyMotel_1F | 13.0 | indoor | inspected | 108/108 | flat-blocked 19 |  |
| LilycoveCity_CoveLilyMotel_2F | 13.1 | indoor | inspected | 108/108 | flat-blocked 8 |  |
| LilycoveCity_LilycoveMuseum_1F | 13.2 | indoor | inspected | 294/294 | flat-blocked 99 |  |
| LilycoveCity_LilycoveMuseum_2F | 13.3 | indoor | inspected | 286/286 | flat-blocked 93 |  |
| LilycoveCity_ContestLobby | 13.4 | indoor | inspected | 372/372 | flat-blocked 74 |  |
| LilycoveCity_ContestHall | 13.5 | indoor | inspected | 1683/1683 | flat-blocked 444 | warped to; in play its facility's or event's script enters it |
| LilycoveCity_PokemonCenter_1F | 13.6 | indoor | inspected | 126/126 |  |  |
| LilycoveCity_PokemonCenter_2F | 13.7 | indoor | inspected | 140/140 |  |  |
| LilycoveCity_UnusedMart | 13.8 | indoor | not reachable on PC | - |  | unused: nothing leads there |
| LilycoveCity_PokemonTrainerFanClub | 13.9 | indoor | inspected | 168/168 | flat-blocked 31 |  |
| LilycoveCity_Harbor | 13.10 | indoor | inspected | 360/360 | flat-blocked 97 |  |
| LilycoveCity_MoveDeletersHouse | 13.11 | indoor | inspected | 88/88 |  |  |
| LilycoveCity_House1 | 13.12 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 90/90) |
| LilycoveCity_House2 | 13.13 | indoor | inspected | 64/64 | flat-blocked 4 |  |
| LilycoveCity_House3 | 13.14 | indoor | inspected | 88/88 |  |  |
| LilycoveCity_House4 | 13.15 | indoor | inspected | 90/90 |  |  |
| LilycoveCity_DepartmentStore_1F | 13.16 | indoor | inspected | 144/144 | flat-blocked 50 |  |
| LilycoveCity_DepartmentStore_2F | 13.17 | indoor | inspected | 144/144 | flat-blocked 46 |  |
| LilycoveCity_DepartmentStore_3F | 13.18 | indoor | inspected | 144/144 | flat-blocked 42 |  |
| LilycoveCity_DepartmentStore_4F | 13.19 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 144/144) |
| LilycoveCity_DepartmentStore_5F | 13.20 | indoor | inspected | 144/144 | flat-blocked 57 |  |
| LilycoveCity_DepartmentStoreRooftop | 13.21 | indoor | inspected | 216/216 | flat-blocked 118 |  |
| LilycoveCity_DepartmentStoreElevator | 13.22 | indoor | inspected | 30/30 | flat-blocked 15 |  |
| MossdeepCity_Gym | 14.0 | indoor | inspected | 936/936 | flat-blocked 1 |  |
| MossdeepCity_House1 | 14.1 | indoor | inspected | 88/88 |  |  |
| MossdeepCity_House2 | 14.2 | indoor | inspected | 90/90 |  |  |
| MossdeepCity_PokemonCenter_1F | 14.3 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 126/126) |
| MossdeepCity_PokemonCenter_2F | 14.4 | indoor | inspected | 140/140 |  |  |
| MossdeepCity_Mart | 14.5 | indoor | inspected | 88/88 |  |  |
| MossdeepCity_House3 | 14.6 | indoor | inspected | 88/88 |  |  |
| MossdeepCity_StevensHouse | 14.7 | indoor | inspected | 88/88 | flat-blocked 8 |  |
| MossdeepCity_House4 | 14.8 | indoor | inspected | 80/80 |  |  |
| MossdeepCity_SpaceCenter_1F | 14.9 | indoor | inspected | 160/160 | flat-blocked 9 |  |
| MossdeepCity_SpaceCenter_2F | 14.10 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 160/160) |
| MossdeepCity_GameCorner_1F | 14.11 | indoor | inspected | 120/120 |  |  |
| MossdeepCity_GameCorner_B1F | 14.12 | indoor | inspected | 108/108 | flat-blocked 21 |  |
| SootopolisCity_Gym_1F | 15.0 | indoor | inspected | 442/442 | flat-blocked 98 |  |
| SootopolisCity_Gym_B1F | 15.1 | indoor | inspected | 442/442 | flat-blocked 190 |  |
| SootopolisCity_PokemonCenter_1F | 15.2 | indoor | inspected | 126/126 |  |  |
| SootopolisCity_PokemonCenter_2F | 15.3 | indoor | inspected | 140/140 |  |  |
| SootopolisCity_Mart | 15.4 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 88/88) |
| SootopolisCity_House1 | 15.5 | indoor | inspected | 56/56 | flat-blocked 4 |  |
| SootopolisCity_House2 | 15.6 | indoor | inspected | 56/56 | flat-blocked 4 |  |
| SootopolisCity_House3 | 15.7 | indoor | inspected | 56/56 | flat-blocked 2 |  |
| SootopolisCity_House4 | 15.8 | indoor | inspected | 56/56 | flat-blocked 4 |  |
| SootopolisCity_House5 | 15.9 | indoor | inspected | 56/56 | flat-blocked 4 |  |
| SootopolisCity_House6 | 15.10 | indoor | inspected | 56/56 | flat-blocked 2 |  |
| SootopolisCity_House7 | 15.11 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 56/56) |
| SootopolisCity_LotadAndSeedotHouse | 15.12 | indoor | inspected | 56/56 | flat-blocked 4 |  |
| SootopolisCity_MysteryEventsHouse_1F | 15.13 | indoor | inspected | 88/88 |  |  |
| SootopolisCity_MysteryEventsHouse_B1F | 15.14 | indoor | not reachable on PC | - |  | no e-Reader trainer on PC |
| EverGrandeCity_SidneysRoom | 16.0 | indoor | inspected | 182/182 | flat-blocked 20 |  |
| EverGrandeCity_PhoebesRoom | 16.1 | indoor | inspected | 182/182 | flat-blocked 20 |  |
| EverGrandeCity_GlaciasRoom | 16.2 | indoor | inspected | 182/182 | flat-blocked 20 |  |
| EverGrandeCity_DrakesRoom | 16.3 | indoor | inspected | 182/182 | flat-blocked 20 |  |
| EverGrandeCity_ChampionsRoom | 16.4 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 169/169) |
| EverGrandeCity_Hall1 | 16.5 | indoor | inspected | 143/143 | flat-blocked 96 |  |
| EverGrandeCity_Hall2 | 16.6 | indoor | inspected | 143/143 | flat-blocked 96 |  |
| EverGrandeCity_Hall3 | 16.7 | indoor | inspected | 143/143 | flat-blocked 96 |  |
| EverGrandeCity_Hall4 | 16.8 | indoor | inspected | 374/374 | flat-blocked 252 |  |
| EverGrandeCity_Hall5 | 16.9 | indoor | inspected | 143/143 | flat-blocked 96 |  |
| EverGrandeCity_PokemonLeague_1F | 16.10 | indoor | inspected | 228/228 | flat-blocked 40 |  |
| EverGrandeCity_HallOfFame | 16.11 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 255/255) |
| EverGrandeCity_PokemonCenter_1F | 16.12 | indoor | inspected | 126/126 |  |  |
| EverGrandeCity_PokemonCenter_2F | 16.13 | indoor | inspected | 140/140 |  |  |
| EverGrandeCity_PokemonLeague_2F | 16.14 | indoor | inspected | 140/140 |  |  |
| Route104_MrBrineysHouse | 17.0 | indoor | inspected | 108/108 |  |  |
| Route104_PrettyPetalFlowerShop | 17.1 | indoor | inspected | 135/135 | flat-blocked 4 |  |
| Route111_WinstrateFamilysHouse | 18.0 | indoor | inspected | 88/88 |  |  |
| Route111_OldLadysRestStop | 18.1 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 80/80) |
| Route112_CableCarStation | 19.0 | indoor | inspected | 156/156 | flat-blocked 72 |  |
| MtChimney_CableCarStation | 19.1 | indoor | inspected | 156/156 | flat-blocked 72 |  |
| Route114_FossilManiacsHouse | 20.0 | indoor | inspected | 80/80 | flat-blocked 4 |  |
| Route114_FossilManiacsTunnel | 20.1 | indoor | inspected | 338/338 | flat-blocked 192 |  |
| Route114_LanettesHouse | 20.2 | indoor | inspected | 88/88 | flat-blocked 11 |  |
| Route116_TunnelersRestHouse | 21.0 | indoor | inspected | 90/90 | flat-blocked 8 |  |
| Route117_PokemonDayCare | 22.0 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 108/108) |
| Route121_SafariZoneEntrance | 23.0 | indoor | inspected | 252/252 | flat-blocked 59 |  |
| MeteorFalls_1F_1R | 24.0 | cave | inspected | 1260/1260 | fin 31, spike 31, flat-blocked 3, walk-step 2, water-drop 11 |  |
| MeteorFalls_1F_2R | 24.1 | cave | inspected | 960/960 | fin 13, spike 7, flat-blocked 4 |  |
| MeteorFalls_B1F_1R | 24.2 | cave | inspected | 1102/1102 | fin 4, spike 8, flat-blocked 3, walk-step 3, water-drop 9 |  |
| MeteorFalls_B1F_2R | 24.3 | cave | inspected | 198/198 | flat-blocked 1 |  |
| RusturfTunnel | 24.4 | cave | inspected | 864/864 | fin 52, spike 30, flat-blocked 3 |  |
| Underwater_SootopolisCity | 24.5 | underwater | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 200/200) |
| DesertRuins | 24.6 | cave | inspected | 561/561 | fin 19, spike 4, flat-blocked 8 |  |
| GraniteCave_1F | 24.7 | cave | inspected | 630/630 | fin 14, spike 4, flat-blocked 2 |  |
| GraniteCave_B1F | 24.8 | cave | inspected | 832/832 | fin 45, spike 2 |  |
| GraniteCave_B2F | 24.9 | cave | inspected | 832/832 | fin 32, spike 3 |  |
| GraniteCave_StevensRoom | 24.10 | cave | inspected | 210/210 |  |  |
| PetalburgWoods | 24.11 | outdoor | inspected | 2112/2112 | flat-blocked 38 |  |
| MtChimney | 24.12 | outdoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 1880/1880) |
| JaggedPass | 24.13 | outdoor | inspected | 1380/1380 | fin 31, spike 29, flat-blocked 12 |  |
| FieryPath | 24.14 | cave | inspected | 1330/1330 | spike 5, flat-blocked 11 |  |
| MtPyre_1F | 24.15 | indoor | inspected | 418/418 |  |  |
| MtPyre_2F | 24.16 | indoor | inspected | 169/169 | flat-blocked 5 |  |
| MtPyre_3F | 24.17 | indoor | inspected | 169/169 | flat-blocked 5 |  |
| MtPyre_4F | 24.18 | indoor | inspected | 169/169 | flat-blocked 7 |  |
| MtPyre_5F | 24.19 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 169/169) |
| MtPyre_6F | 24.20 | indoor | inspected | 169/169 | flat-blocked 5 |  |
| MtPyre_Exterior | 24.21 | outdoor | inspected | 1938/1938 | fin 32, spike 6, flat-blocked 20 |  |
| MtPyre_Summit | 24.22 | outdoor | inspected | 1850/1850 | fin 65, spike 19, flat-blocked 31 |  |
| AquaHideout_1F | 24.23 | indoor | inspected | 840/840 | flat-blocked 92 |  |
| AquaHideout_B1F | 24.24 | indoor | inspected | 1224/1224 | flat-blocked 185 |  |
| AquaHideout_B2F | 24.25 | indoor | inspected | 816/816 | flat-blocked 60 |  |
| Underwater_SeafloorCavern | 24.26 | underwater | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 126/126) |
| SeafloorCavern_Entrance | 24.27 | cave | inspected | 400/400 |  |  |
| SeafloorCavern_Room1 | 24.28 | cave | inspected | 420/420 | fin 6, spike 3, flat-blocked 2 |  |
| SeafloorCavern_Room2 | 24.29 | cave | inspected | 216/216 | spike 1, flat-blocked 2 |  |
| SeafloorCavern_Room3 | 24.30 | cave | inspected | 272/272 | flat-blocked 2 |  |
| SeafloorCavern_Room4 | 24.31 | cave | inspected | 342/342 | flat-blocked 1 |  |
| SeafloorCavern_Room5 | 24.32 | cave | inspected | 400/400 | fin 3, flat-blocked 2 |  |
| SeafloorCavern_Room6 | 24.33 | cave | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 552/552) |
| SeafloorCavern_Room7 | 24.34 | cave | inspected | 575/575 | flat-blocked 180 |  |
| SeafloorCavern_Room8 | 24.35 | cave | inspected | 154/154 | flat-blocked 1 |  |
| SeafloorCavern_Room9 | 24.36 | cave | inspected | 1242/1242 | spike 14, flat-blocked 4 |  |
| CaveOfOrigin_Entrance | 24.37 | cave | inspected | 494/494 | spike 2, flat-blocked 1 |  |
| CaveOfOrigin_1F | 24.38 | cave | inspected | 529/529 | flat-blocked 1 |  |
| CaveOfOrigin_UnusedRubySapphireMap1 | 24.39 | cave | not reachable on PC | - |  | unused: nothing leads there |
| CaveOfOrigin_UnusedRubySapphireMap2 | 24.40 | cave | not reachable on PC | - |  | unused: nothing leads there |
| CaveOfOrigin_UnusedRubySapphireMap3 | 24.41 | cave | not reachable on PC | - |  | unused: nothing leads there |
| CaveOfOrigin_B1F | 24.42 | cave | inspected | 361/361 | fin 6, spike 8 |  |
| VictoryRoad_1F | 24.43 | cave | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 2070/2070) |
| VictoryRoad_B1F | 24.44 | cave | inspected | 1426/1426 | fin 33, spike 13, walk-step 4 |  |
| VictoryRoad_B2F | 24.45 | cave | inspected | 1426/1426 | fin 30, spike 13, walk-step 5 |  |
| ShoalCave_LowTideEntranceRoom | 24.46 | cave | inspected | 1225/1225 | fin 30, spike 11 |  |
| ShoalCave_LowTideInnerRoom | 24.47 | cave | inspected | 1748/1748 | fin 22, spike 24, flat-blocked 9, walk-step 6 |  |
| ShoalCave_LowTideStairsRoom | 24.48 | cave | inspected | 315/315 | fin 10, spike 4, flat-blocked 1 |  |
| ShoalCave_LowTideLowerRoom | 24.49 | cave | inspected | 434/434 | flat-blocked 3 |  |
| ShoalCave_HighTideEntranceRoom | 24.50 | cave | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 1225/1225) |
| ShoalCave_HighTideInnerRoom | 24.51 | cave | inspected | 1748/1748 | fin 5, spike 14, flat-blocked 2, walk-step 9, water-drop 38 | warped to; in play the low-tide room's map with this layout |
| NewMauville_Entrance | 24.52 | cave | inspected | 81/81 | spike 2, flat-blocked 6, hole 1 |  |
| NewMauville_Inside | 24.53 | cave | inspected | 1681/1681 | flat-blocked 209 |  |
| AbandonedShip_Deck | 24.54 | cave | inspected | 483/483 | flat-blocked 308 |  |
| AbandonedShip_Corridors_1F | 24.55 | cave | inspected | 216/216 | flat-blocked 15 |  |
| AbandonedShip_Rooms_1F | 24.56 | cave | inspected | 306/306 | flat-blocked 59 |  |
| AbandonedShip_Corridors_B1F | 24.57 | cave | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 130/130) |
| AbandonedShip_Rooms_B1F | 24.58 | cave | inspected | 216/216 | flat-blocked 19 |  |
| AbandonedShip_Rooms2_B1F | 24.59 | cave | inspected | 144/144 | flat-blocked 79 |  |
| AbandonedShip_Underwater1 | 24.60 | underwater | inspected | 64/64 | flat-blocked 16 |  |
| AbandonedShip_Room_B1F | 24.61 | cave | inspected | 72/72 | flat-blocked 31 |  |
| AbandonedShip_Rooms2_1F | 24.62 | cave | inspected | 153/153 | flat-blocked 34 |  |
| AbandonedShip_CaptainsOffice | 24.63 | cave | inspected | 63/63 | flat-blocked 26 |  |
| AbandonedShip_Underwater2 | 24.64 | underwater | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 147/147) |
| AbandonedShip_HiddenFloorCorridors | 24.65 | cave | inspected | 143/143 | flat-blocked 16 |  |
| AbandonedShip_HiddenFloorRooms | 24.66 | cave | inspected | 660/660 | flat-blocked 286 |  |
| IslandCave | 24.67 | cave | inspected | 561/561 | fin 19, spike 4, flat-blocked 8 |  |
| AncientTomb | 24.68 | cave | inspected | 561/561 | fin 19, spike 4, flat-blocked 8 |  |
| Underwater_Route134 | 24.69 | underwater | inspected | 180/180 | fin 3, spike 2, flat-blocked 1 |  |
| Underwater_SealedChamber | 24.70 | underwater | inspected | 1056/1056 | fin 12, spike 1 |  |
| SealedChamber_OuterRoom | 24.71 | cave | inspected | 483/483 | fin 3, flat-blocked 6 |  |
| SealedChamber_InnerRoom | 24.72 | cave | inspected | 483/483 | flat-blocked 1 |  |
| ScorchedSlab | 24.73 | cave | inspected | 300/300 | flat-blocked 1 |  |
| AquaHideout_UnusedRubyMap1 | 24.74 | cave | not reachable on PC | - |  | unused: nothing leads there |
| AquaHideout_UnusedRubyMap2 | 24.75 | cave | not reachable on PC | - |  | unused: nothing leads there |
| AquaHideout_UnusedRubyMap3 | 24.76 | cave | not reachable on PC | - |  | unused: nothing leads there |
| SkyPillar_Entrance | 24.77 | cave | inspected | 324/324 | spike 4, flat-blocked 2 |  |
| SkyPillar_Outside | 24.78 | outdoor | inspected | 644/644 | fin 5, flat-blocked 59, water-drop 4 |  |
| SkyPillar_1F | 24.79 | cave | inspected | 196/196 | flat-blocked 63 |  |
| SkyPillar_2F | 24.80 | cave | inspected | 196/196 | flat-blocked 62 |  |
| SkyPillar_3F | 24.81 | cave | inspected | 196/196 | flat-blocked 61 |  |
| SkyPillar_4F | 24.82 | cave | inspected | 196/196 | flat-blocked 61 |  |
| ShoalCave_LowTideIceRoom | 24.83 | cave | inspected | 600/600 | fin 3, spike 24, flat-blocked 3, walk-step 1 |  |
| SkyPillar_5F | 24.84 | cave | inspected | 196/196 | flat-blocked 90 |  |
| SkyPillar_Top | 24.85 | outdoor | inspected | 648/648 | flat-blocked 211 |  |
| MagmaHideout_1F | 24.86 | cave | inspected | 1406/1406 | fin 37, spike 3, flat-blocked 21 |  |
| MagmaHideout_2F_1R | 24.87 | cave | inspected | 1287/1287 | fin 34, spike 7, flat-blocked 26 |  |
| MagmaHideout_2F_2R | 24.88 | cave | inspected | 1372/1372 | fin 3, spike 18, flat-blocked 60 |  |
| MagmaHideout_3F_1R | 24.89 | cave | inspected | 672/672 | fin 19, spike 4, flat-blocked 99 |  |
| MagmaHideout_3F_2R | 24.90 | cave | inspected | 408/408 | spike 1, flat-blocked 63 |  |
| MagmaHideout_4F | 24.91 | cave | inspected | 1652/1652 | fin 3, spike 7, flat-blocked 168 |  |
| MagmaHideout_3F_3R | 24.92 | cave | inspected | 792/792 | fin 41, spike 10, flat-blocked 26 |  |
| MagmaHideout_2F_3R | 24.93 | cave | inspected | 1140/1140 |  |  |
| MirageTower_1F | 24.94 | cave | inspected | 357/357 | flat-blocked 71 |  |
| MirageTower_2F | 24.95 | cave | inspected | 357/357 | flat-blocked 68 |  |
| MirageTower_3F | 24.96 | cave | inspected | 357/357 | flat-blocked 63 |  |
| MirageTower_4F | 24.97 | cave | inspected | 130/130 | flat-blocked 27, walk-step 1 |  |
| DesertUnderpass | 24.98 | cave | inspected | 3197/3197 | flat-blocked 1 |  |
| ArtisanCave_B1F | 24.99 | cave | inspected | 2484/2484 | fin 76, spike 15, flat-blocked 1, walk-step 7 |  |
| ArtisanCave_1F | 24.100 | cave | inspected | 462/462 | flat-blocked 1 |  |
| Underwater_MarineCave | 24.101 | underwater | inspected | 200/200 | spike 2, flat-blocked 1 |  |
| MarineCave_Entrance | 24.102 | cave | inspected | 400/400 |  |  |
| MarineCave_End | 24.103 | cave | inspected | 810/810 | fin 26, spike 1, flat-blocked 4 |  |
| TerraCave_Entrance | 24.104 | cave | inspected | 400/400 | flat-blocked 1 |  |
| TerraCave_End | 24.105 | cave | inspected | 810/810 | fin 5, spike 3, flat-blocked 52 |  |
| AlteringCave | 24.106 | cave | inspected | 768/768 | fin 3, spike 11, flat-blocked 1, walk-step 2 |  |
| MeteorFalls_StevensCave | 24.107 | cave | inspected | 960/960 | spike 3, flat-blocked 17 |  |
| SecretBase_RedCave1 | 25.0 | secret_base | inspected | 99/99 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_BrownCave1 | 25.1 | secret_base | inspected | 99/99 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_BlueCave1 | 25.2 | secret_base | inspected | 99/99 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_YellowCave1 | 25.3 | secret_base | inspected | 99/99 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_Tree1 | 25.4 | secret_base | inspected | 99/99 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_Shrub1 | 25.5 | secret_base | inspected | 99/99 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_RedCave2 | 25.6 | secret_base | inspected | 112/112 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_BrownCave2 | 25.7 | secret_base | inspected | 126/126 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_BlueCave2 | 25.8 | secret_base | inspected | 105/105 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_YellowCave2 | 25.9 | secret_base | inspected | 126/126 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_Tree2 | 25.10 | secret_base | inspected | 112/112 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_Shrub2 | 25.11 | secret_base | inspected | 105/105 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_RedCave3 | 25.12 | secret_base | inspected | 120/120 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_BrownCave3 | 25.13 | secret_base | inspected | 165/165 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_BlueCave3 | 25.14 | secret_base | inspected | 170/170 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_YellowCave3 | 25.15 | secret_base | inspected | 132/132 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_Tree3 | 25.16 | secret_base | inspected | 136/136 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_Shrub3 | 25.17 | secret_base | inspected | 143/143 | flat-blocked 1 | warped to; in play entered from a secret base spot |
| SecretBase_RedCave4 | 25.18 | secret_base | inspected | 135/135 | flat-blocked 3 | warped to; in play entered from a secret base spot |
| SecretBase_BrownCave4 | 25.19 | secret_base | inspected | 168/168 | flat-blocked 3 | warped to; in play entered from a secret base spot |
| SecretBase_BlueCave4 | 25.20 | secret_base | inspected | 153/153 | flat-blocked 3 | warped to; in play entered from a secret base spot |
| SecretBase_YellowCave4 | 25.21 | secret_base | inspected | 182/182 | flat-blocked 3 | warped to; in play entered from a secret base spot |
| SecretBase_Tree4 | 25.22 | secret_base | inspected | 196/196 | flat-blocked 5 | warped to; in play entered from a secret base spot |
| SecretBase_Shrub4 | 25.23 | secret_base | inspected | 154/154 | flat-blocked 3 | warped to; in play entered from a secret base spot |
| BattleColosseum_2P | 25.24 | indoor | not reachable on PC | - |  | no link cable on PC |
| TradeCenter | 25.25 | indoor | not reachable on PC | - |  | no link cable on PC |
| RecordCorner | 25.26 | indoor | not reachable on PC | - |  | no link cable on PC |
| BattleColosseum_4P | 25.27 | indoor | not reachable on PC | - |  | no link cable on PC |
| ContestHall | 25.28 | indoor | not reachable on PC | - |  | nothing leads there |
| UnusedContestHall1 | 25.29 | indoor | not reachable on PC | - |  | unused: nothing leads there |
| UnusedContestHall2 | 25.30 | indoor | not reachable on PC | - |  | unused: nothing leads there |
| UnusedContestHall3 | 25.31 | indoor | not reachable on PC | - |  | unused: nothing leads there |
| UnusedContestHall4 | 25.32 | indoor | not reachable on PC | - |  | unused: nothing leads there |
| UnusedContestHall5 | 25.33 | indoor | not reachable on PC | - |  | unused: nothing leads there |
| UnusedContestHall6 | 25.34 | indoor | not reachable on PC | - |  | unused: nothing leads there |
| ContestHallBeauty | 25.35 | indoor | inspected | 165/165 | flat-blocked 67 | warped to; in play its facility's or event's script enters it |
| ContestHallTough | 25.36 | indoor | inspected | 165/165 | flat-blocked 67 | warped to; in play its facility's or event's script enters it |
| ContestHallCool | 25.37 | indoor | inspected | 165/165 | flat-blocked 67 | warped to; in play its facility's or event's script enters it |
| ContestHallSmart | 25.38 | indoor | inspected | 165/165 | flat-blocked 67 | warped to; in play its facility's or event's script enters it |
| ContestHallCute | 25.39 | indoor | inspected | 165/165 | flat-blocked 67 | warped to; in play its facility's or event's script enters it |
| InsideOfTruck | 25.40 | indoor | not reachable on PC | - |  | the PC's short introduction |
| SSTidalCorridor | 25.41 | indoor | inspected | 234/234 | flat-blocked 109 |  |
| SSTidalLowerDeck | 25.42 | indoor | inspected | 221/221 | flat-blocked 19 |  |
| SSTidalRooms | 25.43 | indoor | inspected | 648/648 | flat-blocked 52 |  |
| BattlePyramidSquare01 | 25.44 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare02 | 25.45 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare03 | 25.46 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare04 | 25.47 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare05 | 25.48 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare06 | 25.49 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare07 | 25.50 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare08 | 25.51 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare09 | 25.52 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare10 | 25.53 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare11 | 25.54 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare12 | 25.55 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare13 | 25.56 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare14 | 25.57 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare15 | 25.58 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| BattlePyramidSquare16 | 25.59 | indoor | inspected | 64/64 |  | warped to; in play a piece of a Battle Pyramid floor (the C code copies its cells there) |
| UnionRoom | 25.60 | indoor | not reachable on PC | - |  | no Wireless Adapter on PC |
| SafariZone_Northwest | 26.0 | outdoor | inspected | 1600/1600 | fin 4, spike 8, flat-blocked 45, water-drop 5 |  |
| SafariZone_North | 26.1 | outdoor | inspected | 1600/1600 | fin 19, spike 11, flat-blocked 73 |  |
| SafariZone_Southwest | 26.2 | outdoor | inspected | 1600/1600 | flat-blocked 105 |  |
| SafariZone_South | 26.3 | outdoor | inspected | 1600/1600 | fin 8, spike 3, flat-blocked 44 |  |
| BattleFrontier_OutsideWest | 26.4 | outdoor | inspected | 4032/4032 | fin 34, spike 11, flat-blocked 276, walk-step 1, water-drop 65 |  |
| BattleFrontier_BattleTowerLobby | 26.5 | indoor | inspected | 250/250 | flat-blocked 14 |  |
| BattleFrontier_BattleTowerElevator | 26.6 | indoor | inspected | 35/35 | flat-blocked 12 | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattleTowerCorridor | 26.7 | indoor | inspected | 85/85 | flat-blocked 34 | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattleTowerBattleRoom | 26.8 | indoor | inspected | 90/90 | flat-blocked 2 | warped to; in play its facility's or event's script enters it |
| SouthernIsland_Exterior | 26.9 | outdoor | inspected | 990/990 | flat-blocked 21, water-drop 3 |  |
| SouthernIsland_Interior | 26.10 | outdoor | inspected | 648/648 | flat-blocked 10 |  |
| SafariZone_RestHouse | 26.11 | indoor | inspected | 90/90 |  |  |
| SafariZone_Northeast | 26.12 | outdoor | inspected | 1600/1600 | fin 15, spike 8, flat-blocked 27 |  |
| SafariZone_Southeast | 26.13 | outdoor | inspected | 1600/1600 | spike 2, flat-blocked 98, water-drop 35 |  |
| BattleFrontier_OutsideEast | 26.14 | outdoor | inspected | 5184/5184 | fin 6, spike 12, flat-blocked 326, walk-step 6, water-drop 72 |  |
| BattleFrontier_BattleTowerMultiPartnerRoom | 26.15 | indoor | entered through its facility | 315/315 | flat-blocked 46 | through its facility |
| BattleFrontier_BattleTowerMultiCorridor | 26.16 | indoor | inspected | 85/85 | flat-blocked 26 | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattleTowerMultiBattleRoom | 26.17 | indoor | inspected | 90/90 | flat-blocked 2 | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattleDomeLobby | 26.18 | indoor | inspected | 391/391 | flat-blocked 179 |  |
| BattleFrontier_BattleDomeCorridor | 26.19 | indoor | inspected | 336/336 | flat-blocked 6 | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattleDomePreBattleRoom | 26.20 | indoor | inspected | 72/72 | flat-blocked 4 | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattleDomeBattleRoom | 26.21 | indoor | inspected | 200/200 |  | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattlePalaceLobby | 26.22 | indoor | inspected | 300/300 |  |  |
| BattleFrontier_BattlePalaceCorridor | 26.23 | indoor | inspected | 238/238 | flat-blocked 59 | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattlePalaceBattleRoom | 26.24 | indoor | inspected | 150/150 | flat-blocked 33, hole 1 | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattlePyramidLobby | 26.25 | indoor | inspected | 270/270 | flat-blocked 128 |  |
| BattleFrontier_BattlePyramidFloor | 26.26 | indoor | inspected | 64/64 |  | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattlePyramidTop | 26.27 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 782/782) |
| BattleFrontier_BattleArenaLobby | 26.28 | indoor | inspected | 208/208 | flat-blocked 131 |  |
| BattleFrontier_BattleArenaCorridor | 26.29 | indoor | inspected | 252/252 | flat-blocked 84 | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattleArenaBattleRoom | 26.30 | indoor | inspected | 176/176 |  | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattleFactoryLobby | 26.31 | indoor | inspected | 228/228 |  |  |
| BattleFrontier_BattleFactoryPreBattleRoom | 26.32 | indoor | inspected | 238/238 |  | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattleFactoryBattleRoom | 26.33 | indoor | inspected | 156/156 |  | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattlePikeLobby | 26.34 | indoor | inspected | 143/143 |  |  |
| BattleFrontier_BattlePikeCorridor | 26.35 | indoor | inspected | 112/112 |  | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattlePikeThreePathRoom | 26.36 | indoor | inspected | 143/143 |  | warped to; in play its facility's or event's script enters it |
| BattleFrontier_BattlePikeRoomNormal | 26.37 | indoor | entered through its facility | 72/72 | flat-blocked 13 | through its facility |
| BattleFrontier_BattlePikeRoomFinal | 26.38 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 40/40) |
| BattleFrontier_BattlePikeRoomWildMons | 26.39 | indoor | inspected | 180/180 | flat-blocked 13 | warped to; in play its facility's or event's script enters it |
| BattleFrontier_RankingHall | 26.40 | indoor | inspected | 795/795 |  |  |
| BattleFrontier_Lounge1 | 26.41 | indoor | inspected | 90/90 |  |  |
| BattleFrontier_ExchangeServiceCorner | 26.42 | indoor | inspected | 165/165 |  |  |
| BattleFrontier_Lounge2 | 26.43 | indoor | inspected | 104/104 |  |  |
| BattleFrontier_Lounge3 | 26.44 | indoor | inspected | 90/90 |  |  |
| BattleFrontier_Lounge4 | 26.45 | indoor | inspected | 90/90 |  |  |
| BattleFrontier_ScottsHouse | 26.46 | indoor | inspected | 48/48 |  |  |
| BattleFrontier_Lounge5 | 26.47 | indoor | inspected | 104/104 |  |  |
| BattleFrontier_Lounge6 | 26.48 | indoor | inspected | 90/90 |  |  |
| BattleFrontier_Lounge7 | 26.49 | indoor | inspected | 90/90 |  |  |
| BattleFrontier_ReceptionGate | 26.50 | indoor | inspected | 126/126 | flat-blocked 5 |  |
| BattleFrontier_Lounge8 | 26.51 | indoor | inspected | 90/90 |  |  |
| BattleFrontier_Lounge9 | 26.52 | indoor | inspected | 90/90 |  |  |
| BattleFrontier_PokemonCenter_1F | 26.53 | indoor | inspected | 126/126 |  |  |
| BattleFrontier_PokemonCenter_2F | 26.54 | indoor | inspected | 140/140 |  |  |
| BattleFrontier_Mart | 26.55 | indoor | inspected | 88/88 |  |  |
| FarawayIsland_Entrance | 26.56 | indoor | inspected | 1564/1564 | flat-blocked 90, water-drop 2 |  |
| FarawayIsland_Interior | 26.57 | indoor | inspected | 754/754 | flat-blocked 43 |  |
| BirthIsland_Exterior | 26.58 | indoor | inspected | 900/900 | flat-blocked 34 |  |
| BirthIsland_Harbor | 26.59 | indoor | inspected | 221/221 | flat-blocked 72 |  |
| TrainerHill_Entrance | 26.60 | indoor | inspected | 323/323 | flat-blocked 98 |  |
| TrainerHill_1F | 26.61 | indoor | inspected | 336/336 | flat-blocked 90 | warped to; in play its facility's or event's script enters it |
| TrainerHill_2F | 26.62 | indoor | inspected | 336/336 | flat-blocked 52 | warped to; in play its facility's or event's script enters it |
| TrainerHill_3F | 26.63 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 336/336) |
| TrainerHill_4F | 26.64 | indoor | inspected | 336/336 | flat-blocked 52 | warped to; in play its facility's or event's script enters it |
| TrainerHill_Roof | 26.65 | indoor | inspected | 400/400 | flat-blocked 331 | warped to; in play its facility's or event's script enters it |
| NavelRock_Exterior | 26.66 | indoor | inspected | 504/504 | flat-blocked 51, walk-step 3 |  |
| NavelRock_Harbor | 26.67 | indoor | inspected | 221/221 | flat-blocked 72 |  |
| NavelRock_Entrance | 26.68 | cave | inspected | 672/672 | fin 14, spike 10, flat-blocked 1 |  |
| NavelRock_B1F | 26.69 | cave | inspected | 253/253 | fin 17 |  |
| NavelRock_Fork | 26.70 | cave | inspected | 2322/2322 | fin 32 |  |
| NavelRock_Up1 | 26.71 | cave | inspected | 72/72 |  |  |
| NavelRock_Up2 | 26.72 | cave | inspected | 72/72 |  |  |
| NavelRock_Up3 | 26.73 | cave | inspected | 72/72 |  |  |
| NavelRock_Up4 | 26.74 | cave | inspected | 72/72 |  |  |
| NavelRock_Top | 26.75 | cave | inspected | 700/700 | spike 4, flat-blocked 417 |  |
| NavelRock_Down01 | 26.76 | cave | inspected | 72/72 |  |  |
| NavelRock_Down02 | 26.77 | cave | inspected | 72/72 |  |  |
| NavelRock_Down03 | 26.78 | cave | inspected | 72/72 |  |  |
| NavelRock_Down04 | 26.79 | cave | inspected | 72/72 |  |  |
| NavelRock_Down05 | 26.80 | cave | inspected | 72/72 |  |  |
| NavelRock_Down06 | 26.81 | cave | inspected | 72/72 |  |  |
| NavelRock_Down07 | 26.82 | cave | inspected | 72/72 |  |  |
| NavelRock_Down08 | 26.83 | cave | inspected | 72/72 |  |  |
| NavelRock_Down09 | 26.84 | cave | inspected | 72/72 |  |  |
| NavelRock_Down10 | 26.85 | cave | inspected | 72/72 |  |  |
| NavelRock_Down11 | 26.86 | cave | inspected | 72/72 |  |  |
| NavelRock_Bottom | 26.87 | cave | inspected | 484/484 | fin 6, spike 1 |  |
| TrainerHill_Elevator | 26.88 | indoor | not inspected | - |  | this run did not get to it (the 2026-10-30 sweep: inspected, 35/35) |
| Route104_Prototype | 27.0 | outdoor | not reachable on PC | - |  | unused: nothing leads there |
| Route104_PrototypePrettyPetalFlowerShop | 27.1 | indoor | not reachable on PC | - |  | unused: nothing leads there |
| Route109_SeashoreHouse | 28.0 | indoor | inspected | 150/150 |  |  |
| Route110_TrickHouseEntrance | 29.0 | indoor | inspected | 96/96 | flat-blocked 4 |  |
| Route110_TrickHouseEnd | 29.1 | indoor | inspected | 96/96 | flat-blocked 20 |  |
| Route110_TrickHouseCorridor | 29.2 | indoor | inspected | 360/360 | flat-blocked 36 |  |
| Route110_TrickHousePuzzle1 | 29.3 | indoor | inspected | 330/330 | flat-blocked 54 |  |
| Route110_TrickHousePuzzle2 | 29.4 | indoor | inspected | 330/330 |  |  |
| Route110_TrickHousePuzzle3 | 29.5 | indoor | inspected | 330/330 | flat-blocked 51 |  |
| Route110_TrickHousePuzzle4 | 29.6 | indoor | inspected | 330/330 |  |  |
| Route110_TrickHousePuzzle5 | 29.7 | indoor | inspected | 330/330 | flat-blocked 143 |  |
| Route110_TrickHousePuzzle6 | 29.8 | indoor | inspected | 330/330 | flat-blocked 14 |  |
| Route110_TrickHousePuzzle7 | 29.9 | indoor | inspected | 330/330 | flat-blocked 37 |  |
| Route110_TrickHousePuzzle8 | 29.10 | indoor | inspected | 330/330 | flat-blocked 31 |  |
| Route110_SeasideCyclingRoadSouthEntrance | 29.11 | indoor | inspected | 90/90 | flat-blocked 44 |  |
| Route110_SeasideCyclingRoadNorthEntrance | 29.12 | indoor | inspected | 90/90 | flat-blocked 44 |  |
| Route113_GlassWorkshop | 30.0 | indoor | inspected | 90/90 | flat-blocked 6 |  |
| Route123_BerryMastersHouse | 31.0 | indoor | inspected | 88/88 |  |  |
| Route119_WeatherInstitute_1F | 32.0 | indoor | inspected | 260/260 | flat-blocked 3 |  |
| Route119_WeatherInstitute_2F | 32.1 | indoor | inspected | 220/220 | flat-blocked 18 |  |
| Route119_House | 32.2 | indoor | inspected | 90/90 |  |  |
| Route124_DivingTreasureHuntersHouse | 33.0 | indoor | inspected | 90/90 | flat-blocked 11 |  |
| BattleColosseum_2P_Frlg | 34.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TradeCenter_Frlg | 34.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| RecordCorner_Frlg | 34.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| BattleColosseum_4P_Frlg | 34.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| UnionRoom_Frlg | 34.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ViridianForest_Frlg | 35.0 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtMoon_1F_Frlg | 35.1 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtMoon_B1F_Frlg | 35.2 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtMoon_B2F_Frlg | 35.3 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_Exterior_Frlg | 35.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_1F_Corridor_Frlg | 35.5 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_2F_Corridor_Frlg | 35.6 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_3F_Corridor_Frlg | 35.7 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_B1F_Corridor_Frlg | 35.8 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_Deck_Frlg | 35.9 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_Kitchen_Frlg | 35.10 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_CaptainsOffice_Frlg | 35.11 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_1F_Room1_Frlg | 35.12 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_1F_Room2_Frlg | 35.13 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_1F_Room3_Frlg | 35.14 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_1F_Room4_Frlg | 35.15 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_1F_Room5_Frlg | 35.16 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_1F_Room7_Frlg | 35.17 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_2F_Room1_Frlg | 35.18 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_2F_Room2_Frlg | 35.19 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_2F_Room3_Frlg | 35.20 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_2F_Room4_Frlg | 35.21 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_2F_Room5_Frlg | 35.22 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_2F_Room6_Frlg | 35.23 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_B1F_Room1_Frlg | 35.24 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_B1F_Room2_Frlg | 35.25 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_B1F_Room3_Frlg | 35.26 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_B1F_Room4_Frlg | 35.27 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_B1F_Room5_Frlg | 35.28 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SSAnne_1F_Room6_Frlg | 35.29 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| UndergroundPath_NorthEntrance_Frlg | 35.30 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| UndergroundPath_NorthSouthTunnel_Frlg | 35.31 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| UndergroundPath_SouthEntrance_Frlg | 35.32 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| UndergroundPath_WestEntrance_Frlg | 35.33 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| UndergroundPath_EastWestTunnel_Frlg | 35.34 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| UndergroundPath_EastEntrance_Frlg | 35.35 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| DiglettsCave_NorthEntrance_Frlg | 35.36 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| DiglettsCave_B1F_Frlg | 35.37 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| DiglettsCave_SouthEntrance_Frlg | 35.38 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| VictoryRoad_1F_Frlg | 35.39 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| VictoryRoad_2F_Frlg | 35.40 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| VictoryRoad_3F_Frlg | 35.41 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| RocketHideout_B1F_Frlg | 35.42 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| RocketHideout_B2F_Frlg | 35.43 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| RocketHideout_B3F_Frlg | 35.44 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| RocketHideout_B4F_Frlg | 35.45 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| RocketHideout_Elevator_Frlg | 35.46 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SilphCo_1F_Frlg | 35.47 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SilphCo_2F_Frlg | 35.48 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SilphCo_3F_Frlg | 35.49 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SilphCo_4F_Frlg | 35.50 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SilphCo_5F_Frlg | 35.51 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SilphCo_6F_Frlg | 35.52 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SilphCo_7F_Frlg | 35.53 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SilphCo_8F_Frlg | 35.54 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SilphCo_9F_Frlg | 35.55 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SilphCo_10F_Frlg | 35.56 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SilphCo_11F_Frlg | 35.57 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SilphCo_Elevator_Frlg | 35.58 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonMansion_1F_Frlg | 35.59 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonMansion_2F_Frlg | 35.60 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonMansion_3F_Frlg | 35.61 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonMansion_B1F_Frlg | 35.62 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SafariZone_Center_Frlg | 35.63 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SafariZone_East_Frlg | 35.64 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SafariZone_North_Frlg | 35.65 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SafariZone_West_Frlg | 35.66 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SafariZone_Center_RestHouse_Frlg | 35.67 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SafariZone_East_RestHouse_Frlg | 35.68 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SafariZone_North_RestHouse_Frlg | 35.69 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SafariZone_West_RestHouse_Frlg | 35.70 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SafariZone_SecretHouse_Frlg | 35.71 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeruleanCave_1F_Frlg | 35.72 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeruleanCave_2F_Frlg | 35.73 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeruleanCave_B1F_Frlg | 35.74 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonLeague_LoreleisRoom_Frlg | 35.75 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonLeague_BrunosRoom_Frlg | 35.76 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonLeague_AgathasRoom_Frlg | 35.77 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonLeague_LancesRoom_Frlg | 35.78 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonLeague_ChampionsRoom_Frlg | 35.79 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonLeague_HallOfFame_Frlg | 35.80 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| RockTunnel_1F_Frlg | 35.81 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| RockTunnel_B1F_Frlg | 35.82 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SeafoamIslands_1F_Frlg | 35.83 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SeafoamIslands_B1F_Frlg | 35.84 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SeafoamIslands_B2F_Frlg | 35.85 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SeafoamIslands_B3F_Frlg | 35.86 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SeafoamIslands_B4F_Frlg | 35.87 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonTower_1F_Frlg | 35.88 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonTower_2F_Frlg | 35.89 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonTower_3F_Frlg | 35.90 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonTower_4F_Frlg | 35.91 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonTower_5F_Frlg | 35.92 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonTower_6F_Frlg | 35.93 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PokemonTower_7F_Frlg | 35.94 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PowerPlant_Frlg | 35.95 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtEmber_RubyPath_B4F_Frlg | 35.96 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtEmber_Exterior_Frlg | 35.97 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtEmber_SummitPath_1F_Frlg | 35.98 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtEmber_SummitPath_2F_Frlg | 35.99 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtEmber_SummitPath_3F_Frlg | 35.100 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtEmber_Summit_Frlg | 35.101 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtEmber_RubyPath_B5F_Frlg | 35.102 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtEmber_RubyPath_1F_Frlg | 35.103 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtEmber_RubyPath_B1F_Frlg | 35.104 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtEmber_RubyPath_B2F_Frlg | 35.105 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtEmber_RubyPath_B3F_Frlg | 35.106 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtEmber_RubyPath_B1F_Stairs_Frlg | 35.107 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| MtEmber_RubyPath_B2F_Stairs_Frlg | 35.108 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ThreeIsland_BerryForest_Frlg | 35.109 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FourIsland_IcefallCave_Entrance_Frlg | 35.110 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FourIsland_IcefallCave_1F_Frlg | 35.111 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FourIsland_IcefallCave_B1F_Frlg | 35.112 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FourIsland_IcefallCave_Back_Frlg | 35.113 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_RocketWarehouse_Frlg | 35.114 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_DottedHole_1F_Frlg | 35.115 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_DottedHole_B1F_Frlg | 35.116 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_DottedHole_B2F_Frlg | 35.117 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_DottedHole_B3F_Frlg | 35.118 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_DottedHole_B4F_Frlg | 35.119 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_DottedHole_SapphireRoom_Frlg | 35.120 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_PatternBush_Frlg | 35.121 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_AlteringCave_Frlg | 35.122 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_Exterior_Frlg | 36.0 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TrainerTower_1F_Frlg | 36.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TrainerTower_2F_Frlg | 36.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TrainerTower_3F_Frlg | 36.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TrainerTower_4F_Frlg | 36.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TrainerTower_5F_Frlg | 36.5 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TrainerTower_6F_Frlg | 36.6 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TrainerTower_7F_Frlg | 36.7 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TrainerTower_8F_Frlg | 36.8 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TrainerTower_Roof_Frlg | 36.9 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TrainerTower_Lobby_Frlg | 36.10 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TrainerTower_Elevator_Frlg | 36.11 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Entrance_Frlg | 36.12 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Room1_Frlg | 36.13 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Room2_Frlg | 36.14 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Room3_Frlg | 36.15 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Room4_Frlg | 36.16 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Room5_Frlg | 36.17 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Room6_Frlg | 36.18 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Room7_Frlg | 36.19 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Room8_Frlg | 36.20 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Room9_Frlg | 36.21 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Room10_Frlg | 36.22 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Room11_Frlg | 36.23 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Room12_Frlg | 36.24 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Room13_Frlg | 36.25 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_LostCave_Room14_Frlg | 36.26 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_TanobyRuins_MoneanChamber_Frlg | 36.27 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_TanobyRuins_LiptooChamber_Frlg | 36.28 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_TanobyRuins_WeepthChamber_Frlg | 36.29 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_TanobyRuins_DilfordChamber_Frlg | 36.30 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_TanobyRuins_ScufibChamber_Frlg | 36.31 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_TanobyRuins_RixyChamber_Frlg | 36.32 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_TanobyRuins_ViapoisChamber_Frlg | 36.33 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ThreeIsland_DunsparceTunnel_Frlg | 36.34 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_SevaultCanyon_TanobyKey_Frlg | 36.35 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_1F_Frlg | 36.36 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_Summit_Frlg | 36.37 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_Base_Frlg | 36.38 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_SummitPath_2F_Frlg | 36.39 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_SummitPath_3F_Frlg | 36.40 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_SummitPath_4F_Frlg | 36.41 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_SummitPath_5F_Frlg | 36.42 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_BasePath_B1F_Frlg | 36.43 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_BasePath_B2F_Frlg | 36.44 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_BasePath_B3F_Frlg | 36.45 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_BasePath_B4F_Frlg | 36.46 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_BasePath_B5F_Frlg | 36.47 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_BasePath_B6F_Frlg | 36.48 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_BasePath_B7F_Frlg | 36.49 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_BasePath_B8F_Frlg | 36.50 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_BasePath_B9F_Frlg | 36.51 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_BasePath_B10F_Frlg | 36.52 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_BasePath_B11F_Frlg | 36.53 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_B1F_Frlg | 36.54 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_Fork_Frlg | 36.55 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| BirthIsland_Exterior_Frlg | 36.56 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| OneIsland_KindleRoad_EmberSpa_Frlg | 36.57 | cave | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| BirthIsland_Harbor_Frlg | 36.58 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| NavelRock_Harbor_Frlg | 36.59 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PalletTown_Frlg | 37.0 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ViridianCity_Frlg | 37.1 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PewterCity_Frlg | 37.2 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeruleanCity_Frlg | 37.3 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| LavenderTown_Frlg | 37.4 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| VermilionCity_Frlg | 37.5 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_Frlg | 37.6 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FuchsiaCity_Frlg | 37.7 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CinnabarIsland_Frlg | 37.8 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| IndigoPlateau_Exterior_Frlg | 37.9 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SaffronCity_Frlg | 37.10 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SaffronCity_Connection_Frlg | 37.11 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| OneIsland_Frlg | 37.12 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TwoIsland_Frlg | 37.13 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ThreeIsland_Frlg | 37.14 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FourIsland_Frlg | 37.15 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_Frlg | 37.16 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_Frlg | 37.17 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_Frlg | 37.18 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route1_Frlg | 37.19 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route2_Frlg | 37.20 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route3_Frlg | 37.21 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route4_Frlg | 37.22 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route5_Frlg | 37.23 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route6_Frlg | 37.24 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route7_Frlg | 37.25 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route8_Frlg | 37.26 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route9_Frlg | 37.27 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route10_Frlg | 37.28 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route11_Frlg | 37.29 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route12_Frlg | 37.30 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route13_Frlg | 37.31 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route14_Frlg | 37.32 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route15_Frlg | 37.33 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route16_Frlg | 37.34 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route17_Frlg | 37.35 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route18_Frlg | 37.36 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route19_Frlg | 37.37 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route20_Frlg | 37.38 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route21_North_Frlg | 37.39 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route21_South_Frlg | 37.40 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route22_Frlg | 37.41 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route23_Frlg | 37.42 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route24_Frlg | 37.43 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route25_Frlg | 37.44 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| OneIsland_KindleRoad_Frlg | 37.45 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| OneIsland_TreasureBeach_Frlg | 37.46 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TwoIsland_CapeBrink_Frlg | 37.47 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ThreeIsland_BondBridge_Frlg | 37.48 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ThreeIsland_Port_Frlg | 37.49 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_ResortGorgeous_Frlg | 37.50 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_WaterLabyrinth_Frlg | 37.51 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_Meadow_Frlg | 37.52 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_MemorialPillar_Frlg | 37.53 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_OutcastIsland_Frlg | 37.54 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_GreenPath_Frlg | 37.55 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_WaterPath_Frlg | 37.56 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_RuinValley_Frlg | 37.57 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_TrainerTower_Frlg | 37.58 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_SevaultCanyon_Entrance_Frlg | 37.59 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_SevaultCanyon_Frlg | 37.60 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_TanobyRuins_Frlg | 37.61 | outdoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PalletTown_PlayersHouse_1F_Frlg | 38.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PalletTown_PlayersHouse_2F_Frlg | 38.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PalletTown_RivalsHouse_Frlg | 38.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PalletTown_ProfessorOaksLab_Frlg | 38.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ViridianCity_House_Frlg | 39.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ViridianCity_Gym_Frlg | 39.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ViridianCity_School_Frlg | 39.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ViridianCity_Mart_Frlg | 39.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ViridianCity_PokemonCenter_1F_Frlg | 39.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ViridianCity_PokemonCenter_2F_Frlg | 39.5 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PewterCity_Museum_1F_Frlg | 40.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PewterCity_Museum_2F_Frlg | 40.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PewterCity_Gym_Frlg | 40.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PewterCity_Mart_Frlg | 40.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PewterCity_House1_Frlg | 40.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PewterCity_PokemonCenter_1F_Frlg | 40.5 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PewterCity_PokemonCenter_2F_Frlg | 40.6 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| PewterCity_House2_Frlg | 40.7 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeruleanCity_House1_Frlg | 41.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeruleanCity_House2_Frlg | 41.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeruleanCity_House3_Frlg | 41.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeruleanCity_PokemonCenter_1F_Frlg | 41.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeruleanCity_PokemonCenter_2F_Frlg | 41.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeruleanCity_Gym_Frlg | 41.5 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeruleanCity_BikeShop_Frlg | 41.6 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeruleanCity_Mart_Frlg | 41.7 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeruleanCity_House4_Frlg | 41.8 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeruleanCity_House5_Frlg | 41.9 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| LavenderTown_PokemonCenter_1F_Frlg | 42.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| LavenderTown_PokemonCenter_2F_Frlg | 42.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| LavenderTown_VolunteerPokemonHouse_Frlg | 42.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| LavenderTown_House1_Frlg | 42.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| LavenderTown_House2_Frlg | 42.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| LavenderTown_Mart_Frlg | 42.5 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| VermilionCity_House1_Frlg | 43.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| VermilionCity_PokemonCenter_1F_Frlg | 43.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| VermilionCity_PokemonCenter_2F_Frlg | 43.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| VermilionCity_PokemonFanClub_Frlg | 43.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| VermilionCity_House2_Frlg | 43.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| VermilionCity_Mart_Frlg | 43.5 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| VermilionCity_Gym_Frlg | 43.6 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| VermilionCity_House3_Frlg | 43.7 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_DepartmentStore_1F_Frlg | 44.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_DepartmentStore_2F_Frlg | 44.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_DepartmentStore_3F_Frlg | 44.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_DepartmentStore_4F_Frlg | 44.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_DepartmentStore_5F_Frlg | 44.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_DepartmentStore_Roof_Frlg | 44.5 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_DepartmentStore_Elevator_Frlg | 44.6 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_Condominiums_1F_Frlg | 44.7 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_Condominiums_2F_Frlg | 44.8 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_Condominiums_3F_Frlg | 44.9 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_Condominiums_Roof_Frlg | 44.10 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_Condominiums_RoofRoom_Frlg | 44.11 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_PokemonCenter_1F_Frlg | 44.12 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_PokemonCenter_2F_Frlg | 44.13 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_GameCorner_Frlg | 44.14 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_GameCorner_PrizeRoom_Frlg | 44.15 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_Gym_Frlg | 44.16 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_Restaurant_Frlg | 44.17 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_House1_Frlg | 44.18 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CeladonCity_Hotel_Frlg | 44.19 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FuchsiaCity_SafariZone_Entrance_Frlg | 45.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FuchsiaCity_Mart_Frlg | 45.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FuchsiaCity_SafariZone_Office_Frlg | 45.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FuchsiaCity_Gym_Frlg | 45.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FuchsiaCity_House1_Frlg | 45.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FuchsiaCity_PokemonCenter_1F_Frlg | 45.5 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FuchsiaCity_PokemonCenter_2F_Frlg | 45.6 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FuchsiaCity_WardensHouse_Frlg | 45.7 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FuchsiaCity_House2_Frlg | 45.8 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FuchsiaCity_House3_Frlg | 45.9 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CinnabarIsland_Gym_Frlg | 46.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CinnabarIsland_PokemonLab_Entrance_Frlg | 46.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CinnabarIsland_PokemonLab_Lounge_Frlg | 46.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CinnabarIsland_PokemonLab_ResearchRoom_Frlg | 46.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CinnabarIsland_PokemonLab_ExperimentRoom_Frlg | 46.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CinnabarIsland_PokemonCenter_1F_Frlg | 46.5 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CinnabarIsland_PokemonCenter_2F_Frlg | 46.6 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| CinnabarIsland_Mart_Frlg | 46.7 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| IndigoPlateau_PokemonCenter_1F_Frlg | 47.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| IndigoPlateau_PokemonCenter_2F_Frlg | 47.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SaffronCity_CopycatsHouse_1F_Frlg | 48.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SaffronCity_CopycatsHouse_2F_Frlg | 48.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SaffronCity_Dojo_Frlg | 48.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SaffronCity_Gym_Frlg | 48.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SaffronCity_House_Frlg | 48.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SaffronCity_Mart_Frlg | 48.5 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SaffronCity_PokemonCenter_1F_Frlg | 48.6 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SaffronCity_PokemonCenter_2F_Frlg | 48.7 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SaffronCity_MrPsychicsHouse_Frlg | 48.8 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SaffronCity_PokemonTrainerFanClub_Frlg | 48.9 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route2_ViridianForest_SouthEntrance_Frlg | 49.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route2_House_Frlg | 49.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route2_EastBuilding_Frlg | 49.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route2_ViridianForest_NorthEntrance_Frlg | 49.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route4_PokemonCenter_1F_Frlg | 50.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route4_PokemonCenter_2F_Frlg | 50.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route5_PokemonDayCare_Frlg | 51.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route5_SouthEntrance_Frlg | 51.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route6_NorthEntrance_Frlg | 52.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route7_EastEntrance_Frlg | 53.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route8_WestEntrance_Frlg | 54.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route10_PokemonCenter_1F_Frlg | 55.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route10_PokemonCenter_2F_Frlg | 55.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route11_EastEntrance_1F_Frlg | 56.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route11_EastEntrance_2F_Frlg | 56.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route12_NorthEntrance_1F_Frlg | 57.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route12_NorthEntrance_2F_Frlg | 57.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route12_FishingHouse_Frlg | 57.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route15_WestEntrance_1F_Frlg | 58.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route15_WestEntrance_2F_Frlg | 58.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route16_House_Frlg | 59.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route16_NorthEntrance_1F_Frlg | 59.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route16_NorthEntrance_2F_Frlg | 59.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route18_EastEntrance_1F_Frlg | 60.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route18_EastEntrance_2F_Frlg | 60.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route22_NorthEntrance_Frlg | 61.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| Route25_SeaCottage_Frlg | 62.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_House_Room1_Frlg | 63.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_House_Room2_Frlg | 63.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_Mart_Frlg | 63.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_PokemonCenter_1F_Frlg | 63.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_PokemonCenter_2F_Frlg | 63.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_Harbor_Frlg | 63.5 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| OneIsland_PokemonCenter_1F_Frlg | 64.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| OneIsland_PokemonCenter_2F_Frlg | 64.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| OneIsland_House1_Frlg | 64.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| OneIsland_House2_Frlg | 64.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| OneIsland_Harbor_Frlg | 64.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TwoIsland_JoyfulGameCorner_Frlg | 65.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TwoIsland_House_Frlg | 65.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TwoIsland_PokemonCenter_1F_Frlg | 65.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TwoIsland_PokemonCenter_2F_Frlg | 65.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TwoIsland_Harbor_Frlg | 65.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ThreeIsland_House1_Frlg | 66.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ThreeIsland_PokemonCenter_1F_Frlg | 66.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ThreeIsland_PokemonCenter_2F_Frlg | 66.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ThreeIsland_Mart_Frlg | 66.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ThreeIsland_House2_Frlg | 66.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ThreeIsland_House3_Frlg | 66.5 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ThreeIsland_House4_Frlg | 66.6 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ThreeIsland_House5_Frlg | 66.7 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FourIsland_PokemonDayCare_Frlg | 67.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FourIsland_PokemonCenter_1F_Frlg | 67.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FourIsland_PokemonCenter_2F_Frlg | 67.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FourIsland_House1_Frlg | 67.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FourIsland_LoreleisHouse_Frlg | 67.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FourIsland_Harbor_Frlg | 67.5 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FourIsland_House2_Frlg | 67.6 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FourIsland_Mart_Frlg | 67.7 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_PokemonCenter_1F_Frlg | 68.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_PokemonCenter_2F_Frlg | 68.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_Harbor_Frlg | 68.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_House1_Frlg | 68.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_House2_Frlg | 68.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_PokemonCenter_1F_Frlg | 69.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_PokemonCenter_2F_Frlg | 69.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_Harbor_Frlg | 69.2 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_House_Frlg | 69.3 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_Mart_Frlg | 69.4 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| ThreeIsland_Harbor_Frlg | 70.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| FiveIsland_ResortGorgeous_House_Frlg | 71.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| TwoIsland_CapeBrink_House_Frlg | 72.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_WaterPath_House1_Frlg | 73.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SixIsland_WaterPath_House2_Frlg | 73.1 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
| SevenIsland_SevaultCanyon_House_Frlg | 74.0 | indoor | not reachable on PC | - |  | FireRed/LeafGreen: not in this build |
