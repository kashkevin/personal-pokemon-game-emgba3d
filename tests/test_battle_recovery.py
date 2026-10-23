"""Real TCP/SQLite recovery with explicit synthetic original native cores.

This proves protocol/replay/lease fences, not real native battle acceptance.
"""
import asyncio
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
import struct
import sys
import threading
from types import SimpleNamespace
import unittest
import unittest.mock
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from emerald_multiplayer.battle_execution import BattleExecutionService
from emerald_multiplayer.battle_desk import BattleError
from emerald_multiplayer.battle_execution_journal import RouteJournal
from emerald_multiplayer.battle_execution_protocol import decode_control, encode_control
from emerald_multiplayer.battle_journal import BattleJournalError
from emerald_multiplayer.battle_protocol import validate_battle_reply
from emerald_multiplayer.battle_recovery import BattleRecoveryService
from emerald_multiplayer.native_battle import NativeBinding, NativeControl, Opcode
from emerald_multiplayer.native_battle_resume import Admission, ResumeAuthorization
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore
import test_battle_arbitration as fixture
import test_battle_desk as desk_fixture
import test_battle_execution as execution_fixture


class RecoveryRecordTests(unittest.TestCase):
    """Real checkpoint/reservation validation on every synchronous recovery poll."""

    tearDown = desk_fixture.BattleDeskTests.tearDown
    actor = desk_fixture.BattleDeskTests.actor
    call = desk_fixture.BattleDeskTests.call
    accept = desk_fixture.BattleDeskTests.accept
    register = desk_fixture.BattleDeskTests.register
    assert_code = desk_fixture.BattleDeskTests.assert_code

    def setUp(self):
        desk_fixture.BattleDeskTests.setUp(self)
        self.register()
        self.call("authorize_bind", 0)
        self.recovery = BattleRecoveryService(SimpleNamespace(desk=self.desk))
        self.request = dict(battle_id=self.battle_id, generation=self.generation, incarnation=100)

    def record(self):
        return self.recovery._record(*self.actor(0), self.request)

    def test_one_full_checkpoint_validation_per_poll_without_cross_request_cache(self):
        with patch.object(self.store, "read_checkpoint", wraps=self.store.read_checkpoint) as read:
            first = self.record()
            self.assertEqual(read.call_count, 1)
            self.assertEqual(self.record(), first)
            self.assertEqual(read.call_count, 2)
            # A subsequent poll must hash the current bytes, even with the same head.
            self.store._connection.execute(
                "UPDATE checkpoints SET payload=? WHERE player_id=? AND revision=?",
                (b"corrupt", self.actor(0)[0], self.heads[0].revision))
            self.assert_code("storage_corrupt", self.record)
            self.assertEqual(read.call_count, 3)

    def test_live_and_durable_lease_checks_survive_successful_poll(self):
        self.record()
        actor, lease = self.actor(0)
        self.leases[actor] = lease + 1
        self.assert_code("stale_lease", self.recovery._record, actor, lease, self.request)
        self.leases[actor] = lease
        self.assertTrue(self.store.release_lease(actor, lease))
        # Even a missing reservation must not hide the stale durable lease.
        missing = dict(self.request, battle_id=str(uuid4()))
        self.assert_code("stale_lease", self.recovery._record, actor, lease, missing)

    def test_valid_but_changed_canonical_head_is_rejected_after_successful_poll(self):
        self.record()
        actor, _ = self.actor(0)
        # Inject a separately valid checkpoint head into this disposable database.
        # Production commits are reserved during battles; this probes the read fence.
        self.store._connection.execute("""INSERT INTO checkpoints
            SELECT player_id, revision+1, ?, revision, payload, sha256, build_id, ruleset_id, save_profile
            FROM checkpoints WHERE player_id=? AND revision=?""",
            (str(uuid4()), actor, self.heads[0].revision))
        self.store._connection.execute("UPDATE players SET latest_revision=? WHERE player_id=?",
            (self.heads[0].revision + 1, actor))
        self.assert_code("canonical_head_mismatch", self.record)

    def test_changed_reservation_digest_is_rejected_after_successful_poll(self):
        self.record()
        self.store._connection.execute("UPDATE battle_reservations SET sha256=? WHERE battle_id=?",
            ("0" * 64, self.battle_id))
        self.assert_code("battle_reservation_invalid", self.record)


