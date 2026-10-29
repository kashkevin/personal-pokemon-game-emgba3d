# Small updates, UI overhaul and rendering fixes (2026-10-26)

The owner's request of 2026-10-26 ("Small Updates, UI Overhaul & Rendering Fixes") and its completion report. Engine
`claude/feature-update-engine` `ef762adc` to `cf23908c`, app `claude/admiring-bohr-dpxzuy`. KNOWN_ISSUES MS-87 (update) and
MS-99 to MS-109; TEST_LEDGER and FEATURE_STATUS sections of the same name.

**Where every result comes from: L only**, this Linux machine: the 3D test build under Xvfb, its 3D view and its classic 2D
view (`PKMN_DEBUG_CLASSIC=1`), drawn by Mesa's software OpenGL, not a GPU. No Windows run covers these commits: Windows
run 231 was cancelled before its Windows jobs, and no full run has been started since because a full run builds the
installer. Nothing here ran on the owner's PC or between two PCs.

**Not done, as asked:** no package, installer or release was made, and nothing was published or merged into a default
branch. Casino wager prices, payouts and the stake rule are unchanged. No save format changed and no player save was
touched; the tests used their own new saves.

## 1. Summary

| Item | Result | Engine |
| --- | --- | --- |
| Entering a roulette table showed the Buy Coins screen first (MS-99) | **Fixed**, verified in the real Game Corner (L, 3D) | `ef762adc` |
| Casino coins shown and accurate in every casino screen (MS-100, MS-101) | **Fixed**: the screens showed only the table's stake; now the whole Coin Case. Verified up to a save and CONTINUE (L) | `ef762adc` |
| Water: uneven surfaces, seams, wrong heights, water meeting land (MS-102) | **Fixed** at the cause (the map's sea edge, sea levels, water beside the sea), verified by height dumps of 33 maps and pictures (L, software GL) | `d654b78a` |
| Render distance wrong on the owner's game only (MS-87) | **Cause found and fixed**: only a zoomed-out, low camera on a wide window reached past the 3D view's cells, and the effects setting moved the haze. Verified on the owner's camera settings (L, software GL) | `b13e0f9e` |
| Full UI audit | **Done**: the whole-game walk with the audit log, a picture pass of the menus on the final build, every screen file checked against the game's screens (section 3) | `dd416dd0` (audit switch) |
| Old GBA interface replaced | **Replaced**: the location pop-up, the battle transitions and the trainer's last line, a field move's cut-in, PokeNav calls, the Fly map and the Pokemon Center wall map, Egg hatching, the wall clock. **Still GBA**: the screens listed in section 3.4 (MS-105) | `dd416dd0` `9c3e08e5` `57dbedc2` `db0e2547` `7c2e2d0f` `bfd5ff6f` |
| Found while auditing | **Fixed**: a field move's cut-in was never seen in the 3D view (MS-103); the PC renderer drew the second GBA window with the first one's rectangle (MS-104); the Frontier squares transition brought the trainer's box back (found in testing the same day) | `9c3e08e5` `f36530ee` `d08d4573` |
| The GBA ROM | **Unchanged** after every commit: sha256 `f214735b64e113fd10730eacca5764d757f2c93a3685230aa905af7a7cdd3387` on `cf23908c`; `check_gba_lines.py` over the 14 GBA files changed: 0 moved lines | - |

## 2. Issues fixed

### 2.1 Entering the roulette showed the Buy Coins screen (MS-99)

**Reproduced** (L, the 3D game, the real Mauville Game Corner): a roulette table's "The minimum wager at this table is 25. Do
you want to play?" (the table's script, `PlayRoulette`) shows the game's coin box. The Game Corner's counter screen
(`ui_game_corner.c`) took every coin box on that map for a clerk's: over the table's question it put up the PRIZE CORNER with
an empty board and no YES / NO, and after coins had been bought from the clerk, the COIN COUNTER. **Cause**: the screen took
the clerk from the last person talked to, which a table (a sign) does not change.

**Fix**: the counter screen is up only while a clerk's own script runs (`script.c` remembers the script the field started
last, `ScriptContext_NativeUiStartedScript`). The table's question is the field's own message, drawn by the field's message
screen with the design's money and coin windows and the shared YES / NO; every vending machine, fee and Game Corner prompt
with a money or coin box now draws the same way, and the money box's label sprite goes with it.

