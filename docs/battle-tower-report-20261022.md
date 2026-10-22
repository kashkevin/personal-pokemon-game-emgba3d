# Battle Tower: Legends - implementation and verification report (2026-10-22)

The owner's queued update (QUEUED 1). Design and the engine/app contract: `docs/battle-tower-legends.md`. Every floor:
the engine's generated `tools/tower_legends/FLOORS.md`. Test records: `TEST_LEDGER.md` (2026-10-22 section); faults:
`KNOWN_ISSUES.md` MS-47 to MS-52.

Environments: **L** cloud Linux (real game processes of the PC game under Xvfb; the real launchers and world server);
**W** GitHub's Windows runners (`windows-package` full runs: real Windows game processes on a hosted runner, one PC on
its own loopback - not a player's PC, no second PC or Internet); **T** the engine's GBA test ROM; **S** an engine
self-test. Nothing here was run on the owner's own PC. "Passed" below means executed and passed; anything not executed
says so.

## 1. Implementation summary

* **Engine** (PC only, `#ifdef PORTABLE`; the GBA ROM is unchanged, `f214735b...3387`): `src/tower_legends.c` - the
  save's Tower record (`struct MPTowerRecord`, SaveBlock3, CRC-sealed), the solo floor (its intro, the battle against
  the floor's trainer, the result kept in the save until the host settles it), the trainer hook for the two Tower
  trainer ids, the experience cap, the reward words (Tower state, milestone Pokemon), world action 7 (started,
  refused, won, lost, drew), the Duo battle code on the native co-op battle, Hyper Training and the Ability Patch
  through the Bag and the party menu, the native UI page data (`src/native_ui/screens/ui_tower.c`).
* **Floor data**: `tools/tower_legends/generate.py` builds the 100 floors from the game's own data
  (`pokeemerald-mp --dump-tower-data`): 1030 Pokemon on 100 solo teams and 200 Duo teams, 118 Mega Stone holders,
  table hash `0x5256f5dd` (the game refuses a host with another table).
* **App (host)**: `tower.py` (the ledger: players, tickets, words, Duos, milestones, purchases), `tower_service.py`
  (issues, settles, pays, reconciles), `tower_rules.py` (progress, checkpoints, caps, legality), `tower_rewards.py`
  (prizes, BP, the shop), `tower_menu.py` (the Players menu pages), `tower_data.py` / `tower_floors.py`.
* **This session's changes** (2026-10-22): MS-47 co-op team selection (the whole saved party travelled), MS-48 held
  items after an evolution, MS-49 the queued floor's deadline and the save hold, MS-50 the shop lock; the breeding
  check; the Windows jobs for the Tower floors, caps and items, the launcher proofs, breeding, the multiplayer Mega
  proof and interrupted battles.

## 2. Branches and commits

| Repository | Branch | Head at this report | Tower commits |
| --- | --- | --- | --- |
| App | `claude/admiring-bohr-dpxzuy` | see the final report | `6a6b6a5`, `1550320`, `304daed`, `647f275`, `c241ecf`, `15ab178`, `0db6cf7`, `6123912`, `ac5c5c6`, `3ee7c91`, `4dcec39`, `6a3639e`, `f9c4df6`, `dbb8185`, `4cddf97`, `8c668bc` (MS-53), `a100436` (MS-54), `26a6e15`, `341e505` (the ui proof), `815d4b6` (the climb on Windows), `1c9d1f3` (co-op progression: no repeated rewards, the host chooses the Duo floor), `5034e60` (the Duo's save gate, MS-60), `81cec9a` (the join proof's host restart), `cff44fe` and `4328509` (MS-60's fix: a game with unsaved progress turned away at Enter; the Duo page's "Save first: launcher Save now") |
| Engine | `claude/feature-update-engine` | `547d0789` (the Tower's code unchanged since `a5ce214d`: the later commits are test-build checks, MS-57's fix and MS-60's save mailbox QUERY_PARTY) | `1ba266c8`, `122ebcda`, `282ec5d9`, `68a8b0f5`, `547b2950`, `0df64e01` (co-op selection, also the Frontier's), `f4c512b4`, `6408f4ce`, `83214a4e` (breeding check), `a5ce214d` |

Not merged: integration waits for every release gate (section 15).

## 3. The 100 floors

