# Animated battle sprites (the sprite library in the native 3D battles)

Recorded 2026-10-12. Owner directives: "FINAL SPRITE LIBRARY APPROVAL — BEGIN GAME INTEGRATION"
(the approved animated Gen 1–6 sprites into the native 3D battle renderer, on an isolated branch,
GBA sprites kept for restricted or unavailable art, no uncleared community art in runtime builds,
nothing merged before validation) and the follow-ups: find the newest graphics, battle-environment
and performance sources, use the existing pack and loader, test Singles, Doubles, shiny, gender,
Megas, Primal Reversion, timing, positioning and performance, and report which Pokémon are
animated and which keep their GBA sprite.

## Where it is

| Repo | Branch | Base | What |
| --- | --- | --- | --- |
| engine | `claude/sprite-integration` | `9c1c6aef8` (`claude/battle-environments-graphics8`: the 3D battles with their environments, on the overworld's `graphics-wip-20261010-8`) | The integration. Nothing merged anywhere. |
| app | `claude/sprite-integration` | `d778ca3` (the battle-environments docs) | This document, the ledger entry, the known issues S1–S7. |

Sources looked for (2026-10-12): the battle line's newest is `claude/battle-environments-graphics8`
`9c1c6aef8` (checkpoint `battle3d-env-wip-20261011-1`), newer than the merge candidate
`e747ce106`. The performance work's `00fd30ca7` (the `perf-benchmark-20261011` test exe) had no
source in any checkpoint until `native-wip-20261012-1` (engine `claude/graphics-overhaul`
`c51769606`, tag `graphics-wip-20261012-1`), which contains it. The UI line is `claude/native-ui`
`a794a52d3`. Trial merges (in memory and a scratch build, below) show how this branch meets them.

The sprite pack is the sprite library's permission-gated runtime export (library checkpoint
`cp-0056`, `battle-sprites.ebsp`, 12,372,036 bytes; byte-for-byte the same sprites as the
`cp-0054` export the first tests used). It is private official art: it is not in Git; builds find
it beside the program.

## How it works

The battle engine, its controllers, sprites, healthboxes and move animations are unchanged and
draw the same GBA picture as ever. The swap happens where that picture is drawn:

1. **What a battler shows** (game thread, hooks under `ENABLE_BATTLE_SPRITES`, GBA line numbers
   kept with `#line … // gba-line`): when the battle code loads a battler's picture
   (`BattleLoadMonSpriteGfx`: send-out, switch, Illusion; `HandleSpeciesGfxDataChange`:
   Transform, form changes, Mega Evolution, Primal Reversion) the species as drawn (Unown's
   letter resolved), personality, gender, shininess, the picture's 16 colours and its opaque box
   are recorded; also the Substitute doll (`BattleLoadSubstituteOrMonSpriteGfx`), a move's copy of
   a battler on BG1/BG2 (`MoveBattlerSpriteToBG` / `ResetBattleAnimBg`, the `monbg` commands) and
   a fainting foe's sinking line (`SpriteCB_FaintOpponentMon`). Nothing is written to game memory.