**Verified** (L): a table pressed with 500 coins: its question in the new message box with COINS and YES / NO, then the
roulette (before: the PRIZE CORNER); after buying 50 coins from the clerk (the COIN COUNTER, correct there): the table's
question, then the roulette (before: the COIN COUNTER); too few coins; leaving and entering again.

### 2.2 Casino currency (MS-100, MS-101)

**Found** checking "the coin balance shown and accurate in every casino screen": a table plays a stake of at most 5,000 coins
from a Coin Case of 9,999 or more and keeps the rest in reserve until you leave (`coin_wallet.c`), and the roulette and slot
screens showed only the stake as CREDIT: 30,000 coins read as 5,000.

**Fix**: both screens show COINS, the stake and the reserve together (what the Coin Case holds when you leave), counting with
every bet and payout. The roulette's "Keep playing?" and the slots' "Quit the game?" YES / NO now sit in the panel beside the
message instead of over the coins and the machine number. The slots' help said A bets three with no coins in bets; the
machine does that on R (`SlotTask_HandleBetInput`), so the line and the prompts now say R. Bets, payouts and the stake rule
are unchanged.

**Verified** (L, the real Game Corner): 30,000 coins shown as 30,000 at the table and in both games, 29,975 / 29,985 at the
bet, 30,060 after a slots win, the same in the Coin Case on leaving; saved with the game's own Save menu, loaded through the
title screen and CONTINUE: 29,975 after the load, at the table and in the roulette. `--selftest-coins` (53 checks), the
start-menu, rewards and update32 self-tests: 0 failed.

Already in place from earlier the same day (engine `cc43a414`; MS-85, MS-86): no 9,999 cap at the tables (wins past it go to
the Coin Case) and A skips a payout's count.

### 2.3 Water (MS-102)

The owner: uneven water surfaces, seams, wrong heights, water meeting land wrongly. **Causes** (the 3D view's terrain rules;
grid height dumps of 33 outdoor maps' middles):

1. Past a map's edge with no neighbour that way, the cells took the underground cliff rock's record, so the open sea ended in
   a wall of land along Routes 105, 108, 109, 122, 125 and 130-132.
2. The terrace solver laid some seas deeper than the rest (Mossdeep's east sea under its cliffs at -3, Ever Grande's below the
   waterfall at -2); they met the border's and the next map's sea as walls of water.
3. Water the map's elevations part from the sea it touches (Route 132's line of deep water by Pacifidlog) stood a step over
   it.
4. The distant scenery's sea blocks stood a step over the near sea.

**Fix** (PC 3D only): outdoors the border block's sea takes the sea's own record (`rules.c` BorderRecord); the open sea
outdoors is one level (-1): a body laid deeper is raised with the rocks and models in it, and flat ground under it comes up to
it (`buildings.c` LevelWaterBodies, MoveCellTo, FillUnderSea); water within a tile of the sea lies at the sea's level
(JoinSea); the distant sea blocks lie at the near sea's level (`far_field.c`).

**Verified** (L, software GL): every open-sea cell of the 33 maps at -1; no step between neighbouring water cells on 32 of 33
maps (Pacifidlog 10 -> 0, Mossdeep 2 -> 0; the only water left above the sea is Mossdeep's tide pools, closed in by rocks);
Route 105's edge wall gone (pictures before and after); `check-diorama` passed (far field 49,810 checks, props 7,991, camera
403, rules, terrain mesh, goldens). **Left**: a pale band at the foot of the brown sea stacks (the mountain art's side
texture). Flicker was not seen in any picture; a GPU was not tried, so flicker on a real graphics card is not ruled out.

