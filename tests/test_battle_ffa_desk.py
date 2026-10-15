"""Four-player free-for-all (1v1v1v1): four independent consents, the winner/draw outcome, durable host record.

Host/desk contract only (simulated native receipts); the native engine rules are the GBA test ROM's battle/ffa suite.
"""
from dataclasses import replace
import struct
import tempfile
import time
import unittest
from uuid import uuid4

from emerald_multiplayer.ffa_results import FfaBook, FfaResultError
from emerald_multiplayer.native_battle import Opcode
import test_battle_desk as fixture
import test_battle_multi_desk as multi


class FreeForAllDeskTests(multi.MultiBattleDeskTests):
    """Reuses the full-multi fixture, replacing the invitation; the stage machinery is identical."""

    def invite(self, *, opponents=None, battle_id=None):
        return self.desk.invite_ffa(*self.actor(0), opponents if opponents is not None else
            tuple(p.player_id for p in self.players[1:]), battle_id or self.battle_id)

    outcome = 1

    def release(self, index, seq=4):
        request = self.control(index, Opcode.RELEASE, seq,
            data=struct.pack("<II", self.descriptor(index).party_crc32, self.outcome))
        response = replace(request, data=b"")
        return self.call("released", index, request, response), request, response

    # Inherited full-multi cases assume duos/outcome 1: run only the ones that hold for four independent trainers.
    test_fixed_duos_canonical_sources_and_no_inherited_consent = None
    test_exact_roster_retry_and_changed_team_or_format_conflict = None

    def test_four_independent_trainers_not_teams(self):
        self.assertEqual(self.view["mode"], 5)
        self.assertEqual(self.view["scope"], "session-local-native-free-for-all")
        self.assertEqual(self.view["teams"], [[p] for p in self.view["players"]])
        self.assertEqual(sorted(self.view["players"]), sorted(p.player_id for p in self.players))
        self.assertEqual(self.view["players"][0], self.players[0].player_id)
        self.assertEqual(self.view["consent"], [self.players[0].player_id])
        for i in range(4):
            descriptor = self.descriptor(i)
            self.assertEqual(descriptor.mode, 5)
            self.assertEqual(descriptor.source_slot, self.view["players"].index(self.players[i].player_id))
            self.assertEqual(len(descriptor.party), 600)
        # nobody's consent is inherited: each of the three accepts for themselves
        for i in (1, 2):
            self.assertEqual(self.call("accept", i, self.view["fingerprint"])["state"], "invited")
            self.assert_code("battle_state", self.call, "register", i, 100 + i)
        self.assertEqual(self.call("accept", 3, self.view["fingerprint"])["state"], "accepted")

    def test_exact_retry_and_changed_roster_or_format_conflict(self):
        ids = [p.player_id for p in self.players[1:]]
        self.assertEqual(self.invite(opponents=tuple(reversed(ids))), self.view)   # same four, same slots (sorted)
        self.assert_code("request_conflict", self.desk.invite, *self.actor(0), ids[0], self.battle_id)
        self.assert_code("request_conflict", self.desk.invite_multi, *self.actor(0), ids[1], (ids[0], ids[2]),
                         self.battle_id)
        for opponents in ((ids[0],), (ids[0], ids[1]), (ids[0], ids[0], ids[1]),
                          (self.players[0].player_id, ids[1], ids[2]), [ids[0], ids[1], ids[2]]):
            self.assert_code("invalid_battle", self.invite, opponents=opponents, battle_id=str(uuid4()))

    def test_a_win_names_the_winning_slot_and_every_trainer_must_agree(self):
        self.running()
        for i in range(3):
            view, *_ = self.finish(i, outcome=3)
            self.assertEqual(view["state"], "finishing")
        self.assert_code("battle_result_mismatch", self.finish, 3, outcome=2)
        self.assertEqual(self.call("status", 0)["state"], "recovery_required")

    def test_win_draw_and_invalid_outcomes(self):
        for outcome in (0, 6, True, None):
            fresh = type(self)("test_four_independent_trainers_not_teams")
            fresh.setUp()
            try:
                fresh.running()
                with self.subTest(outcome=outcome), self.assertRaises(Exception):
                    fresh.finish(0, outcome=outcome)
            finally:
                fresh.tearDown()
        for outcome in (1, 2, 3, 4, 5):
            fresh = type(self)("test_four_independent_trainers_not_teams")
            fresh.setUp()
            try:
                fresh.running()
                for i in range(3):
                    fresh.finish(i, outcome=outcome)
                view, *_ = fresh.finish(3, outcome=outcome)
                self.assertEqual(view["outcome"], outcome)
                self.assertEqual(view["state"], "release_authorized")
            finally:
                fresh.tearDown()

    def test_the_outcome_is_published_to_the_host_once_before_the_battle_closes(self):
        published = []
        self.desk.on_publish = lambda battle: published.append(
            (battle.battle_id, next(iter(battle.finished.values())), battle.mode, tuple(battle.players)))
        self.running()
        self.outcome = 4
        for i in range(4):
            self.finish(i, outcome=4)
        for i in range(3):
            self.release(i)
        self.assertEqual(published, [])
        self.release(3)
        self.assertEqual(published, [(self.battle_id, 4, 5, tuple(self.view["players"]))])
        self.release(3)                                                             # exact retry: still once
        self.assertEqual(len(published), 1)

    def test_a_free_for_all_never_enters_the_two_sided_pvp_archive(self):
        archive = []
        self.desk.results = type("Archive", (), {"_append_closed": lambda self_, *a: archive.append(a)})()
        self.running()
        self.outcome = 5
        for i in range(4):
            self.finish(i, outcome=5)
        for i in range(4):
            self.release(i)
        self.assertEqual(archive, [])


