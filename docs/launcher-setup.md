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

The explicit host-approved source is an existing wholly unassigned legacy Flash container. Only its private copy is launched, under the existing save lease and source/export journals. Setup keeps new trades disabled. Enrollment establishes native revision one; success closes the bootstrap child before its receipt completes. The context drains that runtime, then closes companion, listener and store, retaining ownership through cancellation. All future play goes through ordinary canonical recovery. Another player's source can be approved for its provisioned friend slot locally by the host; this is not remote source submission or a registration RPC.

Status callbacks receive frozen `SetupStatus(phase, code)` records: validation, approval, connection, the ordinary Continue step, completion, or a bounded failure. No credentials, raw exceptions or source paths appear in those records. Observer errors cannot cancel cleanup. An uncertain attempt retains its original source, approval, private copy and journals; this controller adds no retry, recopy, offline merge, battle settlement or abandoned-attempt deletion policy.

Selecting no source returns `source_required`. Ordinary New Game creation, the required starter selector/content and customization, remote source approval, and integration/acceptance of GUI inputs remain separate tasks. This controller does not synthesize a starter save or write emulator RAM. Its automated tests use native Flash/export fixtures, so they do not establish actual native or Windows enrollment gameplay acceptance.

## Reuse and verification

The [enrollment reuse review](launcher-session.md#reuse-review-for-this-composition) applies unchanged: this is composition of the existing `HostWorld`, pinned-TLS `WorldServer`/`Companion`, `EnrollmentRuntime`, and cancellation-safe process owner. No new library, upstream source, native effect or save format is incorporated.

`tests/test_launcher_setup.py` covers unique unbooted private worlds, pin changes before creation, friend-only invitations and no overwrite, missing sources and invalid slots, real TLS authentication, explicit revision-one enrollment, separate friend identity, active-host refusal before provenance mutation, retained uncertain journals, cancellation with real child/OS lock cleanup, and public status/error secrecy. Native enrollment uses the existing strict mailbox fixture; the network, SQLite, child process and save locks are real.

On October 8, 2026, the setup/enrollment/launcher/host/invitation group passed **60 tests on both Windows and WSL**, without skips, including ten new setup tests. Windows completed in 64.351 seconds and WSL in 100.194 seconds. The private `artifacts/windows-runtime` logs are `launcher-setup-windows-2.log`, SHA-256 `b715d510aea01414b815eacd8725b48eb638fcf50eee7cf9df411cb6a7eb39b9`, and `launcher-setup-wsl-1.log`, SHA-256 `ae24a9d6225b469994d048bc1506d3b67e52a3f1bae8ef2f453866adc1c4f373`. The WSL archive copy matches its original. These affected-group results do not constitute native gameplay, final GUI acceptance, or a full-suite rerun.
