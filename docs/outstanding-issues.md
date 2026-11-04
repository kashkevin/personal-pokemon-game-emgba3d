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
| Co-op EXP | Gym EXP farming by losing again; the pending award lost on a reset before the award script | **Fixed** (engines `1b2c0089`, `1552e268`; app: this change): EXP with the badge-earning win only; the waiting result in the save; the launcher saves on the host as the co-op battle ends, the script runs after that save, the host save again after it (retried while the launcher is busy) (`docs/owner-decisions.md` 4-5) | self-test 57/57 (also under Wine); check-native, tower, ladder, update32: 0 failed; app save checks 79 passed; **real two-game run c5 passed** (a game closed during its award came back with the same award, nothing lost or doubled; runs c1-c4 found and fixed two launcher faults: KNOWN_ISSUES MS-190) | not yet | - |
| MS-145 | Kept shinies and Legendaries forgotten when the game closes | **Fixed** (engine `9f0809f6`, app: this change): the keep list is a save record | self-test 24/24 (12 new; also under Wine); app record tests; a real game closed with a kept shiny: not yet | not yet | - |
| MS-161 | Opening a world slows as its saves pile up | **Improved again** (app: this change): about 2x more (600 saves: 2.67 s to 1.1-1.4 s), every check the same; still grows (about 1.9 ms a save); options (b) and (c) in KNOWN_ISSUES MS-161 are the owner's | the reader's equivalence test (5,603 slots); timings on a 600-save test world | not yet | - |
| MS-118 | 3D frame hitches when many chunks come into view at once | **Improved** (engine `9f41e9f3`), still open: chunks keep two earlier versions, so walking back over a seam builds nothing (20 crossings: 237 chunks built instead of 2,109, syncs over 16 ms 42 instead of 156); left: several new chunks at once and the atlas redrawn at a crossing (options in KNOWN_ISSUES MS-118) | A/B walks of the same binary; every chunk taken back built anyway and compared (1,892, 0 differed); 421,888 skipped-sync checks (0 stale); mesh check; check-diorama | not yet | - |
| MS-189 | The 3D rules parity test compares out of step | **Fixed** (engine `49b12c51`): not out of step - both list 325,079 terrain rows (the 332,226 counted the pixel objects' lines too); the test expected the classifier's height and shape where the resolver applies the terrace levels and the tree groups' bodies (also MS-170) | `tools/diorama_rules/test_rules_parity.py`: passed (all 325,079 rows and the pixel objects; every field) | - | - |
| MS-39 | Mega Rayquaza unreachable (no way to learn Dragon Ascent) | **Fixed** (engine `d6e3072e`): Dragon Ascent at level 1 (the Gen 8 and Gen 9 level), offered by the move relearners | `--selftest-megas` (the learnset, the Sky Pillar Rayquaza's moves, the relearner's list, CanMegaEvolve with and without the move and the Mega Ring; also under Wine); ROM unchanged | not yet | - |
| MS-38 | Mega Lucario Z's Aura Guard does nothing | **Fixed** (engine `d6e3072e`): half damage from moves that make contact, Mold Breaker ignores it (the effect from search results: KNOWN_ISSUES MS-38) | `--selftest-megas` (the battle's own damage calculation with the same roll: contact halved, the rest unchanged; also under Wine) | not yet | - |

## 2. Other engineering issues (to be worked through; options documented where a design call is needed)

| Issue | What | Status |
| --- | --- | --- |
| G3 | A World Event's 120 s claim release after a disconnect could let two players catch the same event Pokemon | open (improved before: active seconds only); a gameplay call, so options only: (a) the shared spawns' 600 s grace for events too (rarer, not gone); (b) hold the claim until its claimant comes back and reports the battle (no duplicate, but one absent player can keep an event from everyone); (c) keep 120 s and accept the rare second copy |
| NU-7 | An invite code cannot be revoked for one friend | open (design: per-friend credential rotation) |
| MS-29 | START > PLAYER > RESET sometimes does not open PLAYERS (the player is told to try again) | **Fixed** (engine `62da105f`, PC only): the START menu ends a turn in place, so the field is at rest; `--selftest-start-menu` 12/12 (the new check fails without the fix); not run in a real game process |
| MS-55 | A new Players menu page opens with the previous page's cursor row | open (cosmetic); options in KNOWN_ISSUES MS-55: the game cannot tell a new page from a refresh by its title (the Tower's pages name their floors), so a fix needs the launcher to say so (a flag in the screen's spare bytes, an ABI addition in both repos) |
| MS-52 | The native Tower screens show the game's copy of the record until the next word | open (cosmetic) |
| MS-154 | 6 ledges the player cannot jump land a level higher in 3D | partly fixed |
| MS-108 | Transitions' pictures still the GBA's art | open (art) |
| VR-5 | 226 of 959 battle animations have no HD version | open (art) |
| MS-9 | The emulator fallback's Lua bridge has the same all-zero check as the old native one | open (fallback only) |
| MS-26 | Save checks on the launcher's and host's event loops | measured, no player-visible cost found |
| Trades | Eggs, mail and unsupported forms are refused in trades | open (adapter work) |
| G1 | An evolution trade that must choose a move for a Pokemon knowing a post-Gen-6 move is refused | open (owner decision recorded: such moves trade unchanged; the move-choice path still refuses) |
| MS-141c limits | Wireless minigames: four players not run | open |
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
NU-8, VR-6, WC-4, MS-7 hold the checklists.

## 5. Windows CI coverage of the newest work

Run 271 (2026-11-04 morning) covered engine `2054cf05`. Run 273 (started 16:47 UTC, engine `49b12c51`, app
`6952acc`) covers section 1's fixes up to MS-189 (its results are recorded here when it ends). Not in it: MS-118's
change (engine `9f41e9f3`) and 21 engine self-tests the Windows job did not run until now (the wireless minigames
with computer partners and over the world among them: `netlink`, `minigame-partners`; also Frontier saves, trade
evolutions, items); the workflow now runs every self-test but the 5-minute statistical shiny audit. A Windows job for
the minigames between two real games (`native_launcher_minigame_proof.py` has no Windows mode yet) is being added.
The installer is prepared only from a run whose every required job passes, and is not distributed (N8).
