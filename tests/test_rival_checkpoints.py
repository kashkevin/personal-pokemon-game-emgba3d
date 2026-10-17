"""Update 31: the rival checkpoint coordinator's lobby, battles, completion and recovery.

The native layer is a small fake with the Desk/BattleResults/reservation
surfaces the coordinator reads; ``test_rival_integration`` repeats the key
flows against the real BattleDesk and BattleResults.
"""
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.rival_checkpoints import RivalCheckpoints
from emerald_multiplayer.rival_protocol import validate_rival_reply
from emerald_multiplayer.storage import StorageError

WORLD = "11111111-1111-4111-8111-111111111111"
MAPS = {"route103": (0, 18), "rustboro": (0, 3), "route110": (0, 25), "route119": (0, 34), "lilycove": (0, 5)}
ELSEWHERE = (0, 9)  # Littleroot


class Boom(BaseException):
    pass


@dataclass
class Native:
    battle_id: str
    mode: int
    players: tuple
    sender: str
    state: str = "invited"
    bind_intent: set = field(default_factory=set)
    generation: str = field(default_factory=lambda: str(uuid4()))


class FakeReservations:
    def __init__(self):
        self.reserved, self.terminals = set(), {}

    def contains(self, battle_id):
        return battle_id in self.reserved

    def terminal(self, battle_id):
        return self.terminals.get(battle_id)


@dataclass
class Terminal:
    kind: str


class FakeDesk:
    def __init__(self):
        self._active, self._history = {}, {}
        self.reservations = FakeReservations()
        self.refreshes = 0

    def refresh(self):
        self.refreshes += 1

    def add(self, battle_id, mode, players, sender):
        if any(set(players) & set(b.players) for b in self._active.values()):
            from emerald_multiplayer.battle_desk import BattleError
            raise BattleError("battle_busy", "a participant has an unresolved battle lifecycle")
        self._active[battle_id] = Native(battle_id, mode, tuple(players), sender)

    def archive(self, battle_id, state):
        native = self._active.pop(battle_id)
        native.state = state
        self._history[battle_id] = native


class FakeResults:
    def __init__(self):
        self.rows = {}

    def get(self, battle_id):
        return self.rows.get(battle_id)


def uuid(n):
    return str(UUID(int=n + 1, version=4))


class Harness:
    def __init__(self, test, players=4, **timings):
        self.test = test
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "world.sqlite3.rival-checkpoints.sqlite3"
        self.now = 1000.0
        self.timings = dict(countdown=5, grace=60, solo_wait=120, ready_timeout=180)
        self.timings.update(timings)
        self.players = [uuid(i) for i in range(players)]
        self.names = {p: f"Trainer{i}" for i, p in enumerate(self.players)}
        self.online = set(self.players)
        self.presence = {p: self._at(ELSEWHERE) for p in self.players}
        self.unusable, self.strength = set(), {p: 10 for p in self.players}
        self.desk, self.results = FakeDesk(), FakeResults()
        self.invites = []
        self.open()

    def open(self):
        self.rivals = RivalCheckpoints(self.path, world_id=WORLD, build_id="test-build", ruleset_id="test-rules",
                                       clock=lambda: self.now, **self.timings)

    def restart(self):
        """A host restart: the Desk's memory and the lobby are gone; SQLite and released results remain."""
        self.desk = FakeDesk()
        self.open()

    def close(self):
        self.temp.cleanup()

    @staticmethod
    def _at(map_id, activity="overworld"):
        return dict(map_group=map_id[0], map_number=map_id[1], activity=activity, x=1, y=1)

    def go(self, player, checkpoint_or_map, activity="overworld"):
        target = MAPS.get(checkpoint_or_map, checkpoint_or_map)
        self.presence[self.players[player]] = self._at(target, activity)

    def tick(self, seconds):
        self.now += seconds

    def invite(self, actor):
        def callback(match, battle_id):
            self.invites.append((battle_id, actor, match))
            if match.mode == 2:
                players = tuple(sorted(match.players))
            else:
                own = sorted(next(t for t in match.teams if actor in t))
                other = sorted(next(t for t in match.teams if actor not in t))
                players = (own[0], other[0], own[1], other[1])
            self.desk.add(battle_id, match.mode, players, actor)
        return callback

    def call(self, player, operation, invite=None, **fields):
        actor = self.players[player]
        if actor not in self.online:
            raise ProtocolError("stale_lease", "the real server refuses a disconnected player")
        request = dict(version=1, operation=operation, **fields)
        roster = {p: self.names[p] for p in self.players if p in self.online}
        reply = self.rivals.handle(actor, request, roster=roster,
            presences={p: self.presence[p] for p in roster},
            strengths=lambda p: self.strength[p], usable=lambda p: p not in self.unusable,
            desk=self.desk, results=self.results, invite=invite or self.invite(actor))
        validate_rival_reply(reply, actor, request)
        return reply

    def status(self, player, checkpoint=None):
        reply = self.call(player, "status")
        here = reply["here"]
        if checkpoint is not None:
            self.test.assertIsNotNone(here)
            self.test.assertEqual(here["checkpoint_id"], checkpoint)
        return here

    def vote(self, player, checkpoint, choice="start"):
        return self.call(player, "vote", checkpoint_id=checkpoint, choice=choice)["here"]

    def match(self, player, checkpoint, index=None, attempt=None, invite=None):
        here = self.status(player, checkpoint) if self.presence[self.players[player]]["map_number"] == MAPS[checkpoint][1] \
            else self.call(player, "vote", checkpoint_id=checkpoint, choice="wait")["here"]
        session = here["session"]
        if index is None:
            index = next(m["index"] for m in session["matches"] if m["state"] == "ready")
        public = session["matches"][index]
        return self.call(player, "match", invite=invite, checkpoint_id=checkpoint, session_id=session["session_id"],
                         match=index, attempt=public["attempt"] if attempt is None else attempt)["here"]

    def latest_native(self):
        return self.desk._active[self.invites[-1][0]]

    def play(self, battle_id, outcome):
        """Accept, run and release: the released result appears exactly as BattleResults stores it."""
        native = self.desk._active[battle_id]
        native.state = "running"
        native.bind_intent = set(native.players)
        self.desk.reservations.reserved.add(battle_id)
        self.desk.archive(battle_id, "closed")
        self.results.rows[battle_id] = dict(battle_id=battle_id, mode=native.mode, players=list(native.players),
                                            outcome=outcome, sender=native.sender)

    def decline(self, battle_id):
        self.desk.archive(battle_id, "aborted")

    def start_battle(self, checkpoint, voters):
        for v in voters:
            self.go(v, checkpoint)
        for v in voters:
            self.vote(v, checkpoint)
        self.tick(self.timings["countdown"])
        return self.status(voters[0], checkpoint)

    def summary(self, player):
        return {row["checkpoint_id"]: row for row in self.call(player, "status")["checkpoints"]}

    def table(self, name):
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(f"SELECT * FROM {name}").fetchall()


