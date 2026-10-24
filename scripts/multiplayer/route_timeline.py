"""Proof instrumentation for KNOWN_ISSUES MS-17: where a native battle command spends its time, hop by hop.

In two four-game runs the host's own core missed its 600-frame deadline: between two QUERY rounds the friends' cores
used 9-18 frames, the host's core all 577 it had left, and no launcher loop stalled over 1.5 s. The route's own record
(battle_execution.py: room.hops, room.polls, <battle>.diagnosis.json) says when a command was published, first handed
to a companion and answered; this timeline adds what happens in between, for every player:

    command / response  the route's journal entry (RouteJournal.append): a command published, a response accepted
    handed / acked      the server's exchange() handing a new command to a companion, or taking a new response
    poll_gap            a companion's polls more than 50 ms apart (the server's view)
    execute             a companion's poll RPC that brought a command or carried a response, or took over 50 ms
    send                a companion's message to the server that waited over 20 ms for the send lock or the drain
    outbox              a battle command ('D') that waited over 20 ms in the companion's bridge queue
    rpc                 a command's trip companion -> game -> companion, with the game's frame counter before and after
                        (the last pose the game sent: frames the game ran meanwhile)
    persist             a companion's battle state write over 20 ms
    lag                 a launcher loop that woke over 50 ms late (a 20 ms sampler: sustained load a 1.5 s stall
                        watchdog misses)
    stall               a published command unanswered for STALL seconds: every thread's stack, every companion's
                        asyncio tasks (their stacks), pending RPCs, send lock and bridge queue - once per command
    gc                  a garbage collection over 20 ms (it stops every thread of the process: the four launchers share
                        one here, as they never do on PCs), with its generation and the objects it went through
    pause               the whole process stopped over 200 ms (a monitor thread that should wake every 50 ms woke late;
                        a loop's own watchdog thread stops with it and can miss it)

All times are time.monotonic() seconds, the clock of the route's own hops. Nothing here changes what the launcher, the
companion or the route does: each wrapper calls the original and only writes down when and how long.
"""
from __future__ import annotations

import asyncio
import functools
import json
import threading
import time
from pathlib import Path
from uuid import uuid4

SLOW = .05      # a poll RPC, a poll gap
WAIT = .02      # a send-lock wait, a drain, a bridge queue wait, a state write
LAG = .05       # a loop wake-up this late
STALL = 2.0     # a command unanswered this long gets the stall probe (the core's deadline is 10 s)
# Fault injection, proofs only: {player label: dict(seconds=S, after=N)} holds the Nth QUERY after that player's own
# game started its battle for S seconds before the companion hands it to the game, as a command to the host's own core
# was held up in win-ffa-exit-1 (KNOWN_ISSUES MS-17). The other games' commands are not held.
DELAYS: dict = {}


class Timeline:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.out = self.path.open("a", buffering=1)

    def write(self, event: str, **fields):
        fields = dict(t=round(time.monotonic(), 4), ev=event, **fields)
        with self.lock:
            self.out.write(json.dumps(fields, separators=(",", ":")) + "\n")

    def watch(self, slot: int, loop) -> None:
        """A 20 ms sampler on a launcher's loop: every wake-up more than LAG late."""
        async def sampler():
            while True:
                before = time.monotonic()
                await asyncio.sleep(.02)
                late = time.monotonic() - before - .02
                if late > LAG:
                    self.write("lag", slot=slot, late=round(late, 3))
        asyncio.run_coroutine_threadsafe(sampler(), loop)


def _stack(frame, limit=25):
    import traceback
    return [f"{f.filename.rsplit('/', 2)[-1]}:{f.lineno} {f.name}: {(f.line or '').strip()}"
            for f in traceback.extract_stack(frame)[-limit:]]


def _task_stacks(loop):
    out = []
    try:
        tasks = list(asyncio.all_tasks(loop))
    except RuntimeError:
        return out
    for task in tasks:
        try:
            frames = task.get_stack(limit=12)
        except Exception:  # noqa: BLE001 - a record only
            frames = []
        out.append(dict(name=task.get_name(), stack=[f"{f.f_code.co_filename.rsplit('/', 2)[-1]}:{f.f_lineno} "
                                                    f"{f.f_code.co_name}" for f in frames]))
    return out


