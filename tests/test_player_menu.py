import unittest
import unittest.mock
from types import SimpleNamespace

from emerald_multiplayer.player_menu import PlayerMenu, PlayerMenuError, refusal_text
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
        self.assertIn("Leave team...", [r.label for r in menus[1].screen.rows])
        screen = await self.click(menus[1], "Leave team...")                 # it asks first (No first)
        self.assertEqual(screen.title, "Leave the team?")
        with unittest.mock.patch("emerald_multiplayer.player_menu.ASK_GRACE_SECONDS", 0):
            await self.click(menus[1], "Yes, leave the team")
        self.assertEqual(menus[1].screen.status, "Choose a player to invite")

    async def test_no_team_page_leaves_a_destructive_row_under_the_cursor(self):
        # The game keeps its cursor row when the next screen comes (back to the top when that is shorter). With two
        # players, Invite to team rested on Cancel invitation, Team invitation on Decline invitation and Your team on
        # Leave team, each acting at once. Now none of the rows under the cursor ends anything, each of those asks
        # first, and the question's Yes is never under the cursor either: two stray presses change nothing.
        from emerald_multiplayer.player_menu import _ASKED_OPS
        from test_team_network import wait_until
        for companion in self.companions[2:]:
            await companion.close()
        await wait_until(lambda: all(len(c._players) == 2 for c in self.companions[:2]))
        a, b = PlayerMenu(self.companions[0]), PlayerMenu(self.companions[1])

        async def stray_twice(menu, label):
            """A on ``label``, then two more A presses wherever the kept cursor lands: the labels they landed on."""
            landed = []
            index = [r.label for r in menu.screen.rows].index(label)
            screen = await self.click(menu, label)
            for _ in range(2):
                row = screen.rows[index if index < len(screen.rows) else 0] if screen.rows else None
                if row is None:
                    break
                op = menu._actions.get(row.action, ("", ()))[0]
                self.assertNotIn(op, _ASKED_OPS, (label, row.label))
                landed.append(row.label)
                if not row.action:
                    break
                index = [r.label for r in screen.rows].index(row.label)
                screen = await menu.choose(screen.revision, row.action)
            return landed

        await a.refresh(); await self.click(a, "Trainer 1")
        self.assertEqual(await stray_twice(a, "Invite to team"), ["Cancel invitation...", "B or No keeps it"])
        self.assertEqual(len(self.server.team_desk._invitations), 1)            # still invited
        await b.refresh()
        self.assertEqual(await stray_twice(b, "Team invitation"), ["Decline invitation...", "B or No keeps it"])
        self.assertEqual(len(self.server.team_desk._invitations), 1)
        await b.choose(b.screen.revision, 7)                                     # B on the question: No
        await self.click(b, "Accept invitation")
        while b.screen.back:
            await b.choose(b.screen.revision, b.screen.back)
        self.assertEqual(await stray_twice(b, "Your team"), ["Leave team...", "B or No keeps it"])
        self.assertIsNotNone((await self.companions[1].team_rpc("status"))["result"]["team"])   # still a team

    async def test_changed_menu_and_double_click_cannot_repeat_mutation(self):
        menu = PlayerMenu(self.companions[0]); await menu.refresh()
        screen = await self.click(menu, "Trainer 1")
        action = next(r.action for r in screen.rows if r.label == "Invite to team")
        await menu.choose(screen.revision, action)
        with self.assertRaises(PlayerMenuError): await menu.choose(screen.revision, action)
        self.assertEqual(len(self.server.team_desk._invitations), 1)

    async def test_challenge_consent_is_exact_and_does_not_start_native_battle(self):
        a, b = (PlayerMenu(self.companions[i]) for i in (0, 1))
        await a.refresh(); await self.click(a, "Trainer 1"); await self.click(a, "Rival Battle - 1v1")
        await b.refresh(); await self.click(b, "Pending challenge")
        await self.click(b, "Accept challenge")
        self.assertEqual(b.screen.status, "Waiting for battle coordinator")
        room = next(iter(self.server.battle_desk._active.values()))
        self.assertEqual(len(room.consent), 2)
        self.assertFalse(room.bind_intent)

    async def test_cancel_asks_and_a_yes_in_the_moment_it_asked_cancels_nothing(self):
        import emerald_multiplayer.player_menu as player_menu
        a, b = (PlayerMenu(self.companions[i]) for i in (0, 1))
        await a.refresh(); await self.click(a, "Trainer 1"); await self.click(a, "Rival Battle - 1v1")
        await b.refresh(); await self.click(b, "Pending challenge")
        screen = await self.click(b, "Cancel challenge...")
        self.assertEqual(screen.title, "Cancel the challenge?")
        self.assertEqual([row.label for row in screen.rows], ["No, keep it", "Yes, cancel challenge"])
        self.assertEqual(b._actions[screen.back], ("ask_no", ()))            # B is No
        screen = await self.click(b, "Yes, cancel challenge")              # the press that asked, repeated: nothing
        self.assertEqual(screen.title, "Cancel the challenge?")
        self.assertTrue(self.server.battle_desk._active)
        screen = await self.click(b, "No, keep it")
        self.assertIn("Accept challenge", [row.label for row in screen.rows])
        await self.click(b, "Cancel challenge...")
        with unittest.mock.patch.object(player_menu, "ASK_GRACE_SECONDS", 0):
            screen = await self.click(b, "Yes, cancel challenge")
        self.assertEqual(screen.status, "Challenge cancelled")
        self.assertFalse(self.server.battle_desk._active)

    async def test_a_challenge_to_a_trainer_with_no_pokemon_yet_is_refused_where_it_was_made(self):
        # Update 32: a new character has no Pokemon until it claims its starter in Birch's lab.
        from emerald_multiplayer.battle_desk import BattleError
        desk = self.server.battle_desk
        for code, notice in (("peer_no_pokemon", "They have no Pokemon yet"), ("no_pokemon", "Get a Pokemon in Birch's lab")):
            with self.subTest(code=code):
                def refuse(*args, code=code, **kwargs):
                    raise BattleError(code, "a trainer has no Pokemon yet")
                desk._invite = refuse
                menu = PlayerMenu(self.companions[0]); await menu.refresh()
                await self.click(menu, "Trainer 1")
                screen = await self.click(menu, "Rival Battle - 1v1")
                self.assertEqual(screen.status, notice)
                self.assertIn("Rival Battle - 1v1", [row.label for row in screen.rows])  # still on the player's page
                self.assertFalse(desk._active)

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
        self.assertEqual(screen.status, "Connection interrupted")
        self.assertFalse(screen.rows)

    async def test_disabled_services_keep_read_only_card_but_no_mutation_buttons(self):
        self.server.team_desk = self.server.battle_desk = None
        menu = PlayerMenu(self.companions[0]); await menu.refresh()
        screen = await self.click(menu, "Trainer 1")
        # The player's status first (no game reports a position in this fixture), not selectable.
        self.assertEqual([row.label for row in screen.rows], ["Joining", "View Trainer Card"])
        self.assertEqual(screen.rows[0].action, 0)

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
        self.assertEqual(len(screen.rows), 3)
        self.assertTrue(all(row.action == 0 for row in screen.rows[:2]))
        self.assertEqual(screen.rows[2].label, "Back to matching results")

    async def test_free_for_all_is_offered_to_all_four_and_each_trainer_accepts_for_themselves(self):
        menus = [PlayerMenu(c) for c in self.companions]
        await menus[0].refresh()
        await self.click(menus[0], "Challenges")
        await self.click(menus[0], "New battle")
        self.assertFalse(self.companions[0].config.battle_ffa_enabled)     # the fixture ROM has no free-for-all marker
        self.assertNotIn("Free-for-All - 4 Players", [row.label for row in menus[0].screen.rows])
        for companion in self.companions:
            object.__setattr__(companion.config, "battle_ffa_enabled", True)
        await menus[0].refresh()
        if "New battle" in [row.label for row in menus[0].screen.rows]:
            await self.click(menus[0], "New battle")
        screen = await self.click(menus[0], "Free-for-All - 4 Players")
        self.assertEqual(screen.title, "Free-for-All: 4 Players")
        labels = [row.label for row in screen.rows]
        self.assertFalse([label for label in labels if label.startswith("Wager")])    # no wager in a free-for-all
        self.assertIn("Cancel challenge...", labels)
        self.assertNotIn("Accept challenge", labels)                                   # the challenger's consent is given
        for i in (1, 2, 3):
            await menus[i].refresh()
            screen = await self.click(menus[i], "Pending challenge")
            self.assertEqual(screen.title, "Free-for-All: 4 Players")
            self.assertIn("Accept challenge", [row.label for row in screen.rows])
            await self.click(menus[i], "Accept challenge")
        pending = await self.companions[0].battle_challenge_rpc("pending")
        self.assertEqual(pending["result"][0]["state"], "accepted")
        self.assertEqual(pending["result"][0]["mode"], 5)

    async def test_with_four_connected_a_free_for_all_names_everyone_or_two_of_the_three_others(self):
        """Update 32: the 1v1v1. With four trainers connected the Free-for-All page offers everyone (1v1v1v1) or a
        three-trainer free-for-all with any two of the other three; only the invited two see the challenge."""
        menus = [PlayerMenu(c) for c in self.companions]
        for companion in self.companions:
            object.__setattr__(companion.config, "battle_ffa_enabled", True)
            object.__setattr__(companion.config, "battle_ffa3_enabled", True)
        await menus[0].refresh()
        await self.click(menus[0], "Challenges")
        await self.click(menus[0], "New battle")
        self.assertNotIn("Free-for-All - 4 Players", [row.label for row in menus[0].screen.rows])
        screen = await self.click(menus[0], "Free-for-All")
        self.assertEqual(screen.title, "Free-for-All")
        labels = [row.label for row in screen.rows]
        self.assertEqual(labels[0], "Everyone: 4 Players")
        pairs = [label for label in labels if label.startswith("With ")]
        self.assertEqual(len(pairs), 3)                                  # the three pairs of the other three
        screen = await self.click(menus[0], pairs[0])
        self.assertEqual(screen.title, "Free-for-All: 3 Players")
        labels = [row.label for row in screen.rows]
        self.assertFalse([label for label in labels if label.startswith("Wager")])
        self.assertIn("Cancel challenge...", labels)
        pending = (await self.companions[0].battle_challenge_rpc("pending"))["result"][0]
        self.assertEqual((pending["mode"], len(pending["players"]), pending["players"][0]),
                         (6, 3, self.companions[0].config.player_id))
        invited = [i for i, c in enumerate(self.companions) if c.config.player_id in pending["players"][1:]]
        left_out = [i for i in (1, 2, 3) if i not in invited]
        self.assertEqual(len(invited), 2)
        await menus[left_out[0]].refresh()
        self.assertNotIn("Pending challenge", [row.label for row in menus[left_out[0]].screen.rows])
        for i in invited:
            await menus[i].refresh()
            screen = await self.click(menus[i], "Pending challenge")
            self.assertEqual(screen.title, "Free-for-All: 3 Players")
            await self.click(menus[i], "Accept challenge")
        pending = (await self.companions[0].battle_challenge_rpc("pending"))["result"][0]
        self.assertEqual((pending["state"], pending["mode"]), ("accepted", 6))

    async def test_an_older_game_offers_no_1v1v1(self):
        menus = [PlayerMenu(c) for c in self.companions]
        for companion in self.companions:
            object.__setattr__(companion.config, "battle_ffa_enabled", True)
        await menus[0].refresh()
        await self.click(menus[0], "Challenges")
        await self.click(menus[0], "New battle")
        labels = [row.label for row in menus[0].screen.rows]
        self.assertIn("Free-for-All - 4 Players", labels)               # the four-player row as before
        self.assertNotIn("Free-for-All", labels)

    async def test_history_stays_reachable_when_new_battles_are_disabled(self):
        fixture = fixtures.BattleChallengeNetworkTests
        self.rpc = fixture.rpc.__get__(self)
        self.invite = fixture.invite.__get__(self)
        await fixture.seed_result(self)
        self.server.battle_desk = None
        menu = PlayerMenu(self.companions[0])
        screen = await menu.refresh()
        self.assertEqual(len(screen.rows), 6)  # Three peers, team, history, refresh.
        self.assertNotIn("Challenges", [row.label for row in screen.rows])
        await self.click(menu, "Battles and records")
        screen = await self.click(menu, "Recent battle results")
        self.assertEqual(len(screen.rows), 2)
        self.assertIn("#1", screen.rows[0].label)
        self.assertEqual(screen.rows[1].label, "Filters and refresh")
        await menu.choose(screen.revision, 7)
        screen = await self.click(menu, "Trainer 1")
        self.assertNotIn("Rival Battle - 1v1", [row.label for row in screen.rows])


