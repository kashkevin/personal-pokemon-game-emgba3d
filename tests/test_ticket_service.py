"""The Legendary Tickets' host service end to end (ticket_service.py; server.WorldServer.enable_tickets).

A real world server over loopback TCP with its real checkpoint store, its shared world (the ticket ledger) and its wallet
stream (wagers.Wagers). Each player's game is a scripted client: it saves on the host through the checkpoint protocol,
reports its save's wallet sequence in its presence, applies the wallet word its world frame offers when it is the next
one, answers with the receipt the engine gives (MultiplayerTickets_Grant, engine b270e14a: 1 given, 2 already owned, 0 no
room; nothing set without room) and keeps what it applied only once it saves. The engine's own application of kind 8 is
its --selftest-tickets; real games through the real launcher are scripts/multiplayer/native_launcher_ticket_proof.py.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import closing, suppress
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile
from types import SimpleNamespace
import unittest
from uuid import uuid4

from emerald_multiplayer import legendary_tickets as lt
from emerald_multiplayer import rewards
from emerald_multiplayer.flash import LAYOUT_ID
from emerald_multiplayer.protocol import (CHECKPOINT_CHUNK_BYTES, PROTOCOL_VERSION, encode_message, launcher_version,
                                          read_message)
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.shared_world import SharedWorld
from emerald_multiplayer.storage import CheckpointStore
from test_flash import _rewrite, make_flash

BUILD, RULES = "ticket-service-test", "test-rules"
GAME_CLEAR = lt.FLAG_SYS_GAME_CLEAR
SEA_MAP, EON, AURORA, MYSTIC = (lt.TICKET_BY_KEY[key] for key in ("old_sea_map", "eon", "aurora", "mystic"))
BANNER = "OLD SEA MAP!|Show it at LILYCOVE's port."


async def wait_until(predicate, timeout=8.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.005)


def save_bytes(counter, *, flags=(), hall_of_fame=0) -> bytes:
    """A synthetic save the host parses as the game's (test_flash: the newest bank is counter % 2): SaveBlock1's flags
    and the Hall of Fame statistic (XOR SaveBlock2's encryption key), at legendary_tickets' pinned offsets."""
    data, bank, key = make_flash(counter=counter, with_rtc=True), counter % 2, 0x5A5AC3C3

    def block1(offset, payload):
        return _rewrite(data, bank, 1 + offset // 3968, offset % 3968, payload)
    raw = bytearray(lt.FLAG_BYTES)
    for flag in flags:
        raw[flag // 8] |= 1 << (flag % 8)
    data = block1(lt.FLAGS_OFFSET, bytes(raw))
    data = _rewrite(data, bank, 0, lt.ENCRYPTION_KEY_OFFSET, struct.pack("<I", key))
    data = block1(lt.GAME_STATS_OFFSET + 4 * lt.GAME_STAT_ENTERED_HOF, struct.pack("<I", hall_of_fame ^ key))
    return data


class Game:
    """One player's game and its launcher, as the host sees them. ``saved`` is its last save on the host; ``live`` the
    running game's memory (what a game closed before saving loses). The Bag and the PC have room unless ``room`` is
    False."""

    def __init__(self, player, *, flags=(), hall_of_fame=0):
        state = dict(wallet_seq=0, receipt=None, items=frozenset(), flags=frozenset(flags), hall_of_fame=hall_of_fame)
        self.player, self.saved, self.live = player, dict(state), dict(state)
        self.room, self.counter, self.revision = True, 1, 0
        self.applied = []            # (seq, delta, receipt) of every word this game applied, in order
        self.reader = self.writer = self.task = None

    # the connection ---------------------------------------------------------------------------------------------
    async def connect(self, address):
        self.pending, self.worlds, self.seq = {}, [], 0
        self.reader, self.writer = await asyncio.open_connection(*address)
        await self.send(dict(type="hello", protocol=PROTOCOL_VERSION, build_id=BUILD, ruleset_id=RULES,
                             player_id=self.player.player_id, display_name=self.player.display_name,
                             credential=self.player.credential.hex(), launcher=launcher_version()))
        welcome = await asyncio.wait_for(read_message(self.reader), 8)
        assert welcome is not None and welcome["type"] == "welcome", welcome
        self.lease = welcome["session_epoch"]
        self.task = asyncio.create_task(self._read())
        # Once per connection the game reports its save's last receipt again (engine UpdateWallet).
        if self.live["wallet_seq"]:
            await self.request("wallet_applied", seq=self.live["wallet_seq"], amount=self.live["receipt"])
        await self.present()
        return self

    async def send(self, message):
        self.writer.write(encode_message(message))
        await self.writer.drain()

    async def _read(self):
        try:
            while True:
                message = await read_message(self.reader)
                if message is None:
                    return
                if message["type"] == "ping":
                    await self.send({**message, "type": "pong"})
                elif message["type"] == "world":
                    self.worlds.append(message)
                    del self.worlds[:-4]
                else:
                    future = self.pending.get(message.get("request_id"))
                    if future is not None and not future.done():
                        future.set_result(message)
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("the game's link closed"))

    async def request(self, kind, **fields):
        request_id = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.send(dict(type=kind, session_epoch=self.lease, request_id=request_id, **fields))
            return await asyncio.wait_for(future, 8)
        finally:
            self.pending.pop(request_id, None)

    async def present(self):
        self.seq += 1
        await self.send(dict(type="presence", session_epoch=self.lease, seq=self.seq, map_epoch=0, map_group=0,
                             map_number=9, x=6, y=11, direction=1, elevation=0, avatar_gender=0, activity="overworld",
                             wallet_seq=self.live["wallet_seq"] & 0xFF))

    async def close(self):
        if self.writer is not None:
            self.writer.close()
            with suppress(ConnectionError, OSError):
                await self.writer.wait_closed()
        if self.task is not None:
            if not self.task.done():
                self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.writer = self.task = None

    # the game ---------------------------------------------------------------------------------------------------
    async def save(self):
        """The game saves on the host (the checkpoint protocol); its save holds the running game's state."""
        live = self.live
        flags = set(live["flags"]) | {lt.TICKET_BY_INDEX[i].ship_flag for i in live["items"]}
        self.counter += 1
        payload = save_bytes(self.counter, flags=flags, hall_of_fame=live["hall_of_fame"])
        values = dict(expected_revision=self.revision, size=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
                      save_profile=LAYOUT_ID)
        reply = await self.request("checkpoint_begin", **values)
        assert reply["type"] == "checkpoint_result", reply
        upload = reply["upload_id"]
        for offset in range(0, len(payload), CHECKPOINT_CHUNK_BYTES):
            chunk = payload[offset:offset + CHECKPOINT_CHUNK_BYTES]
            reply = await self.request("checkpoint_chunk", upload_id=upload, offset=offset,
                                       data_b64=base64.b64encode(chunk).decode("ascii"))
            assert reply["type"] == "checkpoint_result", reply
        reply = await self.request("checkpoint_commit", upload_id=upload, **values)
        assert reply["type"] == "checkpoint_result", reply
        self.revision = reply["checkpoint"]["revision"]
        self.saved = dict(live)
        return self.revision

    def close_without_saving(self):
        """The game ends before saving: what it applied since its last save is gone with it."""
        self.live = dict(self.saved)

    def offered(self):
        """The wallet adjustment the host's latest world frame offers this game (None: none)."""
        return self.worlds[-1]["wallet"] if self.worlds else None

    async def apply(self, server, *, report=True):
        """The next wallet word, as the engine applies it in a calm field: only seq = its save's + 1; kind 8 gives the
        ticket in the Bag (else the PC) with its ship flag, 2 when either holds it already, 0 without room (nothing set).
        The receipt goes to the host (world action 5 -> wallet_applied) unless ``report`` is False (lost on the way)."""
        server._broadcast_world()
        await wait_until(lambda: self.offered() is not None
                         and self.offered()["seq"] == (self.live["wallet_seq"] + 1) & 0xFFFF)
        word = self.offered()
        decoded = rewards.decode(word["delta"], tickets=True)
        assert decoded is not None and decoded[0] == rewards.KIND_TICKET, word
        index, live = decoded[1], self.live
        if index in live["items"]:
            receipt = lt.RECEIPT_OWNED
        elif self.room:
            receipt, live["items"] = lt.RECEIPT_GIVEN, live["items"] | {index}
        else:
            receipt = lt.RECEIPT_NO_ROOM
        live.update(wallet_seq=word["seq"], receipt=receipt)
        self.applied.append((word["seq"], word["delta"], receipt))
        if report:
            reply = await self.request("wallet_applied", seq=word["seq"], amount=receipt)
            assert reply["type"] == "world_result", reply
            await self.present()
        return word["seq"], word["delta"], receipt


class TicketServiceTests(unittest.IsolatedAsyncioTestCase):
    tickets = True               # the host's game applies kind 8 (manifest ticket_abi_version 1)
    sources = None               # the world's setting (None: the owner's defaults)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "world.sqlite3"
        self.store = CheckpointStore(self.path, BUILD, RULES, LAYOUT_ID)
        self.alice, self.bob = (self.store.create_player(name) for name in ("Alice", "Bob"))
        self.games = {}
        await self.start_host()

    async def asyncTearDown(self):
        for game in self.games.values():
            await game.close()
        await self.server.close()
        self.store.close()

    async def start_host(self):
        self.server = WorldServer(ServerConfig(BUILD, RULES, heartbeat_interval=.05, idle_timeout=20,
                                               monitor_interval=.005), store=self.store)
        if self.tickets:
            self.server.enable_tickets(self.sources)
        await self.server.start(port=0)

    async def restart_host(self):
        """The host process stops and starts again on the same world files."""
        for game in self.games.values():
            await game.close()
        await self.server.close()
        self.store.close()
        self.store = CheckpointStore(self.path, BUILD, RULES, LAYOUT_ID)
        await self.start_host()

    async def join(self, player, **state):
        game = self.games.get(player.player_id) or Game(player, **state)
        self.games[player.player_id] = game
        await game.connect(self.server.address)
        await wait_until(lambda: (self.server.sessions.get(player.player_id) is not None
                                  and self.server.sessions[player.player_id].presence is not None))
        return game

    # what the host holds --------------------------------------------------------------------------------------------
    def words(self, player):
        """(seq, delta, reference, receipt) of the player's wallet stream."""
        return [(w["seq"], w["delta"], w["battle_id"], w["applied"]) for w in self.server.wagers.pending_for(player.player_id)]

    def state(self, player, key):
        row = self.server.shared_world.tickets.row(player.player_id, key)
        return None if row is None else row["state"]

    def notices(self, player):
        world = self.server.shared_world
        return [n["text"] for n in [world._notice, *world._notice_queue]
                if n is not None and n["to"] is not None and player.player_id in n["to"]]

    async def tick(self, until):
        """The host's own 5 s pass, now (the monitor runs it once its last one is 5 s old)."""
        self.server._last_ticket_tick = 0.0
        await wait_until(until)


class GrantTests(TicketServiceTests):
    async def test_a_ticket_from_a_save_on_the_host_to_the_bag_exactly_once(self):
        alice = await self.join(self.alice, flags=lt.REGI_FLAGS + (GAME_CLEAR,))
        bob = await self.join(self.bob, flags=(GAME_CLEAR,))
        self.assertEqual(self.words(self.alice), [])
        await alice.save()                                      # the save that shows the quest done: the pass at once
        self.assertEqual(self.words(self.alice), [(1, 0x48000004, "ticket:old_sea_map:1", None)])
        self.assertEqual(self.state(self.alice, "old_sea_map"), "sent")
        await bob.save()
        self.assertEqual(self.words(self.bob), [])
        self.assertEqual(await alice.apply(self.server), (1, 0x48000004, lt.RECEIPT_GIVEN))
        self.assertEqual(alice.live["items"], {SEA_MAP.index})
        await self.tick(lambda: self.state(self.alice, "old_sea_map") == "delivered")
        self.assertEqual(self.notices(self.alice), [BANNER])
        self.assertEqual(self.notices(self.bob), [])
        await alice.save()                                      # the next save holds the ticket and its island's flag
        for _ in range(3):
            self.server._last_ticket_tick = 0.0
            await asyncio.sleep(.05)
        self.assertEqual(self.words(self.alice), [(1, 0x48000004, "ticket:old_sea_map:1", 1)])
        self.assertEqual(self.notices(self.alice), [BANNER])
        self.server._broadcast_world()
        await wait_until(lambda: bob.worlds and alice.worlds and alice.offered() is None)
        self.assertIsNone(bob.offered())
        self.assertEqual(self.words(self.bob), [])
        self.assertEqual([row["ticket"] for row in self.server.shared_world.tickets.rows(self.bob.player_id)], [])

    async def test_the_world_frame_carries_the_word_to_its_player_only(self):
        alice = await self.join(self.alice, flags=lt.WEATHER_FLAGS)
        bob = await self.join(self.bob)
        await alice.save()
        self.server._broadcast_world()
        await wait_until(lambda: alice.offered() is not None and bob.worlds)
        self.assertEqual(alice.offered(), {"seq": 1, "delta": 0x48000003})          # the Aurora Ticket
        self.assertIsNone(bob.offered())

    async def test_two_players_each_get_their_own(self):
        alice = await self.join(self.alice, flags=lt.REGI_FLAGS)
        bob = await self.join(self.bob, flags=lt.WEATHER_FLAGS + (GAME_CLEAR,), hall_of_fame=2)
        await alice.save()
        await bob.save()
        self.assertEqual([w[2] for w in self.words(self.alice)], ["ticket:old_sea_map:1"])
        self.assertEqual(sorted(w[2] for w in self.words(self.bob)), ["ticket:aurora:1", "ticket:eon:1"])
        for _ in range(2):
            await bob.apply(self.server)
        await alice.apply(self.server)
        await self.tick(lambda: all(self.state(self.bob, key) == "delivered" for key in ("eon", "aurora"))
                        and self.state(self.alice, "old_sea_map") == "delivered")
        self.assertEqual(self.notices(self.alice), [BANNER])
        self.assertEqual(sorted(self.notices(self.bob)), ["AURORA TICKET!|Show it at LILYCOVE's port.",
                                                          "EON TICKET!|Show it at LILYCOVE's port."])
        self.assertEqual(bob.live["items"], {EON.index, AURORA.index})
        self.assertEqual(alice.live["items"], {SEA_MAP.index})

    async def test_a_save_that_already_opens_the_island_is_sent_nothing(self):
        alice = await self.join(self.alice, flags=lt.REGI_FLAGS + (SEA_MAP.ship_flag,))
        await alice.save()
        await self.tick(lambda: self.server._last_ticket_tick > 0)
        await asyncio.sleep(.05)
        self.assertEqual(self.words(self.alice), [])
        self.assertIsNone(self.state(self.alice, "old_sea_map"))


class FailureTests(TicketServiceTests):
    async def test_a_host_restart_between_the_word_and_its_receipt(self):
        alice = await self.join(self.alice, flags=lt.REGI_FLAGS)
        await alice.save()
        await alice.apply(self.server, report=False)             # the game has it; its receipt is lost with the host
        await self.restart_host()                                # (the restarted host never heard the receipt)
        self.assertIsNone(self.server.wagers.entry(self.alice.player_id, "ticket:old_sea_map:1")["applied"])
        self.assertEqual(self.state(self.alice, "old_sea_map"), "sent")
        await self.join(self.alice)                              # the game reports its last receipt on connecting
        await self.tick(lambda: self.state(self.alice, "old_sea_map") == "delivered")
        self.assertEqual(self.notices(self.alice), [BANNER])
        self.assertEqual([w[:3] for w in self.words(self.alice)], [(1, 0x48000004, "ticket:old_sea_map:1")])
        self.assertEqual(alice.applied, [(1, 0x48000004, 1)])

    async def test_a_host_restart_before_the_game_applied_it_queues_nothing_new(self):
        alice = await self.join(self.alice, flags=lt.REGI_FLAGS)
        await alice.save()
        await self.restart_host()
        await self.join(self.alice)
        for _ in range(3):
            self.server._last_ticket_tick = 0.0
            await asyncio.sleep(.05)
        self.assertEqual([w[:3] for w in self.words(self.alice)], [(1, 0x48000004, "ticket:old_sea_map:1")])
        await alice.apply(self.server)
        await self.tick(lambda: self.state(self.alice, "old_sea_map") == "delivered")
        self.assertEqual(alice.live["items"], {SEA_MAP.index})

    async def test_a_reconnect_after_saving_sends_no_second_word(self):
        alice = await self.join(self.alice, flags=lt.REGI_FLAGS)
        await alice.save()
        await alice.apply(self.server)
        await self.tick(lambda: self.state(self.alice, "old_sea_map") == "delivered")
        await alice.save()
        await alice.close()
        await wait_until(lambda: self.alice.player_id not in self.server.sessions)
        await self.join(self.alice)
        for _ in range(3):
            self.server._last_ticket_tick = 0.0
            await asyncio.sleep(.05)
        self.server._broadcast_world()
        await wait_until(lambda: alice.worlds)
        self.assertIsNone(alice.offered())
        self.assertEqual(self.words(self.alice), [(1, 0x48000004, "ticket:old_sea_map:1", 1)])
        self.assertEqual(self.notices(self.alice), [BANNER])
        self.assertEqual(alice.applied, [(1, 0x48000004, 1)])

    async def test_a_game_closed_before_saving_gets_the_same_word_and_one_ticket(self):
        alice = await self.join(self.alice, flags=lt.REGI_FLAGS)
        await alice.save()
        await alice.apply(self.server)
        await self.tick(lambda: self.state(self.alice, "old_sea_map") == "delivered")
        self.assertEqual(self.notices(self.alice), [BANNER])
        await alice.close()
        alice.close_without_saving()                             # after the banner, before saving: the ticket is gone
        self.assertEqual(alice.live["items"], frozenset())
        await wait_until(lambda: self.alice.player_id not in self.server.sessions)
        await self.join(self.alice)
        self.assertEqual(await alice.apply(self.server), (1, 0x48000004, lt.RECEIPT_GIVEN))    # the same word again
        self.assertEqual(alice.live["items"], {SEA_MAP.index})                    # one ticket
        await alice.save()
        self.assertEqual([w[:3] for w in self.words(self.alice)], [(1, 0x48000004, "ticket:old_sea_map:1")])
        self.assertEqual(self.state(self.alice, "old_sea_map"), "delivered")

    async def test_no_room_is_owed_and_offered_again_only_after_a_newer_save(self):
        alice = await self.join(self.alice, flags=lt.REGI_FLAGS)
        alice.room = False
        revision = await alice.save()
        self.assertEqual(await alice.apply(self.server), (1, 0x48000004, lt.RECEIPT_NO_ROOM))
        await self.tick(lambda: self.state(self.alice, "old_sea_map") == "owed")
        row = self.server.shared_world.tickets.row(self.alice.player_id, "old_sea_map")
        self.assertEqual((row["receipt"], row["owed_revision"]), (0, revision))
        self.assertEqual(self.notices(self.alice), ["NO ROOM FOR THE OLD SEA MAP|Make room, then save"])
        alice.room = True                                        # room made, but not saved yet: nothing new
        for _ in range(3):
            self.server._last_ticket_tick = 0.0
            await asyncio.sleep(.05)
        self.assertEqual(len(self.words(self.alice)), 1)
        await alice.save()                                       # the newer save: the next attempt at once
        self.assertEqual([w[:3] for w in self.words(self.alice)], [(1, 0x48000004, "ticket:old_sea_map:1"),
                                                                   (2, 0x48000004, "ticket:old_sea_map:2")])
        self.assertEqual(await alice.apply(self.server), (2, 0x48000004, lt.RECEIPT_GIVEN))
        await self.tick(lambda: self.state(self.alice, "old_sea_map") == "delivered")
        self.assertEqual(self.notices(self.alice)[-1], BANNER)
        self.assertEqual(alice.live["items"], {SEA_MAP.index})

    async def test_a_fault_never_stops_the_host_loop_a_save_or_another_player(self):
        alice = await self.join(self.alice, flags=lt.REGI_FLAGS)
        bob = await self.join(self.bob, flags=lt.WEATHER_FLAGS)
        book = self.server.shared_world.tickets
        real_rows = book.rows

        def broken(player):
            if player == self.alice.player_id:
                raise sqlite3.OperationalError("a fault in Alice's pass")
            return real_rows(player)
        book.rows = broken
        await alice.save()                                       # the save commits whatever the pass does
        await bob.save()
        self.assertEqual(self.words(self.alice), [])
        self.assertEqual([w[2] for w in self.words(self.bob)], ["ticket:aurora:1"])
        await self.tick(lambda: self.server.tickets.faults >= 2)
        self.assertIn("a fault in Alice's pass", self.server.tickets.last_fault)
        reply = await alice.request("tickets_get")
        self.assertEqual((reply["type"], reply["code"]), ("world_error", "tickets_failed"))
        self.assertIn(self.alice.player_id, self.server.sessions)       # an answer, not a dropped link
        self.assertFalse(self.server._monitor_task.done())
        book.rows = real_rows
        await self.tick(lambda: self.state(self.alice, "old_sea_map") == "sent")
        self.assertEqual([w[2] for w in self.words(self.alice)], ["ticket:old_sea_map:1"])

    async def test_an_unreadable_pass_never_stops_the_monitor(self):
        await self.join(self.alice, flags=lt.REGI_FLAGS)
        self.server._ticket_service.reconcile = lambda players=None: 1 / 0
        await self.tick(lambda: self.server._last_ticket_tick > 0)
        await asyncio.sleep(.05)
        self.assertFalse(self.server._monitor_task.done())
        self.assertFalse(self.server._reconcile_tickets())


class PageTests(TicketServiceTests):
    async def test_the_page_through_the_protocol(self):
        alice = await self.join(self.alice, flags=lt.REGI_FLAGS[:2] + lt.WEATHER_FLAGS, hall_of_fame=1)
        reply = await alice.request("tickets_get")
        self.assertEqual(reply["type"], "world_result")
        view = reply["result"]
        self.assertEqual(view["problem"], "Save your game first")
        self.assertEqual([t["state"] for t in view["tickets"]], ["locked"] * 4)
        self.assertTrue(all(s["have"] is None for t in view["tickets"] for s in t["sources"]))
        await alice.save()
        view = (await alice.request("tickets_get"))["result"]
        from emerald_multiplayer.ticket_service import validate_view
        self.assertIs(validate_view(view), view)
        tickets = {t["key"]: t for t in view["tickets"]}
        self.assertEqual([t["key"] for t in view["tickets"]], ["eon", "mystic", "aurora", "old_sea_map"])
        self.assertIsNone(view["problem"])
        self.assertEqual((tickets["eon"]["state"], tickets["eon"]["island"]), ("locked", "Southern Island"))
        self.assertEqual(tickets["eon"]["sources"], [{"text": "hall_of_fame:2", "label": "Enter the Hall of Fame 2 time(s)",
                                                      "short": "Hall of Fame", "have": 1, "need": 2, "solo": True}])
        self.assertEqual([(s["short"], s["have"], s["need"]) for s in tickets["mystic"]["sources"]],
                         [("Silver Symbols", 0, 7), ("Tower floor", 0, 75)])
        self.assertEqual((tickets["aurora"]["state"], tickets["aurora"]["earned_by"]), ("sending", "weather_trio"))
        self.assertEqual(tickets["old_sea_map"]["sources"][0]["have"], 2)
        await alice.apply(self.server)
        view = (await alice.request("tickets_get"))["result"]    # the page brings the ledger up to date first
        self.assertEqual({t["key"]: t["state"] for t in view["tickets"]}["aurora"], "given")
        self.assertEqual(self.notices(self.alice), ["AURORA TICKET!|Show it at LILYCOVE's port."])

    async def test_the_island_open_in_the_save_counts_as_given(self):
        alice = await self.join(self.alice, flags=(MYSTIC.ship_flag,))
        await alice.save()
        view = (await alice.request("tickets_get"))["result"]
        self.assertEqual({t["key"]: t["state"] for t in view["tickets"]}["mystic"], "given")


class HostRecordTests(TicketServiceTests):
    sources = {"eon": ["coop_league:1"], "mystic": ["tower_floor:75"], "aurora": ["championship_wins:1"],
               "old_sea_map": ["coop_frontier_streak:7"]}

    async def test_the_hosts_own_records_earn_tickets(self):
        world, player = self.server.shared_world, self.alice.player_id
        alice = await self.join(self.alice)
        await alice.save()
        self.assertEqual(self.words(self.alice), [])
        world.tower.sync(player, "Alice", SimpleNamespace(progress=76, highest=75, claims=0, revision=1), outstanding=0)
        with world._transaction():
            world._db.execute("INSERT INTO frontier_records VALUES (?, 7, 1, 7, 0)", (player,))
            world._db.execute("INSERT INTO league_records VALUES (?, 1, 3, 1.0, 1.0)", (player,))
        self.server._championships = SimpleNamespace(statistics=lambda actor: {"entries": 1, "completed": 1,
                                                                               "wins": 1 if actor == player else 0})
        await self.tick(lambda: len(self.words(self.alice)) == 4)
        self.assertEqual(sorted(w[2] for w in self.words(self.alice)),
                         ["ticket:aurora:1", "ticket:eon:1", "ticket:mystic:1", "ticket:old_sea_map:1"])
        sources = {row["ticket"]: row["source"] for row in world.tickets.rows(player)}
        self.assertEqual(sources, {"eon": "coop_league:1", "mystic": "tower_floor:75", "aurora": "championship_wins:1",
                                   "old_sea_map": "coop_frontier_streak:7"})


class SettingTests(TicketServiceTests):
    async def test_the_worlds_file_replaces_a_tickets_line(self):
        await self.server.close()
        settings = lt.settings_path(self.path)
        self.assertEqual(settings.name, "world.sqlite3.tickets.json")
        settings.write_text(json.dumps({"sources": {"eon": ["hall_of_fame:1"]}}), encoding="utf-8")
        self.server = WorldServer(ServerConfig(BUILD, RULES, heartbeat_interval=.05, idle_timeout=20,
                                               monitor_interval=.005), store=self.store)
        self.server.enable_tickets(lt.load_sources(settings))
        await self.server.start(port=0)
        self.assertEqual(self.server.tickets.sources["eon"], (lt.Source("hall_of_fame", 1),))
        self.assertEqual(self.server.tickets.sources["aurora"], (lt.Source("weather_trio", None),))
        alice = await self.join(self.alice, flags=(GAME_CLEAR,))
        await alice.save()
        self.assertEqual([w[2] for w in self.words(self.alice)], ["ticket:eon:1"])

    async def test_enable_tickets_checks_its_setting_and_comes_before_the_host_opens(self):
        with self.assertRaises(ValueError):
            self.server.enable_tickets()                          # the host is open
        server = WorldServer(ServerConfig(BUILD, RULES), store=None)
        self.addAsyncCleanup(server.close)
        for bad in ({"eon": ["casino"]}, {"eon": ["hall_of_fame:2"]}, {**lt.DEFAULT_SOURCES, "gs_ball": ["regi_trio"]}):
            with self.subTest(bad=bad), self.assertRaises(lt.TicketError):
                server.enable_tickets(bad)
        self.assertIsNone(server.tickets)
        server.enable_tickets()
        self.assertEqual(server.tickets.sources, lt.validate_sources(lt.DEFAULT_SOURCES))
        self.assertEqual(lt.CASINO_PRICES, {})                    # no Game Corner ticket


class WithoutTheCapabilityTests(TicketServiceTests):
    tickets = False              # an older game: no gMultiplayerTicketAbiVersion in its manifest

    async def test_a_host_whose_game_has_no_tickets_never_queues_kind_8(self):
        alice = await self.join(self.alice, flags=lt.REGI_FLAGS + lt.WEATHER_FLAGS + (GAME_CLEAR,), hall_of_fame=2)
        await alice.save()
        self.server._last_ticket_tick = 0.0
        await asyncio.sleep(.1)
        self.assertIsNone(self.server.tickets)
        self.assertEqual(self.words(self.alice), [])
        self.assertEqual(self.server.shared_world.tickets.rows(self.alice.player_id), [])
        self.server._broadcast_world()
        await wait_until(lambda: alice.worlds)
        self.assertIsNone(alice.offered())
        reply = await alice.request("tickets_get")
        self.assertEqual((reply["type"], reply["code"]), ("world_error", "tickets_disabled"))
        self.assertIn(self.alice.player_id, self.server.sessions)


class ExistingWorldTests(unittest.TestCase):
    def test_a_world_written_before_the_tickets_opens_unchanged(self):
        """The Update 14 shared-world fixture (test_save_compat): every table and row it had is as it was; the ledger's
        empty table is added beside them, and works."""
        from test_save_compat import U14, WORLD, build_database
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "copy"
            shutil.copytree(U14, folder)
            path = build_database(folder)

            def tables():
                with closing(sqlite3.connect(path)) as db:
                    schema = dict(db.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"))
                    rows = {name: sorted(db.execute(f"SELECT * FROM {name}"), key=repr) for name in schema}
                return schema, rows
            schema, rows = tables()
            self.assertNotIn("legendary_tickets", schema)
            world = SharedWorld(path, WORLD)
            try:
                self.assertEqual(world.tickets.rows("someone"), [])
                self.assertTrue(world.tickets.earn("someone", "eon", "hall_of_fame:2"))
            finally:
                world.close()
            after, after_rows = tables()
            for name, sql in schema.items():
                self.assertEqual(after[name], sql, name)
                if name not in ("kv", "clock", "events"):         # close() persists the clock and the event timers
                    self.assertEqual(after_rows[name], rows[name], name)
            self.assertIn("legendary_tickets", after)
            self.assertEqual([r[:3] for r in after_rows["legendary_tickets"]], [("someone", "eon", "earned")])


class LauncherHostingTests(unittest.IsolatedAsyncioTestCase):
    """The launcher's host enables the tickets exactly when its installed game's manifest has them, with the world's
    setting read before the host opens (test_launcher_session's hosting fixture)."""

    def setUp(self):
        from test_launcher_session import LauncherSessionTests
        LauncherSessionTests.setUp(self)

    async def asyncTearDown(self):
        from test_launcher_session import LauncherSessionTests
        await LauncherSessionTests.asyncTearDown(self)

    def session(self, **options):
        from test_launcher_session import LauncherSessionTests
        return LauncherSessionTests.session(self, **options)

    async def test_a_game_without_the_tickets_hosts_without_them(self):
        lt.settings_path(self.host.database_path).write_text("{", encoding="utf-8")   # never read for such a game
        session = self.session()
        async with session.open():
            self.assertIsNone(session._server.tickets)

    async def test_a_game_with_the_tickets_hosts_with_the_worlds_setting(self):
        from unittest.mock import patch
        seen = []

        def enabled(manifest):
            seen.append(manifest)
            return True
        lt.settings_path(self.host.database_path).write_text(json.dumps({"sources": {"eon": ["hall_of_fame:1"]}}),
                                                             encoding="utf-8")
        with patch("emerald_multiplayer.bridge_config.tickets_enabled", enabled):
            session = self.session()
            async with session.open():
                tickets = session._server.tickets
                self.assertIsNotNone(tickets)
                self.assertEqual(tickets.sources["eon"], (lt.Source("hall_of_fame", 1),))
                self.assertEqual(tickets.sources["mystic"], (lt.Source("silver_symbols", 7), lt.Source("tower_floor", 75)))
        self.assertIs(seen[0], session._manifest)                                     # the installed game's manifest

    async def test_a_setting_that_cannot_be_used_stops_the_host_and_names_the_problem(self):
        from unittest.mock import patch
        from emerald_multiplayer.launcher_session import LauncherSessionError
        lt.settings_path(self.host.database_path).write_text(json.dumps({"sources": {"gs_ball": ["regi_trio"]}}),
                                                             encoding="utf-8")
        with patch("emerald_multiplayer.bridge_config.tickets_enabled", lambda manifest: True):
            session = self.session()
            with self.assertRaises(LauncherSessionError) as caught:
                async with session.open():
                    self.fail("the host opened with a setting it cannot use")
        self.assertEqual(caught.exception.code, "ticket_settings_invalid")
        self.assertIn("names unknown tickets: gs_ball", caught.exception.cause)
        self.assertIsNone(session._server)


if __name__ == "__main__":
    unittest.main()