All 100 floor definitions - trainer, class, picture, every Pokemon's level, item, Ability, nature, IVs, EVs and moves,
the Duo pair, texts and music - are in the engine's `tools/tower_legends/FLOORS.md`, generated from the floor table
`tools/tower_legends/tower_legends.json` (version 1, hash `0x5256f5dd`); the game's own copy is
`src/data/tower_legends*.h`. Summary:

| Kind | Floors | Count |
| --- | --- | --- |
| Regular | every floor not listed below | 88 |
| Boss | 10, 20, 30, 40, 60, 70, 80, 90 | 8 |
| Special boss | 25 (Giovanni), 50 (Wallace), 75 (Brandon) | 3 |
| Final | 100 (Red) | 1 |

Every opposing Pokemon is exactly the floor's level (floor 1 = level 1 ... floor 100 = level 100). Mega Stone holders
on the solo teams, by ten floors: none before floor 30 (Flannery's Houndoom is the first), 1 on 21-30, 2 on 31-40, 3 on
41-50, 4 on 51-60, 4 on 61-70, 10 on each of 71-80, 81-90 and 91-100; 118 holders counting the Duo teams. The S check verifies the table against the game's own data
(2077 checks: species, moves legal for the species, items, Abilities, every party as a battle builds it).

## 4. Boss roster and sprite sources

| Floor | Kind | Boss | Class (prints) | Picture (source) | Mega | Battle music | Duo partner (class, picture) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | boss | BROCK | LEADER_FRLG (LEADER) | LEADER_BROCK_FRLG (FRLG) | - | MUS_RG_VS_GYM_LEADER | HIKER CLIFFORD (HIKER_FRLG, HIKER_FRLG) |
| 20 | boss | MISTY | LEADER_FRLG (LEADER) | LEADER_MISTY_FRLG (FRLG) | - | MUS_RG_VS_GYM_LEADER | SWIMMER♀ CORAL (SWIMMER_F_FRLG, SWIMMER_F_FRLG) |
| 25 | special | GIOVANNI | BOSS_FRLG (BOSS) | LEADER_GIOVANNI_FRLG (FRLG) | - | MUS_RG_VS_GYM_LEADER | TEAM ROCKET GRUNT (TEAM_ROCKET_FRLG, ROCKET_GRUNT_M_FRLG) |
| 30 | boss | FLANNERY | LEADER (LEADER) | LEADER_FLANNERY (Emerald) | Mega Houndoom | MUS_VS_GYM_LEADER | KINDLER ASHTON (KINDLER, KINDLER) |
| 40 | boss | NORMAN | LEADER (LEADER) | LEADER_NORMAN (Emerald) | Mega Kangaskhan | MUS_VS_GYM_LEADER | PKMN TRAINER WALLY (RIVAL, WALLY) |
| 50 | special | WALLACE | CHAMPION (CHAMPION) | CHAMPION_WALLACE (Emerald) | Mega Gyarados | MUS_VS_CHAMPION | LEADER JUAN (LEADER, LEADER_JUAN) |
| 60 | boss | WINONA | LEADER (LEADER) | LEADER_WINONA (Emerald) | Mega Altaria | MUS_VS_GYM_LEADER | BIRD KEEPER SKYLER (BIRD_KEEPER, BIRD_KEEPER) |
| 70 | boss | STEVEN | CHAMPION (CHAMPION) | STEVEN (Emerald) | Mega Metagross | MUS_VS_CHAMPION | EXPERT RENZO (EXPERT, EXPERT_M) |
| 75 | special | BRANDON | PYRAMID_KING (PYRAMID KING) | PYRAMID_KING_BRANDON (Emerald) | Mega Tyranitar | MUS_VS_FRONTIER_BRAIN | PIKE QUEEN LUCY (PIKE_QUEEN, PIKE_QUEEN_LUCY) |
| 80 | boss | DRAKE | ELITE_FOUR (ELITE FOUR) | ELITE_FOUR_DRAKE (Emerald) | Mega Salamence | MUS_VS_ELITE_FOUR | DRAGON TAMER RYUJI (DRAGON_TAMER, DRAGON_TAMER) |
| 90 | boss | BLUE | CHAMPION (CHAMPION) | CHAMPION_RIVAL_FRLG (FRLG) | Mega Alakazam | MUS_RG_VS_CHAMPION | COOLTRAINER TRISTA (COOLTRAINER_FRLG, COOLTRAINER_F_FRLG) |
| 100 | final | RED | CHAMPION (CHAMPION) | RED (FRLG) | Mega Charizard X | MUS_RG_VS_CHAMPION | PKMN TRAINER LEAF (RIVAL, LEAF) |

Sprite sources: every picture is one the game already has - FireRed/LeafGreen trainer pictures (`TRAINER_PIC_*_FRLG`,
RED, LEAF) for the Kanto bosses and their partners, Emerald's for everyone else; Pokemon pictures are the game's own.
The generator refuses a species whose picture is the game's question-mark placeholder (the sprite audit, engine
`282ec5d9`), so no floor shows an invisible or placeholder Pokemon. Substitutions from the design (Blue's class,
Blue's Mega, Red's Charizardite X, ...) are listed in FLOORS.md.

