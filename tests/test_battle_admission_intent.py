"""Original provisional metadata/durable publication; no native game claim."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.battle_admission_intent import (
    BattleAdmissionIntent, FILENAME, FORMAT, MAX_JOURNAL_BYTES,
    create_admission_intent, publish_admission_intent, read_admission_intent,
)
from emerald_multiplayer.battle_execution_protocol import encode_control
from emerald_multiplayer.battle_journal import BattleJournalError
from emerald_multiplayer.battle_protocol import SCOPE
from emerald_multiplayer.battle_roster import CanonicalBattler
from emerald_multiplayer.live_checkpoint import _json_bytes
from emerald_multiplayer.native_battle import Opcode
from emerald_multiplayer.native_battle_resume import Admission
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE


class BattleAdmissionIntentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory/FILENAME
        players = sorted(str(uuid4()) for _ in range(4))
        self.c = SimpleNamespace(connected=True, world_id=str(uuid4()), server_epoch=3,
            session_epoch=7, battle_incarnation=20, save_profile=OWNERSHIP_PROFILE,
            _live_battle_runtime_id=str(uuid4()),
            _bridge=SimpleNamespace(incarnation=20, battle_capable=True),
            config=SimpleNamespace(player_id=players[0], build_id='a'*64, ruleset_id='gen6',
                battle_abi_version=3, battle_resume_abi_version=1, ownership_enabled=True,
                development_battle_channel=True, server_credential=b's'*32))
        self.challenge = dict(scope=SCOPE, battle_id=str(uuid4()), generation=str(uuid4()),
            sender=players[0], mode=3, state='accepted', reason=None, players=players,
            fingerprint='b'*64, consent=list(players), outcome=None,
            checkpoints=[dict(player_id=actor, source_slot=i, revision=2,
                sha256=hashlib.sha256(actor.encode()).hexdigest(), party_count=6) for i, actor in enumerate(players)])
        self.canonical = CanonicalBattler(self.c.world_id, players[0], 2,
            self.challenge['checkpoints'][0]['sha256'], 0, 3, 123, 6, 0, bytes(600), bytes(28), mode=3)
        self.intent = create_admission_intent(self.c, self.challenge, self.canonical)

    def envelope(self, value):
        return _json_bytes(dict(format=FORMAT, intent=value,
            sha256=hashlib.sha256(_json_bytes(value)).hexdigest()))

    def test_pure_candidate_pins_exact_native_identity_and_detaches_mutable_consent(self):
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assertEqual(self.intent.battle_id, self.challenge['battle_id'])
        self.assertEqual(self.intent.generation, self.challenge['generation'])
        self.assertEqual(self.intent.admit.opcode, Opcode.ADMIT)
        self.assertEqual(self.intent.admit.sequence, 1)
        self.assertEqual(Admission.unpack(self.intent.admit.data),
            Admission(self.intent.generation, self.c.config.player_id, self.c._live_battle_runtime_id))
        fresh = self.intent.challenge
        fresh['players'].reverse();fresh['checkpoints'][0]['revision']=99
        self.challenge['consent'].clear()
        self.assertEqual(len(self.intent.challenge['consent']), 4)
        self.assertEqual(self.intent.challenge['checkpoints'][0]['revision'], 2)
        with self.assertRaises(FrozenInstanceError):self.intent.lease_epoch=8
        self.assertEqual(BattleAdmissionIntent.from_value(self.intent.value()),self.intent)

    def test_candidate_refuses_changed_session_capability_and_original_core(self):
        cases = ((self.c,'connected',False), (self.c,'battle_incarnation',21),
            (self.c,'_live_battle_runtime_id',None), (self.c,'save_profile','legacy'),
            (self.c.config,'battle_abi_version',2), (self.c.config,'battle_resume_abi_version',True),
            (self.c.config,'battle_resume_abi_version',0), (self.c.config,'ownership_enabled',False),
            (self.c.config,'development_battle_channel',False), (self.c.config,'server_credential',b's'*31),
            (self.c._bridge,'battle_capable',False))
        for target, field, bad in cases:
            previous=getattr(target,field)
            try:
                setattr(target,field,bad)
                with self.subTest(field=field,bad=bad),self.assertRaises(BattleJournalError):
                    create_admission_intent(self.c,self.challenge,self.canonical)
            finally:setattr(target,field,previous)
        for canonical in (replace(self.canonical,revision=3),replace(self.canonical,party_count=5),
                          replace(self.canonical,world_id=str(uuid4())),replace(self.canonical,mode=2)):
            with self.assertRaises(BattleJournalError):create_admission_intent(self.c,self.challenge,canonical)
        self.assertFalse(self.path.exists())

    def test_constructor_and_parser_refuse_boolean_counters_foreign_control_and_mutable_bytes(self):
        for field,bad in (('server_epoch',True),('lease_epoch',0),('incarnation',2**32),
            ('canonical_revision',False),('canonical_sha256','A'*64),('world_id','0'*36),
            ('challenge_bytes',bytearray(self.intent.challenge_bytes))):
            with self.subTest(field=field),self.assertRaises(BattleJournalError):replace(self.intent,**{field:bad})
        for command in (replace(self.intent.admit,sequence=2), replace(self.intent.admit,session_epoch=8),
            replace(self.intent.admit,incarnation=21), replace(self.intent.admit,source_slot=1),
            replace(self.intent.admit,opcode=Opcode.QUERY,data=b''),
            replace(self.intent.admit,data=Admission(self.intent.generation,self.intent.player_id,str(uuid4())).pack())):
            with self.subTest(command=command.opcode),self.assertRaises(BattleJournalError):
                BattleAdmissionIntent.from_value({**self.intent.value(),'admit_b64':encode_control(command)})

    def test_partial_consent_and_changed_canonical_descriptor_are_rejected(self):
        changes = ({'state':'invited'},{'consent':self.challenge['players'][:3]}, {'outcome':1},
            {'players':[self.challenge['players'][0]]*4})
        for change in changes:
            value=self.intent.value();value['challenge'].update(change)
            with self.subTest(change=change),self.assertRaises(BattleJournalError):BattleAdmissionIntent.from_value(value)
        value=self.intent.value();value['challenge']['checkpoints'][0]['sha256']='f'*64
        with self.assertRaises(BattleJournalError):BattleAdmissionIntent.from_value(value)

    def test_exclusive_publication_is_durable_and_exact_retry_preserves_original_bytes(self):
        from emerald_multiplayer import battle_admission_intent as module
        with patch.object(module,'_sync_directory',wraps=module._sync_directory) as sync:
            self.assertEqual(publish_admission_intent(self.path,self.intent),self.intent)
            sync.assert_called_once_with(self.directory)
        original=self.path.read_bytes();before=self.path.stat().st_mtime_ns
        with patch.object(module,'_atomic',side_effect=AssertionError('exact retry must not replace intent')):
            self.assertEqual(publish_admission_intent(self.path,self.intent),self.intent)
        self.assertEqual(self.path.read_bytes(),original)
        self.assertEqual(self.path.stat().st_mtime_ns,before)
        self.assertEqual(read_admission_intent(self.path),self.intent)
        self.assertNotIn(self.c.config.server_credential.hex().encode(),original)
        self.assertEqual(list(self.directory.iterdir()),[self.path])

    def test_conflicting_and_racing_publications_never_replace_the_winner(self):
        from emerald_multiplayer import battle_admission_intent as module
        competitor=replace(self.intent,server_epoch=4)
        competing_bytes=self.envelope(competitor.value())
        def raced_link(source,destination):
            destination.write_bytes(competing_bytes)
            raise FileExistsError()
        with patch.object(module.os,'link',side_effect=raced_link),self.assertRaises(BattleJournalError) as caught:
            publish_admission_intent(self.path,self.intent)
        self.assertEqual(caught.exception.code,'battle_admission_conflict')
        self.assertEqual(self.path.read_bytes(),competing_bytes)
        self.assertEqual(list(self.directory.iterdir()),[self.path])
        with self.assertRaises(BattleJournalError):publish_admission_intent(self.path,self.intent)
        self.assertEqual(self.path.read_bytes(),competing_bytes)

    def test_failed_durable_publication_never_reports_success_and_retains_published_intent(self):
        from emerald_multiplayer import battle_admission_intent as module
        with patch.object(module,'_sync_directory',side_effect=OSError('directory sync failed')):
            with self.assertRaises(OSError):publish_admission_intent(self.path,self.intent)
        self.assertEqual(read_admission_intent(self.path),self.intent)
        self.assertEqual(list(self.directory.iterdir()),[self.path])
        with patch.object(module,'_sync_directory',wraps=module._sync_directory) as sync:
            self.assertEqual(publish_admission_intent(self.path,self.intent),self.intent)
            sync.assert_called_once_with(self.directory)

    def test_reader_refuses_corruption_duplicates_unknown_fields_nonregular_and_oversize(self):
        valid=self.envelope(self.intent.value())
        envelope=json.loads(valid)
        malformed = (b'{}',valid+b' ',valid.replace(b'"schema":1',b'"schema":1,"schema":1'),
            _json_bytes({**envelope,'sha256':'0'*64}),_json_bytes({**envelope,'extra':1}),
            b' '* (MAX_JOURNAL_BYTES+1),valid.replace(b'"server_epoch":3',b'"server_epoch":NaN'))
        for raw in malformed:
            self.path.write_bytes(raw)
            with self.subTest(size=len(raw)),self.assertRaises(BattleJournalError):read_admission_intent(self.path)
            self.assertEqual(self.path.read_bytes(),raw)
        self.path.unlink();self.path.mkdir()
        with self.assertRaises(BattleJournalError):read_admission_intent(self.path)
        with self.assertRaises(BattleJournalError):publish_admission_intent(self.path,self.intent)


if __name__ == '__main__':
    unittest.main()
