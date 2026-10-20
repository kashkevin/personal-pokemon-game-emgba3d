"""Update 32: START > PLAYER > RESET in a world, and the in-game banner the launcher uses to say what it did.

The game restarts from the character's host save in the same launcher session (the world, a host's server and the
other players carry on); it is refused while a trade, a challenge, a battle or a save is unresolved.
"""
import asyncio
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from uuid import uuid4

from emerald_multiplayer.bridge_config import configure_native, menu_open_page_enabled
from emerald_multiplayer.bridge_protocol import BridgeOutbox
from emerald_multiplayer.launcher_session import GameInstallation, LauncherSession
from emerald_multiplayer.menu_mailbox import MenuRequest, unpack_screen
from emerald_multiplayer.menu_session import MenuSession
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.player_menu import MenuRow, MenuScreen, PlayerMenu, save_age, soft_reset_refusal

TOKEN = "ab" * 32


class OpenPageCodecTests(unittest.TestCase):
    def test_an_open_may_name_the_soft_reset_page_and_nothing_else(self):
        self.assertEqual(MenuRequest.unpack(MenuRequest(4, 0, 1, 1).pack()), MenuRequest(4, 0, 1, 1))
        for request in (MenuRequest(4, 0, 2, 1), MenuRequest(4, 0, 7, 1), MenuRequest(4, 0, 1, 3),
                        MenuRequest(4, 3, 1, 1)):
            with self.subTest(request=request), self.assertRaises(ValueError):
                request.pack()

    def test_the_launcher_opts_in_only_beside_the_players_menu_abi_2(self):
        manifest = dict(menu_open_page_abi_version=1, menu_abi_version=2)
        self.assertTrue(menu_open_page_enabled(manifest))
        self.assertEqual(configure_native(manifest, TOKEN, 9).splitlines()[2:], ["menu_open_page=1"])
        for other in (dict(manifest, menu_abi_version=1), dict(manifest, menu_open_page_abi_version=2),
                      dict(manifest, menu_open_page_abi_version=True), dict(menu_abi_version=2)):
            with self.subTest(manifest=other):
                self.assertFalse(menu_open_page_enabled(other))
                self.assertEqual(configure_native(other, TOKEN, 9), f"port=9\ntoken={TOKEN}\n")

    def test_page_texts_fit_the_game_window(self):
        for seconds in (None, -1, 0, 59, 60, 3599, 3600, 10 ** 9):
            self.assertLessEqual(len(save_age(seconds)), 25)
        self.assertEqual(save_age(None), "Host save: at game start")
        self.assertEqual(save_age(125), "Host save: 2 min ago")
        for code in ("trade_pending", "challenge_pending", "battle_pending", "character_busy", "unknown"):
            self.assertLessEqual(len(soft_reset_refusal(code)), 31)


class FakeMenu:
    def __init__(self):
        self.screen = MenuScreen(1, "Players", "Ready", (MenuRow(1, "Accept"),), 0)
        self.pages = []
        self.handoff = None

    async def refresh(self):
        return self.screen

    async def open_page(self, page):
        self.pages.append(page)
        return replace(self.screen, title="Soft reset")


class OpenPageSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.closed = False
        def close(): self.closed = True
        self.bridge = SimpleNamespace(outbox=BridgeOutbox(), writer=SimpleNamespace(close=close))
        self.companion = SimpleNamespace(_bridge=self.bridge, config=SimpleNamespace(menu_open_page_abi_version=1))
        self.session = MenuSession(self.companion, self.bridge)
        self.session.menu = FakeMenu()

    async def asyncTearDown(self):
        await self.session.close()

    async def test_the_named_page_opens(self):
        self.session.feed(MenuRequest(1, 0, 1, 1).pack())
        await self.session._task
        frame = await asyncio.wait_for(self.bridge.outbox.get(), 1)
        sequence, screen, close = unpack_screen(frame[5:])
        self.assertEqual((sequence, screen.title, close), (1, "Soft reset", False))
        self.assertEqual(self.session.menu.pages, ["soft_reset"])

    async def test_a_page_the_launcher_did_not_enable_is_a_protocol_error(self):
        self.companion.config.menu_open_page_abi_version = 0
        with self.assertRaises(ValueError):
            self.session.feed(MenuRequest(1, 0, 1, 1).pack())
        self.assertEqual(self.session.menu.pages, [])
        self.assertIsNone(self.session._task)
        self.assertEqual(self.session.sequence, 0)

    async def test_the_choice_is_handed_to_the_launcher_after_the_menu_closed(self):
        calls = []
        async def handoff(kind, value, owner):
            calls.append((kind, value))
        self.companion._native_menu_handoff = handoff
        self.session.feed(MenuRequest(1, 0, 1, 1).pack())
        await self.session._task
        await self.bridge.outbox.get()
        async def choose(screen, action):
            self.session.menu.handoff = ("soft_reset", {})
            return replace(self.session.menu.screen, revision=2, rows=())
        self.session.menu.choose = choose
        self.session.feed(MenuRequest(2, 1, 1, 2).pack())
        frame = await asyncio.wait_for(self.bridge.outbox.get(), 1)
        self.assertTrue(unpack_screen(frame[5:])[2])      # CLOSE first
        self.assertEqual(calls, [])
        self.session.feed(MenuRequest(3, 0, 0, 3).pack())   # the game's close acknowledgment
        await self.session._task
        self.assertEqual(calls, [("soft_reset", {})])


