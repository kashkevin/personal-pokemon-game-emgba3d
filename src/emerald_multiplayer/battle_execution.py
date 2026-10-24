"""Host-owned native battle execution with one exact command per participant.

This reuses the qualified full-Multi batch router. It consumes authenticated
mailbox responses, never diagnostic RAM, choices, damage, or claimed winners.
Uncertain execution remains reserved; ABI 3 interruption is not auto-resumable.
"""
from __future__ import annotations

import asyncio
from collections import deque
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
import struct
import time
import traceback
import zlib

from .battle_controller import ControllerValidator
from .battle_desk import BattleError
from .battle_execution_protocol import decode_control, encode_control, execution_view
from .battle_execution_journal import RouteJournal
from .battle_mailbox import Status
from .battle_roster import validate_auxiliary_startup
from .live_checkpoint import _atomic, _json_bytes
from .native_battle import DELIVER_ACK, DELIVER_MAX_BYTES, Kind, NativeControl, NativeQuery, Opcode, pack_deliver, pack_receive_many

# KEEP refreshes a core's native watchdog (MULTIPLAYER_BATTLE_DEADLINE, 600 frames) and the desk's
# host deadline. Every accepted mutating command refreshes the native watchdog too; QUERY does not,
# and reports the frames left. So a slot gets KEEP when its last query showed fewer than
# KEEP_BELOW_FRAMES frames left (at least 8 s of the 10 s budget remain for the next step), or when
# KEEP_EVERY_STEPS steps passed without one (the desk's 180 s host deadline during long transfers).
# Both inputs are journaled responses and step counts, never wall time, so recovery replays the same
# commands: a wall-clock throttle (tried first) made replay diverge from the journal.
KEEP_BELOW_FRAMES = 480
KEEP_EVERY_STEPS = 32
# The observed router (KNOWN_ISSUES MS-62, run_observed): a launcher reports its core's state as it changes (it says when
# fewer than KEEP_OBSERVED_FRAMES frames are left, and the core's own grace adds 20 s), and a slot gets KEEP then, or after
# KEEP_OBSERVED_COMMANDS other commands (the desk's 180 s host deadline). Both come from journaled evidence.
KEEP_OBSERVED_FRAMES = 240
KEEP_OBSERVED_COMMANDS = 64
# The transport commands. With a route journal they need no room record of their own (the journal holds them).
TRANSPORT = frozenset((Opcode.QUERY, Opcode.PEEK, Opcode.READ_OUT, Opcode.RECEIVE, Opcode.RECEIVE_MANY, Opcode.DELIVER,
                       Opcode.ACK_OUT, Opcode.KEEP))
OBSERVE_SCOPE = "native-battle-observation-v1"
# The master's last command of a battle (engine CONTROLLER_ENDLINKBATTLE): the delivering router defers nothing after it.
CONTROLLER_ENDLINKBATTLE = 50


async def _independent(*commands):
    """Settle every issued mailbox command before advancing or failing a batch."""
    tasks = [asyncio.create_task(command) for command in commands]
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return results
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@dataclass
class _Room:
    battle: object
    path: Path
    ready: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)
    acknowledged: dict = field(default_factory=dict)
    dispatch_ids: dict = field(default_factory=dict)
    state: str = "waiting"
    task: object = None
    error: str | None = None
    route: object = None
    journal: object = None
    admitted: dict = field(default_factory=dict)
    # Diagnosis only (KNOWN_ISSUES MS-17): each player's last commands (published, first handed to that player's
    # companion, answered) and the gaps between that companion's polls; written with the route's exception when the
    # route stops (<battle_id>.diagnosis.json). Never persisted with the intent, never read back.
    hops: dict = field(default_factory=dict)
    polls: dict = field(default_factory=dict)
    # KNOWN_ISSUES MS-62: a held execute poll's wake-up when its player's next command is published (server.py).
    waiters: dict = field(default_factory=dict)


HOPS_KEPT = 48


