"""Step 10 (the owner's decision of 2026-10-29): the route journal's transport records no longer wait for an fsync each.

They are written before their command goes out (a crash of a game, a launcher or the host keeps them: the system holds
what was written) and made durable in the background, about every other turn, or by the next lifecycle command's own
fsync. tests/test_battle_recovery.py covers recovery from a journal that lost its newest records.
"""
from dataclasses import replace
import os
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from emerald_multiplayer import battle_execution_journal as journal_module
from emerald_multiplayer.battle_execution_journal import RouteJournal
from emerald_multiplayer.native_battle import Opcode
from test_native_battle import binding, control, query


class JournalFlushTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "route.jsonl"
        bound = binding()
        self.actor = bound.players[0]
        self.header = dict(players=list(bound.players), leases=list(bound.leases),
                           incarnations=list(bound.incarnations), battle_id=control().battle_id, mode=2)
        self.fsyncs = []
        real = os.fsync

        def counted(fd):
            self.fsyncs.append(threading.current_thread().name)
            return real(fd)
        patcher = patch.object(journal_module.os, "fsync", counted)
        patcher.start()
        self.addCleanup(patcher.stop)

    def bound_journal(self):
        """A journal whose first BIND was answered: the lifecycle command and its reply, each fsynced."""
        journal = RouteJournal(self.path, self.header, create=True)
        bind = control()
        journal.append("command", self.actor, 1, bind)
        journal.append("response", self.actor, 1, replace(bind, data=query()))
        return journal, bind

    def queries(self, journal, bind, first, count):
        for ident in range(first, first + count):
            command = replace(bind, sequence=2, opcode=Opcode.QUERY, data=b"")
            journal.append("command", self.actor, ident, command)
            journal.append("response", self.actor, ident, replace(command, data=query()))

    def test_transport_records_go_out_without_their_own_fsync(self):
        journal, bind = self.bound_journal()
        self.assertFalse(journal.unsynced)
        before = len(self.fsyncs)
        with patch.object(journal_module, "FLUSH_SECONDS", 3600):
            self.queries(journal, bind, 2, 20)
        self.assertEqual(len(self.fsyncs), before)           # 40 records, no fsync held a command back
        self.assertTrue(journal.unsynced)
        # written all the same: a new process (the host started again after its own crash) reads every record
        self.assertEqual(RouteJournal(self.path, self.header).events, journal.events)

    def test_a_lifecycle_command_is_still_fsynced_and_makes_every_record_before_it_durable(self):
        journal, bind = self.bound_journal()
        with patch.object(journal_module, "FLUSH_SECONDS", 3600):
            self.queries(journal, bind, 2, 3)
            before = len(self.fsyncs)
            release = replace(bind, sequence=3, opcode=Opcode.RELEASE, data=struct.pack("<II", 0, 1))
            journal.append("command", self.actor, 5, release)
        self.assertEqual(len(self.fsyncs), before + 1)
        self.assertFalse(journal.unsynced)

    def test_flush_makes_the_written_records_durable(self):
        journal, bind = self.bound_journal()
        with patch.object(journal_module, "FLUSH_SECONDS", 3600):
            self.queries(journal, bind, 2, 4)
        self.assertTrue(journal.unsynced)
        journal.flush()
        self.assertFalse(journal.unsynced)

    def test_the_background_flush_runs_in_its_own_thread_one_at_a_time(self):
        journal, bind = self.bound_journal()
        gate, started = threading.Event(), []
        real_flush = journal.flush

        def slow_flush():
            started.append(threading.current_thread().name)
            gate.wait(5)
            real_flush()
        journal.flush = slow_flush
        with patch.object(journal_module, "FLUSH_SECONDS", 0):
            self.queries(journal, bind, 2, 5)                 # ten records while the first flush is held
            self.assertEqual(len(started), 1)                  # one flush at a time
            self.assertTrue(journal.unsynced)
            gate.set()
            deadline = time.monotonic() + 5
            while (journal._flushing or journal.unsynced) and time.monotonic() < deadline:
                time.sleep(.01)
                if not journal._flushing and journal.unsynced:
                    self.queries(journal, bind, 100 + len(started), 1)   # the next record starts the next flush
        self.assertEqual(started[0], "battle-journal-flush")
        self.assertFalse(journal.unsynced)
        self.assertIn("battle-journal-flush", self.fsyncs)

    def test_a_flush_after_the_files_are_gone_is_quiet(self):
        journal, bind = self.bound_journal()
        with patch.object(journal_module, "FLUSH_SECONDS", 3600):
            self.queries(journal, bind, 2, 1)
        self.path.unlink()
        journal._flushing = True
        journal._flush_in_background()                         # no exception: the battle's files went away
        self.assertFalse(journal._flushing)


class LauncherRecordTests(unittest.TestCase):
    """The launcher's record of its outstanding command (battle_session._persist): before a transport command it is
    replaced without an fsync of the payload or the directory; a lifecycle command's record is still fsynced."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "native-battle-execution.json"

    def test_an_unsynced_replace_writes_the_record_without_an_fsync(self):
        from emerald_multiplayer import live_checkpoint
        calls = []
        with patch.object(live_checkpoint.os, "fsync", lambda fd: calls.append(fd)):
            live_checkpoint._atomic(self.path, b"first\n", sync=False)
            live_checkpoint._atomic(self.path, b"second\n", sync=False)
            self.assertEqual(calls, [])
            self.assertEqual(self.path.read_bytes(), b"second\n")   # replaced in one step all the same
            live_checkpoint._atomic(self.path, b"third\n")
        self.assertEqual(len(calls), 2 if os.name != "nt" else 1)    # the payload and its directory (not on Windows)
        self.assertEqual(self.path.read_bytes(), b"third\n")
        self.assertEqual(sorted(p.name for p in Path(self.temp.name).iterdir()), [self.path.name])


if __name__ == "__main__":
    unittest.main()
