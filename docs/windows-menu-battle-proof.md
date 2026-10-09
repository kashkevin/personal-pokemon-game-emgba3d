# Windows native-menu 1v1 qualification

Private `PokemonPrivate/wqb1` **passed** on October 8, 2026, in 643.067 seconds including setup, manual normal closure and fresh Continue. It used the real `LauncherWindow`, `SessionWorker` and `LauncherSession`, the current production Python/bridge and the input-guard SDL candidate. This qualifies the exercised source-launched Windows flow, not the packaged executable or four-PC gameplay.

## What actually ran

Two legitimate copied starter-stage saves, with parties of two and one Pokémon, enrolled separately through ordinary native Continue. The real host and friend workers connected over authenticated pinned TLS loopback. Ordinary joypad input selected Players, Challenge 1v1, Accept challenge, and Enter battle in both original games. No preparation lock gate, production method replacement, controller receipt injection, native RAM write, or fabricated winner was used.

The production executor routed **362 native blocks**. A forced switch selected the two-member trainer's second Pokémon. The native match and terminal adoption took **168.115 seconds**. Both original processes, runtime objects, bridges, incarnations and native runtime identities survived through completion. Both launchers reported `battle_finished`, restored their exact full personal parties, retired the previous saver and armed the successor before field handoff. Their durable result records agreed. Ordinary Players → Challenges → Recent battle results showed the matching native result screens for both trainers.

Both players then saved to canonical revision 2. Friend and host windows closed through their title-bar Close actions with exit codes `[0, 0]`. New Host/Join processes loaded those exact checkpoint bytes through native Continue, with the expected parties, store integrity and exclusive-save lease checks. The second pair also closed normally with `[0, 0]`. The two earlier enrollment children had been closed automatically by the existing production enrollment contract; their recorded exit code 1 is explicitly distinguished from normal play exits. All six recorded PIDs and all test-owned windows were independently absent afterward.

The qualifier, outer runner and independent watchdog all report success. There were no forced child cleanups, cleanup errors or deadline extensions. Original inputs, parent/proof runtime manifests, and every indexed frozen source retained their hashes. The original source saves remain unchanged.

## Exact source and artifact boundaries

The application base remains uncommitted work on `31e5bf93ec8fb24e7cf522908b540b318890d365`. The frozen run contains 349 indexed repository files. Its native ROM is base `aef47e4b28fd6d0e84376961e0cc6632996bb0be` **plus** the seven-file cleanup delta, patch SHA-256 `9f73e474f7e48d99257c74cf1b051fc80ad4ca56af1757e2d73f11962e18c067`. Bare `aef47e4` does not reproduce it. [Native reconstruction and tests](native-admission-cleanup.md).

| Component | SHA-256 |
| --- | --- |
| ROM | `a46cb8ae950d6fcf15f15fd065d5fa2cd9be4daa6a69e113e9a48651716974a8` |
| ELF | `1aa449932c40ea9011d5e8ce4723397fadacf560c6525b96f350ca760f41e534` |
| Game manifest | `6d117095cffcb40c4f2f6d60a6a7f869b1fd3497de123c11ae1c1808df17c766` |
| Parent runtime manifest | `d07b4dcdc12d3cb3cdb68e58178ad4f1981a1d527d44d3653beb39d04f2c5b1a` |
| Derived input/diagnostic runtime manifest | `63171d3aeea41f6b007cdae11dfa8a2a56c75ab4462a707a34cf03dd8eadedac` |
| Frozen repository index | `6b630d663dca49ab80431ea25c06de495fcfe2ae120cc13e332cd754e14e6687` |
| Qualification controller | `dd908102d7224f44071a93cd5b45a51add253dcbc90a248f56cda1cf2dbbcd5c` |
| `run/evidence.json` | `9655b9b2915010f942b5c882c97d7d41a2fda2c64d5c2349eb3df320e3cab337` |
| `outer-evidence.json` | `b67b3931243afba2f0c99586f3ff5a96a0e98dc4f631786f71ea6ec473387f1e` |
| `watchdog-evidence.json` | `3f32a0f302ba5cf62331f06865ece364344137ddc3f845981af18fabb9bae06c` |
| `controller.log` | `f895df6deef5ea049ab6e9ba7ab8cb9c88f66e5e94f845006fb620a0742c9c83` |

[`qualify_menu_battle.py`](../scripts/windows-runtime/qualify_menu_battle.py) reuses the proven menu/input helpers and adds bounded, read-only task/party diagnostics from the pinned ELF. Its ordinary key driver reads the existing validated pending controller request; it cannot replace a controller result. Key presses are serial per game and include release acknowledgements. The production Lua prefix is retained exactly; the separately hashed suffix performs ordinary input and read-only observation only. Eight focused helper tests passed in 0.059 seconds, separately from the earlier full 1,144-test production regression. [Helper tests](../tests/test_windows_menu_battle_qualifier.py).

## Limits

This is two-versus-one-party **1v1**, with automated ordinary input on one Windows PC. It does not qualify 2v2 through Windows menus, six-versus-six singles, interrupted Windows battles, physical keyboard/gamepad/audio, observers, timed autosave, trade effects, clean installation, the packaged launcher or remote networking. [Separate final four-core recovery](native-battle-resume-proof.md#final-combined-candidate--populated-party-all-fault-recovery), [separate cancellation proof](windows-admission-cleanup-proof.md), and [separate timed saving](windows-controls-audit.md) retain their own scopes.
