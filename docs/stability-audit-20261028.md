# Stability audit: crashes, freezes, leaks and timeouts (2026-10-28)

Step 11 of the queue: long play and multiplayer looked at for crashes, freezes, memory that keeps growing and time
limits that end things they should not. What was run, what it found, the one fix (MS-165, app `ff3cafb`, for a later
build: the 2026-10-27 package has the old wait), and what is left.

Where each result comes from: **L** this Linux machine: real game processes (the Classic 2D test build unless said),
the real world server and real launchers (their sessions and companions) on one machine, the network between them the
loopback. Nothing here ran on Windows, on the owner's PCs or between two PCs. In these proofs the host (the world
server) and both players' launchers run in the proof's own process; the games are their own processes.

## 1. Memory over long play (leaks)

| Run | What | Result |
| --- | --- | --- |
| 12-town loop, 3D test build (2026-10-26) | one game, 15 rounds of 12 towns, 180 targets | memory flat: 288 to 290 MB in use from the first round to the last |
| Two players, 75 minutes, 2D | Route 117 to Mauville City and back, 298 map crossings each | each game's own memory flat (35.6 and 35.7 MB); the server and both companions 22.2 to 23.1 MB; relayed steps p99 64.6 ms, no growth |
| Two players, 44 minutes, 3D | the same walk, software OpenGL | each game 183.5 to 204.2 MB in every 5 minutes, no growth; the server and companions as in 2D |
| **Trades and battles, 6 rounds in one session** (`soak-6`, 14 minutes) | two new characters claim their starters, then 6 times: Rival Battle 1v1, a trade and a trade back | **passed**: 6 battles (44 to 53 s), 12 trades (8 to 9 s each), the saves from revision 2 to 26, closing saves, a fresh Continue, the store's integrity check. Each game's own memory 3.0 MB throughout (+60 KB), 3 threads, 6 open files. The proof's process (the host and both launchers) 73.6 to 90.4 MB: about 2.8 MB a round |
| The same with Python's allocation tracer (`soak-traced`, 4 rounds) | where that process's memory goes | **passed**; the growth is the host's record of each finished battle (its route journal, every command and answer decoded and in base64: about 1.4 MB a battle) and a cache of read save images (32 at most, `flash.py`, MS-161: about 4.5 MB when full). Both are bounded: the host keeps the last 64 finished battles (`battle_execution.py`), so the process should level off about 90 MB higher after 64 battles in a session. Not run that far (64 battles is about an hour and a half of battling); the bound is the code's |

So no memory grows without end in what was run. The cost of a long battling session on the host is the one above; a
smaller record of a finished battle (its journal is on disk) would lower it, and is not done.

## 2. Freezes: a player's launcher or game stopped in a trade or a battle

`scripts/multiplayer/native_launcher_newcomers_proof.py` (the trade and battle-trade scenarios: two new characters
claim their starters, then a trade and a trade back, after Rival Battle 1v1 with `battle-trade`) gained:

* `--rounds N`: the battle and both trades N times over in one session;
* `--sample-every SECONDS` (and `--trace-memory`): each game's and the proof process's memory, threads and open files
  to `samples.jsonl`;
* `--freeze KIND:PLAYER:STEP:SECONDS[:ROUND]`: a player's launcher session frozen (`worker`: its event loop runs
  nothing, so its companion neither reads nor writes, to the host or to its game) or its game stopped (`game`:
  SIGSTOP, then SIGCONT), once the first player confirmed a trade (`trade`) or 20 s into a battle (`battle`). A trade it
  ends must have changed nothing on either side; the proof then does what the launcher tells the player (Resolve
  interrupted trade, then close the game and open the character again, where the host dropped the player) and makes the
  trade again;
* `--game-answer-seconds`: the launcher's wait for its game's battle answers (MS-165: the old 5 s against the new 15 s).

Every run ends with the closing saves, a normal close of both games, a fresh Continue and the store's integrity check.

