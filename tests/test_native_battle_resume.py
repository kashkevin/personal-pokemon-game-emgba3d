from dataclasses import replace
import json
import struct
import tempfile
from pathlib import Path
import unittest

from emerald_multiplayer.battle_execution_journal import RouteJournal
from emerald_multiplayer.battle_journal import BattleJournalError
from emerald_multiplayer.battle_mailbox import BattleMailboxError
from emerald_multiplayer.native_battle import NativeBinding, NativeControl, NativeQuery, Opcode
from emerald_multiplayer.native_battle_resume import Admission, Retirement, ResumeAuthorization, ResumeQuery
from test_native_battle import binding, control, query


class NativeResumeCodecTests(unittest.TestCase):
    def test_provisional_hold_cannot_claim_blocks_or_exhausted_ordinary_sequence(self):
        b = binding()
        admission = Admission(b.generation, b.players[0], b.players[1])
        request = control(opcode=Opcode.ADMIT, data=admission.pack())
        request.validate_command(player_id=b.players[0])
        raw = query(flags=129, seq=0, remaining=0)
        self.assertTrue(NativeQuery.unpack(raw).provisional)
        replace(request, data=raw).validate_response(request)
        for bad in (query(flags=129, seq=0xFFFFFFFF, remaining=0), query(flags=129, seq=0),
                    query(flags=131, seq=0, remaining=0), query(flags=129, seq=0, remaining=1)):
            with self.assertRaises(BattleMailboxError):
                NativeQuery.unpack(bad)
        with self.assertRaises(BattleMailboxError):
            request.validate_command(player_id=b.players[1])

    def test_terminal_retirement_and_handoff_preserve_exact_original_release_tuple(self):
        retired = Retirement(binding().generation, 27, 0x12345678, 2)
        self.assertEqual(Retirement.unpack(retired.pack()), retired)
        for opcode in (Opcode.RETIRE, Opcode.HANDOFF):
            request = control(opcode=opcode, data=retired.pack())
            request.validate_command()
            request.validate_response(request)
            with self.assertRaises(BattleMailboxError):
                replace(request, data=replace(retired, release_sequence=28).pack()).validate_response(request)
        for flags, name in ((257, "terminal_waiting"), (513, "handoff_waiting")):
            observed = NativeQuery.unpack(query(flags=flags, seq=27, remaining=0))
            self.assertTrue(observed.held)
            self.assertTrue(getattr(observed, name))
        with self.assertRaises(BattleMailboxError):
            NativeQuery.unpack(query(flags=769, seq=27, remaining=0))

    def test_renewal_preserves_original_cores_and_validates_exact_native_receipt(self):
        original = replace(binding(), resumable=True)
        updated = replace(original, leases=(17, 18))
        self.assertEqual(NativeBinding.unpack(original.pack()), original)
        renewal = ResumeAuthorization(updated, b"q"*16, 2, 57)
        self.assertEqual(ResumeAuthorization.unpack(renewal.pack()), renewal)
        renewal.validate_previous(original)
        request = control(session_epoch=17, sequence=58, opcode=Opcode.REAUTHORIZE, data=renewal.pack())
        request.validate_command(binding=updated, player_id=updated.players[0])
        raw = query(flags=1|2|64, seq=57, remaining=0) + struct.pack("<II", 9|256|(2<<16), 2) + b"q"*16
        result = ResumeQuery.unpack(raw)
        self.assertTrue(result.suspended)
        replace(request, data=raw).validate_response(request)
        for changed in (replace(updated, players=tuple(reversed(updated.players))),
                        replace(updated, incarnations=(20, 22)), replace(updated, leases=(6, 18)),
                        replace(updated, resumable=False)):
            with self.subTest(changed=changed), self.assertRaises(BattleMailboxError):
                replace(renewal, binding=changed).validate_previous(original)
        for changed in (raw[:72] + b"x"*16, raw[:68] + struct.pack("<I", 3) + raw[72:]):
            with self.assertRaises(BattleMailboxError):
                replace(request, data=changed).validate_response(request)

    def test_suspend_state_cannot_be_reported_as_a_successful_resume(self):
        request = control(sequence=58, opcode=Opcode.RESUME, data=b"q"*16+struct.pack("<I", 2))
        request.validate_command()
        raw = query(flags=1|2|64, seq=57, remaining=0)+struct.pack("<II", 9|256|(2<<16), 2)+b"q"*16
        with self.assertRaises(BattleMailboxError):
            replace(request, data=raw).validate_response(request)
        active = query(seq=57)+struct.pack("<II", 2|256|(2<<16), 2)+b"q"*16
        replace(request, data=active).validate_response(request)
        for payload in (bytes(140), b"x"*139, b"x"*141):
            with self.assertRaises(BattleMailboxError):
                ResumeAuthorization.unpack(payload)


class RouteJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"route.jsonl"
        bound = binding()
        self.actor = bound.players[0]
        self.header = dict(players=list(bound.players), leases=list(bound.leases),
            incarnations=list(bound.incarnations), battle_id=control().battle_id, mode=2)

    def test_reload_keeps_exact_uncertain_dispatch_and_rejects_changed_or_skipped_reply(self):
        journal = RouteJournal(self.path, self.header, create=True)
        request = control()
        journal.append("command", self.actor, 1, request)
        recovered = RouteJournal(self.path, self.header)
        self.assertEqual(recovered.pending, {self.actor: (1, request)})
        with self.assertRaises(ValueError):
            recovered.append("command", self.actor, 2, replace(request, sequence=2))
        reply = replace(request, data=query())
        with self.assertRaises(ValueError):
            recovered.append("response", self.actor, 2, reply)
        recovered.append("response", self.actor, 1, reply)
        complete = RouteJournal(self.path, self.header)
        self.assertEqual(complete.pending, {})
        self.assertEqual(complete.events, recovered.events)
        self.assertEqual(complete.digest, recovered.digest)

    def test_truncated_reordered_changed_or_foreign_history_never_reconstructs(self):
        journal = RouteJournal(self.path, self.header, create=True)
        journal.append("command", self.actor, 1, control())
        original = self.path.read_bytes()
        lines = original.splitlines(keepends=True)
        for broken in (original[:-1], original[:-8], lines[1]+lines[0], original.replace(b'"command"', b'"response"')):
            self.path.write_bytes(broken)
            with self.assertRaises(BattleJournalError):
                RouteJournal(self.path, self.header)
        self.path.write_bytes(original)
        with self.assertRaises(BattleJournalError):
            RouteJournal(self.path, dict(self.header, mode=3))
        self.path.write_bytes(original+b"incomplete")
        with self.assertRaises(BattleJournalError):
            journal.append("response", self.actor, 1, replace(control(), data=query()))

    def test_live_owner_refuses_same_size_replacement_or_changed_bytes_before_append(self):
        for replacement in (False, True):
            with self.subTest(replacement=replacement):
                path = self.path.with_name("replacement.jsonl" if replacement else "changed.jsonl")
                journal = RouteJournal(path, self.header, create=True)
                journal.append("command", self.actor, 1, control())
                raw = path.read_bytes()
                if replacement:
                    other = path.with_suffix(".tmp")
                    other.write_bytes(raw)
                    other.replace(path)
                else:
                    changed = raw.replace(b'"command"', b'"commanz"')
                    self.assertEqual(len(changed), len(raw))
                    self.assertNotEqual(changed, raw)
                    path.write_bytes(changed)
                with self.assertRaises(BattleJournalError):
                    journal.append("response", self.actor, 1, replace(control(), data=query()))
