"""The Legendary Tickets: every byte between the engine and the app (docs/legendary-tickets.md section 6.1).

Reward word kind 8 (its layout, its payloads, its receipts), the capability (the native marker gMultiplayerTicketAbiVersion
-> manifest ticket_abi_version 1, beside the shared world; no bridge.txt opt-in; the companion's configuration; the
Windows package's marker and self-test lists) and the rule that a game without it never receives kind 8: the wire, the
world mailbox and a real companion all refuse it. The engine checks the same numbers in its --selftest-tickets (24 checks,
engine b270e14a); a real game applying them is the real-game proof (scripts/multiplayer/native_launcher_ticket_proof.py).
"""
from __future__ import annotations

import json
import re
import secrets
import struct
import tempfile
import unittest
from uuid import uuid4

from emerald_multiplayer import legendary_tickets as lt
from emerald_multiplayer import rewards
from emerald_multiplayer.bridge_config import configure_native, tickets_enabled
from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.shared_world import _banner
from emerald_multiplayer.shared_world_protocol import validate_wallet, validate_world_request
from emerald_multiplayer.world_mailbox import WALLET_OFFSET, WorldInbound, WorldMailboxError

TOKEN = "ab" * 32
MARKER = "00bd27a4 00000004 R gMultiplayerTicketAbiVersion\n"


class WordTests(unittest.TestCase):
    def test_the_word_layout_is_the_engines(self):
        """0x48000000 | index: bit 30 the reward flag, bits 24-27 kind 8 (MP_REWARD_TICKET), bits 0-7 the ticket's index
        (MP_TICKET_EON 1, _MYSTIC 2, _AURORA 3, _OLD_SEA_MAP 4), bits 8-23 zero; a signed 32-bit wallet delta."""
        self.assertEqual(rewards.KIND_TICKET, 8)
        self.assertEqual({t.key: t.index for t in lt.TICKETS}, {"eon": 1, "mystic": 2, "aurora": 3, "old_sea_map": 4})
        self.assertEqual(rewards.TICKET_INDEXES, frozenset(t.index for t in lt.TICKETS))
        for ticket in lt.TICKETS:
            word = rewards.encode(rewards.KIND_TICKET, ticket.index, tickets=True)
            self.assertEqual(word, rewards.REWARD_FLAG | (8 << 24) | ticket.index)
            self.assertEqual(word & 0x00FFFF00, 0)
            self.assertLess(word, 2 ** 31)
            self.assertTrue(rewards.is_reward_word(word))
            self.assertEqual(rewards.decode(word, tickets=True), (8, ticket.index))
        self.assertEqual([hex(rewards.encode(8, i, tickets=True)) for i in (1, 2, 3, 4)],
                         ["0x48000001", "0x48000002", "0x48000003", "0x48000004"])

    def test_the_receipts_and_the_reference(self):
        """MP_TICKET_RECEIPT_GIVEN 1, _OWNED 2, _NOTHING 0; one word per (player, ticket:<name>:<attempt>)."""
        self.assertEqual((lt.RECEIPT_GIVEN, lt.RECEIPT_OWNED, lt.RECEIPT_NO_ROOM), (1, 2, 0))
        self.assertEqual(lt.ticket_ref("old_sea_map", 3), "ticket:old_sea_map:3")

    def test_the_banner_is_the_designs_two_lines(self):
        for ticket in lt.TICKETS:
            text = _banner(*lt.notice(ticket))
            self.assertEqual(text, f"{ticket.name.upper()}!|Show it at LILYCOVE's port.")
            self.assertLessEqual(len(text), 64)
        self.assertEqual(_banner(*lt.notice(lt.TICKET_BY_KEY["eon"])).split("|"), ["EON TICKET!",
                                                                                  "Show it at LILYCOVE's port."])

    def test_nothing_else_is_a_ticket(self):
        for payload in (0, 5, 0x100 | 1, 0x10001, 0xFFFFFF):
            with self.subTest(payload=hex(payload)), self.assertRaises(rewards.RewardError):
                rewards.encode(8, payload, tickets=True)
        for kind in (9, 15):
            with self.assertRaises(rewards.RewardError):
                rewards.encode(kind, 1, tower=True, tickets=True)


