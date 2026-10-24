"""Update 32 (feature 10): battle lobbies, the format follows the trainers who joined.

The desk on its own (battle_lobby.py), its wire validation (lobby_protocol.py), and the whole path through a real host
and four connected companions in the in-game Players menu (player_menu.py): who is invited, who joined or declined,
the detected format, the leader's start (the ordinary challenge of that format, for exactly the joined trainers), and
that nobody else is pulled in. Simulated clients, not games.
"""
from types import SimpleNamespace
import unittest
import unittest.mock
from uuid import uuid4

from emerald_multiplayer.battle_lobby import LobbyDesk, LobbyError, detected_formats
from emerald_multiplayer.lobby_protocol import validate_lobby_reply, validate_lobby_request
from emerald_multiplayer.player_menu import PlayerMenu
from emerald_multiplayer.protocol import PROTOCOL_VERSION, ProtocolError
import test_battle_challenge_network as fixtures

A, B, C, D = (str(uuid4()) for _ in range(4))


class FakeBattles:
    """The battle desk's surface the lobby reads: its active challenges."""

    def __init__(self):
        self._active = {}

    def refresh(self):
        pass

    def add(self, sender, players, mode):
        battle_id = str(uuid4())
        self._active[battle_id] = SimpleNamespace(sender=sender, players=tuple(players), mode=mode)
        return battle_id


class LobbyDeskTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.roster = {A: 1, B: 2, C: 3, D: 4}
        self.battles = FakeBattles()
        self.desk = LobbyDesk(lambda: dict(self.roster), battle_desk=self.battles, timeout=300, linger=60,
                              clock=lambda: self.now)

    def lease(self, player):
        return player, self.roster[player]

    def create(self, *invitees, creator=A):
        return self.desk.create(*self.lease(creator), tuple(invitees), str(uuid4()))

    def code(self, expected, function, *args, **kwargs):
        with self.assertRaises(LobbyError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, expected)

    def test_the_format_follows_the_joined_count_never_the_invited_one(self):
        self.assertEqual([detected_formats(n) for n in range(1, 6)],
                         [(), ("1v1",), ("1v1v1",), ("1v1v1v1", "2v2"), ()])
        view = self.create(B, C, D)
        ids = view["lobby_id"], view["generation"]
        self.assertEqual((view["joined"], view["formats"]), ([A], []))      # the leader alone: nothing yet
        view = self.desk.join(*self.lease(B), *ids)
        self.assertEqual(view["formats"], ["1v1"])
        view = self.desk.join(*self.lease(C), *ids)
        self.assertEqual(view["formats"], ["1v1v1"])
        view = self.desk.join(*self.lease(D), *ids)
        self.assertEqual(view["formats"], ["1v1v1v1", "2v2"])
        view = self.desk.leave(*self.lease(D), *ids)
        self.assertEqual((view["formats"], view["left"]), (["1v1v1"], [D]))

    def test_a_decline_is_not_counted_and_nobody_answers_twice(self):
        view = self.create(B, C)
        ids = view["lobby_id"], view["generation"]
        self.desk.join(*self.lease(B), *ids)
        view = self.desk.decline(*self.lease(C), *ids)
        self.assertEqual((view["joined"], view["declined"], view["formats"]), ([A, B], [C], ["1v1"]))
        self.code("lobby_answered", self.desk.join, *self.lease(C), *ids)
        self.code("lobby_answered", self.desk.decline, *self.lease(B), *ids)
        self.code("lobby_not_invited", self.desk.join, *self.lease(D), *ids)    # an unrelated trainer cannot join

    def test_everyone_declining_ends_the_lobby_and_it_lingers_with_its_reason(self):
        view = self.create(B)
        view = self.desk.decline(*self.lease(B), view["lobby_id"], view["generation"])
        self.assertEqual((view["state"], view["reason"]), ("ended", "nobody_joined"))
        self.assertEqual(len(self.desk.status(*self.lease(A))["lobbies"]), 1)
        self.now += 61
        self.assertEqual(self.desk.status(*self.lease(A))["lobbies"], [])

    def test_the_deadline_ends_an_unstarted_lobby(self):
        view = self.create(B)
        self.desk.join(*self.lease(B), view["lobby_id"], view["generation"])
        self.now += 299
        self.assertEqual(self.desk.status(*self.lease(A))["lobbies"][0]["state"], "open")
        self.now += 1
        ended = self.desk.status(*self.lease(B))["lobbies"][0]
        self.assertEqual((ended["state"], ended["reason"]), ("ended", "timed_out"))

    def test_a_reconnect_leaves_the_lobby_and_the_leader_leaving_ends_it(self):
        view = self.create(B, C)
        ids = view["lobby_id"], view["generation"]
        self.desk.join(*self.lease(B), *ids)
        self.desk.join(*self.lease(C), *ids)
        self.roster[C] = 30                                                 # C's connection was replaced
        view = self.desk.status(*self.lease(A))["lobbies"][0]
        self.assertEqual((view["joined"], view["left"], view["formats"]), ([A, B], [C], ["1v1"]))
        view = self.desk.leave(*self.lease(A), *ids)
        self.assertEqual((view["state"], view["reason"]), ("ended", "cancelled"))
        self.code("lobby_closed", self.desk.join, *self.lease(B), *ids)
        view = self.create(C, D, creator=B)
        del self.roster[B]                                                  # the leader left the world
        self.assertEqual(self.desk.status(*self.lease(C))["lobbies"][-1]["reason"], "creator_left")

    def test_one_open_lobby_per_trainer_and_only_connected_distinct_invitees(self):
        self.create(B)
        self.code("lobby_busy", self.create, C, B, creator=D)
        self.code("lobby_busy", self.create, C, creator=B)
        for invitees in ((), (C,), (D, D), (D, B, A, str(uuid4()))):
            self.code("invalid_lobby", self.desk.create, *self.lease(C), invitees, str(uuid4()))
        self.code("player_offline", self.create, str(uuid4()), creator=C)
        self.battles.add(C, (C, D), 2)
        self.code("battle_busy", self.create, D, creator=C)

    def test_start_links_only_the_leaders_challenge_for_exactly_the_joined_trainers(self):
        view = self.create(B, C, D)
        ids = view["lobby_id"], view["generation"]
        for player in (B, C):
            self.desk.join(*self.lease(player), *ids)
        self.code("lobby_not_creator", self.desk.start, *self.lease(B), *ids, self.battles.add(B, (A, B, C), 6))
        wrong = (self.battles.add(A, (A, B), 2),                 # not everyone who joined
                 self.battles.add(A, (A, B, C, D), 5),           # someone who did not join
                 self.battles.add(A, (A, B, C), 5),              # the wrong format for three
                 str(uuid4()))                                   # no such challenge
        for battle_id in wrong:
            self.code("lobby_changed", self.desk.start, *self.lease(A), *ids, battle_id)
        battle_id = self.battles.add(A, (A, C, B), 6)
        view = self.desk.start(*self.lease(A), *ids, battle_id)
        self.assertEqual((view["state"], view["format"], view["battle_id"]), ("started", "1v1v1", battle_id))
        self.assertEqual(self.desk.start(*self.lease(A), *ids, battle_id), view)      # an exact retry
        self.code("lobby_closed", self.desk.join, *self.lease(D), *ids)

    def test_four_joined_trainers_start_a_free_for_all_or_a_2v2(self):
        for mode, name in ((5, "1v1v1v1"), (3, "2v2")):
            with self.subTest(name=name):
                self.battles = FakeBattles()
                self.desk = LobbyDesk(lambda: dict(self.roster), battle_desk=self.battles, clock=lambda: self.now)
                view = self.create(B, C, D)
                ids = view["lobby_id"], view["generation"]
                for player in (B, C, D):
                    self.desk.join(*self.lease(player), *ids)
                view = self.desk.start(*self.lease(A), *ids, self.battles.add(A, (A, B, C, D), mode))
                self.assertEqual(view["format"], name)

    def test_too_small_and_stale_leases_are_refused(self):
        view = self.create(B)
        ids = view["lobby_id"], view["generation"]
        self.code("lobby_too_small", self.desk.start, *self.lease(A), *ids, self.battles.add(A, (A, B), 2))
        self.code("stale_lease", self.desk.join, B, 99, *ids)
        self.code("lobby_generation_mismatch", self.desk.join, *self.lease(B), ids[0], str(uuid4()))


