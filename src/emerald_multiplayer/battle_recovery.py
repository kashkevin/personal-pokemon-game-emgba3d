"""Host recovery for the exact original native cores and durable router history."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import hashlib
from pathlib import Path
import secrets
import stat
import struct

from .battle_desk import BattleError
from .battle_execution import _independent
from .battle_execution_journal import RouteJournal
from .battle_journal import BattleJournalError
from .battle_execution_protocol import decode_control, encode_control
from .battle_recovery_protocol import recovery_view
from .battle_replay import RouteReplay
from .live_checkpoint import _atomic, _json_bytes
from .native_battle import NativeBinding, NativeControl, NativeQuery, Opcode
from .native_battle_resume import ResumeAuthorization, ResumeQuery, Retirement


@dataclass
class _Recovery:
    record: dict
    path: Path
    ready: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)
    acknowledged: dict = field(default_factory=dict)
    ids: dict = field(default_factory=dict)
    state: str = "waiting"
    stage: str = "recovery"
    task: object = None
    replay: object = None
    journal: object = None
    loading: object = None
    error: object = None


class BattleRecoveryService:
    def __init__(self, execution):
        self.execution, self.desk = execution, execution.desk
        self.rooms = {}

    def _record(self, actor, lease, request):
        cp = self.desk._auth(actor, lease)
        row = self.desk.store._connection.execute("SELECT * FROM battle_reservations WHERE battle_id=?",
            (request["battle_id"],)).fetchone()
        if row is None:
            raise BattleError("battle_missing", "the original durable reservation is missing")
        record = self.desk.reservations._read(row)
        view = record["view"]
        if actor not in view["players"] or view["generation"] != request["generation"]:
            raise BattleError("battle_not_participant", "recovery changed the original challenge")
        slot = view["players"].index(actor)
        if request["incarnation"] != record["incarnations"][slot] or lease < record["leases"][slot]:
            raise BattleError("battle_incarnation_changed", "retain the exact original game core")
        pinned = view["checkpoints"][slot]
        if cp is None or (cp.revision, cp.sha256) != (pinned["revision"], pinned["sha256"]):
            raise BattleError("canonical_head_mismatch", "the original battle checkpoint changed")
        return record

    def _persist(self, room):
        _atomic(room.path, _json_bytes(dict(format="native-battle-quorum-intent-v1", record=room.record,
            ready=room.ready, state=room.state, stage=room.stage,
            pending={actor: [value[2], encode_control(value[0])] for actor, value in room.pending.items()},
            acknowledged={actor: [ident, encode_control(response)]
                          for actor, (ident, response) in room.acknowledged.items()})))

    def exchange(self, actor, lease, request):
        if not self.execution.resume_enabled:
            raise BattleError("battle_resume_disabled", "host ROM does not expose verified retained-core recovery")
        if "admission_b64" in request:
            return self.execution.admission.recover(actor, lease, request)
        record = self._record(actor, lease, request)
        battle_id, generation = record["view"]["battle_id"], record["view"]["generation"]
        terminal = self.desk.store._connection.execute(
            "SELECT terminal_kind, terminal_digest FROM battle_reservations WHERE battle_id=?", (battle_id,)).fetchone()
        room = self.rooms.get(battle_id)
        if terminal["terminal_kind"] == "closed":
            if room is None:
                room = _Recovery(record, self.execution.directory / (battle_id+".quorum.json"))
                self.rooms[battle_id] = room
            if room.record != record:
                raise BattleError("battle_generation_mismatch", "durable reservation changed during recovery")
            if not self._journal_ready(room):
                return recovery_view(battle_id, generation, "waiting")
            self._verify_journal(room.journal)
            return self._terminal(actor, lease, record, terminal["terminal_digest"], room.journal)
        if room is not None and actor in room.ready and room.ready[actor] != [lease, request["incarnation"]]:
            if room.task is not None and not room.task.done():
                room.task.cancel()
                return recovery_view(battle_id, generation, "waiting")
            room = None
        if room is not None and room.state == "recovery_required" and request["response_b64"] is None:
            if room.task is not None and not room.task.done():
                return recovery_view(battle_id, generation, "recovery_required")
            room = None
        if room is None:
            if request["response_b64"] is not None:
                raise BattleError("invalid_receipt", "recovery must first register the authenticated original core")
            room = _Recovery(record, self.execution.directory / (battle_id+".quorum.json"))
            self.rooms[battle_id] = room
        if room.record != record:
            raise BattleError("battle_generation_mismatch", "durable reservation changed during recovery")
        if not self._journal_ready(room):
            return recovery_view(battle_id, generation, "waiting")
        if room.task is None:
            # Provisional bootstrap can extend a valid first-BIND crash prefix
            # only before any native response exists. After that boundary,
            # authenticate every current byte without decoding the entire
            # unchanged history again on each wait-for-everyone poll.
            if room.journal.completed:
                self._verify_journal(room.journal)
            else:
                room.journal = self._load_journal(room)
        admission = request.get("admission_sha256")
        if actor not in room.journal.admitted:
            pending = room.journal.pending.get(actor)
            if (admission is None or pending is None or pending[1].opcode != Opcode.BIND
                    or hashlib.sha256(pending[1].pack()).hexdigest() != admission):
                raise BattleError("battle_not_admitted", "persist the exact original BIND before joining native recovery")
            room.journal.admit(actor, admission)
        elif admission is not None and room.journal.admitted[actor] != admission:
            raise BattleError("invalid_admission", "original durable BIND acknowledgment changed")
        self.execution.admission.register_full(actor, lease, request, record)
        room.ready[actor] = [lease, request["incarnation"]]
        if room.stage == "route":
            fields = dict(request)
            if request["response_stage"] == "recovery":
                response = decode_control(request["response_b64"], response=True)
                if room.acknowledged.get(actor) != (request["response_id"], response):
                    raise BattleError("invalid_receipt", "only the exact final quorum receipt may cross stages")
                fields.update(response_b64=None, response_id=0)
            result = self.execution.exchange(actor, lease, fields)
            return {**result, "scope": "native-battle-recovery-v1", "stage": "route"}
        if request["response_b64"] is not None:
            if request["response_stage"] != "recovery":
                raise BattleError("invalid_receipt", "route acknowledgments cannot authorize native recovery")
            response = decode_control(request["response_b64"], response=True)
            receipt = (request["response_id"], response)
            if room.acknowledged.get(actor) != receipt:
                pending = room.pending.get(actor)
                if pending is None or pending[2] != request["response_id"]:
                    raise BattleError("invalid_receipt", "no exact quorum command is outstanding")
                response.validate_response(pending[0])
                room.acknowledged[actor] = receipt
                del room.pending[actor]
                self._persist(room)
                if not pending[1].done():
                    pending[1].set_result(response)
        if room.task is None and len(room.ready) == len(record["view"]["players"]):
            self._current(room)
            room.state = "executing"
            self._persist(room)
            room.task = asyncio.create_task(self._drive(room), name="native-original-core-recovery")
        pending = room.pending.get(actor) if room.state == "executing" else None
        return recovery_view(battle_id, generation, room.state, room.stage,
            None if pending is None else pending[0], 0 if pending is None else pending[2])

    def _journal_ready(self, room):
        """Load exact history without blocking RPCs, heartbeats or native holds.

        Only immutable record data and read-only route bytes reach the worker.
        SQLite authentication and all publication remain on the event loop.
        A loading room supplies neither readiness nor native commands.
        """
        if room.journal is not None:
            return True
        if room.loading is None:
            room.loading = asyncio.create_task(asyncio.to_thread(self._load_journal, room),
                name="native-route-journal-read")
        if not room.loading.done():
            return False
        loading, room.loading = room.loading, None
        journal = loading.result()  # Consume errors; the next authenticated poll may retry.
        self._verify_journal(journal)  # Reject mutation after the worker finished reading.
        room.journal = journal
        return True

    @staticmethod
    def _verify_journal(journal):
        try:
            journal.verify_current()
        except BattleJournalError as error:
            # Cache validation must use the same bounded authenticated error
            # response as initial parsing, rather than dropping the socket.
            raise BattleError(error.code, str(error)) from error

    def _terminal(self, actor, lease, record, expected_digest, journal):
        """Retire one already-finished original core without recalling its peers.

        Global closure already requires every native restored RELEASE. Verify
        the same terminal material against that committed same-database fact;
        later peer checkpoints/leases are therefore deliberately irrelevant.
        """
        from .battle_reservations import SCOPE
        view = record["view"]
        receipts = {}
        for player, _, command, response in journal.completed:
            if response.status == 0 and command.opcode in (Opcode.BIND, Opcode.PREPARE, Opcode.START, Opcode.QUERY, Opcode.RELEASE):
                receipts[player, command.opcode] = command, response
        material = bytearray((SCOPE+":closed").encode("ascii"))
        try:
            for slot, player in enumerate(view["players"]):
                for opcode in (Opcode.BIND, Opcode.PREPARE, Opcode.START, Opcode.QUERY, Opcode.RELEASE):
                    command, response = receipts[player, opcode]
                    if (command.incarnation != record["incarnations"][slot] or command.source_slot != slot
                            or command.battle_id != view["battle_id"]
                            or command.session_epoch not in {epoch[slot] for epoch in journal.lineage}):
                        raise ValueError()
                    response.validate_response(command)
                    material.extend(command.pack()); material.extend(response.pack())
            if hashlib.sha256(material).hexdigest() != expected_digest:
                raise ValueError()
        except (KeyError, ValueError) as error:
            raise BattleError("battle_journal_invalid", "terminal route evidence differs from durable global closure") from error
        command, response = receipts[actor, Opcode.RELEASE]
        retirement = Retirement(view["generation"], command.sequence, *struct.unpack("<II", command.data))
        retire = NativeControl(command.incarnation, lease, command.battle_id, 1, Opcode.RETIRE,
            phase=command.phase, source_slot=command.source_slot, data=retirement.pack())
        result = recovery_view(view["battle_id"], view["generation"], "closed", "terminal")
        result["terminal"] = dict(release_b64=encode_control(command), receipt_b64=encode_control(response),
                                  retire_b64=encode_control(retire))
        return result

    def _current(self, room):
        for slot, actor in enumerate(room.record["view"]["players"]):
            lease, incarnation = room.ready[actor]
            self._record(actor, lease, dict(battle_id=room.record["view"]["battle_id"],
                generation=room.record["view"]["generation"], incarnation=incarnation))

    def _load_journal(self, room):
        record, view = room.record, room.record["view"]
        path = self.execution.directory / (view["battle_id"]+".events.jsonl")
        if not stat.S_ISREG(path.lstat().st_mode):
            raise BattleError("battle_journal_invalid", "original route evidence must be a regular file")
        with path.open("rb") as source:
            raw = source.readline(16385)
        try:
            header = json.loads(raw)["value"]["value"]
            sequences = header["initial_sequences"]
            if (type(sequences) is not list or len(sequences) != len(view["players"])
                    or any(type(n) is not int or not 0 <= n < 0xFFFFFFFF for n in sequences)):
                raise ValueError()
            expected = dict(record=record, battle_id=view["battle_id"], generation=view["generation"],
                players=view["players"], leases=record["leases"], incarnations=record["incarnations"],
                mode=view["mode"], initial_sequences=sequences)
            if header != expected:
                raise ValueError()
            return RouteJournal(path, expected)
        except (ValueError, KeyError, TypeError) as error:
            raise BattleError("battle_journal_invalid", "route history differs from its same-database reservation") from error

    async def _issue(self, room, slot, opcode, *, sequence=1, data=b""):
        self._current(room)
        view = room.record["view"]
        actor = view["players"][slot]
        lease, incarnation = room.ready[actor]
        command = NativeControl(incarnation, lease, view["battle_id"], sequence, opcode,
                                source_slot=slot, phase=view["mode"], data=data)
        command.validate_command(player_id=actor)
        if actor in room.pending:
            raise BattleError("battle_order", "one quorum command may be outstanding per original core")
        future = asyncio.get_running_loop().create_future()
        ident = room.ids.get(actor, 0)+1
        room.ids[actor] = ident
        room.pending[actor] = (command, future, ident)
        self._persist(room)
        try:
            response = await asyncio.wait_for(asyncio.shield(future), 20)
            response.validate_response(command)
            if response.status:
                raise BattleError("native_refused", "original native core refused retained recovery")
            return command, response
        finally:
            if not future.done():
                future.cancel()

    def _extend_bind_authority(self, room):
        # A host may have crashed while publishing the first parallel BINDs.
        # Original consent/roster/incarnations are already frozen; extending
        # the mask only follows current authenticated exact canonical heads.
        from .battle_reservations import _digest
        self._current(room)
        store = self.desk.store
        with store._transaction():
            row = store._connection.execute("SELECT * FROM battle_reservations WHERE battle_id=?",
                (room.record["view"]["battle_id"],)).fetchone()
            if self.desk.reservations._read(row) != room.record or row["terminal_kind"] is not None:
                raise BattleError("battle_reservation_conflict", "cannot extend a different or terminal native lifecycle")
            mask = sum(1 << room.replay.room.battle.players.index(actor)
                       for actor in room.replay.room.battle.bind_intent) | row["authorized_mask"]
            store._connection.execute("UPDATE battle_reservations SET authorized_mask=?, sha256=? WHERE battle_id=?",
                (mask, _digest([room.record, mask, None, None]), room.record["view"]["battle_id"]))

    async def _suspend(self, room, slot, leases):
        actor = room.record["view"]["players"][slot]
        _, response = await self._issue(room, slot, Opcode.QUERY)
        query = NativeQuery.unpack(response.data)
        logical = room.replay.blocked.get(actor)
        if query.provisional or (not query.held and query.generation != room.record["view"]["generation"]):
            if (logical is None or logical.opcode != Opcode.BIND
                    or query.last_sequence != logical.sequence-1):
                raise BattleError("battle_incarnation_changed", "unbound core cannot replace the retained battle")
            rebound = room.journal._renew_control(actor, logical, leases)
            await self._issue(room, slot, Opcode.BIND, sequence=rebound.sequence, data=rebound.data)
        elif query.generation != room.record["view"]["generation"]:
            raise BattleError("battle_generation_mismatch", "native core holds another generation")
        command, response = await self._issue(room, slot, Opcode.SUSPEND)
        suspended = ResumeQuery.unpack(response.data)
        sequence = room.replay.route.sequences[slot]
        possible = {sequence}
        pending = room.journal.pending.get(actor)
        if logical is not None and logical.opcode != Opcode.QUERY and (pending is not None or logical.opcode == Opcode.BIND):
            possible.add(logical.sequence)
        if suspended.query.last_sequence not in possible:
            raise BattleError("battle_order", "original native sequence differs from its exact durable boundary")
        if suspended.released:
            release = room.replay.room.battle.receipts.get((actor, Opcode.RELEASE))
            if not ((logical is not None and logical.opcode == Opcode.RELEASE)
                    or (release is not None and NativeControl.unpack(release[0]).sequence == suspended.query.last_sequence)):
                raise BattleError("battle_order", "an idle core lacks the original authorized RELEASE")
        return command, response, suspended

    async def _drive(self, room):
        replay = None
        try:
            view = room.record["view"]
            old = self.execution.rooms.get(view["battle_id"])
            if old is not None and old.task is not None and not old.task.done():
                old.task.cancel()
                await asyncio.gather(old.task, return_exceptions=True)
            self._current(room)
            room.journal = await asyncio.to_thread(self._load_journal, room)
            self._current(room)
            room.journal.verify_current()
            leases = tuple(room.ready[actor][0] for actor in view["players"])
            replay = room.replay = RouteReplay(self.execution, room.record, room.journal, leases)
            route_room = await replay.prepare()
            completed = route_room.state == "closed"
            if not completed:
                self._extend_bind_authority(room)
            suspended = await _independent(*(self._suspend(room, slot, leases) for slot in range(len(leases))))
            epoch = max(room.journal.renewal_epoch, *(item[2].epoch for item in suspended))+1
            token = secrets.token_bytes(16)
            authorizations = []
            for slot, (_, _, query) in enumerate(suspended):
                binding = NativeBinding(view["generation"], tuple(view["players"]), leases,
                    tuple(room.record["incarnations"]), slot, mode=view["mode"], resumable=True)
                authorization = ResumeAuthorization(binding, token, epoch, query.query.last_sequence)
                authorizations.append(self._issue(room, slot, Opcode.REAUTHORIZE, data=authorization.pack()))
            authorized = await _independent(*authorizations)
            self._current(room)
            proofs = [dict(suspend=encode_control(old[0]), suspended=encode_control(old[1]),
                           authorize=encode_control(new[0]), authorized=encode_control(new[1]))
                      for old, new in zip(suspended, authorized)]
            room.journal.renew(epoch, leases, proofs)  # Full durable quorum before any core thaws.
            await _independent(*(self._issue(room, slot, Opcode.RESUME, data=token+struct.pack("<I", epoch))
                                 for slot in range(len(leases))))
            self._current(room)
            if completed:
                await self._settle_completed(room)
                return
            replay.activate()
            for slot, actor in enumerate(view["players"]):
                self.execution.native_sequences[actor] = (leases[slot], room.record["incarnations"][slot],
                                                         replay.route.sequences[slot])
            room.stage = "route"
            self._persist(room)
            await replay.task
            self.execution._persist(route_room)
            room.state = "closed"
            self._persist(room)
        except asyncio.CancelledError:
            room.state = "recovery_required"
            if replay is not None:
                await replay.close()
            self._persist(room)
            raise
        except Exception as error:
            room.error = error
            room.state = "recovery_required"
            if replay is not None:
                await replay.close()
                self.execution._fail(replay.room, "retained_recovery_interrupted")
            self._persist(room)

    async def _settle_completed(self, room):
        """A replayed complete release quorum may finish its interrupted DB commit."""
        replay, b = room.replay, room.replay.room.battle
        room.journal.verify_current()
        last = b.players[-1]
        request, response = [NativeControl.unpack(raw) for raw in b.receipts[last, Opcode.RELEASE]]
        b.state, b.released = "release_authorized", set(b.players)-{last}
        b.leases = room.journal.leases
        b.lease_lineage = tuple(room.journal.lineage) if room.journal.renewal_epoch else ()
        b.renewal_digest = room.journal.renewal_digest
        self.desk._publish_closed(b, last, request, response)
        b.released.add(last)
        b.state = replay.room.state = "closed"
        self.desk._history[b.battle_id] = b
        self.execution.rooms[b.battle_id] = replay.room
        # Closed responses use authenticated recovery status directly; no new
        # native mutation is authorized under these newly authenticated leases.
        room.state = "closed"
        self.execution._persist(replay.room)
        self._persist(room)

    async def close(self):
        tasks = [task for room in self.rooms.values() for task in (room.task, room.loading)
                 if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
