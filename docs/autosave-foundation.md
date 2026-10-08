# Verified checkpoint scheduler

`AutosaveScheduler` schedules the existing ROM-owned live checkpoint lifecycle. Its caller supplies an existing local revision verified by startup, enrollment, or recovery, and an interval. The owner subsequently selected a five-minute default-on policy with an off switch and manual saving retained; the [launcher integration](launcher-session.md#five-minute-autosave-and-save-now) now supplies that policy and a persistent per-character preference. `PlayerRuntime` and the companion do not independently create timers. The scheduler never enrolls a legacy character, adopts a newly queried server head, resolves journals, restores a save, or accesses a native `.sav` file.

The optional [read-only save window](save-window.md) has passed actual-core export and recovery tests. Its subsequent [CRC optimization](save-performance.md) measured a 6.328-second checkpoint with headless cores paced at 60 frames/s; the original window version took 9.298 seconds and the original 1,024 sequential reads took 39.254 seconds. The faster unthrottled result does not represent normal gameplay speed. That player's native callbacks, RNG streams, and playtime remain held throughout; this is still too long for transparent periodic saving and does not establish usable Windows autosave performance. The scheduler simply calls the existing coordinator and does not select or weaken transport capability. Performance and actual player-facing pause/status behavior remain delivery gates.

The API is explicit:

```python
from emerald_multiplayer.autosave import AutosaveScheduler
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator

coordinator = LiveCheckpointCoordinator(companion, private_directory)
scheduler = AutosaveScheduler(
    coordinator, expected_revision=verified_revision,
    interval=explicit_interval_seconds,
    safe_point=lambda: runtime_alive_and_no_battle_or_reset,
    on_status=update_status,
)
await scheduler.start()  # Authenticate and obtain the verified live bridge first.
try:
    await game.wait()
finally:
    await scheduler.stop()
```

Lifecycle integration must stop/await the scheduler before terminating the core or releasing its file lease. Normal runtime exit still does not imply a final save. The example is scheduling scaffolding, not a complete shutdown controller: a launcher that owns game closure must coordinate it, and an already user-closed core causes terminal bridge loss. This module does not implement the subsequently selected host-loss save-and-disconnect policy or interrupted-battle preservation; those require their dedicated recovery controllers.

One companion can own one scheduler. One worker coalesces overdue timer ticks and explicit `request()` signals into one due operation. No export overlaps another; a slow export does not accumulate a backlog. The next interval starts after completion, and requests received during a save cannot cause an immediate catch-up burst. Shared live-checkpoint locks and lifecycle owners defer autosave rather than queueing an export behind another operation. Manual/trade/recovery flows that advance the character revision should stop autosave and create a new scheduler only after verifying their resulting revision.

Before an attempt, the scheduler checks the same durable world/player/build/ruleset/profile, server epoch, lease and local game incarnation. The child rechecks that binding before starting, and the coordinator also checks the pinned world/lease/incarnation after acquiring its lifecycle lock, before any checkpoint RPC or ROM command. It requires a fresh monotonic local pose with available overworld presence, a verified save-capable bridge, and no pending trade, active save/battle RPC, blocked bridge admission or other lifecycle owner. Heartbeats alone never establish a safe scene. A synchronous additional `safe_point` gate lets the runtime explicitly exclude a native battle, Local Soft Reset, or another operation. New reset/battle integration must provide that gate or own the shared lifecycle lock; this scheduler does not implement either feature. The ROM's stable-field predicate remains the final admission authority.

Only explicitly marked pre-export admission `rom_busy`/`rom_unsafe` refusals without a durable export journal are deferred at the bounded polling cadence. Lost/changed authentication, incarnation or world; canceled or uncertain commands; pending export journals; revision conflicts; malformed results; and unexpected errors stop the worker in `RECOVERY_REQUIRED`. Reconnect does not resume it. Journals and their exact bytes/base/UUID remain owned by the existing coordinator. Explicit live or closed-game reconciliation is required before creating a replacement scheduler with a verified revision. There is no automatic offline saving or automatic rollback.

Successful revision updates require the coordinator's typed completed result, matching build/profile, next revision, operation UUID, full native-Flash SHA256, and absence of a pending export. Status observers receive bounded state/code/revision/count fields without credentials or raw exception details. Observer exceptions are counted and cannot cancel a save; an invalid or failing safe-point callback stops scheduling. `stop()` is idempotent and drains an in-flight checkpoint through repeated caller cancellation before returning or re-raising cancellation. It never cancels the coordinator to hurry shutdown.

`tests/test_autosave.py` uses injected monotonic clocks and slow/error coordinators for timer, gating and cancellation policy. Six additional cases use the real live coordinator, full wire codecs, checkpoint client transfers and SQLite with a strict synthetic-ROM Flash endpoint: a complete durable export/release, lost committed acknowledgment with explicit exact retry, an external-head conflict rejected before any ROM command, definite initial admission refusal, READ BUSY followed by lost cancellation while the ROM remains frozen, and reconnect while the child waits for the lifecycle lock. They preserve a sentinel native-save file throughout. This is scheduler/lifecycle coverage, not actual emulator, Windows autosave, Internet, or offline-policy acceptance.

Foundation validation on 2026-10-08: all 57 targeted scheduler/live-checkpoint/player-runtime tests passed on Windows Python 3.14 (7.696 seconds) and WSL Python 3.12 (7.777 seconds), including 25 scheduler tests. No skips or unexpected loop errors occurred. Existing asyncio debug slow-task notices under concurrent builds did not indicate test failures. The scheduler was disabled in normal runtime at that checkpoint; the later launcher integration and its separate verification are recorded in [launcher-session.md](launcher-session.md).
