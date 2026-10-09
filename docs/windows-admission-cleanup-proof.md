# Windows launcher cancellation qualification

On October 8, 2026, private run `%LOCALAPPDATA%/PokemonPrivate/wqc8` passed in **498.080 seconds** including its outer watchdog. This exercises the real source-launched `LauncherWindow`, `SessionWorker`, `LauncherSession`, authenticated TLS host/friend connection and two actual Windows mGBA SDL games. It is not an installed friend download, physical-controller test, Internet test or completed playable battle.

The native candidate is the [admission-cleanup build](native-admission-cleanup.md): base `aef47e4b28fd6d0e84376961e0cc6632996bb0be` plus source patch `9f73e474f7e48d99257c74cf1b051fc80ad4ca56af1757e2d73f11962e18c067`, ROM `a46cb8ae950d6fcf15f15fd065d5fa2cd9be4daa6a69e113e9a48651716974a8`, ELF `1aa449932c40ea9011d5e8ce4723397fadacf560c6525b96f350ca760f41e534`, manifest `6d117095cffcb40c4f2f6d60a6a7f869b1fd3497de123c11ae1c1808df17c766`. The unchanged input-guard runtime executable is `3dc0a6d0c93a80c83f0e59d73bccb66561d1ccb605b7e5d8b6811ae0e01caf5b`; its original parent manifest is `d07b4dcdc12d3cb3cdb68e58178ad4f1981a1d527d44d3653beb39d04f2c5b1a`.

## What passed

Two legitimate copied source characters were enrolled through the production bootstrap lifecycle. Successful enrollment automatically terminates its temporary child; those two exit codes were 1, as expected for that existing Windows contract. They are explicitly distinguished from the four normal play-window exits below.

The ordinary Players menus selected the friend, issued a 1v1 challenge, accepted it, and selected Enter battle. A proof-only observer held the existing checkpoint lock before selection so preparation waited at its usual boundary. It changed no production method, lifecycle owner, native receipt or emulated RAM. The actual enabled **Cancel battle entry** Tk widget was invoked programmatically through its real `SessionWorker` dispatch. This is a widget/API test, not a physical mouse-click test of that button.

The observer released its lock only after the real host had durably canceled consent and the exact original preparation task drained. No battle reservation or routed BIND existed. The production path then completed native HOLD, old-saver retirement, fresh emergency arming and HANDOFF. Launcher status became `admission_canceled`, the native hold cleared, the pending intent disappeared, and ordinary saving was available again. Both players saved revision 2 with their original parties intact.

The four actual play windows were closed through their normal title-bar Close controls using the Windows computer-use tool: friend then host for the first phase, and friend then host after fresh Continue. Both phases returned `[0, 0]`. Fresh sessions reloaded exactly the saved canonical checkpoints and parties; native runtime logs, exclusive mirror leases and final SQLite integrity also passed. All six test child PIDs were independently absent afterward, with no remaining `wqc8` window, forced qualifier cleanup, cleanup error, changed original input or changed frozen source.

## Controller and evidence

[`qualify_admission_cleanup.py`](../scripts/windows-runtime/qualify_admission_cleanup.py) appends bounded ordinary joypad controls and read-only diagnostics to a byte-identical copy of the production Lua bridge. Inputs have exact LF wire bytes, bounded key/hold/release values and single-use sequence acknowledgments. Diagnostic symbols and sizes are checked against the exact pinned ELF. A separate real-Lua fixture checked parsing, duplicate rejection, bounds and snapshot framing; a Windows check verified the emitted key-file bytes. No emulator state, party or save injection is used.

The run freezes 346 project files. Its application source includes the same-lease saver fix but predates the later asynchronous large-journal recovery load; this scenario performs no interrupted battle replay. It uses the existing isolated Windows Python/cryptography environment, verified BelowNormal priority, a 600-second scenario limit, a 780-second coroutine envelope and a separate 900-second process watchdog. The five-minute autosave setting was deliberately off for this cancellation scenario; its separate timed qualification is recorded elsewhere.

| Private evidence under `wqc8` | SHA-256 |
| --- | --- |
| `frozen-source-index.json` | `33fc96093bb449228e745c11f4fcbe4fbb4ec4d56b5d618df54ff7549e77ab65` |
| Frozen qualification controller | `5f09b692fc0c6b4ebb77ac60a9bf0d517faa1199eb664f2270dc8b0869e9fe04` |
| Proof runtime manifest, including scripted input | `8bc45a44ee471b7a7ab2b6baf6f3199d5ba02cc63bdccdbee610ffe502751b9b` |
| `run/evidence.json` | `63978250f8e81c95cdf6d2a5233d186ea852aacdbf51be7d7809be86241f78ea` |
| `outer-evidence.json` | `bfddcec03ba43ee9c13112e2756ee6eb7ebc2b43fae65837c8528b1f4594f0a7` |
| `watchdog-evidence.json` | `bbc9743397a852806ac1844898703dfd5eb34e7cbed8cef78fd61ff9fa6f36f7` |
| `controller.log` | `25bb77b55047922a98152b3075eb89804d2caa0a4dce923eb6441722f7b294a7` |

The earlier private attempts remain preserved and do not count as passing gameplay. `wqc1` failed before launch because the runner expected a dictionary instead of the input inventory's list. `wqc2` used the unqualified system Python without the existing private cryptography dependency and created no game. `wqc3` incorrectly demanded a manual zero-code exit from the production-terminated enrollment child. `wqc4` used a nonexistent `Companion.ipc_port` attribute; its initially untracked disposable game was subsequently closed through the UI, and the controller now registers every child before later inspection can fail. That run's missing recorded child exit code is UNKNOWN. `wqc5` exposed Windows newline translation in its strict input files. `wqc6` is an unused preflight snapshot, not a run. `wqc7` reached consent but timed out on an unobserved gate-readiness future; the discarded gate exception is UNKNOWN. Review corrected access to the optional `_live_battle_owner` and made gate failures propagate promptly. Each actual attempt has a separate directory; no failed evidence was overwritten.

The remaining boundaries are cleanup after BIND/preparation, cancellation interruption through the actual Windows GUI, native menu-to-completed 1v1/2v2, physical keyboard/gamepad controls, installed package/import, separate PCs and Internet. The three headless cancellation fault cases remain separately scoped in the native report.