class RivalTestCase(unittest.TestCase):
    players = 4
    timings = {}

    def setUp(self):
        self.h = Harness(self, self.players, **self.timings)
        self.addCleanup(self.h.close)

    def code(self, code, function, *args, **kwargs):
        with self.assertRaises((ProtocolError, StorageError)) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)


class LobbyTests(RivalTestCase):
    def test_waiting_for_rival_players_alone(self):
        self.h.go(0, "route110")
        here = self.h.status(0, "route110")
        self.assertEqual(here["state"], "open")
        self.assertEqual(here["message"], "Waiting for rival players...")
        self.assertTrue(here["can_start"] and here["can_wait"])
        self.assertFalse(here["can_solo"], "three other trainers are online")
        self.assertEqual(here["others_online"], 3)

    def test_two_start_now_votes_begin_the_countdown_then_a_singles_session(self):
        self.h.go(0, "route110"); self.h.go(1, "route110")
        self.assertEqual(self.h.status(0, "route110")["message"], "Start now or wait for others?")
        self.h.vote(0, "route110")
        here = self.h.vote(1, "route110")
        self.assertEqual(here["state"], "countdown")
        self.assertEqual(here["countdown_ms"], 5000)
        self.assertEqual(here["message"], "Battle starts in 5s")
        self.h.tick(4.9)
        self.assertEqual(self.h.status(0, "route110")["state"], "countdown")
        self.h.tick(0.1)
        here = self.h.status(0, "route110")
        self.assertEqual(here["state"], "battling")
        self.assertEqual(here["session"]["format"], "singles")
        self.assertEqual(here["session"]["matches"][0]["state"], "ready")
        self.assertEqual(here["message"], "Your rival battle is ready")

    def test_start_and_wait_never_starts_with_two_players(self):
        self.h.go(0, "route110"); self.h.go(1, "route110")
        self.h.vote(0, "route110", "start")
        self.h.vote(1, "route110", "wait")
        self.h.tick(10_000)
        here = self.h.status(0, "route110")
        self.assertEqual(here["state"], "open")
        self.assertIsNone(here["session"])

    def test_simultaneous_start_votes_create_one_session(self):
        self.h.go(0, "route110"); self.h.go(1, "route110")
        self.h.vote(0, "route110"); self.h.vote(1, "route110"); self.h.vote(0, "route110"); self.h.vote(1, "route110")
        self.h.tick(5)
        for p in (0, 1, 0, 1):
            self.h.status(p, "route110")
        self.assertEqual(len(self.h.table("sessions")), 1)

    def test_waiters_are_left_out_after_the_grace(self):
        for p in (0, 1, 2):
            self.h.go(p, "route110")
        self.h.vote(0, "route110"); self.h.vote(1, "route110"); self.h.vote(2, "route110", "wait")
        here = self.h.status(0, "route110")
        self.assertEqual(here["state"], "open")
        self.assertEqual(here["grace_ms"], 60000)
        self.assertEqual(here["message"], "Starting without waiters 60s")
        self.h.tick(60)
        self.assertEqual(self.h.status(0, "route110")["state"], "countdown")
        self.h.tick(5)
        session = self.h.status(2, "route110")["session"]
        self.assertEqual(set(session["players"]), {self.h.players[0], self.h.players[1]})

    def test_a_player_joining_during_the_countdown_cancels_it(self):
        self.h.go(0, "route110"); self.h.go(1, "route110")
        self.h.vote(0, "route110"); self.h.vote(1, "route110")
        self.h.tick(3)
        self.h.go(2, "route110")
        self.assertEqual(self.h.status(2, "route110")["state"], "open")
        self.h.vote(2, "route110")
        self.assertEqual(self.h.status(0, "route110")["countdown_ms"], 5000, "a fresh countdown for the new roster")
        self.h.tick(5)
        self.assertEqual(self.h.status(0, "route110")["session"]["format"], "round_robin")

    def test_a_player_leaving_during_the_countdown_cancels_it(self):
        for p in (0, 1, 2):
            self.h.go(p, "route110"); self.h.vote(p, "route110")
        self.h.tick(3)
        self.h.go(2, ELSEWHERE)
        here = self.h.status(0, "route110")
        self.assertEqual(here["state"], "countdown")
        self.assertEqual(here["countdown_ms"], 5000, "the countdown restarted for the two who stayed")
        self.h.tick(5)
        self.assertEqual(self.h.status(0, "route110")["session"]["format"], "singles")

    def test_a_disconnect_during_the_countdown_cancels_it(self):
        self.h.go(0, "route110"); self.h.go(1, "route110")
        self.h.vote(0, "route110"); self.h.vote(1, "route110")
        self.h.online.discard(self.h.players[1])
        self.h.tick(10)
        here = self.h.status(0, "route110")
        self.assertEqual(here["state"], "open")
        self.assertEqual(self.h.table("sessions"), [])

    def test_only_players_standing_at_the_checkpoint_count(self):
        self.h.go(0, "route110")
        for activity in ("battle", "transition", "unavailable"):
            self.h.go(1, "route110", activity)
            self.assertEqual([r["player_id"] for r in self.h.status(0, "route110")["present"]], [self.h.players[0]])
        self.code("rival_not_present", self.h.vote, 2, "route110")
        self.h.go(1, ELSEWHERE)
        self.assertIsNone(self.h.status(1))

    def test_no_usable_pokemon_cannot_start(self):
        self.h.go(0, "route110"); self.h.go(1, "route110")
        self.h.unusable.add(self.h.players[1])
        self.code("rival_no_usable_pokemon", self.h.vote, 1, "route110")
        self.assertFalse(self.h.status(1, "route110")["can_start"])
        self.h.vote(1, "route110", "wait")

    def test_a_party_that_becomes_unusable_before_the_countdown_ends_starts_nothing(self):
        self.h.go(0, "route110"); self.h.go(1, "route110")
        self.h.vote(0, "route110"); self.h.vote(1, "route110")
        self.h.unusable.add(self.h.players[1])
        self.h.tick(5)
        here = self.h.status(0, "route110")
        self.assertEqual(here["state"], "open")
        self.assertEqual(self.h.table("sessions"), [])

    def test_four_players_make_a_balanced_two_versus_two(self):
        self.h.strength.update({self.h.players[0]: 60, self.h.players[1]: 20, self.h.players[2]: 55, self.h.players[3]: 25})
        here = self.h.start_battle("route119", [0, 1, 2, 3])
        session = here["session"]
        self.assertEqual(session["format"], "multi")
        teams = [set(t) for t in session["matches"][0]["teams"]]
        p = self.h.players
        self.assertIn({p[0], p[1]}, teams)
        self.assertIn({p[2], p[3]}, teams)


