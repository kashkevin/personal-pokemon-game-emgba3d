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

### Phase C2: the whole world again (sweep 2026-10-30 05:55-06:40; engine `3ed7b0a2`, then `97663b8f`)

The full sweep of `3ed7b0a2`: 535 of the 537 places, 501 of the 503 maps wholly seen (the same two rooms stop the
game when warped into, and Sootopolis's Mystery Events basement crashes as before and is restarted after - all three
not reachable this way in play, as written above). The whole world, the baseline, C1 and now:

| Sweep | fin | spike | flat-blocked | card-tree | walk-step | seam | water-wall | water-drop | hole (places) | not-3d |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline (2026-10-29) | 2,038 | 1,135 | 26,304 | 16,957 | 72 | 64 | 45 | 1,528 | 60 | 2 |
| C1 (`242e3764`) | 1,711 | 901 | 23,053 | 16,957 | 72 | 64 | 24 | 1,535 | 31 | 3 |
| C2 (`3ed7b0a2`) | 1,761 | 936 | 20,558 | 16,957 | 72 | 64 | 24 | 1,535 | 9 | 2 |

Since C1: outdoors 2,508 fewer blocked cells drawn flat (Route 126 and Sootopolis), 22 places fewer with a hole
(18 of them caves: their void is now drawn as the GBA's black in the probe, test builds only), and 50 more fin and
35 more spike cells: Sootopolis's terrace ledges, now walls (above). The 9 places left with a hole are the ones
listed as left as they are. Caves, underwater and rooms are otherwise as after C1.

`97663b8f` (after the sweep): the tall faces of C1's rock bands (Route 126's crater, Route 115's and Ever Grande's
cliffs) showed one pixel's colour drawn down the whole face, a stripe; a side three quarters of a tile tall or more
now shows the cell's drawing, as a cliff's face does. Shorter sides keep the pixel's colour (Route 104's terraces,
the owner's report of 2026-10-24). Six places probed before and after: only rock faces differ. Linux and Mesa's
software renderer only.

Next: the trees (C3). Every tree of the General tileset is still the 3DS project's cut-out (16,957 cells, the
default the owner chose on 2026-10-10): each crown becomes a solid of voxels made from that same art, with a trunk
under it.

### Phase C3, first part: the trees stand as solids (2026-10-30 06:48-07:50; engine `29c95198`)

"Trees must have actual 3D trunks and canopy volume." The 3DS trees the owner chose on 2026-10-10 keep their art
and their place, but each crown is now a solid of voxels made from that art, where the cut-out stood: each leaf
pixel a column through the crown's plane, longest where it is furthest inside the outline (a rounded crown about
1.5 tiles thick for the large tree, the art on its front and back, each pixel's colour down its sides, every face
shaded by the way it looks), and a trunk of bark stands under it, its foot on the trunk's art and its top inside
the crown (the small trees' drawn trunk replaced by it). From the field's cameras the forests read as rows of
round crowns with shaded sides, short trunks under the nearest, and broad shadows; from the low camera, solid
masses where the cut-outs were paper. The cut-outs are still drawn with `PKMN_DIORAMA_TREE_CARDS=1`, for
comparisons (the same pictures as before).

The 87 places of every outdoor map, swept with the solids: card-tree 16,957 -> 0; fins, spikes, flat-blocked
cells, seams, steps and water as before; two places' far skyline (Route 105, the Safari Zone's south-west) leave a
little more sky between the crowns' outlines past the scene's edge, counted as holes there (looked at: not gaps
in the trees).

**Speed** (Mesa's software renderer, a 640x360 scene, Linux; no graphics card measured, so nothing claimed for
one): a solid crown is a few hundred faces where a cut-out was one, so only the tree cells on screen are drawn,
the nearest first, without the faces no camera of the field sees and with the faces looking away culled; the sun's
shadows are cast by the cut-outs as before.

| Place | Before (cut-outs) | Solids |
| --- | --- | --- |
| Petalburg Woods | 49 fps, 17 ms a frame, 132k vertices | 27-28 fps, 29 ms, 234k vertices (403 of 5,829 tree cells drawn) |
| Route 120 | 48 fps, 17 ms, 143k vertices | 40-45 fps, 18-20 ms, 149k vertices |

