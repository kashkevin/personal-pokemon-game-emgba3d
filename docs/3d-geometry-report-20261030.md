# The 3D world's geometry: the defect list after step 16's work so far (2026-10-30)

The geometry probe's check over every map the game shows (`tools/qa/geometry_check.py check`, engine `5ea03aec`, the
sweep of 2026-10-30 21:42-22:42 with fresh building models; Linux, Mesa's software OpenGL). For each map: the places
the probe stood the player at, the share of the map's cells they reached, and the cells (or places, for holes and
not-3d) each check found. What the checks mean is in `docs/3d-world-geometry-20261029.md` (phase B) and the tool's
own description; a defect counted here is a cell to look at, not always a fault (a blocked plain-grass cell, an
invisible wall, counts as flat-blocked). The probe's pictures and cell dumps are game art and stay out of the
repository (scratchpad `c6/full6/`).


## outdoor: 67 maps, 67 wholly inspected

Totals: fin 937, spike 540, flat-blocked 2582, walk-step 20, seam 64, water-wall 24, water-drop 1428, hole 6

| Map | Status | Cells seen | fin | spike | flat-blocked | card-tree | walk-step | seam | water-wall | water-drop | hole | not-3d |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PetalburgCity | inspected | 900/900 |  |  | 10 |  |  |  |  |  |  |  |
| SlateportCity | inspected | 2400/2400 |  | 1 | 63 |  |  |  |  | 36 |  |  |
| MauvilleCity | inspected | 800/800 |  |  | 47 |  |  | 10 |  | 2 |  |  |
| RustboroCity | inspected | 2400/2400 |  |  | 2 |  |  |  |  | 4 |  |  |
| FortreeCity | inspected | 800/800 |  |  | 90 |  |  |  |  |  | 1 |  |
| LilycoveCity | inspected | 3200/3200 | 62 | 17 | 37 |  |  |  |  | 81 |  |  |
| MossdeepCity | inspected | 3200/3200 | 20 | 25 | 24 |  | 6 |  | 24 | 78 |  |  |
| SootopolisCity | inspected | 3600/3600 | 81 | 66 | 168 |  |  |  |  | 36 |  |  |
| EverGrandeCity | inspected | 3200/3200 | 14 | 21 | 16 |  |  |  |  | 1 |  |  |
| LittlerootTown | inspected | 400/400 |  |  |  |  |  |  |  |  |  |  |
| OldaleTown | inspected | 400/400 |  |  |  |  |  |  |  |  |  |  |
| DewfordTown | inspected | 400/400 | 3 | 3 | 2 |  |  |  |  | 17 |  |  |
| LavaridgeTown | inspected | 400/400 | 21 | 2 | 12 |  |  |  |  |  |  |  |
| FallarborTown | inspected | 400/400 |  |  | 8 |  |  |  |  |  |  |  |
| VerdanturfTown | inspected | 400/400 |  | 2 | 13 |  |  |  |  |  |  |  |
| PacifidlogTown | inspected | 800/800 | 37 |  |  |  |  |  |  | 97 | 1 |  |
| Route101 | inspected | 400/400 |  |  | 1 |  |  |  |  |  |  |  |
| Route102 | inspected | 1000/1000 |  |  | 2 |  |  |  |  |  |  |  |
| Route103 | inspected | 1760/1760 |  |  | 18 |  |  |  |  | 23 |  |  |
| Route104 | inspected | 3200/3200 | 3 |  | 28 |  |  |  |  | 4 |  |  |
| Route105 | inspected | 3200/3200 | 12 | 6 | 1 |  |  |  |  | 69 |  |  |
| Route106 | inspected | 1600/1600 |  | 1 | 10 |  |  |  |  | 51 |  |  |
| Route107 | inspected | 1200/1200 | 4 |  |  |  |  |  |  | 9 |  |  |
| Route108 | inspected | 1200/1200 |  | 1 | 12 |  |  |  |  | 2 |  |  |
| Route109 | inspected | 2520/2520 |  | 1 | 1 |  |  |  |  | 108 | 2 |  |
| Route110 | inspected | 4000/4000 |  | 12 | 174 |  |  |  |  | 208 |  |  |
| Route111 | inspected | 5600/5600 | 22 | 31 | 59 |  |  | 10 |  |  |  |  |
| Route112 | inspected | 2400/2400 | 6 | 23 | 22 |  |  |  |  |  |  |  |
| Route113 | inspected | 2000/2000 | 3 | 8 | 27 |  |  |  |  |  |  |  |
| Route114 | inspected | 3200/3200 |  | 6 | 59 |  |  |  |  | 123 |  |  |
| Route115 | inspected | 3200/3200 | 23 | 14 | 19 |  |  |  |  | 52 |  |  |
| Route116 | inspected | 2000/2000 |  | 1 | 9 |  |  |  |  |  |  |  |
| Route117 | inspected | 1200/1200 |  | 4 | 15 |  |  |  |  |  |  |  |
| Route118 | inspected | 1600/1600 |  | 4 | 40 |  |  |  |  | 39 |  |  |
| Route119 | inspected | 5600/5600 | 70 | 30 | 326 |  | 2 |  |  | 77 |  |  |
| Route120 | inspected | 4000/4000 | 73 | 21 | 142 |  |  |  |  |  |  |  |
| Route121 | inspected | 1600/1600 | 13 | 5 | 13 |  |  |  |  | 4 |  |  |
| Route122 | inspected | 1600/1600 |  |  |  |  |  |  |  | 10 |  |  |
| Route123 | inspected | 2800/2800 |  | 2 | 34 |  |  |  |  | 34 |  |  |
| Route124 | inspected | 6400/6400 | 21 | 19 | 8 |  |  |  |  | 21 | 1 |  |
| Route125 | inspected | 3200/3200 | 8 | 15 | 10 |  |  |  |  | 8 |  |  |
| Route126 | inspected | 6400/6400 | 6 | 7 | 33 |  |  |  |  | 2 |  |  |
| Route127 | inspected | 6400/6400 |  | 33 | 5 |  |  |  |  |  |  |  |
| Route128 | inspected | 4800/4800 | 9 | 14 | 4 |  |  |  |  | 1 |  |  |
| Route129 | inspected | 3200/3200 |  | 3 | 3 |  |  |  |  |  |  |  |
| Route130 | inspected | 3200/3200 | 7 | 7 | 4 |  |  |  |  |  |  |  |
| Route131 | inspected | 2400/2400 | 7 | 2 | 2 |  |  |  |  | 10 | 1 |  |
| Route132 | inspected | 3200/3200 | 11 | 4 |  |  |  |  |  | 17 |  |  |
| Route133 | inspected | 3200/3200 |  |  |  |  |  |  |  |  |  |  |
| Route134 | inspected | 3200/3200 | 28 | 2 |  |  |  |  |  | 12 |  |  |
| PetalburgWoods | inspected | 2112/2112 |  |  | 38 |  |  |  |  |  |  |  |
| MtChimney | inspected | 1880/1880 | 19 | 9 | 76 |  |  |  |  |  |  |  |
| JaggedPass | inspected | 1380/1380 | 13 | 16 | 12 |  |  |  |  |  |  |  |
| MtPyre_Exterior | inspected | 1938/1938 | 32 | 6 | 20 |  |  |  |  |  |  |  |
| MtPyre_Summit | inspected | 1850/1850 | 65 | 19 | 31 |  |  |  |  |  |  |  |
| SkyPillar_Outside | inspected | 644/644 | 5 |  | 59 |  |  |  |  | 4 |  |  |
| SkyPillar_Top | inspected | 648/648 |  |  | 211 |  |  |  |  |  |  |  |
| SafariZone_Northwest | inspected | 1600/1600 | 18 | 7 | 3 |  |  | 5 |  | 5 |  |  |
| SafariZone_North | inspected | 1600/1600 | 43 | 21 | 10 |  | 2 | 2 |  |  |  |  |
| SafariZone_Southwest | inspected | 1600/1600 |  | 3 | 2 |  |  | 5 |  |  |  |  |
| SafariZone_South | inspected | 1600/1600 | 42 |  | 10 |  |  | 2 |  |  |  |  |
| BattleFrontier_OutsideWest | inspected | 4032/4032 | 32 | 13 | 225 |  |  | 15 |  | 65 |  |  |
| SouthernIsland_Exterior | inspected | 990/990 |  |  | 21 |  |  |  |  | 3 |  |  |
| SouthernIsland_Interior | inspected | 648/648 |  |  | 10 |  |  |  |  |  |  |  |
| SafariZone_Northeast | inspected | 1600/1600 | 90 | 18 | 1 |  |  |  |  |  |  |  |
| SafariZone_Southeast | inspected | 1600/1600 |  | 1 | 71 |  |  |  |  | 43 |  |  |
| BattleFrontier_OutsideEast | inspected | 5184/5184 | 14 | 14 | 209 |  | 10 | 15 |  | 72 |  |  |

