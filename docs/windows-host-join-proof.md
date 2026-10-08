# Windows TLS enrollment and Host/Join qualification

`scripts/windows-runtime/qualify_launcher_session.py` exercises the public setup and session controllers with two actual Windows SDL cores, original unassigned character sources, the pinned production bridge, and authenticated certificate-pinned TLS over loopback. Test-only additions replay ordinary GBA buttons and read party diagnostics. No RAM/save injection, savestate, debug warp, fabricated world descriptor, or reenrollment of an owned checkpoint is used.

The intended sequence is sequential local host enrollment to canonical revision 1, export of an individual friend invitation, simultaneous Host/Join, explicit `LauncherSession.save()` to revision 2, normal closure of both children, fresh Host/Join and ordinary Continue of the exact revision-2 bytes, then normal closure and final integrity checks. Default battle/trade creation desks remain disabled. This controller does not exercise packaged GUI buttons, physical keyboard input, clean-machine installation, or separate computers.

## Retained attempts on October 8, 2026

The common game SHA-256 is `bb322038d761cd04b9a525b058c953b8b479402054e895a7ea8a19664d344435`, game manifest is `1d1d89070b503acdda9238cb66bafe365d10f813fc96d967379aebefe63d49c7`, and parent runtime manifest is `2833fab2ed76dca444eb9cbfecc252088b9018f5bae4ce59483737bf409594fc`. Every input is checked against an explicit pin before launch. Generated worlds, invitations, character copies and recovery evidence remain private under `PokemonPrivate/artifacts/windows-runtime`.

Attempts 1 and 2 failed before native creation because the former nested launch working directory exceeded the pinned Windows frontend's path limit. Their pending enrollment/source data was retained. Source `1c8ed077392d584ee42d8c81e982ee96d9563c3e` adds early path validation and a shorter per-launch directory, and fixes verified enrollment completion after its own deliberate child shutdown. Its 102 Windows and 82 WSL tests are recorded in [launcher-session.md](launcher-session.md).

Attempt 3 used that fixed source and successfully completed both actual-core enrollments. The controller then incorrectly inspected redirected native logs while both processes were still running. Those logs were buffered and empty; the absence of a sample was incorrectly reported as a party mismatch. The canonical party assertion had succeeded. This attempt is **failed**, not gameplay acceptance. Commit `c9c9501` moves the native diagnostic assertion after normal exit, as the earlier accepted direct-runtime proof already did, and distinguishes absent diagnostics from different party data.

Attempt 4 froze source `c9c9501` before launch. Both original sources enrolled through ordinary Continue to revision 1, with TLS verified before the deliberate enrollment shutdown and exact completion receipts afterward. Actual Host and Join children authenticated over pinned TLS, retained their exclusive character leases, reached the field, and each completed `LauncherSession.save()` to revision 2. Both canonical party CRCs and ownership serials matched their enrolled characters. The controller reached `ready_for_normal_close`.

Windows Computer Use had been stopped with Escape during the separate package preview. No further desktop input was issued. Attempt 4's bounded wait for normal game-window closure expired; its existing cleanup closed both owned game processes. **The overall attempt remains failed/incomplete:** normal-exit diagnostics, fresh Host/Join Continue, and final acceptance were not reached. All four children used by this attempt were closed, and all original source hashes remained unchanged. The separately accepted direct `PlayerRuntime` checkpoint/fresh-Continue proof remains valid within its [documented narrower scope](windows-launcher-gui.md#actual-windows-checkpoint-and-fresh-continue).

## Private evidence pins

| Record | SHA-256 |
| --- | --- |
| Attempt 3 prefrozen source index | `2b31b4bfebfb6341d08dbb95406ffde0adba19e2eea182234210f61778936713` |
| Attempt 3 evidence | `84f9af8150fb40690d29492fc4bec4ff28bb7d34c59679d74bf6cb9ed46fa941` |
| Attempt 3 complete artifact index, 54 files | `9cfd9613c360f12f73a13ab6f050c26d6e4c0d544037f1ea486d29a19928300f` |
| Attempt 4 prefrozen source index | `ffcaef97562639509f95d5354eb2d0bc2632899c3dbe7b69afb11052647a7323` |
| Attempt 4 evidence | `357d33f09200bda0256340a460beba16cc6e9fabdf2fd9df24dec52ca2a6b5eb` |
| Attempt 4 complete artifact index, 54 files | `c4805f0e0b80b16fb45f1be1e3d762975597ba3e5a8cada2007aa8102625fcd8` |
| Attempt 4 controller output log | `024c25752ae1b003388a9fc5d95b065cc87d6ad0440f42b648a95c95afc63fb2` |

Artifact indexes hash every retained file except the index itself. No private world database, save, invitation, certificate key or game image is committed to Git. A later rerun must use a new private output directory and a new recorded source freeze; these incomplete attempts must remain intact.