2. **Latched with OAM** (`LoadOam`, main thread, game parked): that state together with each
   battler sprite's OAM tiles, so it matches the OAM, palette and VRAM of the next picture (the
   frame is drawn before the VBlank handler runs). A battler sprite is recognised by the
   multiuse template and its own palette slot (trainers' pictures use tag palettes, slot 4 up).
3. **The picture** (`gba_easy_draw.c`): every 64×64 OAM entry on a battler's tiles - its sprite,
   or a move's copy of it (Double Team, afterimages) - is drawn from the pack instead of its tiles.
   The library frame sits in the entry's texture space: feet on the GBA picture's feet line (the
   row under the lowest opaque pixel, which is the library's own anchor) and the two opaque boxes
   sharing a horizontal centre, one library pixel to one GBA pixel. It goes through the entry's
   affine matrix (a Poké Ball's release, Minimize, Growth), flips and mosaic, and each pixel is
   written exactly as the entry's own would be: OAM priority and order, windows and the OBJ
   window, alpha blending, brightness. Its colours follow the entry's palette: a least-squares fit
   of the palette shown against the picture's own colours finds the fade or tint (screen fades,
   status flashes, a move's blend, Transform's pale tint) and applies it to the library colours;
   a palette that is not a fade (greyscale, inversion) shows the GBA sprite while it lasts. The
   copy on BG1/BG2 is replaced inside that layer the same way, so the moves that lift battlers
   onto a background - Tackle, Scratch, Pound, Psychic, Quick Attack and hundreds more - keep the
   animated sprite. A fainting foe is cut at its sinking line as the GBA erases its rows.
4. **Above and beside the picture** (`gl_battle_sprites.c`, 3D battles only): the 3D battle draws
   the picture at an integer scale on the window's bottom edge, with at least 20 GBA pixels of the
   world above it at the default scaling, and the world on both sides. A Pokémon taller than the
   room above its feet (Lugia, Rayquaza, Ho-Oh, Pidgeotto…) keeps its head there, and one wider than
   the picture (Lugia's wings) its wing tips: the frame's parts outside the picture are drawn after
   the picture as a textured quad at the picture's scale (same position, affine matrix, flips,
   fade, blend and brightness), cut to the box its battler covers at rest - above the picture, and
   beside it down to the text box's rows - so a sprite leaving the screen (a slide-in, Fly) still
   leaves it as the picture shows. Its frame is uploaded once per game picture.
5. **Timing**: the game's frame clock (59.7275 Hz), so the animation runs with the game, pauses
   with it and stays deterministic; each battler starts at its own phase (personality ^ slot)
   so two identical Pokémon do not move in lockstep.

Kept as the game's GBA sprite: a species or facing the pack does not hold (permission-gated
community art: Gen 6, every Mega and Primal, some forms; species after Gen 6), a shiny without a
library shiny (none in this pack), the Substitute doll, an empty picture, a palette that is not
a fade, and anything outside the battle screen (bag, party, summary, Pokédex: `gMain.callback2`
must be `BattleMainCB2`).

Why not a pass in the world (`battle_environment.h`'s world passes): those are drawn before the
backdrop and the GBA picture, under the stage light and fade, with the world cache off, and they
know nothing of the GBA picture's priorities, windows and blending; the healthboxes, text box, move
effects and the battlers lifted onto backgrounds would have had to be re-layered by hand. Drawn in
the picture, every layering rule of the GBA holds by construction, in 2D and 3D battles alike. The
environment interface stays free for later effects.

`PKMN_BATTLE_SPRITES=0` draws the GBA sprites (A/B comparison); `PKMN_BATTLE_SPRITES_PACK` another
pack; `PKMN_BATTLE_SPRITES_LOG=1` a line per battler look (pack facing, or why the GBA sprite) and
costs every 600 battle frames; `PKMN_BATTLE_SPRITES_TRACE` and `_DUMP*` are for the tests.
`Makefile_pc BATTLE_SPRITES=0` builds without it.

## Tests

Linux test build under Xvfb (Mesa software OpenGL) and the Windows build under Wine; not on a
graphics card. The GBA ROM built from this branch is byte-identical to the base's (SHA-256
`f214735b64e113fd10730eacca5764d757f2c93a3685230aa905af7a7cdd3387`): every hook is native-only.

* **19 real battles** (test driver `PKMN_TEST_*`): singles, a shiny female Pikachu against a male
  one and the reverse, doubles, Lugia/Ho-Oh, Rayquaza/Wailord, Gen 6 (GBA), forms (Deoxys-Speed,
  Shellos-East, Burmy-Trash), Unown, Mega Evolution (Gardevoirite and the Mega Ring), Primal
  Reversion on both sides, Tackle with the foe's faint, Substitute, Double Team, Minimize,
  Transform, a Gym and an Elite Four trainer battle, a cave. Every traced frame of a battler drawn
  from the pack showed the frame the pack's own timing gives for the game clock: 36,080 checked,
  0 wrong. 96.5 % of the library pixels drawn without a transform were found in the dumped
  pictures in the pack's colours; the rest are under the healthboxes, the text box and the
  R-button indicator, which are in front. No palette refusals. Mega Gardevoir and both Primal
  forms switch to their GBA pictures; the Substitute doll is the GBA doll; Tackle's lifted foe
  and the faint's sinking stay animated.
* **Species parades** (every species the game has a picture for, both sides, normal, shiny and
  female looks): 1,570 species; 1,461 of 3,140 looks drawn from the pack, exactly as the
  manifest says (1,894 facings compared, 0 disagreements); 192 female animations used; 0 timing
  errors in about 18,900 frames per parade; 98.7–98.9 % of the pixels found. Placement: 181 of
  730 animated fronts reach above the picture at rest (at most 45 GBA pixels), 3 fronts and 1
  back past its sides; median first-frame height 1.086 (front) and 1.068 (back) of the GBA
  picture's.
* **Costs** (software rendering, so slow overall): the sprites add about 0.2–0.3 ms to a game
  picture; the 3D pass above and beside the picture 1.1 ms a frame with its drawing at 1834x1032
  (after the buffer rings, 56f6b8b9; before, it waited about 24 ms for the world's drawing); a
  640x360 window presented 6.2 ms a frame with the sprites and 5.8 ms without.
* **Windows**: the stripped player exe starts under Wine and loads the pack from its folder; the
  test exe ran a singles battle there with both sprites animated.

## The Windows build

`Pokemon\artifacts\sprite-integration\game` on the owner's computer: the player build of this
branch (`pokeemerald-mp-diorama.exe`, engine `56f6b8b9`), `battle-sprites.ebsp` beside it and
`SDL2.dll`. The animated sprites are on by default; `PKMN_BATTLE_SPRITES=0` turns them off.