## cave: 99 maps, 99 wholly inspected

Totals: fin 789, spike 372, flat-blocked 3127, walk-step 49, water-drop 69, hole 1

| Map | Status | Cells seen | fin | spike | flat-blocked | card-tree | walk-step | seam | water-wall | water-drop | hole | not-3d |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MeteorFalls_1F_1R | inspected | 1260/1260 | 31 | 31 | 3 |  | 2 |  |  | 11 |  |  |
| MeteorFalls_1F_2R | inspected | 960/960 | 13 | 7 | 4 |  |  |  |  |  |  |  |
| MeteorFalls_B1F_1R | inspected | 1102/1102 | 4 | 8 | 3 |  | 3 |  |  | 9 |  |  |
| MeteorFalls_B1F_2R | inspected | 198/198 |  |  | 1 |  |  |  |  |  |  |  |
| RusturfTunnel | inspected | 864/864 | 52 | 30 | 3 |  |  |  |  |  |  |  |
| DesertRuins | inspected | 561/561 | 19 | 4 | 8 |  |  |  |  |  |  |  |
| GraniteCave_1F | inspected | 630/630 | 14 | 4 | 2 |  |  |  |  |  |  |  |
| GraniteCave_B1F | inspected | 832/832 | 45 | 2 |  |  |  |  |  |  |  |  |
| GraniteCave_B2F | inspected | 832/832 | 32 | 3 |  |  |  |  |  |  |  |  |
| GraniteCave_StevensRoom | inspected | 210/210 |  |  |  |  |  |  |  |  |  |  |
| FieryPath | inspected | 1330/1330 |  | 5 | 11 |  |  |  |  |  |  |  |
| SeafloorCavern_Entrance | inspected | 400/400 |  |  |  |  |  |  |  |  |  |  |
| SeafloorCavern_Room1 | inspected | 420/420 | 6 | 3 | 2 |  |  |  |  |  |  |  |
| SeafloorCavern_Room2 | inspected | 216/216 |  | 1 | 2 |  |  |  |  |  |  |  |
| SeafloorCavern_Room3 | inspected | 272/272 |  |  | 2 |  |  |  |  |  |  |  |
| SeafloorCavern_Room4 | inspected | 342/342 |  |  | 1 |  |  |  |  |  |  |  |
| SeafloorCavern_Room5 | inspected | 400/400 | 3 |  | 2 |  |  |  |  |  |  |  |
| SeafloorCavern_Room6 | inspected | 552/552 |  |  | 206 |  |  |  |  |  |  |  |
| SeafloorCavern_Room7 | inspected | 575/575 |  |  | 180 |  |  |  |  |  |  |  |
| SeafloorCavern_Room8 | inspected | 154/154 |  |  | 1 |  |  |  |  |  |  |  |
| SeafloorCavern_Room9 | inspected | 1242/1242 |  | 14 | 4 |  |  |  |  |  |  |  |
| CaveOfOrigin_Entrance | inspected | 494/494 |  | 2 | 1 |  |  |  |  |  |  |  |
| CaveOfOrigin_1F | inspected | 529/529 |  |  | 1 |  |  |  |  |  |  |  |
| CaveOfOrigin_B1F | inspected | 361/361 | 6 | 8 |  |  |  |  |  |  |  |  |
| VictoryRoad_1F | inspected | 2070/2070 | 45 | 31 | 2 |  | 7 |  |  |  |  |  |
| VictoryRoad_B1F | inspected | 1426/1426 | 33 | 13 |  |  | 4 |  |  |  |  |  |
| VictoryRoad_B2F | inspected | 1426/1426 | 30 | 13 |  |  | 5 |  |  |  |  |  |
| ShoalCave_LowTideEntranceRoom | inspected | 1225/1225 | 30 | 11 |  |  |  |  |  |  |  |  |
| ShoalCave_LowTideInnerRoom | inspected | 1748/1748 | 22 | 24 | 9 |  | 6 |  |  |  |  |  |
| ShoalCave_LowTideStairsRoom | inspected | 315/315 | 10 | 4 | 1 |  |  |  |  |  |  |  |
| ShoalCave_LowTideLowerRoom | inspected | 434/434 |  |  | 3 |  |  |  |  |  |  |  |
| ShoalCave_HighTideEntranceRoom | inspected | 1225/1225 | 29 | 4 | 2 |  | 2 |  |  | 11 |  |  |
| ShoalCave_HighTideInnerRoom | inspected | 1748/1748 | 5 | 14 | 2 |  | 9 |  |  | 38 |  |  |
| NewMauville_Entrance | inspected | 81/81 |  | 2 | 6 |  |  |  |  |  | 1 |  |
| NewMauville_Inside | inspected | 1681/1681 |  |  | 209 |  |  |  |  |  |  |  |
| AbandonedShip_Deck | inspected | 483/483 |  |  | 308 |  |  |  |  |  |  |  |
| AbandonedShip_Corridors_1F | inspected | 216/216 |  |  | 15 |  |  |  |  |  |  |  |
| AbandonedShip_Rooms_1F | inspected | 306/306 |  |  | 59 |  |  |  |  |  |  |  |
| AbandonedShip_Corridors_B1F | inspected | 130/130 |  |  | 29 |  |  |  |  |  |  |  |
| AbandonedShip_Rooms_B1F | inspected | 216/216 |  |  | 19 |  |  |  |  |  |  |  |
| AbandonedShip_Rooms2_B1F | inspected | 144/144 |  |  | 79 |  |  |  |  |  |  |  |
| AbandonedShip_Room_B1F | inspected | 72/72 |  |  | 31 |  |  |  |  |  |  |  |
| AbandonedShip_Rooms2_1F | inspected | 153/153 |  |  | 34 |  |  |  |  |  |  |  |
| AbandonedShip_CaptainsOffice | inspected | 63/63 |  |  | 26 |  |  |  |  |  |  |  |
| AbandonedShip_HiddenFloorCorridors | inspected | 143/143 |  |  | 16 |  |  |  |  |  |  |  |
| AbandonedShip_HiddenFloorRooms | inspected | 660/660 |  |  | 286 |  |  |  |  |  |  |  |
| IslandCave | inspected | 561/561 | 19 | 4 | 8 |  |  |  |  |  |  |  |
| AncientTomb | inspected | 561/561 | 19 | 4 | 8 |  |  |  |  |  |  |  |
| SealedChamber_OuterRoom | inspected | 483/483 | 3 |  | 6 |  |  |  |  |  |  |  |
| SealedChamber_InnerRoom | inspected | 483/483 |  |  | 1 |  |  |  |  |  |  |  |
| ScorchedSlab | inspected | 300/300 |  |  | 1 |  |  |  |  |  |  |  |
| SkyPillar_Entrance | inspected | 324/324 |  | 4 | 2 |  |  |  |  |  |  |  |
| SkyPillar_1F | inspected | 196/196 |  |  | 63 |  |  |  |  |  |  |  |
| SkyPillar_2F | inspected | 196/196 |  |  | 62 |  |  |  |  |  |  |  |
| SkyPillar_3F | inspected | 196/196 |  |  | 61 |  |  |  |  |  |  |  |
| SkyPillar_4F | inspected | 196/196 |  |  | 61 |  |  |  |  |  |  |  |
| ShoalCave_LowTideIceRoom | inspected | 600/600 | 3 | 24 | 3 |  | 1 |  |  |  |  |  |
| SkyPillar_5F | inspected | 196/196 |  |  | 90 |  |  |  |  |  |  |  |
| MagmaHideout_1F | inspected | 1406/1406 | 37 | 3 | 21 |  |  |  |  |  |  |  |
| MagmaHideout_2F_1R | inspected | 1287/1287 | 34 | 7 | 26 |  |  |  |  |  |  |  |
| MagmaHideout_2F_2R | inspected | 1372/1372 | 3 | 18 | 60 |  |  |  |  |  |  |  |
| MagmaHideout_3F_1R | inspected | 672/672 | 19 | 4 | 99 |  |  |  |  |  |  |  |
| MagmaHideout_3F_2R | inspected | 408/408 |  | 1 | 63 |  |  |  |  |  |  |  |
| MagmaHideout_4F | inspected | 1652/1652 | 3 | 7 | 168 |  |  |  |  |  |  |  |
| MagmaHideout_3F_3R | inspected | 792/792 | 41 | 10 | 26 |  |  |  |  |  |  |  |
| MagmaHideout_2F_3R | inspected | 1140/1140 |  |  |  |  |  |  |  |  |  |  |
| MirageTower_1F | inspected | 357/357 |  |  | 71 |  |  |  |  |  |  |  |
| MirageTower_2F | inspected | 357/357 |  |  | 68 |  |  |  |  |  |  |  |
| MirageTower_3F | inspected | 357/357 |  |  | 63 |  |  |  |  |  |  |  |
| MirageTower_4F | inspected | 130/130 |  |  | 27 |  | 1 |  |  |  |  |  |
| DesertUnderpass | inspected | 3197/3197 |  |  | 1 |  |  |  |  |  |  |  |
| ArtisanCave_B1F | inspected | 2484/2484 | 76 | 15 | 1 |  | 7 |  |  |  |  |  |
| ArtisanCave_1F | inspected | 462/462 |  |  | 1 |  |  |  |  |  |  |  |
| MarineCave_Entrance | inspected | 400/400 |  |  |  |  |  |  |  |  |  |  |
| MarineCave_End | inspected | 810/810 | 26 | 1 | 4 |  |  |  |  |  |  |  |
| TerraCave_Entrance | inspected | 400/400 |  |  | 1 |  |  |  |  |  |  |  |
| TerraCave_End | inspected | 810/810 | 5 | 3 | 52 |  |  |  |  |  |  |  |
| AlteringCave | inspected | 768/768 | 3 | 11 | 1 |  | 2 |  |  |  |  |  |
| MeteorFalls_StevensCave | inspected | 960/960 |  | 3 | 17 |  |  |  |  |  |  |  |
| NavelRock_Entrance | inspected | 672/672 | 14 | 10 | 1 |  |  |  |  |  |  |  |
| NavelRock_B1F | inspected | 253/253 | 17 |  |  |  |  |  |  |  |  |  |
| NavelRock_Fork | inspected | 2322/2322 | 32 |  |  |  |  |  |  |  |  |  |
| NavelRock_Up1 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Up2 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Up3 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Up4 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Top | inspected | 700/700 |  | 4 | 417 |  |  |  |  |  |  |  |
| NavelRock_Down01 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Down02 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Down03 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Down04 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Down05 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Down06 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Down07 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Down08 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Down09 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Down10 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Down11 | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| NavelRock_Bottom | inspected | 484/484 | 6 | 1 |  |  |  |  |  |  |  |  |

