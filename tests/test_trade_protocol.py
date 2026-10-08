from __future__ import annotations

import asyncio
from copy import deepcopy
import struct
from types import SimpleNamespace
import unittest
from uuid import uuid4

from emerald_multiplayer.ownership_protocol import OWNERSHIP_PROFILE
from emerald_multiplayer.protocol import MAX_COUNTER, MAX_FRAME_BYTES, ProtocolError, encode_message, read_message
from emerald_multiplayer.trade_protocol import TRADE_TYPES, validate_trade_common, validate_trade_request, validate_trade_reply

ACTOR, PEER = sorted((str(uuid4()), str(uuid4())))
WORLD, TX, GENERATION, REQUEST = (str(uuid4()) for _ in range(4))
SHA = "1" * 64
CONFIG = SimpleNamespace(player_id=ACTOR, build_id="test-trade-build", ruleset_id="test-rules")
EPOCH = 7


def request(operation, **changes):
    body = {
        "open": {"peer": PEER, "transaction_id": TX},
        "offer": {"transaction_id": TX, "generation": GENERATION, "revision": 1, "sha256": SHA, "serial": 1},
        "confirm": {"transaction_id": TX, "generation": GENERATION, "fingerprint": SHA},
        "cancel": {"transaction_id": TX, "generation": GENERATION},
        "status": {"transaction_id": TX},
        "pending": {},
        "proposals": {},
        "ack": {"transaction_id": TX, "revision": 2, "sha256": SHA},
    }[operation]
    return {"type": "trade_" + operation, "request_id": REQUEST, "session_epoch": EPOCH, **body, **changes}


def offering(count=2, confirmed=False):
    return {
        "transaction_id": TX, "generation": GENERATION, "state": "offering",
        "players": [ACTOR, PEER], "fingerprint": SHA if count == 2 else None,
        "offers": [{"player_id": player, "serial": index + 1, "species": 265,
                    "revision": 1, "sha256": SHA} for index, player in enumerate((ACTOR, PEER)[:count])],
        "confirmations": [ACTOR] if confirmed else [],
    }


def committed():
    return {"transaction_id": TX, "state": "committed", "outcome_fingerprint": SHA, "revision": 2, "sha256": SHA}


def metadata():
    return {"revision": 2, "request_id": TX, "size": 131088, "sha256": SHA,
            "build_id": CONFIG.build_id, "ruleset_id": CONFIG.ruleset_id, "save_profile": OWNERSHIP_PROFILE}


def reply(op, **changes):
    value = {"type": "trade_result", "protocol": 1, "session_epoch": EPOCH,
             "request_id": REQUEST, "operation": op, "world_id": WORLD, "player_id": ACTOR}
    if op == "proposals":
        value["proposals"] = [offering()]
    elif op == "pending":
        value["recoveries"] = [{"transaction_id": TX, "sequence": 3, "outcome_fingerprint": SHA, "checkpoint": metadata()}]
    elif op == "ack":
        value["trade"] = {"transaction_id": TX, "state": "acknowledged", "revision": 2, "sha256": SHA}
    elif op == "cancel":
        value["trade"] = {"transaction_id": TX, "state": "aborted"}
    else:
        value["trade"] = offering()
    return {**value, **changes}


class TradeRequestTests(unittest.TestCase):
    def test_every_exact_request_is_bounded_and_preserved(self):
        for kind in TRADE_TYPES:
            message = request(kind.removeprefix("trade_"))
            before = deepcopy(message)
            self.assertEqual(validate_trade_request(message, EPOCH), message)
            self.assertEqual(message, before)
            self.assertLess(len(encode_message(message)) - 4, MAX_FRAME_BYTES)

    def test_actor_claims_save_bytes_and_missing_or_extra_fields_reject(self):
        for op in ("open", "offer", "confirm", "cancel", "status", "pending", "ack"):
            for field, value in (("player_id", PEER), ("credential", "a" * 64), ("payload", "save"), ("incarnation", 1)):
                with self.subTest(op=op, field=field), self.assertRaises(ProtocolError):
                    validate_trade_request(request(op, **{field: value}), EPOCH)
            missing = request(op); del missing["request_id"]
            with self.assertRaises(ProtocolError):
                validate_trade_request(missing, EPOCH)

    def test_correlation_errors_are_distinct_from_body_errors(self):
        valid = request("offer")
        self.assertEqual(validate_trade_common({**valid, "serial": False}, EPOCH), {**valid, "serial": False})
        with self.assertRaises(ProtocolError) as caught:
            validate_trade_request(request("offer", session_epoch=EPOCH + 1), EPOCH)
        self.assertEqual(caught.exception.code, "session_epoch_mismatch")
        for changed in ({"session_epoch": True}, {"request_id": "bad"}, {"type": "checkpoint_info"}):
            with self.assertRaises(ProtocolError):
                validate_trade_common({**valid, **changed}, EPOCH)

    def test_numeric_hash_uuid_boundaries_reject_bool_and_noncanonical_values(self):
        for field, values in (("serial", (True, 0, -1, 0x100000, "1")),
                              ("revision", (True, 0, MAX_COUNTER + 1, 1.0)),
                              ("sha256", (SHA.upper().replace("1", "A"), "f" * 63, None)),
                              ("generation", (True, "0" * 32, "00000000-0000-0000-0000-000000000000"))):
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ProtocolError):
                    validate_trade_request(request("offer", **{field: value}), EPOCH)
        self.assertEqual(validate_trade_request(request("offer", serial=0xFFFFF, revision=MAX_COUNTER), EPOCH)["serial"], 0xFFFFF)