## 5. Solo and co-op behaviour

* **Solo**: START > PLAYER > TOWER (or PLAYERS > Battle Tower: Legends) > Solo: floor P > the floor's preview > Start
  the battle. The battle runs in the player's own game where they stand; the result is written into the save's record
  at once and sent until the host settles it. After it: the party healed, held items back (MS-48: once, not an item an
  evolution used). A started floor whose result never arrives counts as a loss on the next ask (forfeit). A queued
  floor that cannot start within 45 s is refused, never started late (MS-49).
* **Duo**: two players of a team; one invites (Invite: floor F, or a replay floor), the other accepts, both Ready. The
  host issues the native co-op battle with the floor's two trainers; each player brings at most three Pokemon (the
  host's team selection; MS-47 fixed the selection's transport); each game awards its own party's experience under its
  own cap. A released result settles both players; an abandoned battle is void for both.
* **Co-op progression** (owner request 2026-10-22, app `1c9d1f3`): different progress never keeps two players apart.
  The Duo's host - the player who invited - chooses the floor, any floor open to both (each player's own next floor or
  one they cleared), so a player who has climbed higher joins a friend's lower floor; the partner cannot change it.
  Each player's page row says what the floor pays them ("prizes": their first clear; "Exp only": cleared before). After
  each battle the Duo goes on to the lower progress floor. Between two Duo floors both players save with the launcher
  (Save now or its autosave; app `5034e60`): the host prepares each native battle from the players' host saves and the
  co-op award changes the parties after a battle, so Ready answers "Save your game first" until each player's save is
  newer than the one the last floor was prepared from (KNOWN_ISSUES MS-60). The page said "Save first: START > SAVE"
  until app `cff44fe`; the game's own save is not a host save, so it now says "Save first: launcher Save now".

| Behaviour | Evidence | Result |
| --- | --- | --- |
| Solo floors through the menus, settled by the host, money and BP in the next save, checkpoint prize, replay, Tower Shop purchase | L tower-solo-7 and -8 (found MS-53 and MS-54), tower-solo-9; W runs 121 and 129 (floors 1-11 and the replay passed, then MS-53 at the shop), run 133 | passed on Linux (solo-9: 11 floors, the replay, the HP Up bought for 16 BP, the closing saves +$15,900, 10 Rare Candy, 1 HP Up, BP 0 to 3); passed on Windows (run 133 end to end; runs 138 and 141 again) |
| The special boss's loss back to checkpoint 20 (player 2 on floor 25) | L tower-solo-9; W run 133 | passed on Linux (P 21, H 24, saved) and on Windows (runs 133, 138, 141) |
| Milestone Pokemon (Giovanni, floor 25) made in the game, replay without a second | L tower-milestone-2; W run 129 | passed (L: Miltank level 15 made and delivered; W run 129: claims 4100, the replay paid no second prize; both runs then stopped at the shop, MS-53) |
| Duo floor 1: invitation, Ready, native co-op battle, settled for both | L tower-duo-2 (battle won and settled), tower-duo-3 (whole proof); W runs 121, 129 | passed (L, W) |
| Mega Duo: floor 40 replay, Norman's Kangaskhan Mega Evolves in the co-op battle | L tower-mega-2; W runs 121, 129 | passed (L, W) |
| Forfeit: a solo floor closed mid-battle, counted as a loss on the next ask | L tower-forfeit-2, W runs 121, 129 | passed (L, W) |
| Co-op progression: player 1 (floors 1-11 cleared, three level-10 Mewtwo) joins player 2's (floors 1-9) Duo on player 2's floor 10, plays 10, 11 and 12; player 2's game closed and started again between 10 and 11 | L tower-join-2 (floor 10 passed; floor 11 found MS-60), tower-join-3, tower-join-4; W run 151 (`join`) | passed on Linux (tower-join-3) and on Windows (run 151, the same payments and levels; player 2's game closed by TerminateProcess there): floors 10 and 11 paid player 1 nothing (0 BP, $0, no items) while its Mewtwo gained 847/421/421 and 898/448/448 experience; player 2 got Brock's prize (6 BP, $10,000, 10 Rare Candy) and 2 BP + $1,100; player 2 back with P 11, H 10; player 1's Ready refused until it saved; floor 12 paid both 2 BP + $1,200; the final saves: player 1 $1,200, 2 BP, Mewtwo at levels 14, 12, 12; player 2 $12,300, 10 Rare Candy, 10 BP; both P 13, H 12. tower-join-4 again, then the world's host and both games restarted: the host kept P 13, H 12 and best 12, and 30 s later each game's money, items, BP and record were still its save's (nothing paid again). Windows: run 151's `join` job on `a7d3aa8` (before the restart check) and the next run |

