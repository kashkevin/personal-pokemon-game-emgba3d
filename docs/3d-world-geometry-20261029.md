# The 3D world's geometry: what is wrong, why, and the plan (2026-10-29)

Step 16, expanded by the owner on 2026-10-29 ("complete world geometry & true 3D overhaul"): every map of the world
in believable 3D, the root causes fixed rather than map by map, every map inspected by a tool from several cameras,
no loss of speed. Publishing waits for it (owner, 21:10). This file is **phase A**: the inventory, the audit of the
3D pipeline and the plan. Nothing in the game changed for it.

Where each result comes from: **L** this Linux machine (Mesa's software OpenGL, no graphics card, at noon, the
default camera). Not covered: Windows, a graphics card, the owner's PCs. The owner's screenshots did not come through;
the defects below are the ones the owner described, found again in pictures taken here.

## 1. The world: 503 maps (the inventory)

`tools/qa/geometry_inventory.py` (engine `c46e943e`) reads the game's own data: every map of `data/maps/map_groups.json`, whether
the game enters it (`tools/qa/inventory.py`'s reachability), and for each one its layout's size and tilesets, its kind
and what its cells hold (height levels, the steps between levels, water, waterfalls, ledges, stairs, bridges, doors).
The full table: `docs/3d-world-geometry-inventory.md`.

| Kind | Maps in the game |
| --- | --- |
| Outdoor (towns, cities, routes, sea routes) | 67 |
| Caves and other underground maps | 99 |
| Underwater | 14 |
| Indoor (rooms, gyms, Centers, Marts, the Battle Frontier's buildings...) | 299 |
| Secret bases | 24 |
| **In the game** | **503** (393 layouts, 310,969 cells) |
| Out of scope | 432: 417 FireRed/LeafGreen maps compiled in but not part of the game, 15 unused |

The 503 are the 460 a player walks into plus the 43 only the C code enters (24 secret bases, 16 Battle Pyramid floor
pieces, the 2 high-tide Shoal Cave rooms, the truck).

What the data says about height: the GBA barely records it. **49 of the 67 outdoor maps use one height level** for
all their ground - Route 111, Route 112, Route 113, Mt. Chimney and Jagged Pass among them, all drawn with big cliffs -
and 86 of the 99 caves. The cliffs exist only in the drawing and in the collision. So the 3D shape has to be read from
what the tiles are and from how the ground around them connects; the stored height alone cannot give it.

## 2. A correction to the 2026-10-28 depth audit

`docs/3d-depth-audit-20261028.md` judged all 67 outdoor maps as meeting the depth standard "with the open issues
below". That was too lenient: the pictures taken today show fins, flat cut-out trees and flat blue boxes on many of
them (section 4). Its room findings stand (the 35 rooms with furniture on the floor are part of this step).

## 3. How the 3D world is made now (the audit)

Three read-only passes over the 3D code (terrain; objects, trees, buildings and water; culling, transitions, camera,
performance and tools), their main claims then checked in the code (marked **checked**).

* **Heights**: every cell of every layout gets a record from an offline compiler (`tools/diorama_rules/
  compile_rules.py`, about 4 minutes for the world). Level changes come only from General's ten terrace metatiles
  (`terrace_topology.py` `TERRACE_ROLES`, **checked**); the GBA's stored height is never turned into height outdoors
  (`terrain_mesh.c` `DioramaTerrain_NormalizeElevation` and `rules.c` `DioramaRules_DefaultGroundHeight` return 0,
  **checked**). Each layout is solved alone, its highest ground level 0; a group of ground whose constraints contradict
  each other is dropped (left flat).
* **Cliffs and rock**: a cliff record is a box from its own ground up one tile (cliff and rock cells are never put
  on the level between the two grounds they separate); other rock is drawn as a height per pixel taken from the art.
* **Trees**: the default is the 3DS project's flat cut-outs (`sdl2.c` `sTreeStyle3ds = TRUE`, **checked**): a trunk
  painted on the ground and a tilted card for the crown. The voxel tree (one model, a real trunk and crown, F8) covers
  8,340 of General's 18,511 tree cells; the dense forest is a bumpy green slab; other tilesets' trees are flat.
* **Everything else**: 51% of all cells fall back to flat ground for want of a rule (113,122 of them MB_NORMAL);
  buildings are modelled from their drawing (1,553 models, 4,676 placements in 196 layouts) but most route houses
  keep a flat roof; Strength boulders, Rock Smash rocks and Cut trees are cards like people; cave mouths, shores and
  waterfalls are painted on; 94 indoor layouts have no model.
* **Beyond the scene**: past the 81 x 81 cells drawn round the camera, and through any gap in the ground, the clear
  colour shows - a pale sky blue outdoors. The far field (2 x 2 blocks out to 55 tiles) is off by default.
* **Speed**: terrain in 8 x 8 chunks, frustum-culled; buildings, props and sprites are not culled; no level of detail,
  no occlusion culling. The chunk cache's lookups scan up to 1,024 slots, several times a chunk a sync (a candidate
  for lag that grows as the cache fills: to be measured in phase D).
* **Tools**: a 3D map sweep exists (`tools/pc_port/map_inspection.py`: one process per picture, a blank/hole/dark
  check on a thumbnail), and a per-cell dump of the resolved scene (`PKMN_DIORAMA_STAGE_DUMP`). The camera always looks
  north: no test can turn it.

## 4. The defects and their root causes

Pictures taken today (L, engine `9f032173`, 20 maps, scratchpad `geo/base1/`; game art, not committed):

| What the owner described | Seen here | Root cause |
| --- | --- | --- |
| Tall, narrow, rectangular cliffs | Mossdeep's cliff a row of pillars; the Safari Zone's cliffs thin slabs | **R1** |
| | Route 120's one long cliff painted flat on the ground | **R2** |
| Inconsistent cliff heights | the same rock drawn as a step on one map and flat on the next | **R1, R2, R3** |
| Flat trees and vegetation | every route's trees (the default cut-outs) | **R5** |
| Abrupt height transitions | whole-tile steps with vertical sides; the sea a full tile under every coast | **R1, R4** |
| Large featureless blue rectangles | the Safari Zone's pond a raised blue box; pale blue through gaps; Route 110's Cycling Road a bare slab | **R4** |
| Seams and gaps | maps a level apart where they meet (MS-162); faces that do not meet | **R3, R4** |

* **R1. A cliff stands on its own ground, not between its two grounds.** Mossdeep (checked cell by cell in the
  compiled records): the lower street lies at -1 tile, the plateau at 0, and the cliff's corner pieces (General 0x89,
  0x79) are boxes from 0 to +1 - each stands a tile over the plateau and two over the street, a pillar. The rock pieces
  between them lie flat on one level or the other. The same rule makes the slabs and fins wherever ground was lowered
  (Ever Grande 1,554 such cells, Mt. Pyre's summit 1,044, Route 111 883, Routes 124 and 127 about 800 each:
  the audit's count from the compiled tables; phase B counts them as drawn).
* **R2. Rock drawn on level ground is read pixel by pixel.** Route 120 (checked): its cliff is a band of General's
  rock (0x72, 0x75) and the secondary tileset's 0x3A between two areas the GBA keeps on one level; the compiler calls
  the cells flat ground, so the cliff is only paint on level ground (phase B's pictures; an earlier reading of this
  doc said its strata stood as ridges - they do not). Rock, in Emerald's art, is a mass seen from above - a ridge, a
  hill or the face between two levels - and the 3D shape must follow the mass, not the stripes.
* **R3. Levels come from too little.** Only General's terrace pieces make a level; other tilesets' cliffs (Fallarbor,
  Sootopolis, Mossdeep, Lavaridge, Fortree, the Safari Zone) and the GBA's own height levels where it has them are
  ignored; contradictory groups are dropped flat; each map is solved alone, so neighbours meet a level apart.
* **R4. Gaps, water walls and the sky.** Vertical sides are only hung from some cells, so the clear colour shows
  between pieces; water is a slab whose sides show the water tile, so a pond the solver lifts stands as a blue box;
  the sea lies a whole tile under every coast; past the scene's edge there is only the sky colour.
* **R5. Trees and plants are flat by default**, and the voxel tree covers less than half of the tree cells (one model
  for all).
* **R6. Things the rules do not know lie flat**: other tilesets' rock and fences, boulders and Cut trees (cards),
  cave mouths, shores and waterfalls (painted), most route houses' roofs, 94 rooms (the 35 with furniture on the floor
  among them).
