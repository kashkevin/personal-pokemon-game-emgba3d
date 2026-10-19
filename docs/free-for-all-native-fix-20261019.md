# The four-player free-for-all through the native bridge, and what testing it on Windows found (2026-10-19)

The owner's request: fix the 1v1v1v1 free-for-all so it works through the real native game's multiplayer bridge without
disconnecting anybody; test it with four real game processes on one host; check entering, finishing, returning to the world
and staying connected; winning, losing, disconnecting, reconnecting and simultaneous battles where supported; that saves,
Pokemon, items and progression stay intact; recheck the earlier session fixes; make sure the latest Windows installer still
supports Create World, Solo, Host World and Join Friend; run the suites and Windows CI; never call a scenario passed unless
it ran, and say where it ran.

Branches: app `claude/admiring-bohr-dpxzuy`, engine `claude/mp-session-engine`. The default branches are unchanged
(app `claude/emeraldtogether-combined-app` `30dffa7`, engine `claude/emeraldtogether-combined` `47767264`).

Where each result comes from, in this document:

| Label | Meaning |
| --- | --- |
| **Simulated** | Unit tests and real servers/companions over TCP with a scripted game bridge; no game runs |
| **Linux** | The native Linux game (the same engine sources as the Windows game, built for Linux), real launcher code, X displays, one cloud PC |
| **Wine** | The Windows game under Wine on the cloud PC, with the Linux launcher (not run this round) |
| **Windows CI** | GitHub's hosted Windows Server 2022 runner (a VM without a graphics card): the real installer, installed and played there |
| **PC** | The owner's PCs. **Nothing in this document ran on a physical PC or a home network.** |

## 1. The free-for-all (MS-11)

**Root cause.** The host sends a free-for-all as native battle phase 5 (four cores, `MP_FFA_ENABLED` on PC). The bridge's
`BattleControl` accepted phases 2-4 only, so the first free-for-all command would have stopped all four games' links
("invalid battle command"). The free-for-all had only ever run on the GBA test ROM and in simulation. A second defect waited
behind it: the app's `Retirement` record (a battle's terminal handoff, which repeats RELEASE's party CRC and outcome) allowed
outcomes 1-3, while a free-for-all's outcome is the winner's slot 1-4, or 5 for a draw.

**Changes.**
* Engine `44b6ebea` (`src/platform/mp_bridge.c`, PC only): phase 5 with its four-participant mask when the game's
  `gMultiplayerBattleFfaAbiVersion` marker is set (new capability `battleFfa`, checked against `battle 3`); the startup log
  says `ffa 1`. The GBA ROM is unchanged (`f214735b...3387`).
* App `5357402`: `native_battle.validate_command`/`validate_response` check a RETIRE/HANDOFF outcome against its phase (1-5
  for the free-for-all, 1-3 otherwise).

**Tests.**

| Test | Where | Result |
| --- | --- | --- |
| `tools/pc_port/tests/test_mp_bridge.c` `free_for_all_commands_reach_the_game` (all four source slots, refused without the marker and for a fifth slot, the four-player mask) | Simulated (native C test) | 4393 checks, 0 failures; **11 failures on the old bridge** |
| `tests/test_native_battle_resume.py` `test_free_for_all_retirement_carries_its_winning_slot_or_draw` | Simulated | passes; **fails on the old code** |
| `scripts/multiplayer/native_launcher_ffa_proof.py` run **ffa-2** | Linux, 4 games | **passed** (below) |
| the same, run ffa-1 | Linux, 4 games | the battle passed (the host won, 1076 s, 1457 routed blocks, everyone back on the field in the same sessions); the run stopped at the proof's own item comparison, which compared encrypted bytes (fixed in `6c65f05`; the stored saves re-read: unchanged) |

**ffa-2, four real games through the whole launcher** (real `LauncherWindow`/`SessionWorker`/`LauncherSession` per player,
production world creation and enrollment, the real world server and store; app `6c65f05`, engine `44b6ebea`):

1. All four linked, each game drawing the other three; every PLAYERS tab "Connected: 4/4" (sessions 10-13).
2. The host opened PLAYERS > Challenges > "Free-for-all 1v1v1v1"; the three friends opened the pending challenge and
   accepted; all four saw the same challenge (mode 5) and pressed Enter battle.
