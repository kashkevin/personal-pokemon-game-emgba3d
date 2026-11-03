"""Authenticated loopback clients, real SQLite and original-consent files.

No native execution is simulated as acceptance: these cases never enter a battle.
"""
from copy import deepcopy
import unittest
from uuid import uuid4

from emerald_multiplayer.battle_execution import BattleExecutionService
from emerald_multiplayer.championship_protocol import validate_championship_reply
import test_battle_arbitration as fixtures


class ChampionshipRecoveryNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = fixtures.BattleArbitrationTests()
        await self.fixture.asyncSetUp()
        self.addAsyncCleanup(self.fixture.asyncTearDown)
        self.fixture.call("cancel", 0)
        self.server = self.fixture.server
        self.execution = BattleExecutionService(self.fixture.desk, (None,) * 721,
            self.fixture.root / "champ-execution", resume_enabled=True)
        self.server.battle_execution = self.execution
        self.players = [p.player_id for p in self.fixture.players]
        self.identities = [dict(incarnation=100+i,runtime_id=str(uuid4())) for i in range(4)]
        self.view = None
        await self.call("create", championship_id=str(uuid4()), players=self.players)
        for i in range(1,4):
            await self.call("accept",actor=i)

    async def call(self, operation, actor=0, expected_error=None, **fields):
        request = dict(version=1,operation=operation)
        if operation not in {"create","status","history"}:
            request.update({key:self.view[key] for key in ("championship_id","generation","fingerprint")})
        if operation in {"match","recover"}:
            match = self.view["matches"][fields.get("round",0)]
            request.update(round=match["round"],attempt=match["attempt"])
            if operation == "recover":
                request["battle_id"] = match["battle_id"]
        request.update(fields)
        reply = await self.fixture.actors[actor].rpc("battle_pending", championship=request,
            **(self.identities[actor] if operation=="match" else {}))
        if expected_error:
            self.assertEqual(reply["type"],"battle_error")
            self.assertEqual(reply["code"],expected_error)
            return reply
        self.assertEqual(reply["type"],"battle_result",reply)
        validate_championship_reply(reply["championship"],self.players[actor],request)
        self.view = reply["championship"]["current"]
        return reply

    async def test_disconnect_reconnect_recover_and_explicit_rematch_use_real_server_fences(self):
        await self.call("match")
        original = deepcopy(self.view["matches"][0])
        sender = self.fixture.actors[0]
        await sender.close()
        await fixtures.wait_until(lambda:self.players[0] not in self.server.sessions)
        self.fixture.actors[0] = await fixtures.Actor.connect(self.server.address,self.fixture.players[0])
        self.assertGreater(self.fixture.actors[0].lease,sender.lease)
        await self.call("status")
        self.assertEqual(self.view["matches"][0]["state"],"waiting")
        await self.call("recover",actor=2,expected_error="championship_changed")
        await self.call("recover",actor=1)
        self.assertEqual(self.view["matches"][0]["state"],"canceled")
        self.assertEqual(self.view["matches"][0]["battle_id"],original["battle_id"])
        tombstone = self.execution.admission._path(original["battle_id"]).read_bytes()
        self.assertTrue(self.execution.admission._read(original["battle_id"])["canceled"])
        self.assertEqual(len(self.fixture.desk._active),0)
        await self.call("match",actor=1)
        replacement = deepcopy(self.view["matches"][0])
        self.assertEqual(replacement["attempt"],2)
        self.assertNotEqual(replacement["battle_id"],original["battle_id"])
        await self.call("recover",actor=1,attempt=original["attempt"],battle_id=original["battle_id"],
                        expected_error="championship_changed")
        self.assertEqual(self.fixture.desk._active[replacement["battle_id"]].state,"invited")
        self.assertEqual(self.execution.admission._path(original["battle_id"]).read_bytes(),tombstone)
        for i,player in enumerate(self.players):
            current = self.fixture.store.read_checkpoint(player,self.fixture.actors[i].lease)
            self.assertEqual((current.revision,current.sha256,current.payload),
                (self.fixture.heads[i].revision,self.fixture.heads[i].sha256,self.fixture.heads[i].payload))
        self.assertIsNone(self.view["champion"])



