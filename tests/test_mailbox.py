from __future__ import annotations

import asyncio
import struct
import unittest

from emerald_multiplayer.bridge_protocol import (
    BridgeError, LatestPacket, encode_packet, read_packet,
)
from emerald_multiplayer.mailbox import (
    ABI_VERSION, MAILBOX_MAGIC, MAILBOX_SIZE, MailboxError, Peer, Pose,
    Snapshot, inspect_mailbox,
)


def pose(**changes):
    fields = dict(map_epoch=2, frame=60, x=-3, y=27, map_group=0,
                  map_number=1, direction=4, elevation=0, avatar_gender=1,
                  movement_mode=0, activity=1)
    return Pose(**{**fields, **changes})


class MailboxTests(unittest.TestCase):
    def test_pose_layout_and_signed_coordinates(self):
        value = pose(x=-32768, y=32767, map_group=255, elevation=15)
        payload = value.pack()
        self.assertEqual(len(payload), 20)
        self.assertEqual(struct.unpack("<IIhh", payload[:12]), (2, 60, -32768, 32767))
        self.assertEqual(Pose.unpack(payload), value)
        self.assertEqual(payload[-1], 0)
        with self.assertRaises(MailboxError):
            Pose.unpack(payload[:-1] + b"\1")
        for changes in ({"direction": 0}, {"elevation": 16}, {"avatar_gender": 2}, {"activity": 2}, {"movement_mode": 5}, {"x": True}):
            with self.subTest(changes=changes), self.assertRaises(MailboxError):
                pose(**changes)

    def test_snapshot_layout_three_peers_and_unused_zero_records(self):
        value = Snapshot(1, 31, 4, 2, tuple(Peer(index + 1, pose(frame=index)) for index in range(3)))
        self.assertEqual(len(value.pack()), 88)
        self.assertEqual(struct.unpack("<IIIBBH", value.pack()[:16]), (1, 31, 4, 2, 3, 0))
        self.assertEqual(Snapshot.unpack(value.pack()), value)
        single = Snapshot(1, 2, 3, 0, (Peer(7, pose()),))
        self.assertEqual(single.pack()[40:], bytes(48))
        self.assertEqual(Snapshot.unpack(single.pack()), single)
        self.assertEqual(Snapshot.unpack(Snapshot().pack()), Snapshot())
        for payload in (
            single.pack()[:14] + b"\1\0" + single.pack()[16:],
            single.pack()[:-1] + b"\1",
            struct.pack("<I", 2) + single.pack()[4:],
            struct.pack("<I", 0) + single.pack()[4:],
        ):
            with self.subTest(payload=payload), self.assertRaises(MailboxError):
                Snapshot.unpack(payload)
        with self.assertRaises(MailboxError):
            Snapshot(1, peers=(Peer(1, pose()), Peer(1, pose())))

    def test_full_mailbox_header_and_seqlocks(self):
        local, snapshot = pose(), Snapshot(1, 1, 1, 0, (Peer(2, pose(x=4)),))
        payload = struct.pack("<IHHII", MAILBOX_MAGIC, ABI_VERSION, MAILBOX_SIZE, 60, 2) + local.pack() + struct.pack("<I", 4) + snapshot.pack()
        self.assertEqual(len(payload), 128)
        self.assertEqual(inspect_mailbox(payload), (local, snapshot))
        for changed in (
            b"bad!" + payload[4:],
            payload[:4] + struct.pack("<H", 2) + payload[6:],
            payload[:12] + struct.pack("<I", 3) + payload[16:],
            payload[:36] + struct.pack("<I", 5) + payload[40:],
            payload[:-1],
        ):
            with self.subTest(changed=changed), self.assertRaises(MailboxError):
                inspect_mailbox(changed)

    def test_movement_mapping_and_safe_unavailable_modes(self):
        for mode, expected in ((0, "walk"), (1, "bike"), (2, "bike"), (3, "surf")):
            self.assertEqual(pose(movement_mode=mode).network_fields(True)["movement_mode"], expected)
        self.assertEqual(pose(movement_mode=4).network_fields(True)["activity"], "unavailable")
        self.assertEqual(pose().network_fields(False)["activity"], "unavailable")
        self.assertEqual(pose(activity=0).network_fields(True)["activity"], "unavailable")
        presence = pose().network_fields(True)
        converted = Pose.from_presence({**presence, "map_epoch": 3, "seq": 99})
        self.assertEqual(converted.frame, 99)
        self.assertEqual(converted.activity, 1)


class BridgeFramingTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_binary_frames_and_clean_eof(self):
        reader = asyncio.StreamReader()
        payload = b"P" + pose().pack()
        frame = encode_packet(payload)
        pending = asyncio.create_task(read_packet(reader))
        reader.feed_data(frame[:2])
        await asyncio.sleep(0)
        self.assertFalse(pending.done())
        reader.feed_data(frame[2:-1])
        await asyncio.sleep(0)
        self.assertFalse(pending.done())
        reader.feed_data(frame[-1:])
        self.assertEqual(await pending, payload)
        reader.feed_eof()
        self.assertIsNone(await read_packet(reader))

    async def test_bridge_bounds_and_truncation(self):
        for data in (struct.pack("!I", 257), bytes(4), b"\0\0", struct.pack("!I", 21) + b"P"):
            reader = asyncio.StreamReader()
            reader.feed_data(data)
            reader.feed_eof()
            with self.subTest(data=data), self.assertRaises(BridgeError):
                await read_packet(reader)
        with self.assertRaises(BridgeError):
            encode_packet(bytes(257))

    async def test_latest_packet_replacement_and_close(self):
        queue = LatestPacket()
        for index in range(100):
            queue.put(b"S" + bytes([index]))
        self.assertEqual(await queue.get(), encode_packet(b"S\x63"))
        pending = asyncio.create_task(queue.get())
        await asyncio.sleep(0)
        queue.close()
        self.assertIsNone(await pending)


if __name__ == "__main__":
    unittest.main()
