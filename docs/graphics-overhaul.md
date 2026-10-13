# Graphics overhaul: from the GBA's board to a 3D diorama world

Owner directives 2026-10-10: "CRITICAL CLARIFICATION - ACTUAL 3D GRAPHICS ARE
REQUIRED" and "MAJOR GRAPHICS OVERHAUL - TRANSFORM OUR POKEMON GAME INTO A
BEAUTIFUL 3D DIORAMA WORLD". Reference: ZallaxDev/pokeemerald-3Ds-dualscreen
(`4a699e3`, its voxel world code) and ZallaxDev/pokeemerald-voxel-project (the
Diorama renderer we started from). Engine branch `claude/graphics-overhaul` (from
`claude/native-graphics` `b86ea813a`); every step is checkpointed and the old look
stays reachable while the new one is not finished.

Battle presentation (the directive's phase 6) is the 3D battle session's work
(`docs/battle-3d.md`); the overworld changes keep its interfaces.

## Where we start (measured 2026-10-10, screenshots in the cloud workspace)

| Area | Today | Gap to the directive |
| --- | --- | --- |
| Camera | Default (owner's B): the 3DS framing, 40 degrees, about 10 tiles top to bottom; follows the GBA camera exactly; F7 switches to the voxel project's wide view (pitch 40.5, focal length 130: about 30 tiles, a strong perspective) | The wide view is the "tiny floating board" (the scene ends in black 16 tiles from the camera). No smoothing, no look-ahead, no ground following, the eye always 16 tiles up whatever the zoom (zoom changes the lens, not the distance). No photo camera. |
| World extent | 33 x 33 cells round the camera, from the game's own map grid (the map and 7 tiles of its connections); a neighbouring map shows only where it shares both tilesets; past that the border block, past the cells nothing (clear colour almost black) | KNOWN_ISSUES V20: hard board edges in every wider view; towns next to routes with other tilesets (Rustboro, Slateport, Mauville...) do not appear until crossed. The 3DS project places the current map, its connections and theirs (static layouts) and fills the rest with the border block, up to 44 tiles out. |
| Maps in 3D | All 518 maps are in the rules, but a map whose weather the 3D view does not draw falls back to the flat 2D view: Petalburg Woods (shade), underwater (bubbles), and any map while a sandstorm, thunderstorm, snow, drought or downpour runs | Petalburg Woods is flat 2D: the one forest the directive names. |
| Terrain | GBA metatile art on flat cells; cliffs, ledges and terraces from the Diorama's rules; tall grass and flowers as voxel/pixel objects | Repetitive GBA texture tiling on large grass areas; no ambient occlusion, no material variation, edges of paths and grass are the GBA's hard tile edges. The 3DS project's relief (cliffs and stairs lifted to the height the art implies) is not ported. |
| Trees | 3DS project's trees (owner's B): two-sprite crown + trunk billboards, one model, in the map's own grid | Every tree identical and on the grid; no size/colour/lean variation, no sway; forests read as rows. |
| Buildings | 475 models generated from our maps with the 3DS generator, coloured from the live palettes | Boxy at the default distance; roofs are the GBA roof art on a slope; no window light at night. |
| Light | Fixed sun in the northwest, one 2048 shadow map, ambient 0.70; the 3DS weather light (warm sun, cool shade, haze); dapples, dust, rays, bloom; saturation 1.30 grade | No soft shadows, no ambient occlusion, no sky light, no tone mapping; the sun never moves with the time of day. |
| Day/night | The game's palette tint (the GBA look), half-strength sun at night | No warm evening sun, no long shadows, no lit windows or lamps. |
| Water | GBA animated water tiles, reflections of sprites | No surface shading, highlights or shoreline. |
| Sprites | Leaning cards (crisp, nearest-neighbour), round contact shadows, cast silhouettes along the sun, occlusion by buildings/furniture | Mostly in place; scale follows the GBA; no per-light tint besides the ground's. |
| Speed | Software GL only (5-8 fps at 720p-1080p); no real GPU number yet | The owner's `benchmark.log` is the reference. |

The 3DS reference screenshots (README of the 3DS project) are on imgur, which this
workspace's network blocks; the comparison uses its source code (camera, world,
lighting constants) and our own renders of its models until the owner supplies
screenshots or a capture.

## Order of work

Phase 1 - camera and world presentation (first):

1. A camera module: the **Adventure camera** (default) - the 3DS framing (about
   11 tiles top to bottom at the player, 42 degrees, a moderate 33 degree lens),
   smoothed follow with a little look-ahead, the eye following the ground's height;
   the **Diorama camera** (F7) - higher, wider, a long lens for the miniature look;
   the **Photo camera** (F9) - free zoom and tilt, the game paused, the 2D layer
   hidden, F12 saves a PNG. Zoom keys stay, within each camera's limits.
2. A larger scene: 49 x 49 cells instead of 33 x 33, connected maps' cells where
   their art can be drawn, the border block beyond, and a world-edge fog into a sky
   colour that follows the time of day and weather, so no view ends at a board's
   edge.
3. Every weather in 3D (shade first: Petalburg Woods).
4. Later in phase 1: neighbouring maps with other tilesets drawn from their own
   tiles and palettes (the 3DS project's static-layout instances).

Phase 2 - geometry: terrain variation (noise-based tint, edge blending, ambient
occlusion at cliff feet and walls), tree variety (size, tint, lean, sway; forest
floor shadow), the 3DS project's relief for cliffs and stairs, building detail.

Phase 3-4 - light and environment: soft shadows, ambient occlusion, a sun that moves
with the time of day (morning, day, evening, night), lit windows and lamps, tone
mapping; water surface shading and shorelines; weather that darkens and fogs.

Phase 5 - characters and Pokemon: scale, contact shadows, light tint, riding,
four players.

Phase 7 - speed and polish: measured on the owner's PC.

Each step: built and run (Linux, then the Windows exe under Wine), screenshots
before and after in the same places (Route 101, Rustboro, Petalburg Woods, Oldale,
Dewford...), the multiplayer regression for anything touching the game thread,
docs and a checkpoint.

## Phase 1, step 1: cameras and a world without board edges (2026-10-10)

Engine `claude/graphics-overhaul` (`630c975fb`..`6743bc1e5`), merged into
`claude/native-graphics` as tag `graphics-wip-20261010-6`; checkpoint
`native-wip-20261010-6`. Items 1-3 of the order above; item 4 (other tilesets'
neighbours) is next.

### What the player gets

| Key | What it does |
| --- | --- |
| (none) | **Adventure camera**, the default: the 3DS project's framing (42 degrees down, a 33 degree lens, 11.5 tiles from the top of the picture to the bottom at the player outdoors, 9 indoors, 10.5 in caves). The eye is about 13 tiles above the ground and 14 behind the player and rises and falls with the ground (eased over a quarter second). The view follows the player smoothly (eased in real time, so the same at any frame rate) and looks 0.6 tiles ahead while walking; warps and jumps of more than 4 tiles cut straight to the new place; walking onto the next map carries the view across without a jump. |
| F7 | **Diorama camera** and back: higher (52 degrees) and wider (about 24 tiles) through a long 20 degree lens, the miniature look; no look-ahead, a slower follow. |
| F9 | **Photo mode** (only while the 3D view is shown): the game stands still, text boxes and the map name are hidden, the view starts from the one shown. Arrows move the camera a tile at a time (up to 16 tiles from where it began), `-`/`=` or the mouse wheel zoom (4-40 tiles), `,`/`.` tilt (15-80 degrees). Esc, X or Backspace go back. The keys are shown along the bottom in the UI art direction's style. |
| F12 | **Picture**: the frame as drawn, without the PC's own menus and hints, saved as `screenshots/emerald-<date>-<time>.png` next to the game (`-2`, `-3`... for several in a second); a message box says where for 4 seconds. Works in any camera, in photo mode and in the 2D view. |
| `-` `=` wheel, `,` `.` | Zoom (1 tile steps, 7.5-16.5 tiles for Adventure; 2 tile steps, 14-34 for Diorama) and tilt (4 degree steps; 30-62 and 38-70 degrees), kept for each camera. |

The F10 menu's camera row reads Adventure or Diorama. `pokeemerald.cfg` keeps
`cameraMode=adventure|diorama` and `adventureZoom`, `adventureTilt`,
`dioramaZoom`, `dioramaTilt`; the old `cameraStyle`, `cameraPitch` and
`cameraZoom` lines are ignored, so everyone starts on the Adventure camera.
`PKMN_DIORAMA_CAMERA=adventure` or `diorama` sets it for one run without writing the
file.

The scene holds 49 x 49 cells round the camera (33 x 33 before). Outdoors the last
cells fade into the sky's colour (from 18.5 to 23 tiles from the scene's centre),
and the picture past them is that colour: a clear sky's pale haze, carried through
the palette's fade (warps, the battle transition), the time-of-day tint and the
weather's own haze (fog, rain, ash). Indoors and in caves the dark stays.
Petalburg Woods (shade weather) is drawn in 3D: the shade only darkens the
palettes, which the 3D view reads as the GBA shows them.

