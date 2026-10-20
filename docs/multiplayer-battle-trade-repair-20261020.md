# Multiplayer battle, trading and performance repair (2026-10-20)

The owner's report from two Windows PCs: after a 1v1 rival battle was accepted and both players chose Enter battle,
**both** games stayed on "Waiting for server..." for good (title "1v1 challenge", the two trainers greyed, Cancel
challenge, Enter battle, Championship); a trade stalled; lag spikes around interactions; battle background effects
froze. Branches: app `claude/admiring-bohr-dpxzuy`, engine `claude/mp-battle-trade-engine` (from the merged defaults:
app `2e6fe36`, engine `44b6ebea`). Nothing is merged.

Test environments are named as in `TEST_LEDGER.md`: **L** cloud Linux (native Linux games, software OpenGL, the real
launcher, companions and host in one harness process), **W** Wine, **CI** the Windows runner, **PC** the owner's PCs.
Nothing here ran on PC hardware.

## 1. What both games were waiting for (root causes)

### 1.1 The Enter battle latch had no failure exit

Choosing the challenge's admission row ("Enter battle") **latches** the native window (`multiplayer_menu.c`): input
and B are ignored, the window never closes, soft reset is off, and it shows "Waiting for server..." until the
companion's **ADMIT** moves the field into the battle hold (`MultiplayerMenu_TransferBattleAdmission`), which closes
the window. A window still showing "Waiting for server..." over Cancel challenge / Enter battle therefore means ADMIT
was never sent.

Between the Enter and ADMIT the companion makes several checks (`launcher_session._native_menu_capture_battle`,
`battle_admission_session.publish_battle_admission` / `prepare_battle_admission`). Any refusal there:

- sent nothing to the game (`MenuSession._send` refuses while latched), so the window waited for good;
- was turned into a session-wide save failure (`_native_menu_abandon_battle_preparation` sets `_save_failed`), so
  saving stopped and every later Enter and trade was refused the same way;
- logged nothing.

The checks that refuse: a save failure that stays set (`_save_failed`: a failed autosave or host-loss arm, a failed
trade), a leftover trade or export record (`pending-trade.json`, `pending-export.json`: `character_recovery_pending`),
a changed binding after a reconnect, a revision that no longer matches the challenge's pinned checkpoint, a busy save.

**Reproduced on the deployed code (L, real launcher, companions, host and two native games,
`native_launcher_challenge_proof.py`):** `save-failed` (the friend's launcher holds the failed-save state a real
network can leave; run repro-ch-failed-1): the friend's window stayed latched on "1v1 challenge / All players accepted
/ Waiting for server..." for the whole watch (`battle_recovery_held`, `save_failed`, `admission_failed`); the host's
ADMIT went through and its game sat held, waiting for a friend who could never come.

**Why both PCs:** the refusing conditions are per player; both players' windows stay latched when both companions
refuse. A stalled trade involves both players and leaves both with the refusing state (a failed trade sets
`_save_failed`; a trade record left at an intermediate phase is `character_recovery_pending`), so every later
Enter of both players latched. That chain is shown in code and by the reproduction of each link (a failed save on one
player: repro-ch-failed-1); which exact condition each of the owner's PCs held is not known (nothing was logged, and
the PCs' private data was not available).

### 1.2 A challenge that ended before its battle left the entered player held

When a challenge became `recovery_required` before any BIND (its 180 s time limit after the last acceptance, once one
player had entered), the host's execution room stayed `waiting` (`battle_execution.exchange` answered the room's
state), so the entered game's battle session polled `waiting` for good, frozen with no window. Reproduced:
late-enter (L, repro-ch-late-1: the host entered, the friend entered 200 s later): the friend's claim was refused, the
companion still sent ADMIT (it does so on any claim error, meant for a lost reply), and both games ended frozen with no
message.

### 1.3 A save after accepting silently ended the challenge

A save of either player after the invitation changes the checkpoint pinned by the challenge; the host aborts the
challenge (`canonical_changed`), and it vanished from both menus without a word (L, repro-ch-save-5). Autosave runs on
the field every 5 minutes on real installations (the harness had it off), so a player who leaves PLAYERS after
accepting can hit this.

### 1.4 Trades: the happy path works; the failure paths stranded the players

