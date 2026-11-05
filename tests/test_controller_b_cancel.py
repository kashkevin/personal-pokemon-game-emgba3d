"""B is Cancel, and no confirmation of a multiplayer action can be confirmed with it (owner decision #43, 2026-11-05;
docs/owner-decisions.md #21 and #43).

Since Update 24 the engine maps an Xbox pad's right face button (B) to the game's B, as the keyboard's B key and the
pad's X already were (engine src/platform/gamepad.c; its self-test, --selftest-keybinds: "pad B (right face) is also
the B button"), and the pre-game menu window takes the pad's B as Back, as Esc (engine src/platform/shell_menu.c). The
app has no controller code of its own, so B reaches it in exactly three ways, and these tests check that none of them
confirms anything:

* the pre-game menu (shell_app.ShellApp): the event "back", which every question answers No and every page treats as
  Back (ShellApp.confirm is the menu's one question: its Yes is a row only A chooses);
* the Players menu in a world (player_menu.PlayerMenu; the game's multiplayer_menu.c Input): CHOOSE with the screen's
  Back action 7 when the screen has one, else the game closes its window. Action 7 is never a row (rows are 1-6) and
  always one of a fixed set of ways back: a question's No, a page back, the Tower's and the Championship's own page
  back, or leaving a wireless minigame's lobby before it starts;
* the held-trade window (trade_menu.NativeTradeMenu): the same action 7, which asks "Cancel the trade?" or goes back a
  page, and on that question keeps trading.

The game's own questions are engine code, read (not run) for this check; each takes its Yes only from A on YES: the
soft reset (data/scripts/mp_soft_reset.inc, NO the default), "go on to floor N?" and the co-op Gym offer (MSGBOX_YESNO,
B is NO), "Give up the battle?" (battle_controller_player.c RunForfeitPrompt: NO first, Yes only for A on YES), the
battle's yes/no box (PlayerHandleYesNoInput: B closes it) and the personal encounter's reset
(multiplayer_local_reset.c: accepted only for A on YES)."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from uuid import uuid4

from emerald_multiplayer import tower_data
from emerald_multiplayer.player_menu import _ASKED_OPS, QUESTIONS, PlayerMenu
from emerald_multiplayer.shell_protocol import ScriptedShell
from emerald_multiplayer.trade_menu import PartyChoice
from shell_fixture import BACK, LAN, Driver, FakeWorker, World, fake_drafter, fake_register, select
import test_championship_eight as championship_tests
from test_championship_eight import Fixture as ChampionshipFixture
from test_shell_app import library_character, main_exit, make_world
from test_tower_menu import DUO_VIEWS, TEAMMATE, FakeCompanion, host_view
from test_tower_rules import synthetic_data

# What the Players menu's Back (action 7) may do: go back, answer a question No, or leave a lobby before it starts.
WAYS_BACK = {"ask_no", "home", "records_back", "new_battle", "battles", "lobby", "tower_back", "champ_back", "mg_back"}
# Every page the Players menu draws (player_menu.PlayerMenu._render).
PAGES = ("home", "player", "trade", "team", "battles", "new_battle", "lobby_pick", "lobby", "lobby_2v2", "ffa", "confirm",
         "soft_reset", "soft_reset_confirm", "wager", "world", "world_players", "world_player", "world_outbreak",
         "world_event", "base", "frontier", "league", "hall", "shop", "team_pick", "extras", "coop", "habitat",
         "championship", "rival", "records", "tower", "card", "card_battles", "card_championships", "card_shared",
         "card_progress", "hunts", "hunt", "hunt_filters", "hunt_totals", "results", "result_filters", "result",
         "minigame")
# The host reads a refresh makes (nothing else may be sent when B is pressed).
READS = {("team", "status"), ("battle", "pending"), ("lobby", "status"), ("tower", "status")}


# ---------------------------------------------------------------------------------------------- the pre-game menu


class ShellBackTests(unittest.TestCase):
    """The pre-game menu: B (the event "back") never says Yes."""

    def test_b_answers_no_to_the_menus_question(self):
        world = World(self)
        app, _ = world.app(Driver(("confirm", BACK), ("confirm", BACK), ("confirm", select("yes")), ("choose", BACK)))
        self.assertFalse(app.confirm("Delete Kevin's world?", "It is moved aside.", "Delete Kevin's world", warn=True))
        self.assertFalse(app.confirm("Restore this version?", "The current save is kept.", "Restore"))
        self.assertTrue(app.confirm("Restore this version?", "The current save is kept.", "Restore"))   # A on Yes
        self.assertIsNone(app.choose("Replace a friend's code", [("slot1", "Player 2", "")]))

    def test_b_on_delete_world_keeps_the_world(self):
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()
        driver = Driver(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("delete")),
                        ("confirm", BACK), ("world", BACK), ("host_list", BACK), main_exit())
        app2, _ = world.app(driver)
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual([e.world_id for e in app2.registry.entries()], [entry.world_id])
        self.assertFalse((world.private / "worlds-deleted").exists())

    def test_b_on_delete_character_keeps_it(self):
        world = World(self)
        character = library_character(world)
        driver = Driver(("main", select("characters")), ("characters", select("c:" + character.character_id)),
                        ("character", select("delete")), ("confirm", BACK), ("character", BACK), ("characters", BACK),
                        main_exit())
        app, _ = world.app(driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual([c.character_id for c in app.library.all()], [character.character_id])

    def test_b_on_replacing_a_friends_code_keeps_every_code(self):
        from emerald_multiplayer.host_world import HostWorld
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()
        before = HostWorld.open(entry.folder, world.rom, world.manifest)
        driver = Driver(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("codes")),
                        ("codes", select("replace")), ("choose", select("slot2")), ("confirm", BACK),
                        ("codes", select("replace")), ("choose", BACK),                 # B on the friend list too
                        ("codes", BACK), ("world", BACK), ("host_list", BACK), main_exit())
        app2, ui = world.app(driver)
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(HostWorld.open(entry.folder, world.rom, world.manifest).accounts, before.accounts)
        self.assertEqual(ui.copied, [])                                                 # no new code was made

    def test_b_on_allowing_internet_connections_keeps_them_off(self):
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()
        self.assertFalse(entry.internet)
        driver = Driver(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("network")),
                        ("network", select("internet")), ("confirm", BACK), ("network", BACK), ("world", BACK),
                        ("host_list", BACK), main_exit())
        app2, _ = world.app(driver)
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertFalse(app2.registry.get(entry.world_id).internet)

    def test_b_on_removing_a_saved_server_keeps_it(self):
        world = World(self)
        library_character(world)
        driver = Driver(("main", select("join")), ("join_list", lambda s: select(next(i.id for i in s.items
                                                                                   if i.label == "Kevin's server"))),
                        ("server", select("remove")), ("confirm", BACK), ("server", BACK), ("join_list", BACK),
                        main_exit())
        app, _ = world.app(driver)
        server, _ = app.servers.add("Kevin's server", "192.168.1.30", 7777, str(uuid4()), str(uuid4()), 1, "Player 2")
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual([s["id"] for s in app.servers.all()], [server["id"]])

    def test_b_on_bringing_a_character_in_starts_nothing(self):
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()
        registrations, worker = [], FakeWorker()
        driver = Driver(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("host")),
                        ("bring_character", BACK), ("host_list", BACK), main_exit())
        app2, _ = world.app(driver, worker=worker, register=fake_register(registrations))
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual((registrations, worker.requests), ([], []))

    def test_b_in_a_running_session_abandons_saves_and_restarts_nothing(self):
        """The session window while a game runs: B only says how to end the session; on "Abandon interrupted battle"
        (it asks first) B keeps the battle."""
        from emerald_multiplayer.launcher_gui import UiEvent
        from emerald_multiplayer.shell_app import ShellApp
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()

        class Held(FakeWorker):
            abandons = restarts = recoveries = 0

            def start(self, request):
                self.requests.append(request)
                self.events.put(UiEvent("status", "running", "running", True, save_available=True, is_host=True,
                                        connected=True, battle_abandon_available=True, host_restart_available=True,
                                        battle_recovery_available=True))
                return True

            def request_battle_abandon(self):
                self.abandons += 1
                return True

            def request_host_restart(self):
                self.restarts += 1
                return True

            def request_battle_recovery(self):
                self.recoveries += 1
                return True

        worker = Held()
        answers = iter([BACK, select("abandon_battle"), None])
        seen = {}

        def responder(screen, waiting=False):
            if screen.id == "session":
                seen.setdefault("rows", [i.id for i in screen.items])
                answer = next(answers)
                if answer is None:
                    seen["status"] = screen.status
                    worker.events.put(UiEvent("complete", "game_closed"))
                return answer
            if screen.id == "confirm":
                seen["question"] = screen.title
                return BACK
            if screen.id == "busy" and waiting:
                return None
            if screen.id == "world":
                seen["hosted"] = True
                return select("host")
            if screen.id == "bring_character":
                return select("go")
            if screen.id == "main":
                return select("exit") if seen.get("hosted") else select("host")
            if screen.id == "host_list":
                return BACK if seen.get("hosted") else select(entry.world_id)
            self.fail(f"unexpected {screen.id}")
        app2 = ShellApp(world.installation, world.private, ScriptedShell(responder), worker=worker, lan=LAN,
                        graphics_gate=lambda: "3d", version="t", register=fake_register([]), drafter=fake_drafter([]))
        app2.run()
        self.assertIn("abandon_battle", seen["rows"])
        self.assertEqual(seen["question"], "Abandon interrupted battle")
        self.assertEqual((worker.abandons, worker.restarts, worker.recoveries, worker.saves), (0, 0, 0, 0))


# ---------------------------------------------------------------------------------------------- the Players menu


class RecordingCompanion(FakeCompanion):
    """test_tower_menu's fake host, with every request of the other services recorded as (service, operation)."""

    def __init__(self, test):
        super().__init__(test)
        self.sent = []

    async def team_rpc(self, operation, **fields):
        self.sent.append(("team", operation))
        return await super().team_rpc(operation, **fields)

    async def battle_challenge_rpc(self, operation, **fields):
        self.sent.append(("battle", operation))
        return await super().battle_challenge_rpc(operation, **fields)

    async def lobby_rpc(self, operation, **fields):
        self.sent.append(("lobby", operation))
        return {"result": {"lobbies": []}}

    async def tower_rpc(self, op="status", **fields):
        self.sent.append(("tower", op))
        return await super().tower_rpc(op, **fields)


class PlayersMenuBackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tower_data.install(synthetic_data())
        self.addCleanup(tower_data.reset)
        self.calls, self.refuse, self.disabled = [], None, False
        self.view = host_view()
        self.companion = RecordingCompanion(self)
        self.menu = PlayerMenu(self.companion)

    labels = property(lambda self: [row.label for row in self.menu.screen.rows])

    async def click(self, label):
        row = next((r for r in self.menu.screen.rows if r.label == label), None)
        self.assertIsNotNone(row, (label, self.labels))
        return await self.menu.choose(self.menu.screen.revision, row.action)

    async def b(self):
        """B as the game sends it: CHOOSE with the screen's Back action."""
        self.assertEqual(self.menu.screen.back, 7)
        return await self.menu.choose(self.menu.screen.revision, 7)

    def test_back_is_never_a_row_nor_anything_but_a_way_back(self):
        for page in PAGES:
            with self.subTest(page=page):
                self.menu._page = (page, ("battle_cancel", 0, (), ("home", None)) if page == "confirm" else None)
                self.menu._signature = None
                screen = self.menu._show("Players", "", [("Accept challenge", "battle_accept", ("b", 1, "f")),
                                                         ("Confirm this trade", "trade_confirm", ())])
                rows = {row.action for row in screen.rows}
                if page in ("home", "soft_reset", "soft_reset_confirm"):
                    # no Back: B closes the game's window, which chooses nothing (multiplayer_menu.c Input)
                    self.assertEqual(screen.back, 0)
                    self.assertNotIn(7, self.menu._actions)
                    continue
                self.assertEqual(screen.back, 7)
                self.assertNotIn(7, rows)
                op, _ = self.menu._actions[7]
                self.assertIn(op, WAYS_BACK)
                self.assertNotIn(op, _ASKED_OPS)

    async def test_b_on_every_question_is_no_and_sends_nothing(self):
        await self.menu.refresh()
        for question, (title, _, yes, yes_op, fixed) in QUESTIONS.items():
            with self.subTest(question=question):
                self.menu._page = ("confirm", (question, 0, ("x", 1), ("home", None)))
                screen = await self.menu.refresh()
                self.assertEqual((screen.title, screen.rows[0].label), (title, "No, keep it"))
                yes_row = next(row for row in screen.rows if row.label == yes)
                self.assertEqual(self.menu._actions[yes_row.action][0], yes_op)      # Yes is a row: only A takes it
                self.assertEqual(self.menu._actions[7], ("ask_no", ()))
                self.companion.sent.clear()
                await self.b()
                self.assertEqual(self.menu._page, ("home", None))
                self.assertLessEqual(set(self.companion.sent), READS)              # read again, nothing sent

    async def open_tower(self):
        await self.menu.refresh()
        await self.click("World and my base")
        await self.click("Frontier and League")
        await self.click("Battle Tower: Legends")

    def acted(self, *operations):
        return [op for op, _ in self.calls if op in operations]

    async def test_b_on_the_towers_acting_pages_sends_nothing(self):
        await self.open_tower()
        await self.click("Solo: floor 12")
        self.assertIn("Start the battle", self.labels)
        await self.b()
        self.assertEqual((self.menu.screen.title, self.menu.tower_reply), ("Battle Tower: Legends", None))
        await self.click("Prizes and shop")
        await self.click("Tower Shop (45 BP)")
        self.assertTrue(any(label.endswith("BP") for label in self.labels))
        await self.b()
        await self.b()
        self.view = host_view(milestones=[{"milestone": 0, "floor": 25, "state": "owed", "name": "Lapras",
                                           "level": 30}])
        await self.menu.refresh()
        await self.click("Prizes and shop")
        self.assertIn("Send Lapras now", self.labels)
        await self.b()
        self.assertEqual(self.acted("solo", "shop_buy", "milestone_send"), [])

    async def test_b_on_a_duo_invitation_or_its_ready_sends_nothing(self):
        self.view = host_view(teammate=TEAMMATE, duo=DUO_VIEWS["invited, theirs"])
        await self.open_tower()
        await self.click("Duo: floor 12 (invited)")
        self.assertIn("Accept: floor 12", self.labels)
        await self.b()
        self.view = host_view(teammate=TEAMMATE, duo=deepcopy(DUO_VIEWS["forming"]))
        self.view["duo"]["members"][0]["ready"] = False
        await self.menu.refresh()
        await self.click("Duo: floor 12 (forming)")
        self.assertIn("Ready", self.labels)
        await self.b()
        self.assertEqual(self.menu.screen.title, "Battle Tower: Legends")
        self.assertEqual(self.acted("duo_accept", "duo_ready", "duo_decline", "duo_leave", "duo_invite"), [])

    async def test_b_in_a_minigame_lobby_leaves_it_and_never_starts_it(self):
        from test_minigame_menu import FakeCompanion as MinigameCompanion, view

        class Host:
            calls, refuse = [], None
            mine = view(["a", "b"], 0)                       # this player leads; Bob has joined: it could start

            def reply(self, operation, fields):
                if operation == "status":
                    return {"activity": "berry_crush", "groups": [], "mine": self.mine}
                self.mine = None
                return {"left": True}
        host = Host()
        menu = PlayerMenu(MinigameCompanion(host))
        await menu.open_page("minigame_berry_crush")
        self.assertIn("Start with 2 players", [row.label for row in menu.screen.rows])
        await menu.choose(menu.screen.revision, 7)
        self.assertEqual([op for op, _ in host.calls if op != "status"], ["leave"])
        self.assertEqual(menu.handoff, ("close", {}))


