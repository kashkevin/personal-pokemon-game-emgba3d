# Development Host/Join session controller

`launcher_session.LauncherSession` joins the existing provisioning, authenticated transport and native runtime lifecycles for **already enrolled characters**. It is a backend for a later Host Game / Join Game interface. It does not create characters, import or patch a game, offer player interactions, install a package, change network settings or establish a friend-ready release.

## Reused components and trust

The implementation reuses `HostWorld.open/open_store/host_companion_config`, `Invitation.load/companion_config`, `WorldServer`, `Companion`, `CheckpointClient`, `PlayerRuntime` and `ColdStartRecovery`. No dependency, wire format, server RPC or gameplay rule is added. The [Windows lifecycle](windows-launcher-foundation.md), [pinned native runtime](windows-runtime.md), [Host/Join provisioning](host-provisioning.md) and [durable battle admission](native-battle-admission.md) remain their authoritative contracts.

The existing `python -m emerald_multiplayer.server` and `...companion` entry points still launch the earlier presence prototype. They are not used by this controller: its host owns an authenticated store and TLS listener, and its friend imports a separately provisioned account invitation.

`GameInstallation` requires application-supplied SHA-256 pins for the installed ROM, mailbox manifest and `RuntimeBundle.runtime.json`. Do not derive the expected pins from files supplied by an invitation or from whichever files happen to be installed. Verification checks the exact manifest bytes, the ROM/compiled mailbox contract and every pinned runtime component before connecting, again before launching, and through the existing runtime's post-recovery recheck. An invitation identifies the required game/world; it cannot choose an executable or bridge.

The qualified runtime remains the bundle with manifest SHA-256 `98d6273bd87b277a69d46b1e8195204c3285d148571355a8899df66d83677c2f`, recorded in [windows-runtime.md](windows-runtime.md). Its accepted Windows gameplay proof used the frozen trade-foundation ROM. This controller does not replace its Lua template or qualify ABI3, the larger save window, or Local Soft Reset on that bundle. A later combined game needs a separately collected and tested bundle and application pins.

## API and lifetime

Construct the trusted `GameInstallation` using the application release record, then select exactly one existing host directory or friend invitation:

```python
installation = GameInstallation(
    rom_path, manifest_path, APPLICATION_ROM_SHA256,
    APPLICATION_MANIFEST_SHA256, RuntimeBundle(bundle_directory, APPLICATION_RUNTIME_SHA256),
)
host = LauncherSession(
    installation, private_app_directory,
    world_directory=existing_world_directory,
    bind_address="192.168.1.20", host_route="192.168.1.20",
    development_trades=False,  # Default: recovery works; new trades stay disabled.
)
# Alternatively:
friend = LauncherSession(
    installation, private_app_directory, invitation_path=friend_invitation_path,
)

async with host.open() as session:
    status = session.status
    if status.state is SessionState.READY:
        exit_code = await session.play()
```

The application supplies its private AppData directory; there is no use of the downloaded directory or repository as a player profile. Character files and journals are isolated under `players/<world UUID>/<player UUID>`. The local mirror is `character.sav`. The controller creates no replacement world or account and never reads an original source save to enroll it.

The host's numeric local bind address and local connection route are separate from its advertised invitation endpoint. The local route preserves the same world, account credential, trusted certificate and DER pin; it does not change exported invitations or `host.json`. This supports a host connecting locally while friends use the advertised address. Wildcard/DNS bind routes are refused. `public=False` is the default; an explicit public listener still goes through the existing TLS/durable-store gate. Port forwarding, firewall configuration and separate-PC connectivity are outside this component.

`open()` validates inputs, opens the existing store when hosting, starts the listener/companion, waits for authentication and performs an observational readiness check. A missing canonical checkpoint, any pending battle path, or unavailable trade recovery yields a connected BLOCKED status. No game is launched. Readiness exposes a revision for display only; it never adopts that revision as permission to overwrite a save.