class RecoveryWaitingJournalTests(unittest.IsolatedAsyncioTestCase):
    """Real route bytes and SQLite ownership; admission transport is isolated."""

    tearDown = desk_fixture.BattleDeskTests.tearDown
    actor = desk_fixture.BattleDeskTests.actor
    call = desk_fixture.BattleDeskTests.call
    accept = desk_fixture.BattleDeskTests.accept
    register = desk_fixture.BattleDeskTests.register
    descriptor = desk_fixture.BattleDeskTests.descriptor
    query = desk_fixture.BattleDeskTests.query
    record = RecoveryRecordTests.record

    def setUp(self):
        RecoveryRecordTests.setUp(self)
        self.directory = Path(self.temp.name) / "execution"
        self.directory.mkdir()
        self.recovery = BattleRecoveryService(SimpleNamespace(desk=self.desk,
            resume_enabled=True, directory=self.directory,
            admission=SimpleNamespace(register_full=Mock())))
        self.request.update(response_b64=None, response_id=0, response_stage="recovery")
        record = self.record()
        view = record["view"]
        self.header = dict(record=record, battle_id=self.battle_id, generation=self.generation,
            players=view["players"], leases=record["leases"], incarnations=record["incarnations"],
            mode=view["mode"], initial_sequences=[0, 0])
        self.path = self.directory / (self.battle_id + ".events.jsonl")
        self.binds = [NativeControl(100 + slot, self.actor(slot)[1], self.battle_id, 1, Opcode.BIND,
            phase=view["mode"], source_slot=self.descriptor(slot).source_slot,
            data=self.call("authorize_bind", slot).pack())
            for slot in range(2)]

    async def asyncTearDown(self):
        await self.recovery.close()

    def seed(self, *, bootstrap=False):
        # Encode a real canonical chain in one write, avoiding thousands of
        # fixture fsyncs. Production RouteJournal must validate every row.
        from emerald_multiplayer.battle_execution_journal import FORMAT, ZERO_HASH
        values = [dict(kind="header", format=FORMAT, value=self.header)]
        def event(kind, slot, ident, control):
            values.append(dict(kind=kind, actor=self.actor(slot)[0], dispatch_id=ident,
                               control_b64=encode_control(control)))
        for slot in range(1 if bootstrap else 2):
            event("command", slot, 1, self.binds[slot])
            values.append(dict(kind="admission", actor=self.actor(slot)[0],
                               control_sha256=hashlib.sha256(self.binds[slot].pack()).hexdigest()))
        if not bootstrap:
            for slot in range(2):
                event("response", slot, 1, replace(self.binds[slot], data=self.query(slot, 1)))
            for ident in range(2, 514):
                for slot in range(2):
                    query = replace(self.binds[slot], sequence=2, opcode=Opcode.QUERY, data=b"")
                    event("command", slot, ident, query)
                    event("response", slot, ident, replace(query, data=self.query(slot, 1)))
        raw, previous = bytearray(), ZERO_HASH
        for sequence, value in enumerate(values):
            line, previous = RouteJournal._record(sequence, previous, value)
            raw.extend(line)
        self.path.write_bytes(raw)
        return bytes(raw)

    async def poll(self):
        result = self.recovery.exchange(*self.actor(0), self.request)
        room = self.recovery.rooms[self.battle_id]
        if room.loading is not None:
            await asyncio.wait_for(asyncio.shield(room.loading), 5)
            result = self.recovery.exchange(*self.actor(0), self.request)
        self.assertEqual(result["state"], "waiting")
        self.assertIsNone(room.task)  # The absent original peer remains required.
        return room

    async def test_completed_waiting_history_is_decoded_once_but_verified_on_every_poll(self):
        original = self.seed()
        with patch.object(self.recovery, "_load_journal", wraps=self.recovery._load_journal) as load:
            room = await self.poll()
            self.assertEqual(load.call_count, 1)
            self.assertEqual(len(room.journal.completed), 1026)
            with patch.object(room.journal, "verify_current", wraps=room.journal.verify_current) as verify, \
                    patch("emerald_multiplayer.battle_execution_journal.decode_control",
                          wraps=decode_control) as decode:
                for _ in range(5):
                    self.assertIs(await self.poll(), room)
                self.assertEqual(verify.call_count, 5)
                self.assertEqual(decode.call_count, 0)
                self.assertEqual(load.call_count, 1)
        self.assertEqual(self.path.read_bytes(), original)

    async def test_same_size_prefix_corruption_is_rejected_even_if_metadata_is_unchanged(self):
        raw = self.seed()
        room = await self.poll()
        changed = bytearray(raw)
        changed[raw.index(b'"sha256":"') + len(b'"sha256":"')] ^= 1
        self.path.write_bytes(changed)
        self.assertEqual(len(changed), len(raw))
        # Model coarse or masked filesystem timestamps: the full-byte digest,
        # not a metadata cache or last-record check, must reject this prefix.
        with patch.object(room.journal, "_identity", return_value=room.journal._stamp), \
                self.assertRaises(BattleError) as caught:
            await self.poll()
        self.assertEqual(caught.exception.code, "battle_journal_changed")

    async def test_waiting_poll_rejects_identical_replacement_growth_and_truncation(self):
        raw = self.seed()
        for mutation in ("replacement", "growth", "truncation"):
            with self.subTest(mutation=mutation):
                self.path.write_bytes(raw)
                self.recovery.rooms.clear()
                room = await self.poll()
                if mutation == "replacement":
                    replacement = self.path.with_suffix(".replacement")
                    replacement.write_bytes(raw)
                    info = self.path.stat()
                    os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns))
                    replacement.replace(self.path)
                elif mutation == "growth":
                    with self.path.open("ab") as stream:
                        stream.write(b"\n")
                else:
                    self.path.write_bytes(raw[:-1])
                with self.assertRaises(BattleError) as caught:
                    await self.poll()
                self.assertEqual(caught.exception.code, "battle_journal_changed")
                self.assertIsNone(room.task)

    async def test_incomplete_bootstrap_still_reloads_a_valid_external_first_bind_extension(self):
        self.seed(bootstrap=True)
        room = await self.poll()
        original = room.journal
        extended = RouteJournal(self.path, self.header)
        extended.append("command", self.actor(1)[0], 1, self.binds[1])
        with patch.object(self.recovery, "_load_journal", wraps=self.recovery._load_journal) as load:
            self.assertIs(await self.poll(), room)
            self.assertEqual(load.call_count, 1)
        self.assertIsNot(room.journal, original)
        self.assertEqual(room.journal.pending[self.actor(1)[0]], (1, self.binds[1]))
        self.assertFalse(room.journal.completed)

    async def test_slow_initial_read_is_single_flight_and_cannot_register_or_dispatch(self):
        raw = self.seed()
        started, finish = threading.Event(), threading.Event()
        load = self.recovery._load_journal
        main_thread = threading.get_ident()
        def delayed(room):
            self.assertNotEqual(threading.get_ident(), main_thread)
            started.set()
            if not finish.wait(5):
                raise TimeoutError("test failed to release read-only worker")
            return load(room)
        with patch.object(self.recovery, "_load_journal", side_effect=delayed) as spy:
            try:
                for _ in range(10):
                    result = self.recovery.exchange(*self.actor(0), self.request)
                    self.assertEqual((result["state"], result["command_b64"]), ("waiting", None))
                    await asyncio.sleep(.01)
                self.assertTrue(started.is_set())
                room = self.recovery.rooms[self.battle_id]
                self.assertEqual(spy.call_count, 1)
                self.assertEqual(room.ready, {})
                self.assertIsNone(room.task)
                self.assertIsNone(room.journal)
                self.recovery.execution.admission.register_full.assert_not_called()
            finally:
                finish.set()
            await asyncio.wait_for(room.loading, 5)
            self.assertIs(await self.poll(), room)
            self.assertEqual(spy.call_count, 1)
        self.assertEqual(self.path.read_bytes(), raw)

    async def test_changed_bytes_after_worker_completion_are_rejected_before_readiness(self):
        raw = self.seed()
        self.recovery.exchange(*self.actor(0), self.request)
        room = self.recovery.rooms[self.battle_id]
        await asyncio.wait_for(room.loading, 5)
        self.path.write_bytes(raw[:-1])
        with self.assertRaises(BattleError):
            self.recovery.exchange(*self.actor(0), self.request)
        self.assertIsNone(room.journal)
        self.assertEqual(room.ready, {})
        self.recovery.execution.admission.register_full.assert_not_called()

    async def test_read_error_is_consumed_and_retry_still_validates_real_history(self):
        raw = self.seed()
        self.path.write_bytes(raw[:-1])
        self.recovery.exchange(*self.actor(0), self.request)
        room = self.recovery.rooms[self.battle_id]
        await asyncio.gather(room.loading, return_exceptions=True)
        with self.assertRaises(BattleError):
            self.recovery.exchange(*self.actor(0), self.request)
        self.assertIsNone(room.loading)
        self.assertIsNone(room.journal)
        self.assertEqual(room.ready, {})
        self.path.write_bytes(raw)
        self.assertIs(await self.poll(), room)

    async def test_close_does_not_publish_a_late_read_only_worker_result(self):
        raw = self.seed()
        started, finish, finished = threading.Event(), threading.Event(), threading.Event()
        load = self.recovery._load_journal
        def delayed(room):
            started.set()
            if not finish.wait(5):
                raise TimeoutError("test failed to release read-only worker")
            try:
                return load(room)
            finally:
                finished.set()
        with patch.object(self.recovery, "_load_journal", side_effect=delayed):
            self.recovery.exchange(*self.actor(0), self.request)
            room = self.recovery.rooms[self.battle_id]
            try:
                async with asyncio.timeout(2):
                    while not started.is_set():
                        await asyncio.sleep(.01)
                await asyncio.wait_for(self.recovery.close(), 1)
                self.assertTrue(room.loading.cancelled())
                self.assertIsNone(room.journal)
                self.assertEqual(room.ready, {})
            finally:
                finish.set()
                # The canceled thread wrapper may finish its read, but has no
                # callback capable of publishing to the closed host room.
                self.assertTrue(await asyncio.to_thread(finished.wait, 5))
        self.assertEqual(self.path.read_bytes(), raw)