class WireTests(unittest.TestCase):
    def test_the_wire_and_the_mailbox_carry_kind_8_only_with_the_capability(self):
        word = rewards.encode(8, 2, tickets=True)
        self.assertEqual(validate_wallet({"seq": 2, "delta": word}, tickets=True), {"seq": 2, "delta": word})
        for options in ({}, {"tower": True}, {"tickets": False}):
            with self.subTest(options=options), self.assertRaises(ProtocolError):
                validate_wallet({"seq": 2, "delta": word}, **options)
        inbound = WorldInbound(wallet_seq=2, wallet_delta=word, tickets=True).pack()
        self.assertEqual(struct.unpack_from("<Ii", inbound, WALLET_OFFSET), (2, word))
        for options in ({}, {"tower": True}):
            with self.assertRaises(WorldMailboxError):
                WorldInbound(wallet_seq=2, wallet_delta=word, **options)
        with self.assertRaises(WorldMailboxError):
            WorldInbound(tickets=1)
        self.assertEqual(WorldInbound(tickets=True).pack(), WorldInbound().pack())     # the flag itself is never sent

    def test_the_page_is_a_plain_read(self):
        base = dict(type="tickets_get", session_epoch=4, request_id=str(uuid4()))
        self.assertEqual(validate_world_request(base, 4), base)
        for request in ({**base, "op": "status"}, {**base, "ticket": "eon"}):
            with self.assertRaises(ProtocolError):
                validate_world_request(request, 4)


class CapabilityTests(unittest.TestCase):
    def manifest(self, **changes):
        return {"world_abi_version": 1, "ticket_abi_version": 1, **changes}

    def test_the_host_and_the_companion_read_the_same_manifest_fields(self):
        self.assertTrue(tickets_enabled(self.manifest()))
        for changes in (dict(ticket_abi_version=2), dict(ticket_abi_version=True), dict(ticket_abi_version=None),
                        dict(ticket_abi_version="1"), dict(world_abi_version=None), dict(world_abi_version=True),
                        dict(world_abi_version=2)):
            with self.subTest(changes=changes):
                self.assertFalse(tickets_enabled(self.manifest(**changes)))
        self.assertFalse(tickets_enabled({"world_abi_version": 1}))

    def test_no_bridge_opt_in(self):
        """The game applies kind 8 whenever it has the code: bridge.txt says nothing of tickets."""
        for manifest in (self.manifest(), {}):
            self.assertNotIn("ticket", configure_native(manifest, TOKEN, 9))

    def test_the_companion_reads_its_games_capability(self):
        from emerald_multiplayer.companion import CompanionConfig
        from test_world_companion import make_world_files
        for extra, expected in (({}, 0), ({"ticket_abi_version": 1}, 1), ({"ticket_abi_version": 2}, 0),
                                ({"ticket_abi_version": True}, 0)):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temp:
                rom, manifest = make_world_files(temp)
                data = json.loads(manifest.read_text())
                data.update(extra)
                manifest.write_text(json.dumps(data))
                config = CompanionConfig(rom, manifest, str(uuid4()), "Alice", secrets.token_bytes(32), ipc_port=0)
                self.assertTrue(config.world_enabled)
                self.assertEqual(config.ticket_abi_version, expected)

    def test_a_game_without_the_shared_world_has_no_tickets(self):
        from emerald_multiplayer.companion import CompanionConfig
        from test_companion import make_files
        with tempfile.TemporaryDirectory() as temp:
            rom, manifest = make_files(temp)
            data = json.loads(manifest.read_text())
            data["ticket_abi_version"] = 1
            manifest.write_text(json.dumps(data))
            config = CompanionConfig(rom, manifest, str(uuid4()), "Alice", secrets.token_bytes(32), ipc_port=0)
            self.assertFalse(config.world_enabled)
            self.assertEqual(config.ticket_abi_version, 0)


class ManifestTests(unittest.TestCase):
    """The marker comes from the native executable, beside the shared world mailbox."""

    def setUp(self):
        from test_battle_manifest import CoopAndWorldManifestTests
        self.fixture = CoopAndWorldManifestTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def generate(self, elf, native):
        f = self.fixture
        return f.generate_native(f.base + f.battle + elf, native)

    def test_the_marker_needs_the_shared_world(self):
        f = self.fixture
        generated = self.generate(f.world, MARKER)
        self.assertEqual((generated["ticket_abi_version"], generated["world_abi_version"]), (1, 1))
        self.assertTrue(tickets_enabled(generated))
        self.assertNotIn("ticket", configure_native(generated, TOKEN, 9))
        mingw = self.generate(f.world, "00bd27a4 R _gMultiplayerTicketAbiVersion\n")   # MinGW nm prints no size
        self.assertEqual(mingw["ticket_abi_version"], 1)
        self.assertNotIn("ticket_abi_version", self.generate(f.world, ""))             # an older game: no tickets
        self.assertNotIn("ticket_abi_version", self.generate(f.world, "00bd27a4 T gMultiplayerTicketAbiVersion\n"))
        for elf, native in (("", MARKER),                                              # no shared world
                            (f.world, MARKER + MARKER),
                            (f.world, "00bd27a4 00000008 R gMultiplayerTicketAbiVersion\n")):
            with self.subTest(elf=elf, native=native), self.assertRaises(ValueError):
                self.generate(elf, native)

    def test_the_windows_package_checks_the_marker_and_runs_the_self_test(self):
        from test_windows_workflow import WORKFLOW, job
        markers = re.search(r"markers = \{(.*?)\}", WORKFLOW, re.S).group(1)
        self.assertIn('"gMultiplayerTicketAbiVersion": "ticket_abi_version"', markers)
        self.assertIn('"tickets"', re.search(r"\$tests = @\((.*?)\)", job("selftests"), re.S).group(1))


