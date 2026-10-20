# Update 32: short introduction, starters in Birch's lab, soft reset, three players, battle lobby (2026-10-20)

The owner's feature update (features 1-16, queued after the battle and trade repair of 2026-10-20), plus the later
request for complete Mega Evolution testing. This report covers features 1-10, which are implemented; features 11-16
(the earlier repairs re-checked, breeding, Windows) and Mega Evolution are in progress and get their own sections
when they are done. Branches: app `claude/admiring-bohr-dpxzuy`, engine `claude/feature-update-engine` (from the
repair's engine `c76651ea`). **Nothing is merged.**

Test environments are named as in `TEST_LEDGER.md`: **L** cloud Linux (native Linux games, software OpenGL, the real
launcher, companions and host; several "PCs" are several games on one machine), **W** Wine, **CI** the GitHub Windows
runner, **PC** the owner's PCs. **Every gameplay run below is L.** Nothing in this report ran on Windows or on a PC yet.

The release GBA ROM stays byte-identical after every engine change (SHA-256 `f214735b...3387`): every engine change is
PC-only (`#ifdef PORTABLE` or `MP_FFA_ENABLED`, GBA lines kept by `tools/pc_port/check_gba_lines.py`).

## 1. Summary

| # | Feature | What a player sees now | Engine | App | Evidence (L) |
| --- | --- | --- | --- | --- | --- |
| 1 | Short introduction | NEW GAME asks boy or girl at once, then the name; the character saves and starts in Littleroot with no Pokemon | `37f4edaf` | `66b0049` | `intro32_check.py` 9/9; `--selftest-update32` 35/0 |
| 2 | Characters with no Pokemon | Saving, loading, hosting, joining and reconnecting with an empty party; Pokemon-dependent actions say "Get a Pokemon in Birch's lab" / "They have no Pokemon yet" | `1b8af913`, `91d856fb` | `66b0049`, `47b7457` | newcomer-4 (two games) |
| 3 | Starters in Birch's lab | Three Poke Balls on the lab table; each opens the 18-starter screen on its own type; one claim per character | `37f4edaf` | - | `intro32_check.py`; newcomer-4 (two claims 18 s apart) |
| 4 | Soft reset | START > PLAYER > RESET: offline back to the last save; in a world the Players menu's reset page restarts the game from the host save, in the same session | `09ee5144`, `91d856fb` | `9397a61` | `soft_reset_check.py` 2/2; soft-reset-7 (two games) |
| 5 | Shiny starter hunting | Save, claim, inspect, reset, claim again: a new Pokemon each time, shiny 1 in 4096 | `37f4edaf`, `09ee5144` | `9397a61` | selftest 400,000 claims; soft-reset-7 (new personality and IVs) |
| 6 | Players in menus stay drawn | A player in a menu, the bag, the party screen or a dialogue stays drawn for the others; a battle or a map change hides them | `1b8af913` | `66b0049` | unit tests; real games: see 2.6 |
| 7 | Three players | Three players in one world | - | this update | see 2.7 |
| 8 | 1v1v1 | "Free-for-All - 3 Players": three trainers, each on a side of their own | `eb496d27` | this update | test ROM; ffa3-1, lobby-1 (three games) |
| 9 | 1v1v1v1 and 2v2 | Unchanged rules; reached through PLAYERS > Challenges > New battle | - | this update | see 2.9 |
| 10 | Battle lobby | Invite players; the format follows who joined (2: 1v1, 3: 1v1v1, 4: 1v1v1v1 or 2v2); start, leave, decline, cancel, time-out | - | this update | 14 unit/network tests; lobby-1 (three games) |

## 2. Features

### 2.1 Feature 1: the short introduction

- **New Game:** boy or girl at once (no speech), then the name, then the game saves the character and starts it in
  Littleroot Town in front of its house, with no Pokemon (`main_menu.c`, `multiplayer_rival.c`, PC build only).
- **Story state:** that of a character Birch has rescued and sent to Route 103 (`ApplyIntroState`: Birch rescued,
  the moving truck and the house visits done, the wall clock set, the player's room as the heal location), so Route
  101's rescue scene and its bag of starters never play. The path from Littleroot to Route 101 turns a character with
  no Pokemon back ("guard-no-pokemon"); with a Pokemon it is open. Character appearance (START > PLAYER > STYLE) is
  unchanged.
- **Existing characters** (earlier introductions) load as before: they never see the lab balls or the guard
  ("lab-update31-character").
- **Launcher:** character creation, the first Solo and the character library describe the short introduction; a
  character with no Pokemon is a valid character everywhere (feature 2).
- Evidence (L): `tools/pc_port/intro32_check.py` from a fresh boot and the field scene, 9 scenarios, 0 failed
  (intro-short-male, intro-short-female, guard-no-pokemon, guard-with-starter, lab-fire-ball, lab-grass-ball,
  lab-water-ball-kanto, lab-back-out, lab-update31-character); `--selftest-update32` 35 checks, 0 failed.

### 2.2 Feature 2: characters with no Pokemon

- No starter is created and none goes to the PC. The save is an ordinary save with an empty party (no placeholder
  Pokemon). The app accepts it wherever a character is made, handed over, recovered, enrolled, hosted or joined
  (`draft_runtime`, `character_handoff`, `character_migration`, `battle_roster`, the save checks); the engine's
  `tools/pc_port/save_safety_check.py` accepts a party of 0 to 6.
- Pokemon-dependent actions refuse with a reason on the page the choice was made from: a challenge or a trade with a
  trainer who has no Pokemon ("Get a Pokemon in Birch's lab" for oneself, "They have no Pokemon yet" for the other;
  `no_pokemon` / `peer_no_pokemon` from the host's battle and trade desks), the rival and championship menus; a World
  Event or a shared wild Pokemon talked to with no party says so instead of starting a battle.
- Evidence (L): newcomer-4 (`scripts/multiplayer/native_launcher_newcomer_proof.py`, two short-introduction
  characters through real launchers): enrolled and linked with no Pokemon (games and the host's canonical saves),
  both refusals by name with nothing left open on the host, a cut connection and a rejoin with no Pokemon, both lab
  claims, owned serials on the host, a 1v1 to its result, closing saves and a fresh Continue; 31 checks.

### 2.3 Feature 3: starters in Birch's lab

- Three Poke Balls on the lab table (the post-game table objects, shown while the character's starter is still to be
  claimed). Each ball opens the 18-starter screen on its own type (Fire, Grass, Water; the screen's regions keep every
  starter the game already offered, including the other generations'); B backs out with nothing given and the ball
  stays.
- The claim gives one level-5 Pokemon met in Littleroot, sets the starter flag and choice and works once per
  character (a second talk gives nothing; the balls disappear). Each player's game holds its own lab state, so players
  claim independently and at the same time; nobody can claim another player's starter or a second one.
- Evidence (L): the lab scenarios of `intro32_check.py`; newcomer-4: two players claimed in the same lab 18 s apart,
  one Pokemon each, each saved as an owned Pokemon on the host.

### 2.4 Features 4 and 5: soft reset and shiny starter hunting

- **Offline** (no world): START > PLAYER > RESET asks "Reset the game to your last save? Progress since then will be
  lost." (NO first). YES resets as A+B+START+SELECT does: the title screen, CONTINUE loads the last save.
- **In a world:** RESET opens the Players menu on its reset page: "Unsaved progress is lost", how old the host save is,
  "Save on host now" and "Reset to last host save" behind a question ("Reset the game?"). The reset closes the game and
  starts it again from the character's **host** save in the same launcher session: the world, the host's server and
  the other players carry on, nobody is disconnected, the host save is not changed by the reset.
- **Refused** (the reason on the page) while a trade, a challenge or a battle is open, while a save is in progress or
  has failed, or while the session is changing. So a committed trade cannot be undone, and nothing can be duplicated:
  the reset only goes back to what the host already holds. An older launcher's player is told the reset needs this
  launcher.
- **Shiny hunting:** a claim rolls personality, IVs, nature and shininess from the game's random state at that moment.
  That state is never stored in a save; every start of the game (and so every reset) seeds it from the PC's clock and
  it advances every frame, so a reset never repeats a roll. A starter claimed and saved on the host is the character's
  for good (the reset goes back to that save); one claimed after the last host save can be rolled again. Shiny odds
  are the configured 1 in 4096 (no Shiny Charm at the start).
- Evidence (L): `tools/pc_port/soft_reset_check.py` (save in the lab, claim, RESET and YES, the title, CONTINUE, a new
  roll; RESET and NO keeps playing): 2/2. `--selftest-update32`: every claim of 400,000 rolls a new Pokemon and the rate
  is 1/4096 within 4.5 sigma. soft-reset-7 (`native_launcher_soft_reset_proof.py`, two games): the page, "Save on host
  now", claim, reset, the same session restarted at the lab with no Pokemon and the friend still connected, a new roll
  (personality `ed741162` -> `179da0ec`, IVs 14/7/22/16/8/24 -> 12/30/25/5/4/13), both saves with one Pokemon, and
  with an open challenge the page offers no reset ("Cancel your challenge first"); 24 checks.

### 2.5 Battles and trades with a new character

A trainer with no Pokemon cannot be challenged or traded with (the refusals of 2.2); after the lab claim the same
character battles and trades normally (newcomer-4's 1v1).

### 2.6 Feature 6: players in menus stay drawn

- The game reports a dialogue, a cutscene and a save on the field as "menu" (they used to be "unavailable"), and while
  the field stays on screen (a dialogue, the START menu) its pose follows the avatar. The other players' launchers draw
  a player in a menu standing where they are; a battle or a map change still hides the avatar, and it is drawn again
  as soon as the player is back on the field. A game also keeps drawing the other players while its own script runs
  (frozen with every other object) instead of removing them for each sign read.
- Evidence: `tests/test_mailbox.py`, `tests/test_session_persistence.py` (simulated). Real games: the three-player
  proof below samples, ten times a second, whether the other games draw a player who is in the START menu, the bag, the
  party screen and PLAYERS (section 2.7).

### 2.7 Feature 7: three players

Three players were already supported by the world (up to four); this update adds the three-player battles (2.8, 2.10)
and checks the three-player world with real games: `scripts/multiplayer/native_launcher_three_player_proof.py`
(mixed parties: two characters with a Pokemon, one new character with none) - everyone linked and drawn by everyone,
menus, a refused trade, a trade between two while the third walks into the lab (another map), claims its starter and
comes back, a cut connection and a rejoin, a 1v1 while the third walks, saves and a fresh Continue.

Result: **pending** (the run follows this report's first commit; the ledger records it).

### 2.8 Feature 8: the 1v1v1

- **Engine (PC only):** battle phase 6. A 1v1v1 is the free-for-all's four battlers with the fourth place empty: three
  cores, every trainer on a side of their own (never two sides), the same rules code as the 1v1v1v1. The empty place is
  battler 3 (link player 3, no name, no Pokemon), drawn in the second player position on every game, so each player
  sees the two others where a double battle's opponents stand and the existing texts read right ("X and Y want to
  battle", "Go! A!"). The battle intro draws no trainer, party summary or Poke Ball for it; it is absent from the first
  turn; the VS screen names only the three. The winner is one of the three (slot + 1) or a draw. Marker
  `gMultiplayerBattleFfa3AbiVersion` (manifest `battle_ffa3_abi_version` 1); the bridge accepts phase 6 only from a game
  with it, with three source slots.
- **App:** mode 6 everywhere a battle mode is checked (envelopes, consent `EM-NATIVE-FFA3-CONSENT-1`, the host's desk,
  reservations, abandonment, the free-for-all results book with three players, the roster's link type, the launcher's
  battle panel); a companion refuses phase 6 without the game's marker. PLAYERS offers "Free-for-All - 3 Players" when
  exactly three are connected and, with four, a Free-for-All page (everyone, or three of the four).
- **Rules tests** (engine test ROM, `test/battle/ffa/ffa3.c`, `FFA3_BATTLE_TEST`: the free-for-all with the second
  player place empty): each trainer a foe of the two others and the empty place absent; Swift hits both others and
  nothing in the empty place; Surf hits both others; a single-target move at either one; a random-target move picks a
  real trainer, never the empty place; Intimidate lowers both others; turn order by Speed; a switch keeps the place;
  a trainer with no Pokemon left is out and the others fight on; the last trainer standing wins; a trainer who falls
  while another stands has lost. **Result: pending** (built after the app suite).
- **Channel tests** (`test/multiplayer_battle.c`): only phase 6 binds three players and it binds exactly three; three
  trainers start as one free-for-all with the empty place in the second player position everywhere. Test ROM
  "Multiplayer" 138/138.
- Evidence (L): **ffa3-1** (`native_launcher_ffa3_proof.py`, three games through real launchers): everyone linked
  ("Connected: 3/4"), the 1v1v1 from PLAYERS, played with default moves to its end (833 routed blocks, 273 s; winner the
  host, both friends lost), every launcher back with its original game, bridge and native identity, the same world
  sessions, each party back exactly, money, items, flags and variables unchanged, saves, store integrity and a fresh
  Continue; 38 checks. **lobby-1** (the same 1v1v1 started from a lobby, 2.10): 865 blocks, 279 s, winner the host; 40
  checks. Both runs used default moves: targeting choices are covered by the rules tests, not by these runs.
- **Rival formats unchanged:** `rival_formats.py` still plays three rivals as a round robin of 1v1s (that rule predates
  the 1v1v1; changing it is the owner's decision, `AGENTS.md`).

### 2.9 Feature 9: 1v1v1v1 and 2v2

The rules and the battle code are unchanged (Update 15's free-for-all, the full Multi 2v2; their engine tests still
pass: test ROM "Multiplayer" 138/138). What changed is the way in: the Challenges page now has "New battle" (the lobby,
and the free-for-all rows). The four-player proofs were updated for that step (`challenge_free_for_all`).
**Re-run with the new menus: pending** (a four-game lobby with a 2v2 start, and the four-player free-for-all).

### 2.10 Feature 10: the battle lobby (format detection)

- **Where:** PLAYERS > Challenges > New battle > Battle lobby: choose the players to invite ("Name: Yes/No"), "Send
  invitations". Invited players see a banner ("<name>: BATTLE LOBBY", "Open PLAYERS to join") and a "Battle lobby" row
  on PLAYERS' first page; they choose Join lobby or Decline.
- **The format follows who joined** (only players who joined count; nobody is pulled in): 2 joined (the creator and
  one): 1v1; 3: 1v1v1; 4: 1v1v1v1 or 2v2 (the creator picks, and for 2v2 the teammate). The lobby page shows the
  format, every member's state (leader, joined, declined, left, invited) and "Waiting for N to answer" or
  "<format>: N joined"; the creator has "Start <format>" for each playable format and "Cancel lobby"; a member has
  "Leave lobby".
- **Start:** the creator's game sends the ordinary challenge of that format to exactly the joined players (the game
  identity capture and consent are unchanged), and the host links the lobby to it only if the challenge is the
  creator's, names exactly the joined players and has a format their number allows. Each joined player then accepts
  the challenge as any challenge ("<format> CHALLENGE!", "Accept it in PLAYERS"), and from there the challenge's own
  deadlines and messages apply (Enter battle never waits forever, the repair of 2026-10-20).
- **Ends cleanly:** cancelled by its creator, the creator leaving the world ("LOBBY CANCELLED"), everyone declining,
  or 300 s without a start (timed out); an ended or started lobby stays visible 60 s. At most two open lobbies per
  world and one per trainer; a trainer in a battle cannot open one.
- **Host side:** `battle_lobby.py` (`LobbyDesk`, session-local: nothing is stored, a host restart ends every lobby),
  `lobby_protocol.py` (strict requests and replies, like the team channel); the companion's `lobby_rpc`.
- Evidence: `tests/test_battle_lobby.py` (14: the desk's formats, joins, declines, leaves, starts that must match the
  joined set, time-outs and the creator leaving; the protocol; the whole menu flow over a real host with four connected
  players). (L) **lobby-1** (`native_launcher_lobby_proof.py`, three games): the host invited both friends ("Waiting for
  2 to answer"), each joined from PLAYERS, the host's page showed "1v1v1: 3 joined" with "Start 1v1v1" and no other
  format, the start, both accepted, the 1v1v1 to its end, saves and a fresh Continue (above). The four-player choice
  (1v1v1v1 or 2v2) is unit-tested; its real-game run is pending (2.9).

## 3. Known limits

- Nothing here ran on Windows (W or CI) or on a PC yet (feature 16 is next).
- Players of one world need the same version: the world's build id is the game data (unchanged GBA ROM hash), so an
  older and a newer launcher can meet in a world, and a host that does not know a request type ends that player's
  connection. A newer player with an older host is disconnected when PLAYERS asks for the lobbies (as it already was
  for every earlier new request type, such as friendship); an older player cannot read a 1v1v1 challenge. KNOWN_ISSUES
  MS-28.
- MS-17 (a healthy native battle interrupted by the host core's expired deadline, seen twice on four games) is still
  open and **release-blocking**; no 1v1v1 run hit it.
