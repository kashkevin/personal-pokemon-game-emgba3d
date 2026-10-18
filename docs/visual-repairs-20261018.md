# Visual repairs before the merge (2026-10-18)

The four visual problems the owner reported after the previous update, the reasons the previous repairs did not reach
the game, the repairs, and how each was checked. App branch `claude/admiring-bohr-dpxzuy`, engine branch
`claude/vr-repairs-engine` (on `claude/nu-engine` `6cd8af0f`).

**The original video was not available to this session.** No video file was in either repository, in the container or
in the repository's issues, so it was not reviewed. Issue 3 was reproduced from the written description: a small
screen when entering a new area.

Where things ran: **L** is cloud Linux with software OpenGL (llvmpipe). **W** is the packaged Windows executable under
Wine on the same machine, also with software OpenGL. Nothing here ran on a Windows PC or a real GPU. The screenshots are
in the session's scratchpad, not in Git, because they contain game art.

## 1. Battle effects looked like the plain GBA animations on Windows

**Root cause.** The HD battle effects are data files: the effect core `bfx_core.js`, `bfx_moves.json`, shaders and
textures, about 7.4 MB in the engine's `battlefx/` folder. The game reads them from `battlefx/` beside its executable
(engine `src/diorama/battlefx/bfx_game.c`, `SDL_GetBasePath()`). The Windows runtime bundle held flat files only: the
game, SDL2.dll, the picture pack and the game facts. `collect_native_bundle.py` never copied that folder and CI never
handed it over. So no Windows package ever had it, and every move played its GBA animation. The game logs this as
"Battle FX: cannot read battlefx/bfx_core.js and bfx_moves.json; the original GBA animations play".

**Why the earlier work did not show it.** Update 27 verified the effects in the cloud with the Linux build, run from the
engine checkout, where `battlefx/` sits beside the executable. The Windows CI job only started the launcher and a 3D
start check on a runner with no GPU (`docs/battle-fx-audit-update27.md`). No check looked for the folder in the package.

**Repair (app `47045e9`).**
- `player_runtime.py`: runtime.json `"data"` for native bundles pins each `battlefx/<path>` file by SHA-256 (at most
  64 files, safe names, no programs). `RuntimeBundle.verify()` checks them before every start, refuses links, and
  refuses an unlisted program or script in the folder.
- `collect_native_bundle.py --battle-effects`. `build_launcher.py` copies the files and audits them.
- `installation_check.py`: `battle_effects_missing` and `battle_effects_changed`. Unlisted scripts are named.
- CI: the engine job hands over `battlefx/`, and the package job pins it. The package check fails if
  `battlefx/bfx_core.js`, `bfx_moves.json` or `settings.cfg` is missing. In full mode it also requires at least 20
  files and a core over 1 MB.

**Verified.**
- **L:** seven moves in a real 3D wild battle, each with its own effect: Flamethrower, Thunderbolt, Earthquake, Psychic
  (background), Razor Leaf, Swords Dance (stat change) and Toxic (status).
- **W:** the stripped Windows exe in a bundle collected with `--battle-effects`, launched from another folder as the
  launcher does. It logged "Battle FX: core ready ... runtime\battlefx" and played the HD effects for Flamethrower,
  Thunderbolt, Water Gun, Earthquake, Psychic and Swords Dance.
- **W, control:** the same exe in a bundle without the folder, which is how the earlier packages were built, logged
  "cannot read" and drew the GBA flame sprites.
- App tests: bundle, installation check and package build.

**Not covered.** 226 of 959 animations, mostly moves, have no HD version and play their GBA animation drawn in 3D
(`docs/battle-fx-audit/matrix.md`). That is by design, not this bug. The effect quality adapts to the measured frame
rate, so a slow PC shows a lighter version.

## 2. Objects appeared only when the player got close

**Root cause.** The GBA spawns an object only within two tiles of its own 240x160 picture and removes it past that
(`TrySpawnObjectEvents`, `RemoveObjectEventIfOutsideView`). The 3D camera sees further, north most of all and wider in
a 16:9 window. So trainers, people, item balls and rocks popped in a few steps away.

**Why the previous repair failed.** It made objects that had already spawned stay drawn while offscreen
(`DIORAMA_OBJECT_OFFSCREEN`). Objects the GBA had not spawned yet still had nothing to draw.

**Repair (engine `47767264`).** The snapshot now carries render-only stand-ins, at most 24. Each is one of the map's
object templates outside the GBA's spawn window but inside the view's cells, drawn as it would spawn: its graphics
(after the graphics variables), place, elevation and starting facing, standing still. Its flag still hides it. Things
the GBA would not show are left out: invisible, buried and disguised trainers, berry trees, light sprites and Pokémon.
The stand-in gives way to the real object the frame the GBA spawns it. Nothing is spawned or moved, and no trainer can
see further: the code only reads game state. If an object's palette isn't loaded, it goes into a free slot of the
snapshot only, tinted for the time of day and the screen fade.

**Verified (L).**
- Route 102: trainers Allen and Tiana were drawn before (missing in the old build). Walking north, Allen stays drawn
  continuously as his stand-in becomes the spawned object.