## 6. Checkpoints and saves

* Checkpoints 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100; a loss sends the climb to the floor after the highest
  checkpoint reached (`tower_rules.checkpoint`, engine `CheckpointBelow`).
* The record (64 bytes in SaveBlock3, CRC-sealed; a damaged record is not trusted) holds progress, highest, claims, the
  unsettled result and a revision; the host's ledger is the authority and imports a newer save's record (a character
  from another world). Every prize and state change travels on the wallet stream with a receipt (exactly once per
  save).
* Evidence: S (record, words, damaged record, unsettled result, claims), app tests (`test_tower*.py`), L/W proofs (the
  saved record after each proof: P, H, claims, money, items, BP and the PC checked in the canonical checkpoint).

## 7. Experience cap

Badges 0-8 -> 15, 20, 25, 30, 40, 45, 50, 55, 60; Champion -> 100. Solo: the in-battle award is clamped
(`TowerLegends_ClampExp` from `Cmd_getexp`); Duo: the co-op award is clamped with each game's own badges. Evidence: S
(caps, the clamp below, at and above the cap), L `tower_check.py --caps` (real Tower battles: no badges, one badge,
eight, the Champion, a Pokemon above its cap; engine `68a8b0f5`), W runs 121 and 129 "Battle Tower caps and items" (passed).

## 8. Rewards and anti-duplication

* Prize floors' first clears (Rare Candy, Bottle Caps, Gold Bottle Caps, Ability Patches, money, the four milestone
  Pokemon), BP and money for a floor's first clear, nothing for a loss - `tower_rewards.py`. **A floor already cleared
  pays nothing again** (owner request 2026-10-22; until then replays and re-climbs paid a third of the BP and $30 or
  $10 a floor): a replay, a re-climb after a loss and a Duo partner's lower floor give no BP, money, items, prize or
  milestone; their battles still give experience (each game's award, with levels, moves and evolutions). First-clear
  rewards resume once a player wins a floor above the highest they ever cleared in the world (`tower_rules.first_clear`:
  above H and above the ledger's `best`, which no save import lowers; a prize floor's claim bit also counts), each
  player reckoned on their own.
* Exactly once: each prize is a reference on the wallet stream (a repeat queues nothing); the game's receipt says what
  moved; a claim bit in the save and the ledger stops a second first-clear prize; a milestone Pokemon is made from a
  seed of (milestone, species, trainer id), so a resend makes the same Pokemon and a save that already has it answers
  "already delivered" (2) and makes nothing; the host records the species before anything is sent.
* Fixed this session: MS-48 (held items copied after an evolution), MS-50 (an order without its debit held the shop).
  Open: MS-51 (a milestone Pokemon lost when the game closed unsaved after the delivery and the older save has no room).

## 9. Bottle Cap, Gold Bottle Cap, Hyper Training, Ability Patch

Hyper Training from the Bag and from the Tower page (the stat list shows natural IVs and trained stats; the trained bit
counts the stat as 31 and travels with the Pokemon); the Ability Patch switches to and from the Hidden Ability after a
confirmation; each refuses without using the item where it would do nothing. Evidence: L `train_check.py` (a Bottle
Cap, a Gold Bottle Cap and an Ability Patch used through the game's own Bag and party menus, refused where they would
do nothing, saved and loaded; engine `282ec5d9`); W runs 121 and 129 "Battle Tower caps and items" (passed).

## 10. Tower Shop and Battle Points

Battle Points are the save's own counter (shared with the Frontier; at most 9,999). The shop debits first (the game's
receipt), then gives the item; refunds when nothing can be given; one order at a time; an order without its debit is
void (MS-50).

