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