class FfaBookTests(unittest.TestCase):
    def setUp(self):
        import sqlite3
        from contextlib import contextmanager
        self.db = sqlite3.connect(":memory:", isolation_level=None)

        @contextmanager
        def transaction():
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        from emerald_multiplayer.ffa_results import SCHEMA
        for statement in SCHEMA:
            self.db.execute(statement)
        self.book = FfaBook(self.db, transaction, clock=lambda: 1.0)
        self.players = ["a", "b", "c", "d"]

    def test_the_winner_is_the_slot_named_and_a_repeat_changes_nothing(self):
        self.assertEqual(self.book.record("x", 3, self.players), "c")
        self.assertEqual(self.book.record("x", 1, self.players), "c")    # a replayed RELEASE, a later wrong claim: first stands
        self.assertEqual(self.book.result("x")["outcome"], 3)

    def test_a_draw_has_no_winner(self):
        self.assertIsNone(self.book.record("d", 5, self.players))
        self.assertEqual(self.book.result("d")["outcome"], 5)

    def test_invalid_outcomes_and_rosters_are_refused(self):
        for outcome in (0, 6, True, "1"):
            with self.assertRaises(FfaResultError):
                self.book.record("y", outcome, self.players)
        for players in (["a", "b"], ["a", "a", "b", "c"]):
            with self.assertRaises(FfaResultError):
                self.book.record("z", 1, players)
        self.assertIsNone(self.book.result("y"))

    def test_records_are_counted_per_trainer(self):
        self.book.record("1", 1, self.players)
        self.book.record("2", 1, self.players)
        self.book.record("3", 5, self.players)
        self.book.record("4", 2, ["a", "e", "f", "g"])
        self.assertEqual(self.book.record_of("a"), dict(played=4, won=3 - 1 + 0, drawn=1, lost=1) | dict(won=2))
        self.assertEqual(self.book.record_of("b"), dict(played=3, won=0, drawn=1, lost=2))
        self.assertEqual(self.book.record_of("nobody"), dict(played=0, won=0, drawn=0, lost=0))


if __name__ == "__main__":
    unittest.main()
