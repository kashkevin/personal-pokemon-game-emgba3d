# Update 27 — Battle FX, animations and visual effects audit

Engine `claude/dev-update27-battlefx-engine`, app `claude/dev-update27-battlefx` (cut from the Update 26 default branches, engine `903e63b8`, app `e3adf05`).
Per-animation results: `docs/battle-fx-audit/matrix.md` and `matrix.json` (959 rows).

**Everything here was run in a cloud simulation: Linux, software OpenGL (llvmpipe), a virtual screen, scripted input. Nothing was run on a real GPU or a real
Windows PC. "Rendered" below means the game drew it into the window in that simulation; "inspected" means a person looked at the captured picture.** GPU
times in the reports are the software renderer's and say nothing about a graphics card.

## What exists, and what the audit found

The game has two presentations of a battle move:

* **Native 3D (the Diorama game).** The game's own animation script still runs (timing, sound, palette fades, battler motion, the length of the animation).
  For the 621 moves and the 83 battle animations in the Battle FX package (`battlefx/`), the Battle FX core replays the same script and the 3D view draws **HD
  effects** (particles, ribbons, meshes, lights) in place of the GBA effect sprites. For every other move (numbers 622–847: Generation 6 additions to
  Generation 9) there is no HD data; the **game's own effect sprites and background** are drawn into the 3D view as before.
* **Classic 2D.** The plain GBA renderer; every animation is the game's original. There is no HD layer.