## underwater: 14 maps, 14 wholly inspected

Totals: fin 31, spike 7, flat-blocked 61

| Map | Status | Cells seen | fin | spike | flat-blocked | card-tree | walk-step | seam | water-wall | water-drop | hole | not-3d |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Underwater_Route124 | inspected | 6400/6400 |  |  |  |  |  |  |  |  |  |  |
| Underwater_Route126 | inspected | 6400/6400 | 5 |  |  |  |  |  |  |  |  |  |
| Underwater_Route127 | inspected | 6400/6400 |  |  |  |  |  |  |  |  |  |  |
| Underwater_Route128 | inspected | 4800/4800 |  |  |  |  |  |  |  |  |  |  |
| Underwater_Route129 | inspected | 3200/3200 |  |  |  |  |  |  |  |  |  |  |
| Underwater_Route105 | inspected | 3200/3200 |  |  |  |  |  |  |  |  |  |  |
| Underwater_Route125 | inspected | 3200/3200 |  |  |  |  |  |  |  |  |  |  |
| Underwater_SootopolisCity | inspected | 200/200 | 8 |  | 1 |  |  |  |  |  |  |  |
| Underwater_SeafloorCavern | inspected | 126/126 | 3 | 2 | 1 |  |  |  |  |  |  |  |
| AbandonedShip_Underwater1 | inspected | 64/64 |  |  | 16 |  |  |  |  |  |  |  |
| AbandonedShip_Underwater2 | inspected | 147/147 |  |  | 41 |  |  |  |  |  |  |  |
| Underwater_Route134 | inspected | 180/180 | 3 | 2 | 1 |  |  |  |  |  |  |  |
| Underwater_SealedChamber | inspected | 1056/1056 | 12 | 1 |  |  |  |  |  |  |  |  |
| Underwater_MarineCave | inspected | 200/200 |  | 2 | 1 |  |  |  |  |  |  |  |

