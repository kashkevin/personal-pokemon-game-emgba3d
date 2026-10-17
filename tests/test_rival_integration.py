"""Update 31 rival checkpoints over the real BattleDesk and BattleResults.

Real SQLite stores, real owned Flash checkpoints and the Desk's real consent,
binding, preparation, start, result and release barriers, driven with
correlated simulated native receipts (as test_battle_results does). No
emulator or actual game core runs here.
"""
from dataclasses import replace
from pathlib import Path
import struct
import unittest

from emerald_multiplayer.battle_desk import BattleError
from emerald_multiplayer.battle_results import BattleResults
from emerald_multiplayer.native_battle import Opcode
from emerald_multiplayer.rival_checkpoints import RivalCheckpoints
from emerald_multiplayer.rival_protocol import validate_rival_reply
import test_battle_desk as fixture

ROUTE110, ROUTE119, ELSEWHERE = (0, 25), (0, 34), (0, 9)


class RivalIntegrationTests(unittest.TestCase):
    tearDown = fixture.BattleDeskTests.tearDown
    actor = fixture.BattleDeskTests.actor
    call = fixture.BattleDeskTests.call
    descriptor = fixture.BattleDeskTests.descriptor
    control = fixture.BattleDeskTests.control
    query = fixture.BattleDeskTests.query
    bind = fixture.BattleDeskTests.bind
    prepare = fixture.BattleDeskTests.prepare
    start = fixture.BattleDeskTests.start
    parts = fixture.BattleDeskTests.parts
    finish = fixture.BattleDeskTests.finish
    assert_code = fixture.BattleDeskTests.assert_code

    def setUp(self):
        fixture.BattleDeskTests.setUp(self)
        self.call("cancel", 0)  # the fixture's own challenge; the trainers are free again
        self.results = BattleResults(Path(self.temp.name) / "results.sqlite3", world_id=self.store.metadata.world_id,
                                     build_id=self.store.build_id, ruleset_id=self.store.ruleset_id)
        self.desk.results = self.results
        self.rival_now = 0.0
        self.rivals = self.open()
        self.ids = [p.player_id for p in self.players]
        self.presence = {p: dict(map_group=ELSEWHERE[0], map_number=ELSEWHERE[1], activity="overworld") for p in self.ids}
        self.online = set(self.ids)

    def open(self):
        return RivalCheckpoints(Path(self.temp.name) / "world.sqlite3.rival-checkpoints.sqlite3",
                                world_id=self.store.metadata.world_id, build_id=self.store.build_id,
                                ruleset_id=self.store.ruleset_id, clock=lambda: self.rival_now)

    def invite_as(self, actor):
        """The same Desk calls WorldServer._rival_challenge makes, sent as the requesting trainer."""
        lease = self.leases[actor]
        def invite(match, battle_id):
            if match.mode == 2:
                self.desk.invite(actor, lease, next(p for p in match.players if p != actor), battle_id)
            else:
                own = next(t for t in match.teams if actor in t)
                other = next(t for t in match.teams if actor not in t)
                self.desk.invite_multi(actor, lease, next(p for p in own if p != actor), tuple(other), battle_id)
        return invite

    def rpc(self, index, operation, **fields):
        actor = self.ids[index]
        request = dict(version=1, operation=operation, **fields)
        roster = {p: f"Trainer {self.ids.index(p)}" for p in self.ids if p in self.online}
        reply = self.rivals.handle(actor, request, roster=roster, presences={p: self.presence[p] for p in roster},
                                   strengths=lambda p: 5, usable=lambda p: True, desk=self.desk,
                                   results=self.results, invite=self.invite_as(actor))
        validate_rival_reply(reply, actor, request)
        return reply["here"]

    def gather(self, indices, map_id):
        for i in indices:
            self.presence[self.ids[i]] = dict(map_group=map_id[0], map_number=map_id[1], activity="overworld")
        for i in indices:
            self.rpc(i, "vote", checkpoint_id=self.checkpoint, choice="start")
        self.rival_now += 5
        return self.rpc(indices[0], "status")

    def issue(self, index):
        here = self.rpc(index, "status")
        session = here["session"]
        ready = next(m for m in session["matches"] if m["state"] == "ready")
        here = self.rpc(index, "match", checkpoint_id=self.checkpoint, session_id=session["session_id"],
                        match=ready["index"], attempt=ready["attempt"])
        match = here["session"]["matches"][ready["index"]]
        self.battle_id = match["battle_id"]
        self.view = self.desk.status(*self.actor(index), self.battle_id)
        self.generation = self.view["generation"]
        return here

    def slot(self, player_id):
        return self.ids.index(player_id)

    def release_with(self, index, outcome, seq=4):
        request = self.control(index, Opcode.RELEASE, seq, data=struct.pack("<II", self.descriptor(index).party_crc32, outcome))
        return self.call("released", index, request, replace(request, data=b""))

    def play(self, outcome):
        """Every trainer accepts, binds, prepares, starts, finishes with ``outcome`` and releases."""
        players = [self.slot(p) for p in self.view["players"]]
        sender = self.slot(self.view["sender"])
        for i in players:
            if i != sender:
                self.call("accept", i, self.view["fingerprint"])
        for i in players:
            self.call("register", i, 100 + i)
        for i in players:
            self.prepare(i)
        self.desk.authorize_start(self.battle_id, self.generation)
        for i in players:
            self.start(i); self.parts(i)
        self.desk.authorize_running(self.battle_id, self.generation)
        for i in players:
            self.finish(i, outcome=outcome)
        for i in players:
            last = self.release_with(i, outcome)
        return last

    def test_singles_rival_battle_completes_the_checkpoint_from_the_released_result(self):
        self.checkpoint = "route110"
        here = self.gather([0, 1], ROUTE110)
        self.assertEqual(here["session"]["format"], "singles")
        here = self.issue(0)
        self.assertEqual(here["session"]["matches"][0]["state"], "invited")
        pending = self.desk.pending(*self.actor(1))
        self.assertEqual([v["battle_id"] for v in pending], [self.battle_id], "the rival sees an ordinary challenge")
        self.assertEqual(self.play(2)["state"], "closed")
        result = self.results.get(self.battle_id)
        self.assertEqual(result["outcome"], 2)
        here = self.rpc(1, "status")
        self.assertEqual(here["state"], "completed")
        self.assertEqual(here["completion"]["winners"], [result["players"][1]])
        for i in (0, 1):
            self.assertTrue(self.rpc(i, "status") and self.rivals.summary(self.ids[i])[2]["cleared"])
        # The canonical parties are restored exactly; the rival battle changed no save.
        for i in range(4):
            self.assertEqual(self.store.read_checkpoint(*self.actor(i)), self.heads[i])

    def test_two_versus_two_rival_battle_resolves_by_team(self):
        self.checkpoint = "route119"
        here = self.gather([0, 1, 2, 3], ROUTE119)
        self.assertEqual(here["session"]["format"], "multi")
        teams = {frozenset(t) for t in here["session"]["matches"][0]["teams"]}
        self.issue(0)
        self.assertEqual(self.view["mode"], 3)
        self.assertEqual({frozenset(t) for t in self.view["teams"]}, teams, "the Desk's duos are the planned teams")
        self.assertEqual(self.play(1)["state"], "closed")
        result = self.results.get(self.battle_id)
        here = self.rpc(3, "status")
        self.assertEqual(here["state"], "completed")
        self.assertEqual(sorted(here["completion"]["winners"]), sorted(result["players"][0::2]))
        self.assertEqual(sum(r["wins"] for r in here["completion"]["standings"]), 2)

    def test_a_declined_rival_challenge_reopens_the_lobby_and_completes_nothing(self):
        self.checkpoint = "route110"
        self.gather([0, 1], ROUTE110)
        self.issue(0)
        self.call("cancel", 1)
        here = self.rpc(0, "status")
        self.assertEqual(here["state"], "open")
        self.assertIsNone(self.results.get(self.battle_id))
        self.assertFalse(self.rivals.summary(self.ids[0])[2]["completed"])

    def test_an_expired_invitation_is_void_and_a_new_vote_issues_a_new_battle(self):
        self.checkpoint = "route110"
        self.gather([0, 1], ROUTE110)
        self.issue(0)
        first = self.battle_id
        self.now += 11  # the Desk's own 10 s test timeout
        self.desk.refresh()
        self.assertEqual(self.rpc(0, "status")["state"], "open")
        self.gather([0, 1], ROUTE110)
        self.issue(1)
        self.assertNotEqual(self.battle_id, first)

    def test_a_trainer_already_in_another_battle_refuses_synchronously(self):
        self.checkpoint = "route110"
        self.gather([0, 1], ROUTE110)
        self.desk.invite(*self.actor(1), self.ids[3], "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        with self.assertRaises(BattleError) as caught:
            self.issue(0)
        self.assertEqual(caught.exception.code, "battle_busy")
        self.assertEqual(self.rpc(0, "status")["state"], "open", "the refused session is canceled, not stuck")

    def test_started_battle_survives_a_rival_restart_and_completes(self):
        self.checkpoint = "route110"
        self.gather([0, 1], ROUTE110)
        self.issue(0)
        self.call("accept", 1, self.view["fingerprint"])
        for i in (0, 1):
            self.call("register", i, 100 + i)
        for i in (0, 1):
            self.prepare(i)
        self.rivals = self.open()  # host-side sidecar reopened; the Desk still holds the battle
        self.assertEqual(self.rpc(0, "status")["session"]["matches"][0]["state"], "playing")
        self.desk.authorize_start(self.battle_id, self.generation)
        for i in (0, 1):
            self.start(i); self.parts(i)
        self.desk.authorize_running(self.battle_id, self.generation)
        for i in (0, 1):
            self.finish(i, outcome=1)
        for i in (0, 1):
            self.release_with(i, 1)
        self.assertEqual(self.rpc(1, "status")["state"], "completed")


if __name__ == "__main__":
    unittest.main()
