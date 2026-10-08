"""Real TCP/SQLite recovery with explicit synthetic original native cores.

This proves protocol/replay/lease fences, not real native battle acceptance.
"""
import asyncio
import hashlib
import json
from dataclasses import replace
import struct
import unittest
from uuid import UUID, uuid4

from emerald_multiplayer.battle_execution import BattleExecutionService
from emerald_multiplayer.battle_execution_journal import RouteJournal
from emerald_multiplayer.battle_execution_protocol import decode_control, encode_control
from emerald_multiplayer.battle_protocol import validate_battle_reply
from emerald_multiplayer.native_battle import NativeBinding, NativeControl, Opcode
from emerald_multiplayer.native_battle_resume import Admission, ResumeAuthorization
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore
import test_battle_arbitration as fixture
import test_battle_execution as execution_fixture


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
    asyncTearDown = fixture.BattleArbitrationTests.asyncTearDown
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
            self.root/"execution", resume_enabled=True)
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
                    response = await self.models[actor.player.player_id].rpc(command)
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
        self.server.enable_battle_execution((None,)*721, self.root/"execution", resume_enabled=True)
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
                    response = await self.models[self.players[index].player_id].rpc(command)
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
