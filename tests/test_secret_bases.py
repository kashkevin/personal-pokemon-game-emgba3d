"""Multiplayer Secret Bases and the PokeNav World view (expansion Phases 6 and 7).

Codec and host book are unit tests; the companion path uses the real TCP host
and two companions with scripted (fake) native bridges, as test_world_spawns_companion.
The game's side of the same records is the engine's --selftest-secret-base."""
from __future__ import annotations

import asyncio
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from emerald_multiplayer.bridge_protocol import read_packet
from emerald_multiplayer.extras_mailbox import (
    BASE_BYTES, INBOUND_SIZE, LOCAL_SIZE, ExtrasInbound, ExtrasLocal, ExtrasMailboxError, capability_packet,
    normalize_base, owner_key, tombstone, validate_base)
from emerald_multiplayer.player_menu import PlayerMenu
from emerald_multiplayer.secret_bases import SecretBaseBook, SecretBaseError
from emerald_multiplayer.shared_world import SharedWorld
from emerald_multiplayer.shared_world_protocol import validate_extras, validate_world_request
from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.world_mailbox import WorldState
from test_companion import wait_until
import test_world_companion as world_companion
from test_world_companion import local_record


def make_base(location=11, owner=1, decorations=(1, 2), species=263, level=5, flags=0, junk=False):
    rec = bytearray(BASE_BYTES)
    rec[0] = location
    rec[1] = (owner & 1) << 4 | (0xE3 if junk else flags)       # gender bit + bookkeeping bits
    rec[2:9] = bytes((0xBB + owner, 0xBC, 0xBD, 0xBE, 0xFF, 0xFF, 0xFF))
    rec[9:13] = bytes((0x10 * owner + i) for i in range(4))
    rec[13] = 2
    if junk:
        rec[14:18] = b"\x09\x00\x07\x01"
        rec[50:52] = b"\x55\xaa"
    for i, decor in enumerate(decorations):
        rec[18 + i] = decor
        rec[34 + i] = 0x23
    struct.pack_into("<H", rec, 124, species)
    rec[148] = level
    return bytes(rec)


class ExtrasCodecTests(unittest.TestCase):
    def test_sizes_and_capability_match_the_c_header(self):
        self.assertEqual(capability_packet(), b"e" + struct.pack("<HHHH", 1, 384, 160, 0))
        self.assertEqual((LOCAL_SIZE, INBOUND_SIZE), (168, 176))
        self.assertEqual(len(ExtrasInbound().pack()), INBOUND_SIZE)

    def test_local_record_round_trip_and_bounds(self):
        base = make_base()
        payload = struct.pack("<IB3x", 77, 1) + base
        self.assertEqual(ExtrasLocal.unpack(payload), ExtrasLocal(77, True, base))
        with self.assertRaises(ExtrasMailboxError):
            ExtrasLocal.unpack(payload[:-1])
        with self.assertRaises(ExtrasMailboxError):
            ExtrasLocal.unpack(struct.pack("<IB3x", 5, 0) + base)       # no base, yet data
        self.assertEqual(ExtrasLocal.unpack(struct.pack("<IB3x", 5, 0) + bytes(160)).has_base, False)
        with self.assertRaises(ExtrasMailboxError):
            ExtrasLocal.unpack(struct.pack("<IB3x", 5, 2) + base)

    def test_inbound_layout(self):
        base = make_base()
        data = ExtrasInbound(True, 9, 4, 2, base).pack()
        self.assertEqual(struct.unpack_from("<IIIB3x", data), (1, 9, 4, 2))
        self.assertEqual(data[16:], base)
        with self.assertRaises(ExtrasMailboxError):
            ExtrasInbound(True, 0, 1, 4, base).pack()

    def test_normalize_drops_only_the_receiving_saves_bookkeeping(self):
        clean = make_base()
        self.assertEqual(normalize_base(make_base(junk=True)), clean)
        self.assertEqual(clean[1] & 0x10, 0x10)  # the owner's gender survives

    def test_validation_refuses_what_the_game_would_refuse(self):
        self.assertEqual(validate_base(make_base()), make_base())
        for location in (0, 5, 0xFF, 241, 15):
            with self.assertRaises(ExtrasMailboxError, msg=location):
                validate_base(make_base(location=location))
        for bad in (make_base(decorations=(121,)), make_base(species=1701), make_base(level=101)):
            with self.assertRaises(ExtrasMailboxError):
                validate_base(bad)
        nameless = bytearray(make_base())
        nameless[2] = 0xFF
        with self.assertRaises(ExtrasMailboxError):
            validate_base(bytes(nameless))
        with self.assertRaises(ExtrasMailboxError):
            validate_base(make_base()[:-1])

    def test_withdrawal_names_the_owner_and_no_location(self):
        base = make_base(owner=3)
        gone = tombstone(base)
        self.assertEqual(gone[0], 0)
        self.assertEqual(owner_key(gone), owner_key(base))
        self.assertFalse(any(gone[18:]))
        self.assertEqual(gone[2:13], base[2:13])


class SecretBaseBookTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "world.sqlite3"
        self.world = SharedWorld(self.path, "world")
        self.addCleanup(lambda: self.world.close())
        self.book = self.world.bases

    def test_publish_is_durable_and_changes_only_when_the_base_does(self):
        base = make_base()
        self.assertTrue(self.book.publish("a", base.hex()))
        self.assertFalse(self.book.publish("a", base.hex()))
        self.assertFalse(self.book.publish("a", make_base(junk=True).hex()))   # same base, other bookkeeping
        self.assertTrue(self.book.publish("a", make_base(decorations=(1, 2, 3)).hex()))
        self.world.close()
        reopened = SharedWorld(self.path, "world")
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.bases.state("a"), {"published": True, "visibility": "everyone"})
        self.assertEqual(reopened.bases.view_for("b", None, ["a", "b"])[0]["record"],
                         make_base(decorations=(1, 2, 3)).hex())

    def test_invalid_records_are_refused_and_nothing_is_stored(self):
        for bad in ("zz", make_base(location=0).hex(), make_base(species=9999).hex(), None.__class__.__name__):
            with self.assertRaises(SecretBaseError):
                self.book.publish("a", bad)
        self.assertEqual(self.book.state("a"), {"published": False, "visibility": "everyone"})

    def test_visibility_everyone_team_nobody(self):
        self.book.publish("a", make_base(owner=1).hex())
        self.book.publish("c", make_base(location=21, owner=2).hex())
        roster = ["a", "b", "c"]
        records = lambda teammate: {v["owner"]: v["record"] for v in self.book.view_for("b", teammate, roster)}
        self.assertEqual({k: v == make_base(owner=1).hex() for k, v in records(None).items() if k == "a"}, {"a": True})
        self.assertEqual(len(records(None)), 2)
        self.assertTrue(self.book.set_visibility("a", "team"))
        self.assertFalse(self.book.set_visibility("a", "team"))
        self.assertEqual(bytes.fromhex(records(None)["a"])[0], 0)          # a withdrawal for a non-teammate
        self.assertEqual(records("a")["a"], make_base(owner=1).hex())      # the teammate still sees it
        self.book.set_visibility("a", "nobody")
        self.assertEqual(bytes.fromhex(records("a")["a"])[0], 0)
        with self.assertRaises(SecretBaseError):
            self.book.set_visibility("a", "friends")

    def test_removing_a_base_withdraws_it_and_the_owner_never_sees_their_own(self):
        self.book.publish("a", make_base().hex())
        self.assertEqual(self.book.view_for("a", None, ["a", "b"]), [])
        self.assertTrue(self.book.publish("a", None))
        self.assertFalse(self.book.publish("a", None))
        gone = self.book.view_for("b", None, ["a", "b"])
        self.assertEqual(len(gone), 1)
        self.assertEqual(bytes.fromhex(gone[0]["record"])[0], 0)
        self.assertFalse(self.book.publish("never-published", None))
        self.assertEqual(self.book.view_for("b", None, ["a", "b"]), gone)

    def test_a_player_who_never_shared_has_no_record_even_after_choosing_visibility(self):
        self.book.set_visibility("a", "nobody")
        self.assertEqual(self.book.view_for("b", None, ["a", "b"]), [])
        self.book.publish("a", make_base().hex())
        self.assertEqual(self.book.state("a"), {"published": True, "visibility": "nobody"})

    def test_the_view_is_capped_and_lists_online_players_first(self):
        for i in range(9):
            self.book.publish(f"p{i}", make_base(location=1 + 10 * i, owner=i).hex())
        view = self.book.view_for("me", None, ["me", "p0"])
        self.assertEqual(len(view), 6)
        self.assertEqual(view[0]["owner"], "p0")

    def test_old_world_files_gain_the_table_without_losing_data(self):
        self.world.close()
        db = sqlite3.connect(self.path)
        db.execute("DROP TABLE secret_bases")
        db.commit()
        db.close()
        again = SharedWorld(self.path, "world")
        self.addCleanup(again.close)
        self.assertFalse(again.bases.state("a")["published"])


