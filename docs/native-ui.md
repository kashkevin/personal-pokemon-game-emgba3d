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
compile none of it; the ROM stays byte-identical at every UI commit (`b37759ea…e79a` since
the engine fix U10, `f214735b…3387` before it).

## Branches and checkpoints

| What | Where |
| --- | --- |
| Engine branch | `claude/native-ui`, from `d799c4a8a` (`graphics-wip-20261010-8`) |
| App branch (these docs) | `claude/native-ui`, from `4f1115e` (`claude/native-pc`) |
| Trial with the 3D battles | `claude/native-ui-3dbattle-trial` = `claude/native-ui` + `claude/native-graphics-3d-battles-4` (`e747ce106`), test only, not for merging as is |
| Trial over the newest overworld | `claude/native-ui-overworld-trial` = the overworld tip `c51769606` (`graphics-wip-20261012-1`) + `claude/native-ui`, a merge check only (two conflicts, resolved as the overworld session's note says); not shipped, not for merging as is |
| Trial with the battle environments | `claude/native-ui-battleenv-trial` = `claude/battle-environments-2` (`719e16c78`, `battle3d-env-wip-20261012-1`) + `claude/native-ui`, a merge check only (two conflicts, resolved as the battle session's note says); not shipped, not for merging as is |
| Checkpoints | `claude-checkpoints\ui-native-wip-<date>-<n>` (bundles, a Windows test build, `COORDINATION.txt`) |

Nothing is merged into `claude/native-graphics`, `claude/native-pc` or any other session's
branch; that waits for validation on the owner's PC and the owner's approval. The 3D
battle merge goes first; the UI branch then merges that tip (the trial shows it merges
with one conflict, in `gl_compositor.c`, both sides kept). Over the newest overworld tip
(`c51769606`) it merges with two conflicts, both sides kept as the overworld session's
note asks: in `gl_compositor.c` the UI's `DIORAMA_PICTURE_HIDE_ALL` condition with the
overworld's lazy `EnsureFrameTexture()` inside both picture branches, and in `sdl2.c`
`NativeUi_CaptureFrame()` first, then `DioramaProfile_Begin(DIORAMA_PROF_TICK)`, then
`VDraw` (the merge check branch `claude/native-ui-overworld-trial`). With the battle
environments (`claude/battle-environments-2`) it merges with two conflicts, both sides
kept as the battle session's note asks: in `gl_compositor.c` the UI's condition on the
battles' `else if (sTwoDOpacity > 0 ...)` and on the border, after the battles'
`sDrewField3D = ...;`, and in `sdl2.c` `NativeUi_FilterKeys()` first, then the
`DIORAMA_BATTLE_ENV_TEST` key filter (the merge check branch
`claude/native-ui-battleenv-trial`).

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
| 3 | Battle HUD | Integrated | singles and doubles, wild and trainer: databoxes (HP as the bar moves, level, status, caught ball), the foe trainer's party pips, messages, commands, moves (type, PP, description, effectiveness mark), the Mega toggle, targets, YES/NO, the last used Ball (R). Kept as the game's picture: the Safari Zone, the catching tutorial, the Battle Arena, ability pop-ups. The level-up box is screen 26's. Link (PvP) battles not yet run with two games in the cloud |
| 4 | Pause menu | Integrated | the engine's entries; Events marked PLANNED |
| 5 | Summary | Integrated | the game's four pages (CONTEST MOVES takes the RIBBONS tab's place, marked PLANNED) |
| 6 | Pokédex | Integrated | the red device over the game's Pokédex: the Hoenn and National lists, search results, the entry pane, the START menu; the entry's pages in the left screen: AREA (the game's region map art; the sections where it finds the species glow red with its pulse, caves and special places blink as rings with its markers, the player's icon, the place names, AREA UNKNOWN), CRY (the game's cry, its sampled waveform and VU needle, PLAY), SIZE (the game's silhouettes at its scales, 2x); the search form over both screens (SEARCH / SHIFT / CANCEL, the game's rows, option lists, text, results); a catch's new entry page in battle (the entry, REGISTERED, the footprint); FIND PLANNED; forms catalogue pending |
| 7 | Trainer card | Integrated | the collectible card over the engine's card (START > PLAYER, and from the Frontier Pass): front with the engine's trainer picture and your walking field sprite (saved look), name, ID No., money, Pokédex caught (and seen), the save's play time with its blinking colon, the profile words, the engine's badge art in sockets and its four stars picking the card colour; back with the records the engine prints (Hall of Fame debut, link battles with a W/L bar, trades, Pokéblocks and contests with friends, Battle Points), only those it has; the design's LINK, CHAMP, TRADES and HUNTS pages are the host's (PLAYERS > Your Trainer Card) and say so, FRIENDS PLANNED; the left panes: who is in this world (bridge), the four star rules with the ones met. The engine's keys (back: A closes, B flips back); click flips, right click closes; the 9-frame flip squash. Other players' cards: the host's PLAYERS pages (screen 12) |
| 8 | Trade | Partial | the host's trade pages (choose, both offers, confirm, change, cancel, the pending trade) on the Players screen's sheet, on the kit's trade blue, with the engine's cursor; the design's two-panel trade window (portraits, details, consent lamps) needs data the host does not send yet (offers come as text rows) |
| 9 | Customization | Integrated | the dressing room over the STYLE editor (START > PLAYER > STYLE): its four colour rows (skin tone, hair, outfit, hat and bag) with the engine's names, colours and palette slots behind the BODY, HAIR, TOP and HAT tags; the mirror (the player's field sprite at 3x, recoloured live by the engine's own palette recolour; walk, run, turn), the portrait (base art), the sync tag (the look's 8 bytes, what the host has); presets, body, the styles, bottoms, shoes, bag, accessories and unlocks PLANNED (they need layered art the game does not have) |
| 10 | Save | Integrated | "saved" only after the engine reports success and the file write finished |
| 11 | Options | Integrated | the six GBA options; the second tab opens F10 (Display & Graphics) |
| 12 | Players | Integrated | the link device over the host-driven Players menu: every page the host sends (players list, a player's actions, records, teams, challenges) with title, status, rows (rows without an action as information), the engine's cursor, waiting for the host, B as Back or Close; beside it you (your field sprite with your saved look in LCD tones, name, place), the session's connected players from the bridge, your card's public facts; FRIENDS, ALL, friendship ranks and Lucky Friends PLANNED |
| 13 | Teams | Unavailable in game | host-side only |
| 14 | PC storage | Integrated | the PC's first menus over the field in the design's message and menu boxes (booting up, which PC, the PC's lines, the Pokémon Storage System's menu with its descriptions and refusals, the player's PC and ITEM STORAGE menus); the storage terminal in every mode (withdraw, deposit, move Pokémon, move items), menus, JUMP list, wallpapers, marks, item info; several Pokémon at once (the quick hand: the selection, the group carried lifted, a cell at a time and into the next box, the places in the way marked; dragged and clicked with the mouse). The player's PC's item lists, mailbox and decorations and the Hall of Fame PC keep the game's picture |
| 15 | Shop | Partial | the Poké Mart: the design's mart (awning, pegboard, counter and shelves with the stock, price tags) over the engine's: the field's BUY / SELL / QUIT with the board FOR SALE and the clerk's line, the buy screen (engine prices, the POKéNEWS sale, SOLD OUT key items, how many with its total, YES / NO, the clerk's lines and the Premier Ball bonus), money and the Bag count; SELL is the bag's selling mode (screen 2). Decoration shops keep the game's picture (their icons are the decorations' own art) |
| 16 | Item details | Integrated | the UI's own view over the bag (Tab, pad Y, Details prompt): prices, description, uses from the item's data, holders, TM compatibility, Mega forms |
| 17 | Events | Unavailable | no engine screen (PLANNED in the pause menu) |
| 18 | Championship | Unavailable in game | host-side only |
| 19 | Invites | Unavailable in game | host-side (the ROM shows a battle-admission row only) |
| 20 | Lobby | Unavailable in game | the launcher |
| 21 | Title and main menu | Integrated | the Emerald title remaster; CONTINUE with the save's summary; QUIT GAME; Host / Join stay launcher actions |
| 22 | Game Corner | Integrated | the design's prize corner over the Mauville Game Corner's four clerks (scripts): the Coin Case counter with reel digits, money, the prize board with its marquee; the clerk talked to picks the counter (TM, prize, coin); rows are the engine's multichoice rows (TMs with their moves and the party's real compatibility, the three dolls drawn from their field sprites and sent to the PC, 50 / 500 coins for money with the Coin Case's room); the Shiny Charm (the owner's guaranteed prize, 9,000 coins, OWNED once had, refused a second time) heads the prize counter and is its own clerk's; the engine's YES / NO and lines. Another clerk's rows and tabs only say so. The slot machines and roulette keep the game's picture |
| 23 | Friendship | Unavailable in game | host-side (the ROM has only the Lucky mark) |
| 24 | Mega | Partial | the battle toggle (screen 3) and the stones' Mega forms (screen 16); no engine screen of its own |
| 25 | Evolution | Integrated | the design's night stage over the engine's evolution scene: the starfield, the spotlight and stage rings turning while it evolves; the old form alternating with the new one's pale silhouette as fast as the engine alternates its sprites, the new form white in bursts of sparkles, its colours returning with the engine's flash, then the new form; B held, a click or a right click stops an evolution the engine lets stop ("Huh? ... stopped evolving!"); a new move's messages and YES / NO are the engine's (clicks, wheel), the move to forget is chosen on the summary (screen 5). Evolutions inside a trade keep the trade's own picture |
| 26 | Battle results | Partial | drawn by the battle HUD over the engine's battle end: the level-up box (gains, then totals, from the engine's stats; its own box and banner left out) and, when a trainer battle ends, the rewards ledger with the defeated trainer's plate - won (from the prize message on, after the trainer's last words): the engine's prize (Amulet Coin included), money before and after, each Pokémon's level, Exp. bar and the Exp. gained in this battle (UP, NO EXP., TRADED); lost with money paid: OUT OF POKéMON and the money paid. The engine's messages stay in the message plate. Link and multiplayer results (VS card, records, archived record number) are the host's (PLAYERS records): not drawn; co-op prizes and wagers planned |
| 27 | Connection | Partial | the game's multiplayer notice banner (host notices, wager money, hints) as the design's toast over the calm field, for as long as the game shows it; the recovery dialogs (host lost, saved here, rejoin, mismatches) are the launcher's, not the game's |
| 28 | Starters | Integrated | Birch's open bag over the engine's six-page starter choice (Hoenn, Kanto, Johto, Sinnoh, Unova, Kalos): the region tag and page dots, the tray in the region's colour, GRASS / FIRE / WATER cradles, the hand and label, the round window with the Pokémon's front animation; the research card from the engine's data (name, category, types, Pokédex entry, first ability, the role the rival follows); the engine's lines and YES / NO. The first battle, the level and the nickname stay the game's |
| 29 | Naming | Integrated | the name tag (the engine's title, slots, block cursor, count; the player's walking sprite, the Pokémon's icon and gender, the Box icon) and the three keyboard pages over the engine's naming screen (player, rival, Box, nickname, caught Pokémon, Walda's words, codes): the engine's own grid in the design's keycaps (eight keys a row, six on OTHERS, blank keys type a space) with its PAGE / BACK / OK column. Typing on the PC keyboard becomes the engine's own presses (page, cursor, A; then the cursor waits on OK: Enter finishes; Backspace deletes; Page Up / Down); clicks on keys, tabs and PAGE / BACK / OK; the wheel turns pages. Walda's dad and the code man are not drawn in the icon disc |
| 30 | Soft reset | Partial | the in-battle prompt shows in the battle HUD (message and YES/NO); hunt records host-side |
| 31 | Records | Unavailable in game | host-side |

## Input

* Keyboard: the game's keys (Z = A, X = B, Enter = START, `\` = SELECT, A = L, S = R,
  arrows); **Tab** opens a screen's details view (the bag's item details). On the naming
  screen the letter keys type (Enter = A, Backspace and Esc = B, Page Up / Down = pages).
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
  (`title, main_menu, options, pause, party, summary, bag, pokedex, storage, battle,
  customize, players, trainer_card, shop, naming, starters, evolution, game_corner,
  notice`).
