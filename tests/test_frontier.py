"""The cooperative Battle Frontier (expansion Phase 8): the pure rules, the durable book, and the host service against
the real battle desk and real saved parties. The battle itself is the engine's (`--selftest-ladder`); here its released
result is fed in the way the archive provides it."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from emerald_multiplayer import coop_code, frontier_rewards, rewards
from emerald_multiplayer.rewards import decode, is_reward_word
from emerald_multiplayer.frontier import (
    LEAGUE, LEAGUE_FIRST_CLEAR_BONUS, LEAGUE_PRIZES, league_plan, league_prize,
    BRAINS, FrontierBook, FrontierError, POOLS, SET_LENGTH, TRAINER_NAMES, level_for, plan, prize_for, set_of)
from emerald_multiplayer.frontier_service import FrontierService, count_badges, BADGE_FLAGS, FLAGS_OFFSET
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
                    1 << 32):
            self.assertFalse(coop_code.valid_code(bad), bad)
        self.assertEqual(coop_code.decode(coop_code.encode(261, 262, 0)).level, 0)          # 0: the trainers' own levels
        for args in ((0, 262, 50), (261, 261, 50), (261, 863, 50), (261, 262, 101), (261, 262, -1)):
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


class LeagueBookTests(unittest.TestCase):
    """The Pokemon League on the same book: three co-op rounds, individual progress, a Hall of Fame."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "w.sqlite3"
        self.world = SharedWorld(self.path, WORLD)
        self.addCleanup(lambda: self.world.close())
        self.book = self.world.frontier

    def run_league(self, run_id, a, b, outcomes, prefix=None):
        prefix = prefix or run_id
        self.book.propose(run_id, a, b, 1, "league")
        self.book.accept(run_id, b)
        settled = []
        for i, outcome in enumerate(outcomes, 1):
            run = self.book.run(run_id)
            self.book.issue(run_id, f"{prefix}-{i}", league_plan(run["round"]))
            settled.append(self.book.settle(f"{prefix}-{i}", outcome))
        return settled

    def test_the_ladder_is_the_elite_four_then_the_champion_at_their_own_levels(self):
        self.assertEqual([r[:2] for r in LEAGUE], [(261, 262), (263, 264), (335, 804)])
        for i in (1, 2, 3):
            code = coop_code.decode(league_plan(i).code)
            self.assertEqual((code.trainer_a, code.trainer_b, code.level), LEAGUE[i - 1][:2] + (0,))
        self.assertTrue(league_plan(3).brain and not league_plan(1).brain)
        with self.assertRaises(FrontierError):
            league_plan(4)
        self.assertTrue(all(len(name) <= 25 for _, _, name in LEAGUE))

    def test_clearing_it_pays_each_round_and_a_first_clear_bonus_once_per_player(self):
        settled = self.run_league("L1", "pa", "pb", [1, 1, 1])
        self.assertEqual([s["prizes"]["pa"] for s in settled], [LEAGUE_PRIZES[0], LEAGUE_PRIZES[1],
                                                                 LEAGUE_PRIZES[2] + LEAGUE_FIRST_CLEAR_BONUS])
        run = self.book.run("L1")
        self.assertEqual((run["state"], run["ended_reason"], run["streak"]), ("ended", "cleared", 3))
        for player in ("pa", "pb"):
            record = self.book.league_record(player)
            self.assertEqual((record["clears"], record["best_round"]), (1, 3))
            self.assertIsNotNone(record["first_clear"])
            self.assertEqual(self.book.record(player)["runs"], 1)
        # A second clear by the same pair pays a tenth and no bonus.
        again = self.run_league("L2", "pa", "pb", [1, 1, 1])
        self.assertEqual([s["prizes"]["pa"] for s in again], [league_prize(r, first_time=False) for r in (1, 2, 3)])
        self.assertEqual(self.book.league_record("pa")["clears"], 2)

    def test_progress_is_individual_a_newcomer_still_earns_their_own_first_time_prizes(self):
        self.run_league("L1", "pa", "pb", [1, 1, 1])
        mixed = self.run_league("L2", "pa", "pc", [1, 1, 1])          # pa is a veteran helping pc
        self.assertEqual(mixed[0]["prizes"]["pa"], league_prize(1, first_time=False))
        self.assertEqual(mixed[0]["prizes"]["pc"], league_prize(1, first_time=True))
        self.assertEqual(mixed[2]["prizes"]["pc"], LEAGUE_PRIZES[2] + LEAGUE_FIRST_CLEAR_BONUS)
        self.assertEqual(mixed[2]["prizes"]["pa"], league_prize(3, first_time=False))
        self.assertEqual([self.book.league_record(p)["clears"] for p in ("pa", "pb", "pc")], [2, 1, 1])

    def test_a_defeat_ends_the_run_and_keeps_the_rounds_beaten_and_the_next_try_starts_over(self):
        lost = self.run_league("L1", "pa", "pb", [1, 2])
        self.assertEqual(lost[1]["state"], "lost")
        run = self.book.run("L1")
        self.assertEqual((run["state"], run["ended_reason"], run["streak"]), ("ended", "defeated", 1))
        self.assertEqual(self.book.league_record("pa"), {**self.book.league_record("pa"), "clears": 0, "best_round": 1})
        self.book.propose("L2", "pa", "pb", 2, "league")
        self.assertEqual(self.book.run("L2")["round"], 1)
        self.book.accept("L2", "pb")
        self.book.issue("L2", "x", league_plan(1))
        # round 1 again pays a tenth: it was cleared before
        self.assertEqual(self.book.settle("x", 1)["prizes"]["pa"], league_prize(1, first_time=False))

    def test_the_hall_of_fame_enters_a_cleared_run_exactly_once_and_survives_a_restart(self):
        self.run_league("L1", "pa", "pb", [1, 1, 1])
        party = [{"name": "Alice", "mons": [[25, 50]]}, {"name": "Bob", "mons": [[6, 52], [9, 51]]}]
        self.assertTrue(self.book.add_hall_of_fame("L1", ["Alice", "Bob"], party))
        self.assertFalse(self.book.add_hall_of_fame("L1", ["Alice", "Bob"], party))
        self.assertEqual(self.book.cleared_without_hall(), [])
        self.run_league("L2", "pa", "pb", [1, 1, 1])
        self.assertEqual([r["run_id"] for r in self.book.cleared_without_hall()], ["L2"])
        with self.assertRaises(FrontierError):
            self.book.propose("F1", "pa", "pb", 1)
            self.book.accept("F1", "pb")
            self.book.add_hall_of_fame("F1", [], [])                                  # not a cleared League run
        self.world.close()
        again = SharedWorld(self.path, WORLD)
        self.addCleanup(again.close)
        hall = again.frontier.hall_of_fame()
        self.assertEqual([e["run_id"] for e in hall], ["L1"])
        self.assertEqual(hall[0]["party"], party)
        self.assertEqual(again.frontier.league_record("pb")["clears"], 2)

    def test_a_world_file_from_before_the_league_is_upgraded_in_place(self):
        import sqlite3
        self.world.close()
        db = sqlite3.connect(self.path)
        db.execute("DROP TABLE frontier_runs")
        db.execute("""CREATE TABLE frontier_runs (run_id TEXT PRIMARY KEY, players TEXT NOT NULL, state TEXT NOT NULL,
            consent TEXT NOT NULL, round INTEGER NOT NULL, streak INTEGER NOT NULL, seed INTEGER NOT NULL,
            created REAL NOT NULL, updated REAL NOT NULL, ended_reason TEXT)""")
        db.execute("INSERT INTO frontier_runs VALUES ('old', '[\"pa\", \"pb\"]', 'active', '[\"pa\", \"pb\"]', 4, 3, 9, 0, 0, NULL)")
        db.commit()
        db.close()
        again = SharedWorld(self.path, WORLD)
        self.addCleanup(again.close)
        run = again.frontier.run("old")
        self.assertEqual((run["mode"], run["round"], run["streak"]), ("frontier", 4, 3))


