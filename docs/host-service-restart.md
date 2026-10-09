# Restarting a retained host service

The launcher now exposes **Restart host service** in a running host window.
It becomes available when the host is disconnected and its exact original
battle remains recoverable, after conflicting game, save, settings and
recovery operations have finished. Joining players do not see this action.

The action keeps the original game process, PlayerRuntime, Companion, bridge,
native incarnation and battle intent. It verifies the installed game and the
original world descriptor, including the certificate pin, endpoint, port,
accounts and credentials. It then drains automatic saving, finishes closing
the old WorldServer and store, and opens a new real service and store for that
same world on the owning session's event loop. It does not replace saves,
create a world or clear battle journals.

After the service returns, **every original player, including the host, must
press Recover battle**. The existing native recovery protocol still requires
the original roster and durable receipts before resuming. Restarting the
service does not reconnect players, resume a core or enable saving by itself.
The existing terminal battle handoff restores saving after verified recovery.

Restart work retains ownership through cancellation and is drained before
session cleanup. Failed shutdown/setup keeps its remaining service/store
references for retry or final cleanup; a second service cannot be opened over
an owned store. A failed old heartbeat task is drained without preventing
connection shutdown. Changed installation or world identity is refused. The GUI
provides restarting, restarted, unavailable and not-ready states without
displaying credentials, paths or exception details.

Implementation: `launcher_session.py` provides `can_restart_host_service` and
`restart_host_service`; `launcher_gui.py` exposes the serialized SessionWorker
action and host-only button; `server.py` supplies read-only `is_serving` status.

This handles an interrupted host service while the original launcher and
native game processes survive. It cannot reconstruct a game after the host
application or PC exits. Non-battle disconnect saving continues to use the
existing emergency preservation and reopen flow.

Status: implemented, **not executed or tested** after the user's instruction
to stop testing. Earlier private service-restart proof code and partial runs
do not verify this newly added production button and lifecycle.
