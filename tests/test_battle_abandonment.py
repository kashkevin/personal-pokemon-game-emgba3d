"""Abandoning an interrupted native battle (KNOWN_ISSUES MS-16).

The network tests run the real world server and store with explicitly synthetic native cores (test_battle_execution's
NativeFixture); the launcher tests use a stand-in companion and a real child process as the held game. None of them
claims an actual game, ordinary input or Windows. Each test that guards against the old behaviour names it.
"""
import asyncio
import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from emerald_multiplayer.battle_abandonment import (
    CLIENT_FORMAT, RECORD_FORMAT, SCOPE, abandonment_view, local_battle_targets, record_digest,
    releases_journaled, retire_local_battle, validate_abandonment_view)
from emerald_multiplayer.battle_desk import BattleError
from emerald_multiplayer.battle_execution import BattleExecutionService
from emerald_multiplayer.battle_execution_protocol import decode_control, encode_control
from emerald_multiplayer.battle_journal import BattleIntent, FORMAT
from emerald_multiplayer.battle_protocol import validate_battle_reply, validate_battle_request
from emerald_multiplayer.battle_reservations import BattleReservations
from emerald_multiplayer.launcher_session import GameInstallation, LauncherSession, LauncherSessionError
from emerald_multiplayer.live_checkpoint import _json_bytes
from emerald_multiplayer.native_battle import NativeBinding, NativeControl, Opcode
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore
import test_battle_arbitration as arbitration
from test_battle_arbitration import Actor, BUILD, RULES, wait_until
from test_battle_execution import NativeFixture


def intent_for(world_id, actor, peer, battle_id=None, lease=7, incarnation=20, runtime_id=None):
    native = NativeBinding(str(uuid4()), (actor, peer), (lease, lease + 1), (incarnation, incarnation + 1), 0,
                           resumable=True)
    bind = NativeControl(incarnation, lease, battle_id or str(uuid4()), 1, Opcode.BIND, data=native.pack())
    return BattleIntent(world_id, actor, "a" * 64, "rules", OWNERSHIP_PROFILE, 3, lease, incarnation,
                        runtime_id or str(uuid4()), native.generation, bind.battle_id, 2, "c" * 64, bind)


def write_intent(path, intent):
    value = intent.value()
    path.write_bytes(_json_bytes(dict(format=FORMAT, intent=value, sha256=hashlib.sha256(_json_bytes(value)).hexdigest())))


class AbandonmentProtocolTests(unittest.TestCase):
    def test_requests_and_answers_are_bounded(self):
        battle, generation = str(uuid4()), str(uuid4())
        for operation in ("abandon", "fate"):
            request = dict(type="battle_" + operation, session_epoch=3, request_id=str(uuid4()),
                           battle_id=battle, generation=generation)
            self.assertEqual(validate_battle_request(request, 3), request)
            with self.assertRaises(ProtocolError):
                validate_battle_request(dict(request, winner=battle), 3)       # nobody names a result
        actor, peer = str(uuid4()), str(uuid4())
        request = dict(battle_id=battle, generation=generation)
        good = abandonment_view(battle, generation, "abandoned", (actor, peer), "a" * 64)
        self.assertEqual(validate_abandonment_view(good, actor, request), good)
        for bad in (dict(good, state="won"), dict(good, terminal_sha256=None), dict(good, players=[peer, str(uuid4())]),
                    dict(good, battle_id=str(uuid4())), dict(good, state="unresolved"), dict(good, extra=1)):
            with self.assertRaises(ProtocolError):
                validate_abandonment_view(bad, actor, request)
        unresolved = abandonment_view(battle, generation, "unresolved", (actor, peer), None)
        self.assertEqual(validate_abandonment_view(unresolved, actor, request)["state"], "unresolved")

    def test_capability_query_and_reply(self):
        request = dict(type="battle_pending", session_epoch=3, request_id=str(uuid4()), abandon_version=1)
        self.assertEqual(validate_battle_request(request, 3), request)
        with self.assertRaises(ProtocolError):
            validate_battle_request(dict(request, abandon_version=2), 3)
        world, actor = str(uuid4()), str(uuid4())
        reply = dict(type="battle_result", protocol=__import__("emerald_multiplayer.protocol").protocol.PROTOCOL_VERSION,
                     session_epoch=3, request_id=request["request_id"], operation="pending", world_id=world,
                     player_id=actor, result=[], abandon_version=1)
        validate_battle_reply(reply, actor, world, 3, request)
        with self.assertRaises(ProtocolError):
            validate_battle_reply(dict(reply, operation="history"), actor, world, 3)