class CompanionTests(unittest.IsolatedAsyncioTestCase):
    """A host's ticket word reaches a real companion's game mailbox exactly when the game has the tickets: a companion
    whose game has none refuses the world frame that carries one (even from a host that queued it) and never writes it."""

    async def start(self, *, capability):
        from emerald_multiplayer.companion import BASELINE_RULESET, Companion, CompanionConfig, verify_rom_manifest
        from emerald_multiplayer.server import ServerConfig, WorldServer
        from test_companion import wait_until
        from test_world_companion import Bridge, make_world_files
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        rom, manifest = make_world_files(temp.name)
        if capability:
            data = json.loads(manifest.read_text())
            data["ticket_abi_version"] = 1
            manifest.write_text(json.dumps(data))
        build = verify_rom_manifest(rom, manifest)[0]
        server = WorldServer(ServerConfig(build, BASELINE_RULESET, heartbeat_interval=0.05, idle_timeout=2,
                                          monitor_interval=0.005))
        await server.start(port=0)
        self.addAsyncCleanup(server.close)
        config = CompanionConfig(rom, manifest, str(uuid4()), "Alice", secrets.token_bytes(32),
                                 server_port=server.address[1], ipc_port=0, pose_interval=0.005,
                                 snapshot_interval=0.01, reconnect_delay=0.02)
        self.assertEqual(config.ticket_abi_version, 1 if capability else 0)
        companion = Companion(config)
        await companion.start()
        self.addAsyncCleanup(companion.close)
        await wait_until(lambda: companion.connected)
        bridge = await Bridge.connect(companion)
        self.addAsyncCleanup(self._close_bridge, bridge)
        return server, companion, bridge

    @staticmethod
    async def _close_bridge(bridge):
        try:
            await bridge.close()
        except (ConnectionError, OSError):
            pass

    async def present(self, bridge):
        from test_companion import make_pose
        from test_world_companion import local_record
        from emerald_multiplayer.world_mailbox import WorldState
        await bridge.send(local_record(WorldState(wallet_seq=0)))
        await bridge.send(b"P" + make_pose(frame=5, x=5).pack())

    async def test_the_word_reaches_the_games_inbound_record(self):
        from test_world_companion import wallet
        server, companion, bridge = await self.start(capability=True)
        server.wagers.grant_reward(companion.config.player_id, 8, 4, "ticket:old_sea_map:1", tickets=True)
        await self.present(bridge)
        data = await bridge.world(lambda d: wallet(d)[0] == 1)
        self.assertEqual(wallet(data)[:2], (1, 0x48000004))

    async def test_a_game_without_the_capability_never_receives_kind_8(self):
        import asyncio
        from test_companion import wait_until
        from test_world_companion import wallet
        server, companion, bridge = await self.start(capability=False)
        await self.present(bridge)
        await bridge.world(lambda d: True)
        # A host that queued kind 8 anyway (the real one never does: WorldServer.enable_tickets follows its own manifest,
        # and every player of a world runs that build): the companion refuses the frame that carries it.
        server.wagers.grant_reward(companion.config.player_id, 8, 4, "ticket:old_sea_map:1", tickets=True)
        server._broadcast_world()
        await wait_until(lambda: companion.last_error == "invalid_server_message", timeout=3)
        seen = []
        try:
            async with asyncio.timeout(1.0):
                while True:
                    seen.append(wallet(await bridge.world(timeout=1.0))[:2])
        except (TimeoutError, ConnectionError):
            pass
        self.assertNotIn((1, 0x48000004), seen)
        self.assertTrue(all(delta != 0x48000004 for _, delta in seen))


if __name__ == "__main__":
    unittest.main()
