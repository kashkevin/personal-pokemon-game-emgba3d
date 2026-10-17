"""Update 31 rival checkpoints through the real WorldServer over authenticated loopback.

Real SQLite world, four authenticated TCP actors, real presence messages and
the real ``battle_pending`` RPC with its ``rival`` extension. No native battle
is executed here (see test_rival_integration for the Desk lifecycle).
"""
import unittest
from uuid import uuid4

from emerald_multiplayer.rival_protocol import validate_rival_reply
from emerald_multiplayer.wagers import WagerError
import test_battle_arbitration as fixtures

ROUTE110 = 25


class RivalServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = fixtures.BattleArbitrationTests()
        await self.fixture.asyncSetUp()
        self.addAsyncCleanup(self.fixture.asyncTearDown)
        self.fixture.call("cancel", 0)
        self.server = self.fixture.server
        self.rivals = self.server._rivals
        self.rivals.countdown = 0.0
        self.ids = [p.player_id for p in self.fixture.players]
        self.seq = [0] * 4

    async def move(self, index, map_number, activity="overworld"):
        self.seq[index] += 1
        actor = self.fixture.actors[index]
        await actor.send(dict(type="presence", session_epoch=actor.lease, seq=self.seq[index], map_epoch=self.seq[index],
                              map_group=0, map_number=map_number, x=34, y=57, direction=1, elevation=0,
                              avatar_gender=0, activity=activity))
        await fixtures.wait_until(lambda: (self.server.sessions[self.ids[index]].presence or {}).get("map_number") == map_number)

    async def rival(self, index, operation, expected_error=None, **fields):
        request = dict(version=1, operation=operation, **fields)
        reply = await self.fixture.actors[index].rpc("battle_pending", rival=request)
        if expected_error:
            self.assertEqual(reply["type"], "battle_error", reply)
            self.assertEqual(reply["code"], expected_error)
            return reply
        self.assertEqual(reply["type"], "battle_result", reply)
        validate_rival_reply(reply["rival"], self.ids[index], request)
        return reply

    def test_the_sidecar_exists_beside_the_world_and_is_world_pinned(self):
        self.assertIsNotNone(self.rivals)
        self.assertEqual(self.rivals.path.name, "world.sqlite3.rival-checkpoints.sqlite3")
        self.assertEqual(self.rivals.identity["world_id"], self.fixture.store.metadata.world_id)

    async def test_status_far_from_any_checkpoint_lists_the_world_summary(self):
        reply = await self.rival(0, "status")
        self.assertIsNone(reply["rival"]["here"])
        self.assertEqual([row["checkpoint_id"] for row in reply["rival"]["checkpoints"]],
                         ["route103", "rustboro", "route110", "route119", "lilycove"])
        self.assertFalse(any(row["completed"] or row["cleared"] for row in reply["rival"]["checkpoints"]))

    async def test_vote_start_issue_and_the_rival_sees_an_ordinary_challenge(self):
        await self.move(0, ROUTE110)
        await self.move(1, ROUTE110)
        here = (await self.rival(0, "status"))["rival"]["here"]
        self.assertEqual(here["checkpoint_id"], "route110")
        self.assertEqual({row["name"] for row in here["present"]}, {"Trainer 0", "Trainer 1"})
        await self.rival(0, "vote", checkpoint_id="route110", choice="start")
        await self.rival(1, "vote", checkpoint_id="route110", choice="start")
        here = (await self.rival(1, "status"))["rival"]["here"]
        self.assertEqual(here["state"], "battling")
        session = here["session"]
        reply = await self.rival(1, "match", checkpoint_id="route110", session_id=session["session_id"], match=0, attempt=0)
        battle_id = reply["rival"]["here"]["session"]["matches"][0]["battle_id"]
        self.assertEqual([view["battle_id"] for view in reply["result"]], [battle_id], "the sender's pending challenge")
        pending = await self.fixture.actors[0].rpc("battle_pending")
        self.assertEqual([view["battle_id"] for view in pending["result"]], [battle_id])
        self.assertEqual(pending["result"][0]["sender"], self.ids[1])
        # The reserved battle ID cannot be reused by a plain challenge, nor carry a wager.
        conflict = await self.fixture.actors[2].rpc("battle_invite", peer=self.ids[3], battle_id=battle_id)
        self.assertEqual((conflict["type"], conflict["code"]), ("battle_error", "rival_match_owned"))
        with self.assertRaises(WagerError) as caught:
            self.server._wager_request(self.server.sessions[self.ids[0]],
                                       dict(type="wager_set", battle_id=battle_id, amount=100))
        self.assertEqual(caught.exception.code, "rival_match")

    async def test_errors_reach_the_client_as_battle_errors(self):
        await self.rival(0, "vote", expected_error="rival_not_present", checkpoint_id="route110", choice="start")
        await self.rival(0, "continue", expected_error="rival_not_completed", checkpoint_id="route110", via="catch_up")
        bad = await self.fixture.actors[0].rpc("battle_pending", rival=dict(version=2, operation="status"))
        self.assertEqual((bad["type"], bad["code"]), ("battle_error", "rival_unsupported"))
        bad = await self.fixture.actors[0].rpc("battle_pending", rival=dict(version=1, operation="status"),
                                               championship=dict(version=1, operation="status"))
        self.assertEqual((bad["type"], bad["code"]), ("battle_error", "invalid_fields"))

    async def test_a_disconnected_rival_leaves_the_lobby_and_reconnecting_restores_status(self):
        await self.move(0, ROUTE110)
        await self.move(1, ROUTE110)
        await self.rival(0, "vote", checkpoint_id="route110", choice="start")
        await self.fixture.actors[1].close()
        await fixtures.wait_until(lambda: self.ids[1] not in self.server.sessions)
        here = (await self.rival(0, "status"))["rival"]["here"]
        self.assertEqual([row["player_id"] for row in here["present"]], [self.ids[0]])
        self.assertEqual(here["state"], "open")
        self.fixture.actors[1] = await fixtures.Actor.connect(self.server.address, self.fixture.players[1])
        self.seq[1] = 0
        await self.move(1, ROUTE110)
        here = (await self.rival(1, "status"))["rival"]["here"]
        self.assertEqual(len(here["present"]), 2)
        self.assertIsNone(next(r for r in here["present"] if r["player_id"] == self.ids[1])["vote"],
                          "a reconnect never inherits an earlier vote")

    async def test_the_save_derived_party_checks(self):
        for player in self.ids:
            self.assertTrue(self.server._party_usable(player))
            self.assertGreater(self.server._party_strength(player), 0)
        self.assertFalse(self.server._party_usable(str(uuid4())))
        self.assertEqual(self.server._party_strength(str(uuid4())), 0)


if __name__ == "__main__":
    unittest.main()