### 2.4 Render distance on the owner's game only (MS-87)

**Why one player**: the camera's zoom and tilt are kept per player (`pokeemerald.cfg`). The owner's camera, zoomed out and
tilted low on a wide window, sees about 39 tiles ahead and 43 to the sides of level ground; the default camera sees 15 ahead
and 16-21 to the sides, inside the detail at any setting. Only a camera that reaches the edge of the 3D view's cells meets
what was wrong there:

- The 81 x 81 cells stood centred on the player although the camera always looks north (it sees at most about 21 tiles
  behind); past them stood the distant scenery's flat 2x2 blocks with little haze, and the effects setting turned that
  scenery off and moved the haze, so two players saw to different distances (Low and Medium 39 tiles, High and Ultra 54).
- The cells held only the map and its direct neighbours; past those, the map's border block (trees, rock). From Littleroot a
  zoomed-out camera saw a wall of trees where Oldale is, and walking from Oldale into Route 101 turned Route 103's lake into
  trees.

**Fix** (PC 3D only): the cells stand 12 rows ahead of the player (28 behind, 52 ahead) and the haze ends with them at every
quality setting; the distant scenery is off unless `PKMN_DIORAMA_FAR=1`; cells of the next map but one come from its own
layout; the terrain's rebuild order measures from the player. Safeguards: `runtime.log` says what each player's camera sees
whenever the camera, the window or the place changes ("Diorama: view: ..."), so a difference between two players' games
shows there; `test_camera.c` checks every Adventure and Diorama zoom and tilt on 16:9 to 4:3 windows stays inside the cells
(12,062 checks).

**Verified** (L, software GL): the owner's camera on a 21:9 window at Littleroot (Oldale's Pokemon Center at the top, not
trees), Mauville (full detail to the top), Lilycove, Mossdeep, Ever Grande, Routes 111 and 119; the Diorama camera zoomed
out on 16:9 and 21:9; the default camera on 16:9 and 21:9; a walk from Oldale into Route 101 and back (the lake stays); a
save at Littleroot loaded again (the view complete on the first frame); 118 zoomed-out pictures of 51 towns and routes, none
with missing ground. Cost walking Mauville (software GL, 4 shared cores): the owner's camera 113.6 -> 117.4 ms CPU a frame,
the default camera 85.6 -> 86.1. **Left**: photo mode panned far south looking straight down shows the haze at the bottom;
on a 21:9 or wider window a zoomed-out camera sees the haze in its far top corners. **Not verified on the owner's PC.**

### 2.5 Found while auditing

- **A field move's cut-in** (Cut, Strength, Surf, Fly: the Pokemon on a banner) was never seen in the 3D view (MS-103). Now
  the design's band in the Pokemon's type colours with its picture, indoors and out, in both views (`9c3e08e5`).
- **The PC renderer's second window** (MS-104): `gba_easy_draw.c` read WIN0's rectangle for WIN1, so the PokeNav's condition
  graph (and the Pokeblock feeding screen's) drew only its right half. Fixed (`f36530ee`); screens with one window unchanged.
- **The trainer's box over the Frontier squares**: the transition screen took any tile in the box's corner for the box, and
  the Frontier squares fill that layer with their own tiles; the box came back over the squares and on the black screen
  after. A box now counts as on screen only while its own first tile, in its own palette, is there (`d08d4573`).
- Test switches: `PKMN_DEBUG_HATCH` took no species (fixed, `c7d69f43`; the earlier commit message's Mudkip check had
  hatched a Torchic and was re-done).

## 3. The UI audit

### 3.1 How

1. **The audit log** (`PKMN_NATIVE_UI_AUDIT=1`, engine `dd416dd0`): every frame in which the game's own interface (a window,
   a battle transition, a screen of its own) shows with no current-UI screen over it is logged with the screen and the script.
   Run through the whole-game walk (`tools/qa/gameplay_check.py`, 2 shards, 2 h 13 min, 3,598 targets, of which 1,012
   people, 505 signs, 149 items, 106 hidden items, 1,023 warps, 237 triggers and 497 trainers passed) and game launches.
