# Windows launcher lifecycle foundation

The player package remains in development. The native Windows runtime, Host/Join interface, new-character enrollment/import flow, save scheduling, connection policy and clean-machine acceptance have separate gates. This document records the implemented lifecycle for an already enrolled character; it does not qualify a downloadable release.

## Verified startup and process ownership

`player_runtime.PlayerRuntime.open()` checks a pinned runtime bundle and the actual ROM/manifest, then enters `ColdStartRecovery.open()` while the game is closed. Recovery acquires the save lease, reconciles durable pending intent, installs the current canonical checkpoint and records evidence before yielding. Companion IPC refuses both new and already waiting bridge hellos while this reconciliation runs.

Only then does the launcher create a private per-launch Lua configuration and start the native runtime with explicit game/save/script paths. It uses an argument array without a shell, a new private working directory, a private log, and no additional caller-supplied emulator flags. The SDL game has its own window; Windows receives no console window. The same save lease remains held until the child exits. If startup is cancelled while process creation is outstanding, the launcher first obtains and closes that child, including through repeated cancellation, before releasing its lease. A changed authenticated session during process creation prevents the launcher from yielding a playable instance.

Normal callers wait for the player to close the native window inside the context. An error or cancelled context terminates a remaining process. This does not imply that unsynchronized progress has been saved; canonical checkpoints and retained transaction journals remain the recovery authority. The launcher does not infer an offline merge or automatically confirm a trade.

## Bundle contract

`RuntimeBundle` requires an application-supplied SHA-256 pin for `runtime.json`; a manifest cannot establish its own trust. The strict manifest has exactly `format`, `executable`, `bridge` and `files`. Format is `emerald-windows-runtime-v1`. `files` maps two to thirty-two simple filenames to SHA-256 hashes, including the `.exe`, `.lua` bridge and shipped DLLs. Every component is rehashed before launch. Duplicate JSON keys, ambiguous case variants, path escapes, linked components, changed files and unlisted executable/DLL/Lua files are refused. The eventual package builder must embed the generated manifest pin in the launcher and include dependency notices and corresponding covered source.

This detects accidental/inconsistent bundles and binds the expected shipped runtime. It is not a substitute for installer signing, secure updates or review of included game assets. Private character saves, journals, tokens and server databases are never runtime-bundle components.

## Verification and remaining work

Twelve new bundle/process tests use real child processes, SQLite/Flash recovery and OS save locking. Together with the affected cold-start, companion and bridge-manifest tests, **51 tests pass on Windows and WSL without skips** (12.424 and 15.597 seconds). A pending-hello test proves rejected connections do not acquire a game incarnation or change the authenticated server lease. Independent review caught a pinning gap across awaited recovery; the launcher now rechecks both runtime and ROM/manifest after reconciliation, with tests for each changing before launch. The process tests deliberately run a Python child, so they verify lifecycle and cancellation rather than native Windows gameplay.

The bridge configuration renderer now lives in `emerald_multiplayer.bridge_config`; the existing developer script imports the same function. Existing save/trade ABIs and verified ROM identity checks are unchanged.

The process fixtures now launch the actual base interpreter on Windows, because a virtual-environment `python.exe` redirects to a second process. The first combined run under the private cryptography environment exposed two crash tests terminating only that redirector while the interpreter correctly retained its save/database lock. A diagnostic confirmed the different launcher/interpreter process IDs. The fixtures now assert that their reported lock-owning PID equals the process being terminated. All 47 storage, mirror and runtime tests pass on Windows and WSL after that correction; production file locking and the native SDL executable were not changed.

The native SDL Windows build now passes an actual `PlayerRuntime.open()` proof with a copied, closed consistent world backup. Recovery installed current revision 4 before opening the core; the save lease blocked another owner throughout ordinary Continue and normal window closure. Read-only native party Box CRCs and IDs matched canonical state, and the copied database head and original source hashes remained unchanged. The child exited 0. This used a separately pinned proof Lua template with ordinary timed Start/A inputs; Windows keyboard, audible playback and gamepads remain unqualified. Bundle/component pins, covered-source/relink material and the immutable evidence hash are recorded in [windows-runtime.md](windows-runtime.md).

The final UI must hold this context through game closure, present recovery errors, supply only revisions established by verified startup/transactions, and manage the companion/server lifetimes. Host/Join packaging and new-character enrollment remain separate gates. Autosave must measure and reduce the current per-frame Flash transfer pause before selecting a shipping interval. Final server-loss behavior still awaits the owner's decision; it is not chosen by this foundation.
