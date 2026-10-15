# Updates 15-20: final report

Branches: app `claude/dev-update15-20` (head `62bab63` + this report), engine `claude/dev-update15-20-engine` (head `676afe0c`).
Nothing was merged into a default branch; nothing was published. Everything "tested" below is cloud-simulated or headless unless it says otherwise.

## What was implemented
| Update | Result | Where |
|---|---|---|
| 15 True 1v1v1v1 free-for-all | **Done in the native battle engine**: four independent trainers on four rules-sides, any foe targetable, last trainer standing wins (draw if the last fall together), no EXP, no wager, no run; server-authoritative (host desk, protocol, validator, consent, reservation, journal, recovery); durable win record; Players menu and launcher entry offered only when the game advertises it | `docs/free-for-all.md` |
| 16 Complete Battle Frontier | **Done**: team selection from a larger party, Battle Points (persistent, in the save), item rewards, BP shop (debit first, refunds), exactly-once delivery over the wallet stream, anti-duplication, multiplayer consistency, streak and Brains kept, co-op Frontier working | `docs/battle-frontier.md` |
| 17 Legendary catch consistency | **Done**: the game records the catch in its save, the host decides once (restart-safe, retroactive after expiry), the loser's duplicate is released by exact match; no arbitrary save bytes rewritten | `docs/legendary-catch-resolution.md` |
| 18 Graphical PokéNav map | **Done** with the game's own art: other players (per-slot colour), the visible World Event, the outbreak, SELECT jumping, zoom, live refresh; text pages remain; exact missing art listed | `docs/graphical-pokenav-map.md` |
| 19 Final PC feature audit | **Done**: everything re-run; two small defects fixed (stale status text; a marker-palette guard) | `docs/final-pc-audit.md` |
| 20 Windows integration | **Done as far as the cloud goes**: both exes (2D, 3D) and the launcher build; ROM hash pinned and unchanged; private artifact produced (the first CI run failed on an SDL include in the new debug aid, fixed, second run succeeded) | `DEVELOPMENT_LEDGER.md` |

## Is 1v1v1v1 genuinely playable in the native engine?
Yes in the engine: the real battle code runs it (25 free-for-all tests on the GBA test ROM, a four-core native startup test, and the
host/desk/protocol tests), not four 1v1s and not a renamed 2v2. **It has never been played on four PCs.** Known limits: the screen reuses
the doubles layout (a third foe stands in the partner slot); there is no forfeit; the exact visuals are unverified.

## Test results
* App suite: **1756 passed, 50 skipped, 0 failed.**
* Engine native self-tests (`check-native` and 20 selftest targets): **all 0 failures.** New: `--selftest-rewards` 18, `--selftest-catch-reconcile` 11, `--selftest-pokenav-map` 8.
* GBA test ROM (`make check`): **5532 passed, 39 failed = exactly the expected list, 0 new** (6034 total).
* GBA release ROM sha256 **f214735b64e113fd10730eacca5764d757f2c93a3685230aa905af7a7cdd3387, unchanged** after every engine change.
* `abi_layout.py`: 172 types OK.
* Looked at rendered screens headlessly (new debug scene): the Town Map markers, and both native builds booting to Birch's introduction.

## Latest private Windows artifact
GitHub Actions run **38726808703** (`windows-package`, full): artifact `EmeraldTogether-windows-full`, ID 11969537177, 63 MB, sha256 `fff7bbbf…e93610`,
expires 2026-10-22, https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/38726808703 . **bios.c licensing is unresolved; not cleared for distribution.**

## Incomplete or limited (not hidden)
* Free-for-all: doubles layout, no forfeit. Frontier: no real-save BP/items check. Catch reconciliation: a traded or evolved duplicate, and saves from before Update 17, are not reconciled.
* Town Map: event/outbreak markers use borrowed art; indoor places are the middle of the town's section; no hide-my-location setting.
* Existing open items in `KNOWN_ISSUES.md` (fast-forward while connected M7, hint arrow M27, world-day counters G13) are unchanged.

## Owner decisions needed (`docs/owner-decisions.md`)
Free-for-all defaults (hazards per side, no EXP); Frontier BP amounts and shop prices; whether the losing legendary duplicate is released automatically or after a confirmation;
map art and whether players can hide their place; what to do about bios.c.

## Still needs real-PC testing
Everything in `docs/windows-test-update15-20.md` (sections A-D), plus the earlier checklists: four-PC free-for-all, Frontier rounds with a reduced party and BP/items in a real
save, a real two-PC legendary race, the PokéNav map in the 3D window and on Windows, controller/XInput, real network play, existing saves loading in the new build.