class EightPlaceNetworkTests(unittest.IsolatedAsyncioTestCase):
    """Step 18 over authenticated loopback clients and the real server: protocol version 2 through the battle pending
    RPC (battle_protocol validates each version with its own module), the eight-place sidecar, the four players'
    bracket shown in version 2's shape."""

    async def asyncSetUp(self):
        self.fixture = fixtures.BattleArbitrationTests()
        await self.fixture.asyncSetUp()
        self.addAsyncCleanup(self.fixture.asyncTearDown)
        self.fixture.call("cancel", 0)
        self.server = self.fixture.server
        self.players = [p.player_id for p in self.fixture.players]
        self.view = None

    async def call(self, operation, actor=0, expected_error=None, version=2, **fields):
        from emerald_multiplayer import championship8_protocol, championship_protocol
        request = dict(version=version, operation=operation)
        if operation not in {"create", "status", "history"}:
            request.update({key: self.view[key] for key in ("championship_id", "generation", "fingerprint")})
        if operation in {"match", "recover"}:
            match = self.view["matches"][fields.get("round", 0)]
            request.update(round=match["round"], attempt=match["attempt"])
        request.update(fields)
        reply = await self.fixture.actors[actor].rpc("battle_pending", championship=request)
        if expected_error:
            self.assertEqual((reply["type"], reply["code"]), ("battle_error", expected_error), reply)
            return reply
        self.assertEqual(reply["type"], "battle_result", reply)
        module = championship8_protocol if version == 2 else championship_protocol
        module.validate_championship_reply(reply["championship"], self.players[actor], request)
        self.view = reply["championship"]["current"]
        return reply

    async def test_two_players_and_six_computer_trainers_over_the_real_server(self):
        # The host's game fights computer matches (manifest championship_abi_version 1) and has the Tower.
        self.server._championship_computers = True
        self.server._tower_enabled = True
        await self.call("create", championship_id=str(uuid4()), players=self.players[:2])
        self.assertEqual((self.view["format"], self.view["state"], self.view["rule"]), (8, "proposed", "open"))
        self.assertEqual([entrant["player"] for entrant in self.view["entrants"][:2]], self.players[:2])
        self.assertTrue(all(entrant["floor"] for entrant in self.view["entrants"][2:]))
        await self.call("accept", actor=1)
        self.assertEqual(self.view["state"], "active")
        self.assertEqual([(m["kind"], m["state"]) for m in self.view["matches"][:4]],
                         [("computer", "ready"), ("auto", "won"), ("computer", "ready"), ("auto", "won")])
        # These loopback players have no game connected: no ticket is issued, and the refusal says why.
        reply = await self.call("match", expected_error="championship_busy", round=0)
        self.assertEqual(reply["message"], "Your game is not connected")
        await self.call("status")
        self.assertEqual(self.view["matches"][0]["attempt"], 0)
        await self.call("status", actor=2)
        self.assertIsNone(self.view)                 # a player outside the bracket
        await self.call("create", actor=2, expected_error="championship_busy", championship_id=str(uuid4()),
                        players=self.players[2:])
        await self.call("create", actor=2, version=1, expected_error="championship_busy", championship_id=str(uuid4()),
                        players=[self.players[2], self.players[3], self.players[0], self.players[1]])

    async def test_without_computer_matches_version_2_plays_the_four_players_bracket(self):
        await self.call("create", championship_id=str(uuid4()), players=self.players[:2],
                        expected_error="championship_unavailable")
        await self.call("create", championship_id=str(uuid4()), players=self.players)
        self.assertEqual((self.view["format"], len(self.view["matches"])), (4, 3))
        for actor in range(1, 4):
            await self.call("accept", actor=actor)
        self.assertEqual(self.view["state"], "active")
        await self.call("status", version=1, actor=3)
        self.assertEqual(self.view["state"], "active")      # version 1 reads the same bracket


if __name__ == "__main__":
    unittest.main()
