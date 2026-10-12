# Native PC UI

The approved Gen 4/5-style interface (the UI art direction's 31 designed screens) drawn
natively by the 3D game at the window's resolution, in place of the GBA menus' 240×160
picture. It is a **presentation layer**: every replaced screen's engine code still runs
underneath (its state machine, cursor, what each button does, saving, multiplayer); the
UI reads that state once a frame, draws the design, hides the GBA picture of the screen,
and turns mouse clicks into the engine's own button presses. It never decides anything
the engine decides.

Engine code: `src/native_ui/` and `include/native_ui/` (README there), built only with
`Makefile_pc DIORAMA=1` (`ENABLE_NATIVE_UI`). The GBA ROM and the classic 2D native build
compile none of it; the ROM stays byte-identical (`f214735b…3387`).

## Branches and checkpoints

| What | Where |
| --- | --- |
| Engine branch | `claude/native-ui`, from `d799c4a8a` (`graphics-wip-20261010-8`) |
| App branch (these docs) | `claude/native-ui`, from `4f1115e` (`claude/native-pc`) |
| Trial with the 3D battles | `claude/native-ui-3dbattle-trial` = `claude/native-ui` + `claude/native-graphics-3d-battles-4` (`e747ce106`), test only, not for merging as is |
| Checkpoints | `claude-checkpoints\ui-native-wip-<date>-<n>` (bundles, a Windows test build, `COORDINATION.txt`) |

Nothing is merged into `claude/native-graphics`, `claude/native-pc` or any other session's
branch; that waits for validation on the owner's PC and the owner's approval. The 3D
battle merge goes first; the UI branch then merges that tip (the trial shows it merges
with one conflict, in `gl_compositor.c`, both sides kept).

## Screens

Status of the 31 designed screens. **Integrated**: drawn natively from the game's real
state in every state the engine has, keyboard, mouse and controller. **Partial**: what is
listed is native, the rest keeps the game's picture. **Game picture**: not replaced yet
(the game's own screen shows, unchanged). **Unavailable**: the game has no such screen or
data; nothing is drawn (host or launcher features, see below).

| # | Screen | Status | Notes |
| --- | --- | --- | --- |
| 1 | Party | Integrated | every mode of the single and double layouts (field, items, TMs, giving, battle, challenge choice); SELECT moves; multi-battle layouts keep the game's picture |
| 2 | Bag | Integrated | every place it opens (field, battle, giving, selling, PC deposit, berries); the item menu, quantities, YES/NO, moving (SELECT), the game's sort (START); FIND marked PLANNED; favourites left out (not in the game) |
| 3 | Battle HUD | Integrated | singles and doubles, wild and trainer: databoxes (HP as the bar moves, level, status, caught ball), the foe trainer's party pips, messages, commands, moves (type, PP, description, effectiveness mark), the Mega toggle, targets, YES/NO, the last used Ball (R). Kept as the game's picture: the Safari Zone, the catching tutorial, the Battle Arena, ability pop-ups, the level-up stat box. Link (PvP) battles not yet run with two games in the cloud |
| 4 | Pause menu | Integrated | the engine's entries; Events marked PLANNED |
| 5 | Summary | Integrated | the game's four pages (CONTEST MOVES takes the RIBBONS tab's place, marked PLANNED) |
| 6 | Pokédex | Partial | lists, search results, entry pane, START menu native; the entry's AREA, CRY and SIZE pages and the search form keep the game's picture; FIND PLANNED; forms catalogue pending |
| 7 | Trainer card | Game picture | phase 7 (own card exists in the engine) |
| 8 | Trade | Game picture | phase 6 (the host's text menu) |
| 9 | Customization | Game picture | phase 5 (the STYLE colour editor) |
| 10 | Save | Integrated | "saved" only after the engine reports success and the file write finished |
| 11 | Options | Integrated | the six GBA options; the second tab opens F10 (Display & Graphics) |
| 12 | Players | Game picture | phase 6 (the host's six-row menu) |
| 13 | Teams | Unavailable in game | host-side only |
| 14 | PC storage | Partial | the boxes in every mode (withdraw, deposit, move Pokémon, move items), menus, JUMP list, wallpapers, marks, item info native; the PC's first menus and moving several Pokémon at once keep the game's picture |
| 15 | Shop | Game picture | phase 7 |
| 16 | Item details | Integrated | the UI's own view over the bag (Tab, pad Y, Details prompt): prices, description, uses from the item's data, holders, TM compatibility, Mega forms |
| 17 | Events | Unavailable | no engine screen (PLANNED in the pause menu) |
| 18 | Championship | Unavailable in game | host-side only |
| 19 | Invites | Unavailable in game | host-side (the ROM shows a battle-admission row only) |
| 20 | Lobby | Unavailable in game | the launcher |
| 21 | Title and main menu | Integrated | the Emerald title remaster; CONTINUE with the save's summary; QUIT GAME; Host / Join stay launcher actions |
| 22 | Game Corner | Game picture | phase 7 (script menus) |
| 23 | Friendship | Unavailable in game | host-side (the ROM has only the Lucky mark) |
| 24 | Mega | Partial | the battle toggle (screen 3) and the stones' Mega forms (screen 16); no engine screen of its own |
| 25 | Evolution | Game picture | phase 7 |
| 26 | Battle results | Game picture | phase 7 (the battle's end messages show in the battle HUD's message plate) |
| 27 | Connection | Game picture | phase 6 (notices in the game's own windows) |
| 28 | Starters | Game picture | phase 7 |
| 29 | Naming | Game picture | phase 7 |
| 30 | Soft reset | Partial | the in-battle prompt shows in the battle HUD (message and YES/NO); hunt records host-side |
| 31 | Records | Unavailable in game | host-side |

## Input

* Keyboard: the game's keys (Z = A, X = B, Enter = START, `\` = SELECT, A = L, S = R,
  arrows); **Tab** opens a screen's details view (the bag's item details).
* Mouse: click a row, button, tab or prompt; right click is the screen's "back" (B); the
  wheel scrolls lists and browses. A click moves the engine's own cursor with the engine's
  own presses (one edge a frame) and then presses A, so every rule stays the engine's.
* Controller (XInput on Windows): the game's mapping (A = A, X = B, Back = SELECT, LB / RB
  = L / R, START); **Y** opens the details view (the game does not use Y).
* Prompts show the keys of the device used last (keyboard caps or pad buttons).

## Scaling

The 640×360 logical canvas at the largest whole-number scale: ×2 at 720p, ×3 at 1080p,
×4 at 1440p, ×6 at 4K (UI size Small: one step lower, never below ×2), growing on the long
axis for other window shapes; nearest sampling, every quad on the logical grid. The GBA
picture is never stretched.

## Rollback

* `PKMN_NATIVE_UI=0` (environment): the GBA presentation everywhere, as before this work.
* `PKMN_NATIVE_UI_SCREENS=title,pause,...`: only the listed screens replaced
  (`title, main_menu, pause, options, party, summary, bag, pokedex, storage, battle`).
* The checkpoint's `test-run\run-classic-ui.bat` starts the same build with the old
  presentation. Development switches only: not in the launcher or `pokeemerald.cfg`.
* Engine rollback points: `graphics-wip-20261010-8` (no native UI) and each
  `ui-native-wip-*` checkpoint.

## Testing and regression results

Cloud computer (Linux, software OpenGL, a virtual display; the Windows build under Wine):

| Check | Result |
| --- | --- |
| GBA ROM identity at every commit (`2622871e`, `5f71c090`, `58f0194d`, `1364a05f`, `92bee637`, `ee3e1bc9`, `a794a52d`) and the trial merges | byte-identical, `f214735b…3387` |
| Linux and Windows (mingw) builds of `claude/native-ui` and of the trial | pass, no new warnings in the files touched |
| Title, main menu, CONTINUE, field, pause, bag (Windows exe under Wine) | pass |
| Bag: all five pockets with a filled test bag (items, Balls, TMs and an HM, Berries, Key Items), item details on 14 items incl. two Mega Stones, browsing by keys, arrows, wheel and the strip, back on the bag at the item shown | pass |
| Pokédex and PC storage (earlier phase runs: every mode, menus, slide, jump list, wallpapers, marks, release, summary round trip, mouse goals) | pass |
| Battles, singles: wild (Petalburg Woods) and trainer (a Bug Catcher), messages, commands on the design's grid, moves, L description, Mega toggle offered, Hypnosis (SLP badge after its animation), poison (PSN, HP drain), the last used Ball thrown with R, bag and party from the battle and back, mouse on commands and moves | pass |
| Battles, doubles (a test build with every wild battle double, not shipped): four databoxes, one-target selection following the engine's cursor, a spread move's targets, faint and removal | pass |
| 3D battles trial: the HUD over the 3D world, the GBA healthboxes and message box gone | pass |
| `PKMN_NATIVE_UI=0`: the old presentation (benchmark run through field, pause, bag, party) | pass |
| Benchmark visit (title, main menu, field, pause, bag, party), UI on and off, Linux at 1280×720 Low and at 1920×1080 High (about 12 fps in the field: the game itself slows down), and the checkpoint's `ui-benchmark.bat` with the Windows exe under Wine | every phase reached, the expected screen up 100 % of each phase |

Not run yet: link battles with two games (PvP 1v1 / 2v2), the multiplayer 2v2 owner tags.

## Performance

The UI pass is one buffer and a few draw calls a frame (a few hundred to a few thousand
quads), shapes rasterised once into an atlas; the title screen and the main menu add the
title remaster's animated background, one shader pass at the canvas size. Measured in the
cloud with **software OpenGL** (llvmpipe: the "GPU" is the CPU), 1280×720, Quality Low,
`PKMN_NATIVE_UI_BENCH` (these are not graphics-card numbers):

| Phase | UI on: mean frame | UI off: mean frame | UI pass CPU | UI pass "GPU" |
| --- | --- | --- | --- | --- |
| Title screen | 13.7 ms | 3.0 ms | 9.1 ms | 11.1 ms |
| Main menu | 22.8 ms | 2.9 ms | 11.4 ms | 18.8 ms |
| Field (no menu) | 48.4 ms | 54.6 ms | - | - |
| Pause menu over the 3D field | 54.6 ms | 50.2 ms | 1.7 ms | 0.05 ms |
| Bag (full screen) | 31.1 ms | 2.9 ms | 3.1 ms | 0.11 ms |
| Party (full screen) | 27.8 ms | 3.0 ms | 1.9 ms | 0.09 ms |

On software OpenGL the 3D field dominates (on and off differ by noise), and the native
full screens and the title's shader cost their rasterisation (the old screens are one
240×160 texture). The real cost on a graphics card, and frame rates, come only from the
owner's PC: the checkpoint's `test-run\ui-benchmark.bat` (about six minutes, no keys)
runs the visit four times - UI on and off, in a 1920×1080 window and borderless with the
3D view at 3840×2160 (Quality High, VSync off) - and writes one CSV per run to
`test-run\results\ui-run-N\` (per phase: frame-time mean, median, 99th percentile,
1 % low, the UI pass's CPU time and GPU time from GL timer queries, and how much of the
phase the expected screen was up). The script presses the game's own buttons one at a
time and waits for each screen and its fade, counting game frames, so a slow PC or a
hitch cannot put it out of step. No frame-rate figure is claimed before those results.

## Known issues

| # | Issue |
| --- | --- |
| U1 | Screens 7, 8, 9, 12, 15, 22, 25-29 still show the game's picture (phases 5-7). |
| U2 | Pokédex: AREA, CRY, SIZE and the search form keep the game's picture. |
| U3 | PC: the PC's first menus and moving several Pokémon at once keep the game's picture. |
| U4 | Battle: Safari Zone, catching tutorial and Battle Arena keep the game's picture; ability pop-ups and the level-up stat box are the game's art. |
| U5 | With the current 2D battles (no 3D battle merge yet) the strip under the old message box shows the backdrop; with the 3D battles the world shows there. |
| U6 | Link (PvP) battles not yet run with two games; in a link battle the fourth command reads GIVE UP (running loses a link battle). |
| U7 | Frame times only from software OpenGL so far (see Performance). |
| U8 | Opening and leaving the PC boxes crashed natively before this work (also with the UI off): this branch carries the fix commits of `claude/native-pc` (`99a4f186`, `bfa4303e`, cherry-picked unchanged). |
| U9 | Not the UI's: a battle against two trainers at once aborts natively (KNOWN_ISSUES N37). |

## Shared files touched (for merging)

All under `ENABLE_NATIVE_UI` unless said; engine-side accessors are read-only and sit at
the end of their files; hooks in the middle of a file keep the GBA line numbers with
`#line`:

* `Makefile_pc` (sources), `src/platform/sdl2.c` (frame-boundary capture, events, key
  filter, overlay chain, XInput Y), `src/platform/gba_easy_draw.c` (`gPlatformPictureHideBgMask`,
  `gPlatformPictureHideObj`: background layers and OAM entries left out of the picture;
  not Diorama-only, zero outside the UI), `src/diorama/gl/gl_compositor.c` (picture policy).
* Accessors: `title_screen.c`, `main_menu.c`, `start_menu.c`, `field_screen_effect.c`,
  `option_menu.c`, `party_menu.c`, `pokemon_summary_screen.c`, `item_menu.c`, `pokedex.c`,
  `pokemon_storage_system.c`, `menu_helpers.c`, `text.c`, `window.c`, `pokemon_icon.c`,
  `multiplayer.c`, `sprite.c`, `battle_controller_player.c`, `battle_interface.c` (three
  one-line hooks noting what a healthbox shows).