class TradeReplyTests(unittest.TestCase):
    def validate(self, message):
        return validate_trade_reply(message, CONFIG, OWNERSHIP_PROFILE, WORLD, EPOCH)

    def test_proposal_discovery_is_bounded_and_actor_scoped(self):
        self.validate(reply("proposals"))
        self.validate(reply("proposals", proposals=[]))
        for proposals in ([offering(), offering()], [committed()], [{}]):
            with self.assertRaises(ProtocolError):
                self.validate(reply("proposals", proposals=proposals))
        foreign = offering()
        foreign["players"] = sorted([PEER, str(uuid4())])
        with self.assertRaises(ProtocolError):
            self.validate(reply("proposals", proposals=[foreign]))

    def test_valid_states_and_own_pending_metadata(self):
        for operation in ("open", "offer", "confirm", "cancel", "status", "pending", "ack"):
            self.assertEqual(self.validate(reply(operation)), reply(operation))
        for count in (0, 1, 2):
            self.validate(reply("status", trade=offering(count)))
        self.validate(reply("confirm", trade=offering(confirmed=True)))
        for operation in ("open", "confirm", "cancel", "status"):
            self.validate(reply(operation, trade=committed()))
        self.validate(reply("pending", recoveries=[]))

    def test_error_envelope_still_binds_world_player_lease_and_correlation(self):
        error = reply("confirm", type="trade_error", code="trade_offer_changed", message="Confirm the current offer.")
        del error["trade"]
        self.assertEqual(self.validate(error), error)
        for changes in ({"world_id": str(uuid4())}, {"player_id": PEER}, {"session_epoch": EPOCH + 1},
                        {"code": "x" * 129}, {"message": "x" * 513}, {"message": "bad\ntext"}, {"trade": {}}):
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                self.validate({**error, **changes})

    def test_foreign_identity_protocol_profile_and_unknown_envelopes_reject(self):
        for changes in ({"world_id": str(uuid4())}, {"player_id": PEER}, {"protocol": True},
                        {"protocol": 2}, {"request_id": "bad"}, {"operation": "trade_confirm"},
                        {"type": "checkpoint_result"}, {"payload": "save"}, {"session_epoch": True}):
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                self.validate(reply("status", **changes))
        with self.assertRaises(ProtocolError):
            validate_trade_reply(reply("status"), CONFIG, "legacy-profile", WORLD, EPOCH)

    def test_offers_and_confirmations_must_match_the_complete_two_player_view(self):
        variants = []
        for field, value in (("players", [PEER, ACTOR]), ("players", [ACTOR, ACTOR]),
                             ("players", [PEER, str(uuid4())]), ("offers", offering()["offers"] * 2),
                             ("confirmations", [ACTOR, PEER]), ("fingerprint", None),
                             ("confirmations", [str(uuid4())])):
            value_state = offering(); value_state[field] = value; variants.append(value_state)
        for field, value in (("serial", True), ("serial", 0x100000), ("species", 0), ("revision", False),
                             ("sha256", "F" * 64), ("player_id", str(uuid4())), ("payload", "save")):
            value_state = offering(); value_state["offers"][0][field] = value; variants.append(value_state)
        duplicate = offering(); duplicate["offers"][1]["serial"] = 1; variants.append(duplicate)
        unoffered = offering(1); unoffered["confirmations"] = [ACTOR]; variants.append(unoffered)
        bad_hash = offering(1); bad_hash["fingerprint"] = SHA; variants.append(bad_hash)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                self.validate(reply("status", trade=value))

    def test_result_operation_state_and_exact_fields_reject_ambiguity(self):
        for operation, trade in (("ack", committed()), ("offer", committed()),
                                 ("confirm", {"transaction_id": TX, "state": "aborted"}),
                                 ("cancel", offering()), ("open", {"transaction_id": TX, "state": "aborted"})):
            with self.subTest(operation=operation), self.assertRaises(ProtocolError):
                self.validate(reply(operation, trade=trade))
        for changes in ({"revision": True}, {"sha256": "x" * 64}, {"outcome_fingerprint": ""}, {"payload": "save"}):
            with self.assertRaises(ProtocolError):
                self.validate(reply("status", trade={**committed(), **changes}))

    def test_pending_is_bounded_own_compatible_checkpoint_not_peer_save(self):
        base = reply("pending")
        variants = []
        two = deepcopy(base); two["recoveries"] *= 2; variants.append(two)
        for field, value in (("sequence", True), ("transaction_id", str(uuid4())),
                             ("outcome_fingerprint", ""), ("player_id", PEER), ("payload", "save")):
            changed = deepcopy(base); changed["recoveries"][0][field] = value; variants.append(changed)
        for field, value in (("build_id", "other"), ("save_profile", "legacy"), ("size", 131071),
                             ("revision", False), ("request_id", str(uuid4())), ("payload", "save")):
            changed = deepcopy(base); changed["recoveries"][0]["checkpoint"][field] = value; variants.append(changed)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                self.validate(value)


class TradeFramingTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_trade_frames_and_existing_frame_cap(self):
        message = request("confirm")
        encoded = encode_message(message)
        reader = asyncio.StreamReader()
        pending = asyncio.create_task(read_message(reader))
        for chunk in (encoded[:1], encoded[1:4], encoded[4:17], encoded[17:-1]):
            reader.feed_data(chunk); await asyncio.sleep(0)
            self.assertFalse(pending.done())
        reader.feed_data(encoded[-1:])
        self.assertEqual(validate_trade_request(await pending, EPOCH), message)
        oversized = asyncio.StreamReader(); oversized.feed_data(struct.pack("!I", MAX_FRAME_BYTES + 1))
        with self.assertRaises(ProtocolError) as caught:
            await read_message(oversized)
        self.assertEqual(caught.exception.code, "frame_too_large")


if __name__ == "__main__":
    unittest.main()
