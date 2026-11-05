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
| MS-51 | Battle Tower milestone Pokemon lost when the game closed before saving and the older save had no room | **Fixed** (engine `36fb4589`, app: this change) | self-test 2,103/2,103 (the real game code: a full party and PC answer 0, the host's replayed claims change nothing, the resend makes it); app tests 173 | run 277: `--selftest-tower` in the Windows build passed | - |
| Co-op EXP | Gym EXP farming by losing again; the pending award lost on a reset before the award script | **Fixed** (engines `1b2c0089`, `1552e268`; app: this change): EXP with the badge-earning win only; the waiting result in the save; the launcher saves on the host as the co-op battle ends, the script runs after that save, the host save again after it (retried while the launcher is busy) (`docs/owner-decisions.md` 4-5) | self-test 57/57 (also under Wine); check-native, tower, ladder, update32: 0 failed; app save checks 79 passed; **real two-game run c5 passed** (a game closed during its award came back with the same award, nothing lost or doubled; runs c1-c4 found and fixed two launcher faults: KNOWN_ISSUES MS-190) | run 277: `--selftest-coop-exp` in the Windows build passed; run 280's new coop-proof job **passed** (a game closed during its award in Windows game processes came back with the same award) | - |
| MS-145 | Kept shinies and Legendaries forgotten when the game closes | **Fixed** (engine `9f0809f6`, app: this change): the keep list is a save record | self-test 24/24 (12 new; also under Wine); app record tests; **a real game closed and started again with four kept shinies: all four back, drawn shiny** (`shiny_check.py` keep-restart, engine `7f9b56bf`) | run 277: `--selftest-shiny` (its 12 new checks) in the Windows build passed; keep-restart passed in run 280's feature checks and **failed in run 284's, a fault of the check** (it wanted the first-seen place; the save rightly holds the last): fixed in engine `6b75d6b6` (the save's entries logged, every one put back compared; L 5 of 5); Windows: run 288 | - |
| MS-161 | Opening a world slows as its saves pile up | **Improved again** (app: this change): about 2x more (600 saves: 2.67 s to 1.1-1.4 s), every check the same; still grows (about 1.9 ms a save); options (b) and (c) in KNOWN_ISSUES MS-161 are the owner's | the reader's equivalence test (5,603 slots); timings on a 600-save test world; `tools/perf/world_open_bench.py` (600 saves: 1.3-1.6 s) | the new world-open-bench job, run 281: **600 saves checked cold in 0.94-0.95 s** (GitHub's Windows runner) | - |
| MS-118 | 3D frame hitches when many chunks come into view at once | **Improved** (engine `9f41e9f3`), still open: chunks keep two earlier versions, so walking back over a seam builds nothing (20 crossings: 237 chunks built instead of 2,109, syncs over 16 ms 42 instead of 156); and the mesher's face sort moves 12-byte keys (engine `586a6156`: the same meshes, 10-21% less meshing alone, 6-14% in the walk); and the atlas's redraw draws each tile a row at a time (engine `daeed7a0`: the same pixels, its drawing 38% shorter in the walk: 3.7 to 2.3 ms a redraw); and the cells' rules resolve, run on every step while walking, finds its overrides and source cells by index (engine `d9a2db62`: the same cells on 383 recorded snapshots, 2.1-2.2 times faster); and the buildings' sync compares its triangles with the last upload instead of hashing them, uploading only when they change (engine `c8ba843f`: the same triangles, read back after every rebuild; 239-243 to 95-98 ms over the seam walk); and the chunks' signature hashes the same bytes with MurmurHash3 instead of FNV-1a a byte at a time (engine `bc57e464`: the same keys on 2,009 recorded inputs and 280,576 byte changes; 4 times faster, a crossing's terrain sync 10-12 to 7-9 ms); and a redraw of the atlas clears only the rows it uploads (engine `88e58c7d`: the same upload, 1.0 to 0.4 ms of each fade step's redraw); and the chunks' signature leaves out the cells' gameplay elevation, which the mesher never reads (engine `67e39839`: the same meshes; the seam walk builds 368-374 chunks instead of 412-415, its meshing about 15% less); left: several new chunks at once (options in KNOWN_ISSUES MS-118: worker threads within the frame, more sort tuning, builds spread over frames, the last a visual call), the rest of a crossing's atlas sync (about 1 ms clearing, 2.4 ms the cells' rules, 1.9 ms the upload) and a screen fade redrawing the atlas at each step (options in KNOWN_ISSUES MS-118) | A/B walks of the same binary; every chunk taken back built anyway and compared (1,892, 0 differed); 421,888 skipped-sync checks (0 stale); mesh check; check-diorama; **the same walk under AddressSanitizer** (engine `7f9b56bf`): no report, 1,882 taken back, 0 differed, 0 stale; the twelve-town loop there: 360 visits, no report; the face sort: 2,009 recorded chunk inputs meshed alike before and after, byte for byte; the atlas's drawing: the code before and after side by side, every output byte-identical (20,000 random metatiles, 300 random scenes: 375,584 slot draws), the engine's atlas test against the per-pixel functions; the signature without gameplay elevation: the 2,009 recorded inputs built again with random gameplay elevation (8,036 builds, the same meshes and signatures), 7.9 million byte changes elsewhere changing it exactly as before, the checked seam walk (86 chunks kept with another gameplay elevation built again, 0 differed) | run 277: the 3D graphics job (Mesa) passed with it; **run 286 (W, Mesa llvmpipe): the face sort (`586a6156`) and the seam walk passed** (160 chunks brought back, 0 differed; 36,866 skipped-sync checks, 0 stale); **run 288** (engine `6b75d6b6`, with the atlas's drawing and the rules resolve): the seam walk passed (160 brought back, 0 differed; 36,877 skipped-sync checks, 0 stale); **run 291** (engine `88e58c7d`, with the buildings' sync, the chunks' signature and the atlas's clearing): the seam walk passed (160 brought back, 0 differed; 36,922 skipped-sync checks, 0 stale; the buildings' buffer read back after 98 rebuilds, 0 differed), the geometry probe 14 of 14 places, the benchmark 19.4 fps through Mesa; the signature without gameplay elevation (`67e39839`) in no Windows run yet | - |
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
| Trades | Eggs, mail and unsupported forms are refused in trades | open (adapter work) |
| G1 | An evolution trade that must choose a move for a Pokemon knowing a post-Gen-6 move is refused | **Fixed** (app: this change): the owner's decision applied, such moves trade unchanged; the move being learned stays a Gen 6 one; unit tests only (L), no real trade with such a Pokemon |
| MS-141c limits | Wireless minigames: four players not run | **Run** (app: this change): all three with four world players on Linux (L, real games and launchers; the proof's focus timing fixed for Pokemon Jump); Windows run 277 and run 280 passed two and three players (W); four on Windows: run 280's Dodrio and Jump jobs failed in the proof's phase checks (the games played and agreed), the proof fixed, the next full run |
| MS-98 | The 3D map sweep's debug scene stops in three rooms (debug warp only) | open (not reachable in play) |
| MS-170 | A 3D rules test's notion of height (records vs resolved cells) | **Fixed** with MS-189: the test checks the resolved cells, by the resolver's own rules from the records |

## 3. Decisions only the owner can make (options in `docs/owner-decisions.md`)

N8 licensing of `src/platform/bios.c` (blocks giving the build to anyone; "Leave for now"); the base game dump for CI
(U31-13); the Node 24 actions patch (U31-16); day counters on the world clock (G13); a ticket source for personal
static legendaries; the character customization scope; the 39 upstream GBA test failures under Gen 6 rules; egg
hatching speed (MS-42); and the "built, your call" items: Xbox B as Cancel, 3D vehicles falling back to 2D, music
loudness, Battle Point shop prices, a launcher checkbox for location privacy.

## 4. Verification only the owner's PCs can give

A real graphics card at 60 fps, a controller, two PCs on a home network and over the Internet (router, UPnP/NAT-PMP),
a fresh install and first play on the owner's PC, and the owner's crash logs if the Safari crash recurs (MS-169).
NU-8, VR-6, WC-4, MS-7 hold the checklists; V21, V39, U30-5 and NU-10 (section 6) are owner tests too.

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