- Rustboro City: three people near the top of the view are drawn (missing before).
- Performance on Rustboro: object sync +0.03 ms and object drawing +0.09 ms a frame; draw calls rose from 72 to 84.
- Determinism: the old build itself gives different wild spawns on two runs (time-seeded RNG). The new code makes no
  random calls and writes no game state.

**Not covered.**
- Objects on a connected map. On the GBA these never exist until you cross the border, so a town's people appear when
  you enter it, as before.
- Moving people stand still until they spawn.
- Objects larger than 32x32.
- Static Pokémon such as legendary encounters.

## 3. A small screen flashed when entering a new area

**Root cause.** When the 3D view became ready on a new map (a door, a warp, walking into the next town or route), or
after a stretch of 2D, the compositor did this: it snapped the GBA's 240x160 picture to full opacity over the 3D field,
boxed in the middle of the window at whole-number scale, and faded it out over 0.12 s (`gl_compositor.c`,
`SnapOpacity(1.0)` on a map change). On a PC at 60 fps that is about seven frames of a small 2D screen in the middle of
the view at every area change. It shows black over the room after a door, and the bright 2D map when crossing a route.

**Why earlier checks missed it.** The fade is timed in seconds. The cloud's software renderer draws one frame per 0.1
to 0.3 s, so the box showed for one frame or none. "Door warps stay in 3D" in
`docs/windows-gameplay-repairs-20261017.md` was judged from those captures.

**Repair (engine `df5f960b`).** The GBA picture there is the field the 3D view draws, or black during a fade, so it is
no longer laid over it. The opacity snaps to 0 on a new map and after a hard 2D stretch. Only leaving a soft 2D
fallback on the same map still fades: a text box the 3D view could not draw. `PKMN_DIORAMA_TRANSITION_LOG=1` logs what
each frame shows.

**Verified (L).** The transition matrix counts frames with the GBA picture over the 3D field.

| Case | Before | After |
| --- | --- | --- |
| Pokémon Center in and out twice | 13 | 0 |
| Pokémon Center at 1920x1080 | 5 | 0 |
| Pokémon Center at 960x600 | 8 | 0 |
| Mart | 7 | 0 |
| House | 7 | 0 |
| Route 101 into Oldale Town | 4 | 0 |
| Oldale Town into Route 101 | 3 | 0 |

Captures: Route 101 into Oldale Town shows the boxed 2D picture before and none after. Entering the Pokémon Center
shows a black box over the dimmed room before, and the room fading in after. Frames during the map's own load are
black in both builds. `check-diorama` passed.

**Not covered.** Real 60 fps on a PC was not observed. The fix removes the overlay whatever the frame rate.

## 4. The Pokémon Center healing animation was missing

**Root cause.** The healing effect is made of field-effect sprites: the Poké Balls placed one by one, their glow and
flash, and the monitor (`field_effect.c`, `FLDEFF_POKECENTER_HEAL`). The 3D view drew object events only, so the
machine stayed empty while the jingle played. A trainer's "!" was missing for the same reason, so it was fixed too.

**Repair (engine `4e213ddf`).**
- The snapshot carries field-effect sprites: the healing machines' sprites (Pokémon Center and Hall of Fame,
  `DioramaFieldEffect_IsMachineSprite`) and the emote icons over walkers (`DioramaTrainerSee_GetIconOwner`).
- The renderer stands a machine sprite on the frontmost model face that is there at its height, which is the machine's
  front rather than the wall behind it. An icon follows its walker.
- These sprites never switch the view to 2D. The hooks are behind `ENABLE_DIORAMA`.

**Verified (L).**
- GBA and 3D frames side by side through the whole effect, with 3 and 6 Pokémon. The balls appear one by one in two
  columns, glow red, flash yellow, the monitor flashes, and everything clears at the end.
- With a hurt, poisoned party (`PKMN_DEBUG_HURT=1`, 4 Pokémon), three runs gave HP 40/165 with status poison, then
  165/165 with no status at frame 701. The player then walked away, so control returned.
- The "!" appeared over trainer Calvin (Route 102) in 3D, matching the GBA frames.

**Not covered.** The heal sound plays as before; it was not checked by ear in the cloud.

## ROM and gameplay

- The GBA ROM rebuilt at the engine head has SHA-256 `f214735b64e113fd10730eacca5764d757f2c93a3685230aa905af7a7cdd3387`,
  unchanged. Every engine change is PC-only (diorama code, or `ENABLE_DIORAMA` / `PORTABLE` blocks), and the
  GBA-shared code only gained read-only accessors.
- Saves, the multiplayer protocol and the installer flow are unchanged. The runtime bundle gained optional pinned data,
  and bundles without it still verify.

## Checking on a Windows PC

1. Battle effects: start a wild battle and use a few different moves. Each should have its own effect: fire as a
   stream of flame, electricity as a bolt, Psychic as a coloured background. "Settings, Check installed game files"
   should report no problem.
2. Distance: walk toward a route with trainers, or a town with people. They should be visible from the edge of the
   view, not appear a few steps away.
3. Area changes: walk in and out of a Pokémon Center, a Mart and a house several times, and cross from a route into a
   town. No small picture should flash in the middle of the window. Try a smaller window and fullscreen.
4. Healing: with a hurt Pokémon, talk to the nurse and choose YES. The balls should appear on the machine one by one,
   glow and flash, the monitor should flash, and you should be able to walk away afterwards.