| Item | BP | Item | BP | Item | BP |
| --- | --- | --- | --- | --- | --- |
| Bottle Cap | 48 | HP Up / Protein / Iron / Calcium / Zinc / Carbos | 16 each | Focus Sash | 48 |
| Gold Bottle Cap | 192 | Leftovers | 48 | Assault Vest | 64 |
| Ability Patch | 200 | Choice Band / Specs / Scarf | 64 each | Rocky Helmet | 48 |
| Ability Capsule | 50 | Life Orb | 64 | Expert Belt | 48 |
| Rare Candy | 24 | Weakness Policy | 48 | Lum Berry | 16 |
| PP Up | 24 | PP Max | 64 | Sitrus Berry | 8 |

Earning: a first clear pays (1 + floor // 10) BP x 3 on the boss floors, x4 on 25/50/75, x5 on 100, else x1; a floor
already cleared pays no BP (section 8; until 2026-10-22 a later win paid a third). Evidence: app tests; L/W solo proofs (the
HP Up bought for 16 BP and found in the next save).

## 11. UI evidence

The Classic 2D menus are the Players menu's pages, recorded by every proof (titles, rows and status lines in
`evidence.json`, e.g. "Tower Friend: floor 1 / You: floor 1 / Invite: floor 1 / Invite: replay a floor"). The 3D game's
native PC UI pages are pictured by the launcher proof's `ui` scenario: two 3D games through the whole launcher, player 1
opening each page from the Players menu. On Linux it passed end to end (L tower-ui-5, app `341e505`, the 3D player
build of engine `a5ce214d`; the engine commits since touch only test tools and logs: ten pages pictured, the saves, a normal close, a fresh Continue, the store's integrity check):
the home page (floor, best, BP, the next boss Brock with his sprite, the session's milestones), floor 1's preview
(Tuber Larry, "Win: 1 BP, $100", the experience cap), floors and bosses (Brock, Misty, Giovanni, Flannery...), the
100-floor map (floors 1-4 listed, the grid with won/next/boss/special colours), prizes and shop, the floor prize list
(10 Rare Candy, 5 Bottle Caps, the Shiny Pokemon, 15 Rare Candy...), the Tower Shop (Bottle Cap 48 BP, Gold Bottle Cap
192 BP, Ability Patch 200 BP, Ability Capsule 50 BP, the Bag's counts), Hyper Training, records and the Duo page ("Form a
team in PLAYERS first"). The pictures are in the session's proof directory (not in Git: they show the game's art).
Windows: the same scenario runs in windows-package's tower-proof `ui` entry through Mesa's software OpenGL (pinned; the
hosted runner's own OpenGL is 1.1): **passed in runs 138 and 141** (Mesa's software renderer only; no graphics card).

## 12. Test matrix

| Area | T / S / app | L | W |
| --- | --- | --- | --- |
| Floor table against the game's data | S 2077/0 | - | - |
| Every floor won and lost (test build) | - | 200/200 (engine `547b2950`); the final build's rerun stopped at floor 49 (98/98: Windows ran all 100) | 200/200 in run 121 and in run 129 (`docs/battle-tower-floors-20261022.md`) |
| Experience caps in real battles | S | passed (`--caps`) | passed (runs 121, 129) |
| Items in the real menus | - | passed (`train_check.py`) | passed (runs 121, 129) |
| Solo through the launcher (prizes, replay, shop) | app | passed (tower-solo-9, after MS-53 and MS-54) | passed end to end in run 133 (floors 1-11, Brock's prize, the replay, the HP Up bought with 16 BP, the saved wallet as the host's rules say); runs 121 and 129 stopped at the shop (MS-53) |
| Special boss loss, milestone Pokemon | app | passed (tower-solo-9, tower-milestone-2) | passed in run 133 (player 2 lost Giovanni and went back to floor 21; the milestone proof end to end); the milestone part already in run 129 |
| Duo (native co-op) | T (team selection) | passed (tower-duo-3) | passed (runs 121, 129) |
| Mega Duo | - | passed (tower-mega-2) | passed (runs 121, 129) |
| Forfeit | app | passed (tower-forfeit-2) | passed (runs 121, 129) |
| Held items after evolution, queued floor deadline | S | - | - |
| Shop order without its debit | app (2 tests) | - | - |
| Battle Points received since the save (MS-53), "Close the menu to finish" (MS-54) | app (new tests) | passed (tower-solo-9) | passed (run 133 solo and milestone) |
| 3D native UI pages | - | passed (tower-ui-5: ten pages) | passed in runs 138 and 141 (`ui` entry, Mesa only) |
| A whole climb, 100 floors, through the launcher (`climb`, fast-text fixtures) | - | passed (tower-climb-3: both players floors 1-100, 189 minutes, every claim, $990,000, 45 Rare Candy, 751 BP and 4 milestone Pokemon paid as the rules say) | passed in runs 141 and 145 (both players floors 1-100 in 181 and 181.5 minutes, the same prizes paid) |
| Co-op progression: a higher player on a friend's lower floor, no repeated rewards, experience kept, first clears resume, a reconnect, a save between Duo floors (`join`) | app (the owner's 30-and-10 example over 22 floors; replays, re-climbs, restarts, reset and older saves; the host's floor choice; MS-60's gate) | passed (tower-join-3; tower-join-4 and -5 with the host's restart; tower-join-reset-1 with player 2's soft reset after a prize it had not saved: the prize arrived again once) | passed in runs 151 (`join`, its first Windows pass) and 158 (`join` with the restarted world's check: records kept, nothing paid again); the soft reset passed in run 160 (`join-reset`: the prize the game had not saved arrived again once, the records kept) |

## 13. Windows gameplay verification

GitHub's hosted Windows runners (`windows-2022`), real Windows game processes of the MinGW build; not a player's PC.

* Run 116 (app `6123912`, engine `547b2950`): floors 1-5 of the solo proof and the forfeit's loss counted; the floor
  shards and the caps-and-items job never started a game (a workflow argument fault), the Duo and Mega Duo hit MS-47,
  the solo proof's old fixture could not pass floor 6, the forfeit's final save hit the harness's host close.
* Run 121 (app `6a3639e`, engine `a5ce214d`,
  https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39700894025): every floor won and lost (200 of
  200), caps and items, Duo, Mega Duo and forfeit passed; the milestone proof stopped on its own record right after the
  game made the Pokemon (harness, fixed); the solo proof passed floors 1-11 and the replay, then MS-53 at the shop.
* Run 129 (app `c5c2a35`, engine `a5ce214d`,
  https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39704312638): the same passes again, the
  milestone Pokemon made and delivered on Windows; solo and milestone then stopped at the shop (MS-53, before its fix).
* Run 133 (app `26a6e15`, engine `b1066514`,
  https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39710794241): every Tower job passed - the four
  floor shards (200 of 200 again), caps and items, Duo, Mega Duo, forfeit, and, for the first time on Windows, the solo
  proof end to end (floors 1-11 settled, Brock's 10 Rare Candy and $10,000, floor 10 replayed at the replay rates of the time, an HP Up
  bought in the Tower Shop with 16 BP, the next save holding $15,900, 10 Rare Candy, 1 HP Up and 3 BP as the host's rules
  say; player 2 lost Giovanni on floor 25 and went back to floor 21, nothing paid) and the milestone proof end to end.
* Run 138 (app `341e505`, engine `83808e7e`,
  https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39716739086): the release candidate's run,
  with the new `ui` entry (the 3D pages through Mesa): every Tower job passed (the four floor shards, caps and items,
  solo, milestone, Duo, Mega Duo, forfeit, `ui`); the run's one failure was the multiplayer `ffa-exit` (MS-57).
* Run 141 (app `a2ce0a2`, engine `da278011`,
  https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39723669535): every Tower job passed again;
  the new 100-floor climb through the launcher passed (both players floors 1-100 in 181 minutes, every claim, the
  saves paid as the rules say).
* Run 145 (app `1a9a14b`, engine `65641401`,
  https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39741875955): every Tower job passed again
  (the four floor shards, caps and items, solo, milestone, Duo, Mega Duo, forfeit, `ui`), and the climb for the second
  time (both players floors 1-100 in 181.5 minutes, every claim, the saves paid as the rules say). The run's three
  failures were multiplayer proofs' own (TEST_LEDGER.md).
* Run 151 (app `a7d3aa8`, engine `65641401`,
  https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39778505816): the co-op progression's first
  Windows pass (`join`: player 1's replays paid nothing while its Mewtwo levelled, player 2's first clears paid, the
  Ready refused until the save, floor 12 paid both) and every other Tower job again, the climb for the third time
  (both players floors 1-100 in 180.5 minutes, every claim, the saves paid as the rules say): 54 of 54.
* Run 158 (app `46e46ee`, engine `547d0789`,
  https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39803470837): MS-60's fix; every Tower job
  but the climb had passed when this was written (the four floor shards, caps and items, solo, milestone, Duo, Mega
  Duo, forfeit, `ui`, and `join` with the restarted world's check: the saves held exactly what the host paid, the
  restarted host kept both records and paid nothing again); the climb still running (TEST_LEDGER.md).

## 14. Known issues and limitations

MS-53 (medium, fixed in app `8c668bc`, verified on Windows in run 133): the host read the Battle Points only from the
last save, so the shop refused points a climb had paid (found by the Windows and Linux solo proofs). MS-54 (low, fixed
in app `a100436`, verified in run 133): the shop said "Waiting for your game..." while the game, which pays only on the
field, waited for the menu to close. MS-55 (low, cosmetic, open): a new Players menu page opens with the cursor on the
row chosen on the page before (the Tower Shop opens on its second item); the rule is the menu's GBA code.
MS-51 (low, open): a milestone Pokemon lost in a narrow case (game closed unsaved after the delivery, older save full).
MS-52 (low, open, cosmetic): native Tower screens show the game's copy of the record until the host's word arrives.
MS-60 (high, fixed; the Duo's save gate since app `5034e60`, verified on Linux in tower-join-3): the host prepares a
native battle from each player's host save, and a party the co-op award changed after the save made the next Duo
floor's start refused; the Duo waits until both players have saved with the launcher ("Save first: launcher Save now";
it said "START > SAVE", which saves only in the game). Outside the Tower the same refusal held every trainer of any
native battle entered with unsaved progress, and its abandonment lost that progress; since engine `547d0789` and app
`cff44fe` a game whose party is not its host save is turned away at Enter, before anything is held (a Duo battle
refused this way is void for both).
MS-49's remainder: a game below about 22 frames a second could still start a floor after the host's two minutes. The 3D
UI is verified on Linux and on Windows through Mesa only (runs 138, 141). The full 100-floor climb through the launcher
passed on Linux (tower-climb-3) and on Windows (runs 141 and 145). Older Mega items (MS-38
Mega Lucario Z's Aura Guard, MS-39 Mega Rayquaza) affect no Tower floor (no floor uses them).

## 15. Integration and release readiness

Not merged. Gates: the Windows run on the final commits green (Tower jobs included), the multiplayer proofs green, no
open critical or high fault (MS-47 fixed and confirmed on Windows in runs 121 and 129), save integrity verified (every proof's
canonical checkpoints), app and engine commits compatible (one engine commit per run, ROM pinned), the newest features
covered (this report's matrix). Status: in progress. The Tower jobs passed in runs 133, 138, 141 and 145 (the whole
climb on Windows in runs 141 and 145); multiplayer's MS-57 (High: a battle stopped once the host's battler was out of
Pokemon) is fixed in engine `65641401` and the app and verified on Windows (the free-for-all in runs 145 and 147, the
2v2 in run 147). The co-op progression (app `1c9d1f3`, `5034e60`) passed on Linux (tower-join-3, -4) and on Windows
(run 151). MS-60 (High, found by the co-op progression's proof; its general case outside the Tower confirmed in real
games) is fixed in engine `547d0789` and app `cff44fe`, `4328509`, verified on Linux (stale-save-6, -7) and on Windows
(run 158's `stale-save` entry, both attempts); run 158's climb was the gate still open when this
was written. See the final report.
