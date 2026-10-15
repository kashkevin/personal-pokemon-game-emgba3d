"""The cooperative Battle Frontier (expansion Phase 8): the pure rules, the durable book, and the host service against
the real battle desk and real saved parties. The battle itself is the engine's (`--selftest-ladder`); here its released
result is fed in the way the archive provides it."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from emerald_multiplayer import coop_code
from emerald_multiplayer.frontier import (
    BRAINS, FrontierBook, FrontierError, POOLS, SET_LENGTH, TRAINER_NAMES, level_for, plan, prize_for, set_of)
from emerald_multiplayer.frontier_service import FrontierService
from emerald_multiplayer.shared_world import SharedWorld, SharedWorldError
from emerald_multiplayer.wagers import Wagers
import test_battle_desk as fixtures

WORLD = "11111111-1111-4111-8111-111111111111"


class PureRuleTests(unittest.TestCase):
    def test_codes_round_trip_and_refuse_nonsense(self):
        code = coop_code.encode(261, 262, 57, True)
        self.assertEqual(coop_code.decode(code), coop_code.Ladder(261, 262, 57, True))
        self.assertTrue(coop_code.valid_code(code) and coop_code.valid_code(1) and coop_code.valid_code(8))
        for bad in (0, 9, -1, 5.0, True, coop_code.LADDER_FLAG, 0x7FFFFFFF, code | 0x80, code | 0x100,
                    coop_code.encode(261, 262, 57) & ~0x7F, 1 << 32):
            self.assertFalse(coop_code.valid_code(bad), bad)
        for args in ((0, 262, 50), (261, 261, 50), (261, 863, 50), (261, 262, 0), (261, 262, 101)):
            with self.assertRaises(ValueError):
                coop_code.encode(*args)

    def test_levels_climb_and_cap(self):
        self.assertEqual([level_for(50, r) for r in (1, 2, 7, 8, 15)], [50, 51, 56, 59, 68])
        self.assertEqual(level_for(1, 1), 5)                        # never below 5
        self.assertEqual(level_for(99, 30), 100)
        self.assertEqual(level_for(50, 1), 50)

    def test_the_plan_is_deterministic_distinct_and_ends_every_set_with_a_brain_pair(self):
        for seed in (1, 77, 123456):
            for r in range(1, 50):
                p = plan(seed, r, 40)
                self.assertEqual(p, plan(seed, r, 40))
                a, b = p.trainers
                self.assertNotEqual(a, b)
                self.assertTrue(a in TRAINER_NAMES and b in TRAINER_NAMES)
                self.assertEqual(coop_code.decode(p.code).level, p.level)
                self.assertEqual(p.brain, r % SET_LENGTH == 0)
                if p.brain:
                    self.assertIn(p.trainers, BRAINS)
                else:
                    self.assertTrue(set(p.trainers) <= set(POOLS[min(set_of(r), len(POOLS) - 1)]))
        self.assertNotEqual({plan(s, 1, 40).trainers for s in range(1, 30)}, {plan(1, 1, 40).trainers})

    def test_difficulty_rises_with_the_sets(self):
        early = {t for r in range(1, 7) for t in plan(3, r, 40).trainers}
        late = {t for r in range(15, 21) for t in plan(3, r, 40).trainers}
        self.assertTrue(early <= set(POOLS[0]))
        self.assertTrue(late <= set(POOLS[2]))
        self.assertLess(plan(3, 1, 40).level, plan(3, 20, 40).level)

    def test_prizes(self):
        self.assertEqual(prize_for(50, 1, first_time=True), 1250)
        self.assertEqual(prize_for(50, 1, first_time=False), 125)
        self.assertEqual(prize_for(50, 7, first_time=True), 3750)         # a Brain pays three times
        self.assertGreater(prize_for(50, 8, first_time=True), prize_for(50, 6, first_time=True))
        self.assertEqual(prize_for(100, 700, first_time=True) <= 999_999, True)
        self.assertGreaterEqual(prize_for(5, 1, first_time=False), 1)


class BookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "w.sqlite3"
        self.world = SharedWorld(self.path, WORLD)
        self.addCleanup(lambda: self.world.close())
        self.book = self.world.frontier
        self.a, self.b, self.c = "pa", "pb", "pc"

    def start(self, run_id="r1"):
        self.book.propose(run_id, self.a, self.b, 99)
        return self.book.accept(run_id, self.b)

    def attempt(self, run_id="r1", battle="b1"):
        run = self.book.run(run_id)
        return self.book.issue(run_id, battle, plan(run["seed"], run["round"], 40))

    def test_a_run_needs_both_players_and_only_one_run_each(self):
        run = self.book.propose("r1", self.a, self.b, 5)
        self.assertEqual((run["state"], run["round"], run["streak"]), ("forming", 1, 0))
        self.assertEqual(self.book.propose("r1", self.a, self.b, 5)["run_id"], "r1")      # a retried proposal
        with self.assertRaises(FrontierError):
            self.book.propose("r2", self.a, self.c, 5)                                       # a is busy
        with self.assertRaises(FrontierError):
            self.book.propose("r1", self.a, self.c, 5)                                       # that id is another team's
        with self.assertRaises(FrontierError):
            self.book.propose("r3", self.a, self.a, 5)
        self.assertEqual(self.book.accept("r1", self.a)["state"], "forming")                 # the proposer already agreed
        self.assertEqual(self.book.accept("r1", self.b)["state"], "active")
        with self.assertRaises(FrontierError):
            self.book.accept("r1", self.c)
        self.assertEqual(self.book.accept("r1", self.b)["state"], "active")                  # repeating changes nothing

    def test_a_win_advances_once_and_a_repeated_result_changes_nothing(self):
        self.start()
        first = self.attempt()
        self.assertEqual(first["state"], "issued")
        with self.assertRaises(FrontierError):
            self.attempt(battle="b2")                                                        # one battle at a time
        settled = self.book.settle("b1", 1)
        self.assertEqual(settled["state"], "won")
        self.assertIsNone(self.book.settle("b1", 1))
        self.assertIsNone(self.book.settle("b1", 2))                                         # a contradicting repeat too
        run = self.book.run("r1")
        self.assertEqual((run["round"], run["streak"], run["state"]), (2, 1, "active"))
        for player in (self.a, self.b):
            self.assertEqual(self.book.record(player)["best_streak"], 1)
            self.assertEqual(self.book.record(player)["rounds"], 1)

    def test_prizes_are_in_full_only_for_a_new_depth(self):
        self.start()
        self.attempt(battle="b1")
        first = self.book.settle("b1", 1)
        self.assertEqual(set(first["prizes"]), {self.a, self.b})
        self.assertEqual(first["prizes"][self.a], prize_for(first["level"], 1, first_time=True))
        # a loses on round 2, a second run replays round 1
        self.attempt(battle="b2")
        self.book.settle("b2", 2)
        self.assertEqual(self.book.run("r1")["state"], "ended")
        self.assertEqual(self.book.record(self.a)["runs"], 1)
        self.start("r2")
        self.attempt("r2", "b3")
        again = self.book.settle("b3", 1)
        self.assertEqual(again["prizes"][self.a], prize_for(again["level"], 1, first_time=False))

    def test_a_loss_or_a_draw_ends_the_run_and_keeps_the_streak(self):
        for outcome, reason in ((2, "defeated"), (3, "draw")):
            self.start(f"r{outcome}")
            self.attempt(f"r{outcome}", f"w{outcome}")
            self.book.settle(f"w{outcome}", 1) if False else None
            lost = self.book.settle(f"w{outcome}", outcome)
            self.assertEqual(lost["state"], "lost")
            run = self.book.run(f"r{outcome}")
            self.assertEqual((run["state"], run["ended_reason"]), ("ended", reason))
            self.assertIsNone(self.book.open_attempt(f"r{outcome}"))

    def test_a_battle_that_never_started_is_voided_and_the_round_is_offered_again(self):
        self.start()
        self.attempt(battle="b1")
        self.assertEqual(self.book.void("b1")["state"], "void")
        self.assertEqual(self.book.run("r1")["round"], 1)
        self.attempt(battle="b2")                                                            # the same round again
        self.assertIsNone(self.book.settle("b1", 1))                                         # a voided battle can never pay
        self.assertEqual(self.book.settle("b2", 1)["round"], 1)

    def test_retire_keeps_the_streak_and_cannot_happen_during_a_battle(self):
        self.start()
        self.attempt(battle="b1")
        with self.assertRaises(FrontierError):
            self.book.end("r1", "retired")
        self.book.settle("b1", 1)
        ended = self.book.end("r1", "retired")
        self.assertEqual((ended["state"], ended["streak"]), ("ended", 1))
        self.assertEqual(self.book.end("r1", "retired")["state"], "ended")
        self.assertEqual(self.book.record(self.a)["runs"], 1)                                # counted once
        self.assertEqual(self.book.run_of(self.a)["state"], "ended")

    def test_a_declined_proposal_is_not_a_run(self):
        self.book.propose("r1", self.a, self.b, 5)
        self.book.end("r1", "declined")
        self.assertEqual(self.book.record(self.a)["runs"], 0)
        self.assertEqual(self.book.propose("r2", self.a, self.b, 5)["state"], "forming")

    def test_everything_survives_a_host_restart(self):
        self.start()
        self.attempt(battle="b1")
        self.book.settle("b1", 1)
        self.attempt(battle="b2")
        self.world.close()
        again = SharedWorld(self.path, WORLD)
        self.addCleanup(again.close)
        book = again.frontier
        self.assertEqual(book.run("r1")["round"], 2)
        self.assertEqual(book.open_attempt("r1")["battle_id"], "b2")
        self.assertEqual(book.record(self.a)["best_streak"], 1)
        self.assertEqual(book.attempt("b1")["state"], "won")
        self.assertIsNone(book.settle("b1", 1))
        self.assertEqual(len(book.unpaid()), 1)
        book.mark_paid("b1")
        book.mark_paid("b1")
        self.assertEqual(book.record(self.a)["earned"], book.attempt("b1")["prizes"][self.a])   # counted once
        self.assertEqual(book.unpaid(), [])


class FakeResults:
    pass


class ServiceTests(unittest.TestCase):
    """The host service against the real desk and real saved parties."""

    def setUp(self):
        self.fixture = fixtures.BattleDeskTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        f = self.fixture
        self.players = [p.player_id for p in f.players]
        f.desk.cancel(self.players[0], f.leases[self.players[0]], f.battle_id, f.generation)   # the fixture's own challenge
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.world = SharedWorld(Path(self.temp.name) / "w.sqlite3", WORLD)
        self.addCleanup(lambda: self.world.close())
        self.results = FakeResults()
        self.sessions = {p: SimpleNamespace(player_id=p, display_name=f"Trainer {i}", closed=False,
                                            session_epoch=f.leases[p]) for i, p in enumerate(self.players)}
        self.teams = {self.players[0]: self.players[1], self.players[1]: self.players[0],
                      self.players[2]: self.players[3], self.players[3]: self.players[2]}
        self.broadcasts = 0
        server = SimpleNamespace(
            store=f.store, sessions=self.sessions, battle_desk=f.desk, _battle_results=self.results,
            _battle_reservations=None, battle_execution=None, shared_world=self.world,
            wagers=Wagers(":memory:", WORLD),
            _teammate=lambda p: self.teams.get(p), _player_name=lambda p: self.sessions[p].display_name,
            _assert_battle_available=lambda *p: None)
        server._broadcast_world = lambda: setattr(self, "broadcasts", self.broadcasts + 1)
        self.server = server
        self.service = FrontierService(server)
        self.a, self.b = self.players[0], self.players[1]
        self.sa, self.sb = self.sessions[self.a], self.sessions[self.b]

    def call(self, session, op, **extra):
        return self.service.request(session, dict(type="frontier", op=op, **extra))

    def begin(self):
        self.call(self.sa, "propose")
        return self.call(self.sb, "accept")

    def round(self):
        view = self.call(self.sa, "battle")
        return view["run"]["battle_id"]

    def finish(self, battle_id, outcome):
        self.world.frontier.record_result(battle_id, outcome, self.players[:2])   # what the desk's on_publish hook does
        self.fixture.desk._active.pop(battle_id, None)
        self.fixture.desk._history.pop(battle_id, None)

    def wallet(self, player):
        return [w for w in self.server.wagers.pending_for(player)]

    def test_a_team_proposes_accepts_and_the_first_round_is_planned_from_their_party(self):
        view = self.call(self.sa, "propose")
        self.assertEqual(view["run"]["state"], "forming")
        self.assertEqual(self.call(self.sb, "status")["run"]["consent"], [self.a])
        view = self.call(self.sb, "accept")
        run = view["run"]
        self.assertEqual((run["state"], run["round"], run["streak"]), ("active", 1, 0))
        self.assertEqual(run["next"]["round"], 1)
        self.assertEqual(coop_code.decode(plan(1, 1, 1).code) is not None, True)
        self.assertGreaterEqual(run["next"]["level"], 5)
        self.assertEqual(self.call(self.sa, "status")["party_limit"], 3)

    def test_a_player_without_a_team_cannot_start_and_a_big_party_is_refused(self):
        lone = SimpleNamespace(player_id=self.players[2], display_name="Lone", closed=False,
                               session_epoch=self.fixture.leases[self.players[2]])
        self.teams[self.players[2]] = None
        with self.assertRaises(SharedWorldError) as caught:
            self.call(lone, "propose")
        self.assertEqual(caught.exception.code, "no_teammate")
        self.service.party_limit = 1                                                # the fixture's saved parties hold 2
        with self.assertRaises(SharedWorldError) as caught:
            self.call(self.sa, "propose")
        self.assertEqual(caught.exception.code, "too_many")
        self.assertIsNone(self.call(self.sa, "status")["run"])

    def test_a_round_is_a_real_coop_challenge_on_the_desk_and_only_one_at_a_time(self):
        self.begin()
        battle_id = self.round()
        native = self.fixture.desk._active[battle_id]
        run = self.world.frontier.run_of(self.a)
        expected = plan(run["seed"], 1, self.service.base_level([self.a, self.b]))
        self.assertEqual((native.mode, native.gym, tuple(native.players)), (4, expected.code, (self.a, self.b)))
        self.assertEqual(self.call(self.sb, "status")["run"]["battle_id"], battle_id)
        with self.assertRaises(SharedWorldError) as caught:
            self.call(self.sb, "battle")
        self.assertIn(caught.exception.code, ("battle_open",))
        with self.assertRaises(SharedWorldError):
            self.call(self.sa, "retire")                                           # not during a battle

    def test_a_win_pays_each_player_exactly_once_and_opens_the_next_round(self):
        self.begin()
        battle_id = self.round()
        self.finish(battle_id, 1)
        view = self.call(self.sa, "status")
        self.assertEqual((view["run"]["round"], view["run"]["streak"]), (2, 1))
        paid = self.world.frontier.attempt(battle_id)
        self.assertTrue(paid["paid"])
        for player in (self.a, self.b):
            rows = self.wallet(player)
            self.assertEqual([r["delta"] for r in rows], [paid["prizes"][player]])
        for _ in range(5):                                                         # reads, reconnects, restarts
            self.service.reconcile()
            self.call(self.sb, "status")
        self.assertEqual(len(self.wallet(self.a)), 1)
        self.assertEqual(len(self.wallet(self.b)), 1)
        self.assertEqual(self.call(self.sa, "status")["record"]["best_streak"], 1)

    def test_payment_that_crashed_halfway_is_completed_not_doubled(self):
        self.begin()
        battle_id = self.round()
        self.finish(battle_id, 1)
        self.world.frontier.settle(battle_id, 1)                                   # settled, nothing paid yet
        prizes = self.world.frontier.attempt(battle_id)["prizes"]
        self.server.wagers.grant(self.a, prizes[self.a], battle_id)               # the host died after the first grant
        self.service.reconcile()
        self.service.reconcile()
        self.assertEqual([r["delta"] for r in self.wallet(self.a)], [prizes[self.a]])
        self.assertEqual([r["delta"] for r in self.wallet(self.b)], [prizes[self.b]])
        self.assertTrue(self.world.frontier.attempt(battle_id)["paid"])

    def test_a_loss_ends_the_run_with_no_prize_and_a_new_run_can_begin(self):
        self.begin()
        self.finish(self.round(), 2)
        view = self.call(self.sa, "status")
        self.assertEqual((view["run"]["state"], view["run"]["ended_reason"]), ("ended", "defeated"))
        self.assertEqual(self.wallet(self.a), [])
        self.assertEqual(view["record"]["runs"], 1)
        self.begin()                                                               # the same team goes again
        self.assertEqual(self.call(self.sa, "status")["run"]["round"], 1)

    def test_a_battle_the_desk_never_started_comes_back_as_the_same_round(self):
        self.begin()
        battle_id = self.round()
        self.fixture.desk._active.pop(battle_id)                                  # the host lost the volatile challenge
        view = self.call(self.sa, "status")
        self.assertIsNone(view["run"]["battle_id"])
        self.assertEqual(view["run"]["round"], 1)
        again = self.round()
        self.assertNotEqual(again, battle_id)
        self.finish(again, 1)
        self.assertEqual(self.call(self.sa, "status")["run"]["streak"], 1)

    def test_a_result_that_arrives_late_for_a_voided_battle_pays_nothing(self):
        self.begin()
        battle_id = self.round()
        self.fixture.desk._active.pop(battle_id)
        self.call(self.sa, "status")                                              # voided
        self.world.frontier.record_result(battle_id, 1, self.players[:2])         # a stale or replayed result
        self.call(self.sa, "status")
        self.assertEqual(self.wallet(self.a), [])
        self.assertEqual(self.call(self.sa, "status")["run"]["streak"], 0)

    def test_a_result_is_durable_before_the_battle_closes_and_the_first_one_stands(self):
        self.world.frontier.record_result("x", 1, ["a", "b"])
        self.world.frontier.record_result("x", 2, ["a", "b"])
        self.assertEqual(self.world.frontier.coop_result("x"), 1)
        with self.assertRaises(FrontierError):
            self.world.frontier.record_result("y", 4, ["a"])

    def test_the_streak_climbs_and_retiring_keeps_it(self):
        self.begin()
        for expected in (1, 2, 3):
            self.finish(self.round(), 1)
            self.assertEqual(self.call(self.sa, "status")["run"]["streak"], expected)
        view = self.call(self.sb, "retire")
        self.assertEqual((view["run"]["state"], view["run"]["streak"]), ("ended", 3))
        self.assertEqual(view["record"]["best_streak"], 3)
        self.assertEqual(len(self.wallet(self.a)), 3)

    def test_declining_a_proposal_and_a_teammate_who_left(self):
        self.call(self.sa, "propose")
        self.assertEqual(self.call(self.sb, "cancel")["run"]["state"], "ended")
        self.begin()
        self.teams[self.a] = None
        with self.assertRaises(SharedWorldError) as caught:
            self.call(self.sa, "battle")
        self.assertEqual(caught.exception.code, "no_teammate")


class MenuTests(unittest.IsolatedAsyncioTestCase):
    """The Players menu's Battle Frontier pages against a fake host."""

    A, B = "a", "b"

    def setUp(self):
        from emerald_multiplayer.protocol import ProtocolError
        self.ProtocolError = ProtocolError
        self.calls, self.refuse = [], None
        record = {"best_streak": 4, "runs": 2, "rounds": 7, "earned": 9000}
        self.state = {"record": record, "party_limit": 3, "run": None}
        self.nav = {"players": [], "outbreak": None, "event": None}
        outer = self

        class Companion:
            config = SimpleNamespace(player_id="a", world_enabled=True, menu_abi_version=1, trade_enabled=False)
            connected, world_id, server_epoch, session_epoch = True, "w", 1, 2
            _players = [{"player_id": "a", "display_name": "Alice"}, {"player_id": "b", "display_name": "Bob"}]

            def world_nav(self):
                return outer.nav

            async def team_rpc(self, operation, **fields):
                return {"result": {"team": None, "invitations": []}}

            async def battle_challenge_rpc(self, operation, **fields):
                return {"result": []}

            async def frontier_rpc(self, op="status"):
                outer.calls.append(op)
                if outer.refuse and op != "status":
                    raise outer.ProtocolError("too_many", outer.refuse)
                return outer.advance(op)

        self.menu_cls = __import__("emerald_multiplayer.player_menu", fromlist=["PlayerMenu"]).PlayerMenu
        self.menu = self.menu_cls(Companion())

    def advance(self, op):
        run = self.state["run"]
        if op == "propose":
            self.state["run"] = dict(run_id="r", state="forming", players=["a", "b"], names=["Alice", "Bob"],
                                     consent=["a"], round=1, streak=0, ended_reason=None, battle_id=None, next=None)
        elif op == "accept":
            run.update(state="active", consent=["a", "b"], next=dict(round=1, level=42, label="Roxanne & Brawly",
                                                                     brain=False, set=1, prize=1050))
        elif op == "battle":
            run.update(battle_id="bt")
        elif op in ("cancel", "retire"):
            run.update(state="ended", ended_reason="retired" if op == "retire" else "declined", battle_id=None)
        return self.state

    async def click(self, label):
        row = next((r for r in self.menu.screen.rows if r.label == label), None)
        self.assertIsNotNone(row, [r.label for r in self.menu.screen.rows])
        return await self.menu.choose(self.menu.screen.revision, row.action)

    labels = property(lambda self: [r.label for r in self.menu.screen.rows])

    async def open(self):
        await self.menu.refresh()
        await self.click("World and my base")
        await self.click("Battle Frontier")

    async def test_the_pages_follow_a_run_from_invitation_to_retirement(self):
        await self.open()
        self.assertEqual(self.menu.screen.title, "Battle Frontier")
        self.assertIn("Bring up to 3 Pokemon", self.menu.screen.status)
        self.assertEqual(self.labels, ["Start a Frontier run", "Best 4  runs 2", "Back to World"])
        await self.click("Start a Frontier run")
        self.assertEqual(self.menu.screen.status, "Waiting for Bob")
        self.assertIn("Cancel the invitation", self.labels)
        self.state["run"]["consent"] = ["a", "b"]
        self.state["run"].update(state="active", next=dict(round=1, level=42, label="Roxanne & Brawly", brain=False,
                                                          set=1, prize=1050))
        await self.menu.refresh()
        self.assertEqual(self.menu.screen.status, "Round 1  streak 0")
        self.assertEqual(self.labels[:4], ["vs Roxanne & Brawly", "Lv42  prize $1,050", "Start round 1",
                                           "Retire (keep streak)"])
        await self.click("Start round 1")
        self.assertIn("battle", self.calls)
        self.assertIn("Recent battle results", self.labels)                        # on to the Challenges page
        self.menu._page = ("home", None)
        await self.menu.refresh()
        await self.click("World and my base")
        await self.click("Battle Frontier")
        self.assertIn("Battle: open Challenges", self.labels)
        self.assertNotIn("Retire (keep streak)", self.labels)                     # not during a battle
        self.assertTrue(all(len(label) <= 25 for label in self.labels))

    async def test_an_invitation_can_be_joined_or_declined(self):
        self.state["run"] = dict(run_id="r", state="forming", players=["b", "a"], names=["Bob", "Alice"], consent=["b"],
                                 round=1, streak=0, ended_reason=None, battle_id=None, next=None)
        await self.open()
        self.assertEqual(self.menu.screen.status, "Bob invites you")
        await self.click("Join the Frontier run")
        self.assertIn("accept", self.calls)
        self.assertEqual(self.menu.screen.status, "Round 1  streak 0")
        await self.click("Retire (keep streak)")
        self.assertIn("Last: Retired, streak 0", self.labels)

    async def test_a_brain_round_is_named_and_a_refusal_is_shown_not_hidden(self):
        self.state["run"] = dict(run_id="r", state="active", players=["a", "b"], names=["Alice", "Bob"],
                                 consent=["a", "b"], round=7, streak=6, ended_reason=None, battle_id=None,
                                 next=dict(round=7, level=60, label="Tucker & Spenser", brain=True, set=1, prize=4000))
        await self.open()
        self.assertEqual(self.labels[0], "Brain: Tucker & Spenser")
        self.refuse = "Alice: bring at most 3 Pokemon"
        await self.click("Start round 7")
        self.assertEqual(self.menu.screen.status, "Alice: bring at most 3 Pokemon")
        self.assertEqual(self.menu.screen.title, "Battle Frontier")

    def test_a_ladder_battle_has_a_readable_title(self):
        title = self.menu_cls._coop_title
        self.assertEqual(title(coop_code.encode(265, 266, 40)), "Co-op: Roxanne & Brawly")
        self.assertEqual(title(3), "Team Gym vs Wattson")
        self.assertEqual(title(None), "Team Gym vs Leader")

    async def test_a_host_without_the_frontier_says_so(self):
        self.menu.companion.frontier_rpc = None
        await self.open()
        self.assertEqual(self.menu.screen.status, "The host has no Frontier")