class BattleTests(RivalTestCase):
    def finish_singles(self, outcome):
        self.h.start_battle("route110", [0, 1])
        here = self.h.match(0, "route110")
        self.assertEqual(here["session"]["matches"][0]["state"], "invited")
        self.assertEqual(here["message"], "Accept it in Challenges")
        battle_id = self.h.invites[-1][0]
        self.assertEqual(self.h.status(1, "route110")["session"]["matches"][0]["state"], "invited")
        self.h.desk._active[battle_id].state = "running"
        self.assertEqual(self.h.status(1, "route110")["session"]["matches"][0]["state"], "playing")
        native_players = self.h.desk._active[battle_id].players
        self.h.play(battle_id, outcome)
        return self.h.status(0, "route110"), native_players

    def test_first_slot_wins(self):
        here, players = self.finish_singles(1)
        self.assertEqual(here["state"], "completed")
        self.assertEqual(here["completion"]["winners"], [players[0]])
        for p in (0, 1):
            self.assertEqual(self.h.summary(p)["route110"], dict(checkpoint_id="route110", completed=True, cleared=True, via="battle"))

    def test_second_slot_wins_and_progression_continues_for_the_loser(self):
        here, players = self.finish_singles(2)
        self.assertEqual(here["completion"]["winners"], [players[1]])
        loser = self.h.players.index(players[0])
        view = self.h.status(loser, "route110")
        self.assertEqual(view["message"], "Good battle! The story goes on")
        self.assertTrue(view["cleared"])
        winner = self.h.players.index(players[1])
        self.assertEqual(self.h.status(winner, "route110")["message"], "You won the rival battle!")

    def test_draw_completes_with_no_winner(self):
        here, _ = self.finish_singles(3)
        self.assertEqual(here["completion"]["winners"], [])
        self.assertEqual(here["message"], "The rival battle was a draw")
        self.assertEqual({(r["wins"], r["losses"], r["draws"]) for r in here["completion"]["standings"]}, {(0, 0, 1)})

    def test_completed_checkpoint_cannot_be_replayed_or_completed_twice(self):
        self.finish_singles(1)
        self.code("rival_completed", self.h.vote, 0, "route110")
        for _ in range(5):
            self.h.status(0, "route110"); self.h.status(1, "route110")
        self.assertEqual(len(self.h.table("completions")), 1)
        self.assertEqual(len(self.h.table("clears")), 2)
        self.assertEqual(len(self.h.invites), 1)

    def test_a_lost_reply_retry_does_not_issue_a_second_battle(self):
        self.h.start_battle("route110", [0, 1])
        here = self.h.match(0, "route110")
        session = here["session"]
        self.h.call(1, "match", checkpoint_id="route110", session_id=session["session_id"], match=0, attempt=0)
        self.assertEqual(len(self.h.invites), 1)
        self.code("rival_not_ready", self.h.call, 1, "match", checkpoint_id="route110",
                  session_id=session["session_id"], match=0, attempt=1)

    def test_only_the_match_trainers_may_issue_it(self):
        self.h.start_battle("route110", [0, 1])
        session = self.h.status(0, "route110")["session"]
        self.h.go(2, "route110")
        self.code("rival_not_participant", self.h.call, 2, "match", checkpoint_id="route110",
                  session_id=session["session_id"], match=0, attempt=0)
        self.code("rival_changed", self.h.call, 0, "match", checkpoint_id="route110",
                  session_id=str(uuid4()), match=0, attempt=0)

    def test_declined_challenge_cancels_the_session_and_reopens_the_lobby(self):
        self.h.start_battle("route110", [0, 1])
        self.h.match(0, "route110")
        self.h.decline(self.h.invites[-1][0])
        here = self.h.status(0, "route110")
        self.assertEqual(here["state"], "open")
        self.assertIsNone(here["session"])
        self.assertEqual(self.h.summary(0)["route110"]["completed"], False)
        here = self.h.start_battle("route110", [0, 1])
        self.assertEqual(here["state"], "battling", "a new session after re-voting")
        self.assertEqual(len(self.h.table("sessions")), 2)

    def test_synchronous_invite_refusal_cancels_the_session_and_reports_the_reason(self):
        from emerald_multiplayer.battle_desk import BattleError
        self.h.start_battle("route110", [0, 1])
        def refuse(match, battle_id):
            raise BattleError("checkpoint_required", "all trainers need a valid owned canonical party")
        self.code("checkpoint_required", self.h.match, 0, "route110", invite=refuse)
        self.assertEqual(self.h.status(0, "route110")["state"], "open")
        self.assertTrue(all(row[3] == "canceled" for row in self.h.table("sessions")))

    def test_disconnect_during_the_battle_waits_for_native_recovery_then_completes(self):
        self.h.start_battle("route110", [0, 1])
        self.h.match(0, "route110")
        battle_id = self.h.invites[-1][0]
        self.h.desk._active[battle_id].state = "running"
        self.h.online.discard(self.h.players[1])
        self.h.tick(3600)
        here = self.h.status(0, "route110")
        self.assertEqual(here["state"], "battling", "a started battle is never voided by a disconnect")
        self.assertEqual(here["session"]["matches"][0]["state"], "playing")
        self.h.online.add(self.h.players[1])
        self.h.play(battle_id, 1)
        self.assertEqual(self.h.status(1, "route110")["state"], "completed")

    def test_recovery_required_stays_waiting_and_never_completes(self):
        self.h.start_battle("route110", [0, 1])
        self.h.match(0, "route110")
        battle_id = self.h.invites[-1][0]
        self.h.desk._active[battle_id].state = "recovery_required"
        for _ in range(3):
            self.h.tick(1000)
            here = self.h.status(0, "route110")
        self.assertEqual(here["session"]["matches"][0]["state"], "waiting")
        self.assertEqual(self.h.table("completions"), [])

    def test_ready_match_nobody_requests_times_out(self):
        self.h.start_battle("route110", [0, 1])
        self.h.tick(179)
        self.assertEqual(self.h.status(0, "route110")["state"], "battling")
        self.h.tick(1)
        self.assertEqual(self.h.status(0, "route110")["state"], "open")

    def test_ready_match_with_an_offline_trainer_is_void(self):
        self.h.start_battle("route110", [0, 1])
        self.h.online.discard(self.h.players[1])
        self.assertEqual(self.h.status(0, "route110")["state"], "open")

    def test_player_cannot_be_in_two_sessions(self):
        self.h.start_battle("route110", [0, 1])
        self.h.go(0, "route119"); self.h.go(2, "route119")
        self.h.vote(0, "route119"); self.h.vote(2, "route119")
        self.h.tick(5)
        self.assertEqual(self.h.status(2, "route119")["state"], "open", "trainer 0 still has a Route 110 session")

    def test_two_versus_two_resolves_by_team(self):
        here = self.h.start_battle("route119", [0, 1, 2, 3])
        self.h.match(0, "route119")
        battle_id = self.h.invites[-1][0]
        native = self.h.desk._active[battle_id]
        self.assertEqual(native.mode, 3)
        self.h.play(battle_id, 2)
        here = self.h.status(3, "route119")
        self.assertEqual(sorted(here["completion"]["winners"]), sorted(native.players[1::2]))
        for row in here["completion"]["standings"]:
            self.assertEqual(row["wins"], int(row["player_id"] in native.players[1::2]))
        self.assertEqual(len(self.h.table("clears")), 4)


