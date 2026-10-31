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

### Phase D, second part: the terrain drawn three times, and the props in runs (2026-10-30 15:30-17:30; engine `190f7176`, `ff6f8528`)

The per-pass profile (phase E's second part) said where the Frontier's west side spent its frame: the terrain
173k vertices, the props 104k. Both had a cause that was not the new geometry itself.

* **The terrain was drawn three times a frame** (`ff6f8528`). After the picture, the terrain renderer drew every
  chunk on screen twice more, with colour and depth writes off, to mark the stencil: where water reflects (the
  objects' reflections are drawn only there) and where the terrain shows pixel colour (the layer-3 models, which
  an object in front of is drawn over). The shader keeps only those pixels, but every triangle was still shaded and
  filled in both passes: the 173k were 58k three times. Each chunk now keeps, after its own indices, the two short
  lists of triangles those passes can mark, and they draw only those, nothing for a chunk with none. The marks are
  the same by construction - a triangle the lists leave out is one the shader leaves out whole - and the probe's
  pictures at 12 places with reflecting water, ice and pixel models (Sootopolis, the Safari Zone, Routes 117, 120
  and 123, Southern Island, Shoal Cave's ice room, Mossdeep, Fortree, Route 110, the Frontier) differ from the
  build before only where flowers, water, tall grass, the map's name and wild Pokemon moved; Sootopolis's and the
  Safari Zone's are the same to the pixel. This was in the build before step 16 too; the taller terrain of step 16
  made it cost more.
* **Rounded props in runs** (`190f7176`): a mound prop (round bushes, rock heaps, the sea rocks, Fortree's fronds)
  was a quad for each pixel of its top and one for each side of a pixel over a lower neighbour; the round bushes by
  the Battle Tower were 1,932 vertices each, and the 34 seen from the Frontier's west 66k of its props' 104k. A
  run of a row's pixels at one height is now one quad, and the sides go in runs as a wall's do: 1,284 vertices a
  bush, the Frontier's props 71k. The probe's pictures (the Frontier's east and west, Ever Grande, Granite Cave,
  Mossdeep, Fortree) differ from the build before only where the water, the flowers and a wild Pokemon moved.

The same 12 places, measured as in the first part (L, Mesa llvmpipe on 4 otherwise idle cores; medians of the
profile's windows after the map has loaded; frames a second, vertices a frame in brackets). The first three columns
are the first part's last pass; the last three a new pass with its own "before" column, the build before step 16
measured again in the same run:

| Place | before step 16 | step 16 at `b4ce6755` | change | before step 16 (again) | now (`ff6f8528`) | change |
| --- | --- | --- | --- | --- | --- | --- |
| Battle Frontier, west | 36.9 (221k) | 22.2 (345k) | -40% | 32.0 (221k) | 36.6 (196k) | +14% |
| Sootopolis City | 46.8 (65k) | 30.5 (193k) | -35% | 41.3 (65k) | 48.0 (84k) | +16% |
| Route 120 | 42.5 (134k) | 32.1 (150k) | -24% | 42.9 (134k) | 49.8 (80k) | +16% |
| Mossdeep City | 32.9 (214k) | 27.5 (323k) | -16% | 31.8 (214k) | 43.2 (201k) | +36% |
| Route 110 | 40.5 (153k) | 37.9 (151k) | -7% | 36.3 (153k) | 48.2 (119k) | +33% |
| Petalburg Woods | 38.8 (132k) | 39.5 (109k) | +2% | 45.5 (132k) | 59.3 (71k) | +30% |
| Fortree City | 32.5 (114k) | 28.3 (86k) | -13% | 33.6 (114k) | 34.9 (101k) | +4% |
| Lilycove City | 25.0 (181k) | 20.2 (282k) | -19% | 26.0 (181k) | 40.0 (138k) | +54% |
| Slateport City | 25.0 (349k) | 24.6 (325k) | -2% | 25.1 (349k) | 35.3 (236k) | +41% |
| Route 104 | 23.9 (239k) | 28.0 (199k) | +17% | 22.6 (239k) | 38.5 (98k) | +71% |
| Route 119 | 23.8 (214k) | 29.2 (164k) | +23% | 25.0 (214k) | 43.0 (102k) | +72% |
| Route 112 | 11.9 (1050k) | 17.3 (415k) | +45% | 11.9 (1050k) | 34.4 (190k) | +190% |

**Now no slower than before step 16 at any of the 12 places** on this renderer. The build before step 16, measured
in both passes, differed by up to 17% (Petalburg Woods 38.8 and 45.5, the Frontier's west 36.9 and 32.0,
Sootopolis 46.8 and 41.3), so only the larger differences say something:

* Clearly faster: Route 112 (+190%: its trees were voxel hulls), Route 119 (+72%), Route 104 (+71%), Lilycove
  (+54%), Slateport (+41%), Mossdeep (+36%), Route 110 (+33%), Petalburg Woods (+30%), Route 120 (+16%, both
  "before" passes 42.5 and 42.9).
* Level, within what the same build varies: the Frontier's west (36.6 now; 36.9 and 32.0 before), Sootopolis (48.0;
  46.8 and 41.3) and Fortree (34.9; 32.5 and 33.6) - where step 16 stood the rock up (the Frontier's west,
  Sootopolis's crater) or made the trees solids (Fortree).

The marking fix would have made the build before step 16 faster too; the comparison is the player's - the game
before step 16 against the game now. Where the frame goes now (the per-pass profile): the Frontier's west 58k
terrain, 71k props, 64k buildings; Slateport's props 181k: 251 upright slabs (the signs, lamps and fences' form,
66 quads each whatever its art, as the walls were before `a367e474`: 99k) and 49 rounded heaps (74k) - the next
to look at if a graphics card needs it.
Nothing here says how fast a graphics card is (phase E's frame-time lines are for that).

### Phase C5, first part: the furnished rooms (2026-10-30 17:50-18:40; engine `131de763`)

The depth audit of 2026-10-28 (MS-164) listed 35 rooms whose furniture the generic 3D rules leave as a picture on
the floor: the Battle Frontier's nine lounges, six lobbies, the Pike's corridor and three-path room, the Exchange
Service Corner, the Ranking Hall, the reception gate and Scott's house; the Hall of Fame, the Department Store's
rooftop, the Mauville bike shop, the two Game Corners, the diving treasure hunters' house, Devon Corporation's 1F,
the Safari Zone's rest house, the Sootopolis Mystery Events house; Ever Grande City's five halls - 26 layouts (the
lounges share two, the halls two; Mossdeep's Game Corner B1F was taken with its 1F).

The tool that models the rooms battles are fought in (`tools/battle_env/auto_rooms.py`: each room read off its
cells - walls, edges, furniture - every piece built as a model and proved against its drawing, then the room with
every piece standing in it proved against the room's drawing, pixel for pixel; `--repair 3` leaves out the pieces
whose cells differ) proved 23 of the 26. Its own two pictures of each (a battle camera and a field camera) looked
right. **The game's pictures did not all agree**: the geometry probe took the 23 rooms from the field's cameras
with the build before and with them modelled, and six looked worse or wrong - the Battle Arena's lobby (its wooden
stage's edge stood as tall walls), the Battle Palace's lobby (its back wall broke into slabs), the two lounge
layouts (only their walls stood: the sofas the audit meant stay pictures), the reception gate (its stools stood as
glass boxes, and a counter cell drew a piece of the Factory's lobby), the Sootopolis Mystery Events house (its table
stood as a cabinet). They are not taken. A room's pieces also stand in the other listed rooms that repeat them, so
the list is proved as a whole; without those six, five more no longer proved (the Factory's lobby, Scott's house,
the Pike's three-path room, Mossdeep's Game Corner B1F, the diving treasure hunters' house). Not proved at all: the
Battle Dome's lobby, the Exchange Service Corner, Devon Corporation's 1F.

**Twelve rooms are modelled now** (`battle_room_specs.AUTO_ROOMS`, proved together with no repair: 12 of 12, every
model exact): the Battle Pike's lobby (its chairs) and corridor (its chairs and pedestals), the Battle Pyramid's
lobby (the stair rails, the pools' edges, the torches and the back wall), the Ranking Hall (its record machines),
the Hall of Fame (its machine and back wall), the Department Store's rooftop (planters, benches, vending
machines), the Mauville bike shop (its counters; the bikes stay pictures), the Mauville Game Corner (slot machines,
chairs, roulette tables, the prize counter), Mossdeep's Game Corner 1F (the counter, the tables), the Safari Zone's
rest house (its walls; the table and chairs as before), and Ever Grande's halls (their back walls only - **their
stairs and railings are a level change the room tool does not make, and stay drawn on the floor**, MS-172).

Evidence (L, the 3D test build, Mesa): the probe's pictures of all 23 rooms before and after - the twelve as looked
at, the eleven not taken the same as before to the pixel (the reception gate but for an NPC's "!" bubble);
check-diorama passed; the building tool's tests 39 passed. Of MS-164's 35 rooms, the furniture now stands in
eight (the Pike's lobby and corridor, the Pyramid's lobby, the Ranking Hall, the Hall of Fame, the rooftop, both
Game Corners) and partly in the bike shop (its counters, not its bikes). MS-164 stays open for the rest: the nine
lounges' sofas, the Dome's, Arena's, Palace's and Factory's lobbies, the reception gate, the Exchange Service
Corner, Scott's house, the Pike's three-path room, the diving treasure hunters' house, Devon Corporation's 1F, the
Safari Zone's rest house (its table and chairs), the Sootopolis house, the bike shop's bikes and the five halls'
stairs.

### Phase E, third part: the Windows builds stopped, and built again (2026-10-30 17:32-17:49; engine `ee84a646`)

The Windows package's run 248 (dispatched for the Rotom Catalog) stopped at its build: `299a5b04` (phase D's far
trees) named a loop variable `far`, and Windows' headers define `far` and `near` as nothing, so MinGW read
`int ;`. Every Windows build of the engine from `299a5b04` until `ee84a646` stopped there (run 248 was the first
since); the Linux builds have no such macro. The variable is `distant` now (`ee84a646`); the Windows 3D game, the
Classic 2D game and both test builds were built here with MinGW and the pinned SDL 2.30.7, and run 249's build job
passed on GitHub's runner.

### The building models went stale in the local builds (found 2026-10-30 19:10; engine `5ea03aec`)

The sky at the foot of the Pokemon League's west side (the probe's magenta, 181 pixels from the Adventure camera)
was not the League's: the building search reads `props.c` (a detail object beside a building is not the building's
cell), but the build did not list `props.c` among the models' inputs. When `00458735` made Ever Grande's garden
wall a prop, the incremental 3D builds kept the building models made at 01:51 that morning - the League still
claimed the wall's cells beside it, and neither stood there. The models are made again now when `props.c` or the
metatile behaviours change; with them made again the gap is gone (0 pixels; the steep view's two thin lines at the
League's back corners, 106 pixels, remain). A fresh build - CI's and the package's - was never stale. **The local
builds from 10:31 to 18:04 used the stale models** (`props.c` changed at 10:31, 11:36, 14:37 and 15:22: the white
walls, Ever Grande's wall and bushes, Fortree's palms), so their pictures and phase D's speed passes may differ from a
fresh build wherever a building meets one of those props; the step's last sweep and speed check are taken with fresh
models.

### Phase C5, second part: roofs (2026-10-30 21:45-22:10; engine `cca519e8`)

"Most route houses keep a flat roof" (section 3) was checked building by building. The hand-made models (the
3DS project's houses, Centers, Marts, the labs) carry real hipped roofs. Of the 107 buildings modelled from their own
drawing (`auto_buildings.py`), 82 have a real roof (pitched, domes, cones, pyramids, tents, parapets) and 25 kept
their drawn roof laid flat on top: sixteen are the Battle Frontier's modern blocks, three were left so on purpose
(the Weather Institute, the Cove Lily Motel, the Battle Tower's own roofs) and one is a Mauville house the search
draws with its neighbour. Of the rest, five are drawn by the GBA with a flat roof inside a raised rim - Route 110's
two Cycling Road gatehouses, the gatehouse on Route 111 to Route 112, the glass workshop and Lanette's house - and
take the roof tool's "flat" roof now: the drawing on top and a parapet standing round the edge. Each proves exactly
against its drawing; the probe's pictures show the parapets and nothing else changed. **Lavaridge's Gym was tried
with a pitched roof and not taken**: the roof the drawing gave covered only the part over the door and left its lower
wing flat beside it. The three "route houses left flat" in the building tool's log (Routes 112, 114, 115) are not
houses: they are doors in cliff faces (the Fiery Path's on Route 112, Meteor Falls' on Routes 114 and 115), which the
tool rightly leaves to the rock.

### The whole world again, with fresh building models (sweep 2026-10-30 21:42-22:42; engine `5ea03aec`)

The same 537 places as the sweep of 10:40 (the probe, 4 cameras each), now with the building models made again
(the earlier local sweeps had the 01:51 models): 535 of 537 places, 501 of 503 maps - the Union Room and the Battle
Tower's multi partner room stop the game when the probe warps straight into them, as at 10:40 (a scripted room
entered without the state a player arrives with). Against the 10:40 sweep (engine `05136fb6`):

| Check | 10:40 | now |
| --- | --- | --- |
| flat-blocked (all) | 15,566 | 14,284 |
| ... outdoors | 3,077 | 2,582 |
| ... rooms | 9,263 | 8,476 |
| ... caves | 3,127 | 3,127 |
| fin | 1,761 | 1,757 |
| spike | 925 | 919 |
| water-drop | 1,499 | 1,499 |
| walk-step | 72 | 72 |
| seam | 64 | 64 |
| water-wall | 24 | 24 |
| holes to the sky (places) | 9 | 9 |

The holes are the same nine places; the largest are at Battle Palace's battle room (81 pixels from the Adventure
camera), New Mauville's entrance (56) and Fortree City (112 from the Diorama camera: at one tree house's sides under
its canopy - a floor under the canopies was tried and did not change it). Seams and walk-steps are MS-162's (phase
C1); fins and spikes the rock that stands; the rooms' flat-blocked their furniture and walls (phase C5).

### Phase F: the evidence (2026-10-30 23:20-23:40)

**The whole world, before step 16 and now** (the probe's check over the same 537 places: the baseline of phase B,
engine `9f032173`, against the sweep of 21:42 with fresh building models, engine `5ea03aec`; Linux, Mesa):

| Check | before step 16 | now | outdoors before | outdoors now |
| --- | --- | --- | --- | --- |
| card-tree (a tree as a flat cut-out) | 16,957 | 0 | 16,957 | 0 |
| flat-blocked (a blocked cell drawn flat) | 26,304 | 14,284 | 13,175 | 2,582 |
| fin (rock standing over both neighbours, in runs) | 2,038 | 1,757 | 1,205 | 937 |
| spike (the same, alone) | 1,135 | 919 | 745 | 540 |
| hole (places with the sky showing through) | 54 | 9 | 38 | 6 |
| water-wall (water standing over its banks) | 45 | 24 | 42 | 24 |
| water-drop (land far over the water beside it) | 1,528 | 1,499 | 1,459 | 1,428 |
| seam (map edges a level apart) | 64 | 64 | 64 | 64 |
| walk-step (a step walked over with no stairs) | 72 | 72 | 20 | 20 |

The per-map list - every map, its places, how much of it they reached and each check's count - is
`docs/3d-geometry-report-20261030.md`.

**The owner's six defects, before and after** (sheets of the probe's pictures, the same place and camera from the
two sweeps side by side; game art, kept in the scratchpad `c6/evidence/`, not committed). What each sheet shows, and
where it shows little, what the counts say:

1. *Tall, narrow, rectangular cliffs* - Mossdeep City (the Diorama camera): the cliff that stood as a row of
   pillars is one band of rock between its two grounds. Outdoors fins 1,205 -> 937, spikes 745 -> 540.
2. *Inconsistent cliff heights, Route 120's cliff painted flat* - at the sweep's places on Routes 120 and 111 the two
   sweeps look much alike from these cameras; the painted cliffs standing are phase C4's first part's pictures, and
   outdoors flat-blocked fell 13,175 -> 2,582.
3. *Flat trees and vegetation* - 16,957 cut-out tree cells -> 0. Route 113 (sheet 4): its ash-covered trees, flat
   before, stand as solids. Petalburg Woods and Route 119 look much alike at this distance: General's trees were
   partly voxel trees already.
4. *Abrupt height transitions* - Route 104 looks much alike; walk-steps 72 -> 72 (most in caves, where a cave's
   elevations meet without stairs) and the sea still lies a level under every coast (E1's choice): **open**.
5. *Large featureless blue rectangles* - Route 110: its cycling road's low white walls stand; water standing over
   its banks 45 -> 24.
6. *Seams and gaps* - holes to the sky at 54 places -> 9: Route 113's and Route 118's, magenta in the baseline's
   pictures, are gone. **Still open**: the four seams (the Battle Frontier's halves - a visible one-level step;
   Mauville with Route 111; the Safari Zone's two), MS-162; seams 64 -> 64.

What is left is listed with its map and place: the per-map list above, KNOWN_ISSUES MS-162 (the seams), MS-164
(the rooms' furniture), MS-172 (what step 16 leaves flat or simplified), and this file's phases.

**Speed, the last check** (the same 12 places, the build before step 16 against `cca519e8` with fresh building models,
one game at a time; medians; L, Mesa llvmpipe, 4 cores). The machine ran slower overall than at 17:25 (the "before"
build too), and the first five places of this pass overlapped work of mine (the evidence sheets), so those five were
measured again with nothing else running; the table has the idle pass for them:

| Place | before step 16 | now (`cca519e8`) | change |
| --- | --- | --- | --- |
| Battle Frontier, west | 28.6 (220k) | 31.5 (191k) | +10% |
| Sootopolis City | 37.8 (64k) | 42.8 (83k) | +13% |
| Route 120 | 34.7 (134k) | 40.9 (80k) | +18% |
| Mossdeep City | 31.2 (213k) | 38.5 (200k) | +23% |
| Route 110 | 33.7 (152k) | 44.1 (118k) | +31% |
| Petalburg Woods | 35.5 (131k) | 46.5 (70k) | +31% |
| Fortree City | 30.8 (113k) | 28.6 (100k) | -7% |
| Lilycove City | 20.9 (180k) | 30.1 (137k) | +44% |
| Slateport City | 22.7 (348k) | 29.3 (235k) | +29% |
| Route 104 | 20.3 (238k) | 33.0 (97k) | +63% |
| Route 119 | 22.2 (212k) | 33.8 (101k) | +52% |
| Route 112 | 11.1 (1049k) | 29.3 (189k) | +164% |

Faster at eleven places; Fortree -7% here, +4% at 17:25 - level within the spread (the same build up to 17% apart in
two passes). The software renderer only: nothing about a graphics card.

### Phase E, fourth part: the Windows 3D job with step 16's last parts (run 250, 2026-10-31 00:00-00:22; engine `cca519e8`)

The Windows package's 3D graphics job again (`only`: graphics-3d), with the engine of step 16's last parts
(`cca519e8`: the fresh building models, the parapets): the probe drew all 14 showcase places in Windows game
processes through Mesa's llvmpipe (`done: 14 of 14 places`) and passed the job's check of at least 56 pictures; in
the same job the Mega Evolution picture series and parade passed, and the 3D view ran 14.5 frames a second at
1280x720 on the runner's 4 cores (informational). What that shows: those places are drawn in a Windows process by a
software renderer with this engine. Not shown: anything about a graphics card or the owner's PCs. The pictures were
not looked at from here (the artifact store's host is not allowed by this environment's network policy); they are in
run 250's `EmeraldTogether-graphics-3d` artifact for 7 days.

### After the owner's look at the update (2026-10-31 03:30-04:40; engine `5169d96c`)

The owner installed run 253's build and found two things that looked worse than before: Lilycove's cliffs by the
Department Store "look like walls", and the Mauville Game Corner's furniture ("if ur gonna 3d everything at least make it
look nice"). Pictured against the build before step 16, both were step 16's: C1's rock bands stood a band of rock that
parts no levels as a ridge a tile over the ground on both sides of it, and where the GBA paints a cliff on level ground
(Lilycove, Route 120, Fallarbor, Route 121, the Safari Zone) that is a wall, the stairs sunk between two of them; C4's
rule for the General tileset's brown rock (`18f6759f`) stood more such cliffs; and C5's twelve rooms (`131de763`),
proved exact from the GBA's camera, showed from the game's camera boxes with their drawing smeared down them, the Game
Corner's counter hiding its clerks. The metric step 16 worked to - blocked cells drawn flat - counted the painted cliffs
as defects; drawn flat with the GBA's perspective they read as cliffs, stood up they read as walls.

The fix (`5169d96c`): a thin band (no cell more than two in from its edge) that parts no levels, on land more than in
water, lies as drawn, as before step 16; `18f6759f` and `131de763` are reverted. Bands between two levels (Mossdeep's
cliff, one face where it was pillars), mountains and rocks in the sea stand as step 16 made them. The probe at 53 places
(the 35 the changes touch, 18 more towns and routes), four cameras, against the build before step 16 and run 253's:
the cliffs and the rooms as before step 16; Mossdeep, Routes 119, 125 and 126 and Ever Grande keep step 16's fixes, their
holes closed. The owner was sent the before/after pictures of Lilycove, the Game Corner, the Safari Zone and Route 120.
check-diorama, test_compile_rules (35) and test_rock_bands (11) passed. Linux, Mesa's software renderer only. The
counts of phase F (flat-blocked cells and the rest) are those of `cca519e8`, before this; the furniture of MS-164 is
open again for the twelve rooms.
