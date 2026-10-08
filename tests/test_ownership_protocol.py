from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import unittest
import uuid

from emerald_multiplayer.ownership_protocol import OWNERSHIP_PROFILE, validate_ownership_reply
from emerald_multiplayer.protocol import ProtocolError, validate_checkpoint_request


class OwnershipProtocolTests(unittest.TestCase):
    def setUp(self):
        self.world, self.player = str(uuid.uuid4()), str(uuid.uuid4())
        self.config = SimpleNamespace(player_id=self.player)
        self.request = {"type": "ownership_grant", "request_id": str(uuid.uuid4()), "session_epoch": 3,
                        "expected_revision": 0, "incarnation": 1, "count": 432}
        self.reply = {"type": "checkpoint_result", "protocol": 1, "request_id": self.request["request_id"],
                      "session_epoch": 3, "operation": "ownership_grant", "checkpoint": None,
                      "grant": {"world_id": self.world, "player_id": self.player, "grant_id": str(uuid.uuid4()),
                                "start": 1, "end_exclusive": 433, "lease_epoch": 3, "incarnation": 1,
                                "expected_revision": 0}}

    def validate(self, reply):
        return validate_ownership_reply(reply, self.config, OWNERSHIP_PROFILE, self.world, 3)

    def test_bounded_request_and_reply(self):
        self.assertEqual(validate_checkpoint_request(self.request, 3), self.request)
        self.assertEqual(self.validate(self.reply), self.reply)
        for field, value in (("count", 0), ("count", 433), ("count", True), ("incarnation", 0),
                             ("incarnation", 0x100000000), ("expected_revision", -1), ("expected_revision", True)):
            with self.subTest(field=field, value=value), self.assertRaises(ProtocolError):
                validate_checkpoint_request({**self.request, field: value}, 3)

    def test_replies_reject_wrong_identity_bounds_and_extra_fields(self):
        changes = [("world_id", str(uuid.uuid4())), ("player_id", str(uuid.uuid4())), ("grant_id", str(uuid.UUID(int=0))),
                   ("start", 0), ("start", True), ("end_exclusive", 1), ("end_exclusive", 434),
                   ("lease_epoch", 2), ("incarnation", 0), ("expected_revision", -1)]
        for field, value in changes:
            reply = deepcopy(self.reply)
            reply["grant"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ProtocolError):
                self.validate(reply)
        with self.assertRaises(ProtocolError):
            self.validate({**self.reply, "party": []})
        with self.assertRaises(ProtocolError):
            self.validate({**self.reply, "session_epoch": 4})

    def test_controlled_error_remains_correlated_and_has_no_grant(self):
        reply = {key: value for key, value in self.reply.items() if key not in {"checkpoint", "grant"}}
        reply.update(type="checkpoint_error", code="enrollment_required", message="host enrollment required")
        self.assertEqual(self.validate(reply), reply)
        with self.assertRaises(ProtocolError):
            self.validate({**reply, "grant": self.reply["grant"]})
