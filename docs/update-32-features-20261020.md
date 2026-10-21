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
| 6 | Players in menus stay drawn | A player in a menu, the bag, the party screen or a dialogue stays drawn for the others; a battle or a map change hides them | `1b8af913` | `66b0049` | unit tests; three-4 (three games: every sample drawn) |
| 7 | Three players | Three players in one world | `62c1711a` (MS-30) | this update | three-4 (three games, 61 checks) |
| 8 | 1v1v1 | "Free-for-All - 3 Players": three trainers, each on a side of their own | `eb496d27` | this update | test ROM; ffa3-1, lobby-1 (three games) |
| 9 | 1v1v1v1 and 2v2 | Unchanged rules; reached through PLAYERS > Challenges > New battle | - | this update | lobby4-1 (a 2v2 from a lobby); see 2.9 |
| 10 | Battle lobby | Invite players; the format follows who joined (2: 1v1, 3: 1v1v1, 4: 1v1v1v1 or 2v2); start, leave, decline, cancel, time-out | - | this update | 14 unit/network tests; lobby-1 (three games), lobby4-1 (four games) |

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

Result (L, three games): **three-4 passed** (61 checks) on engine `af9b33dd`:

- Everyone drawn by everyone at once; a player in the START menu, the bag, the party screen and PLAYERS stayed drawn
  for both others in every sample (START 30/30, bag 50/50, party 40/40, PLAYERS 30/30 per observer; the longest gap
  0.0 s). Pictures: the host's and the newcomer's view of the friend in its bag.
- The newcomer (no Pokemon) was refused a trade with "Get a Pokemon in Birch's lab"; in the lab (another map) it was
  drawn by nobody and drew nobody; it claimed a starter (20.6 s) while the other two traded; the trade applied in 11 s.
- The friend's connection was cut; it joined again and everyone was drawn again at once.
- **A 1v1 right after the trade** (neither had saved since) ran to its end in 110 s while the newcomer walked 105 steps;
  the two battlers were hidden from the walker (220 of 221 samples) and drawn again at once afterwards. All three saved
  the expected Pokemon; a fresh Continue.

