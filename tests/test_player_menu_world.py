"""Players menu: friendship labels, the wager page and co-op Gym challenges.

A fake companion stands in for the authenticated host; the host rules
themselves are tested in test_world_server/test_wagers."""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from emerald_multiplayer.player_menu import WAGER_CHOICES, PlayerMenu
from emerald_multiplayer.protocol import ProtocolError

ALICE, BOB = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"


class FakeCompanion:
    def __init__(self, actor=ALICE, mode=2, gym=0, state="accepted"):
        self.config = SimpleNamespace(player_id=actor, world_enabled=True, menu_abi_version=1, trade_enabled=False)
        self.connected, self.world_id, self.server_epoch, self.session_epoch = True, "world", 1, 2
        self._players = [{"player_id": ALICE, "display_name": "Alice"}, {"player_id": BOB, "display_name": "Bob"}]
        self.battle = dict(battle_id="battle", generation="gen", fingerprint="f" * 64, state=state, mode=mode,
                           gym=gym, sender=ALICE, players=[ALICE, BOB], consent=[ALICE, BOB],
                           checkpoints=[dict(player_id=ALICE, party_count=6), dict(player_id=BOB, party_count=3)])
        self.wager = None
        self.money = 20_000
        self.calls = []

    async def team_rpc(self, operation, **fields):
        return {"result": {"team": None, "teams": [], "invitations": []}}

    async def battle_challenge_rpc(self, operation, **fields):
        self.calls.append((operation, fields))
        return {"result": [self.battle]}

    async def friendship_rpc(self):
        return {BOB: {"level": 1, "name": "Good Friends", "points": 40, "next": 120, "lucky_friends": True}}

    async def wager_rpc(self, operation, **fields):
        self.calls.append((operation, fields))
        if operation == "wager_set":
            if fields["amount"] > self.money:
                raise ProtocolError("insufficient_funds", "every trainer needs enough money for the wager")
            self.wager = None if fields["amount"] == 0 else dict(
                battle_id="battle", amount=fields["amount"], sender=self.config.player_id,
                players=[ALICE, BOB], accepted=[self.config.player_id], state="proposed")
        elif operation == "wager_accept":
            self.wager = {**self.wager, "accepted": [ALICE, BOB]}
        elif operation == "wager_decline":
            self.wager = None
        return {"wager": self.wager, "money": self.money}