class LobbyProtocolTests(unittest.TestCase):
    def request(self, operation, **fields):
        return dict(type="lobby_" + operation, request_id=str(uuid4()), session_epoch=3, **fields)

    def test_requests_name_their_lobby_and_up_to_three_distinct_invitees(self):
        self.assertTrue(validate_lobby_request(self.request("create", lobby_id=str(uuid4()), invitees=[B, C]), 3))
        for invitees in ([], [B, B], [B, C, D, A], "B", [7]):
            with self.subTest(invitees=invitees), self.assertRaises(ProtocolError):
                validate_lobby_request(self.request("create", lobby_id=str(uuid4()), invitees=invitees), 3)
        with self.assertRaises(ProtocolError):
            validate_lobby_request(self.request("join", lobby_id=str(uuid4())), 3)           # no generation
        with self.assertRaises(ProtocolError):
            validate_lobby_request(self.request("status"), 4)                                # another lease
        with self.assertRaises(ProtocolError):
            validate_lobby_request(self.request("delete", lobby_id=str(uuid4())), 3)

    def test_a_reply_must_be_a_consistent_lobby_of_this_player(self):
        world = str(uuid4())
        desk = LobbyDesk(lambda: {A: 1, B: 2, C: 3}, clock=lambda: 5.0)
        lobby_id = str(uuid4())
        view = desk.create(A, 1, (B, C), lobby_id)
        request = self.request("create", lobby_id=lobby_id, invitees=[B, C])
        reply = dict(type="lobby_result", protocol=PROTOCOL_VERSION, session_epoch=3, request_id=request["request_id"],
                     operation="create", world_id=world, player_id=A, result=view)
        self.assertEqual(validate_lobby_reply(reply, A, world, 3, request), reply)
        for change in (dict(formats=["1v1"]), dict(joined=[A, D]), dict(state="started"), dict(invited=[])):
            bad = dict(reply, result=dict(view, **change))
            with self.subTest(change=change), self.assertRaises(ProtocolError):
                validate_lobby_reply(bad, A, world, 3, request)
        with self.assertRaises(ProtocolError):
            validate_lobby_reply(reply, D, world, 3)                       # a foreign player's lobby


