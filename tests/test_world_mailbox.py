"""EMW1 shared-world mailbox codecs (layout must match include/multiplayer_world.h)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import struct
import tempfile
import unittest

from emerald_multiplayer.world_mailbox import (
    ACTION_APPEARANCE, ACTION_CLAIM, ACTION_COOP_GYM, ACTION_KINDS, ACTION_RESULT, ACTION_WALLET,
    EVENT_MEGA, EVENT_MINE, EVENT_SHINY, EVENT_VISIBLE, FLAG_CLOCK_VALID, FLAG_EVENTS, WALLET_OFFSET,
    WORLD_INBOUND_OFFSET, WORLD_INBOUND_SIZE, WORLD_LOCAL_OFFSET, WORLD_LOCAL_SIZE, WORLD_MAILBOX_SIZE,
    WorldAction, WorldEventView, WorldInbound, WorldMailboxError, WorldState, capability_matches,
    unpack_local, validate_world_manifest,
)

LOOK = bytes((1, 2, 3, 4, 5, 6, 7, 0))


class LayoutTests(unittest.TestCase):
    def test_offsets_match_the_engine_static_asserts(self):
        # include/multiplayer_world.h / src/multiplayer_world.c _Static_asserts
        self.assertEqual(WORLD_MAILBOX_SIZE, 256)
        self.assertEqual(WORLD_LOCAL_OFFSET, 12)
        self.assertEqual(WORLD_LOCAL_SIZE, 32)
        self.assertEqual(WORLD_INBOUND_OFFSET, 48)
        self.assertEqual(WORLD_INBOUND_OFFSET + WORLD_INBOUND_SIZE, WORLD_MAILBOX_SIZE)
        inbound = WorldInbound().pack()
        self.assertEqual(len(inbound), WORLD_INBOUND_SIZE)
        # peers at mailbox 68, event at 128, notice at 160, wallet at 228, teammate at 236
        self.assertEqual(WORLD_INBOUND_OFFSET + 20, 68)
        self.assertEqual(WORLD_INBOUND_OFFSET + 20 + 3 * 20, 128)
        self.assertEqual(WORLD_INBOUND_OFFSET + 112, 160)
        self.assertEqual(WORLD_INBOUND_OFFSET + WALLET_OFFSET, 228)
        self.assertEqual(WORLD_INBOUND_OFFSET + WALLET_OFFSET + 8, 236)
        self.assertEqual(len(WorldState().pack()), 16)
        self.assertEqual(len(WorldAction().pack()), 16)
        self.assertEqual(len(WorldEventView().pack()), 32)

    def test_action_kinds_match_the_rom(self):
        self.assertEqual(ACTION_KINDS, {1: "claim", 2: "result", 3: "release", 4: "appearance",
                                        5: "wallet", 6: "coop_gym"})


class StateAndActionTests(unittest.TestCase):
    def test_local_record_round_trip_carries_wallet_low_byte_only_locally(self):
        state = WorldState(25, 5, 1, 254, 3, LOOK, wallet_seq=7)
        raw = struct.pack("<HBBHBB8s", 25, 5, 1, 254, 3, 7, LOOK)
        action = WorldAction(9, ACTION_WALLET, 1, 0, 42, 5000)
        parsed_state, parsed_action = unpack_local(raw + action.pack())
        self.assertEqual(parsed_state, state)
        self.assertEqual(parsed_action, action)
        self.assertEqual(parsed_state.network_fields()["wallet_seq"], 7)
        # Peer records published to other games never carry a wallet sequence.
        self.assertEqual(state.pack()[7], 0)

    def test_state_bounds(self):
        for changes in (dict(follower_species=1701), dict(follower_flags=8), dict(mount_state=2),
                        dict(mount_species=-1), dict(mount_flags=4), dict(wallet_seq=256),
                        dict(appearance=bytes(7)), dict(appearance=bytearray(8)), dict(follower_species=True)):
            with self.subTest(changes=changes), self.assertRaises(WorldMailboxError):
                replace(WorldState(), **changes)
        with self.assertRaises(WorldMailboxError):
            WorldState.unpack(bytes(15))

    def test_action_amount_only_for_wallet_receipts(self):
        self.assertEqual(WorldAction(1, ACTION_WALLET, 2, 0, 3, 999_999).amount, 999_999)
        for changes in (dict(kind=ACTION_CLAIM, amount=1), dict(kind=ACTION_WALLET, amount=1_000_000),
                        dict(kind=7), dict(result=6), dict(seq=-1), dict(event_id=1 << 32)):
            with self.subTest(changes=changes), self.assertRaises(WorldMailboxError):
                replace(WorldAction(1, ACTION_RESULT, 1, 25, 7), **changes)
        raw = bytearray(WorldAction(1, ACTION_CLAIM, 0, 25, 7).pack())
        struct.pack_into("<I", raw, 12, 5)
        with self.assertRaises(WorldMailboxError):
            WorldAction.unpack(bytes(raw))
        for kind in (ACTION_APPEARANCE, ACTION_COOP_GYM):
            self.assertEqual(WorldAction.unpack(WorldAction(3, kind, 0, 0, 4).pack()).kind, kind)

    def test_network_state_defaults_and_peer_appearance(self):
        state = WorldState.from_network({"follower_species": 6, "follower_flags": 4, "mount_state": 0,
                                          "mount_species": 0, "mount_flags": 0, "wallet_seq": 9}, LOOK)
        self.assertEqual((state.follower_species, state.appearance, state.wallet_seq), (6, LOOK, 0))
        self.assertEqual(WorldState.from_network(None, bytes(8)), WorldState())


class InboundTests(unittest.TestCase):
    def inbound(self, **changes):
        peer = WorldState(6, 4, 0, 0, 0, LOOK)
        event = WorldEventView(77, 384, 50, EVENT_VISIBLE | EVENT_SHINY | EVENT_MEGA | EVENT_MINE, 0, 16, 10, 7,
                               0, 600, 3)
        values = dict(clock_valid=True, events_enabled=True, world_seconds=123456, action_ack=5,
                      self_appearance=LOOK, peers=((2, peer), (4, WorldState())), event=event,
                      notice_id=3, notice_text="WORLD EVENT!|near Route 101", wallet_seq=12,
                      wallet_delta=-5000, teammate_token=2)
        values.update(changes)
        return WorldInbound(**values)

    def test_exact_bytes_for_every_field(self):
        data = self.inbound().pack()
        flags, seconds, ack = struct.unpack_from("<III", data, 0)
        self.assertEqual(flags, FLAG_CLOCK_VALID | FLAG_EVENTS)
        self.assertEqual((seconds, ack), (123456, 5))
        self.assertEqual(data[12:20], LOOK)
        token, species, fflags = struct.unpack_from("<IHB", data, 20)
        self.assertEqual((token, species, fflags), (2, 6, 4))
        self.assertEqual(struct.unpack_from("<I", data, 40)[0], 4)
        self.assertEqual(data[60:80], bytes(20))  # unused third peer slot is all zero
        event_id, species, level, eflags, group, number, x, y, item, left, ivs = struct.unpack_from(
            "<IHBBBBhhHIB", data, 80)
        self.assertEqual((event_id, species, level, group, number, x, y, left, ivs), (77, 384, 50, 0, 16, 10, 7, 600, 3))
        self.assertEqual(eflags, EVENT_VISIBLE | EVENT_SHINY | EVENT_MEGA | EVENT_MINE)
        self.assertEqual(data[101:112], bytes(11))
        self.assertEqual(struct.unpack_from("<I", data, 112)[0], 3)
        self.assertEqual(data[116:180].rstrip(b"\0"), b"WORLD EVENT!|near Route 101")
        self.assertEqual(struct.unpack_from("<IiI", data, WALLET_OFFSET), (12, -5000, 2))
        self.assertEqual(data[192:], bytes(16))

    def test_notice_is_printable_ascii_and_bounded(self):
        data = self.inbound(notice_text="café\nline" + "x" * 80).pack()
        text = data[116:180]
        self.assertEqual(len(text), 64)
        self.assertTrue(all(32 <= c < 127 for c in text))

    def test_wallet_and_teammate_consistency(self):
        self.assertEqual(self.inbound(wallet_seq=0, wallet_delta=0).pack()[WALLET_OFFSET:WALLET_OFFSET + 8], bytes(8))
        for changes in (dict(wallet_seq=1, wallet_delta=0), dict(wallet_seq=0, wallet_delta=5),
                        dict(wallet_seq=0x10000), dict(wallet_delta=1_000_000), dict(wallet_delta=-1_000_000),
                        dict(teammate_token=3), dict(teammate_token=5), dict(teammate_token=-1)):
            with self.subTest(changes=changes), self.assertRaises(WorldMailboxError):
                self.inbound(**changes)

    def test_peer_bounds(self):
        state = WorldState()
        for peers in (((1, state),) * 2, tuple((i, state) for i in range(1, 5)), ((0, state),), [(1, state)]):
            with self.subTest(peers=peers), self.assertRaises(WorldMailboxError):
                self.inbound(peers=peers, teammate_token=0)

    def test_event_bounds(self):
        for changes in (dict(level=101), dict(flags=32), dict(perfect_ivs=7), dict(species=1701), dict(x=40000)):
            with self.subTest(changes=changes), self.assertRaises(WorldMailboxError):
                replace(WorldEventView(1, 25, 10), **changes)


class ManifestTests(unittest.TestCase):
    def manifest(self, **changes):
        value = dict(world_abi_version=1, world_abi_address=0x08000100, world_mailbox_address=0x02030000,
                     world_mailbox_size=256, mailbox_address=0x02001000, mailbox_size=128)
        value.update(changes)
        return value

    def test_optional_capability_and_overlap(self):
        self.assertFalse(validate_world_manifest({"abi_version": 1}))
        self.assertTrue(validate_world_manifest(self.manifest()))
        self.assertTrue(capability_matches(self.manifest()))
        for changes in (dict(world_abi_version=2), dict(world_mailbox_size=128), dict(world_abi_address=0x08000101),
                        dict(world_mailbox_address=0x02040000), dict(world_mailbox_address=0x02001040),
                        dict(world_abi_address=None)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_world_manifest(self.manifest(**changes))
        partial = self.manifest()
        del partial["world_mailbox_size"]
        with self.assertRaises(ValueError):
            validate_world_manifest(partial)

    def test_marker_must_match_the_rom(self):
        with tempfile.TemporaryDirectory() as directory:
            rom = Path(directory) / "game.gba"
            data = bytearray(0x200)
            struct.pack_into("<I", data, 0x100, 1)
            rom.write_bytes(bytes(data))
            self.assertTrue(validate_world_manifest(self.manifest(), rom))
            struct.pack_into("<I", data, 0x100, 2)
            rom.write_bytes(bytes(data))
            with self.assertRaises(ValueError):
                validate_world_manifest(self.manifest(), rom)
            with self.assertRaises(ValueError):
                validate_world_manifest(self.manifest(world_abi_address=0x08000200), rom)


if __name__ == "__main__":
    unittest.main()
