"""The world-trade proof's readings of Mail and Eggs (scripts/multiplayer/trade_eggs_mail_evidence.py; the newcomers
proof's --scenario trade-mail and trade-egg read the host's saves with it) on the independent C-layout fixtures of
test_trade_eggs_mail: what it finds in the exact exchange, and that it reports a Mail held twice, a Mail lost, a hatch
that keeps the Egg's trainer, loses its shininess or turns it into a Bad Egg. A reading that passed a broken save would
make the real two-game proof say nothing."""
from __future__ import annotations

from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
from emerald_multiplayer.trade_flash import build_party_swap  # noqa: E402
from emerald_multiplayer.trade_mail import cleared_mail  # noqa: E402
from test_trade_eggs_mail import TRAINER_A, TRAINER_B, make_mail, make_mon, pair_saves  # noqa: E402
import trade_eggs_mail_evidence as evidence  # noqa: E402

WAVE_MAIL, WOOD_MAIL = 204, 203
MAIL_A = make_mail(WAVE_MAIL, species=278, author=b"\xce\xbf\xcc\xcf\xff\xff\xff\xff", trainer=b"\x33\x5f\x01\x27")
MAIL_B = make_mail(WOOD_MAIL, species=252, author=b"\xc6\xcf\xbd\xd3\xff\xff\xff\xff", trainer=b"\x40\x72\xe0\xde",
                   words=(1, 2, 3, 4, 5, 6, 7, 8, 9))
TEST_NAME = b"\xce\xbf\xcd\xce\xff\xff\xff"   # "TEST", the fixtures' player (test_flash._blocks)


def wingull(serial=1, mail=0):
    return make_mon(serial, personality=11, species=278, held_item=WAVE_MAIL, mail=mail)


def treecko(serial=33, mail=0, ot_id=TRAINER_B):
    return make_mon(serial, personality=12, species=252, held_item=WOOD_MAIL, mail=mail, ot_id=ot_id)


def zigzagoon(serial=34):
    return make_mon(serial, personality=13, species=263, ot_id=TRAINER_B)


class MailReadingTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = pair_saves([wingull()], [treecko(), zigzagoon()], a_mails={0: MAIL_A}, b_mails={0: MAIL_B})

    def test_mail_both_ways_arrives_whole_and_each_senders_slot_is_taken_by_the_mail_received(self):
        after = build_party_swap(self.a, 1, self.b, 33)
        summary, problems = evidence.mail_trade((self.a, self.b), after, (1, 33))
        self.assertEqual(problems, [])
        rows = {row["serial"]: row for row in summary["sides"]}
        self.assertEqual((rows[1]["received_slot"], rows[33]["received_slot"]), (0, 0))
        self.assertTrue(rows[1]["received_bytes_equal"] and rows[33]["received_bytes_equal"])
        self.assertEqual({rows[1]["sender_slot_after"], rows[33]["sender_slot_after"]}, {"the received Mail"})
        self.assertEqual(rows[1]["mail"]["hex"], MAIL_A.hex())
        self.assertEqual((summary["held_before"], summary["held_after"]), (2, 2))
        self.assertEqual((evidence.census((self.a, self.b)), evidence.census(after)), ([1, 1], [1, 1]))

    def test_mail_one_way_clears_the_senders_slot_and_takes_the_first_free_one(self):
        a, b = build_party_swap(self.a, 1, self.b, 33)
        after = build_party_swap(a, 33, b, 34)            # the Treecko (holding B's Mail) for the Zigzagoon
        summary, problems = evidence.mail_trade((a, b), after, (33, 34))
        self.assertEqual(problems, [])
        rows = {row["serial"]: row for row in summary["sides"]}
        self.assertEqual((rows[33]["sent_slot"], rows[33]["received_slot"], rows[33]["sender_slot_after"]),
                         (0, 1, "cleared"))
        self.assertEqual(evidence.save_mail(after[0])["slots"][0], cleared_mail(MAIL_B))
        self.assertIsNone(rows[34]["mail"])
        self.assertEqual(summary["held_after_slots"], [[1, 0], [1, 1]])

    def test_a_mail_left_behind_is_reported_held_twice(self):
        after_a, after_b = pair_saves([treecko(serial=33, mail=0)], [wingull(serial=1, mail=0), zigzagoon()],
                                      a_mails={0: MAIL_B, 1: MAIL_A}, b_mails={0: MAIL_A})
        _, problems = evidence.mail_trade((self.a, self.b), (after_a, after_b), (1, 33))
        self.assertIn("serial 1's Mail is still in its sender's save", problems)
        self.assertIn("a Mail is held twice", problems)
        self.assertEqual(evidence.census((after_a, after_b)), [1, 2])
        self.assertIn("the Mails held in the two parties differ before and after (one duplicated or lost)", problems)

    def test_a_lost_mail_is_reported(self):
        # The Wingull arrives holding its Mail item but no Mail: the item an ordinary one, the words gone.
        after_a, after_b = pair_saves([treecko(serial=33, mail=0)], [wingull(serial=1, mail=0xFF), zigzagoon()],
                                      a_mails={0: MAIL_B})
        _, problems = evidence.mail_trade((self.a, self.b), (after_a, after_b), (1, 33))
        self.assertIn("serial 1's Mail did not arrive whole in slot None", problems)
        self.assertIn("the Mails held in the two parties differ before and after (one duplicated or lost)", problems)

    def test_an_untouched_slot_that_changes_is_reported(self):
        after = build_party_swap(self.a, 1, self.b, 33)
        stray = make_mail(WOOD_MAIL, species=1, words=(9,) * 9)
        after_a, after_b = pair_saves([treecko(serial=33, mail=0)], [wingull(serial=1, mail=0), zigzagoon()],
                                      a_mails={0: MAIL_B, 9: stray}, b_mails={0: MAIL_A})
        self.assertEqual(evidence.mail_trade((self.a, self.b), after, (1, 33))[1], [])
        _, problems = evidence.mail_trade((self.a, self.b), (after_a, after_b), (1, 33))
        self.assertIn("side 0's Mail slot 9 changed though no traded Mail used it", problems)