| | |
|---|---|
| Moves in the game (numbers 1–847, distinct) | 847 |
| of them with HD effects (Battle FX package) | 621 (652 animation rows; a two-turn move has a row per turn) |
| of them played as the game's own animation in the 3D view | 226 |
| Z-Moves (37) and Max / G-Max moves (51), numbers 848–934 | not tested: Dynamax is off (`B_FLAG_DYNAMAX_BATTLE 0`) and no map or script places a Z-Power Ring or Dynamax Band; their scripts exist |
| Battle animations (status, stat change, weather, Mega Evolution, shiny, level up, substitute, ...) | 81 rows (the package's 83 less 2 controller entries played in the shiny and send-out checks) |

### Results of the 3D gallery (each animation played at a wild battle's action menu, 959 rows)

| Column | Result |
|---|---|
| Animation triggered and ended (the game's own animation ran to its end) | **959 of 959** (3 Safari-only animations, the Poke Block throw, the rock throw and the trainer's ball throw, wait for a Safari Zone battle: played there, all three ended) |
| HD effects: every compared frame of the game's effect sprites equals the core's replay | **652 of 652** package move rows, **76 of 76** HD battle animations; none failed, none crashed, none stuck |
| HD effects drawn (HD layers > 0) | 651 of 652 move rows (Mirror Move has no animation of its own: it plays the copied move's); 77 of 81 battle animations (4 draw nothing by design: restore background, two substitute swaps, Max weather) |
| The game's own animation for the 226 moves past the package | 226 of 226 triggered, ended, drew something into the window (`lit`) |
| Poke Ball throw, send-out and recall | the game's original animations by the owner's decision of 2026-10-13 (`bfx_game.c PokeBallAnimation`): not taken by Battle FX, no HD parity comparison |
| Effects continuing after their animation (`hdTail`, `afterEnd`) | **0** in all 737 reports of the HD runs |
| Memory over 170 animations in one process | flat: 340 MB after 5 animations, 350 MB after 138 (resident, software OpenGL; no growth trend) |
| Core cost | a frame 1–2 ms, the worst frame in a run 15 ms at the median, 366 ms once (a begin of a 267-frame plan), 1 garbage collection step in 737 runs |

"Gameplay logic": `test/battle` names 761 of the 847 moves (567 of the 621 HD moves, 194 of the 226 others); that is the GBA test ROM's coverage. The last full run
of that suite (Update 25) had 5532 passed and 39 failed, the known list; Update 27 changes no game logic (the GBA ROM is byte-identical, see below).

### Inspected by eye

Contact sheets of the middle capture of every move (30 to a sheet) were made; **sheets 4, 5, 6, 9, 14 and 22 (180 moves, after the fix) and sheets 1-3 (90 moves, before it) were looked at, and about thirty of the animations that had shown the black block
below, before and after**, as were the shiny, Mega Evolution, status and double-battle captures of the fought battles. The other moves were
checked by the measurements above only (something drawn, the right parity), not by eye. No sheet that was looked at showed an effect on the wrong Pokemon, a
Pokemon hidden by a panel, an effect behind the background or an effect left on screen.

## A defect found and fixed: a black block over the player's Pokemon behind a move's background

**What:** in the 3D battle, about 36 animations that bring in a full-screen background (Aura Sphere, Armor Cannon, Magic Room, Trick Room, Sea of Fire, Hurricane,
Focus Blast, Assurance, Baddy Bad, Mighty Cleave, Blazing Torque, ... - HD and original alike) showed an **opaque black rectangle** at the bottom centre (about a
fifth of the window's height), cutting off the lower part of the player's Pokemon. Pictures: `before` below.

**Why:** a move's background (BG3) fills the part of the GBA picture the game's text box did not cover. On the GBA the picture's rows 112-160 are hidden by the
opaque text box, so a background owes them nothing: its map is empty there (black). The 3D view shows the whole picture with only the native interface's small
strip over the bottom, so those rows - and the strip's carried-out sides - were visible. (Same family of symptom as the Update 26 reports of a large opaque panel
over the Pokemon; this one is during animations, not at the end of a battle.)

**Fix** (`src/platform/gba_easy_draw.c`, 3D battle with a move's background only; Classic 2D unchanged): the picture's rows 112-160 of that background, and of the wide
picture beside it, show the rows above mirrored at row 112 - the way the wide picture already goes on past the picture's left and right edges.

**Check:** `tools/battlefx/black_rect_check.py` finds a black block with a bright background beside it down to the picture's bottom edge in a capture.
Before the fix, over the same 919 animations' captures: **36 animations flagged**; after: **2** (Bolt Strike and Nasty Plot, whose backgrounds are dark with black
gaps on purpose; looked at). `tools/battlefx/bg_check.sh` (`make -f Makefile_pc NATIVE_LINUX=1 DIORAMA=1 check-battlefx-bg`, needs the test build) replays twelve of the
affected animations and requires none flagged: passes (0 of 12).

## Native 3D versus Classic 2D

* **Classic 2D**: the game's original animations through the GBA picture, played in a wild battle with a debug field scene
  (`tools/pc_port/classic_move_check.py`): **45 of 46** sampled moves drew an effect into the picture (Flamethrower, Fire Blast, Overheat, Thunderbolt, Thunder, Volt
  Tackle, Ice Beam, Blizzard, Ice Shard, Surf, Hydro Pump, Water Pulse, Solar Beam, Hyper Beam, Dragon Pulse, Shadow Ball, Dark Pulse, Aura Sphere, Earthquake,
  Rock Slide, Stone Edge, Psychic, Psybeam, Confusion, Leaf Storm, Energy Ball, Razor Leaf, Explosion, Self-Destruct, Protect, Substitute, Swords Dance, Pound,
  Tackle, Splash, Toxic, Will-O-Wisp, Thunder Wave, Sleep Powder, Stealth Rock, Spikes, Rain Dance, Sunny Day, Sandstorm, Hail). The 46th, **Recover**, played no
  animation: the move fails at full HP, which is the game's rule, not a missing effect. Several moves needed a second try because a miss or an immunity plays no
  animation (Thunder missed; Shadow Ball is no use on a Normal type). Moves past the package were not sampled in Classic 2D: their script and sprites are the ones the 3D view draws.
* **Native 3D**: HD effects for the 621 moves, the game's own for the other 226; the GBA backgrounds (psychic, fire, aura, dark, rooms) fill the window.
  Differences a player sees: HD particles and lights against GBA sprites; the wide background filling the window's sides; HD effects are placed for the animated
  battle sprites when the sprite pack is in (not in these runs: no pack in the cloud, the GBA pictures were the battlers).

## Special effects (fought battles, 3D)

`tools/battlefx/realsuite.sh`-style fought battles with the autopilot (the debug field scene's party: one Level 100 Pokemon): a shiny wild Pokemon, a trainer's
Mega Evolution (Manectric), a gym double battle, a wild double battle. Every animation the battles played: **50 of 50 exact** against the core's replay. Looked at:
shiny entrance sparkles (stars as the Pokemon appears), Mega Evolution (the ring and light), Intimidate's pop-up, stat arrows, burn flames, Calm Mind's ring on the
right Pokemon, Flamethrower from the player's Pokemon to the foe in singles and doubles. The gym double battle was lost (one Pokemon against two): its 37
animations, including the status ones, played and were exact.

Not exercised in this simulation: critical-hit and effectiveness feedback (the game shows these as text, not as animations; nothing to render), the
player's own Mega Evolution through the menu, a voluntary switch's animation in a fought battle (the recall and send-out are the original Poke Ball
animations), weather animations in a fought battle (the HD weather-continues animations played in the gallery), hazards in a fought battle (Stealth Rock and
Spikes are moves: played in the gallery), Z-Moves and Dynamax.

## Layering with the battle interface

Update 26's end-of-battle fix (the native battle screen stays up through the fade) is checked by `tools/pc_port/battle_end_check.py`. In this audit the whole
entrance of a wild and a trainer battle, the return from the party menu inside a battle and the battle's end were captured with the native interface in front; no
original GBA panel appeared. The one opaque thing that did cut off the player's Pokemon was the black block above. Two stretches of a battle (the set-up callback
before the main callback, and the return from the party or bag) have no native screen in front; only black or fading frames were captured there.

## Multiplayer battles

* Doubles (wild and gym): effects from the right Pokemon to the right target, parity exact (above).
* **Four-player free-for-all** (`PKMN_DEBUG_SCENE=ffa`, real battle code, four battlers): the Battle FX core takes each animation (`MOVE_GROWL (battler 2 -> 0)`,
  `B_ANIM_STATS_CHANGE (battler 3 -> 3)`) and the game's effects drew on the right battlers, but this debug scene has no map, so the battle is drawn in its 2D
  fallback and the **HD layer is not drawn there**. An FFA battle in the overworld (3D) was **not** exercised: it needs a real multiplayer session.
* Battle FX only draws; it never writes game memory or decides damage, accuracy, turn order or results (`src/diorama/battlefx/README.md`). Neither does this
  update: its changes are in the picture's rows and the test tools.

## Things found that are not defects

* Last Resort, Luster Purge, Dragon Ascent and a few others show a full white or one-colour frame at the moment captured: the game's own flash.
* Moves whose user is a dark silhouette (Calm Mind, Chloroblast, Curse) dim the stage by design.
* Some effects are on a part of the move not in the captured frame (three captures per animation); the per-animation `lit` check takes the best of the three.

## Limitations (remaining)

* **No real GPU run.** Shader compile differences, driver bugs, frame pacing, the auto quality tiers (`quality=auto`) on a real card, all unverified. The
  Windows CI job ran only the launcher and a 3D start check on a runner with no GPU (3D reported unsupported, as designed).
* The 226 moves past the package have the game's original effects (they are not HD): some are plain by the GBA's standards (many reuse another move's animation).
  Making HD versions needs the Battle FX package's data for Generations 7-9, which this repository does not have.
* The effects are placed for the GBA battler pictures here; with the animated sprite pack, the placing follows the shown body (Battle FX report section 1) - not run in the cloud (no pack).
* The animations that wait for a Safari Zone battle were exercised in one.
* Left as it was: the Poke Ball throw, send-out and recall are the game's originals (owner's decision); contests are not drawn by Battle FX; a second HD animation does not play while one runs (a double battle's opening send-outs play as GBA).
* A thin black strip can remain at a background's very bottom edge in animations that use a window mask (not seen in the last run's captures; the checks above would flag a block, not a hairline).

## Tools added (engine)

`make -f Makefile_pc NATIVE_LINUX=1 DIORAMA=1 BFX_TEST=1` (the Battle FX test build, `pokeemerald-mp-diorama-bfxtest`), `tools/battlefx/gallery.sh OUT - BATTLE MOVES` (a gallery without a save,
from the debug field scene), `PKMN_BFX_TEST_MOVE_NUMS` (moves past the package), `audit_matrix.py` (the matrix and the contact sheets), `black_rect_check.py`, `bg_check.sh`,
`tools/pc_port/classic_move_check.py`, `move_3d_check.py`; debug scene: `PKMN_DEBUG_MOVES`, `PKMN_DEBUG_ANIMSHOTS`, `PKMN_DEBUG_GLANIM`, `PKMN_DEBUG_HIDEBG`.

## Still to check on a real Windows PC with a GPU

See the list in the Update 27 report: Flamethrower, Thunderbolt, Surf and Earthquake in 3D; one background move (Aura Sphere, Trick Room, Hurricane) - no black block;
a shiny entrance; a Mega Evolution; Stealth Rock and weather; a double battle; the quality tiers; then the same moves in Classic 2D.
