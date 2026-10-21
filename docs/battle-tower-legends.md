# Battle Tower: Legends (design and interfaces)

**Status: in development (2026-10-21), not merged. Nothing here is verified until TEST_LEDGER says so.** Owner request of
2026-10-21 (the main request and its "additional requirements"). PC only: the GBA ROM stays byte-identical
(`f214735b64e113fd10730eacca5764d757f2c93a3685230aa905af7a7cdd3387`); engine code is under `#ifdef PORTABLE` with
`#line N // gba-line` after each PC-only block (checked by `tools/pc_port/check_gba_lines.py`). Builds on the native co-op
battle, the co-op Battle Frontier's ladder (`docs/battle-frontier.md`), the wallet stream (`rewards.py`, `wagers.py`) and
the Players menu.

This file is the contract between the engine and the app. Section 8 lists every byte that crosses between them.

## 1. What the players get
* **START > PLAYER > TOWER** (a new entry of the PLAYER submenu, in a world only) opens the Players menu on the Battle
  Tower's home page; the same page is **PLAYERS > World and my base > Frontier and League > Battle Tower: Legends**. No map,
  no building, no warp: a Tower battle starts where the player stands (the battle uses its own indoor scene) and returns
  there. Nothing else in the world stops: other players keep exploring.
* **100 floors.** Every floor is one battle against a trainer; every opposing Pokemon is exactly the floor's level (floor
  1 = level 1, floor 100 = level 100). The player's Pokemon keep their own levels (no level sync).
* **Solo:** one player against the floor's trainer with their own party (up to six), a normal single battle run by their
  own game. **Duo:** exactly two players of the world, each controlling their own Pokemon (three each), against the floor's
  two trainers in the native co-op double battle (the co-op Gym's and the Battle Frontier's battle). Never three or more
  humans; PvP formats are unchanged.
* Progress, prizes and experience caps are each player's own (Duo too). A Tower battle never sets story flags, never gives
  badges, never whites out, costs no money and gives no trainer prize money (the host pays the Tower's prizes).
* After every Tower battle the player's party is healed and its held items are restored (the Battle Frontier's rule).

## 2. Floors, checkpoints and runs
* **Checkpoints:** floors 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90 and 100. A checkpoint is reached once that floor is
  cleared and is never lost.
* **Progress:** each player has a *progress floor* P (the next floor of their climb, 1..100; 101 when floor 100 is cleared)
  and a *highest cleared floor* H (0..100). Winning floor P: P+1, H = max(H, P). Losing (or drawing) floor P: P = C+1, where C
  is the highest checkpoint <= H (0 when none). Examples: lose on 18 -> 11, on 48 -> 41, on 73 -> 71, on 79 -> 76, on 7 -> 1.
* **Replays:** any floor <= H can be fought again ("Replay floor N"); a replay never changes P or H and pays the replay rates
  (section 4). After floor 100 (P = 101) every floor is a replay.
* **No skipping:** a player only ever fights their P or a floor <= H. The host checks it for every battle it issues.
* **One Tower battle at a time per player** (solo or Duo): while one is issued or running, every other Tower action of that
  player is refused with the reason.