class ChampionshipBackTests(ChampionshipFixture, unittest.TestCase):
    """B in the Championship pages goes back a page; a proposal not yet sent is dropped, never proposed."""

    # the menu tests' own helpers (test_championship_eight.EightChampionshipMenuTests): its pages against the real store
    companion = championship_tests.EightChampionshipMenuTests.companion
    check_page = championship_tests.EightChampionshipMenuTests.check_page
    press = championship_tests.EightChampionshipMenuTests.press

    def test_b_drops_an_unsent_proposal_and_never_accepts_or_cancels(self):
        from emerald_multiplayer.championship_menu import ChampionshipMenu
        first, second = self.players[:2]
        menu = ChampionshipMenu(self.companion(first))
        asyncio.run(menu.refresh())
        self.press(menu, "Propose a Championship")
        self.assertEqual(self.check_page(menu)[0], "New Championship")
        self.assertIsNone(asyncio.run(menu.choose("champ_back", ())))                 # B
        asyncio.run(menu.refresh())
        self.assertEqual(self.check_page(menu)[0], "Championship")
        self.assertIsNone(self.call(first, "status")["current"])                      # nothing was proposed
        # A proposal the other player has not accepted: B on its consent page accepts and cancels nothing.
        self.press(menu, "Propose a Championship")
        self.press(menu, "Propose: 2")
        other = ChampionshipMenu(self.companion(second))
        asyncio.run(other.refresh())
        self.press(other, "Places and consent")
        labels = [label for label, _, _ in self.check_page(other)[2]]
        self.assertIn("Accept this bracket", labels)
        self.assertIn("Cancel proposal", labels)
        self.assertIsNone(asyncio.run(other.choose("champ_back", ())))
        current = self.call(second, "status")["current"]
        self.assertEqual((current["state"], current["consent"], current["cancel_consent"]), ("proposed", [first], []))


