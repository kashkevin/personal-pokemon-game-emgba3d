from __future__ import annotations

import asyncio
import struct
import unittest
import uuid

from emerald_multiplayer.protocol import (
    MAX_FRAME_BYTES, ProtocolError, encode_message, read_message,
    validate_heartbeat, validate_hello, validate_presence,
)


def hello(**changes):
    return {
        "type": "hello", "protocol": 1, "build_id": "test-build",
        "ruleset_id": "clean-upstream-test", "player_id": str(uuid.uuid4()),
        "display_name": "Player", **changes,
    }


def presence(**changes):
    return {
        "type": "presence", "session_epoch": 1, "seq": 1, "map_epoch": 0,
        "map_group": 0, "map_number": 1, "x": 5, "y": 6, "direction": 1,
        "elevation": 0, "avatar_gender": 0, "activity": "overworld", **changes,
    }


class FramingTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_frames_and_clean_eof(self):
        reader = asyncio.StreamReader()
        first, second = {"type": "one", "name": "Pokémon"}, {"type": "two"}
        reader.feed_data(encode_message(first) + encode_message(second))
        reader.feed_eof()
        self.assertEqual(await read_message(reader), first)
        self.assertEqual(await read_message(reader), second)
        self.assertIsNone(await read_message(reader))

    async def test_partial_header_and_payload(self):
        reader = asyncio.StreamReader()
        message = hello()
        frame = encode_message(message)
        pending = asyncio.create_task(read_message(reader))
        for piece in (frame[:1], frame[1:3], frame[3:9], frame[9:-1]):
            reader.feed_data(piece)
            await asyncio.sleep(0)
            self.assertFalse(pending.done())
        reader.feed_data(frame[-1:])
        self.assertEqual(await pending, message)

    async def test_oversize_rejected_before_payload_read(self):
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack("!I", MAX_FRAME_BYTES + 1))
        with self.assertRaises(ProtocolError) as caught:
            await read_message(reader)
        self.assertEqual(caught.exception.code, "frame_too_large")
        with self.assertRaises(ProtocolError):
            encode_message({"text": "x" * MAX_FRAME_BYTES})

    async def test_zero_length_and_truncated_frames(self):
        for frame, code in (
            (b"\0\0\0\0", "frame_too_large"),
            (b"\0\0", "truncated_frame"),
            (struct.pack("!I", 10) + b"{}", "truncated_frame"),
        ):
            with self.subTest(code=code, frame=frame):
                reader = asyncio.StreamReader()
                reader.feed_data(frame)
                reader.feed_eof()
                with self.assertRaises(ProtocolError) as caught:
                    await read_message(reader)
                self.assertEqual(caught.exception.code, code)

    async def test_invalid_json_duplicate_keys_nonfinite_and_nonobject(self):
        for payload in (b"\xff", b"{} trailing", b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b"[]"):
            with self.subTest(payload=payload):
                reader = asyncio.StreamReader()
                reader.feed_data(struct.pack("!I", len(payload)) + payload)
                with self.assertRaises(ProtocolError):
                    await read_message(reader)
        with self.assertRaises(ProtocolError):
            encode_message({"x": float("nan")})


class ValidationTests(unittest.TestCase):
    def test_hello_requires_exact_identity_and_compatible_versions(self):
        valid = hello()
        self.assertEqual(validate_hello(valid, "test-build", "clean-upstream-test"), valid)
        for changes, code in (
            ({"protocol": 2}, "unsupported_protocol"),
            ({"protocol": True}, "unsupported_protocol"),
            ({"build_id": "another"}, "build_mismatch"),
            ({"ruleset_id": "gen6"}, "ruleset_mismatch"),
            ({"player_id": "Player"}, "invalid_player_id"),
            ({"display_name": "\nPlayer"}, "invalid_display_name"),
            ({"display_name": " "}, "invalid_display_name"),
            ({"display_name": "x" * 25}, "invalid_display_name"),
            ({"save": {}}, "invalid_fields"),
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ProtocolError) as caught:
                    validate_hello(hello(**changes), "test-build", "clean-upstream-test")
                self.assertEqual(caught.exception.code, code)

    def test_presence_bounded_fields_and_optional_walk_default(self):
        validated = validate_presence(presence(x=-32768, y=32767, map_group=255, map_number=255, elevation=15, avatar_gender=1), 1)
        self.assertEqual(validated["movement_mode"], "walk")
        self.assertNotIn("type", validated)
        for changes in (
            {"x": 32768}, {"y": -32769}, {"x": True}, {"x": 1.0},
            {"map_group": 256}, {"map_number": -1}, {"direction": 0},
            {"elevation": 16}, {"avatar_gender": 2}, {"seq": -1},
            {"activity": "trading"}, {"movement_mode": "teleport"},
            {"activity": []}, {"session_epoch": 2}, {"money": 100},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ProtocolError):
                    validate_presence(presence(**changes), 1)

    def test_heartbeat_is_bound_to_protocol_and_session(self):
        message = {"type": "pong", "protocol": 1, "session_epoch": 9, "nonce": 42}
        self.assertEqual(validate_heartbeat(message, 9), message)
        for changes in ({"session_epoch": 8}, {"protocol": 2}, {"nonce": True}, {"nonce": -1}):
            with self.subTest(changes=changes):
                with self.assertRaises(ProtocolError):
                    validate_heartbeat({**message, **changes}, 9)


if __name__ == "__main__":
    unittest.main()
