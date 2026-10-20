from copy import deepcopy
import struct
import unittest
from uuid import uuid4

from emerald_multiplayer.battle_protocol import (
    BATTLE_OPERATIONS, SCOPE, validate_battle_request, validate_battle_reply,
)
from emerald_multiplayer.protocol import MAX_FRAME_BYTES, ProtocolError, encode_message
from emerald_multiplayer.protocol import PROTOCOL_VERSION

ACTOR, PEER, THIRD, FOURTH, WORLD, REQUEST, BATTLE, GENERATION = (str(uuid4()) for _ in range(8))


def cleanup_receipt(*, held=False):
    """Wire fixture only; host/native authority is tested in the cleanup suites."""
    from emerald_multiplayer.battle_execution_protocol import encode_control
    from emerald_multiplayer.native_battle import NativeControl, Opcode
    from emerald_multiplayer.native_battle_resume import Admission
    data = Admission(GENERATION, ACTOR, REQUEST).pack() + struct.pack("<I", 7)
    if held:
        data += bytes.fromhex("c" * 64)
    return encode_control(NativeControl(1, 7, BATTLE, 1,
        Opcode.ADMISSION_CANCEL_HOLD if held else Opcode.ADMISSION_CANCEL_READY,
        phase=2, source_slot=0, data=data))


def handoff_receipt():
    from dataclasses import replace
    from emerald_multiplayer.battle_execution_protocol import decode_control, encode_control
    from emerald_multiplayer.native_battle import Opcode
    return encode_control(replace(decode_control(cleanup_receipt(held=True)),
                                  opcode=Opcode.ADMISSION_CANCEL_HANDOFF))


def request(op, **fields):
    extra = dict(
        invite=dict(peer=PEER, battle_id=BATTLE),
        invite_multi=dict(teammate=THIRD, opponents=[PEER, FOURTH], battle_id=BATTLE),
        invite_ffa=dict(opponents=[PEER, THIRD, FOURTH], battle_id=BATTLE),
        invite_ffa3=dict(opponents=[PEER, THIRD], battle_id=BATTLE),
        accept=dict(battle_id=BATTLE, generation=GENERATION, fingerprint="a" * 64),
        claim=dict(battle_id=BATTLE, generation=GENERATION, incarnation=1, runtime_id=REQUEST),
        cancel=dict(battle_id=BATTLE, generation=GENERATION),
        cancel_admission=dict(battle_id=BATTLE, generation=GENERATION, incarnation=1,
                              runtime_id=REQUEST, cleanup_ready_b64=cleanup_receipt(),
                              cleanup_receipt_b64=None),
        admission_handoff=dict(battle_id=BATTLE, generation=GENERATION, incarnation=1,
                               runtime_id=REQUEST, handoff_receipt_b64=handoff_receipt()),
        status=dict(battle_id=BATTLE), pending={}, history={}, waiting={},
        execute=dict(battle_id=BATTLE, generation=GENERATION, incarnation=1,
                     response_id=0, response_b64=None),
        resume=dict(battle_id=BATTLE, generation=GENERATION, incarnation=1,
                    response_id=0, response_b64=None, response_stage=None),
        abandon=dict(battle_id=BATTLE, generation=GENERATION),
        fate=dict(battle_id=BATTLE, generation=GENERATION),
    )[op]
    return dict(type="battle_" + op, request_id=REQUEST, session_epoch=7, **(extra | fields))


def view(mode=2):
    players = [ACTOR, PEER] if mode == 2 else [ACTOR, PEER, THIRD] if mode == 6 else [ACTOR, PEER, THIRD, FOURTH]
    return dict(scope=SCOPE, battle_id=BATTLE, generation=GENERATION, sender=ACTOR,
        mode=mode, state="invited", reason=None, players=players,
        fingerprint="a" * 64, consent=[ACTOR], outcome=None,
        checkpoints=[dict(player_id=p, source_slot=i, revision=1, sha256="b" * 64,
                          party_count=6) for i, p in enumerate(players)])


