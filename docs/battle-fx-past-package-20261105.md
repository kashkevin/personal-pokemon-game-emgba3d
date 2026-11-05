# Battle FX past the package, and the transitions' own art (VR-5, MS-108) — 2026-11-05

Engine branch `claude/battlefx-more` (worktree of `b270e14a`), app branch `claude/battlefx-more-app` (this file and the
audit matrix). Owner directives of 2026-11-05: VR-5 "Upgrade the remaining 226 GBA battle animations to polished
HD/3D-compatible animations"; MS-108 "Upgrade outdated GBA transition artwork while preserving the game's visual
identity".

**Where results come from.** **L**: this Linux machine, the 3D test build (`pokeemerald-mp-diorama-bfxtest` of
`b270e14a`, not rebuilt), Mesa's software OpenGL (llvmpipe) on a virtual screen, scripted input; **N**: the Battle FX
core run under Node. Nothing here ran on a real graphics card or on Windows. "Parity" is the test build's own
comparison: every frame, the game's effect sprites (graphics tag and position) against the core's replay.

## Summary

| | |
|---|---|
| Moves past the package (622-847) | 226 |
| ... a player can meet in this game (Phase 1) | **16** (14 by an egg move a hatched Pokemon switches in, 2 by level-up of an evolution; 2 of them also used by the Battle Tower Legends' trainers) |
| ... the rest | 210: learnt only by species this game does not give (Gen 7-9 families, regional forms) or by nothing at all here |
| Why none had an HD version | the package's data stops at 621; its converter (`battlefx_kit`) is not in the repository. Its tables already hold every sprite template and graphics tag of the newer moves and its kits draw almost all of their tags |
| Converted now (a converter of the repository's own, `tools/battlefx/convert_more.py`) | 222 of 226 (Dragon Darts, Tera Blast, Ivy Cudgel, Tera Starstorm need two script commands it does not convert) |
| ... needing nothing more (every callback and task already in the core) | 169, 15 of the 16 reachable |
| **HD now (engine `claude/battlefx-more`)** | **the 16 reachable moves**: data, one callback ported (Stone Axe's), an HD presentation each; 17 animation rows (Psychic Fangs has two), **every compared frame equal**, none failed, stuck or left over; also as the foe's and in a double battle. **184 of the 226 in all** with the row below |
| **HD too: moves no player can meet here** | **168**: the 154 needing only data and 14 whose callbacks and tasks were ported here, each played with every compared frame equal ("The other 154" below) |
| Still GBA after this | 42: 38 needing 30 more callbacks and 16 tasks ported, the 4 unconverted; all unreachable in this game |
| MS-108 | inventory and an approach with an offline prototype (pictures below); not built into the engine: it needs a 3D build (C in the native UI and the transitions' PC hooks), which this machine had neither the disk (1.2-2.4 GB free) nor the processors (load 20-44 on 4 cores, other builds running) for today; the offline step is done (`tools/native_ui/transition_art_hd.py`) |

## Phase 1 (a): which of the 226 can a player meet?

`tools/battlefx/moves_past_package.py` (engine) reads the game's own data. What it found, against the premise of the
task:

* **The level-up learnsets are Gen 6, not Gen 9.** `include/config/general.h` sets `GEN_LATEST GEN_6`, and
  `P_LVL_UP_LEARNSETS` is `GEN_LATEST`, so `src/pokemon.c` includes `level_up_learnsets/gen_6.h` (ORAS). That file
  holds every species' list (a later species' first one), but the Gen 1-6 species' lists have no move past 621.
* **The species a player can own are Gen 1-6.** The wild pool (`src/data/mp_wild_pool.h`, all 312 Gen 1-6 families,
  every map and method), the random Legendary / Mythical roll (54 species, Gen 1-6), the scripts, trades and starters;
  no Gen 7-9 family and no regional form. Two later species come from evolving: **Kleavor** (Scyther with the Black
  Augurite, sold at RARE GOODS) and **Kingambit** (Bisharp after the Leader's Crest battles). Regional evolutions
  need their region (`IF_REGION`, the game is in Hoenn); the evolution items of the others are given by nothing
  (the item audit of 2026-10-27).
* **Egg moves are the main way in.** The PC game's move switching (`src/move_relearner.c`, as Legends Z-A) lets a
  Pokemon hatched from an Egg switch in any egg move of its line, without a parent that knows it, and the egg move
  lists (`egg_moves.h`) are the expansion's latest: 14 moves past 621 are egg moves of Gen 1-6 lines.
* TMs (Gen 1-6 rule, `tm_learnsets_pc.h`) and tutors (`teachable_learnsets_pc.h`, Emerald's tutors) teach none.
  Metronome calls moves 1-621 only (`B_METRONOME_MOVES` is Gen 6); Sleep Talk, Assist, Copycat, Mirror Move, Sketch
  and Mimic only call or copy moves already in use. The debug menus are off; Z-Moves and Max Moves are off and are not
  among the 226. Trainers: `trainers.party` has none; `tower_legends.party` (the Battle Tower Legends) has High
  Horsepower (6 sets) and Throat Chop (4).

| Number | Move | Egg move of (a hatched Pokemon of the line switches it in) | Level-up of | Opponents |
|---|---|---|---|---|
| 623 | First Impression | Farfetch'd | - | - |
| 630 | High Horsepower | Phanpy, Ponyta | - | Battle Tower Legends |
| 631 | Strength Sap | Bellsprout, Hoppip, Oddish | - | - |
| 634 | Spotlight | Spinda | - | - |
| 638 | Throat Chop | Sneasel | - | Battle Tower Legends |
| 641 | Psychic Terrain | Abra, Drowzee, Fennekin, Girafarig | - | - |
| 642 | Lunge | Joltik, Spinarak, Surskit, Volbeat | - | - |
| 644 | Power Trip | Mankey, Pancham, Piplup, Sandile | - | - |
| 645 | Burn Up | Growlithe, Tepig | - | - |
| 646 | Speed Swap | Emolga | - | - |
| 655 | Dragon Hammer | Tropius | - | - |
| 660 | Psychic Fangs | Carvanha, Girafarig, Lillipup | - | - |
| 664 | Liquidation | Corsola, Tirtouga | - | - |
| 669 | Tearful Look | Dedenne, Minun, Patrat, Plusle | - | - |
| 758 | Stone Axe | - | Kleavor | - |
| 797 | Kowtow Cleave | - | Kingambit | - |

| Reachability of the 226 | Moves |
|---|---|
| egg move of an obtainable line (PC move switching) | 14 |
| level-up of an obtainable species (Kleavor, Kingambit) | 2 |
| also an opponent's move (Battle Tower Legends) | 2 (High Horsepower, Throat Chop; both are egg moves too) |
| TM, tutor, Metronome, a wild Pokemon's or a trainer's level-up moves | 0 |
| **reachable** | **16** |
| not reachable (only Gen 7-9 species or regional forms learn them, or nothing here) | 210 |

Would change this: making Gen 7-9 species or regional forms obtainable, Gen 7+ learnsets, Z-Moves or Dynamax, or
`B_METRONOME_MOVES` past Gen 6. The tool reruns in a minute after any of those.

## Phase 1 (a): why no HD version, and what each needs

The package (Battle FX v3.3) converted moves 1-621; its own converter
(`battlefx_kit/prototype/build_preview_data.py`) is not in the repository (`tools/battlefx/convert_data.py` only wraps
it). Its data already has all 1146 sprite templates and 473 graphics tags of the game, the newer moves' included, and
its HD kits draw 124 of the 149 graphics tags those moves use (the other 25 draw as the GBA picture with a glow). So what a move past the
package needs is, in order:

1. **Its animation data** (all 226): the script converted into the package's rows. Done here for 222 by
   `tools/battlefx/convert_more.py`, checked against the package: converting the package's own 621 moves gives its rows
   exactly for 601; the other 20 differ only where the package's conversion is not the game's (README, "Moves past the
   package": default branches, the contest jump, Surf's palette argument; four old multi-valued branches it does not
   enumerate).
2. **The core's re-implementation of each callback and task the script uses** (the replay must equal the game frame
   for frame); a missing one plays an approximation and fails parity.
3. **Two script commands** the converter does not convert: `createdragondartsprite`, `jumpifmovetypeequal`.
4. **Presentation**: the package's moves each have a config of their own (`HD.moves`); the generic kits draw the
   others, so a polished version adds one.

Ranked by the reachable moves each unlocks (`moves_past_package.py --md`):

| Need | What | Moves | Reachable |
|---|---|---|---|
| data | the 226 scripts converted | 226 | 16 |
| callback | `SpriteCB_HorizontalSlice` | 1 | 1 (Stone Axe) |
| script command | `jumpifmovetypeequal` | 3 | 0 (Tera Blast, Ivy Cudgel, Tera Starstorm) |
| script command | `createdragondartsprite` | 1 | 0 (Dragon Darts) |
| callback | 34 others (`AnimEllipticalGustCentered` 4 moves, `SpriteCB_FallingObject` 3, `SpriteCB_SpriteOnMonUntilAffineAnimEnds` 3, `SpriteCB_AcidDripSingleTarget` / `AcidLaunchSingleTarget` / `PhotonGeyserBeam` / `SunsteelStrikeRings` 2 each, 27 with 1) | 36 | 0 |
| task | 19 (`AnimTask_AllBattlersVisible` 4 moves, `AllBattlersInvisible` 2, `AllBattlersInvisibleExceptAttackerAndTarget` 2, 16 with 1) | 19 | 0 |
| template not in the package's table | `gSnipeShotBallTemplate` (converted from C), `gGrowingSuperpowerTemplate` | 3 | 0 |
| HD kit for the tag (presentation, not parity) | 25 tags (`ANIM_TAG_SMALL_ROCK` 4 moves, `EXPLOSION_2` 3, `PURPLE_CHAIN`, `SPIRIT_ARROW`, `STRAIGHT_BEAM`, `APPLE` 2 each, 19 with 1) | 27 | 0 |

So 169 moves (15 reachable) needed only their data; 53 needed callbacks or tasks ported (35 callbacks, 19 tasks), Stone
Axe (one callback) the only reachable one among them; 4 need the two script commands. After this work: 38 moves need 30
callbacks and 16 tasks, all unreachable.

## Phase 2: what was upgraded

Engine branch `claude/battlefx-more`, on `b270e14a`: `3f075284` (the converter), `fd0f1615` (the 16 reachable moves'
HD), `60e82325` (callbacks and tasks ported, converter fixes), `64dd947d` (MS-108's offline step; the converter's turn
fix), `63e14383` (the 168 others), `fa649556` (MS-108 previews' palette). Files:

| File | |
|---|---|
| `tools/battlefx/convert_more.py` | the converter (`--check` against the package) |
| `tools/battlefx/extend_folder.py` | the `battlefx/` folder: the package's data with the listed moves added, `bfx_core.js` with `core_more.js` after it, `MANIFEST.txt` hashes |
| `tools/battlefx/core_more.js` | Stone Axe's callback (`SpriteCB_HorizontalSlice`, from `battle_anim_new.c`), four more callbacks and three tasks for 14 unreachable moves (below), Psychic Terrain's field of motes, and an HD presentation for each of the 16 (the package's own effects keyed to each script's sprites and tasks: e.g. High Horsepower takes Mega Kick's strike with a horseshoe and a ground thud, Spotlight Encore's stage light - its GBA spotlight is an OBJ-window mask the HD layer does not draw - Liquidation Waterfall's cloak and cascade, Burn Up a red-hot user and the flames engulfing the target) |
| `tools/battlefx/moves_past_package.py` | the Phase 1 tables |
| `tools/native_ui/transition_art_hd.py` | MS-108's offline step (below) |
| `tools/battlefx/moves_more.txt` | the moves the folder adds |
| `battlefx/bfx_moves.json`, `bfx_core.js`, `MANIFEST.txt` | the folder the game reads (the package's 621 moves, general animations and tables unchanged; the package's bundle unchanged, `core_more.js` after it) |
| `src/diorama/battlefx/README.md` | "Moves past the package" |

No C file, no GBA source changed; the GBA ROM is not rebuilt (`f214735b...` as before). The game picks the new moves
up from `battlefx/` (`PKMN_BATTLEFX_DIR` for a copy): no engine rebuild.

### Evidence (L, N)

Gallery runs of the test build (`tools/battlefx/gallery.sh`, a wild battle from the debug field scene), the HD data
folder against the original one:

| Move | Game frames (GBA = HD) | Parity: frames equal / compared | Effect sprites | Failed / stuck / left over / HD tail |
|---|---|---|---|---|
| First Impression | 137 | 136 / 136 | 39 | no / no / 0 / 0 |
| High Horsepower | 149 | 149 / 149 | 73 | no / no / 0 / 0 |
| Strength Sap | 191 | 190 / 190 | 175 | no / no / 0 / 0 |
| Spotlight | 171 | 171 / 171 | 126 | no / no / 0 / 0 |
| Throat Chop | 77 | 76 / 76 | 56 | no / no / 0 / 0 |
| Psychic Terrain | 200 | 200 / 200 | 76 | no / no / 0 / 0 |
| Lunge | 313 | 312 / 312 | 270 | no / no / 0 / 0 |
| Power Trip | 161 | 160 / 160 | 140 | no / no / 0 / 0 |
| Burn Up | 308 | 307 / 307 | 89 | no / no / 0 / 0 |
| Speed Swap | 120 | 119 / 119 | 73 | no / no / 0 / 0 |
| Dragon Hammer | 186 | 186 / 186 | 54 | no / no / 0 / 0 |
| Psychic Fangs (turn 0) | 133 | 133 / 133 | 44 | no / no / 0 / 0 |
| Psychic Fangs (turn 1, a screen broken) | 163 | 163 / 163 | 82 | no / no / 0 / 0 |
| Liquidation | 85 | 84 / 84 | 62 | no / no / 0 / 0 |
| Tearful Look | 136 | 135 / 135 | 107 | no / no / 0 / 0 |
| Stone Axe | 61 | 60 / 60 | 32 | no / no / 0 / 0 |
| Kowtow Cleave | 225 | 225 / 225 | 59 | no / no / 0 / 0 |

* Two HD runs of the 16 (before and after their HD presentation was added): the same parity, every frame; the HD
  layers drawn per animation rose (High Horsepower 78 to 173, Burn Up 152 to 206; Spotlight none to 130: its GBA
  spotlight is a window mask the HD layer leaves to the game, its stage light is now drawn).
* The game's own animation is the same length with the HD data as without it (the GBA run of the same 16, by number:
  the same frame counts): the battle's timing does not change. Where the core ends one frame before the game, that
  frame shows no effect sprite (the reports' `tail`: 0 with sprites).
* As the foe's (attacker 1 against the player's battler, the HD layer not drawn): the 16 again, 17 rows, every compared
  frame equal (High Horsepower's other background branch, `IsTargetPlayerSide = TRUE`, included; High Horsepower and
  Throat Chop are the Battle Tower Legends' moves).
* The second HD run ended with a segmentation fault after its last result was written ("done, 17 animations, 0
  failed, 0 with parity differences", then the crash): the test driver's exit on the game's thread while the main
  thread draws, which the Battle FX README already lists (seen once before); the runner then replayed the last move
  (the same parity). Not in a battle.
* N: every configured HD effect of the 16 triggers (`fx` keyed to sprites and tasks); 309 converted moves (the 222 of
  the 226 and the 87 Z / Max Moves) played through the core with frames drawn: no exception; one task failure in the
  core (Teatime's `AnimTask_RockMonBackAndForth` with an absent battler in Node's setup; in the game its parity is
  exact), 87 moves played with stand-ins for callbacks or tasks the core lacked (the 53 above and 34 Z / Max Moves).
* N: the package's moves are untouched: 63 of them (two samples across the list) give byte-identical frame packets,
  every frame, with the package's core and data and with the extended ones.
* Pictures (scratchpad, not packaged): GBA before / HD after side by side, the contact sheets of the HD captures;
  listed in the report.

### The other 154, and 14 more with callbacks ported

The 154 unreachable moves that need nothing but their data, played by the same gallery with the HD layer not drawn
(that leaves the replay and its parity as they are; it was the only way to fit them in this machine's time):
153 of the 154 moves every frame equal (161 animation rows); Dual Wingbeat failed (its turn-0 variant was missing - the converter fixed, then both its turns every frame equal).
Then 14 moves whose missing callbacks or tasks were ported to `core_more.js` from `battle_anim_new.c` /
`battle_anim_flying.c`: the four storms of the Forces of Nature (`AnimEllipticalGustCentered`), Chloroblast, Lunar
Blessing, Revival Blessing (`AnimTask_AllBattlersInvisible` / `Visible` / `InvisibleExceptAttackerAndTarget`),
Prismatic Laser, Grav Apple, Take Heart (`SpriteCB_FallingObject`), Photon Geyser, Baddy Bad
(`SpriteCB_PhotonGeyserBeam`), Buzzy Buzz, Spirit Break (`SpriteCB_SpriteOnMonUntilAffineAnimEnds`): all 14 every frame equal (14 rows).

Only moves whose every frame was equal are in `battlefx/` (`tools/battlefx/moves_more.txt`: 184 moves past the
package in all). Their HD drawing was exercised under Node (frames drawn for every one, no exception) and, for a sample
of 8 (Spirit Shackle, Sparkling Aria, Solar Blade's two turns, Shadow Bone, Nature's Madness, Clangorous Soul,
Springtide Storm, Photon Geyser), in the game with the HD layer drawn: 9 rows, 1997 of 1997 frames equal, 47 to 209 HD layers drawn per animation
(pictures in the report). They draw with the package's kits for
their sprites and no config of their own. None of them can be met in this game.

| Run (L, a wild battle, the debug field scene's Mudkip against Zigzagoon) | Animations | Every compared frame equal |
|---|---|---|
| the 16 reachable, HD drawn (twice: before and after their HD presentation) | 17 each | 17 / 17 each |
| the 16 reachable as the foe's (attacker 1), HD not drawn | 17 | 17 / 17 |
| the 16 reachable in a wild double battle, two Pokemon a side (`PKMN_DEBUG_PARTY=2`), HD not drawn | 17 | 17 / 17 (2806 frames) |
| the 16 reachable in a wild double battle with the player's lone Mudkip (one side single) | 17 | 10 / 17: see "Found on the way" (the package's moves fail there the same way) |
| the 154 data-only unreachable moves, HD not drawn | 161 (+ 2: Dual Wingbeat again after the converter's fix) | 153 of 154 moves, then Dual Wingbeat's two turns: 154 of 154 |
| the 14 newly ported, HD not drawn | 14 | 14 / 14 |

## Found on the way

* **The task's premise "the learnsets are Gen 9" does not hold here**: `GEN_LATEST` is `GEN_6`, so
  `P_LVL_UP_LEARNSETS` selects ORAS (`gen_6.h`); see Phase 1.
* **A double battle where one side has a single Pokemon** (the debug field scene's lone Mudkip against two wild
  Pokemon): the game draws that side's battler at the singles position (`GetBattlerCoordsIndex`,
  `battle_interface.c`: `gPartiesCount == 1`), the core at the doubles one, 40 pixels apart, so every effect placed
  from that battler is off by 40 pixels and parity fails from that frame: 7 of the 16 there, and the package's own moves
  the same way (Ember, Focus Energy, Giga Drain, Calm Mind, Swords Dance: 5 of 6 sampled; Night Slash, placed from the
  target, exact). The core has no such rule; the
  fix is the game's request telling the core each battler's coordinate set (a `bfx_game.c` change plus a small core
  helper), not data. In a double battle with two Pokemon a side the 16 are exact (table above).
* The package's own conversion differs from the game's script in 20 of its 621 moves (default branches, the
  `AnimTask_IsContest` jump, Surf's palette argument, four multi-valued branches): engine README, "Moves past the
  package". The game plays the package's data for those; changing them would need their own gallery runs.
* Kowtow Cleave's dark background (`BG_DARK`) shows magenta in the 3D test build in the GBA run as in the HD one (not
  Battle FX); worth a look against Classic 2D.

## MS-108: the transitions' own art

### Inventory

| Art (`graphics/battle_transitions/`) | Transitions (`include/battle_transition.h`) | Code | How the 3D view draws it now |
|---|---|---|---|
| `frontier_logo.png` + `.bin` (BG0) | `B_TRANSITION_FRONTIER_LOGO_WIGGLE`, `_LOGO_WAVE` | `battle_transition.c` (`FrontierLogoWiggle_*`, `FrontierLogoWave_*`) | the GBA picture's BG0, scaled, over the 3D field (`gl_compositor.c`) |
| `frontier_logo_center.png` + `.bin` (BG0), `frontier_logo_circles.png` (64 x 64 sprites, 3 frames) | `B_TRANSITION_FRONTIER_CIRCLES_MEET`, `_CROSS`, `_ASYMMETRIC_SPIRAL`, `_SYMMETRIC_SPIRAL` and the four `_IN_SEQ` | `battle_transition_frontier.c` (no PC hook yet) | the GBA picture (BG0 + OBJ) |
| `frontier_square_*.4bpp`, `frontier_squares*.png` | `B_TRANSITION_FRONTIER_SQUARES`, `_SCROLL`, `_SPIRAL` | `battle_transition.c` | the GBA picture, the grid carried out over the window (MS-106) |
| `kyogre.png` + `.bin`, `kyogre_pt1/pt2.pal` (palette cycling) | `B_TRANSITION_KYOGRE` | `battle_transition.c` | the GBA picture |
| `groudon.png` + `.bin`, `groudon_pt1/pt2.pal` | `B_TRANSITION_GROUDON` | `battle_transition.c` | the GBA picture |
| `rayquaza.png` + `.bin`, `rayquaza.pal` | `B_TRANSITION_RAYQUAZA` | `battle_transition.c` | the GBA picture |
| `regis.png`, `regice/registeel/regirock.bin/.pal`; `team_aqua.png/.bin`, `team_magma.png/.bin`, `evil_team.pal` | `B_TRANSITION_REGICE`, `_REGISTEEL`, `_REGIROCK`, `_AQUA`, `_MAGMA` | `battle_transition.c` | the circles are the native UI's (`ui_transition.c`, NATIVE_TRANSITION_CIRCLE); the patterns under them the GBA picture |
| `elite_four_bg.png` + `elite_four_bg_map.bin`, `*_bg.pal` (5 colours, Brendan's, May's); the trainers' front pictures (`graphics/trainers/front_pics/`) | `B_TRANSITION_MUGSHOT` (Elite Four, Champion: `GetTrainerMugshotColorFromId`) | `battle_transition.c` (`Mugshot_*`) | the GBA picture |
| (already redrawn) `big_pokeball.png`, `pokeball.png`, `pokeball_trail.png`, the wipes, the black holes | `BIG_POKEBALL`, `POKEBALLS_TRAIL`, `CLOCKWISE_WIPE`, `ANGLED_WIPES`, `BLACKHOLE*` | `battle_transition.c` `BattleTransition_NativeUiState` (ENABLE_NATIVE_UI) | the native UI's shapes at the window's resolution (`src/native_ui/screens/ui_transition.c`, engine `9c3e08e5`) |

### Approach (keeps the look: the art is the game's own, drawn sharp)

* **Frontier logo, circles, the legendaries', Regis' and the teams' patterns: the GBA art redrawn as smooth shapes,
  generated from the art itself.** An offline tool turns each picture into a label map at 8x: every palette slot's
  pixels (and the empty background's) become a smooth membership field (an approximate distance field), each high
  resolution pixel takes the slot with the most, blended with the next across a one-pixel edge. The pixel stairs become
  the circles, ellipses and straight strokes the art draws, with no seam between colours; the shapes, proportions and
  colours stay the GBA's. The game keeps animating the palette: at run time each slot takes the colour the game's
  palette gives it that frame (the patterns' palette cycling, the fades), and the layer moves with BG0's scroll and per
  line offsets (the waves) as `ui_transition.c` already does for the big Poke Ball's weave.
* The Frontier logo and circles are geometric enough (three overlapping rings, an inner disc and ring, an egg-shaped
  centre) to be authored as vector pieces of the design (`UiW_*Piece`, as the Poke Ball is) instead - the prototype
  shows the generated version is already close.
* **Mugshots**: the banner (`elite_four_bg`) is flat stripes, redrawn as shapes; the trainers' and the player's pictures
  are the game's own front pictures (`ui_gfx.c` already draws trainer front pictures at whole-number scales): kept as
  pixel art at a whole-number scale (the design's rule), optionally a careful 2x-4x pixel-art upscale per picture with a
  look by eye (custom characters' pictures included).

**The offline step, done (engine `tools/native_ui/transition_art_hd.py`):** it turns all eleven pictures (the
Frontier logo, its centre and its circles' sheet, Kyogre's, Groudon's and Rayquaza's patterns, the three Regis', Team
Aqua's and Team Magma's) into label maps at any scale (`NAME.slots.png`: the winning palette slot, the runner-up and
their blend per pixel, to be coloured from the game's palette of the frame) and previews beside the GBA picture
(`NAME.preview.png`). Run at 4x here (scratchpad `ms108/hd4/`, a few in the report's pictures): the stairs of the
logo's rings, the patterns' diagonals and ellipses become smooth, the colours and shapes stay the GBA's. Not used by
the game yet. Seen at 8x: the art's own one-pixel edge colours (the logo's light-blue and grey rims) come out beaded,
since they are themselves stair-stepped; the production step folds such rims into the edge between their neighbours
(or the Frontier logo and circles are authored as vector pieces, as the Poke Ball is) - part of the estimate below.

### What implementing it takes (estimate)

| Step | Work |
|---|---|
| The offline tool (label maps of the patterns and the circles' sheet) | done (`tools/native_ui/transition_art_hd.py`); the maps at 8x into the native UI's data: 0.25 day |
| A palette-mapped HD layer in the native UI (the label map's slots coloured from `gPlttBufferFaded`, the scroll and line offsets) | 1 day |
| PC hooks in `battle_transition.c` / `battle_transition_frontier.c` (`#ifdef PORTABLE` / `ENABLE_NATIVE_UI`, `#line` markers): which pattern, its scroll, line offsets, the circles' positions and scale; the GBA BG0 / the circles' OAM hidden as for the big Poke Ball | 1 day |
| Tests: `PKMN_DEBUG_TRANSITION` 15-20 and 26-34 over a 3D field, pictured every few frames against the 2D build; `check_gba_lines.py`; the ROM unchanged | 0.5-1 day |
| Mugshots (banner shapes; picture scaling and a look by eye) | 1-2 days |
| **Total** | **about 3 days for the Frontier logo / circles and the patterns, 1-2 more for the mugshots** |

Needs a 3D build (about 1 GB of objects) on a machine with the room for it; not started today.

## What remains (estimate)

| Work | Moves | Estimate |
|---|---|---|
| Port 30 more callbacks and 16 tasks from `battle_anim_new.c` and friends (statement for statement, then a gallery run each; `moves_past_package.py` lists them) | 38 | 3-4 days (most are short; Core Enforcer, Pyro Ball, Glacial Lance, Steel Roller, Mind Blown, Wicked Blow are the long ones) |
| `createdragondartsprite`, `jumpifmovetypeequal` in the converter and the core (variants by the move's type, which the game's `BranchValue` would have to give: a `bfx_game.c` change) | 4 | 1 day |
| The core's battler coordinates in a double battle where one side has one Pokemon (all moves, the package's too: "Found on the way") | all | 0.5-1 day (`bfx_game.c` request field and `kGameHelperJs`; galleries) |
| HD kits for 25 tags (now the GBA picture with a glow) and per-move presentation for the moves no player can meet | 210 | 2-4 days by eye |
| HD drawing of the moves proven with the HD layer off, looked at in the game (a gallery with the HD view and captures) | 168 | 1-2 hours of machine time, a look by eye |
| MS-108 in the engine (above) | - | about 3 days, 1-2 more for the mugshots |

None of the 210 can appear in this game today, so they are worth less than the 16 until the game makes them
reachable.

## What the records should say (not edited here)

* **KNOWN_ISSUES.md**, VR-5: "16 of the 226 moves past the Battle FX package can be met in this game (14 egg moves a
  hatched Pokemon switches in; Stone Axe, Kleavor's; Kowtow Cleave, Kingambit's; the Battle Tower Legends use High
  Horsepower and Throat Chop). They play HD from engine `claude/battlefx-more` (data converted by
  `tools/battlefx/convert_more.py`, every frame equal to the game's, as the attacker, as the foe and in a double battle).
  The other 210 cannot be met here (the learnsets are Gen 6; no Gen 7-9 species or regional form is obtainable); 168 of
  them are HD too, 42 still play the GBA animation in 3D (38 need callbacks or tasks ported, 4 script commands the
  converter does not convert)." A new low line: "Battle FX: in a double battle where one side has a single Pokemon, the
  core places that battler at the doubles position and the game at the singles one; effects from it are 40 pixels off
  (package moves too)." MS-108: "Inventory, approach and the offline step (`tools/native_ui/transition_art_hd.py`) in
  `docs/battle-fx-past-package-20261105.md`; open until a 3D build draws it (about 3 days, 1-2 more for the mugshots)."
* **TEST_LEDGER.md** (L, software OpenGL, no GPU, no Windows): the 16 reachable, HD drawn, two runs: 17 rows each, every
  compared frame equal; as the foe's: 17 / 17; in a double battle with two Pokemon a side: 17 / 17 (2806 frames); with
  one side single: 10 / 17 (the coordinate limit above; package moves too: 1 / 6); the GBA run of the 16 by number: the
  same lengths; the 154 data-only unreachable moves (HD not drawn): 153 / 154, Dual Wingbeat 2 / 2 after the converter's
  fix; the 14 ported: 14 / 14; 8 of them with the HD layer drawn: 9 / 9 (1997 frames). N: `convert_more.py --check` 601
  of 621 identical, 20 explained; 309 converted moves through the core with frames drawn, no exception; 63 package moves
  sampled, frame packets identical with the extended core.
* **docs/outstanding-issues.md**: VR-5 "184 of 226 HD (the 16 reachable among them; engine `claude/battlefx-more`); 42
  left, none reachable (estimate in this file)"; MS-108 "approach, offline step and estimate; implementation needs a 3D
  build".
* **docs/owner-decisions.md**: nothing to record; one question for the owner: whether the 42 moves no player can meet are
  worth the porting estimate before something makes them reachable, and whether the Frontier logo should be authored as
  vector pieces or drawn from the generated maps.