class BadgeTests(unittest.TestCase):
    def test_badges_are_read_from_the_games_flags(self):
        block = bytearray(0x4000)
        self.assertEqual(count_badges(bytes(block)), 0)
        for flag in BADGE_FLAGS[:5]:
            block[FLAGS_OFFSET + flag // 8] |= 1 << flag % 8
        self.assertEqual(count_badges(bytes(block)), 5)
        for flag in BADGE_FLAGS:
            block[FLAGS_OFFSET + flag // 8] |= 1 << flag % 8
        self.assertEqual(count_badges(bytes(block)), 8)
        other = bytearray(0x4000)                      # the neighbouring system flags are not badges
        for flag in (0x864, 0x866, 0x86F):
            other[FLAGS_OFFSET + flag // 8] |= 1 << flag % 8
        self.assertEqual(count_badges(bytes(other)), 0)


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
        """The player's money adjustments (Battle Points and items travel on the same stream: see rewards())."""
        return [w for w in self.server.wagers.pending_for(player) if not is_reward_word(w["delta"])]

    def rewards(self, player):
        return [(decode(w["delta"]), w["battle_id"]) for w in self.server.wagers.pending_for(player) if is_reward_word(w["delta"])]

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

    def test_a_player_without_a_team_cannot_start(self):
        lone = SimpleNamespace(player_id=self.players[2], display_name="Lone", closed=False,
                               session_epoch=self.fixture.leases[self.players[2]])
        self.teams[self.players[2]] = None
        with self.assertRaises(SharedWorldError) as caught:
            self.call(lone, "propose")
        self.assertEqual(caught.exception.code, "no_teammate")
        self.assertIsNone(self.call(self.sa, "status")["run"])

    # ----------------------------------------------- team selection from a larger party (Update 16)
    def selected(self, session):
        return [slot["slot"] for slot in self.call(session, "status")["team"]["slots"] if slot["selected"]]

    def test_a_party_over_the_limit_is_no_longer_refused_it_brings_its_first_pokemon_by_default(self):
        self.service.party_limit = 1                                                # the fixture's saved parties hold 2
        self.begin()
        team = self.call(self.sa, "status")["team"]
        self.assertTrue(team["auto"])
        self.assertEqual((team["limit"], self.selected(self.sa)), (1, [0]))
        battle_id = self.round()
        roster = self.fixture.desk._active[battle_id].roster
        self.assertEqual([r.bring for r in roster], [1, 1])                         # slot 0 of each saved party
        self.assertEqual([r.battle_party[:100] for r in roster], [r.party[:100] for r in roster])
        self.assertEqual(roster[0].battle_party[100:], bytes(500))

    def test_a_party_within_the_limit_needs_no_selection_and_the_battle_is_unchanged(self):
        self.begin()
        self.assertEqual(self.selected(self.sa), [0, 1])
        roster = self.fixture.desk._active[self.round()].roster
        self.assertEqual([r.bring for r in roster], [0, 0])
        self.assertEqual([r.battle_party for r in roster], [r.party for r in roster])

    def test_a_chosen_team_is_used_for_the_level_the_battle_and_the_next_rounds(self):
        self.service.party_limit = 1
        self.begin()
        self.call(self.sa, "bring", mask=0b10)                                       # b's second Pokemon... a's, not b's
        self.assertEqual(self.selected(self.sa), [1])
        self.assertFalse(self.call(self.sa, "status")["team"]["auto"])
        self.assertEqual(self.selected(self.sb), [0])                                # the teammate keeps the default
        battle_id = self.round()
        roster = self.fixture.desk._active[battle_id].roster
        self.assertEqual([r.bring for r in roster], [2, 1])
        self.assertEqual(roster[0].battle_party[:100], roster[0].party[100:200])
        self.finish(battle_id, 1)
        self.call(self.sa, "status")
        self.assertEqual(self.selected(self.sa), [1])                                # still chosen after the round
        self.call(self.sa, "bring", mask=0)
        self.assertTrue(self.call(self.sa, "status")["team"]["auto"])                # cleared: the default again

    def test_a_bad_selection_is_refused_and_changes_nothing(self):
        self.service.party_limit = 1
        self.begin()
        for mask, code in ((0b100, "invalid_team"), (0b11, "too_many"), (0x40, "invalid_team"), (-1, "invalid_team"),
                           (True, "invalid_team"), ("1", "invalid_team")):
            with self.subTest(mask=mask), self.assertRaises(SharedWorldError) as caught:
                self.call(self.sa, "bring", mask=mask)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.world.frontier.bring(self.a), 0)
        battle_id = self.round()
        with self.assertRaises(SharedWorldError) as caught:                          # not while a battle waits
            self.call(self.sa, "bring", mask=0b10)
        self.assertEqual(caught.exception.code, "battle_open")

    def test_a_selection_that_the_save_no_longer_supports_falls_back_to_the_default(self):
        self.service.party_limit = 1
        self.begin()
        self.world.frontier.set_bring(self.a, 0b100000)                              # slot 6 does not exist in the saved party
        self.assertEqual(self.selected(self.sa), [0])
        self.assertTrue(self.call(self.sa, "status")["team"]["auto"])

    def test_the_selection_is_individual_and_survives_a_restart(self):
        self.service.party_limit = 1
        self.begin()
        self.call(self.sa, "bring", mask=0b10)
        self.service = FrontierService(self.server, party_limit=1)
        self.assertEqual(self.selected(self.sa), [1])
        self.assertEqual(self.selected(self.sb), [0])
        self.assertEqual(self.world.frontier.bring(self.b), 0)

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

    def league_service(self, badges=8):
        self.service.badges = lambda player: badges
        return self.service

    def test_the_league_needs_every_badge_from_both_players(self):
        self.league_service(badges=7)
        with self.assertRaises(SharedWorldError) as caught:
            self.call(self.sa, "propose", mode="league")
        self.assertEqual(caught.exception.code, "badges")
        self.league_service(badges=8)
        self.assertEqual(self.call(self.sa, "propose", mode="league")["run"]["mode"], "league")
        self.service.badges = lambda player: 8 if player == self.a else 6                # the partner has fewer
        with self.assertRaises(SharedWorldError) as caught:
            self.call(self.sb, "accept")
        self.assertEqual(caught.exception.code, "badges")

    def test_a_league_run_is_three_real_coop_battles_with_the_trainers_own_levels(self):
        self.league_service()
        self.call(self.sa, "propose", mode="league")
        view = self.call(self.sb, "accept")
        self.assertEqual(view["run"]["next"]["label"], "Elite 4 Sidney & Phoebe")
        self.assertEqual(view["run"]["next"]["level"], 0)
        self.assertEqual(view["league"]["rounds"], 3)
        battle_id = self.round()
        native = self.fixture.desk._active[battle_id]
        decoded = coop_code.decode(native.gym)
        self.assertEqual((native.mode, decoded.trainer_a, decoded.trainer_b, decoded.level, decoded.exp),
                         (4, 261, 262, 0, True))                    # first clear: experience is awarded
        self.finish(battle_id, 1)
        self.assertEqual(self.call(self.sa, "status")["run"]["round"], 2)
        self.finish(self.round(), 1)
        champion = self.round()
        self.assertEqual(coop_code.decode(self.fixture.desk._active[champion].gym).trainer_a, 335)
        self.finish(champion, 1)
        view = self.call(self.sa, "status")
        self.assertEqual((view["run"]["state"], view["run"]["ended_reason"]), ("ended", "cleared"))
        self.assertEqual(view["league"]["clears"], 1)
        self.assertEqual([e["names"] for e in view["league"]["hall"]], [["Trainer 0", "Trainer 1"]])
        wallet = [w["delta"] for w in self.wallet(self.a)]
        self.assertEqual(wallet, [LEAGUE_PRIZES[0], LEAGUE_PRIZES[1], LEAGUE_PRIZES[2] + LEAGUE_FIRST_CLEAR_BONUS])
        for _ in range(4):                                               # reconnects and restarts change nothing
            self.service.reconcile()
            self.call(self.sb, "status")
        self.assertEqual([w["delta"] for w in self.wallet(self.a)], wallet)
        self.assertEqual(len(self.world.frontier.hall_of_fame()), 1)
        # a second clear: veterans earn no experience and a tenth of the prize
        self.call(self.sa, "propose", mode="league")
        self.call(self.sb, "accept")
        again = self.round()
        self.assertFalse(coop_code.decode(self.fixture.desk._active[again].gym).exp)

    def test_a_ladder_run_blocks_the_other_ladder_for_the_same_team(self):
        self.league_service()
        self.begin()                                                       # a Frontier run
        with self.assertRaises(SharedWorldError) as caught:
            self.call(self.sa, "propose", mode="league")
        self.assertEqual(caught.exception.code, "run_busy")

    def test_the_streak_climbs_and_retiring_keeps_it(self):
        self.begin()
        for expected in (1, 2, 3):
            self.finish(self.round(), 1)
            self.assertEqual(self.call(self.sa, "status")["run"]["streak"], expected)
        view = self.call(self.sb, "retire")
        self.assertEqual((view["run"]["state"], view["run"]["streak"]), ("ended", 3))
        self.assertEqual(view["record"]["best_streak"], 3)
        self.assertEqual(len(self.wallet(self.a)), 3)

    # ------------------------------------------------------ Battle Points, items and the shop (Update 16)
    def play_round(self):
        battle_id = self.round()
        self.finish(battle_id, 1)
        self.call(self.sa, "status")
        return battle_id

    def receipt(self, player, ref, amount):
        """The player's game reports having applied the wallet adjustment queued under ``ref``."""
        entry = self.server.wagers.entry(player, ref)
        self.server.wagers.applied(player, entry["seq"], amount)

    def test_a_cleared_round_sends_each_player_their_battle_points_exactly_once(self):
        self.begin()
        battle_id = self.play_round()
        bp = frontier_rewards.bp_for(1, first_time=True)
        for player in (self.a, self.b):
            self.assertEqual(self.rewards(player), [(( rewards.KIND_BP, bp), f"{battle_id}:bp")])
        for _ in range(4):
            self.service.reconcile()
            self.call(self.sb, "status")
        for player in (self.a, self.b):
            self.assertEqual(len(self.rewards(player)), 1)
        self.assertEqual(self.world.frontier.bp_ledger(self.a)["earned"], 0)          # not before the game says it landed
        self.receipt(self.a, f"{battle_id}:bp", bp)
        self.service.reconcile(); self.service.reconcile()
        self.assertEqual(self.world.frontier.bp_ledger(self.a)["earned"], bp)         # once, even though reconciled twice
        self.assertEqual(self.world.frontier.bp_ledger(self.b)["earned"], 0)          # b's game has not reported yet
        self.assertEqual(self.call(self.sa, "status")["bp"]["earned"], bp)

    def test_battle_points_that_did_not_land_are_not_counted(self):
        self.begin()
        battle_id = self.play_round()
        self.receipt(self.a, f"{battle_id}:bp", 0)             # the save was at the 9999 cap
        self.service.reconcile()
        self.assertEqual(self.world.frontier.bp_ledger(self.a)["earned"], 0)
        self.assertEqual([r["state"] for r in self.world.frontier.rewards_of(battle_id) if r["player_id"] == self.a], ["undelivered"])

    def test_a_brain_round_adds_one_item_prize_but_only_the_first_time_a_player_clears_it(self):
        self.begin()
        run = self.world.frontier.run_of(self.a)
        brains = []
        for round_no in range(1, SET_LENGTH + 1):
            battle_id = self.play_round()
            if round_no == SET_LENGTH:
                brains.append(battle_id)
        items = [r for r in self.world.frontier.rewards_of(brains[0]) if r["kind"] == "item"]
        self.assertEqual(len(items), 2)                                                 # one for each player
        item, quantity = frontier_rewards.SET_ITEMS[0]
        self.assertEqual({r["payload"] for r in items}, {(item << 8) | quantity})
        for player in (self.a, self.b):
            kinds = [decode_word[0][0] for decode_word in self.rewards(player)]
            self.assertEqual(kinds.count(rewards.KIND_ITEM), 1)
        # the same Brain round again (a later run): no second item, only (halved) Battle Points
        self.call(self.sa, "retire")
        self.begin()
        for round_no in range(1, SET_LENGTH + 1):
            self.play_round()
        again = [r for r in self.world.frontier.rewards_of(self.world.frontier.run_of(self.a) and
                 next(a["battle_id"] for a in self._attempts() if a["round"] == SET_LENGTH and a["battle_id"] != brains[0]))]
        self.assertFalse([r for r in again if r["kind"] == "item"])

    def _attempts(self):
        rows = self.world.frontier._db.execute("SELECT battle_id, round FROM frontier_attempts WHERE state='won'").fetchall()
        return [{"battle_id": r[0], "round": r[1]} for r in rows]

    def test_battle_points_survive_a_crash_between_settling_and_sending(self):
        self.begin()
        battle_id = self.round()
        self.finish(battle_id, 1)
        self.world.frontier.settle(battle_id, 1)                  # settled; nothing paid, nothing sent
        self.assertEqual([r["state"] for r in self.world.frontier.rewards_of(battle_id)], ["queued", "queued"])
        self.server.wagers.grant_reward(self.a, rewards.KIND_BP, 1, f"{battle_id}:bp")   # died right after the first grant
        self.service.reconcile(); self.service.reconcile()
        for player in (self.a, self.b):
            self.assertEqual(len(self.rewards(player)), 1)
        self.assertTrue(all(r["state"] == "sent" for r in self.world.frontier.rewards_of(battle_id)))

    def test_a_league_run_pays_no_battle_points(self):
        for player in self.players[:2]:
            self.service.badges = lambda p: 8
        self.service.check_league = lambda p: None
        self.call(self.sa, "propose", mode="league")
        self.call(self.sb, "accept")
        battle_id = self.round()
        self.finish(battle_id, 1)
        self.call(self.sa, "status")
        self.assertEqual(self.rewards(self.a), [])
        self.assertEqual(self.world.frontier.rewards_of(battle_id), [])

    def buy(self, slot, bp=100):
        self.service.battle_points = lambda player: bp
        return self.call(self.sa, "shop_buy", slot=slot)

    def test_a_purchase_debits_first_and_grants_the_item_only_after_the_points_were_taken(self):
        slot = next(i for i, e in enumerate(frontier_rewards.SHOP) if e.item == frontier_rewards.ITEM_LEFTOVERS)
        entry = frontier_rewards.SHOP[slot]
        self.buy(slot)
        purchase = self.world.frontier.open_purchase(self.a)
        self.assertEqual(purchase["state"], "debit")
        self.assertEqual(self.rewards(self.a), [((rewards.KIND_BP_DEBIT, entry.price), f"shop:{purchase['purchase_id']}:debit")])
        self.service.reconcile()
        self.assertEqual(len(self.rewards(self.a)), 1)                      # no item before the receipt
        self.receipt(self.a, f"shop:{purchase['purchase_id']}:debit", entry.price)
        self.service.reconcile(); self.service.reconcile()
        words = [w[0] for w in self.rewards(self.a)]
        self.assertEqual(words, [(rewards.KIND_BP_DEBIT, entry.price), (rewards.KIND_ITEM, rewards.item_payload(entry.item, 1))])
        self.assertEqual(self.world.frontier.purchase(purchase["purchase_id"])["state"], "granting")
        self.receipt(self.a, f"shop:{purchase['purchase_id']}:item", 1)
        self.service.reconcile()
        self.assertEqual(self.world.frontier.purchase(purchase["purchase_id"])["state"], "done")
        self.assertEqual(self.world.frontier.bp_ledger(self.a)["spent"], entry.price)
        self.assertIsNone(self.world.frontier.open_purchase(self.a))
        self.buy(slot)                                                        # the next one can start

    def test_a_save_with_fewer_points_than_the_host_believed_gets_its_points_back_and_no_item(self):
        self.buy(0)
        purchase = self.world.frontier.open_purchase(self.a)
        price = frontier_rewards.SHOP[0].price
        self.receipt(self.a, f"shop:{purchase['purchase_id']}:debit", price - 6)       # the game only had 10
        self.service.reconcile(); self.service.reconcile()
        self.assertEqual(self.world.frontier.purchase(purchase["purchase_id"])["state"], "refused")
        kinds = [w[0] for w in self.rewards(self.a)]
        self.assertEqual(kinds, [(rewards.KIND_BP_DEBIT, price), (rewards.KIND_BP, price - 6)])   # refund, never an item
        self.buy(0)                                                                     # not stuck

    def test_a_game_with_no_points_buys_nothing(self):
        self.buy(0)
        purchase = self.world.frontier.open_purchase(self.a)
        self.receipt(self.a, f"shop:{purchase['purchase_id']}:debit", 0)
        self.service.reconcile()
        self.assertEqual(self.world.frontier.purchase(purchase["purchase_id"])["state"], "refused")
        self.assertEqual(len(self.rewards(self.a)), 1)                          # only the debit that moved nothing

    def test_a_bag_that_could_not_hold_the_item_is_refunded(self):
        self.buy(0)
        purchase = self.world.frontier.open_purchase(self.a)
        price = frontier_rewards.SHOP[0].price
        pid = purchase["purchase_id"]
        self.receipt(self.a, f"shop:{pid}:debit", price)
        self.service.reconcile()
        self.receipt(self.a, f"shop:{pid}:item", 0)                             # bag and PC were full
        self.service.reconcile(); self.service.reconcile()
        self.assertEqual(self.world.frontier.purchase(pid)["state"], "refunded")
        self.assertEqual(self.rewards(self.a)[-1][0], (rewards.KIND_BP, price))
        self.assertEqual(self.world.frontier.bp_ledger(self.a)["spent"], 0)

    def test_one_open_purchase_at_a_time_and_bad_requests_are_refused(self):
        self.buy(0)
        with self.assertRaises(SharedWorldError) as caught:
            self.buy(1)
        self.assertEqual(caught.exception.code, "purchase_open")
        for slot in (-1, len(frontier_rewards.SHOP), True, "0"):
            with self.subTest(slot=slot), self.assertRaises(SharedWorldError):
                self.call(self.sb, "shop_buy", slot=slot)
        self.service.battle_points = lambda player: 3
        with self.assertRaises(SharedWorldError) as caught:
            self.call(self.sb, "shop_buy", slot=0)
        self.assertEqual(caught.exception.code, "not_enough_bp")

    def test_the_purchase_survives_a_restart_and_a_repeated_receipt_changes_nothing(self):
        self.buy(0)
        pid = self.world.frontier.open_purchase(self.a)["purchase_id"]
        price = frontier_rewards.SHOP[0].price
        self.receipt(self.a, f"shop:{pid}:debit", price)
        self.receipt(self.a, f"shop:{pid}:debit", price)                           # the game re-sends its last receipt
        self.service = FrontierService(self.server)                                # a restarted host
        for _ in range(3):
            self.service.reconcile()
        self.assertEqual(sum(1 for w in self.rewards(self.a) if w[0][0] == rewards.KIND_ITEM), 1)

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
        self.state = {"record": record, "party_limit": 3, "run": None,
                      "league": dict(clears=0, best_round=0, rounds=3, first_clear=None, last_clear=None, hall=[])}
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

            async def frontier_rpc(self, op="status", mode=None, slot=None, mask=None):
                outer.calls.append(op if mode is None else f"{op}:{mode}")
                if slot is not None:
                    outer.calls.append(f"{op}@{slot}")
                if mask is not None:
                    outer.calls.append(f"{op}@{mask}")
                    if outer.refuse is None and "team" in outer.state:          # the host keeps the selection
                        for entry in outer.state["team"]["slots"]:
                            entry["selected"] = bool(mask >> entry["slot"] & 1)
                        outer.state["team"]["auto"] = mask == 0
                if outer.refuse and op != "status":
                    raise outer.ProtocolError("too_many", outer.refuse)
                return outer.advance(op, mode)

        self.menu_cls = __import__("emerald_multiplayer.player_menu", fromlist=["PlayerMenu"]).PlayerMenu
        self.menu = self.menu_cls(Companion())

    def advance(self, op, mode=None):
        run = self.state["run"]
        if op == "propose":
            self.state["run"] = dict(run_id="r", mode=mode or "frontier", state="forming", players=["a", "b"],
                                     names=["Alice", "Bob"], consent=["a"], round=1, streak=0, ended_reason=None,
                                     battle_id=None, next=None)
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
        await self.click("Frontier and League")
        await self.click("Battle Frontier")

    async def test_the_pages_follow_a_run_from_invitation_to_retirement(self):
        await self.open()
        self.assertEqual(self.menu.screen.title, "Battle Frontier")
        self.assertIn("Bring up to 3 Pokemon", self.menu.screen.status)
        self.assertEqual(self.labels, ["Start a Frontier run", "Best 4  runs 2", "Back"])
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
        await self.click("Frontier and League")
        await self.click("Battle Frontier")
        self.assertIn("Battle: open Challenges", self.labels)
        self.assertNotIn("Retire (keep streak)", self.labels)                     # not during a battle
        self.assertTrue(all(len(label) <= 25 for label in self.labels))

    def shop_state(self, balance=40):
        shop = [dict(slot=i, name=n, price=p, quantity=1) for i, (n, p) in enumerate(
            [("Protein", 16), ("Iron", 16), ("Calcium", 16), ("Zinc", 16), ("Carbos", 16), ("Leftovers", 48)])]
        self.state["bp"] = dict(balance=balance, earned=12, spent=0, shop=shop, purchase=None)

    def team_state(self, selected=(0,), limit=3, count=6, auto=True):
        names = ["Mudkip", "Wurmple", "Zigzagoon", "Taillow", "Ralts", "Seedot"]
        self.state["team"] = dict(limit=limit, auto=auto, slots=[
            dict(slot=i, name=names[i], level=10 + i, egg=False, able=True, selected=i in selected) for i in range(count)])

    async def test_the_battle_points_shop_pages_and_an_order(self):
        self.shop_state()
        await self.open()
        self.assertEqual(self.labels, ["Start a Frontier run", "Team, BP shop  best 4", "Back"])
        await self.click("Team, BP shop  best 4")
        self.assertEqual(self.menu.screen.title, "Team and BP shop")
        await self.click("BP shop (40 BP)")
        self.assertEqual(self.menu.screen.title, "BP Shop")
        self.assertEqual(self.menu.screen.status, "Your BP: 40")
        self.assertEqual(self.labels, ["Protein 16BP", "Iron 16BP", "Calcium 16BP", "Zinc 16BP", "More items (1/2)", "Back"])
        await self.click("More items (1/2)")
        self.assertEqual(self.labels, ["Carbos 16BP", "Leftovers 48BP", "More items (2/2)", "Back"])
        await self.click("Leftovers 48BP")
        self.assertIn("shop_buy@5", self.calls)
        self.assertEqual(self.menu.screen.status, "Close the menu to finish")    # the game pays on the field
        self.state["bp"]["purchase"] = dict(state="debit", name="Leftovers", price=48, quantity=1)
        self.menu._notice = None
        await self.menu.refresh()
        self.assertEqual(self.menu.screen.status, "Close the menu to finish")
        self.state["bp"]["purchase"] = dict(state="done", name="Leftovers", price=48, quantity=1)
        await self.menu.refresh()
        self.assertEqual(self.menu.screen.status, "Bought Leftovers")
        await self.click("Back")
        await self.click("Back to the Frontier")
        self.assertEqual(self.menu.screen.title, "Battle Frontier")

    async def test_a_refused_order_is_shown(self):
        self.state["bp"] = dict(balance=2, earned=0, spent=0, purchase=None,
                                shop=[dict(slot=0, name="Protein", price=16, quantity=1)])
        await self.open()
        await self.click("Team, BP shop  best 4")
        await self.click("BP shop (2 BP)")
        self.refuse = "Protein costs 16 BP; you have 2"
        await self.click("Protein 16BP")
        self.assertEqual(self.menu.screen.status, "Protein costs 16 BP; you have 2")

    async def test_the_team_page_selects_swaps_and_refuses(self):
        self.team_state(selected=(0,), limit=2)
        self.state["bp"] = dict(balance=None, earned=0, spent=0, purchase=None, shop=[])
        await self.open()
        await self.click("Team, BP shop  best 4")
        self.assertEqual(self.menu.screen.rows[0].label, "Team: Mudkip")
        await self.click("Team: Mudkip")
        self.assertEqual(self.menu.screen.title, "Your team")
        self.assertEqual(self.menu.screen.status, "Bring up to 2: 1 chosen (auto)")
        self.assertEqual(self.labels, ["* Mudkip L10", "- Wurmple L11", "- Zigzagoon L12", "- Taillow L13", "More (1/2)", "Back"])
        await self.click("- Wurmple L11")                                            # adds: 0 and 1 -> mask 3
        self.assertIn("bring@3", self.calls)
        await self.click("- Zigzagoon L12")                                          # a full team gives up its first
        self.assertIn("bring@6", self.calls)
        await self.click("More (1/2)")
        self.assertEqual(self.labels, ["- Ralts L14", "- Seedot L15", "More (2/2)", "Back"])
        await self.click("- Seedot L15")
        self.assertIn("bring@36", self.calls)

    async def test_the_last_chosen_pokemon_cannot_be_dropped_and_a_refusal_is_shown(self):
        self.team_state(selected=(1,), limit=3, count=2, auto=False)
        self.state["bp"] = dict(balance=None, earned=0, spent=0, purchase=None, shop=[])
        await self.open()
        await self.click("Team, BP shop  best 4")
        await self.click("Team: Wurmple")
        await self.click("* Wurmple L11")
        self.assertEqual(self.menu.screen.status, "Bring at least one Pokemon")
        self.assertNotIn("bring@0", self.calls)
        self.refuse = "bring at most 3 Pokemon"
        await self.click("- Mudkip L10")
        self.assertEqual(self.menu.screen.status, "bring at most 3 Pokemon")

    async def test_an_egg_cannot_be_chosen(self):
        self.team_state(selected=(0,), count=2)
        self.state["team"]["slots"][1].update(egg=True, name="Egg", selected=False)
        self.state["bp"] = dict(balance=None, earned=0, spent=0, purchase=None, shop=[])
        await self.open()
        await self.click("Team, BP shop  best 4")
        await self.click("Team: Mudkip")
        self.assertEqual(self.labels, ["* Mudkip L10", "Egg (cannot fight)", "Back"])
        self.assertEqual(self.menu.screen.rows[1].action, 0)

    async def test_an_invitation_can_be_joined_or_declined(self):
        self.state["run"] = dict(run_id="r", mode="frontier", state="forming", players=["b", "a"], names=["Bob", "Alice"], consent=["b"],
                                 round=1, streak=0, ended_reason=None, battle_id=None, next=None)
        await self.open()
        self.assertEqual(self.menu.screen.status, "Bob invites you")
        await self.click("Join the Frontier run")
        self.assertIn("accept", self.calls)
        self.assertEqual(self.menu.screen.status, "Round 1  streak 0")
        await self.click("Retire (keep streak)")
        self.assertIn("Last: Retired, streak 0", self.labels)

    async def test_a_brain_round_is_named_and_a_refusal_is_shown_not_hidden(self):
        self.state["run"] = dict(run_id="r", mode="frontier", state="active", players=["a", "b"], names=["Alice", "Bob"],
                                 consent=["a", "b"], round=7, streak=6, ended_reason=None, battle_id=None,
                                 next=dict(round=7, level=60, label="Tucker & Spenser", brain=True, set=1, prize=4000))
        await self.open()
        self.assertEqual(self.labels[0], "Brain: Tucker & Spenser")
        self.refuse = "Alice: bring at most 3 Pokemon"
        await self.click("Start round 7")
        self.assertEqual(self.menu.screen.status, "Alice: bring at most 3 Pokemon")
        self.assertEqual(self.menu.screen.title, "Battle Frontier")

    async def test_the_league_pages_and_the_hall_of_fame(self):
        await self.menu.refresh()
        await self.click("World and my base")
        await self.click("Frontier and League")
        self.assertEqual(self.labels, ["Battle Frontier", "Pokemon League", "Back to World"])
        await self.click("Pokemon League")
        self.assertEqual(self.menu.screen.title, "Pokemon League")
        self.assertEqual(self.menu.screen.status, "All 8 badges, 1-3 Pokemon")
        await self.click("Challenge the League")
        self.assertIn("propose:league", self.calls)
        self.assertEqual(self.menu.screen.status, "Waiting for Bob")
        self.state["run"].update(state="active", consent=["a", "b"], next=dict(
            round=1, level=0, label="Elite 4 Sidney & Phoebe", brain=False, set=1, prize=4000))
        await self.menu.refresh()
        self.assertEqual(self.menu.screen.status, "Round 1 of 3")
        self.assertEqual(self.labels[:3], ["Elite 4 Sidney & Phoebe", "Prize $4,000, own levels", "Start round 1"])
        self.assertTrue(all(len(label) <= 25 for label in self.labels))
        self.state["league"] = dict(clears=2, best_round=3, rounds=3, first_clear=1.0, last_clear=2.0,
                                    hall=[dict(entry=2, names=["Alice", "Bob"]), dict(entry=1, names=["Cy", "Di"])])
        self.state["run"].update(state="ended", ended_reason="cleared", streak=3)
        await self.menu.refresh()
        self.assertIn("Last: CLEARED, round 3", self.labels)
        self.assertIn("Cleared 2x", self.labels)
        await self.click("Cleared 2x")
        self.assertEqual(self.menu.screen.title, "Hall of Fame")
        self.assertEqual(self.labels[:2], ["#2 Alice & Bob", "#1 Cy & Di"])

    async def test_a_run_of_the_other_ladder_is_pointed_out_not_hidden(self):
        self.state["run"] = dict(run_id="r", mode="league", state="active", players=["a", "b"], names=["Alice", "Bob"],
                                 consent=["a", "b"], round=2, streak=1, ended_reason=None, battle_id=None, next=None)
        await self.menu.refresh()
        await self.click("World and my base")
        await self.click("Frontier and League")
        await self.click("Battle Frontier")
        self.assertEqual(self.menu.screen.status, "A League run is active")
        self.assertIn("Open the League", self.labels)

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