import test_battle_challenge_network as network


class SoftResetPageTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = network.BattleChallengeNetworkTests.asyncSetUp
    asyncTearDown = network.BattleChallengeNetworkTests.asyncTearDown

    async def click(self, menu, label):
        screen = menu.screen
        return await menu.choose(screen.revision, next(row.action for row in screen.rows if row.label == label))

    def page(self, i=0, blocker=None, last_save=125.0):
        companion = self.companions[i]
        companion._native_menu_reset_blocker = lambda: blocker
        companion._native_menu_last_save = lambda: last_save
        return PlayerMenu(companion)

    async def test_the_reset_is_confirmed_then_handed_to_the_launcher(self):
        menu = self.page()
        screen = await menu.open_page("soft_reset")
        self.assertEqual((screen.title, screen.status, screen.back), ("Soft reset", "Back to your last host save", 0))
        self.assertEqual([(row.label, bool(row.action)) for row in screen.rows],
                         [("Unsaved progress is lost", False), ("Host save: 2 min ago", False),
                          ("Reset to last host save", True), ("Save on host now", True)])
        screen = await self.click(menu, "Reset to last host save")
        self.assertEqual((screen.title, screen.status), ("Reset the game?", "Unsaved progress will be lost"))
        self.assertEqual([row.label for row in screen.rows], ["No, go back", "Yes, reset now"])
        self.assertEqual((await menu.choose(screen.revision, screen.back)).title, "Soft reset")   # B: back
        await self.click(menu, "Reset to last host save")
        screen = await self.click(menu, "No, go back")
        self.assertEqual(screen.title, "Soft reset")
        await self.click(menu, "Reset to last host save")
        self.assertIsNone(menu.handoff)
        screen = await self.click(menu, "Yes, reset now")
        self.assertEqual(menu.handoff, ("soft_reset", {}))
        self.assertEqual(screen.rows, ())

    async def test_save_on_host_now_is_the_launchers_save(self):
        menu = self.page(last_save=None)
        screen = await menu.open_page("soft_reset")
        self.assertEqual(screen.rows[1].label, "Host save: at game start")
        await self.click(menu, "Save on host now")
        self.assertEqual(menu.handoff, ("host_save", {}))

    async def test_an_open_challenge_or_trade_or_a_busy_launcher_has_no_reset_row(self):
        challenger = PlayerMenu(self.companions[1])
        await challenger.refresh()
        await self.click(challenger, "Trainer 0")
        await self.click(challenger, "Rival Battle - 1v1")
        menu = self.page()
        screen = await menu.open_page("soft_reset")
        self.assertEqual(screen.status, "Cancel your challenge first")
        labels = [row.label for row in screen.rows]
        self.assertNotIn("Reset to last host save", labels)
        self.assertIn("Save on host now", labels)
        for blocker, status in (("character_busy", "Busy saving: try again shortly"),
                                ("battle_pending", "Finish the battle first"),
                                ("save_recovery_required", "Saving stopped: restart game")):
            with self.subTest(blocker=blocker):
                menu = self.page(blocker=blocker)
                screen = await menu.open_page("soft_reset")
                self.assertEqual(screen.status, status)
                self.assertNotIn("Reset to last host save", [row.label for row in screen.rows])

    async def test_a_reset_that_became_blocked_cannot_be_confirmed(self):
        reason = [None]
        companion = self.companions[0]
        companion._native_menu_reset_blocker = lambda: reason[0]
        menu = PlayerMenu(companion)
        await menu.open_page("soft_reset")
        await self.click(menu, "Reset to last host save")
        reason[0] = "character_busy"
        screen = await menu.refresh()
        self.assertEqual((screen.title, screen.status), ("Soft reset", "Busy saving: try again shortly"))
        self.assertNotIn("Yes, reset now", [row.label for row in screen.rows])

    async def test_a_game_without_the_launcher_hook_is_never_offered_a_reset(self):
        menu = PlayerMenu(self.companions[0])        # no _native_menu_reset_blocker: an older launcher
        screen = await menu.open_page("soft_reset")
        self.assertEqual(screen.status, "Your game is busy: try again")
        self.assertNotIn("Reset to last host save", [row.label for row in screen.rows])