The densest wood costs the software renderer about 12 ms a frame more: it is bound by vertices there, which a
graphics card handles far faster, but that is not measured here. Phase D measures the walks again; if the owner's
PC shows the forests slower, the cut-outs can come back as an option (a setting), or far trees can be drawn
simpler.

Still flat: the ash-covered trees of Route 113, Route 114 and Fallarbor Town (the Fallarbor tileset's own
trees, laid out as the General tileset's dense forest), next.

### Phase C3, second part: the ash-covered trees, and trees cut by a wood's edge (2026-10-30 07:50-08:17; engine `f696f71a`)

The Fallarbor tileset's ash-covered wood is laid out as the General tileset's dense forest, in sixteen metatiles of
its own (on the ash and on the volcanic sand; inside a wood, beside open ground, at a wood's foot). Each is now
the quarter of a 2x2 tree it plays (worked out from how they lie beside and over one another on the three maps),
and stands as the same solid crown and trunk, the crown in the ash trees' colours (its outline, shade, leaf and
light as Route 113's trees draw them), on its own ash or sand.

A large tree's quarter whose other half or other row is not a tree - a wood's edge cut by a cliff, a house or a
map's border: 1.4% and 2.2% of the tree cells in the outdoor sweep - now rounds off on that side as at its outline,
not cut flat (seen from the side the cut-off half trees were slabs).

The 87 outdoor places, against `29c95198`: blocked cells drawn flat 7,435 -> 6,733 (Route 113 602 -> 107,
Route 114 444 -> 256, Fallarbor Town 81 -> 62); everything else as before, except that three places' low camera
(Lavaridge Town, Route 112, Route 114) now sees the neighbouring maps' ash crowns standing on the far skyline, and
the sky between them counts as holes there (looked at: no gap in the world; the check's holes are being made to
tell those skyline pockets apart).

What remains flat outdoors (6,733 cells), by the art (the most common metatiles drawn): the General tileset's
brown rock on level ground (about 900 cells: Route 120's and others' rock the rock bands did not reach), white
fences and posts (about 600), the volcanic and Lavaridge rock, Lilycove's railing, signs, the sea's boulders,
Mauville's posts, a Lavaridge tree, the Frontier's bushes: phase C4 (objects).

### Phase C4, first part: the General tileset's rock, and a truer check (2026-10-30 08:17-08:53; engine `18f6759f`, `88ab17f6`)

The General tileset's brown rock that no class stands - Route 120's long cliff painted on level ground (the audit's
R2), the Safari Zone's and the Battle Frontier's cliffs, the rock round Lilycove, the shore rock of Rustboro and
Routes 119, 125 and 126 - now starts and joins rock bands wherever it is blocked (the General tileset file's
"rockArt": the 26 metatiles a blocked cell drew flat in the sweep, not its cave mouths or white ledges; walked, the
same art stays ground). The painted cliffs are now rock walls a tile high along their art (pictures looked at:
walls along the drawing, not pillars); Route 119's plateau edge is its rock face where its cells lay dark and flat.

The check was also made truer, and the sweeps checked again with it:

- **Detail objects.** A blocked cell a detail object stands on (a fence, a sign, a lamp, a rock, a bush, a crate:
  the props) was counted as a blocked cell drawn flat. 1,351 of the outdoor maps' flat-blocked cells were such:
  fences 784, rocks 209, signs 135, crates and pots 110, bushes 69. They are now counted as objects.
- **The scene's far edge.** A pocket of the probe's sky that opens onto the scene's far edge (drawn wholly in the
  edge fog's colour) is past the loaded scene, not a hole; the solid trees on the far skyline left many such pockets
  between their crowns. Holes, places: baseline 60 -> 54, C1 31 -> 26, C2 9 (as it was).

The 87 outdoor places after C3 and now (the same check for both):

| Outdoors | fin | spike | flat-blocked | card-tree | walk-step | seam | water-wall | water-drop | hole (places) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C2 (`3ed7b0a2`, the old check) | 928 | 546 | 7,435 | 16,957 | 20 | 64 | 24 | 1,464 | 6 |
| C3 (`f696f71a`) | 928 | 546 | 6,733 | 0 | 20 | 64 | 24 | 1,464 | 7 |
| C4 rock (`18f6759f`), props counted as objects | 1,045 | 584 | 4,313 | 0 | 20 | 64 | 24 | 1,428 | 6 |

Of the 2,420 fewer flat-blocked cells, about 1,070 are this rock standing (Route 120 419 -> 146, the Safari Zone's
North 73 -> 10, Northwest 58 -> 3, Southwest 106 -> 3, Lilycove 155 -> 83, Mossdeep 186 -> 133) and 1,351 the
props now counted. The 117 more fin cells are those painted cliffs standing as one- and two-cell-thick ridges a
tile high. Linux and Mesa's software renderer only.

### Phase C4, second part: the volcano's rock, and the Lavaridge tileset's trees (2026-10-30 08:53-10:13; engine `f000fc64`)

The largest groups of blocked cells still drawn flat outdoors were the Fallarbor and Lavaridge tilesets' own rock:
the brown volcanic rock round Fallarbor and on Routes 113 and 114, Route 115's rock in the sea, and the pink rock of
Jagged Pass and Mt Chimney's summit. Their tileset files now list it as rock art (not their trees, sand, lava or
towns), so it stands as rock bands like the General tileset's. The 9 volcanic places, flat-blocked cells before and
after (pictures looked at for each):

| Map | flat-blocked | fin | spike |
| --- | --- | --- | --- |
| Fallarbor Town | 55 -> 8 | | |
| Jagged Pass | 190 -> 26 | 42 -> 21 | 34 -> 25 |
| Mt Chimney | 230 -> 76 | 47 -> 19 | 26 -> 9 |
| Route 113 | 81 -> 27 | | |
| Route 114 | 251 -> 59 | | |
| Route 115 | 79 -> 19 | | |
| Lavaridge Town, Route 112 | unchanged | | |

Standing that rock swallowed the trees drawn on it, which showed that the Lavaridge tileset's trees had never been
solid: they are the General tileset's large and small trees drawn with its own tiles on the volcano's ground, and
they were drawn as rock columns painted with the tree (Route 112's terraces) or as the tree painted flat. They now
stand as the solid trees do, with the General crowns, each cell showing the ground under it; a crown's top over the
cliff above keeps that cliff's height. The rules compiler stands each such tree on the walkable ground within two
cells of it (the level most of it meets, the lower of two), else on the rock's top: at the foot of the rock its cells
had joined, a tree stood in a pit up to three levels deep (seen on the first try, and fixed before this commit).

Probed against the build before (14 places: Route 112 five times, Jagged Pass three, Lavaridge Town, Mt Chimney, and
Route 113, Petalburg Woods and Routes 116 and 120 as controls):

| Map | flat-blocked | fin | spike |
| --- | --- | --- | --- |
| Route 112 | 110 -> 22 | 9 -> 6 | 28 -> 23 |
| Jagged Pass (three places) | 26 -> 14 | 21 -> 17 | 25 -> 16 |
| the controls | unchanged | unchanged | unchanged |

Route 113 is the same pixel for pixel; Petalburg Woods and Routes 116 and 120 differ only in their visible wild
Pokemon. Route 112 also got cheaper to draw - 12.4-12.8 frames a second before, 18.4-18.9 after, 1,083k vertices a
frame down to 555k - because the painted columns cost more than the solid trees. Linux and Mesa's software renderer
only: nothing here was measured on Windows or a graphics card.

Still flat outdoors after this, the largest groups: Mt Chimney's lava (its edge pieces), the white walls and curbs of
the Battle Frontier and Route 110's cycling road, Route 119's jungle trees (the Fortree tileset's), flower beds, and
the broken floor on Sky Pillar's top.

### Phase C4, third part: the low white walls (2026-10-30 10:13-10:31; engine `05136fb6`)

The General tileset's low white walls - along Route 110's cycling road, round the Battle Frontier's plazas and pools,
in Slateport and on Southern Island's dock - were painted on the ground: after the volcano's rock, the largest flat
groups left outdoors (the Frontier's two halves 777 flat-blocked cells, Route 110 356). They are drawn on the same
layer as the grass or paving beside them, so the detail objects learned to stand only one palette's tiles of a
drawing (the walls' stones) and to stand only where a cell is blocked: the same art is walked on Southern Island's and
Faraway Island's docks (6 cells), where it stays paint. The walls are now low blocks, under half a tile high.

The 10 places of Route 110, the Battle Frontier, Route 123, Slateport and Southern Island against the build before
(pictures looked at for each):

| Map | flat-blocked | fin |
| --- | --- | --- |
| Battle Frontier, west | 454 -> 292 | 80 -> 32 |
| Battle Frontier, east | 323 -> 254 | 14 -> 14 |
| Route 110 | 309 -> 135 | |
| Slateport City | 175 -> 161 | |
| Southern Island | 35 -> 27 | |

Spikes on the Frontier's west half went 15 -> 17. Linux and Mesa's software renderer only.

What this phase leaves, looked at and kept as it is: Mt Chimney's lava is flat because it is a liquid (56 and 18
cells of its two metatiles); Sky Pillar's top already stands its rubble, its flat cells are its floor; Route 119's
largest flat group (165 cells) is the river's blocked water art, which reads as water. The sea still lies a level
under the land (KNOWN_ISSUES E1: every map's sea on one level, so maps meet at their seams), which the check counts as
water-drop at every coast (1,428 cells outdoors); on beaches it reads as a low bank, not a box, and changing it would
move every coast, pier and seam - not done here. Fortree City's tree houses and Ever Grande's flower beds are left
for later.

### Phase C4, fourth part: the white walls of the other tilesets (2026-10-30 10:57-11:31; engine `8afd8a4e`)

The same white stones are drawn into other tilesets' metatiles, which stayed painted: Slateport's harbour and beach
walls, the Battle Frontier's walls round its plazas, pools and paths (its two halves' tilesets), Route 110's by the
water (the Mauville tileset) and Southern Island's and Faraway Island's docks (the Rustboro tileset). They stand as
the General tileset's do: only the stones' palette, only on blocked cells. The Frontier's half wall, half planter
(General `0x005`-`0x006`, 10 cells) is left out: as a block it hid the planter's bushes (seen in the pictures).

The probe over 19 places against the build before, pictures looked at for each:

| Map | flat-blocked |
| --- | --- |
| Slateport City | 161 -> 63 |
| Battle Frontier, west | 292 -> 195 (spikes 17 -> 13) |
| Battle Frontier, east | 254 -> 206 |
| Route 110 | 135 -> 127 |
| Faraway Island | 96 -> 90 |
| Southern Island | 27 -> 21 |

Fins unchanged. Linux and Mesa's software renderer only.

### The whole world again (sweep 2026-10-30 10:40-11:47; engine `05136fb6`)

The full sweep of the build with C3 and C4's first three parts (all but the walls just above): 534 of the 537 places
in one run, 3 games stopped. Two are the rooms that stop the game when warped into (the Union Room and the Battle
Tower's multi-battle partner room, as before). The third, the Battle Pike's normal room, waited for ever: the room
picks its trainer from the challenge's battle number when it is entered, which the game sets before it lets the
player in; warped in with none, the GBA's own loop never ends (`battle_pike.c` `PrepareOneTrainer`). Earlier sweeps
passed it only because places before it in the same game had set the number. Not reachable this way in play; the
probe now sets the number for that room (engine `0066c637`, test builds only) and drew it in 36 frames. The same
commit fixes the sweep cutting one place's cell dump short (Rustboro's flat, 3F): its runner compressed a dump
another game was still writing. That place was drawn again; 501 of the 503 maps are wholly seen, as after C2.

| Sweep | fin | spike | flat-blocked | card-tree | walk-step | seam | water-wall | water-drop | hole (places) | not-3d |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline (2026-10-29) | 2,038 | 1,135 | 26,304 | 16,957 | 72 | 64 | 45 | 1,528 | 54 | 2 |
| C2 (`3ed7b0a2`) | 1,761 | 936 | 20,558 | 16,957 | 72 | 64 | 24 | 1,535 | 9 | 2 |
| now (`05136fb6`) | 1,761 | 925 | 15,566 | 0 | 72 | 64 | 24 | 1,499 | 9 | 2 |

By kind of map (now; baseline in brackets): outdoors fin 941 (1,205), spike 546 (745), flat-blocked 3,077
(13,175), water-drop 1,428 (1,459), holes 6 places (38); rooms flat-blocked 9,263 (9,860); caves fin 789 (802),
spike 372 (383), flat-blocked 3,127 (3,170). The baseline's and C2's flat-blocked count every detail object's cell
(their dumps have no column for them); the check of C4's first part counts those as objects, about 1,350 cells
outdoors, so the outdoors' 13,175 -> 3,077 is about 8,750 cells now standing and 1,350 counted truly. The holes
column is the check of C4's first part for all three (the baseline's 60 was 54 with it).

What is left of flat-blocked: rooms 9,263 (their furniture and walls: C5), caves 3,127 (rock and boulders in the
caves' own tilesets), outdoors 3,077: the next ones are the Mossdeep tileset's round trees (Mossdeep City and Route
127's grove, 435 cells, painted flat), Fortree's trees and tree houses, Lilycove's and Route 121's iron fences,
Sootopolis's white ledges, Ever Grande's stone walls, and the boulders, Rock Smash rocks and Cut trees, which are
map objects drawn as upright cut-outs like the people.

### Phase E, first part: the Windows 3D job draws the world's showcase places (run 246, 2026-10-30 12:17-12:38)

The Windows package's 3D graphics job now runs the geometry probe in Windows game processes through Mesa's software
OpenGL (llvmpipe) on a hosted Windows runner: 14 places - those the owner's defects were seen at (Mossdeep's cliff,
the Safari Zone's pond and cliffs, Route 120's painted cliff, the forests and the volcano's trees, Route 110's and the
Frontier's walls, Sootopolis, Route 126's crater) and two caves - four cameras each, uploaded with the job's other
pictures. Run 244 stopped at the probe's first line (it reads the rules' header, which the job did not have; app
`ba318dc`); run 246 drew all 14 places (`done: 14 of 14 places`) and passed the job's own check of at least 56
pictures. What that shows: those places are drawn in a Windows process, by a software renderer, with the engine of
that hour (`0066c637`). Not shown: anything about a graphics card or the owner's PCs. The pictures were not looked
at from here (this environment cannot download the run's artifacts); they are in the run's
`EmeraldTogether-graphics-3d` artifact for 7 days.

### Phase C3/C4, more: Mossdeep's round trees, and the boulders, rocks and Cut trees (2026-10-30 12:18-12:56; engine `8e4ee6f4`, `c647a796`)

**The Mossdeep tileset's round tree** (Mossdeep City, the grove on Route 127's shallows, two on Route 128: 435 cells)
was painted on the ground. It now stands as the General tileset's trees do since C3: a solid crown with a trunk,
made from its own art - cut from the game's tileset when the tree texture is packed (no art added to the
repository). Where two of its trees overlap (a grove's rows stand a column apart), the cell is the lower tree's
upper quarter, as the GBA draws that crown over the other tree's trunk; each cell shows its own ground (grass,
rock, the shallows) and keeps the height the rules gave it - drawn as the shallows' art without that, the grove
stood on a box of water a level over the shallows round it (seen in the low camera's pictures, fixed before the
commit). The probe at 10 places against the build before: Mossdeep City flat-blocked 128 -> 24 (fins, spikes and
water walls as they were), Route 127 31 -> 1 (spikes 21 -> 13), the controls (Petalburg Woods, Routes 119 and 128)
unchanged. Left flat: Mossdeep's large three-wide tree (4 of them).

**Strength's boulders, Rock Smash's rocks and the trees Cut fells** are map objects the GBA draws as sprites; they
stood as upright cards like the people. Each picture of one now stands as a solid of voxels made from it, the way
the crowns are: as deep as a ball inside its outline, its art on its faces, leaning back as the crowns do, its depth
along the field camera's line of sight, so that from that camera it is its own picture and from any other it has
its volume. Two other ways were tried and dropped from the pictures: the sprite's dark outline as deep as the rest
(a dark rim round every rock and tree), and the depth level with the ground (boulders half again as tall as their
pictures). Probed at 10 places (Routes 104, 111, 114, 116, 120, Petalburg Woods, Rusturf Tunnel, Fiery Path,
Victory Road B1F, Seafloor Cavern); objects are not cells, so the cell checks are unchanged.

Linux and Mesa's software renderer only for both.

### Phase C4, fifth part: cave mouths cut into the rock, the Regi tombs' doors, Ever Grande (2026-10-30 13:40-14:40; engine `b4ce6755`, `00458735`)

**Cave mouths** were painted on. The GBA draws a mouth's dark arch over two cells: the mouth's own (a door walked
into) and the bottom of the rock's cell north of it. In 3D the mouth's cell was a gap in the mountain's face with
the arch on its floor, and the rock behind it a slope with the arch's top painted on - a dark shape, not an
opening. Now, where the rock north of a mouth rises at least a tile over the mouth's ground and there is rock on
both sides of it, that rock stands as an upright face and a tunnel is cut into it: half a tile deep, as wide as the
arch, its top following the arch's curve in the rock's drawing, dark inside. The mouth's cell stays the ground the
player stands on, so a walker going in or coming out is never inside the rock. Found by the probe's pictures and a
sheet of all 63 doors walked into on outdoor maps (scratchpad `c4/mouths-all.png`, game art): about 23 are cave
mouths, the rest doors into buildings and gaps between trees, which are not touched. Seen cut in: Routes 106 and
116, Verdanturf, Victory Road's mouth in Ever Grande, Mt Pyre, Meteor Falls (its face rises from two levels under
the mouth; a light seam crosses its opening). **Left as they were**: Route 110's mouth, Shoal Cave's, the Fiery
Path's and the Cave of Origin's - there the rock does not rise over the mouth's ground (the heights' solve puts the
mouth on the rock's top level, or the cell over the mouth is ground), so there is nothing to cut into; that is the
levels' work (MS-162's kind).