3. One native free-for-all ran to its end with default moves: **1408 routed blocks, 1139.5 s; Friend 1 won (outcome 2);
   the host, Friend 3 and Friend 2 lost.** Every link stayed up for the whole battle (checked every 30 s). Every launcher
   reported `battle_finished` with its original game, bridge and native identity; each trainer's exact party was back in
   memory; the host's free-for-all book (`shared_world.ffa`) has the result.
4. Everyone back on the field at their own spot **in the same sessions (10, 11, 12, 13)**, rosters of four, PLAYERS
   "Connected: 4/4" on all four.
5. All four saved (revision 2). Each character's canonical save before and after the battle, decrypted: **money 3000 ->
   3000, the same item, every flag and variable unchanged** (all four). Store integrity check passed; a normal close (exit
   codes 0); a fresh Continue onto the same canonical saves; the source saves unchanged.

Winning and losing: both seen (ffa-1: the host won; ffa-2: a friend won, the host lost). A draw (outcome 5) is accepted by
the bridge and the app (simulated), not seen in a real run.

## 2. A player leaving during the free-for-all (exploratory; ffa-leave-1, Linux, 4 games)

`native_launcher_ffa_proof.py --leave-after 120 --watch 240`: 120 s into the battle (161 routed blocks) the last friend
closed their game the ordinary way (exit code 0). What the other three saw, every 30 s for 240 s:

* **Nobody else was disconnected.** All three stayed connected to the world with their game links up and rosters of three.
* **They stayed in the battle.** From 30 s on the host's battle desk was `recovery_required` (`execution_interrupted`) and
  every launcher `battle_recovery_held`, offering "Recover interrupted battle"; nobody could save or return to the field.
  That recovery is same-core: it waits for all four original games, and one of them is gone.
* After they closed their games too (exit codes 0), **the host's launcher refused to open the world again**:
  `pending_battle`, "An interrupted battle needs recovery before this character can open" (checked directly with the run's
  files). The host keeps a durable reservation for the battle and every participant a recovery intent.