class RetainedFixture(execution_fixture.NativeFixture):
    def __init__(self, battle, slot):
        super().__init__(battle, slot)
        self.bound = False
        self.provisional = None
        self.suspended = False
        self.resume_epoch, self.suspension_epoch = 0, 0
        self.token = bytes(16)
        self.previous = 0
        self.cached = None
        self.binding = None
        self.calls = []

    def query(self):
        if not self.bound:
            if self.provisional is not None:
                binding = self.provisional
                return struct.pack("<I16sBBBB10I", 129, UUID(binding.generation).bytes,
                    len(self.battle.players), self.slot, self.battle.mode, 0, self.sequence, *([0]*9))
            return bytes(64)
        data = bytearray(super().query())
        if self.released:
            struct.pack_into("<I", data, 0, 257)
        if self.suspended:
            struct.pack_into("<I", data, 0, struct.unpack_from("<I", data)[0] | 2 | 64)
            struct.pack_into("<I", data, 52, 0)
        return bytes(data)

    def resume_query(self):
        state = 1 if self.released else 9 if self.suspended else 5 if self.started else 4 if self.prepared else 2
        return self.query()+struct.pack("<II", state | 256 | self.previous << 16, self.resume_epoch)+self.token

    async def rpc(self, command):
        if command.opcode == Opcode.PEEK:   # an observation changes nothing (KNOWN_ISSUES MS-62)
            return await execution_fixture.NativeFixture.rpc(self, command)
        self.calls.append(command)
        if command.opcode == Opcode.ADMIT:
            self.provisional = Admission.unpack(command.data)
            return replace(command, data=self.query())
        if command.opcode >= Opcode.SUSPEND:
            if not self.bound or command.incarnation != self.binding.incarnations[self.slot]:
                raise AssertionError("replacement native core")
            if command.opcode == Opcode.SUSPEND:
                if not self.released and not self.suspended:
                    self.previous = 5 if self.started else 4 if self.prepared else 2
                    self.suspension_epoch = self.resume_epoch
                    self.suspended = True
            elif command.opcode == Opcode.REAUTHORIZE:
                auth = ResumeAuthorization.unpack(command.data)
                auth.validate_previous(self.binding)
                if auth.last_sequence != self.sequence or auth.epoch <= self.suspension_epoch:
                    raise AssertionError("quorum changed native cursor or episode")
                self.binding, self.resume_epoch, self.token = auth.binding, auth.epoch, auth.token
                if self.cached:
                    request, response = self.cached
                    request = replace(request, session_epoch=command.session_epoch,
                        data=self.binding.pack() if request.opcode == Opcode.BIND else request.data)
                    self.cached = request, replace(response, session_epoch=command.session_epoch)
            elif command.opcode == Opcode.RESUME:
                if command.data != self.token+struct.pack("<I", self.resume_epoch):
                    raise AssertionError("wrong quorum token")
                self.suspended = False
            return replace(command, data=self.resume_query())
        if self.cached and command == self.cached[0]:
            return self.cached[1]
        if self.suspended and command.opcode != Opcode.QUERY:
            raise AssertionError("ordinary mutation while suspended")
        if command.opcode == Opcode.BIND:
            self.bound, self.binding = True, NativeBinding.unpack(command.data)
            self.provisional = None
        response = await super().rpc(command)
        if command.opcode == Opcode.RELEASE and not response.status:
            self.previous = self.resume_epoch = self.suspension_epoch = 0
            self.token = bytes(16)
        if command.opcode != Opcode.QUERY and not response.status:
            self.cached = command, response
        return response


class BattleRecoveryNetworkTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.BattleArbitrationTests.asyncSetUp
    peek = False   # KNOWN_ISSUES MS-62: the observed router, journal v4 and the clients' observers (ObservedRecoveryTests)

    async def asyncTearDown(self):
        for observer in getattr(self, "observers", []):
            await observer.stop()
        await fixture.BattleArbitrationTests.asyncTearDown(self)

    def observer(self, index, model):
        """A client's observer (battle_observer.py) on its synthetic core, reporting through its current connection."""
        if not self.peek:
            return None
        from emerald_multiplayer.battle_observer import BattleObserver
        from emerald_multiplayer.protocol import ProtocolError

        async def challenge(operation, **fields):
            reply = await self.actors[index].rpc("battle_" + operation, **fields)
            if reply.get("type") != "battle_result":
                raise ProtocolError(str(reply.get("code")), "refused")
            return reply
        companion = SimpleNamespace(config=SimpleNamespace(battle_peek_abi_version=1), battle_rpc=model.rpc,
                                    battle_challenge_rpc=challenge)
        observer = BattleObserver(companion, self.battle_id, self.generation, 100 + index, model.slot, model.battle.mode)
        self.observers = getattr(self, "observers", []) + [observer]
        return observer

    @staticmethod
    async def run_command(observer, model, command):
        if observer is None:
            return await model.rpc(command)
        observer.holding(command)
        async with observer.lock:
            response = await model.rpc(command)
        observer.executed(command, response)
        return response
    actor = fixture.BattleArbitrationTests.actor
    call = fixture.BattleArbitrationTests.call
    accept = execution_fixture.BattleExecutionNetworkTests.accept

    async def test_resume_consent_requires_original_identity_before_mutation_and_entry_claim_is_explicit(self):
        self.call("cancel", 0)
        self.server.battle_execution = BattleExecutionService(self.desk, (None,)*721,
            self.root/"execution", resume_enabled=True)
        battle = str(uuid4())
        missing = await self.actors[0].rpc("battle_invite", battle_id=battle, peer=self.players[1].player_id)
        self.assertEqual(missing["code"], "battle_original_core_required")
        self.assertNotIn(battle, self.desk._active)
        identities = [dict(incarnation=100+i, runtime_id=str(uuid4())) for i in range(2)]
        invited = await self.actors[0].rpc("battle_invite", battle_id=battle,
            peer=self.players[1].player_id, **identities[0])
        self.assertEqual(invited["type"], "battle_result", invited)
        view = invited["result"]
        missing = await self.actors[1].rpc("battle_accept", battle_id=battle,
            generation=view["generation"], fingerprint=view["fingerprint"])
        self.assertEqual(missing["code"], "battle_original_core_required")
        self.assertEqual(self.desk._active[battle].consent, {self.players[0].player_id})
        accepted = await self.actors[1].rpc("battle_accept", battle_id=battle,
            generation=view["generation"], fingerprint=view["fingerprint"], **identities[1])
        self.assertEqual(accepted["result"]["state"], "accepted")
        self.assertFalse(self.desk._active[battle].resumable)
        changed = await self.actors[0].rpc("battle_claim", battle_id=battle,
            generation=view["generation"], **(identities[0] | {"runtime_id": str(uuid4())}))
        self.assertEqual(changed["code"], "battle_not_ready")
        self.assertFalse(self.desk._active[battle].resumable)
        claimed = await self.actors[0].rpc("battle_claim", battle_id=battle,
            generation=view["generation"], **identities[0])
        self.assertEqual(claimed["result"]["state"], "accepted")
        self.assertTrue(self.desk._active[battle].resumable)
        record = self.server.battle_execution.admission._read(battle)
        self.assertEqual(record["claimed"], [self.players[0].player_id])
        self.assertEqual(record["identities"], {self.players[i].player_id: identities[i] for i in range(2)})

    async def _interrupt(self, opcode, *, uncertain=True, multi=False):
        self.server.battle_execution = BattleExecutionService(self.desk, (None,)*721,
            self.root/"execution", resume_enabled=True, peek=self.peek)
        self.accept(multi)
        battle = self.desk._active[self.battle_id]
        self.models = {actor: RetainedFixture(battle, slot) for slot, actor in enumerate(battle.players)}
        self.admission_proofs = {}
        for index, actor in enumerate(self.actors[:len(battle.players)]):
            runtime = str(uuid4())
            self.server.battle_execution.admission.capture(actor.player.player_id, actor.lease,
                dict(battle_id=self.battle_id, incarnation=100+index, runtime_id=runtime))
            self.server.battle_execution.admission.claim(actor.player.player_id, actor.lease,
                dict(battle_id=self.battle_id, generation=self.generation, incarnation=100+index, runtime_id=runtime))
            slot = battle.players.index(actor.player.player_id)
            command = NativeControl(100+index, actor.lease, self.battle_id, 1, Opcode.ADMIT,
                phase=battle.mode, source_slot=slot,
                data=Admission(self.generation, actor.player.player_id, runtime).pack())
            receipt = await self.models[actor.player.player_id].rpc(command)
            self.admission_proofs[actor.player.player_id] = dict(runtime_id=runtime,
                admission_b64=encode_control(command), admission_receipt_b64=encode_control(receipt))
        stopped = asyncio.Event()
        async def client(index):
            actor = self.actors[index]
            response, ident = None, 0
            admission = {}
            observer = self.observer(index, self.models[actor.player.player_id])
            while True:
                result = await actor.rpc("battle_execute", battle_id=self.battle_id, generation=self.generation,
                    incarnation=100+index, response_id=ident if response else 0,
                    response_b64=encode_control(response) if response else None, **admission,
                    **self.admission_proofs[actor.player.player_id])
                self.assertEqual(result["type"], "battle_result", result)
                view = result["result"]
                self.assertNotEqual(view["state"], "recovery_required", view)
                if view["state"] == "admitting":
                    if view["command_b64"] is not None:
                        command = decode_control(view["command_b64"])
                        self.assertEqual(command.opcode, Opcode.BIND)
                        admission = dict(admission_sha256=hashlib.sha256(command.pack()).hexdigest())
                    await asyncio.sleep(.001)
                    continue
                if view["command_b64"] is not None and ident != view["command_id"]:
                    command = decode_control(view["command_b64"])
                    selected = index == 0 and command.opcode == opcode
                    if selected and not uncertain:
                        stopped.set()
                        await asyncio.Future()
                    response = await self.run_command(observer, self.models[actor.player.player_id], command)
                    ident = view["command_id"]
                    if selected:
                        stopped.set()
                        await asyncio.Future()  # The reply was lost after the native mutation.
                await asyncio.sleep(.001)
        if opcode == Opcode.ADMIT:
            stopped.set()
        tasks = [] if opcode == Opcode.ADMIT else [asyncio.create_task(client(i)) for i in range(4 if multi else 2)]
        try:
            async with asyncio.timeout(40):
                await stopped.wait()
        finally:
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for observer in getattr(self, "observers", []):
                await observer.stop()   # the interrupted games: their launchers stop with them
            self.observers = []
            for result in results:
                if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                    raise result
        self.old_leases = [actor.lease for actor in self.actors]
        await self._restart_host()

    async def _restart_host(self):
        for actor in self.actors:
            await actor.close()
        await self.server.close()
        self.store.close()
        self.store = TradeCheckpointStore(self.root/"world.sqlite3", fixture.BUILD, fixture.RULES)
        self.server = WorldServer(ServerConfig(fixture.BUILD, fixture.RULES, heartbeat_interval=.05, idle_timeout=20),
            store=self.store, development_trades=True, development_battles=True)
        self.server.enable_battle_execution((None,)*721, self.root/"execution", resume_enabled=True, peek=self.peek)
        await self.server.start(port=0)
        self.actors = [await fixture.Actor.connect(self.server.address, player) for player in self.players]
        self.desk = self.server.battle_desk

    async def _recover(self, count):
        async def exchange(index, response=None, ident=0, stage=None, incarnation=None):
            request = dict(battle_id=self.battle_id, generation=self.generation,
                incarnation=100+index if incarnation is None else incarnation,
                response_id=ident if response else 0, response_b64=encode_control(response) if response else None,
                response_stage=stage if response else None)
            admission = getattr(self, "recovery_admissions", {}).get(index)
            if admission is not None:
                request["admission_sha256"] = admission
            result = await self.actors[index].rpc("battle_resume", **request)
            validate_battle_reply(result, self.players[index].player_id, self.store.metadata.world_id,
                                 self.actors[index].lease)
            return result
        bad = await exchange(0, incarnation=999)
        self.assertEqual(bad["code"], "battle_incarnation_changed")
        before = sum(len(model.calls) for model in self.models.values())
        for index in range(count-1):
            self.assertEqual((await exchange(index))["result"]["state"], "waiting")
        self.assertEqual(sum(len(model.calls) for model in self.models.values()), before)
        async def client(index):
            response, ident, stage = None, 0, None
            model = self.models[self.players[index].player_id]
            observer = None
            while True:
                result = await exchange(index, response, ident, stage)
                self.assertEqual(result["type"], "battle_result", result)
                view = result["result"]
                self.assertNotEqual(view["state"], "recovery_required", repr(
                    self.server.battle_execution.recovery.rooms[self.battle_id].error))
                if view["state"] == "closed":
                    return
                if view["command_b64"] is not None and (stage, ident) != (view["stage"], view["command_id"]):
                    command = decode_control(view["command_b64"])
                    if view["stage"] == "route" and observer is None:
                        observer = self.observer(index, model)
                    response = await self.run_command(observer, model, command)
                    ident, stage = view["command_id"], view["stage"]
                await asyncio.sleep(.001)
        async with asyncio.timeout(50):
            await asyncio.gather(*(client(i) for i in range(count)))
        self.assertTrue(all(model.released for model in self.models.values()))
        self.assertTrue(all(self.actors[i].lease > self.old_leases[i] for i in range(count)))
        for index in range(count):
            self.assertEqual(self.server._battle_reservations.waiting(*self.actor(index)), [])
            self.assertEqual(self.store.read_checkpoint(*self.actor(index)).revision, 1)
        self.store.integrity_check()

    async def test_four_original_cores_resume_after_host_restart_and_uncertain_read(self):
        await self._interrupt(Opcode.READ_OUT, multi=True)
        await self._recover(4)

    async def test_uncertain_successful_release_reconciles_without_replaying_gameplay(self):
        await self._interrupt(Opcode.RELEASE)
        await self._recover(2)

    async def test_interrupted_at_a_deadline_keep_while_players_wait_replays_the_same_keep_decisions(self):
        # The router now sends KEEP only when a core's watchdog needs it (battle_execution
        # KEEP_BELOW_FRAMES). Interrupt four cores at the first such KEEP, after idle steps that
        # skipped it, and recover: replay must make exactly the journal's KEEP/skip decisions.
        self.addCleanup(setattr, RetainedFixture, "IDLE_QUERIES", 0)
        RetainedFixture.IDLE_QUERIES = 12
        await self._interrupt(Opcode.KEEP, multi=True)
        journal = self.root/"execution"/(self.battle_id+".events.jsonl")
        events = [json.loads(line)["value"] for line in journal.read_text().splitlines()[1:]]
        opcodes = [decode_control(event["control_b64"]).opcode for event in events if event.get("kind") == "command"]
        self.assertGreater(opcodes.count(Opcode.QUERY), 4 * opcodes.count(Opcode.KEEP))  # most steps skipped it
        await self._recover(4)

    async def test_replaying_history_does_not_wait_between_historical_steps(self):
        # A live route sleeps 1 ms per step for the cores; a replay of recorded responses must not
        # (it doubled the recovery time of a long battle and let waiting clients' polls interleave
        # with every historical step).
        self.addCleanup(setattr, RetainedFixture, "IDLE_QUERIES", 0)
        RetainedFixture.IDLE_QUERIES = 40
        await self._interrupt(Opcode.RELEASE, multi=True)
        real_sleep, waits = asyncio.sleep, []
        async def sleep(delay, result=None):
            caller = sys._getframe(1)
            if caller.f_code.co_filename.endswith("battle_execution.py"):
                replay = getattr(caller.f_locals.get("self"), "service", None)
                waits.append((delay, getattr(replay, "replaying", False)))
            return await real_sleep(delay, result)
        with patch.object(asyncio, "sleep", sleep):
            await self._recover(4)
        replayed = [delay for delay, replaying in waits if replaying]
        self.assertGreater(len(replayed), 40)                  # the idle history was replayed
        self.assertEqual(set(replayed), {0})                   # without waiting

    async def test_a_journal_written_before_the_keep_change_recovers_with_a_keep_every_step(self):
        # A battle interrupted under the old router (format v1: KEEP on every step) must replay
        # with that policy after the upgrade, or its commands would differ from its own journal.
        from emerald_multiplayer import battle_execution_journal as route_journal
        with unittest.mock.patch.object(route_journal, "FORMAT", route_journal.LEGACY_FORMATS[0]):
            await self._interrupt(Opcode.RELEASE)
        journal = self.root/"execution"/(self.battle_id+".events.jsonl")
        header = json.loads(journal.read_text().splitlines()[0])["value"]
        self.assertEqual(header["format"], "native-battle-route-events-v1")
        events = [json.loads(line)["value"] for line in journal.read_text().splitlines()[1:]]
        opcodes = [decode_control(event["control_b64"]).opcode for event in events if event.get("kind") == "command"]
        self.assertEqual(opcodes.count(Opcode.KEEP), opcodes.count(Opcode.QUERY))  # the old policy
        await self._recover(2)

    async def test_a_journal_written_by_the_lock_step_router_recovers_with_its_steps(self):
        # A battle interrupted under the v2 router (lock-step steps, KEEP when needed) must replay with
        # those steps after the pipelined router (v3) ships, or its commands would differ from its journal.
        from emerald_multiplayer import battle_execution_journal as route_journal
        with unittest.mock.patch.object(route_journal, "FORMAT", route_journal.LEGACY_FORMATS[1]):
            await self._interrupt(Opcode.RELEASE)
        journal = self.root/"execution"/(self.battle_id+".events.jsonl")
        header = json.loads(journal.read_text().splitlines()[0])["value"]
        self.assertEqual(header["format"], "native-battle-route-events-v2")
        await self._recover(2)

    async def test_the_pipelined_router_overlaps_one_cores_query_with_anothers_block_commands(self):
        # KNOWN_ISSUES MS-62: a v3 route gives every core its own command each round, so a core is
        # queried while another core's block is read, received or acknowledged (v2 queried all first).
        await self._interrupt(Opcode.RELEASE)
        journal = self.root/"execution"/(self.battle_id+".events.jsonl")
        lines = journal.read_text().splitlines()
        self.assertEqual(json.loads(lines[0])["value"]["format"], "native-battle-route-events-v3")
        events = [json.loads(line)["value"] for line in lines[1:]]
        commands = [(event["actor"], decode_control(event["control_b64"]).opcode)
                    for event in events if event.get("kind") == "command"]
        opcodes = [opcode for _, opcode in commands]
        self.assertLess(opcodes.count(Opcode.KEEP), opcodes.count(Opcode.QUERY))
        overlapped = sum(1 for (a, x), (b, y) in zip(commands, commands[1:]) if a != b and Opcode.QUERY in (x, y)
                         and {x, y} & {Opcode.READ_OUT, Opcode.RECEIVE, Opcode.ACK_OUT})
        self.assertGreater(overlapped, 0)
        await self._recover(2)

    async def test_original_unexecuted_first_bind_is_completed_only_after_all_reconnect(self):
        await self._interrupt(Opcode.BIND, uncertain=False)
        await self._recover(2)

    async def test_original_provisional_holds_rebuild_first_bind_after_host_died_before_any_execute(self):
        await self._interrupt(Opcode.ADMIT, multi=True)
        self.assertIsNone(self.store._connection.execute("SELECT 1 FROM battle_reservations").fetchone())
        self.recovery_admissions = {}
        for index in range(4):
            actor = self.actors[index]
            request = dict(battle_id=self.battle_id, generation=self.generation, incarnation=100+index,
                response_id=0, response_b64=None, response_stage=None,
                **self.admission_proofs[actor.player.player_id])
            result = await actor.rpc("battle_resume", **request)
            self.assertEqual(result["type"], "battle_result", result)
            self.assertEqual(result["result"]["state"], "waiting" if index < 3 else "admitting")
        for index in range(4):
            actor = self.actors[index]
            result = await actor.rpc("battle_resume", battle_id=self.battle_id, generation=self.generation,
                incarnation=100+index, response_id=0, response_b64=None, response_stage=None,
                **self.admission_proofs[actor.player.player_id])
            validate_battle_reply(result, actor.player.player_id, self.store.metadata.world_id, actor.lease)
            descriptor = result["result"]["admission"]
            command = decode_control(descriptor["bind_b64"])
            self.assertEqual(command.sequence, 1)
            self.assertEqual(command.session_epoch, self.old_leases[index])
            self.recovery_admissions[index] = hashlib.sha256(command.pack()).hexdigest()
        self.assertTrue(all(not model.bound for model in self.models.values()))
        await self._recover(4)

    async def test_second_restart_preserves_mixed_provisional_and_full_original_intents(self):
        await self._mixed_restart()

    async def test_partial_first_bind_prefix_can_grow_after_a_full_intent_already_registered(self):
        await self._mixed_restart(partial_prefix=True)

    async def _mixed_restart(self, *, partial_prefix=False):
        await self._interrupt(Opcode.ADMIT)
        async def provisional(index):
            actor = self.actors[index]
            result = await actor.rpc("battle_resume", battle_id=self.battle_id, generation=self.generation,
                incarnation=100+index, response_id=0, response_b64=None, response_stage=None,
                **self.admission_proofs[actor.player.player_id])
            self.assertEqual(result["type"], "battle_result", result)
            return result["result"]
        self.assertEqual((await provisional(0))["state"], "waiting")
        self.assertEqual((await provisional(1))["state"], "admitting")
        command = decode_control((await provisional(0))["admission"]["bind_b64"])
        self.recovery_admissions = {0: hashlib.sha256(command.pack()).hexdigest()}
        if partial_prefix:
            # A valid durable crash boundary after header and trainer0 BIND,
            # before the host published trainer1's initial native command.
            path = self.root/"execution"/(self.battle_id+".events.jsonl")
            lines = path.read_bytes().splitlines(keepends=True)
            self.assertEqual(len(lines), 3)
            prefix = path.with_suffix(".prefix")
            journal = RouteJournal(prefix, json.loads(lines[0])["value"]["value"], create=True)
            journal.append("command", self.players[0].player_id, 1, command)
            prefix.replace(path)
        await self._restart_host()  # Only trainer 0 durably converted locally.
        result = await self.actors[0].rpc("battle_resume", battle_id=self.battle_id,
            generation=self.generation, incarnation=100, response_id=0, response_b64=None,
            response_stage=None, admission_sha256=self.recovery_admissions[0])
        self.assertEqual(result["type"], "battle_result", result)
        self.assertEqual(result["result"]["state"], "waiting")
        room = self.server.battle_execution.recovery.rooms[self.battle_id]
        if room.loading is not None:
            # A full intent counts toward provisional bootstrap only after
            # its original route bytes have completed read-only validation.
            await asyncio.wait_for(room.loading, 5)
            result = await self.actors[0].rpc("battle_resume", battle_id=self.battle_id,
                generation=self.generation, incarnation=100, response_id=0, response_b64=None,
                response_stage=None, admission_sha256=self.recovery_admissions[0])
            self.assertEqual(result["result"]["state"], "waiting")
        command = decode_control((await provisional(1))["admission"]["bind_b64"])
        self.recovery_admissions[1] = hashlib.sha256(command.pack()).hexdigest()
        self.assertTrue(all(not model.bound for model in self.models.values()))
        await self._recover(2)

    async def test_globally_closed_result_retires_one_original_without_recalling_finished_peer(self):
        await self._interrupt(Opcode.READ_OUT)
        await self._recover(2)
        before = sum(len(model.calls) for model in self.models.values())
        await self.actors[1].close()
        result = await self.actors[0].rpc("battle_resume", battle_id=self.battle_id, generation=self.generation,
            incarnation=100, response_id=0, response_b64=None, response_stage=None)
        self.assertEqual(result["type"], "battle_result", result)
        validate_battle_reply(result, self.players[0].player_id, self.store.metadata.world_id, self.actors[0].lease)
        self.assertEqual(result["result"]["stage"], "terminal")
        self.assertEqual(result["result"]["state"], "closed")
        retirement = decode_control(result["result"]["terminal"]["retire_b64"])
        self.assertEqual(retirement.opcode, Opcode.RETIRE)
        self.assertEqual(retirement.session_epoch, self.actors[0].lease)
        self.assertEqual(sum(len(model.calls) for model in self.models.values()), before)
        recovery = self.server.battle_execution.recovery
        fields = dict(battle_id=self.battle_id, generation=self.generation,
            incarnation=100, response_id=0, response_b64=None, response_stage=None)
        with patch.object(recovery, "_load_journal", wraps=recovery._load_journal) as load:
            for _ in range(2):
                result = await self.actors[0].rpc("battle_resume", **fields)
                self.assertEqual(result["result"]["stage"], "terminal")
            self.assertEqual(load.call_count, 0)
            # Discard only the closed service's memory, as on a fresh host.
            await recovery.close()
            recovery.rooms.clear()
            result = await self.actors[0].rpc("battle_resume", **fields)
            self.assertEqual(result["result"]["state"], "waiting")
            room = recovery.rooms[self.battle_id]
            await asyncio.wait_for(room.loading, 5)
            result = await self.actors[0].rpc("battle_resume", **fields)
            self.assertEqual(result["result"]["stage"], "terminal")
            self.assertEqual(load.call_count, 1)
        journal = room.journal
        raw = journal.path.read_bytes()
        changed = bytearray(raw)
        changed[raw.index(b'"sha256":"') + len(b'"sha256":"')] ^= 1
        journal.path.write_bytes(changed)
        with patch.object(journal, "_identity", return_value=journal._stamp):
            result = await self.actors[0].rpc("battle_resume", **fields)
        self.assertEqual(result["type"], "battle_error")
        self.assertEqual(sum(len(model.calls) for model in self.models.values()), before)