### How it works

* `include/diorama/camera.h`, `src/diorama/scene/camera.c` (project-owned, no GL):
  the modes, their limits and the follow. A view is given as the 3D battle
  session's camera rig (`DioramaCameraRig` in `terrain_mesh.h`: the eye's height
  over y = 0, its distance behind the target, the screen offset), worked out from
  the pitch, the lens and the extent so the player stays exactly where the
  overworld has always put them on screen.
* Every scene shader (terrain, buildings, trees, sprites, air, field light, haze)
  and the culling take the rig as uniforms instead of the fixed 16-tile eye; with
  the rig inactive they draw as before. The rig is the battle session's own design,
  applied unchanged (see Coordination).
* `gl_compositor.c` updates the camera once a frame from the game's camera
  position, the player's facing and ground height and the map type, works out map
  crossings from the connected cells, sets the rig and the edge fog for the field
  pass and clears them afterwards.
* `gl_light.h`: `Haze(colour, depth, position)` adds the edge fog to the distance
  haze; `DioramaGLLight_SetEdgeFog` sets it for a frame.
* `src/platform/png_write.c`: an 8-bit RGB PNG writer with its own deflate (fixed
  Huffman codes, LZ77): a 1080p picture of Route 101 is 1.2 MB, written in about
  0.1 s (on the game thread: one short hitch when F12 is pressed).

### Verification

| Check | Result |
| --- | --- |
| Linux and Windows 3D builds | Compile with no new warnings. |
| `check-native` | Pass: platform 1063, bridge 4186, display settings 139, PNG writer 176 checks; 9 test pictures decoded by Python's zlib, every pixel matching. |
| `check-diorama` | Pass: 11 renderer unit-test programs (new: camera, 403 checks: the framing against the shaders' projection at 4 pitches x 2 lenses x 3 extents x 2 ground heights, the modes' limits, the follow at 30 and 144 frames a second, look-ahead, warps, map crossings, the ground, photo mode), 18,318-metatile compositor goldens, rule validation, generated tables. `test_rules`' border-tree case was written for a 33-wide grid and now follows the grid's width. |
| `check-abi` | Pass (172 types). |
| GBA ROM | Unchanged, sha256 `f214735b...3387`. |
| Screenshots, Linux, 1920x1080, software GL | Route 101, Petalburg Woods, Rustboro City, Oldale Town: Adventure, Diorama, photo mode (start, zoomed/tilted/panned, the F12 message), back to Adventure. No black past the scene in any of them; in the Diorama view Oldale's and Littleroot's buildings stand at the ends of Route 101 and the edges fade into haze. The F12 file (1920x1080) decoded and matched the frame without the hints. |
| Frame rate, software GL (llvmpipe, 2 cores; same save and machine as the resolution benchmark) | 720p 6.6 fps (8.3 before), 1080p 4.4 (5.6), 1440p 3.1 (3.2), 4K 1.6 (1.6): the larger scene costs about a fifth at the small sizes on a CPU renderer; a real GPU is unmeasured (the owner's `benchmark.log`). |

Not seen yet: a map crossing and a warp with the new follow (unit-tested, not
watched; software GL runs the game at a few frames a second here), night and rain
with the edge fog, the Windows exe's photo mode on a real GPU, the 2D layers'
fade around photo mode at full speed.

### Coordination with the 3D battle session

The battle branch (`claude/native-graphics-3d-battles`) introduced
`DioramaCameraRig` and `DioramaCamera_GetRig` in `terrain_mesh.h` and the rig
uniforms in the terrain, building and tree shaders. This branch applies those hunks
unchanged and extends the same uniforms to the object, air and field light shaders
and the haze, so merging the battles should meet identical lines there. Expected
overlaps: `gl_compositor.c` (the field camera now comes from `camera.h`: the battle's
glide from the field's view can take `DioramaCamera_FixedEyeFocalLength`, or read
the rig the field frame set, instead of the old focal-length styles), and
`gl_air.c`/`gl_object_renderer.c` if the battle branch changed the same uniforms.
The edge fog is off outside the field pass, so a battle frame has none.

### What was left of phase 1

Done in step 2 below: the neighbouring maps, the readable player, the woods'
crowns, distant scenery and the other weathers.

## Phase 1, step 2: the neighbours, a readable player, every weather, the distance (2026-10-10)

Engine `claude/graphics-overhaul` (`d73f16e45`..`cb859b10c`), merged into
`claude/native-graphics` as tag `graphics-wip-20261010-7`; checkpoint
`native-wip-20261010-7`. This finishes phase 1 (directive "CONTINUE 3D GRAPHICS
OVERHAUL + COMPLETE ENVIRONMENTAL OBJECT UPGRADE", section 1 items 1-5).

### What the player gets

* **Neighbouring towns and routes look like themselves before you cross into
  them.** Slateport's north edge shows Route 110 (its sand path, the Trick House,
  the Cycling Road) instead of the sea; Rustboro shows Route 115's beach and
  ledges; Route 118 shows Route 119's hills and tall grass; Verdanturf shows Route
  116's mountains. Their hills and buildings stand in 3D, and walking across the
  border carries the camera over without a cut.
* **You are never lost behind a building or a tree.** When the world hides your
  character (or a teammate, or your follower), a see-through blue outline of them
  is drawn through it. Not in photo mode, so pictures stay clean.
* **Petalburg Woods' trees keep their crowns** (the band that cut them is gone).
* **Every weather is drawn in 3D**: a downpour's heavier rain, snow, a sandstorm's
  blowing sand with a sandy distance, bubbles rising under water; none drops back to
  the flat view any more.
* **The world goes on into the distance.** Past the detailed 49 x 49 tiles a
  simple version of the surroundings (forests as a green canopy, towns as coloured
  blocks, the sea) carries on to about 48 tiles and fades into the sky's haze.
  Mostly seen in the Diorama camera's corners and in photo mode zoomed out.
* Photo mode can zoom all the way out from the Diorama camera (the scene used to
  disappear).

### How it works

* Silhouette (`gl_object_renderer.c`, draw mode 5): after the scene, the player,
  remote players (local ids 241-243) and the follower are drawn once more with the
  depth test reversed (only where something is in front of them), a 0.75-tile
  depth margin so the ground at their feet does not count, as a translucent
  two-tone blue taken from the sprite's own light and dark.
* Woods: the 3DS tree list maps metatiles `0x1F2`/`0x1F3` (a tree's lower row
  beside open ground) to the crown's bottom quarters (`tree_sprites.c`).
* Weather: `weather.c` classifies every weather; `BuildWeatherImage` draws the
  new layers; `gl_light.c` gives sand and snow their sun and haze;
  `PKMN_DIORAMA_WEATHER=<n>` previews one (the 3D view only).
* Neighbour pages (`scene_snapshot.c` `NeighbourPage`, `metatile_atlas.c`
  `DioramaAtlas_SetPages`, `DioramaAtlas_MapPalette`): up to three neighbouring
  maps with another secondary tileset at once. Their cells carry `atlasPage`; the
  atlas holds 512 more metatile slots per page (2560 in all); a page's tiles are
  the live primary tiles plus that tileset's own secondary tiles (decompressed once
  on the game thread), its palettes 6-12 the tileset's with the game's night mix,
  faded by each channel's mapping read off the live palettes (so the day/night
  tint, weather colour maps and fades match). Terrain materials, alpha masks, the
  mountains' art masks and the buildings' palette rows follow the page.