* **R7. Textures**: a side's art is the cell's whole drawing squeezed into every 16-voxel band (stripes), and colour
  0 of the art is a hole.

## 5. The plan

Each fix is general - one rule for every map - and checked by the tool over every map, not by eye on a few. Collision
and gameplay never change: the 3D view draws what the GBA's map is.

| Phase | What | Estimate |
| --- | --- | --- |
| A | Inventory, audit, root causes, plan (this file) | ~0.7 h spent (21:14-21:55, three readers alongside) |
| B | **The inspection tool**: a geometry probe in the 3D test build (each cell's ground, top and kind as drawn, after every run-time adjustment), cameras a test can set (pitch, zoom, and a turned view to see the sides and backs), a tour through every map in few processes; the checks (pillars and fins, cliffs without a level change, steps the player walks across, water standing over its banks, holes to the sky, seams at map connections, things standing off the ground); a coverage manifest of every map; the baseline run of all 503 | ~10-12 h |
| C1 | **Heights**: one solve per connected world (maps together, no group dropped), from terrace art, every tileset's cliff art, the GBA's height levels, ledges, stairs and slopes; every rock band one continuous surface between the levels round it (a face where they differ, a ridge where they do not), computed once per layout | ~22-28 h |
| C2 | **Mesh and textures**: sides hung to any lower neighbour, slopes as wide as their rise, cliff texture tiled by height, no colour-0 holes, the map's border on its edge's level, water banks, the sea at its coast | ~8-10 h |
| C3 | **Trees and plants**: voxel trees the default, several models (large, small, the dense forest's canopy with trunks, other tilesets' trees), every tree cell claimed; speed kept (instancing, a simpler model at distance) | ~10-12 h |
| C4 | **Objects**: rock and fences of every tileset, boulders, Rock Smash rocks and Cut trees as models, cave mouths cut into the rock, waterfalls | ~6-8 h |
| C5 | **Buildings and rooms**: real roofs on every house, a model kept when a script redraws a cell of it, the 94 unmodelled rooms (the 35 with furniture on the floor first) | ~18-22 h |
| D | **Speed**: the same walks and long sessions before and after (frame time, draws, vertices, memory), the chunk cache's lookups, the lag that grows over a session | ~5-6 h |
| E | **Windows**: the Windows package's 3D job takes the inspection pictures with Mesa (no graphics card in CI); a capture script for the owner's PC for a real graphics card - not claimed until the owner runs it | ~3-4 h |
| F | Evidence: before/after pictures of every defect, the manifest with defect counts, what is left unverified | ~3-4 h |

**Total: about 85-110 hours** (phase A included), in this order. Ledges, hills and ramps (#275), the map seams
(#302) and the 35 rooms (#267) are part of C1, C2 and C5. The multiplayer, battle-latency, save and lag work stays
in the plan: none of it is open now except the overworld lag the owner reported, which phase D measures (its details
- when and where it starts - would help; none came through yet).

## 6. What "done" will mean

Every one of the 503 maps visited by the tool from several cameras, its pictures kept and its checks passed or each
remaining defect listed with its map and place; the owner's six defects shown before and after; collision unchanged
(the game's own); no slower than now on the same walks; the Windows results stated for what was run (CI's software
renderer) and what was not (a graphics card). Not claimed: that the world is free of defects, or anything about a
graphics card or the owner's PCs until they are tried there.

## 7. Progress

### Phase B: the inspection tool and the baseline (done 2026-10-29 21:42-22:45; engine `71aff298`)

`tools/qa/geometry_check.py` with the geometry probe in the 3D test build: 537 places whose scenes cover every cell
of the 503 maps, each written cell by cell as the terrain mesh is built (ground, top, per-pixel rock heights, kind,
model) and photographed from four cameras (the Adventure and Diorama cameras, fixed 15 and 75 degree views) against
a magenta sky, so any hole to the sky is a colour the game never draws. The checks per map: fins and spikes (terrain
three quarters of a tile over both neighbours on a side - in runs, or alone), blocked cells drawn flat, cut-out
trees, steps between walkable cells, seams at map connections, water standing over its banks, drops to water, holes
to the sky, places not drawn in 3D; a coverage manifest (`manifest.json`), a report and contact sheets.

The baseline (the build of 2026-10-29, before any phase C change): 535 of the 537 places, 501 of the 503 maps wholly
seen (the Union Room - no wireless on PC - and the Battle Tower's multi-battle partner room stop the game when
warped into). Cells found: fins 2,038, spikes 1,135, blocked cells drawn flat 26,304, cut-out trees 16,957, drops to
water 1,528, water over its banks 45, seams 64, steps 72; holes to the sky at 107 places; 2 places not in 3D.

| Map kind | Maps | fin | spike | flat-blocked | card-tree | walk-step | seam | water-wall | water-drop | hole (places) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| outdoor | 67 | 1,205 | 745 | 13,175 | 16,957 | 20 | 64 | 42 | 1,459 | 38 |
| cave | 99 | 802 | 383 | 3,170 | 0 | 49 | 0 | 0 | 69 | 19 |
| underwater | 14 | 31 | 7 | 61 | 0 | 0 | 0 | 0 | 0 | 0 |
| indoor | 299 | 0 | 0 | 9,860 | 0 | 3 | 0 | 3 | 0 | 50 |
| secret base | 24 | 0 | 0 | 38 | 0 | 0 | 0 | 0 | 0 | 0 |

### Phase C1, first part: rock bands (done 2026-10-30 02:31; engine `242e3764`, with the crash fixes `42daa2b6`)

The rules' rock - cliffs, mounds, walls, mountains' art, and the blocked plain cells drawn in a palette their rock is
drawn in - is cut into bands, each one surface over the ground and water round it (`tools/diorama_rules/rock_bands.py`):
one ground per band (the lowest level it meets along a real share of its edge); a band between two levels a cliff,
its top level with the higher of the levels near each cell and its face down to the lower; rock near one level only a
tile over it, never above the band's top; a band on one level a ridge or mountain, a tile over it and half a tile more
each cell in, at most two tiles over its ground. What the player walks on keeps its height (a mountain's walkable
art, and the mountains of several tops settled on 2026-10-24 for Routes 111-116). A pond lies no higher than its
lowest bank; a ground cell beside rock hangs its side down to the rock's own pixel heights.

Before and after, the same 17 places across 14 maps (the probe, the same cameras):

| | fin | spike | flat-blocked | water-wall | water-drop | sky through (pixels) |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | 299 | 202 | 2,645 | 42 | 413 | 7,106 |
| C1 | 166 | 150 | 1,829 | 24 | 418 | 755 |

The whole world, the full sweep of the C1 build (`242e3764`; 534 of the 537 places - the Union Room and the Battle
Tower's multi-battle partner room stop the game, the Battle Pike's room did this time) against the baseline:

| Map kind | fin | spike | flat-blocked | water-wall | water-drop | places with sky through |
| --- | --- | --- | --- | --- | --- | --- |
| outdoor (67 maps) | 1,205 -> 878 | 745 -> 511 | 13,175 -> 9,943 | 42 -> 24 | 1,459 -> 1,464 | 38 -> 9 |
| cave (99) | 802 -> 802 | 383 -> 383 | 3,170 -> 3,170 | 0 -> 0 | 69 -> 69 | 19 -> 19 |
| indoor (299) | 0 -> 0 | 0 -> 0 | 9,847 -> 9,841 | 3 -> 0 | 0 -> 2 | 50 -> 50 |
| all (503) | 2,038 -> 1,711 | 1,135 -> 901 | 26,291 -> 23,053 | 45 -> 24 | 1,528 -> 1,535 | 107 -> 78 |

Cut-out trees (16,957), steps between walkable cells (72) and seams (64) are unchanged: they are C3's, C1's level
solve's and MS-162's. Engine `4d94b864` (phase C2's first fix) then hangs rock's sides down to rock on a lower ground:
on the 17 places above the sky through fell from 755 to 47 pixels (Mt Pyre's summit's pit, Ever Grande City); its
own full sweep comes with the next part.

The owner's defects this reaches: Mossdeep's cliff, a row of pillars a tile over its plateau and two over the street,
is one face from the street to the plateau; Ever Grande's rock has no sky through it; the Safari Zone's north-west
pond is sunk between its banks, not a raised blue box. Mt Pyre's summit keeps the original's even walls. Pictures were
looked at for every place above, not only the counts.

Eight versions were tried; the rejected ones taught: one ground for a whole band took a maze of rock down to a pit
two levels down beside it, and the water round it with it (Mt Pyre's summit as a sunken blue box); each cell on its
own ground left the sky between them, and rising inside wide masses stood them as columns; heights summed over a
band bulged a maze's junctions to two tiles; a face laid smoothly between its levels became a ramp, Ever Grande's
mountain a slope down to Victory Road's mouth; rock rising over the upper level inward stood Route 114's mountains
taller than the game draws them; rock a tile over its level next to a face at that level stood in steps.

Not fixed by this part (still open): walkable mountain-top pockets inside a mountain drawn a tile up (Ever Grande
round Victory Road: small notches); caves (802 fins and 383 spikes in the baseline: their rock is the caves' own
rule); trees (C3), objects (C4), rooms (C5); the four map seams of MS-162. Linux and Mesa's software renderer only:
nothing is claimed for Windows or a graphics card until it is run there.

The tool warps the game straight into every place, and three rooms the game reaches only through its own flows crash
it when entered so, before C1 as after (not reachable this way in play): Sootopolis's Mystery Events house's
basement (its e-Reader trainer's team made from no data: a stack overflow; Mystery Events are not on PC), the Union
Room (wireless data; no wireless on PC) and the Battle Tower's multi-battle partner room (its candidates, set up only
by the Tower's challenge).

### Phase C2, second part: where the sky still showed through (done 2026-10-30 03:47-04:35; engine `00d58e6b`)

After C1's sweep and `4d94b864`, 31 places still showed the probe's magenta sky somewhere in their pictures. Each
was looked at in the probe's pictures and again in the game's own sky (the same places, the same cameras,
`PKMN_TEST_GEO_SKY=0`), and sorted:

- **Not holes: the GBA's black between rooms.** The Abandoned Ship's cabins and corridors, New Mauville, Mirage
  Tower's corners and the Mossdeep Gym have cells the GBA draws black between their rooms. The 3D view draws nothing
  there, and the room's dark shows: in play the same near-black as the void round the map (pictured both ways). So the
  probe now draws those cells as the black floor the GBA shows (test builds only: the game itself is unchanged), and
  takes its pictures with the air's dust, light rays and gloom off (drawn over the scene, not part of it: the dust
  read as stars in the void and the rays lifted its black). Its sky then shows only where the scene itself is open.
- **Holes, fixed.** Meteor Falls 1F's bridge kept the water under it at the water's nominal level while the cave's
  pools round it are sunk 6/16 of a tile: a band of sky under its deck, and Victory Road's bridges the same at their
  sides. The water under a bridge now lies at the level of the water beside it, and the ground beside a bridge hangs
  its side down to that water. The Abandoned Ship's outside stairs on Route 108 stand on its deck's level, a level
  over the sea, and reached only a voxel under it: the sky showed under them. Stairs going up now hang a side down to
  lower ground beside them, as ground does. (A player surfing under such a bridge now stays at the river's level
  too, where it rose 6/16 of a tile under the deck.)
- **Left as they are (looked at, not holes in play or too small to matter):** the far edge of the loaded scene in the
  low 15-degree view - sky seen past the last cells, between beach umbrellas or behind a rock (Routes 109, 124 and
  131, Pacifidlog): in play the scene's edge fades into the sky's own haze there, so nothing shows. Fortree's east
  tree house (slivers between its crown and its platform, 112 pixels), the Battle Palace battle room (a hairline
  along its two pools' back edges), New Mauville's entrance (its door model's light slits are see-through) and
  Faraway Island's entrance (a hairline beside a small object): open, small.

The same 31 places, the probe's pictures with the air off and the void drawn black, the worst of the four views per
place:

| Build | places with 40 or more sky pixels | sky pixels |
| --- | --- | --- |
| `4d94b864` (the probe's changes only) | 12 | 2,519 |
| this part | 9 | 1,033 |

(With the probe as it was - the air on, the void drawn as nothing - `4d94b864` had 23 such places: 11 of them were
the void and the air, not holes.) The whole world's sweep of this build comes next.

### Phase C2, third part: Sootopolis's crater (2026-10-30 05:04-05:50; engine `3ed7b0a2`)

The largest groups of blocked cells still drawn flat after C1 were the white rock of two tilesets no rule names:
Route 126's crater round Sootopolis (1,225 cells: a low terraced island with its dark mouth level with the rock) and
Sootopolis's own crater walls and terrace ledges (1,500: painted on a flat white plane). The classifier left them as
flat ground, and no cliff of the General tileset stood beside them to start a rock band (Mossdeep City's brown
cliffs had one, so C1 stood those).

A tileset file may now say which of its metatiles are rock wherever a cell drawn with them is blocked ("rockArt"):
walked, the same art stays ground - Sootopolis paves its streets with its white rock, 1,214 walked cells against 574
blocked of one metatile. With it, "pits": rock that shapes its band but lies on its ground (Route 126's crater mouth:
the rim rises to it and the mouth sinks between walls), and "capTiles": how high that rock may stand (four tiles
over its ground). The Mossdeep and Sootopolis tilesets list their white rock, its tops, faces and shore rock (not
their trees, houses, striped walls or the sea's brown rocks; each one's blocked and walked uses counted over every
map that draws with it).

The 15 places of Mossdeep City, Sootopolis and Routes 124-129, against `00d58e6b` (the probe; pictures looked at
for each):

| Map | fin | spike | flat-blocked |
| --- | --- | --- | --- |
| Route 126 | 18 -> 6 | 32 -> 7 | 1,225 -> 47 |
| Sootopolis City | 19 -> 81 | 6 -> 66 | 1,500 -> 170 |
| Mossdeep City, Routes 124, 125, 127, 128, 129 | unchanged | unchanged | unchanged |
| all 15 places | 82 -> 132 | 132 -> 167 | 3,011 -> 503 |

No sky shows through any of them. Sootopolis's fins and spikes are its terrace ledges: one or two cells of rock
between streets the terrace solver lays on one level (the GBA gives the streets one elevation; the ledges are drawn
as steps), now walls a tile high where they were paint. Steps between street levels are the level solve's work,
still to come. Linux and Mesa's software renderer only.