class HatchReadingTests(unittest.TestCase):
    PERSONALITY = 0x4B1D5EED

    def receiver(self, first, boxes=None):
        """The receiving side's save (player B, trainer TRAINER_B, the fixtures' "TEST", male)."""
        _, b = pair_saves([make_mon(1, personality=8)], [first, zigzagoon()], b_mails=None)
        if boxes is None:
            return b
        from test_trade_eggs_mail import make_ownership_record, make_save
        return make_save([first, zigzagoon()], boxes=boxes, trainer_id=TRAINER_B,
                         metadata=make_ownership_record(player_id="0b3c2e4d-0000-4000-8000-00000000000b", start=33,
                                                        end_exclusive=65, next_serial=65))

    def egg(self, **changes):
        values = dict(personality=self.PERSONALITY, egg=True, friendship=1, ot_id=TRAINER_A, level=1)
        values.update(changes)
        return make_mon(5, **values)

    def hatched(self, **changes):
        values = dict(personality=self.PERSONALITY, egg=False, friendship=120, ot_id=TRAINER_B, level=1,
                      ot_name=TEST_NAME)
        values.update(changes)
        return make_mon(5, **values)

    def test_a_right_hatch_reads_without_a_problem(self):
        summary, problems = evidence.hatch(self.receiver(self.egg()), self.receiver(self.hatched()), 5)
        self.assertEqual(problems, [])
        self.assertTrue(summary["before"]["egg"])
        self.assertEqual((summary["after"]["ot_id"], summary["after"]["ot_name"], summary["hatcher"]["name"]),
                         (TRAINER_B, "TEST", "TEST"))
        self.assertEqual(summary["after"]["ivs"], summary["before"]["ivs"])

    def test_the_hatch_in_a_pc_box_reads_the_same(self):
        lead = make_mon(40, personality=99, ot_id=TRAINER_B)
        before = self.receiver(lead, boxes={(0, 0): self.egg()})
        after = self.receiver(lead, boxes={(0, 0): self.hatched()})
        summary, problems = evidence.hatch(before, after, 5)
        self.assertEqual(problems, [])
        self.assertEqual((summary["before"]["location"], summary["after"]["location"]), ("box:0:0", "box:0:0"))

    def test_a_hatch_that_keeps_the_eggs_trainer_or_still_an_egg_is_reported(self):
        _, problems = evidence.hatch(self.receiver(self.egg()), self.receiver(self.hatched(ot_id=TRAINER_A)), 5)
        self.assertTrue(any(p.startswith("the original trainer ID is 0x1111aaaa") for p in problems), problems)
        _, problems = evidence.hatch(self.receiver(self.egg()), self.receiver(self.egg()), 5)
        self.assertIn("the record is still an Egg", problems)

    def test_changed_ivs_name_or_lost_shininess_are_reported(self):
        _, problems = evidence.hatch(self.receiver(self.egg()), self.receiver(self.hatched(ivs=0x0A5294A6)), 5)
        self.assertTrue(any(p.startswith("ivs changed") for p in problems), problems)
        _, problems = evidence.hatch(self.receiver(self.egg()),
                                     self.receiver(self.hatched(ot_name=b"\xbb\xbb\xff\xff\xff\xff\xff")), 5)
        self.assertTrue(any(p.startswith("the original trainer's name") for p in problems), problems)
        shiny_egg = bytearray(self.egg())
        shiny_egg[31] |= 0x40                    # the shiny modifier: shiny under the Egg's trainer
        _, problems = evidence.hatch(self.receiver(bytes(shiny_egg)), self.receiver(self.hatched()), 5)
        self.assertIn("shiny changed: True -> False", problems)

    def test_a_bad_egg_is_reported(self):
        # The pinned engine's old party hatch: the new trainer ID written over a record encrypted with the old one.
        bad = bytearray(self.egg())
        struct.pack_into("<I", bad, 4, TRAINER_B)
        _, problems = evidence.hatch(self.receiver(self.egg()), self.receiver(bytes(bad)), 5)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("a save does not read"), problems)

    def test_the_record_decoder_reads_the_c_layout(self):
        record = evidence.decode_record(make_mon(7, personality=0x13579BDF, species=175, ivs=3 | 7 << 5 | 11 << 10,
                                                 egg=True, friendship=1)[:80])
        self.assertEqual((record["species"], record["ivs"][:3], record["moves"][:2], record["friendship"]),
                         (175, [3, 7, 11], [33, 45], 1))
        self.assertTrue(record["egg"] and record["egg_flag_misc"] and record["egg_flag_header"] and record["checksum_ok"])


if __name__ == "__main__":
    unittest.main()
