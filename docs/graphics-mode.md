# Graphics mode: 3D Diorama or Classic 2D

Branches: app `claude/graphics-mode-selector`, engine `claude/graphics-mode-engine` (both from the
2026-10-14 setup branches; nothing merged). PC builds only; the GBA ROM is not touched.

## What the player gets

* **Help > Game display > Graphics mode** (and a **Test 3D graphics now** button): *3D Diorama
  (default when supported)* or *Classic 2D*. The choice is saved per PC (`graphics-mode.json` in the
  launcher's private folder) and restored on every launch. A package without a Classic 2D game offers
  only 3D.
* **Before every start** (Host Game, Join Game, and the first-time setup that also starts a game) the
  launcher asks the 3D game whether it can start here (`--probe-graphics`). If it cannot, a prompt
  explains in plain language and offers **Launch in Classic 2D** or **Cancel**. Launching in 2D is for
  that start only: the saved preference stays 3D (never forced to 2D), and Cancel changes nothing.
* **Manual 2D** works on any PC, including ones that support 3D; the 3D check is then skipped.
* If a game's graphics fail after all (a driver that passed the check and then failed), the game itself
  shows a message and exits with code 78; the launcher shows its own explanation. Nothing closes
  silently.

## Switching keeps everything

Both games are built from the same engine source and differ only in how they draw (`Makefile_pc`:
`DIORAMA=1` is the 3D game). The launcher starts either one with the **same** `--save`, `--bridge` and
`--config` files and the same verified ROM pairing, so saves, Pokémon, inventory, progress and the
multiplayer character are untouched. One thing did need care: the game rewrites the settings file from
scratch, and the 2D build does not know the 3D view's own keys (camera, trees, zoom, tilt). The 2D build
now keeps those lines as they were, so switching to 2D and back loses no 3D choice
(`check-graphics-mode`).

## Can the mode change while a game is running? No: restart based

* The 3D renderer and the Classic 2D renderer are **different programs** chosen at build time (the 3D
  game compiles the OpenGL compositor in, the 2D game an SDL renderer). One process cannot become the
  other.
* The 3D game's F4 (3D/classic *view*) stays inside the 3D program and still needs OpenGL 3.3, so it
  does not help a PC where 3D cannot start.
* An automatic restart would have to close a game that holds the save in memory, the host connection,
  a battle/trade recovery state and the save lease. The launcher already has a safe close for that
  (Save now, normal close, recovery rules); this feature does not bypass it.

So the mode is chosen when a game **starts**. Changing it while a game runs saves the choice and says so:
"A game that is running keeps the graphics it started with. Close it, then start again to switch."
The restart goes through the existing safe close, then Host/Join again.

## Parts

| Part | File |
| --- | --- |
| Check, preference, decision, explanation | `src/emerald_multiplayer/graphics_mode.py` |
| Window flow, prompt, settings row | `src/emerald_multiplayer/launcher_graphics.py`, `launcher_gui.py` |
| Bundle with two games (`classic_executable`, `RuntimeBundle.graphics`) | `player_runtime.py`, `scripts/windows-runtime/collect_native_bundle.py` |
| Engine: `--probe-graphics`, message + exit 78, settings pass-through | `src/platform/sdl2.c`, `src/diorama/gl/gl_compositor.c` (`DioramaGL_Probe`) |
| CI | `.github/workflows/windows-package.yml`, `scripts/windows-runtime/ci_graphics_check.py` |

`--probe-graphics` runs the checks that make the 3D game's own start-up fail (an OpenGL 3.3 core
context, every entry point, the compositor's shaders; for the 2D game an SDL renderer) on a hidden
throwaway window, prints one JSON line and exits 0 (usable) or 78. It reads and writes no save or
settings file. Test hooks: `PKMN_GRAPHICS_FORCE_FAIL=<text>` makes either game fail as if the renderer
were unavailable; `PKMN_GRAPHICS_NO_DIALOG=1` prints the message instead of showing a message box.

## Tests

* `tests/test_graphics_mode.py` (33): preference (default, saved and restored, unreadable file kept, no
  forced 2D); the check's parsing (supported, unsupported with reason, crash, hang, garbage); the launch
  decision for **supported 3D**, **unsupported 3D**, **manual 2D** and **failed initialization**; the
  window flow with a fake Tk clock; the real Tk prompt (Launch in Classic 2D / Cancel / 2D unavailable);
  the runtime bundle with and without a 2D game (tampering, malformed records); the bundle collector;
  and that the two modes start different programs with identical `--save`, `--bridge`, `--config`
  arguments while the save and private files stay byte-identical.
* Engine `make -f Makefile_pc [NATIVE_LINUX=1] [DIORAMA=1] check-graphics-mode` (7 checks on the 2D
  game, 6 on the 3D game): usable graphics, the probe writes no file, failed initialization exits 78 with
  a reason, a failed start explains itself and creates no save or settings file, the 2D game keeps the 3D
  settings lines.
* `ci_graphics_check.py` against the real packaged games (below).

## What the Windows runner proves, and what it cannot

See the results recorded below ("Evidence"). A GitHub-hosted Windows runner is a **virtual machine
without a graphics card**; its OpenGL is Windows' built-in 1.1 software renderer. That is the right
machine for proving the **failure path and the fallback**: the real 3D exe cannot create what it needs,
the real check says so, the real Classic 2D exe starts. It says nothing about real GPUs and vendor
drivers, DPI scaling, exclusive fullscreen, audio devices or controllers; those still need a person at a
real PC. The *success* path of the 3D check was exercised on Linux with Mesa's software renderer (also
not a real GPU), and the real-driver-limit case with Mesa forced to OpenGL 2.1.

## Evidence

GitHub Actions run 38655648745 (workflow `windows-package`, branch `claude/graphics-mode-selector`, app commit
`f622f01`, engine `claude/graphics-mode-engine` commit `730aba1e`, full mode, windows-2022 runner). Both jobs
succeeded; the graphics step printed **16 of 16 checks passed**:

* 3D check on the VM: `supported=False, reason='functions', detail='glActiveTexture is missing',
  renderer='GDI Generic', version='1.1.0'` (a definite answer, not a hang or crash).
* Decision: unsupported 3D means the player is asked first; the explanation names Classic 2D and says the
  save is unchanged. "Launch in Classic 2D" selects the pinned 2D game; the saved preference stays 3D; a
  manual 2D choice never runs the 3D check.
* The real Classic 2D game passes its own check (`direct3d`) and stays running for 20 s.
* The real 3D game with unsupported graphics exits **78** with the explanation (it does not close silently
  or crash) and creates no save or settings file; forced renderer failure behaves the same for both games.
* Classic 2D keeps the 3D view's settings lines.
* Package: both game executables are the engine job's builds (sha256 `69ab8fd5…ba20` 3D, `48ca6c6c…54f7` 2D);
  the frozen launcher stayed up for 20 s.

Not shown by this run: a real GPU with a vendor driver, audio, controllers, fullscreen/DPI behaviour, the
success path of the 3D game on Windows, and any gameplay or network behaviour. The VM has no sound device
(`WASAPI can't find requested audio endpoint`) and no sprite pack or base ROM.
