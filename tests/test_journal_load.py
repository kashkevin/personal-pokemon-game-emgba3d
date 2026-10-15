"""P2: the route journal's size and reload cost (diagnosis issue 3).

The full-six recovery run that failed reached a 66 MB, 110,048-event journal whose reconstruction took
5.4 s on the owner's machine against a five-second RPC deadline. The host now loads it in a worker
thread (tests/test_battle_recovery.py covers that); these tests pin the *cost* of the load itself and
the on-disk format, so a later change cannot silently make recovery slower or alter the bytes.
Run with ``-s`` for the numbers; ``JOURNAL_BENCH_PAIRS`` raises the size (27000 pairs is the 66 MB case).
"""
import hashlib
import json
import os
import time
import unittest
from dataclasses import replace

import test_battle_recovery as recovery
from emerald_multiplayer.battle_execution_journal import FORMAT, ZERO_HASH, RouteJournal
from emerald_multiplayer.battle_execution_protocol import encode_control
from emerald_multiplayer.native_battle import Opcode

PAIRS = int(os.environ.get("JOURNAL_BENCH_PAIRS", "2500"))


def legacy_record(sequence, previous, value):
    """The encoding before the single-pass change: two canonical dumps of the whole record."""
    def dumps(v):
        return (json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(dumps(dict(sequence=sequence, previous=previous, value=value))).hexdigest()
    return dumps(dict(sequence=sequence, previous=previous, value=value, sha256=digest)), digest


class JournalLoadTests(recovery.RecoveryWaitingJournalTests):
    # Reuse the two-player recovery fixture (header, binds, query bytes); run none of its own tests.
    def seed_pairs(self, pairs):
        values = [dict(kind="header", format=FORMAT, value=self.header)]

        def event(kind, slot, ident, control):
            values.append(dict(kind=kind, actor=self.actor(slot)[0], dispatch_id=ident,
                               control_b64=encode_control(control)))
        for slot in range(2):
            event("command", slot, 1, self.binds[slot])
            values.append(dict(kind="admission", actor=self.actor(slot)[0],
                               control_sha256=hashlib.sha256(self.binds[slot].pack()).hexdigest()))
        for slot in range(2):
            event("response", slot, 1, replace(self.binds[slot], data=self.query(slot, 1)))
        for ident in range(2, pairs + 2):
            for slot in range(2):
                query = replace(self.binds[slot], sequence=2, opcode=Opcode.QUERY, data=b"")
                event("command", slot, ident, query)
                event("response", slot, ident, replace(query, data=self.query(slot, 1)))
        raw, previous = bytearray(), ZERO_HASH
        for sequence, value in enumerate(values):
            line, previous = RouteJournal._record(sequence, previous, value)
            raw.extend(line)
        self.path.write_bytes(raw)
        return values, bytes(raw)

    def test_record_bytes_are_unchanged_by_the_single_pass_encoding(self):
        values, raw = self.seed_pairs(20)
        previous, expected = ZERO_HASH, bytearray()
        for sequence, value in enumerate(values):
            line, previous = legacy_record(sequence, previous, value)
            expected.extend(line)
        self.assertEqual(raw, bytes(expected))
        for value in (dict(kind="x", text="é \"\\ \n", n=[1, 2.5, None, True], nested=dict(b=1, a=2)), {}, []):
            self.assertEqual(RouteJournal._record(7, "ab" * 32, value), legacy_record(7, "ab" * 32, value))

    def test_growth_per_native_command_is_bounded(self):
        values, raw = self.seed_pairs(200)
        events = len(values)
        # Every native command is two events (command and response); a synthetic QUERY is ~600 bytes.
        self.assertEqual(events, 1 + 4 + 2 + 200 * 4)
        self.assertLess(len(raw) / events, 700)

    def test_reload_cost_per_event_is_bounded(self):
        values, raw = self.seed_pairs(PAIRS)
        start = time.perf_counter()
        journal = RouteJournal(self.path, self.header)
        elapsed = time.perf_counter() - start
        self.assertEqual(len(journal.events), len(values))
        self.assertEqual(journal.size, len(raw))
        per_event = elapsed / len(values)
        print(f"\n[P2] reload {len(values)} events / {len(raw) / 1e6:.1f} MB in {elapsed:.2f} s "
              f"({per_event * 1e6:.0f} us/event; the 110,048-event journal would take "
              f"{per_event * 110048:.1f} s here)")
        # Before the cached UUID/enum validation and the single-pass encoding: ~114 us/event on the
        # development machine (12.3 s for 108,000 events). A loose ceiling for slow machines.
        self.assertLess(per_event, 400e-6)


# The inherited tests belong to test_battle_recovery; do not run them twice.
for _name in [n for n in dir(recovery.RecoveryWaitingJournalTests) if n.startswith("test_")]:
    setattr(JournalLoadTests, _name, None)

if __name__ == "__main__":
    unittest.main()