`play()` checks readiness and the installation again, then exclusively delegates to `PlayerRuntime.open()`. Closed recovery retains the ordinary save/trade journals, verifies canonical ownership and holds `MirrorLease` from reconciliation through the native child's exit. The runtime owns the generated Lua and process arguments. A second play operation is refused. After one successful native creation, another launch requires a new session. A changed authenticated lease also requires a new session and verified recovery; reconnect does not automatically authorize another core.

The context remains open while the game runs. If the caller starts `play()` in a separate task and leaves the context, cleanup cancels and drains that task first. Native process creation/termination and save-lease release complete before companion, server and store closure. Repeated caller cancellation does not abandon an outstanding child. Each launcher session is single-use and belongs to one asyncio event loop.

## Development gates and status

`development_trades` defaults to false. Authenticated schema-3 hosts provide the existing `trade_pending`, `trade_status` and exact committed `trade_ack` operations independently of that gate. `trade_open`, `trade_offer`, `trade_confirm` and `trade_cancel` remain disabled until explicit opt-in. The private recovery desk shares the active proposal desk when trading is enabled; when disabled after a host restart, it reports the existing durable committed fate or the authoritative absence of a volatile proposal. It cannot create, edit, confirm or cancel a proposal through a recovery route.

Host and friend readiness check recovery with an observational `trade_pending` request. They can resume an enrolled character on a default host. Pending results still block ordinary persistent mutation until closed recovery installs and verifies that player's current canonical bytes, records its evidence, and sends the exact result acknowledgment. Foreign results, stale leases, wrong revision/hash acknowledgments and active battle reservations retain their existing refusals. A malformed local journal or uncertain response still prevents a game launch. Readiness alone neither acknowledges nor clears recovery.

An older host or unsupported store without that capability reports `trade_recovery_unavailable`; it is never treated as an empty recovery list. No new RPC, unauthenticated registration, schema migration, native trade effect or offline/battle settlement policy is introduced. This does not qualify trade evolution, mail, offer menus or the final trading interface.

`SessionStatus` contains only state, bounded code, connection availability, revision and process exit code. `LauncherSessionError` uses an allowlist of fixed messages; raw exceptions, credentials, IPC tokens and journal contents do not reach it. An optional synchronous `on_status` callback receives lifecycle changes; callback exceptions are counted and cannot cancel the lifecycle. A UI should also poll `session.status` for current connection state, because network observations do not create controller actions.

Connection loss during a running game changes its observable status while the runtime continues to own the process and save lease. This component deliberately implements no pause/continue gameplay decision, offline merge, automatic recovery, battle result, forfeit or payout. The owner's offline and interrupted-battle policies remain pending. Normal process exit is not a final-save acknowledgment. Autosave stays disabled, and its measured pause/performance and shutdown integration remain separate delivery gates.

## Explicit first-enrollment backend

[EnrollmentRuntime](../src/emerald_multiplayer/enrollment_runtime.py) now supplies a separate local backend for an existing, wholly unassigned legacy source. The application explicitly calls `approve_enrollment_source(store, player_id, source_path)` on its schema-3 host store. This reuses [OwnershipCheckpointStore.enroll_player](../src/emerald_multiplayer/ownership_storage.py) to retain the exact source bytes/hash, trainer and inventory provenance. Approval alone creates no canonical checkpoint and is not a remote registration capability. The original file is never written.

```python
approval = approve_enrollment_source(host_store, player_id, original_source)
bootstrap = EnrollmentRuntime(companion, bundle, private_profile,
                              private_profile / "character.sav", approval)
async with bootstrap.open() as game:
    # The player uses ordinary Continue, then reaches a safe native field point.
    # The GUI must present this step; no timed input is hidden in this backend.
    result = await bootstrap.enroll()
```

The companion must already authenticate the approved world/account/build. `open()` refuses an existing canonical head, private save/sidecar, active game, or unresolved export/trade/battle/enrollment intent. It verifies the source and runtime, retains an immutable private source plus `pending-enrollment.json`, and copies the source only under [MirrorLease](../src/emerald_multiplayer/checkpoint_mirror.py). A private shared process helper rechecks installation identity and owns cancellation/termination; the lease outlives child creation and exit. Leaving the context drains any concurrent enrollment operation before closing the child.

