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

### What is left of phase 1

* Neighbouring maps whose tilesets differ from the current map's are still drawn as
  its border block (Rustboro from Route 104, Slateport, Mauville...): the 3DS
  project's static-layout instances, next.
* Petalburg Woods in 3D shows a raised band of ground in its south east whose
  front cuts the 3DS tree crowns in front of it (KNOWN_ISSUES V23); the rules lift
  some Rustboro-tileset forest metatiles there. Phase 2 (geometry).
* Readable player: a building south of the player can cover them (Birch's lab in
  Littleroot when standing just north of it; the old close camera did the same).
  A see-through silhouette or fading what stands in front (KNOWN_ISSUES V24).
* Distant scenery past the 49 x 49 cells (the 3DS project's far border block
  ring) and the other unsupported weathers (sandstorm, thunderstorm, snow,
  drought, downpour, underwater), which still fall back to the 2D view.

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