class ObservedRecoveryTests(BattleRecoveryNetworkTests):
    """KNOWN_ISSUES MS-62: every recovery again on the observed router's journal (v4): the replay answers the recorded
    responses and observations in journal order and then takes the cores' live reports."""
    peek = True

    async def test_a_journal_written_before_the_keep_change_recovers_with_a_keep_every_step(self):
        self.skipTest("a v1 journal: BattleRecoveryNetworkTests")

    async def test_a_journal_written_by_the_lock_step_router_recovers_with_its_steps(self):
        self.skipTest("a v2 journal: BattleRecoveryNetworkTests")

    async def test_the_pipelined_router_overlaps_one_cores_query_with_anothers_block_commands(self):
        self.skipTest("a v3 journal: BattleRecoveryNetworkTests")

    async def test_interrupted_at_a_deadline_keep_while_players_wait_replays_the_same_keep_decisions(self):
        # Players choose for 600 looks with no block: the launchers report the frames running low, the route sends
        # KEEP; interrupted at the first one, recovery replays the reports and makes the same decision.
        self.addCleanup(setattr, RetainedFixture, "IDLE_QUERIES", 0)
        RetainedFixture.IDLE_QUERIES = 600
        await self._interrupt(Opcode.KEEP, multi=True)
        journal = self.root/"execution"/(self.battle_id+".events.jsonl")
        lines = journal.read_text().splitlines()
        self.assertEqual(json.loads(lines[0])["value"]["format"], "native-battle-route-events-v4")
        events = [json.loads(line)["value"] for line in lines[1:]]
        self.assertTrue(any(event.get("kind") == "observation" for event in events))
        await self._recover(4)

    async def test_replaying_history_does_not_wait_between_historical_steps(self):
        self.addCleanup(setattr, RetainedFixture, "IDLE_QUERIES", 0)
        RetainedFixture.IDLE_QUERIES = 40
        await self._interrupt(Opcode.RELEASE, multi=True)
        real_sleep, waits = asyncio.sleep, []
        async def sleep(delay, result=None):
            caller = sys._getframe(1)
            if caller.f_code.co_filename.endswith("battle_execution.py"):
                replay = getattr(caller.f_locals.get("self"), "service", None)
                waits.append((delay, getattr(replay, "replaying", False)))
            return await real_sleep(delay, result)
        with patch.object(asyncio, "sleep", sleep):
            await self._recover(4)
        self.assertEqual({delay for delay, replaying in waits if replaying} - {0}, set())   # it never waited