2. **The screens one at a time**, opened with test switches and pictured in the 3D view and the classic 2D view: each new
   screen of this update in its states (section 3.3), and on the final build a picture pass of the menus (3.2).
3. **The game's screens against the UI's screen files**: every `CB2_`/task screen the audit or the game's code names, checked
   for a current-UI screen (`src/native_ui/README.md` lists them).

### 3.2 Screens reviewed

"Current UI" means the design's own screen at the window's resolution, the game's rules underneath. "This update": pictured
on the final build (engine code of `cf23908c`) unless it says otherwise.

| Category | Screens and states looked at | Result |
| --- | --- | --- |
| Pause menu | the menu with its rows and hints; the save card | Current UI (this update) |
| Pokedex | the list, an entry (caught and unseen), the entry's actions, the AREA page | Current UI (this update) |
| Party | the list; a Pokemon's submenu (SUMMARY, MOVES, SWITCH, ITEM, CANCEL) | Current UI (this update) |
| Summary and stats | INFO, SKILLS (stats, EXP, ability), MOVES, CONTEST | Current UI (this update) |
| Bag | the Items and Poke Balls pockets | Current UI (this update) |
| Trainer Card | START > PLAYER (Trainer Card, Players, Style), the card's front | Current UI (this update) |
| Options | the six options and their descriptions | Current UI (this update) |
| Save | the save card, "Would you like to save the game?" with YES / NO | Current UI (this update) |
| Poke Mart | the clerk's welcome, BUY / SELL / QUIT, the stock, the quantity | Current UI (this update) |
| Pokemon Center | the nurse's lines and YES / NO; the PC: its boot line, which PC, the storage system's menu | Current UI (this update); the storage box screen itself not pictured in this pass (earlier update) |
| Game Corner | the coin counter with its clerk; a table's question; the roulette and the slots, bets and payouts with 30,000 coins | Current UI (MS-99 to MS-101) |
| NPC dialogue, signs, YES / NO | the walk's 1,012 people and 505 signs: every game window the log found without a current-UI screen over it is one of the screens replaced in 3.3 or listed in 3.4 | Current UI |
| Entering battles | every battle transition (ids 0-41) with a trainer's line (3D view); a wild battle's transition and a wild and a trainer battle's opening (3D, final build) | Current UI for the transitions and the line (this update); see MS-106 to MS-109 |
| Battle menus, moves, messages | "Go!", the move page with a move's details, the battle's messages | Current UI (this update) |
| Battle results | a won trainer battle's rewards ledger with the party's EXP | Current UI (this update) |
| Location pop-up | the wooden sign sliding in and out (3D) | Current UI (new) |
| Field move cut-in | Cut / Strength / Surf style banner, indoors and out, both views | Current UI (new) |
| PokeNav calls | a call over the field, ringing, the caller, hanging up | Current UI (new) |
| Fly map, wall map | moving the cursor (keys and clicks), flying, the trainers' markers (SELECT), closing | Current UI (new) |
| Egg hatching | shake, cracks, shards, flash, the Pokemon, the message, nickname YES / NO, the naming screen after YES | Current UI (new) |
| Wall clock | setting it (held direction, YES / NO), looking at it (boy's and girl's) | Current UI (new) |
| Naming screen | after an Egg's YES | Current UI (earlier update) |
| Title, main menu, starters, evolution, move switching, storage box, Players menu and trades, Style, Battle Tower | not re-pictured in this pass | Current UI from earlier updates (`src/native_ui/README.md`) |

### 3.3 Replaced in this update

