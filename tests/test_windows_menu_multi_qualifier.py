"""Multi proof-boundary fixtures, not native or graphical acceptance."""
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts" / "windows-runtime")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from qualify_menu_multi import (FULL_PARTY_COUNTS, challenge_slots, outcome_label,
                                qualification_profile, selected_party_slots)


def challenge():
    # Account order deliberately differs from sorted/interleaved native slots.
    accounts = [SimpleNamespace(player_id=p) for p in ("z", "a", "y", "b")]
    players = ["a", "b", "z", "y"]
    value = dict(mode=3, state="accepted", players=players, consent=list(reversed(players)),
        checkpoints=[dict(player_id=p, source_slot=i, party_count=2 if p == "z" else 1)
                     for i, p in enumerate(players)])
    return accounts, value


class MultiRosterTests(unittest.TestCase):
    def test_explicit_full_party_profile_cannot_weaken_default_bounds(self):
        self.assertEqual(qualification_profile(False, None), ((2, 1, 1, 1), 1200, 2100))
        self.assertEqual(qualification_profile(True, None), ((6, 6, 6, 6), 6600, 7200))
        for mode, timeout in ((False, 2101), (True, 7201), (False, float("nan")),
                              (True, float("inf")), (True, True), (1, None)):
            with self.subTest(mode=mode, timeout=timeout), self.assertRaises(AssertionError):
                qualification_profile(mode, timeout)

    def test_full_profile_requires_every_exact_personal_party_to_have_six(self):
        accounts, value = challenge()
        with self.assertRaises(AssertionError):
            challenge_slots(value, accounts, FULL_PARTY_COUNTS)
        for cp in value["checkpoints"]:
            cp["party_count"] = 6
        self.assertEqual(challenge_slots(value, accounts, FULL_PARTY_COUNTS), [2, 0, 3, 1])
        for slot in range(4):
            partial = deepcopy(value)
            partial["checkpoints"][slot]["party_count"] = 3
            with self.subTest(slot=slot), self.assertRaises(AssertionError):
                challenge_slots(partial, accounts, FULL_PARTY_COUNTS)

    def test_native_slots_derive_from_the_exact_four_personal_roster(self):
        accounts, value = challenge()
        self.assertEqual(challenge_slots(value, accounts), [2, 0, 3, 1])

    def test_missing_or_duplicate_consent_cannot_admit_a_partial_team(self):
        accounts, value = challenge()
        for consent in (value["consent"][:-1], ["a", "a", "b", "y"], ["a", "b", "y", "outsider"]):
            with self.subTest(consent=consent), self.assertRaises(AssertionError):
                challenge_slots(dict(value, consent=consent), accounts)

    def test_reordered_native_sides_cannot_silently_change_formed_teams(self):
        accounts, value = challenge()
        value["players"] = ["a", "z", "b", "y"]
        value["checkpoints"] = [dict(player_id=p, source_slot=i, party_count=2 if p == "z" else 1)
                                  for i, p in enumerate(value["players"])]
        with self.assertRaisesRegex(AssertionError, "two explicitly formed teams"):
            challenge_slots(value, accounts)

    def test_checkpoint_slot_count_or_identity_must_match_its_actor(self):
        accounts, base = challenge()
        for key, replacement in (("source_slot", 0), ("party_count", 1), ("player_id", "outsider")):
            value = deepcopy(base)
            value["checkpoints"][2][key] = replacement
            with self.subTest(key=key), self.assertRaises(AssertionError):
                challenge_slots(value, accounts)

    def test_every_player_result_label_uses_native_side_and_actual_outcome(self):
        _, value = challenge()
        result = dict(mode=3, players=value["players"], sequence=17)
        for outcome, expected in ((1, ("Win", "Loss", "Win", "Loss")),
                                  (2, ("Loss", "Win", "Loss", "Win")),
                                  (3, ("Draw",) * 4)):
            self.assertEqual([outcome_label(dict(result, outcome=outcome), p) for p in result["players"]],
                             [f"2v2 {word} #17" for word in expected])
        with self.assertRaises(AssertionError):
            outcome_label(dict(result, outcome=0), "a")

    def test_forced_switch_evidence_requires_validated_native_party_response(self):
        packet = bytes([1]) + bytes(7) + bytes([33, 1])
        blocks = [dict(kind=8, source=2, data=packet.hex()),
                  dict(kind=7, source=0, data=packet.hex()),
                  dict(kind=8, source=0, data=packet[:9].hex()),
                  dict(kind=8, source=0, data=(bytes([2])+packet[1:]).hex())]
        self.assertEqual(selected_party_slots(blocks), [dict(owner=2, slot=1)])


if __name__ == "__main__":
    unittest.main()