class LocalNoticeTests(unittest.TestCase):
    """The banner goes through the game's world inbound record, as the host's notices do."""

    def companion(self):
        from emerald_multiplayer.companion import Companion
        c = Companion.__new__(Companion)
        c.config = SimpleNamespace(player_id="me", rival_abi_version=0)
        c.connected, c._roster_signature, c._players = True, (), [dict(player_id="me", presence=None)]
        c._world_action_ack, c._world_clock, c._world_event, c._world_wallet = 0, None, None, None
        c._world_teammate = c._world_extras = c._world_rival = None
        c._world_notice, c._local_notice, c._local_notice_id = None, None, 0
        return c

    @staticmethod
    def published(c):
        inbound = c.world_inbound()
        return inbound.notice_id, inbound.notice_text

    def test_a_local_notice_shows_until_the_hosts_next_notice(self):
        c = self.companion()
        c._world_notice = dict(id=5, text="Outbreak", to=None)
        self.assertEqual(self.published(c), (5, "Outbreak"))
        c.show_local_notice("Saved on the host.")
        local_id, text = self.published(c)
        self.assertTrue(local_id & 0x80000000)          # never one of the host's ids
        self.assertEqual(text, "Saved on the host.")
        c._world_notice = None                           # a reconnect: the host has not sent its notice again yet
        self.assertEqual(self.published(c), (local_id, "Saved on the host."))
        c._world_notice = dict(id=5, text="Outbreak", to=None)
        self.assertEqual(self.published(c), (local_id, "Saved on the host."))   # not shown twice
        c._world_notice = dict(id=6, text="Event", to=None)
        self.assertEqual(self.published(c), (6, "Event"))
        self.assertIsNone(c._local_notice)
        c.show_local_notice("Again.")
        self.assertNotEqual(self.published(c)[0], local_id)   # a new banner is a new id

    def test_a_stale_local_notice_is_dropped(self):
        c = self.companion()
        c.show_local_notice("Reset.", seconds=-1)
        self.assertEqual(self.published(c), (0, ""))

    def test_another_players_notice_is_not_this_ones(self):
        c = self.companion()
        c._world_notice = dict(id=9, text="For someone else", to=["other"])
        self.assertEqual(self.published(c), (0, ""))