**The Regi tombs' doors** (Routes 105, 111, 120) are rock walls until the Sealed Chamber is solved: a script
redraws them on the map's load, collision on. The 3D rules were made for the open door, so the shut door lay flat
- a notch through the mound with the wall's picture on its floor (the "ghost doorway" in the pictures). A cell a
script redraws that the game blocks, with a mountain's rock on both sides at its ground, now stands as that rock.
All three tombs are whole in the pictures.

**Ever Grande City**: the round bushes beside the League's path stand as bushes and the garden's stone wall as a
wall - its cobbled top a block a tile high, its dark front standing at its foot.

Linux and Mesa's software renderer only.

### Phase D, first part: speed (2026-10-30 13:05-15:00; engine `a367e474`, `299a5b04`, `c8037c2a`)

The same 12 places with the build from before step 16 (the baseline's, `9f032173`) and the current one, one game at
a time: the player standing at each place for 1,200 game frames, the game's own profile (frame time, vertices a
frame) every two seconds, the median over the windows after the map has loaded. Mesa's software renderer
(llvmpipe) on 4 processor cores: it does a graphics card's work on the processor, so every vertex a change adds
shows. A graphics card does the same work far faster; **nothing is claimed for one** (phase E's frame-time lines are
for that).

**A first comparison was wrong and is not used**: three game processes left over from earlier test runs (a timeout
had ended their `xvfb-run`, not them) held about three of the four cores while it ran. They were stopped, and the
measuring scripts now run each game in its own process group and end the whole group (scratchpad `trees/perf.py`,
`c4/longwalk.py`). The runs below had the machine to themselves. Run to run the same build differs by up to about
8% (the build before step 16 at Petalburg Woods: 43.8 and 40.2 frames a second in two passes), so differences that
small say little.