* Distant scenery (`far_field.c`, `CopyFar`): blocks of 2 x 2 cells out to 48
  tiles from the map, its connections and theirs (the border block beyond), each
  a column of its rules height (`DioramaRules_StaticHeights`; a model's height for
  a building; trees a low peaked canopy) coloured with the average of its art;
  culled in 49 sectors; the edge fog moves out to 30-47 tiles.
* The scene shaders' far plane goes from 80 to 400 tiles of depth.

### Coordination (shared rendering interfaces)

These change interfaces the 3D battle branch also uses; noted here for the merge
(no other session was running to message):

* `scene_snapshot.h`: `DioramaCellSnapshot.atlasPage` (it fills a padding byte;
  the struct keeps its size), `neighbourPages[]` and the far blocks at the end of
  `DioramaSceneSnapshot`. The battle branch adds `paletteFading` and
  `battleTransition` after `doorLevel`: no overlap.
* `metatile_atlas.h`: the atlas functions take slots; a page 0 cell's slot is its
  metatile id, so code that passes metatile ids of the map's own cells works
  unchanged. The atlas is 576 x 1440 (was 576 x 576); a reset uploads only the
  rows in use.
* `gl_compositor.c` `EnsureAtlas`: calls `DioramaAtlas_SetPages` first and
  indexes its arrays by slot. The battle branch changes the same function to
  return whether the atlas changed: keep both (`return reset || changed;`).
  `DioramaGL_SetBattleTiles` passes snapshots whose pages stay valid (a page's
  tiles are never freed).
* `gl_building_renderer.c`: a palette row per page (vertex attribute 3); the battle
  branch's hunks there are the camera rig's, already applied here.
* All scene shaders: `farDepth` is `DIORAMA_FAR_DEPTH_GLSL` (400) instead of 80; the
  battle's own shaders, if they copy the projection, can take the same constant.

### Verification

Engine `cb859b10c` (Linux 3D binary and Windows exe built from it; checkpoint
`native-wip-20261010-7`).

