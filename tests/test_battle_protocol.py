from copy import deepcopy
import unittest
from uuid import uuid4

from emerald_multiplayer.battle_protocol import (
    BATTLE_OPERATIONS, SCOPE, validate_battle_request, validate_battle_reply,
)
from emerald_multiplayer.protocol import MAX_FRAME_BYTES, ProtocolError, encode_message

ACTOR, PEER, THIRD, FOURTH, WORLD, REQUEST, BATTLE, GENERATION = (str(uuid4()) for _ in range(8))


def request(op, **fields):
    extra = dict(
        invite=dict(peer=PEER, battle_id=BATTLE),
        invite_multi=dict(teammate=THIRD, opponents=[PEER, FOURTH], battle_id=BATTLE),
        accept=dict(battle_id=BATTLE, generation=GENERATION, fingerprint="a" * 64),
        cancel=dict(battle_id=BATTLE, generation=GENERATION),
        status=dict(battle_id=BATTLE), pending={},
    )[op]
    return dict(type="battle_" + op, request_id=REQUEST, session_epoch=7, **(extra | fields))


def view(mode=2):
    players = [ACTOR, PEER] if mode == 2 else [ACTOR, PEER, THIRD, FOURTH]
    return dict(scope=SCOPE, battle_id=BATTLE, generation=GENERATION, sender=ACTOR,
        mode=mode, state="invited", reason=None, players=players,
        fingerprint="a" * 64, consent=[ACTOR], outcome=None,
        checkpoints=[dict(player_id=p, source_slot=i, revision=1, sha256="b" * 64,
                          party_count=6) for i, p in enumerate(players)])


def reply(op):
    return dict(type="battle_result", protocol=1, session_epoch=7, request_id=REQUEST,
        operation=op, world_id=WORLD, player_id=ACTOR,
        result=[view()] if op == "pending" else view(3 if op == "invite_multi" else 2))


class BattleProtocolTests(unittest.TestCase):
    def check(self, value, expected=None):
        return validate_battle_reply(value, ACTOR, WORLD, 7, expected)

    def test_exact_operations_roundtrip_and_fit_transport(self):
        for op in BATTLE_OPERATIONS:
            req, result = request(op), reply(op)
            self.assertEqual(validate_battle_request(req, 7), req)
            self.assertEqual(self.check(result, req), result)
            self.assertLess(len(encode_message(result)) - 4, MAX_FRAME_BYTES)

    def test_execution_and_actor_fields_never_accepted(self):
        for key, value in dict(actor=PEER, player_id=PEER, outcome=1,
                               receipt="a", incarnation=1, rng="a" * 32).items():
            with self.subTest(key=key), self.assertRaises(ProtocolError):
                validate_battle_request(request("accept", **{key: value}), 7)
        for op in ("bind", "start", "running", "finish", "release", "register"):
            with self.subTest(op=op), self.assertRaises(ProtocolError):
                validate_battle_request(dict(type="battle_" + op, request_id=REQUEST, session_epoch=7), 7)

    def test_invalid_identity_epoch_and_generation(self):
        for key, values in {"session_epoch": [True, 0, 8], "request_id": [None, "", 1],
                            "generation": ["0" * 36, GENERATION.upper(), []]}.items():
            for value in values:
                req = request("accept"); req[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ProtocolError):
                    validate_battle_request(req, 7)

    def test_bad_multi_rosters(self):
        for opponents in ([PEER], [PEER, PEER], [THIRD, PEER], (PEER, FOURTH), [PEER, {}]):
            with self.subTest(opponents=opponents), self.assertRaises(ProtocolError):
                validate_battle_request(request("invite_multi", opponents=opponents), 7)

    def test_reply_correlation_and_identity_cannot_change(self):
        for key, value in dict(request_id=str(uuid4()), player_id=PEER, world_id=str(uuid4()),
                               session_epoch=8, operation="status", protocol=True).items():
            result = reply("accept"); result[key] = value
            with self.subTest(key=key), self.assertRaises(ProtocolError):
                self.check(result, request("accept"))
        for key in ("battle_id", "generation", "fingerprint"):
            result = reply("accept"); result["result"][key] = "c" * 64 if key == "fingerprint" else str(uuid4())
            with self.subTest(key=key), self.assertRaises(ProtocolError):
                self.check(result, request("accept"))

    def test_pending_does_not_expose_another_players_room(self):
        result = reply("pending"); result["result"] = [view(), view()]
        with self.assertRaises(ProtocolError): self.check(result)
        result["result"] = [view()]
        result["result"][0]["players"][0] = THIRD
        with self.assertRaises(ProtocolError): self.check(result)

    def test_roster_counts_slots_and_types_strict(self):
        for key, values in dict(party_count=[0, 7, True], revision=[0, True],
                                source_slot=[1, False], sha256=["x" * 64], player_id=[PEER]).items():
            for value in values:
                result = reply("status"); result["result"]["checkpoints"][0][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ProtocolError):
                    self.check(result)

    def test_multi_team_membership_cannot_change(self):
        result = reply("invite_multi")
        result["result"]["players"][1:3] = [THIRD, PEER]
        for slot, cp in enumerate(result["result"]["checkpoints"]):
            cp["player_id"] = result["result"]["players"][slot]
        with self.assertRaises(ProtocolError): self.check(result, request("invite_multi"))

    def test_native_material_and_malformed_state_are_rejected(self):
        for fields in ({"rng": "a" * 32}, {"state": []}, {"reason": "bad\ntext"},
                       {"consent": [ACTOR, ACTOR]}, {"consent": [THIRD]}, {"outcome": True}):
            result = reply("status"); result["result"].update(fields)
            with self.subTest(fields=fields), self.assertRaises(ProtocolError):
                self.check(result)

    def test_bounded_error_envelope(self):
        result = reply("accept"); del result["result"]
        result.update(type="battle_error", code="battle_offer_changed", message="Challenge changed")
        self.assertEqual(self.check(result, request("accept")), result)
        for key, value in (("code", "bad code"), ("message", "x" * 513), ("message", "\x00")):
            bad = deepcopy(result); bad[key] = value
            with self.assertRaises(ProtocolError): self.check(bad)
