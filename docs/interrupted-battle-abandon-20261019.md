# Interrupted multiplayer battles no longer lock players out of their world (MS-16, 2026-10-19)

The owner's request: if a player disconnects, crashes, closes the game or loses the connection during a PvP, 2v2 or
four-player free-for-all battle, the others must not be stuck. Give them a clear way to abandon the interrupted battle
safely, with no winner, loser, reward, wager or progression change unless that result was already final. Restore every
participant's Pokemon, HP, PP, items and battle state to the last verified safe checkpoint, keeping unrelated progress.
Release stale battle reservations and locks. Let players close and reopen EmeraldTogether and return to their world
normally, and let the player who left rejoin with the same character. Prevent duplicate rewards, corrupted saves and
repeated result processing. Recover safely when the host restarts after a crash. Support 1v1, 2v2 and the free-for-all,
including several independent battles in one world. Reproduce the failure first, test with four real game processes
(crashes, intentional exits, reconnects, full application restarts), add regression tests, rebuild the Windows installer,
run CI, and do not merge.

Branches: app `claude/admiring-bohr-dpxzuy`, engine `claude/mp-session-engine` (no engine change was needed). The default
branches are unchanged (app `claude/emeraldtogether-combined-app` `30dffa7`, engine `claude/emeraldtogether-combined`
`47767264`).

Where each result comes from, in this document:

| Label | Meaning |
| --- | --- |
| **Simulated** | Unit tests and real servers/companions over TCP with a scripted game bridge; no game runs |
| **Linux** | The native Linux game (the same engine sources as the Windows game, built for Linux), the real launcher code, X displays, one cloud PC |
| **Wine** | The Windows game under Wine on the cloud PC (not run this round) |
| **Windows CI** | GitHub's hosted Windows Server 2022 runner (a VM without a graphics card): the real installer, installed and played there |
| **PC** | The owner's PCs. **Nothing in this document ran on a physical PC or a home network.** |

## 1. The failure, reproduced on the unchanged code (Linux, four games)

`scripts/multiplayer/native_launcher_abandon_proof.py` drives four native games through the whole launcher (real
`LauncherWindow`, `SessionWorker` and `LauncherSession` per player, production world creation and enrollment, the real
world server and store, ordinary key presses). On a build without the abandon option it records what the players get and
ends "MS-16 reproduced". Run from a worktree of the unchanged app `de821f0` (engine `44b6ebea`):

| Run | What happened |
| --- | --- |
| **repro-pairs-1**: two 1v1 battles at once (host vs Friend 1, Friend 2 vs Friend 3); Friend 3's game killed (SIGKILL) 60 s in | The other battle was not affected: it finished normally with a result (outcome 1, 92 s). Friend 2 stayed held in the battle for the whole 90 s watch (`battle_recovery_held`; the host's desk `recovery_required`, `execution_interrupted`), with only "Recover interrupted battle" on offer, which waits for all the original games. Friend 3's launcher could not open the world again. **MS-16 reproduced.** |
| **repro-host-2**: a free-for-all; the host's game killed and every host connection cut | The three friends were held and disconnected (`battle_recovery_held`, connected false, only recovery offered). The host's launcher could not open the world again, so nobody could. **MS-16 reproduced.** |
| ffa-leave-1 (the earlier round, app `d34d473`) | One friend closed the game the ordinary way during a free-for-all; the three others were held for 240 s, then the host's launcher refused the world (`pending_battle`). |

**Root cause.** The native battle recovery (`docs/native-battle-recovery.md`) is same-core: it waits for every original
game process, and it was the only way out of an interrupted battle. A game that crashed, closed or lost power never comes
back, so:

* the host's desk stays `recovery_required` (or `aborting` before the battle starts, waiting for an ABORT receipt from a
  core that is gone), and the recovery quorum can never complete;
* the host keeps the battle's durable reservation (`battle_reservations`), which bars every participant's character;
* every participant keeps a local battle intent (`pending-battle.json`, `pending-battle-admission.json`), which the
  launcher refuses at start (`pending_battle`);