| Check | Result |
| --- | --- |
| Linux and Windows 3D builds | Compile with no new warnings (two Windows-only name clashes found on the way, `near`/`far` are macros in the Windows headers: renamed). |
| `check-native` | Pass: platform 1063, bridge 4186, display settings 139, PNG writer 176 checks. |
| `check-diorama` | Pass: 13 programs (new: `test_far_field`, 54,618 checks; `test_metatile_atlas` with the pages and the palette mapping; `test_tree_sprites` with the woods' metatiles; `test_weather` with every weather), 18,318-metatile compositor goldens, rule validation, generated tables. |
| `check-abi` | Pass (172 types). |
| GBA ROM | Unchanged, sha256 `f214735b...3387`. |
| Python tests | 1399 passed, 1 skipped (as at checkpoint -6). |
| Before/after under Wine (checkpoint -6 exe, then this one; 1920x1080, software GL) | Littleroot, Oldale, Rustboro, Route 101, Petalburg Woods, Granite Cave 1F, Dewford, Adventure and Diorama cameras (28 pictures, put side by side): the Adventure views are the same picture (the distance is out of its frame), the Diorama views go on into distant scenery at their corners where the haze began before (Oldale's forest and Route 103's water, Rustboro's forest), the woods' crowns are whole, nothing new is missing or misplaced. |
| Linux, the same 7 places, both cameras | Visually render (14 pictures). |
| Neighbours, silhouette, weathers, distance | As in `TEST_PLAN.md` 7c (by hand, during the work): see the list there. |
| Frame rate, software GL, `--benchmark 5` | The distant scenery costs nothing measurable: Adventure 720p 6.9 fps with it, 6.6 without; 1080p 4.8 / 4.7; Diorama 720p 6.2 / 6.0, 1080p 4.3 / 4.2; 1440p and 4K 1.6-2.9 either way (CPU renderer: fill bound). A real GPU is unmeasured (V3). |
| Multiplayer regression | native-checkpoint-3d-9: 2 Linux 3D clients enrol, save (1.6-1.75 s), restart, live recovery (42.0 s), host store intact. |

Not seen yet: snow, a downpour and a thunderstorm on a real map (previews only), a
neighbour page's tiles at night, the Windows exe on a real GPU.

## Phases 2-4: world detail objects, every building in 3D, lamps and lit windows (2026-10-11)

Engine `claude/graphics-overhaul` (`732a1ad56`..`d799c4a8a`), merged into
`claude/native-graphics` as tag `graphics-wip-20261010-8`; checkpoint
`native-wip-20261010-8`. Directive "CONTINUE 3D GRAPHICS OVERHAUL + COMPLETE
ENVIRONMENTAL OBJECT UPGRADE", sections 2-9 (phases 2-4, and the quality option of
phase 5).

### What the player gets

* **The small things stand up.** Tall grass and long grass as two swaying cards a
  tile, flowers, signs and the house signs, white, stone and iron fences and
  Mauville's wooden posts (facing along their line, north-south runs too),
  Rustboro's street lamps with
  their lantern on the post, rocks and boulders (from above as mounds, from the
  front as reliefs), Slateport's flower baskets and market goods, Lavaridge's lava
  rocks, Mossdeep's sea rocks, Fallarbor's ash boulders - every one from its own
  pixel art, lit, casting a real shadow. Collision is unchanged.
* **The grass moves.** It sways in the wind, harder in rain, a storm or a
  sandstorm and less in fog, and shivers where someone walks through it.
* **Every building is a building.** About seventy buildings that lay flat on the
  ground (in Slateport, Mauville, Lilycove, Fortree, Mossdeep, Pacifidlog, Dewford,
  Fallarbor, Verdanturf, the route houses and the Battle Frontier) now stand in 3D,
  built from their own drawing: Lilycove's department store and the Battle Tower
  are tall, the houses have walls and roofs, doors open on them. From the default
  cameras each looks exactly like its art; from the side it has depth and casts a
  shadow. Sootopolis's houses, cut into the crater, stay as drawn.
* **Towns light up after dark.** In the evening and at night the windows of houses,
  shops, gyms and Centers glow warm (each window its own brightness), and
  Rustboro's street lamps light the ground, walls and people round them.
* **A setting for it.** F10 > World details (On/Off); the Low quality preset turns
  it off. Lamps and lit windows go off with Lighting.

### How it works

* Props (`include/diorama/props.h`, `scene/props.c`, `gl/gl_props.c`): a catalogue
  per tileset (made with `tools/diorama_objects`) names a metatile's object and its
  form (slab, cards, block, mound, relief); the renderer composes each prop's art
  into a small texture of its own, draws slabs and cards instanced (a slab's sides
  cut per pixel by the art's transparency) and mounds and reliefs as column meshes
  made from the art; the ground under a prop is its lower layer or the commonest
  neighbouring ground. Cells a modelled building stands on (the generator's own
  hedges, railings and sea rocks) are left to the model
  (`DioramaProps_SetCellTaken`).
* Lamps (`gl/gl_lamps.c`): the 16 lamps nearest the camera as point lights with a
  smooth falloff in the terrain, building, tree, prop and sprite shaders, in the
  field pass only; `DioramaGLLamps_NightFor` (the game's time of day on maps it
  tints) sets how lit they and the windows are.
* Every building (`tools/diorama_buildings/auto_buildings.py`): each door of an
  outdoor map whose building no spec models gives a building - its front the
  door's row as far as the cells beside the door are drawn over, its cells up from
  the front and a little to the sides (never sideways into leaves), the row over
  its north edge that the roof is painted on, two touching buildings split by their
  fronts - and the 3DS generator models it as a `Relief` read off its drawing: a
  front as tall as the facade (the first long edge over the door; overrides for
  the tall ones), the roof laid back to the north edge of its cells (the depth the
  drawing does not show laid with the middle of its own roof, `roof_band`, so no
  eave repeats behind it). Each model is proved pixel for pixel in the GBA
  projection (`--verify`, 70 of 70).
* Lit windows (`tools/diorama_buildings/window_glow.py`, `export_gl.py`,
  `DioramaBuildings_PageWindows`): glass-coloured panes in a darker frame on the
  models' upright faces, found on their texture pages at build time; the page
  texture carries each texel's window brightness beside its palette slot (RG8);
  the building shader mixes in a warm light.
* World details setting (`platform/display_settings.c`, `pc_menu.c`, `sdl2.c`):
  `details=` in `pokeemerald.cfg` with the quality block; the launcher's game
  display settings treat it as a quality key (`game_display_settings.py`).

### Coordination (shared rendering interfaces)

Noted here and in the checkpoint's `COORDINATION.txt` for the 3D battle session,
whose merge candidate 4 (`e747ce106`, the battles on `cb859b10c`) was tried against
this tip in memory (`git merge-tree`): one conflict, two insertions at the same place
in `DioramaGL_Init` (keep both: the props' init, then the battle's). The battle's
`DioramaGL_DrawBattleWorld` draws the field without the props pass, so the cells a
prop stands on would show bare ground behind a battle (tall grass first of all);
the note gives the three lines to add. The changes:

* `gl_compositor.c`: new calls (`DioramaGLProps_Init/Sync/Draw/DrawShadow/
  Shutdown`, the props' geometry generation in the shadow key,
  `DioramaGLLamps_SetFocus/SetActive/SetNight` round the field pass).
* Scene shaders (terrain, building, tree, sprite): `DIORAMA_GLSL_LAMPS` and its
  uniforms (`DioramaGLLamps_Locate/Apply`; `ApplyNone` in debug and shadow
  passes); `gl_loader` gains `dglUniform4fv`.
* `gl_terrain_renderer.c` `BuildInput`: a prop's cell gets its ground material.
* `gl_building_renderer.c`: page textures are RG8 (slot, window brightness); the
  fragment shader reads `.rg`; a `windowLight` uniform.
* `buildings.generated.c` gains `gDioramaBuildingsWindowRuns`; buildings.bin gains
  about seventy models (545 in all, 3170 placements).
* Outside the 3D view: `struct DisplaySettings` gains `details` (after `effects`),
  `enum PcMenuItem` gains `PC_MENU_DETAILS` (after `PC_MENU_EFFECTS`).

### Verification

Engine `d72d32c09` for the checks and the full before/after set; the two roof fixes
after it (`a82a652c8`, `d799c4a8a`) change only the generated building models and
were checked again where they show (below). Checkpoint -7's exe and Linux binary
are the "before".

| Check | Result |
| --- | --- |
| Linux and Windows 3D builds | Compile; the Windows build has the same three header warnings as checkpoint -7 and no new ones. |
| `check-native` | Pass: platform 1063, bridge 4186, display settings 151 (World details row and preset), PNG writer 176 checks. |
| `check-diorama` | Pass: 13 renderer test programs (new: `test_props`, 1714 checks: catalogue, placement, ground, art, building cells left to the models), compositor goldens (18,318 metatiles), rule validation. |
| `check-abi` | Pass (172 types). |
| Building models | All 70 automatic models exact in the GBA projection (`--verify`); `test_auto_buildings` (11) and `test_window_glow` (9) pass. |
| GBA ROM | Unchanged, sha256 `f214735b...3387` (built from `d72d32c09` and again from `d799c4a8a`). |
| Before/after, Linux, 1920x1080, software GL | Littleroot, Oldale, Rustboro, Route 101, Petalburg Woods, Granite Cave, Dewford, Lilycove, Slateport, Mauville; Adventure and Diorama cameras (40 pictures, evening): grass, flowers, signs, fences, lamps, rocks and baskets stand; the new buildings stand in the four cities; windows lit; Rustboro's lamps light the street; nothing new missing or misplaced. The roof fix seen again in Lilycove, Slateport, Mauville and Dewford (both cameras). |
| Before/after, Windows exe under Wine | The same first eight places, both cameras (32 pictures, daytime): the same objects and buildings as on Linux. At night (the final exe; `TZ=EST5EDT`, because Wine's C library reads only POSIX-style zones and took the shell's `America/New_York` as UTC, which is daytime in the test saves): Rustboro's lamps light the street, and windows glow in Rustboro and Lilycove. |
| Multiplayer | `native_checkpoint_proof.py --slow 1.5 --recover`, Linux 3D, 2 clients: native-checkpoint-3d-12 with the final build passed (enrol, walk and save, restart, saves 1.59-1.77 s, live recovery 42.4 s); native-checkpoint-3d-10 and -11 passed on `d72d32c09` and `a82a652c8`. |
| Python tests | 1399 passed, 1 skipped (with the launcher's `details=` quality key). |
| Frame rate, software GL | See FEATURE_STATUS and V30: Lilycove Adventure 7.4 / 5.7 / 3.6 / 1.9 fps at 720p-4K (8.4 / 6.2 / 3.6 / 2.1 with World details off; checkpoint -7 8.7 / 6.4 / 4.0 / 2.3). A real GPU is unmeasured. |

Not seen yet: the props and lamps on a real GPU; a downpour or a storm on a real map
with the grass (previews only); the World details switch under Wine.

## Performance directive phase 4: the last flat things, levels and steps, night (2026-10-12)

Directive "8 GB RAM support, 4K 200 FPS optimization and final 3D environment
overhaul", phase 4 (performance and memory: `docs/performance/`). Engine
`claude/graphics-overhaul` `d799c4a8a`..`c51769606`, tag `graphics-wip-20261012-1`;
checkpoint `native-wip-20261012-1`.

### What the player gets

* **Sootopolis's houses stand up.** The 22 white houses cut into the crater (the
  towers under their pyramid roofs and the flat-roofed boxes) are buildings with
  walls, roofs and doors like every other town's.
* **Slateport's market has stalls.** The six market stalls have their striped
  canopy as a roof on posts over the stall, its front hanging high enough to show
  the stallholder; the orange awnings stand on their legs; the rope along the beach
  kerb hangs between its posts. Rustboro's iron fences turn their corners.
* **Mossdeep stands on its ground.** Its houses, Pokemon Center and its own round
  trees no longer stand a tile up on plinths (the town lies a level under its cliff
  tops).
* **Route 109's beach is furnished**: parasols on their poles, deck chairs with
  raised backrests, air mattresses on the sand.
* **Route 113's ash grass stands** like tall grass; **long grass** no longer drops
  Routes 119 and 120 to the flat view when you stand in it.
* **No more holes in the world.** Pale squares and bands where the sky showed
  through - round the sea's rocks and sandbars on the sea routes, along Route 113's,
  116's and 118's ledges, under rows of trees on raised ground - are closed: each
  step between two levels has its side. The sea's shallows lie level with the sea,
  and its grey rocks and brown stacks stand in the water.
* **At night more windows glow**: dark-glass windows (Mossdeep's houses, Devon's in
  Rustboro) light up as well as the light-glass ones, and Rustboro's lamp glass
  glows again (the night tint had made it too dark to be found). Trees follow the
  night tint again (a performance change had left them bright at night for a day).

### How it works

* Props (`props.h`, `props.c`, `gl_props.c`): a prop can float (`lift16`: a canopy,
  its front), slope (`rise16`: a lying block's north edge raised) and lie deeper
  than one cell (`depth`); new kind `CANOPY`. Catalogue additions: Slateport's stall
  roofs, fronts and posts, awnings and legs, beach rope (north-south runs turned to
  face east), Route 109's parasols (dome, rim, pole), deck chairs and air mattresses,
  Rustboro's iron fence ends and corners, Route 113's ash grass.
* Sootopolis (`tools/diorama_buildings/auto_buildings.py` `crater_specs`): the door
  search ran into the crater's rock, so the map was skipped; its houses are found by
  their roofs (3 x 4 cells and a tower's tip) and modelled as a Relief read off their
  drawing like the others; all 22 exact in the GBA projection.
* Levels (`tools/diorama_rules/terrace_topology.py`, `compile_rules.py`): the
  terrace solver gives levels to walkable regions only. Now blocked cells take the
  level of the land nearest them in Mossdeep (`lift_blocked_cells`,
  `LIFT_BLOCKED_LAYOUTS`; elsewhere a blocked cell by a lower level is as often a wall
  between two levels, so only there), unsolved shallows joining the solved sea take
  its level (`join_water`), the sea's rocks and stacks (the buildings generator's own
  finder, `voxel_props.py`) stand on the water round them, and ledges on a lower level
  take it.
* Steps (`terrain_mesh.c` `AppendSkirtFaces`): a cell beside a lower whole cell or
  ledge gets a side from that cell's top to its own footing, drawn with its ground; a
  ledge on a level below the ground is a column a voxel thick with its whole drawing
  on its sides.
* Long grass (`scene_snapshot.c`): a walker split into full-width strips (subsprite
  tables 4 and 5) is drawn whole; the 3D grass stands in front of it.
* Windows (`window_glow.py`): dark panes solid in a much lighter frame are windows
  too (39 more, 2945 runs); lamp glass is marked from its unfaded colours.
* Shared renderer hooks for the 3D battles and the UI: the checkpoint's
  `COORDINATION.txt` (trial merges with both branches, the hunks to keep, the one
  duplicate function to drop).

### Verification

Engine `c51769606` (the Linux and Windows 3D builds made from it; checkpoint -8's
builds are the "before").

| Check | Result |
| --- | --- |
| Linux and Windows 3D builds | Compile; the Windows build has the same three header warnings as checkpoint -8 and no new ones; the exe is large-address-aware and imports no DirectX redistributable DLL. |
| `check-native` | Pass: platform 1067 (with the clock override), bridge 4186, display settings 244 (frame-rate limits, render scale, memory budget, the limiter's beat), PNG writer 176 checks. |
| `check-diorama` | Pass: 13 test programs (`test_terrain_mesh` with the steps, ledges and their sides - each check fails on the old code; `test_props` 5703 checks), compositor goldens (18,318 metatiles), rule validation, generated tables. |
| `check-abi` | Pass (172 types). |
| Rules and building tools (`check-diorama-tools`, each file run) | `test_compile_rules` 22 of 23 (the one failure is V31, as before); `test_tile_shape` 8, `test_structures` 13, `test_measured_volumes` 8, `test_mountain_art` 5, `test_terrace_topology` 6, `test_pixel_objects` 15, `test_catalog` 8, `test_occupancy_model` 8, `test_window_glow` 12, `test_auto_buildings` 11 pass; `test_rules_parity` fails as before (V2, upstream). Every Sootopolis model exact in the GBA projection (22/22). |
| GBA ROM | Unchanged, sha256 `f214735b...3387`. |
| Python tests | 1399 passed, 1 skipped, 2326 subtests (6 min 46 s). |
| Holes and steps, Linux, 1920x1080, before and after | Routes 132, 127, 124, 125, 128, 113, 116, 118, 119, 109, Pacifidlog, Mossdeep, Sootopolis, Ever Grande, Dewford, Slateport, Adventure camera, noon: the pale squares and bands are gone; rocks stand in the water, shallows lie level with the sea, ledges closed. `PKMN_DIORAMA_TERRAIN_CHECK=1`: 0 stale chunks. |
| Long grass | Route 119 (27,95): the field stays 3D, the player in the grass; no refusal in the log. |
| Survey of the remaining towns and routes (day and night) | Fortree, Pacifidlog, Dewford, Verdanturf, Fallarbor, Lavaridge, Petalburg, Lilycove, Routes 119 and 120, Granite Cave; Fortree, Petalburg, Lilycove, Lavaridge, Granite Cave at night: the holes above (fixed) were the only new faults found. |
| Before/after under Wine (checkpoint -8's exe and the new one), Adventure and Diorama cameras | Mossdeep (the plinths and broken trees gone), Dewford, Lilycove, Granite Cave (no change), Route 101 (the new exe; the old one's run stayed in the intro: a timing fault of the script); at night Rustboro (Devon's windows lit) and Mossdeep (houses' windows lit). |
| Frame-rate limits, final build | 60.0, 144.0, 240.0 fps at those limits, about 2000 unlimited, the game at 120 frames every 2 s at each (`docs/performance/high-refresh-and-benchmarks.md`). |
| Benchmark, software GL | Lilycove and Route 101, checkpoint -8 against the final build: the same within noise standing still (fill bound); see the performance doc. |
| Multiplayer | native-checkpoint-3d-13 (Linux 3D, 2 clients): enrol 2.0 s, saves 1.86-1.97 s, restart, live recovery 44.9 s, host store intact; native-trade-6 (Linux 2D build of the same commit, 2 clients): both offers, one confirmation commits nothing, trade applied in both games (44.9 s), back-out aborts, restart keeps both parties, host store intact. |
| Launcher package | "Native 3D preview 6" built under Wine (PyInstaller, package audit), its runtime the tested exe (sha256 `cb58d4e8...`). |

Not seen yet: any of it on a graphics card; Sootopolis's houses at night (no lit
windows found on them: their glass is not window-coloured); the Battle Pyramid and
Arena area, the cable car stations, the Trick House and Trainer Hill (still flat).

## Option B: real roofs, recessed windows and framed doors; the last flat landmarks; cave levels (2026-10-12)

The owner's choice of 2026-10-12 ("Option B: real sloped roofs, window recesses,
door frames and architectural trim ... a genuinely dimensional Pokemon Emerald
world, not flat GBA artwork viewed from an angle"), keeping Emerald's art style,
silhouettes, colours and architecture. Engine `claude/graphics-overhaul`
`c51769606`..`8e4604993`, tag `graphics-wip-20261012-2`; checkpoint `native-wip-20261012-2`.

### What the player gets

* **Real roofs.** The buildings that had their drawn roof laid flat on top now
  have roofs of their own: 25 pitched hipped roofs with a ridge (Slateport,
  Lilycove, Dewford, Verdanturf, Fallarbor, Route 109's houses, Mauville's Bike
  Shop, the Trick House, both cable car stations, the Battle Arena), laid from
  the tiles of their own drawn roof, never stretched; 26 flat roofs behind a
  parapet (Lilycove's department store and museum, Slateport's museum, Mossdeep's
  houses - now two storeys with a railed roof - the Pokemon League, the Safari
  Zone's gates, Mauville's Game Corner); domes over Fortree's tree houses and the
  Mirage Tower; cones over Pacifidlog's huts; octagonal pyramids over
  Sootopolis's towers and Trainer Hill; the Battle Pyramid as a pyramid; the three
  Battle Tents as domes with their entrance standing out in front.
* **Windows and doors with depth.** On every building outdoors (the hand-made
  models too: Pokemon Centers, Marts, Gyms, houses) the windows are set back into
  the wall with reveals and a sill under them, and the doors stand in a framed
  recess; the door's own opening animation plays in it. 298 windows and doors on
  77 buildings. At night the lit windows glow in their recesses.
* **The last flat landmarks stand.** The Battle Pyramid, the cable car stations
  on Route 112 and on Mt. Chimney, the Trick House and Trainer Hill (on its rock
  over the door cut into the cliff) were spiky reliefs of their drawing; they are
  buildings now. Trainer Hill also stands on the days the Mirage Tower is hidden
  (and for good after its event), and the Mirage Tower no longer stands on the
  sand on those days.
* **Caves have levels.** In caves the raised floors (the GBA's elevations) stand
  higher than the lower ones - up to a tile, so nobody walking a floor drops out
  of view - and the bridges between them are wooden decks at their level
  (Victory Road, Meteor Falls, Shoal Cave, the Cave of Origin, Mirage Tower's
  top floor, Artisan Cave, Altering Cave; caves of one floor are as they were).
* **The same look costs less.** The terrain is drawn from fewer vertices: no
  undersides where a column stands on its own floor, and each quad drawn from its
  four corners instead of six vertices - in Jagged Pass, the Lavaridge rocks' worst
  place, a third less vertex work in every pass and a quarter less GPU memory for
  the terrain, the picture identical.
* **The Players menu is seen in 3D.** The in-game Players menu (trades, battles,
  the players list) worked but was never shown over the 3D field (V42, found by
  the native UI session as its U11): it pauses the field callbacks, and the 3D
  view's text boxes come from the field's snapshot, which only the field
  callback published. The main loop now publishes it while the menu is open
  (`main.c`), so the menu's window shows like the start menu's.

What stays as it was: every building's footprint, door, collision and
interaction (the models are visual; the cells, warps and scripts are the game's);
the facades are still proved pixel for pixel against their drawing; Sky Pillar's
rubble is the 3D battle session's (its props catalogue entries, in its branch).

### How it works

* Roofs (`tools/diorama_buildings/dimensional.py`, project-owned; which building
  gets which roof: `auto_buildings.py` `ROOFS`, `LANDMARKS`, `CRATER_HOUSES`): the
  walls stay the Relief read off the drawing; `build_roof` adds a roof by type -
  pitched (a hipped roof after the 3DS port's `HipRoof`/`Strip`: the drawn roof is
  read row by row into eave, courses and ridge; a clean swatch of it is appended
  to the model's art and tiled over the slopes at 30 degrees, with fascia, hips,
  ridge cap and a 2-pixel overhang), flat (a parapet), dome, cone, pyramid4/8
  (`Shell`), tent and split. Roof faces are tagged so the GBA-projection proof
  skips them; the facade must still match its drawing.
* Facades (`facade_details`, `detail_model`): windows are found as in
  `window_glow.py` and grown to their frame; doors where the game's door
  animation draws; each is cut back 1.5 (windows) or 3 (doors) pixels with
  reveals, a sill under a window; the detail rectangles are left out of the
  proof (`voxel_building.ortho_check(ignore=...)`).
* Layouts a map's scripts switch to (`setmaplayoutindex`): the scene snapshot
  now names the layout the game draws (`scene_snapshot.c` `CurrentLayoutId`;
  `gMapHeader.mapLayoutId` keeps the map's own); the generator places the
  buildings found on a map in its switched layouts where their cells are the same
  (`gen_voxel_buildings.py` `layout_variants`). Shoal Cave at high tide is drawn
  from its high-tide layout's own rules (with their levels) instead of the
  low-tide one's; a layout only a script reaches gets its map's cave levels
  (`compile_rules.py` `_script_layouts`; none of today's caves needs it).
* Cave levels (`tools/diorama_rules/terrace_topology.py` `cave_levels`): in a
  layout whose maps are all underground, the walkable floors of each elevation get
  a level: the lowest where it was, the highest a tile (16/16) over it, the ones
  between in even steps; bridges (elevation 15) become decks at the highest floor
  they meet. Walls, water, elevation 0 and cells another solver placed are left.
* Terrain cost (`terrain_mesh.c` `DropBaseUndersides`, `DioramaTerrain_FoldQuads`;
  `gl_terrain_renderer.c` `UploadChunk`, `DrawChunk`): a column's bottom face on
  its own cell's floor is dropped before the faces merge; each chunk's quads are
  folded to four vertices with 16-bit (or 32-bit) indices written into the
  scratch buffer's unused tail (no new memory), drawn with `glDrawElements` in all
  four terrain passes. `PKMN_DIORAMA_CHUNK_LOG=1` logs every chunk's cost.

### Coordination (shared rendering interfaces)

* The checkpoint's `COORDINATION.txt` has the trial merge with the battle
  session's `claude/battle-environments-2` (`719e16c78`): the conflicts and how
  they were kept, the merged TEST build's tests and a battle survey of the maps
  with the new geometry (caves with levels, towns with roofs, the landmarks).

### Verification

Engine `8e4604993` (the checkpoint's Linux and Windows 3D builds; checkpoint -1's builds are
the "before"). The pictures, doors, benchmark and Wine runs used builds from before the last commit
(`0c4b1f85c`'s, or earlier where a row says so): that commit changes only `main.c`'s
paused-callback branch while the Players menu is open (V42), checked by its own row below.

| Check | Result |
| --- | --- |
| Linux and Windows 3D builds | Compile; the Windows build has the same three header warnings as before and no new ones; the exe is large-address-aware and imports no DirectX redistributable DLL. |
| `check-native` | Pass: platform 1067, bridge 4186, display settings 244 (frame-rate limits, render scale, memory budget), PNG writer 176 checks - the settings, memory budget and frame pacing unchanged. |
| `check-diorama` | Pass: 13 test programs (`test_terrain_mesh` with the folded quads drawing the same triangles; `test_props` 5703 checks), compositor goldens (18,318 metatiles), rule validation, generated tables current. |
| `check-abi` | Pass (172 types). |
| Rules and building tools (each file run) | `test_compile_rules` 23 of 24 (the one failure is V31, as before); `test_tile_shape` 8, `test_structures` 13, `test_measured_volumes` 8, `test_mountain_art` 5, `test_terrace_topology` 8, `test_pixel_objects` 15, `test_catalog` 8, `test_occupancy_model` 8, `test_window_glow` 12, `test_auto_buildings` 13, `test_dimensional` 14 pass; `test_rules_parity` fails as before (V2, upstream). The generator's proof (`--verify`): 573 of 573 models exact against their drawing (the roofs and details left out), 50 rooms composed with the terrain, 0 pixels differ. |
| GBA ROM | Unchanged, sha256 `f214735b...3387`. |
| Python tests | 1399 passed, 1 skipped. |
| Before/after tour, Linux 1920x1080, Adventure and Diorama cameras | 31 places by day (62 pairs) and 8 towns at night (16 pairs), checkpoint -1's build against this one: the roofs, recessed windows and framed doors, the six landmarks, the cave levels; lit windows in their recesses at night. Nothing else changed in the pictures (the map name's timing aside). |
| Doors | Stand south of the door and hold Up (`door-test.sh`, Adventure camera): the door opens in its frame and the player is inside - the Name Rater's house and the Battle Tent (Slateport), a Lilycove house, Wanda's house (Verdanturf), Cozmo's house (Fallarbor), the Trick House, both cable car stations, the Battle Pyramid, the Battle Arena, Trainer Hill: 11 doors, `0c4b1f85c`'s build for 7 of them (the others with earlier builds of this round). On the rocky maps the key has to be held longer: the game runs slowly there on software GL. |
| Switched layouts (V40) | Route 111 from a save with the Mirage Tower gone: layout 392 logged, sand where the tower stood, Trainer Hill standing; from a save with it shown: layout 27, the tower. |
| Terrain cost (V37) | Jagged Pass, 1280x720, the same spot, before indexing and after: 948,870 vertices built in both, 632,580 uploaded with 948,870 16-bit indices; the game's GPU buffers 33.9 MB to 24.8 MB; the pictures identical but for the ash motes and the map name. |
| 3D battles (trial merge with `claude/battle-environments-2`, its TEST build, not merged anywhere) | Builds; its `check-diorama` passes with the skirts' own test left out (the battle side's risers kept); `survey.py` on 32 maps (the caves with levels, the Lavaridge relief, the towns and routes with new roofs, the Battle Frontier): 32 pictures, every battler's foot error 0 px; battles on a raised floor stand on it (Victory Road 1F a tile up, Meteor Falls B1F half a tile). |
| Benchmark, software GL (`--benchmark 8`, 1080p, the same spots) | Checkpoint -1's build / option B before indexing / the final build, the same spot each: Jagged Pass 1.7 / 2.2 / 2.7 fps (median frame 624 / 499 / 389 ms; terrain on the GPU clock 364 / 257 / 208 ms; 937k / 843k / 843k triangles; the game's GPU memory 82.7 / 79.1 / 70.0 MB); Mt. Chimney 1.5 / 1.7 / 2.2 fps (732 / 664 / 467 ms; terrain 513 / 426 / 289 ms; 1986k / 1670k / 1670k triangles; 128.2 / 118.7 / 100.2 MB); Slateport 5.4 / 5.7 / 5.1, Lilycove 5.7 / 5.7 / 5.9, Mauville 5.6 / 5.5 / 5.6 fps (towns fill-bound on software GL: the same within its noise; the new roofs add 0.5-5 % triangles, GPU memory unchanged). Process RAM: towns and Jagged Pass the same within 5 MB (208-220 MB, 424-427 MB); Mt. Chimney 427-466 MB before indexing and 513-516 MB after (five runs each) - llvmpipe's own queue of binned triangles for its rasterizer threads, which runs further ahead now; with llvmpipe on one thread the indexed build uses 26 MB less (V37). Software numbers only. The checkpoint's own `benchmark\run-benchmark.bat` (full) ran under Wine from the checkpoint's folder layout after the checkpoint was made: all 14 scenes at 1080p, 1440p and 4K (42 rows in `results.csv`) and the four before runs with checkpoint -1's exe found next to it; Jagged Pass 2.0 / 2.8 fps at 1080p, 1.5 / 2.0 at 1440p, 1.1 / 1.3 at 4K (-1 / this checkpoint; Wine and software GL, about 33 minutes in all). |
| Before/after under Wine, both cameras | `0c4b1f85c`'s Windows exe (`3e407ba0...`) against checkpoint -1's (`cb58d4e8...`), 1920x1080, a fresh folder each, Adventure then Diorama camera: Slateport's market, Lilycove, the Battle Pyramid, Victory Road 1F - the new roofs on Slateport's and Lilycove's houses, the Pyramid standing, Victory Road's raised floors and decks; nothing else differs (`pictures\other\wine-*.jpg`). The new exe's first Slateport run was still at the title screen when the script pressed its keys; the same run again went in. |
| Players menu in 3D (V42) | `native_trade_proof.py` with two Linux 3D clients (`--hold .5 --gap .6`): with `0c4b1f85c`'s build the trade went through while both screens showed only the field (native-trade-3d-u11-before2); with `8e4604993`'s the trade screens show over the 3D field, and the trade, back-out, restart and the host store check pass (native-trade-3d-u11-after; `pictures\other\players-menu-in-3d-before-after.jpg`); the same with two Windows clients of the checkpoint's exe under Wine (native-trade-wine3d-u11, `players-menu-in-3d-wine.jpg`). GBA ROM rebuilt: unchanged. `check-native`, `check-abi`, `check-diorama` pass again on `8e4604993`. |
| Multiplayer | native-checkpoint-3d-14 (Linux 3D, `0c4b1f85c`'s build, 2 clients): enrol 1.53/1.54 s, saves 1.54-1.55 s, restart, live recovery 40.9 s, host store intact; native-trade-7 (the Linux 2D build - nothing in it changed this round, `make` rebuilt nothing; the last commit's `main.c` lines compile only with `DIORAMA=1` - 2 clients): both offers, one confirmation commits nothing, the trade applied in both games (41.5 s), back-out aborts, restart keeps both parties, host store intact. |
| Launcher package | "Native 3D preview 7" built under Wine (PyInstaller, package audit: 1009 files, import off), its runtime the checkpoint's exe (sha256 `918e1be1...`, stripped; it ran Lilycove under Wine, both cameras; the Wine trade proof ran its unstripped twin `b25131eb...`). |

Not seen yet: any of it on a graphics card (V39); the high-tide Shoal Cave in game (the
tide only changes on entering from outside).

## Graphics handoff: building heights, windows at night, the message box, the relief's cracks (2026-10-12)

The owner approved option B (`native-wip-20261012-2`) and asked for the remaining graphics
issues to be finished before the branch goes to the main integration session: V29 (building
heights) and V32 (windows that should light up at night), keeping every approved roof, terrain,
cave and environment improvement, the Players menu fix and multiplayer, touching nothing of the
UI, sprites, Battle FX or characters, and staying compatible with the 3D battle branch (Sky
Pillar's rubble). The battle session's `combined-dev-20261012-1`, delivered meanwhile, reported
one regression of option B in this branch's terrain (its E14, here V47); it is fixed here too.
Engine `claude/graphics-overhaul` `8e4604993`..`53bb34a63`, tag `graphics-handoff-20261012`;
checkpoint `graphics-handoff-20261012`. Commits, merge notes and rollback:
`docs/graphics-handoff.md`. With V29 and V32 resolved, the graphics development phase is ready
for integration; the frame rate on a graphics card (V39) is tracked separately.

### What the player gets

* **Buildings as tall as their drawing (V29).** Sootopolis's 11 tower houses stand up to their
  roof's outline (they stopped at the door's lintel, 8 rows lower); the Cove Lily Motel
  (Lilycove) and the Battle Dome (Battle Frontier west) have their second storey, which was laid
  back as roof; Route 113's glass workshop is one building on its own four rows with its window
  (it took the trees over it for its roof and left its window's cell out, a hole in its front).
* **Windows at night (V32).** The windows that stayed dark light up: Slateport's, Petalburg's,
  Lavaridge's and Verdanturf's houses, with every pane of the white-barred sash windows;
  Mauville's Game Corner's display windows and every bulb round its door; Lilycove's department
  store; the Battle Frontier's lounges and exchange corner; Sootopolis's arched windows, drawn in
  stone (its emblems and doors, in the same greys, stay dark).
* **Messages stay on screen (V43, the UI session's U12).** A sign's or a person's last line
  stayed in the 2D game but vanished from the 3D view as soon as it was printed, while the game
  waited for a button; the save prompt was never shown in 3D. Both stay now.
* **No cracks along the Lavaridge relief (V47, the battle session's E14).** Thin lines of the
  sky's colour (black underground) ran along the rock steps of Mt. Chimney, Jagged Pass, Fiery
  Path and Magma Hideout, in the field and in the battles there, since option B; they are gone.

What stays as it was: every other building, roof, window, door and cave level; the terrain (but
for V47's undersides), props, lights and settings; the Players menu over the 3D field (V42); the
GBA ROM. `buildings.bin` differs from option B's only in the V29 buildings.

### How it works

* V29 (`tools/diorama_buildings/auto_buildings.py`): a facade's height is the first long edge
  over the door (`facade_height`). A survey drew every automatic building's drawing with that
  edge marked and a 3D preview from 35 degrees (scratch tools, not committed); four were wrong.
  The fixes are data: `OVERRIDES` (`"facade"` for the motel, 64, and the Battle Dome, 56; the
  workshop's `"cols"`, `"top"`, `"cells"` and facade 28) and `CRATER_HOUSES` `"facades"`
  (`{"tower": 28}`, read by `crater_specs`). `test_auto_buildings.py` `HeightTests`.
* V32 (`tools/diorama_buildings/window_glow.py` `find_page_windows`, called by `export_gl.py`):
  the page's windows as before (the same pieces on all 137 pages, so `dimensional.py`'s recessed
  windows are the same and no lit window is lost), then each model's drawing on its own
  (`model_rects`): a pane whose glass is another building's wall colour on the page (at least
  3 x 2, not running out to the drawing's side; pale glass only where a frame of one colour
  closes round it, `enclosed`); every pane of a window past glazing bars of its frame's colour
  (`whole_window`); shop windows a frame holds at its sides only (`shop_window`); arched stone
  windows (`stone_panes`: grey with white glints in a dark blue outline, an arch over straight
  sides, a white sill). `test_window_glow.py` (22 tests, 10 new).
* V43 (`src/diorama/scene/scene_snapshot.c`): `FieldMessageBoxShown` - a message printing, or
  window 0's first tile in the window layer's tilemap (`WindowShown`) - decides the dialogue scene
  and the text box over the 3D view, where `IsFieldMessageBoxHidden()` alone did.
* V47 (`src/diorama/terrain/terrain_mesh.c`): `DropBaseUndersides` (`9d63e60f5`, V37) is gone.
  The terrain is drawn from both sides; where a merged face's edge meets smaller faces (a
  T-junction) the rasterizer leaves pixel-wide cracks, and the column's underside behind them is
  what shows there. Without the undersides the sky (or the caves' clear colour) did. The cost
  comes back (V37: about 11 % more terrain work at Jagged Pass); the indexing's saving stays.

### Verification

Engine `c806a788c` for the checks; the V29, V32 and V43 pictures used the builds of `61935f7eb`
(`c806a788c` changes a comment and a test's names: `buildings.bin` and `buildings.generated.c`
are byte for byte the same). "Before" is `native-wip-20261012-2`'s build (`8e4604993`). V47
(`1d54639cf`; after it `53bb34a63` changes only the renderer's README) changes `terrain_mesh.c` only: `check-diorama` ran again on it, and
the V47 pictures, the Windows exe, the multiplayer proofs marked "(final)" and the second trial
used its builds; "before" for V47 is `61935f7eb`'s build (the terrain of option B).

| Check | Result |
| --- | --- |
| Linux and Windows 3D builds | Compile; the Windows exe imports only `SDL2.dll` and Windows' own DLLs (`objdump -p`). The 2D Linux build compiles (no warnings). |
| `check-native` | Pass: platform 1067, bridge 4186, display settings 244, PNG writer 176 checks. |
| `check-diorama` | Pass: 13 test programs (camera 403 checks, far field 54,618, `test_props` 5703, snapshot exchange, presentation transition, UI overlay, terrain mesh, ...), compositor goldens (18,318 metatiles, 75 tilesets), rules valid, generated tables current. Again on `1d54639cf`: pass (the terrain mesh tests with the undersides back). |
| `check-abi` | Pass (172 types). |
| Rules and building tools (each file run) | `test_compile_rules` 23 of 24 (the one failure is V31, as before); `test_tile_shape` 8, `test_structures` 13, `test_measured_volumes` 8, `test_mountain_art` 5, `test_terrace_topology` 8, `test_pixel_objects` 15, `test_catalog` 8, `test_occupancy_model` 8, `test_window_glow` 22, `test_auto_buildings` 16, `test_dimensional` 14 pass; `test_rules_parity` fails as before (V2, upstream). |
| The generator's proof (`--verify`) | 573 of 573 models exact against their drawing (98 of 98 automatic; roofs and details left out as before), 50 rooms composed with the terrain, 0 pixels differ. |
| `find_windows` over a page | The same pieces as `8e4604993`'s on all 137 pages (so the recessed windows are the same); `buildings.bin` with V32 byte for byte the V29 build's. |
| Windows at night, census | The 260 windows `dimensional.py` sets back outdoors, against the window runs: 12 dark before, 2 after (V44, a shading band). On the 58 outdoor pages 612 windows to 654, 17,297 lit texels to 22,785, 2,884 window runs to 3,842 (every page; no window lost or shrunk). Each new or grown window looked at in crops of its page (before / after). |
| GBA ROM | Unchanged, sha256 `f214735b...3387`. |
| Python tests | 1399 passed, 1 skipped. |
| V29 before/after, Linux 1920x1080, both cameras, 12:00 | Sootopolis (9,8), Lilycove's motel (37,26), the Battle Dome (19,20), Route 113's workshop (33,7): 8 pairs. |
| V32 before/after, Linux 1920x1080, 22:00 | Slateport (21,46) and (5,21), Mauville's Game Corner (8,16, both cameras), Lilycove's department store (27,9), Sootopolis (23,7, both cameras) and (55,7), Verdanturf (6,17), Petalburg, Battle Frontier east (22,53): 11 pairs. |
| V43 before/after, Linux | Rustboro's Gym sign from (23,20): its last line ("The ROCK-loving honors student!") gone while the game waits, with the handoff's build on screen (two runs); START > SAVE: the prompt missing, then shown with the save info and YES / NO. |
| Windows exe under Wine, before/after | Lilycove and Slateport's market, both cameras, in the evening (Wine's clock), against `native-wip-20261012-2`'s exe: the department store's windows lit. Jagged Pass at noon, both cameras, the final exe against `61935f7eb`'s: the cracks' colour on 0.97 % and 0.87 % of the picture before, none after (V47). The final exe imports only `SDL2.dll` and Windows' own DLLs, large-address-aware. |
| V47 before/after, Linux 1920x1080, both cameras, 12:00, the 3D view's ash off | Jagged Pass (21,16) and (14,24), Mt. Chimney (16,14), Fiery Path (19,8), Magma Hideout 2F's third room (49,11): the cracks' colour - the sky's (173-176, 207-209, 226-232) outdoors, (8-13, 13-15, 17-19) underground - on 0.72-2.31 % of the picture before, on one lone pixel after (Mt. Chimney, Adventure camera): 10 pairs. |
| V47's cost (V37) | The benchmark's `jagged` scene at 1280x720 (`PKMN_DIORAMA_CHUNK_LOG=1`, `--bench-csv`), 49 chunks: 948,870 vertices built and 632,580 uploaded before, 1,055,694 and 703,796 after; 842.5k triangles a frame before, 936.8k after; the game's GPU memory 52.7 MB, 55.6 MB. |
| Players menu in 3D (V42) and multiplayer | native-trade-3d-handoff (2 Linux 3D clients) and native-trade-wine3d-handoff (2 clients of the handoff's Windows exe under Wine): the trade screens over the 3D field, trade applied (48.7 / 49.7 s from the first confirmation), back-out, restart, store intact; native-checkpoint-3d-15 (2 Linux 3D clients): enrol 1.45/1.61 s, saves 1.41-1.71 s, restart, live recovery 40.6 s, store intact. (final) native-trade-3d-handoff-v47 and native-trade-wine3d-handoff-v47 (the final Linux build; the final Windows exe under Wine): the same, trade applied 49.0 / 49.8 s from the first confirmation; native-checkpoint-3d-16: enrol 1.54/1.54 s, saves 1.49-1.54 s, restart, live recovery 40.9 s, store intact, source saves unchanged. |
| With the integration, second trial: `8706f8f6c` (emeraldtogether-integration-20261012-3) merged with `1d54639cf`, then the battle session's `5699d58b3` (V46 = its E13) cherry-picked, in a scratch worktree (not a branch, removed) | `git merge-tree`: no conflict, and none for the cherry-pick. GBA ROM byte-identical. TEST build, `PKMN_NATIVE_UI=0`: 14 battles at noon drawn in 3D with foot error 0 px - Sky Pillar 1F, 3F, 5F and the top on their switched layouts (433, 435, 437, 438; the rubble round Rayquaza), Route 131 (switched, 319), Mt. Chimney, Jagged Pass, Fiery Path, Magma Hideout 1F and 2F's third room (void 0 in every one: V47), Mauville, Lilycove, Sootopolis, Route 113 - and Lilycove and Sootopolis at 22:00; Sky Pillar's top and Mt. Chimney in the field, both cameras; Rustboro's Gym sign to its last line with the native UI on (its box) and off (the game's box). A Jagged Pass battle's view: 188,086 triangles (168,812 on the first trial, without the undersides). |
| With the integration, first trial: `7a98bd4a5` merged with the handoff at `61935f7eb` (scratch, removed) | `git merge-tree`: no conflict. GBA ROM byte-identical. TEST build: 10 battles drawn in 3D (Battle Frontier east, Jagged Pass, Lilycove, Mauville, Meteor Falls, Route 113, Route 119, Slateport, Sootopolis, Victory Road; Lilycove and Sootopolis also at 22:00); Sky Pillar's four floors drawn in 2D - the battle frame's layout id against the snapshot's (V46) - and in 3D with V46's line in `battle_capture.c` (a scratch change on the trial: 1F, 3F, 5F, and the top with the rubble standing round Rayquaza; Mauville unchanged); Sky Pillar's top in the field: the rubble standing (both cameras; flat on the graphics branch alone); the Gym sign with the native UI on (its box) and off (the game's box). |

Not seen yet: any of it on a graphics card (V39).