Frames a second (vertices a frame); "before phase D" is step 16's work up to `c647a796` with the far trees as
cut-outs past 9 tiles, measured in an earlier pass with its own "before" column:

| Place | before step 16 | before phase D | change | now | change |
| --- | --- | --- | --- | --- | --- |
| Battle Frontier, west | 36.9 (221k) | 18.8 (474k) | -46% | 22.2 (345k) | -40% |
| Sootopolis City | 46.8 (65k) | 29.4 (225k) | -34% | 30.5 (193k) | -35% |
| Route 120 | 42.5 (134k) | 31.6 (166k) | -24% | 32.1 (150k) | -24% |
| Mossdeep City | 32.9 (214k) | 25.4 (356k) | -18% | 27.5 (323k) | -16% |
| Route 110 | 40.5 (153k) | 33.2 (196k) | -18% | 37.9 (151k) | -7% |
| Petalburg Woods | 38.8 (132k) | 36.9 (149k) | -16% | 39.5 (109k) | +2% |
| Fortree City | 32.5 (114k) | 27.2 (114k) | -15% | 28.3 (86k) | -13% |
| Lilycove City | 25.0 (181k) | 20.5 (299k) | -15% | 20.2 (282k) | -19% |
| Slateport City | 25.0 (349k) | 25.3 (387k) | +0% | 24.6 (325k) | -2% |
| Route 104 | 23.9 (239k) | 25.9 (204k) | +5% | 28.0 (199k) | +17% |
| Route 119 | 23.8 (214k) | 25.6 (198k) | +8% | 29.2 (164k) | +23% |
| Route 112 | 11.9 (1050k) | 16.1 (503k) | +38% | 17.3 (415k) | +45% |