The earlier runs: three-1 and three-2 failed in the proof itself (a recording name clash; the rejoin check read the
trade's persistent notice in PLAYERS as a status); **three-3 found a real bug**: that 1v1 right after the trade never
started. The trade's canonical post-image keeps the save counter of the frozen export (it is byte-preserving) while the
game writes it one counter higher, and the game's PREPARE refused a preparation naming the image's counter: both
launchers held the battle as interrupted and stopped saving. It is older than this update (KNOWN_ISSUES MS-30).
Reproduced with two games (trade-battle-1, `native_launcher_challenge_proof.py --scenario trade-battle`), fixed in
engine `62c1711a` (PC only: after it imports a canonical image the game accepts that image's counter until it saves
again; the trainer id and party CRC checks are unchanged), and trade-battle-2 passed on the fix.

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
  while another stands has lost. **Result: 11 of 11 passed** (the whole test ROM suite on engine `7abaa6c6`, 2026-10-21; TEST_LEDGER).
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
Re-run with the new menus (L, four games): **lobby4-1 passed** - a 2v2 started from a lobby of four (2.10) ran to its
end in 724 s with the teams the host chose, everyone back with the same parties. The four-player free-for-all from the
Challenges page (Free-for-All > Everyone: 4 Players): **mega-5 passed** (section 4.3) - it ran to its end in 390 s and
everyone was back with the same parties; and the free-for-all proof itself (`native_launcher_ffa_proof.py`) through
the new page: **ffa-qf7-1 passed** (57 checks: the free-for-all to its end in 718 s, the host the winner and three
losers in the free-for-all book, everyone back in the world with the same sessions, saved, money, items and
progression unchanged, a fresh Continue). Its leave-during-the-battle variant and the abandonment proofs were not
re-run in this update.

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
  format, the start, both accepted, the 1v1v1 to its end, saves and a fresh Continue (above). **lobby4-1** (`native_launcher_lobby4_proof.py`, four games, 57
  checks): the host invited three; two joined and one declined: "1v1v1: 3 joined", the decliner shown as declined,
  only "Start 1v1v1"; the two accepted, the decliner had no challenge and no battle and stayed on the field in every
  sample (69 of 69) while the 1v1v1 ran to its end (343 s); a second lobby where all three joined showed "1v1v1v1 or
  2v2: 4 joined" with "Start 1v1v1v1" and "Start 2v2"; "Start 2v2" asked "Choose your 2v2 partner", the host chose the
  first friend, the teams were host + first friend against the other two, and the 2v2 ran to its end (724 s); everyone
  was back in the world with the same parties after each battle.

## 3. Known limits

- Nothing here ran on Windows (W or CI) or on a PC yet (feature 16 is next).
- Players of one world need the same version: the world's build id is the game data (unchanged GBA ROM hash), so an
  older and a newer launcher can meet in a world, and a host that does not know a request type ends that player's
  connection. A newer player with an older host is disconnected when PLAYERS asks for the lobbies (as it already was
  for every earlier new request type, such as friendship); an older player cannot read a 1v1v1 challenge. KNOWN_ISSUES
  MS-28.
- MS-17 (a healthy native battle interrupted by the host core's expired deadline, seen twice on four games) is still
  open and **release-blocking**; no 1v1v1 run hit it.

## 4. Mega Evolution

The owner's request (2026-10-20, during this update): inspect the Mega Evolution the game has, test every Mega and
every rule automatically (the 14 items of 4.3), in real game processes including Windows ones, repair what is broken,
report what is missing, and keep new implementation apart from testing. **Mega Evolution is not declared fully
verified** (4.5).

### 4.1 What the game has

- **97 Mega Evolutions** in the species data's form change tables, the game's own list (the test ROM and the
  real-game check both read it at run time): 96 by a Mega Stone - the Gen 6-7 Megas, Charizard X and Y and Mewtwo X
  and Y among them, the Legends Z-A Megas of Gen 1-9 species and Mega Zygarde (from Zygarde-Complete) - and Mega
  Rayquaza, by the move Dragon Ascent without a stone. **92 different Mega Stones** for the 96 (Tatsugiri's three
  forms share one, as do Magearna's two forms and male and female Meowstic).
- **Getting them on PC:** the Mega Ring is a Game Corner prize in Mauville (25,000 coins); the Mega Stone dealer in the
  Mauville Poke Mart, only for a player with the Ring, sells **82 stones** (the Mega of every Gen 1-6 species) for
  30,000-100,000 coins (Update 29). The release GBA ROM keeps its own way (the dealer gives the Ring after the fourth
  badge).
- **Missing (reported; not built here):**
  - 10 stones are neither sold nor found anywhere: the Megas of Gen 7-9 species (Crabominite, Golisopite, Drampanite,
    Falinksite, Glimmoranite, Baxcalibrite, Scovillainite, Tatsugirinite, Magearnite, Zeraorite). They work when held
    (the tests hand them over), but no player can own them.
  - Mega Rayquaza cannot be reached: Rayquaza cannot learn Dragon Ascent (MS-39). Primal Reversion is enabled but
    neither orb can be obtained.
  - Mega Lucario Z's Ability, Aura Guard, is unimplemented (it does nothing; MS-38), while Lucarionite Z is sold.
  - The dealer sells a stone the player already owns again (one of each is all a player needs).
- **Rules** (the battle engine's, unchanged): the stone must be the species' own and the Ring must be in the bag; one
  Mega per trainer per battle; the form lasts until the Pokemon faints or the battle ends (switching keeps it); a usable
  stone cannot be knocked off, stolen or swapped; the turn a Pokemon Mega Evolves it moves at its old Speed.
- **Multiplayer** (native battles of linked players, PC): before this update only the player whose game runs the
  battle could Mega Evolve (MS-32).

### 4.2 New implementation, repairs and test tools

- **New implementation:** every player of a native multiplayer battle can Mega Evolve with their own Ring and stone,
  one Mega each, in the 1v1, 1v1v1, 1v1v1v1 and 2v2 (engine `731a7c87`, app `5bde8c5`; MS-32, MS-33). The battle's
  running game names a battler's usable Mega in the move request it sends; the player's own game offers it only with
  the Ring in that player's bag; the host's route accepts that one mark and nothing else.
- **Repairs** (KNOWN_ISSUES): MS-34 Mega Chimecho's HP, MS-35 a revived Mega's mark, MS-36 the one-Mega rule when the
  turn's choices are carried out, MS-37 Zygarde-Complete's crash screen at every battle's end (engine `8906fb9b`);
  MS-40 the Mega Ring message that stopped a player's game in a 1v1v1, 1v1v1v1 or 2v2 (engine `d02e0cc9`); MS-41 the
  Mega Stone dealer's coin display (engine `b763ce6f`). Each was found by these tests; all are older than Update 32.
- **Test tools** (test builds only, never shipped): the test ROM's Mega tests (`test/battle/form_change/`, 26) and the
  native controller's test; the battle test driver's Mega log and the Classic 2D test build with
  `tools/battle_env/mega_check.py` (engine `7b7d2489`, `2bcbeffb`): everything read from the game's own log, so the same
  check runs on Windows; the multiplayer proof `scripts/multiplayer/native_launcher_mega_proof.py` (app `c2db4e8`,
  `0f95b61` and this report's commit): four games, three games, and two games with one player without the Ring
  (in either game).

### 4.3 Results by requested item

**T** the engine's GBA test ROM (`make check`, battles without a link). **L** cloud Linux, real game processes: the test
builds of 4.2 for single-player battles (Classic 2D and 3D), the player build through the real launcher for
multiplayer. **CI** the GitHub Windows runner: real Windows game processes of the Classic 2D test build (a hosted
runner, not a player's PC; Windows' software renderer).

| # | Requested | Tests | Result |
| --- | --- | --- | --- |
| 1 | Every Mega, Charizard X/Y and Mewtwo X/Y | T: every holder of the form change tables (96) by dex range; Mega Rayquaza by Dragon Ascent. L/CI `mega_check.py --sweep`: every holder in a wild battle of its own in the real game, level 100, read from its log. The four-game proof's leads: Charizard X and Y, Mewtwo X and Y | T 25 of 26 (the 26th is MS-39, Rayquaza cannot learn the move; its Mega works when it knows it). L: **passed**, all 96 holders (Classic 2D), and all 96 again shiny; Mega Rayquaza, which no player can reach, only in T. CI: **passed**, all 96 holders and all 96 again shiny (run 97, engine `7abaa6c6`; run 95 the same) |
| 2 | Stones: ownership, purchase, equip, remove, persistence | L/CI `mega_check.py --items`, the game's own menus: GIVE from the bag and SAVE; TAKE and SAVE; load; the Ring bought at the Game Corner (25,000 coins, the Shiny Charm declined) and Venusaurite from the dealer (60,000 coins), each saved, then loaded: Ring, stone and coins left, money untouched. `--selftest-coins` (prices, payment) | L: **passed** (items-6), and it **found MS-41** (the dealer's coin display; fixed). CI: **passed** (runs 95 and 97: the stone given, used, taken, saved, loaded and reset away; the Ring and Venusaurite bought, saved and loaded) |
| 3 | Eligibility and activation | T: the right stone with the Ring, a wrong stone, no stone, a species without a Mega, Floette and Zygarde forms. L/CI cases: no Ring, another species' stone, Pikachu holding Charizardite X, Zygarde-Complete with and without Zygardite: the move menu offers the trigger exactly when it may, and START turns it on. L multiplayer (two games through the launcher, a 1v1): one player without the Ring, once in the game that runs the battle (its own bag is read) and once in the other game (it refuses the Mega the running game names) | L: **passed**, all 12 cases in the Classic 2D test build and all 12 in the 3D one; multiplayer **passed** (mega-noring-1, -2, mega-noring-host-1: the player without the Ring never offered the Mega, the other player Mega Evolving, one Mega in both games). CI: **passed**, all 12 cases (run 97; in run 95 the Gym and rival cases never ended: the check's own Recover fault, fixed in `7abaa6c6`) |
| 4 | Appearance, form, typing, stats, Ability | T: each holder's Mega form, typing, Ability, stats and max HP (found MS-34). L/CI: in every battle the lead as the game shows it (species, types, Ability, the Mega mark) against the species data, after the animation drawn with the Mega form's palette, and a picture | L: **passed**, all 12 cases in the Classic 2D test build and all 12 in the 3D one. CI: **passed**, all 12 cases and all 96 holders (run 97) |
| 5 | Moves, damage, turn order | T: the Mega turn at the old Speed and the next at the Mega's; Mega Mawile's Huge Power doubles its damage; Mega Charizard X loses Flying and Ground hits it | T: passed. Not re-checked in a real game (damage is the engine's, the same code) |
| 6 | One Mega per battle | T: once per battle; one of two holders in a double; checked again when carried out (found MS-36). L/CI: the double case, Venusaur and Blastoise both holding their stones: one Mega on the player's side | L: **passed**, all 12 cases in the Classic 2D test build and all 12 in the 3D one. CI: **passed**, the double case (runs 95 and 97) |
| 7 | Switching, fainting, battle end, soft reset | T: switching keeps the form; fainting reverts it and the Mega stays used; a revived Mega unmarked (found MS-35). L/CI: after every battle the lead is its own form holding its stone; after a Mega battle the stone taken (not saved) and START > PLAYER > RESET: back from the title the save as it was. A reset in the middle of a battle does not exist on PC (4.4) | T: passed. L: **passed** (items-6; every case). CI: **passed** (runs 95 and 97: the items check with the reset; after every case and holder the lead its own form holding its stone) |
| 8 | Wild, trainer, rival, Gym, multiplayer | L/CI cases: wild, trainer, Gym (Roxanne), rival (May, a shiny Mewtwo), a Multi with an in-game partner, both sides Mega Evolving; multiplayer: item 9 | L: **passed**, all 12 cases in the Classic 2D test build and all 12 in the 3D one. CI: **passed**, all 12 cases (run 97) |
| 9 | 1v1, 1v1v1, 1v1v1v1, 2v2 | L, four games through the real launcher: mega-5. T: a free-for-all, a 1v1v1 and a multi battle with every trainer Mega Evolving | L: **passed** (mega-5; the 1v1 also with two 3D games, mega-two-3d-2; earlier runs: 4.5). T: passed. Not on Windows (4.4) |
| 10 | Several players Mega Evolving in one battle | As 9: every player of every battle Mega Evolved (2, 3, 4 and 4 Megas, marked in every game) | L: **passed** (mega-5) |
| 11 | Animations and rendering, Classic 2D and 3D | L/CI: a picture after each Mega's animation (every case and holder), the parade of every Mega form on both sides; the multiplayer proof's screenshots of each game | L: **passed** - Classic 2D: a picture after the Mega animation in every case and for every holder (normal and shiny), the parade of all 96 forms on both sides (normal and shiny), no placeholder; 3D: every case's Mega and the parade of all 96 forms (normal and shiny) in the Diorama battle scene; the multiplayer proofs' screenshots of each game at its Megas (Classic 2D), and a 1v1 of two 3D games (mega-two-3d-2: both Mega Evolved, each game drawing both Megas in the 3D battle scene, the battle to its end, saved, a fresh Continue). CI: **passed**, Classic 2D: a picture after the Mega animation in every case and for every holder (normal and shiny), both parades of all 96 forms (run 97); the 3D build does not run on the runner (Windows' software renderer has no OpenGL 3.3: the graphics mode check offers Classic 2D there) |
| 12 | Save and load without duplication or corruption | L/CI items: one stone, never two or none, through give, take, save, load and the reset; the purchases saved and loaded. L multiplayer: every party the canonical one after each battle, all saved, the store's integrity check, a fresh Continue | L: **passed** (items-6, mega-5). CI: **passed** (runs 95 and 97, the items check) |
| 13 | Shiny Megas, shiny legendaries | T: every Mega form has a shiny palette of its own; a shiny Pokemon Mega Evolves into its shiny colors. L/CI: the shiny sweep (every holder shiny, the legendary and mythical ones among them: Mewtwo X and Y, Latias, Latios, Diancie, Zygarde, Heatran, Darkrai, Magearna, Zeraora), each drawn with its shiny Mega palette; the shiny parade; the rival case's shiny Mewtwo Y; the proof's shiny Mewtwo Y | T: passed. L: **passed** - the shiny sweep (96 of 96, each drawn with its shiny Mega palette, the legendary and mythical holders among them), the shiny parade, the rival case's shiny Mega Mewtwo Y (2D and 3D), the four-game proof's shiny Mewtwo Y Mega Evolving in the 1v1v1v1 and the 2v2. CI: **passed**, the shiny sweep 96 of 96, each drawn with its shiny Mega palette, and the shiny parade (runs 95 and 97); the rival case's shiny Mega Mewtwo Y (run 97) |
| 14 | Pokemon that cannot Mega Evolve, wrong stones | As 3 | L: **passed**, all 12 cases in the Classic 2D test build and all 12 in the 3D one; the multiplayer runs without the Ring (3). CI: **passed**, all 12 cases (run 97) |

### 4.4 Not verified

- **No player's PC** ran any of this. Windows: only the runner's single-player check (CI, 4.3). No multiplayer Mega
  battle ran on Windows: the four-game proof needs the Linux harness (it reads each game's memory with gdb's help).
- **Co-op battles** (linked players against the game's trainers, the co-op Battle Frontier): the Mega mark of 4.2
  covers every native link battle, co-op included, but no co-op battle with a Mega ran in a game.
- **A soft reset in the middle of a battle does not exist on PC**: RESET is a field menu, and the A+B+START+SELECT chord
  is claimed by the multiplayer reset handler and never resets, by design. What was tested is the reset on the field
  after a Mega battle (item 7).
- **Damage and turn order** after a Mega Evolution were checked in the test ROM only (item 5).
- **3D multiplayer:** one 1v1 of two 3D games ran (mega-two-3d-2, item 11); the 1v1v1, 1v1v1v1 and 2v2 with Megas ran
  in the Classic 2D player build only (three or four 3D games on software OpenGL are too slow for the proofs'
  deadlines).
- The gaps of 4.1 (10 stones, Mega Rayquaza, Primal Reversion, Aura Guard) are owner decisions or new work; none was
  done here.

### 4.5 Verdict

**Mega Evolution is not declared fully verified.** Every supported Mega form and every rule the request names passed
the automated tests listed in 4.3 where they could run (the test ROM, real Linux game processes, and the Windows
runner's single-player check), and the multiplayer formats passed with four real games through the launcher. Missing
for a full verification: the items of 4.4 (no PC, no Windows multiplayer, no co-op), and the game's own gaps of 4.1
(10 stones no player can get, Mega Rayquaza unreachable, Aura Guard unimplemented), which need the owner's decision
before they can be built or tested. MS-17 (KNOWN_ISSUES) stays release-blocking; no Mega run hit it.

Earlier runs, for the record: mega-1 to mega-4 and mega-three-1 to -3 (four and three games) failed in the proof or
found MS-40 (4.2); the items check items-1 to -5 was tuned on its pictures; the case table's Mewtwo first fought with
its own first move, Recover, and never ended its battles (fixed in the check, engine `7abaa6c6`).

## 5. Features 11-16

### 5.1 Features 11-14: rival matchmaking, trading, lag, battle backgrounds

These four were the battle and trade repair that ran just before this update
(`docs/multiplayer-battle-trade-repair-20261020.md`; KNOWN_ISSUES MS-19 to MS-27): the stuck "Waiting for server..." of
two players entering a 1v1 (root causes and fixes in its section 1-2), the stalled trades and their failure exits, the
35-40 s frozen fields after a trade (measured, fixed), and the 3D battle background that stood still after slow frames
(fixed, 3D and 2D checked over many frames). This update re-checked them in real games (L) and found one more:

- **Matchmaking and battles:** every battle of this update's proofs went through the repaired challenge path: the 1v1s
  of mega-2, mega-3 and mega-5, the 1v1v1 of ffa3-1, lobby-1, lobby4-1 and mega-three-4/mega-5, the 1v1v1v1 and the 2v2
  of lobby4-1 and mega-5, each entered, played to its end and closed with everyone back in the world. None stayed on
  "Waiting for server...". MS-17 (a healthy battle interrupted by the host core's expired deadline) did not recur and
  stays open and release-blocking.
- **Trading:** the three-player proof's trades applied in about 10-11 s while the third player walked. A battle right
  after a trade, before either player saved again, **never started** (MS-30, older than Update 32): fixed in engine
  `62c1711a`; trade-battle-2 and three-4 passed on the fix.
- **Lag:** no new measurement in this update; the four-game proofs report no event-loop stall.
- **Battle backgrounds:** not re-checked in this update beyond the repair's own checks.

### 5.2 Feature 15: breeding and the Pokemon collection systems

Audit of what exists (the engine's Day Care, eggs and hatching; PC storage; party; catching; evolution; shiny):

- **Implemented and tested** (`--selftest-breeding` 64 checks, 0 failed on this update's build; the test ROM's
  `test/daycare.c` and `test/egg_hatch.c`; the app's save and ownership tests): Day Care deposit from the party or a PC
  box and withdrawal (100 + 100 per level gained); the 64-step egg check (70/50/20% by compatibility; Ditto 50/20; the
  Undiscovered group never); up to five Eggs waiting per character (Update 30); the egg species, incense babies,
  Nidoran/Volbeat/Illumise, Manaphy to Phione and regional forms; egg moves; Everstone nature, three inherited IVs (five
  with the Destiny Knot), the Gen 6 Ability and Poke Ball rules; hatching in 32 steps per cycle, halved by Flame Body,
  Magma Armor or Steam Engine; the hatched Pokemon's friendship 120, met level 0, its trainer the hatcher; a shiny
  rolled into the Egg when it is made (three rolls with a shiny parent, six with two, three more with the Shiny Charm).
- **Repaired:** level-up moves both parents know were inherited only if they were the baby's first learnset move (and
  the loop read past its four-move array): MS-31, engine `af9b33dd` (PC only).
- **Reported, not changed** (they are owner decisions or missing content, not faults of the code that exists):
  - MS-42: the PC's hatch speed is 87.5% fewer steps than this game's Gen 6 cycle (257), not the 75% Update 30 asked for.
  - Items breeding uses that a player cannot get: the Power items, seven of the nine incenses (Full, Luck, Odd, Pure,
    Rock, Rose, Wave), the Oval Charm and the Mirror Herb; the Destiny Knot only from Pickup (about 1% at level 21 and
    up). So Munchlax, Happiny, Mime Jr., Chingling, Bonsly, Budew and Mantyke cannot be bred.
  - The Masuda method does not exist (by the project's rules: shiny parents add rolls instead).
  - A party that is full keeps the Eggs waiting at the Day Care (none go to a PC box); Eggs cannot be traded (KNOWN_ISSUES
    U30-4).
  - Latent: hatching sets the trainer to the hatcher, and a Pokemon's shininess depends on its trainer id, so an Egg
    hatched by another trainer than the one it was made for could change shininess. No such path exists today (each
    character's Day Care and Eggs are its own and Eggs cannot be traded).
- Catching, evolution, friendship, PC storage, party management and the shiny rates were not changed by this update;
  their tests pass (the app suite, `--selftest-shiny`).

### 5.3 Feature 16: Windows

What ran on Windows, on the GitHub runner (CI: real Windows processes, Windows' software renderer, Classic 2D; not a
player's PC), from this update's branches (windows-package runs 95 and 97, full, engine `2bcbeffb` and `7abaa6c6`, app
`0f95b61`, ROM pinned `f214735b...3387`):

| Update 32 feature | On the runner | Result |
| --- | --- | --- |
| 1 Short introduction, 2 characters with no Pokemon | The installed build's play check: two profiles each create a character through New Game (now the short introduction: no Pokemon), Solo, Host World on the runner's address, the friend joins with the invite code; every save in its world | **passed** in both runs (no error in either profile) |
| Mega Evolution (section 4) | The Classic 2D test build in real Windows game processes: the 12 cases, the 96 holders, the parade, the stones through the menus (give, take, save, load, RESET, the Ring and a stone bought), then the 96 holders and the parade shiny | **passed** in run 97 (engine `7abaa6c6`): 110 of 110 (the 12 cases, the 96 holders, the stones through the menus, the parade), then 97 of 97 shiny (the 96 holders, the parade), 73 minutes. Run 95 (engine `2bcbeffb`): 108 of 110 and 97 of 97 - the Gym and rival cases never ended (the check gave Mewtwo its own first move, Recover; fixed in `7abaa6c6`), everything else passed |
| The package itself | Build, package contents, the packaged game files, the frozen launcher stays up, the graphics mode check (3D unsupported on the runner, Classic 2D offered), the in-game menu check, silent install, repair, uninstall, Create World | **passed** in both runs |

Not run on Windows (the hosted runner's checks cannot drive them yet; the four-game proofs need the Linux harness):
the starters in Birch's lab (3), the soft reset and shiny rerolls (4, 5), players drawn in menus (6), three players (7),
the 1v1v1 (8), four-player battles (9), the lobby (10), battles and trades between players (11, 12), lag (13), battle
backgrounds (14) and breeding (15). Each passed on Linux (sections 2 and 5); on Windows they are for the final QA
update and the owner's PCs.
