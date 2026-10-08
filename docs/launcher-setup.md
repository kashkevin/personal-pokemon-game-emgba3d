# Local host setup controller

[`launcher_setup.py`](../src/emerald_multiplayer/launcher_setup.py) composes the existing private world and [first-enrollment backend](launcher-session.md#explicit-first-enrollment-backend) for launcher forms. These are developer entry points; they do not authorize an unattended enrollment or replace the player's explicit host approval.

`create_world(installation, private_root, *, player_names, endpoint, port)` verifies the application's exact ROM, manifest and runtime pins, then creates a new UUID-named directory under `private_root/worlds`. It returns the existing `HostWorld` value. The existing API generates one host and up to three distinct friends, certificate/key, credentials and schema-3 store. It never overwrites a world or opens a listener. Incomplete creation stays marked for inspection.

`export_friend_invitation(installation, world_directory, slot, destination)` validates the installation and world, then exclusively creates the selected friend's invitation at the explicit Save As destination. Slot zero is refused; an existing file is never replaced. The return value is the destination `Path`, not a credential-bearing status record. The invitation itself is a private access credential intended for that friend.

```python
async with host_enrollment(
    installation, private_root,
    world_directory=host.directory, slot=0,
    source_path=approved_original_save,
    bind_address="127.0.0.1", on_status=show_setup_status,
) as runtime:
    # Player uses ordinary Continue and reaches a safe field point.
    # Invoke only after the explicit Finish enrollment action.
    await runtime.enroll()
# Now normal LauncherSession/PlayerRuntime performs canonical closed recovery.
```

`host_enrollment` yields an **already opened** `EnrollmentRuntime`; callers must not enter its `open()` again. The context validates the selected existing account slot and retains the advertised invitation endpoint while choosing a local socket route with the original TLS pin. Binding and the store's exclusive host lock precede source approval. A currently running host therefore prevents a second setup from altering enrollment provenance or fencing its active lease. Close the ordinary host session before starting setup.

Setup preflights the pinned native executable, ROM, canonical character path and the shorter `private_root/launches/<UUID>/bridge.lua` location before opening the host or approving its source. The [Windows path bound](launcher-session.md#native-launch-paths) is checked again by enrollment before copying a source or writing an intent, and by the child owner before spawn. A rejected location leaves no new source approval or bootstrap attempt. Draft preparation applies the same native path guard before creating its private directory. None of these checks move an existing character or change its save lease.

The explicit host-approved source is an existing wholly unassigned legacy Flash container. Only its private copy is launched, under the existing save lease and source/export journals. Setup keeps new trades disabled. Enrollment establishes native revision one; success closes the bootstrap child before its receipt completes. The context drains that runtime, then closes companion, listener and store, retaining ownership through cancellation. All future play goes through ordinary canonical recovery. Another player's source can be approved for its provisioned friend slot locally by the host; this is not remote source submission or a registration RPC.

Status callbacks receive frozen `SetupStatus(phase, code)` records: validation, approval, connection, the ordinary Continue step, completion, or a bounded failure. No credentials, raw exceptions or source paths appear in those records. Observer errors cannot cancel cleanup. An uncertain attempt retains its original source, approval, private copy and journals; this controller adds no retry, recopy, offline merge, battle settlement or abandoned-attempt deletion policy.

Selecting no source returns `source_required`; the separate draft runtime below creates that source through ordinary player inputs. The required starter selector/content and customization, remote source approval, and integration/acceptance of GUI inputs remain separate tasks. These controllers do not synthesize a starter save or write emulator RAM. Their automated tests use native Flash/export fixtures, so they do not establish actual native or Windows enrollment gameplay acceptance.

## Ordinary New Game source preparation

[`DraftRuntime`](../src/emerald_multiplayer/draft_runtime.py) opens a brand-new private save path under `private_root/drafts/<UUID>`. It accepts no imported save, world, account, credential, or companion. It verifies the installed ROM/manifest/runtime, holds `MirrorLease`, writes a constant comment-only Lua chunk, and launches the existing SDL adapter with its explicit script/save arguments. The script attaches no callbacks and makes no IPC, network, input or memory calls. The SDL adapter's save isolation, reset/state/cheat protections remain enabled. The game itself creates the save file through its ordinary New Game and Save behavior.

```python
draft = DraftRuntime(installation, private_root)
async with draft.open() as game:
    # Player completes ordinary New Game, chooses a starter, saves, and
    # closes the game window. No timed keys are sent by this backend.
    await game.wait()
    source = draft.finish()
# Only now select source.source_path and request separate host approval.
```

`finish()` runs while the draft's save lease is held, after natural process exit with code zero. It requires a complete pinned legacy Flash container, wholly unassigned inventory and at least one party Pokémon. Missing/partial/owned saves, starterless saves, running games and abnormal exits cannot produce a source receipt. A successful private receipt binds the exact source hash and installed build; it grants no identity or canonical revision. The original draft remains intact when the enrollment workflow later copies it. Duplicate finish and context reuse are refused; another attempt receives another fresh directory.

Cancellation and forced shutdown retain the incomplete draft and wait for late child creation/termination before releasing the save lease. They do not publish a source or automatically resume a draft. This is preparation of a never-enrolled character, so it adds no offline gameplay or merge rule for an owned character. The GUI must select `DraftSource.source_path` only after the context has closed.

The exact pinned mGBA `26b7884` source `src/core/core.c:mCoreLoadSaveFile` opens the explicit missing save with `O_CREAT | O_RDWR`. The project adapter [`mSDLMultiplayerLoad`](../native/windows-runtime/sdl-multiplayer.c) already loads that path and a Lua chunk before starting the core; no native frontend changes are needed. The official [Lua chunk definition](https://www.lua.org/manual/5.4/manual.html#3.3.2) and [mGBA scripting API](https://mgba.io/docs/scripting.html) support the empty script path. The inspected qualified engine `afd92ce` already permits ordinary native saves while ownership metadata is legacy/unassigned. Current upstream/reuse and license boundaries remain those in the enrollment review; no upstream source or new dependency is imported. This small process composition is necessary because ordinary `PlayerRuntime` correctly requires an existing canonical checkpoint and must keep doing so.

## Reuse and verification

The [enrollment reuse review](launcher-session.md#reuse-review-for-this-composition) applies unchanged: this is composition of the existing `HostWorld`, pinned-TLS `WorldServer`/`Companion`, `EnrollmentRuntime`, and cancellation-safe process owner. No new library, upstream source, native effect or save format is incorporated.

`tests/test_launcher_setup.py` covers unique unbooted private worlds, pin changes before creation, friend-only invitations and no overwrite, missing sources and invalid slots, real TLS authentication, explicit revision-one enrollment, separate friend identity, active-host refusal before provenance mutation, retained uncertain journals, cancellation with real child/OS lock cleanup, and public status/error secrecy. Native enrollment uses the existing strict mailbox fixture; the network, SQLite, child process and save locks are real.

On October 8, 2026, the setup/enrollment/launcher/host/invitation group passed **60 tests on both Windows and WSL**, without skips, including ten new setup tests. Windows completed in 64.351 seconds and WSL in 100.194 seconds. The private `artifacts/windows-runtime` logs are `launcher-setup-windows-2.log`, SHA-256 `b715d510aea01414b815eacd8725b48eb638fcf50eee7cf9df411cb6a7eb39b9`, and `launcher-setup-wsl-1.log`, SHA-256 `ae24a9d6225b469994d048bc1506d3b67e52a3f1bae8ef2f453866adc1c4f373`. The WSL archive copy matches its original. These affected-group results do not constitute native gameplay, final GUI acceptance, or a full-suite rerun.

The subsequent draft/setup/process group passed **34 tests on both Windows and WSL**, without skips, including **12 new draft tests**. Windows completed in 16.426 seconds and WSL in 14.070 seconds. The tests exercise real child processes and OS save locks, with controlled Flash fixtures standing in for the native New Game/Save result. They cover strict source qualification, abnormal exit, repeated cancellation during late process creation, retained unfinished drafts, unique paths, relative ROM resolution and refusal to overwrite an existing draft. An independent read-only review of both setup and draft modules found no admission, cleanup or lease-order blocker. Actual Windows New Game, native Save, keyboard/starter interaction and end-to-end enrollment remain unqualified by these tests.

Private logs under the same archive directory are `draft-runtime-windows-2.log`, SHA-256 `e69cba714f7da3de719ea82d76ee36e4776a6eebb74feec484d1812414312207`, and `draft-runtime-wsl-1.log`, SHA-256 `b3104081b58e76f3653ed636e37ad3e5eb155978582cd2a7b0097303837431d9`. The WSL physical copy is hash-verified against its original; these functional timings are not native performance measurements.
