"""Update 31: the rival checkpoint page of the native Players menu, end to end.

Real Companions (the game-side client) against a real WorldServer over
authenticated loopback; the menu is driven exactly as the native menu
mailbox drives it (screen revision + row action). The players' positions are
set on the host's sessions as a presence message would set them, because
these companions have no game core attached. Simulated input, not a game run.
"""
import unittest

from emerald_multiplayer.player_menu import PlayerMenu, PlayerMenuError
from emerald_multiplayer.rival_menu import STATE_WORDS, _versus
from emerald_multiplayer.protocol import validate_presence
import test_battle_challenge_network as fixtures

ROUTE110 = dict(map_group=0, map_number=25)
LITTLEROOT = dict(map_group=0, map_number=9)


class VersusLabelTests(unittest.TestCase):
    """A match row fits the menu's 25 characters with both names whole (L rival-1 in real games showed
    "Battle: Rival F vs Rival " - the second name's last letter cut)."""

    def test_two_seven_letter_names_keep_every_letter(self):
        label = "Battle: " + _versus([["Rival F"], ["Rival H"]], 25 - len("Battle: "))
        self.assertEqual(label, "Battle: Rival F v Rival H")
        self.assertLessEqual(len(label), 25)

    def test_short_names_keep_vs(self):
        self.assertEqual(_versus([["Kash"], ["Bob"]], 17), "Kash vs Bob")

    def test_a_2v2_keeps_all_four_trainers(self):
        # MS-58 (L rival-4p-1): the teams cut as one string showed "Battle: Rival T v Rival H", one trainer a side.
        self.assertEqual(_versus([["Kevin", "Sam"], ["Alex", "Jo"]], 17), "Kev&Sam v Alex&Jo")
        self.assertEqual(_versus([["Al", "Bo"], ["Cy", "Di"]], 17), "Al & Bo v Cy & Di")
        self.assertEqual(_versus([["Al", "Bo"], ["Cy", "Di"]], 18), "Al & Bo vs Cy & Di")
        for teams in ([["Rival F", "Rival H"], ["Rival T", "Rival Q"]], [["A", "B"], ["Rival Thirds", "Rival Q"]]):
            label = _versus(teams, 17)
            self.assertLessEqual(len(label), 17, label)
            left, right = label.split(" v ")
            self.assertEqual((left.count("&"), right.count("&")), (1, 1), label)

    def test_a_bystanders_row_fits_with_its_state(self):
        for state in ("ready", "pending", "invited", "waiting", "resolved", "void"):
            word = " " + STATE_WORDS.get(state, state)
            label = _versus([["Rival F"], ["Rival H"]], 25 - len(word)) + word
            self.assertLessEqual(len(label), 25, state)
            self.assertTrue(label.startswith("Rival F v") and "Rival H" in label, f"{state}: {label}")
        self.assertEqual(STATE_WORDS["resolved"], "done")     # L rival-3p-1: "Rival  v Rival  resolved"


class RivalMenuTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.BattleChallengeNetworkTests.asyncSetUp
    asyncTearDown = fixtures.BattleChallengeNetworkTests.asyncTearDown

    async def place(self, index, where, activity="overworld"):
        session = self.server.sessions[self.players[index].player_id]
        self.seq = getattr(self, "seq", 0) + 1
        # Exactly what the host stores for a presence message (WorldServer: validate_presence).
        session.presence = validate_presence(dict(type="presence", session_epoch=session.session_epoch, seq=self.seq,
            map_epoch=self.seq, x=34, y=57, direction=1, elevation=0, avatar_gender=0, activity=activity, **where),
            session.session_epoch)
        self.server._broadcast_world()
        companion = self.companions[index]
        await fixtures.wait_until(lambda: any(p["player_id"] == self.players[index].player_id and p["presence"]
                                              and p["presence"]["map_number"] == where["map_number"]
                                              for p in companion._players))

    def labels(self, menu):
        return [row.label for row in menu.screen.rows]

    async def click(self, menu, label):
        screen = menu.screen
        row = next((row for row in screen.rows if row.label == label and row.action), None)
        self.assertIsNotNone(row, f"{label!r} not clickable in {self.labels(menu)}")
        return await menu.choose(screen.revision, row.action)

    async def open_rival(self, index):
        menu = PlayerMenu(self.companions[index])
        await menu.refresh()
        await self.click(menu, "Rival checkpoint")
        return menu

    async def test_home_shows_the_rival_row_only_at_a_checkpoint(self):
        menu = PlayerMenu(self.companions[0])
        await menu.refresh()
        self.assertNotIn("Rival checkpoint", self.labels(menu))
        await self.place(0, ROUTE110)
        await menu.refresh()
        self.assertIn("Rival checkpoint", self.labels(menu))
        self.assertLessEqual(len(menu.screen.rows), 6)

    async def test_waiting_alone_then_start_now_with_a_second_player_then_challenge(self):
        self.server._rivals.countdown = 0.0
        await self.place(0, ROUTE110)
        menu = await self.open_rival(0)
        self.assertEqual(menu.screen.title, "Rival: Route 110")
        self.assertEqual(menu.screen.status, "Waiting for rival players...")
        self.assertIn("Start Now", self.labels(menu))
        self.assertIn("Wait for Other Players", self.labels(menu))
        await self.click(menu, "Start Now")
        self.assertEqual(menu.screen.status, "You chose Start Now")
        # Double click on the same (consumed) screen is refused: no second vote RPC.
        screen = menu.screen
        await self.place(1, ROUTE110)
        other = await self.open_rival(1)
        self.assertIn("Trainer 0: Start", self.labels(other))
        await self.click(other, "Start Now")
        await menu.refresh()
        battle_row = next(label for label in self.labels(menu) if label.startswith("Battle: "))
        await self.click(menu, battle_row)
        self.assertEqual(menu._page[0], "battles", "a proposed match opens ordinary Challenges")
        await other.refresh()
        self.assertIn("Open Challenges to accept", self.labels(other))
        await self.click(other, "Open Challenges to accept")
        self.assertEqual(other._page[0], "battles")
        challenges = PlayerMenu(self.companions[1])
        await challenges.refresh()
        await self.click(challenges, "Pending challenge")
        self.assertIn("Accept challenge", self.labels(challenges))
        self.assertFalse(any(label.startswith("Wager") for label in self.labels(challenges)),
                         "rival battles never offer a wager")
        await self.click(challenges, "Accept challenge")
        room = next(iter(self.server.battle_desk._active.values()))
        self.assertEqual(len(room.consent), 2)
        self.assertFalse(room.bind_intent, "menu consent never binds a native battle by itself")
        self.assertTrue(screen.revision < menu.screen.revision)

    async def test_wait_choice_and_back_navigation(self):
        await self.place(0, ROUTE110)
        menu = await self.open_rival(0)
        await self.click(menu, "Wait for Other Players")
        self.assertEqual(menu.screen.status, "You chose to wait")
        self.assertIn("Trainer 0: Wait", self.labels(menu))
        home = await menu.choose(menu.screen.revision, 7)
        self.assertEqual(home.title, "Players")
        await self.click(menu, "Rival checkpoint")
        self.assertIn("Trainer 0: Wait", self.labels(menu), "reopening shows the saved choice")

    async def test_stale_and_repeated_clicks_are_refused(self):
        await self.place(0, ROUTE110)
        menu = await self.open_rival(0)
        screen = menu.screen
        action = next(row.action for row in screen.rows if row.label == "Start Now")
        await menu.choose(screen.revision, action)
        with self.assertRaises(PlayerMenuError):
            await menu.choose(screen.revision, action)
        self.assertEqual(self.server._rivals._lobbies["route110"].votes, {self.players[0].player_id: "start"})

    async def test_leaving_the_checkpoint_disables_the_buttons(self):
        await self.place(0, ROUTE110)
        menu = await self.open_rival(0)
        await self.place(0, LITTLEROOT)
        await menu.refresh()
        self.assertEqual(menu.screen.status, "World rival progress 0/5")
        self.assertNotIn("Start Now", self.labels(menu))

    async def test_disconnect_revokes_rival_actions(self):
        await self.place(0, ROUTE110)
        menu = await self.open_rival(0)
        screen = menu.screen
        self.companions[0].connected = False
        with self.assertRaises(PlayerMenuError):
            await menu.choose(screen.revision, next(r.action for r in screen.rows if r.label == "Start Now"))
        screen = await menu.refresh()
        self.assertEqual(screen.status, "Connection interrupted")

    async def test_challenges_page_links_rival_progress(self):
        menu = PlayerMenu(self.companions[2])
        await menu.refresh()
        await self.click(menu, "Challenges")
        self.assertLessEqual(len(menu.screen.rows), 6)
        await self.click(menu, "Rival checkpoints")
        self.assertEqual(menu.screen.status, "World rival progress 0/5")
        self.assertEqual(self.labels(menu)[0], "Route 103: open")

    async def test_host_without_rival_support_reports_it(self):
        self.server._rivals = None
        await self.place(0, ROUTE110)
        menu = await self.open_rival(0)
        self.assertEqual(menu.screen.status, "Host has no rival checkpoints")
        self.assertEqual(self.labels(menu), ["Refresh"])


if __name__ == "__main__":
    unittest.main()