| GBA interface | Now | Engine |
| --- | --- | --- |
| The map's name pop-up | the pause menu's wooden location sign, sliding with the game's pop-up (only over the field, only when no other game window is on that layer) | `dd416dd0` |
| Battle transitions: the big Poke Ball closing, the rolling Poke Balls, Team Aqua's / Magma's / the Regis' circles, the clockwise and angled wipes, the black holes | the design's shapes at the window's resolution over the GBA picture, the game's steps and timing | `9c3e08e5` |
| The trainer's last line still up as a battle begins | the design's message box, flashing and fading with the game's palette | `9c3e08e5`, `d08d4573` |
| A field move's cut-in (not seen at all in 3D before) | the design's band in the Pokemon's type colours | `9c3e08e5` |
| A PokeNav call's box over the field | the design's message box with a PokeNav tab | `57dbedc2` |
| The Fly map and a Pokemon Center's wall map | the region's map at twice the game's size, fly spots as pins, the cursor's place lit, a side card, the other trainers | `db0e2547` |
| Egg hatching | a nursery version of the evolution stage | `7c2e2d0f` |
| The wall clock | a round clock in the design's pieces | `bfd5ff6f` |
| A table's question, vending machines, fees and every prompt with a money or coin box | the field's message box with the design's money and coin windows and YES / NO | `ef762adc` |

The game keeps every rule, step and timing of each: the screens only read its state and turn clicks into its own button
presses (`src/native_ui/README.md`). The classic 2D game (the separate 2D build) keeps the GBA look by design.

### 3.4 Still the GBA's (MS-105)

Found by the audit log or the game's screen list, not replaced in this update (each is a screen of its own):

- PokeNav: its menus, zoomable region map, condition (and its search), match call list, ribbons. (Replaced on
  2026-10-29, step 13: `docs/pokenav-revamp-20261029.md`.)
