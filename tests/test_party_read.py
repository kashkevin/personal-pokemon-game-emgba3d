"""party_read.py: a running game's Pokemon read from outside its process as the game keeps them at rest - never a read
caught while the game has a slot decrypted in place (run 450's egg-box trade, TEST_LEDGER)."""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "multiplayer"))

from party_read import box_checks_out, consistent  # noqa: E402


def box(personality, ot_id, plain_words):
    """A BoxPokemon's 80 bytes as the game keeps them: the checksum over the plain secure words, the words encrypted."""
    checksum = sum((w & 0xFFFF) + (w >> 16) for w in plain_words) & 0xFFFF
    head = struct.pack("<II", personality, ot_id) + bytes(range(8, 28)) + struct.pack("<HH", checksum, 0)
    return head + b"".join(struct.pack("<I", w ^ personality ^ ot_id) for w in plain_words)


def decrypted(record, words=12):
    """The same record with its first `words` secure words decrypted in place, as GetBoxMonData leaves it meanwhile."""
    personality, ot_id = struct.unpack_from("<II", record, 0)
    out = bytearray(record)
    for i in range(words):
        at = 32 + 4 * i
        struct.pack_into("<I", out, at, struct.unpack_from("<I", out, at)[0] ^ personality ^ ot_id)
    return bytes(out)


PLAIN = [0x00010119, 0x00000B40, 0x00210021, 0x0000002D, 0x23232323, 0x00000000,
         0x01020304, 0x0A0B0C0D, 0x11111111, 0x22222222, 0x45454545, 0x00FF00FF]
MON = box(0x9A3F12C7, 0x7E21ABCD, PLAIN)
OTHER = box(0x13579BDF, 0x2468ACE0, [w ^ 0x5A5A0101 for w in PLAIN])


def slot(record):
    return record + bytes(20)          # a party slot: the BoxPokemon and 20 bytes of battle stats


class BoxChecksOutTests(unittest.TestCase):
    def test_a_record_at_rest_checks_out(self):
        self.assertTrue(box_checks_out(MON))
        self.assertTrue(box_checks_out(OTHER))

    def test_an_empty_slot_checks_out(self):
        self.assertTrue(box_checks_out(bytes(80)))

    def test_a_record_caught_decrypted_or_half_decrypted_does_not(self):
        self.assertFalse(box_checks_out(decrypted(MON)))
        self.assertFalse(box_checks_out(decrypted(MON, 5)))
        self.assertFalse(box_checks_out(decrypted(OTHER, 1)))


class ConsistentTests(unittest.TestCase):
    def reader(self, reads):
        it = iter(reads)
        calls = []

        def read():
            calls.append(1)
            return next(it)
        return read, calls

    def test_a_torn_read_is_read_again(self):
        steady = slot(MON) + slot(OTHER) + bytes(400)
        torn = slot(decrypted(MON, 7)) + slot(OTHER) + bytes(400)
        read, calls = self.reader([torn, steady, steady])
        self.assertEqual(consistent(read), steady)
        self.assertEqual(len(calls), 3)

    def test_a_read_counts_only_when_the_next_is_the_same(self):
        first = slot(MON) + bytes(500)
        second = slot(OTHER) + bytes(500)            # the party changed between two reads (a battle's turn)
        read, calls = self.reader([first, second, second])
        self.assertEqual(consistent(read), second)
        self.assertEqual(len(calls), 3)

    def test_a_record_that_never_checks_out_is_returned_as_it_is(self):
        bad_egg = bytearray(slot(MON))
        bad_egg[28] ^= 0xFF                          # its checksum wrong at rest (a Bad Egg)
        data = bytes(bad_egg) + bytes(500)
        read, calls = self.reader([data] * 10)
        self.assertEqual(consistent(read, tries=10), data)
        self.assertEqual(len(calls), 10)

    def test_box_records_by_their_own_stride(self):
        read, calls = self.reader([decrypted(OTHER, 12), OTHER, OTHER])
        self.assertEqual(consistent(read, stride=80), OTHER)
        self.assertEqual(len(calls), 3)


class ProbePartyTests(unittest.TestCase):
    def test_party_now_never_takes_a_torn_read(self):
        sys.path.insert(0, str(ROOT / "scripts" / "windows-runtime"))
        from native_launcher_battle_proof import NativeProbe

        steady = slot(MON) + slot(OTHER) + bytes(400)
        torn = slot(MON) + slot(decrypted(OTHER, 3)) + bytes(400)
        parties = iter([torn, steady, steady])

        class Probe(NativeProbe):
            def __init__(self):
                pass

            def mem(self, name, size=None, offset=0):
                return bytes([2]) if name == "gPartiesCount" else next(parties)

        import zlib
        self.assertEqual(Probe().party_now(),
                         dict(count=2, box_crc=f"{zlib.crc32(MON + OTHER):08x}"))


class BoxRecordTests(unittest.TestCase):
    def test_a_box_record_is_found_and_read_again_at_rest(self):
        """The newcomers' and Egg proofs' PC record: found by its personality in the storage, then read again at its own
        place until it checks out (an Egg in the PC counts its steps in place)."""
        sys.path.insert(0, str(ROOT / "scripts" / "windows-runtime"))
        from native_launcher_newcomers_proof import NewcomersProof
        from emerald_multiplayer.flash import STORAGE_SIZE

        base = 0x10000
        at = base + 4 + (3 * 30 + 7) * 80                      # box 3, slot 7
        memory = bytearray(base + STORAGE_SIZE + 16)
        steady = OTHER[:19] + bytes([OTHER[19] | 2]) + OTHER[20:]   # has a species (the flag the search reads)
        memory[at:at + 80] = steady
        torn = [decrypted(steady, 4)]                            # the second read of the record catches it decrypted

        class Raw:
            def _raw(self, address, size):
                if address == at and size == 80 and torn:
                    return torn.pop()
                return bytes(memory[address:address + size])

        class Probe:
            memory = Raw()

            def mem(self, name, size=None, offset=0):
                assert name == "gPokemonStoragePtr"
                return base.to_bytes(4, "little")

        personality = struct.unpack_from("<I", steady, 0)[0]
        location, record = NewcomersProof.game_box_record(None, Probe(), personality)
        self.assertEqual(location, "box:3:7")
        self.assertEqual(record, steady)
        self.assertEqual(torn, [])                               # the torn read was taken, and read again
        self.assertEqual(NewcomersProof.game_box_record(None, Probe(), personality + 1), (None, None))


if __name__ == "__main__":
    unittest.main()