Explicit `enroll()` uses [LiveCheckpointCoordinator.enroll()](../src/emerald_multiplayer/live_checkpoint.py): the authenticated grant is journaled before native ID assignment, frozen export commits exact bytes at base 0 to revision 1, and native END acknowledges the complete export. The store still requires the original approved boxed content and locations. A definite native unsafe/busy refusal permits a safe-point retry in the same context; uncertainty does not. On success the bootstrap child closes before the completion receipt is written. Its source copy, grants and export receipts remain private evidence. Subsequent play always uses [PlayerRuntime.open()](../src/emerald_multiplayer/player_runtime.py) and [ColdStartRecovery](../src/emerald_multiplayer/cold_start.py), which install the canonical owned save. Normal startup has no enrollment bypass.

After interruption, a fresh `EnrollmentRuntime(...).recover()` validates the exact retained approval/intent and runs ordinary closed reconciliation under its save lease. It can retry the same frozen first export or recover a committed result whose server/native acknowledgment was lost, without allocating another grant or copying the original source over the character. It never launches a game. If no canonical head or durable export exists, or evidence is malformed/conflicting, it preserves the attempt and refuses automatic restart. Explicit handling of such abandoned pre-export attempts remains a follow-up; no gameplay rollback or offline merge is inferred.

Both live enrollment and closed recovery capture their authenticated session before waiting for the lifecycle lock and recheck it inside that lock. A reconnect while waiting cannot start a grant/export or canonical restore under a different session. These optional admission fences preserve existing callers' behavior and add no wire operation.

This backend accepts host-approved private files. The later [setup GUI](windows-launcher-gui.md) now provides explicit approval and enrollment over this controller, plus ordinary New Game preparation through `DraftRuntime`; remote source submission is still absent. The [four-player prepare harness](../scripts/multiplayer/four_player_proof.py) is a development reference. Real own-dump patch acceptance, required 18-starter selection and character customization remain separate work. Neither this backend nor its fixture tests qualify native Windows enrollment gameplay or choose offline/interrupted-battle policy.

### Reuse review for this composition