class RoundRobinTests(RivalTestCase):
    def setUp(self):
        super().setUp()
        self.session = self.h.start_battle("route110", [0, 1, 2])["session"]
        self.assertEqual(self.session["format"], "round_robin")

    def play_next(self, outcome=1):
        here = self.h.status(0, "route110")
        ready = next(m for m in here["session"]["matches"] if m["state"] == "ready")
        trainer = self.h.players.index(ready["teams"][0][0])
        self.h.match(trainer, "route110", index=ready["index"])
        battle_id = self.h.invites[-1][0]
        players = self.h.desk._active[battle_id].players
        self.h.play(battle_id, outcome)
        return players

    def test_three_matches_in_order_then_one_completion(self):
        winners = [self.play_next(1)[0] for _ in range(3)]
        here = self.h.status(0, "route110")
        self.assertEqual(here["state"], "completed")
        wins = {row["player_id"]: row["wins"] for row in here["completion"]["standings"]}
        self.assertEqual(sum(wins.values()), 3)
        self.assertEqual(sorted(here["completion"]["winners"]),
                         sorted(p for p, w in wins.items() if w == max(wins.values())))
        for row in here["completion"]["standings"]:
            self.assertEqual(row["wins"] + row["losses"] + row["draws"], 2)
        self.assertEqual(len(self.h.table("clears")), 3)
        self.assertEqual(len(winners), 3)

    def test_only_one_match_is_ready_at_a_time(self):
        states = [m["state"] for m in self.h.status(0, "route110")["session"]["matches"]]
        self.assertEqual(states, ["ready", "pending", "pending"])

    def test_a_trainer_leaving_skips_their_remaining_matches(self):
        first = self.play_next(1)
        gone = next(p for p in self.h.players[:3] if p not in first)
        # The next match involves the trainer who has not played yet; they go offline.
        self.h.online.discard(gone)
        here = self.h.status(self.h.players.index(first[0]), "route110")
        self.assertEqual(here["state"], "completed")
        self.assertEqual(sorted(here["completion"]["players"]), sorted(first))
        self.assertEqual(self.h.summary(self.h.players.index(first[0]))["route110"]["via"], "battle")
        self.h.online.add(gone)
        absent = self.h.players.index(gone)
        self.assertFalse(self.h.summary(absent)["route110"]["cleared"])
        self.assertTrue(self.h.status(absent, "route110")["can_catch_up"])

    def test_every_match_void_cancels_the_session(self):
        self.h.online.difference_update(self.h.players[1:3])
        self.h.online.add(self.h.players[1])
        self.h.online.discard(self.h.players[1])
        here = self.h.status(0, "route110")
        self.assertEqual(here["state"], "open")
        self.assertEqual(self.h.table("completions"), [])


