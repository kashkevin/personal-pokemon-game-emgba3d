# Outstanding issues and their verification status

The owner's instruction of 2026-11-04: work through the remaining engineering issues (save integrity first, then
multiplayer performance, then 3D stability), document the options where a change would be a gameplay design
decision, keep this list complete, and treat nothing as verified on Windows from Linux results.

Verification marks: **L** Linux (this cloud machine: unit tests, self-tests in the real game code, real native games
through real launchers); **W** Windows on GitHub's hosted runners (CI, not a player's PC); **PC** the owner's own PCs
(nothing has run there). A fix is "done" here when it is committed and pushed with its tests; "Windows" says whether
a Windows CI run has covered it since.

Updated with every fix; the newest first within each section.

## 1. Engineering work in progress (owner's approval of 2026-11-04)

| Issue | What | Status | L | W | PC |
| --- | --- | --- | --- | --- | --- |
| MS-198 | The AI's damage estimate read the word before the critical-hit odds table for a target that blocks critical hits (Battle Armor, Shell Armor, Lucky Chant; AddressSanitizer, Steven's battle) | **Fixed** (engine `0d25e9c0`, PC only, the ROM unchanged): a blocked critical hit is none, as in the battle; the value read was not 1 in these builds, so nothing a player saw changes | Steven's battle under AddressSanitizer before (reported) and after (no report), won both times; the line check; MinGW 3D compiles | not yet | - |
| MS-197 | A world's shared world, friendship or wager store refused as it opened kept its file open until garbage collection, and the server kept the stores it had opened when a later one was refused: on Windows the world's files stayed locked until the launcher closed | **Fixed** (app: this change): a store refused or failing as it opens closes its connection; the server closes the ones it opened | `tests/test_store_open_failures.py` (4 new; failed before); the whole suite | found by the app's suite on Windows (run 304); **passed** in runs 317 and 322's `app-tests` (the whole suite on Windows, none failed; these tests have no Windows skip) | - |
| MS-196 | A power cut or system crash in the seconds after the native game saved could leave an empty or garbage save file: its data was not flushed to the disk before the rename that replaces the old save | **Fixed** (engine `9edbceed`, PC only, the ROM unchanged): the file's data goes to the disk first (`FlushFileBuffers`, `fsync`), then the rename; best effort on a disk that cannot flush (logged once) | the shiny check's keep-restart (a save, a second game continuing from it) under strace (one flush before each save's rename) and the Windows build under Wine: passed | **passed**: the feature checks' keep-restart (a save, then a second game continuing from it) in runs 310 and 322, the Windows build's saves flushed before their rename; not a power cut | a power cut: not shown anywhere |
| Save integrity | The world server's process killed in the middle of a save (a crashed launcher, End task in Task Manager) | **Checked, no change needed** (app: this change, a new permanent test `tests/test_server_killed_mid_save.py`): every save the server acknowledged is kept byte for byte, nothing newer than what was sent, the integrity check passes; a process kill, not a power cut | the new test (six kills of a real server process, during an upload and just after a commit was sent) and a 120-kill soak (2,957 saves; 55 commits that landed though the kill cut off their answer): integrity passed after every kill | the test is a step of the world-loading job (`world-open-bench`): its first Windows run (294) **failed in the test** (it killed a virtual environment's launcher, not the server holding the database; the store, opened at once, gave "disk I/O error"); fixed in the test, **passed in run 296** (GitHub's Windows runner) | - |
| MS-195 | A world that could not be opened at that moment (a lock held elsewhere, an I/O error, a full disk) was reported as damaged | **Fixed** (app: this change): damage only when SQLite says so (`SQLITE_CORRUPT`, `SQLITE_NOTADB`), anything else `storage_error` naming SQLite's error | `tests/test_storage.py` (injected errors, a held lock, damaged files) | **passed** in runs 317 and 322's `app-tests` (`tests/test_storage.py` with the rest of the suite, none failed) | - |
| MS-51 | Battle Tower milestone Pokemon lost when the game closed before saving and the older save had no room | **Fixed** (engine `36fb4589`, app: this change) | self-test 2,103/2,103 (the real game code: a full party and PC answer 0, the host's replayed claims change nothing, the resend makes it); app tests 173 | run 277: `--selftest-tower` in the Windows build passed | - |
| Co-op EXP | Gym EXP farming by losing again; the pending award lost on a reset before the award script | **Fixed** (engines `1b2c0089`, `1552e268`; app: this change): EXP with the badge-earning win only; the waiting result in the save; the launcher saves on the host as the co-op battle ends, the script runs after that save, the host save again after it (retried while the launcher is busy) (`docs/owner-decisions.md` 4-5) | self-test 57/57 (also under Wine); check-native, tower, ladder, update32: 0 failed; app save checks 79 passed; **real two-game run c5 passed** (a game closed during its award came back with the same award, nothing lost or doubled; runs c1-c4 found and fixed two launcher faults: KNOWN_ISSUES MS-190) | run 277: `--selftest-coop-exp` in the Windows build passed; run 280's new coop-proof job **passed** (a game closed during its award in Windows game processes came back with the same award) | - |
| MS-145 | Kept shinies and Legendaries forgotten when the game closes | **Fixed** (engine `9f0809f6`, app: this change): the keep list is a save record | self-test 24/24 (12 new; also under Wine); app record tests; **a real game closed and started again with four kept shinies: all four back, drawn shiny** (`shiny_check.py` keep-restart, engine `7f9b56bf`) | run 277: `--selftest-shiny` (its 12 new checks) in the Windows build passed; keep-restart passed in run 280's feature checks and **failed in run 284's, a fault of the check** (it wanted the first-seen place; the save rightly holds the last): fixed in engine `6b75d6b6` (the save's entries logged, every one put back compared; L 5 of 5); **run 288's feature checks passed with it** (keep-restart on Windows, engine `6b75d6b6`) | - |
| MS-161 | Opening a world slows as its saves pile up | **Improved again** (app: this change): about 2x more (600 saves: 2.67 s to 1.1-1.4 s), every check the same; still grows (about 1.9 ms a save); options (b) and (c) in KNOWN_ISSUES MS-161 are the owner's | the reader's equivalence test (5,603 slots); timings on a 600-save test world; `tools/perf/world_open_bench.py` (600 saves: 1.3-1.6 s) | the new world-open-bench job, run 281: **600 saves checked cold in 0.94-0.95 s** (GitHub's Windows runner) | - |
| MS-118 | 3D frame hitches when many chunks come into view at once | **Improved** (engine `9f41e9f3`), still open: chunks keep two earlier versions, so walking back over a seam builds nothing (20 crossings: 237 chunks built instead of 2,109, syncs over 16 ms 42 instead of 156); and the mesher's face sort moves 12-byte keys (engine `586a6156`: the same meshes, 10-21% less meshing alone, 6-14% in the walk); and the atlas's redraw draws each tile a row at a time (engine `daeed7a0`: the same pixels, its drawing 38% shorter in the walk: 3.7 to 2.3 ms a redraw); and the cells' rules resolve, run on every step while walking, finds its overrides and source cells by index (engine `d9a2db62`: the same cells on 383 recorded snapshots, 2.1-2.2 times faster); and the buildings' sync compares its triangles with the last upload instead of hashing them, uploading only when they change (engine `c8ba843f`: the same triangles, read back after every rebuild; 239-243 to 95-98 ms over the seam walk); and the chunks' signature hashes the same bytes with MurmurHash3 instead of FNV-1a a byte at a time (engine `bc57e464`: the same keys on 2,009 recorded inputs and 280,576 byte changes; 4 times faster, a crossing's terrain sync 10-12 to 7-9 ms); and a redraw of the atlas clears only the rows it uploads (engine `88e58c7d`: the same upload, 1.0 to 0.4 ms of each fade step's redraw); and the chunks' signature leaves out the cells' gameplay elevation, which the mesher never reads (engine `67e39839`: the same meshes; the seam walk builds 368-374 chunks instead of 412-415, its meshing about 15% less); left: several new chunks at once (options in KNOWN_ISSUES MS-118: worker threads within the frame, more sort tuning, builds spread over frames, the last a visual call), the rest of a crossing's atlas sync (about 1 ms clearing, 2.4 ms the cells' rules, 1.9 ms the upload) and a screen fade redrawing the atlas at each step (options in KNOWN_ISSUES MS-118) | A/B walks of the same binary; every chunk taken back built anyway and compared (1,892, 0 differed); 421,888 skipped-sync checks (0 stale); mesh check; check-diorama; **the same walk under AddressSanitizer** (engine `7f9b56bf`): no report, 1,882 taken back, 0 differed, 0 stale; the twelve-town loop there: 360 visits, no report; the face sort: 2,009 recorded chunk inputs meshed alike before and after, byte for byte; the atlas's drawing: the code before and after side by side, every output byte-identical (20,000 random metatiles, 300 random scenes: 375,584 slot draws), the engine's atlas test against the per-pixel functions; the signature without gameplay elevation: the 2,009 recorded inputs built again with random gameplay elevation (8,036 builds, the same meshes and signatures), 7.9 million byte changes elsewhere changing it exactly as before, the checked seam walk (86 chunks kept with another gameplay elevation built again, 0 differed) | run 277: the 3D graphics job (Mesa) passed with it; **run 286 (W, Mesa llvmpipe): the face sort (`586a6156`) and the seam walk passed** (160 chunks brought back, 0 differed; 36,866 skipped-sync checks, 0 stale); **run 288** (engine `6b75d6b6`, with the atlas's drawing and the rules resolve): the seam walk passed (160 brought back, 0 differed; 36,877 skipped-sync checks, 0 stale); **run 291** (engine `88e58c7d`, with the buildings' sync, the chunks' signature and the atlas's clearing): the seam walk passed (160 brought back, 0 differed; 36,922 skipped-sync checks, 0 stale; the buildings' buffer read back after 98 rebuilds, 0 differed), the geometry probe 14 of 14 places, the benchmark 19.4 fps through Mesa; **run 293** (only the 3D job, engine `67e39839`: the signature without gameplay elevation): the seam walk passed (131 brought back, 0 differed; 32,787 skipped-sync checks, 0 stale; 86 chunks kept with another gameplay elevation built again, 0 differed; the buildings' buffer after 98 rebuilds, 0 differed), the Mega battles, the geometry probe and the benchmark too | - |
| MS-192 | Windows run 273's Tower Duo proofs (duo, mega, join, join-reset) waited 30 minutes after their Duo battles | **Fixed** in the proof (app: this change): since MS-190 the launcher saves as a co-op battle ends and the game again after a Tower floor's result, which the proof did not expect; the game and launcher unchanged | `native_launcher_tower_proof.py` duo and join passed (real games, real launchers) | **run 277**: duo, mega, join and join-reset passed | - |
| MS-189 | The 3D rules parity test compares out of step | **Fixed** (engine `49b12c51`): not out of step - both list 325,079 terrain rows (the 332,226 counted the pixel objects' lines too); the test expected the classifier's height and shape where the resolver applies the terrace levels and the tree groups' bodies (also MS-170) | `tools/diorama_rules/test_rules_parity.py`: passed (all 325,079 rows and the pixel objects; every field) | - | - |
| MS-39 | Mega Rayquaza unreachable (no way to learn Dragon Ascent) | **Fixed** (engine `d6e3072e`): Dragon Ascent at level 1 (the Gen 8 and Gen 9 level), offered by the move relearners | `--selftest-megas` (the learnset, the Sky Pillar Rayquaza's moves, the relearner's list, CanMegaEvolve with and without the move and the Mega Ring; also under Wine); ROM unchanged | run 277: `--selftest-megas` in the Windows build passed | - |
| MS-38 | Mega Lucario Z's Aura Guard does nothing | **Fixed** (engine `d6e3072e`): half damage from moves that make contact, Mold Breaker ignores it (the effect from search results: KNOWN_ISSUES MS-38) | `--selftest-megas` (the battle's own damage calculation with the same roll: contact halved, the rest unchanged; also under Wine) | run 277: `--selftest-megas` in the Windows build passed | - |

## 2. Other engineering issues (to be worked through; options documented where a design call is needed)

| Issue | What | Status |
| --- | --- | --- |
| G3 | A World Event's 120 s claim release after a disconnect could let two players catch the same event Pokemon | open (improved before: active seconds only); a gameplay call, so options only: (a) the shared spawns' 600 s grace for events too (rarer, not gone); (b) hold the claim until its claimant comes back and reports the battle (no duplicate, but one absent player can keep an event from everyone); (c) keep 120 s and accept the rare second copy |
| NU-7 | An invite code cannot be revoked for one friend | **Fixed** (option (a), not gameplay; app: this change): Invite codes for friends > Replace a friend's code (while not hosted): the old code refused at once, the account kept; crash-safe (record, database, host.json, the next open finishing a half-done one); the friend's PC takes the new code only after the host accepted it. L: unit, page and real-server tests; **W: run 291's world-loading job** (GitHub's windows-2022 runner, not a player's PC): the host world's and the stored invite's replacement tests, 9 passed (the msvcrt owner lock, files replaced whole) |
| MS-29 | START > PLAYER > RESET sometimes does not open PLAYERS (the player is told to try again) | **Fixed** (engine `62da105f`, PC only): the START menu ends a turn in place, so the field is at rest; `--selftest-start-menu` 12/12 (the new check fails without the fix); not run in a real game process ; Windows: run 277's `--selftest-start-menu` passed (the 2D and 3D games) |
| MS-55 | A new Players menu page opens with the previous page's cursor row | **Fixed** (option (a); engine `8c383890`, app: this change; PC only, the ROM unchanged): the launcher marks a page's first screen (flags 0x80) for a game whose manifest has `menu_new_page_abi_version` 1, and the window starts it on its first row; refreshes and one list's pages keep the row; the bridge's tests, the app suite and a real game's Tower pages (L: every page on row 0; before: rows 2, 1 and 2 on three of them); W: run 288 packaged it (the manifest's `menu_new_page_abi_version`) and its jobs that page through the Players menu passed with it; the row each page opens on is checked on Linux only |
| MS-52 | The native Tower screens show the game's copy of the record until the next word | open (cosmetic) |
| MS-154 | 6 ledges the player cannot jump land a level higher in 3D | partly fixed |
| MS-108 | Transitions' pictures still the GBA's art | open (art) |
| VR-5 | 226 of 959 battle animations have no HD version | open (art) |
| MS-9 | The emulator fallback's Lua bridge has the same all-zero check as the old native one | open (fallback only) |
| MS-26 | Save checks on the launcher's and host's event loops | measured, no player-visible cost found |
| MS-194 | World trades refused every alternate form but Rotom's (a female Meowstic, Burmy's cloaks, Pumpkaboo's sizes, an Origin Giratina, Vivillon's patterns, ...) | **Fixed** (app: this change, not gameplay: a Gen 6 game trades them as they are): every form of a Kanto-to-Kalos species reviewed against the engine pin; the 163 kept outside battle are exchanged exactly and named in the menus; battle-only, later games' and the games' untradable forms stay refused; the menu rows keep a level whole. L: unit tests, the whole suite; two real games: a Female Meowstic for an Origin Giratina, and a Small Pumpkaboo for a Large one (each evolving into the Gourgeist of its size). W: **passed** in the `trade-proof` job (run 299, its first run; the full runs 310 and 322) |
| MS-193 | The Championships' Species Clause and No Legendaries ignored forms (two Rotom forms as two species; Origin Giratina, Deoxys's formes, the Therian Formes, ... as no legendary) | **Fixed** (app: this change): the rules compare National Pokedex numbers from a table generated from the engine pin (`species_national.py`; all 1,573 IDs agree with the game's compiled table). L: unit tests. W: the tests **passed** in runs 317 and 322's `app-tests` |
| Trades | Eggs and Mail are refused in trades (the menus say so) | open, options in KNOWN_ISSUES ("Trades: eggs and Mail"): Eggs (a) refused, (b) traded as the games do, the hatcher becoming the original trainer (the host's checks accept that one change); Mail (a) taken off first, (b) carried into a free Mail slot of the receiver |
| G1 | An evolution trade that must choose a move for a Pokemon knowing a post-Gen-6 move is refused | **Fixed** (app: this change): the owner's decision applied, such moves trade unchanged; the move being learned stays a Gen 6 one; unit tests only (L), no real trade with such a Pokemon |
| MS-141c limits | Wireless minigames: four players not run | **Run** (app: this change): all three with four world players on Linux (L, real games and launchers; the proof's focus timing fixed for Pokemon Jump); Windows run 277 and run 280 passed two and three players (W); four on Windows: run 280's Dodrio and Jump jobs failed in the proof's phase checks (the games played and agreed), the proof fixed; **passed** in run 288 and every full run since (run 322: all three with four players) |
| MS-98 | The 3D map sweep's debug scene stops in three rooms (debug warp only) | open (not reachable in play) |
| MS-170 | A 3D rules test's notion of height (records vs resolved cells) | **Fixed** with MS-189: the test checks the resolved cells, by the resolver's own rules from the records |

## 3. Decisions only the owner can make (options in `docs/owner-decisions.md`)

N8 licensing of `src/platform/bios.c` (blocks giving the build to anyone; "Leave for now"); the base game dump for CI
(U31-13); the Node 24 actions patch (U31-16); day counters on the world clock (G13); a ticket source for personal
static legendaries; the character customization scope; the 39 upstream GBA test failures under Gen 6 rules; egg
hatching speed (MS-42); and the "built, your call" items: Xbox B as Cancel, 3D vehicles falling back to 2D, music
loudness, Battle Point shop prices, a launcher checkbox for location privacy. Also, with their options in
KNOWN_ISSUES: a World Event's claim release after a disconnect (G3, gameplay); whether trades take Eggs and Mail
("Trades: eggs and Mail", gameplay); how far a world's integrity check
may trust its own earlier result (MS-161 (b) and (c)); and the 3D view's two visual trade-offs, a screen fade
redrawing the atlas at each step and a map crossing's new chunks spread over a few frames (MS-118). Three smaller
questions are in section 7 (MS-85, MS-149, U31-5).

## 4. Verification only the owner's PCs can give

A real graphics card at 60 fps, a controller, two PCs on a home network and over the Internet (router, UPnP/NAT-PMP),
a fresh install and first play on the owner's PC, and the owner's crash logs if the Safari crash recurs (MS-169).
NU-8, VR-6, WC-4, MS-7 hold the checklists; V21, V39, U30-5 and NU-10 (section 6) are owner tests too, and so are
the fixes section 7 lists as not yet tried between two real PCs.

## 5. Windows CI coverage of the newest work

Run 271 (2026-11-04 morning) covered engine `2054cf05` and is the last installer prepared. Run 273 (engine
`49b12c51`, app `6952acc`): 55 jobs passed, 4 failed (the Tower Duo proofs' expectation, MS-192, fixed). Run 277
(engine `9f41e9f3`, app `3e42c54`, the gameplay check on): **all 62 jobs passed** (the engine self-tests with every
fix of the day, the three wireless minigames between two and three players, the Tower's Duo proofs, multiplayer,
saving, 3D graphics through Mesa, the Tower's 100-floor climb, 18:58-22:06 UTC); its installer predates G1 and is not
the next one. Run 281 (a smoke run of app `7307edd`): the new world-loading job passed
(600 saves checked cold in 0.94-0.95 s).

Run 280 (engine `7f9b56bf`, app `bbaa9a7`, the gameplay check on) was to be the installer candidate: everything of
run 277 plus G1, MS-145's keep-restart in a real Windows game, the minigames with four players and the new coop-proof
job (a game closed during its co-op award). Its first attempt stopped before any build when the runner's package
installs stalled three times (a mirror, not this code; no check ran), and its failed jobs were run again at 21:25 UTC.
In that second attempt the coop-proof job **passed** (MS-190 on Windows) and so did the minigames between two and three
players, but the new four-player Dodrio Berry Picking and Pokemon Jump jobs **failed in the proof's checks, not in the
games** (each wanted every game's reading to catch a phase of a second or less while the proof's pictures held up the
readings; every game played, agreed on the results and came back to the field). With the proof fixed (app `0e04cc5`),
run 282 was dispatched as the installer candidate; its engine job's package install stalled three times with no output
before any build (as in run 280's first attempt; not this code), so the step now fetches and installs in two parts and
shows apt's state when a part stalls, and the next full run is the installer candidate. The installer is prepared only
from a run whose every required job passes, and is not distributed (N8).

Run 284 (engine `7f9b56bf`, app `47e1ad9`, the gameplay check on) was that candidate: its toolchain step passed in 41
s and 65 of its 67 jobs passed, but its feature checks **failed in the shiny check's keep-restart**: the check
compared the shiny put back after a restart with where it was first seen, while the save (rightly) holds where it
last stood; the game was right (KNOWN_ISSUES MS-145's update of 2026-11-05). The check is fixed (engine `6b75d6b6`,
five Linux runs passed, three of them the case that failed), so run 284 is not the installer; the next full run,
with every engine change since (`586a6156` to `6b75d6b6`), is the candidate. Run 284's climb was left to finish.
Run 286 (only the 3D graphics job; engine `586a6156`, app `5451278`) **passed**: MS-118's face sort and the new seam walk
on Windows through Mesa (160 chunks brought back, none differed; 36,866 skipped-sync checks, none stale). Changes since
run 284's engine (the face sort, MS-55, the atlas's drawing) go to Windows in the next full run.

Run 288 (engine `6b75d6b6`, app `68187b0`, the gameplay check on) **passed every one of its 67 jobs** on the first
attempt (00:58-05:02 UTC on 2026-11-05): its installer is the one prepared (`docs/package-20261105.md`), not
distributed (N8). Run 291 (engine `88e58c7d`, with the 3D view's buildings' sync, chunks' signature and atlas clearing)
and run 293 (only the 3D job, engine `67e39839`: passed) followed. Run 295 (engine `67e39839`, app `8a970e6`) carries the
kill test as first written, which failed in its own harness on Windows (run 294); run 297 (engine `67e39839`, app
`f83c033`: the fixed test, MS-193, MS-194, MS-195) is the next candidate, dispatched at 05:14 UTC.

Runs 298-307 (2026-11-05 morning; nothing published): run 299 (only `trade-proof`, engine `67e39839`) **passed** world
trades of forms and a trade evolution (MS-194, MS-151) in real Windows games; run 302 (only `battle-trade-3d`, engine
`4c35be64`) **passed** the first battle and trades between players in the 3D game on Windows (Mesa); run 306 (only
`gameplay-3d`, engine `9edbceed`) ran the whole game's gameplay plan in the 3D game through Mesa: 7 of 8 shards passed,
and shard 1's one failure is the plan runner's (Liza; fixed in `e88dbdf6`, to run again with it). Run 304 (only
`app-tests`) ran the app's whole suite on Windows for the first time: 103 tests failed in seven Windows-only kinds,
one in the app (MS-197: files left open by a refused store) and the rest in the tests (8.3 temporary paths, files
left open, a refused connection's 2 s, a path across drives, cp1252, the event loop's 15.6 ms tick, a Lua that is
not there); all fixed (app `975d700` and `58ffc1f`; TEST_LEDGER), the next `app-tests` runs the check. The
smoke runs of the pushes (300, 301, 303, 305, 307) failed in the world-loading job's new step, the save path's own
tests (the tests' paths and open files on Windows, not the store); fixed in `975d700`, whose smoke run 309 passed
the step on Windows (312 tests, the 3 expected skips). Run 310 (engine `e88dbdf6`, app `975d700`, the gameplay
check on) **passed every job** (08:42-12:32 UTC): its installer is now the one prepared,
`docs/package-20261105c.md`, not distributed (N8).

Run 297 (engine `67e39839`, app `f83c033`, the gameplay check on) **passed every one of its 67 jobs** on the first
attempt (05:14-09:16 UTC; the 100-floor climb 3 h 07 min): its installer is now the one prepared
(`docs/package-20261105b.md`), not distributed (N8). Run 308 (only the 3D gameplay plan, engine `e88dbdf6`)
**passed** all eight shards: 3,612 targets, none failed, Liza's battle among them; the 3D gameplay check now runs in
every full run with the gameplay check on, as the Classic 2D one does. Run 311 (only `app-tests`, app `975d700`): 13
failed, 3,046 passed; twelve of kinds `58ffc1f` fixes and one new, a race in a test (`test_world_server` compared two
players' views of the wild Pokemon from two moments; fixed, both now from one broadcast); its 119 more skips are
the Lua bridge tests, as intended. Run 313 (`app-tests` on `58ffc1f`): **2 failed**, 3,057 passed; every kind of
run 311 passed. The two are `test_battle_execution`'s longest four-player battles, which ran past their clients'
20 s: without a route journal the host flushes the room record 1,310 times in each, and the Windows runner's disk
is slower (reproduced on Linux with flushes 5 ms slower; with the limit lifted they end and pass). Their limit is
now 120 s, a hang's limit (the fixture counts game frames, not time); the next `app-tests` checks it.

Added since: the multiplayer-check job's `give-up` and `give-up-mid-turn` entries (MS-126) and the package job's
in-game menu check of a mouse at rest where the menu window opens and of one crossing straight back into it
(KNOWN_ISSUES P14, fixed in engine `6ce2648c`). Run 317 (engine `6ce2648c`, app `86c8fde`) **passed** every job it
ran: both give-ups in Windows game processes (the mid-turn one with the master's command before the notice) and
`app-tests`, the app's whole suite on Windows with **none failed** for the first time (3,061 passed, 154 skipped);
the app tests now run in every full run. The menu check with the crossing (app `f500637`) **failed** on the old
engine (run 319: in both games the row under the mouse, Host Server, took the focus) and **passed** on engine
`6ce2648c` (run 320): P14's fix shown on the Windows runner.

Run 322 (engine `fb6bcd9f`: P14's fix and the gameplay check's narrowed blocked rule, app `cbc4419`, the gameplay
check on), the first full run with the app's tests and the 3D gameplay check in it, **passed every one of its 82
jobs** (12:54-16:16 UTC): its installer is now the one prepared, `docs/package-20261105d.md`, not distributed
(N8). MS-198's fix (engine `0d25e9c0`, no player-visible change in these builds) comes with the next full run.

## 6. Earlier issues in KNOWN_ISSUES (reviewed 2026-11-04)

Every issue in KNOWN_ISSUES whose row there still reads open, or whose fix was never shown in this list, checked
against the code, the tests and the Windows jobs on 2026-11-04. Nothing here changes gameplay.

| Issue | What | Status now | Verification |
| --- | --- | --- | --- |
| MS-62 | Battles between two PCs over the internet paused 30-60 s between actions | **Improved** (engines `09dd6ac6`, `42c2f4a7`; app `2237839`): the battle PEEK and each launcher's observer, the host's observed router | L with simulated internet delay; W: every multiplayer battle job; **PC**: two real PCs over the internet not tried |
| M25 | Native battles slow to relay (about 2.8 blocks a second; every command written durably before use) | **Improved**, by MS-62 (the per-block round trips) and step 10 (the journal's transport records without an fsync before each command; TEST_LEDGER "Step 10") | L; W as MS-62; **PC**: not measured on a Windows PC or an SSD |
| MS-64 | A trade ended as soon as it began on two real PCs | **Fixed** (app): the trade asks the game again while it is busy; saves send four chunks at a time | L real games, 2D and 3D, simulated delay; W: the trade jobs; **PC**: two real PCs not tried |
| MS-82 | Mr. Briney's sail lags in 3D | **Improved** (engine `38626dad`): far chunks wait their rebuild; left: the map seams of the sail build 9-14 new chunks at once (as MS-118's first part; MS-118's earlier versions do not help a one-way sail) | L software OpenGL; **PC**: the owner's check |
| V37 | Lavaridge's stepped relief is the heaviest terrain (about 135,000 triangles in a battle's view) | **Reduced**; open until the owner's graphics-card benchmark (V39) shows whether it still costs | L software OpenGL |
| M2 | Which multiplayer paths had run natively | **Covered since**: Windows game processes run 2-4 player gameplay, trades, every interrupted battle and the Tower (W, runs 271 and 273); a multiplayer Mega battle ran in the 3D build (L) | L, W; **PC**: two real PCs (section 4) |
| N42 | Under Wine, closing the Windows game once ended in glibc's "double free" (1 close in 250) | open, Wine only (the message is glibc's, Linux-side code under Wine); never seen on Windows, where every multiplayer and Mega job closes its games and checks the exit code | L (Wine), W |
| M14 | The spawn catalogue lists 31 Kanto maps this build does not contain | open, harmless (nobody can stand there; the host fills only maps with players) | - |
| M27 | The one-time hint banner shows "START  PLAYER  STYLE" without its arrows | open: both files are GBA code (the ROM stays byte-identical); a PC-only arrow or other words is the owner's call | - |
| V44, V45 | Two strips of the Battle Frontier's wall shading set back as windows; the Battle Dome's curved ends as thin strips | open, low (art: a change to `window_rects` would move every building's windows; a curved front needs its own model) | - |
| E9 | Magma Hideout 2F's machines are flat on the floor, and a battle's stage can stand a foe on one | open, low (the machines are not modelled) | - |
| S2, S3, S5, S7 | Battle sprites: a tall Pokemon's head behind the foe's lower healthbox in doubles; Spinda's spots the animation's own; a very tall Pokemon cut at a 2D battle's edge; Role Play and Snatch show the GBA art | open, low (art and the battle HUD's layout) | - |
| U30-1, U30-2, U30-3 | A first character takes three short game windows; the menu is its own small window; the launcher-only panels need `--classic-launcher` | by design (documented in `docs/update30-main-menu.md`; the in-game PLAYER menu has the player-facing equivalents) | - |
| V2 | The voxel project's rules parity test failed (height 32 against 0) | **Resolved** with MS-189: the test checks the resolved cells by the resolver's rules; passes (all 325,079 rows) | L |
| V4 | The voxel project's rule-compiler test failed (mountain records with flag 128 as well as 32) | **Resolved**: passes on the current engine (2026-11-04, 238 s) | L |
| U31-1 | The Update 14 shared-world compat fixture missing from a fresh clone | **Resolved**: committed as deterministic SQL text and built by the tests (app `2dae2b1`, `97e97a4`) | L, CI |
| U31-2 | The engine repository and GitHub Actions not reachable from the session | **Resolved**: this session builds the engine and dispatches and reads the Windows runs | - |
| U31-3 | A rival battle drew the Frontier arena instead of its checkpoint's environment | **Fixed** (engine): the preparation carries the checkpoint's environment (PLAIN) | L `--selftest-rival`, `rival_check.py`; W: the rival-check job ("a rival battle takes its checkpoint's environment") |
| U31-12 | `tests/fixtures/compat/checkpoints_u14/credentials.json`: synthetic, no test reads it | harmless leftover of an unfinished compat test | - |
| N13, N35, M5, M16, V20, MS-45, MS-54 | Pokedex and PC-box crashes natively; a live save's pause; a shared wild Pokemon's lost result; the 3D board in the dark; the soft-reset page; the shop's "Waiting" | **Fixed** (each row in KNOWN_ISSUES; M16's last part is G3, section 2) | L (MS-54 also W run 133) |

Owner tests added to section 4 by this review: V21 (125-200% display scaling, two displays, exclusive fullscreen),
V39 (the frame-rate targets on a graphics card), U30-5 (the menu with a controller), NU-10 (`--relay-server` from
the packaged launcher opens its own console).

## 7. What KNOWN_ISSUES still leaves open, issue by issue (audit of 2026-11-05)

Section 6 listed the rows that still read open. On 2026-11-05 every issue's latest row in KNOWN_ISSUES (399 issues)
was read again for what it still leaves: a part left as it is, a check not run, or a question for the owner. Those not
already in a section above are here, each as its row last says (the row's date given; not checked again unless
said). Nothing here changes gameplay.

**Left as they are** (low; the game, collision and saves unaffected unless said):

| Issue | What is left | Row of | Verification |
| --- | --- | --- | --- |
| MS-49 | A Battle Tower floor in a game running below about 22 frames a second could still start after the host's two minutes (the game's wait counts its own frames, which keep real time unless the picture is drawn at fewer than 12 frames a second: `sdl2.c` runs up to five game frames per drawn frame) | 2026-10-22 | L self-test (the 45 s limit) |
| MS-181 | Another player diving is drawn with the original underwater look, not on their own carrier | 2026-11-04 | L |
| MS-12 | The bridge's limits: another operation's CANCEL, a second CANCEL or any other command still stops the bridge; a recovery control that replaces the command takes the waiting CANCEL with it. **Checked 2026-11-05: not reached by the launcher** (a timed-out checkpoint forbids every later save of that game session; trades, their effects and battles start from the player's choice in a running game, which answers its outstanding command first; KNOWN_ISSUES MS-12's update); would need a change only if a feature sent save commands on its own timer | 2026-11-03, 2026-11-05 | L; not run on Windows or in mGBA |
| M1 | The check that a native game was built with the same ROM build runs for games the launcher starts, not for one started by hand | 2026-10 (Milestone C) | L |
| M10, G5 | The emulator (GBA) build keeps the original behaviour (a World Event Pokemon's missing map template; the real-time clock), as its ROM stays byte-identical; on PC the other clock uses (tides, time-based evolutions) follow the world clock by design | 2026-10 | - |
| G14 | The fix to experience in a battle against two trainers at once (one "already gave experience" mark per opposing trainer) has not been played in a real two-trainer battle in the native game | 2026-10 | the battle test `exp_two_opponents.c` |
| MS-97, MS-163 | Harmless reads past their data in upstream code and data the GBA ROM shares, recorded for later sanitizer runs (padding them would change the ROM); an AddressSanitizer run must continue past them (`halt_on_error=0`; the build recovers), or the first one stops the game; the trade evolution under AddressSanitizer (2026-11-05) added one of the same kind, the evolution scene's palette animation reading one row past its table, a value it never uses | 2026-10-28, 2026-11-05 | L AddressSanitizer |
| MS-167 | Blank 3D message boxes: the cause found was fixed; other causes may remain (a screenshot and the place would show which) | 2026-10-29 | L |
| MS-102 | The 3D view: a pale band at the foot of the sea stacks (the mountain art's side texture) | 2026-10-26 | L software OpenGL; a GPU not tried |
| MS-76 | The 3D view: two slivers of the sky's colour at inner corners of Route 111's rock band (zoomed out); Route 112's small blue slivers north of the station | 2026-10-26 | L |
| MS-87 | The 3D view: photo mode looking straight down far south, and 21:9 or wider zoomed out at the far top corners, show the distance haze | 2026-10-26 | L |
| MS-173 | The 3D view: cliffs between two levels (Mossdeep's one face), mountains and rocks in the sea stand as step 16 made them (the owner's report covered the thin painted cliffs, which lie as drawn again) | 2026-10-31 | L; W run 255's 3D job |
| MS-186 | The 3D view: Shoal Cave's low-tide bridge stands half a level over the floor under it, and a person there stands on its deck | 2026-11-03 | L |
| MS-164, MS-172, MS-178 | The 3D view: notice boards on legs drawn as they are (the Frontier lobbies); painted tree crowns beyond Fortree that the game's cameras never see; the Safari Zone north-east's closed pocket, which no one can walk into | 2026-11-01 to 11-04 | L pictures |
| V6 | The 3D view: an unmodelled building's door does not open (modelled buildings' doors do) | 2026-10 | L |
| V10 | 3D battles: in maze-like rooms the battle stage still has walls near every spot | 2026-10 | L |
| V23 | The 3D view with the voxel trees (F8, not the default): the rules' grouped tree hulls in Petalburg Woods still stand as a step | 2026-10 | L |
| E5 | 3D battles: places still flat when its row was written: the Trainer Hill's roof floor, Shoal Cave's tidal flat (one level on the GBA too), the Battle Pyramid's top (since made a stepped pyramid in the 3D view, engine `6244408e`; its battle stage not checked again) | 2026-10 | L |
| V46 | 3D battles on maps whose layout a script switches: not tried on Route 130 with Mirage Island, Shoal Cave's inner room at high tide, Sootopolis in the legends' battle (the same code path as those tried) | 2026-10 | L |
| V26 | The 3D view: particles in the world and weather on vegetation, planned for a later phase | 2026-10 | - |
| N4 | Linux's renderer is the Windows build's; a visual re-check of it was left pending (a Linux build is not shipped) | 2026-10 | L |

**The owner's calls** (with the ones in section 3):

| Issue | The question | Row of |
| --- | --- | --- |
| MS-85 | A casino table's counter shows at most 9,999 (the GBA's digits): a 6,000-coin slot jackpot is cut when the machine already holds more than 3,999 coins, a 2,400 roulette win at the left table above 7,599, the right table's 9,600 above 399; a cap on what a table takes from the wallet would prevent it, a change to coin handling not asked for | 2026-10-26 |
| MS-149 | Whether a Poke Ball throw at catch odds 0 (the fixed Heavy Ball on a catch rate of 1, a Beast Ball on a low one) should get a minimum chance | 2026-10-27 |
| U31-5 | The rival checkpoint's personal pass still registers the original May or Brendan in Match Call, as the original scene does (its story flag kept); remove the NPC rival's calls? | 2026-10-16 |

**Only two PCs or the owner's PC can show** (with section 4): MS-63 (the rival checkpoint battle reported on two PCs,
not reproduced; both launchers' `runtime.log` after the next one), MS-71 (a game closing in a battle, not reproduced;
the next `crash.log` or `errors.log`), MS-88 and MS-165 (battles between players over a slow connection, and a PC
that stops a game for seconds), MS-68, MS-69, MS-70, MS-72, MS-95, MS-96 (trade and battle fixes not yet tried
between two real PCs), MS-81 (the owner's check of spawn odds), MS-65 and MS-89 (the 3D view on a real graphics card,
with V3, V25, E8: V39's benchmark). MS-126's give-up notice reaching the battle's master during a turn has run since
(2026-11-05: the newcomers proof's `give-up-mid-turn`, L, and on the Windows runner in run 317). Not run anywhere yet: a battle ending another way after a give-up; MS-83's race, seen once and not reproduced
after its fix.
MS-156's other static encounters have run since (2026-11-05, engine `e88dbdf6`): all 17 that a talk reaches started
their battle offline in the Classic 2D and 3D test builds (L); the feature-checks job runs them on Windows from the next
full run; Mew and Deoxys (a walk into the grass, the triangle's puzzle first) not.

**Covered on Windows since their rows were written** (the rows say "not on Windows"): MS-78 (move switching) and
MS-171 (the Acro Bike's rails) by the feature-checks job (`move_switch_check.py`, `acro_check.py`; passed in run 288);
MS-151 (a trade evolution between two games) by the new trade-proof job (its first run, run 299: **passed**); MS-166 (the 99 script
specials' 8-bit results, the Day Care's money among them) by the engine self-tests job (`--selftest-special-results`
since run 277, passed in run 288). MS-182 and MS-185 have no Windows check of their own (reads past their data that
AddressSanitizer found on Linux); the Windows builds carry the fixes.

**Fixed though its row still read open**: MS-125's Classic 2D notice ("This battle stopped. In the launcher: Recover
battle, or Abandon battle." over the GBA picture when a battle's core stops itself) has been in the game since engine
`2f45fe5c` (2026-10-27; its drawing checked in the 2D test build, a core stopping itself not reproduced); KNOWN_ISSUES now
says so. Every other row above was checked against both repositories' histories for a later fix: none.

**Fixed since this audit**: MS-84, the Classic 2D Slot Machine's payout table (SELECT) shows the PC game's payouts
(engine `4c35be64`, a picture of the PC game's own; L in the real game, the GBA ROM unchanged; not on Windows).