# ---------------------------------------------------------------------------------------------- the trade window


class TradeWindowBackTests(unittest.TestCase):
    def test_b_on_every_trade_page_asks_or_goes_back_and_never_trades_or_cancels(self):
        from test_trade_menu import TradeMenuTests
        menu, _, _, _, view = TradeMenuTests.make(self)
        choices = (PartyChoice(41, 25, 7, True), PartyChoice(42, 64, 8, False))
        offers = [{"player_id": "actor", "species": 25}, {"player_id": "peer", "species": 265}]
        pages = {"party (nothing offered)": ("party", {}),
                 "party (offered)": ("party", dict(fingerprint="f", offers=offers)),
                 "review": ("review", dict(fingerprint="f", offers=offers)),
                 "review (confirmed)": ("review", dict(fingerprint="f", offers=offers, confirmations=["actor"])),
                 "blocked": ("blocked", {}),
                 "ask_cancel": ("ask_cancel", {}),
                 "preparing": ("review", dict(state="preparing", prepared=[], fingerprint="f", offers=offers,
                                              confirmations=["actor", "peer"]))}
        expected = {"party (nothing offered)": "ask_cancel", "party (offered)": "review", "review": "ask_cancel",
                    "review (confirmed)": "ask_cancel", "blocked": "party", "ask_cancel": "keep",
                    "preparing": "ask_cancel"}
        for name, (page, changes) in pages.items():
            with self.subTest(page=name):
                menu.page, menu.signature, menu.blocked_serial = page, None, 42
                screen = menu._render({**view, **changes}, choices)
                self.assertEqual(screen.back, 7)
                self.assertNotIn(7, {row.action for row in screen.rows})
                self.assertEqual(menu.actions[7], (expected[name], None))
        menu.page, menu.signature = "details", None
        menu.inspection = ("f", {"peer": SimpleNamespace(pages=lambda: [("Moves", ["Tackle"])])})
        menu.detail_player, menu.detail_page = "peer", 0
        menu._render({**view, "fingerprint": "f", "offers": offers}, choices)
        self.assertEqual(menu.actions[7], ("review", None))


if __name__ == "__main__":
    unittest.main()
