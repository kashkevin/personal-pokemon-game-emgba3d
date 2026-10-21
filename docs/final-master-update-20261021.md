# Final master update: audit, plan and release gates (started 2026-10-21)

The owner's queued "final master update" (19 phases): finish the requested features, find every implemented system,
test it with accelerated test-only tools, run real Windows game processes on GitHub's runners, fix what breaks, then
merge both repositories and certify a Windows installer once the mandatory gates pass. This file is the plan (phase 1)
and becomes the final report (phase 19). **Nothing is merged yet.**

Test environments as in `TEST_LEDGER.md`: **T** the engine's GBA test ROM, **L** cloud Linux (real native games,
software OpenGL, the real launcher, companions and host; "several PCs" are several games on one machine), **W** Wine,
**CI** the GitHub-hosted Windows runner (real Windows processes, no GPU: Windows' software renderer has no OpenGL 3.3, so
only the Classic 2D game runs there), **PC** the owner's PCs (never used: the owner asked not to need them).

## 1. Audit (phase 1, 2026-10-21)

### 1.1 Repositories

| | Default branch (HEAD) | Candidate | Ahead | Fast-forward |
| --- | --- | --- | --- | --- |
| App `kashkevin/personal-pokemon-game-emgba3d` | `claude/emeraldtogether-combined-app` at `2e6fe36` (the merge of 2026-10-20) | `claude/admiring-bohr-dpxzuy` | 23 commits: the battle, trade and lag repair (`a4aaa5e`-`df06949`) and Update 32 (`66b0049`-) | yes |
| Engine `kashkevin/personal-pokemon-game-emgba3d-engine` | `claude/emeraldtogether-combined` at `44b6ebea` | `claude/feature-update-engine` | 19 commits: the repair's `be8b28ab`, `1afd495c`, `c76651ea` and Update 32's 16 | yes |

Neither the repair nor Update 32 is merged (the owner's rule: no merge before the tests pass and, for the repair, the
owner's approval; this update carries the owner's authorization to merge when its gates pass, phase 18). The other
remote branches are earlier updates already contained in the defaults or abandoned lines; nothing else is in flight.

App and engine revisions are paired: each engine marker the Windows game exports (`gMultiplayer*AbiVersion`) must be in
the manifest the app generates, which the Windows package job asserts; the candidate pair passed it (windows-package
runs 97 and 99).

### 1.2 Workflows and test infrastructure

