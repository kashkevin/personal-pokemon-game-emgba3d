# Windows controls and Local Soft Reset audit

October 8, 2026. This runtime/engine audit and candidate source correction supplement the [Windows qualification record](windows-launcher-gui.md). They do not establish physical keyboard, audio, gamepad, packaged gameplay, or separate-PC acceptance. Existing native engine worktrees, accepted runtime binaries, private saves and packages were not modified or rebuilt.

## Existing input path

The pinned mGBA source is `26b7884bc25a5933960f3cdcd98bac1ae14d42e2`. Its SDL `sdl-events.c:mSDLInitBindingsGBA` assigns arrows, X/Z, Enter/Backspace and A/S to movement, A/B, Start/Select and L/R respectively. `_mSDLHandleKeypress` maps ordinary SDL key events through `mInputMapKey`, then calls the core's `addKeys` or `clearKeys`. Gameplay keys with modifiers other than Num Lock or Caps Lock are excluded. This explains the supported event path; it does not explain the earlier automation failure without captured events.

The accepted runtime's project [SDL adapter](../native/windows-runtime/sdl-multiplayer.c) wrapped `setKeys` and `addKeys`, suppressing Start only when all four traditional reset buttons were held. An ordinary Enter/Start press was unchanged. Frontend rewind, state and reset shortcuts remain blocked. No source defect explaining absent ordinary Start input was established. The candidate correction below changes the unsafe full-chord handling, not the ordinary keyboard mapping.

`mCoreLoadConfig` reads the user's mGBA configuration, and `mSDLPlayerLoadConfig` applies the `gba.input.SDLK` keyboard section after defaults. The locally inspected configuration had Qt keyboard and SDL joystick sections, but no `gba.input.SDLK` override; the observed joystick entries do not disable the separate SDL keyboard mappings. The configuration was not changed. The earlier failed automated key attempts remain **UNKNOWN**, not proof of a hardware keyboard failure or permission to change mappings.

## Why the existing reset ABI cannot enable the classic chord

The inspected combined engine is `1a7a0cdb5dadd2820a3b6c25c4ecafce1facd6eb` in `/home/kevin/src/pokemon/engine-delivery-integration`.

- `src/multiplayer_reset_admission.c:16` publishes `gMultiplayerResetAbiVersion` unconditionally. This is an attempt-admission protocol marker, not proof that reset encounters or safe chord handling are enabled.
- `src/multiplayer_local_reset.c:306` handles the chord only when `MP_LOCAL_RESET_ENABLED` is compiled in. At line 317 it still returns false without `MultiplayerSave_HasBinding()`.
- `src/multiplayer_save.c:219` defines that binding from runtime state, session and incarnation; a verified ROM hash or reset ABI does not establish this live state.
- `src/main.c:157` consumes keys when the native handler succeeds. Its following branch calls `DoSoftReset()` when the handler returns false and the ordinary chord is held.

Consequently, passing the raw chord through the Windows filter based on `reset_abi_version` alone could reboot a build with resets disabled, or a game before binding. No such flag was added. Translating it to Select unconditionally would also invoke unrelated Select behavior outside eligible encounters: `battle_controller_player.c:407` has a conditional debug action, line 874 has move rearrangement, and field Select has registered-item behavior. When Select arrives before the final chord key and a game frame observes it, translating the completed combination to Select would not create the fresh Select press required by `RequestFromSelect`. A mask-only translation therefore neither preserves unsafe-scene behavior nor reliably opens confirmation for every press order.

The existing eligible first-action **Select** command already enters native Yes/No confirmation, defaults to No, and rechecks the binding, original encounter state and battle safety. See [durable encounter admission](local-reset-durable-admission.md) for its scope. Windows physical Select input remains to be qualified.

A future classic-chord implementation needs a distinct native input capability whose contract suppresses reboot throughout the launched multiplayer lifetime, including pre-binding and disconnected states. Only a verified build advertising that stronger contract should allow frontend passthrough. Tests must cover startup, binding loss, unsafe saves/trades/battles, unqualified encounters, held/released chords and eligible confirmation, followed by actual-core and Windows input proof. This requires coordinated native/runtime work rather than a launcher-only switch.

## Candidate correction: consume blocked chords through release

