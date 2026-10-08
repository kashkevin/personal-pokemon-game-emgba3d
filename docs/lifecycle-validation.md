# Launcher lifecycle validation, October 8, 2026

The complete Python suite passed on both platforms at frozen source `1b7c75013d570de8f33d75f2a29bdbe67003114c`. This integrates five-minute autosave, its persistent per-character off switch, independent **Save now**, durable battle reservations and startup admission, the optional emergency protocol, Windows path checks, and enrollment/exit handling. The native emergency prototype remains disabled and is excluded from the qualified Windows runtime.

| Platform | Interpreter | Result | Test duration |
| --- | --- | --- | --- |
| Windows | Pinned host-provisioning environment, Python 3.14.4 | 834 passed, zero skips | 368.571 seconds |
| Ubuntu under WSL | Pinned host-provisioning environment, Python 3.12.3 | 834 passed, zero skips | 201.221 seconds |

Both commands were `python -m unittest discover -s tests -v`, with `src` and `tests` on `PYTHONPATH`. Windows ran below normal priority; WSL used `nice -n 19`. There were at most two concurrent test/build workers. Real Tk fixture widgets and Lua bridge checks ran, without desktop input or Computer Use. These elapsed times measure the test suites, not game performance.

Each run used its own immutable Git archive. All 258 files remained unchanged throughout each run. Python source matched byte-for-byte between the two archives. Seven non-Python text files differed only by the platforms' Git line-ending conversion; that comparison is retained in the private cross-platform source record.

The optional read-only Flash validation ran against both original private characters. Their before/after SHA-256 values remained `8d611857e848f68ff3624d8540704d7e70ed4115326f82e304408587df9f3bf6` and `28075aba43fcd5b862c9c6b2a64c06318ffabff4ff95d02c696aabe1e731db17`. No original character was enrolled, replaced, migrated or written by this validation.

## Save and shutdown correction

Independent review found that a connection-loss status could hide an uncertain autosave warning and let normal process exit report ordinary closure. The corrected launcher preserves save-recovery status even when disconnected. A separate idle IPC shutdown can clear its warning only after a confirmed zero process exit, drained operations and a final check for unresolved exports. Dispatched/uncertain saves, earlier genuine failures, retained journals and nonzero exits retain recovery status. A changed live connection or incarnation cannot restart saving through an autosave toggle.

Six new real-TLS/child-lifetime cases cover those exit orders, including the actual session worker's completion result. Their native bridge and checkpoint producer are controlled fixtures. All 88 affected Windows cases passed before the complete runs. See [launcher lifecycle](launcher-session.md), [autosave scheduling](autosave-foundation.md), and [durable battle reservations](battle-reservations.md) for contracts and focused evidence.

## Retained evidence

Windows evidence is under private `PokemonPrivate/artifacts/lifecycle-regression-2`; WSL evidence is under `/home/kevin/src/pokemon/multiplayer-proof/lifecycle-regression-2`, with a hash-verified Windows copy at `PokemonPrivate/artifacts/windows-runtime/lifecycle-regression-wsl-2`.

| Record | SHA-256 |
| --- | --- |
| Windows complete test log | `9e30e2dfc3f7751916e2c641915ab33fb65a52fd9b919ccdd5855a88e55ea79e` |
| Windows result evidence | `dae25e06335139aeb9ab7e1dce066a654a6c225d088758c438fd835803508c57` |
| Windows artifact index | `71287f626b291808df884eaee68a981d4fdf751e33b7e51289fcb99406a8dab0` |
| Windows before/after source index | `36cbe29eb265592ce10a8cdf7cd75d11dc0182a83a859591545839dac84895d1` |
| WSL complete test log | `acb120b8313ec3195e0b5a0f41ce7e6b0f3aa607e1b831250d5f008ec86addf4` |
| WSL result evidence | `4223e74ea6be2588e925e82eeda4af88e8847c7fb4e0aa5dcac69834ae75d0ae` |
| WSL artifact index | `a4cac76736ac1223047f4fdd399d880fee12491498e6e277d96dcc91904e3150` |
| WSL before/after source index | `02bda9d2fa818af44d44c8cce4c63f01f53a43bf97ce6676de395d2807f8d58c` |
| Cross-platform source comparison | `91bd70aef4d0c7b229808705b9c10abc3775cbd1f5d1ea0773a2dbeb194a3412` |

Earlier attempts remain intact. The pre-correction Windows archive at `3653121` ran 828 cases successfully with one optional private-save test skipped because its environment variable was unset. The first WSL harness was interrupted before completion while its display-fixture scope was being clarified; it is not acceptance evidence. The final runs above include that read-only save case and the six shutdown regressions, without skips.

## Acceptance boundary

These are source, protocol, persistence and lifecycle regressions. They do not establish five elapsed minutes of actual Windows autosave, usable pause/status behavior, host-loss local preservation, resumed native battles, complete trade/battle UI, physical input, clean-machine installation, own-dump patch import, or separate-PC Wi-Fi/Internet gameplay. Existing [actual-core evidence](windows-host-join-proof.md), [native emergency prototype](emergency-save.md), and [package records](windows-launcher-gui.md) retain their separate limits. No private ROM, save, world database, invitation or certificate key is committed to Git.

## Combined delivery base, later October 8 validation

Frozen application `5a7afee7f14dbc86dbaaba909c9f57688df7ac0b` adds the integrated native interaction handoff, emergency preservation controller, durable personal-reset accounting and retained-game close behavior. The complete Windows discovery run found **972 methods: 971 passed and one was skipped**, with no failures, in **412.479 seconds**. The optional private-save case was skipped because its input environment variable was not configured. That exact case then passed separately in **0.007 seconds**, reading both preserved source saves without changing either. All 972 discovered methods therefore have passing evidence across these two runs; the initial full-run log still correctly records its one skip. This newer source has not yet repeated the full WSL suite.

Tests loaded `src` and `tests` from the private Git archive, separate from the optional battle-resume draft under development. After testing, all **298 archived files** still matched their original ZIP bytes. The ZIP SHA-256 is `716bcd859c34d16872f58bd035ed1381f2541d1e8645e57db9e08fbeec65c1f2`; it contains 68 application modules. Private `artifacts/windows-runtime/delivery-base-validation-1/evidence.json` has SHA-256 `13b3cfec2b55ccea5f34a9cd71da1286b2e388e818b18dea8fc1ceebcb517e60`. The full test log is `f1223c5a1b080d1680ce5211e639bd4f37461441577291426fa81eff4a80c005`; the private-save follow-up log is `211a84e3bb4f65be76f9cc41fe836c95cc943899fb5dac25c99ab247d0da935d`.

Unlike the earlier fixture-only acceptance boundary above, this source also has separate [actual Windows five-minute, manual-save and visible button evidence](windows-launcher-gui.md#combined-native-save-and-visible-button-qualification), plus [actual combined-build host-loss preservation and rejoin](emergency-save.md#combined-native-build-qualification). Each retains its own stated limits. None qualifies the later optional battle-resume draft, physical input, a packaged game-import flow or separate-PC networking.

The newer full-suite wrapper requested BelowNormal priority through an unchecked Windows call. Packaging preflight subsequently exposed a missing 64-bit handle declaration in that wrapper, so the suite's actual priority is unverified; the original evidence's priority annotation is corrected by its retained `priority-correction.json`. Counts, timing and source verification are unaffected. Subsequent package commands declare the handle types and require both the priority change and its readback to succeed.
