# Native PC resolution, display modes and graphics quality

Owner directive 2026-10-10 ("NATIVE PC RESOLUTION UPGRADE - 1080P, 1440P AND
4K"). Engine branch `claude/native-resolution` (from `claude/native-graphics`
`edd1f5105`, merged back only after verification); app branch `claude/native-pc`
for the launcher's part.

## What the player gets

| Setting | Values | Default | Where |
| --- | --- | --- | --- |
| Resolution | 1280x720 (performance), 1920x1080, 2560x1440, 3840x2160 | 1920x1080 | F10 in the game; launcher Controls & Help > Game display |
| Display mode | Windowed, Borderless fullscreen, Exclusive fullscreen | Windowed | F10; launcher; F11 switches windowed and the last fullscreen kind |
| VSync | On, Off | On | F10 |
| Graphics quality | Low, Medium, High, Ultra (Custom when single values differ) | High (the look before these settings) | F10; launcher |
| Shadows | Off, Low (1024), Medium (2048), High (4096) | Medium | F10 |
| Lighting | On, Off (weather light, sun dapples, colour grade) | On | F10 |
| Effects | On, Off (dust, sun rays, bloom, mist banks) | On | F10 |
| Anti-aliasing | Off, 2x, 4x, 8x MSAA | Off | F10 |
| Game picture | Standard (8/9 of the height), Largest (as large as fits) | Standard | F10 |
| Show frame rate | On, Off | Off | F10 |
| Camera, Trees | 3DS close / Wide, 3DS / Voxel | 3DS, 3DS (owner's choice) | F10; F7, F8 |

Presets: Low = shadows off, lighting off, effects off; Medium = shadows low,
lighting on, effects off; High = shadows medium, lighting and effects on; Ultra =
shadows high, lighting and effects on, 4x MSAA.

Every choice is kept in the game's settings file (`pokeemerald.cfg` beside a test
game, `game-settings.cfg` in the launcher's private folder) and written only once
it is the player's, as the camera and tree styles are. A resolution or display
mode chosen in the F10 menu is shown at once and must be kept within 15 seconds
(Enter), otherwise the previous one comes back by itself, so a display that shows
nothing cannot lock the player out. Older settings files keep working:
`fullscreen=1` is the borderless kind, `windowScale=` 2, 3, 5 and 6 are honoured as
sizes, and `windowScale=4` (every older file's default, 1280x720) is not taken for
a choice, so those files get the new 1080p default.

## How each picture is drawn

* **3D scene** (terrain, models, trees, characters, Pokemon, shadows, light): drawn
  at the chosen resolution with the camera projection of the window's shape (16:9,
  16:10, 21:9 all see more or less to the sides; nothing is stretched).
  * Windowed: the window is the chosen size (or the largest window of that shape
    the display has room for, keeping its title bar and the taskbar visible); the
    scene is drawn straight into it and follows a resized window.
  * Borderless: the window covers the display at the display's own size; the
    scene is drawn offscreen at the chosen resolution's height and the display's
    shape, then scaled into the window (bilinear). 1080p on a 4K display is the
    performance path; 4K on a 1080p display is supersampling.
  * Exclusive fullscreen: the display switches to its closest mode to the chosen
    resolution at the desktop's refresh rate and the scene is drawn straight into
    it; a display without such a mode gets borderless instead (logged).
  * Multisampling (anti-aliasing) always uses the offscreen target; the bloom
    reads a resolved copy.
* **Pixel-art picture** (the GBA's 240x160: text boxes, menus, battles in 2D, 2D
  scenes): drawn after the scene at the window's own resolution in whole-number
  steps with nearest-neighbour sampling: 4x at 720p, 6x at 1080p, 8x at 1440p,
  12x at 2160p (the same sizes as before at 16:9), and a whole number at any other
  window size (no uneven pixels, no blur). "Largest" uses the largest whole number
  that fits (9x at 1440p).
* **Pokemon and characters in 3D** keep nearest-neighbour texels (crisp pixel art)
  at any resolution.
* **Weather layer** (rain, snow, sand): one whole-number scale covering the window,
  centred, instead of being stretched to the window's shape.
* **PC interface** (F10 settings menu, frame rate): drawn last at the window's own
  resolution with the system's TrueType font (Segoe UI on Windows) rasterised by
  stb_truetype at the exact pixel size: sharp text at any resolution and display
  scaling. Sizes follow the window's height (24 px body text at 1080p, 48 px at 4K).

## Windows display scaling and several displays

The game declares itself per-monitor DPI aware (SDL hint `permonitorv2`): sizes
are physical pixels and Windows never stretches its picture (no blur at 125-200%
scaling). A fullscreen window moved to another display (Win+Shift+arrow, a display
unplugged) goes fullscreen there at that display's size. The launcher declares
system DPI awareness before its first window, so its text is drawn at the
display's scaling instead of being stretched.

## Benchmark and reference hardware

`pokeemerald-mp-diorama.exe --save test.sav --benchmark [seconds]` (the
checkpoint's `benchmark.bat`): the game boots and Continues by itself (the save
should stand outdoors), then draws the 3D scene at 1280x720, 1920x1080,
2560x1440 and 3840x2160 in turn with VSync off and the player's quality, counts
the frames after a 3-second warm-up (15 seconds each by default) and writes
`benchmark.log`: average frame rate, 1% low, median, 99th percentile and worst
frame time, how many frames showed the 3D scene, the GPU (OpenGL renderer string),
CPU, RAM and display, then quits. Nothing is saved.

Reference hardware: the owner's PC (`kevpc`), as its `benchmark.log` records it;
the target is a steady 60 frames a second at 1920x1080 on High there, higher
resolutions as its GPU allows. No real-GPU number exists yet: the cloud computer
has no graphics card (Mesa llvmpipe, software rendering on 2 cores), and its
numbers are only labelled software measurements.

## Coordination

* The 3D battle branches (`claude/battle-3d`, `claude/battle-3d-integration`) are
  not changed. Their battle frame draws straight into the window at the window's
  size (`DioramaGLBattle_Present` returns before the offscreen target), which
  stays correct at every resolution; to follow the chosen render resolution in
  borderless mode they can draw between `DioramaGLTarget_Begin`/`End`
  (`include/diorama/gl_target.h`). Their compositor hunks and these do not
  overlap (checked with a trial merge before merging).
* A UI session's PC menus can draw through `DioramaGL_SetOverlay` and
  `gl_pc_overlay.h` (panels and sharp text at the window's resolution).
