"""KNOWN_ISSUES MS-141c: a wireless minigame's lobby page in the Players menu (minigame_link.MinigameMenu through
player_menu.PlayerMenu) against a fake host: the page an attendant's OPEN names, also as the session's first page (the
menu's first refresh of a session showed the home page instead: found in the launcher proof), leading, the start row
once enough players are in, joining, and B leaving the lobby."""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from emerald_multiplayer.menu_mailbox import pack_screen
from emerald_multiplayer.minigame_link import MinigameLink, MinigameRemoteError
from emerald_multiplayer.player_menu import PlayerMenu

ME, BOB = "a", "b"
PLAYER = bytes([0xBB, 0xCC, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0, 2, 3, 0x40, 1, 2, 3, 4])


class FakeCompanion:
    def __init__(self, test):
        self.test = test
        self.config = SimpleNamespace(player_id=ME, world_enabled=True, menu_abi_version=1, trade_enabled=False,
                                      tower_abi_version=0, menu_open_page_abi_version=1)
        self.connected, self.world_id, self.server_epoch, self.session_epoch = True, "w", 1, 2
        self._players = [{"player_id": ME, "display_name": "Alice"}, {"player_id": BOB, "display_name": "Bob"}]
        self._remote_writer = None
        self.minigames = MinigameLink(self)
        self.minigames.activity, self.minigames.link_player = "berry_crush", PLAYER

    def world_nav(self):
        return {"players": [], "outbreak": None, "event": None}

    async def team_rpc(self, operation, **fields):
        return {"result": {"team": None, "teams": [], "invitations": []}}

    async def battle_challenge_rpc(self, operation, **fields):
        return {"result": []}

    async def minigame_rpc(self, operation, **fields):
        self.test.calls.append((operation, fields))
        if self.test.refuse:
            raise MinigameRemoteError(*self.test.refuse)
        return {"result": self.test.reply(operation, fields)}


def view(players, index, gid=7, started=False):
    return {"group_id": gid, "activity": "berry_crush", "leader": players[0], "index": index, "started": started,
            "minimum": 2, "players": [{"player_id": p, "display_name": {ME: "Alice", BOB: "Bob"}[p]} for p in players]}


class LobbyPageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls, self.refuse = [], None
        self.mine, self.groups = None, [{"group_id": 9, "leader_name": "Bob", "players": 1, "minimum": 2}]
        self.companion = FakeCompanion(self)
        self.menu = PlayerMenu(self.companion)

    def reply(self, operation, fields):
        if operation == "status":
            return {"activity": "berry_crush", "groups": self.groups if self.mine is None else [], "mine": self.mine}
        if operation == "open":
            self.mine = view([ME], 0)
            return self.mine
        if operation == "join":
            self.mine = view([BOB, ME], 1, gid=fields["group_id"])
            return self.mine
        if operation == "start":
            return self.mine
        self.mine = None
        return {"left": True}

    labels = property(lambda self: [row.label for row in self.menu.screen.rows])

    async def click(self, label):
        row = next((r for r in self.menu.screen.rows if r.label == label), None)
        self.assertIsNotNone(row, (label, self.labels))
        self.assertTrue(row.action, label)
        return await self.menu.choose(self.menu.screen.revision, row.action)

    async def test_the_attendants_open_shows_the_lobby_even_as_the_sessions_first_page(self):
        await self.menu.open_page("minigame_berry_crush")             # nothing refreshed before: a fresh session
        screen = self.menu.screen
        self.assertEqual((screen.title, screen.status), ("BERRY CRUSH", "Lead a group or join one"))
        self.assertEqual(self.labels, ["Lead a group", "Join Bob 1/4"])
        self.assertEqual(screen.back, 7)
        pack_screen(1, screen, allow_new_page=True)                    # the game's 240 bytes

    async def test_leading_then_the_start_row_once_a_member_is_in(self):
        await self.menu.open_page("minigame_berry_crush")
        await self.click("Lead a group")
        self.assertIn(("open", {"activity": "berry_crush", "link_player": PLAYER.hex()}), self.calls)
        self.assertEqual((self.menu.screen.status, self.labels),
                         ("Waiting: 2 players or more", ["Alice", "End the group"]))
        self.mine = view([ME, BOB], 0)                                 # Bob joins; the page reads the host again
        await self.menu.refresh()
        self.assertEqual(self.labels, ["Start with 2 players", "Alice", "Bob", "End the group"])
        self.assertEqual(self.menu.screen.status, "2 of 4 players: start?")
        await self.click("Start with 2 players")
        self.assertIn(("start", {"group_id": 7}), self.calls)

    async def test_joining_and_b_leaves_the_group_and_closes_the_window(self):
        await self.menu.open_page("minigame_berry_crush")
        await self.click("Join Bob 1/4")
        self.assertEqual((self.menu.screen.status, self.labels),
                         ("Waiting for Bob to start", ["Bob", "Alice", "Leave the group"]))
        await self.menu.choose(self.menu.screen.revision, 7)           # B
        self.assertIn(("leave", {"group_id": 9, "lost": False}), self.calls)
        self.assertEqual(self.menu.handoff, ("close", {}))

    async def test_a_full_group_says_so(self):
        await self.menu.open_page("minigame_berry_crush")
        self.refuse = ("minigame_full", "that group is full")
        await self.click("Join Bob 1/4")
        self.assertEqual(self.menu.screen.status, "That group is full")