class PlayerMenuChallengeStatusTests(PlayerMenuNetworkTests):
    async def test_a_challenge_that_ends_unstarted_says_why(self):
        # Seen 2026-10-20: a save after accepting ended the challenge and it vanished from both menus without a word.
        a, b = (PlayerMenu(self.companions[i]) for i in (0, 1))
        await a.refresh(); await self.click(a, "Trainer 1"); await self.click(a, "Rival Battle - 1v1")
        self.assertEqual(a.screen.title, "Rival Battle - 1v1")
        self.assertEqual(a.screen.status, "Waiting for opponent")
        await b.refresh(); await self.click(b, "Pending challenge")
        self.assertEqual(b.screen.status, "Trainer 0 challenges you")
        room = next(iter(self.server.battle_desk._active.values()))
        self.server.battle_desk._abort(room, "canonical_changed")
        screen = await b.refresh()
        self.assertEqual(screen.status, "Cancelled: a party was saved")
        self.assertNotIn("Accept challenge", [row.label for row in screen.rows])
        self.assertEqual((await a.refresh()).status, "Cancelled: a party was saved")

    async def test_an_enter_refused_after_the_challenge_ended_says_why(self):
        # KNOWN_ISSUES MS-60 (L stale-save-1): the other trainer's Enter was refused (its game not saved) and the
        # challenge ended; this menu still showed its Enter (a displayed Enter screen is never refreshed underneath), so
        # the player pressed it and the host answered battle_not_ready. The menu then says why the challenge ended.
        a, b = (PlayerMenu(self.companions[i]) for i in (0, 1))
        await a.refresh(); await self.click(a, "Trainer 1"); await self.click(a, "Rival Battle - 1v1")
        await b.refresh(); await self.click(b, "Pending challenge")
        room = next(iter(self.server.battle_desk._active.values()))
        self.server.battle_desk._abort(room, "save_needed")
        b.notice(refusal_text("battle_not_ready"))         # what MenuSession._release_refused shows first
        self.assertEqual((await b.refresh()).status, "Cancelled: a trainer must save")
        a.notice(refusal_text("character_busy"))           # a refusal about this game itself stays
        self.assertEqual((await a.refresh()).status, "Busy saving: try again shortly")

    async def test_a_refused_trainer_reads_its_reason_while_the_other_leaves_the_challenge(self):
        # L stale-save-4: the refused trainer's menu read "Battle needs recovery" while the trainer who had entered
        # cancelled its entry (recovery_required); its own reason comes first, the state otherwise.
        a, b = (PlayerMenu(self.companions[i]) for i in (0, 1))
        await a.refresh(); await self.click(a, "Trainer 1"); await self.click(a, "Rival Battle - 1v1")
        await b.refresh(); await self.click(b, "Pending challenge")
        self.server.battle_desk._recover(next(iter(self.server.battle_desk._active.values())), "save_needed")
        self.assertEqual((await b.refresh()).status, "Battle needs recovery")
        b.notice(refusal_text("save_needed"))
        self.assertEqual((await b.refresh()).status, "Not saved: close menu to save")


class PlayerMenuAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.companion = SimpleNamespace(config=SimpleNamespace(menu_abi_version=2,
            battle_resume_abi_version=1, emergency_save_abi_version=2), connected=True,
            world_id="world", server_epoch=1, session_epoch=2)
        for name in ("handoff", "capture_battle", "prepare_battle", "abandon_battle_preparation"):
            setattr(self.companion, "_native_menu_" + name, lambda *args: None)
        self.menu = PlayerMenu(self.companion)
        self.menu._binding = ("world", 1, 2)
        self.menu._page = ("battles", None)
        self.battle = dict(battle_id="id", generation=1, fingerprint="accepted",
            state="accepted", players=["a", "b"], consent=["a", "b"])
        self.menu._battles = [self.battle]
        self.actions = [("Cancel", "battle_cancel", ("id", 1)),
                        ("Enter battle", "battle_enter", ("id", 1, "accepted"))]

    def test_only_explicit_enter_row_is_marked_and_capability_changes_generation(self):
        screen = self.menu._show("Battle", "Accepted", self.actions)
        self.assertEqual(screen.admission_action, 2)
        self.assertEqual(self.menu._show("Battle", "Accepted", self.actions), screen)
        self.companion.config.battle_resume_abi_version = 0
        changed = self.menu._show("Battle", "Accepted", self.actions)
        self.assertGreater(changed.revision, screen.revision)
        self.assertEqual(changed.admission_action, 0)

    def test_exact_native_selection_preserves_original_descriptor_after_host_loss_once(self):
        screen = self.menu._show("Battle", "Accepted", self.actions)
        self.companion.connected = False
        self.companion.world_id = self.companion.server_epoch = self.companion.session_epoch = None
        captured = self.menu.claim_battle_admission(screen.revision, screen.admission_action)
        self.assertEqual(captured, self.battle)
        self.battle["players"].append("c")
        self.assertEqual(captured["players"], ["a", "b"])
        with self.assertRaises(PlayerMenuError):
            self.menu.claim_battle_admission(screen.revision, screen.admission_action)

    def test_unmarked_cancel_stale_revision_and_incomplete_consent_never_claim(self):
        screen = self.menu._show("Battle", "Accepted", self.actions)
        for revision, action in ((screen.revision, 1), (screen.revision + 1, 2), (screen.revision, True)):
            with self.subTest(revision=revision, action=action), self.assertRaises(PlayerMenuError):
                self.menu.claim_battle_admission(revision, action)
        self.battle["consent"] = ["a"]
        with self.assertRaises(PlayerMenuError): self.menu.claim_battle_admission(screen.revision, 2)