- Easy Chat (the Lilycove fan club interviewer, Gabby and Ty, the Berry Master's wife, the trendy phrase).
- The Hall of Fame and the credits.
- Contests: the contest, its results, the painting.
- Berry Blender, Dodrio Berry Picking, Berry Crush, the Pokeblock case and feeding.
- Battle Frontier: the Frontier Pass and its map, the Dome's tourney tree, the Factory's rental and swap, the Pyramid's bag,
  the Pike and Arena screens, the Ranking Hall's records, the Exchange Service Corner's lists, the Battle Tower lobby's
  YES / NO.
- Trainer Hill records; mail; decorations (secret base and room); the trade animation of an in-game trade; a script's picture
  box and its YES / NO (the starter in Birch's lab); the start menu a script draws for the PokeNav tutorial in Rustboro
  (replaced on 2026-10-29, step 13); the
  Lilycove department store elevator's floors; the cable car.
- In battle: the Battle Arena's judgment and the ability pop-ups.

Art, not interface (MS-108): the transitions' own pictures (the Frontier logo and circles, trainer mugshots, the legendary
patterns) are the GBA's art under the design's shapes. The boot screens (copyright, the expansion's splash, the Game Freak
intro) are the original art and were kept.

## 4. Tests and results

All **L**. "Passed" means the scenario was run; pictures were looked at.

| Test | Build | Result |
| --- | --- | --- |
| Roulette entry and coins in the real Game Corner (500 coins; after buying 50; 30,000 coins: bets and payouts in both games; too few coins; leave and enter; save, title, CONTINUE) | `ef762adc` | **Passed** (2.1, 2.2) |
| `--selftest-coins` (53), start-menu, rewards, update32 self-tests | `ef762adc` | 0 failed |
| Water: grid heights of 33 outdoor maps before and after, pictures, `check-diorama` | `d654b78a` | **Passed** what could be checked (2.3) |
| Render distance: the owner's camera at 7 places on 21:9, Diorama and default cameras on 16:9 and 21:9, Oldale to Route 101 and back, save and load, 118 zoomed-out pictures of 51 maps, `test_camera.c` (12,062), `check-diorama`, frame cost | `b13e0f9e` | **Passed** what could be checked (2.4) |
| UI audit walk (`PKMN_NATIVE_UI_AUDIT=1`, the whole-game walk, 2 shards) | `dd416dd0` audit build | Log read; every state it found is replaced (3.3) or listed (3.4). The walk itself: 3,529 of 3,598 targets passed (631 more left out: the save's story state hides them); 69 did not: 50 not reached, 2 where the game stopped mid-target (a Lavaridge Gym B1F trainer, the door of Wally's house), 17 gameplay targets (items not reaching the bag in the Trick House puzzles, the Safari Zone and on Routes 124, 126 and 127; three hidden items; Mossdeep Gym's trainer 9 started no battle). The walk ran for its interface log; these gameplay results were not investigated in this update |
| Location sign pictures (3D) | `dd416dd0` | **Passed** |
| Every battle transition (ids 0-41) with a trainer's line, 3D view; the field move cut-in indoors and out, both views | `9c3e08e5` | **Passed**, with MS-106 to MS-108 left |
| The PokeNav condition page before and after (classic view, raw GBA frames) | `f36530ee` | **Passed** (both halves) |
| A PokeNav call, 3D and classic views | `57dbedc2` | **Passed** |
| Frontier squares without the box; the big Poke Ball keeps the line until the ball covers it | `d08d4573` | **Passed** |
| Fly map: a click moved the cursor to Oldale, a second click flew (the cut-in, then Oldale in 3D); SELECT to the test trainers; the wall map in 3D and classic, B back; the Pokedex AREA page still draws | `db0e2547` | **Passed**. The `regionmap` debug scene crashes on flying with or without the new screen (it opens the map with no field loaded): a test-scene limit; the field-based switch flies correctly |
| Egg hatching: Torchic in 3D and classic (NO back to the field), Mudkip YES to the naming screen | `7c2e2d0f`, `c7d69f43` | **Passed** |
| Wall clock: set from 10:00 AM to 10:28 AM with RIGHT held, A asks, NO back to setting; the girl's clock at 7:00 PM, B back | `bfd5ff6f` | **Passed** |
| Menu picture pass (3.2) on the final build | engine code of `cf23908c` | **Passed**: all current UI; MS-109 seen |
| The 3D map sweep's last 264 pictures looked at (the MP+3D sweep, `docs/mp-3d-update-20261026.md` section 4) | `5ec3d26f` | Nothing new beyond the water seams fixed in 2.3 |
| GBA ROM and GBA lines | `cf23908c` | **Unchanged**: sha256 `f214735b...3387`; 14 files, 0 moved lines |
| Windows | - | **Not run** (run 231 cancelled; no full run since: it builds the installer) |
| The owner's PC, a GPU, two PCs | - | **Not run** |

## 5. Remaining issues and limitations

- **Still GBA**: the screens in 3.4 (MS-105).
- **3D battle transitions**: the Frontier's squares, spiral and scroll transitions show a black frame or black stripes where
  the field is carried out (MS-106); one frame at the peak of the opening flash shows the 3D field flat grey (MS-107); the
  transitions' own pictures are GBA art (MS-108).
- **The 3D battle's opening camera** passes close to scenery beside the player: for about half a second tall grass, a roof or
  a wall nearby fills part of the picture (MS-109; seen on Route 104 and in Oldale; older than this update).
- **Water**: the pale band at the foot of the sea stacks; flicker on a GPU not ruled out (MS-102).
- **Render distance**: photo mode looking straight down far south, and 21:9 or wider zoomed out at the far top corners, show
  the haze (MS-87).
- **Not verified on Windows, on a GPU or on the owner's PC**: all of this update. The render-distance fix in particular should
  be checked on the owner's PC with the owner's camera settings; `runtime.log`'s "Diorama: view:" line shows what the camera
  sees.
- **Windows run 230's Tower climb** (the MP+3D update, MS-93): the fresh Continue failed with "checkpoint transaction failed";
  not investigated.