class ProtocolTests(unittest.TestCase):
    request = {"type": "base_publish", "session_epoch": 3, "request_id": "11111111-1111-4111-8111-111111111111",
               "seq": 4, "base": make_base().hex()}

    def test_requests(self):
        validate_world_request(dict(self.request), 3)
        validate_world_request({**self.request, "base": None}, 3)
        for bad in ({**self.request, "base": "ab"}, {**self.request, "seq": 0}, {**self.request, "extra": 1},
                    {**self.request, "base": make_base().hex().upper()}):
            with self.assertRaises(ProtocolError):
                validate_world_request(bad, 3)
        ok = {k: v for k, v in self.request.items() if k not in ("seq", "base")}
        validate_world_request({**ok, "type": "base_visibility", "mode": "team"}, 3)
        validate_world_request({**ok, "type": "base_get"}, 3)
        with self.assertRaises(ProtocolError):
            validate_world_request({**ok, "type": "base_visibility", "mode": "friends"}, 3)

    def test_extras_view(self):
        nav = {"players": [{"player_id": "a", "place": "ROUTE 101", "weather": "Rain"}],
               "outbreak": {"name": "WURMPLE", "place": "ROUTE 101", "seconds_left": 90}, "event": None}
        good = {"bases": [{"owner": "a", "slot": 1, "record": make_base().hex()}], "nav": nav}
        self.assertIs(validate_extras(good), good)
        self.assertIsNone(validate_extras(None))
        for bad in ({**good, "bases": [{"owner": "a", "slot": 4, "record": make_base().hex()}]},
                    {**good, "bases": [{"owner": "a", "slot": 1, "record": "00"}]},
                    {**good, "nav": {**nav, "outbreak": {"name": "x", "place": "y", "seconds_left": -1}}},
                    {**good, "nav": {**nav, "players": [{"player_id": "a", "place": "\x01", "weather": None}]}},
                    {"bases": []}):
            with self.assertRaises(ProtocolError):
                validate_extras(bad)


class NavViewTests(unittest.TestCase):
    def test_places_weather_outbreak_and_event_come_from_the_host(self):
        with tempfile.TemporaryDirectory() as folder:
            world = SharedWorld(Path(folder) / "w.sqlite3", "world")
            try:
                code = next(v for k, v in world.spawn_director.catalogue["weather"].items() if k == "WEATHER_RAIN")
                nav = world.nav_view({"a": {"map_group": 0, "map_number": 16, "weather": code}, "b": None,
                                      "c": {"map_group": 99, "map_number": 98}})
                self.assertEqual([p["player_id"] for p in nav["players"]], ["a", "c"])
                self.assertEqual(nav["players"][0]["weather"], "Rain")
                self.assertEqual(nav["players"][0]["place"], world._place_name(0, 16))
                self.assertEqual(nav["players"][1], {"player_id": "c", "place": "Area 99-98", "weather": None})
                self.assertEqual((nav["outbreak"], nav["event"]), (None, None))
                validate_extras({"bases": [], "nav": nav})
            finally:
                world.close()