class PlayerMenuWorldTests(unittest.IsolatedAsyncioTestCase):
    async def click(self, menu, label):
        screen = menu.screen
        row = next((row for row in screen.rows if row.label == label), None)
        self.assertIsNotNone(row, [r.label for r in screen.rows])
        return await menu.choose(screen.revision, row.action)

    def labels(self, menu):
        return [row.label for row in menu.screen.rows]

    async def test_friendship_levels_on_home_and_player_pages(self):
        menu = PlayerMenu(FakeCompanion())
        await menu.refresh()
        self.assertIn("Bob - Good", self.labels(menu))
        screen = await self.click(menu, "Bob - Good")
        self.assertEqual(screen.status, "Good Friends 40/120")
        self.assertIn("LUCKY FRIENDS: next trade", self.labels(menu))

    async def test_long_names_stay_apart_beside_the_friendship_level(self):
        # native-launcher-multi-4: "Multi Friend 1/2/3" were all cut to "Multi Friend ".
        companion = FakeCompanion()
        third = "33333333-3333-4333-8333-333333333333"
        companion._players = [{"player_id": ALICE, "display_name": "Alice"},
                              {"player_id": BOB, "display_name": "Multi Friend 1"},
                              {"player_id": third, "display_name": "Multi Friend 2"}]
        async def friendship_rpc():
            return {BOB: {"level": 1, "name": "Good Friends", "points": 40, "next": 120, "lucky_friends": False},
                    third: {"level": 2, "name": "Great Friends", "points": 130, "next": 300, "lucky_friends": False}}
        companion.friendship_rpc = friendship_rpc
        menu = PlayerMenu(companion)
        await menu.refresh()
        labels = self.labels(menu)
        self.assertIn("Multi Friend 1 - Good", labels)
        self.assertIn("Multi Friend 2 - Great", labels)
        # The longest name (24 characters) is cut only to make room for the level.
        companion._players[1]["display_name"] = "A" * 23 + "Z"
        await menu.refresh()
        long = next(label for label in self.labels(menu) if label.startswith("AAA"))
        self.assertEqual(long, "A" * 18 + " - Good")
        self.assertLessEqual(max(len(label) for label in self.labels(menu)), 25)

    async def test_wager_must_be_accepted_by_everyone_before_enter(self):
        companion = FakeCompanion()
        menu = PlayerMenu(companion)
        await menu.refresh()
        await self.click(menu, "Pending challenge")
        self.assertIn("Wager: none (set one)", self.labels(menu))
        await self.click(menu, "Wager: none (set one)")
        self.assertEqual(menu.screen.title, "Battle wager")
        self.assertIn("Your money: $20,000", self.labels(menu))
        self.assertIn(f"Amount: ${WAGER_CHOICES[1]:,}", self.labels(menu))
        await self.click(menu, f"Amount: ${WAGER_CHOICES[1]:,}")
        self.assertIn(f"Amount: ${WAGER_CHOICES[2]:,}", self.labels(menu))
        await self.click(menu, "Propose this wager")
        self.assertIn(("wager_set", dict(battle_id="battle", amount=WAGER_CHOICES[2])), companion.calls)
        await menu.refresh()
        # Where Propose was, a row that does nothing; removing it asks first.
        self.assertEqual(self.labels(menu)[2:4], ["Waiting for the others", "Remove wager..."])
        await self.click(menu, "Back to challenge")
        self.assertEqual(menu.screen.status, "Everyone must accept the wager")
        # Bob sees the exact amount and accepts it.
        bob = PlayerMenu(SimpleNamespace(**{**companion.__dict__, "config": SimpleNamespace(
            **{**companion.config.__dict__, "player_id": BOB})}))
        bob.companion.team_rpc, bob.companion.battle_challenge_rpc = companion.team_rpc, companion.battle_challenge_rpc
        bob.companion.friendship_rpc, bob.companion.wager_rpc = companion.friendship_rpc, companion.wager_rpc
        await bob.refresh()
        await self.click(bob, "Pending challenge")
        await self.click(bob, "Wager $10,000 1/2 OK")
        await self.click(bob, "Accept $10,000 wager")
        self.assertIn(("wager_accept", dict(battle_id="battle", amount=10_000)), companion.calls)
        await menu.refresh()
        self.assertIn("Wager $10,000 2/2 OK", self.labels(menu))
        self.assertNotEqual(menu.screen.status, "Everyone must accept the wager")

    async def test_host_refusal_is_shown_not_retried(self):
        companion = FakeCompanion()
        companion.money = 500
        menu = PlayerMenu(companion)
        await menu.refresh()
        await self.click(menu, "Pending challenge")
        await self.click(menu, "Wager: none (set one)")
        await self.click(menu, "Propose this wager")
        self.assertEqual(menu.screen.status, "every trainer needs enough mone")  # 31-char status line
        self.assertEqual(sum(1 for call in companion.calls if call[0] == "wager_set"), 1)

    async def test_coop_gym_challenge_is_titled_and_has_no_wager_row_once_started(self):
        companion = FakeCompanion(mode=4, gym=7)
        menu = PlayerMenu(companion)
        await menu.refresh()
        screen = await self.click(menu, "Pending challenge")
        self.assertEqual(screen.title, "Team Gym vs Tate&Liza")
        self.assertIn("Alice (6)", self.labels(menu))
        companion.battle["state"] = "running"
        await menu.refresh()
        self.assertFalse(any(label.startswith("Wager") for label in self.labels(menu)))


if __name__ == "__main__":
    unittest.main()
