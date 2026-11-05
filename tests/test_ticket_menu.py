"""The Legendary Tickets' pages in the Players menu (player_menu.py; PLAYERS > World and my base > Frontier and League >
Legendary Tickets) against a fake host whose views come from the host's own builders (ticket_service.SHORT_NAMES, the
world's setting through legendary_tickets) and pass the companion's check (ticket_service.validate_view): each ticket, its
island, given or how to earn it with the player's progress, within the menu's limits (a title of 23, a status of 31, six
rows of 25 printable ASCII, B) and the game's canonical screen bytes."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import unittest

from emerald_multiplayer import legendary_tickets as lt
from emerald_multiplayer.menu_mailbox import pack_screen
from emerald_multiplayer.player_menu import PlayerMenu
from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.ticket_service import SHORT_NAMES, validate_view

ME = "11111111-1111-4111-8111-111111111111"


def host_view(states=None, haves=None, *, sources=None, problem=None, earned=None):
    """What TicketService.view answers: ``states`` {ticket: state} (default locked), ``haves`` {source text: have} (default
    0; None: progress unknown), ``sources`` the world's setting (default the owner's)."""
    setting = lt.validate_sources(sources or lt.DEFAULT_SOURCES)
    tickets = []
    for ticket in lt.TICKETS:
        rows = []
        for source in setting[ticket.key]:
            need = source.progress(lt.TicketFacts())[1]
            have = (haves or {}).get(source.text, 0)
            rows.append({"text": source.text, "label": source.label, "short": SHORT_NAMES[source.kind],
                         "have": None if have is None else min(have, need), "need": need, "solo": source.condition.solo})
        state = (states or {}).get(ticket.key, "locked")
        tickets.append({"key": ticket.key, "name": ticket.name, "island": ticket.island, "state": state,
                        "earned_by": (earned or {}).get(ticket.key, rows[0]["text"] if state != "locked" else None),
                        "sources": rows})
    return validate_view({"tickets": tickets, "problem": problem})


class FakeCompanion:
    def __init__(self, test, *, tickets=True):
        self.test = test
        self.config = SimpleNamespace(player_id=ME, world_enabled=True, menu_abi_version=1, trade_enabled=False,
                                      ticket_abi_version=1 if tickets else 0)
        self.connected, self.world_id, self.server_epoch, self.session_epoch = True, "w", 1, 2
        self._players = [{"player_id": ME, "display_name": "Alice"}]

    def world_nav(self):
        return {"players": [], "outbreak": None, "event": None}

    async def team_rpc(self, operation, **fields):
        return {"result": {"team": None, "teams": [], "invitations": []}}

    async def battle_challenge_rpc(self, operation, **fields):
        return {"result": []}

    async def tickets_rpc(self):
        self.test.calls += 1
        if self.test.refuse is not None:
            raise ProtocolError(*self.test.refuse)
        return deepcopy(self.test.view)


class TicketPageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls, self.refuse = 0, None
        self.view = host_view({"aurora": "sending", "old_sea_map": "given"},
                              {"hall_of_fame:2": 1, "silver_symbols:7": 3, "tower_floor:75": 40, "weather_trio": 3,
                               "regi_trio": 3})
        self.companion = FakeCompanion(self)
        self.menu = PlayerMenu(self.companion)

    labels = property(lambda self: [row.label for row in self.menu.screen.rows])

    async def click(self, label):
        row = next((r for r in self.menu.screen.rows if r.label == label), None)
        self.assertIsNotNone(row, (label, self.labels))
        self.assertTrue(row.action, label)
        screen = await self.menu.choose(self.menu.screen.revision, row.action)
        self.assert_fits()
        return screen

    def assert_fits(self):
        screen = self.menu.screen
        pack_screen(1, screen, allow_new_page=True)                                    # the canonical 240 bytes
        self.assertLessEqual(len(screen.rows), 6)
        self.assertEqual(screen.back, 7)

    async def open_tickets(self):
        await self.menu.refresh()
        await self.click("World and my base")
        await self.click("Frontier and League")
        return await self.click("Legendary Tickets")

    async def test_the_way_in_is_frontier_and_league_with_the_capability_only(self):
        screen = await self.open_tickets()
        self.assertEqual((screen.title, screen.status), ("Legendary Tickets", "Given: 1 of 4"))
        self.assertEqual(self.labels, ["Eon Ticket: 1/2", "Mystic Ticket: not yet", "Aurora Ticket: on its way",
                                       "Old Sea Map: GIVEN", "Back"])
        await self.click("Back")
        self.assertEqual(self.menu.screen.title, "Frontier and League")
        menu = PlayerMenu(FakeCompanion(self, tickets=False))
        await menu.refresh()
        for label in ("World and my base", "Frontier and League"):
            row = next(r for r in menu.screen.rows if r.label == label)
            await menu.choose(menu.screen.revision, row.action)
        self.assertNotIn("Legendary Tickets", [r.label for r in menu.screen.rows])

    async def test_one_way_to_earn_it_is_shown_whole_with_the_progress(self):
        await self.open_tickets()
        screen = await self.click("Eon Ticket: 1/2")
        self.assertEqual((screen.title, screen.status), ("Eon Ticket", "How to earn it"))
        self.assertEqual(self.labels, ["Island: Southern Island", "Enter the Hall of Fame 2", "time(s): 1/2", "Back"])
        await self.click("Back")
        self.assertEqual(self.menu.screen.title, "Legendary Tickets")

    async def test_several_ways_each_have_their_progress_and_their_whole_sentence(self):
        await self.open_tickets()
        screen = await self.click("Mystic Ticket: not yet")
        self.assertEqual((screen.title, screen.status), ("Mystic Ticket", "Any one of these earns it"))
        self.assertEqual(self.labels, ["Island: Navel Rock", "Silver Symbols: 3/7", "Tower floor: 40/75", "Back"])
        screen = await self.click("Tower floor: 40/75")
        self.assertEqual((screen.title, screen.status), ("Mystic Ticket", "One way to earn it"))
        self.assertEqual(self.labels, ["Island: Navel Rock", "Clear floor 75 of Battle", "Tower: Legends: 40/75", "Back"])
        await self.click("Back")
        self.assertEqual(self.labels[1:3], ["Silver Symbols: 3/7", "Tower floor: 40/75"])
        await self.click("Silver Symbols: 3/7")
        self.assertEqual(self.labels[1:-1], ["Earn 7 of the Battle", "Frontier's Silver", "Symbols: 3/7"])

    async def test_a_given_ticket_says_where_to_show_it_and_what_earned_it(self):
        await self.open_tickets()
        screen = await self.click("Old Sea Map: GIVEN")
        self.assertEqual((screen.title, screen.status), ("Old Sea Map", "Show it at LILYCOVE's port."))
        self.assertEqual(self.labels, ["Island: Faraway Island", "Earned: Sealed Chamber", "Back"])

    async def test_on_its_way_and_no_room(self):
        await self.open_tickets()
        screen = await self.click("Aurora Ticket: on its way")
        self.assertEqual(screen.status, "Earned: on its way to your Bag")
        self.assertEqual(self.labels, ["Island: Birth Island", "Catch or defeat Kyogre,", "Groudon and Rayquaza: 3/3",
                                       "Back"])
        self.view = host_view({"aurora": "owed"}, {"weather_trio": 3})
        await self.menu.refresh()
        self.assertEqual(self.menu.screen.status, "No room: make room, then save")

    async def test_an_unread_save_shows_what_is_needed_and_why(self):
        self.view = host_view(haves={source: None for source in ("hall_of_fame:2", "regi_trio", "weather_trio",
                                                                 "silver_symbols:7", "tower_floor:75")},
                              problem="Save your game first")
        screen = await self.open_tickets()
        self.assertEqual(screen.status, "Save your game first")
        self.assertEqual(self.labels[0], "Eon Ticket: ?/2")
        await self.click("Old Sea Map: ?/3")
        self.assertEqual(self.labels[1:-1], ["Solve the Sealed Chamber:", "catch or defeat Regirock,",
                                             "Regice and Registeel: ?/3"])

    async def test_a_host_without_tickets_and_a_failing_one(self):
        self.refuse = ("tickets_disabled", "this host's game has no Legendary Tickets")
        screen = await self.open_tickets()
        self.assertEqual((screen.title, screen.status), ("Legendary Tickets", "The host has no tickets"))
        self.assertEqual(self.labels, ["Back"])
        self.refuse = ("tickets_failed", "Tickets unavailable: try again")
        await self.menu.refresh()
        self.assertEqual(self.menu.screen.status, "Tickets unavailable: try again")
        self.refuse = None
        await self.menu.refresh()
        self.assertEqual(len(self.labels), 5)

    def test_every_setting_the_owner_can_choose_fits_the_menu(self):
        """Every condition at its largest amount, and a ticket with four sources: no row is cut (25 characters), no page
        has more than six rows."""
        largest = {kind: (f"{kind}:{c.bounds[1]}" if c.bounds else kind) for kind, c in lt.CONDITIONS.items()}
        kinds = list(largest.values())
        settings = [{"eon": kinds[i:i + 4] or kinds[:4], "mystic": kinds[i + 4:i + 8] or kinds[:4],
                     "aurora": kinds[i + 8:i + 12] or kinds[:4], "old_sea_map": [kinds[(i + 12) % len(kinds)]]}
                    for i in range(0, len(kinds), 4)]
        settings.append({key: [kind] for key, kind in zip(lt.TICKET_BY_KEY, kinds)})
        for kind, text in largest.items():
            settings.append({key: [text] for key in lt.TICKET_BY_KEY})
        menu = PlayerMenu(FakeCompanion(self))
        for setting in settings:
            for haves in ({}, None):
                view = host_view(sources=setting, haves=None if haves is None else {})
                if haves is None:
                    view = host_view(sources=setting, haves={s["text"]: s["need"] for t in view["tickets"]
                                                             for s in t["sources"]})
                menu._tickets = view
                pages = [("tickets", None)] + [("ticket", t["key"]) for t in view["tickets"]] + \
                    [("ticket_source", (t["key"], n)) for t in view["tickets"] for n in range(len(t["sources"]))]
                for page, target in pages:
                    for state in ("locked", "sending", "owed", "given"):
                        for ticket in view["tickets"]:
                            ticket["state"] = state
                        title, status, actions = menu._render_tickets(page, target)
                        with self.subTest(setting=setting, page=page, target=target, state=state):
                            self.assertLessEqual(len(title), 23)
                            self.assertLessEqual(len(status), 31)
                            self.assertLessEqual(len(actions), 6)
                            for label, _, _ in actions:
                                self.assertLessEqual(len(label), 25, label)
                                self.assertTrue(all(32 <= ord(c) <= 126 for c in label), label)


if __name__ == "__main__":
    unittest.main()