This is the documented policy for every native PvP battle, not new with the free-for-all ("Process termination or power
loss that destroys the original native core remains outside this recovery mechanism", `docs/native-battle-recovery.md`).
What this run shows is its consequence: **if any player's game closes, crashes or loses power during a native battle,
everyone in that battle is locked out of that world** (here the host, so the whole world), with no supported way out. The
characters' saves are untouched (a PvP battle never changes them). Changing that, for example letting the remaining players
abandon an interrupted battle with no result and their parties as they were, changes a battle-integrity rule, so it needs
the owner's decision (`KNOWN_ISSUES.md` MS-16). Reconnecting **outside** a battle is supported and passed (section 5).

## 3. Found while testing the installed Windows build

The new installed play check (section 4) ran the native game together with the launcher's companion on real Windows for
the first time. That found three defects; all three are fixed and the Windows evidence is the fixed installer's.

### MS-13 (critical, Windows only): every Windows manifest lacked the PC-only capabilities

`windows-package.yml` generates the Windows game's manifest from `i686-w64-mingw32-nm --print-size` of the Windows
executable. A PE executable has no symbol sizes, so MinGW prints `00c0449c R _gMultiplayerBattleFfaAbiVersion` with no
size column, and `generate_manifest.py` required one. Every Windows manifest since these markers existed therefore lacked
the **free-for-all, rival and presence-detail** capabilities. (The Linux and Wine runs used a manifest generated from Linux
symbols, which have sizes; the tests' "MinGW" lines had a size the real tool never prints.)

Without presence detail the companion refuses the game's pose whenever it is off the field (battle, menu, map change, title
screen: `MailboxError: local pose reserved byte must be zero`) and closes its link; the game reconnects and is refused again.
On the installed build (installed check run 39298566536) a character could not enter a world ("Setting up your character
could not finish"; the game's log: "Multiplayer bridge connected to local companion", then "disconnected", three times).
**It also means the session fix delivered earlier today (installers of windows-package runs 39259757031 and 39272719523)
could not have held a Windows player through a battle or a menu**: on Windows, the owner's original report would have
reproduced with those installers. And the free-for-all and rival checkpoints were not offered on Windows at all.

Fix (app `fc41598`): the markers are read with or without a size (a size, when printed, must still be four bytes; one
marker; data, not code); `windows-package.yml` now fails if a marker the Windows game has is missing from its manifest
(run 39300939302: "PC-only markers in the manifest: ['battle_ffa_abi_version', 'rival_abi_version',
'presence_detail_abi_version']"); the companion keeps why it refused a game's bridge (`last_bridge_refusal`) and carries it
in the lost-bridge error, instead of dropping it. Tests: `tests/test_battle_manifest.py` (the real MinGW lines; fails on the
old generator), `tests/test_session_persistence.py` (the refusal reason).

### MS-14 (high, PCs without 3D): character creation and registration ignored the graphics check

Only playing went through the 3D check and its "Play in Classic 2D this time". Creating a character and bringing a
character into a world (the first step of Solo, Host World and Join Friend) always started the 3D game, which on a PC
without OpenGL 3.3 only reported "Graphics unavailable" and closed (run 39272719523's installed check: "Graphics
unavailable (3D Diorama): glActiveTexture is missing"; that check only looked for the process). Fix (app `66babe1`): the same
check and choice; Classic 2D is not asked twice in one menu session. Tests: two in `tests/test_shell_app.py`, both failing on
the old code. The installed world check now answers the question (`31c45ad`).

### MS-15 (medium): a key that "cancelled" a registration the world had already saved

The game a character enters a world with closes by itself once the world has saved the character. A key the player meant
for the game (A, B or Start) then lands on the menu window, whose busy screen has only Cancel: the menu said "Cancelled. Your
character was not changed" although the world held the character, and did not record that save as the character's latest
(seen in the Linux rehearsal). Fix (app `629ef51`): after a cancel, a save of this account that is new since the
registration began, of this trainer, means the character came in. Test: `tests/test_shell_app.py`, fails on the old code.

## 4. Create World, Solo, Host World and Join Friend on the installed build

`scripts/windows-runtime/ci_play_check.py` (new) plays an installed build as two players on one PC, both menus open, every
key posted to the window it is meant for, waiting for the screen it answers (the menu's opt-in screen log,
`EMERALD_SHELL_SCREEN_LOG`, `c2c38ea`):

1. host and friend: Characters > Create a new character: the game's New Game (A through Birch's speech, the name, the
   starter) until the game saved the trainer; close the game;
2. host: Solo > New world; the character enters it (the game opens, CONTINUE, it closes by itself: revision 1); the Solo
   game: CONTINUE, "Save now" (revision 2); close;
3. host: Host World > Create a new world (local network), copy the first friend's invite code, Host this world now: the
   character enters (revision 1), the hosted game: CONTINUE, Save now (revision 2); it stays open;
4. friend: Join Friend > Join with an invite code (the code typed in), Check and join: the friend's character enters the
   host's world over the connection (revision 1 in the host's world), the friend's game: CONTINUE, Save now (revision 2 in
   the host's world); close; then the host closes;
5. both characters' latest saves are the hosted world's; both menus Exit with code 0; no error recorded.

On a PC without 3D (the runner) every start first asks "3D graphics cannot start"; the check chooses Classic 2D.

| Run | Where | Result |
| --- | --- | --- |
| r6 (`--linux --loopback`) | Linux, the real menu (`--shell`) and real games, two X displays; hosted on "This PC only" (the cloud PC's only address, 192.0.2.2, is a documentation address invitations refuse) | **passed**: both New Games; Solo 1 -> 2; Host World 1 -> 2 (code copied, 127.0.0.1:7778); Join Friend 1 -> 2 in the host's world, "Connected to the host's world."; Exit 0 twice; no errors |
| installed check 39296878554 / 39298566536 (installer of run 39293623472, before MS-13) | Windows CI | **failed at Solo**: both New Games passed on Windows; the character could not enter the Solo world (MS-13) |
| installed check **39303520514**, play-check job (installer of windows-package run **39300939302**, `EmeraldTogether-Setup-EmeraldTogether-2026-10-19-session-fix-5.exe`) | Windows CI | **passed** (10 min 24 s): both menus open; "3D graphics cannot start" answered with Classic 2D (both players); both New Games (2 min 19 s each); Solo: World 1 on 127.0.0.1, entered (revision 1), Save now (1 -> 2), "Your world is running and your game is connected to it."; Host World: CI Hosted World on the runner's network address **10.1.0.44:7778**, invite code copied and decoded (slot 1), entered (1), Save now (1 -> 2); Join Friend: the code typed in, Check and join, the friend's character entered the host's world (1), the friend's game: Save now (1 -> 2 in the host's world), "Connected to the host's world."; both closed; both characters' latest saves are the hosted world's; Exit code 0 twice; no error recorded |
| windows-package run **#81** (`39305831099`), its own installation check (the delivered installer, `EmeraldTogether-Setup-EmeraldTogether-2026-10-19-session-fix-6.exe`) | Windows CI | **passed** (10 min 36 s): the same steps on a fresh runner (network address 10.1.0.11): Classic 2D chosen for both; both New Games; Solo: World 1 on 127.0.0.1, entered (1), Save now (1 -> 2); Host World: CI Hosted World on **10.1.0.11:7778**, invite code copied (slot 1), entered (1), Save now (1 -> 2); Join Friend: the code typed in, entered the host's world (1), Save now (1 -> 2), "Connected to the host's world."; both characters' latest saves are the hosted world's; Exit code 0 twice; no error recorded. Its Create World step passed too (default network 10.1.0.11:7777, invite code, rename, public address, delete, hosting up to the game, a restart), and the installed game logged `Multiplayer bridge: ... detail 1 ffa 1` |
| installed check 39303520514, world-check job (the same installer; and the crashed build 39180878911) | Windows CI | **passed**: the old build's crash reproduced; the new build over the old one's leftover data and on a fresh profile: Create World on the network address and with a public address, invite code, rename, delete, hosting up to the game (the 3D question answered with Classic 2D), restart with the worlds kept |

Create World is also covered by the installed world check (`ci_world_check.py`: on the default network and with a public
address, invite code, rename, delete, hosting up to the game opening, a restart; and the old build's crash reproduced).

## 5. The earlier session fixes, rechecked

| Fix | This round | Where | Result |
| --- | --- | --- | --- |
| Players through battles, menus and map changes; visibility; PLAYERS; leave and rejoin; mass outbreak | `native_session_persistence_proof.py` run session-4p-ffa, 4 games, engine `44b6ebea`, app `d34d473` | Linux | **passed**: all four linked, each game drawing the other three, PLAYERS "Connected: 4/4"; the mass outbreak (Route 102 marker in all four games) kept everyone; the host fought a wild battle out and won, a friend ran, then **two friends battled at the same time**: PLAYERS "<name> - In battle" each time, everyone back on the field in the same sessions (10-13); a player on another map listed, page "Field: LITTLEROOT TOWN"; a close: "Connected: 3/4"; rejoin: "Connected: 4/4"; store integrity |
| The free-for-all keeps everybody (this round's MS-11) | ffa-2 | Linux | passed |
| After the free-for-all everyone closes and comes back (fresh Continue) on the same canonical saves | ffa-2 | Linux | passed |
| Lucky Trade's record (MS-10) | `test_mp_bridge` `trade_record_carries_the_lucky_bit` | Simulated | passes (6 failures on the old validator). **No real Lucky Trade can run in this release**: Lucky Trades are decided only on the trade-effect path (its manifest opt-ins, a world created with a trade-effect policy, the native trade replay worker), and the package's manifest is generated without them ("effects 0/0/0" in every game log). |

## 6. Suites and CI

| Suite | Where | Result |
| --- | --- | --- |
| App suite (`pytest`, xvfb), app `d34d473` working tree | Linux | **2331 passed, 1 failed, 2 skipped** (809 s). The failure, `test_launcher_menu.py::...worlds_are_listed...` (the classic launcher's Host button disabled), is this cloud PC's: it failed the same way before today's changes (this session's earlier run: 2314 passed, the same 1 failed; run alone on the unchanged default `30dffa7` here: the same failure) and passes on GitHub's runner |
| `python-tests` (GitHub, Ubuntu) | CI | success on every push of this round, up to `3036be2` (runs 152-162) |
| Engine `make -f Makefile_pc NATIVE_LINUX=1 check-native check-abi` on `44b6ebea` | Linux | **0 failures** in every suite: 1067, 4393 (the bridge, `test_mp_bridge`), 307, 22148, 28215, 8694, 15 and 176 (the free-for-all) checks; ABI layout parity OK (172 types); the pictures decode |
| Engine self-tests on `44b6ebea` (`check-rival check-mp-objects check-spawn-claims check-pokenav-map check-game-sections`) | Linux | 0 failures: 31, 21, 23 and 8 checks; game sections: 528 global variables checked |
| Engine renderer checks on `44b6ebea` (`DIORAMA=1 check-diorama`) | Linux | exit 0: every suite passed (camera 403 checks, far field 54618, props 7991, battle stage, UI overlay, rules and more); compositor goldens: 18318 metatiles, 75 tilesets; "diorama rules are valid" |
| GBA ROM | Linux | `pokedev.gba` sha256 `f214735b64e113fd10730eacca5764d757f2c93a3685230aa905af7a7cdd3387`, unchanged |
| windows-package (full), engine `44b6ebea`, app `7259c9f` | Windows CI | run 39300939302 (#79): success, superseded by #81 (engine build with the manifest check, package, silent install / start / repair / uninstall, installed world check) |
| **windows-package (full), engine `44b6ebea`, app `691a162`: the delivered installer** | Windows CI | run **39305831099 (#81): success**. ROM pin `f214735b...3387`; "PC-only markers in the manifest: ['battle_ffa_abi_version', 'rival_abi_version', 'presence_detail_abi_version']"; the packaged 3D and Classic 2D games are the engine job's build; graphics checks 16 of 16; in-game menu check; installer `EmeraldTogether-Setup-EmeraldTogether-2026-10-19-session-fix-6.exe`, 57,617,861 bytes, SHA-256 `797688b1b698a16184cb83ffe55622e5d29c2febcd55a9b26a66c9bc8badc1c9` (artifact `EmeraldTogether-Windows-Installer`, ID 12213904832, zip digest `b7691465...92ecf3`, unsigned, kept 7 days); silent install / start / repair / uninstall; Create World; the play check (section 4). Report: artifact `EmeraldTogether-installer-check-full` 12213814881 |
| windows-package push run #80 (smoke) | Windows CI | success |

## 7. What was not run

* Nothing on physical PCs, a home network, the Internet relay or a GPU (the Windows runner renders in software, so the games
  ran in Classic 2D there; the 3D game ran nowhere with multiplayer this round).
* The free-for-all ran on Linux only: not under Wine and not on the Windows runner (one runner cannot run four games and their
  input, and its play check covers Solo, Host and Join). On Windows the free-for-all was not even offered before `fc41598`.
* A free-for-all draw (outcome 5) in a real run; a free-for-all in the 3D build.
* Two PvP battles at the same time: the session proof ran two wild battles at once; two simultaneous player battles were not run.
* A real Lucky Trade (unreachable in this release, above).

## 8. On two or four PCs

Install `EmeraldTogether-Setup-EmeraldTogether-2026-10-19-session-fix-6.exe` (run #81) on each PC; the installers before run #79 have MS-13.

1. Host World, create a world, Host this world now; give each friend their invite code; each friend: Join Friend, Join with
   an invite code, paste, Check and join. Each game shows the others.
2. Everyone: PLAYERS shows "Connected: 4/4". The host: PLAYERS > Challenges > Free-for-all 1v1v1v1. Each friend: PLAYERS >
   Pending challenge > Accept challenge. Everyone: Enter battle.
3. Fight to the end. Expected: one winner, three losers, everyone back on the field where they stood, PLAYERS still 4/4.
4. During any battle, do not close a game: the others stay connected but are held in the battle, and nobody in it can open
   that world again (section 2).