class SoloAndCatchUpTests(RivalTestCase):
    def test_solo_when_alone_online(self):
        self.h.online = {self.h.players[0]}
        self.h.go(0, "route110")
        here = self.h.status(0, "route110")
        self.assertTrue(here["can_solo"])
        here = self.h.call(0, "continue", checkpoint_id="route110", via="solo")["here"]
        self.assertTrue(here["cleared"])
        self.assertEqual(here["via"], "solo")
        self.assertEqual(here["state"], "open", "a solo pass never completes the world checkpoint")
        self.assertEqual(self.h.summary(0)["route110"], dict(checkpoint_id="route110", completed=False, cleared=True, via="solo"))
        self.h.call(0, "continue", checkpoint_id="route110", via="solo")
        self.assertEqual(len(self.h.table("clears")), 1)

    def test_solo_after_waiting_alone_while_others_are_elsewhere(self):
        self.h.go(0, "route110")
        self.code("rival_solo_unavailable", self.h.call, 0, "continue", checkpoint_id="route110", via="solo")
        self.h.tick(119)
        self.assertFalse(self.h.status(0, "route110")["can_solo"])
        self.h.tick(1)
        self.assertTrue(self.h.status(0, "route110")["can_solo"])

    def test_solo_is_refused_while_another_player_is_present(self):
        self.h.online = {self.h.players[0], self.h.players[1]}
        self.h.go(0, "route110"); self.h.go(1, "route110")
        self.h.tick(1000)
        self.code("rival_solo_unavailable", self.h.call, 0, "continue", checkpoint_id="route110", via="solo")

    def test_catch_up_only_after_the_world_completed(self):
        self.code("rival_not_completed", self.h.call, 3, "continue", checkpoint_id="route110", via="catch_up")
        self.h.start_battle("route110", [0, 1])
        self.h.match(0, "route110")
        self.h.play(self.h.invites[-1][0], 1)
        self.h.go(3, "route110")
        here = self.h.status(3, "route110")
        self.assertTrue(here["can_catch_up"])
        self.assertEqual(here["message"], "Completed - you may continue")
        self.assertFalse(here["can_start"])
        here = self.h.call(3, "continue", checkpoint_id="route110", via="catch_up")["here"]
        self.assertEqual(here["via"], "catch_up")
        self.assertFalse(here["can_catch_up"])
        self.h.call(3, "continue", checkpoint_id="route110", via="catch_up")
        self.assertEqual(len(self.h.table("clears")), 3)
        self.assertEqual(len(self.h.table("completions")), 1)

    def test_catch_up_does_not_require_standing_at_the_checkpoint(self):
        self.h.start_battle("route110", [0, 1])
        self.h.match(0, "route110")
        self.h.play(self.h.invites[-1][0], 2)
        self.h.call(2, "continue", checkpoint_id="route110", via="catch_up")
        self.assertTrue(self.h.summary(2)["route110"]["cleared"])

    def test_a_held_battle_that_never_resolves_does_not_strand_the_others(self):
        self.h.start_battle("route110", [0, 1])
        self.h.match(0, "route110")
        battle_id = self.h.invites[-1][0]
        self.h.desk._active[battle_id].state = "recovery_required"   # held: never voided, never completed
        self.h.go(2, "route110")
        self.assertFalse(self.h.status(2, "route110")["can_solo"])
        self.code("rival_solo_unavailable", self.h.call, 2, "continue", checkpoint_id="route110", via="solo")
        self.h.tick(120)
        here = self.h.status(2, "route110")
        self.assertTrue(here["can_solo"])
        self.h.call(2, "continue", checkpoint_id="route110", via="solo")
        self.assertEqual(self.h.summary(2)["route110"]["via"], "solo")
        # The held battle's own trainers never get the escape: their battle recovery owns them.
        self.assertFalse(self.h.status(0, "route110")["can_solo"])
        self.code("rival_solo_unavailable", self.h.call, 1, "continue", checkpoint_id="route110", via="solo")
        self.assertEqual(self.h.table("completions"), [])
        self.assertEqual(self.h.status(0, "route110")["session"]["matches"][0]["state"], "waiting")

    def test_a_progressing_battle_does_not_offer_the_escape(self):
        self.h.start_battle("route110", [0, 1])
        self.h.match(0, "route110")
        self.h.desk._active[self.h.invites[-1][0]].state = "running"
        self.h.go(2, "route110")
        self.h.tick(10_000)
        self.assertFalse(self.h.status(2, "route110")["can_solo"])