A complete trade through the real launcher path (L, repro-trade-1): both chose a Pokemon and confirmed; both applied
at revision 3 about 40 s after the confirmations (the frozen-field import), no journal left. A player walking while
PLAYERS closes for the trade did not break it (repro-trade-walk-1; B then cancelled cleanly and the 1v1 that followed
played to its result). The failure exits (traced from code; `docs` of the trade agent report are summarised here):

- a refused open or decline closed the menu without showing why (the proposal could stay open for the other player);
- any failure after the trade window opened (a stale offer at Confirm, a lost reply, the window's 10 s watchdog) left
  the field frozen and saving disabled until a restart; nothing told the game;
- a failure before the ROM hold left the proposal open, the other player waiting.

The server side is atomic (both post-images, the ownership transfer and both recovery rows in one SQLite transaction)
and was not changed.

### 1.5 The 3D battle background froze

`gl_battle.c` spaces the background tile redraws (water, flowers, sea air) by measured frame time. After a few slow
redraw frames the step went past 32 game frames and became 0; with no redraw there was no new measurement, so the
background stood still for the rest of the battle. One hitch (a save, the bridge, a window drag) was enough, and a
single slow frame was counted again in every following decision. Classic 2D has no ambient battle background
animation (`battle_bg.c` loads the background once and creates no task), so nothing there can freeze.

## 2. Fixes

| Area | Change | Commit |
| --- | --- | --- |
| Engine (PC only, GBA ROM unchanged) | A refused Enter releases its window: screen flags 3, taken only while latched, only for the very Enter request and only while no battle or admission-cleanup hold exists; marker `gMultiplayerMenuReleaseAbiVersion`, bridge capability `menuRelease` | engine `1afd495c` |
| Engine (PC only) | 3D battle tiles: standing water is tried again (2 s, doubling to 64 s), each step change starts a fresh measurement | engine `be8b28ab` |
| Launcher | Every Enter check runs before anything is written; a refusal is `BattleAdmissionRefused`, never a save failure; PLAYERS asks the launcher before it offers Enter | app `af77426` |
| Companion | A claim the host definitely refused sends no ADMIT; its intent is retired as a refused record | app `af77426` |
| Menu | The latched window gets the release with the reason; its rows work again | app `af77426` |
| Host | A challenge ended before any BIND answers the waiting core `recovery_required`; a trainer who has not entered may cancel a challenge another trainer entered | app `9b14cb3` |
| Launcher | An admitted entry whose battle ended unstarted is cancelled neutrally by the launcher itself (`cancel_admission`) | app `9b14cb3` |
| Trades | A failed trade is settled in the same session (the host's answer decides: applied or aborted); one that never held cancels its proposal; refusals are shown | app `91760bd` |
| Trades (engine PC only, app) | The received save goes to the PC game a 4 KiB sector per command (WRITE_WINDOW, opcode 30, frame 'i'), not 1024 WRITEs of 128 bytes; marker `gMultiplayerSaveImportWindowAbiVersion`, bridge capability `saveImportWindow`; the GBA ROM is unchanged | engine `c76651ea`, app `4c96fe2` |
| PLAYERS | "Rival Battle - 1v1", "Rival Battle - 2v2", "Free-for-All - 4 Players", "Trading", "Championship"; statuses Waiting for opponent, Opponent accepted, Waiting for remaining players, All players ready, Starting battle, Connection interrupted, Challenge cancelled (with why) | app `af77426` |


## 3. Regression tests (simulated: real codecs and coordinators, fake games or transports)

- Both players waiting for the server at once (`tests/test_menu_session.py` `BothPlayersEnterTests`): both enter and
  both battle; both are refused and both windows are released with the reason; one is refused while the other's
  battle ends unstarted (the entered player is told and freed). None of them can end waiting. They fail on the old
  code (the refused window never got a screen).
- `AdmissionReleaseTests` (the release screen only for the very Enter, only while latched, never with a battle hold),
  `tests/test_menu_mailbox.py` `MenuReleaseTests`, the bridge's `menu_release_screen_needs_its_capability`.
- The companion sends no ADMIT for a claim the host definitely refused and retires its intent; an older game is held
  as before (`tests/test_battle_recovery_session.py`).
- The host answers a waiting core `recovery_required` when the challenge ended before BIND
  (`tests/test_battle_execution.py`); a trainer who has not entered may cancel a challenge another entered
  (`tests/test_battle_entry_refusal.py`).
- PLAYERS: labels, statuses, the Enter precheck, "Connection interrupted", cancel reasons
  (`tests/test_player_menu.py`, `tests/test_rival_menu.py`).
- Trades: settled by the host's answer, applied or aborted, a never-held proposal cancelled
  (`tests/test_trade_settlement.py`); the import window: codec, the companion's 'i' frame on a real socket, a whole
  trade through the fake ROM (32 sectors, same post-image), a lost sector reply restaged
  (`tests/test_save_mailbox.py`, `tests/test_companion_live.py`, `tests/test_live_trade.py`, `tests/test_save_window.py`);
  the bridge's `save_import_window_needs_its_capability` (refused without the marker, sector then command with it,
  a bad CRC, a misaligned sector and a plain 'C' refused).
- 3D tile pace: `tests/diorama/test_battle_tile_pace.c` (`make -f Makefile_pc DIORAMA=1 check-diorama`).
- Engine `check-native`: 8 suites, 0 failures (`test_mp_bridge` 4422 checks). The GBA ROM rebuilt with every engine
  change: SHA-256 `f214735b...3387`, unchanged.
- App suite (`pytest`, xvfb): exit 0 before the import window (L); `python-tests` CI run 183 on `4c96fe2`: success.

## 4. Real games through the real launcher (L)

Two or four native Linux games, each with its own launcher, companion and the host's world server, driven through
PLAYERS as players do it (`scripts/multiplayer/native_launcher_challenge_proof.py`, `native_launcher_abandon_proof.py`).

| Run | Build | What | Result |
| --- | --- | --- | --- |
| repro-ch-failed-1 | deployed code | friend's launcher in the failed-save state; both Enter | **reproduced**: the friend's window latched on "Waiting for server..." for the whole watch; the host held |
| repro-ch-late-1 | deployed code | host enters, friend enters 200 s later | **reproduced**: both games frozen, no message |
| repro-ch-save-5 | deployed code | friend saves after accepting | **reproduced**: the challenge vanished from both menus |
| repro-trade-1, repro-trade-walk-1 | deployed code | a full trade; a player walking while PLAYERS closes | trade applied (about 40 s after the confirmations, frozen field); the walk did not break it |
| fixed-ch-both-1 | engine `1afd495c`, app `9b14cb3` | both Enter | passed: 1v1 to its result, both back on the field, fresh Continue |
| fixed-ch-failed-2 | same | the friend refused (failed save) | passed: the friend's window released with "Saving stopped: restart game", the friend cancelled, the host's launcher cancelled its entry by itself, both free, store integrity passed |
| win-trade-perf-1 | engine `c76651ea`, app `4c96fe2` | a full trade, measured | passed: both applied at revision 3 about 5 s after the second confirmation; closing saves and fresh Continue |
| win-enter-perf-1 | same | both Enter, measured | **failed in the proof, not the game**: the battle bound before the proof's first look and the proof read hold 0 as "not running" (the journals show both games executing); proof fixed (MS-27) |
| win-enter-perf-2 | same | both Enter, measured | passed: 1v1 to its result in 100 s, both back on the field, closing saves |
| win-late-1 | same | host enters, friend enters 200 s later | passed: the friend's window released with "Challenge expired: try again", the host's launcher cancelled its own entry (its game idle, not held), both free, saves and fresh Continue |

## 5. Lag: measured before and after

`scripts/multiplayer/multiplayer_perf.py` (`--perf`): each game's frame counter read every 4 ms through /proc, a
10 ms heartbeat on every launcher's event loop with the blocking stack when it is late, every fsync, every companion
request and host handler timed, CPU per phase. Same harness, same saves, the cloud computer (4 cores, software
OpenGL, 2D games).

| Trade (two games) | Old game, 1024 WRITEs (base-trade-perf-1) | New game, 32 WRITE_WINDOW (win-trade-perf-1) |
| --- | --- | --- |
| Import commands per player | 1024, p50 32 ms | 32, p50 32 ms |
| Second confirmation to both applied | 38 s | about 5 s |
| Trade phase length / game CPU per player | 59.8 s / 8.2 s | 26.9 s / 3.9 s |
| Game frames | p50 16.5 ms, p99 33.5 ms, max 52 ms (both) | the same |

1v1 (win-enter-perf-2, new build): during the 100 s battle no game frame gap over 50 ms and no launcher loop late by
more than 50 ms; game frames p50 16.7 ms, p99 33.7 ms. The battle journals made 29,890 fsyncs in those 100 s (11.5 s
in total, at most 24 ms each); the earlier `m25-bench` measured the same writes on the Windows runner at 0.47 ms and
0.13 ms, so they are not shown to cost a player anything on Windows (a slow disk or heavy antivirus PC was not
measured).

Remaining loop blocks during a trade: synchronous save checks (`inspect_flash` about 12 ms, ownership about 5 ms per
call on this computer) at confirm, prepare and apply. The harness recorded 100-300 ms because all launchers share one
Python process there; on PCs each launcher is its own process. Not changed (MS-26).

What the owner felt as lag around interactions is, from these measurements, the frozen trade import (fixed) and the
frozen Enter battle window (fixed); nothing in the battle path showed a stall on this computer. Not measured on PCs.

## 6. Battle background animation (3D and 2D)

**3D (Diorama).** The same two-game 3D 1v1 through the launcher, once on the old game and once on the fixed one
(`native_launcher_battle_3d_proof.py --parties 1,1` beside `diorama_stall_check.py`: once the battle's glide is over,
both games are paused and resumed in bursts for 4 s, SIGSTOP 120 ms / SIGCONT 40 ms, like a busy PC, a save or a
window drag; then left alone). Same frame budget for both (`PKMN_DIORAMA_BATTLE_FRAME_BUDGET=33`, software OpenGL),
each game's `runtime.log` read afterwards (L, not a GPU):

| | Old game (tiles-old-4) | Fixed game, engine `be8b28ab` (tiles-new-1) |
| --- | --- | --- |
| After the hitches | step 2, 4, 8, 16, 32 game frames, then "water and flowers stand still" | the same steps, then "stand still" |
| Rest of the battle | stood still to the end, never measured again | tried again at intervals (each try measured); when frames recovered: 32, 16, 8, 4, 2, then "move at every change" |
| Battle length | 6,935 / 6,945 frames | 6,751 frames |
| Tile redraws in the whole battle | 8 and 9 | 405 |

The battle itself, its mechanics and its pictures are unchanged; only when the background redraws is decided
differently (`src/diorama/gl/battle_tile_pace.c`, unit test `tests/diorama/test_battle_tile_pace.c`).

**Classic 2D.** No ambient battle background animation exists: `battle_bg.c` loads the background once and creates
no task, so there is nothing that could freeze (code inspection; the 2D runs above played their battles normally).
Wild, trainer and network-delay cases in 3D share the same pacing code; only the 1v1 rival battle above was run.

## 7. Four players

Four native Linux games, four launchers and companions, the host's world server, all through PLAYERS (L). The
saves have one Pokemon each (the full-party 2v2 proof needs six-Pokemon saves and about 150 minutes; the
interrupted-battle proof plays the same 2v2 through PLAYERS with these saves).

| Run | What | Result |
| --- | --- | --- |
| win-multi-net-2 (`native_launcher_abandon_proof.py --scenario multi-network`) | 2v2 (host and Friend 1 against Friends 2 and 3); Friend 1's connection cut mid-battle; abandon; teams formed again; **2v2 rematch to its result** | **passed**, 51 checks: abandoned with no result (desk, room, reservation aborted), teams re-formed, rematch result after 456 s, everyone back on the field, saves, fresh Continue, store integrity. win-multi-net-1 had reached the rematch when a container restart ended it (no result counted) |
| win-pairs-1 (`--scenario pairs-crash`) | two 1v1s at once; one game killed in the second | **passed**, 46 checks: the other 1v1 finished normally (71 s), the killed player's battle abandoned, the player came back with the same character, 1v1 rematch to its result (123 s); MS-16 not regressed |
| win-ffa-host-1 (`--scenario ffa-host-crash`) | free-for-all; the host crashes mid-battle (game killed, connections cut); host restart | **passed**, 47 checks: the host's launcher wound down, the battle abandoned with no result, the host restarted and reopened the world, the others rejoined, 1v1 rematch to its result (127 s) |
| win-ch4-enter-1 (`native_launcher_challenge_proof.py`, four sources) | 1v1 between players 1 and 2 while players 3 and 4 stay connected on the field | **passed**: 1v1 result in 114 s, all four saved, fresh Continue |
| win-ch4-enter-3 | the same with players 3 and 4 **walking** the whole time | the 1v1 played to its result (121 s) while players 3 and 4 walked (about 90 steps each, 4 places each, never off the field); the closing check then failed on the proof's own assumption: player 3's Pokemon gained 1 friendship from the steps (70 -> 71, nothing else changed), which the check read as a changed party. The proof now compares only who is in a walker's party |
| win-ch4-enter-5 | the same, players 3 and 4 walking the whole time (proof fixed as above) | **passed**: 1v1 result in 118 s while players 3 and 4 walked 87 steps each (4 places each, never off the field); the walkers kept the same Pokemon; saves, fresh Continue |
| win-ch4-trade-3 | a trade between players 1 and 2 while players 3 and 4 walk | **passed**: both applied at revision 3 about 5.5 s after the second confirmation; walkers 26-27 steps; saves, fresh Continue |
| win-ffa-exit-1 (`--scenario ffa-exit`) | free-for-all, a game closed mid-battle, abandon, rejoin, **free-for-all rematch to its end** | **failed** in the rematch, about 17 minutes in: the host's own core's 600-frame command deadline expired while the three friends' cores had used 9-18 frames between the same two QUERY rounds; the host stopped the battle (`execution_interrupted`). This is MS-17 again (seen once before this repair, abandon-exit-1; abandon-exit-2 played the same rematch to its end in 1031 s). No launcher loop stalled over 1.5 s this time. Nobody was locked out; the battle can be abandoned (MS-16). Root cause still open |

**Not covered here:** three-player worlds (only two- and four-game runs), a complete free-for-all on this build (the
rematch above was interrupted), the 2v2 with full six-Pokemon parties, Windows (Wine or the runner) or PCs.

## 8. Windows build (CI, not a PC)

windows-package run #90 (39371001628), full, from app `4c96fe2` and engine `claude/mp-battle-trade-engine` =
`c76651ea`, version "Battle trade repair dev 20261020":
- the build step enforces the ROM pin `f214735b...3387` and checks every PC-only marker reaches the manifest; both
  passed;
- the packaged Windows game logs `... ffa 1 release 1 import 1` (both new capabilities);
- installed check on a fresh runner: install (160 files), start, repair, uninstall (player files kept); Create World,
  invite code, rename, delete, a restart; the play check: two profiles create a character each through New Game, Solo
  World 1 (revision 1 -> 2), Host World on the runner's LAN address 10.1.0.101:7778, Join Friend with the copied
  code, both saves reach the hosted world, no error in either profile. Classic 2D (the runner has no OpenGL 3.3).
- Installer: `EmeraldTogether-Setup-Battle-trade-repair-dev-20261020.exe`, artifact `EmeraldTogether-Windows-Installer`
  (id 12241877497, private to the repository, 7 days).

No battle, trade or four-player session ran on Windows (CI or Wine) or on a PC.

## 9. What is left for the owner's PCs

Nothing here ran on the owner's PCs. With the installer from windows-package run #90, on two to four PCs:

1. **Both Enter at once.** Rival Battle - 1v1, both accept, both choose Enter battle: the battle starts within a few
   seconds. If either PC shows "Waiting for server..." for more than about 20 s, note what each window says, then
   keep both PCs' newest `runtime.log` (each game launch folder under `%LOCALAPPDATA%\PokemonPrivate\launcher\launches\`) and the time.
2. **A refused Enter.** Make one player save right after accepting (Start > Save): the challenge shows "Cancelled: a
   party was saved" on both PCs and both can challenge again.
3. **Late Enter.** One player enters, the other waits more than 3 minutes: the waiting player's window says
   "Challenge expired: try again", the entered player is free again on the field.
4. **Trade.** Trading, pick one Pokemon each, confirm: both fields come back within a few seconds (it was about 40 s);
   check both parties and save. Then cancel one trade halfway (B in the trade window): both keep their Pokemon.
5. **2v2 and Free-for-All - 4 Players** with four PCs; one of them closes the game mid-battle: the others can abandon
   it (no result), the leaver rejoins, and a rematch plays to the end.
6. **3D battles** on a weaker PC: water and flowers in the battle background keep moving (they may move less often
   while the PC is busy, never stop for the rest of the battle).
7. While two players battle or trade, the other two walk around and open menus; nobody is disconnected.

## 10. Known issues

`KNOWN_ISSUES.md`, section "Battle, trade and lag repair": MS-19 to MS-25 fixed as above (MS-23's failure exits only
simulated), MS-26 measured and not changed, MS-27 fixed in the proof. Still open from before: **MS-17** (recurred in
win-ffa-exit-1, details there) and **MS-18** (by design).