class ProtocolPathTests(unittest.IsolatedAsyncioTestCase):
    """A real host and companion: the request travels the world protocol and the refusals come back as host reasons."""
    import test_world_companion as _wc
    asyncSetUp = _wc.WorldCompanionTests.asyncSetUp
    asyncTearDown = _wc.WorldCompanionTests.asyncTearDown

    async def test_status_and_refusals_over_the_wire(self):
        from emerald_multiplayer.protocol import ProtocolError
        view = await self.companions[0].frontier_rpc()
        self.assertEqual((view["run"], view["party_limit"]), (None, 3))
        self.assertEqual(view["record"], {"best_streak": 0, "runs": 0, "rounds": 0, "earned": 0})
        with self.assertRaises(ProtocolError) as caught:
            await self.companions[0].frontier_rpc("propose")                       # no team
        self.assertEqual(caught.exception.code, "no_teammate")
        with self.assertRaises(ProtocolError) as caught:
            await self.companions[0].frontier_rpc("battle")
        self.assertIn(caught.exception.code, ("not_active",))

    async def test_a_malformed_request_never_leaves_the_companion(self):
        from emerald_multiplayer.protocol import ProtocolError
        with self.assertRaises(ProtocolError):
            await self.companions[0].world_rpc("frontier", op="cheat")
        with self.assertRaises(ProtocolError):
            await self.companions[0].world_rpc("frontier", op="status", amount=5)


if __name__ == "__main__":
    unittest.main()