What was done, from where the vertices went (the terrain chunks a place builds, `PKMN_DIORAMA_CHUNK_LOG=1`, and the
per-pass profile):

* **Walls and hedges** (`a367e474`): every block prop - the white walls of Slateport, Route 110 and the Frontier, the
  hedges, the stone walls - was drawn with the slab's mesh, 66 quads whatever its art. Each art piece now has a mesh
  of its own: its top one quad and its sides only along its outline (a whole wall piece is 5 quads). The probe's
  pictures of the walls look as before.
* **Far trees** (`299a5b04`): a tree more than 6 tiles from where the camera looks is its cut-out with its trunk.
  From the field's cameras the cut-out is the solid's front: the pictures of the woods at 6 tiles and at 9 look the
  same. Petalburg Woods with every tree solid: 30.7 frames a second; at 6 tiles 41.1 (before step 16: 43.8).
* **The mountains' slopes in steps of two voxels** (`c8037c2a`): the rock that stands since C1 and C2 is most of the
  terrain's new cost - Sootopolis's crater went from 300 cells of mountain rock to 2,334, its terrain from 207k to
  422k vertices. In steps of two: 370k there, Lilycove 224k -> 206k, Mossdeep 366k -> 329k, Route 120 206k -> 196k,
  the Frontier's west 254k -> 236k; the pictures look the same side by side, enlarged.

