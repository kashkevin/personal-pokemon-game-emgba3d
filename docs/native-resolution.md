# Native PC resolution, display modes and graphics quality

Owner directive 2026-10-10 ("NATIVE PC RESOLUTION UPGRADE - 1080P, 1440P AND
4K"). Engine branch `claude/native-resolution` (from `claude/native-graphics`
`edd1f5105`), verified and fast-forwarded into `claude/native-graphics`
(`b86ea813a`, tag `graphics-wip-20261010-5`); app branch `claude/native-resolution`
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
| Camera, Trees | Adventure / Diorama (since `graphics-wip-20261010-6`; 3DS close / Wide before), 3DS / Voxel | Adventure, 3DS | F10; F7, F8 (F9 photo mode, F12 picture: `docs/graphics-overhaul.md`) |

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
a choice, so those files get the new 1080p default. `windowScale=` is written back
only for a kept size an older build also has.

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
* **PC interface** (F10 settings menu, frame rate): drawn as the UI art direction
  asks (the UI session's `artifacts/ui-art-direction/docs/ART_DIRECTION.md`,
  version 2): the engine's own bitmap fonts with their built-in shadow, the
  original Route Caps face for the title tab and key caps, a cream sheet in the
  Emerald green frame with stepped corners, the red cursor arrow and orange value
  arrows, on a 640x360 logical canvas drawn once and shown at a whole-number scale
  with nearest-neighbour sampling: x2 at 720p, x3 at 1080p, x4 at 1440p, x6 at 4K.
  A window of another shape gets a longer canvas (more room), never a stretched
  one. No system font is used in the game.

## Windows display scaling and several displays

The game declares itself per-monitor DPI aware (SDL hint `permonitorv2`): sizes
are physical pixels and Windows never stretches its picture (no blur at 125-200%
scaling). A fullscreen window moved to another display (Win+Shift+arrow, a display
unplugged) goes fullscreen there at that display's size. The launcher declares
system DPI awareness before its first window, so its text is drawn at the
display's scaling instead of being stretched. Neither can be tested on the cloud
computer (no Windows display scaling, one virtual display): owner test.

## Benchmark and reference hardware

`pokeemerald-mp-diorama.exe --save test.sav --benchmark [seconds]` (the
checkpoint's `benchmark.bat`): the game boots and Continues by itself (Start past
the intro, then A every 3 seconds until the first 3D frame, at most 90 seconds; the
save should stand outdoors), then draws the 3D scene at 1280x720, 1920x1080,
2560x1440 and 3840x2160 in turn with VSync off and the player's quality, counts the
frames after a 3-second warm-up (15 seconds each by default) and writes
`benchmark.log`: average frame rate, 1% low, median, 99th percentile and worst
frame time, how many frames showed the 3D scene, the GPU (OpenGL renderer string),
CPU, RAM and display, then quits. Nothing is saved.

Reference hardware: the owner's PC (`kevpc`), as its `benchmark.log` records it;
the target is a steady 60 frames a second at 1920x1080 on High there, higher
resolutions as its GPU allows. No real-GPU number exists yet. The cloud computer
has no graphics card (Mesa llvmpipe, software rendering on 2 cores of a Xeon at
2.8 GHz); its numbers are software measurements only, Littleroot Town, High,
5 seconds a resolution:

| Resolution | Linux build: frames (all 3D), average fps, 1% low | Windows build under Wine: average fps, 1% low |
| --- | --- | --- |
| 1280x720 | 41, 8.3, 6.7 | 7.9, 6.2 |
| 1920x1080 | 27, 5.6, 4.6 | 5.4, 4.5 |
| 2560x1440 | 14, 3.2, 2.6 | 3.5, 2.8 |
| 3840x2160 | 7, 1.6, 1.3 | 2.5, 1.6 |

They say the method works (every measured frame showed the 3D field) and that the
software renderer's cost grows with the pixel count, nothing about a real GPU.

## Verification (2026-10-10)

* `check-native` 1063 + 4186 + 139 (display settings, menu, benchmark) checks,
  `check-abi` 172 types, `check-diorama`: pass. GBA ROM rebuilt from the branch:
  `f214735b...3387`, unchanged.
* Linux 3D build, Xvfb: default 1920x1080 window (fit to 1834x1032 on a 1080p
  virtual display); F10 menu at x2; 1440p chosen, confirmation shown, timeout
  undoes it, Enter keeps it and `resolution=2560x1440` is written; Esc undoes a
  1280x720 change; pixel art exactly 8x at 1440p and 12x at 4K; 4K windowed;
  borderless (openbox) with a 1920x1080 render on a 4K display; exclusive
  fullscreen 3840x2160 with Ultra (4x MSAA).
* Windows 3D build under Wine: F10 menu, frame-rate readout (`showFrameRate=1`
  kept, no `windowScale` written), `--benchmark` writes `benchmark.log` with the
  CPU name from the registry.
* Multiplayer regression with the branch's Linux 3D build: native-checkpoint-3d-7
  passed (two clients: enrolment, saves in 1.6-1.7 s, restart onto the saved
  spots, live recovery in 41.6 s, host store integrity).
* 3D battles at every resolution: on a throwaway trial merge with
  `claude/battle-3d-integration` `732fbef43` (branch `trial/resolution-battle3d`,
  never merged): their `battle-test.sav`, walking into the Shinx, at 1280x720,
  1834x1032, 2560x1440 and 3840x2160 windows: the world, both sprites, the health
  box and the text box in place at each size.

## Coordination

* The 3D battle branches (`claude/battle-3d`, `claude/battle-3d-integration`) are
  not changed. A trial merge (`git merge-tree`) of this work with
  `claude/battle-3d-integration` `732fbef43` has two conflicts, both in
  `src/diorama/gl/gl_compositor.c` and both two sides adding lines at the same
  place (new functions after the frame function; shutdown calls): keeping both
  sides compiles and runs (see Verification). Their battle frame draws straight
  into the window at the window's size (`DioramaGLTarget_Framebuffer()` is 0
  outside the field's offscreen pass), which stays correct at every resolution; to
  follow the chosen render resolution in borderless mode they can draw between
  `DioramaGLTarget_Begin`/`End` (`include/diorama/gl_target.h`).
* The battle session's second round (checkpoint `battle3d-wip-20261010-2`) offers
  `claude/native-graphics-3d-battles` (`7bf42d267`, their merge of the 3D battles
  into `claude/native-graphics` `edd1f5105`) as a fast-forward for the owner's go.
  With the resolution work on `claude/native-graphics` it is no longer one: a trial
  merge (`git merge-tree`) gives three conflicts, all in
  `src/diorama/gl/gl_compositor.c`: the two adjacent insertions above, and the field
  drawing block, where both changed its start (their `composing` flag and an
  aspect from the window; here the scene size from `DioramaGLTarget_Begin`). Their
  `DioramaGLBattle_ComposeFieldBands` draws at the window's size: when the field is
  drawn offscreen (borderless at another render height, or MSAA), it must run after
  `DioramaGLTarget_End` or be given the scene size, otherwise its bands land in the
  offscreen target at the wrong scale.
* The UI session's art direction is followed by the F10 menu (see above). Its
  menus can draw through `DioramaGL_SetOverlay` and the canvas in
  `src/diorama/gl/gl_pc_overlay.c` (engine fonts, Route Caps, panels with stepped
  corners, whole-number scale); the art direction's Options screen, when designed,
  replaces this menu's look.
