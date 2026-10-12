# High frame rates, frame pacing and the benchmark suite (native PC game)

Performance work of 2026-10-11 and 2026-10-12 (directive "8 GB RAM support, 4K 200
FPS optimization and final 3D environment overhaul", phases 2 and 3), engine branch
`claude/graphics-overhaul` from `graphics-wip-20261010-8` (`d799c4a8a`) to
`graphics-wip-20261012-1`. Memory and 64-bit: `64-bit-and-memory.md`.

Every number here was measured in the development container: Linux with Mesa's
software OpenGL (llvmpipe, 2 CPU cores) and the Windows exe under Wine on the same
software renderer. **None of it says how fast the game runs on a graphics card.**
The owner's PC runs the benchmark suite (below); until its results come back, every
frame-rate target of the directive is unverified.

## Status in short

| Target (directive) | Status |
| --- | --- |
| 1920x1080 at 200+ fps | **Unverified** (no graphics card here; the suite measures it) |
| 2560x1440 at 200+ fps | **Unverified** |
| 3840x2160 at 180-200+ fps | **Unverified** |
| Lower-end hardware at 60+ fps | **Unverified** (render scale and quality presets exist for it) |
| Frame-rate limits 60/120/144/165/180/200/240/unlimited + VSync | **Done and tested** (limits hit exactly on the title screen; game speed unchanged) |
| Rendering decoupled from the game's speed | **Done** (it already was: fixed game step, interpolated drawing; kept and tested at every limit) |
| Battle timing independent of the frame rate | **Done** (the battle engine runs in game frames; nothing of it changed) |
| Profiling before optimising | **Done** (per-pass CPU and GPU time, draws, uploads, GPU memory) |
| No per-frame rebuilds or uploads of unchanged data | **Done** for everything measured (table below) |
| Reproducible benchmark with the requested scenes | **Done**; the owner's run is pending |
| Native resolutions vs render scale | **Done**: the benchmark always draws every pixel (render scale 100 %); render scale is a separate F10 setting |

## How a frame is made

* The game itself steps at a fixed 60 frames a second (`sdl2.c`: an accumulator of
  real time, `fixedTimestep`), exactly as before. Battles, the overworld, the
  multiplayer bridge, saves and the world clock all run in these game frames, so
  their speed and outcomes do not depend on the frame rate or the graphics card.
* The 3D view is drawn once per pass of the main loop, interpolating the camera and
  the people between the last two game frames (`frameAlpha`). This was already so
  (the PC port and the Diorama renderer); it is what lets the picture run at 144 or
  240 Hz while the game stays at 60.
* New: a frame-rate limit (F10 "Frame rate limit", `fpsCap=`): 60, 120, 144, 165,
  180, 200, 240 or unlimited. Frames start on an even beat (`frame_limiter.c`: a
  high-resolution wait, then a short spin), only the drawing waits, the game's own
  clock is untouched. VSync (F10) is separate; with VSync on the display paces the
  frames and a limit above its refresh rate does nothing.
* New: what only changes once per game frame is done once per game frame, and what
  does not change is not redone at all (next section). At 200 fps most frames are
  "in between" two game frames and now cost only the drawing.

## What was profiled and what changed

The profiler (`gl_profile.c`; `PKMN_DIORAMA_PROFILE=1`, and every benchmark run)
records per frame: CPU time of each pass (sync and its parts, shadow, terrain,
trees, props, buildings, people, air, field light, resolve, 2D, swap), GPU time per
pass (timer queries, read back later, never waited for), draw calls, vertices,
instances, bytes uploaded by call site, and the GPU memory the game allocated (with
the driver's own numbers where it reports them). A frame three times the average and
12 ms or more is logged as a hitch with its parts.

Findings and fixes, measured in the software renderer (absolute times are the CPU
rasteriser's; what matters is what was redone needlessly):

| Found | Fix | Measured |
| --- | --- | --- |
| Every game frame resolved the 2401 cells' rules again and synced every terrain chunk | Resolve only when a cell, the map, the rules or a dirty cell changed; skip the chunk loop when cells, resolved cells and tiles are unchanged; an animated tile rebuilds only the chunks that read it | Sync 5-10 ms to 0.8 ms a game frame (Route 101 walk); `PKMN_DIORAMA_TERRAIN_CHECK=1`: 0 stale chunks over walks in six places |
| Map changes rebuilt every chunk | Chunk cache across maps, sized by the memory budget | Back from Oldale to Route 101: 47 of 49 chunks from the cache; in and out of a Mart: 49 of 49 |
| A walk built all new chunks in one frame | Chunks near the camera first, at most two off screen a frame | Part of the sync figure above |
| The sun's depth map redrawn for every far chunk built during a walk | Redrawn at most every 250 ms when only casters away from the player changed | Walking (320x180, the same keys): Rustboro 32.9 to 58.4 fps (slowest frame 229 to 87 ms), Slateport's market 26.0 to 41.8, Route 101 to Oldale and back 26.8 to 46.4 (frames over 100 ms: 14 to 0), Petalburg Woods 40.9 to 81.7 |
| The GBA picture (150 KB) and the text-box overlay (150 KB) uploaded every frame although hidden or unchanged | Uploaded only when drawn and changed | Two 150 KB uploads less per game frame |
| Prop art (324 KB) resent whenever the palette faded (night tint, fades) and the prop instances every frame | Only changed pieces; instances only when one changed | Prop uploads 238.7 KB to 0.1 KB a frame |
| The weather layer (150 KB) made and uploaded every frame; it moves 60 times a second | Made and uploaded only when its inputs change | At 200 fps: 60 uploads a second instead of 200 (not measurable here: the software renderer stays under 60 fps) |
| 3DS trees rebuilt and uploaded every sync | Only when the trees in view change | Tree sync 0.36 ms to 0.01 ms |
| The bloom pass asked the driver for the bound framebuffer (a pipeline stall on threaded drivers) | Uses the known framebuffer | - |

What a frame draws (profiled in ten places during the work): 52-88 draw calls,
78k-209k vertices, 59-313 instances (Slateport's market the most vertices, Route 110
the most instances). That is a light load for any graphics card made in
the last ten years; whether the CPU side (one thread drives OpenGL) reaches 200 fps
is what the owner's run will show.

Lighting: the street lamps are 16 point lights at most (the nearest to the camera),
with a smooth falloff and no shadow maps of their own; the sun's single 2048 shadow
map is the only shadow pass. Nothing gives a small lamp its own shadow calculation.

## Resolution and render scale

* The window's resolution (F10 "Resolution", 720p to 4K and the desktop's) is the
  resolution drawn: the 3D scene is rendered at that size.
* "3D render scale" (F10, `renderScale=`): 100 % (default, native), 83, 75, 67 or
  50 %: the 3D scene at that share of the height, scaled up; the pixel-art text and
  menus stay at the window's own resolution. A frame-rate aid for weak hardware.
* The benchmark always runs at 100 %: its 1080p, 1440p and 2160p are true native
  frames (offscreen when the window is smaller, then scaled into the window).

## The benchmark suite

`tools/benchmark` in the engine (README there): the game measures itself
(`--benchmark`) in fixed scenes from fixed saves. Scenes: Route 101, Petalburg Woods,
Rustboro, Slateport's market, Mauville, Granite Cave, Dewford's coast, Route 110
(dense objects), Mauville at night (`PKMN_CLOCK_HOUR=22`), Route 104 in a downpour
(`PKMN_DIORAMA_WEATHER=13`), and three of them with World details off; then three
with the previous checkpoint's build for before/after. Directive scenes not in the
suite: Rustboro stands in for "Mauville and Rustboro"; Lilycove's coast and the
Route 109 beach are not separate scenes yet (Dewford's coast covers sea and beach).

Per scene and resolution it writes the GPU, driver, CPU, RAM, display and settings,
average fps, 1 % and 0.1 % lows, frame-time percentiles (median, 90, 95, 99, 99.9),
worst frame, stutters, CPU and GPU time per frame, draw calls, triangles, uploads,
process RAM and GPU memory (`SCENE.log`, and one row each in `results.csv`).

On the owner's PC: `benchmark\run-benchmark.bat` in the checkpoint folder (about 17
minutes; `run-benchmark.bat quick`: about 4). Results land in
`benchmark\results\run-N`, where Claude reads them.

## Measured here (software renderer; NOT the owner's hardware)

Frame-rate limits, final build (`graphics-wip-20261012-1`), title screen at 320x180,
VSync off, the profile line every 2 s:

| Limit | Presented | Game frames per 2 s |
| --- | --- | --- |
| 60 | 59.9-60.0 fps | 120-121 |
| 144 | 143.9-144.0 fps | 120 |
| 240 | 237.6-240.0 fps | 120 |
| unlimited | 1930-2023 fps | 120 |

The game's speed is the same at every limit (120 game frames every 2 s).

Standing still, `--benchmark 5`, Adventure camera, quality High, the same machine,
checkpoint -8's build (`d799c4a8a`) against the final one; average fps (1 % low):

| Scene | Build | 1280x720 | 1920x1080 | 2560x1440 | 3840x2160 |
| --- | --- | --- | --- | --- | --- |
| Lilycove | -8 | 9.5 (7.3) | 6.4 (5.2) | 4.0 (3.2) | 2.3 (1.9) |
| Lilycove | final | 10.3 (7.6) | 6.7 (4.4) | 4.1 (2.7) | 2.1 (1.5) |
| Route 101 | -8 | 9.6 (6.6) | 6.6 (4.8) | 3.8 (2.9) | 2.1 (1.6) |
| Route 101 | final | 10.0 (7.3) | 6.6 (4.6) | 4.0 (3.2) | 2.2 (1.8) |

Standing still the software renderer is bound by filling pixels (at 4K the full-screen
air pass - dust, rays, bloom - takes 444 of 497 ms on the CPU rasteriser): the
optimisations do not show there, and the extra geometry of phase 4 costs nothing
measurable. They show while walking (the table above: 1.6-2x the frame rate, the
slowest frames halved) and in what a frame no longer uploads.

What a frame costs in the final build (Lilycove, 4K, from the benchmark's log): 77
draw calls, 84k vertices, 189 instances; the CPU sync of a new game frame 0.7-1.1 ms;
GPU memory allocated by the game 38 MB at 720p to 98 MB at 4K (the 4K render targets
63 MB); process RAM 206-265 MB (peak 292 MB) of a 4 GB address space; the game's own
heap 20 KB at its peak of 113 KB. Remaining uploads per frame: the dust motes'
vertices (15.6 KB, moving particles, by design) and animated tiles (water, flowers;
only the slots that changed, once per game frame).

## Not verified

* Any frame rate on a graphics card, at any resolution (the directive's targets).
* The limiter's pacing against a real display's refresh (VSync on a 144 or 240 Hz
  monitor), exclusive fullscreen on a real display.
* GPU time per pass (llvmpipe has no timer queries; the profiler reports them where
  the driver does).
