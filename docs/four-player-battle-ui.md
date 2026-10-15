# Four-player battle screen (Update 21)

**Status: built and looked at in a headless simulation only (software display, scripted keys, computer-controlled opponents).
Not seen on a real monitor, not played over a real network.** Engine branch `claude/dev-update21-25-engine`.

## What the screen shows now
| Need | Classic 2D | 3D (native interface) |
|---|---|---|
| All four Pokémon distinct, no overlap | yes: you (back sprite), the first and third foe on the right/left top, the second player's Pokémon drawn *facing you* in the lower middle | same sprites over the 3D stage; the third foe also counts as a foe for the 3D effects' "front" direction |
| Whose is whose | the healthbox shows the trainer's name where the level is ("BOB"); your own box keeps the level | a name tag on every box in the trainer's colour (you blue, others red / green / gold): `ALICE (YOU)`, `BOB`, `CY`, `DI` |
| HP / status / level | the normal healthbox of each Pokémon | name, level, HP bar, status badge on each; HP numbers and EXP only on your own box |
| Battle text | "BOB's Gardevoir used Swift!", "DI's Rayquaza's Attack fell!" (your own Pokémon unprefixed; "The opposing …" is not used) | same text in the message plate |
| Choosing a target | the engine's flashing sprite (unchanged) | a plate for every Pokémon: nickname, trainer, **FOE** (nobody is anybody's ally), the cursor plate framed and the sprite blinking; yourself greyed out as **YOU** |
| Eliminated trainer | the healthbox leaves, the message "BOB's Gardevoir fainted!" | the box is replaced by a grey `BOB - OUT` tag in its place for the rest of the battle |
| Switching / animations / effects | unchanged (the engine's own); the intro balls, send-out, moves, status and faint animations all ran in the preview | unchanged |

What changed in the engine (all behind the free-for-all flag, the GBA release ROM is byte-identical; see `DEVELOPMENT_LEDGER.md`):
the third foe's sprite faces you and its animations use the foe tables; the foe animation offsets; the owner-name text;
the native interface's boxes/tags/target plates; PC-only debug scene for the preview.

## How it was checked (this is simulation)
`PKMN_DEBUG_SCENE=ffa` starts a four-trainer battle on one screen with three computer trainers (the real battle engine, the
free-for-all controller layout). With `PKMN_DEBUG_KEYS` it plays the intro, the action menu, the move menu, target selection,
a turn with every trainer's move and faints, and with `PKMN_DEBUG_SHOTS` (GBA frames) or `PKMN_DEBUG_GLSHOTS` (the window)
writes PNGs. `PKMN_DEBUG_FFA_WEAK=1` makes the other trainers' Pokémon level 3 to see the elimination display;
`PKMN_DEBUG_FFA_AS_2V2=1` shows the same four Pokémon as a normal 2v2 for a layout comparison. Debug-scene Pokémon are
marked so the computer trainers do not Dynamax or Terastallize (a scene artefact found on the way, not a game bug).

**Visual regression check:** `tools/pc_port/ffa_visual_check.py` (engine repo) runs the 2D preview and compares two
screenshots (send-out finished, action menu) with 24×16 colour signatures stored in `tests/visual/ffa_signatures.json`
(numbers only, no game art in Git). It is deterministic (difference 0.00 on repeat runs). `--update` regenerates it after a
deliberate change. It checks that the approved layout did not move; it cannot say the layout looks good.

## Regression comparison with other layouts
1v1 and 2v2/co-op code paths are unchanged by construction (every new branch tests the free-for-all flag; the GBA hash and the
GBA test ROM cover the rules). The 2v2 preview (`PKMN_DEBUG_FFA_AS_2V2`) was screenshotted in 2D and 3D after the change: normal
partner layout, no name tags, back sprites for you and the partner.

## Needs a real monitor / real session
* How the name tags read at 1080p/4K and at the window sizes players use; colour-blind legibility of the four trainer colours.
* A real 4-player battle: the link controllers (not the preview's computer controllers) drive the same boxes; the owner names
  come from the link players' names; a late disconnect mid-battle.
* Classic 2D target selection still has no names while choosing (only the blinking sprite; the healthboxes carry the owner
  names). The native (3D) screen has the full plates.
* Move animations in 3D were seen as the 2D sprite effects over the stage (the 3D move effects are not specific to four players).
