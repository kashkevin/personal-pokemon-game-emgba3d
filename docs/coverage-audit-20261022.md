# Coverage audit, Windows first (2026-10-22)

What each part of the game was tested with, and where. **Windows** means GitHub's hosted `windows-2022` runners in the
`windows-package` workflow: real Windows game processes of the MinGW build, driven by key presses and judged from the
games' memory, their own logs and the host's records. It is not a player's PC: the runner has no graphics card (the
Classic 2D game draws with Windows' software renderer; the 3D game ran only through Mesa's software OpenGL), every
player's game runs on one machine over loopback, and nobody watched the screens. **Linux** means the cloud session's
Classic 2D PC game under Xvfb (and the engine's GBA test ROM, `T`); a Linux pass is never counted as a Windows pass.

Statuses: **Passed on Windows**, **Passed on Linux only**, **Failed**, **Blocked**, **Unverified**, **Not implemented**.
Commits: app `claude/admiring-bohr-dpxzuy`, engine `claude/feature-update-engine`. Windows runs: 121 (app `6a3639e`,
engine `a5ce214d`), 129 (app `c5c2a35`, engine `a5ce214d`), 133 (app `26a6e15`, engine `b1066514`: running when this
was written; its results are added in section 5).

## 1. The newest updates

| Feature | Status | Windows evidence | Linux / other evidence |
| --- | --- | --- | --- |
| Battle Tower: every floor won and lost (100 floors, test build's real solo start) | **Passed on Windows** | runs 121 and 129: 200 of 200 runs each; Mega forms seen on 44 won floors (`docs/battle-tower-floors-20261022.md`) | 200/200 (engine `547b2950`) |
| Battle Tower: experience caps, Bottle Cap, Gold Bottle Cap, Hyper Training, Ability Patch in the real menus | **Passed on Windows** | runs 121, 129 | S, L |
| Battle Tower: Duo (native co-op battle with a host-formed team) | **Passed on Windows** | runs 121, 129 (settled for both players) | L tower-duo-3 |
| Battle Tower: Mega Duo (floor 40, the boss's Kangaskhan Mega Evolves) | **Passed on Windows** | runs 121, 129 | L tower-mega-2 |
| Battle Tower: forfeit (the joiner's forfeit counts as a loss, the host's world stays up) | **Passed on Windows** | runs 121, 129 | L tower-forfeit-2 |
| Battle Tower: milestone Pokemon (floor 25, made in the game, delivered once, replay without a second) | **Passed on Windows** (the milestone part) | run 129: claims 4100, the replay paid no second prize; the run then stopped at the shop (MS-53, fixed after) | L tower-milestone-2 |
| Battle Tower: solo climb through the launcher, prizes, replay, Tower Shop, special boss loss to its checkpoint | **Passed on Linux only** so far | runs 121/129 failed at the shop (MS-53, then MS-54: both fixed); run 133 has both fixes | L tower-solo-9 passed end to end |
| Battle Tower: native 3D UI pages | **Unverified** | the 3D UI was never drawn on a Windows runner (no OpenGL 3.3 without Mesa; the Tower proof's `ui` scenario is not ported to Mesa) | not run on Linux either |
| Battle Tower: a whole 100-floor climb through the launcher | **Unverified** | not run | not run (`climb` scenario exists) |
| Co-op team selection (MS-47, engine `0df64e01`) | **Passed on Windows** | runs 121, 129 (Tower Duo and Mega Duo with six-Pokemon parties) | T 3/3, L |
| Battle Points the game received since its save (MS-53, app `8c668bc`) | **Passed on Linux only** | run 133 | L tower-solo-8/9; app tests |
| Shop orders finish after the menu closes (MS-54, app `a100436`) | **Passed on Linux only** | run 133 | L tower-solo-9; app tests |
| Breeding and egg hatching (the Day Care man's Egg, Everstone, Destiny Knot, ball, Egg move, hatching, saves) | **Passed on Windows** | runs 121, 129 | L |
| Evolution: Rare Candy, stopped with B, Fire Stone, after a won battle (engine `3446295c`) | **Passed on Linux only** | run 133 (new evolve-check job) | L 8/8 steps |
| Update 31 rival checkpoints (field scripts: gates, rewards once, NPC rivals away, the battle's environment, host gone mid-scene) and the short introduction | **Passed on Linux only** | run 133 (new rival-check job, engine `6e62d3f5`'s PKMN_DEBUG_LOG) | L: 25/25 in Update 31's integration (and 25/25 under Wine then: not Windows); this session 4 scenarios in the new file mode |
| Update 31 rival checkpoint battle between players (the lobby, formats, completion) | **Unverified** | never played in real games on any platform (FEATURE_STATUS) | engine self-test `rival` passed in the Windows build (run 129) |
| Update 32: starters in Birch's lab, soft reset rerolls, shiny odds | **Passed on Windows** | runs 121, 129 (starters job); self-tests `update32` (35 checks; run 133 after the console fix) and `shiny` (run 129) | L |
| Mega Evolution, single player: every case, all 96 holders, the stones and the Mega Ring in the menus, normal and shiny parades | **Passed on Windows** | run 121: 97 of 97 | L |
| Mega Evolution drawn in 3D (wild, trainer, the 96-form parade) | **Passed on Windows** (Mesa software OpenGL only) | run 129 (Mesa 26.2.4 llvmpipe; pinned since) | - |
| Mega Evolution in a multiplayer battle (both players; one without the Mega Ring) | **Passed on Linux only**; Windows reached the Megas | run 129: both Mega Evolutions happened, then the proof stopped on its own picture (harness, fixed `26a6e15`); run 133 | L (earlier sessions) |
| Interrupted battles: pairs crash, multi-battle network loss, free-for-all exit, free-for-all host crash | **Passed on Windows** | run 129 (first Windows run) | L |
| Engine self-tests in the Windows build (24) | 23 **Passed on Windows**, `update32` **Failed** on the runner's console (environment) | run 129; run 133 has the fix (engine `b1066514`, app `bc8ca31`) | L 24/24 |

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
| Every reachable map's people, signs, items, hidden items, trainers, warps, coordinate triggers | **Passed on Windows** except 1 target | run 129: 3,609 targets passed (1,048 people, 512 signs, 1,039 warps, 237 triggers, 162 items, 109 hidden items, 502 trainers), 1 failed (`warp:MAP_ABANDONED_SHIP_ROOMS_1F:5`, a hang; under investigation), the rest blocked by the game's own story state (hidden objects, closed doors) | L gameplay runs; that map's warps pass alone |
| Story events (coordinate triggers, scenes) | **Passed on Windows** (the reachable ones) | the gameplay check's triggers; rival scenes in run 133 | L |
| Menus (start menu, Bag, party, trainer card, options, PLAYERS pages) | **Passed on Windows** | `busy` (trainer card, options), the Bag uses of the Mega and items checks, every Tower and multiplayer page | L |
| Inventory: using items from the Bag | **Passed on Windows** | Bottle Caps, Ability Patch, Mega Stones and the Mega Ring | L (evolution items too) |
| Shops | **Passed on Windows** in part | Mega Stones and the Mega Ring bought with Game Corner coins (Mega check items step); the Tower Shop in run 133 | L Tower Shop; a Poke Mart purchase with money is not checked on either platform (**Unverified**) |
| Battle mechanics (moves, Abilities, held items) | Exercised on Windows; exhaustively only in T | every battle the Windows jobs play (400 Tower battles, 502 trainer battles of the gameplay check, the Mega cases, the multiplayer battles) | T: the engine's GBA test ROM (the same battle code, compiled for the GBA, on Linux); no exhaustive battle suite runs in the Windows build (limitation) |
| Battle animations | **Passed on Windows** | the Mega check's picture series (2D), the 3D Mega series and parade through Mesa | L |
| Classic 2D graphics | **Passed on Windows** (software renderer) | every job; the package's graphics mode check | L |
| 3D graphics | **Passed on Windows** through Mesa only | run 129's graphics-3d job (llvmpipe, OpenGL 4.6); no GPU or vendor driver | L (Xvfb llvmpipe) |
| Performance | **Unverified** on Windows | no frame-time measurement in the Windows jobs; a hosted runner without a graphics card says nothing about a player's PC | L benchmarks (earlier updates) |
| Installer: silent install, start, repair, uninstall, Create World, character, Solo, Host World, Join Friend on the installed build | **Passed on Windows** | runs 121, 129 (installation check) | - |
| Two or more physical PCs, a home network, the Internet relay | **Unverified** | the runner plays every player on one machine (KNOWN_ISSUES MS-7) | - |

## 3. Open issues that touch what was tested

MS-51 (Low, open): a milestone Pokemon can be lost in a narrow case. MS-52 (Low, cosmetic): native Tower screens show
the game's copy of the record until the host's word arrives. MS-49's remainder: a game below about 22 frames a second
could start a floor after the host's two minutes. MS-38 (Medium, open): Mega Lucario Z's Aura Guard does nothing.
MS-39 (Low, owner decision): Mega Rayquaza cannot be reached. MS-28 (Medium, mixed versions only). MS-29 (Low).
MS-17 is fixed and verified (2026-10-21); the multiplayer jobs of runs 121 and 129 that would show it (battle starts
and deliveries in two to four Windows games) all passed. The gameplay check's Abandoned Ship warp (section 2) is under investigation.

## 4. Limitations

No player's PC, no graphics card, no vendor OpenGL driver, no second machine and no real network were used; every
"Passed on Windows" above is a hosted runner's result. The Battle Tower's 3D screens and the rival checkpoint battle
between players were never shown on any platform. Performance on Windows was not measured. The battle mechanics' full
suite runs only in the GBA test ROM on Linux.

## 5. Run 133 (the release candidate's first full run)

Pending at the time of writing; see TEST_LEDGER.md for its results as they are recorded.
