"""Host-owned native battle execution with one exact command per participant.

This reuses the qualified full-Multi batch router. It consumes authenticated
mailbox responses, never diagnostic RAM, choices, damage, or claimed winners.
Uncertain execution remains reserved; ABI 3 interruption is not auto-resumable.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import struct
import zlib

from .battle_controller import ControllerValidator
from .battle_desk import BattleError
from .battle_execution_protocol import decode_control, encode_control, execution_view
from .battle_mailbox import Status
from .battle_roster import validate_auxiliary_startup
from .live_checkpoint import _atomic, _json_bytes
from .native_battle import Kind, NativeControl, NativeQuery, Opcode


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


class BattleExecutionService:
    """Only enable with the string table from the exact installed ROM.

    Durable command/response intents supplement the existing same-DB character
    reservations. Restart leaves those reservations waiting; it does not rebuild
    native RAM or invent route acknowledgments from this audit record.
    """

    def __init__(self, desk, string_lengths, directory, *, observer=None):
        if desk is None:
            raise ValueError("native execution requires an enabled BattleDesk")
        ControllerValidator(string_lengths)
        self.desk, self.string_lengths = desk, string_lengths
        if observer is not None and not callable(observer):
            raise ValueError("execution observer must be a trusted callable")
        self.observer = observer
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.rooms = {}
        self.native_sequences = {}

    def _persist(self, room):
        b = room.battle
        _atomic(room.path, _json_bytes(dict(format="native-battle-execution-intent-v1",
            world_id=self.desk.store.metadata.world_id, build_id=self.desk.store.build_id,
            ruleset_id=self.desk.store.ruleset_id, battle_id=b.battle_id,
            generation=b.generation, fingerprint=b.fingerprint, players=list(b.players),
            leases=list(b.leases), incarnations=dict(room.ready), state=room.state,
            error=room.error,
            pending={p: [value[2], encode_control(value[0])] for p, value in room.pending.items()},
            acknowledged={p: [value[0], encode_control(value[1])] for p, value in room.acknowledged.items()})))

    def exchange(self, actor, lease, request):
        battle = self.desk._get(actor, lease, request["battle_id"], request["generation"])
        room = self.rooms.get(battle.battle_id)
        if room is None:
            if battle.state != "accepted" or battle.consent != set(battle.players):
                raise BattleError("battle_not_ready", "all trainers must accept this exact challenge")
            if request["response_b64"] is not None:
                raise BattleError("invalid_receipt", "no native command was issued")
            path = self.directory / (battle.battle_id + ".json")
            if path.exists():
                raise BattleError("battle_recovery_required", "persisted native execution needs recovery")
            completed = [key for key, value in self.rooms.items() if value.state in ("closed", "aborted")]
            for key in completed[:-63]:
                del self.rooms[key]
            room = _Room(battle, path)
            self.rooms[battle.battle_id] = room
        if room.battle is not battle:
            raise BattleError("battle_generation_mismatch", "execution belongs to a different battle")
        if battle.state == "aborted" and not battle.bind_intent:
            room.state = "aborted"
            self._persist(room)
            return execution_view(battle.battle_id, battle.generation, room.state)
        incarnation = request["incarnation"]
        if actor in room.ready and room.ready[actor] != incarnation:
            self._fail(room, "incarnation_changed")
            raise BattleError("battle_incarnation_changed", "retain the original held battle core")
        if actor not in room.ready:
            if room.state != "waiting":
                raise BattleError("battle_state", "this battle cannot register another core")
            self.desk.register(actor, lease, battle.battle_id, battle.generation, incarnation)
            room.ready[actor] = incarnation
            self._persist(room)
        if request["response_b64"] is not None:
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
                room.acknowledged[actor] = acknowledged
                del room.pending[actor]
                try:
                    self._persist(room)
                except BaseException:
                    room.pending[actor] = pending
                    if previous is None:
                        room.acknowledged.pop(actor, None)
                    else:
                        room.acknowledged[actor] = previous
                    raise
                if not future.done():
                    if response.status == Status.OK and command.opcode != Opcode.QUERY:
                        self.native_sequences[actor] = (lease, incarnation, command.sequence)
                    future.set_result(response)
        if room.task is None and room.state == "waiting" and len(room.ready) == len(battle.players):
            room.state = "executing"
            self._persist(room)
            room.task = asyncio.create_task(self._drive(room), name="native-battle-execution")
        pending = room.pending.get(actor)
        pending = pending if room.state == "executing" else None
        return execution_view(battle.battle_id, battle.generation, room.state,
                              None if pending is None else pending[0], 0 if pending is None else pending[2])

    def _fail(self, room, reason):
        room.state, room.error = "recovery_required", reason
        self.desk._recover(room.battle, reason)
        self._persist(room)

    async def _command(self, room, actor, command):
        b = room.battle
        self.desk._get(actor, b.leases[b.players.index(actor)], b.battle_id, b.generation)
        if actor in room.pending:
            raise BattleError("battle_order", "one native command may be outstanding per player")
        future = asyncio.get_running_loop().create_future()
        dispatch_id = room.dispatch_ids.get(actor, 0) + 1
        if dispatch_id > 0x7FFFFFFF:
            raise BattleError("counter_exhausted", "native dispatch counter is exhausted")
        room.dispatch_ids[actor] = dispatch_id
        room.pending[actor] = (command, future, dispatch_id)
        # Publication precedes dispatch. Cancellation/timeout keeps the intent.
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
            room.state = "closed"
            self._persist(room)
        except asyncio.CancelledError:
            self._fail(room, "execution_stopped")
            raise
        except Exception:
            # No automatic winner, release, retirement, fresh BIND or save.
            self._fail(room, "execution_interrupted")

    async def close(self):
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
        response = await self.service._command(self.room, self.b.players[slot], command)
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
            self.call(callback, slot, command, response)
        return response

    async def queries(self):
        result = []
        for slot in range(self.count):
            q = NativeQuery.unpack((await self.rpc(slot, Opcode.QUERY)).data)
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
                validate_auxiliary_startup(kind, data, issued_rng=self.b.rng)
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
            for target in range(self.count):
                offset = block["offsets"][target]
                if target == source or offset == len(data):
                    continue
                chunk = data[offset:offset + 128]
                reply = await self.rpc(target, Opcode.RECEIVE, busy=True, source_slot=source,
                    block_sequence=block["sequence"], offset=offset, total_size=len(data),
                    kind=block["kind"], data=chunk)
                if reply.status == Status.OK:
                    block["offsets"][target] += len(chunk)
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
                for slot in range(self.count):
                    await self.rpc(slot, Opcode.START)
                self.started = True
            if not self.running and self.next_kind == [8] * self.count:
                self.desk.authorize_running(self.b.battle_id, self.b.generation)
                self.running = True
        # Every step refreshes the held native deadline. No local gameplay
        # controller, diagnostic core API or injected native outcome is used.
        for slot in range(self.count):
            await self.rpc(slot, Opcode.KEEP)
        return queries

    async def run(self):
        for slot in range(self.count):
            binding = self.call("authorize_bind", slot)
            await self.rpc(slot, Opcode.BIND, data=binding.pack())
            preparation = self.call("preparation", slot)
            await self.rpc(slot, Opcode.PREPARE, data=preparation.pack())
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
            await asyncio.sleep(.001)