def reply(op):
    if op == "execute":
        from emerald_multiplayer.battle_execution_protocol import execution_view
        result = execution_view(BATTLE, GENERATION, "waiting")
    elif op == "resume":
        from emerald_multiplayer.battle_recovery_protocol import recovery_view
        result = recovery_view(BATTLE, GENERATION, "waiting")
    elif op == "cancel_admission":
        from emerald_multiplayer.battle_admission_cleanup_protocol import SCOPE as CLEANUP_SCOPE
        result = dict(scope=CLEANUP_SCOPE, battle_id=BATTLE, generation=GENERATION,
            incarnation=1, runtime_id=REQUEST, original_lease=7,
            tombstone_sha256="c" * 64, acknowledged=False)
    elif op == "admission_handoff":
        from emerald_multiplayer.battle_admission_cleanup_protocol import handoff_view
        from emerald_multiplayer.battle_execution_protocol import decode_control
        result = handoff_view(decode_control(handoff_receipt(), response=True))
    elif op in ("abandon", "fate"):
        from emerald_multiplayer.battle_abandonment import abandonment_view
        result = abandonment_view(BATTLE, GENERATION, "abandoned", (ACTOR, PEER), "d" * 64)
    else:
        result = [] if op in ("history", "waiting") else ([view()] if op == "pending" else view({"invite_multi": 3, "invite_ffa": 5, "invite_ffa3": 6}.get(op, 2)))
    return dict(type="battle_result", protocol=PROTOCOL_VERSION, session_epoch=7, request_id=REQUEST,
        operation=op, world_id=WORLD, player_id=ACTOR,
        result=result)