* The checkpoint's `test-run\run-classic-ui.bat` starts the same build with the old
  presentation. Development switches only: not in the launcher or `pokeemerald.cfg`.
* Engine rollback points: `graphics-wip-20261010-8` (no native UI) and each
  `ui-native-wip-*` checkpoint.

## Testing and regression results

Cloud computer (Linux, software OpenGL, a virtual display; the Windows build under Wine):

| Check | Result |
| --- | --- |
| GBA ROM identity at every UI commit (`2622871e`, `5f71c090`, `58f0194d`, `1364a05f`, `92bee637`, `ee3e1bc9`, `a794a52d`, `eb4842ee`) and the trial merges | byte-identical, `f214735b…3387` |
| GBA ROM with the engine fix `a89294c5` (U10, not UI) | differs only in `start_menu.o` (.text +28 bytes; every other section the same size): `b37759ea…e79a` |
| GBA ROM at the UI commits after it (built at `16de85f4`, which carries `b6a2e945`, at `14049f27`, `5b0a37a6`, `b4828995`, `f51084fd`, `59d60a4a`, `6d734278`, `dd6269de`, `2bd61f00` and `b6f0b698`) and on the 3D battles trial `6783586a` | byte-identical, `b37759ea…e79a` |
| Linux and Windows (mingw) builds of `claude/native-ui` and of the trial | pass, no new warnings in the files touched |
| Title, main menu, CONTINUE, field, pause, bag (Windows exe under Wine) | pass |
| Bag: all five pockets with a filled test bag (items, Balls, TMs and an HM, Berries, Key Items), item details on 14 items incl. two Mega Stones, browsing by keys, arrows, wheel and the strip, back on the bag at the item shown | pass |
| Pokédex and PC storage (earlier phase runs: every mode, menus, slide, jump list, wallpapers, marks, release, summary round trip, mouse goals) | pass |
| Battles, singles: wild (Petalburg Woods) and trainer (a Bug Catcher), messages, commands on the design's grid, moves, L description, Mega toggle offered, Hypnosis (SLP badge after its animation), poison (PSN, HP drain), the last used Ball thrown with R, bag and party from the battle and back, mouse on commands and moves | pass |
| Battles, doubles (a test build with every wild battle double, not shipped): four databoxes, one-target selection following the engine's cursor, a spread move's targets, faint and removal | pass |
| 3D battles trial: the HUD over the 3D world, the GBA healthboxes and message box gone | pass |
| 3D battles trial at `6783586a` (Bug Catcher Rick, a level up in the battle): the level-up box over the 3D battle, the trainer's last words with the scene clear, then the rewards ledger and the trainer's plate with the prize message | pass |
| Overworld trial `claude/native-ui-overworld-trial` (`fd25d0d2` = the overworld tip `c51769606` + `claude/native-ui`, test only; built from scratch, no new warnings): title, main menu, CONTINUE, the pause menu over the new 3D field (Mauville City Gym), the bag and the party (the 2D picture hidden), back on the field without leftovers, a trainer battle's HUD (2D battle scene) | pass |
| Battle environments trial `claude/native-ui-battleenv-trial` (`3352ae7c` = `719e16c78` + `claude/native-ui`, test only; built, no new warnings): title, main menu, CONTINUE, the pause menu over the 3D field, the bag and the party, back on the field; Bug Catcher Rick's battle in the 3D battle environment: the HUD, the level-up box, the trainer's last words, the rewards ledger | pass |
| The checkpoint's two Windows exes (debug info split off) under Wine: title, main menu, CONTINUE, pause, bag; `TRY-NATIVE-UI.bat` under Wine's cmd (the nine-choice menu; a dragged save copied to `play\` and the game started with it) | pass |
| `PKMN_NATIVE_UI=0`: the old presentation (benchmark run through field, pause, bag, party) | pass |
| Players with a real local host (`/home/claude/ui/tools/native_ui/mp_one_client.py`: world server, companions, enrolment, the native game with `--bridge`): one client (the list, the records pages, B back and close, the STYLE hint banner as a toast) and two clients (each other in the list and the session LEDs, a trade offered by one, the pending trade chosen by the other, both offers shown, cancelled with B, aborted on both) | pass |
| Customization, Brendan and a May test save: every colour row by keys and mouse (tags, swatches, L/R, wheel), the planned tags, the mirror's poses (Tab), SAVE by START and by the button ("Is this OK?"), the saved look on the field and on reopening (its tick; "saved here" while offline), B with changes ("Discard your changes?") back to the saved look | pass |
| Trainer Card, Brendan and May test saves: front (picture, walking sprite, money, Pokédex caught and seen, time with the blinking colon, profile, 8 badges in the engine's art, stars and colour), back (no records yet: the empty note), the flip caught frame by frame (squashed front, edge-on, squashed back), the host tabs' notes, A / B and a click to flip, a right click to close (back on the pause menu); with two clients on a real local host: 2/4 in this world, the other player "here with you" | pass |
| Poké Mart (the Mauville Mart, a test save continuing at its counter): the menu with the stock and the clerk's line, buying by keys (3 Super Potions: money and the Bag updated) and by mouse (a row, the quantity arrows, OK, NO, right click back and quit), 10 Poké Balls and the Premier Ball line, SELL into the bag and back, "anything else" | pass |
| Naming: a new game's player name typed on the keyboard ("Kevin" with the automatic lower case, Backspace, "n!" across to OTHERS and back, Page Down, Enter: Birch asks "So it's Kevin!?"), by mouse (a key, the OTHERS tab, a key, BACK, OK: "So it's B?"); a Box renamed from the PC ("Hunt", shown on the Box afterwards) | pass |
| Starters (a save continuing beside Birch's bag on Route 101, the bag shown again in a copy): Hoenn, Mudkip, Kanto, Kalos, the question and NO, a click on the GRASS ball and YES: Treecko, the first battle starts | pass |
| Evolution (test saves: a Kirlia from the bag's Rare Candy, and one that knows four moves at the level where Gardevoir learns Dream Eater): the whole scene (intro, sparkles, the alternation caught frame by frame, the white flash and its colours returning, "Congratulations!"), stopped by a click and by holding B ("Huh? Kirlia stopped evolving!", still a Kirlia), the new move: its messages, YES / NO by keys, a click on NO ("did not learn"), a click on YES, the summary's move choice (Cut refused as an HM, Thunderbolt forgotten), "One... two... and... ta-da!", "learned Dream Eater!", back on the bag | pass |
| Game Corner (test saves continuing at each clerk with a Coin Case): the TM counter (TM32 for 1,500 coins: coins 5,000 to 3,500, IN BAG x1, the party ABLE), the Shiny Charm clerk (the charm selected, 9,000 coins, YES: given), the coin counter (50 coins for ¥1,000 by a click: 120 to 170 coins, ¥3,000 to ¥2,000; 500 dimmed without the money), the doll counter (a click on TREECKO DOLL: "So your choice is TREECKO DOLL?"; the charm row: "the next clerk's"); the Poké Mart after the shared helpers moved: pixel-identical but for its bobbing arrows | pass |
| Pokédex pages (a test save with more Pokémon seen): AREA for Treecko (AREA UNKNOWN), Wailord (Route 129 glowing), Zubat (five caves as blinking rings), Geodude (Routes 111 and 114 glowing, four places as rings), the place names; CRY played by A and by a click (waveform, needle to the loud side, PLAYING); SIZE for Treecko and Wailord (the trainer tiny beside it); pages by keys (LEFT / RIGHT, B) and by clicks on AREA, SIZE (two steps), CRY, CANCEL | pass |
| Pokédex search: by keys (ORDER: Smallest; "7 Pokémon found", the results smallest first) and by mouse (a click on TYPE from the top bar opens its options, the wheel scrolls to WATER, a click chooses it, a click on SEARCH: "3 Pokémon found") | pass |
| New entry after a catch (Petalburg Woods with a Master Ball from the native battle bag): Miltank's page with REGISTERED and its footprint, a click goes on to the nickname question | pass |
| The PC's first menus (a test save continuing in front of a Pokémon Center PC, BOX1 and BOX2 filled from the save's own Pokémon): booting up, which PC, "Accessed SOMEONE'S PC.", "POKéMON Storage System opened.", the storage menu with each description by keys, SEE YA! back to which PC, the player's PC ("Accessed …'s PC.", "What would you like to do?", ITEM STORAGE's menu and descriptions, WITHDRAW ITEM's list (the game's picture) and back, CANCEL, TURN OFF), LOG OFF back to the field without leftovers, no frame of the field between the steps; by mouse (the message box, a which-PC row, the MOVE POKéMON row); a one-Pokémon party: DEPOSIT refused ("There is just one POKéMON with you."), the cursor moved while refused | pass |
| Several Pokémon at once: by keys (the quick hand, A held: 2×2 selected, picked up and lifted, moved right and on into BOX2, two places in the way marked and the put-down refused, moved down, put down) and by mouse (a drag from Treecko to Wingull: 4 selected; a click on a free place: carried as near as it fits and put down; a 2-Pokémon drag, the box's right arrow: pushed into BOX2; a click: put down at the top left); the Windows exe under Wine (keys) | pass |
| Battle results (test saves facing Bug Catcher Rick on Route 102): a win (two Wurmples; the plate RICK with his tray, REWARDS: prize ¥64, ¥3,000 to ¥3,064, Gardevoir +96 Exp., Wailord +0), a level up in the battle (the level-up box: +2 +1 +1 +3 +2 +2, then 132 72 72 135 124 88; then UP on the ledger), a loss (OUT OF POKéMON: -¥3,000, ¥3,000 to ¥0, both FNT, NO EXP.) | pass |
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
| U1 | Still the game's picture: decoration shops (screen 15), evolutions inside a trade (screen 25), the Game Corner's slot machines and roulette (screen 22), link battle results (screen 26: the host's records). |
| U2 | Resolved: the Pokédex's AREA, CRY and SIZE pages, its search form and a catch's new entry page are native (`2bd61f00`). Note (not the UI's): on the PC the game's cry waveform samples the PC mixer's float buffer as bytes (`pokedex_cry_screen.c` BufferCryWaveformSegment), so the waveform and needle move with the cry but are not its true shape. |
| U3 | Resolved: the PC's first menus and moving several Pokémon at once are native (`b6f0b698`). The player's PC's item lists, mailbox and decorations and the Hall of Fame PC keep the game's picture. |
| U4 | Battle: Safari Zone, catching tutorial and Battle Arena keep the game's picture; ability pop-ups are the game's art. The rewards ledger comes with the prize message, after the defeated trainer's last words: it covers the right of the scene, where the trainer stands (flat view and 3D battles trial alike; the design draws the trainer beside it). |
| U5 | With the current 2D battles (no 3D battle merge yet) the strip under the old message box shows the backdrop; with the 3D battles the world shows there. |
| U6 | Link (PvP) battles not yet run with two games; in a link battle the fourth command reads GIVE UP (running loses a link battle). |
| U7 | Frame times only from software OpenGL so far (see Performance). |
| U8 | Opening and leaving the PC boxes crashed natively before this work (also with the UI off): this branch carries the fix commits of `claude/native-pc` (`99a4f186`, `bfa4303e`, cherry-picked unchanged). |
| U9 | Not the UI's: a battle against two trainers at once aborts natively (KNOWN_ISSUES N37). The battle session's `claude/native-pc-n37-fix` (`1a26af882`, in `battle3d-env-wip-20261012-1`) fixes it; not in this branch. |
| U10 | Not the UI's, fixed here: choosing STYLE or RIDE / GET OFF in the Player menu faded the screen to black for good (the start menu fades for every item not on its no-fade list; both stay in the field), with the old menus too, since `e726268e`. Fixed in `a89294c5` (both join the list, as PLAYERS); the same commit is on `claude/fix-player-menu-fade` (on `d799c4a8a`) for the multiplayer start menu's owners. It changes the GBA ROM (`start_menu.c` only). |
| U11 | Not the UI's (3D view): with the old menus (`PKMN_NATIVE_UI=0`) the Players menu's window never appears in the 3D build: while the menu pauses the field callbacks the view keeps showing the last field frame (the Start submenu). The new Players screen draws over it. For the overworld session. |
| U12 | Not the UI's (3D view): the field's message box leaves the 3D view as soon as its line is fully printed, UI on or off: `scene_snapshot.c` takes `IsFieldMessageBoxHidden()` for the box being gone, but the field message task sets that when its printer finishes, while the box stays on BG0 until the script closes it; a line that waits for A can only be read while it types. The PC's lines are drawn by the native PC menus. For the overworld session: keep the dialogue rect while window 0's frame is on screen (its tilemap), not only while it prints. |
| U12 | Not the UI's (seen in the cloud runs, to check on the PC): leaving a Poké Mart, the clerk's "Please come again!" closes about a second after it has printed, without a button; the same with the old mart menu (`PKMN_NATIVE_UI_SCREENS=title,main_menu`), so not the new Shop screen. |

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
  `multiplayer.c`, `multiplayer_appearance.c`, `multiplayer_menu.c`, `multiplayer_world.c`,
  `trainer_card.c`, `shop.c`, `naming_screen.c`, `starter_choose.c`, `evolution_scene.c`, `script_menu.c`,
  `coins.c`, `script.c`, `scrcmd.c`, `event_object_movement.c`, `battle_script_commands.c`, `battle_main.c`,
  `sprite.c`, `battle_controller_player.c`,
  `battle_interface.c` (three one-line hooks noting what a healthbox shows).
* Not UI: `start_menu.c` (U10's fix, two callbacks on the no-fade list).
