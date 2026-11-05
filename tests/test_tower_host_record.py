"""KNOWN_ISSUES MS-52: the host's Tower record for the native Tower screens.

The native Tower screens (the 3D UI's home, floor map, previews and prizes) drew the game's own copy of the Tower record,
which the host's TOWER_STATE word changes only on the field, never while the Players menu is open: after a settlement,
or for a game back online, the map could mark the floor before while the host's rows already offered the next one.

The launcher's half, built here: a Tower page's screen goes to a game that draws its Tower screens from the host's
record (manifest tower_record_abi_version 1, bridge.txt tower_record=1) followed by that record (menu_mailbox
.TowerHostRecord: the host's progress, highest floor and claims, 8 bytes after the 240), and a Tower word that reaches
the companion (the host has just settled something for this player) refreshes an open Tower page at once instead of at
the next 2 s status refresh. The engine's half (the bridge taking the 248-byte screen, the menu keeping the record with
its screen, ui_tower.c drawing from it) is not built: no game announces the capability yet, so nothing changes for
today's games, which these tests also check."""
from __future__ import annotations

import asyncio
import json
import secrets
import struct
from types import SimpleNamespace
import tempfile
import unittest
from uuid import uuid4

from emerald_multiplayer import rewards, tower_data
from emerald_multiplayer.bridge_config import configure_native, tower_record_enabled
from emerald_multiplayer.bridge_protocol import MAX_BRIDGE_FRAME_BYTES, BridgeOutbox
from emerald_multiplayer.companion import Companion
from emerald_multiplayer.menu_mailbox import (TOWER_RECORD_MAGIC, TOWER_RECORD_SIZE, MenuRequest, TowerHostRecord,
                                              pack_screen, unpack_screen)
from emerald_multiplayer.menu_session import MenuSession
from emerald_multiplayer.player_menu import MenuScreen, PlayerMenu
from test_tower_menu import FakeCompanion, host_view
from test_tower_rules import synthetic_data

TOKEN = "ab" * 32