class FakeMenuCompanion:
    def __init__(self, visibility="everyone"):
        self.config = SimpleNamespace(player_id="a", world_enabled=True, menu_abi_version=1, trade_enabled=False)
        self.connected, self.world_id, self.server_epoch, self.session_epoch = True, "w", 1, 2
        self._players = [{"player_id": "a", "display_name": "Alice"}, {"player_id": "b", "display_name": "Bob"}]
        self.nav = {"players": [{"player_id": "a", "place": "ROUTE 101", "weather": "Rain"},
                                {"player_id": "b", "place": "LITTLEROOT TOWN", "weather": None}],
                    "outbreak": {"name": "WURMPLE", "place": "ROUTE 102", "seconds_left": 125}, "event": None}
        self.visibility, self.calls = visibility, []

    def world_nav(self):
        return self.nav

    async def team_rpc(self, operation, **fields):
        return {"result": {"team": None, "invitations": []}}

    async def battle_challenge_rpc(self, operation, **fields):
        return {"result": []}

    async def secret_base_rpc(self, mode=None):
        self.calls.append(mode)
        if mode is not None:
            self.visibility = mode
        return {"published": True, "visibility": self.visibility}


class MenuTests(unittest.IsolatedAsyncioTestCase):
    async def click(self, menu, label):
        row = next((r for r in menu.screen.rows if r.label == label), None)
        self.assertIsNotNone(row, [r.label for r in menu.screen.rows])
        return await menu.choose(menu.screen.revision, row.action)

    labels = staticmethod(lambda menu: [r.label for r in menu.screen.rows])

    async def test_world_pages(self):
        menu = PlayerMenu(FakeMenuCompanion())
        await menu.refresh()
        await self.click(menu, "World and my base")
        self.assertEqual(self.labels(menu), ["Players and weather", "Outbreak: WURMPLE", "World Event: none",
                                             "My Secret Base"])
        await self.click(menu, "Players and weather")
        self.assertEqual(self.labels(menu), ["Alice - ROUTE 101", "Bob - LITTLEROOT TOWN"])
        await self.click(menu, "Alice - ROUTE 101")
        self.assertIn("Weather: Rain", self.labels(menu))
        await self.click(menu, "Back to players")
        await self.click(menu, "Bob - LITTLEROOT TOWN")
        self.assertIn("Weather: unknown", self.labels(menu))
        menu._page = ("world", None)
        await menu.refresh()
        await self.click(menu, "Outbreak: WURMPLE")
        self.assertEqual(menu.screen.status, "2m 05s left")
        self.assertTrue(all(len(r.label) <= 25 for r in menu.screen.rows))

    async def test_my_secret_base_cycles_who_can_see_it(self):
        companion = FakeMenuCompanion()
        menu = PlayerMenu(companion)
        await menu.refresh()
        await self.click(menu, "World and my base")
        await self.click(menu, "My Secret Base")
        self.assertIn("Visible to: Everyone", self.labels(menu))
        await self.click(menu, "Visible to: Everyone")
        self.assertIn("Visible to: Teammate", self.labels(menu))
        await self.click(menu, "Visible to: Teammate")
        self.assertIn("Visible to: Nobody", self.labels(menu))
        await self.click(menu, "Visible to: Nobody")
        self.assertIn("Visible to: Everyone", self.labels(menu))
        self.assertEqual(companion.calls, [None, "team", "nobody", "everyone"])

    async def test_a_host_without_a_world_view_says_so(self):
        companion = FakeMenuCompanion()
        companion.nav = None
        menu = PlayerMenu(companion)
        await menu.refresh()
        await self.click(menu, "World and my base")
        self.assertEqual(menu.screen.status, "The host has no world view")

    async def test_a_full_lobby_keeps_every_row_within_six(self):
        companion = FakeMenuCompanion()
        companion._players += [{"player_id": "c", "display_name": "Cy"}, {"player_id": "d", "display_name": "Di"}]
        menu = PlayerMenu(companion)
        await menu.refresh()
        self.assertLessEqual(len(menu.screen.rows), 6)
        self.assertIn("World and my base", self.labels(menu))


def bases_of(frame):
    return struct.unpack_from("<IIIB3x", frame, 0), frame[16:176]


class SecretBaseCompanionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = world_companion.WorldCompanionTests.asyncSetUp
    asyncTearDown = world_companion.WorldCompanionTests.asyncTearDown

    async def extras_frame(self, index, predicate=lambda head, base: True, timeout=6):
        bridge = self.bridges[index]
        async with asyncio.timeout(timeout):
            while True:
                packet = await read_packet(bridge.reader)
                if packet is None:
                    raise ConnectionError("bridge closed")
                if packet[:1] == b"y":
                    self.assertEqual(len(packet), 1 + INBOUND_SIZE)
                    head, base = bases_of(packet[1:])
                    if predicate(head, base):
                        return head, base

    async def announce(self, index, base=None, seq=1):
        await self.bridges[index].send(local_record(WorldState()))
        await self.bridges[index].send(capability_packet())
        local = struct.pack("<IB3x", seq, 0 if base is None else 1) + (bytes(160) if base is None else base)
        await self.bridges[index].send(b"x" + local)

    def book(self):
        return self.server.shared_world.bases

    async def test_a_base_reaches_the_other_game_and_follows_every_change(self):
        a, b = (c.config.player_id for c in self.companions)
        await self.announce(0, make_base(owner=1, junk=True), seq=11)
        await wait_until(lambda: self.book().state(a)["published"], timeout=4)
        await self.announce(1)
        head, base = await self.extras_frame(1, lambda h, rec: rec == make_base(owner=1))
        self.assertEqual(head[0], 1)                                  # enabled
        self.assertGreater(head[2], 0)                                # a record number the game applies once
        # The owner redecorates: the other game gets the new version.
        await self.bridges[0].send(b"x" + struct.pack("<IB3x", 12, 1) + make_base(owner=1, decorations=(1, 2, 3)))
        await self.extras_frame(1, lambda h, rec: rec == make_base(owner=1, decorations=(1, 2, 3)))
        # The owner stops sharing: a withdrawal naming them arrives.
        companion = self.companions[0]
        await companion.secret_base_rpc("nobody")
        head, gone = await self.extras_frame(1, lambda h, rec: rec[0] == 0 and rec[2] == 0xBB + 1)
        self.assertEqual(gone, tombstone(make_base(owner=1)))
        await companion.secret_base_rpc("everyone")
        await self.extras_frame(1, lambda h, rec: rec == make_base(owner=1, decorations=(1, 2, 3)))
        # The owner's own game is never handed its own base.
        self.assertEqual(self.book().view_for(a, None, [a, b]), [])
        # Removing the base (no base in the save any more) withdraws it too.
        await self.bridges[0].send(b"x" + struct.pack("<IB3x", 13, 0) + bytes(160))
        await self.extras_frame(1, lambda h, rec: rec[0] == 0 and rec[2] == 0xBB + 1)
        self.assertFalse(self.book().state(a)["published"])

    async def test_the_host_acknowledges_the_games_base_number(self):
        a = self.companions[0].config.player_id
        await self.announce(0, make_base(), seq=41)
        head, _ = await self.extras_frame(0, lambda h, rec: h[1] == 41)
        self.assertEqual(head[1], 41)
        self.assertTrue(self.book().state(a)["published"])

    async def test_an_invalid_base_is_not_shared(self):
        a = self.companions[0].config.player_id
        await self.announce(0, make_base(species=1701), seq=5)
        await self.extras_frame(0, lambda h, rec: h[1] == 5)
        self.assertFalse(self.book().state(a)["published"])

    async def test_a_publication_the_host_never_got_is_sent_again(self):
        companion, a = self.companions[0], self.companions[0].config.player_id
        real, calls = companion.world_rpc, []

        async def flaky(operation, **fields):
            calls.append(operation)
            if len(calls) == 1:
                raise ConnectionError("the link dropped")
            return await real(operation, **fields)

        companion.world_rpc = flaky
        await self.announce(0, make_base(), seq=7)
        await wait_until(lambda: self.book().state(a)["published"], timeout=6)
        self.assertEqual(calls[:2], ["base_publish", "base_publish"])

    async def test_extras_records_before_the_capability_disconnect_the_bridge(self):
        await self.bridges[0].send(b"x" + struct.pack("<IB3x", 1, 0) + bytes(160))
        with self.assertRaises(ConnectionError):
            for _ in range(50):
                await self.bridges[0].world(timeout=1)

    async def test_a_disconnected_companion_turns_the_mailbox_off(self):
        await self.announce(0)
        await self.extras_frame(0, lambda h, rec: h[0] == 1)
        await self.server.close()
        await self.extras_frame(0, lambda h, rec: h[0] == 0, timeout=8)


if __name__ == "__main__":
    unittest.main()