| Layer | What exists | Last result on the candidate |
| --- | --- | --- |
| App unit/integration suite | `pytest` (203 files, about 4,900 tests with parameters; xvfb), CI `python-tests` on every push | green (runs 190-192; docs-only pushes since) |
| Engine GBA test ROM | `make check`: 6,074 tests (the battle engine's mechanics, the multiplayer channel, the free-for-all rules, Mega Evolution, daycare, eggs) | 5,571 passed; the same 39 known failures as before Update 32 (Gen 9 rule tests, G10) |
| Engine native self-tests | `--selftest-*` (shiny, breeding, coins, Update 29/30/32 economy and rolls) | passed (TEST_LEDGER) |
| Engine field checks (L) | `tools/pc_port/*_check.py` (17: intro, soft reset, rivals, saves, dialogue, party menu, battle end, ...) | passed (TEST_LEDGER) |
| Test-build drivers (L and CI) | the battle test driver (`include/diorama/battle_env_test.h`, test builds only): warps, battles by kind, field keys, soft resets, game-side logs; `mega_check.py`, `feature_check.py`, Battle FX and battle-environment surveys | Mega 110/110 + 97/97 and the starter check passed on the runner (runs 97, 99) |
| Real-game multiplayer proofs (L) | `scripts/multiplayer/*proof*.py` (42): 1v1, 1v1v1, 1v1v1v1, 2v2, lobbies, trades, three and four players, abandon and recovery, perf | every Update 32 format passed (TEST_LEDGER) |
| Windows (CI) | `windows-package` (full): build, package, frozen launcher, graphics mode, in-game menu, silent install/repair/uninstall, Create World, the installed build's play check (two characters, Solo, Host World, Join Friend), the Mega check, the starter check; `installed-world-check`; `m25-bench` | green on run 97/99 |

### 1.3 Known issues (KNOWN_ISSUES.md), open and at least Medium

- **MS-17 High, release-blocking**: a healthy native battle interrupted when the host's own core missed its 600-frame
  deadline (twice on four games, free-for-all rematches after a player closed their game, 15-17 minutes in; the second
  time no launcher loop stalled). Cause not identified. **No merge while it is open** (owner, 2026-10-20).
- G1 (a post-Gen-6 move blocks a trade evolution's move choice), G2 (a cited balance document is missing), G3 (a World
  Event claim can still double after a long disconnect), MS-28 (players of a world need the same version), MS-38 (Mega
  Lucario Z's Ability does nothing), NU-7 (credential rotation design), U31-1 (a compatibility fixture to regenerate).
- Owner decisions recorded, not defects: MS-39 (Mega Rayquaza unreachable), MS-42 (egg cycle 32 steps), G8, G13.

### 1.4 Phases 2-8 (features): already built in Update 32

Phases 2-8 repeat the features of the queued feature update, which are implemented and tested
(`docs/update-32-features-20261020.md`). Per the request ("inspect and verify those changes rather than implementing
them again") they are verified, and the gaps below are closed with tests, not rebuilt:

| Phase | Built | Verified so far | Gaps to close |
| --- | --- | --- | --- |
| 2 Character creation | short introduction (engine `37f4edaf`) | L intro32_check 9/9; CI run 99 | existing saves keep progress (save compatibility suite: re-run on the candidate) |
| 3 Zero-Pokemon characters | engine `1b8af913`, app `66b0049` | L newcomer-4 (two), three-4 (one of three); CI run 99 | four players with mixed parties; one player alone through host/join/reconnect |
| 4 Starters in the lab | engine `37f4edaf` | L intro32_check, newcomer-4 (two claims at once); CI run 99 | claims by three or four players at once; no second claim after trading the starter away; the Route 101 event never fires for a lab character |
| 5 Soft reset, shiny hunting | engine `09ee5144`, `91d856fb`, app `9397a61` | L soft_reset_check, soft-reset-7 (in a world), selftest 400,000 claims; CI run 99 (offline) | refusals during a battle or a trade in a world; repeated resets in a world with others playing |
| 6 Player visibility | engine `1b8af913` | L three-4 (START, bag, party, PLAYERS) | Pokedex, trainer card, options, a shop, a dialogue; four clients |
| 7 Battles, trades, lag, backgrounds | the repair + Update 32 | L every format, trades, perf and 3D background re-checked | MS-17 (above) |
| 8 Party sizes and formats | 1v1, 1v1v1, 1v1v1v1, 2v2, lobby | L (all), T rules | four-player trades and battles at the same time in one world |

## 2. Plan (phases 9-19)

The work is ordered by what the release needs, not by phase number. Workstreams follow phase 12's agents; in this
cloud workspace (one 4-core machine) the heavy game runs go one at a time, while static work (inventories, test
generation, audits) runs in parallel, and Windows work fans out over parallel runner jobs.

1. **MS-17 first** (release gate): instrument the host core's delivery path hop by hop (route -> host companion ->
   bridge outbox -> game), record the route's exception in the room, reproduce with the free-for-all rematch scenario,
   fix the root cause, add a regression test, re-run the scenario several times.
2. **Inventory (phase 9) and coverage manifest (phase 15)**, generated from the game's own data so new content appears
   uncovered automatically: maps, warps, NPCs and other object events, signs, hidden and visible items, trainers (with
   their map placement), gyms, scripted battles, story flags and variables, menus, items and their effects, species and
   forms, moves, abilities, statuses, evolution methods, multiplayer actions, battle formats, side activities, rendering
   modes. Each entry gets a status (passed, failed, blocked, unverified, not implemented) from the tests that cover it.
3. **Accelerated gameplay tests (phase 10)** in the test builds' driver (test builds only, never in a player build), on
   L and in parallel CI jobs: every trainer fought by walking up and talking to them on their own map (rewards, the
   defeated flag, the return to the field, a save); every NPC, sign and object talked to with a hang watchdog; every warp
   taken; every visible item picked up; wild, legendary and scripted battles by their own triggers where the data allows.
4. **Mechanics (phase 10/11)**: the test ROM already covers the battle engine in depth; add the collection systems as
   their own category (daycare to hatch in a real game, trade evolution, Pokedex registration).
5. **Windows multiplayer (phase 13)**: the runner already runs two games and the real launcher in the installed build's
   play check; extend it to battles, trades and three/four players with game-side logs (no debugger on Windows).
6. **Watchdogs (phase 14)**: every check gives a deadline and a diagnosis (logs, screenshots, pending operations).
7. **Cross-system tests (phase 16)**, **fix loop (phase 17)**, then **merge and certify (phases 18-19)**.

## 3. Release gates (mandatory before the merge)

1. MS-17 root-caused and fixed, its scenario re-run without an interruption.
2. App suite green in CI on the candidate head; engine test ROM with no failure beyond the 39 known; native self-tests;
   the GBA ROM still `f214735b...3387`.
3. Every multiplayer format, trades, lobby, three and four players, abandon and recovery: passed in real games (L) on
   the candidate.
4. `windows-package` full on the candidate: package, install, play check, Mega check, starter check and the new
   Windows gameplay jobs all green.
5. The coverage manifest generated for the candidate: no failed entry for an implemented feature; blocked and
   unverified entries listed with their reasons.
6. No known open defect of high or critical severity.
7. After the merge: the same checks on the merged commits, the installer built from them, installed and played on the
   runner; its file name and SHA-256 recorded.

## 4. Progress log

- 2026-10-21: phase 1 audit (this file).