class PersistenceTests(RivalTestCase):
    def test_restart_keeps_completion_and_clears_and_drops_votes(self):
        self.h.start_battle("route110", [0, 1])
        self.h.match(0, "route110")
        self.h.play(self.h.invites[-1][0], 1)
        self.h.go(2, "route119"); self.h.go(3, "route119")
        self.h.vote(2, "route119")
        self.h.restart()
        self.assertTrue(self.h.summary(0)["route110"]["completed"])
        self.assertEqual(self.h.status(2, "route119")["present"][0]["vote"], None)

    def test_restart_with_a_dispatched_battle_and_no_reservation_voids_it(self):
        self.h.start_battle("route110", [0, 1])
        self.h.match(0, "route110")
        self.h.restart()  # the Desk's memory is gone; no BIND was ever reserved
        self.assertEqual(self.h.status(0, "route110")["state"], "open")

    def test_restart_with_a_reserved_battle_stays_waiting(self):
        self.h.start_battle("route110", [0, 1])
        self.h.match(0, "route110")
        battle_id = self.h.invites[-1][0]
        reservations = self.h.desk.reservations
        reservations.reserved.add(battle_id)
        self.h.restart()
        self.h.desk.reservations = reservations
        here = self.h.status(0, "route110")
        self.assertEqual(here["session"]["matches"][0]["state"], "waiting")
        reservations.terminals[battle_id] = Terminal("aborted")
        self.assertEqual(self.h.status(0, "route110")["state"], "open")

    def test_a_result_released_while_the_host_was_down_completes_after_restart(self):
        self.h.start_battle("route110", [0, 1])
        self.h.match(0, "route110")
        battle_id = self.h.invites[-1][0]
        self.h.play(battle_id, 1)
        self.h.restart()
        self.assertEqual(self.h.status(1, "route110")["state"], "completed")

    def test_crash_before_dispatch_is_recovered_without_a_battle(self):
        self.h.start_battle("route110", [0, 1])
        with patch.object(self.h.rivals, "_dispatch", side_effect=Boom):
            with self.assertRaises(Boom):
                self.h.match(0, "route110")
        reservations = self.h.desk.reservations
        reservations.reserved.add("unrelated")
        self.h.restart()
        self.h.desk.reservations = reservations
        here = self.h.status(0, "route110")
        self.assertIn(here["state"], {"battling", "open"})
        self.assertEqual(self.h.invites, [])
        self.assertEqual(self.h.table("completions"), [])

    def test_recover_cancels_a_pending_intent_when_provisional_admission_exists(self):
        class Admission:
            revoked = []
            def unentered_terminal(self, battle_id, revoke=False):
                if revoke:
                    self.revoked.append(battle_id)
                return None
            def terminal(self, battle_id):
                return None
        admission = Admission()
        handle = self.h.rivals.handle
        self.h.rivals.handle = lambda *a, **k: handle(*a, **dict(k, admission=admission))
        self.h.start_battle("route110", [0, 1])
        with patch.object(self.h.rivals, "_dispatch", side_effect=Boom):
            with self.assertRaises(Boom):
                self.h.match(0, "route110")
        # With the provisional-admission ledger a missing reservation proves nothing: it stays waiting.
        session = self.h.status(0, "route110")["session"]
        match = session["matches"][0]
        self.assertEqual(match["state"], "waiting")
        here = self.h.call(0, "recover", checkpoint_id="route110", session_id=session["session_id"], match=0,
                           attempt=match["attempt"], battle_id=match["battle_id"])["here"]
        self.assertEqual(here["state"], "open")
        self.assertEqual(self.h.invites, [])
        self.assertEqual(admission.revoked, [], "the issuance fence alone proves it never ran")

    def test_recover_of_a_dispatched_intent_asks_the_admission_ledger(self):
        class Admission:
            def __init__(self):
                self.revoked, self.aborted = [], set()
            def unentered_terminal(self, battle_id, revoke=False):
                if revoke:
                    self.revoked.append(battle_id)
                    self.aborted.add(battle_id)
                return Terminal("aborted") if battle_id in self.aborted else None
            def terminal(self, battle_id):
                return None
        admission = Admission()
        handle = self.h.rivals.handle
        self.h.rivals.handle = lambda *a, **k: handle(*a, **dict(k, admission=admission))
        self.h.start_battle("route110", [0, 1])
        self.h.match(0, "route110")
        self.h.restart()
        handle = self.h.rivals.handle
        self.h.rivals.handle = lambda *a, **k: handle(*a, **dict(k, admission=admission))
        session = self.h.status(0, "route110")["session"]
        match = session["matches"][0]
        self.assertEqual(match["state"], "waiting", "uncertain after a restart: never voided automatically")
        here = self.h.call(1, "recover", checkpoint_id="route110", session_id=session["session_id"], match=0,
                           attempt=match["attempt"], battle_id=match["battle_id"])["here"]
        self.assertEqual(admission.revoked, [match["battle_id"]])
        self.assertEqual(here["state"], "open")

    def test_corruption_fails_closed(self):
        self.h.start_battle("route110", [0, 1])
        with closing(sqlite3.connect(self.h.path)) as connection:
            connection.execute("UPDATE sessions SET sha256 = ?", ("0" * 64,))
            connection.commit()
        with self.assertRaises(StorageError) as caught:
            self.h.open()
        self.assertEqual(caught.exception.code, "rival_invalid")

    def test_foreign_world_is_refused(self):
        with self.assertRaises(StorageError):
            RivalCheckpoints(self.h.path, world_id=str(uuid4()), build_id="test-build", ruleset_id="test-rules")

    def test_unknown_schema_is_refused(self):
        with closing(sqlite3.connect(self.h.path)) as connection:
            connection.execute("CREATE TABLE extra (x)")
            connection.commit()
        with self.assertRaises(StorageError):
            self.h.open()


