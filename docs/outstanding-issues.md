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
| MS-51 | Battle Tower milestone Pokemon lost when the game closed before saving and the older save had no room | **Fixed** (engine `36fb4589`, app: this change) | self-test 2,103/2,103 (the real game code: a full party and PC answer 0, the host's replayed claims change nothing, the resend makes it); app tests 173 | not yet | - |
| Co-op EXP | Gym EXP farming by losing again; the pending award lost on a reset before the award script | **Fixed** (engines `1b2c0089`, `1552e268`; app: this change): EXP with the badge-earning win only; the waiting result in the save; the launcher saves on the host as the co-op battle ends, the script runs after that save, the host save again after it (retried while the launcher is busy) (`docs/owner-decisions.md` 4-5) | self-test 57/57 (also under Wine); check-native, tower, ladder, update32: 0 failed; app save checks 79 passed; **real two-game run c5 passed** (a game closed during its award came back with the same award, nothing lost or doubled; runs c1-c4 found and fixed two launcher faults: KNOWN_ISSUES MS-190) | the next run's new coop-proof job (a game closed during its award, in Windows game processes) | - |
| MS-145 | Kept shinies and Legendaries forgotten when the game closes | **Fixed** (engine `9f0809f6`, app: this change): the keep list is a save record | self-test 24/24 (12 new; also under Wine); app record tests; **a real game closed and started again with four kept shinies: all four back, drawn shiny** (`shiny_check.py` keep-restart, engine `7f9b56bf`) | not yet | - |
| MS-161 | Opening a world slows as its saves pile up | **Improved again** (app: this change): about 2x more (600 saves: 2.67 s to 1.1-1.4 s), every check the same; still grows (about 1.9 ms a save); options (b) and (c) in KNOWN_ISSUES MS-161 are the owner's | the reader's equivalence test (5,603 slots); timings on a 600-save test world | not yet | - |
| MS-118 | 3D frame hitches when many chunks come into view at once | **Improved** (engine `9f41e9f3`), still open: chunks keep two earlier versions, so walking back over a seam builds nothing (20 crossings: 237 chunks built instead of 2,109, syncs over 16 ms 42 instead of 156); left: several new chunks at once and the atlas redrawn at a crossing (options in KNOWN_ISSUES MS-118) | A/B walks of the same binary; every chunk taken back built anyway and compared (1,892, 0 differed); 421,888 skipped-sync checks (0 stale); mesh check; check-diorama; **the same walk under AddressSanitizer** (engine `7f9b56bf`): no report, 1,882 taken back, 0 differed, 0 stale | not yet | - |
| MS-192 | Windows run 273's Tower Duo proofs (duo, mega, join, join-reset) waited 30 minutes after their Duo battles | **Fixed** in the proof (app: this change): since MS-190 the launcher saves as a co-op battle ends and the game again after a Tower floor's result, which the proof did not expect; the game and launcher unchanged | `native_launcher_tower_proof.py` duo and join passed (real games, real launchers) | **run 277**: duo, mega, join and join-reset passed | - |
| MS-189 | The 3D rules parity test compares out of step | **Fixed** (engine `49b12c51`): not out of step - both list 325,079 terrain rows (the 332,226 counted the pixel objects' lines too); the test expected the classifier's height and shape where the resolver applies the terrace levels and the tree groups' bodies (also MS-170) | `tools/diorama_rules/test_rules_parity.py`: passed (all 325,079 rows and the pixel objects; every field) | - | - |
| MS-39 | Mega Rayquaza unreachable (no way to learn Dragon Ascent) | **Fixed** (engine `d6e3072e`): Dragon Ascent at level 1 (the Gen 8 and Gen 9 level), offered by the move relearners | `--selftest-megas` (the learnset, the Sky Pillar Rayquaza's moves, the relearner's list, CanMegaEvolve with and without the move and the Mega Ring; also under Wine); ROM unchanged | not yet | - |
| MS-38 | Mega Lucario Z's Aura Guard does nothing | **Fixed** (engine `d6e3072e`): half damage from moves that make contact, Mold Breaker ignores it (the effect from search results: KNOWN_ISSUES MS-38) | `--selftest-megas` (the battle's own damage calculation with the same roll: contact halved, the rest unchanged; also under Wine) | not yet | - |

## 2. Other engineering issues (to be worked through; options documented where a design call is needed)

| Issue | What | Status |
| --- | --- | --- |
| G3 | A World Event's 120 s claim release after a disconnect could let two players catch the same event Pokemon | open (improved before: active seconds only); a gameplay call, so options only: (a) the shared spawns' 600 s grace for events too (rarer, not gone); (b) hold the claim until its claimant comes back and reports the battle (no duplicate, but one absent player can keep an event from everyone); (c) keep 120 s and accept the rare second copy |
| NU-7 | An invite code cannot be revoked for one friend | open; options (KNOWN_ISSUES NU-7, not gameplay, how friends join): (a) replace one friend's code (a new credential written crash-safe to the database and `host.json`, the friend's game takes the new code for the same account; about a day), recommended; (b) block an account until let in again (half a day; the leaked code works again after); (c) leave it (a new world stops a leaked code) |
| MS-29 | START > PLAYER > RESET sometimes does not open PLAYERS (the player is told to try again) | **Fixed** (engine `62da105f`, PC only): the START menu ends a turn in place, so the field is at rest; `--selftest-start-menu` 12/12 (the new check fails without the fix); not run in a real game process |
| MS-55 | A new Players menu page opens with the previous page's cursor row | open (cosmetic); options in KNOWN_ISSUES MS-55: the game cannot tell a new page from a refresh by its title (the Tower's pages name their floors), so a fix needs the launcher to say so (a flag in the screen's spare bytes, an ABI addition in both repos) |
| MS-52 | The native Tower screens show the game's copy of the record until the next word | open (cosmetic) |
| MS-154 | 6 ledges the player cannot jump land a level higher in 3D | partly fixed |
| MS-108 | Transitions' pictures still the GBA's art | open (art) |
| VR-5 | 226 of 959 battle animations have no HD version | open (art) |
| MS-9 | The emulator fallback's Lua bridge has the same all-zero check as the old native one | open (fallback only) |
| MS-26 | Save checks on the launcher's and host's event loops | measured, no player-visible cost found |
| Trades | Eggs, mail and unsupported forms are refused in trades | open (adapter work) |
| G1 | An evolution trade that must choose a move for a Pokemon knowing a post-Gen-6 move is refused | **Fixed** (app: this change): the owner's decision applied, such moves trade unchanged; the move being learned stays a Gen 6 one; unit tests only (L), no real trade with such a Pokemon |
| MS-141c limits | Wireless minigames: four players not run | **Run** (app: this change): all three with four world players on Linux (L, real games and launchers; the proof's focus timing fixed for Pokemon Jump); Windows run 277 passed two and three players (W); four on Windows: the next run's new jobs |
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

Run 271 (2026-11-04 morning) covered engine `2054cf05`. Run 273 (16:47 UTC, engine `49b12c51`, app `6952acc`):
54 jobs passed (the self-tests, the multiplayer gameplay of two to four players, every interrupted battle, saving
and the installation check, 3D graphics through Mesa, the Mega, Tower, rival, breeding and gameplay checks), 4
failed (the Tower Duo proofs, MS-192: the proof's expectation, fixed); its installer is not the next one. The next
full run takes engine `9f41e9f3` (MS-118) and app with MS-192's fix, all 54 engine self-tests but the 5-minute
statistical shiny audit (21 more than before: the wireless minigames' `netlink` and `minigame-partners`, Frontier
saves, trade evolutions, items), and a new job: the three wireless minigames between real games in Windows game
processes (`minigame-proof`; the proof's Windows mode passed Berry Crush on Linux). The installer is prepared only
from a run whose every required job passes, and is not distributed (N8).

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
