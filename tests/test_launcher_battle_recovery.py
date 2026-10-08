"""Launcher authority adoption and explicit UI recovery; no native gameplay claim."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
from pathlib import Path
import queue
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from emerald_multiplayer.battle_journal import BattleIntent, FORMAT
from emerald_multiplayer.battle_session import BattleCompletion, RenewedBattleSession
from emerald_multiplayer.launcher_session import GameInstallation, LauncherSession, LauncherSessionError, SessionState, SessionStatus
from emerald_multiplayer.launcher_gui import LauncherWindow, LaunchRequest, SessionWorker, UiEvent, status_text
from emerald_multiplayer.live_checkpoint import _json_bytes
from emerald_multiplayer.native_battle import NativeBinding, NativeControl, Opcode
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from test_launcher_gui import ControlledSession


class LauncherBattleRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        installation = GameInstallation(self.root/'game.gba', self.root/'manifest.json', 'a'*64, 'b'*64, None)
        self.session = s = LauncherSession(installation, self.root,
            world_directory=self.root/'world', bind_address='127.0.0.1')
        actor, peer = sorted((str(uuid4()), str(uuid4())))
        bridge = SimpleNamespace(incarnation=20, battle_capable=True, save_capable=True)
        self.c = c = SimpleNamespace(connected=True, world_id=str(uuid4()), server_epoch=3,
            session_epoch=7, save_profile=OWNERSHIP_PROFILE, save_incarnation=20, battle_incarnation=20, _bridge=bridge,
            config=SimpleNamespace(player_id=actor, build_id='a'*64, ruleset_id='rules',
                battle_resume_abi_version=1, emergency_save_abi_version=2, battle_abi_version=3,
                development_battle_channel=True, ownership_enabled=True, server_credential=b's'*32),
            _live_battle_runtime_id=str(uuid4()), _live_battle_owner=None, _live_save_owner=None, _reconnect_blocked=True)
        c._live_binding=(c.world_id,c.session_epoch,c.battle_incarnation)
        s._companion = c
        s._binding = s._signature()
        self.original_binding = s._binding
        s._profile_directory = self.root/'profile'; s._profile_directory.mkdir()
        s._runtime = object()
        s._game = SimpleNamespace(process=SimpleNamespace(returncode=None))
        s._open = s._save_failed = True
        s._revision = 2; s._save_incarnation = 20
        s._manifest = {'battle_resume_abi_version':1, 'emergency_save_abi_version':2}
        s._autosave_clock = lambda: 100
        native = NativeBinding(str(uuid4()), (actor, peer), (7,8), (20,21), 0, resumable=True)
        bind = NativeControl(20, 7, str(uuid4()), 1, Opcode.BIND, data=native.pack())
        self.intent = BattleIntent(c.world_id, actor, c.config.build_id, c.config.ruleset_id,
            OWNERSHIP_PROFILE, 3, 7, 20, c._live_battle_runtime_id, native.generation,
            bind.battle_id, 2, 'c'*64, bind)
        self.path = s._profile_directory/'pending-battle.json'
        s._battle_retained = (s._game,s._runtime,bridge,self.intent.battle_id,self.intent.generation,
                             2,'c'*64,20,self.intent.runtime_id)
        self.write_intent(self.intent)
        self.original_bytes = self.path.read_bytes()
        lost = asyncio.Event(); lost.set()
        self.old_emergency = SimpleNamespace(session=(c.world_id,7,20), bridge=bridge,
            task=object(), result=SimpleNamespace(state='battle_waiting',can_close=False), lost=lost)
        async def retire(*args):
            self.assertIs(s._emergency, self.old_emergency)
            self.assertEqual(s._binding, self.original_binding)
            self.assertTrue(s._save_failed)
            self.assertEqual(args[1:], (self.intent, bridge))
            c._emergency_controller = None
        self.old_emergency.retire_after_battle_recovery = AsyncMock(side_effect=retire)
        c._emergency_controller = s._emergency = self.old_emergency
        c.connected = False

    def write_intent(self, intent):
        value = intent.value()
        self.path.write_bytes(_json_bytes(dict(format=FORMAT,intent=value,
            sha256=hashlib.sha256(_json_bytes(value)).hexdigest())))

    def provisional(self, *, publish=True):
        from emerald_multiplayer.battle_admission_intent import BattleAdmissionIntent, FILENAME, publish_admission_intent
        from emerald_multiplayer.battle_protocol import SCOPE
        from emerald_multiplayer.native_battle_resume import Admission
        i = self.intent
        bound = NativeBinding.unpack(i.bind.data)
        challenge = dict(scope=SCOPE,battle_id=i.battle_id,generation=i.generation,
            sender=i.player_id,mode=bound.mode,state='accepted',reason=None,
            players=list(bound.players),fingerprint='b'*64,consent=list(bound.players),outcome=None,
            checkpoints=[dict(player_id=actor,source_slot=slot,revision=2,sha256='c'*64,party_count=1)
                         for slot,actor in enumerate(bound.players)])
        admission = BattleAdmissionIntent(i.world_id,i.player_id,i.build_id,i.ruleset_id,i.save_profile,
            i.server_epoch,i.lease_epoch,i.incarnation,i.runtime_id,i.canonical_revision,i.canonical_sha256,
            _json_bytes(challenge),NativeControl(i.incarnation,i.lease_epoch,i.battle_id,1,Opcode.ADMIT,
                phase=bound.mode,source_slot=bound.local_slot,data=Admission(i.generation,i.player_id,i.runtime_id).pack()))
        if publish:
            self.path.unlink(missing_ok=True)
            publish_admission_intent(self.session._profile_directory/FILENAME,admission)
            self.session._battle_recovery_intent=admission
        return admission

    async def asyncTearDown(self):
        for task in (self.session._autosave_task,self.session._emergency_task):
            if task is not None:
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)

    def completion(self, *, lease=9, server=4):
        i = self.intent
        renewed = RenewedBattleSession(i.world_id,i.player_id,i.build_id,i.ruleset_id,i.save_profile,
                                      server,lease,i.incarnation,i.runtime_id)
        return BattleCompletion(i.battle_id,i.generation,i.canonical_revision,i.canonical_sha256,
                                renewed_session=renewed)

    async def finish(self, *, lease=9, server=4, remove=True):
        self.c.connected=True;self.c.session_epoch=lease;self.c.server_epoch=server
        if remove:self.path.unlink()
        return self.completion(lease=lease,server=server)

    async def recover(self, callback, *, handoff=None, arm_hook=None):
        with (patch('emerald_multiplayer.launcher_session.GameInstallation.verify') as verify,
              patch('emerald_multiplayer.battle_recovery_session.NativeBattleRecoverySession',create=True) as controller,
              patch('emerald_multiplayer.battle_recovery_session.verify_recovery_completion',return_value={}),
              patch('emerald_multiplayer.battle_terminal.complete_battle_handoff',new_callable=AsyncMock) as transfer,
              patch('emerald_multiplayer.emergency_save.EmergencySaveController') as emergency,
              patch.object(self.session,'_watch_emergency',new_callable=AsyncMock),
              patch.object(self.session,'_schedule_autosave',new_callable=AsyncMock)):
            controller.return_value.run = AsyncMock(side_effect=callback)
            successor = SimpleNamespace(lost=asyncio.Event(), result=SimpleNamespace(state='unarmed'), needs_arm=True)
            async def arm(base):
                self.assertEqual(base,self.intent.canonical_revision)
                self.assertEqual(self.session._binding,self.original_binding)
                self.assertTrue(self.session._save_failed)
                successor.result.state='armed';successor.needs_arm=False
                self.c._emergency_controller=successor
            successor.arm=AsyncMock(side_effect=arm_hook or arm)
            emergency.return_value = successor
            async def exact_handoff(c,directory,result,intent,bridge,fresh):
                self.assertIs(c,self.c);self.assertEqual(intent,self.intent)
                self.assertIs(bridge,self.c._bridge);self.assertIs(fresh,self.session._emergency)
                self.assertEqual(fresh.result.state,'armed')
                self.assertIs(c._emergency_controller,fresh)
                self.assertEqual(self.session._binding,self.original_binding)
                self.assertTrue(self.session._save_failed)
            transfer.side_effect=handoff or exact_handoff
            value = await self.session.recover_battle()
            verify.assert_called_once()
            return value,controller,emergency

    async def test_exact_terminal_receipt_adopts_renewed_session_then_new_emergency_and_save_policy(self):
        s = self.session
        self.assertTrue(s.can_recover_battle)
        original_game, original_runtime, original_bridge = s._game,s._runtime,self.c._bridge
        result,controller,emergency = await self.recover(self.finish)
        controller.assert_called_once_with(self.c,s._profile_directory,original_intent=self.intent)
        controller.return_value.run.assert_awaited_once_with()
        self.old_emergency.retire_after_battle_recovery.assert_awaited_once()
        emergency.assert_called_once()
        emergency.return_value.arm.assert_awaited_once_with(2)
        self.assertEqual(s._binding,s._signature())
        self.assertFalse(s._save_failed)
        self.assertEqual(s._revision,2)
        self.assertEqual(s._autosave_due,400)
        self.assertTrue(s.can_save)
        self.assertFalse(s.can_recover_battle)
        self.assertEqual(s.status.code,'battle_recovered')
        self.assertIs(s._game,original_game);self.assertIs(s._runtime,original_runtime)
        self.assertIs(self.c._bridge,original_bridge)
        self.assertEqual(result.canonical_sha256,'c'*64)

    async def test_connected_peer_keeps_same_authenticated_lease_after_exact_release(self):
        self.c.connected=True
        self.old_emergency.lost.clear()
        self.old_emergency.result.state='armed';self.old_emergency.task=None
        async def release_on_existing_lease():
            return await self.finish(lease=7,server=3)
        await self.recover(release_on_existing_lease)
        self.assertEqual(self.session._binding,self.original_binding)
        self.assertTrue(self.session.can_save)
        self.old_emergency.retire_after_battle_recovery.assert_awaited_once()

    async def test_original_menu_latch_retires_only_after_verified_native_handoff(self):
        events=[]
        async def handoff(*args):
            self.assertTrue(self.session._save_failed)
            events.append('handoff')
        def finish(battle_id,generation):
            self.assertEqual((battle_id,generation),(self.intent.battle_id,self.intent.generation))
            self.assertEqual(events,['handoff'])
            self.assertEqual(self.session._binding,self.original_binding)
            self.assertEqual(self.session._battle_recovery_intent,self.intent)
            events.append('menu')
        self.c._bridge.menu_session=SimpleNamespace(finish_battle_admission=Mock(side_effect=finish))
        await self.recover(self.finish,handoff=handoff)
        self.assertEqual(events,['handoff','menu'])
        self.assertIsNone(self.session._battle_recovery_intent)
        self.assertTrue(self.session.can_save)

    async def test_menu_retirement_refusal_keeps_original_terminal_intent_and_successor(self):
        self.c._bridge.menu_session=SimpleNamespace(finish_battle_admission=Mock(side_effect=ValueError('foreign UI battle')))
        with self.assertRaises(LauncherSessionError):await self.recover(self.finish)
        self.assertEqual(self.session._battle_recovery_intent,self.intent)
        self.assertEqual(self.session._binding,self.original_binding)
        self.assertIsNotNone(self.session._battle_handoff_successor)
        self.assertFalse(self.session.can_save)
        self.assertTrue(self.session._retain_interrupted_core())

    async def test_no_emergency_capability_cannot_release_terminal_native_hold(self):
        self.c.config.emergency_save_abi_version=0
        self.assertFalse(self.session.can_recover_battle)
        with self.assertRaises(LauncherSessionError):
            await self.recover(self.finish)
        self.old_emergency.retire_after_battle_recovery.assert_not_awaited()
        self.assertEqual(self.path.read_bytes(),self.original_bytes)
        self.assertFalse(self.session.can_save)

    async def test_malformed_or_foreign_intent_and_missing_capability_never_offer_recovery(self):
        s = self.session
        for field,value in (('runtime_id',str(uuid4())),('canonical_revision',3),('lease_epoch',8)):
            with self.subTest(field=field):
                self.write_intent(replace(self.intent,**{field:value}))
                self.assertFalse(s.can_recover_battle)
        self.path.write_bytes(self.original_bytes)
        for target,field,value in ((s._manifest,'battle_resume_abi_version',0),
                                  (self.c.config,'battle_resume_abi_version',0),
                                  (self.c._bridge,'incarnation',21),
                                  (s._game.process,'returncode',0)):
            old=target[field] if isinstance(target,dict) else getattr(target,field)
            if isinstance(target,dict):target[field]=value
            else:setattr(target,field,value)
            self.assertFalse(s.can_recover_battle)
            if isinstance(target,dict):target[field]=old
            else:setattr(target,field,old)
        self.path.write_text('malformed')
        self.assertFalse(s.can_recover_battle)

    async def test_duplicate_action_and_cancellation_retain_original_core_intent_and_binding(self):
        entered=asyncio.Event()
        async def wait():entered.set();await asyncio.Event().wait()
        task=asyncio.create_task(self.recover(wait))
        await entered.wait()
        self.assertFalse(self.session.can_recover_battle)
        with self.assertRaises(LauncherSessionError):await self.session.recover_battle()
        self.assertFalse(self.session.can_save)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(self.path.read_bytes(),self.original_bytes)
        self.assertEqual(self.session._binding,self.original_binding)
        self.assertTrue(self.session._retain_interrupted_core())
        self.assertEqual(self.session.status.code,'battle_recovery_held')
        self.assertTrue(self.session.can_recover_battle)

    async def test_forged_terminal_descriptor_never_retires_controller_or_adopts_lease(self):
        async def corrupt():
            await self.finish(remove=False)
            return replace(self.completion(),canonical_sha256='d'*64)
        with self.assertRaises(LauncherSessionError):await self.recover(corrupt)
        self.assertEqual(self.path.read_bytes(),self.original_bytes)
        self.assertEqual(self.session._binding,self.original_binding)
        self.assertTrue(self.session._save_failed)
        self.old_emergency.retire_after_battle_recovery.assert_not_awaited()

    async def test_exact_result_with_pending_intent_still_refuses(self):
        async def pending():return await self.finish(remove=False)
        with self.assertRaises(LauncherSessionError):await self.recover(pending)
        self.assertEqual(self.path.read_bytes(),self.original_bytes)
        self.assertEqual(self.session._binding,self.original_binding)
        self.old_emergency.retire_after_battle_recovery.assert_not_awaited()

    async def test_replacement_bridge_cannot_inherit_matching_numeric_incarnation(self):
        original=self.c._bridge
        self.c._bridge=SimpleNamespace(**vars(original))
        self.assertFalse(self.session.can_recover_battle)
        self.c._bridge=original
        async def changed():
            result=await self.finish()
            self.c._bridge=SimpleNamespace(**vars(original))
            return result
        with self.assertRaises(LauncherSessionError):await self.recover(changed)
        self.assertEqual(self.session._binding,self.original_binding)
        self.old_emergency.retire_after_battle_recovery.assert_not_awaited()

    async def test_unresolved_export_created_during_recovery_prevents_save_policy_adoption(self):
        async def changed():
            result=await self.finish()
            (self.session._profile_directory/'pending-export.json').write_text('retained')
            return result
        with self.assertRaises(LauncherSessionError):await self.recover(changed)
        self.assertTrue((self.session._profile_directory/'pending-export.json').exists())
        self.assertEqual(self.session._binding,self.original_binding)
        self.assertFalse(self.session.can_save)
        self.old_emergency.retire_after_battle_recovery.assert_not_awaited()

    async def test_retirement_failure_keeps_save_blocked_and_original_launcher_binding(self):
        self.old_emergency.retire_after_battle_recovery.side_effect=ValueError('private path and token')
        with self.assertRaises(LauncherSessionError) as error:await self.recover(self.finish)
        self.assertNotIn('private path',str(error.exception))
        self.assertEqual(self.session._binding,self.original_binding)
        self.assertFalse(self.session.can_save)
        self.assertTrue(self.session._retain_interrupted_core())

    async def test_never_armed_unregistered_controller_is_replaced_without_retirement(self):
        self.c._emergency_controller=None
        self.old_emergency.session=self.old_emergency.bridge=self.old_emergency.task=None
        self.old_emergency.result.state='unarmed';self.old_emergency.lost.clear()
        await self.recover(self.finish)
        self.old_emergency.retire_after_battle_recovery.assert_not_awaited()
        self.assertTrue(self.session.can_save)

    async def test_terminal_adoption_retry_keeps_original_intent_after_pending_unlink(self):
        async def terminal():
            result=await self.finish()
            # The recovery service tests verify this receipt's native contents;
            # this launcher fixture models its retained publication boundary.
            (self.session._profile_directory/(self.intent.battle_id+'.battle-recovery-complete.json')).write_text('{}')
            return result
        retire=self.old_emergency.retire_after_battle_recovery.side_effect
        self.old_emergency.retire_after_battle_recovery.side_effect=OSError('disk unavailable')
        with self.assertRaises(LauncherSessionError):await self.recover(terminal)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.session._battle_recovery_intent,self.intent)
        self.assertTrue(self.session.can_recover_battle)
        self.assertEqual(self.session._binding,self.original_binding)
        self.old_emergency.retire_after_battle_recovery.side_effect=retire
        async def receipt_only():return self.completion()
        _,controller,_=await self.recover(receipt_only)
        controller.assert_called_once_with(self.c,self.session._profile_directory,original_intent=self.intent)
        self.assertTrue(self.session.can_save)
        self.assertIsNone(self.session._battle_recovery_intent)

    async def test_handoff_failure_reuses_same_registered_successor_without_old_retirement(self):
        async def terminal():
            result=await self.finish()
            (self.session._profile_directory/(self.intent.battle_id+'.battle-recovery-complete.json')).write_text('{}')
            return result
        async def uncertain(*args):raise OSError('receipt unavailable')
        with self.assertRaises(LauncherSessionError):await self.recover(terminal,handoff=uncertain)
        successor=self.session._battle_handoff_successor
        self.assertIsNotNone(successor)
        self.assertIs(self.c._emergency_controller,successor)
        self.assertTrue(self.session.can_recover_battle)
        self.assertFalse(self.session.can_save)
        self.assertEqual(self.session._binding,self.original_binding)
        async def receipt_only():return self.completion()
        _,_,constructor=await self.recover(receipt_only)
        constructor.assert_not_called()
        successor.arm.assert_awaited_once_with(2)
        self.old_emergency.retire_after_battle_recovery.assert_awaited_once()
        self.assertIs(self.session._emergency,successor)
        self.assertTrue(self.session.can_save)

    async def test_failed_successor_arm_retains_same_object_for_exact_retry(self):
        attempts=[]
        async def arm(base):
            attempts.append(base)
            if len(attempts)==1:raise OSError('ownership receipt unavailable')
            successor=self.session._battle_handoff_successor
            successor.result.state='armed';successor.needs_arm=False
            self.c._emergency_controller=successor
        async def terminal():
            result=await self.finish()
            (self.session._profile_directory/(self.intent.battle_id+'.battle-recovery-complete.json')).write_text('{}')
            return result
        with self.assertRaises(LauncherSessionError):await self.recover(terminal,arm_hook=arm)
        successor=self.session._battle_handoff_successor
        self.assertEqual(self.session._binding,self.original_binding)
        self.assertTrue(self.session.can_recover_battle)
        async def receipt_only():return self.completion()
        _,_,constructor=await self.recover(receipt_only)
        constructor.assert_not_called()
        self.assertIs(self.session._emergency,successor)
        self.assertEqual(attempts,[2,2])
        self.old_emergency.retire_after_battle_recovery.assert_awaited_once()

    async def test_normal_resumable_completion_uses_same_terminal_adoption_before_field_return(self):
        s=self.session;self.c.connected=True;s._save_failed=False
        self.old_emergency.lost.clear();self.old_emergency.result.state='armed';self.old_emergency.task=None
        s._manifest['battle_execution_abi_version']=1
        admission=self.provisional(publish=False)
        descriptor=admission.challenge
        menu=SimpleNamespace(bridge=self.c._bridge)
        s._interaction=asyncio.current_task()
        s._battle_menu_preparation=(s._interaction,menu,admission)
        events=[]
        async def complete(challenge):
            self.assertIs(challenge,descriptor)
            events.append('terminal')
            return await self.finish(lease=7,server=3)
        async def adopt(result,intent,game,bridge,runtime):
            self.assertEqual(intent,self.intent)
            self.assertIs(game,s._game);self.assertIs(bridge,self.c._bridge);self.assertIs(runtime,s._runtime)
            self.assertEqual(result.renewed_session.lease_epoch,7)
            events.append('adopt')
            s._battle_retained=None
        with (patch('emerald_multiplayer.battle_session.NativeBattleSession') as executor,
              patch('emerald_multiplayer.battle_admission_session.verify_admission_conversion',return_value=self.intent),
              patch.object(s,'_adopt_battle_completion',new_callable=AsyncMock,side_effect=adopt) as transfer):
            executor.return_value.intent=self.intent
            executor.return_value.run=AsyncMock(side_effect=complete)
            await s._native_menu_handoff('battle',descriptor,menu)
        self.assertEqual(events,['terminal','adopt'])
        transfer.assert_awaited_once()
        self.assertEqual(s.status.code,'battle_finished')

    async def test_provisional_recovery_verifies_original_conversion_before_terminal_adoption(self):
        from emerald_multiplayer.battle_admission_intent import FILENAME
        admission = self.provisional()
        self.assertTrue(self.session.can_recover_battle)
        async def complete():
            (self.session._profile_directory/FILENAME).unlink()
            self.write_intent(self.intent)
            return await self.finish()
        with (patch('emerald_multiplayer.launcher_session.GameInstallation.verify'),
              patch('emerald_multiplayer.battle_recovery_session.NativeBattleRecoverySession') as executor,
              patch('emerald_multiplayer.battle_admission_session.verify_admission_conversion',return_value=self.intent) as conversion,
              patch.object(self.session,'_adopt_battle_completion',new_callable=AsyncMock) as adopt):
            executor.return_value.run=AsyncMock(side_effect=complete)
            executor.return_value.intent=self.intent
            await self.session.recover_battle()
        executor.assert_called_once_with(self.c,self.session._profile_directory,original_intent=admission)
        conversion.assert_called_once_with(self.session._profile_directory,admission,self.intent)
        self.assertEqual(adopt.await_args.args[1],self.intent)
        self.assertEqual(self.session._battle_recovery_intent,self.intent)

    async def test_partial_provisional_conversion_retains_original_and_rejects_unverified_replacement(self):
        from emerald_multiplayer.battle_admission_intent import FILENAME
        admission=self.provisional()
        self.write_intent(self.intent)
        self.assertEqual(self.session._retained_battle()[0],admission)
        (self.session._profile_directory/FILENAME).unlink()
        self.assertFalse(self.session.can_recover_battle)
        with patch('emerald_multiplayer.battle_admission_session.verify_admission_conversion',return_value=self.intent) as conversion:
            self.assertEqual(self.session._retained_battle()[0],self.intent)
        conversion.assert_called_once_with(self.session._profile_directory,admission,self.intent)
        self.assertEqual(self.session._battle_recovery_intent,admission)

    async def test_menu_preparation_owns_same_core_before_drain_and_native_admission(self):
        from emerald_multiplayer.battle_admission_intent import FILENAME, read_admission_intent
        admission=self.provisional(publish=False)
        s=self.session;self.c.connected=True;s._save_failed=False
        s._manifest['battle_execution_abi_version']=1
        s._battle_retained=None;s._battle_recovery_intent=None
        menu=SimpleNamespace(bridge=self.c._bridge,_battle_preparing=True)
        self.path.unlink()
        self.assertEqual(s._native_menu_capture_battle(admission.challenge,menu),admission)
        self.assertEqual(read_admission_intent(s._profile_directory/FILENAME),admission)
        self.assertIs(s._interaction,menu)
        events=[]
        async def drain():
            self.assertIs(s._interaction,asyncio.current_task())
            self.assertIs(s._battle_retained[0],s._game)
            self.assertIs(s._battle_retained[2],self.c._bridge)
            self.assertFalse(s.can_save)
            events.append('drain')
        async def prepare(c,directory,descriptor):
            self.assertEqual(descriptor,admission.challenge)
            self.assertEqual(events,['drain'])
            self.assertIs(s._interaction,asyncio.current_task())
            events.append('admit')
            return admission
        with (patch.object(s,'_stop_autosave',new_callable=AsyncMock,side_effect=drain),
              patch('emerald_multiplayer.battle_admission_session.prepare_battle_admission',new_callable=AsyncMock,side_effect=prepare)):
            self.assertEqual(await s._native_menu_prepare_battle(admission.challenge,menu),admission)
        self.assertEqual(events,['drain','admit'])
        self.assertEqual(s._battle_recovery_intent,admission)
        self.assertIs(s._interaction,asyncio.current_task())
        s._native_menu_abandon_battle_preparation(menu)
        self.assertIsNone(s._interaction)
        self.assertTrue(s._retain_interrupted_core())
        self.assertTrue(s._save_failed)
        self.assertEqual(s._battle_recovery_intent,admission)

    async def test_menu_preparation_uncertainty_retains_core_and_blocks_other_actions(self):
        admission=self.provisional()
        s=self.session;self.c.connected=True;s._save_failed=False
        s._manifest['battle_execution_abi_version']=1
        menu=SimpleNamespace(bridge=self.c._bridge,_battle_preparing=True)
        original=s._game
        s._native_menu_capture_battle(admission.challenge,menu)
        async def fail(*args):raise ConnectionError('private transport detail')
        with patch('emerald_multiplayer.battle_admission_session.prepare_battle_admission',new_callable=AsyncMock,side_effect=fail):
            with self.assertRaises(ConnectionError):await s._native_menu_prepare_battle(admission.challenge,menu)
        self.assertIs(s._game,original)
        self.assertIsNone(s._interaction)
        self.assertTrue(s._save_failed)
        self.assertTrue(s._retain_interrupted_core())
        self.assertTrue(s.can_recover_battle)
        self.assertNotIn('private transport',str(s.status))

    async def test_prepared_menu_handoff_requires_same_task_menu_and_immutable_consent(self):
        admission=self.provisional()
        s=self.session;self.c.connected=True;s._save_failed=False
        s._manifest['battle_execution_abi_version']=1
        menu=SimpleNamespace(bridge=self.c._bridge,_battle_preparing=True)
        s._native_menu_capture_battle(admission.challenge,menu)
        with patch('emerald_multiplayer.battle_admission_session.prepare_battle_admission',new_callable=AsyncMock,return_value=admission):
            await s._native_menu_prepare_battle(admission.challenge,menu)
        async def other_task():
            with self.assertRaises(LauncherSessionError):await s._native_menu_handoff('battle',admission.challenge,menu)
        await asyncio.create_task(other_task())
        with self.assertRaises(LauncherSessionError):
            await s._native_menu_handoff('battle',admission.challenge,SimpleNamespace(bridge=self.c._bridge))
        changed=admission.challenge;changed['fingerprint']='d'*64
        with self.assertRaises(LauncherSessionError):await s._native_menu_handoff('battle',changed,menu)
        self.assertIs(s._interaction,asyncio.current_task())
        events=[]
        async def finish(challenge):
            self.assertEqual(challenge,admission.challenge)
            events.append('execute')
            return self.completion(lease=7,server=3)
        async def adopt(*args):events.append('adopt')
        with (patch('emerald_multiplayer.battle_session.NativeBattleSession') as executor,
              patch('emerald_multiplayer.battle_admission_session.verify_admission_conversion',return_value=self.intent) as conversion,
              patch.object(s,'_adopt_battle_completion',new_callable=AsyncMock,side_effect=adopt)):
            executor.return_value.intent=self.intent
            executor.return_value.run=AsyncMock(side_effect=finish)
            await s._native_menu_handoff('battle',admission.challenge,menu)
        self.assertEqual(events,['execute','adopt'])
        conversion.assert_called_once_with(s._profile_directory,admission,self.intent)
        self.assertIsNone(s._interaction)
        self.assertIsNone(s._battle_menu_preparation)

    async def test_enter_latch_preflight_refusal_still_retains_original_core(self):
        s=self.session
        menu=SimpleNamespace(bridge=self.c._bridge,_battle_preparing=True)
        s._native_menu_abandon_battle_preparation(menu)
        self.assertTrue(s._battle_recovery_failed)
        self.assertTrue(s._retain_interrupted_core())
        self.assertTrue(s._save_failed)

    async def test_synchronous_enter_capture_retains_original_offline_binding_before_any_task(self):
        from emerald_multiplayer.battle_admission_intent import FILENAME, read_admission_intent
        admission=self.provisional(publish=False)
        s=self.session
        s._manifest['battle_execution_abi_version']=1
        s._idle_save_disconnect=True
        self.path.unlink()
        menu=SimpleNamespace(bridge=self.c._bridge,_battle_preparing=True)
        self.assertFalse(self.c.connected)
        result=s._native_menu_capture_battle(admission.challenge,menu)
        self.assertEqual(result,admission)
        self.assertEqual(read_admission_intent(s._profile_directory/FILENAME),admission)
        self.assertIs(s._interaction,menu)
        self.assertEqual(s._battle_menu_preparation,(None,menu,admission))
        self.assertFalse(s.can_recover_battle)
        s._native_menu_abandon_battle_preparation(menu)
        self.assertTrue(s.can_recover_battle)
        self.assertTrue(s._retain_interrupted_core())

    async def test_async_preparation_cannot_invent_an_uncaptured_enter(self):
        s=self.session;self.c.connected=True;s._save_failed=False
        s._manifest['battle_execution_abi_version']=1
        menu=SimpleNamespace(bridge=self.c._bridge,_battle_preparing=True)
        with patch('emerald_multiplayer.battle_admission_session.prepare_battle_admission',new_callable=AsyncMock) as prepare:
            with self.assertRaises(LauncherSessionError):
                await s._native_menu_prepare_battle(self.provisional(publish=False).challenge,menu)
        prepare.assert_not_awaited()

    async def terminal_preserver(self):
        from emerald_multiplayer.emergency_save import EmergencySaveController, EmergencyResult
        s=self.session;c=self.c;i=self.intent
        self.path.unlink(missing_ok=True)
        s._battle_recovery_intent=i
        s._battle_recovery_failed=True
        successor=object.__new__(EmergencySaveController)
        successor.companion=c;successor.bridge=c._bridge
        successor.session=(i.world_id,9,i.incarnation)
        successor.base_revision=i.canonical_revision
        successor.identity=dict(world_id=i.world_id,player_id=i.player_id,build_id=i.build_id,
            ruleset_id=i.ruleset_id,save_profile=i.save_profile)
        successor.lost=asyncio.Event();successor.lost.set()
        successor.result=EmergencyResult('preserved',str(uuid4()),'d'*64,True)
        async def completed():return successor.result
        successor.task=asyncio.create_task(completed())
        await successor.task
        s._battle_handoff_successor=s._emergency=c._emergency_controller=successor
        return successor

    async def test_verified_successor_preservation_allows_close_after_failed_terminal_handoff(self):
        successor=await self.terminal_preserver()
        s=self.session
        self.assertTrue(s._terminal_successor_preserved())
        self.assertFalse(s._retain_interrupted_core())
        self.assertEqual(s.status.code,'host_loss_preserved')
        self.assertFalse(s.status.battle_recovery_available)
        self.assertTrue(s._save_failed)
        self.assertEqual(s._binding,self.original_binding)
        self.assertEqual(s._battle_recovery_intent,self.intent)
        self.assertIs(s._battle_handoff_successor,successor)

    async def test_successor_preservation_cannot_close_foreign_or_unfinished_core(self):
        from emerald_multiplayer.emergency_save import EmergencyResult
        successor=await self.terminal_preserver()
        s=self.session
        cases=((s,'_runtime',object()),(self.c,'_bridge',SimpleNamespace(incarnation=20)),
            (self.c,'_emergency_controller',object()),(successor,'base_revision',3),
            (successor,'result',EmergencyResult('unsaved_held')), (self.c,'_live_save_owner',object()))
        for owner,key,changed in cases:
            original=getattr(owner,key)
            try:
                setattr(owner,key,changed)
                self.assertFalse(s._terminal_successor_preserved())
                self.assertTrue(s._retain_interrupted_core())
                self.assertEqual(s.status.code,'battle_recovery_held')
            finally:setattr(owner,key,original)
        self.write_intent(self.intent)
        self.assertFalse(s._terminal_successor_preserved())
        self.assertTrue(s._retain_interrupted_core())

    async def test_explicit_game_exit_drains_recovery_before_runtime_lease_context_exits(self):
        s=self.session;self.c.connected=True
        self.c.config.emergency_save_abi_version=0
        s._emergency=None;s._save_failed=False
        game=s._game
        game.startup=SimpleNamespace(mirror=SimpleNamespace(revision=2))
        entered=asyncio.Event();exit_game=asyncio.Event();drained=asyncio.Event();lease_exited=[]
        async def game_wait():
            entered.set();await exit_game.wait();game.process.returncode=0;return 0
        game.wait=game_wait
        @asynccontextmanager
        async def runtime_open():
            try:yield game
            finally:
                self.assertTrue(drained.is_set())
                lease_exited.append(True)
        s._runtime=SimpleNamespace(open=runtime_open)
        async def recovery():
            try:await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                drained.set()
                s._battle_recovery_task=None
        with (patch.object(s,'_ready',new_callable=AsyncMock,return_value=2),
              patch.object(s,'_schedule_autosave',new_callable=AsyncMock),
              patch('emerald_multiplayer.launcher_session.GameInstallation.verify')):
            play=asyncio.create_task(s.play())
            await entered.wait()
            pending=asyncio.create_task(recovery())
            s._battle_recovery_task=pending
            await asyncio.sleep(0)
            exit_game.set()
            self.assertEqual(await play,0)
        self.assertTrue(pending.cancelled())
        self.assertEqual(lease_exited,[True])
        self.assertEqual(self.path.read_bytes(),self.original_bytes)


class BattleRecoveryWorkerTests(unittest.TestCase):
    def test_explicit_single_flight_action_keeps_worker_game_and_sanitizes_failure(self):
        created=threading.Event();entered=threading.Event();release=threading.Event();instances=[]
        class Session(ControlledSession):
            async def recover_battle(self):
                entered.set()
                while not release.is_set():await asyncio.sleep(.005)
                raise ValueError('secret session and file path')
        def factory(*args,**kwargs):
            s=Session(*args,**kwargs);instances.append(s);created.set();return s
        worker=SessionWorker(object(),Path('private'),factory=factory)
        try:
            self.assertFalse(worker.request_battle_recovery())
            worker.start(LaunchRequest('join',Path('invitation.json')))
            self.assertTrue(created.wait(2));s=instances[0]
            s.release_connect.set();self.assertTrue(s.played.wait(2))
            s.status=SessionStatus(SessionState.RUNNING,'host_loss_battle_waiting',battle_recovery_available=True)
            worker._publish(s.status)
            self.assertTrue(worker.request_battle_recovery())
            self.assertFalse(worker.request_battle_recovery())
            self.assertFalse(worker.request_save())
            self.assertFalse(worker.request_autosave(False))
            self.assertTrue(entered.wait(2));release.set()
            deadline=time.monotonic()+2
            while worker._battle_recovery_pending and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(worker.busy);self.assertFalse(s.play_cancelled)
            events=[]
            while not worker.events.empty():events.append(worker.events.get_nowait())
            self.assertTrue(any(e.code=='battle_recovery_held' for e in events))
            self.assertNotIn('secret',repr(events))
        finally:
            release.set()
            for s in instances:
                s.release_connect.set();s.release_game.set();s.release_cleanup.set()
            if worker._thread:worker._thread.join(4)
        self.assertFalse(worker.busy)


class BattleRecoveryWidgetTests(unittest.TestCase):
    def test_recovery_button_requires_explicit_verified_availability_and_keeps_window_open(self):
        import tkinter as tk
        try:root=tk.Tk()
        except tk.TclError as error:self.skipTest('Tk display unavailable: '+str(error))
        root.withdraw()
        self.addCleanup(root.destroy)
        class Worker:
            busy=holds_game=True
            events=queue.SimpleQueue()
            requested=0
            def request_battle_recovery(self):self.requested+=1;return True
            def cancel_startup(self):raise AssertionError('retained core must not be canceled')
        worker=Worker();window=LauncherWindow(root,worker)
        self.assertEqual(str(window.recover_battle_button.cget('state')),'disabled')
        worker.events.put(UiEvent('status','host_loss_battle_waiting','running'))
        window.poll()
        self.assertEqual(str(window.recover_battle_button.cget('state')),'disabled')
        worker.events.put(UiEvent('status','host_loss_battle_waiting','running',True,True))
        window.poll()
        self.assertEqual(str(window.recover_battle_button.cget('state')),'normal')
        window.close()
        self.assertFalse(window.closing)
        window.recover_battle()
        self.assertEqual(worker.requested,1)
        self.assertEqual(str(window.recover_battle_button.cget('state')),'disabled')
        self.assertEqual(str(window.save_button.cget('state')),'disabled')
        self.assertEqual(window.message.get(),status_text('battle_recovering'))
        self.assertTrue(root.winfo_exists())

