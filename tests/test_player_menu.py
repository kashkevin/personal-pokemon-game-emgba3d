import unittest

from emerald_multiplayer.player_menu import PlayerMenu, PlayerMenuError
import test_battle_challenge_network as fixtures


class PlayerMenuNetworkTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.BattleChallengeNetworkTests.asyncSetUp
    asyncTearDown = fixtures.BattleChallengeNetworkTests.asyncTearDown

    async def click(self, menu, label):
        screen = menu.screen
        return await menu.choose(screen.revision, next(row.action for row in screen.rows if row.label == label))

    async def test_two_players_explicitly_form_leave_and_change_team(self):
        menus = [PlayerMenu(c) for c in self.companions]
        await menus[0].refresh()
        await self.click(menus[0], "Trainer 1")
        await self.click(menus[0], "Invite to team")
        await menus[1].refresh()
        await self.click(menus[1], "Team invitation")
        await self.click(menus[1], "Accept invitation")
        self.assertIn("Leave team", [r.label for r in menus[1].screen.rows])
        await self.click(menus[1], "Leave team")
        self.assertEqual(menus[1].screen.status, "Choose a player to invite")

    async def test_changed_menu_and_double_click_cannot_repeat_mutation(self):
        menu = PlayerMenu(self.companions[0]); await menu.refresh()
        screen = await self.click(menu, "Trainer 1")
        action = next(r.action for r in screen.rows if r.label == "Invite to team")
        await menu.choose(screen.revision, action)
        with self.assertRaises(PlayerMenuError): await menu.choose(screen.revision, action)
        self.assertEqual(len(self.server.team_desk._invitations), 1)

    async def test_challenge_consent_is_exact_and_does_not_start_native_battle(self):
        a, b = (PlayerMenu(self.companions[i]) for i in (0, 1))
        await a.refresh(); await self.click(a, "Trainer 1"); await self.click(a, "Challenge 1v1")
        await b.refresh(); await self.click(b, "Pending challenge")
        await self.click(b, "Accept challenge")
        self.assertEqual(b.screen.status, "Waiting for battle coordinator")
        room = next(iter(self.server.battle_desk._active.values()))
        self.assertEqual(len(room.consent), 2)
        self.assertFalse(room.bind_intent)

    async def test_unchanged_refresh_keeps_visible_action_generation(self):
        menu = PlayerMenu(self.companions[0])
        first = await menu.refresh()
        self.assertEqual(await menu.refresh(), first)
        self.assertEqual(first.back, 0)
        screen = await self.click(menu, "Trainer 1")
        self.assertEqual(screen.back, 7)
        self.assertEqual((await menu.choose(screen.revision, 7)).title, "Players")

    async def test_disconnect_revokes_actions_without_selecting_policy(self):
        menu = PlayerMenu(self.companions[0]); screen = await menu.refresh()
        self.companions[0].connected = False
        with self.assertRaises(PlayerMenuError): await menu.choose(screen.revision, 1)
        screen = await menu.refresh()
        self.assertEqual(screen.status, "Connection lost")
        self.assertFalse(screen.rows)

    async def test_disabled_services_have_no_action_buttons(self):
        self.server.team_desk = self.server.battle_desk = None
        menu = PlayerMenu(self.companions[0]); await menu.refresh()
        screen = await self.click(menu, "Trainer 1")
        self.assertEqual(screen.rows, ())

    async def test_recent_results_show_own_side_and_read_only_roster(self):
        # Simulated native receipts have their own Desk tests. This is the
        # actual authenticated history transport plus immutable menu selection.
        fixture = fixtures.BattleChallengeNetworkTests
        self.rpc = fixture.rpc.__get__(self)
        self.invite = fixture.invite.__get__(self)
        result = await fixture.seed_result(self)
        menu = PlayerMenu(self.companions[0]); await menu.refresh()
        await self.click(menu, "Challenges")
        screen = await self.click(menu, "Recent battle results")
        label = "Win" if result["players"].index(self.players[0].player_id) == 0 else "Loss"
        self.assertEqual(screen.rows[0].label, f"1v1 {label} #1")
        screen = await self.click(menu, screen.rows[0].label)
        self.assertEqual(screen.status, "Team 1 won")
        self.assertEqual(len(screen.rows), 2)
        self.assertTrue(all(row.action == 0 for row in screen.rows))