class JournalTailTests(unittest.TestCase):
    def test_a_result_is_final_only_when_every_restored_release_is_journaled(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "battle.events.jsonl"
            players = [str(uuid4()), str(uuid4())]
            battle = str(uuid4())
            lines = [json.dumps(dict(sequence=0, value=dict(kind="header")))]
            for slot, player in enumerate(players):
                command = NativeControl(20 + slot, 7, battle, 9, Opcode.RELEASE, source_slot=slot, data=bytes(8))
                lines.append(json.dumps(dict(value=dict(kind="command", actor=player, dispatch_id=9,
                                                        control_b64=encode_control(command)))))
                lines.append(json.dumps(dict(value=dict(kind="response", actor=player, dispatch_id=9,
                                                        control_b64=encode_control(replace(command, data=b""))))))
            path.write_text("\n".join(lines[:-1]) + "\n")
            self.assertFalse(releases_journaled(path, players))          # the second RELEASE has no answer yet
            path.write_text("\n".join(lines) + "\n")
            self.assertTrue(releases_journaled(path, players))
            self.assertFalse(releases_journaled(Path(temporary) / "missing.jsonl", players))


class LocalRetirementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.world, self.actor, self.peer = str(uuid4()), str(uuid4()), str(uuid4())

    def test_retirement_keeps_the_host_answer_and_the_exact_bytes_then_removes_only_that_battle(self):
        intent = intent_for(self.world, self.actor, self.peer)
        pending = self.directory / "pending-battle.json"
        write_intent(pending, intent)
        execution = self.directory / "native-battle-execution.json"
        execution.write_bytes(_json_bytes(dict(format="native-battle-client-execution-v1", state="executing",
                                               intent=intent.value())))
        before = pending.read_bytes(), execution.read_bytes()
        self.assertEqual(local_battle_targets(self.directory), [(intent.battle_id, intent.generation)])
        view = abandonment_view(intent.battle_id, intent.generation, "abandoned", (self.actor, self.peer), "d" * 64)
        record = retire_local_battle(self.directory, view)
        self.assertFalse(pending.exists())
        self.assertFalse(execution.exists())
        evidence = json.loads((self.directory / (intent.battle_id + ".battle-abandoned.json")).read_bytes())
        self.assertEqual(evidence, record)
        self.assertEqual(evidence["format"], CLIENT_FORMAT)
        self.assertEqual(evidence["host"], view)
        self.assertEqual(base64.b64decode(evidence["retired"]["pending-battle.json"]), before[0])
        self.assertEqual(base64.b64decode(evidence["retired"]["native-battle-execution.json"]), before[1])
        self.assertEqual(local_battle_targets(self.directory), [])
        # A repeat (a crash between the steps) keeps the first record.
        self.assertEqual(retire_local_battle(self.directory, view)["retired"], evidence["retired"])

    def test_another_battle_is_never_retired_and_an_unresolved_answer_retires_nothing(self):
        mine = intent_for(self.world, self.actor, self.peer)
        pending = self.directory / "pending-battle.json"
        write_intent(pending, mine)
        other = abandonment_view(str(uuid4()), str(uuid4()), "abandoned", (self.actor, self.peer), "d" * 64)
        retire_local_battle(self.directory, other)
        self.assertTrue(pending.exists())
        unresolved = abandonment_view(mine.battle_id, mine.generation, "unresolved", (self.actor, self.peer), None)
        with self.assertRaises(ValueError):
            retire_local_battle(self.directory, unresolved)
        self.assertTrue(pending.exists())


class AbandonNetworkTests(unittest.IsolatedAsyncioTestCase):
    """The host side through real authenticated connections (synthetic native cores)."""
    asyncSetUp = arbitration.BattleArbitrationTests.asyncSetUp
    actor = arbitration.BattleArbitrationTests.actor
    call = arbitration.BattleArbitrationTests.call
    register = arbitration.BattleArbitrationTests.register
    bind = arbitration.BattleArbitrationTests.bind
    control = arbitration.BattleArbitrationTests.control
    descriptor = arbitration.BattleArbitrationTests.descriptor
    query = arbitration.BattleArbitrationTests.query

    async def asyncTearDown(self):
        await arbitration.BattleArbitrationTests.asyncTearDown(self)

    def enable(self):
        self.server.battle_execution = BattleExecutionService(self.desk, (None,) * 721, self.root / "execution")
        return self.server.battle_execution

    async def ask(self, index, operation="abandon", battle_id=None, generation=None):
        return await self.actors[index].rpc("battle_" + operation, battle_id=battle_id or self.battle_id,
                                            generation=generation or self.generation)

    def row(self, battle_id=None):
        return self.store._connection.execute("SELECT * FROM battle_reservations WHERE battle_id=?",
                                              (battle_id or self.battle_id,)).fetchone()

    async def drive(self, battles, until):
        """Each player's synthetic core answers its battle's commands until ``until()``; the clients then stop."""
        models = {}
        kept = getattr(self, "models", {})
        for battle_id in battles:
            battle = self.desk._active[battle_id]
            for slot, player in enumerate(battle.players):
                previous = kept.get(player)
                models[player] = (previous if previous is not None and previous[0] == battle_id
                                  else (battle_id, battle.generation, NativeFixture(battle, slot),
                                        dict(response=None, dispatch=0)))
        self.models = {**kept, **models}
        stop = asyncio.Event()

        async def client(index):
            player = self.players[index].player_id
            if player not in models:
                return
            # The last answer is kept across drives: a core that answered a command just as a drive stopped posts that
            # answer when the battle is driven again, as a real core answers an exact retry from its cached response.
            battle_id, generation, model, last = models[player]
            while not stop.is_set():
                reply = await self.actors[index].rpc("battle_execute", battle_id=battle_id, generation=generation,
                    incarnation=100 + index, response_id=last["dispatch"],
                    response_b64=None if last["response"] is None else encode_control(last["response"]))
                if reply["type"] != "battle_result" or reply["result"]["state"] in ("closed", "aborted", "recovery_required"):
                    return reply
                view = reply["result"]
                if view["command_b64"] is not None and view["command_id"] != last["dispatch"]:
                    command = decode_control(view["command_b64"])
                    last["response"], last["dispatch"] = await model.rpc(command), view["command_id"]
                await asyncio.sleep(.001)

        tasks = [asyncio.create_task(client(i)) for i in range(4)]
        try:
            async with asyncio.timeout(30):
                while not until():
                    for task in tasks:
                        if task.done() and task.exception() is not None:
                            raise task.exception()
                    await asyncio.sleep(.005)
        finally:
            stop.set()
            await asyncio.gather(*tasks, return_exceptions=True)
        return models

    def accept(self, indices=(1,)):
        for index in indices:
            self.call("accept", index, self.view["fingerprint"])

    async def leave(self, index):
        await self.actors[index].close()
        player = self.players[index].player_id
        await wait_until(lambda: self.server._connected_lease(player) is None)

    async def test_a_player_who_leaves_a_running_1v1_no_longer_strands_the_other(self):
        # Before the fix the remaining player had no way out: no abandon operation existed, the reservation stayed.
        self.enable()
        self.accept()
        await self.drive([self.battle_id], lambda: self.desk._active[self.battle_id].state == "running")
        await self.leave(1)
        reply = await self.ask(0)
        self.assertEqual(reply["type"], "battle_result", reply)
        view = reply["result"]
        self.assertEqual((view["state"], view["players"]), ("abandoned", list(self.view["players"])))
        row = self.row()
        record = json.loads((self.root / "execution" / (self.battle_id + ".abandoned.json")).read_bytes())
        self.assertEqual((row["terminal_kind"], row["terminal_digest"]), ("aborted", record_digest(record)))
        self.assertEqual(view["terminal_sha256"], record_digest(record))
        self.assertEqual((record["format"], record["reserved"], record["requested_by"]),
                         (RECORD_FORMAT, True, self.players[0].player_id))
        self.assertEqual(self.server._battle_reservations.waiting(*self.actor(0)), [])
        battle = self.desk._history[self.battle_id]
        self.assertEqual((battle.state, battle.reason), ("aborted", "abandoned"))
        self.assertNotIn(self.battle_id, self.desk._active)
        room = self.server.battle_execution.rooms[self.battle_id]
        self.assertEqual((room.state, room.error), ("aborted", "abandoned"))
        await wait_until(lambda: room.task.done())
        self.assertEqual((room.state, room.error), ("aborted", "abandoned"))
        self.assertIsNone(self.server._battle_results.get(self.battle_id))      # no winner, no loser
        self.store.integrity_check()
        # The one who left comes back with the same character: the battle is over for them too, and both may battle again.
        self.actors[1] = await Actor.connect(self.server.address, self.players[1])
        again = await self.ask(1, "fate")
        self.assertEqual(again["result"], view)
        self.assertEqual((await self.ask(1))["result"], view)                    # exact repeat: same answer, no change
        self.assertEqual(self.row()["terminal_digest"], view["terminal_sha256"])
        fresh = str(uuid4())
        self.assertEqual(self.desk.invite(*self.actor(0), self.players[1].player_id, fresh)["state"], "invited")

    async def test_a_late_release_or_replay_cannot_publish_a_result_after_abandonment(self):
        self.enable()
        self.accept()
        await self.drive([self.battle_id], lambda: self.desk._active[self.battle_id].state == "running")
        await self.leave(1)
        self.assertEqual((await self.ask(0))["result"]["state"], "abandoned")
        battle = self.desk._history[self.battle_id]
        with self.assertRaises(BattleError) as refused:
            self.desk._publish_closed(battle, self.players[0].player_id, None, None)
        self.assertEqual(refused.exception.code, "battle_abandoned")
        self.assertIsNone(self.server._battle_results.get(self.battle_id))
        reply = await self.actors[0].rpc("battle_execute", battle_id=self.battle_id, generation=self.generation,
                                         incarnation=100, response_id=0, response_b64=None)
        self.assertEqual((reply["result"]["state"], reply["result"]["command_b64"]), ("aborted", None))
        self.assertEqual(self.row()["terminal_kind"], "aborted")

    async def test_a_running_battle_that_nobody_left_is_not_abandoned(self):
        self.enable()
        self.accept()
        await self.drive([self.battle_id], lambda: self.desk._active[self.battle_id].state == "running")
        reply = await self.ask(1)
        self.assertEqual((reply["type"], reply["code"]), ("battle_error", "battle_still_running"))
        self.assertIsNone(self.row()["terminal_kind"])
        self.assertEqual((await self.ask(1, "fate"))["result"]["state"], "unresolved")

    async def test_a_finished_battle_keeps_its_result(self):
        self.enable()
        self.accept()
        await self.drive([self.battle_id], lambda: self.desk.status(*self.actor(0), self.battle_id)["state"] == "closed")
        result = self.server._battle_results.get(self.battle_id)
        self.assertIsNotNone(result)
        view = (await self.ask(1))["result"]
        self.assertEqual(view["state"], "closed")
        self.assertEqual(self.row()["terminal_kind"], "closed")
        self.assertEqual(self.server._battle_results.get(self.battle_id), result)
        self.assertFalse((self.root / "execution" / (self.battle_id + ".abandoned.json")).exists())

    async def test_a_bound_battle_whose_player_left_before_start_is_abandoned_not_held_aborting(self):
        # Before the fix: the Desk waited for an ABORT receipt from the game that was gone, holding everyone forever.
        self.enable()
        self.register()
        self.bind(0)
        self.bind(1)
        await self.leave(1)
        self.desk.refresh()
        self.assertEqual(self.desk._active[self.battle_id].state, "aborting")
        view = (await self.ask(0))["result"]
        self.assertEqual(view["state"], "abandoned")
        self.assertEqual(self.server._battle_reservations.waiting(*self.actor(0)), [])
        self.assertNotIn(self.battle_id, self.desk._active)
        self.store.integrity_check()

    async def test_a_wager_is_cancelled_and_nobody_pays(self):
        self.server._money = lambda player: 5000
        players = list(self.view["players"])
        self.server.wagers.propose(self.battle_id, players[0], players, 500, {p: 5000 for p in players})
        for player in players:
            self.server.wagers.accept(self.battle_id, player, 500, 5000)
        self.enable()
        self.accept()
        await self.drive([self.battle_id], lambda: self.desk._active[self.battle_id].state == "running")
        self.assertEqual(self.server.wagers.view(self.battle_id)["state"], "locked")
        sequences = {p: self.server.wagers.applied_seq(p) for p in players}
        await self.leave(1)
        self.assertEqual((await self.ask(0))["result"]["state"], "abandoned")
        self.assertEqual(self.server.wagers.view(self.battle_id)["state"], "void")
        self.assertEqual({p: self.server.wagers.applied_seq(p) for p in players}, sequences)
        self.assertIsNone(self.server.wagers.next_adjustment(players[0], None))
        self.assertIsNone(self.server.wagers.next_adjustment(players[1], None))

    async def test_two_battles_at_once_only_the_interrupted_one_is_abandoned(self):
        self.accept()
        other = str(uuid4())
        view = self.desk.invite(*self.actor(2), self.players[3].player_id, other)
        self.desk.accept(*self.actor(3), other, view["generation"], view["fingerprint"])
        self.enable()
        # Both battles are under way at once: the first one is held part-way (started), the second one runs.
        await self.drive([self.battle_id], lambda: self.desk._active[self.battle_id].state in ("starting", "running"))
        await self.drive([other], lambda: self.desk._active[other].state == "running")
        self.assertIn(self.desk._active[self.battle_id].state, ("starting", "running"))
        await self.leave(3)
        reply = await self.ask(2, battle_id=other, generation=view["generation"])
        self.assertEqual(reply["result"]["state"], "abandoned")
        self.assertIsNone(self.row()["terminal_kind"])                             # the first battle is untouched
        await self.drive([self.battle_id], lambda: self.desk.status(*self.actor(0), self.battle_id)["state"] == "closed")
        self.assertIsNotNone(self.server._battle_results.get(self.battle_id))
        self.assertIsNone(self.server._battle_results.get(other))
        self.assertEqual(self.server._battle_reservations.waiting(*self.actor(2)), [])
        self.store.integrity_check()

    async def test_2v2_and_free_for_all_reservations_are_abandoned_for_all_four(self):
        self.enable()
        for mode in (3, 5):
            self.desk.cancel(*self.actor(0), self.battle_id, self.generation)
            self.battle_id = str(uuid4())
            if mode == 3:
                self.view = self.desk.invite_multi(*self.actor(0), self.players[1].player_id,
                    (self.players[2].player_id, self.players[3].player_id), self.battle_id)
            else:
                self.view = self.desk.invite_ffa(*self.actor(0),
                    tuple(p.player_id for p in self.players[1:]), self.battle_id)
            self.generation = self.view["generation"]
            self.register()
            for index in range(4):
                self.bind(index)
            await self.leave(2)
            view = (await self.ask(3))["result"]
            self.assertEqual((view["state"], len(view["players"])), ("abandoned", 4))
            for index in (0, 1, 3):
                self.assertEqual(self.server._battle_reservations.waiting(*self.actor(index)), [])
            self.actors[2] = await Actor.connect(self.server.address, self.players[2])
            self.assertEqual((await self.ask(2, "fate"))["result"], view)
            self.battle_id = str(uuid4())
            self.view = self.desk.invite(*self.actor(0), self.players[1].player_id, self.battle_id)
            self.generation = self.view["generation"]
        self.store.integrity_check()

    async def test_after_a_host_restart_the_durable_reservation_is_abandoned(self):
        self.enable()
        self.accept()
        await self.drive([self.battle_id], lambda: self.desk._active[self.battle_id].state == "running")
        players = list(self.view["players"])
        # The host goes away with the battle running; the store keeps the reservation (and the route journal).
        for actor in self.actors:
            await actor.close()
        await self.server.close()
        self.store.close()
        self.store = TradeCheckpointStore(self.root / "world.sqlite3", BUILD, RULES)
        self.store.begin_server_boot()
        self.server = WorldServer(ServerConfig(BUILD, RULES, heartbeat_interval=.05, idle_timeout=20),
                                  store=self.store, development_trades=True, development_battles=True)
        self.desk = self.server.battle_desk
        self.server.battle_execution = BattleExecutionService(self.desk, (None,) * 721, self.root / "execution")
        await self.server.start(port=0)
        self.actors = [await Actor.connect(self.server.address, player) for player in self.players]
        self.assertEqual(self.server._battle_reservations.waiting(*self.actor(1))[0]["battle_id"], self.battle_id)
        view = (await self.ask(1))["result"]
        self.assertEqual((view["state"], view["players"]), ("abandoned", players))
        for index in (0, 1):
            self.assertEqual(self.server._battle_reservations.waiting(*self.actor(index)), [])
        record = json.loads((self.root / "execution" / (self.battle_id + ".abandoned.json")).read_bytes())
        self.assertEqual((record["reserved"], record["players"]), (True, players))
        fresh = str(uuid4())
        self.assertEqual(self.desk.invite(*self.actor(0), self.players[1].player_id, fresh)["state"], "invited")
        self.store.integrity_check()

    async def test_a_crash_between_the_record_and_the_reservation_is_finished_by_the_next_request(self):
        self.enable()
        self.register()
        self.bind(0)
        self.bind(1)
        await self.leave(1)
        original = BattleReservations._abandon
        with patch.object(BattleReservations, "_abandon", side_effect=OSError("power cut")):
            failed = await self.ask(0)
        self.assertEqual((failed["type"], failed["code"]), ("battle_error", "battle_abandon_failed"))
        self.assertIsNone(self.row()["terminal_kind"])
        self.assertTrue((self.root / "execution" / (self.battle_id + ".abandoned.json")).exists())
        view = (await self.ask(0))["result"]
        self.assertEqual(view["state"], "abandoned")
        self.assertIs(BattleReservations._abandon, original)

    async def test_the_host_answers_its_capability(self):
        reply = await self.actors[0].rpc("battle_pending", abandon_version=1)
        self.assertEqual(reply.get("abandon_version"), 1)


class LauncherAbandonTests(unittest.IsolatedAsyncioTestCase):
    """The launcher side, with a stand-in companion and a real child process as the held game."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        installation = GameInstallation(self.root / "game.gba", self.root / "manifest.json", "a" * 64, "b" * 64, None)
        self.session = s = LauncherSession(installation, self.root, world_directory=self.root / "world",
                                           bind_address="127.0.0.1")
        self.actor, self.peer = str(uuid4()), str(uuid4())
        self.answers = {}
        self.calls = []

        async def challenge(operation, **fields):
            self.calls.append((operation, fields))
            answer = self.answers.get(operation)
            if isinstance(answer, BaseException):
                raise answer
            return answer(fields) if callable(answer) else answer
        self.c = c = SimpleNamespace(connected=True, world_id=str(uuid4()), server_epoch=3, session_epoch=7,
            save_profile=OWNERSHIP_PROFILE, config=SimpleNamespace(player_id=self.actor, build_id="a" * 64,
            ruleset_id="rules"), _bridge=None, stopped=None, battle_challenge_rpc=challenge,
            _emergency_controller=None, _emergency_authority=None, resumed=0)
        def resume():
            c.resumed += 1
            c.connected = True
        c.resume_world_connection = resume
        s._companion = c
        s._binding = s._signature()
        s._profile_directory = self.root / "profile"
        s._profile_directory.mkdir()
        s._open = True
        s._revision = 2
        self.intent = intent_for(c.world_id, self.actor, self.peer)
        self.pending = s._profile_directory / "pending-battle.json"
        write_intent(self.pending, self.intent)
        self.answers["pending"] = dict(result=[], abandon_version=1)
        self.answers["waiting"] = dict(result=[])
        self.view = abandonment_view(self.intent.battle_id, self.intent.generation, "abandoned",
                                     (self.actor, self.peer), "e" * 64)
        self.answers["abandon"] = self.answers["fate"] = lambda fields: dict(result=self.view)

    async def held_game(self):
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(60)")
        self.addAsyncCleanup(self.stop, process)
        self.session._game = SimpleNamespace(process=process)
        self.session._battle_recovery_failed = self.session._save_failed = True
        return process

    @staticmethod
    async def stop(process):
        if process.returncode is None:
            process.kill()
            await process.wait()

    async def test_a_cold_start_resolves_the_battle_its_lost_game_was_in(self):
        # Before the fix: pending_battle, forever (KNOWN_ISSUES MS-16).
        resolved = await self.session._resolve_interrupted_battles()
        self.assertEqual(resolved, [self.view])
        self.assertFalse(self.pending.exists())
        self.assertTrue((self.session._profile_directory / (self.intent.battle_id + ".battle-abandoned.json")).exists())
        self.assertIn(("abandon", dict(battle_id=self.intent.battle_id, generation=self.intent.generation)), self.calls)

    async def test_a_cold_start_also_resolves_a_reservation_without_a_local_intent(self):
        self.pending.unlink()
        other = str(uuid4()), str(uuid4())
        self.answers["waiting"] = dict(result=[dict(battle_id=other[0], generation=other[1])])
        self.view = abandonment_view(other[0], other[1], "abandoned", (self.actor, self.peer), "e" * 64)
        self.assertEqual(await self.session._resolve_interrupted_battles(), [self.view])

    async def test_an_unresolved_answer_or_an_older_host_leaves_the_intent(self):
        self.view = abandonment_view(self.intent.battle_id, self.intent.generation, "unresolved",
                                     (self.actor, self.peer), None)
        with self.assertRaises(LauncherSessionError) as refused:
            await self.session._resolve_interrupted_battles()
        self.assertEqual(refused.exception.code, "pending_battle")
        self.assertTrue(self.pending.exists())
        from emerald_multiplayer.companion import BattleChallengeError
        self.answers["pending"] = BattleChallengeError("invalid_fields", "unknown field")
        self.c._battle_abandon_capability = None
        self.calls.clear()
        with self.assertRaises(LauncherSessionError) as refused:
            await self.session._resolve_interrupted_battles()
        self.assertEqual(refused.exception.code, "pending_battle")          # as before the fix, for an older host
        self.assertTrue(self.pending.exists())
        self.assertNotIn("abandon", [call[0] for call in self.calls])

    async def test_the_held_game_is_closed_only_after_the_host_has_abandoned_the_battle(self):
        process = await self.held_game()
        self.assertTrue(self.session.can_abandon_battle)
        self.assertTrue(self.session.status.battle_abandon_available)
        views = await self.session.abandon_battle()
        self.assertEqual(views, [self.view])
        self.assertIsNotNone(process.returncode)
        self.assertFalse(self.pending.exists())
        self.assertEqual(self.session._battle_abandoned, [self.view])
        self.assertEqual(self.session.status.code, "battle_abandoned")
        self.assertFalse(self.session.can_abandon_battle)

    async def test_a_refusal_keeps_the_game_and_the_intent(self):
        from emerald_multiplayer.companion import BattleChallengeError
        process = await self.held_game()
        self.answers["abandon"] = BattleChallengeError("battle_still_running", "still running")
        with self.assertRaises(LauncherSessionError) as refused:
            await self.session.abandon_battle()
        self.assertEqual(refused.exception.code, "battle_still_running")
        self.assertIsNone(process.returncode)
        self.assertTrue(self.pending.exists())
        self.assertIsNone(self.session._battle_abandoned)
        self.assertTrue(self.session.can_abandon_battle)

    async def test_a_disconnected_held_game_reconnects_to_abandon(self):
        await self.held_game()
        self.c.connected = False
        await self.session.abandon_battle()
        self.assertEqual(self.c.resumed, 1)
        self.assertFalse(self.pending.exists())

    async def test_a_healthy_session_offers_no_abandonment(self):
        process = await self.held_game()
        self.session._battle_recovery_failed = self.session._save_failed = False
        self.assertFalse(self.session.can_abandon_battle)
        with self.assertRaises(LauncherSessionError):
            await self.session.abandon_battle()
        self.assertIsNone(process.returncode)

    async def test_an_abandonment_decided_elsewhere_is_followed(self):
        process = await self.held_game()
        with patch("emerald_multiplayer.launcher_session.asyncio.sleep", new=AsyncMock()):
            await asyncio.wait_for(self.session._watch_interrupted_battle(), 5)
        self.assertIsNotNone(process.returncode)
        self.assertFalse(self.pending.exists())
        self.assertIn("fate", [call[0] for call in self.calls])

    async def test_an_unresolved_battle_is_left_to_the_player(self):
        process = await self.held_game()
        self.view = abandonment_view(self.intent.battle_id, self.intent.generation, "unresolved",
                                     (self.actor, self.peer), None)
        rounds = []

        async def tick(seconds):
            rounds.append(seconds)
            if len(rounds) > 3:
                self.session._game = None                      # the player closes the game
        with patch("emerald_multiplayer.launcher_session.asyncio.sleep", new=tick):
            await asyncio.wait_for(self.session._watch_interrupted_battle(), 5)
        self.assertIsNone(process.returncode)
        self.assertTrue(self.pending.exists())
        self.assertNotIn("abandon", [call[0] for call in self.calls])

    async def test_the_next_game_starts_with_fresh_state_and_the_world_connection_back(self):
        await self.held_game()
        await self.session.abandon_battle()
        self.c.connected = False
        await self.session._restart_after_abandon()
        s = self.session
        self.assertIsNone(s._battle_abandoned)
        self.assertFalse(s._save_failed or s._battle_recovery_failed)
        self.assertIsNone(s._battle_retained)
        self.assertEqual(self.c.resumed, 1)
        self.assertEqual(s._binding, s._signature())


if __name__ == "__main__":
    unittest.main()