def probe_stalls(timeline: Timeline, services, companions, name_of, stop: threading.Event) -> None:
    """A thread: every 0.25 s, each route's published commands; one unanswered for STALL seconds gets a record of
    where everything is (once per command)."""
    import sys
    done = set()
    while not stop.wait(.25):
        try:
            _probe_once(timeline, services, companions, name_of, done)
        except Exception as error:  # noqa: BLE001 - the probe must outlive any surprise; say so and go on
            timeline.write("stall_probe_error", error=f"{type(error).__name__}: {error}")


def _probe_once(timeline, services, companions, name_of, done):
    import sys
    now = time.monotonic()
    if True:
        for service in list(services):
            for room in list(getattr(service, "rooms", {}).values()):
                for actor, hops in list(room.hops.items()):
                    for hop in list(hops):
                        key = (room.battle.battle_id, actor, hop["dispatch"])
                        if hop["answered"] is not None or key in done or now - hop["published"] < STALL:
                            continue
                        done.add(key)
                        record = dict(battle=room.battle.battle_id, who=name_of(actor) or actor, dispatch=hop["dispatch"],
                                      op=hop["opcode"], age=round(now - hop["published"], 3),
                                      delivered=None if hop["delivered"] is None else round(now - hop["delivered"], 3),
                                      pending={name_of(a) or a: p[2] for a, p in list(room.pending.items())})
                        record["companions"] = []
                        for companion in list(companions):
                            bridge = getattr(companion, "_bridge", None)
                            outbox = getattr(bridge, "outbox", None)
                            loop = getattr(companion, "_timeline_loop", None)
                            record["companions"].append(dict(
                                who=name_of(getattr(companion.config, "player_id", None)),
                                battle_pending=list(getattr(companion, "_battle_pending", {}).keys()),
                                challenge_pending=len(getattr(companion, "_challenge_pending", {})),
                                remote_lock=getattr(getattr(companion, "_remote_lock", None), "locked", lambda: None)(),
                                bridge=None if bridge is None else dict(
                                    controls=len(outbox.controls), closed=outbox.closed,
                                    snapshots=[name for name in ("pending", "pending_world", "pending_spawns",
                                                                 "pending_extras") if getattr(outbox, name) is not None]),
                                pose_frame=getattr(getattr(companion, "_local_pose", None), "frame", None),
                                tasks=_task_stacks(loop) if loop is not None else None))
                        record["threads"] = {str(ident): _stack(frame) for ident, frame in sys._current_frames().items()}
                        timeline.write("stall", **record)


def watch_process(timeline: Timeline) -> None:
    """Garbage collections over 20 ms and pauses of the whole process over 200 ms."""
    import gc
    started = {}

    def on_gc(phase, info):
        if phase == "start":
            started["t"] = time.perf_counter()
        elif "t" in started:
            seconds = time.perf_counter() - started.pop("t")
            if seconds > .02:
                timeline.write("gc", generation=info.get("generation"), seconds=round(seconds, 4),
                               collected=info.get("collected"))
    gc.callbacks.append(on_gc)

    def monitor():
        last = time.monotonic()
        while True:
            time.sleep(.05)
            now = time.monotonic()
            if now - last > .25:
                timeline.write("pause", seconds=round(now - last - .05, 3))
            last = now
    threading.Thread(target=monitor, name="route-timeline-pauses", daemon=True).start()