* when the host was in the battle, closing its game ended the host's session and with it the world server.

## 2. The fix: abandon an interrupted battle with no result

The owner's decision: an interrupted battle can be abandoned; nobody wins. Policy and protocol are in
`docs/native-battle-recovery.md` ("Abandoning an interrupted battle"). In short:

* **Who and when.** Any participant of an interrupted battle can abandon it: a participant's connection changed, the desk
  or execution room is in recovery, the battle was aborting, or the host restarted and no longer has it in memory. A
  healthy battle is refused (`battle_still_running`). The other launchers do not have to do anything.
* **No result.** No winner or loser, no reward, no wager, no progression. A native battle never writes a save (RELEASE only
  restores the party the battle started with), so every participant continues from the canonical checkpoint the challenge
  pinned, their last verified save. Progress since that save is not kept, as with a vanilla link error.
* **A final result stands.** A battle whose reservation is `closed` keeps its result. If every participant's restored
  RELEASE is already in the host's route journal (the host crashed between journaling and publishing), the answer is
  `battle_result_final` and the existing recovery settles it.
* **Host, in order, each step idempotent and keyed by the battle ID** (`src/emerald_multiplayer/battle_abandonment.py`):
  write `native-battle-execution/<battle>.abandoned.json`; close the durable reservation as terminal `aborted` with that
  record's digest (every participant's barrier is released); cancel the consent (no late Enter or BIND); stop the live
  route and any recovery quorum; void a wager; archive the desk battle and post "BATTLE ABANDONED". A crash between steps
  is finished by the next request; other battles in the world are not touched. A late RELEASE cannot publish a result
  for an aborted reservation, and recovery refuses it. Championship, Frontier and rival checkpoints treat it as a match
  to play again.
* **Client** (`launcher_session.py`). The launcher keeps the host's answer and the bytes of the battle intents it retires in
  `<battle>.battle-abandoned.json`, then removes those intents. A game held in the battle is closed and started again in
  the same session: the world, the world server (for the host) and the player's other progress stay. A launcher that
  starts after a crash, a closed game, a full application restart or a host restart resolves the battle by itself before
  opening the world. A launcher still held follows an abandonment decided by someone else within about 2 s. A
  disconnected launcher reconnects to abandon.
* **UI.** While a battle is interrupted, the classic launcher shows "Abandon battle" and the EmeraldTogether menu's play
  screen "Abandon interrupted battle" ("nobody wins; your game restarts"). Both ask first: "The battle ends for everybody
  with no result: nobody wins or loses, and no wager or reward is paid. Your game restarts from your last save, with the
  party it had before the battle."
* **Protocol.** New battle-channel operations `abandon` and `fate` (`{battle_id, generation}`), advertised by `pending` with
  `abandon_version=1`. A host without them (an older build) or with battles turned off leaves the old `pending_battle`
  refusal.

Changed files: `battle_abandonment.py` (new), `battle_reservations.py`, `battle_desk.py`, `battle_execution.py`,
`battle_recovery.py`, `battle_protocol.py`, `battle_admission_host.py`, `server.py`, `companion.py`, `championship.py`,
`frontier_service.py`, `launcher_session.py`, `launcher_gui.py`, `shell_app.py`.

## 3. Four real games on the fixed code (Linux)

`native_launcher_abandon_proof.py`, app `cddfcda` code (the proof script at `20e4319`), engine `44b6ebea`, four native
Linux games on four X displays, each with its own real `LauncherWindow`/`SessionWorker`/`LauncherSession`, the real
world server and store. Every scenario ends with the harness's own checks: everyone back on the field and linked
("Connected: 4/4" on every PLAYERS tab), every party exactly the one from before the battle (count and SHA-256), no
battle intent or reservation left anywhere, the abandoned battle without a result, all four save (revision 1 -> 2) with
money, items, flags and variables unchanged, the store's integrity check, a normal close (exit 0) and a fresh Continue onto
the same saves. A watchdog thread recorded every launcher event-loop stall over 1.5 s (none in these four runs).