## indoor: 299 maps, 297 wholly inspected

Totals: flat-blocked 8476, walk-step 3, water-drop 2, hole 2, not-3d 2

| Map | Status | Cells seen | fin | spike | flat-blocked | card-tree | walk-step | seam | water-wall | water-drop | hole | not-3d |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| LittlerootTown_BrendansHouse_1F | inspected | 99/99 |  |  |  |  |  |  |  |  |  |  |
| LittlerootTown_BrendansHouse_2F | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| LittlerootTown_MaysHouse_1F | inspected | 99/99 |  |  |  |  |  |  |  |  |  |  |
| LittlerootTown_MaysHouse_2F | inspected | 72/72 |  |  |  |  |  |  |  |  |  |  |
| LittlerootTown_ProfessorBirchsLab | inspected | 169/169 |  |  |  |  |  |  |  |  |  |  |
| OldaleTown_House1 | inspected | 90/90 |  |  |  |  |  |  |  |  |  |  |
| OldaleTown_House2 | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| OldaleTown_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| OldaleTown_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| OldaleTown_Mart | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| DewfordTown_House1 | inspected | 80/80 |  |  | 4 |  |  |  |  |  |  |  |
| DewfordTown_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| DewfordTown_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| DewfordTown_Gym | inspected | 504/504 |  |  | 72 |  |  |  |  |  |  |  |
| DewfordTown_Hall | inspected | 153/153 |  |  | 17 |  |  |  |  |  |  |  |
| DewfordTown_House2 | inspected | 90/90 |  |  | 6 |  |  |  |  |  |  |  |
| LavaridgeTown_HerbShop | inspected | 88/88 |  |  | 33 |  |  |  |  |  |  |  |
| LavaridgeTown_Gym_1F | inspected | 323/323 |  |  | 21 |  |  |  |  |  |  |  |
| LavaridgeTown_Gym_B1F | inspected | 323/323 |  |  | 53 |  |  |  |  |  |  |  |
| LavaridgeTown_House | inspected | 80/80 |  |  | 4 |  |  |  |  |  |  |  |
| LavaridgeTown_Mart | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| LavaridgeTown_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| LavaridgeTown_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| FallarborTown_Mart | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| FallarborTown_BattleTentLobby | inspected | 130/130 |  |  | 60 |  |  |  |  |  |  |  |
| FallarborTown_BattleTentCorridor | inspected | 40/40 |  |  | 9 |  |  |  |  |  |  |  |
| FallarborTown_BattleTentBattleRoom | inspected | 90/90 |  |  | 7 |  |  |  |  |  |  |  |
| FallarborTown_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| FallarborTown_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| FallarborTown_CozmosHouse | inspected | 90/90 |  |  |  |  |  |  |  |  |  |  |
| FallarborTown_MoveRelearnersHouse | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| VerdanturfTown_BattleTentLobby | inspected | 130/130 |  |  | 60 |  |  |  |  |  |  |  |
| VerdanturfTown_BattleTentCorridor | inspected | 40/40 |  |  | 9 |  |  |  |  |  |  |  |
| VerdanturfTown_BattleTentBattleRoom | inspected | 117/117 |  |  |  |  |  |  |  |  |  |  |
| VerdanturfTown_Mart | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| VerdanturfTown_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| VerdanturfTown_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| VerdanturfTown_WandasHouse | inspected | 136/136 |  |  | 5 |  |  |  |  |  |  |  |
| VerdanturfTown_FriendshipRatersHouse | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| VerdanturfTown_House | inspected | 90/90 |  |  |  |  |  |  |  |  |  |  |
| PacifidlogTown_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| PacifidlogTown_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| PacifidlogTown_House1 | inspected | 90/90 |  |  | 5 |  |  |  |  |  |  |  |
| PacifidlogTown_House2 | inspected | 90/90 |  |  | 4 |  |  |  |  |  |  |  |
| PacifidlogTown_House3 | inspected | 90/90 |  |  | 5 |  |  |  |  |  |  |  |
| PacifidlogTown_House4 | inspected | 90/90 |  |  | 4 |  |  |  |  |  |  |  |
| PacifidlogTown_House5 | inspected | 90/90 |  |  | 5 |  |  |  |  |  |  |  |
| PetalburgCity_WallysHouse | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| PetalburgCity_Gym | inspected | 1008/1008 |  |  | 4 |  |  |  |  |  |  |  |
| PetalburgCity_House1 | inspected | 90/90 |  |  |  |  |  |  |  |  |  |  |
| PetalburgCity_House2 | inspected | 80/80 |  |  |  |  |  |  |  |  |  |  |
| PetalburgCity_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| PetalburgCity_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| PetalburgCity_Mart | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| SlateportCity_SternsShipyard_1F | inspected | 315/315 |  |  | 121 |  |  |  |  |  |  |  |
| SlateportCity_SternsShipyard_2F | inspected | 255/255 |  |  | 115 |  |  |  |  |  |  |  |
| SlateportCity_BattleTentLobby | inspected | 130/130 |  |  | 60 |  |  |  |  |  |  |  |
| SlateportCity_BattleTentCorridor | inspected | 40/40 |  |  | 9 |  |  |  |  |  |  |  |
| SlateportCity_BattleTentBattleRoom | inspected | 90/90 |  |  | 7 |  |  |  |  |  |  |  |
| SlateportCity_NameRatersHouse | inspected | 80/80 |  |  |  |  |  |  |  |  |  |  |
| SlateportCity_PokemonFanClub | inspected | 154/154 |  |  | 46 |  |  |  |  |  |  |  |
| SlateportCity_OceanicMuseum_1F | inspected | 180/180 |  |  | 60 |  |  |  |  |  |  |  |
| SlateportCity_OceanicMuseum_2F | inspected | 180/180 |  |  |  |  |  |  |  |  |  |  |
| SlateportCity_Harbor | inspected | 360/360 |  |  | 97 |  |  |  |  |  |  |  |
| SlateportCity_House | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| SlateportCity_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| SlateportCity_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| SlateportCity_Mart | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| MauvilleCity_Gym | inspected | 210/210 |  |  | 22 |  |  |  |  |  |  |  |
| MauvilleCity_BikeShop | inspected | 108/108 |  |  | 28 |  |  |  |  |  |  |  |
| MauvilleCity_House1 | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| MauvilleCity_GameCorner | inspected | 242/242 |  |  |  |  |  |  |  |  |  |  |
| MauvilleCity_House2 | inspected | 90/90 |  |  |  |  |  |  |  |  |  |  |
| MauvilleCity_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| MauvilleCity_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| MauvilleCity_Mart | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| RustboroCity_DevonCorp_1F | inspected | 171/171 |  |  | 55 |  |  |  |  |  |  |  |
| RustboroCity_DevonCorp_2F | inspected | 171/171 |  |  | 18 |  |  |  |  |  |  |  |
| RustboroCity_DevonCorp_3F | inspected | 171/171 |  |  | 23 |  |  |  |  |  |  |  |
| RustboroCity_Gym | inspected | 220/220 |  |  | 4 |  |  |  |  |  |  |  |
| RustboroCity_PokemonSchool | inspected | 132/132 |  |  | 14 |  |  |  |  |  |  |  |
| RustboroCity_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| RustboroCity_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| RustboroCity_Mart | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| RustboroCity_Flat1_1F | inspected | 112/112 |  |  | 4 |  |  |  |  |  |  |  |
| RustboroCity_Flat1_2F | inspected | 112/112 |  |  | 8 |  |  |  |  |  |  |  |
| RustboroCity_House1 | inspected | 104/104 |  |  | 6 |  |  |  |  |  |  |  |
| RustboroCity_CuttersHouse | inspected | 99/99 |  |  | 4 |  |  |  |  |  |  |  |
| RustboroCity_House2 | inspected | 108/108 |  |  | 4 |  |  |  |  |  |  |  |
| RustboroCity_Flat2_1F | inspected | 126/126 |  |  | 4 |  |  |  |  |  |  |  |
| RustboroCity_Flat2_2F | inspected | 126/126 |  |  | 2 |  |  |  |  |  |  |  |
| RustboroCity_Flat2_3F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| RustboroCity_House3 | inspected | 108/108 |  |  | 4 |  |  |  |  |  |  |  |
| FortreeCity_House1 | inspected | 48/48 |  |  | 4 |  |  |  |  |  |  |  |
| FortreeCity_Gym | inspected | 500/500 |  |  | 111 |  |  |  |  |  |  |  |
| FortreeCity_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| FortreeCity_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| FortreeCity_Mart | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| FortreeCity_House2 | inspected | 48/48 |  |  | 6 |  |  |  |  |  |  |  |
| FortreeCity_House3 | inspected | 48/48 |  |  | 4 |  |  |  |  |  |  |  |
| FortreeCity_House4 | inspected | 48/48 |  |  | 6 |  |  |  |  |  |  |  |
| FortreeCity_House5 | inspected | 48/48 |  |  | 4 |  |  |  |  |  |  |  |
| FortreeCity_DecorationShop | inspected | 48/48 |  |  | 14 |  |  |  |  |  |  |  |
| LilycoveCity_CoveLilyMotel_1F | inspected | 108/108 |  |  | 19 |  |  |  |  |  |  |  |
| LilycoveCity_CoveLilyMotel_2F | inspected | 108/108 |  |  | 8 |  |  |  |  |  |  |  |
| LilycoveCity_LilycoveMuseum_1F | inspected | 294/294 |  |  | 99 |  |  |  |  |  |  |  |
| LilycoveCity_LilycoveMuseum_2F | inspected | 286/286 |  |  | 93 |  |  |  |  |  |  |  |
| LilycoveCity_ContestLobby | inspected | 372/372 |  |  | 74 |  |  |  |  |  |  |  |
| LilycoveCity_ContestHall | inspected | 1683/1683 |  |  | 444 |  |  |  |  |  |  |  |
| LilycoveCity_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| LilycoveCity_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| LilycoveCity_PokemonTrainerFanClub | inspected | 168/168 |  |  | 31 |  |  |  |  |  |  |  |
| LilycoveCity_Harbor | inspected | 360/360 |  |  | 97 |  |  |  |  |  |  |  |
| LilycoveCity_MoveDeletersHouse | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| LilycoveCity_House1 | inspected | 90/90 |  |  |  |  |  |  |  |  |  |  |
| LilycoveCity_House2 | inspected | 64/64 |  |  | 4 |  |  |  |  |  |  |  |
| LilycoveCity_House3 | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| LilycoveCity_House4 | inspected | 90/90 |  |  |  |  |  |  |  |  |  |  |
| LilycoveCity_DepartmentStore_1F | inspected | 144/144 |  |  | 50 |  |  |  |  |  |  |  |
| LilycoveCity_DepartmentStore_2F | inspected | 144/144 |  |  | 46 |  |  |  |  |  |  |  |
| LilycoveCity_DepartmentStore_3F | inspected | 144/144 |  |  | 42 |  |  |  |  |  |  |  |
| LilycoveCity_DepartmentStore_4F | inspected | 144/144 |  |  | 55 |  |  |  |  |  |  |  |
| LilycoveCity_DepartmentStore_5F | inspected | 144/144 |  |  | 57 |  |  |  |  |  |  |  |
| LilycoveCity_DepartmentStoreRooftop | inspected | 216/216 |  |  | 102 |  |  |  |  |  |  |  |
| LilycoveCity_DepartmentStoreElevator | inspected | 30/30 |  |  | 15 |  |  |  |  |  |  |  |
| MossdeepCity_Gym | inspected | 936/936 |  |  | 1 |  |  |  |  |  |  |  |
| MossdeepCity_House1 | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| MossdeepCity_House2 | inspected | 90/90 |  |  |  |  |  |  |  |  |  |  |
| MossdeepCity_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| MossdeepCity_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| MossdeepCity_Mart | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| MossdeepCity_House3 | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| MossdeepCity_StevensHouse | inspected | 88/88 |  |  | 8 |  |  |  |  |  |  |  |
| MossdeepCity_House4 | inspected | 80/80 |  |  |  |  |  |  |  |  |  |  |
| MossdeepCity_SpaceCenter_1F | inspected | 160/160 |  |  | 9 |  |  |  |  |  |  |  |
| MossdeepCity_SpaceCenter_2F | inspected | 160/160 |  |  | 19 |  |  |  |  |  |  |  |
| MossdeepCity_GameCorner_1F | inspected | 120/120 |  |  | 2 |  |  |  |  |  |  |  |
| MossdeepCity_GameCorner_B1F | inspected | 108/108 |  |  | 21 |  |  |  |  |  |  |  |
| SootopolisCity_Gym_1F | inspected | 442/442 |  |  | 98 |  |  |  |  |  |  |  |
| SootopolisCity_Gym_B1F | inspected | 442/442 |  |  | 190 |  |  |  |  |  |  |  |
| SootopolisCity_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| SootopolisCity_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| SootopolisCity_Mart | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| SootopolisCity_House1 | inspected | 56/56 |  |  | 4 |  |  |  |  |  |  |  |
| SootopolisCity_House2 | inspected | 56/56 |  |  | 4 |  |  |  |  |  |  |  |
| SootopolisCity_House3 | inspected | 56/56 |  |  | 2 |  |  |  |  |  |  |  |
| SootopolisCity_House4 | inspected | 56/56 |  |  | 4 |  |  |  |  |  |  |  |
| SootopolisCity_House5 | inspected | 56/56 |  |  | 4 |  |  |  |  |  |  |  |
| SootopolisCity_House6 | inspected | 56/56 |  |  | 2 |  |  |  |  |  |  |  |
| SootopolisCity_House7 | inspected | 56/56 |  |  | 4 |  |  |  |  |  |  |  |
| SootopolisCity_LotadAndSeedotHouse | inspected | 56/56 |  |  | 4 |  |  |  |  |  |  |  |
| SootopolisCity_MysteryEventsHouse_1F | inspected | 88/88 |  |  | 18 |  |  |  |  |  |  |  |
| SootopolisCity_MysteryEventsHouse_B1F | inspected | 108/108 |  |  | 2 |  |  |  |  |  |  |  |
| EverGrandeCity_SidneysRoom | inspected | 182/182 |  |  | 20 |  |  |  |  |  |  |  |
| EverGrandeCity_PhoebesRoom | inspected | 182/182 |  |  | 20 |  |  |  |  |  |  |  |
| EverGrandeCity_GlaciasRoom | inspected | 182/182 |  |  | 20 |  |  |  |  |  |  |  |
| EverGrandeCity_DrakesRoom | inspected | 182/182 |  |  | 20 |  |  |  |  |  |  |  |
| EverGrandeCity_ChampionsRoom | inspected | 169/169 |  |  | 16 |  |  |  |  |  |  |  |
| EverGrandeCity_Hall1 | inspected | 143/143 |  |  | 66 |  |  |  |  |  |  |  |
| EverGrandeCity_Hall2 | inspected | 143/143 |  |  | 66 |  |  |  |  |  |  |  |
| EverGrandeCity_Hall3 | inspected | 143/143 |  |  | 66 |  |  |  |  |  |  |  |
| EverGrandeCity_Hall4 | inspected | 374/374 |  |  | 222 |  |  |  |  |  |  |  |
| EverGrandeCity_Hall5 | inspected | 143/143 |  |  | 66 |  |  |  |  |  |  |  |
| EverGrandeCity_PokemonLeague_1F | inspected | 228/228 |  |  | 40 |  |  |  |  |  |  |  |
| EverGrandeCity_HallOfFame | inspected | 255/255 |  |  | 34 |  |  |  |  |  |  |  |
| EverGrandeCity_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| EverGrandeCity_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| EverGrandeCity_PokemonLeague_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| Route104_MrBrineysHouse | inspected | 108/108 |  |  |  |  |  |  |  |  |  |  |
| Route104_PrettyPetalFlowerShop | inspected | 135/135 |  |  | 4 |  |  |  |  |  |  |  |
| Route111_WinstrateFamilysHouse | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| Route111_OldLadysRestStop | inspected | 80/80 |  |  | 4 |  |  |  |  |  |  |  |
| Route112_CableCarStation | inspected | 156/156 |  |  | 72 |  |  |  |  |  |  |  |
| MtChimney_CableCarStation | inspected | 156/156 |  |  | 72 |  |  |  |  |  |  |  |
| Route114_FossilManiacsHouse | inspected | 80/80 |  |  | 4 |  |  |  |  |  |  |  |
| Route114_FossilManiacsTunnel | inspected | 338/338 |  |  | 192 |  |  |  |  |  |  |  |
| Route114_LanettesHouse | inspected | 88/88 |  |  | 11 |  |  |  |  |  |  |  |
| Route116_TunnelersRestHouse | inspected | 90/90 |  |  | 8 |  |  |  |  |  |  |  |
| Route117_PokemonDayCare | inspected | 108/108 |  |  | 44 |  |  |  |  |  |  |  |
| Route121_SafariZoneEntrance | inspected | 252/252 |  |  | 59 |  |  |  |  |  |  |  |
| MtPyre_1F | inspected | 418/418 |  |  |  |  |  |  |  |  |  |  |
| MtPyre_2F | inspected | 169/169 |  |  | 5 |  |  |  |  |  |  |  |
| MtPyre_3F | inspected | 169/169 |  |  | 5 |  |  |  |  |  |  |  |
| MtPyre_4F | inspected | 169/169 |  |  | 7 |  |  |  |  |  |  |  |
| MtPyre_5F | inspected | 169/169 |  |  | 13 |  |  |  |  |  |  |  |
| MtPyre_6F | inspected | 169/169 |  |  | 5 |  |  |  |  |  |  |  |
| AquaHideout_1F | inspected | 840/840 |  |  | 92 |  |  |  |  |  |  |  |
| AquaHideout_B1F | inspected | 1224/1224 |  |  | 185 |  |  |  |  |  |  |  |
| AquaHideout_B2F | inspected | 816/816 |  |  | 60 |  |  |  |  |  |  |  |
| BattleColosseum_2P | inspected | 126/126 |  |  | 16 |  |  |  |  |  |  |  |
| TradeCenter | inspected | 108/108 |  |  | 48 |  |  |  |  |  |  |  |
| RecordCorner | inspected | 200/200 |  |  | 58 |  |  |  |  |  |  |  |
| BattleColosseum_4P | inspected | 126/126 |  |  | 16 |  |  |  |  |  |  |  |
| ContestHall | inspected | 165/165 |  |  | 67 |  |  |  |  |  |  |  |
| ContestHallBeauty | inspected | 165/165 |  |  | 67 |  |  |  |  |  |  |  |
| ContestHallTough | inspected | 165/165 |  |  | 67 |  |  |  |  |  |  |  |
| ContestHallCool | inspected | 165/165 |  |  | 67 |  |  |  |  |  |  |  |
| ContestHallSmart | inspected | 165/165 |  |  | 67 |  |  |  |  |  |  |  |
| ContestHallCute | inspected | 165/165 |  |  | 67 |  |  |  |  |  |  |  |
| InsideOfTruck | inspected | 25/25 |  |  | 15 |  |  |  |  |  |  |  |
| SSTidalCorridor | inspected | 234/234 |  |  | 109 |  |  |  |  |  |  |  |
| SSTidalLowerDeck | inspected | 221/221 |  |  | 19 |  |  |  |  |  |  |  |
| SSTidalRooms | inspected | 648/648 |  |  | 52 |  |  |  |  |  |  |  |
| BattlePyramidSquare01 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare02 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare03 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare04 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare05 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare06 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare07 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare08 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare09 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare10 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare11 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare12 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare13 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare14 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare15 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattlePyramidSquare16 | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| UnionRoom | not inspected | 0/180 |  |  |  |  |  |  |  |  |  | 1 |
| BattleFrontier_BattleTowerLobby | inspected | 250/250 |  |  | 14 |  |  |  |  |  |  |  |
| BattleFrontier_BattleTowerElevator | inspected | 35/35 |  |  | 12 |  |  |  |  |  |  |  |
| BattleFrontier_BattleTowerCorridor | inspected | 85/85 |  |  | 34 |  |  |  |  |  |  |  |
| BattleFrontier_BattleTowerBattleRoom | inspected | 90/90 |  |  | 2 |  |  |  |  |  |  |  |
| SafariZone_RestHouse | inspected | 90/90 |  |  | 4 |  |  |  |  |  |  |  |
| BattleFrontier_BattleTowerMultiPartnerRoom | not inspected | 0/315 |  |  |  |  |  |  |  |  |  | 1 |
| BattleFrontier_BattleTowerMultiCorridor | inspected | 85/85 |  |  | 26 |  |  |  |  |  |  |  |
| BattleFrontier_BattleTowerMultiBattleRoom | inspected | 90/90 |  |  | 2 |  |  |  |  |  |  |  |
| BattleFrontier_BattleDomeLobby | inspected | 391/391 |  |  | 179 |  |  |  |  |  |  |  |
| BattleFrontier_BattleDomeCorridor | inspected | 336/336 |  |  | 6 |  |  |  |  |  |  |  |
| BattleFrontier_BattleDomePreBattleRoom | inspected | 72/72 |  |  | 4 |  |  |  |  |  |  |  |
| BattleFrontier_BattleDomeBattleRoom | inspected | 200/200 |  |  |  |  |  |  |  |  |  |  |
| BattleFrontier_BattlePalaceLobby | inspected | 300/300 |  |  | 79 |  |  |  |  |  |  |  |
| BattleFrontier_BattlePalaceCorridor | inspected | 238/238 |  |  | 59 |  |  |  |  |  |  |  |
| BattleFrontier_BattlePalaceBattleRoom | inspected | 150/150 |  |  | 33 |  |  |  |  |  | 1 |  |
| BattleFrontier_BattlePyramidLobby | inspected | 270/270 |  |  |  |  |  |  |  |  |  |  |
| BattleFrontier_BattlePyramidFloor | inspected | 64/64 |  |  |  |  |  |  |  |  |  |  |
| BattleFrontier_BattlePyramidTop | inspected | 782/782 |  |  | 534 |  |  |  |  |  |  |  |
| BattleFrontier_BattleArenaLobby | inspected | 208/208 |  |  | 131 |  |  |  |  |  |  |  |
| BattleFrontier_BattleArenaCorridor | inspected | 252/252 |  |  | 84 |  |  |  |  |  |  |  |
| BattleFrontier_BattleArenaBattleRoom | inspected | 176/176 |  |  |  |  |  |  |  |  |  |  |
| BattleFrontier_BattleFactoryLobby | inspected | 228/228 |  |  | 112 |  |  |  |  |  |  |  |
| BattleFrontier_BattleFactoryPreBattleRoom | inspected | 238/238 |  |  |  |  |  |  |  |  |  |  |
| BattleFrontier_BattleFactoryBattleRoom | inspected | 156/156 |  |  |  |  |  |  |  |  |  |  |
| BattleFrontier_BattlePikeLobby | inspected | 143/143 |  |  | 13 |  |  |  |  |  |  |  |
| BattleFrontier_BattlePikeCorridor | inspected | 112/112 |  |  | 13 |  |  |  |  |  |  |  |
| BattleFrontier_BattlePikeThreePathRoom | inspected | 143/143 |  |  | 55 |  |  |  |  |  |  |  |
| BattleFrontier_BattlePikeRoomNormal | inspected | 72/72 |  |  | 13 |  |  |  |  |  |  |  |
| BattleFrontier_BattlePikeRoomFinal | inspected | 40/40 |  |  | 2 |  |  |  |  |  |  |  |
| BattleFrontier_BattlePikeRoomWildMons | inspected | 180/180 |  |  | 13 |  |  |  |  |  |  |  |
| BattleFrontier_RankingHall | inspected | 795/795 |  |  |  |  |  |  |  |  |  |  |
| BattleFrontier_Lounge1 | inspected | 90/90 |  |  | 27 |  |  |  |  |  |  |  |
| BattleFrontier_ExchangeServiceCorner | inspected | 165/165 |  |  | 58 |  |  |  |  |  |  |  |
| BattleFrontier_Lounge2 | inspected | 104/104 |  |  | 38 |  |  |  |  |  |  |  |
| BattleFrontier_Lounge3 | inspected | 90/90 |  |  | 27 |  |  |  |  |  |  |  |
| BattleFrontier_Lounge4 | inspected | 90/90 |  |  | 27 |  |  |  |  |  |  |  |
| BattleFrontier_ScottsHouse | inspected | 48/48 |  |  | 13 |  |  |  |  |  |  |  |
| BattleFrontier_Lounge5 | inspected | 104/104 |  |  | 38 |  |  |  |  |  |  |  |
| BattleFrontier_Lounge6 | inspected | 90/90 |  |  | 27 |  |  |  |  |  |  |  |
| BattleFrontier_Lounge7 | inspected | 90/90 |  |  | 27 |  |  |  |  |  |  |  |
| BattleFrontier_ReceptionGate | inspected | 126/126 |  |  | 50 |  |  |  |  |  |  |  |
| BattleFrontier_Lounge8 | inspected | 90/90 |  |  | 27 |  |  |  |  |  |  |  |
| BattleFrontier_Lounge9 | inspected | 90/90 |  |  | 27 |  |  |  |  |  |  |  |
| BattleFrontier_PokemonCenter_1F | inspected | 126/126 |  |  |  |  |  |  |  |  |  |  |
| BattleFrontier_PokemonCenter_2F | inspected | 140/140 |  |  |  |  |  |  |  |  |  |  |
| BattleFrontier_Mart | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| FarawayIsland_Entrance | inspected | 1564/1564 |  |  | 90 |  |  |  |  | 2 | 1 |  |
| FarawayIsland_Interior | inspected | 754/754 |  |  | 43 |  |  |  |  |  |  |  |
| BirthIsland_Exterior | inspected | 900/900 |  |  | 34 |  |  |  |  |  |  |  |
| BirthIsland_Harbor | inspected | 221/221 |  |  | 72 |  |  |  |  |  |  |  |
| TrainerHill_Entrance | inspected | 323/323 |  |  | 98 |  |  |  |  |  |  |  |
| TrainerHill_1F | inspected | 336/336 |  |  | 90 |  |  |  |  |  |  |  |
| TrainerHill_2F | inspected | 336/336 |  |  | 52 |  |  |  |  |  |  |  |
| TrainerHill_3F | inspected | 336/336 |  |  | 37 |  |  |  |  |  |  |  |
| TrainerHill_4F | inspected | 336/336 |  |  | 52 |  |  |  |  |  |  |  |
| TrainerHill_Roof | inspected | 400/400 |  |  | 331 |  |  |  |  |  |  |  |
| NavelRock_Exterior | inspected | 504/504 |  |  | 51 |  | 3 |  |  |  |  |  |
| NavelRock_Harbor | inspected | 221/221 |  |  | 72 |  |  |  |  |  |  |  |
| TrainerHill_Elevator | inspected | 35/35 |  |  | 12 |  |  |  |  |  |  |  |
| Route109_SeashoreHouse | inspected | 150/150 |  |  |  |  |  |  |  |  |  |  |
| Route110_TrickHouseEntrance | inspected | 96/96 |  |  | 4 |  |  |  |  |  |  |  |
| Route110_TrickHouseEnd | inspected | 96/96 |  |  | 20 |  |  |  |  |  |  |  |
| Route110_TrickHouseCorridor | inspected | 360/360 |  |  | 36 |  |  |  |  |  |  |  |
| Route110_TrickHousePuzzle1 | inspected | 330/330 |  |  | 54 |  |  |  |  |  |  |  |
| Route110_TrickHousePuzzle2 | inspected | 330/330 |  |  |  |  |  |  |  |  |  |  |
| Route110_TrickHousePuzzle3 | inspected | 330/330 |  |  | 51 |  |  |  |  |  |  |  |
| Route110_TrickHousePuzzle4 | inspected | 330/330 |  |  |  |  |  |  |  |  |  |  |
| Route110_TrickHousePuzzle5 | inspected | 330/330 |  |  | 143 |  |  |  |  |  |  |  |
| Route110_TrickHousePuzzle6 | inspected | 330/330 |  |  | 14 |  |  |  |  |  |  |  |
| Route110_TrickHousePuzzle7 | inspected | 330/330 |  |  | 37 |  |  |  |  |  |  |  |
| Route110_TrickHousePuzzle8 | inspected | 330/330 |  |  | 31 |  |  |  |  |  |  |  |
| Route110_SeasideCyclingRoadSouthEntrance | inspected | 90/90 |  |  | 44 |  |  |  |  |  |  |  |
| Route110_SeasideCyclingRoadNorthEntrance | inspected | 90/90 |  |  | 44 |  |  |  |  |  |  |  |
| Route113_GlassWorkshop | inspected | 90/90 |  |  | 6 |  |  |  |  |  |  |  |
| Route123_BerryMastersHouse | inspected | 88/88 |  |  |  |  |  |  |  |  |  |  |
| Route119_WeatherInstitute_1F | inspected | 260/260 |  |  | 3 |  |  |  |  |  |  |  |
| Route119_WeatherInstitute_2F | inspected | 220/220 |  |  | 18 |  |  |  |  |  |  |  |
| Route119_House | inspected | 90/90 |  |  |  |  |  |  |  |  |  |  |
| Route124_DivingTreasureHuntersHouse | inspected | 90/90 |  |  | 11 |  |  |  |  |  |  |  |