class RecordCodecTests(unittest.TestCase):
    def test_the_record_is_eight_bytes_after_the_screen(self):
        record = TowerHostRecord(13, 12, 0b1000_0000_0011)
        data = record.pack()
        self.assertEqual(TOWER_RECORD_SIZE, 8)
        self.assertEqual(data, struct.pack("<IBBH", 0x31485754, 13, 12, 0b1000_0000_0011))
        self.assertEqual(data[:4], b"TWH1")
        self.assertEqual(TowerHostRecord.unpack(data), record)
        screen = pack_screen(1, MenuScreen(5, "Battle Tower: Legends", "Floor 13", (), 7, 0, 1, 0), allow_tower=True)
        self.assertLessEqual(len(b"M" + screen + data), MAX_BRIDGE_FRAME_BYTES)  # one bridge packet: 249 bytes
        self.assertEqual(TowerHostRecord(101, 100, 0xFFFF).pack()[4:], bytes((101, 100, 0xFF, 0xFF)))  # climbed

    def test_the_tower_state_words_bounds(self):
        for progress, highest, claims in ((0, 0, 0), (102, 100, 0), (1, 101, 0), (1, -1, 0), (1, 0, 0x10000),
                                          (True, 0, 0), (1, 0, None), (1.0, 0, 0)):
            with self.subTest(progress=progress, highest=highest, claims=claims), self.assertRaises(ValueError):
                TowerHostRecord(progress, highest, claims).pack()
        good = TowerHostRecord(12, 11, 3).pack()
        for bad in (good[:7], good + b"\0", bytes(8), struct.pack("<IBBH", TOWER_RECORD_MAGIC, 0, 0, 0),
                    struct.pack("<IBBH", TOWER_RECORD_MAGIC, 12, 101, 0), b"TWR1" + good[4:], bytearray(good)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                TowerHostRecord.unpack(bad)


class CapabilityTests(unittest.TestCase):
    def manifest(self, **changes):
        return {"menu_abi_version": 2, "menu_open_page_abi_version": 1, "world_abi_version": 1, "tower_abi_version": 1,
                "tower_record_abi_version": 1, **changes}

    def test_the_launcher_opts_in_only_beside_the_tower(self):
        self.assertTrue(tower_record_enabled(self.manifest()))
        self.assertIn("tower_record=1", configure_native(self.manifest(), TOKEN, 9).splitlines())
        for changes in (dict(tower_abi_version=0), dict(world_abi_version=None), dict(tower_record_abi_version=2),
                        dict(tower_record_abi_version=True), dict(tower_record_abi_version=None)):
            with self.subTest(changes=changes):
                self.assertFalse(tower_record_enabled(self.manifest(**changes)))
                self.assertNotIn("tower_record=1", configure_native(self.manifest(**changes), TOKEN, 9).splitlines())

    def test_the_companion_reads_its_games_capability(self):
        from emerald_multiplayer.companion import CompanionConfig
        from test_tower_contract import make_tower_world_files
        for extra, expected in (({}, 0), ({"tower_record_abi_version": 1}, 1), ({"tower_record_abi_version": 2}, 0),
                                ({"tower_record_abi_version": 1, "tower_abi_version": 0}, 0)):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temp:
                rom, manifest = make_tower_world_files(temp)
                data = json.loads(manifest.read_text())
                data.update(extra)
                manifest.write_text(json.dumps(data))
                config = CompanionConfig(rom, manifest, str(uuid4()), "Alice", secrets.token_bytes(32), ipc_port=0)
                self.assertEqual(config.tower_record_abi_version, expected)

    def test_the_marker_needs_the_tower(self):
        """gMultiplayerTowerRecordAbiVersion -> manifest tower_record_abi_version 1, only beside the Tower."""
        from test_tower_contract import ManifestTests
        ManifestTests.setUp(self)
        f = self.fixture
        marker = "00bd27a0 00000004 R gMultiplayerTowerRecordAbiVersion\n"
        generated = ManifestTests.generate(self, f.world + self.menu, self.open_page + self.tower + marker)
        self.assertEqual((generated["tower_record_abi_version"], generated["tower_abi_version"]), (1, 1))
        self.assertTrue(tower_record_enabled(generated))
        self.assertNotIn("tower_record_abi_version",
                         ManifestTests.generate(self, f.world + self.menu, self.open_page + self.tower))
        for native in (self.open_page + marker,                                         # no Tower
                       self.open_page + self.tower + marker + marker,
                       self.open_page + self.tower + "00bd27a0 00000008 R gMultiplayerTowerRecordAbiVersion\n"):
            with self.subTest(native=native), self.assertRaises(ValueError):
                ManifestTests.generate(self, f.world + self.menu, native)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    """START > PLAYER > TOWER through the real menu session against a fake host (test_tower_menu)."""

    async def asyncSetUp(self):
        tower_data.install(synthetic_data())
        self.addCleanup(tower_data.reset)
        self.calls, self.refuse, self.disabled, self.view = [], None, False, host_view()
        self.bridge = SimpleNamespace(outbox=BridgeOutbox(), writer=SimpleNamespace(close=lambda: None))
        self.companion = FakeCompanion(self)
        self.companion.config.tower_record_abi_version = 1
        self.companion._bridge = self.bridge
        self.session = MenuSession(self.companion, self.bridge)

    async def asyncTearDown(self):
        await self.session.close()

    async def frame(self, timeout=2.0):
        """The next screen the game gets: ((ack, screen, flags, command), the host record after it or None)."""
        packet = await asyncio.wait_for(self.bridge.outbox.get(), timeout)
        payload = packet[4:]
        self.assertEqual(payload[:1], b"M")
        self.assertIn(len(payload) - 1, (240, 240 + TOWER_RECORD_SIZE))
        screen = unpack_screen(payload[1:241], allow_tower=True)
        return screen, (TowerHostRecord.unpack(payload[241:]) if len(payload) > 241 else None)

    async def no_frame(self, seconds):
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(self.bridge.outbox.get(), seconds)

    async def open_tower(self, sequence=1):
        self.session.feed(MenuRequest(sequence, 0, 2, 1).pack(allow_tower=True))
        await self.session._task
        return await self.frame()

    async def choose(self, sequence, label):
        screen = self.session.menu.screen
        row = next(r for r in screen.rows if r.label == label)
        self.session.feed(MenuRequest(sequence, screen.revision, row.action, 2).pack())
        await self.session._task
        return await self.frame()

    async def test_the_tower_page_carries_the_hosts_record(self):
        (_, screen, flags, _), record = await self.open_tower()
        self.assertEqual((screen.title, screen.style, flags), ("Battle Tower: Legends", 1, 0))
        self.assertEqual(record, TowerHostRecord(12, 11, 0b11))                       # the host's, not the save's
        (_, screen, flags, _), record = await self.choose(2, "Solo: floor 12")        # a floor's preview: style 3
        self.assertEqual((screen.style, screen.style_arg, record), (3, 12, TowerHostRecord(12, 11, 0b11)))
        (_, screen, flags, command), record = await self.choose(3, "Start the battle")
        self.assertEqual((flags, command.floor, record), (4, 12, None))                 # a command carries none

    async def test_a_game_without_the_capability_never_gets_a_record(self):
        self.companion.config.tower_record_abi_version = 0
        (_, screen, _, _), record = await self.open_tower()
        self.assertEqual((screen.style, record), (1, None))                           # 240 bytes, as before

    async def test_no_record_while_the_host_has_none_for_the_player(self):
        self.view["player"]["known"] = False          # no row yet: the game's own save is all there is
        (_, screen, _, _), record = await self.open_tower()
        self.assertEqual((screen.style, record), (1, None))

    async def test_a_page_without_a_tower_style_has_no_record(self):
        await self.open_tower()
        self.session.feed(MenuRequest(2, self.session.menu.screen.revision, 7, 2).pack())   # B: the Players home
        await self.session._task
        (_, screen, _, _), record = await self.frame()
        self.assertEqual((screen.title, screen.style, record), ("Players", 0, None))

    async def test_a_settlement_reaches_an_open_tower_page_at_once(self):
        (_, screen, _, _), record = await self.open_tower()
        self.assertEqual((screen.rows[0].label, record), ("Solo: floor 12", TowerHostRecord(12, 11, 0b11)))
        self.view = host_view(progress=13, highest=12, claims=0b111)                  # the host settled floor 12
        await self.no_frame(0.4)                                                      # the 2 s refresh is not due yet
        self.session.wake_tower()                                                    # a Tower word reached the companion
        (_, screen, _, _), record = await self.frame(timeout=0.5)
        self.assertEqual((screen.rows[0].label, record), ("Solo: floor 13", TowerHostRecord(13, 12, 0b111)))
        self.assertEqual(self.calls[-1], ("status", {}))

    async def test_a_wake_leaves_other_pages_to_their_own_refresh(self):
        self.session.feed(MenuRequest(1, 0, 0, 1).pack())                             # START > PLAYER > PLAYERS
        await self.session._task
        (_, screen, _, _), _ = await self.frame()
        self.assertEqual(screen.title, "Players")
        before = len(self.calls)
        self.session.wake_tower()
        await self.no_frame(0.3)
        self.assertEqual(len(self.calls), before)                                    # no host round trip either


class SignatureTests(unittest.TestCase):
    def test_a_changed_record_alone_is_a_new_screen(self):
        """A floor map whose rows stay the same still changes its record: the 2 s refresh sends it (MenuSession._poll
        sends a screen that differs from the one shown)."""
        menu = PlayerMenu(SimpleNamespace(config=SimpleNamespace(), connected=False))
        first = menu._show("Battle Tower: Legends", "Floor 12", [], (2, 9), TowerHostRecord(12, 11, 0))
        again = menu._show("Battle Tower: Legends", "Floor 12", [], (2, 9), TowerHostRecord(12, 11, 0))
        changed = menu._show("Battle Tower: Legends", "Floor 12", [], (2, 9), TowerHostRecord(13, 12, 0))
        self.assertIs(again, first)
        self.assertEqual(changed.revision, first.revision + 1)
        self.assertEqual(changed.tower_record, TowerHostRecord(13, 12, 0))


class CompanionNoteTests(unittest.TestCase):
    """Companion._note_tower_word: which world views wake an open Tower page."""

    def note(self, previous, wallet, *, tower=1, bridge=True):
        session = SimpleNamespace(wakes=0)
        session.wake_tower = lambda: setattr(session, "wakes", session.wakes + 1)
        fake = SimpleNamespace(config=SimpleNamespace(tower_abi_version=tower),
                               _bridge=SimpleNamespace(menu_session=session) if bridge else None)
        Companion._note_tower_word(fake, previous, wallet)
        return session.wakes

    def test_a_new_tower_word_wakes_and_nothing_else_does(self):
        state = {"seq": 7, "delta": rewards.encode(rewards.KIND_TOWER_STATE, rewards.tower_progress(12, 13, 0x2A),
                                                   tower=True)}
        mon = {"seq": 8, "delta": rewards.encode(rewards.KIND_TOWER_MON, rewards.tower_mon(0, 25, 30), tower=True)}
        bp = {"seq": 9, "delta": rewards.encode(rewards.KIND_BP, 5)}
        self.assertEqual(self.note(None, state), 1)
        self.assertEqual(self.note(state, mon), 1)
        self.assertEqual(self.note(state, dict(state)), 0)                           # the same word again
        for wallet in ({"seq": 9, "delta": 500}, {"seq": 9, "delta": -500}, bp, None):
            with self.subTest(wallet=wallet):
                self.assertEqual(self.note(state, wallet), 0)
        self.assertEqual(self.note(None, state, tower=0), 0)                          # a game without the Tower
        self.assertEqual(self.note(None, state, bridge=False), 0)                     # no game connected: nothing


class CompanionWakeTests(unittest.IsolatedAsyncioTestCase):
    """A real host queues a Tower word for the player: the companion wakes its game's Players window at once."""

    async def asyncSetUp(self):
        from test_tower_contract import CompanionForwardingTests
        await CompanionForwardingTests.asyncSetUp(self)

    async def asyncTearDown(self):
        from test_tower_contract import CompanionForwardingTests
        await CompanionForwardingTests.asyncTearDown(self)

    async def test_the_hosts_tower_word_wakes_the_open_window(self):
        from test_companion import make_pose
        from test_world_companion import local_record, wallet
        from emerald_multiplayer.world_mailbox import WorldState
        player = self.companion.config.player_id
        await self.bridge.send(local_record(WorldState()))
        await self.bridge.send(b"P" + make_pose(frame=5, x=5).pack())
        await self.wait_until(lambda: (self.server.sessions[player].presence or {}).get("x") == 5, timeout=3)
        window = SimpleNamespace(wakes=0)
        window.wake_tower = lambda: setattr(window, "wakes", window.wakes + 1)
        async def close():
            pass
        window.close = close
        self.companion._bridge.menu_session = window
        payload = rewards.tower_progress(12, 13, 0x2A)
        delta = rewards.encode(rewards.KIND_TOWER_STATE, payload, tower=True)
        self.server.wagers.grant_reward(player, rewards.KIND_TOWER_STATE, payload, "tower:ms52", tower=True)
        self.server._broadcast_world()
        await self.wait_until(lambda: window.wakes == 1, timeout=3)
        await self.bridge.world(lambda data: wallet(data)[1] == delta)              # and the word reaches the game
        self.server._broadcast_world()                                              # the same word again: no wake
        await asyncio.sleep(0.2)
        self.assertEqual(window.wakes, 1)


if __name__ == "__main__":
    unittest.main()