| Run | Interruption | What happened | Result |
| --- | --- | --- | --- |
| **abandon-pairs-2** | Two 1v1 battles at once; Friend 3's game **killed** (SIGKILL) 60 s in | The host and Friend 1's battle was not affected and finished with a result (outcome 2, 93 s). Friend 2 was held, offered "Abandon battle" at once, abandoned: its game closed and a new one opened in the same session on the field (`battle_abandoned`). Friend 3 **started the launcher again and opened the world with the same character**. The host: desk, room and reservation `aborted`, the abandonment record, no result, no wager. Friend 2 and Friend 3 then **battled each other again to the end** (outcome 2, 146 s). | **passed** (46 checks) |
| **abandon-multi-2** | A 2v2; Friend 1's world **connection cut** (its game kept running) | All four held; the three connected launchers and the disconnected one offered "Abandon battle" within 20 s. The host abandoned explicitly; **Friends 2 and 3 followed by themselves** (nobody touched their launchers); **Friend 1 reconnected to abandon**. Every game came back on the field; no result, no wager. The teams had ended with the members' connections (existing rule, below); the players teamed up again and **played the 2v2 again to the end** (outcome 2, 675 s). | **passed** (55 checks) |
| **abandon-exit-2** | A free-for-all; Friend 2's game **closed** the ordinary way (SIGTERM, which SDL turns into the same quit as closing the window; exit code 0) | Friend 2's launcher wound down. Friend 2 **started the launcher again: it abandoned the battle as it opened the world**; the host, Friend 1 and Friend 3 followed by themselves. No result, no free-for-all ranking, no wager. The four **played a free-for-all again to the end** (Friend 2 won, outcome 3, 1031 s). | **passed** (59 checks) |
| **abandon-ffa-2** | A free-for-all; the **host crashed**: its game killed and every connection of its server cut | The three friends were held and disconnected, each offered "Abandon battle". The host's launcher wound down (`save_recovery_required`). **The host started the launcher again and the world opened** with the host's own character; its launcher resolved the battle at start. Friends 1 and 2 abandoned (each reconnected to the restarted host); Friend 3 closed its held game and **started the launcher again**. The durable reservation `aborted` with its record, no result, no wager. The host and Friend 3 then **battled 1v1 to the end** (outcome 1, 154 s). | **passed** (47 checks) |

Earlier runs of the same scenarios, kept as recorded:

| Run | Result |
| --- | --- |
| abandon-pairs-1 | Every check up to the fresh Continue passed (abandon, rejoin, no result, rematch to the end, saves). Stopped at the fresh Continue: the proof's own display plumbing opened a game on another player's display (a reused thread ident); fixed in the proof (`b1a73ca`, `de2a465`). |
| abandon-multi-1 | Every abandonment check passed (host explicit, two friends automatic, the disconnected friend reconnected). Stopped at the rematch: the proof challenged with teams that had ended with the members' connections; the proof now teams up again (`e97ee69`). |
| abandon-ffa-1 | The host restart, the world reopening and two friends abandoning passed. Stopped when Friend 3's restarted game opened on another player's display (the proof's plumbing again; `de2a465`). |
| **abandon-exit-1** | Every abandonment check passed (the leaving player's restart resolved it, the other three followed, no result, parties as before). **The free-for-all rematch was then interrupted 15 minutes in**: the host's own game reported its held native deadline expired (600 frames, about 10 s, without a command; the other three cores had used 12-15 frames since their last command), so the host stopped the battle (`execution_interrupted`; every launcher `battle_recovery_held`, nobody disconnected, the battle could be abandoned or recovered). The host launcher's event loop (world server, battle router and the host's companion, all on one loop) stalled for about 10 s. The cause was not identified (KNOWN_ISSUES MS-17); abandon-exit-2 then passed with the stall watchdog and saw no stall over 1.5 s. |

## 4. Regression tests

`tests/test_battle_abandonment.py`, 26 tests (Simulated: real authenticated TCP servers, SQLite stores and companions,
scripted native responses; the launcher tests use a stand-in companion and a real child process for the game):

* protocol: bounded `abandon`/`fate` requests and answers; the capability query and reply;
* a result is final only when every restored RELEASE is in the journal tail;
* local retirement keeps the host's answer and the exact intent bytes, then removes only that battle's intents; another
  battle's intents and an unresolved answer retire nothing;
* network: a player who leaves a running 1v1 no longer strands the other and can join again; a late RELEASE or a replay
  cannot publish a result after abandonment; a running battle that nobody left is refused; a finished battle keeps its
  result; a bound battle whose player left before the start is abandoned instead of held `aborting`; a wager is
  cancelled and nobody pays; two battles at once, only the interrupted one is abandoned; 2v2 and free-for-all
  reservations are abandoned for all four; **after a host restart** the durable reservation is abandoned; **a host crash
  between the record and the reservation is finished by the next request**; the capability answer;
* launcher: a cold start resolves the battle its lost game was in, and a reservation without a local intent; an
  unresolved answer or an older host leaves the intent (`pending_battle` as before); the held game is closed only after
  the host has abandoned the battle; a refusal keeps the game and the intent; a disconnected held game reconnects to
  abandon; a healthy session offers no abandonment; an abandonment decided elsewhere is followed; an unresolved battle is
  left to the player; the next game starts with fresh state and the world connection back.

On the unchanged code these tests cannot run (no `abandon`/`fate` operation, no module); the failure itself was
reproduced with four games (section 1). `tests/test_battle_protocol.py` covers the new operations in its request/reply
tables.

## 5. Suites and CI

| Suite | Where | Result |
| --- | --- | --- |
| App suite (`pytest`, xvfb), app `20e4319` (fix code `cddfcda`) | Linux | **exit 0: 2,360 test cases (5,091 with subtests), 0 failed, 0 errors, 2 skipped**, 775.7 s (JUnit report `mp/app-suite-3.xml`). The launcher-menu Host-button test that failed on this cloud PC in the previous round passed this time |
| `tests/test_battle_abandonment.py` (26) with the protocol and admission tests | Simulated | 47 passed |
| 21 related modules (execution, recovery, desk, reservations, launcher recovery and session, championship recovery and network, challenge network, companion battle, ffa/multi desk, native resume, admission, admission cleanup, frontier, rival checkpoints and server, wagers, launcher GUI, shell app) | Simulated | 405 passed |
| `python-tests` (GitHub, Ubuntu) | CI | runs 164-166, 169 and 170: success. **Runs 167, 168 and 171 failed** on one of the new tests, `test_two_battles_at_once_only_the_interrupted_one_is_abandoned` ("native mutation sequence changed"): a race in the test's own synthetic cores, not in the app. A core could answer a command just as a drive stopped, and the next drive re-applied the same command, where a real core answers an exact retry from its cached response. Reproduced here: 8 of 40 runs of the old test failed; the test now keeps each core's last answer across drives: 0 of 40, and the abandonment and protocol files 43/43 three times. The run for that test fix (`f8f67e6`): run 172 (39346095347): success; run 173 (`ee21c72`): success |
| GBA ROM | Windows CI (engine job) | `f214735b64e113fd10730eacca5764d757f2c93a3685230aa905af7a7cdd3387`, the pin; no engine change in this fix |
| **windows-package (full), engine `claude/mp-session-engine` `44b6ebea`, app `20e4319`** | Windows CI | run **39337084682 (#83): success**. Manifest: "PC-only markers in the manifest: ['battle_ffa_abi_version', 'rival_abi_version', 'presence_detail_abi_version']"; the packaged 3D and Classic 2D games are the engine job's build (SHA-256 `131232e9...474f` and `fcd23f9b...a558`); graphics checks 16 of 16 (3D unsupported on the runner, Classic 2D passes); in-game menu check, no failures. Installer **`EmeraldTogether-Setup-EmeraldTogether-2026-10-19-session-fix-7.exe`, 57,644,983 bytes, SHA-256 `141da7fb99191fc5363e4f069d5d0e07034be9e777827b5b7c379ae2f009a3a8`** (artifact `EmeraldTogether-Windows-Installer`, ID 12227782501, zip digest `b19de5ce...6f70`, unsigned, kept 7 days). Installation check: silent install (160 files), start (20 s, menu up), repair, uninstall (player files kept); Create World (10.1.0.118:7777, invite code decoded, rename, public address, delete, hosting started the game, whose log reads `detail 1 ffa 1`, restart); the play check: two New Games, Solo 1 -> 2, Host World on 10.1.0.118:7778 1 -> 2, Join Friend with the typed invite code 1 -> 2 ("Connected to the host's world"), both Exit code 0, no error in either profile. Report: artifact `EmeraldTogether-installer-check-full` 12228610944 |
| windows-package push run #82 (smoke) on `9b39d71` | Windows CI | success |

The Windows runner cannot run a four-player battle, so the interrupted-battle flow itself has Linux evidence only
(section 3).

## 6. Limits and what was not run

* **Nothing ran on physical PCs, a home network, the Internet relay or a GPU.** The four-game proofs ran on one cloud PC
  (Linux, four X displays, all four launchers in one harness process); the Windows runner cannot run a four-player battle,
  so the abandon flow was **not run on Windows** (CI or Wine). The Windows evidence is the installer build and its
  installed checks (Create World, Solo, Host World, Join Friend), which exercise the changed launcher code paths at start
  but not an interrupted battle.
* Not run with the 3D build, with a wager actually staked in a real game (simulated only), in a Championship or Frontier
  match (simulated only), or with a co-op (two players against the AI) battle.
* **Unsaved progress.** Abandoning restarts the game from the player's last save (the checkpoint the challenge pinned,
  the last verified safe checkpoint). Field progress made after that save and before the battle is not kept, as with a
  vanilla link error: the game is held inside the native battle, and the engine has no command that returns it to the
  field without a battle result (RELEASE needs one), so that progress cannot be read back safely. Saving before a
  challenge keeps it. Keeping it automatically would need a new PC-only native "restore the pre-battle field" command
  (engine, bridge and ABI change); not done in this fix. Everything durable is kept: other characters, the world, other
  battles, earlier saves.
* **A result journaled but not published.** If the host crashes in the moment after every participant's RELEASE is
  journaled but before the result is published, the battle is answered `battle_result_final` and still needs the original
  games (the existing recovery); this window was not reproduced in a real run.
* **Teams.** Every restarted game comes back on a new world session and a team ends when a member's connection changes
  (`team_desk.py`, unchanged), so 2v2 partners form their team again after an abandoned battle (MS-18).
* **An older host** (or battles turned off) cannot abandon; the launcher says so and keeps the old `pending_battle`
  refusal. Every player in a world needs this build.
* **MS-17**: the one host event-loop stall seen (abandon-exit-1) interrupted a healthy battle; the players were not
  locked out (it could be abandoned), but its cause is unknown.

## 7. On two or four PCs

Install `EmeraldTogether-Setup-EmeraldTogether-2026-10-19-session-fix-7.exe` (run #83) on every PC.

1. Host World, Host this world now; each friend: Join Friend with their invite code. PLAYERS shows everyone.
2. Start a battle (PLAYERS > a player > Challenge 1v1, or Challenges > Free-for-all, or a 2v2 between two teams). During
   the battle, close one player's game (or pull their network cable, or end the process in Task Manager).
3. Expected: the others are held in the battle and the launcher offers **Abandon battle** (in these tests at once to about
   20 s after the interruption; the
   EmeraldTogether menu: **Abandon interrupted battle**). One of them confirms; every remaining player's game restarts on
   the field where they last saved, with their party as it was; nobody wins or loses.
4. The player who left starts EmeraldTogether again, Join Friend (or Continue): they open the world with the same
   character. Everyone can challenge again.
5. The same with the host's game closed: the host starts EmeraldTogether again and hosts the same world; the others
   abandon (their launchers reconnect) and play on.

If any step fails, keep each player's `runtime.log` and the host's `native-battle-execution` folder.