class RandomisedInvariantTests(unittest.TestCase):
    """Seeded random event sequences; the invariants are checked after every step."""

    def check(self, h):
        sessions = h.table("sessions")
        completions = h.table("completions")
        clears = h.table("clears")
        active = [row for row in sessions if row[3] == "active"]
        self.assertEqual(len({row[2] for row in active}), len(active), "two active sessions at one checkpoint")
        self.assertEqual(len({row[0] for row in completions}), len(completions))
        completed_sessions = {row[1] for row in completions}
        self.assertTrue(completed_sessions <= {row[1] for row in sessions if row[3] == "completed"})
        import json
        resolved_players = {}
        for row in sessions:
            record = json.loads(row[4])
            if row[3] == "completed":
                self.assertIn(row[1], completed_sessions)
                resolved = [m for m in record["matches"] if m["state"] == "resolved"]
                self.assertTrue(resolved, "completed without a released result")
                for m in resolved:
                    self.assertIn(m["battle_id"], h.results.rows)
                resolved_players[row[2]] = {p for m in resolved for t in m["teams"] for p in t}
        for checkpoint_id, player, via, *_ in clears:
            if via == "battle":
                self.assertIn(player, resolved_players.get(checkpoint_id, set()))
            if via == "catch_up":
                self.assertIn(checkpoint_id, {row[0] for row in completions})

    def test_random_sessions(self):
        import json
        coverage = dict(completed=0, canceled=0, formats=set(), catch_up=0, solo=0, void=0)
        actions = (["move"] * 12 + ["vote"] * 30 + ["tick"] * 14 + ["match"] * 18 + ["native"] * 12
                   + ["online"] * 5 + ["continue"] * 6 + ["restart"] * 3 + ["gather"] * 3)
        # RIVAL_SOAK_SEEDS / RIVAL_SOAK_STEPS lengthen the walk for a soak run (defaults: 24 seeds of 260 steps).
        import os
        seeds, steps = int(os.environ.get("RIVAL_SOAK_SEEDS", 24)), int(os.environ.get("RIVAL_SOAK_STEPS", 260))
        for seed in range(seeds):
            rng = random.Random(seed)
            h = Harness(self, 4)
            try:
                for _ in range(steps):
                    p = rng.randrange(4)
                    player = h.players[p]
                    action = rng.choice(actions)
                    try:
                        if action == "move":
                            h.go(p, rng.choice(["route110"] * 6 + ["route119"] * 2 + [ELSEWHERE]))
                        elif action == "gather":
                            for q in range(4):
                                h.go(q, "route110")
                        elif action == "vote":
                            here = h.status(p)
                            if here is not None:
                                h.vote(p, here["checkpoint_id"], rng.choice(["start"] * 4 + ["wait"]))
                        elif action == "online":
                            (h.online.discard if player in h.online else h.online.add)(player)
                        elif action == "tick":
                            h.tick(rng.choice([1, 5, 5, 60, 200]))
                        elif action == "match":
                            here = h.status(p)
                            if here and here["session"] and here["state"] == "battling":
                                ready = [m for m in here["session"]["matches"] if m["state"] == "ready"
                                         and player in sum(m["teams"], [])]
                                if ready:
                                    h.match(p, here["checkpoint_id"], index=ready[0]["index"])
                        elif action == "native" and h.desk._active:
                            battle_id = rng.choice(sorted(h.desk._active))
                            if rng.random() < 0.75:
                                h.play(battle_id, rng.choice([1, 2, 3]))
                            else:
                                h.decline(battle_id)
                        elif action == "continue":
                            here = h.status(p)
                            if here:
                                h.call(p, "continue", checkpoint_id=here["checkpoint_id"],
                                       via=rng.choice(["solo", "catch_up"]))
                        elif action == "restart":
                            h.restart()
                    except (ProtocolError, StorageError) as error:
                        self.assertNotEqual(getattr(error, "code", ""), "rival_invalid", error)
                    self.check(h)
                for row in h.table("sessions"):
                    record = json.loads(row[4])
                    coverage["formats"].add(record["format"])
                    coverage["completed"] += row[3] == "completed"
                    coverage["canceled"] += row[3] == "canceled"
                    coverage["void"] += sum(m["state"] == "void" for m in record["matches"])
                for row in h.table("clears"):
                    coverage[row[2]] = coverage.get(row[2], 0) + 1
            finally:
                h.close()
        # The random walk must actually reach the interesting states, or it proves nothing.
        self.assertGreaterEqual(coverage["completed"], 5, coverage)
        self.assertGreaterEqual(coverage["canceled"], 3, coverage)
        self.assertGreaterEqual(coverage["void"], 3, coverage)
        self.assertEqual({"singles", "round_robin", "multi"}, coverage["formats"], coverage)
        self.assertGreaterEqual(coverage["catch_up"] + coverage["solo"], 1, coverage)


if __name__ == "__main__":
    unittest.main()