class BattleExecutionService:
    """Only enable with the string table from the exact installed ROM.

    Durable command/response intents supplement the existing same-DB character
    reservations. Restart leaves those reservations waiting; it does not rebuild
    native RAM or invent route acknowledgments from this audit record.
    """

    def __init__(self, desk, string_lengths, directory, *, observer=None, resume_enabled=False, peek=False,
                 receive_many=False, deliver=False):
        if desk is None:
            raise ValueError("native execution requires an enabled BattleDesk")
        ControllerValidator(string_lengths)
        self.desk, self.string_lengths = desk, string_lengths
        if observer is not None and not callable(observer):
            raise ValueError("execution observer must be a trusted callable")
        self.observer = observer
        if type(resume_enabled) is not bool:
            raise ValueError("resume capability must be explicitly verified")
        self.resume_enabled = resume_enabled
        # KNOWN_ISSUES MS-62: the games have battle PEEK (bridge_config.battle_peek_enabled; every player of a world runs the
        # same build): new battles use the observed router and journal v4.
        if type(peek) is not bool:
            raise ValueError("battle PEEK must be explicitly verified")
        self.peek = peek
        # ... and RECEIVE_MANY (bridge_config.battle_receive_many_enabled): their 2v2s use journal v5.
        if type(receive_many) is not bool or (receive_many and not peek):
            raise ValueError("battle RECEIVE_MANY must be explicitly verified, beside PEEK")
        self.receive_many = receive_many
        # ... and DELIVER (bridge_config.battle_deliver_enabled, KNOWN_ISSUES MS-62's battle speed): new battles of every
        # format use the delivering router and journal v6.
        if type(deliver) is not bool or (deliver and not receive_many):
            raise ValueError("battle DELIVER must be explicitly verified, beside RECEIVE_MANY")
        self.deliver = deliver
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.rooms = {}
        self.native_sequences = {}
        self.recovery = None
        from .battle_admission_host import BattleAdmissionHost
        self.admission = BattleAdmissionHost(self)

    def reconnect(self, actor, lease, request):
        if self.recovery is None:
            from .battle_recovery import BattleRecoveryService
            self.recovery = BattleRecoveryService(self)
        return self.recovery.exchange(actor, lease, request)

    def _persist(self, room):
        b = room.battle
        _atomic(room.path, _json_bytes(dict(format="native-battle-execution-intent-v1",
            world_id=self.desk.store.metadata.world_id, build_id=self.desk.store.build_id,
            ruleset_id=self.desk.store.ruleset_id, battle_id=b.battle_id,
            generation=b.generation, fingerprint=b.fingerprint, players=list(b.players),
            leases=list(b.leases), incarnations=dict(room.ready), state=room.state,
            error=room.error,
            admitted=room.admitted,
            pending={p: [value[2], encode_control(value[0])] for p, value in room.pending.items()},
            acknowledged={p: [value[0], encode_control(value[1])] for p, value in room.acknowledged.items()})))

    def exchange(self, actor, lease, request):
        self.admission.assert_not_canceled(request["battle_id"])
        battle = self.desk._get(actor, lease, request["battle_id"], request["generation"])
        room = self.rooms.get(battle.battle_id)
        if room is None:
            path = self.directory / (battle.battle_id + ".json")
            if (battle.state == "recovery_required" and self.resume_enabled and not battle.bind_intent
                    and not battle.bound and not path.exists()):
                # The challenge ended (a trainer could not enter, or cancelled) after this trainer's Enter was recorded
                # but before its core's first poll made the room (L stale-save-4, KNOWN_ISSUES MS-60). Say so, as for a
                # room still waiting, so its launcher cancels the entry neutrally (battle_entry_unstarted, then
                # cancel_admission); answering battle_not_ready left that launcher holding the battle for recovery.
                return execution_view(battle.battle_id, battle.generation, "recovery_required")
            if battle.state != "accepted" or battle.consent != set(battle.players):
                raise BattleError("battle_not_ready", "all trainers must accept this exact challenge")
            if request["response_b64"] is not None:
                raise BattleError("invalid_receipt", "no native command was issued")
            if path.exists():
                raise BattleError("battle_recovery_required", "persisted native execution needs recovery")
            completed = [key for key, value in self.rooms.items() if value.state in ("closed", "aborted")]
            for key in completed[:-63]:
                del self.rooms[key]
            room = _Room(battle, path)
            battle.resumable = self.resume_enabled
            self.rooms[battle.battle_id] = room
        if room.battle is not battle:
            raise BattleError("battle_generation_mismatch", "execution belongs to a different battle")
        now = time.monotonic()
        poll = room.polls.setdefault(actor, dict(first=now, last=now, count=0, longest=0.0, longest_at=None))
        if now - poll["last"] > poll["longest"]:
            poll["longest"], poll["longest_at"] = now - poll["last"], poll["last"]
        poll["last"] = now
        poll["count"] += 1
        if room.error == "abandoned":
            # battle_abandonment.py stopped this route: no command is issued or acknowledged any more.
            return execution_view(battle.battle_id, battle.generation, "aborted")
        if battle.state == "aborted" and not battle.bind_intent:
            room.state = "aborted"
            self._persist(room)
            return execution_view(battle.battle_id, battle.generation, room.state)
        if battle.state == "recovery_required" and room.state == "waiting" and room.task is None and not battle.bind_intent:
            # The challenge ended before any BIND (a trainer cancelled or could not enter, its time limit passed). The
            # room never left "waiting", so an entered core polled it for good, held (seen 2026-10-20). Say so; that
            # core's launcher cancels its entry neutrally (battle_entry_unstarted, then cancel_admission).
            return execution_view(battle.battle_id, battle.generation, "recovery_required")
        incarnation = request["incarnation"]
        if actor in room.ready and room.ready[actor] != incarnation:
            self._fail(room, "incarnation_changed")
            raise BattleError("battle_incarnation_changed", "retain the original held battle core")
        if actor not in room.ready:
            if room.state != "waiting":
                raise BattleError("battle_state", "this battle cannot register another core")
            self.desk.register(actor, lease, battle.battle_id, battle.generation, incarnation)
            if battle.resumable:
                original, held = self.admission.prove(actor, lease, request)
                if original["leases"] != list(battle.leases):
                    raise BattleError("battle_incarnation_changed", "execution changed the original consent leases")
                self.native_sequences[actor] = (lease, incarnation, held.last_sequence)
            room.ready[actor] = incarnation
            self._persist(room)
        admission = request.get("admission_sha256")
        if admission is not None and room.admitted.get(actor) != admission:
            pending = room.pending.get(actor)
            if (not battle.resumable or room.state != "admitting" or pending is None
                    or pending[0].opcode != Opcode.BIND or room.journal is None
                    or hashlib.sha256(pending[0].pack()).hexdigest() != admission):
                raise BattleError("invalid_admission", "persist the exact host-issued BIND before acknowledging admission")
            room.journal.admit(actor, admission)
            room.admitted[actor] = admission
            if len(room.admitted) == len(battle.players):
                room.state = "executing"
            self._persist(room)
        if request["response_b64"] is not None:
            if room.state == "admitting":
                raise BattleError("battle_not_admitted", "no native BIND may execute before every durable intent acknowledgment")
            response = decode_control(request["response_b64"], response=True)
            # Repeated polling may acknowledge the previous command while the
            # next command is being issued. Only byte-identical replay is inert.
            acknowledged = (request["response_id"], response)
            if room.acknowledged.get(actor) != acknowledged:
                pending = room.pending.get(actor)
                if pending is None:
                    raise BattleError("invalid_receipt", "no matching native command is outstanding")
                command, future, dispatch_id = pending
                if request["response_id"] != dispatch_id:
                    raise BattleError("invalid_receipt", "native receipt changed its dispatch ID")
                try:
                    response.validate_response(command)
                except ValueError as error:
                    raise BattleError("invalid_receipt", "native response differs from the outstanding command") from error
                previous = room.acknowledged.get(actor)
                if room.journal is not None:
                    room.journal.append("response", actor, request["response_id"], response)
                room.acknowledged[actor] = acknowledged
                del room.pending[actor]
                if room.journal is None or command.opcode not in TRANSPORT:
                    try:
                        self._persist(room)
                    except BaseException:
                        room.pending[actor] = pending
                        if previous is None:
                            room.acknowledged.pop(actor, None)
                        else:
                            room.acknowledged[actor] = previous
                        raise
                route = room.route
                if route is not None and route.observed:
                    route.on_response(actor, command, response)
                hop = next((h for h in room.hops.get(actor, ()) if h["dispatch"] == dispatch_id), None)
                if hop is not None:
                    hop["answered"], hop["status"] = time.monotonic(), int(response.status)
                if not future.done():
                    if response.status == Status.OK and command.opcode != Opcode.QUERY:
                        self.native_sequences[actor] = (lease, incarnation, command.sequence)
                    future.set_result(response)
        if room.task is None and room.state == "waiting" and len(room.ready) == len(battle.players):
            room.state = "executing"
            self._persist(room)
            room.task = asyncio.create_task(self._drive(room), name="native-battle-execution")
        pending = room.pending.get(actor)
        pending = pending if room.state in ("admitting", "executing") else None
        if pending is not None:
            hop = next((h for h in room.hops.get(actor, ()) if h["dispatch"] == pending[2]), None)
            if hop is not None and hop["delivered"] is None:
                hop["delivered"] = time.monotonic()
        return execution_view(battle.battle_id, battle.generation, room.state,
                              None if pending is None else pending[0], 0 if pending is None else pending[2])

    def _fail(self, room, reason):
        if room.error == "abandoned":
            return  # the abandoned route's own cancellation; the battle has no recovery to wait for
        room.state, room.error = "recovery_required", reason
        self.desk._recover(room.battle, reason)
        self._persist(room)

    async def _command(self, room, actor, command):
        b = room.battle
        self.admission.assert_not_canceled(b.battle_id)
        self.desk._get(actor, b.leases[b.players.index(actor)], b.battle_id, b.generation)
        if actor in room.pending:
            raise BattleError("battle_order", "one native command may be outstanding per player")
        future = asyncio.get_running_loop().create_future()
        dispatch_id = room.dispatch_ids.get(actor, 0) + 1
        if dispatch_id > 0x7FFFFFFF:
            raise BattleError("counter_exhausted", "native dispatch counter is exhausted")
        room.dispatch_ids[actor] = dispatch_id
        room.pending[actor] = (command, future, dispatch_id)
        room.hops.setdefault(actor, deque(maxlen=HOPS_KEPT)).append(dict(
            dispatch=dispatch_id, opcode=int(command.opcode), published=time.monotonic(), delivered=None,
            answered=None, status=None))
        # Publication precedes dispatch. Cancellation/timeout keeps the intent.
        if b.resumable:
            if room.journal is None:
                row = self.desk.store._connection.execute(
                    "SELECT * FROM battle_reservations WHERE battle_id=?", (b.battle_id,)).fetchone()
                record = self.desk.reservations._read(row)
                from .battle_execution_journal import DELIVER_FORMAT, MANY_FORMAT, OBSERVED_FORMAT
                route = room.route
                room.journal = RouteJournal(self.directory / (b.battle_id + ".events.jsonl"),
                    dict(record=record, battle_id=b.battle_id, generation=b.generation, players=list(b.players),
                        leases=list(b.leases), incarnations=[room.ready[p] for p in b.players], mode=b.mode,
                        initial_sequences=list(route.sequences)), create=True,
                    format=(DELIVER_FORMAT if route.deliver else MANY_FORMAT if route.many else OBSERVED_FORMAT)
                    if route.observed else None)
            room.journal.append("command", actor, dispatch_id, command)
            if command.opcode == Opcode.BIND and len(room.admitted) != len(b.players):
                room.state = "admitting"
        if room.journal is None or command.opcode not in TRANSPORT:
            self._persist(room)
        self._wake(room, actor)
        try:
            return await asyncio.wait_for(asyncio.shield(future), 20)
        finally:
            if not future.done():
                future.cancel()

    async def _dispatch(self, room, actor, command):
        return command, await self._command(room, actor, command)

    @staticmethod
    def _wake(room, actor):
        for waiter in room.waiters.pop(actor, ()):
            if not waiter.done():
                waiter.set_result(None)

    async def published(self, room, actor, timeout):
        """KNOWN_ISSUES MS-62: wait (at most timeout seconds) until actor's next command is published, without polling."""
        if actor in room.pending:
            return
        waiter = asyncio.get_running_loop().create_future()
        room.waiters.setdefault(actor, []).append(waiter)
        try:
            await asyncio.wait_for(waiter, timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            if actor in room.waiters and waiter in room.waiters[actor]:
                room.waiters[actor].remove(waiter)

    def observe(self, actor, lease, request):
        """KNOWN_ISSUES MS-62: a launcher's report of its core's state and new block (a PEEK response), as it happens.

        Only an observed route takes it, and only while that player has no outstanding command (its state could not
        have changed since); it is journaled first, and the route answers it in journal order. Otherwise it is refused
        (accepted false) and the launcher reports again. The delivering route (journal v6) also takes one while a command
        is outstanding: a report made before the launcher ran that command (it never looks while it holds one) is of the
        state the route knows, and the route ignores what the command may have changed (_fresh, a report older than the
        core's last command); one made after it ran, which overtook the command's answer, is taken right after the
        answer (_NativeRoute._observation)."""
        from .native_battle import peek_parts
        self.admission.assert_not_canceled(request["battle_id"])
        battle = self.desk._get(actor, lease, request["battle_id"], request["generation"])
        room = self.rooms.get(battle.battle_id)
        route = None if room is None else room.route
        view = dict(scope=OBSERVE_SCOPE, battle_id=battle.battle_id, generation=battle.generation,
                    accepted=False, routed=route is not None and route.observed)
        if (room is None or room.battle is not battle or route is None or not route.observed
                or room.state not in ("admitting", "executing") or room.error is not None
                or room.ready.get(actor) != request["incarnation"] or (actor in room.pending and not route.deliver)):
            return view
        slot = battle.players.index(actor)
        response = decode_control(request["observation_b64"], response=True)
        if (response.opcode != Opcode.PEEK or response.status or response.battle_id != battle.battle_id
                or response.incarnation != request["incarnation"] or response.session_epoch != battle.leases[slot]
                or response.source_slot != slot or response.phase != battle.mode):
            raise BattleError("invalid_receipt", "native observation differs from this player's held core")
        try:
            peek_parts(response)
        except ValueError as error:
            raise BattleError("invalid_receipt", "native observation is inconsistent") from error
        if room.journal is not None:
            room.journal.observe(actor, response)
        route.on_observation(actor, response)
        view["accepted"] = True
        return view

    async def _resumed_command(self, room, actor, command):
        pending = room.journal.pending.get(actor)
        if pending is None:
            return await self._command(room, actor, command)
        dispatch_id, recorded = pending
        if recorded != command or actor in room.pending:
            raise BattleError("battle_order", "recovery cannot replace the exact uncertain route command")
        future = asyncio.get_running_loop().create_future()
        room.pending[actor] = (command, future, dispatch_id)
        self._persist(room)
        try:
            return await asyncio.wait_for(asyncio.shield(future), 20)
        finally:
            if not future.done():
                future.cancel()

    async def _drive(self, room):
        b = room.battle
        try:
            route = _NativeRoute(self, room)
            room.route = route
            await route.run()
            if room.error == "abandoned":
                return
            room.state = "closed"
            self._persist(room)
        except asyncio.CancelledError:
            self._fail(room, "execution_stopped")
            raise
        except Exception as error:
            # No automatic winner, release, retirement, fresh BIND or save.
            self._fail(room, "execution_interrupted")
            self._diagnose(room, "execution_interrupted", error)

    def _diagnose(self, room, reason, error):
        """Why a route stopped (KNOWN_ISSUES MS-17): its exception and each player's last command hops, in seconds
        before now. A record for people; nothing reads it back, and failing to write it changes nothing."""
        now = time.monotonic()

        def ago(value):
            return None if value is None else round(now - value, 3)
        try:
            players = []
            for slot, actor in enumerate(room.battle.players):
                poll = room.polls.get(actor)
                players.append(dict(
                    slot=slot,
                    polls=None if poll is None else dict(count=poll["count"], last=ago(poll["last"]),
                        longest=round(poll["longest"], 3), longest_began=ago(poll["longest_at"])),
                    hops=[dict(dispatch=h["dispatch"], opcode=h["opcode"], published=ago(h["published"]),
                               delivered=ago(h["delivered"]), answered=ago(h["answered"]), status=h["status"])
                          for h in room.hops.get(actor, ())],
                    pending=None if actor not in room.pending else room.pending[actor][2]))
            code = getattr(error, "code", None)
            record = dict(format="native-battle-route-diagnosis-v1", battle_id=room.battle.battle_id, reason=reason,
                          error=f"{type(error).__name__}: {error}", code=None if code is None else str(code),
                          traceback=traceback.format_exception(type(error), error, error.__traceback__)[-12:],
                          players=players)
            _atomic(self.directory / (room.battle.battle_id + ".diagnosis.json"), _json_bytes(record))
        except Exception:  # noqa: BLE001 - the record is best effort; the route's own outcome stands
            pass

    async def close(self):
        if self.recovery is not None:
            await self.recovery.close()
        tasks = [room.task for room in self.rooms.values() if room.task is not None and not room.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class _NativeRoute:
    def __init__(self, service, room):
        self.service, self.room, self.b = service, room, room.battle
        self.desk = service.desk
        self.count = len(self.b.players)
        self.validator = ControllerValidator(service.string_lengths, mode=self.b.mode)
        self.sequences = []
        for actor, lease in zip(self.b.players, self.b.leases):
            previous = service.native_sequences.get(actor)
            self.sequences.append(previous[2] if previous is not None
                and previous[:2] == (lease, room.ready[actor]) else 0)
        self.next_block, self.next_kind = [1] * self.count, [2] * self.count
        self.pending, self.receipts = [None] * self.count, {}
        self.running = False
        self.started = False
        self.steps_since_keep = [0] * self.count
        self.observed = False   # run_observed (KNOWN_ISSUES MS-62): responses and observations arrive as events
        self.many = False       # ... and packs RECEIVE_MANY (journal v5)
        self.deliver = False    # ... or acknowledges and delivers everything a core is owed in one DELIVER (journal v6)
        self.events = None

    def call(self, method, slot, *args, **kwargs):
        return getattr(self.desk, method)(self.b.players[slot], self.b.leases[slot],
            self.b.battle_id, self.b.generation, *args, **kwargs)

    async def rpc(self, slot, opcode, *, busy=False, **fields):
        source = fields.pop("source_slot", slot)
        command = NativeControl(self.room.ready[self.b.players[slot]], self.b.leases[slot],
            self.b.battle_id, self.sequences[slot] + 1, opcode,
            source_slot=source, phase=self.b.mode, **fields)
        command.validate_command(binding=self.desk._binding(self.b, self.b.players[slot]),
                                 player_id=self.b.players[slot])
        command, response = await self.service._dispatch(self.room, self.b.players[slot], command)
        response.validate_response(command)
        if response.status != Status.OK:
            if busy and response.status == Status.BUSY:
                return response
            raise BattleError("native_refused", "native battle command was refused")
        if opcode != Opcode.QUERY:
            self.sequences[slot] += 1
        self.receipts[slot, opcode] = (command, response)
        callback = {Opcode.BIND: "bound", Opcode.START: "started",
                    Opcode.KEEP: "keepalive", Opcode.RELEASE: "released"}.get(opcode)
        if callback:
            if (opcode == Opcode.RELEASE and self.room.journal is not None
                    and self.b.released | {self.b.players[slot]} == set(self.b.players)):
                self.room.journal.verify_current()
            self.call(callback, slot, command, response)
        return response

    async def queries(self):
        result = []
        responses = await _independent(*(self.rpc(slot, Opcode.QUERY) for slot in range(self.count)))
        for slot, response in enumerate(responses):
            q = NativeQuery.unpack(response.data)
            if (not q.held or q.expired or q.recovery_required
                    or (q.generation, q.local_slot, q.mode) != (self.b.generation, slot, self.b.mode)
                    or q.last_sequence != self.sequences[slot]):
                raise BattleError("battle_recovery_required", "native query differs from the held execution")
            result.append(q)
        return result

    async def step(self):
        queries = await self.queries()
        admit_batch = not any(self.pending)
        for source, q in enumerate(queries):
            if not admit_batch or not q.outbound_pending:
                continue
            if (q.outbound_sequence, q.outbound_kind, q.read_offset) != (
                    self.next_block[source], self.next_kind[source], 0):
                raise BattleError("battle_order", "native block order or read cursor differs")
            if q.outbound_kind == Kind.CONTROLLER and not self.running:
                continue
            data = b""
            for offset in range(0, q.outbound_size, 128):
                data += (await self.rpc(source, Opcode.READ_OUT, block_sequence=q.outbound_sequence,
                    offset=offset, total_size=q.outbound_size, kind=q.outbound_kind)).data
            if zlib.crc32(data) != q.outbound_crc32:
                raise BattleError("native_crc", "native complete block checksum differs")
            kind, roster = q.outbound_kind, self.b.roster[source]
            if kind in (Kind.TRAINER, Kind.PARTY_0, Kind.PARTY_1, Kind.PARTY_2):
                roster.verify_startup(kind, data)
                if kind == Kind.TRAINER:
                    self.call("prepared", source, *self.receipts[source, Opcode.PREPARE], data)
                else:
                    self.call("verify_startup", source, kind, q.outbound_sequence, data)
            elif kind in (Kind.START_HEADER, Kind.RNG):
                validate_auxiliary_startup(kind, data, issued_rng=roster.issued_rng(self.b.rng))
            else:
                self.validator.accept(data, source)
            self.pending[source] = dict(sequence=q.outbound_sequence, kind=kind,
                data=data, offsets=[0] * self.count, crc=q.outbound_crc32)
            if self.service.observer is not None:
                self.service.observer(dict(source=source, sequence=q.outbound_sequence,
                    kind=int(kind), data=data.hex()))
        for source, block in enumerate(self.pending):
            if block is None:
                continue
            data = block["data"]
            deliveries = []
            for target in range(self.count):
                offset = block["offsets"][target]
                if target == source or offset == len(data):
                    continue
                chunk = data[offset:offset + 128]
                deliveries.append((target, len(chunk), self.rpc(target, Opcode.RECEIVE, busy=True, source_slot=source,
                    block_sequence=block["sequence"], offset=offset, total_size=len(data),
                    kind=block["kind"], data=chunk)))
            # Different cores have independent mailboxes. Each command is
            # still durable before publication and each receipt before ACK;
            # the complete batch barrier below is unchanged.
            replies = await _independent(*(item[2] for item in deliveries))
            for (target, length, _), reply in zip(deliveries, replies):
                if reply.status == Status.OK:
                    block["offsets"][target] += length
            if all(target == source or block["offsets"][target] == len(data) for target in range(self.count)):
                await self.rpc(source, Opcode.ACK_OUT, block_sequence=block["sequence"], offset=len(data),
                    total_size=len(data), kind=block["kind"], data=struct.pack("<II", block["crc"],
                    ((1 << self.count) - 1) ^ (1 << source)))
                self.next_block[source] += 1
                self.next_kind[source] = min(8, self.next_kind[source] + 1)
                self.pending[source] = None
        if not any(self.pending):
            if not self.started and self.next_kind == [3] * self.count:
                self.desk.authorize_start(self.b.battle_id, self.b.generation)
                await _independent(*(self.rpc(slot, Opcode.START) for slot in range(self.count)))
                self.started = True
            if not self.running and self.next_kind == [8] * self.count:
                self.desk.authorize_running(self.b.battle_id, self.b.generation)
                self.running = True
        # Refresh the held native deadline where it is needed (see KEEP_BELOW_FRAMES). No local
        # gameplay controller, diagnostic core API or injected native outcome is used.
        journal = self.room.journal
        every_step = journal is not None and journal.keeps_every_step
        keep = [slot for slot, q in enumerate(queries)
                if every_step or q.remaining_frames < KEEP_BELOW_FRAMES
                or self.steps_since_keep[slot] + 1 >= KEEP_EVERY_STEPS]
        for slot in range(self.count):
            self.steps_since_keep[slot] = 0 if slot in keep else self.steps_since_keep[slot] + 1
        if keep:
            await _independent(*(self.rpc(slot, Opcode.KEEP) for slot in keep))
        return queries

    # ------------------------------------------------------------------ the pipelined router (journal v3)
    # KNOWN_ISSUES MS-62: battles over the internet were very slow. step() runs lock-step: every core's QUERY, then each
    # source's READ_OUT, then each block's RECEIVEs, then its ACK_OUT, one after another, so a block took four round
    # trips over the network and two blocks at once seven. A round gives every core its own most useful command and
    # runs them all at once (the cores' mailboxes are independent): ACK_OUT for a delivered block, KEEP when its
    # deadline needs it, RECEIVE for a block it is owed, READ_OUT for its new block, else QUERY. So the other core is
    # queried while a block is acknowledged, and read while that core is queried: three round trips a block, two blocks
    # at once in about four. The rules step() keeps hold: new blocks are admitted only with no block in flight, a
    # core's blocks in its own order, controller blocks only once running, every block delivered to every other core
    # before its ACK_OUT. The decisions use only the round's journaled answers, taken in slot order, so recovery
    # replays the same commands.

    def _choose(self, slot, idle):
        q = self.fresh[slot]
        if slot in self.ack_due:
            return ("ack",)
        if (q is not None and q.remaining_frames < KEEP_BELOW_FRAMES
                or self.rounds_since_keep[slot] + 1 >= KEEP_EVERY_STEPS):
            return ("keep",)
        for source, block in enumerate(self.pending):
            if block is not None and source != slot and block["offsets"][slot] < len(block["data"]):
                return ("receive", source)
        if idle and q is not None and q.outbound_pending and self.pending[slot] is None:
            if (q.outbound_sequence, q.outbound_kind, q.read_offset) != (
                    self.next_block[slot], self.next_kind[slot], 0):
                raise BattleError("battle_order", "native block order or read cursor differs")
            if not (q.outbound_kind == Kind.CONTROLLER and not self.running):
                return ("read", q)
        return ("query",)

    async def _command(self, slot, what):
        kind = what[0]
        if kind == "query":
            return await self.rpc(slot, Opcode.QUERY)
        if kind == "start":
            return await self.rpc(slot, Opcode.START)
        if kind == "keep":
            return await self.rpc(slot, Opcode.KEEP)
        if kind == "read":
            q, data = what[1], b""
            for offset in range(0, q.outbound_size, 128):
                data += (await self.rpc(slot, Opcode.READ_OUT, block_sequence=q.outbound_sequence,
                    offset=offset, total_size=q.outbound_size, kind=q.outbound_kind)).data
            return data
        if kind == "receive":
            block = self.pending[what[1]]
            offset = block["offsets"][slot]
            chunk = block["data"][offset:offset + 128]
            reply = await self.rpc(slot, Opcode.RECEIVE, busy=True, source_slot=what[1],
                block_sequence=block["sequence"], offset=offset, total_size=len(block["data"]),
                kind=block["kind"], data=chunk)
            return len(chunk), reply
        block = self.pending[slot]      # "ack"
        return await self.rpc(slot, Opcode.ACK_OUT, block_sequence=block["sequence"], offset=len(block["data"]),
            total_size=len(block["data"]), kind=block["kind"], data=struct.pack("<II", block["crc"],
            ((1 << self.count) - 1) ^ (1 << slot)))

    def _admit(self, source, q, data):
        if zlib.crc32(data) != q.outbound_crc32:
            raise BattleError("native_crc", "native complete block checksum differs")
        kind, roster = q.outbound_kind, self.b.roster[source]
        if kind in (Kind.TRAINER, Kind.PARTY_0, Kind.PARTY_1, Kind.PARTY_2):
            roster.verify_startup(kind, data)
            if kind == Kind.TRAINER:
                self.call("prepared", source, *self.receipts[source, Opcode.PREPARE], data)
            else:
                self.call("verify_startup", source, kind, q.outbound_sequence, data)
        elif kind in (Kind.START_HEADER, Kind.RNG):
            validate_auxiliary_startup(kind, data, issued_rng=roster.issued_rng(self.b.rng))
        else:
            self.validator.accept(data, source)
        self.pending[source] = dict(sequence=q.outbound_sequence, kind=kind,
            data=data, offsets=[0] * self.count, crc=q.outbound_crc32)
        if self.service.observer is not None:
            self.service.observer(dict(source=source, sequence=q.outbound_sequence,
                kind=int(kind), data=data.hex()))

    def _query(self, slot, response):
        q = NativeQuery.unpack(response.data)
        if (not q.held or q.expired or q.recovery_required
                or (q.generation, q.local_slot, q.mode) != (self.b.generation, slot, self.b.mode)
                or q.last_sequence != self.sequences[slot]):
            raise BattleError("battle_recovery_required", "native query differs from the held execution")
        return q

    async def round(self):
        """One round of the pipelined router; True once the battle is released."""
        idle = not any(self.pending) and not self.ack_due
        if idle and not self.started and self.next_kind == [3] * self.count:
            self.desk.authorize_start(self.b.battle_id, self.b.generation)
            plan = [(slot, ("start",)) for slot in range(self.count)]
        elif idle and self.running and all(q is not None and q.restored for q in self.fresh):
            for slot in range(self.count):
                self.call("finish_native", slot, *self.receipts[slot, Opcode.QUERY])
            for slot in range(self.count):
                await self.rpc(slot, Opcode.RELEASE, data=struct.pack("<II",
                    self.b.roster[slot].party_crc32, self.fresh[slot].outcome))
            return True
        else:
            plan = [(slot, self._choose(slot, idle)) for slot in range(self.count)]
        results = await _independent(*(self._command(slot, what) for slot, what in plan))
        for (slot, what), result in zip(plan, results):
            kind = what[0]
            self.fresh[slot] = self._query(slot, result) if kind == "query" else None
            self.rounds_since_keep[slot] = 0 if kind == "keep" else self.rounds_since_keep[slot] + 1
            if kind == "start":
                self.started = True
            elif kind == "read":
                self._admit(slot, what[1], result)
            elif kind == "receive" and result[1].status == Status.OK:
                self.pending[what[1]]["offsets"][slot] += result[0]
            elif kind == "ack":
                self.next_block[slot] += 1
                self.next_kind[slot] = min(8, self.next_kind[slot] + 1)
                self.pending[slot] = None
                self.ack_due.discard(slot)
        for source, block in enumerate(self.pending):
            if block is not None and all(target == source or block["offsets"][target] == len(block["data"])
                                         for target in range(self.count)):
                self.ack_due.add(source)
        if (self.started and not self.running and not any(self.pending) and not self.ack_due
                and self.next_kind == [8] * self.count):
            self.desk.authorize_running(self.b.battle_id, self.b.generation)
            self.running = True
        return False

    # ------------------------------------------------------------------ the observed router (journal v4)
    # KNOWN_ISSUES MS-62: battles over the internet were still far too slow (30-60 s between actions on two real PCs):
    # every block cost several round trips to a remote player, each one after the other, and the host learned of a new
    # block only by asking (QUERY), then read it (READ_OUT). With battle PEEK each launcher reports its core's state and
    # new block itself, as soon as they appear (BattleExecutionService.observe), so the host routes a block the moment it
    # exists: a RECEIVE to its other core, then its source's ACK_OUT. Nothing waits for another player's round trip but
    # what needs its answer. The rules the rounds keep hold: each core's blocks in its own order, controller blocks only
    # once running, every block delivered to every other core before its ACK_OUT, and every core receives the blocks in
    # one global order. Two cores also take a new block while another is still in flight (each hears from the other
    # only); three or four take new blocks only while none is in flight, as before. Decisions use only the
    # journaled responses and observations, one at a time, in the order the journal records them, so recovery replays
    # the same commands from the same events.

    def on_response(self, actor, command, response):
        self.events.put_nowait(("response", self.b.players.index(actor), command, response))

    def on_observation(self, actor, response):
        self.events.put_nowait(("observation", self.b.players.index(actor), None, response))

    def _issue(self, slot, opcode, what, **fields):
        source = fields.pop("source_slot", slot)
        command = NativeControl(self.room.ready[self.b.players[slot]], self.b.leases[slot],
            self.b.battle_id, self.sequences[slot] + 1, opcode, source_slot=source, phase=self.b.mode, **fields)
        command.validate_command(binding=self.desk._binding(self.b, self.b.players[slot]),
                                 player_id=self.b.players[slot])
        self.busy[slot] = (command, what)
        if opcode != Opcode.KEEP:
            self.since_keep[slot] += 1

        async def dispatch():
            try:
                await self.service._dispatch(self.room, self.b.players[slot], command)
            except BaseException as error:  # noqa: BLE001 - the route fails with it, as an awaited command would
                if not isinstance(error, asyncio.CancelledError):
                    self.events.put_nowait(("error", slot, command, error))
                raise
        task = asyncio.create_task(dispatch(), name="native-battle-command")
        self.tasks.add(task)
        task.add_done_callback(self._settled)

    def _settled(self, task):
        self.tasks.discard(task)
        if not task.cancelled():
            task.exception()   # retrieved: the route already has it as an event

    def _observation(self, slot, response):
        from .native_battle import peek_parts
        q, block = peek_parts(response)
        if (not q.held or q.expired or q.recovery_required
                or (q.generation, q.local_slot, q.mode) != (self.b.generation, slot, self.b.mode)):
            raise BattleError("battle_recovery_required", "native observation differs from the held execution")
        if q.last_sequence > self.sequences[slot]:
            busy = self.busy[slot]
            if self.deliver and busy is not None and busy[0].sequence == q.last_sequence:
                # The delivering router takes reports while a command is outstanding: this one was made after that
                # command ran and reached the host before its answer, so it is taken right after the answer.
                self.held[slot] = response
                return
            raise BattleError("battle_order", "native observation is ahead of its core's commands")
        self.seen[slot] = (q, block)

    def _fresh(self, slot):
        """The slot's latest observation while nothing that changes its outbound block has run since (ACK_OUT, READ_OUT)."""
        seen = self.seen[slot]
        return seen if seen is not None and seen[0].last_sequence >= self.outbound_changed[slot] else None

    def _response(self, slot, command, response):
        if self.busy[slot] is None or (self.busy[slot][0].opcode, self.busy[slot][0].sequence) != (
                command.opcode, command.sequence):
            raise BattleError("battle_replay_mismatch", "native response for no outstanding route command")
        _, what = self.busy[slot]
        self.busy[slot] = None
        opcode = command.opcode
        if response.status != Status.OK:
            if opcode in (Opcode.RECEIVE, Opcode.RECEIVE_MANY, Opcode.DELIVER) and response.status == Status.BUSY:
                if opcode == Opcode.DELIVER and what[1] is not None:
                    what[1]["ack_sent"] = False   # nothing applied (a busy core consumes no acknowledgement)
                return  # delivered again by the next plan
            raise BattleError("native_refused", "native battle command was refused")
        if opcode != Opcode.QUERY:
            self.sequences[slot] = command.sequence
        self.receipts[slot, opcode] = (command, response)
        callback = {Opcode.BIND: "bound", Opcode.START: "started",
                    Opcode.KEEP: "keepalive", Opcode.RELEASE: "released"}.get(opcode)
        if callback:
            if (opcode == Opcode.RELEASE and self.room.journal is not None
                    and self.b.released | {self.b.players[slot]} == set(self.b.players)):
                self.room.journal.verify_current()
            self.call(callback, slot, command, response)
        if opcode == Opcode.BIND:
            preparation = self.call("preparation", slot)
            self._issue(slot, Opcode.PREPARE, ("prepare",), data=preparation.pack())
        elif opcode == Opcode.PREPARE:
            self.prepared.add(slot)
        elif opcode == Opcode.START:
            self.start_done.add(slot)
            if len(self.start_done) == self.count:
                self.started = True
        elif opcode == Opcode.KEEP:
            self.since_keep[slot] = 0
        elif opcode == Opcode.READ_OUT:
            self.outbound_changed[slot] = command.sequence
            reading = self.reading[slot]
            reading["data"] += response.data
            if len(reading["data"]) == reading["q"].outbound_size:
                self.reading[slot] = None
                self._admit_block(slot, reading["q"], reading["data"])
        elif opcode == Opcode.RECEIVE:
            what[1]["offsets"][slot] += len(command.data)
            if self.deliver:
                self._retire_delivered()
        elif opcode == Opcode.DELIVER:
            acknowledged, applied, refusal = response.data
            _, ack, entries = what
            if acknowledged:
                self._acknowledged(slot, ack, command)
            for block in entries[:applied]:
                block["offsets"][slot] = len(block["data"])
            if refusal not in (Status.OK, Status.BUSY):
                raise BattleError("native_refused", "native battle command was refused")
            # the rest (the core's link buffer is full) go again with the next plan
            self._retire_delivered()
        elif opcode == Opcode.RECEIVE_MANY:
            applied, refusal = response.data
            for block in what[1][:applied]:
                block["offsets"][slot] = len(block["data"])
            if refusal not in (Status.OK, Status.BUSY):
                raise BattleError("native_refused", "native battle command was refused")
            # the rest (the core is still busy with an earlier block from that player) go again with the next plan
        elif opcode == Opcode.ACK_OUT:
            self.outbound_changed[slot] = command.sequence
            block = what[1]
            self.queue = [b for b in self.queue if b is not block]
            self.next_block[slot] += 1
            self.next_kind[slot] = min(8, self.next_kind[slot] + 1)
        elif opcode == Opcode.QUERY:
            q = self._query(slot, response)
            self.final[slot] = q
        elif opcode == Opcode.RELEASE:
            self.released.add(slot)

    def _admit_block(self, source, q, data):
        self._admit(source, q, data)     # validates and records it as self.pending[source]
        block = self.pending[source]
        self.pending[source] = None
        block["source"] = source
        if self.deliver:
            # The delivering router (journal v6): the block is the host's now; its core may send the next once it is
            # acknowledged, which is due at once (or with the next delivery, _ack_deferrable).
            block["acked"] = block["ack_sent"] = False
            block["role"] = block["data"][0] if block["kind"] == Kind.CONTROLLER else None
            if block["role"] == 0:
                self.last_command[block["data"][1]] = block
                if block["data"][8] == CONTROLLER_ENDLINKBATTLE:
                    self.flush = True
            self.awaiting_ack[source] = block
        self.queue.append(block)

    def _idle(self):
        return not self.queue and not any(self.reading)

    def _plan(self):
        if self.deliver:
            self._admit_delivered()
        else:
            self._admit_observed()
        self._lifecycle()
        # Each free core's command.
        for slot in range(self.count):
            if self.busy[slot] is not None:
                continue
            if self.release_started:
                if slot not in self.released and all(s in self.released for s in range(slot)):
                    self._issue(slot, Opcode.RELEASE, ("release",), data=struct.pack("<II",
                        self.b.roster[slot].party_crc32, self.final[slot].outcome))
                continue
            if self.deliver:
                self._next_delivered(slot)
            else:
                self._next_observed(slot)

    def _admit_observed(self):
        # Admission, in slot order: a core's next block once it may join (see above).
        idle = self._idle()
        for slot in range(self.count):
            seen = self._fresh(slot)
            if seen is None or self.reading[slot] is not None or any(b["source"] == slot for b in self.queue):
                continue
            q, block = seen
            if not q.outbound_pending:
                continue
            if (q.outbound_sequence, q.outbound_kind, q.read_offset) != (
                    self.next_block[slot], self.next_kind[slot], 0):
                raise BattleError("battle_order", "native block order or read cursor differs")
            if q.outbound_kind == Kind.CONTROLLER and not self.running:
                continue
            if q.outbound_kind >= Kind.START_HEADER and not self.started:
                continue
            # Two cores: each hears from the other only, so its next block may join at once. More: only into a batch
            # that starts while no block is in flight (every core that has one now joins it).
            if self.count != 2 and not idle:
                continue
            if block is not None:
                self._admit_block(slot, q, block)
            else:
                self.reading[slot] = dict(q=q, data=b"")

    def _lifecycle(self):
        # The lifecycle steps.
        if (self._idle() and not self.started and not self.start_authorized
                and self.prepared == set(range(self.count)) and self.next_kind == [3] * self.count):
            self.desk.authorize_start(self.b.battle_id, self.b.generation)
            self.start_authorized = True
        if (self.started and not self.running and self._idle() and self.next_kind == [8] * self.count):
            self.desk.authorize_running(self.b.battle_id, self.b.generation)
            self.running = True
        finishing = (self.running and self._idle()
                     and all(seen is not None and seen[0].restored and seen[0].last_sequence == self.sequences[slot]
                             for slot, seen in enumerate(self.seen)))
        if finishing and not self.finishing:
            self.finishing = True
        if self.finishing and len(self.final) == self.count and not self.release_started:
            if not all(q.restored for q in self.final.values()):
                raise BattleError("battle_order", "a core restored, then its final query did not say so")
            for slot in range(self.count):
                # On the pinned ABI 2/3, restored is published only after native exact party-count/CRC checks
                # against PREPARE and personal RNG restoration.
                self.call("finish_native", slot, *self.receipts[slot, Opcode.QUERY])
            self.release_started = True

    def _next_observed(self, slot):
        """A free core's command on the observed router (journal v4 and v5)."""
        own = next((b for b in self.queue if b["source"] == slot), None)
        if own is not None and all(t == slot or own["offsets"][t] == len(own["data"]) for t in range(self.count)):
            self._issue(slot, Opcode.ACK_OUT, ("ack", own), block_sequence=own["sequence"],
                offset=len(own["data"]), total_size=len(own["data"]), kind=own["kind"],
                data=struct.pack("<II", own["crc"], ((1 << self.count) - 1) ^ (1 << slot)))
            return
        reading = self.reading[slot]
        if reading is not None:
            q = reading["q"]
            self._issue(slot, Opcode.READ_OUT, ("read",), block_sequence=q.outbound_sequence,
                offset=len(reading["data"]), total_size=q.outbound_size, kind=q.outbound_kind)
            return
        owed = [b for b in self.queue if b["source"] != slot and b["offsets"][slot] < len(b["data"])]
        many = self._many(slot, owed)
        if many:
            self._issue(slot, Opcode.RECEIVE_MANY, ("receive_many", many), data=pack_receive_many(
                (b["source"], b["kind"], b["sequence"], b["data"]) for b in many))
            return
        block = owed[0] if owed else None
        if block is not None:
            offset = block["offsets"][slot]
            self._issue(slot, Opcode.RECEIVE, ("receive", block), source_slot=block["source"],
                block_sequence=block["sequence"], offset=offset, total_size=len(block["data"]),
                kind=block["kind"], data=block["data"][offset:offset + 128])
            return
        if self.start_authorized and slot not in self.start_issued:
            self.start_issued.add(slot)
            self._issue(slot, Opcode.START, ("start",))
            return
        if self.finishing and slot not in self.final:
            self._issue(slot, Opcode.QUERY, ("final",))
            return
        seen = self.seen[slot]
        if slot in self.prepared and (self.since_keep[slot] >= KEEP_OBSERVED_COMMANDS or (
                seen is not None and seen[0].last_sequence == self.sequences[slot]
                and seen[0].remaining_frames < KEEP_OBSERVED_FRAMES)):
            self._issue(slot, Opcode.KEEP, ("keep",))


    # ------------------------------------------------------------------ the delivering router (journal v6)
    # KNOWN_ISSUES MS-62, battle speed: battles over the internet were still slow, and 2v2s most of all. On the observed
    # router a block's core could send its next block only once every other core had received it (its ACK_OUT followed
    # the last delivery), so the master's next command waited a round trip to every other player for each of its own
    # blocks; each core took one command a round trip (a block's RECEIVE, then the next block's, then its own block's
    # ACK_OUT, one after another); three or four cores took new blocks only between batches; and a launcher's report
    # crossing the host's next command to it was refused and sent again a round trip later. With DELIVER (games with
    # battle_deliver_abi_version 1) the route:
    #   - acknowledges a block as soon as it holds it (the block is the host's to deliver: its bytes are in the journal's
    #     observation or READ_OUT records, made durable by the acknowledgement's own fsync), so its core goes on at once;
    #   - hands each core, in one DELIVER a round trip, its own block's acknowledgement and every block it is owed that
    #     fits, in the one global order every core receives the blocks in (no batches: each block joins that order when
    #     the route takes it);
    #   - lets a slave core (not the master, slot 0, the only one running the battle) receive the others' replies and
    #     DONEs together with the master's next command, which is the first thing that needs them there, and lets a
    #     slave's DONE be acknowledged with that delivery while the slave owes nothing else (its next block can only answer
    #     that command); nothing is held back once the master's end command is taken, or for a core whose deadline runs
    #     low (the KEEP rule: it gets everything it is owed instead of a KEEP);
    #   - takes a launcher's report while a command to it is outstanding (BattleExecutionService.observe).
    # Every decision uses only journaled responses and observations in journal order, so recovery replays the same
    # commands from the same events (battle_replay.py).

    def _stalled(self, slot):
        """The core's latest report is of its present state and says its deadline runs low (the observed KEEP rule)."""
        seen = self.seen[slot]
        return (seen is not None and seen[0].last_sequence == self.sequences[slot]
                and seen[0].remaining_frames < KEEP_OBSERVED_FRAMES)

    def _liveness(self, slot):
        """Nothing is held back for a core whose deadline runs low: it gets everything it is owed instead of a KEEP (a
        held-back block can then never wait longer than that for a command to carry it)."""
        return self._stalled(slot)

    def _deferrable(self, block, target):
        """A block the target core need not have before the master's next command: another core's controller reply or
        DONE, to a core that is not the master (its game runs no battle; a reply goes to the master's battle and a DONE
        gates only the master's next command for that battler, which follows it in the one order)."""
        return (self.running and not self.flush and target != 0 and block["role"] in (1, 2)
                and not self._liveness(target))

    def _ack_deferrable(self, slot, block):
        """A slave's DONE can wait for its acknowledgement until the next delivery to it while it owes no other block:
        its next block can only answer a command it does not hold yet, whose delivery then carries the acknowledgement."""
        if not self.running or self.flush or slot == 0 or block["role"] != 2 or self._liveness(slot):
            return False
        for battler in self.validator.owed_done(slot):
            command = self.last_command.get(battler)
            if command is None or command["offsets"][slot] == len(command["data"]):
                return False   # it holds that command and will answer it: its block needs the acknowledgement
        return True

    def _acknowledged(self, slot, block, command):
        block["acked"] = True
        self.awaiting_ack[slot] = None
        self.outbound_changed[slot] = command.sequence
        self.next_block[slot] += 1
        self.next_kind[slot] = min(8, self.next_kind[slot] + 1)

    def _retire_delivered(self):
        """Blocks every other core holds and their own core had acknowledged leave the order."""
        self.queue = [b for b in self.queue if not (b["acked"] and all(
            t == b["source"] or b["offsets"][t] == len(b["data"]) for t in range(self.count)))]

    def _admit_delivered(self):
        """Admission, in slot order: a core's next block as soon as its last one was acknowledged."""
        for slot in range(self.count):
            seen = self._fresh(slot)
            if seen is None or self.reading[slot] is not None or self.awaiting_ack[slot] is not None:
                continue
            q, block = seen
            if not q.outbound_pending:
                continue
            if (q.outbound_sequence, q.outbound_kind, q.read_offset) != (
                    self.next_block[slot], self.next_kind[slot], 0):
                raise BattleError("battle_order", "native block order or read cursor differs")
            if q.outbound_kind == Kind.CONTROLLER and not self.running:
                continue
            if q.outbound_kind >= Kind.START_HEADER and not self.started:
                continue
            if block is not None:
                self._admit_block(slot, q, block)
            else:
                self.reading[slot] = dict(q=q, data=b"")

    def _next_delivered(self, slot):
        """A free core's command on the delivering router."""
        reading = self.reading[slot]
        if reading is not None:
            q = reading["q"]
            self._issue(slot, Opcode.READ_OUT, ("read",), block_sequence=q.outbound_sequence,
                offset=len(reading["data"]), total_size=q.outbound_size, kind=q.outbound_kind)
            return
        own = self.awaiting_ack[slot]
        ack = own if own is not None and not own["ack_sent"] else None
        owed = [b for b in self.queue if b["source"] != slot and b["offsets"][slot] < len(b["data"])]
        last = max((i for i, b in enumerate(owed) if not self._deferrable(b, slot)), default=-1)
        owed = owed[:last + 1]   # up to the last block it needs now, in the one order
        if ack is not None and self._ack_deferrable(slot, ack) and not owed:
            ack = None
        if owed and (len(owed[0]["data"]) > 128 or owed[0]["offsets"][slot]):
            # A block of more than one chunk (a party block, a long controller message) goes by RECEIVE; an
            # acknowledgement that is due goes first.
            if ack is None or self._ack_deferrable(slot, ack):
                block = owed[0]
                offset = block["offsets"][slot]
                self._issue(slot, Opcode.RECEIVE, ("receive", block), source_slot=block["source"],
                    block_sequence=block["sequence"], offset=offset, total_size=len(block["data"]),
                    kind=block["kind"], data=block["data"][offset:offset + 128])
                return
            owed = []
        entries, size, sources = [], DELIVER_ACK.size if ack is not None else 0, set()
        for block in owed:
            if len(block["data"]) > 128:
                break
            if not self.running and block["source"] in sources:
                break   # before the battle runs, a core's receive slot empties only when its startup reads it
            size += 8 + len(block["data"])
            if size > DELIVER_MAX_BYTES:
                break
            entries.append(block)
            sources.add(block["source"])
        if ack is not None or entries:
            fields = {}
            if ack is not None:
                ack["ack_sent"] = True
                fields = dict(block_sequence=ack["sequence"], offset=len(ack["data"]), total_size=len(ack["data"]),
                              kind=ack["kind"])
            self._issue(slot, Opcode.DELIVER, ("deliver", ack, entries), data=pack_deliver(
                ((b["source"], b["kind"], b["sequence"], b["data"]) for b in entries),
                None if ack is None else (ack["crc"], ((1 << self.count) - 1) ^ (1 << slot))), **fields)
            return
        if self.start_authorized and slot not in self.start_issued:
            self.start_issued.add(slot)
            self._issue(slot, Opcode.START, ("start",))
            return
        if self.finishing and slot not in self.final:
            self._issue(slot, Opcode.QUERY, ("final",))
            return
        if slot in self.prepared and (self.since_keep[slot] >= KEEP_OBSERVED_COMMANDS or self._stalled(slot)):
            self._issue(slot, Opcode.KEEP, ("keep",))

    def _many(self, slot, owed):
        """KNOWN_ISSUES MS-62: the blocks a core is owed that go in one RECEIVE_MANY (at least two, else None): from the
        first, in the order every core receives them, each whole and of at most one chunk, as many as fit in one command
        (they always do but for the 92- and 156-byte controller blocks, a move's rare long messages)."""
        if not self.many:
            return None
        many, size = [], 0
        for block in owed:
            size += 8 + len(block["data"])
            if block["offsets"][slot] or len(block["data"]) > 128 or size > 192:
                break
            many.append(block)
        return many if len(many) > 1 else None

    async def run_observed(self):
        self.observed = True
        journal = self.room.journal
        # A battle of three or four on games with RECEIVE_MANY packs (journal v5); a recovered one as its journal did.
        self.many = journal.receive_many if journal is not None else (
            getattr(self.service, "receive_many", False) and self.count > 2)
        # Games with DELIVER use the delivering router (journal v6) in every format; a recovered battle as its journal did.
        self.deliver = journal.deliver if journal is not None else getattr(self.service, "deliver", False)
        if self.deliver:
            self.many = False
        self.awaiting_ack = [None] * self.count   # the delivering router: each core's block awaiting its acknowledgement
        self.held = [None] * self.count           # ... a report made after a command whose answer is still on its way
        self.last_command = {}                     # ... the master's last command for each battler
        self.flush = False                         # ... the master's end command taken: nothing is held back any more
        self.events = asyncio.Queue()
        self.tasks = set()
        self.busy = [None] * self.count
        self.seen = [None] * self.count
        self.outbound_changed = [0] * self.count
        self.reading = [None] * self.count
        self.since_keep = [0] * self.count
        self.queue = []
        self.prepared, self.start_done, self.start_issued, self.released = set(), set(), set(), set()
        self.final = {}
        self.start_authorized = self.finishing = self.release_started = False
        history = deque()
        if getattr(self.service, "replaying", False) and self.room.journal is not None:
            history.extend(self.room.journal.routed)
        try:
            for slot in range(self.count):
                binding = self.call("authorize_bind", slot)
                self._issue(slot, Opcode.BIND, ("bind",), data=binding.pack())
            while len(self.released) < self.count:
                if history:
                    kind, actor, *rest = history.popleft()
                    event = ((kind, self.b.players.index(actor), rest[1], rest[2]) if kind == "response"
                             else (kind, self.b.players.index(actor), None, rest[0]))
                else:
                    if getattr(self.service, "replaying", False):
                        for _ in range(3):
                            await asyncio.sleep(0)   # the recorded commands' dispatches consume their history
                        consumed = getattr(self.service, "history_consumed", None)
                        if consumed is not None:
                            consumed()
                    event = await self.events.get()
                kind, slot, command, response = event
                if kind == "error":
                    raise response
                if kind == "response":
                    self._response(slot, command, response)
                    held, self.held[slot] = self.held[slot], None
                    if held is not None:
                        self._observation(slot, held)
                else:
                    self._observation(slot, response)
                self._plan()
        finally:
            for task in list(self.tasks):
                task.cancel()
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)

    async def run(self):
        journal = self.room.journal
        if journal.observed if journal is not None else self.service.peek:
            return await self.run_observed()

        async def prepare(slot):
            binding = self.call("authorize_bind", slot)
            await self.rpc(slot, Opcode.BIND, data=binding.pack())
            preparation = self.call("preparation", slot)
            await self.rpc(slot, Opcode.PREPARE, data=preparation.pack())
        await _independent(*(prepare(slot) for slot in range(self.count)))
        journal = self.room.journal
        if journal is None or journal.pipelined:
            self.fresh, self.ack_due, self.rounds_since_keep = [None] * self.count, set(), [0] * self.count
            while not await self.round():
                await asyncio.sleep(0 if getattr(self.service, "replaying", False) else .001)
            return
        while True:
            queries = await self.step()
            if self.running and all(q.restored for q in queries):
                if any(self.pending):
                    raise BattleError("battle_order", "restoration cannot overtake a delivery batch")
                for slot in range(self.count):
                    # On the pinned ABI 2/3, restored is published only after
                    # native exact party-count/CRC checks against PREPARE and
                    # personal RNG restoration. No arbitrary RAM read is needed.
                    self.call("finish_native", slot, *self.receipts[slot, Opcode.QUERY])
                for slot in range(self.count):
                    await self.rpc(slot, Opcode.RELEASE, data=struct.pack("<II",
                        self.b.roster[slot].party_crc32, queries[slot].outcome))
                return
            # A live route gives the cores a moment; a replay of durable history has nothing to wait
            # for (its responses are recorded), so it only yields to the event loop. Commands do not
            # depend on this, so replay stays identical; recovery of a long battle no longer pays
            # 1 ms plus every waiting client's poll per historical step.
            await asyncio.sleep(0 if getattr(self.service, "replaying", False) else .001)