The October 8 audit inspected the pinned engine ownership/save contracts (RHH base `bb1093a`, qualified combined source `afd92ce`), existing ownership proof, and pinned mGBA `26b7884` runtime. Read-only upstream checks returned RHH [`6057b187f946094d614e9c34bc12731ea6a5b7bb`](https://github.com/rh-hideout/pokeemerald-expansion/tree/6057b187f946094d614e9c34bc12731ea6a5b7bb) and mGBA [`143adf5aa2a60c6036810b0cd72445e13d74b0e6`](https://github.com/mgba-emu/mgba/tree/143adf5aa2a60c6036810b0cd72445e13d74b0e6); neither is imported. The engine already supplies ordinary New Game/Continue and native ownership export; the existing companion/store supplies authenticated grants and revision checks. The [mGBA scripting API](https://mgba.io/docs/scripting.html) provides core integration, not this application's account/provenance enrollment contract. Custom composition of the qualified local APIs is needed; no new framework, native memory-writing path, dependency or save migration is added. Existing license/attribution obligations remain in the [dependency ledger](dependency-ledger.md).

Python's official [subprocess lifecycle](https://docs.python.org/3/library/asyncio-subprocess.html) and [cancellation shielding](https://docs.python.org/3/library/asyncio-task.html#shielding-from-cancellation) support retaining the existing shell-free process owner and draining cancellation before releasing the save lease. The code shares that implementation instead of creating another child-process manager. Functional fixture timings do not establish native export performance; the existing [save performance boundary](save-performance.md) remains applicable.

## Verification boundary

`tests/test_launcher_session.py` exercises genuine encrypted Flash fixtures, SQLite ownership heads, generated pinned TLS, actual `WorldServer`/`Companion` sockets, real subprocesses and OS save locks. Only the native executable is replaced by a controlled Python child. The tests cover distinct Host/Join identities, advertised/local route separation, missing enrollment, default-host startup with new trades disabled, malformed pending battle preservation, installation changes, duplicate launches, canceled process creation, cleanup ordering, existing save locks, authenticated reconnect, running disconnect observation and status secrecy. Recovery extensions cover each participant's committed canonical save, foreign/mismatched acknowledgments, retained unresolved local intent, and a lost ACK followed by fresh default-host startup.

On October 8, 2026, all **63 tests in the affected launcher/runtime/cold-start/host/invitation group passed on both Windows and WSL**, without skips. This includes 16 new launcher tests. Windows completed in 35.058 seconds; WSL completed in 38.371 seconds. An independent read-only review found no lifecycle, identity or status-secrecy blocker. Its terminal-status observation was corrected: readiness after a finished launch preserves FINISHED, and readiness after closure refuses the operation without replacing CLOSED. Both paths are covered by the final tests.

The private `artifacts/windows-runtime` logs are `launcher-session-windows-2.log`, SHA-256 `172dec8866c0ebb96b1cd6035cf4db58310fcdb20629faf9a5135679617a42f3`, and `launcher-session-wsl-2.log`, SHA-256 `8464645fb8b4535adf294c1d8935f4f6ef532b390d00e174ea630fc3a1e1b399`. The WSL archive copy was hash-verified against its original. These are functional development timings, not game-performance measurements.

The subsequent default-host recovery change passed **91 affected launcher/trade-network/battle-arbitration/cold-start/runtime/host/invitation tests on both Windows and WSL**, without skips, on October 8, 2026. The launcher module now has 20 tests. Windows completed in 80.972 seconds; WSL completed in 180.543 seconds while a native build ran separately. An independent read-only review found no authentication, ownership, mutation-gate or launch-before-recovery blocker.

Its private logs are `launcher-recovery-windows-1.log`, SHA-256 `93c224fecb0fb43cf26c1ccdeb000483ee8d1889b99cb4af989ee4a2d20f7cfe`, and `launcher-recovery-wsl-1.log`, SHA-256 `3c329de8e202ecbdf04ffdceb4e607d5e4fe19dfeeeb2fff168b024fd51d226a`, under the same archive directory. The copied WSL log matches its original hash. These runs check the default-host recovery change and its adjacent lifecycle gates; they do not constitute another full-suite run or a native-game performance measurement.

The first-enrollment backend and shared process refactor subsequently passed **105 affected tests on both Windows and WSL**, without skips, including **18 new enrollment tests**. Windows completed in 63.631 seconds and WSL in 91.694 seconds. Actual TLS, SQLite, checkpoint transfer, child processes and OS locks are exercised; only the native mailbox/Flash production is a strict fixture. Coverage includes an unchanged approved source, refusal before copy/launch, first revision, mandatory later canonical restore, interrupted upload, lost server/native acknowledgments, exact recovery without another grant, repeated cancellation, concurrent context closure, and session changes while waiting for admission. An independent review found the lock-contention gaps; their explicit fences and regression tests are included in these final results.

Private logs under `artifacts/windows-runtime` are `enrollment-runtime-windows-1.log`, SHA-256 `cf983b3a7c8acf1f4e4662f974e6f69dd0c72aedf4b6157b5044652e10bcd901`, and `enrollment-runtime-wsl-1.log`, SHA-256 `ded9a79dc50f1b0f9d3c81f3b71caff47a3a02da5a6e4ae8133a89371f96ed9d`. The copied WSL log matches its original. These are affected-group lifecycle results, not a full-suite rerun, native enrollment gameplay or performance acceptance.

The later [Windows launcher record](windows-launcher-gui.md) covers implemented Host/Join/setup screens, bundled Python/dependency notices, BPS import, explicit Save now and native runtime qualification. Full new-character/enrollment gameplay, a real own-dump release patch, Windows keyboard/audio/gamepad checks, final save/disconnect policies, and clean-machine/LAN/Internet tests remain separate delivery gates.
