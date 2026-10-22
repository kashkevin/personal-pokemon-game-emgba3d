"""Battle Tower: Legends' pages in the Players menu (tower_menu.py) against a fake host: every page within the menu's
limits (a title of 23, a status of 31, six rows of 25 printable ASCII, B), its style bytes, the way in (Frontier and
League, START > PLAYER > TOWER), the solo command and Hyper Training as the game's flags-4 and flags-5 screens through the
real menu session, the Duo pages and the host's refusals."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from emerald_multiplayer import tower_data, tower_rewards
from emerald_multiplayer.bridge_protocol import BridgeOutbox
from emerald_multiplayer.menu_mailbox import MenuRequest, TowerCommand, pack_screen, unpack_screen
from emerald_multiplayer.menu_session import MenuSession
from emerald_multiplayer.player_menu import PlayerMenu
from emerald_multiplayer.protocol import ProtocolError
from test_tower_rules import TABLE_HASH, synthetic_data

ME, MATE = "a", "b"


def member(player, name, progress, highest, *, progression, first_clear=None, ready=False, team=("Mudkip",)):
    return {"player_id": player, "name": name, "progress": progress, "highest": highest, "progression": progression,
            "first_clear": progression if first_clear is None else first_clear, "ready": ready, "consent": True,
            "team": list(team)}


def host_view(progress=12, highest=11, claims=0b11, *, bp=45, battle=None, last=None, duo=None, teammate=None,
              milestones=(), purchase=None, problem=None, unavailable=None, party=None):
    return {
        "available": unavailable is None, "unavailable": unavailable, "table_hash": TABLE_HASH, "problem": problem,
        "player": {"known": True, "progress": progress, "highest": highest, "checkpoint": 10, "claims": claims,
                   "best": highest, "best_solo": highest, "best_duo": 3, "wins": 14, "losses": 2, "battles": 16,
                   "completions": 0},
        "save": {"badges": 3, "champion": False, "cap": 30, "bp": bp}, "battle": battle, "last": last,
        "milestones": list(milestones), "duo": duo, "teammate": teammate,
        "team": {"limit": 3, "auto": True, "slots": [
            {"slot": i, "name": name, "level": 20 + i, "egg": name == "Egg", "able": True, "selected": i < 3}
            for i, name in enumerate(("Mudkip", "Wurmple", "Zigzagoon", "Taillow", "Egg", "Seedot"))]},
        "shop": [{"slot": i, "name": e.name, "price": e.price} for i, e in enumerate(tower_rewards.SHOP)],
        "purchase": purchase,
        "records": [{"name": "Alice", "best_solo": 11, "best_duo": 3, "completions": 0, "wins": 14, "me": True},
                    {"name": "Bobby Longname", "best_solo": 100, "best_duo": 100, "completions": 3, "wins": 300,
                     "me": False}],
        "party": party if party is not None else [
            {"name": "Swampert", "level": 52, "egg": False, "ivs": [31, 20, 10, 5, 31, 0],
             "trained": [False, True, False, False, False, False]},
            {"name": "Egg", "level": 1, "egg": True, "ivs": [0] * 6, "trained": [False] * 6}],
    }


DUO_VIEWS = {
    "invited, mine": {"duo_id": "d", "state": "invited", "floor": 12, "proposer": ME, "reason": None, "battle_id": None,
                      "native": None, "members": [member(ME, "Alice", 12, 11, progression=True),
                                                  member(MATE, "Bob", 50, 49, progression=False)]},
    "invited, theirs": {"duo_id": "d", "state": "invited", "floor": 12, "proposer": MATE, "reason": None,
                        "battle_id": None, "native": None,
                        "members": [member(MATE, "Bob", 50, 49, progression=False),
                                    member(ME, "Alice", 12, 11, progression=True)]},
    "forming": {"duo_id": "d", "state": "forming", "floor": 12, "proposer": ME, "reason": None, "battle_id": None,
                "native": None, "members": [member(ME, "Alice", 12, 11, progression=True, ready=True),
                                            member(MATE, "Bob", 50, 49, progression=False)]},
    "battle": {"duo_id": "d", "state": "battle", "floor": 12, "proposer": ME, "reason": None, "battle_id": "x",
               "native": "recovery_required",
               "members": [member(ME, "Alice", 12, 11, progression=True, ready=True),
                           member(MATE, "Bob", 50, 49, progression=False, ready=True)]},
    "ended": {"duo_id": "d", "state": "ended", "floor": 12, "proposer": ME, "reason": "team_changed", "battle_id": None,
              "native": None, "members": [member(ME, "Alice", 12, 11, progression=True),
                                          member(MATE, "Bob", 50, 49, progression=False)]},
}
TEAMMATE = {"player_id": MATE, "name": "Bob", "progress": 50, "highest": 49}


class FakeCompanion:
    def __init__(self, test):
        self.test = test
        self.config = SimpleNamespace(player_id=ME, world_enabled=True, menu_abi_version=1, trade_enabled=False,
                                      tower_abi_version=1, menu_open_page_abi_version=1)
        self.connected, self.world_id, self.server_epoch, self.session_epoch = True, "w", 1, 2
        self._players = [{"player_id": ME, "display_name": "Alice"}, {"player_id": MATE, "display_name": "Bob"}]

    def world_nav(self):
        return {"players": [], "outbreak": None, "event": None}

    async def team_rpc(self, operation, **fields):
        return {"result": {"team": None, "teams": [], "invitations": []}}

    async def battle_challenge_rpc(self, operation, **fields):
        return {"result": []}

    async def tower_rpc(self, op="status", **fields):
        self.test.calls.append((op, fields))
        if self.test.refuse is not None and op != "status":
            raise ProtocolError(*self.test.refuse)
        if self.test.disabled:
            raise ProtocolError("tower_disabled", "this host's game has no Battle Tower")
        view = deepcopy(self.test.view)
        if op == "solo":
            view["command"] = {"ticket": 0x2A0501, "floor": fields["floor"], "table_hash": TABLE_HASH}
        return view


class PageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tower_data.install(synthetic_data())
        self.addCleanup(tower_data.reset)
        self.calls, self.refuse, self.disabled = [], None, False
        self.view = host_view()
        self.companion = FakeCompanion(self)
        self.menu = PlayerMenu(self.companion)

    labels = property(lambda self: [row.label for row in self.menu.screen.rows])

    async def click(self, label):
        row = next((r for r in self.menu.screen.rows if r.label == label), None)
        self.assertIsNotNone(row, (label, self.labels))
        self.assertTrue(row.action, label)
        return await self.menu.choose(self.menu.screen.revision, row.action)

    async def back(self):
        return await self.menu.choose(self.menu.screen.revision, 7)

    async def open_tower(self):
        await self.menu.refresh()
        await self.click("World and my base")
        await self.click("Frontier and League")
        await self.click("Battle Tower: Legends")

    def assert_fits(self):
        screen = self.menu.screen
        pack_screen(1, screen, allow_tower=True)                                       # the canonical 240 bytes
        self.assertLessEqual(len(screen.rows), 6)
        self.assertEqual(screen.back, 7)

    # -------------------------------------------------------------- the pages
    def raw_pages(self):
        """Every page of the controller with every argument it can be asked for, rendered raw (before the parent's
        truncation): (page, arg, title, status, actions, style)."""
        tower = self.menu._tower
        for page, args in (("home", [None]), ("solo", [1, 12, 25, 100, 5]), ("replay", [0, 1, 2]),
                           ("bosses", [0, 1, 2]), ("map", [1, 5, 97, 100]), ("preview", [1, 10, 12, 50, 100]),
                           ("prizes", [None]), ("prize_list", [0, 1, 2]), ("prize", list(tower_rewards.PRIZE_FLOORS)),
                           ("shop", list(range(7))), ("training", [None]), ("party", [None]), ("mon", [0, 1, 5]),
                           ("records", [None]), ("duo", [None]), ("duo_floor", [0, 1, 2]), ("team", [0, 1])):
            for arg in args:
                yield (page, arg, *getattr(tower, "_render_" + page)(arg))

    async def test_every_page_fits_the_menu_in_every_state(self):
        await self.open_tower()
        states = {"climbing": host_view(), "fresh": host_view(1, 0, 0, bp=None), "top": host_view(101, 100, 0xFFFF, bp=9999),
                  "after a loss": host_view(41, 48, 0b111111),
                  "battle": host_view(battle={"ticket": 1, "mode": "solo", "floor": 12, "state": "started",
                                              "progression": True, "age": 3}),
                  "owed": host_view(25 + 1, 25, milestones=[{"milestone": 0, "floor": 25, "state": "owed",
                                                             "name": "Dragonite", "level": 25}]),
                  "no save": host_view(problem={"code": "no_save", "message": "Save your game first"}),
                  "no data": host_view(unavailable="Tower floor data is missing"),
                  "bought": host_view(purchase={"state": "refunded", "price": 192, "name": "Gold Bottle Cap"}),
                  "no teammate": host_view(), "teammate": host_view(teammate=TEAMMATE),
                  **{f"duo {name}": host_view(duo=duo, teammate=TEAMMATE) for name, duo in DUO_VIEWS.items()}}
        for name, view in states.items():
            self.menu._tower._view = view
            for page, arg, title, status, actions, (style, style_arg) in self.raw_pages():
                with self.subTest(state=name, page=page, arg=arg):
                    self.assertLessEqual(len(title), 23, title)
                    self.assertLessEqual(len(status), 31, status)
                    self.assertLessEqual(len(actions), 6)
                    for label, op, _ in actions:
                        self.assertLessEqual(len(label), 25, label)
                        self.assertTrue(all(32 <= ord(c) <= 126 for c in label + title + status))
                        self.assertTrue(op == "" or op.startswith("tower_"), op)
                    self.assertIn(style, range(1, 9))
                    self.assertTrue(0 <= style_arg <= 100 and (style_arg == 0 or style in (2, 3, 5, 8)))

    async def test_the_home_page_and_its_rows(self):
        await self.open_tower()
        screen = self.menu.screen
        self.assertEqual((screen.title, screen.status), ("Battle Tower: Legends", "Floor 12 Best 11 CP10 45BP"))
        self.assertEqual((screen.style, screen.style_arg), (1, 0))
        self.assertEqual(self.labels, ["Solo: floor 12", "Duo (needs a teammate)", "Replay a floor", "Floors and bosses",
                                       "Prizes and shop", "Records"])
        self.assert_fits()
        await self.back()
        self.assertEqual(self.menu.screen.title, "Frontier and League")              # back where it was opened from
        self.assertIn("Battle Tower: Legends", self.labels)

    async def test_start_player_tower_opens_the_home_and_b_goes_to_the_players_list(self):
        await self.menu.open_page("tower")
        self.assertEqual(self.menu.screen.title, "Battle Tower: Legends")
        await self.back()
        self.assertEqual(self.menu.screen.title, "Players")

    async def test_a_solo_battle_is_confirmed_then_answered_with_the_command(self):
        await self.open_tower()
        await self.click("Solo: floor 12")
        screen = self.menu.screen
        self.assertEqual((screen.title, screen.style, screen.style_arg), ("Floor 12", 3, 12))
        self.assertEqual(self.labels, ["vs Ace Trainer Ace12", "Win: 2 BP, $1,200", "Exp cap: Lv30 (3 badges)",
                                       "Start the battle"])
        self.assertEqual(screen.status, "Lv12 Trainer, Hoenn")
        await self.click("Start the battle")
        self.assertEqual(self.calls[-1], ("solo", {"floor": 12}))
        self.assertEqual(self.menu.tower_reply, ("command", TowerCommand(0x2A0501, TABLE_HASH, 12)))
        self.assertEqual((self.menu.screen.title, self.menu.screen.status, self.labels),
                         ("Battle Tower", "Floor 12: good luck!", []))

    async def test_a_refusal_says_why_and_sends_nothing(self):
        await self.open_tower()
        await self.click("Solo: floor 12")
        self.refuse = ("tower_saving", "Your game is saving a result")
        await self.click("Start the battle")
        self.assertIsNone(self.menu.tower_reply)
        self.assertEqual(self.menu.screen.status, "Your game is saving a result")
        self.assertIn("Start the battle", self.labels)

    async def test_a_prize_floor_names_its_prize_and_replays_list_cleared_floors(self):
        self.view = host_view(10, 9, 0)
        await self.open_tower()
        await self.click("Solo: floor 10")
        self.assertEqual(self.labels[:3], ["vs Leader Brock", "Prize: 10 Rare Candy", "Win: 6 BP, $10,000"])
        await self.back()
        await self.click("Replay a floor")
        self.assertEqual(self.labels, ["  9 Ace Trainer Ace9", "  8 Ace Trainer Ace8", "  7 Ace Trainer Ace7",
                                       "  6 Ace Trainer Ace6", "More floors (1/3)"])
        self.assertEqual((self.menu.screen.style, self.menu.screen.style_arg), (2, 6))
        await self.click("  7 Ace Trainer Ace7")
        self.assertEqual(self.menu.screen.title, "Floor 7 (replay)")
        self.assertIn("Win: Exp. only (cleared)", self.labels)                      # a cleared floor pays nothing again
        self.assertFalse(any(label.startswith("Win: ") and "BP" in label for label in self.labels))

    async def test_the_floor_map_bosses_and_previews_never_show_a_team(self):
        await self.open_tower()
        await self.click("Floors and bosses")
        self.assertEqual(self.labels, ["Floor map", " 10+ Leader Brock", " 20- Leader Misty", " 25- Boss Giovanni",
                                       " 30- Leader Flannery", "More bosses (1/3)"])
        await self.click(" 25- Boss Giovanni")
        screen = self.menu.screen
        self.assertEqual((screen.title, screen.status, screen.style, screen.style_arg),
                         ("Floor 25: Special", "Clear floor 12 first", 3, 25))
        self.assertEqual(self.labels, ["Boss Giovanni", "Region: Kanto", "Difficulty: 3", "Prize: Shiny Pokemon",
                                       "Win: 12 BP"])
        self.assertFalse(any("GEODUDE" in label.upper() for label in self.labels))  # the team is never shown
        await self.back()
        await self.click("Floor map")
        self.assertEqual((self.menu.screen.title, self.menu.screen.style_arg), ("Floors 9-12", 9))
        self.assertEqual(self.labels[3], " 12> Ace Trainer Ace12")
        await self.click("Previous floors")
        self.assertEqual(self.menu.screen.title, "Floors 5-8")
        await self.click("  5+ Ace Trainer Ace5")
        self.assertEqual(self.labels[-1], "Fight this floor")

    async def test_prizes_the_shop_and_an_owed_milestone(self):
        self.view = host_view(26, 25, 0b111, milestones=[{"milestone": 0, "floor": 25, "state": "owed",
                                                          "name": "Dragonite", "level": 25}])
        await self.open_tower()
        await self.click("Prizes and shop")
        self.assertEqual((self.menu.screen.style, self.menu.screen.status), (8, "No room for it: make room"))
        self.assertEqual(self.labels, ["Prizes: 3/12 claimed", "Send Dragonite now", "Tower Shop (45 BP)",
                                       "Hyper Training"])
        await self.click("Send Dragonite now")
        self.assertIn(("milestone_send", {"milestone": 0}), self.calls)
        self.assertEqual(self.menu.screen.status, "Sent: close the menu")         # the game makes it on the field
        await self.click("Prizes: 3/12 claimed")
        self.assertEqual(self.labels, ["+ 10 10 Rare Candy", "+ 20 5 Bottle Caps", "+ 25 Shiny Pokemon",
                                       "- 30 15 Rare Candy", "More prizes (1/3)"])
        await self.click("+ 25 Shiny Pokemon")
        self.assertEqual(self.labels, ["a random shiny (natural I", "Battle Points: 12", "Dragonite Lv25: owed"])
        await self.back()
        await self.back()
        await self.click("Tower Shop (45 BP)")
        self.assertEqual((self.menu.screen.title, self.menu.screen.style), ("Tower Shop", 4))
        self.assertEqual(self.labels, ["Bottle Cap 48BP", "Gold Bottle Cap 192BP", "Ability Patch 200BP",
                                       "Ability Capsule 50BP", "More items (1/7)"])
        await self.click("Bottle Cap 48BP")
        self.assertIn(("shop_buy", {"slot": 0}), self.calls)
        self.assertEqual(self.menu.screen.status, "Close the menu to finish")
        # the game pays and receives on the field, never with this menu open (engine multiplayer.c FieldReady): the
        # page says so until the order is done (L tower-solo-8 waited with it open for nothing)
        self.menu._tower._notice = ""                                              # the click's notice read
        self.view["purchase"] = {"state": "debit", "price": 48, "name": "Bottle Cap"}
        await self.menu.refresh()
        self.assertEqual(self.menu.screen.status, "Close the menu to finish")
        self.view["purchase"] = {"state": "done", "price": 48, "name": "Bottle Cap"}
        await self.menu.refresh()
        self.assertEqual(self.menu.screen.status, "Bought Bottle Cap")

    async def test_hyper_training_is_the_games_own_screen_and_the_ivs_page(self):
        await self.open_tower()
        await self.click("Prizes and shop")
        await self.click("Hyper Training")
        self.assertEqual(self.menu.screen.style, 7)
        await self.click("Party IVs (last save)")
        self.assertEqual(self.labels, ["Swampert L52: 3 to train", "Egg"])
        await self.click("Swampert L52: 3 to train")
        self.assertEqual(self.labels, ["HP: 31 (max)", "Attack: 20 (trained)", "Defense: 10", "Speed: 5", "Sp. Atk: 31 (max)",
                                       "Sp. Def: 0"])
        await self.back()
        await self.back()
        await self.click("Open Hyper Training")
        self.assertEqual(self.menu.tower_reply, ("hyper_training", None))

    async def test_records(self):
        await self.open_tower()
        await self.click("Records")
        self.assertEqual(self.labels, ["You: best 11, Duo 3", "Won 14 Lost 2 Clears 0", "1. Alice 11 (14W)",
                                       "2. Bobby Long 100 (300W)"])
        self.assertEqual(self.menu.screen.style, 6)

    async def test_the_duo_pages_from_invitation_to_the_battle(self):
        self.view = host_view(teammate=TEAMMATE)
        await self.open_tower()
        self.assertIn("Duo with Bob", self.labels)
        await self.click("Duo with Bob")
        self.assertEqual(self.labels, ["Bob: floor 50", "You: floor 12", "Invite: floor 12", "Invite: replay a floor"])
        await self.click("Invite: replay a floor")
        self.assertEqual(self.labels[0], " 12 Ace Trainer Ace12")
        self.view = host_view(teammate=TEAMMATE, duo=DUO_VIEWS["invited, mine"])
        await self.click(" 11 Ace Trainer Ace11")
        self.assertIn(("duo_invite", {"floor": 11}), self.calls)
        self.assertEqual((self.menu.screen.title, self.menu.screen.status), ("Duo: floor 12", "Waiting for Bob"))
        self.assertEqual(self.labels, ["Alice: prizes", "Bob: Exp only", "Cancel the invitation"])
        self.view = host_view(teammate=TEAMMATE, duo=DUO_VIEWS["forming"])
        await self.menu.refresh()
        self.assertEqual(self.labels, ["Alice: prizes, ready", "Bob: Exp only", "Team: Mudkip", "Not ready",
                                       "Change floor", "Leave the Duo"])
        self.assertEqual((self.menu.screen.status, self.menu.screen.style, self.menu.screen.style_arg),
                         ("Floor 12: 1/2 ready", 5, 12))
        await self.click("Team: Mudkip")
        self.assertEqual(self.labels[:4], ["* Mudkip L20", "* Wurmple L21", "* Zigzagoon L22", "- Taillow L23"])
        await self.click("- Taillow L23")
        self.assertIn(("bring", {"mask": 0b1110}), self.calls)                        # a full team gives up its first
        self.view = host_view(teammate=TEAMMATE, duo=DUO_VIEWS["battle"])
        await self.back()
        self.assertEqual(self.menu.screen.status, "Battle needs recovery")
        await self.click("Open Challenges")
        self.assertEqual(self.menu.screen.title, "Challenges")

    async def test_the_teammate_who_joined_sees_the_hosts_floor_and_cannot_change_it(self):
        """Bob hosts (he climbed to 50); Alice joins on his choice of floor: her row says what the floor pays her, and
        only the host may change the floor."""
        duo = dict(DUO_VIEWS["forming"], proposer=MATE,
                   members=[member(MATE, "Bob", 50, 49, progression=False, first_clear=False),
                            member(ME, "Alice", 12, 11, progression=True, first_clear=True, ready=True)])
        self.view = host_view(teammate=TEAMMATE, duo=duo)
        await self.open_tower()
        await self.click("Duo: floor 12 (forming)")
        self.assertEqual(self.labels, ["Bob: Exp only", "Alice: prizes, ready", "Team: Mudkip", "Not ready",
                                       "Leave the Duo"])
        self.assertNotIn("Change floor", self.labels)
        # A re-climb after a loss is progression but pays nothing: the row says so.
        duo["members"][1] = member(ME, "Alice", 12, 14, progression=True, first_clear=False)
        await self.menu.refresh()
        self.assertEqual(self.labels[1], "Alice: Exp only")

    async def test_an_invitation_is_accepted_or_declined_and_an_ended_duo_says_why(self):
        self.view = host_view(teammate=TEAMMATE, duo=DUO_VIEWS["invited, theirs"])
        await self.open_tower()
        await self.click("Duo: floor 12 (invited)")
        self.assertEqual(self.menu.screen.status, "Bob invites you")
        await self.click("Accept: floor 12")
        self.assertIn(("duo_accept", {}), self.calls)
        self.view = host_view(teammate=TEAMMATE, duo=DUO_VIEWS["ended"])
        await self.menu.refresh()
        self.assertEqual(self.menu.screen.status, "Your team was dissolved")

    async def test_without_a_teammate_the_duo_points_to_the_players_list(self):
        await self.open_tower()
        await self.click("Duo (needs a teammate)")
        self.assertEqual(self.menu.screen.status, "Form a team in PLAYERS first")
        await self.click("Choose a teammate")
        self.assertEqual(self.menu.screen.title, "Players")

    async def test_a_host_without_the_tower_says_so(self):
        self.disabled = True
        await self.open_tower()
        self.assertEqual((self.menu.screen.title, self.menu.screen.status),
                         ("Battle Tower: Legends", "The host has no Battle Tower"))

    async def test_a_game_without_the_tower_is_never_offered_it(self):
        self.companion.config.tower_abi_version = 0
        await self.menu.refresh()
        await self.click("World and my base")
        await self.click("Frontier and League")
        self.assertEqual(self.labels, ["Battle Frontier", "Pokemon League", "Back to World"])

    async def test_the_status_line_follows_the_battle(self):
        self.view = host_view(battle={"ticket": 1, "mode": "solo", "floor": 12, "state": "issued", "progression": True,
                                      "age": 3})
        await self.open_tower()
        self.assertEqual((self.menu.screen.status, self.labels[0]), ("Floor 12: starting", "Floor 12: starting"))
        # Started and no result: this menu is open, so the game is out of that battle. Asking again is offered; the host
        # answers it (a late result is waited for, else the battle counts as a loss).
        self.view = host_view(battle={"ticket": 1, "mode": "solo", "floor": 12, "state": "started", "progression": True,
                                      "age": 40})
        await self.menu.refresh()
        self.assertEqual((self.menu.screen.status, self.labels[0]), ("Floor 12: no result yet", "Solo: floor 12"))
        await self.click("Solo: floor 12")
        self.refuse = ("tower_forfeited", "Floor 12: counted as a loss")
        await self.click("Start the battle")
        self.assertEqual(self.menu.screen.status, "Floor 12: counted as a loss")
        self.assertIsNone(self.menu.tower_reply)
        self.refuse = None
        await self.back()                                                             # the reason stays until a choice
        self.view = host_view(last={"floor": 12, "mode": "solo", "state": "void", "reason": "refused",
                                    "progression": True, "after": None, "reward": None})
        await self.menu.refresh()
        self.assertEqual(self.menu.screen.status, "Floor 12: your game refused")
        self.view = host_view(problem={"code": "no_save", "message": "Save your game first"})
        await self.menu.refresh()
        self.assertEqual(self.menu.screen.status, "Save your game first")


class SessionTests(unittest.IsolatedAsyncioTestCase):
    """START > PLAYER > TOWER and the solo command through the real menu session: the game gets the flags-4 screen."""

    async def asyncSetUp(self):
        tower_data.install(synthetic_data())
        self.addCleanup(tower_data.reset)
        self.calls, self.refuse, self.disabled, self.view = [], None, False, host_view()
        self.bridge = SimpleNamespace(outbox=BridgeOutbox(), writer=SimpleNamespace(close=lambda: None))
        self.companion = FakeCompanion(self)
        self.companion._bridge = self.bridge
        self.session = MenuSession(self.companion, self.bridge)

    async def asyncTearDown(self):
        await self.session.close()

    async def frame(self):
        frame = await asyncio.wait_for(self.bridge.outbox.get(), 2)
        return unpack_screen(frame[5:], allow_tower=True)

    async def choose(self, sequence, label):
        screen = self.session.menu.screen
        row = next(r for r in screen.rows if r.label == label)
        self.session.feed(MenuRequest(sequence, screen.revision, row.action, 2).pack())
        await self.session._task
        return await self.frame()

    async def test_the_tower_page_opens_and_a_solo_battle_reaches_the_game(self):
        self.session.feed(MenuRequest(1, 0, 2, 1).pack(allow_tower=True))
        await self.session._task
        _, screen, flags, _ = await self.frame()
        self.assertEqual((screen.title, screen.style, flags), ("Battle Tower: Legends", 1, 0))
        _, screen, flags, _ = await self.choose(2, "Solo: floor 12")
        self.assertEqual((screen.title, screen.style, screen.style_arg), ("Floor 12", 3, 12))
        sequence, screen, flags, command = await self.choose(3, "Start the battle")
        self.assertEqual((sequence, flags, command, screen.rows), (3, 4, TowerCommand(0x2A0501, TABLE_HASH, 12), ()))
        self.session.feed(MenuRequest(4, 0, 0, 3).pack())                              # the game closed its window
        self.assertFalse(self.session.open)


if __name__ == "__main__":
    unittest.main()