**What is still slower on the software renderer**: the places whose rock now stands - the Frontier's west (-40%),
Sootopolis (-35%), Route 120 (-24%), Lilycove (-19%), Mossdeep (-16%) - and Fortree (-13%). There the terrain
pass takes two to three times its old time (the Frontier's west 4.3 -> 13.5 ms a frame, Mossdeep 3.9 -> 7.3), far
more than its terrain's vertices grew (+52%, +10%), so the vertices are not the whole cost; the next look is per
pass (the profile now counts each pass's draws and vertices), then a lighter mesh for far terrain if it is them.
Faster than before: Route 112 (+45%: its trees were voxel hulls), Route 119 (+23%), Route 104 (+17%); level:
Petalburg Woods, Slateport, Route 110 (-7%).

**A long session** (the 12-town loop of 2026-10-26 again, engine `99dee3de`'s build: 12 towns 15 times in one game
process, 180 places, 627 profile windows, L): frames a second by round 12.5 (the first: first loads), then 13.3 to
15.2 with no trend (the last 14.3); the busy frame's processor time 52.9 ms in the first round, 42.5 to 49.7 after,
45.9 in the last; each town's first three rounds against its last three: some up, some down, none steadily; memory
in use 302 -> 304 MB, the game's graphics memory 61.4 -> 62.9 MB (108 textures, 1,042 buffers throughout). What
grows over a session is not a frame's cost here; on the owner's PC that is still to be seen (phase E).

### Phase C3, more: Fortree's palms (2026-10-30 14:40-15:20; engine `99dee3de`)

Fortree City's five palms - the three-wide crowns outside the tree houses - lay flat among the solid trees, fronds
painted over the forest. They stand now as Birth Island's round trees do: the fronds a heap of leaves lifted on the
trunk, the frond tips of the row north of them its back, the trunk standing up under them (the probe's pictures:
the crowns over the canopy; the trunk reads a little boxy, mostly hidden among the trees). The tree houses' crowns
are their buildings' and were already modelled.

### Phase E, second part: the 3D view's speed in a player's own log (2026-10-30 15:00-15:20; engine `69db86a5`, `83b05b40`)

Nothing about a graphics card is claimed from this environment. So that the owner's PC can say it without any extra
step, the game now writes a line to its log whenever the map changes and when it closes: the 3D frames on that map,
the median time from one to the next, the time 95 in 100 came within, the slowest, and the graphics card's name as
the driver gives it - for example, here, `frame times on map 0.9: 61 frames in 3D, median 34 ms, 95% within 106 ms,
slowest 150 ms (llvmpipe ...)`. The launcher keeps the game's output as each launch's `runtime.log`, the file already
asked for about the crash (MS-169), so the owner's next log of normal play carries real numbers for the maps played,
and a long session's lines show whether frames grow slower. The profile (`PKMN_DIORAMA_PROFILE=1`) now also counts
each pass's draws and vertices, which showed that the Frontier's remaining cost is the terrain (173k vertices a
frame) and its rounded props (104k: the mounds' meshes, a quad a pixel on top - the next to merge).
