"""Development BIND intent/admission tests; no actual game or result settlement."""
import asyncio
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.battle_journal import (BattleJournal, BattleJournalError,
    MAX_JOURNAL_BYTES, pending_battle, read_battle_intent)
from emerald_multiplayer.battle_roster import CanonicalBattler
from emerald_multiplayer.cold_start import ColdStartError, ColdStartRecovery
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, LiveSaveError, _json_bytes
from emerald_multiplayer.live_trade import LiveTradeCoordinator
from emerald_multiplayer.native_battle import NativeBinding, NativeControl, Opcode
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.storage import Checkpoint
from process_fixture import direct_python
import test_cold_start as cold_fixture
import test_live_checkpoint as checkpoint_fixture


class BattleJournalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)/"private"
        actor, peer = str(uuid4()), str(uuid4())
        players = tuple(sorted((actor,peer)))
        local = players.index(actor)
        self.c = SimpleNamespace(connected=True, world_id=str(uuid4()), server_epoch=3,
            session_epoch=7+local, battle_incarnation=20+local, save_profile=OWNERSHIP_PROFILE,
            config=SimpleNamespace(player_id=actor, build_id="a"*64, ruleset_id="test-rules",
                ownership_enabled=True, development_battle_channel=True, battle_abi_version=2,
                server_credential=b"c"*32, trade_enabled=True),
            live_checkpoint_lock=asyncio.Lock(), _live_save_owner=None, _live_battle_owner=None)
        self.binding = NativeBinding(str(uuid4()),players,(7,8),(20,21),local)
        self.bind = NativeControl(self.c.battle_incarnation,self.c.session_epoch,str(uuid4()),1,
                                  Opcode.BIND,source_slot=local,data=self.binding.pack())
        # The real canonical parser has its own tests. This service takes its
        # immutable trusted descriptor, rather than inspecting a live party.
        self.canonical = CanonicalBattler(self.c.world_id,actor,2,"b"*64,local,3,123,1,0,bytes(600),bytes(28))
        self.head = dict(revision=2, request_id=str(uuid4()), size=131072, sha256="b"*64,
            build_id=self.c.config.build_id, ruleset_id=self.c.config.ruleset_id, save_profile=OWNERSHIP_PROFILE)
        self.rpc_calls = []
        self.head_hook = None
        async def checkpoint_rpc(operation):
            self.rpc_calls.append(operation)
            self.assertEqual(operation,"info")
            self.assertTrue(self.c.live_checkpoint_lock.locked())
            if self.head_hook is not None:
                await self.head_hook()
            return {"checkpoint":None if self.head is None else dict(self.head)}
        self.c.checkpoint_rpc = checkpoint_rpc
        self.journal = BattleJournal(self.c,self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def context(self, **changes):
        return self.journal.bind_intent(changes.get("binding",self.binding),
            changes.get("command",self.bind),changes.get("canonical",self.canonical))

    async def write(self):
        async with self.context() as intent:
            return intent

    def rewrite(self, changes, *, envelope_changes=None):
        envelope = json.loads(self.journal.path.read_bytes())
        envelope["intent"].update(changes)
        envelope["sha256"] = hashlib.sha256(_json_bytes(envelope["intent"])).hexdigest()
        envelope.update(envelope_changes or {})
        self.journal.path.write_bytes(_json_bytes(envelope))

    async def test_intent_is_durable_before_dispatch_and_context_owns_exact_task(self):
        from emerald_multiplayer import live_checkpoint
        calls = []
        original = live_checkpoint._atomic
        def atomic(path,data):
            calls.append(path.name)
            original(path,data)
        with patch.object(live_checkpoint,"_atomic",side_effect=atomic):
            async with self.context() as intent:
                self.assertEqual(read_battle_intent(self.journal.path),intent)
                self.assertEqual(intent.bind,self.bind)
                self.assertEqual(intent.generation,self.binding.generation)
                self.assertEqual((intent.server_epoch,intent.lease_epoch,intent.incarnation),(3,self.c.session_epoch,self.c.battle_incarnation))
                self.assertEqual((intent.canonical_revision,intent.canonical_sha256),(2,"b"*64))
                self.assertTrue(self.c.live_checkpoint_lock.locked())
                self.assertIs(self.c._live_save_owner,asyncio.current_task())
                self.assertIs(self.c._live_battle_owner,asyncio.current_task())
                self.assertTrue(calls)
                self.assertTrue(pending_battle(self.c))
        self.assertIsNone(self.c._live_save_owner);self.assertIsNone(self.c._live_battle_owner)
        self.assertFalse(self.c.live_checkpoint_lock.locked())
        self.assertTrue(self.journal.path.is_file())
        self.assertNotIn("bind",repr(intent))

    async def test_uncertain_bind_and_cancel_leave_exact_intent_without_auto_release(self):
        with self.assertRaises(asyncio.TimeoutError):
            async with self.context():
                raise asyncio.TimeoutError("lost BIND reply")
        original = self.journal.path.read_bytes()
        entered = asyncio.Event()
        async def interrupted():
            async with self.context():
                entered.set();await asyncio.Event().wait()
        task = asyncio.create_task(interrupted())
        await entered.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(self.journal.path.read_bytes(),original)
        self.assertIsNone(self.c._live_battle_owner)
        self.assertFalse(self.c.live_checkpoint_lock.locked())

    async def test_exact_retry_is_immutable_and_changed_bind_or_revision_conflicts(self):
        first = await self.write();raw = self.journal.path.read_bytes()
        self.assertEqual(await self.write(),first)
        for changes in ({"command":replace(self.bind,battle_id=str(uuid4()))},
                        {"command":replace(self.bind,sequence=2)},
                        {"canonical":replace(self.canonical,revision=3)}):
            with self.subTest(changes=changes),self.assertRaises(BattleJournalError) as caught:
                async with self.context(**changes):self.fail("changed intent dispatched")
            self.assertEqual(caught.exception.code,"battle_intent_conflict")
            self.assertEqual(self.journal.path.read_bytes(),raw)

    async def test_head_is_authenticated_and_exact_before_first_publication(self):
        good = dict(self.head)
        cases = (None,{**good,"revision":3},{**good,"sha256":"c"*64},
            {**good,"build_id":"d"*64},{**good,"ruleset_id":"other"},
            {**good,"save_profile":"legacy"},{**good,"revision":True},{**good,"extra":1})
        for head in cases:
            with self.subTest(head=head):
                self.head = head
                with self.assertRaises(BattleJournalError) as caught:
                    async with self.context():self.fail("stale or incompatible head dispatched")
                self.assertEqual(caught.exception.code,"canonical_head_mismatch")
                self.assertFalse(self.journal.path.exists())
        self.head = good
        await self.write()
        self.assertEqual(self.rpc_calls,["info"]*(len(cases)+1))

    async def test_exact_retry_rechecks_current_head_and_retains_intent_on_timeout(self):
        await self.write();raw = self.journal.path.read_bytes()
        self.head["revision"] += 1
        with self.assertRaises(BattleJournalError) as caught:
            async with self.context():self.fail("historical exact BIND replay dispatched")
        self.assertEqual(caught.exception.code,"canonical_head_mismatch")
        self.assertEqual(self.journal.path.read_bytes(),raw)
        async def timeout():raise asyncio.TimeoutError("authoritative head unavailable")
        self.head_hook = timeout
        with self.assertRaises(asyncio.TimeoutError):
            async with self.context():self.fail("timeout treated as current head")
        self.assertEqual(self.journal.path.read_bytes(),raw)
        self.assertIsNone(self.c._live_battle_owner)

    async def test_session_or_pending_recovery_changed_during_head_query_blocks_publication(self):
        for name,value in (("world_id",str(uuid4())),("session_epoch",30),("server_epoch",4),
                           ("battle_incarnation",40)):
            old = getattr(self.c,name)
            async def mutate():setattr(self.c,name,value)
            self.head_hook = mutate
            with self.subTest(name=name),self.assertRaises(BattleJournalError) as caught:
                async with self.context():self.fail("changed authenticated actor dispatched")
            self.assertEqual(caught.exception.code,"battle_recovery_required")
            setattr(self.c,name,old)
            self.assertFalse(self.journal.path.exists())
        pending = self.directory/"pending-export.json"
        async def add_recovery():pending.write_bytes(b"uncertain export")
        self.head_hook = add_recovery
        with self.assertRaises(BattleJournalError) as caught:
            async with self.context():self.fail("recovery created during await ignored")
        self.assertEqual(caught.exception.code,"character_recovery_pending")
        self.assertFalse(self.journal.path.exists())

    async def test_publication_or_directory_sync_failure_never_yields_bind(self):
        with patch("emerald_multiplayer.battle_journal.os.link",side_effect=OSError("publication failed")):
            with self.assertRaises(OSError):
                async with self.context():self.fail("unpublished intent dispatched")
        self.assertFalse(self.journal.path.exists())
        # Fail after the final link was created, rather than during _atomic's
        # staging-directory sync. The durable uncertain intent must remain.
        with patch("emerald_multiplayer.live_checkpoint._sync_directory",side_effect=[None,OSError("sync failed")]):
            with self.assertRaises(OSError):
                async with self.context():self.fail("unsynced intent dispatched")
        self.assertTrue(self.journal.path.exists())
        self.assertIsNone(self.c._live_battle_owner)

    async def test_malformed_oversize_duplicate_or_bad_digest_intent_is_never_replaced(self):
        await self.write();good = self.journal.path.read_bytes()
        cases = (b"{}",b"x"*(MAX_JOURNAL_BYTES+1),good.replace(b'"format":',b'"format":"duplicate","format":',1),
                 good.replace(b'"sha256":"',b'"sha256":"0',1),b'{"x":NaN}')
        for raw in cases:
            with self.subTest(raw=raw[:60]):
                self.journal.path.write_bytes(raw)
                with self.assertRaises(BattleJournalError):
                    async with self.context():self.fail("unverified intent dispatched")
                self.assertEqual(self.journal.path.read_bytes(),raw)
                self.assertTrue(pending_battle(self.c))

    async def test_strict_fields_counters_uuid_profile_and_exact_bind_are_validated(self):
        await self.write();good = self.journal.path.read_bytes()
        cases = ({"schema":True},{"server_epoch":False},{"lease_epoch":0},{"incarnation":2**32},
            {"canonical_revision":0},{"canonical_sha256":"B"*64},{"world_id":str(uuid4()).upper()},
            {"player_id":str(uuid4())},{"save_profile":"legacy"},{"extra":1},{"bind_b64":"bad"})
        for changes in cases:
            with self.subTest(changes=changes):
                self.journal.path.write_bytes(good);self.rewrite(changes)
                with self.assertRaises(BattleJournalError):read_battle_intent(self.journal.path)

    async def test_changed_world_epoch_lease_incarnation_or_process_requires_recovery(self):
        await self.write();raw = self.journal.path.read_bytes()
        for name,value in (("world_id",str(uuid4())),("server_epoch",4),("session_epoch",30),
                           ("battle_incarnation",40),("_live_battle_runtime_id",str(uuid4()))):
            before = getattr(self.c,name);setattr(self.c,name,value)
            with self.subTest(name=name),self.assertRaises(BattleJournalError) as caught:self.journal.load()
            self.assertEqual(caught.exception.code,"battle_recovery_required")
            setattr(self.c,name,before)
            self.assertEqual(self.journal.path.read_bytes(),raw)
        replacement = SimpleNamespace(**vars(self.c));replacement._live_battle_runtime_id = None
        with self.assertRaises(BattleJournalError):BattleJournal(replacement,self.directory).load()
        self.assertEqual(self.journal.path.read_bytes(),raw)

    async def test_pending_export_trade_or_other_directory_blocks_new_admission(self):
        for name in ("pending-export.json","pending-trade.json"):
            pending = self.directory/name;pending.write_bytes(b"malformed recovery")
            with self.assertRaises(BattleJournalError) as caught:
                async with self.context():self.fail("overlapping hold dispatched")
            self.assertEqual(caught.exception.code,"character_recovery_pending")
            pending.unlink()
        await self.write()
        with self.assertRaises(BattleJournalError):BattleJournal(self.c,self.directory/"other")
        with self.assertRaises(ColdStartError):ColdStartRecovery(self.c,self.directory/"other",self.directory/"player.sav")

    async def test_registered_export_in_other_directory_cannot_be_bypassed_or_replaced(self):
        export = LiveCheckpointCoordinator(self.c,self.directory/"save-recovery")
        export.pending_path.write_bytes(b"immutable uncertain export")
        with self.assertRaises(BattleJournalError) as caught:
            async with self.context():self.fail("known foreign-directory export ignored")
        self.assertEqual(caught.exception.code,"character_recovery_pending")
        self.assertFalse(self.rpc_calls)
        with self.assertRaises(LiveSaveError) as caught:LiveCheckpointCoordinator(self.c,self.directory/"other")
        self.assertEqual(caught.exception.code,"pending_export")
        with self.assertRaises(ColdStartError) as caught:ColdStartRecovery(self.c,self.directory/"other",self.directory/"player.sav")
        self.assertEqual(caught.exception.code,"pending_export")
        self.assertEqual(self.c._live_export_pending_path,export.pending_path)
        self.assertEqual(export.pending_path.read_bytes(),b"immutable uncertain export")

    async def test_dangling_symlink_directory_and_unreadable_path_fence_admission(self):
        self.journal.path.mkdir()
        self.assertTrue(pending_battle(self.c))
        with self.assertRaises(BattleJournalError):
            async with self.context():self.fail("directory accepted as absent intent")
        self.journal.path.rmdir()
        # A filesystem-independent lstat error tests fail-closed permission
        # handling even under root/admin accounts which bypass normal modes.
        with patch("emerald_multiplayer.battle_journal.Path.lstat",side_effect=PermissionError("denied")):
            with self.assertRaises(BattleJournalError):pending_battle(self.c)
        if os.name != "nt":
            os.mkfifo(self.journal.path)
            self.assertTrue(pending_battle(self.c))
            with self.assertRaises(BattleJournalError):read_battle_intent(self.journal.path)
            self.journal.path.unlink()
            self.journal.path.symlink_to(self.directory/"missing-target")
            self.assertTrue(pending_battle(self.c))
            with self.assertRaises(BattleJournalError):
                async with self.context():self.fail("dangling intent dispatched")
            self.assertTrue(self.journal.path.is_symlink())

    async def test_session_changed_while_waiting_for_lock_cannot_publish_old_bind(self):
        await self.c.live_checkpoint_lock.acquire()
        async def waiter():
            async with self.context():self.fail("old session dispatched")
        task = asyncio.create_task(waiter());await asyncio.sleep(0)
        self.c.session_epoch += 20;self.c.live_checkpoint_lock.release()
        with self.assertRaises(BattleJournalError):await task
        self.assertFalse(self.journal.path.exists())

    async def test_development_capability_and_exact_local_actor_are_required(self):
        for name,value in (("development_battle_channel",False),("battle_abi_version",1),
                           ("server_credential",None),("ownership_enabled",False)):
            old = getattr(self.c.config,name);setattr(self.c.config,name,value)
            with self.subTest(name=name),self.assertRaises(BattleJournalError):
                async with self.context():self.fail("unsupported admission")
            setattr(self.c.config,name,old)
        with self.assertRaises(BattleJournalError):
            async with self.context(canonical=replace(self.canonical,player_id=str(uuid4()))):self.fail("foreign actor")
        self.assertFalse(self.journal.path.exists())

    async def test_real_process_crash_after_intent_keeps_exact_bind_and_no_settlement(self):
        settings = self.directory/"child.json"
        self.directory.mkdir(exist_ok=True)
        settings.write_bytes(_json_bytes(dict(
            config={**vars(self.c.config),"server_credential":self.c.config.server_credential.hex()},
            companion={key:getattr(self.c,key) for key in ("connected","world_id","server_epoch","session_epoch","battle_incarnation","save_profile","_live_battle_runtime_id")},
            head=self.head,
            canonical={**asdict(self.canonical),"party":self.canonical.party.hex(),"trainer_descriptor":self.canonical.trainer_descriptor.hex()},
            binding=self.binding.pack().hex(),bind=self.bind.pack().hex())))
        code = """import asyncio,json,os,sys
from pathlib import Path
from types import SimpleNamespace
from emerald_multiplayer.battle_journal import BattleJournal
from emerald_multiplayer.battle_roster import CanonicalBattler
from emerald_multiplayer.native_battle import NativeBinding,NativeControl
data=json.loads(Path(sys.argv[1]).read_bytes())
data['config']['server_credential']=bytes.fromhex(data['config']['server_credential'])
c=SimpleNamespace(**data['companion'],config=SimpleNamespace(**data['config']),live_checkpoint_lock=asyncio.Lock(),_live_save_owner=None)
async def checkpoint_rpc(operation):
    assert operation=='info'
    return {'checkpoint':data['head']}
c.checkpoint_rpc=checkpoint_rpc
data['canonical']['party']=bytes.fromhex(data['canonical']['party'])
data['canonical']['trainer_descriptor']=bytes.fromhex(data['canonical']['trainer_descriptor'])
async def run():
    j=BattleJournal(c,Path(sys.argv[1]).parent)
    async with j.bind_intent(NativeBinding.unpack(bytes.fromhex(data['binding'])),NativeControl.unpack(bytes.fromhex(data['bind'])),CanonicalBattler(**data['canonical'])):
        print(f'ready:{os.getpid()}',flush=True)
        await asyncio.sleep(3600)
asyncio.run(run())
"""
        child = subprocess.Popen([direct_python(),"-u","-c",code,str(settings)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),f"ready:{child.pid}")
            raw = self.journal.path.read_bytes()
            child.kill();child.wait(timeout=5)
            self.assertNotEqual(child.returncode,0)
            self.assertEqual(read_battle_intent(self.journal.path).bind,self.bind)
            self.assertEqual(self.journal.path.read_bytes(),raw)
            self.assertTrue(pending_battle(self.c))
        finally:
            if child.poll() is None:child.kill();child.wait(timeout=5)
            child.stdout.close();child.stderr.close()


class BattleAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.private = self.root/"private";self.private.mkdir()
        self.pending = self.private/"pending-battle.json";self.pending.write_bytes(b"{}")

    def tearDown(self):self.temp.cleanup()

    async def test_all_ordinary_checkpoint_paths_and_trade_intent_creation_refuse_before_rpc(self):
        c = checkpoint_fixture.FakeCompanion(self.root)
        try:
            checkpoint = LiveCheckpointCoordinator(c,self.private)
            trade = LiveTradeCoordinator(c,self.private)
            for operation in (lambda:checkpoint.checkpoint(expected_revision=1),checkpoint.enroll,
                              checkpoint.resolve_pending,checkpoint.recover,
                              lambda:trade.prepare(str(uuid4()),str(uuid4()),expected_revision=1)):
                with self.subTest(operation=operation),self.assertRaises(LiveSaveError) as caught:await operation()
                self.assertEqual(caught.exception.code,"pending_battle")
            self.assertFalse(c.commands);self.assertFalse(c.server_calls)
            self.assertFalse(trade.trade_path.exists())
            self.assertEqual(self.pending.read_bytes(),b"{}")
        finally:c.close()

    async def test_registered_foreign_directory_intent_fences_live_wrappers(self):
        c = checkpoint_fixture.FakeCompanion(self.root)
        c._live_battle_pending_path = self.pending
        try:
            coordinator = LiveCheckpointCoordinator(c,self.root/"different")
            with self.assertRaises(LiveSaveError) as caught:await coordinator.checkpoint(expected_revision=1)
            self.assertEqual(caught.exception.code,"pending_battle")
            self.assertFalse(c.commands);self.assertFalse(c.server_calls)
        finally:c.close()

    async def test_cold_start_refuses_before_rpc_save_archive_ack_or_intent_delete(self):
        c = cold_fixture.ClosedCompanion(self.root)
        save = self.root/"player.sav";save.write_bytes(b"original closed save")
        try:
            gate = ColdStartRecovery(c,self.private,save)
            with self.assertRaises(ColdStartError) as caught:
                async with gate.open():self.fail("pending battle must not launch")
            self.assertEqual(caught.exception.code,"pending_battle")
            self.assertEqual(save.read_bytes(),b"original closed save")
            self.assertEqual(self.pending.read_bytes(),b"{}")
            self.assertFalse(c.server_calls);self.assertFalse(c.commands)
            self.assertFalse(c._cold_start_active);self.assertFalse(c._bridge_admission_blocked)
            self.assertFalse(c.live_checkpoint_lock.locked())
        finally:c.close()


if __name__ == "__main__":unittest.main()
