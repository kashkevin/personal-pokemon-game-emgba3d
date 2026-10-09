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


if __name__ == "__main__":
    unittest.main()