| Run | Frozen | Outcome | |
| --- | --- | --- | --- |
| f1b | the friend's launcher, 8 s, in a trade | the trade cancelled on both sides ("Trade cancelled. Your saved party is unchanged."), nothing traded; made again and back: **passed** | as designed: a game whose companion is silent 3 s closes its trade window |
| f3 | the friend's game, 15 s, in a trade | the same: cancelled on both sides, made again: **passed** | as designed |
| f2c | the friend's launcher, 30 s, in a trade | the host dropped the friend (its 20 s idle limit) and aborted the trade; the friend's launcher held it ("Trade interrupted ... Resolve interrupted trade"), disconnected. Resolve interrupted trade verified the trade's fate ("Trade fate and saved bytes verified"); the held game closed normally (exit 0) and the character opened again; nothing traded on either side; made again and back: **passed** | as designed (`docs/trade-service-loss-recovery.md`); the player has to resolve it |
| f4 | the friend's launcher, 15 s, in a battle | the battle went on after it and ended; both back with their parties; the trades after it: **passed** | |
| f6 | the host player's launcher, 30 s, in a battle | the host's battle route waits 20 s for each answer: the battle held for recovery for both (Recover battle, Abandon battle) | as designed |
| f5, f5c | the host player's game, 15 s and 10 s, in a battle (f5c with the old 5 s) | **the battle stopped for both** (held for recovery): MS-165, below | fixed |
| f5d | the same 10 s, with the fix | the battle to its end, both back with their parties, the trades after it: **passed** | |

## 3. MS-165: a game stopped for a few seconds stopped a battle (fixed, app `ff3cafb`)

A launcher waited 5 s for its game's answer to each host command of a battle (the companion's own default for the
game's battle mailbox), while the host's route waits 20 s for that answer. A game held up longer (in the test,
SIGSTOP; on a player's PC, a moment the game process does not run) answered after its launcher had given up; the
companion took the late answer for a protocol error ("invalid or uncorrelated diagnostic response") and closed the
game's local link, and the battle was held for recovery for both players. The launcher now gives its game 15 s
(`battle_session.py` `GAME_ANSWER_SECONDS`, under the host's 20 s). The same run both ways (`--game-answer-seconds 5`
is the old wait): a 10 s stop of the host player's game 20 s into Rival Battle 1v1 stopped the battle with 5 s and not
with 15 s. A stop of 15 s or more still holds the battle for recovery, as anything past the host's 20 s does. The app's
battle suites: 249 passed, 17 skipped; the lag lobby (a connection cut and rejoined, then the rival 1v1 with every
message 40 ms late, the CI's `nosave-lag`) passed with the fix.

## 4. The time limits these runs crossed

| Limit | Where | Past it |
| --- | --- | --- |
| 3 s | the game: its companion silent while its trade window is open | the window closes; the trade is cancelled for both |
| 15 s (5 s before MS-165) | the launcher: its game's answer to a battle command | the battle is held for recovery |
| 20 s | the host: a player's companion silent | the player is dropped; a trade in hand waits for Resolve interrupted trade, a battle is held for recovery |
| 20 s | the host's battle route: one player's answer | the battle is held for recovery |
| 45 s | the game: a held trade with no command | the game ends the trade |

## 5. Crashes

No run in this audit crashed or hung a game or a launcher: every game closed normally at the end (exit 0) and opened
again for the fresh Continue. Earlier in the audit: the wireless minigames with computer partners under
AddressSanitizer found two reads past their data (MS-163, fixed, engine `2fcee2ae`). MS-71 (the owner's crash in a
battle between two PCs) is still not reproduced; its diagnostics are in place.

## 6. Not covered

* Windows, the owner's PCs, two PCs, a real network: these trades and battles ran over the loopback (the rough link of
  `proof_network.py` was not used in them).
* What on a player's PC stops a game for seconds during a battle (a window held, a hang, sleep): not tried on Windows.
* A whole PC asleep, a game or launcher killed, the host's own process stopped; four players.
* The host's memory after 64 battles in a session (section 1: the bound is read from the code).

To run them again (the inputs as in the other Linux proofs: a short-introduction save per player, an X display per
player):

    python scripts/multiplayer/native_launcher_newcomers_proof.py --scenario battle-trade --no-save \
      --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \
      --source boy-1.sav --source girl-1.sav --display :94 --display :95 \
      --rounds 6 --sample-every 30 --output /private/multiplayer-proof/soak-6
    # a freeze: --freeze worker:1:trade:30, --freeze game:0:battle:10 (one per run)