class LauncherSoftResetTests(unittest.IsolatedAsyncioTestCase):
    """The launcher side, with a stand-in companion and a real child process as the game."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        installation = GameInstallation(self.root / "game.gba", self.root / "manifest.json", "a" * 64, "b" * 64, None)
        self.session = s = LauncherSession(installation, self.root, world_directory=self.root / "world",
                                           bind_address="127.0.0.1")
        self.notices, self.challenges, self.trades = [], [], []

        async def challenge(operation, **fields):
            return dict(result=list(self.challenges))

        async def trade(operation, **fields):
            return dict(proposals=list(self.trades))
        self.bridge = object()
        self.c = c = SimpleNamespace(connected=True, world_id=str(uuid4()), server_epoch=3, session_epoch=7,
            save_profile=OWNERSHIP_PROFILE, config=SimpleNamespace(player_id=str(uuid4()), build_id="a" * 64,
            ruleset_id="rules", trade_enabled=True), _bridge=self.bridge, battle_challenge_rpc=challenge,
            trade_rpc=trade, _emergency_controller=None, _emergency_authority=None,
            show_local_notice=self.notices.append)
        s._companion = c
        s._binding = s._signature()
        s._profile_directory = self.root / "profile"
        s._profile_directory.mkdir()
        s._open = True
        s._revision = 2
        self.menu = SimpleNamespace(bridge=self.bridge)

    async def game(self):
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(60)")
        self.addAsyncCleanup(self.stop, process)
        self.session._game = SimpleNamespace(process=process)
        return process

    @staticmethod
    async def stop(process):
        if process.returncode is None:
            process.kill()
            await process.wait()

    async def test_the_reset_closes_the_game_for_play_to_open_it_again_from_the_host_save(self):
        process = await self.game()
        s = self.session
        self.assertIsNone(s._native_menu_reset_blocker())
        await s._native_menu_handoff("soft_reset", {}, self.menu)
        task = s._soft_reset_task
        self.assertIs(s._interaction, task)                 # taken at once: nothing else starts in between
        self.assertIsNotNone(task)
        await task
        self.assertIsNotNone(process.returncode)
        self.assertTrue(s._soft_reset_pending)
        self.assertEqual(s.status.code, "soft_resetting")
        self.assertIsNone(s._interaction)
        self.assertEqual(self.notices, ["Reset to your last host save.|Later progress was discarded."])
        s._game, self.c._bridge = None, None                 # the closed game's bridge has wound down
        await s._restart_after_abandon()                     # what play() does next
        self.assertFalse(s._soft_reset_pending)
        self.assertTrue(s._reset_at_start)                  # the next game's first status is soft_reset_done
        self.assertIsNone(s._soft_reset_task)

    async def test_an_open_challenge_or_trade_refuses_and_keeps_the_game(self):
        process = await self.game()
        for opened, reason in ((self.challenges, "Cancel your challenge first"), (self.trades, "Finish the trade first")):
            with self.subTest(reason=reason):
                opened.append(dict(battle_id="b"))
                await self.session._native_menu_handoff("soft_reset", {}, self.menu)
                self.assertIsNone(self.session._soft_reset_task)
                self.assertEqual(self.session.status.code, "soft_reset_refused")
                self.assertEqual(self.notices[-1], "Cannot reset now:|" + reason)
                self.assertIsNone(process.returncode)
                opened.clear()

    async def test_unresolved_records_or_a_running_save_refuse(self):
        process = await self.game()
        s = self.session
        (s._profile_directory / "pending-trade.json").write_text("{}")
        self.assertEqual(s._native_menu_reset_blocker(), "character_recovery_pending")
        (s._profile_directory / "pending-trade.json").unlink()
        s._save_task = asyncio.get_running_loop().create_future()
        self.assertEqual(s._native_menu_reset_blocker(), "character_busy")
        await s._native_menu_handoff("soft_reset", {}, self.menu)
        self.assertEqual(self.notices[-1], "Cannot reset now:|Busy saving: try again shortly")
        s._save_task.set_result(True)
        s._save_failed = True
        self.assertEqual(s._native_menu_reset_blocker(), "save_recovery_required")
        s._save_failed = False
        s._battle_retained = ("held",)
        self.assertEqual(s._native_menu_reset_blocker(), "battle_pending")
        s._battle_retained = None
        self.c.connected = False
        self.assertEqual(s._native_menu_reset_blocker(), "session_changed")
        self.assertIsNone(process.returncode)

    async def test_an_unreadable_host_list_is_a_refusal_never_a_reset(self):
        process = await self.game()
        async def broken(operation, **fields):
            raise ConnectionError("host gone")
        self.c.battle_challenge_rpc = broken
        await self.session._native_menu_handoff("soft_reset", {}, self.menu)
        self.assertIsNone(self.session._soft_reset_task)
        self.assertEqual(self.notices[-1], "Cannot reset now:|Connection interrupted: wait")
        self.assertIsNone(process.returncode)

    async def test_a_save_that_started_meanwhile_finishes_and_the_reset_is_refused(self):
        process = await self.game()
        s = self.session
        (s._profile_directory / "pending-export.json").write_text("{}")   # an export still being written
        task = asyncio.ensure_future(s._soft_reset(s._game))
        s._interaction = s._soft_reset_task = task
        await task
        self.assertIsNone(process.returncode)
        self.assertFalse(s._soft_reset_pending)
        self.assertIsNone(s._soft_reset_task)
        self.assertEqual(s.status.code, "soft_reset_refused")

    async def test_save_on_host_now_reports_in_the_game(self):
        await self.game()
        s = self.session
        results = []
        async def save():
            results.append("saved")
            return True
        s.save = save
        await s._native_menu_handoff("host_save", {}, self.menu)
        self.assertEqual(results, ["saved"])
        self.assertEqual(self.notices[-1], "Saved on the host.|RESET goes back to here.")
        async def refused():
            return False
        s.save = refused
        await s._native_menu_handoff("host_save", {}, self.menu)
        self.assertEqual(self.notices[-1], "Could not save on the host.|See the launcher window.")

    async def test_the_page_shows_how_old_the_host_save_is(self):
        await self.game()
        s = self.session
        s._saved_revision, s._saved_at = 2, None
        self.assertIsNone(s._native_menu_last_save())
        from emerald_multiplayer.launcher_session import SessionState
        s._publish(SessionState.RUNNING, "saved", revision=3)
        self.assertLess(s._native_menu_last_save(), 5)


if __name__ == "__main__":
    unittest.main()