class PlayerMenuEnterTests(PlayerMenuAdmissionTests):
    """Enter battle is offered only when this game's launcher could admit it; otherwise the reason is shown, so the
    game never latches an Enter that must be refused (the owner's report of 2026-10-20)."""

    def render(self, actor="a", **battle):
        self.companion.config.player_id = actor
        self.menu._players = {"a": "Ann", "b": "Bob", "c": "Cy", "d": "Di"}
        self.battle.update(dict(mode=2, sender="a", checkpoints=[dict(player_id=p, party_count=1)
                                                                 for p in self.battle["players"]]), **battle)
        return self.menu._render()

    def test_enter_offered_only_when_the_launcher_could_admit(self):
        screen = self.render()
        self.assertEqual((screen.title, screen.status), ("Rival Battle - 1v1", "Opponent accepted"))
        self.assertIn("Enter battle", [row.label for row in screen.rows])
        self.companion._native_menu_battle_blocker = lambda battle: "save_recovery_required"
        screen = self.render()
        self.assertEqual(screen.status, "Saving stopped: restart game")
        self.assertNotIn("Enter battle", [row.label for row in screen.rows])
        self.assertIn("Cancel challenge...", [row.label for row in screen.rows])
        self.assertEqual(screen.admission_action, 0)
        self.companion._native_menu_battle_blocker = lambda battle: None
        self.assertIn("Enter battle", [row.label for row in self.render().rows])

    def test_the_row_accept_leaves_under_the_cursor_enters_and_never_cancels(self):
        # The owner's report of 2026-10-24: "when clicking start battle it shows battle, however when clicked again it
        # kicks us out back to start". The game keeps its cursor row on the next screen: Accept challenge's row became
        # Cancel challenge once accepted. Now it becomes Enter battle (or a row that does nothing), and Cancel asks.
        def rows(screen):
            return [(row.label, self.menu._actions.get(row.action, ("", ()))[0]) for row in screen.rows]
        before = self.render(actor="b", consent=["a"], state="invited")
        index = [label for label, _ in rows(before)].index("Accept challenge")
        after = self.render(actor="b", consent=["a", "b"], state="accepted")
        self.assertEqual(rows(after)[index], ("Enter battle", "battle_enter"))
        self.assertEqual(after.admission_action, after.rows[index].action)
        self.companion._native_menu_battle_blocker = lambda battle: "save_recovery_required"
        blocked = self.render(actor="b", consent=["a", "b"], state="accepted")
        self.assertEqual(blocked.rows[index].action, 0)                    # a row that does nothing
        waiting = self.render(actor="a", consent=["a"], state="invited")    # the challenger before the answer
        self.assertEqual(waiting.rows[index].action, 0)
        for screen in (after, blocked, waiting):
            ops = [op for _, op in rows(screen)]
            self.assertNotIn("battle_cancel", ops)
            self.assertIn("ask", ops)                                       # Cancel challenge... asks first

    def test_pending_statuses_say_who_is_awaited(self):
        self.assertEqual(self.render(consent=["a"]).status, "Waiting for opponent")
        self.assertEqual(self.render(actor="b", consent=["a"], state="invited").status, "Ann challenges you")
        four = dict(mode=3, players=["a", "b", "c", "d"])
        self.assertEqual(self.render(consent=["a", "b"], state="invited", **four).status,
                         "Waiting for remaining players")
        screen = self.render(consent=["a", "b", "c", "d"], **four)
        self.assertEqual((screen.title, screen.status), ("Rival Battle - 2v2", "All players ready"))
        self.assertEqual(self.render(consent=["a", "b", "c", "d"], state="starting", **four).status, "Starting battle")
        self.assertEqual(self.render(mode=5, consent=["a", "b", "c", "d"], players=["a", "b", "c", "d"]).title,
                         "Free-for-All: 4 Players")