The old filter exposed A, B and Select while blocking Start. Moreover, `addKeys` reconstructed the next held mask from the already filtered core state. That loses which physical/script buttons remain held. A partially released chord could consequently expose a held confirm/cancel/menu button as an ordinary action.

The candidate keeps the requested mask separately, wraps `clearKeys` as well as `setKeys`/`addKeys`, and consumes all four chord buttons once the complete combination is detected. The latch stays active until all four are released; unrelated directional/shoulder input is preserved. It filters the initial core mask and restores all three original callbacks when unloading. Ordinary individual buttons and mappings are unchanged. Inputs observed by the game before the full combination arrives are still ordinary inputs; this correction does not claim to undo earlier actions or implement a reset request.

The portable guard resides in the existing adapter header, so runtime collection retains it without adding bundle files or changing its 32-file manifest bound. Native types in that header use forward declarations; the implementation includes their original dependency headers. No runtime ABI, save layout, new dependency or distribution component is introduced. A newly built/qualified runtime is required before players receive the correction. Existing packages still contain their original filter.

## Reuse review

Read-only `git ls-remote` confirmed current maintained mGBA HEAD `143adf5aa2a60c6036810b0cd72445e13d74b0e6`. Its [SDL input source](https://github.com/mgba-emu/mgba/blob/143adf5aa2a60c6036810b0cd72445e13d74b0e6/src/platform/sdl/sdl-events.c) retains the same default keyboard mapping. The official [scripting API](https://mgba.io/docs/scripting.html) supplies ordinary key input and observation; it does not establish our native ownership or reset-safety contract. Reuse the current public input path. No upstream update, copied implementation, new dependency, license change, or save migration was incorporated. Existing terms remain in the [dependency ledger](dependency-ledger.md); input performance was not measured by this audit.

## Verification performed

The existing five source-sanitizer tests and three network-diagnostic tests passed on Windows in **1.534 seconds**, with zero skips, using the already installed host-provisioning Python environment. The command was `python -m unittest test_source_sanitizer test_network_diagnostics -v`, with `src;tests` on `PYTHONPATH` and bytecode writing disabled. These tests use temporary synthetic archives and loopback TLS. They do not exercise native keyboard input or change private source saves.

[`tests/native/windows-input-guard.c`](../tests/native/windows-input-guard.c) compiled against the actual production header with `-std=c11 -Wall -Wextra -Werror -O2`. Both Linux GCC and a statically linked MinGW x64 executable run on Windows passed **37,889 mask/order cases**: all 1,024 GBA input masks; all 24 press orders crossed with all 24 release orders and 64 unrelated button masks; repeated/partially released chords; fresh input after full release; and direct mask replacement. The complete adapter also passed MinGW syntax compilation against the pinned mGBA/generated/Lua/SDL headers.

The private Windows guard executable and log are retained under `artifacts/windows-runtime/input-guard-audit-1`. SHA-256 values are `56a6e02483594f86d7e888b231882804ddc70df34dfeb8c075c1b74ca1f27a1c` for the executable and `f2d5f2e0939952eaf7969d06fc0fa70fc558a7206ebf1009fceb3c73a5f94809` for the log. Initial command attempts encountered shell argument forwarding and the existing virtualized AppData path; the corrected commands used the pinned headers and copied the compiled test from WSL before executing it on Windows. No failed command modified an accepted runtime. These are input-guard unit checks and compile evidence, not full SDL runtime, gamepad, physical-key or Local Soft Reset gameplay acceptance.

## Isolated runtime candidate

The subsequent authorized build created a new pinned clone at `/home/kevin/src/pokemon/windows-input-runtime-audit-20261008-1/mgba` and a new private Windows collection under `PokemonPrivate/artifacts/windows-runtime/input-guard-candidate-1/bundle`. It preserves the earlier runtime, packages, source worktree, dependency libraries and release pins. The source freeze records adapter SHA-256 values `c3172fea92e99ab9310bfa2f1d3e0096f0c9914237ef0d388a988e3c58a9ee39` (C) and `265ebc6469ea9fe89853ff59dc1056e1957c4159ce5ab9c33f1465c7a939601b` (header). The existing `prepare_frontend.py` was used unchanged. The mGBA CMake configuration was copied exactly from `build_runtime.sh`, using the already verified dependency libraries read-only, with one worker at `nice 19`; the dependency rebuild/install stages were not run. No dependencies were installed. The complete compiler log retains 20 warnings in pinned upstream code, including the existing SDL joystick handler; none names the new adapter.

The collector now accurately states that collection itself establishes neither runtime smoke nor player release acceptance. Its updated source was frozen separately, preserving the original source snapshot; the collector SHA-256 is `fcbbee2126339b5fd18918d5169198820294688b04bde77635f8db68428271a7`. The new bundle retains all 32 permitted manifest components, source/notices and relink material. The sanitizer again excluded exactly the 193 reviewed fixtures and verified every retained member's bytes and metadata. Its newly generated gzip has the hash below; identical retained source does not imply identical compressed archive bytes across environments. The existing recursive content audit inspected 5,265 files/members, 13 archives and 490,749,835 expanded bytes without identifying a prohibited private-data format. Its documented limits still apply.

| Candidate evidence | SHA-256 |
| --- | --- |
| `bundle/runtime.json` | `d07b4dcdc12d3cb3cdb68e58178ad4f1981a1d527d44d3653beb39d04f2c5b1a` |
| `bundle/mgba-sdl.exe` | `3dc0a6d0c93a80c83f0e59d73bccb66561d1ccb605b7e5d8b6811ae0e01caf5b` |
| `bundle/mGBA-source.tar.gz` | `0e4f4458297e2d618ad94536961d93cbe68f23fc0d3aacd28e1f6cd1222a1c68` |
| `compile.log` | `b76703fd255d04f8a097fad14d0b66be6b07b9f7f0d61c90b10b091148400d94` |
| `binary-and-source-verification.json` | `92713b7457f0a10ba4cae11b5d0e573dd70dde26ec845193bf3de2a4b25fb5bc` |
| `windows-cli-verification.json` | `a66e94c6d84b5744a1697d4feeb0815c38d6d096cc27eff7d836a81ea257279a` |

All 14 archived relink inputs byte-match their build/dependency originals, and the seven members of `frontend-objects.a` match the separately retained frontend objects. The published relink command succeeded in another new private directory; its executable and both DLLs have the expected x64 PE architecture and imports. The separate relinked executable is `7c182dad580285a1dfb13ff473c1dea5ec4ddb629cb47bbe91abe8ed4732d6aa`. It is not a byte-identical rebuild: `.text`, `.rdata` and `.idata` sections differ, and the original CMake link response file uses a different/repeated library order from the published simplified command. This verifies usable relink inputs and the bounded checks below, not binary reproducibility or equivalent gameplay execution.

On Windows, the real `RuntimeBundle.verify()` accepted the complete bundle before and after eight noninteractive executable checks: version output, no-ROM help output, and rejection of either missing multiplayer path, for both the candidate and separately relinked executable. These children used BelowNormal priority, dummy SDL driver variables and no visible window. An initial harness incorrectly expected the literal display name `mGBA`; another expected no-ROM help to exit zero. Their results were retained, and inspection of the pinned frontend confirmed the executable-name version string and existing help exit code 1 before the final checks passed. These CLI checks launched no ROM and do not establish gameplay/input acceptance; the separate actual-runtime follow-up below adds its own bounded evidence. No launcher was repackaged and no release pin was changed.

## Actual Windows Host/Join and checkpoint follow-up

The subsequent private `PokemonPrivate/wq1` qualification **passed in 293.648 seconds**, at verified BelowNormal priority with an eight-minute outer deadline. It used the unchanged `qualify_launcher_session.run` controller with autosave timing disabled, frozen current Python/controller source (81 files), the candidate runtime above and copied inputs from the accepted combined save build. This is native `1a7a0cdb5dadd2820a3b6c25c4ecafce1facd6eb`, ROM SHA-256 `4fcdae904ad4f0f49e805096c932c0a8f6ba7f753b1d038cd51c7854142d4fa2`, manifest `aa680a0caf452a95d90b6802cf51da47ee917a97180d37560e6d74154e286325`; it does not exercise the optional `aef47e4` retained-battle recovery build.

Two original unassigned characters enrolled separately through genuine native Continue to revision 1 over pinned TLS. Two simultaneous actual Windows cores then reached the field as Host/Join, retained their exclusive save leases and each completed a manual canonical save to revision 2. After normal closure, fresh Host/Join and Continue loaded the exact revision-2 bytes; native party diagnostics matched the canonical parties. Both phases ended with child exit codes `[0, 0]`, released save leases and final database integrity. The proof bundle pin is `91027de860665e1e663a7c6fadb9de41f53c03ddb59400b6ec74519c05dfa680`; its only bridge additions are the existing ordinary Start/A input plan and read-only party diagnostics. Original saves, ROM, manifest, parent bundle and all indexed original/frozen source files matched their before-run hashes afterward.

At each controller `ready_for_normal_close` event, the documented computer-use plugin observed the exact test-owned window and clicked its title-bar Close. The four play/reload closures were ordinary SDL exits, not process termination. The controller deliberately handles its two enrollment shutdowns after verified enrollment receipts. All six recorded child PIDs were absent after completion, and the window inventory contained no remaining test-owned windows. The unrelated installed mGBA window was untouched. A transient window-capture failure was recovered by refreshing/activating that returned test window before another observation; no stale coordinates or extra gameplay input were used.

| Actual-runtime evidence, under private `PokemonPrivate/wq1` | SHA-256 |
| --- | --- |
| `run/evidence.json` | `c08ae5c09c7d46bf4c7fedf63a0c5eead1cf6e082e26cc4ae47362ab3cb56921` |
| `outer-evidence.json` | `9753b43fca56076d03c0ac5452810649efec694c1d220d32283376b88caa5eb9` |
| `controller.log` | `deb89545abcbd2b2e970403d5410339de66c0947e42ccf347d20bb5c1374197d` |
| `frozen-source-index.json` | `6b83a2ef0da3d1cf5ee8a2e6086d7b1dba12e0df00a2ff9d50c9583687ce10d4` |
| `ui-close-record.json` | `05812bb9beeadf160c3b2a6747ba04a8abfe190ecf54928f069e9fba11f5b684` |
| `artifact-index.json` (165 files) | `1470e10f835fedb492875c64eaaccd7bb5807f12366faf6cf7b2ee20db4a5a62` |

This adds real native startup, ordinary scripted input, bridge, two-client TLS loopback, manual save, normal-close and fresh-Continue evidence for the candidate. It does **not** qualify physical keyboard/gamepad, audible playback, the classic reset chord, five-minute timing, native trades/battles/recovery, launcher GUI buttons, final packaged import/installation, separate PCs or Internet transport. The candidate remains private and unpromoted; accepted packages and release pins are unchanged.

## Timed autosave run wqt1 — gameplay checks observed, final closure failed

The later private `%LOCALAPPDATA%/PokemonPrivate/wqt1` run used the exact cleanup-capable candidate documented in [Windows launcher cancellation qualification](windows-admission-cleanup-proof.md), the same legitimate two/one-member source parties, and the existing `qualify_launcher_session.py --autosave` controller. Its frozen 346-file source index is `bcb1343b65e02463e5e9a9e9695303d1a9629e2116008e31672d213977af2a46`; controller SHA-256 is `9c2ae567d315ea1d90d1808a0d14373e16908e37b9883404f240c2af1e12a53e`. Its separate runtime manifest is `2a0f6c6f61cd181da3caa292b544afe9421fb772a314c5077091e071ab43d5a1`, and the derived ordinary-input proof bundle is `a9aed7a232f4f23cf24cd64b984fadc6c7298f81e145abc6dff4f73355eea9ce`.

Actual Windows native enrollment and two-client pinned-TLS play reached the field. The host's real five-minute autosave completed after **306.781 seconds**, advancing revision 1 to 2; the friend stayed at revision 1 with autosave explicitly disabled. Manual saves then produced host/friend revisions **3/2**, preserving both canonical parties. The first pair of play windows closed normally with exits `[0, 0]`. Fresh Continue loaded the exact saved revision-3/revision-2 checkpoint bytes, reached the native field, and retained the host-enabled/friend-disabled preferences.

The operator missed the final `ready_for_normal_close` event during context compaction. Its unchanged **180-second normal-close wait expired**, and controller cleanup stopped the final disposable games. Therefore this run is **failed qualification**: `passed=false` and `TimeoutError`, with no accepted final normal exits or post-close native-party-log checks for the reload phase. The original inputs and frozen sources remained unchanged, and all children were reported closed. The outer coroutine deadline remained 900 seconds; the independent 1,020-second watchdog was not forced and recorded controller exit 1 after 799.530 seconds. This is a missed operator closure, not evidence of a production autosave failure. The partial observations do not establish complete timed-autosave acceptance.

| Private failed-run evidence under `wqt1` | SHA-256 |
| --- | --- |
| `run/evidence.json` | `cd503c52f40c16ee46e1844fcc117072f9b3fac43d5737f87f7cb3e9e151cfb6` |
| `outer-evidence.json` | `875d834d35965155032de037701a18cefd00dee289e0250e06056eff533a7e37` |
| `watchdog-evidence.json` | `b56a74a9fccd6b5333be44967224f8075bcbe7e56eb3df642dafc79be2721d9f` |
| `controller.log` | `e141618db0ed5f49f9412cfb0c83c390ec34eb1939ce54640766b7fc61c6a417` |

A separate `%LOCALAPPDATA%/PokemonPrivate/wqt2` was prepared with the same frozen sources, runtime, inputs, runner and watchdog. All **363 copied files, 122,064,249 bytes**, except the deliberately updated argument paths, match `wqt1`; the complete original `wqt1` tree and the five original source inputs were rehashed unchanged. The new `run` directory did not exist at preparation. No deadline or production setting changed. Preparation inventory SHA-256 is `980d1e0b9fa03d068bda3d8d3f337a7199a6f825c2720c2eced0c7253f61f8e3`. Preparation alone is not a run or acceptance; its eventual result must be recorded separately.


## Timed autosave repeat wqt2 — complete acceptance

The unchanged repeat **passed in 549.392 seconds**. It used the same frozen 346-file source index, native candidate, runtime and ordinary-input controller as wqt1 above, with a fresh copied world and new output. The host's actual 300-second autosave deadline produced revision 2 after **307.210 seconds**; the friend remained at revision 1 with autosave off. Both manual saves succeeded to revisions **3/2**. Fresh Continue loaded those exact checkpoint bytes, retained the enabled/disabled preferences and matched both native parties.

Both pairs of play/reload windows closed through ordinary title-bar Close actions, friend before host, with exit codes `[0, 0]` in each phase. Enrollment retained its separate automatic-close contract. All six recorded game PIDs and all test-owned windows were independently absent afterward. Store integrity, save leases, original-input hashes, frozen-source hashes and both inner/outer completion checks passed. The independent watchdog reports no forced termination. wqt1 remains preserved as a failed earlier run; it was not overwritten or reclassified.

| Private passed-run evidence under `PokemonPrivate/wqt2` | SHA-256 |
| --- | --- |
| `run/evidence.json` | `8029007007f864ad7cb440cf93058e367b93adb4d285b2642726940fd5377b55` |
| `outer-evidence.json` | `39c9babf242a93aff456a86bd141562c389a8f416608a8c22a43327b82c9b979` |
| `watchdog-evidence.json` | `c1ac58565b8a9f1694de4bb836717b19e9e30bcb4528fb7841086942f2bc464f` |
| `controller.log` | `bbbec2a51d3abd89d872018f2377339969ef6d45bb57c4105192cf53d5737dcf` |
| Frozen source index | `bcb1343b65e02463e5e9a9e9695303d1a9629e2116008e31672d213977af2a46` |

This qualifies the timed/manual save and reload path with the latest recovery/cleanup-capable candidate on Windows TLS loopback. It uses source-launched sessions and scripted ordinary Continue input; it does not establish packaged gameplay, physical controls, network faults, separate PCs or Internet. [Native-menu 1v1](windows-menu-battle-proof.md) is a separate passing run.

## Later source-only classic-chord routing

After the owner stopped tests, [safe classic input routing](local-reset-classic-input.md) was implemented in source using a separate native capability, an unconditional native reboot guard, and the existing eligible encounter confirmation. No runtime or ROM was rebuilt for it. The earlier compiled guard and private package evidence above remain tied to their frozen suppression-only sources; they do not verify the new route. Default-off encounter flags, accepted artifacts and release pins are unchanged.
