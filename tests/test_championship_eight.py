"""Step 18: eight-place Championships with computer trainers (championship8.py, championship8_protocol.py)."""
from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from emerald_multiplayer import tower_data
from emerald_multiplayer.championship import Championships
from emerald_multiplayer.championship8 import (CONNECTION_SECONDS, ISSUED_SECONDS, STARTED_SECONDS, ComputerContext,
                                               EightChampionships, computer_places)
from emerald_multiplayer.championship8_protocol import (VERSION, four_player_view, validate_championship_reply,
                                                        validate_championship_view)
from emerald_multiplayer.championship_protocol import VERSION as FOUR_VERSION
from emerald_multiplayer.frontier_rules import LEGENDARY, PartyMember, check_party
from emerald_multiplayer.menu_mailbox import TowerCommand
from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.storage import StorageError


class Desk:
    """The native battle desk as the bracket reads it: no live challenge unless a test puts one there."""

    def __init__(self):
        self._active, self._history, self.reservations, self.invited = {}, {}, None, []

    def refresh(self):
        pass


class Results:
    def __init__(self):
        self.released = {}

    def get(self, battle_id):
        return self.released.get(battle_id)


class Fixture:
    """A world's eight-place sidecar, four connected players and a host that can fight computer matches."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = tower_data.load()
        self.world = str(uuid4())
        self.clock = [10_000]
        self.players = [str(uuid4()) for _ in range(4)]
        self.roster = {player: name for player, name in zip(self.players, ("Kevin", "Sam", "Alex", "Robin"))}
        self.levels = dict(zip(self.players, (40, 20, 35, 30)))
        self.desk, self.results = Desk(), Results()
        self.busy, self.connected, self.taken = {}, {}, set()
        self.checked = []
        self.store = self.open()

    def open(self, legacy=None):
        return EightChampionships(Path(self.directory.name) / "w.championships8.sqlite3", world_id=self.world,
                                  build_id="build-1", ruleset_id="rules-1", legacy=legacy, clock=lambda: self.clock[0])

    def context(self, experience=False):
        return ComputerContext(data=self.data, busy=lambda player: self.busy.get(player),
                               taken=lambda number: number in self.taken,
                               connected_for=lambda player: self.connected.get(player, 3600.0), experience=experience)

    def eligibility(self, players, rule):
        self.checked.append((tuple(players), rule))

    def call(self, actor, operation, store=None, computers="default", rule="open", invite=None, **fields):
        request = dict(version=VERSION, operation=operation, **fields)
        reply = (store or self.store).handle(
            actor, request, roster=self.roster, desk=self.desk, results=self.results,
            invite=invite or (lambda battle_id, peer: self.desk.invited.append((battle_id, peer))),
            eligibility=self.eligibility, rule=rule, strengths=self.levels.get,
            computers=self.context() if computers == "default" else computers)
        validate_championship_reply(reply, actor, request)
        return reply

    def ids(self, view):
        return dict(championship_id=view["championship_id"], generation=view["generation"],
                    fingerprint=view["fingerprint"])

    def create(self, players, rule="open"):
        view = self.call(players[0], "create", championship_id=str(uuid4()), players=players, rule=rule)["current"]
        for player in players[1:]:
            view = self.call(player, "accept", **self.ids(view))["current"]
        return view

    def match(self, actor, view, index, store=None):
        current = self.call(actor, "status", store=store)["current"]
        attempt = current["matches"][index]["attempt"]
        return self.call(actor, "match", store=store, round=index, attempt=attempt, **self.ids(current))

    def play(self, actor, view, index, outcome, store=None):
        reply = self.match(actor, view, index, store=store)
        command = reply["command"]
        store = store or self.store
        self.assertEqual(store.computer_result(actor, command["ticket"], command["floor"], "started")["state"], "started")
        result = store.computer_result(actor, command["ticket"], command["floor"], outcome)
        self.assertTrue(result["settled"])
        return command, self.bracket(actor, reply["current"]["championship_id"], store)

    def bracket(self, actor, championship_id, store=None):
        """The bracket as it stands, also once it has ended (status shows only a running one, as before)."""
        store = store or self.store
        with store._transaction() as connection:
            row = connection.execute("SELECT * FROM brackets WHERE championship_id=?", (championship_id,)).fetchone()
            return store._bracket(row)

class EightChampionshipTests(Fixture, unittest.TestCase):
    # ------------------------------------------------------------ the places
    def test_computer_places_follow_the_rule_and_spread_between_the_players(self):
        self.assertEqual(computer_places(self.data, "open", [40, 20], 6, check_party), [40, 36, 32, 28, 24, 20])
        self.assertEqual(computer_places(self.data, "open", [45, 50, 46, 47], 4, check_party), [50, 48, 47, 45])
        level30 = computer_places(self.data, "level_30", [30, 30], 6, check_party)
        self.assertEqual(level30, [30, 29, 28, 27, 26, 25])
        for rule in ("no_legendaries", "item_clause", "species_clause", "level_50"):
            for floor in computer_places(self.data, rule, [100, 1], 6, check_party):
                mons = self.data.floor(floor)["solo"]["mons"]
                members = [PartyMember(m["speciesId"], m["level"], m["itemId"] or 0) for m in mons]
                self.assertIsNone(check_party(rule, members), (rule, floor))
        legendary = [entry["floor"] for entry in self.data.floors
                     if any(m["speciesId"] in LEGENDARY for m in entry["solo"]["mons"])]
        self.assertTrue(legendary)
        self.assertFalse(set(computer_places(self.data, "no_legendaries", [100, 100], 6, check_party)) & set(legendary))
        # Unknown strengths (an unreadable save) count as level 1.
        self.assertEqual(computer_places(self.data, "open", [0, 0], 4, check_party), [4, 3, 2, 1])

    def test_two_players_and_six_computer_trainers(self):
        players = self.players[:2]
        view = self.call(players[0], "create", championship_id=str(uuid4()), players=players)["current"]
        self.assertEqual(view["format"], 8)
        self.assertEqual(view["state"], "proposed")
        self.assertEqual([e["player"] for e in view["entrants"][:2]], players)
        self.assertEqual([e["floor"] for e in view["entrants"][2:]], [40, 36, 32, 28, 24, 20])
        self.assertEqual(view["entrants"][2]["name"], self.data.trainer(40).split(" ")[-1])
        self.assertEqual([m["seeds"] for m in view["matches"][:4]], [[0, 7], [3, 4], [1, 6], [2, 5]])
        self.assertEqual([m["kind"] for m in view["matches"]], ["computer", "auto", "computer", "auto", None, None, None])
        self.assertTrue(all(m["state"] in ("ready", "blocked") and m["winner"] is None for m in view["matches"]))
        self.assertEqual(self.checked, [(tuple(players), "open")])
        view = self.call(players[1], "accept", **self.ids(view))["current"]
        self.assertEqual(view["state"], "active")
        # Two computer trainers: the higher seed goes on at once, without a battle.
        self.assertEqual([(m["state"], m["winner"]) for m in view["matches"][:4]],
                         [("ready", None), ("won", 3), ("ready", None), ("won", 2)])

    def test_four_players_hold_the_first_places(self):
        view = self.create(self.players, rule="level_50")
        self.assertEqual(view["rule"], "level_50")
        self.assertEqual(view["players"], self.players)
        self.assertEqual([e["player"] for e in view["entrants"][:4]], self.players)
        self.assertEqual(all(e["player"] is None for e in view["entrants"][4:]), True)
        self.assertEqual([m["kind"] for m in view["matches"][:4]], ["computer"] * 4)
        floors = [e["floor"] for e in view["entrants"][4:]]
        self.assertEqual(floors, sorted(floors, reverse=True))
        self.assertTrue(all(floor <= 50 for floor in floors))

    def test_create_is_refused_without_connection_proposer_or_game(self):
        with self.assertRaises(ProtocolError) as refused:
            self.call(self.players[1], "create", championship_id=str(uuid4()), players=self.players[:2])
        self.assertEqual(refused.exception.code, "championship_invalid")
        stranger = str(uuid4())
        with self.assertRaises(ProtocolError) as refused:
            self.call(self.players[0], "create", championship_id=str(uuid4()), players=[self.players[0], stranger])
        self.assertEqual(refused.exception.code, "championship_roster_changed")
        with self.assertRaises(ProtocolError) as refused:     # no computer matches and no four players' sidecar
            self.call(self.players[0], "create", computers=None, championship_id=str(uuid4()), players=self.players)
        self.assertEqual(refused.exception.code, "championship_unavailable")
        with self.assertRaises(ProtocolError) as refused:
            self.call(self.players[0], "create", championship_id=str(uuid4()), players=self.players[:1])
        self.assertEqual(refused.exception.code, "invalid_field")

    # ------------------------------------------------------ computer matches
    def test_a_computer_match_from_ticket_to_result(self):
        view = self.create(self.players[:2])
        first = self.players[0]
        with self.assertRaises(ProtocolError):
            self.match(self.players[1], view, 0)        # not this player's match
        reply = self.match(first, view, 0)
        command = reply["command"]
        match = reply["current"]["matches"][0]
        self.assertEqual((match["state"], match["attempt"], match["ticket"]), ("invited", 1, command["ticket"]))
        self.assertEqual((command["floor"], command["round"], command["flags"], command["table_hash"]),
                         (20, 1, 0, self.data.table_hash))
        self.assertTrue(command["ticket"] & 0xFF)
        packed = TowerCommand(command["ticket"], command["table_hash"], command["floor"], 2, command["round"],
                              command["flags"]).pack()
        self.assertEqual(TowerCommand.unpack(packed).round, 1)
        # One Tower battle at a time: the Tower asks the Championship.
        self.assertEqual(self.store.computer_busy(first), "Finish your Championship match")
        self.assertIsNone(self.store.computer_busy(self.players[1]))
        # The answer was lost: asking again gives the same ticket (its 120 s renewed), never a second one.
        self.clock[0] += 100
        again = self.call(first, "match", round=0, attempt=0, **self.ids(reply["current"]))
        self.assertEqual(again["command"], command)
        self.clock[0] += 100                            # 200 s after the first command, 100 after the renewal
        self.assertEqual(self.call(first, "status")["current"]["matches"][0]["state"], "invited")
        # Someone else's report, or the wrong floor, changes nothing.
        self.assertEqual(self.store.computer_result(self.players[1], command["ticket"], 20, "won")["state"], "issued")
        self.assertEqual(self.store.computer_result(first, command["ticket"], 21, "won")["state"], "issued")
        self.assertIsNone(self.store.computer_result(first, command["ticket"] ^ 0x100, 20, "won"))
        self.assertEqual(self.store.computer_result(first, command["ticket"], 20, "started")["state"], "started")
        self.assertEqual(self.call(first, "status")["current"]["matches"][0]["state"], "playing")
        result = self.store.computer_result(first, command["ticket"], 20, "won")
        self.assertEqual((result["state"], result["settled"], result["won"], result["stage"]), ("won", True, True, 1))
        # A repeated or contradicting report changes nothing.
        self.assertFalse(self.store.computer_result(first, command["ticket"], 20, "lost")["settled"])
        view = self.call(first, "status")["current"]
        self.assertEqual((view["matches"][0]["state"], view["matches"][0]["winner"]), ("won", 0))
        self.assertIsNone(self.store.computer_busy(first))
        # The semifinal's places follow: the first player and the auto quarterfinal's winner (seed 3).
        self.assertEqual((view["matches"][4]["seeds"], view["matches"][4]["kind"]), ([0, 3], "computer"))
        self.assertEqual(self.checked[-1], ((first,), "open"))

    def test_a_loss_draw_refusal_and_expiry(self):
        view = self.create(self.players[:2])
        first, second = self.players[:2]
        _, view = self.play(second, view, 2, "drew")
        self.assertEqual(view["matches"][2]["state"], "draw")
        drawn = view["matches"][2]["ticket"]
        command, view = self.play(second, view, 2, "lost")
        self.assertNotEqual(command["ticket"], drawn)
        self.assertEqual((view["matches"][2]["state"], view["matches"][2]["winner"], view["matches"][2]["attempt"]),
                         ("won", 6, 2))
        # Refused by the game: the match can be asked for again.
        reply = self.match(first, view, 0)
        command = reply["command"]
        self.assertEqual(self.store.computer_result(first, command["ticket"], 20, "refused")["state"], "void")
        self.assertEqual(self.call(first, "status")["current"]["matches"][0]["state"], "canceled")
        # Never started: void 120 s after the command.
        reply = self.match(first, view, 0)
        self.clock[0] += ISSUED_SECONDS
        view = self.call(first, "status")["current"]
        self.assertEqual((view["matches"][0]["state"], view["matches"][0]["attempt"]), ("canceled", 2))
        late = self.store.computer_result(first, reply["command"]["ticket"], 20, "started")
        self.assertEqual(late["state"], "void")          # a battle the host voided never counts
        self.assertEqual(self.call(first, "status")["current"]["matches"][0]["state"], "canceled")

    def test_a_started_match_that_never_reports(self):
        view = self.create(self.players[:2])
        first = self.players[0]
        reply = self.match(first, view, 0)
        command = reply["command"]
        self.store.computer_result(first, command["ticket"], 20, "started")
        self.connected[first] = CONNECTION_SECONDS - 1    # the game just connected: its kept result may still come
        with self.assertRaises(ProtocolError) as refused:
            self.match(first, view, 0)
        self.assertEqual(refused.exception.code, "championship_result_pending")
        self.connected[first] = CONNECTION_SECONDS
        view = self.match(first, view, 0)["current"]
        self.assertEqual((view["matches"][0]["state"], view["matches"][0]["winner"]), ("won", 7))   # a loss
        self.assertFalse(self.store.computer_result(first, command["ticket"], 20, "won")["settled"])
        # The other player's started match: a loss after 24 hours.
        second = self.players[1]
        reply = self.match(second, view, 2)
        self.store.computer_result(second, reply["command"]["ticket"], 24, "started")
        self.clock[0] += STARTED_SECONDS
        view = self.call(second, "status")["current"]
        self.assertEqual((view["matches"][2]["state"], view["matches"][2]["winner"]), ("won", 6))

    def test_busy_game_and_rule_are_checked_before_a_ticket(self):
        view = self.create(self.players[:2], rule="level_50")
        first = self.players[0]
        self.busy[first] = "Finish your Tower battle first"
        with self.assertRaises(ProtocolError) as refused:
            self.match(first, view, 0)
        self.assertEqual((refused.exception.code, refused.exception.message),
                         ("championship_busy", "Finish your Tower battle first"))
        self.assertEqual(self.call(first, "status")["current"]["matches"][0]["attempt"], 0)
        del self.busy[first]

        def ineligible(players, rule):
            self.assertEqual(rule, "level_50")          # the bracket's own rule, whatever today's is
            raise ProtocolError("championship_ineligible", "Kevin: Over level 50")
        reply = None
        try:
            self.store.handle(first, dict(version=VERSION, operation="match", round=0, attempt=0, **self.ids(view)),
                              roster=self.roster, desk=self.desk, results=self.results, invite=None,
                              eligibility=ineligible, rule="open", strengths=self.levels.get, computers=self.context())
        except ProtocolError as error:
            reply = error.code
        self.assertEqual(reply, "championship_ineligible")
        # A ticket number the Tower already used is never issued.
        reply = self.match(first, view, 0)
        self.assertNotIn(reply["command"]["ticket"], self.taken)

    def test_experience_flag_reaches_the_command(self):
        view = self.create(self.players[:2])
        current = self.call(self.players[0], "status")["current"]
        request = dict(version=VERSION, operation="match", round=0, attempt=0, **self.ids(current))
        reply = self.store.handle(self.players[0], request, roster=self.roster, desk=self.desk, results=self.results,
                                  invite=None, eligibility=self.eligibility, strengths=self.levels.get,
                                  computers=self.context(experience=True))
        self.assertEqual(reply["command"]["flags"], 1)

    # ---------------------------------------------------------- to the final
    def test_a_player_wins_the_championship(self):
        first, second = self.players[:2]
        view = self.create([first, second])
        _, view = self.play(first, view, 0, "won")
        _, view = self.play(second, view, 2, "won")
        self.assertEqual([m["seeds"] for m in view["matches"][4:6]], [[0, 3], [1, 2]])
        _, view = self.play(first, view, 4, "won")
        _, view = self.play(second, view, 5, "won")
        # The final between the two players is the native challenge.
        self.assertEqual((view["matches"][6]["seeds"], view["matches"][6]["kind"]), ([0, 1], "players"))
        reply = self.match(first, view, 6)
        self.assertNotIn("command", reply)
        battle_id = reply["current"]["matches"][6]["battle_id"]
        self.assertEqual(self.desk.invited, [(battle_id, second)])
        self.assertEqual(reply["current"]["matches"][6]["state"], "waiting")
        self.results.released[battle_id] = dict(mode=2, players=[first, second], battle_id=battle_id, sender=first,
                                                generation=str(uuid4()), outcome=2, fingerprint="f" * 64)
        view = self.call(first, "status")["current"]
        self.assertEqual((view["state"], view["champion"], view["matches"][6]["winner"]), ("completed", 1, 1))
        self.assertEqual(self.store.statistics(second), dict(entries=1, completed=1, wins=1))
        self.assertEqual(self.store.statistics(first), dict(entries=1, completed=1, wins=0))
        history = self.call(first, "history")["history"]
        self.assertEqual([(h["format"], h["champion"], h["champion_name"], h["state"]) for h in history],
                         [(8, second, "Sam", "completed")])

    def test_a_computer_trainer_can_win(self):
        first, second = self.players[:2]
        view = self.create([first, second])
        _, view = self.play(first, view, 0, "lost")
        _, view = self.play(second, view, 2, "lost")
        # Every player is out: the rest is decided without a battle, the highest seeds going on.
        self.assertIsNone(self.call(first, "status")["current"])
        self.assertEqual(view["state"], "completed")
        self.assertEqual([m["winner"] for m in view["matches"][4:]], [3, 2, 2])
        self.assertEqual(view["champion"], 2)
        self.assertEqual(self.store.statistics(first), dict(entries=1, completed=1, wins=0))
        summary = self.call(first, "history")["history"][0]
        self.assertEqual((summary["champion"], summary["champion_name"]), (None, view["entrants"][2]["name"]))

    def test_cancel(self):
        view = self.call(self.players[0], "create", championship_id=str(uuid4()), players=self.players[:2])["current"]
        view = self.call(self.players[1], "cancel", **self.ids(view))["current"]
        self.assertEqual(view["state"], "canceled")
        view = self.create(self.players[:2])
        reply = self.match(self.players[0], view, 0)
        view = self.call(self.players[0], "cancel", **self.ids(reply["current"]))["current"]
        view = self.call(self.players[1], "cancel", **self.ids(view))["current"]
        self.assertEqual(view["state"], "active")          # a computer match's command is out
        self.store.computer_result(self.players[0], reply["command"]["ticket"], 20, "refused")
        self.assertIsNone(self.call(self.players[0], "status")["current"])
        self.assertEqual(self.bracket(self.players[0], view["championship_id"])["state"], "canceled")
        # The proposal canceled before every player accepted is no entry (as in the four players' bracket).
        self.assertEqual(self.store.statistics(self.players[0]), dict(entries=1, completed=0, wins=0))

    # ------------------------------------------------------------ durability
    def test_restart_keeps_every_record_and_refuses_tampering(self):
        view = self.create(self.players[:3])
        command, view = self.play(self.players[0], view, 0, "won")
        reopened = self.open()
        again = self.call(self.players[0], "status", store=reopened)["current"]
        self.assertEqual(again, view)
        self.assertTrue(reopened.computer_ticket(command["ticket"]))
        with sqlite3.connect(Path(self.directory.name) / "w.championships8.sqlite3") as connection:
            connection.execute("UPDATE brackets SET record=replace(record, '\"rule\":\"open\"', '\"rule\":\"level_30\"')")
        with self.assertRaises(StorageError):
            self.open()

    def test_one_bracket_at_a_time(self):
        self.create(self.players[:2])
        with self.assertRaises(ProtocolError) as refused:
            self.call(self.players[2], "create", championship_id=str(uuid4()), players=self.players[2:])
        self.assertEqual(refused.exception.code, "championship_busy")

    # ---------------------------------------- the four players' bracket of before
    def test_the_four_players_bracket_stays_playable_and_counted(self):
        legacy = Championships(Path(self.directory.name) / "w.championships.sqlite3", world_id=self.world,
                               build_id="build-1", ruleset_id="rules-1")
        store = self.open(legacy=legacy)
        older = legacy.handle(self.players[0], dict(version=FOUR_VERSION, operation="create",
                              championship_id=str(uuid4()), players=self.players), roster=self.roster, desk=self.desk,
                              results=self.results, invite=None)["current"]
        # Version 2 shows it in its own shape and plays it on.
        view = self.call(self.players[1], "status", store=store)["current"]
        self.assertEqual((view["format"], view["championship_id"], view["state"]), (4, older["championship_id"], "proposed"))
        self.assertEqual(view, four_player_view(older))
        for player in self.players[1:]:
            view = self.call(player, "accept", store=store, **self.ids(view))["current"]
        self.assertEqual((view["format"], view["state"]), (4, "active"))
        # ... and no eight-place bracket starts beside it.
        with self.assertRaises(ProtocolError) as refused:
            self.call(self.players[0], "create", store=store, championship_id=str(uuid4()), players=self.players[:2])
        self.assertEqual(refused.exception.code, "championship_busy")
        reply = self.call(self.players[0], "match", store=store, round=0, attempt=0, **self.ids(view))
        self.assertEqual(reply["current"]["format"], 4)
        self.assertEqual(len(self.desk.invited), 1)
        # Version 1 still reaches it unchanged.
        old = store.handle(self.players[0], dict(version=FOUR_VERSION, operation="status"), roster=self.roster,
                           desk=self.desk, results=self.results, invite=None)
        self.assertEqual(old["version"], FOUR_VERSION)
        self.assertEqual(store.statistics(self.players[0]), dict(entries=1, completed=0, wins=0))

    def test_without_computer_matches_four_players_get_the_old_bracket(self):
        legacy = Championships(Path(self.directory.name) / "w.championships.sqlite3", world_id=self.world,
                               build_id="build-1", ruleset_id="rules-1")
        store = self.open(legacy=legacy)
        view = self.call(self.players[0], "create", store=store, computers=None, championship_id=str(uuid4()),
                         players=self.players)["current"]
        self.assertEqual((view["format"], len(view["matches"])), (4, 3))

    # ------------------------------------------------------------- protocol
    def test_views_that_break_the_bracket_are_refused(self):
        view = self.create(self.players[:2])
        broken = [dict(view, entrants=view["entrants"][:2] + list(reversed(view["entrants"][2:]))),
                  dict(view, matches=[dict(view["matches"][0], seeds=[0, 6])] + view["matches"][1:]),
                  dict(view, matches=view["matches"][:1] + [dict(view["matches"][1], winner=4)] + view["matches"][2:]),
                  dict(view, champion=0), dict(view, rule="anything"),
                  dict(view, matches=[dict(view["matches"][0], kind="auto")] + view["matches"][1:])]
        for value in broken:
            with self.assertRaises(ProtocolError):
                validate_championship_view(value, self.players[0])


class EightChampionshipMenuTests(Fixture, unittest.TestCase):
    """The in-game pages (championship_menu.py) against the real store: every page within the menu's limits (six rows,
    title 23, status 31, rows 25), a computer match answered with the game's command, B back a page."""

    def companion(self, player, capable=True):
        from types import SimpleNamespace
        test = self

        async def rpc(operation, *, championship):
            reply = test.store.handle(player, deepcopy(championship), roster=test.roster, desk=test.desk,
                                      results=test.results, invite=lambda b, peer: test.desk.invited.append((b, peer)),
                                      eligibility=test.eligibility, rule="open", strengths=test.levels.get,
                                      computers=test.context())
            return dict(championship=reply, result=[])
        return SimpleNamespace(config=SimpleNamespace(player_id=player, championship_abi_version=1 if capable else 0),
                               connected=True, world_id=self.world, server_epoch=1, session_epoch=1,
                               _players=[dict(player_id=p, display_name=self.roster[p]) for p in self.players[:2]],
                               battle_challenge_rpc=rpc)

    def check_page(self, menu):
        title, status, actions = menu.render()
        self.assertLessEqual(len(title), 23)
        self.assertLessEqual(len(status), 31)
        self.assertLessEqual(len(actions), 6)
        for label, _op, _args in actions:
            self.assertLessEqual(len(label), 25, label)
        return title, status, actions

    def press(self, menu, label_start):
        import asyncio
        _, _, actions = self.check_page(menu)
        action = next(a for a in actions if a[0].startswith(label_start))
        outcome = asyncio.run(menu.choose(action[1], action[2]))
        asyncio.run(menu.refresh())
        return outcome

    def test_menu_from_proposal_to_a_computer_match(self):
        import asyncio
        from emerald_multiplayer.championship_menu import ChampionshipMenu
        first, second = self.players[:2]
        menu = ChampionshipMenu(self.companion(first))
        asyncio.run(menu.refresh())
        self.assertEqual(self.check_page(menu)[1], "Players + computer trainers")
        self.press(menu, "Propose a Championship")
        title, status, actions = self.check_page(menu)
        self.assertEqual(title, "New Championship")
        self.assertEqual([a[0] for a in actions], ["1 Kevin (you)", "+ Sam", "Propose: 2 + 6 computers"])
        self.press(menu, "Propose: 2")
        title, status, actions = self.check_page(menu)
        self.assertEqual(status, "Accepted 1/2")
        # The other player accepts in their own menu.
        other = ChampionshipMenu(self.companion(second))
        asyncio.run(other.refresh())
        self.press(other, "Places and consent")
        self.press(other, "Accept this bracket")
        asyncio.run(menu.refresh())
        title, status, actions = self.check_page(menu)
        self.assertEqual(status, "Rule: Open")
        labels = [a[0] for a in actions]
        self.assertEqual(labels[0], "You: QF1 Kevin v Misty")
        self.assertIn("Quarterfinals 2/4", labels)
        self.press(menu, "You: QF1")
        title, status, actions = self.check_page(menu)
        self.assertEqual((title, status), ("Quarterfinal 1", "Battle in your own game"))
        self.assertEqual([a[0] for a in actions[:2]], ["1 Kevin", "8 Leader Misty"])
        outcome = self.press(menu, "Battle Misty now")
        self.assertEqual(outcome[0], "command")
        command = outcome[1]
        self.assertEqual((command.mode, command.round, command.flags, command.floor), (2, 1, 0, 20))
        self.assertEqual(self.store.computer_busy(first), "Finish your Championship match")
        self.assertEqual(self.check_page(menu)[1], "Your game starts it")
        # B: the match, then the quarterfinals, then the bracket, then the Players home.
        self.assertIsNone(asyncio.run(menu.choose("champ_back", ())))
        self.assertEqual(self.check_page(menu)[0], "Quarterfinals")
        self.assertIsNone(asyncio.run(menu.choose("champ_back", ())))
        self.assertEqual(self.check_page(menu)[0], "Championship")
        self.assertEqual(asyncio.run(menu.choose("champ_back", ())), "leave")
        # The places pages fit too.
        self.press(menu, "Places")
        title, status, actions = self.check_page(menu)
        self.assertEqual([a[0] for a in actions][-1], "6 computer trainers")
        self.press(menu, "6 computer trainers")
        title, status, actions = self.check_page(menu)
        self.assertEqual(len(actions), 6)
        self.assertTrue(actions[0][0].startswith("3 Leader Norman"))

    def test_an_older_game_is_never_sent_a_computer_match(self):
        import asyncio
        from emerald_multiplayer.championship_menu import ChampionshipMenu
        first, second = self.players[:2]
        self.create([first, second])
        menu = ChampionshipMenu(self.companion(first, capable=False))
        asyncio.run(menu.refresh())
        self.press(menu, "You: QF1")
        self.assertIsNone(self.press(menu, "Battle Misty now"))
        self.assertEqual(self.check_page(menu)[1], "Update the game for this match")
        self.assertIsNone(self.store.computer_busy(first))


if __name__ == "__main__":
    unittest.main()
