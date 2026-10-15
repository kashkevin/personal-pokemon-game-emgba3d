# Final PC feature audit (Update 19)

Scope: everything the owner listed for the PC build. Method: re-run every automated check that exists, read the status of each area
against the evidence, look at rendered screens with the new headless debug scene, and fix only **confirmed** defects. Nothing here
claims real Windows play, a real network or a real controller: those are in `docs/windows-test-update15-20.md`.

## What was run (this audit, cloud only)
| Check | Result |
|---|---|
| App test suite (Python 3.12 + tkinter, `pytest tests`) | **1756 passed, 50 skipped, 0 failed** (skipped by their own conditions) |
| Engine native self-tests (`check-native`: 1067 + 4307 + 308 + 24154 + 28216 + 176 checks; `check-secret-base` 36, `check-rewards` 18, `check-catch-reconcile` 11, `check-pokenav-map` 8, `check-ladder` 20, `check-coop-exp` 32, `check-coop-controller` 22, `check-keybinds` 21, `check-spawn-claims` 23, `check-mp-objects` 21, `check-clock` 58, `check-wild-weather` 139, `check-line-break` 54, `check-shake-anim` 11, `check-cry-stop` 5, `check-battle-names` 1724, `check-party-order` 1119, `check-decompress` 7682 assets, `check-graphics-mode`) | all **0 failures** |
| `abi_layout.py` (GBA/PC struct layout parity) | 172 types OK |
| GBA test ROM (`make check`, the real battle engine) | **5532 passed, 39 failed = exactly the 39 in `docs/gba-test-expected-failures.txt`, 0 new, 0 listed-but-passing** (6034 total, 1389 s; run at engine `68ca2f02`; the one later engine change is PC-only code in `src/region_map.c`, which the test ROM does not compile) |
| Release GBA ROM hash | **f214735b…3387, unchanged** |
| 2D native game, headless, scripted keys from a cold boot | reaches Birch's introduction with correct pictures; no crash |
| 3D (Diorama) native game, same | same; also renders the PokéNav map screen identically |

## Area by area
"Cloud evidence" is simulated or headless; "Real PC" is what is still unverified.

| Area | Cloud evidence | Real PC (unverified) | Defects found in this audit |
|---|---|---|---|
| Co-op story (twin Gyms, co-op battles, co-op EXP, teammates) | `test_coop_battle`, GBA tests (multiplayer, co-op team selection), `check-coop-exp`, `check-coop-controller`; earlier real two-client run of one Gym (native-launcher-coop-6) | the other seven Gyms; Windows | none |
| Multiplayer Pokémon League | `test_frontier` (43 tests incl. three real desk battles to a clear), `check-ladder` | a full League run on two PCs | none |
| Battle Frontier (survival ladder, team selection, BP, items, BP shop, Brains) | `test_frontier`, `test_rewards`, `test_coop_battle`, `check-rewards`, GBA team-selection tests | BP/items in a real save, new pages on screen | none |
| Secret Bases | `check-secret-base` (36), `test_secret_bases` | visiting a base between two PCs | none |
| PokéNav (text pages, habitat, graphical map) | menu tests, `check-pokenav-map`, rendered screens inspected (own icon, players, event, outbreak, SELECT, zoom, live refresh) | Windows, the 3D window as seen by a user | none (one robustness gap fixed: a full sprite-palette bank now skips a marker instead of drawing it in another colour) |
| Legendary World Events (spawn, claim, conditions, catch ownership, reconciliation) | `test_event_catch`, `test_event_conditions`, `test_world_server` (contested catch over the wire), `check-catch-reconcile` | a real two-PC race | none |
| Trading | ~20 trade test files, native trade runs on Linux/Wine (earlier) | two Windows PCs | none |
| 1v1, 2v2, 1v1v1v1 | GBA battle tests (25 free-for-all tests), `test_native_ffa`, `test_battle_ffa_desk`, earlier real 1v1/2v2 native runs | four real PCs for the free-for-all; the free-for-all's screen layout | none |
| Breeding / eggs (Gen 6 rules) | GBA tests `(Daycare)`, `GetChildNature`, `InheritIVs`, `InheritPokeball`, `InheritAbility`, `(EggHatch)` | an in-game hatch | none |
| Mega Evolution, Gen 6 mechanics | GBA suite (Gen 6 profile; the upstream Mega Evolution tests), 84 Mega records on Gen 1-6 bases | a full Mega battle on a PC | none (the 39 listed upstream failures are the same as before) |
| Character customization | `test_appearance_names`, engine appearance code | the editor in the running game | none |
| Followers, rides | earlier native follower proofs (Linux/Wine), mailbox tests | Windows, long play | none |
| Saving, reconnecting, host loss, recovery | recovery/journal tests (battle, trade, checkpoint), earlier native reconnect runs | a real network drop | none |
| 2D/3D rendering | both builds boot headless; PokéNav map identical in both; earlier graphics evidence | a real GPU, real window sizes/DPI | none |
| Keybinds and XInput | `check-keybinds`, `--selftest-keybinds`, `test_game_controls`; XInput is loaded at run time | a real controller | none |

## Defects confirmed and fixed in this update
1. **Documentation that contradicted the facts:** `FEATURE_STATUS.md` still said "the Windows .exe is not built yet" (private Windows
   packages have been built by GitHub Actions since Update 7); fixed. The Town Map entry no longer says "not built".
2. **Town Map markers:** when every sprite palette bank was taken (an unusually crowded screen) a marker would have been drawn in
   whatever colours the missing bank held. It now draws nothing for that marker. (Found by reading the code while auditing; the
   crowded case cannot be forced in the headless scene, so the fix is covered by review, not by a rendered picture.)

No other defect was confirmed. Items that were *read* and left alone: see `KNOWN_ISSUES.md` (M7 fast-forward while connected, M27 hint
arrow, G13 day counters on world days: all owner decisions or cosmetic).

## Honest limits of this audit
* "No defect found" means no check that exists failed and nothing read looked wrong. It does not mean the features work on a PC:
  every area above still needs the real-PC pass in `docs/windows-test-update15-20.md` and the earlier checklists.
* The headless scene can look at screens that need no host (the PokéNav map). Screens that depend on a live host (the Players menu
  pages, Frontier pages, battle screens) were not looked at.
