# Coverage audit, Windows first (2026-10-22)

What each part of the game was tested with, and where. **Windows** means GitHub's hosted `windows-2022` runners in the
`windows-package` workflow: real Windows game processes of the MinGW build, driven by key presses and judged from the
games' memory, their own logs and the host's records. It is not a player's PC: the runner has no graphics card (the
Classic 2D game draws with Windows' software renderer; the 3D game ran only through Mesa's software OpenGL), every
player's game runs on one machine over loopback, and nobody watched the screens. **Linux** means the cloud session's
Classic 2D PC game under Xvfb (and the engine's GBA test ROM, `T`); a Linux pass is never counted as a Windows pass.

Statuses: **Passed on Windows**, **Passed on Linux only**, **Failed**, **Blocked**, **Unverified**, **Not implemented**.
Commits: app `claude/admiring-bohr-dpxzuy`, engine `claude/feature-update-engine`. Windows runs: 121 (app `6a3639e`,
engine `a5ce214d`), 129 (app `c5c2a35`, engine `a5ce214d`), 133 (app `26a6e15`, engine `b1066514`; section 5), 138 (app
`341e505`, engine `83808e7e`: 41 of 42), 141 (app `a2ce0a2`, engine `da278011`: 43 of 45 at 07:20 UTC, the climb
still running), 143 (app `fa6e601`, engine `da278011`: the `ffa-exit` check alone, four attempts).

## 1. The newest updates

| Feature | Status | Windows evidence | Linux / other evidence |
| --- | --- | --- | --- |
| Battle Tower: every floor won and lost (100 floors, test build's real solo start) | **Passed on Windows** | runs 121 and 129: 200 of 200 runs each; Mega forms seen on 44 won floors (`docs/battle-tower-floors-20261022.md`) | 200/200 (engine `547b2950`) |
| Battle Tower: experience caps, Bottle Cap, Gold Bottle Cap, Hyper Training, Ability Patch in the real menus | **Passed on Windows** | runs 121, 129 | S, L |
| Battle Tower: Duo (native co-op battle with a host-formed team) | **Passed on Windows** | runs 121, 129 (settled for both players) | L tower-duo-3 |
| Battle Tower: Mega Duo (floor 40, the boss's Kangaskhan Mega Evolves) | **Passed on Windows** | runs 121, 129 | L tower-mega-2 |
| Battle Tower: forfeit (the joiner's forfeit counts as a loss, the host's world stays up) | **Passed on Windows** | runs 121, 129 | L tower-forfeit-2 |
| Battle Tower: milestone Pokemon (floor 25, made in the game, delivered once, replay without a second) | **Passed on Windows** | run 133 end to end; run 129 the milestone part (claims 4100, no second prize) | L tower-milestone-2 |
| Battle Tower: solo climb through the launcher, prizes, replay, Tower Shop, special boss loss to its checkpoint | **Passed on Windows** | run 133 end to end (floors 1-11, Brock's prize, the replay, the HP Up for 16 BP, the saved wallet as the rules say; player 2 back to floor 21 after Giovanni) | L tower-solo-9 |
| Battle Tower: native 3D UI pages | **Passed on Windows** (Mesa software OpenGL only) | runs 138 and 141 (the `ui` entry, pinned Mesa) | L tower-ui-5: ten pages pictured, saves, fresh Continue, integrity check |
| Battle Tower: a whole 100-floor climb through the launcher | **Unverified** (running on both) | run 141's climb job, running since 05:00 UTC | L tower-climb-3 (fast-text fixtures), past floor 90 at 2.5 h |
| Co-op team selection (MS-47, engine `0df64e01`) | **Passed on Windows** | runs 121, 129 (Tower Duo and Mega Duo with six-Pokemon parties) | T 3/3, L |
| Battle Points the game received since its save (MS-53, app `8c668bc`) | **Passed on Windows** | run 133 (solo, milestone) | L tower-solo-8/9; app tests |
| Shop orders finish after the menu closes (MS-54, app `a100436`) | **Passed on Windows** | run 133 (solo) | L tower-solo-9; app tests |
| Breeding and egg hatching (the Day Care man's Egg, Everstone, Destiny Knot, ball, Egg move, hatching, saves) | **Passed on Windows** | runs 121, 129 | L |
| Evolution: Rare Candy, stopped with B, Fire Stone, after a won battle (engine `3446295c`) | **Passed on Windows** | run 133 (new evolve-check job: all eight steps) | L 8/8 steps |
| Update 31 rival checkpoints (field scripts: gates, rewards once, NPC rivals away, the battle's environment, host gone mid-scene) and the short introduction | **Passed on Windows** | run 133 (new rival-check job: every scene, `rival_check: 0 failed`) | L: 25/25 in Update 31's integration; 4 scenarios in the new file mode |
| Update 31 rival checkpoint battle between players (the gate, the lobby, the challenge, the battle, completion, the reward) | **Passed on Linux only**; Windows run 141 **failed on the proof's own race** (fixed, app `a16fdcf`) | run 141: the gate, both votes, the session, the 1v1 to a durable result (108 s) passed; the proof then read the host's checkpoint 4 s after the result, before the host had completed it, and failed. Rerun in the next full run | L rival-1 (two players: gate, votes, challenge, native 1v1 to its end, completion "via battle", the Dowsing Machine and VAR_ROUTE110_STATE in both saves); L rival-3p-1 (three players: the round robin of three 1v1s); L rival-4p-1 (four players: one 2v2, full Multi, to its result); engine self-test `rival` passed in the Windows build |
| Update 32: starters in Birch's lab, soft reset rerolls, shiny odds | **Passed on Windows** | runs 121, 129 (starters job); self-tests `update32` (35 checks; run 133 after the console fix) and `shiny` (run 129) | L |
| Mega Evolution, single player: every case, all 96 holders, the stones and the Mega Ring in the menus, normal and shiny parades | **Passed on Windows** | run 121: 97 of 97 | L |
| Mega Evolution drawn in 3D (wild, trainer, the 96-form parade) | **Passed on Windows** (Mesa software OpenGL only) | run 129 (Mesa 26.2.4 llvmpipe; pinned since) | - |
| Mega Evolution in a multiplayer battle (both players; one without the Mega Ring) | **Passed on Windows** | run 133: two and no-ring end to end (run 129 stopped on the proof's own picture: harness, fixed `26a6e15`) | L (earlier sessions) |
| Interrupted battles: pairs crash, multi-battle network loss, free-for-all exit, free-for-all host crash | **Passed on Windows** except while MS-57 is open | runs 129, 133, 141 every scenario; run 138's `ffa-exit` and run 143's attempt 2 of 4 failed in the rematch with MS-57 (the host knocked out while the free-for-all went on) | L; MS-57 reproduced (ffa-exit-diag-1, double-2, ffa-exit-gdb-5) |
| A host knocked out while the battle goes on (KNOWN_ISSUES MS-57: a free-for-all, the same path in a 2v2 or co-op battle) | **Failed** before the fix; the fix (engine `65641401` and the app's check) **Passed on Linux only** (free-for-all and 2v2) | `ffa-knockout` and `multi-knockout` (deterministic: the host out on turn 1) run first in run 145, twice each | L: double-2 failed on turn 1 (pre-fix); knockout-fixed-1 failed on the app's check (the engine half only); **knockout-fixed-2 passed end to end with both halves** (the host out on turn 1, the free-for-all to its result in 293 s); **knockout-2v2-1 passed** (the 2v2, 253 s); the test ROM 142/142 and the app's controller tests pass with the fix |
| Engine self-tests in the Windows build (24) | **Passed on Windows** (24 of 24) | run 133 (`update32` 35 checks after the console fix: engine `b1066514`, app `bc8ca31`; run 129 had 23 of 24) | L 24/24 |

## 2. The whole game

| Area | Status | Windows evidence | Linux / other evidence |
| --- | --- | --- | --- |
| Character creation (New Game's short introduction, boy and girl) | **Passed on Windows** | every multiplayer job makes its characters with the game's own introduction (runs 121, 129); the starter job | L |
| Zero-Pokemon refusals (trade, challenge, lobby) | **Passed on Windows** | `mixed` (runs 121, 129) | L |
| Starters: the claim in Birch's lab, one per character, simultaneous claims | **Passed on Windows** | newcomers proofs, starters job | L |
| Hosting and joining a world, 2 to 4 players | **Passed on Windows** | every multiplayer and Tower job | L |
| 1v1 | **Passed on Windows** | `busy` (host against player 2) | L |
| 1v1v1 | **Passed on Windows** | `lobby` with three, `mixed` | L |
| 1v1v1v1 | **Passed on Windows** | `lobby` with four | L |
| 2v2 | **Passed on Windows** | `mixed`'s second lobby | L |
| Trading | **Passed on Windows** | `busy` (each holding the other's starter afterwards; resets refused during the offer) | L |
| Visibility of other players (everyone draws everyone) | **Passed on Windows** | `lobby`, `busy` | L |
| Disconnect and reconnect | **Passed on Windows** | `lobby` (player 2's connection cut, rejoined), the four interrupted battles | L |
| Save and load | **Passed on Windows** | every proof's closing saves and a fresh Continue; breeding's two saves; the Tower's canonical checkpoints | L |
| Every reachable map's people, signs, items, hidden items, trainers, warps, coordinate triggers | **Passed on Windows** | run 133: 3,612 targets passed (1,049 people, 512 signs, 1,041 warps, 237 triggers, 162 items, 109 hidden items, 502 trainers), none failed, 617 blocked by the game's own story state (hidden objects, closed doors). Run 129's one failure (`warp:MAP_ABANDONED_SHIP_ROOMS_1F:5`) was the test runner's: a trainer who turned toward the player between two targets and was never answered (fixed in engine `83808e7e`; run 138 runs it) | L: the fix's A/B (the old runner hung in 6 of 8 runs, the fixed one passed 12 of 12) |
| Story events (coordinate triggers, scenes) | **Passed on Windows** (the reachable ones) | the gameplay check's triggers; rival scenes in run 133 | L |
| Menus (start menu, Bag, party, trainer card, options, PLAYERS pages) | **Passed on Windows** | `busy` (trainer card, options), the Bag uses of the Mega and items checks, every Tower and multiplayer page | L |
| Inventory: using items from the Bag | **Passed on Windows** | Bottle Caps, Ability Patch, Mega Stones and the Mega Ring; a Rare Candy and a Fire Stone (run 133's evolution check) | L |
| Catching wild Pokemon (a Ball from the battle's Bag, the party or the PC, the Pokedex) | **Passed on Windows** | run 141 (the catch-check job, its first run) | L: the catch check (a Master Ball; a party of five keeps the catch, a full party sends it to the PC; the Pokedex's caught count; saved and loaded) |
| Shops | **Passed on Windows** | Mega Stones and the Mega Ring bought with Game Corner coins (Mega check items step); the Tower Shop's HP Up for 16 BP (run 133); a Potion bought at the Oldale Mart and sold back, saved and loaded (runs 138, 141) | L: the shop check |
| Battle mechanics (moves, Abilities, held items) | Exercised on Windows; exhaustively only in T | every battle the Windows jobs play (400 Tower battles, 502 trainer battles of the gameplay check, the Mega cases, the multiplayer battles) | T: the engine's GBA test ROM (the same battle code, compiled for the GBA, on Linux); no exhaustive battle suite runs in the Windows build (limitation) |
| Battle animations | **Passed on Windows** | the Mega check's picture series (2D), the 3D Mega series and parade through Mesa | L |
| Classic 2D graphics | **Passed on Windows** (software renderer) | every job; the package's graphics mode check | L |
| 3D graphics | **Passed on Windows** through Mesa only | run 129's graphics-3d job (llvmpipe, OpenGL 4.6); no GPU or vendor driver | L (Xvfb llvmpipe) |
| Performance | **Unverified** on Windows for a player's PC | the graphics-3d job's informational benchmark (the 3D view at 1280x720 through Mesa's llvmpipe, from run 138) says the 3D view runs on Windows at that rate, nothing about a graphics card | L: 8.9 fps average at 720p under Xvfb's llvmpipe; earlier updates' benchmarks |
| Installer: silent install, start, repair, uninstall, Create World, character, Solo, Host World, Join Friend on the installed build | **Passed on Windows** | runs 121, 129 (installation check) | - |
| Two or more physical PCs, a home network, the Internet relay | **Unverified** | the runner plays every player on one machine (KNOWN_ISSUES MS-7) | - |

## 3. Open issues that touch what was tested

MS-51 (Low, open): a milestone Pokemon can be lost in a narrow case. MS-52 (Low, cosmetic): native Tower screens show
the game's copy of the record until the host's word arrives. MS-49's remainder: a game below about 22 frames a second
could start a floor after the host's two minutes. MS-38 (Medium, open): Mega Lucario Z's Aura Guard does nothing.
MS-39 (Low, owner decision): Mega Rayquaza cannot be reached. MS-28 (Medium, mixed versions only). MS-29 (Low).
MS-17 is fixed and verified (2026-10-21); the multiplayer jobs of runs 121, 129 and 133 that would show it (battle starts
and deliveries in two to four Windows games) all passed. MS-57 (High, fixed, verification running): a battle stopped
for everyone once the host's battler was out of Pokemon while it went on; it was MS-17's two free-for-all recurrences
too. MS-58 (Low, cosmetic, fixed): a 2v2 rival match's row. MS-59 (closed, not a defect): the gdb instrument. MS-53 and MS-54 are verified on Windows (run 133). MS-55 (Low,
cosmetic, open): a new Players menu page opens with the cursor on the row chosen on the page before. The gameplay
check's Abandoned Ship hang was the test runner's (fixed, section 2).

## 4. Limitations

No player's PC, no graphics card, no vendor OpenGL driver, no second machine and no real network were used; every
"Passed on Windows" above is a hosted runner's result. The Battle Tower's 3D screens were shown on Linux only (Windows
through Mesa only); the rival checkpoint battle between players was never shown on any platform. Performance on
Windows was measured only through Mesa's software renderer (informational). The battle mechanics' full suite runs only
in the GBA test ROM on Linux.

## 5. Run 133 and the release candidate

Run 133 (app `26a6e15`, engine `b1066514`, https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39710794241):
every job passed - build, symbol sizes, package, installation check, starters and soft resets, breeding, evolution (new),
rival checkpoints (new), self-tests 24 of 24, 3D graphics through Mesa, the four Tower floor shards, caps and items, the
five Tower proofs (solo and milestone end to end for the first time on Windows), the four interrupted battles, the four
multiplayer jobs, both multiplayer Mega proofs, and the gameplay check's eight shards (3,612 targets, none failed). Its
Mega Evolution check was still running when this was updated (TEST_LEDGER.md records it).

Run 138 (app `341e505`, engine `83808e7e`, https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39716739086):
the release candidate, with the newest jobs: the Poke Mart check, the Tower's 3D UI through Mesa, the pinned Mesa and the
informational benchmark, and the gameplay runner's fix. 41 of 42 jobs passed; the interrupted battle `ffa-exit` failed
in its rematch (MS-57), so it was not the release.

Run 141 (app `a2ce0a2`, engine `da278011`, https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39723669535):
the catch check, the rival checkpoint battle between players and the Tower's 100-floor climb added. 43 of 45 jobs had
passed at 07:20 UTC (`ffa-exit` among them this time); the rival battle failed on the proof's own race (fixed) and the
climb was still running.

Run 143 (app `fa6e601`, https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39726406080): the
`ffa-exit` check alone, four attempts side by side: three passed, attempt 2 failed with MS-57 and the proof's new
diagnosis named it. The next full run carries both halves of MS-57's fix and the deterministic `ffa-knockout` check.
