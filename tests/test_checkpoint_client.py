import asyncio
import base64
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.checkpoint_client import (
    CheckpointClient, CheckpointError, validate_checkpoint_reply,
)
from emerald_multiplayer.protocol import ProtocolError


def metadata(payload, revision=1, transaction=None):
    return {"revision": revision, "request_id": transaction or str(uuid4()), "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(), "build_id": "a" * 64,
            "ruleset_id": "rules", "save_profile": "profile"}


class ReplyTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(build_id="a" * 64, ruleset_id="rules")
        self.reply = {"type": "checkpoint_result", "protocol": 1, "session_epoch": 5,
                      "request_id": str(uuid4()), "operation": "info", "checkpoint": metadata(b"a" * 131072)}

    def test_exact_metadata_bindings_and_epoch(self):
        self.assertEqual(validate_checkpoint_reply(self.reply, self.config, 5, "profile"), self.reply)
        for field, value in (("revision", True), ("build_id", "b" * 64), ("size", 131073), ("sha256", "x" * 64)):
            altered = {**self.reply, "checkpoint": {**self.reply["checkpoint"], field: value}}
            with self.subTest(field=field), self.assertRaises(ProtocolError):
                validate_checkpoint_reply(altered, self.config, 5, "profile")
        with self.assertRaises(ProtocolError):
            validate_checkpoint_reply(self.reply, self.config, 6, "profile")

    def test_read_bounds_and_eof_are_validated(self):
        reply = {**self.reply, "operation": "read", "offset": 0, "data_b64": base64.b64encode(b"a" * 4096).decode(), "eof": False}
        validate_checkpoint_reply(reply, self.config, 5, "profile")
        for changes in ({"eof": True}, {"offset": 131072}, {"data_b64": "!"}, {"data_b64": base64.b64encode(b"a" * 4097).decode()}, {"extra": 1}):
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                validate_checkpoint_reply({**reply, **changes}, self.config, 5, "profile")

    def test_conflicts_are_bounded_errors_not_success(self):
        reply = {k: v for k, v in self.reply.items() if k != "checkpoint"}
        reply.update(type="checkpoint_error", code="revision_conflict", message="Newer checkpoint exists")
        validate_checkpoint_reply(reply, self.config, 5, "profile")
        with self.assertRaises(ProtocolError):
            validate_checkpoint_reply({**reply, "message": "x" * 513}, self.config, 5, "profile")

    def test_untyped_operation_is_rejected_as_protocol_error(self):
        for value in ([], {}, None, 1):
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                validate_checkpoint_reply({**self.reply, "operation": value}, self.config, 5, "profile")


class FakeCompanion:
    def __init__(self, payload):
        self.config = SimpleNamespace(build_id="a" * 64, ruleset_id="rules", player_id=str(uuid4()))
        self.world_id, self.session_epoch, self.connected, self.save_profile = str(uuid4()), 1, True, "profile"
        self.payload = payload
        self.head = metadata(payload)
        self.calls = []
        self.bad_hash = self.change_session = False
        self.committed_retry = False
        self.wrong_commit_id = self.change_commit_session = False

    async def checkpoint_rpc(self, op, **fields):
        self.calls.append((op, fields))
        await asyncio.sleep(0)
        if op == "info":
            return {"checkpoint": {**self.head, "sha256": "b" * 64} if self.bad_hash else self.head}
        if op == "read":
            start = fields["offset"]
            chunk = self.payload[start:start + fields["length"]]
            if self.change_session:
                self.session_epoch += 1
            return {"checkpoint": {**self.head, "sha256": "b" * 64} if self.bad_hash else self.head,
                    "offset": start, "data_b64": base64.b64encode(chunk).decode()}
        if op == "begin":
            self.transaction = fields["request_id"]
            return {"checkpoint": None, "upload_id": self.transaction, "next_offset": len(self.payload) if self.committed_retry else 0}
        if op == "chunk":
            return {"upload_id": self.transaction, "next_offset": fields["offset"] + len(base64.b64decode(fields["data_b64"]))}
        if op == "commit":
            if self.change_commit_session:
                self.session_epoch += 1
            return {"checkpoint": metadata(self.payload, fields["expected_revision"] + 1, self.transaction), "upload_id": str(uuid4()) if self.wrong_commit_id else self.transaction}
        raise AssertionError(op)


class TransferTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.payload = b"a" * 131088
        self.companion = FakeCompanion(self.payload)
        self.client = CheckpointClient(self.companion)

    async def test_download_checks_complete_hash_and_session(self):
        with patch("emerald_multiplayer.flash.inspect_flash") as inspect:
            result = await self.client.download()
            self.assertEqual(result.payload, self.payload)
            inspect.assert_called_once_with(self.payload)
            self.assertEqual(len([op for op, _ in self.companion.calls if op == "read"]), 33)
            self.companion.bad_hash = True
            with self.assertRaises(ProtocolError):
                await self.client.download()
            self.companion.bad_hash = False
            self.companion.change_session = True
            with self.assertRaises(ConnectionError):
                await self.client.download()

    async def test_upload_preserves_transaction_identity_across_retry(self):
        transaction = str(uuid4())
        with patch("emerald_multiplayer.flash.inspect_flash"):
            result = await self.client.upload(self.payload, 0, transaction_id=transaction)
            self.assertEqual(result["request_id"], transaction)
            chunks = [fields for op, fields in self.companion.calls if op == "chunk"]
            self.assertEqual(b"".join(base64.b64decode(c["data_b64"]) for c in chunks), self.payload)
            self.assertEqual(len(chunks), 33)
            self.companion.calls.clear()
            self.companion.committed_retry = True
            result = await self.client.upload(self.payload, 0, transaction_id=transaction)
            self.assertEqual(result["revision"], 1)
            self.assertEqual([op for op, _ in self.companion.calls], ["begin", "commit"])

    async def test_disconnected_download_fails_before_any_request(self):
        self.companion.connected = False
        with patch("emerald_multiplayer.flash.inspect_flash"), self.assertRaises(ConnectionError):
            await self.client.download()
        self.assertEqual(self.companion.calls, [])

    async def test_commit_acknowledgement_matches_upload_and_original_session(self):
        self.companion.wrong_commit_id = True
        with patch("emerald_multiplayer.flash.inspect_flash"), self.assertRaises(ProtocolError):
            await self.client.upload(self.payload, 0)
        self.companion.wrong_commit_id = False
        self.companion.change_commit_session = True
        with patch("emerald_multiplayer.flash.inspect_flash"), self.assertRaises(ConnectionError):
            await self.client.upload(self.payload, 0)


if __name__ == "__main__":
    unittest.main()
