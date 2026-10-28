# The 3D view's depth, map by map (2026-10-28)

Step 12 of the queue: a checklist of every map a player enters, against the depth standard (walls with height and
thickness, counters, machines and furniture standing as objects, no picture on the floor), to say what step 16 (real
depth in every flat room) has to do. Nothing in the game changed for this audit.

Where each result comes from: **L** this Linux machine. The pictures are the 3D map sweep's (the 3D test build of
engine `5ec3d26f`, 2026-10-26, Mesa's software OpenGL, at noon, the default camera: `docs/mp-3d-update-20261026.md`
section 4); the room list and the model list are read from the data of engine `723d7506`. Not covered: a graphics
card, Windows, the owner's PCs, night, weather.

## How

* **The maps**: `tools/qa/inventory.py` lists 935 maps; 460 are entered in the game (the FireRed/LeafGreen maps, the
  ones only the C code enters and the unused ones left out, as in the sweep).
* **Modelled rooms**: `tools/diorama_buildings/voxel_building_specs.py` models 116 room layouts as voxel interiors
  (each piece of furniture built from its own drawing and proved pixel for pixel in the GBA's view), used by 194 of
  the maps: 179 rooms (every Pokemon Center, Mart, house layout, gym, the Elite Four's rooms, the Battle Frontier's
  battle rooms...) and 15 cave-like interiors (New Mauville, the Abandoned Ship, Sky Pillar, Mirage Tower).
* **The rest of the rooms** (103) are drawn by the generic 3D rules. A count from the compiled rules alone (blocked
  cells with no height of their own) called them all flat, but the pictures show otherwise: the renderer stands walls
  and many counters, shelves and machines up from their art. So each of the 102 that the sweep pictured (one stopped
  the test scene, below) was looked at, on contact sheets of 12 (scratchpad `depth/sheets/`), one picture each.
* **Outdoor maps and caves** (67 outdoor, 97 caves, 14 underwater): every picture of theirs was looked at in the
  sweep itself (outdoor in three cameras): buildings, trees, cliffs and rock stand; what was wrong there is in its own
  issues (below).

## Summary

| Kind | Maps | Meets the standard | Partly flat | Flat | Not seen |
| --- | --- | --- | --- | --- | --- |
| Rooms with a modelled interior | 179 | 179 (by construction: proved against their drawing) | - | - | - |
| Rooms drawn by the generic rules | 103 | 65 | 30 | 5 | 3 |
| Cave-like interiors with a model | 15 | 15 | - | - | - |
| Caves, underwater | 96 | 96 (rock masses; Victory Road's floors dark until Flash, as in the game) | - | - | - |
| Outdoor | 67 | 67, with the open issues below | - | - | - |

Open issues that touch depth outdoors and in caves (each in `KNOWN_ISSUES.md`): 37 slopes that lie flat (MS-153; Route
115's 2 rise since engine `563c0f77`, Granite Cave B1F's 2 since `a23e77e0` and Route 119's 2 since `f1391374`, later
the same day; Sootopolis Gym's 12 slides are flat ice in the GBA's own drawing), three map seams a level apart (MS-162:
Mauville City and Route 111, the Battle Frontier's halves, the Safari Zone's two), 6 decorative ledges of Route 118's
that land a level higher (MS-154).

**Partly flat** means the walls stand and most of the room does, but some furniture is drawn on the floor; **flat**
means the room's main features are. These 35 rooms are step 16's list. Most share a few tilesets (the Battle
Frontier's lounges and lobbies, Ever Grande's halls), so one modelled piece of furniture serves many rooms.

## The rooms drawn by the generic rules

By eye, from one picture each at the sweep's start (the map's middle or a warp). "Check" marks what one picture
cannot settle; it is confirmed room by room when the room is corrected.

| # | Map | Depth | On the floor |
| --- | --- | --- | --- |
| 1 | Battle Frontier: Battle Arena corridor | not seen | the script walks the player at once; the camera is over the dark |
| 2 | Battle Arena lobby | partly flat | the PCs and the side desks |
| 3 | Battle Dome corridor | meets | |
| 4 | Battle Dome lobby | partly flat | the tables (check); the rope posts stand |
| 5 | Battle Factory lobby | partly flat | the counters and benches (check) |
| 6 | Battle Palace corridor | meets | |
| 7 | Battle Palace lobby | partly flat | the tables |
| 8 | Battle Pike corridor | partly flat | the stands |
| 9 | Battle Pike lobby | partly flat | the tables and chairs |
| 10 | Battle Pike three-path room | partly flat | the tables |
| 11 | Battle Pyramid floor | not seen | dark but for the light round the player, as in the game |
| 12 | Battle Pyramid lobby | partly flat | the PCs |
| 13 | Battle Pyramid top | meets | |
| 14 | Battle Tower corridor | meets | |
| 15 | Battle Tower elevator | meets | drawn in 2D: the 3D view's fallback for a room it does not support (by design) |
| 16 | Battle Tower multi corridor | meets | |
| - | Battle Tower multi partner room | not seen | the sweep's test scene stopped there (MS-98) |
| 17 | Exchange Service Corner | partly flat | the counter (check) |
| 18-26 | Battle Frontier lounges 1 to 9 | partly flat | the sofas, chairs and tables (the plants and the TV stand) |
| 27 | Ranking Hall | partly flat | the display cases (check) |
| 28 | Reception gate | partly flat | the tables and benches |
| 29 | Scott's house | partly flat | the furniture |
| 30 | Birth Island | meets | |
| 31 | Birth Island harbor | meets | |
| 32-37 | Contest halls (normal, Beauty, Cool, Cute, Smart, Tough) | meets | the stage and its rim stand |
| 38-40, 42 | Ever Grande City halls 1, 2, 3, 5 | flat | the stairs and their railings |
| 41 | Ever Grande City hall 4 | flat | the stairs and their railings |
| 43 | Hall of Fame | partly flat | the machine |
| 44 | Pokemon League 1F | meets | |
| 45 | Fallarbor Battle Tent corridor | meets | |
| 46 | Fallarbor Battle Tent lobby | meets | |
| 47 | Faraway Island entrance | meets | |
| 48 | Faraway Island | meets | |
| 49 | Lavaridge herb shop | meets | |
| 50 | Lilycove Contest Hall | meets | |
| 51 | Lilycove Contest lobby | meets | |
| 52-56 | Lilycove Department Store 1F to 5F | meets | |
| 57 | Department Store elevator | meets | |
| 58 | Department Store rooftop | partly flat | the benches and planters |
| 59 | Lilycove harbor | meets | |
| 60, 61 | Lilycove Museum 1F, 2F | meets | |
| 62 | Pokemon Trainer Fan Club | meets | |
| 63 | Mauville bike shop | partly flat | the bikes |
| 64 | Mauville Game Corner | partly flat | the roulette tables (the slot machines stand) |
| 65 | Mossdeep Game Corner 1F | partly flat | the tables |
| 66 | Mossdeep Game Corner B1F | meets | |
| 67 | Mt. Chimney cable car station | meets | |
| 68 | Navel Rock | meets | |
| 69 | Navel Rock harbor | meets | |
| 70 | Record Corner | meets | |
| 71, 72 | Cycling Road entrances (north, south) | meets | |
| 73 | Trick House corridor | meets | |
| 74 | Trick House puzzle 5 | meets | a floor puzzle |
| 75 | Trick House puzzle 8 | meets | |
| 76 | Route 112 cable car station | meets | |
| 77 | Fossil Maniac's tunnel | meets | |
| 78 | Lanette's house | meets | |
| 79 | Pokemon Day Care | meets | |
| 80 | Safari Zone entrance | meets | |
| 81 | Diving treasure hunter's house | partly flat | the table and chairs |
| 82 | Devon Corporation 1F | partly flat | the counters (check) |
| 83 | Safari Zone rest house | partly flat | the table |
| 84 | Slateport Battle Tent corridor | meets | |
| 85 | Slateport Battle Tent lobby | meets | |
| 86 | Slateport harbor | meets | |
| 87 | Oceanic Museum 1F | meets | |
| 88 | Slateport Pokemon Fan Club | meets | |
| 89, 90 | Stern's shipyard 1F, 2F | meets | |
| 91 | Sootopolis Mystery Events house 1F | partly flat | the table and chairs |
| 92 | S.S. Tidal corridor | meets | the cabins' roof is white, as the GBA draws it |
| 93 | Trade Center | meets | |
| 94-97 | Trainer Hill 1F to 4F | meets | |
| 98 | Trainer Hill elevator | meets | |
| 99 | Trainer Hill entrance | meets | |
| 100 | Trainer Hill roof | meets | |
| 101 | Verdanturf Battle Tent corridor | meets | |
| 102 | Verdanturf Battle Tent lobby | meets | |

Counts: 65 meet the standard (counting each room of a numbered range), 30 partly flat, 5 flat, 3 not seen (the
Arena corridor and the Pyramid's floor by the game's own darkness or script, the multi partner room by MS-98).

## Not done

* The corrections themselves (step 16): model the furniture of the 35 rooms above, first the Battle Frontier's
  lounge and lobby pieces and Ever Grande's hall stairs (the most rooms per piece), then the rest; each proved
  against its drawing as the modelled rooms are, pictured before and after.
* A second picture of the rooms marked "check", and of the two not seen once their scripts or light allow.
* Movement and collision checks per room: the 3D view does not change either (the game's own), so none were run.
