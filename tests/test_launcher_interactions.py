import asyncio
import hashlib
import json
from pathlib import Path
import socket
import struct
import tempfile
import zlib
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from emerald_multiplayer.launcher_session import GameInstallation, LauncherSession, LauncherSessionError
from emerald_multiplayer.battle_session import BattleCompletion
from emerald_multiplayer.host_world import HostWorld
from test_host_world import make_trade_files
from test_player_runtime import write_bundle


class LauncherRetentionTests(unittest.IsolatedAsyncioTestCase):
    def controller(self, *, unsafe=False):
        session = object.__new__(LauncherSession)
        done = asyncio.Event()
        async def wait():
            await done.wait()
            session._game.process.returncode = 0
            return 0
        session._game = SimpleNamespace(process=SimpleNamespace(returncode=None), wait=wait)
        lost = asyncio.Event()
        if unsafe: lost.set()
        session._emergency = SimpleNamespace(lost=lost, result=SimpleNamespace(can_close=False))
        session._profile_directory = "."
        session._companion = object()
        return session, done

    async def test_repeated_cancel_retains_unsafe_core_until_ordinary_exit(self):
        session, done = self.controller(unsafe=True)
        task = asyncio.create_task(session._wait_game(session._game))
        await asyncio.sleep(0)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertIsNone(session._game.process.returncode)
        done.set()
        with self.assertRaises(asyncio.CancelledError): await task

    async def test_pending_battle_is_retained_even_without_emergency_loss(self):
        session, done = self.controller()
        with patch("emerald_multiplayer.launcher_session.pending_battle", return_value=True):
            task = asyncio.create_task(session._wait_game(session._game))
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            done.set()
            with self.assertRaises(asyncio.CancelledError): await task

    async def test_durable_emergency_receipt_allows_normal_cancellation_cleanup(self):
        session, _ = self.controller(unsafe=True)
        session._emergency.result.can_close = True
        with patch("emerald_multiplayer.launcher_session.pending_battle", return_value=False):
            task = asyncio.create_task(session._wait_game(session._game))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task

    async def test_normal_game_exit_propagates_its_result(self):
        session, done = self.controller()
        done.set()
        self.assertEqual(await session._wait_game(session._game), 0)

    async def test_unreadable_battle_intent_cannot_authorize_destroying_core(self):
        session, _ = self.controller()
        with patch("emerald_multiplayer.launcher_session.pending_battle", side_effect=ValueError("unreadable")):
            self.assertTrue(session._retain_interrupted_core())


class LauncherHandoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        installation = GameInstallation(self.directory/'game.gba', self.directory/'manifest.json', 'a'*64, 'b'*64, None)
        self.session = session = LauncherSession(installation, self.directory,
            world_directory=self.directory/'world', bind_address='127.0.0.1')
        session._profile_directory = self.directory/'profile'
        session._companion = SimpleNamespace(connected=True, world_id='world', server_epoch=2,
            session_epoch=3, save_profile='profile', save_incarnation=8, _bridge=object(),
            config=SimpleNamespace(player_id='player', build_id='a'*64, ruleset_id='rules'))
        session._binding = session._signature()
        session._open = True
        session._game = SimpleNamespace(process=SimpleNamespace(returncode=None))
        session._revision = 1
        session._autosave_clock = lambda: 100
        self.menu = SimpleNamespace(bridge=session._companion._bridge)
        self.receipt = dict(transaction_id='transaction', state='applied', checkpoint=dict(
            revision=3, request_id='11111111-1111-4111-8111-111111111111', size=131072,
            sha256='c'*64, build_id='a'*64, ruleset_id='rules', save_profile='profile'))

    async def trade(self, callback):
        with patch('emerald_multiplayer.trade_menu.NativeTradeMenu') as controller:
            controller.return_value.run = AsyncMock(side_effect=callback)
            await self.session._native_menu_handoff('trade', {'transaction_id':'transaction'}, self.menu)

    async def test_completed_trade_advances_only_receipt_revision_and_resumes_save_policy(self):
        async def complete(*args):
            self.assertFalse(self.session.can_save)
            return self.receipt
        await self.trade(complete)
        self.assertEqual(self.session._revision, 3)
        self.assertEqual(self.session._autosave_due, 400)
        self.assertTrue(self.session.can_save)
        self.assertEqual(self.session.status.code, 'trade_finished')

    async def test_changed_incarnation_never_adopts_completed_trade_revision(self):
        async def changed(*args):
            self.session._companion.save_incarnation += 1
            return self.receipt
        with self.assertRaises(LauncherSessionError): await self.trade(changed)
        self.assertEqual(self.session._revision, 1)
        self.assertFalse(self.session.can_save)

    async def test_pending_native_trade_journal_prevents_receipt_adoption(self):
        self.session._profile_directory.mkdir()
        (self.session._profile_directory/'pending-trade.json').write_text('retained')
        async def incomplete(*args): return self.receipt
        with self.assertRaises(LauncherSessionError): await self.trade(incomplete)
        self.assertEqual(self.session._revision, 1)
        self.assertTrue((self.session._profile_directory/'pending-trade.json').exists())
        self.assertFalse(self.session.can_save)

    async def test_cancellation_of_dispatched_operation_requires_recovery(self):
        async def canceled(*args): raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError): await self.trade(canceled)
        self.assertIsNone(self.session._interaction)
        self.assertEqual(self.session._revision, 1)
        self.assertFalse(self.session.can_save)

    async def test_battle_completion_for_different_checkpoint_cannot_release_save_policy(self):
        self.session._manifest = {'battle_execution_abi_version':1}
        descriptor = dict(battle_id='battle', generation='generation',
                          checkpoints=[dict(player_id='player', revision=1, sha256='c'*64)])
        with patch('emerald_multiplayer.battle_session.NativeBattleSession') as controller:
            controller.return_value.run = AsyncMock(return_value=BattleCompletion('battle','generation',1,'d'*64,'closed'))
            with self.assertRaises(LauncherSessionError):
                await self.session._native_menu_handoff('battle',descriptor,self.menu)
        self.assertFalse(self.session.can_save)
        self.assertEqual(self.session._revision, 1)


class LauncherBattleCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_host_and_join_enable_native_channel_only_for_verified_execution_manifest(self):
        for enabled in (False, True):
            with self.subTest(execution=enabled), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                rom, manifest = make_trade_files(root)
                raw = bytearray(4096)
                struct.pack_into('<II', raw, 0, 1, 3)
                rom.write_bytes(raw)
                value = json.loads(manifest.read_text())
                value.update(rom_sha256=hashlib.sha256(raw).hexdigest(), rom_size=len(raw),
                    rom_crc32=f'{zlib.crc32(raw):08x}', battle_abi_version=3,
                    battle_abi_address=0x08000004, battle_mailbox_address=0x02022000, battle_mailbox_size=512)
                if enabled:
                    value.update(battle_execution_abi_version=1,
                        battle_string_table_address=0x08000400, battle_string_table_size=2884)
                manifest.write_text(json.dumps(value))
                bundle_dir = root/'bundle'; bundle_dir.mkdir()
                installation = GameInstallation(rom, manifest, hashlib.sha256(raw).hexdigest(),
                    hashlib.sha256(manifest.read_bytes()).hexdigest(), write_bundle(bundle_dir))
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
                host = HostWorld.create(root/'world',rom,manifest,
                    player_names=('Host','Friend'), endpoint='127.0.0.1',port=port)
                invitation = root/'friend.json'; host.invitation(1).save(invitation)
                sessions = (
                    LauncherSession(installation,root/'private',world_directory=host.directory,bind_address='127.0.0.1'),
                    LauncherSession(installation,root/'private',invitation_path=invitation),
                )
                async with sessions[0].open(), sessions[1].open():
                    self.assertEqual(sessions[0]._server.battle_execution is not None, enabled)
                    for session in sessions:
                        self.assertTrue(session._companion.connected)
                        self.assertIsNotNone(session._companion._remote_writer.get_extra_info('ssl_object'))
                        self.assertEqual(session._companion.config.development_battle_channel, enabled)
