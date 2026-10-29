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
| | Route 120's one long cliff three thin ridges | **R2** |
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
  the cells flat ground, and the drawn strata become ridges. Rock, in Emerald's art, is a mass seen from above - a
  ridge, a hill or the face between two levels - and the 3D shape must follow the mass, not the stripes.
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