def install(timeline: Timeline, name_of) -> None:
    """Wrap the companion, the battle session, the bridge queue, the route's exchange and journal. name_of(player_id)
    gives a player's label (or None)."""
    from emerald_multiplayer import companion as companion_module
    from emerald_multiplayer.battle_execution import BattleExecutionService
    from emerald_multiplayer.battle_execution_journal import RouteJournal
    from emerald_multiplayer.battle_session import NativeBattleSession
    from emerald_multiplayer.bridge_protocol import BridgeOutbox
    from emerald_multiplayer.native_battle import NativeQuery, Opcode
    from emerald_multiplayer.protocol import encode_message
    Companion = companion_module.Companion

    import weakref
    companions, services = weakref.WeakSet(), weakref.WeakSet()
    original_companion_init = Companion.__init__

    @functools.wraps(original_companion_init)
    def companion_init(self, *args, **kwargs):
        original_companion_init(self, *args, **kwargs)
        try:
            self._timeline_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._timeline_loop = None
        companions.add(self)
    Companion.__init__ = companion_init

    original_service_init = BattleExecutionService.__init__

    @functools.wraps(original_service_init)
    def service_init(self, *args, **kwargs):
        original_service_init(self, *args, **kwargs)
        services.add(self)
    BattleExecutionService.__init__ = service_init
    threading.Thread(target=probe_stalls, args=(timeline, services, companions, name_of, threading.Event()),
                     name="route-timeline-stalls", daemon=True).start()
    watch_process(timeline)

    def who(companion):
        player = getattr(getattr(companion, "config", None), "player_id", None)
        return name_of(player) or player

    def frame(companion):
        pose = getattr(companion, "_local_pose", None)
        return None if pose is None else pose.frame

    # The companion's messages to the server: the send lock (shared with presence, pongs, rival polls) and the drain.
    async def _send_remote(self, writer, message):
        asked = time.monotonic()
        async with self._remote_lock:
            got = time.monotonic()
            writer.write(encode_message(message))
            await asyncio.wait_for(writer.drain(), self.config.send_timeout)
        done = time.monotonic()
        if got - asked > WAIT or done - got > WAIT:
            timeline.write("send", who=who(self), type=message.get("type"), wait=round(got - asked, 4),
                           drain=round(done - got, 4))
    Companion._send_remote = _send_remote

    original_execute = Companion.battle_challenge_rpc

    @functools.wraps(original_execute)
    async def battle_challenge_rpc(self, operation, *, request_id=None, **fields):
        if operation != "execute":
            return await original_execute(self, operation, request_id=request_id, **fields)
        request_id = str(uuid4()) if request_id is None else request_id
        self._timeline_loop = asyncio.get_running_loop()
        began = time.monotonic()
        try:
            reply = await original_execute(self, operation, request_id=request_id, **fields)
        except BaseException as error:
            timeline.write("execute", who=who(self), request=request_id, began=round(began, 4),
                           error=f"{type(error).__name__}: {error}")
            raise
        ended = time.monotonic()
        view = reply.get("result", {}) if isinstance(reply, dict) else {}
        command = view.get("command_b64") is not None
        if command or fields.get("response_b64") is not None and fields.get("response_id") != getattr(
                self, "_timeline_last_response", None) or ended - began > SLOW:
            timeline.write("execute", who=who(self), request=request_id, began=round(began, 4),
                           seconds=round(ended - began, 4), command=view.get("command_id") if command else None,
                           response=fields.get("response_id"), state=view.get("state"))
        if fields.get("response_b64") is not None:
            self._timeline_last_response = fields.get("response_id")
        return reply
    Companion.battle_challenge_rpc = battle_challenge_rpc

    original_rpc = Companion.battle_rpc

    @functools.wraps(original_rpc)
    async def battle_rpc(self, control, *, timeout=5.0):
        plan = DELAYS.get(who(self))
        if plan is not None and not plan.get("done"):
            if control.opcode == Opcode.START:
                plan["started"] = True
            elif plan.get("started") and control.opcode == Opcode.QUERY:
                plan["queries"] = plan.get("queries", 0) + 1
                if plan["queries"] == plan["after"]:
                    plan["done"] = True
                    timeline.write("delay", who=who(self), seq=control.sequence, seconds=plan["seconds"],
                                   frame=frame(self))
                    await asyncio.sleep(plan["seconds"])
        began, first = time.monotonic(), frame(self)
        try:
            response = await original_rpc(self, control, timeout=timeout)
        except BaseException as error:
            timeline.write("rpc", who=who(self), op=int(control.opcode), seq=control.sequence, began=round(began, 4),
                           frame=first, error=f"{type(error).__name__}: {error}")
            raise
        timeline.write("rpc", who=who(self), op=int(control.opcode), seq=control.sequence, began=round(began, 4),
                       seconds=round(time.monotonic() - began, 4), frame=first, frames=None if first is None or
                       frame(self) is None else (frame(self) - first) & 0xFFFFFFFF, status=int(response.status))
        return response
    Companion.battle_rpc = battle_rpc

    original_persist = NativeBattleSession._persist

    @functools.wraps(original_persist)
    def _persist(self, *args, **kwargs):
        began = time.monotonic()
        try:
            return original_persist(self, *args, **kwargs)
        finally:
            seconds = time.monotonic() - began
            if seconds > WAIT:
                timeline.write("persist", who=who(self.companion), seconds=round(seconds, 4))
    NativeBattleSession._persist = _persist

    # The bridge queue: how long a battle command ('D') waits before the writer takes it.
    queued = {}
    original_put, original_get = BridgeOutbox.put_control, BridgeOutbox.get

    @functools.wraps(original_put)
    def put_control(self, payload, **kwargs):
        original_put(self, payload, **kwargs)
        if payload[:1] == b"D" and self.controls:
            queued[id(self.controls[-1])] = (self.controls[-1], time.monotonic(), len(self.controls))
    BridgeOutbox.put_control = put_control

    @functools.wraps(original_get)
    async def get(self):
        frame_bytes = await original_get(self)
        entry = queued.pop(id(frame_bytes), None) if frame_bytes is not None else None
        if entry is not None and entry[0] is frame_bytes:
            waited = time.monotonic() - entry[1]
            if waited > WAIT:
                timeline.write("outbox", waited=round(waited, 4), depth=entry[2])
        return frame_bytes
    BridgeOutbox.get = get

    # The server's side: every exchange() of a native battle (the host's loop).
    polls = {}
    original_exchange = BattleExecutionService.exchange

    @functools.wraps(original_exchange)
    def exchange(self, actor, lease, request):
        now = time.monotonic()
        state = polls.setdefault(actor, dict(last=None, handed=None, acked=None))
        if state["last"] is not None and now - state["last"] > SLOW:
            timeline.write("poll_gap", who=name_of(actor) or actor, gap=round(now - state["last"], 4),
                           request=request.get("request_id"))
        state["last"] = now
        view = original_exchange(self, actor, lease, request)
        if request.get("response_b64") is not None and request.get("response_id") != state["acked"]:
            state["acked"] = request.get("response_id")
            timeline.write("acked", who=name_of(actor) or actor, response=state["acked"],
                           request=request.get("request_id"), seconds=round(time.monotonic() - now, 4))
        if view.get("command_b64") is not None and view.get("command_id") != state["handed"]:
            state["handed"] = view.get("command_id")
            timeline.write("handed", who=name_of(actor) or actor, command=state["handed"],
                           request=request.get("request_id"), seconds=round(time.monotonic() - now, 4))
        return view
    BattleExecutionService.exchange = exchange

    # KNOWN_ISSUES MS-62: when each pushed observation reached the route (the journal records them without a time), and
    # every observe call the host answered (accepted or not: a refused one is sent again later).
    original_observe = RouteJournal.observe

    @functools.wraps(original_observe)
    def journal_observe(self, actor, control):
        result = original_observe(self, actor, control)
        timeline.write("observation", who=name_of(actor) or actor)
        return result
    RouteJournal.observe = journal_observe

    original_service_observe = BattleExecutionService.observe

    @functools.wraps(original_service_observe)
    def service_observe(self, actor, lease, request):
        room = self.rooms.get(request.get("battle_id"))
        pending = None if room is None or actor not in room.pending else room.pending[actor][2]
        view = original_service_observe(self, actor, lease, request)
        if not view.get("accepted"):
            timeline.write("observe_refused", who=name_of(actor) or actor, pending=pending)
        return view
    BattleExecutionService.observe = service_observe

    # Every fsync, by thread (the host's route journal, the launchers' records, the stores): counted and timed, written
    # as a running total every 10 s by the monitor below.
    import os as _os
    fsyncs = {}
    real_fsync = _os.fsync

    def counted_fsync(fd):
        began = time.perf_counter()
        try:
            return real_fsync(fd)
        finally:
            name = threading.current_thread().name
            count, seconds = fsyncs.get(name, (0, 0.0))
            fsyncs[name] = (count + 1, seconds + time.perf_counter() - began)
    _os.fsync = counted_fsync

    def fsync_totals():
        while True:
            time.sleep(10)
            timeline.write("fsyncs", totals={name: [count, round(seconds, 3)] for name, (count, seconds) in fsyncs.items()})
    threading.Thread(target=fsync_totals, name="route-timeline-fsyncs", daemon=True).start()

    original_append = RouteJournal.append

    @functools.wraps(original_append)
    def append(self, kind, actor, dispatch_id, control):
        began = time.monotonic()
        result = original_append(self, kind, actor, dispatch_id, control)
        extra = {}
        if kind == "response" and control.opcode == Opcode.QUERY and control.data:
            try:
                extra["left"] = NativeQuery.unpack(control.data).remaining_frames
            except Exception:  # noqa: BLE001 - a record only
                pass
        timeline.write(kind, who=name_of(actor) or actor, dispatch=dispatch_id, op=int(control.opcode),
                       status=int(getattr(control, "status", 0)), write=round(time.monotonic() - began, 4), **extra)
        return result
    RouteJournal.append = append
