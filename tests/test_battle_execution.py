"""Authenticated execution tests with explicit synthetic native responses.

These exercise the real server, canonical owned saves and client journal. They
do not claim an actual game, ordinary input, Windows, or reconnect acceptance.
"""
import asyncio
from dataclasses import replace
import json
import struct
from types import SimpleNamespace
import unittest
from uuid import UUID, uuid4
import zlib

from emerald_multiplayer.battle_execution import BattleExecutionService, _independent
from emerald_multiplayer.battle_execution_protocol import (
    decode_control, encode_control, execution_view, validate_execution_view)
from emerald_multiplayer.battle_journal import BattleJournalError
from emerald_multiplayer.battle_protocol import challenge_view, validate_battle_request
from emerald_multiplayer.battle_session import NativeBattleSession
from emerald_multiplayer.native_battle import Kind, NativeControl, Opcode
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.protocol import ProtocolError
import test_battle_arbitration as arbitration_fixture
from test_battle_arbitration import wait_until


class NativeFixture:
    """A synthetic mailbox lifecycle, deliberately not a battle simulator.

    It models the native watchdog as the game does (multiplayer_battle.c): every accepted mutating
    command refreshes it to 600 frames, QUERY reports the frames left without refreshing it, and a
    core whose watchdog runs out reports itself expired. FRAMES_PER_QUERY is the game time that passes
    from one query to the next."""
    FRAMES_PER_QUERY = 40
    IDLE_QUERIES = 0   # after START, this many queries see no outbound block (players choosing)

    def __init__(self, battle, slot):
        self.battle, self.slot = battle, slot
        self.frames_left = 600
        self.idle_left = self.IDLE_QUERIES
        self.sequence = 0
        self.prepared = self.started = self.released = False
        self.out_index, self.offset = 0, 0
        self.received = {}
        self.busy_once = False
        header = bytearray(32)
        header[1], header[4] = 3, 255
        roster = battle.roster[slot]
        self.blocks = [roster.trainer_descriptor, bytes(header),
            roster.party[:200], roster.party[200:400], roster.party[400:], battle.rng]

    def query(self):
        outbound = self.prepared and self.out_index < 6 and not (self.started and self.idle_left)
        restored = self.started and self.out_index == 6 and all(
            self.received.get(p) == (6, 16) for p in range(len(self.battle.players)) if p != self.slot)
        flags = (0 if self.released else 1) | (8 if self.prepared and not self.released else 0)
        flags |= 16 if self.started and not self.released else 0
        flags |= 32 if restored and not self.released else 0
        flags |= 4 if outbound else 0
        expired = self.frames_left == 0 and not self.released
        flags |= 2 if expired else 0
        data = self.blocks[self.out_index] if outbound else b""
        return struct.pack("<I16sBBBB10I", flags, UUID(self.battle.generation).bytes,
            len(self.battle.players), self.slot, self.battle.mode, 0,
            self.sequence, self.out_index + 1 if outbound else 0,
            self.out_index + 2 if outbound else 0, len(data), zlib.crc32(data) if data else 0,
            self.offset if outbound else 0, 0, self.frames_left if not self.released else 0,
            self.battle.roster[self.slot].revision if self.prepared and not self.released else 0,
            2 if restored and not self.released else 0)

    async def rpc(self, command):
        command.validate_command()
        if command.opcode == Opcode.QUERY:
            data = self.query()
            self.frames_left = max(0, self.frames_left - self.FRAMES_PER_QUERY)
            if self.started and self.idle_left:
                self.idle_left -= 1
            return replace(command, data=data)
        if command.sequence != self.sequence + 1:
            raise AssertionError("native mutation sequence changed")
        if command.opcode == Opcode.RECEIVE and self.busy_once:
            self.busy_once = False
            return replace(command, status=1, data=b"")
        self.sequence += 1
        if self.frames_left:
            self.frames_left = 600   # an accepted command refreshes the watchdog; an expired core stays expired
        data = b""
        if command.opcode == Opcode.PREPARE:
            self.prepared = True
        elif command.opcode == Opcode.START:
            self.started = True
        elif command.opcode == Opcode.READ_OUT:
            if command.offset != self.offset:
                raise AssertionError("outbound cursor changed")
            data = self.blocks[self.out_index][self.offset:self.offset + 128]
            self.offset += len(data)
        elif command.opcode == Opcode.RECEIVE:
            self.received[command.source_slot] = (command.block_sequence, command.offset + len(command.data))
        elif command.opcode == Opcode.ACK_OUT:
            if self.offset != len(self.blocks[self.out_index]):
                raise AssertionError("unread outbound block acknowledged")
            self.out_index += 1
            self.offset = 0
        elif command.opcode == Opcode.RELEASE:
            self.released = True
        if command.opcode in (Opcode.BIND, Opcode.PREPARE, Opcode.START, Opcode.KEEP):
            data = self.query()
        return replace(command, data=data)


class IndependentDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_waits_for_every_already_issued_receipt(self):
        settled = []
        async def refuse():
            raise ValueError("refused")
        async def receipt():
            await asyncio.sleep(.01)
            settled.append(True)
        with self.assertRaisesRegex(ValueError, "refused"):
            await _independent(refuse(), receipt())
        self.assertEqual(settled, [True])

    async def test_cancellation_drains_children_before_returning(self):
        entered, stopped = asyncio.Event(), asyncio.Event()
        async def held():
            entered.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()
        task = asyncio.create_task(_independent(held()))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(stopped.is_set())


class ExecutionProtocolTests(unittest.TestCase):
    def test_execution_is_bounded_and_does_not_accept_requested_commands(self):
        request = dict(type="battle_execute", request_id=str(uuid4()), session_epoch=2,
            battle_id=str(uuid4()), generation=str(uuid4()), incarnation=3,
            response_id=0, response_b64=None)
        self.assertEqual(validate_battle_request(request, 2), request)
        for changes in ({"response_id": 1}, {"command": "START"}, {"incarnation": True},
                        {"response_id": True}, {"response_b64": "x" * 320}):
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                validate_battle_request({**request, **changes}, 2)

    def test_reply_correlation_rejects_changed_lease_incarnation_battle_and_dispatch(self):
        request = dict(battle_id=str(uuid4()), generation=str(uuid4()), incarnation=3, session_epoch=2)
        command = NativeControl(3, 2, request["battle_id"], 1, Opcode.QUERY)
        view = execution_view(request["battle_id"], request["generation"], "executing", command, 1)
        self.assertEqual(validate_execution_view(view, request=request), view)
        for changes in ({"command_id": 0}, {"generation": str(uuid4())}, {"state": "closed"},
                        {"command_b64": encode_control(replace(command, session_epoch=3))},
                        {"command_b64": encode_control(replace(command, incarnation=4))}):
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                validate_execution_view({**view, **changes}, request=request)


class BattleExecutionNetworkTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = arbitration_fixture.BattleArbitrationTests.asyncSetUp
    actor = arbitration_fixture.BattleArbitrationTests.actor
    call = arbitration_fixture.BattleArbitrationTests.call

    async def asyncTearDown(self):
        await arbitration_fixture.BattleArbitrationTests.asyncTearDown(self)

    def enable(self):
        self.server.battle_execution = BattleExecutionService(self.desk, (None,) * 721, self.root / "execution")
        return self.server.battle_execution

    def accept(self, multi=False):
        if multi:
            self.desk.cancel(*self.actor(0), self.battle_id, self.generation)
            self.battle_id = str(uuid4())
            self.view = self.desk.invite_multi(*self.actor(0), self.players[1].player_id,
                (self.players[2].player_id, self.players[3].player_id), self.battle_id)
            self.generation = self.view["generation"]
        for index in range(1, 4 if multi else 2):
            self.call("accept", index, self.view["fingerprint"])
        self.view = self.desk.status(*self.actor(0), self.battle_id)

    async def exchange(self, index, response=None, dispatch=0, **changes):
        return await self.actors[index].rpc("battle_execute", battle_id=self.battle_id,
            generation=self.generation, incarnation=100 + index,
            response_id=dispatch, response_b64=None if response is None else encode_control(response), **changes)

    async def run_clients(self, *, multi=False, busy=False, use_journal=False, mutate=None, reuse=False):
        service = self.server.battle_execution if reuse else self.enable()
        self.accept(multi)
        battle = self.desk._active[self.battle_id]
        models = {p: NativeFixture(battle, slot) for slot, p in enumerate(battle.players)}
        if reuse:
            for player, model in models.items():
                model.sequence = self.native_models[player].sequence
        self.native_models = models
        for model in models.values():
            model.busy_once = busy
        async def client(index):
            actor = self.actors[index]
            model = models[actor.player.player_id]
            if use_journal:
                config = SimpleNamespace(player_id=actor.player.player_id, build_id=self.store.build_id,
                    ruleset_id=self.store.ruleset_id, ownership_enabled=True, development_battle_channel=True,
                    battle_abi_version=3, server_credential=actor.player.credential)
                c = SimpleNamespace(config=config, world_id=self.store.metadata.world_id,
                    server_epoch=self.store.metadata.server_epoch, session_epoch=actor.lease,
                    battle_incarnation=100 + index, save_profile=OWNERSHIP_PROFILE, connected=True,
                    live_checkpoint_lock=asyncio.Lock(), _live_save_owner=None, _live_battle_owner=None)
                async def cp(operation, **fields):
                    return await actor.rpc("checkpoint_" + operation, **fields)
                async def challenge(operation, **fields):
                    return await actor.rpc("battle_" + operation, **fields)
                session = NativeBattleSession(c, self.root / ("client-" + str(index)))
                async def native(command):
                    if command.opcode != Opcode.QUERY:
                        self.assertTrue(session._authorizes(command))
                    reply = await model.rpc(command)
                    if mutate is not None:
                        return mutate(index, command, reply, session)
                    return reply
                c.checkpoint_rpc, c.battle_challenge_rpc, c.battle_rpc = cp, challenge, native
                completion = await session.run(challenge_view(self.view))
                self.assertFalse(session.journal.path.exists())
                self.assertFalse(c.live_checkpoint_lock.locked())
                self.assertEqual(completion.canonical_revision, 1)
                self.assertEqual(json.loads(session.path.read_bytes())["state"], "closed")
                return completion
            response, dispatch = None, 0
            async with asyncio.timeout(20):
                while True:
                    reply = await self.exchange(index, response, dispatch)
                    self.assertEqual(reply["type"], "battle_result", reply)
                    view = reply["result"]
                    if view["state"] == "closed":
                        return
                    self.assertNotEqual(view["state"], "recovery_required")
                    if view["command_b64"] is not None and view["command_id"] != dispatch:
                        command = decode_control(view["command_b64"])
                        response, dispatch = await model.rpc(command), view["command_id"]
                    await asyncio.sleep(.001)
        tasks = [asyncio.create_task(client(i)) for i in range(4 if multi else 2)]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.assertEqual(self.desk.status(*self.actor(0), self.battle_id)["state"], "closed")
        self.assertTrue(all(model.released for model in models.values()))
        self.assertEqual(self.server._battle_reservations.waiting(*self.actor(0)), [])
        self.store.integrity_check()
        self.assertEqual(service.rooms[self.battle_id].state, "closed")

    async def test_two_authenticated_clients_complete_with_persistent_native_journals(self):
        await self.run_clients(use_journal=True)

    async def test_four_clients_route_batches_and_retry_busy_without_new_native_sequence(self):
        await self.run_clients(multi=True, busy=True, use_journal=True)

    async def test_second_battle_on_same_core_continues_native_sequence(self):
        await self.run_clients(use_journal=True)
        previous = {p: model.sequence for p, model in self.native_models.items()}
        self.battle_id = str(uuid4())
        self.view = self.desk.invite(*self.actor(0), self.players[1].player_id, self.battle_id)
        self.generation = self.view["generation"]
        await self.run_clients(use_journal=True, reuse=True)
        room = self.server.battle_execution.rooms[self.battle_id]
        for player in room.battle.players:
            command = NativeControl.unpack(room.battle.receipts[player, Opcode.BIND][0])
            self.assertEqual(command.sequence, previous[player] + 1)

    async def test_no_execution_before_every_consent_and_no_foreign_receipt(self):
        self.enable()
        reply = await self.exchange(0)
        self.assertEqual(reply["code"], "battle_not_ready")
        self.accept()
        command = NativeControl(100, self.actors[0].lease, self.battle_id, 1, Opcode.QUERY)
        reply = await self.exchange(0, replace(command, data=bytes(64)), 1)
        self.assertEqual(reply["code"], "invalid_receipt")
        self.assertFalse(self.server.battle_execution.rooms)

    async def test_forged_early_release_does_not_advance_host_or_clear_reservation(self):
        service = self.enable()
        self.accept()
        await self.exchange(0); await self.exchange(1)
        await wait_until(lambda: any(room.pending for room in service.rooms.values()))
        room = service.rooms[self.battle_id]
        actor = next(iter(room.pending))
        index = next(i for i, p in enumerate(self.players) if p.player_id == actor)
        command, future, dispatch = room.pending[actor]
        self.assertEqual(command.opcode, Opcode.BIND)
        forged = replace(command, opcode=Opcode.RELEASE, data=b"")
        reply = await self.exchange(index, forged, dispatch)
        self.assertEqual(reply["code"], "invalid_receipt")
        self.assertFalse(future.done())
        self.assertTrue(self.server._battle_reservations.waiting(*self.actor(index)))

    async def test_cancel_while_waiting_for_other_players_never_binds_or_strands_waiter(self):
        service = self.enable()
        self.accept()
        self.assertEqual((await self.exchange(0))["result"]["state"], "waiting")
        self.call("cancel", 1)
        self.assertEqual((await self.exchange(0))["result"]["state"], "aborted")
        room = service.rooms[self.battle_id]
        self.assertFalse(room.pending)
        self.assertIsNone(room.task)
        self.assertFalse(room.battle.bind_intent)
        self.assertEqual(self.server._battle_reservations.waiting(*self.actor(0)), [])

    async def test_challenge_ended_before_bind_tells_the_waiting_core(self):
        # Seen 2026-10-20: the time limit (or a cancel by the trainer who had not entered) moved an entered challenge
        # to recovery_required while its room stayed "waiting"; the entered core polled that room for good, held.
        service = self.enable()
        self.accept()
        self.assertEqual((await self.exchange(0))["result"]["state"], "waiting")
        self.desk._recover(self.desk._active[self.battle_id], "deadline")
        self.assertEqual((await self.exchange(0))["result"]["state"], "recovery_required")
        room = service.rooms[self.battle_id]
        self.assertFalse(room.pending)
        self.assertIsNone(room.task)
        self.assertFalse(room.battle.bind_intent)
        self.assertEqual(room.state, "waiting")   # the persisted room is untouched: neutral cleanup's evidence stays exact

    async def test_shutdown_keeps_durable_exact_pending_command_and_all_participants_reserved(self):
        service = self.enable()
        self.accept(multi=True)
        for i in range(4):
            await self.exchange(i)
        await wait_until(lambda: any(room.pending for room in service.rooms.values()))
        room = service.rooms[self.battle_id]
        await service.close()
        value = json.loads(room.path.read_bytes())
        self.assertEqual(value["state"], "recovery_required")
        self.assertTrue(value["pending"])
        for i in range(4):
            waiting = self.server._battle_reservations.waiting(*self.actor(i))
            self.assertEqual(waiting[0]["battle_id"], self.battle_id)

    async def test_corrupt_native_startup_never_starts_or_releases_battle(self):
        def corrupt(index, command, response, session):
            if index == 0 and command.opcode == Opcode.READ_OUT and command.kind == Kind.TRAINER:
                return replace(response, data=b"x" + response.data[1:])
            return response
        with self.assertRaises(BattleJournalError):
            await self.run_clients(use_journal=True, mutate=corrupt)
        room = self.server.battle_execution.rooms[self.battle_id]
        self.assertEqual(room.state, "recovery_required")
        self.assertFalse(room.battle.started)
        self.assertFalse(room.battle.released)
        for i in range(2):
            self.assertTrue((self.root / ("client-" + str(i)) / "pending-battle.json").exists())
        # KNOWN_ISSUES MS-17: the stopped route says why, with each player's last command hops and poll gaps.
        diagnosis = json.loads((self.server.battle_execution.directory / (self.battle_id + ".diagnosis.json")).read_bytes())
        self.assertEqual(diagnosis["reason"], "execution_interrupted")
        self.assertTrue(diagnosis["error"].startswith("BattleError"), diagnosis["error"])
        self.assertTrue(diagnosis["traceback"])
        self.assertEqual([player["slot"] for player in diagnosis["players"]], [0, 1])
        for player in diagnosis["players"]:
            self.assertGreater(player["polls"]["count"], 0)
            self.assertTrue(player["hops"])
            answered = [hop for hop in player["hops"] if hop["answered"] is not None]
            self.assertTrue(answered)
            for hop in answered:
                self.assertGreaterEqual(hop["published"], hop["delivered"])
                self.assertGreaterEqual(hop["delivered"], hop["answered"])