class LobbyMenuNetworkTests(unittest.IsolatedAsyncioTestCase):
    """Four connected companions ("Trainer 0" to "Trainer 3") and a real host."""
    asyncSetUp = fixtures.BattleChallengeNetworkTests.asyncSetUp
    asyncTearDown = fixtures.BattleChallengeNetworkTests.asyncTearDown

    async def click(self, menu, label):
        screen = menu.screen
        return await menu.choose(screen.revision, next(row.action for row in screen.rows if row.label == label))

    def labels(self, menu):
        return [row.label for row in menu.screen.rows]

    async def open_lobby(self, menu, *names):
        await menu.refresh()
        await self.click(menu, "Challenges")
        await self.click(menu, "New battle")
        await self.click(menu, "Battle lobby")
        for name in names:
            await self.click(menu, f"{name}: No")
        return await self.click(menu, "Send invitations")

    async def lobby_page(self, menu):
        """PLAYERS > Battle lobby (the menu stays on the lobby page after its own choices)."""
        screen = await menu.refresh()
        if screen.title != "Battle lobby":
            screen = await self.click(menu, "Battle lobby")
        return screen

    async def home(self, menu):
        screen = await menu.refresh()
        while screen.back:                       # B back to the player list
            screen = await menu.choose(screen.revision, screen.back)
        return screen

    async def answer(self, menu, label):
        await self.home(menu)
        self.assertIn("Battle lobby", self.labels(menu))
        await self.click(menu, "Battle lobby")
        return await self.click(menu, label)

    async def test_two_join_one_declines_and_the_leader_starts_a_1v1v1_only_for_them(self):
        menus = [PlayerMenu(c) for c in self.companions]
        for companion in self.companions:
            object.__setattr__(companion.config, "battle_ffa_enabled", True)
            object.__setattr__(companion.config, "battle_ffa3_enabled", True)
        screen = await self.open_lobby(menus[0], "Trainer 1", "Trainer 2", "Trainer 3")
        self.assertEqual(screen.title, "Battle lobby")
        self.assertEqual(screen.status, "Waiting for 3 to answer")
        self.assertEqual(sorted(self.labels(menus[0])[:3]),
                         ["Trainer 1: invited", "Trainer 2: invited", "Trainer 3: invited"])
        await self.answer(menus[1], "Join lobby")
        await self.answer(menus[2], "Join lobby")
        await self.answer(menus[3], "Decline")
        screen = await self.lobby_page(menus[0])
        self.assertEqual(screen.status, "1v1v1: 3 joined")
        self.assertIn("Trainer 3: declined", self.labels(menus[0]))
        self.assertNotIn("Start 1v1", self.labels(menus[0]))
        screen = await self.click(menus[0], "Start 1v1v1")
        pending = (await self.companions[0].battle_challenge_rpc("pending"))["result"]
        ids = {c.config.player_id for c in self.companions}
        self.assertEqual((len(pending), pending[0]["mode"], len(pending[0]["players"])), (1, 6, 3))
        self.assertEqual(set(pending[0]["players"]), ids - {self.companions[3].config.player_id})
        self.assertEqual(pending[0]["consent"], [self.companions[0].config.player_id])  # each accepts for themselves
        self.assertEqual((await self.companions[3].battle_challenge_rpc("pending"))["result"], [])   # not pulled in
        for i in (1, 2):
            await menus[i].refresh()
            await self.click(menus[i], "Pending challenge")
            await self.click(menus[i], "Accept challenge")
        pending = (await self.companions[0].battle_challenge_rpc("pending"))["result"][0]
        self.assertEqual(pending["state"], "accepted")
        lobby = self.server.lobby_desk.status(self.companions[0].config.player_id,
                                              self.companions[0].session_epoch)["lobbies"][0]
        self.assertEqual((lobby["state"], lobby["format"], lobby["battle_id"]), ("started", "1v1v1", pending["battle_id"]))

    async def test_one_joined_trainer_makes_a_1v1_and_four_offer_both_four_player_formats(self):
        menus = [PlayerMenu(c) for c in self.companions]
        await self.open_lobby(menus[0], "Trainer 1")
        await self.answer(menus[1], "Join lobby")
        screen = await self.lobby_page(menus[0])
        self.assertEqual(screen.status, "1v1: 2 joined")
        await self.click(menus[0], "Start 1v1")
        pending = (await self.companions[1].battle_challenge_rpc("pending"))["result"][0]
        self.assertEqual((pending["mode"], len(pending["players"])), (2, 2))
        await self.companions[0].battle_challenge_rpc("cancel", battle_id=pending["battle_id"],
                                                      generation=pending["generation"])
        for companion in self.companions:
            object.__setattr__(companion.config, "battle_ffa_enabled", True)
        await self.open_lobby(menus[2], "Trainer 0", "Trainer 1", "Trainer 3")
        for i in (0, 1, 3):
            await self.answer(menus[i], "Join lobby")
        screen = await self.lobby_page(menus[2])
        self.assertEqual(screen.status, "1v1v1v1 or 2v2: 4 joined")
        self.assertIn("Start 1v1v1v1", self.labels(menus[2]))
        screen = await self.click(menus[2], "Start 2v2")
        self.assertEqual(screen.status, "Choose your 2v2 partner")
        await self.click(menus[2], "With Trainer 0")
        pending = (await self.companions[2].battle_challenge_rpc("pending"))["result"][0]
        self.assertEqual(pending["mode"], 3)
        own = {self.companions[2].config.player_id, self.companions[0].config.player_id}
        self.assertTrue(own in ({*pending["players"][::2]}, {*pending["players"][1::2]}))

    async def test_a_lobby_the_leader_cancels_ends_for_everyone_and_an_older_game_cannot_start_a_1v1v1(self):
        menus = [PlayerMenu(c) for c in self.companions]
        await self.open_lobby(menus[0], "Trainer 1", "Trainer 2")
        await self.answer(menus[1], "Join lobby")
        await self.answer(menus[2], "Join lobby")
        screen = await self.lobby_page(menus[0])
        self.assertEqual(screen.status, "Your game cannot play 1v1v1")      # the fixture game has no 1v1v1 marker
        self.assertNotIn("Start 1v1v1", self.labels(menus[0]))
        await self.click(menus[0], "Cancel lobby...")               # it asks first (No first)
        with unittest.mock.patch("emerald_multiplayer.player_menu.ASK_GRACE_SECONDS", 0):
            await self.click(menus[0], "Yes, leave the lobby")
        screen = await self.lobby_page(menus[1])
        self.assertEqual(screen.status, "The lobby was cancelled")
        self.assertEqual((await self.companions[1].battle_challenge_rpc("pending"))["result"], [])


if __name__ == "__main__":
    unittest.main()