class BattleProtocolTests(unittest.TestCase):
    def check(self, value, expected=None):
        return validate_battle_reply(value, ACTOR, WORLD, 7, expected)

    def test_exact_operations_roundtrip_and_fit_transport(self):
        for op in BATTLE_OPERATIONS:
            req, result = request(op), reply(op)
            self.assertEqual(validate_battle_request(req, 7), req)
            self.assertEqual(self.check(result, req), result)
            self.assertLess(len(encode_message(result)) - 4, MAX_FRAME_BYTES)

    def test_cancellation_acknowledgment_has_exact_stage_and_identity(self):
        req = request("cancel_admission", cleanup_receipt_b64=cleanup_receipt(held=True))
        result = reply("cancel_admission")
        result["result"]["acknowledged"] = True
        self.assertEqual(validate_battle_request(req, 7), req)
        self.assertEqual(self.check(result, req), result)
        self.assertLess(len(encode_message(req)) - 4, MAX_FRAME_BYTES)
        self.assertLess(len(encode_message(result)) - 4, MAX_FRAME_BYTES)
        for field, value in (("battle_id", str(uuid4())), ("generation", str(uuid4())),
                             ("runtime_id", str(uuid4())), ("incarnation", 2),
                             ("acknowledged", False), ("tombstone_sha256", "0" * 64)):
            changed = deepcopy(result)
            changed["result"][field] = value
            with self.subTest(field=field), self.assertRaises(ProtocolError):
                self.check(changed, req)

    def test_cancellation_requires_ready_and_correct_successful_receipt_kinds(self):
        for field, value in (("cleanup_ready_b64", None), ("cleanup_ready_b64", "invalid"),
                             ("cleanup_ready_b64", cleanup_receipt(held=True)),
                             ("cleanup_receipt_b64", cleanup_receipt()),
                             ("cleanup_receipt_b64", True)):
            with self.subTest(field=field, value=value), self.assertRaises(ProtocolError):
                validate_battle_request(request("cancel_admission", **{field: value}), 7)
        missing = request("cancel_admission")
        del missing["cleanup_ready_b64"]
        with self.assertRaises(ProtocolError):
            validate_battle_request(missing, 7)

    def test_handoff_requires_original_receipt_and_exact_acknowledgment(self):
        req = request("admission_handoff")
        for value in (cleanup_receipt(), cleanup_receipt(held=True), None):
            with self.subTest(receipt=value), self.assertRaises(ProtocolError):
                validate_battle_request(request("admission_handoff",handoff_receipt_b64=value),7)
        for key,value in (("receipt_sha256","d"*64),("handoff_lease",8),
                          ("generation",str(uuid4())),("acknowledged",False)):
            result = reply("admission_handoff")
            result["result"][key] = value
            with self.subTest(field=key), self.assertRaises(ProtocolError):
                self.check(result,req)

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

    def test_bad_free_for_all_rosters(self):
        for opponents in ([PEER], [PEER, THIRD], [PEER, PEER, THIRD], [PEER, THIRD, FOURTH, ACTOR], [PEER, THIRD, {}]):
            with self.subTest(opponents=opponents), self.assertRaises(ProtocolError):
                validate_battle_request(request("invite_ffa", opponents=opponents), 7)

    def test_free_for_all_reply_names_exactly_the_invited_four_and_the_challenger_first(self):
        req = request("invite_ffa")
        result = reply("invite_ffa")
        self.assertEqual(result["result"]["mode"], 5)
        self.assertEqual(self.check(result, req), result)
        swapped = reply("invite_ffa")
        swapped["result"]["players"][0], swapped["result"]["players"][1] = PEER, ACTOR
        for slot, cp in enumerate(swapped["result"]["checkpoints"]):
            cp["player_id"] = swapped["result"]["players"][slot]
        with self.assertRaises(ProtocolError): self.check(swapped, req)
        other = reply("invite_ffa")
        other["result"]["players"][3] = str(uuid4())
        other["result"]["checkpoints"][3]["player_id"] = other["result"]["players"][3]
        with self.assertRaises(ProtocolError): self.check(other, req)

    def test_free_for_all_outcome_is_a_winner_slot_or_a_draw(self):
        for outcome in (1, 2, 3, 4, 5):
            result = reply("status"); result["result"] = view(5) | dict(outcome=outcome)
            self.check(result)
        for outcome in (0, 6, True):
            result = reply("status"); result["result"] = view(5) | dict(outcome=outcome)
            with self.subTest(outcome=outcome), self.assertRaises(ProtocolError): self.check(result)
        result = reply("status"); result["result"].update(outcome=4)   # four is not a result of a two-trainer battle
        with self.assertRaises(ProtocolError): self.check(result)

    def test_1v1v1_roster_reply_and_outcomes(self):
        """Update 32: the three-player free-for-all names two other trainers, comes back as mode 6 with the challenger
        first, and ends with one of the three slots or a draw (never 4: the empty place)."""
        for opponents in ([PEER], [PEER, PEER], [PEER, THIRD, FOURTH], [PEER, {}]):
            with self.subTest(opponents=opponents), self.assertRaises(ProtocolError):
                validate_battle_request(request("invite_ffa3", opponents=opponents), 7)
        req, result = request("invite_ffa3"), reply("invite_ffa3")
        self.assertEqual((result["result"]["mode"], len(result["result"]["players"])), (6, 3))
        self.assertEqual(self.check(result, req), result)
        for mode in (5, 2):
            wrong = reply("invite_ffa3"); wrong["result"]["mode"] = mode
            with self.subTest(mode=mode), self.assertRaises(ProtocolError): self.check(wrong, req)
        four = reply("invite_ffa")
        with self.assertRaises(ProtocolError): self.check(four, req)          # four players are not a 1v1v1
        for outcome in (1, 2, 3, 5):
            result = reply("status"); result["result"] = view(6) | dict(outcome=outcome)
            self.check(result)
        for outcome in (0, 4, 6):
            result = reply("status"); result["result"] = view(6) | dict(outcome=outcome)
            with self.subTest(outcome=outcome), self.assertRaises(ProtocolError): self.check(result)

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

    def test_history_is_bounded_ordered_participant_only_and_read_only(self):
        from emerald_multiplayer.battle_results import SCOPE as RESULT_SCOPE, HISTORY_LIMIT
        result = reply("history")
        for number in range(HISTORY_LIMIT, 0, -1):
            item = view(3)
            for key in ("state", "reason", "consent"): del item[key]
            item.update(scope=RESULT_SCOPE, sequence=number, battle_id=str(uuid4()), outcome=1)
            result["result"].append(item)
        self.assertEqual(self.check(result, request("history")), result)
        self.assertLess(len(encode_message(result)) - 4, MAX_FRAME_BYTES)
        for change in (lambda r: r["result"].reverse(), lambda r: r["result"].append(r["result"][0]),
                lambda r: r["result"][0].update(outcome=None),
                lambda r: r["result"][0].update(sequence=True),
                lambda r: r["result"][0].update(scope=SCOPE),
                lambda r: r["result"][0].update(receipt="private")):
            bad = deepcopy(result); change(bad)
            with self.assertRaises(ProtocolError): self.check(bad)
        with self.assertRaises(ProtocolError):
            validate_battle_request(request("history", player_id=PEER), 7)