## secret_base: 24 maps, 24 wholly inspected

Totals: flat-blocked 38

| Map | Status | Cells seen | fin | spike | flat-blocked | card-tree | walk-step | seam | water-wall | water-drop | hole | not-3d |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SecretBase_RedCave1 | inspected | 99/99 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_BrownCave1 | inspected | 99/99 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_BlueCave1 | inspected | 99/99 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_YellowCave1 | inspected | 99/99 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_Tree1 | inspected | 99/99 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_Shrub1 | inspected | 99/99 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_RedCave2 | inspected | 112/112 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_BrownCave2 | inspected | 126/126 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_BlueCave2 | inspected | 105/105 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_YellowCave2 | inspected | 126/126 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_Tree2 | inspected | 112/112 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_Shrub2 | inspected | 105/105 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_RedCave3 | inspected | 120/120 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_BrownCave3 | inspected | 165/165 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_BlueCave3 | inspected | 170/170 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_YellowCave3 | inspected | 132/132 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_Tree3 | inspected | 136/136 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_Shrub3 | inspected | 143/143 |  |  | 1 |  |  |  |  |  |  |  |
| SecretBase_RedCave4 | inspected | 135/135 |  |  | 3 |  |  |  |  |  |  |  |
| SecretBase_BrownCave4 | inspected | 168/168 |  |  | 3 |  |  |  |  |  |  |  |
| SecretBase_BlueCave4 | inspected | 153/153 |  |  | 3 |  |  |  |  |  |  |  |
| SecretBase_YellowCave4 | inspected | 182/182 |  |  | 3 |  |  |  |  |  |  |  |
| SecretBase_Tree4 | inspected | 196/196 |  |  | 5 |  |  |  |  |  |  |  |
| SecretBase_Shrub4 | inspected | 154/154 |  |  | 3 |  |  |  |  |  |  |  |