* **Interrupted battles:**
  * Solo: the battle runs in the player's own game, so it needs no connection while it runs. The result is written into the
    save's Tower record the moment the battle ends and is sent to the host until the host has settled it (a reconnect or a
    restart after a save sends it again). A started solo battle whose result never reaches the host (the game closed or
    crashed before the result was saved or sent) counts as a **loss** when the player next asks for a Tower battle (Battle
    Frontier rule: quitting a challenge forfeits it); a battle that never started (the game refused the command, or closed
    before the battle began) changes nothing.
  * Duo: the existing native recovery. A battle that starts and is abandoned without a result is **void** for both (the
    co-op Battle Frontier's owner default: no progress lost or gained); a battle that never started changes nothing.
  * A result is settled once; a repeated or contradicting result changes nothing.

## 3. Experience caps (Tower battles only)
Badges 0..8 -> cap 15, 20, 25, 30, 40, 45, 50, 55, 60; Champion (FLAG_IS_CHAMPION) -> 100. Each game reads its own badge
flags when it awards experience (a Duo: each game for its own party, so a teammate's badges never raise a cap). A Pokemon at
or above its cap gains no experience from a Tower battle; one below gains normally but stops exactly at the cap's level. Levels
are never reduced, Pokemon above the cap may still battle, and nothing changes outside Tower battles (Rare Candy, wild and
trainer battles, the Day Care). Effort values are gained as in any battle.
* Solo: the in-battle award (`Cmd_getexp`) is clamped by a PC-only Tower hook. Duo: the co-op award (`MultiplayerCoop_ExpReward`)
  is clamped the same way. Both use `TowerLegends_ExpCap()`.

## 4. Prizes
All prizes go through the wallet stream (exactly once per save and adjustment; the receipt says what really moved).
* **First clear of a prize floor** (once per player, ever; the claim is recorded in the save and in the host's ledger):
  | Floor | Prize |
  | --- | --- |
  | 10 | 10 Rare Candy + $10,000 |
  | 20 | 5 Bottle Cap + $20,000 |
  | 25 | milestone Pokemon: random shiny (natural IVs; no legendary or mythical) |
  | 30 | 15 Rare Candy + $30,000 |
  | 40 | 1 Gold Bottle Cap + $40,000 |
  | 50 | milestone Pokemon: random, all IVs 31 (normal shiny odds; no legendary or mythical) + $50,000 |
  | 60 | 20 Rare Candy + $60,000 |
  | 70 | 2 Gold Bottle Cap + $70,000 |
  | 75 | milestone Pokemon: random shiny, all IVs 31 (no legendary or mythical) |
  | 80 | 1 Ability Patch + $80,000 |
  | 90 | 1 Ability Patch + 3 Gold Bottle Cap + $90,000 |
  | 100 | milestone Pokemon: shiny, all IVs 31, a legendary of the supported pool + $100,000 |
* **Every won battle** also pays Battle Points and (except on a prize floor's first clear) money:
  * first clear (the floor's first win ever): BP = (1 + floor // 10) x (3 on floors 10, 20, 30, 40, 60, 70, 80, 90; 4 on 25,
    50, 75; 5 on 100; else 1); money = floor x $100.
  * any later win (a replay, or a re-climb after a loss): BP = max(1, first-clear BP // 3) and money = floor x $30 when the
    floor is within 20 of the player's H; 1 BP and floor x $10 below that (anti-farming).
  * A loss pays nothing.
* **Milestone Pokemon** (25, 50, 75, 100): once per player permanently. The host picks the species when the floor is first
  cleared and records it before anything is sent; the game makes the Pokemon from that species and a seed of (milestone,
  species, the save's trainer ID), so a resend, a reload or a retry makes the same Pokemon (no rerolls). Level: the floor,
  at most the player's Tower experience cap at the claim, legendary at most 70; the species is legal at that level (section
  7's rules). Original trainer: the player; a Cherish Ball; met in the Battle Frontier at that level; its nature, ability
  (a regular one), gender and moves (its level-up moves at that level) from the seed. Party first, else the PC; when both are
  full nothing is made, the claim stays owed and is offered again (the Tower page says so).
* Money over $999,999, BP over 9,999 and items without room behave as everywhere in the game (the receipt records what moved);
  the claim itself is recorded as delivered only for what landed.

## 5. Items
* **Bottle Cap / Gold Bottle Cap: Hyper Training.** A Bottle Cap trains one chosen stat, a Gold Bottle Cap all six. A stat
  can be trained when its natural IV is below 31 and it is not trained yet (the engine's own rule, `canhypertrain`; no
  level requirement). The natural IV is kept (breeding and the summary's judge use it); the trained bit (PokemonSubstruct1)
  makes the stat count as 31; it travels with the Pokemon (saves, trades, battles). Use from the Bag (party menu, then the
  stat list showing each stat's natural IV and whether it is trained) and from the Tower page *Hyper Training* (the same
  screens). Refused without using the item: an Egg, nothing left to train, a Gold Bottle Cap when no stat can be trained.
* **Ability Patch:** switches a Pokemon between a regular Ability and its species' Hidden Ability (both ways), after a
  confirmation; refused without using the item when the species has no Hidden Ability distinct from its current one, or on
  an Egg. The ability slot travels with the Pokemon (saves, trades, evolution, battles).
* **Battle Points:** the save's `frontier.battlePoints` (shared with the Battle Frontier and the co-op Battle Frontier), at most
  9,999.
* **Tower Shop** (BP): debit first, like the Frontier shop: the game takes the points (its receipt says how many), then the
  item is given; refunded when the bag and the PC cannot hold it. One purchase at a time per player. Catalogue and prices:
  `tower_rewards.py` (section 11).

## 6. Mega Evolution in the Tower
The opposing trainers use the existing Mega Evolution (the AI Mega Evolves a Pokemon holding its stone; one Mega per trainer
per battle; only the forms of the engine's form-change tables, the 96 the Mega check covers). Floors 1-29: none. 30-49:
selected bosses (Flannery's Houndoom, Norman's Kangaskhan) and a few trainers. 50-69: the bosses and about a third of the
trainers. 70-89: every trainer's ace may Mega Evolve. 90-100: every trainer has an optimized Mega. Players use their own
Megas under the existing rules (the Mega Ring).

## 7. Floor data
* Source of truth: the engine's `src/data/tower_legends.party` (the game's own Showdown-format trainer file, made by
  `tools/tower_legends/generate.py` from curated pools and the hand-written bosses, with a fixed seed) compiled by
  `trainerproc` for the PC game; `tools/tower_legends/tower_legends.json` (the same data, and its hash) for the app and the
  tests; `src/data/tower_legends_floors.h` (each floor's kind, trainers, texts and music).
* Per floor: the solo trainer (team of 1-6), and the Duo pair: trainer A (the solo trainer with three of its team) and
  trainer B (a partner, three). Team sizes grow with the floor; bosses have larger teams.
* Legality: the species is enabled and has its own front, back, shiny and icon pictures (no placeholder); it can exist at
  that level (a level evolution only at or above its level, a stone evolution from 20, friendship from 18, trade from 30,
  other methods from 25, and every earlier stage's requirement); moves: the level-up moves learnable at that level (floors
  1-29), plus the game's TMs and tutors (from 30) and egg moves (from 50); no OHKO move; at least one damaging move; one of
  the species' own Abilities (the Hidden Ability only from floor 50); a real held item, no item twice in one team from floor
  30; IVs 0-31; EVs at most 252 each and 510 in all; a Mega Stone only for a species whose Mega it makes, at most one per
  trainer. Regular floors use no legendary, mythical, Ultra Beast or paradox species.
* Difficulty grows with team size, evolution stage, moves, abilities, held items, IVs and EVs, natures, the AI flags and the
  team's synergy, not only with the level.

### Bosses
| Floor | Boss | Pic | Class | Type theme | Mega | Duo partner |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | Brock | LEADER_BROCK_FRLG | Leader (FRLG) | Rock | - | a Hiker |
| 20 | Misty | LEADER_MISTY_FRLG | Leader (FRLG) | Water | - | a Swimmer |
| 25 (special) | Giovanni | LEADER_GIOVANNI_FRLG | Boss (FRLG) | Ground | - | a Team Rocket Grunt |
| 30 | Flannery | LEADER_FLANNERY | Leader | Fire | Houndoom | a Kindler |
| 40 | Norman | LEADER_NORMAN | Leader | Normal | Kangaskhan | Wally |
| 50 (special) | Wallace | CHAMPION_WALLACE | Champion | Water | Gyarados | Juan |
| 60 | Winona | LEADER_WINONA | Leader | Flying | Altaria | a Bird Keeper |
| 70 | Steven | STEVEN | Champion | Steel | Metagross | an Expert |
| 75 (special) | Brandon | PYRAMID_KING_BRANDON | Pyramid King | Frontier Brain (the Regis) | one member | Lucy (Pike Queen) |
| 80 | Drake | ELITE_FOUR_DRAKE | Elite Four | Dragon | Salamence | a Dragon Tamer |
| 90 | Blue | CHAMPION_RIVAL_FRLG | Champion (FRLG; never the rival classes, which print the rival's name) | balanced | Pidgeot or Alakazam | a Cooltrainer |
| 100 (final) | Red | RED | Champion | Pikachu, Charizard, Venusaur, Blastoise, Snorlax, Lapras, all level 100 | Charizard | Leaf (Duo: Red brings Pikachu, Charizard and Snorlax, Leaf Venusaur, Blastoise and Lapras) |
Bosses 25, 50, 75 and 100 are markedly harder (IVs 31, optimized EVs, natures and items, the smartest AI flags). Every pic
above exists in the engine; the generator and the self-test check each is drawn (not a placeholder) in this build. The Duo
partners use existing Emerald and FRLG trainer pictures; any substitution is listed in the generated floor list.

## 8. Engine <-> app interfaces (the contract)
All of these exist in the native PC game only. A game without them never sees them: the host enables the Tower only when its
installed game's manifest has `tower_abi_version` 1 (every player of a world runs the same build: hello `build_id`).

### 8.1 Capability
* Engine: `const u32 gMultiplayerTowerAbiVersion = 1;` (native marker, like `gMultiplayerRivalAbiVersion`).
  `scripts/multiplayer/generate_manifest.py` writes `tower_abi_version=1` when the marker exists (it needs the Players menu ABI
  2, `menu_open_page_abi_version` 1 and the shared world). The launcher opts in (`bridge.txt` line `tower=1`, like
  `menu_open_page=1`); the bridge's capability `tower` (1) then allows everything below; without it the bridge refuses it.
* The floor table's hash: `TOWER_LEGENDS_TABLE_HASH` (u32, CRC-32 of the canonical JSON's `floors` array) in the engine and
  `tower_legends.json`'s `hash` in the app; the solo command carries it and the game refuses a command whose hash differs.

### 8.2 Players menu
* **Open page 2 = the Tower.** START > PLAYER > TOWER calls `MultiplayerMenu_OpenPage(MP_MENU_PAGE_TOWER)` (2). The bridge
  accepts an OPEN action of 2 with the tower capability; app `menu_mailbox.OPEN_PAGES[2] = "tower"`.
* **Screen style (bytes 238-239 of the 240-byte screen, zero otherwise):** byte 238 `style`, byte 239 `arg`, only with the
  tower capability: 0 none; 1 Tower home; 2 floor map (arg: the first floor shown, 1..100); 3 floor or boss preview (arg:
  floor 1..100); 4 shop; 5 Duo status; 6 records; 7 Hyper Training information; 8 prizes. The classic window ignores it; the
  native PC UI draws the Tower screens from it (section 10).
* **Flags 4 = start a solo Tower battle.** A screen with flags 4, count 0, admission 0 and this 32-byte command at screen
  offset 68 (the rows area; every other byte of the rows area zero):
  ```
  u32 magic      0x31525754 ("TWR1")
  u32 ticket     nonzero, low byte nonzero (the host's ticket number)
  u32 tableHash  TOWER_LEGENDS_TABLE_HASH
  u8  floor      1..100
  u8  mode       1 (solo)
  u8  reserved[18] zero
  ```
  Valid only as the answer (ack == the game's last CHOOSE) of an open, waiting window. The game closes the window, then (with
  the field calm) starts the floor's battle, or refuses it (posting result 4, below): a different table hash, an unsettled
  Tower result in the save, no Pokemon able to battle, a battle or a save hold in progress.
* **Flags 5 = open Hyper Training.** Count 0, rows area zero: the game closes the window and opens the Hyper Training screens
  (section 5). Nothing is posted.

### 8.3 World action 7 (the game -> the host)
`struct MultiplayerWorldAction { u32 seq; u8 kind = 7; u8 result; u16 species = floor; u32 eventId = ticket; u32 amount = 0 }`
result: 1 started (the battle began), 2 won, 3 lost, 4 refused (the command could not start a battle), 5 drew (a loss for
the rules). The game keeps a won/lost/drew result in the save (section 8.6) and posts it again every 20 s and after every
(re)connection until a TOWER_STATE word (8.4) settles that ticket. The companion forwards it as world request
`{"type": "tower_result", "ticket", "floor", "outcome": "started"|"won"|"lost"|"refused"|"drew", "seq"}` and acknowledges
the action when the host has answered.

### 8.4 Reward words (the host -> the game, on the wallet stream)
`bit 30 | kind << 24 | payload (24 bits)`; the bridge accepts kinds 1-7 with the tower capability (1-5 without).
* **Kind 6, TOWER_STATE:** bits 22-23 op.
  * op 0 PROGRESS: bits 15-21 H (0..100), bits 8-14 P (1..101), bits 0-7 the settled ticket's low byte (0: none). The save's
    record takes H and P as they are (the host is the authority) and clears its unsettled result when the byte matches.
  * op 1 CLAIMS: bits 0-15 claim bits, OR-ed into the save's (never cleared): bits 0-11 the prize of floor 10, 20, 25, 30,
    40, 50, 60, 70, 75, 80, 90, 100 claimed; bits 12-15 the milestone Pokemon of 25, 50, 75, 100 delivered. Bits 16-21 zero.
  * Receipt amount: the record's revision after applying (a counter in the save; 8.6).
* **Kind 7, TOWER_MON:** bits 22-23 milestone (0: floor 25, 1: 50, 2: 75, 3: 100), bits 11-21 species (1..2047), bits 4-10
  level (1..100), bits 0-3 zero. The game makes the Pokemon (section 4) into the party, else the PC. Receipt amount: 1 made,
  0 nothing made (no room, an invalid species or level).

### 8.5 Duo battle code (the native co-op preparation's 32-bit flags; engine `multiplayer_ladder.h`, app `coop_code.py`)
The ladder layout with family 1 in bits 7-9 (the ladder requires them zero today, so an older engine refuses a Tower code):
`bit 31 ladder | bit 30 experience awarded | bits 20-29 floor (1..100) | bits 10-19 zero | bits 7-9 = 1 | bits 0-6 the floor
again`. Every core builds the floor's Duo trainers A and B (the Tower trainer ids, 8.7) from its own compiled table at
exactly the floor's level; experience goes through the co-op award with the cap (section 3); the battle plays the floor's
music. The host's existing native result path settles it (both cores agree).

### 8.6 Save: `struct MPTowerRecord` (SaveBlock3, after the Day Care egg queue, PC only; 64 bytes)
```
u32 magic;           0x314C5754 ("TWL1"); zero = no record (every older save): P 1, H 0, nothing claimed
u8  version;         1
u8  highest;         H 0..100
u8  progress;        P 1..101
u8  pendingOutcome;  0 none, 2 won, 3 lost, 5 drew
u32 pendingTicket;
u8  pendingFloor;
u8  reserved0;
u16 claims;          8.4 op 1's bits
u16 revision;        +1 for every kind 6 word applied
u16 reserved1;
u8  reserved[36];    zero
u32 crc32;           CRC-32 of the 60 bytes before
```
`MP_SAVE_BLOCK_3_BYTES` grows by 64 (1012 -> 1076): the engine's sector check and the app's `flash.py` (`SAVE_BLOCK_3_FULL_SIZE`,
a zero or valid record) move together.

### 8.7 Tower trainers in the engine
`GetTrainerStructFromId` (include/data.h) gets a PC-only first line: while a Tower battle is set up or running,
`TRAINER_TOWER_A` (= TRAINER_RED, 851) and `TRAINER_TOWER_B` (= TRAINER_LEAF, 852), never fought in Emerald, return the
floor's trainers from `gTowerLegendsTrainers`; every lookup (party, names, class, pic, AI flags, items, music, money) follows.
Their trainer flags are never set by a Tower battle.

## 9. The host (app)
* `tower.py` (TowerBook): shared-world SQLite tables (CREATE TABLE IF NOT EXISTS; documented in the module): players
  (P, H, claims, the save revision last seen, records), tickets (solo and Duo: issued, started, won, lost, drew, void,
  forfeit), Duo sessions, milestone choices, purchases. A player's first Tower action in a world (or a save whose record
  revision is newer than the ledger's) imports the save's record (the latest checkpoint) and keeps the larger claims.
* `tower_service.py` (TowerService): the rules of sections 2-4; issues solo commands (8.2) and Duo battles
  (`BattleDesk.invite_coop` with the Tower code, the Frontier's team selection), settles results once, queues TOWER_STATE,
  prizes and milestone words through `Wagers.grant`/`grant_reward`, reconciles every 5 s and on every status read and battle
  close (like the Frontier).
* `tower_menu.py`: the pages (home, solo, Duo invite/accept/status, replay, floors, boss previews, prizes, shop, Hyper
  Training information, records), within the menu's limits (title 23, status 31, six rows of 25, printable ASCII).
* `tower_rewards.py`: prizes, BP, money, the shop catalogue; `tower_legends.json`: the floor data and its hash.

## 10. UI
* Classic window (both builds): the host's pages.
* Native PC UI (the 3D build): `src/native_ui/screens/ui_tower.c` draws the Tower screens from the page's style (8.2), the
  game's own floor table (names, pictures, levels) and its save record: the home screen (current floor, highest, checkpoint,
  next boss, next milestone, BP), the 100-floor map (cleared, current, locked, bosses, specials, checkpoints, claimed prizes),
  the boss preview (name, region, picture, floor, difficulty, the prize; never the team), the shop, the Duo status. The host's
  rows stay the buttons; input and every rule stay in `multiplayer_menu.c`. Keyboard, mouse and controller as the Players UI.

## 11. Tests (plan)
Engine `--selftest-tower` (the table: every floor and trainer, levels, legality, pictures, Megas; the exp cap; the reward words;
the record; milestone generation; the codes and commands); the test build's `PKMN_TEST_BATTLE=tower:<floor>` (the real solo start
and end) driven by `tools/battle_env/tower_check.py` over all 100 floors, won and lost, on Linux and on the Windows runner; app
unit tests; launcher proofs in real games (solo run with a loss and a checkpoint, Duo run, Megas, prizes, saves, reconnects).
