"""Launcher task ownership and failure ordering; native protocol tested separately."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from emerald_multiplayer.battle_admission_cleanup import AdmissionCleanupCompletion
from emerald_multiplayer.battle_session import RenewedBattleSession
from emerald_multiplayer.launcher_session import LauncherSessionError
import test_launcher_battle_recovery as fixture


class LauncherAdmissionCleanupTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.LauncherBattleRecoveryTests.setUp
    asyncTearDown = fixture.LauncherBattleRecoveryTests.asyncTearDown
    write_intent = fixture.LauncherBattleRecoveryTests.write_intent
    provisional = fixture.LauncherBattleRecoveryTests.provisional
    terminal_preserver = fixture.LauncherBattleRecoveryTests.terminal_preserver

    def enable(self):
        self.intent = self.provisional()
        self.c.config.battle_admission_cleanup_abi_version = 1
        self.session._manifest["battle_admission_cleanup_abi_version"] = 1
        self.c.connected = True
        self.session._save_failed = False

    async def waiting_menu(self):
        s, i = self.session, self.intent
        menu = SimpleNamespace(_admission_identity=(i.battle_id, i.generation), _battle_latched=True,
            _battle_preparing=True, bridge=self.c._bridge)
        started = asyncio.Event()
        async def wait():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                s._native_menu_abandon_battle_preparation(menu)
                self.c._live_save_owner = self.c._live_battle_owner = None
        task = asyncio.create_task(wait())
        self.addAsyncCleanup(self.drain, task)
        menu._task = task
        self.c._bridge.menu_session = menu
        s._interaction = task
        s._battle_menu_preparation = (task, menu, i)
        self.c._live_save_owner = self.c._live_battle_owner = task
        await started.wait()
        return task, menu

    async def drain(self, task):
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_old_build_and_full_bind_never_offer_or_dispatch_cleanup(self):
        self.assertFalse(self.session.can_cancel_battle_entry)
        with self.assertRaises(LauncherSessionError) as error:
            await self.session.cancel_battle_entry()
        self.assertEqual(error.exception.code, "admission_cleanup_unsupported")
        self.c.config.battle_admission_cleanup_abi_version = 1
        self.session._manifest["battle_admission_cleanup_abi_version"] = 1
        self.assertFalse(self.session.can_cancel_battle_entry)
        with self.assertRaises(LauncherSessionError):
            await self.session.cancel_battle_entry()

    async def test_native_capacity_refusal_never_interrupts_original_menu_or_consent(self):
        self.enable()
        task, menu = await self.waiting_menu()
        # A real launcher scheduler loop remains alive but pauses under menu
        # ownership. Cancellation must not wait forever for that loop to exit.
        self.session._autosave_task = asyncio.create_task(self.session._schedule_autosave())
        self.assertTrue(self.session.can_cancel_battle_entry)
        with (patch('emerald_multiplayer.launcher_session.GameInstallation.verify'),
              patch('emerald_multiplayer.battle_admission_cleanup.AdmissionCleanupSession') as cls):
            cleanup = cls.return_value
            cleanup.revocation_requested = False
            cleanup.revoke_before_menu_drain = AsyncMock(side_effect=ValueError("native capacity unavailable"))
            cleanup.run = AsyncMock()
            with self.assertRaises(LauncherSessionError):
                await asyncio.wait_for(self.session.cancel_battle_entry(), 2)
            self.assertFalse(task.done())
            self.assertIs(self.session._interaction, task)
            self.assertFalse(self.session._save_failed)
            self.assertFalse(self.session._battle_recovery_failed)
            self.assertFalse(self.session._autosave_task.done())
            cleanup.run.assert_not_called()

    async def test_revocation_precedes_exact_menu_drain_and_hold_precedes_adoption(self):
        self.enable()
        task, menu = await self.waiting_menu()
        order = []
        i = self.intent
        completion = AdmissionCleanupCompletion(i.battle_id, i.generation, i.canonical_revision, i.canonical_sha256,
            RenewedBattleSession(i.world_id, i.player_id, i.build_id, i.ruleset_id, i.save_profile,
                i.server_epoch, i.lease_epoch, i.incarnation, i.runtime_id))
        async def revoke():
            self.assertFalse(task.done())
            self.assertIs(self.c._live_save_owner, task)
            order.append("durable_host_revocation")
        async def hold():
            self.assertTrue(task.done())
            self.assertIsNone(self.session._battle_menu_preparation)
            self.assertEqual(order, ["durable_host_revocation"])
            order.append("native_hold_and_host_ack")
            return completion
        async def adopt(*args, **kwargs):
            self.assertEqual(order, ["durable_host_revocation", "native_hold_and_host_ack"])
            self.assertTrue(kwargs["cleanup"])
            self.assertEqual(args[:2], (completion, i))
            order.append("fresh_saver_handoff")
        with (patch('emerald_multiplayer.launcher_session.GameInstallation.verify'),
              patch('emerald_multiplayer.battle_admission_cleanup.AdmissionCleanupSession') as cls,
              patch.object(self.session, '_adopt_battle_completion', side_effect=adopt)):
            cls.return_value.revocation_requested = True
            cls.return_value.revoke_before_menu_drain = AsyncMock(side_effect=revoke)
            cls.return_value.run = AsyncMock(side_effect=hold)
            self.assertEqual(await self.session.cancel_battle_entry(), completion)
        self.assertEqual(order[-1], "fresh_saver_handoff")
        self.assertIsNone(self.session._interaction)
        self.assertIsNone(self.session._battle_recovery_task)

    async def test_host_refuses_reserved_race_without_canceling_original_task(self):
        self.enable()
        task, _ = await self.waiting_menu()
        with (patch('emerald_multiplayer.launcher_session.GameInstallation.verify'),
              patch('emerald_multiplayer.battle_admission_cleanup.AdmissionCleanupSession') as cls):
            cls.return_value.revocation_requested = True
            cls.return_value.revoke_before_menu_drain = AsyncMock(side_effect=ValueError("already reserved"))
            with self.assertRaises(LauncherSessionError):
                await self.session.cancel_battle_entry()
            self.assertFalse(task.done())
            self.assertIs(self.session._interaction, task)
            self.assertEqual(self.session.status.code, "admission_cleanup_held")

    async def test_cleanup_successor_preservation_allows_close_and_fresh_continue_after_uncertain_handoff(self):
        from emerald_multiplayer.battle_admission_intent import FILENAME, BattleAdmissionIntent
        self.enable()
        (self.session._profile_directory / FILENAME).unlink()
        self.c.connected = False
        self.session._save_failed = True
        successor = await self.terminal_preserver()
        self.assertIs(type(self.session._battle_recovery_intent), BattleAdmissionIntent)
        self.assertTrue(self.session._terminal_successor_preserved())
        self.assertFalse(self.session._retain_interrupted_core())
        self.assertEqual(self.session.status.code, "host_loss_preserved")
        self.assertFalse(self.session.status.battle_recovery_available)
        self.assertFalse(self.session.status.admission_cleanup_available)
        self.assertIs(self.session._battle_handoff_successor, successor)
        self.assertEqual(self.session._binding, self.original_binding)
        self.assertTrue(self.session._save_failed)

    async def test_cleanup_successor_cannot_close_wrong_original_or_unfinished_preservation(self):
        from emerald_multiplayer.battle_admission_intent import FILENAME, publish_admission_intent
        from emerald_multiplayer.emergency_save import EmergencyResult
        self.enable()
        (self.session._profile_directory / FILENAME).unlink()
        self.c.connected = False
        self.session._save_failed = True
        successor = await self.terminal_preserver()
        cases = ((self.session, "_runtime", object()),
            (self.c, "_bridge", SimpleNamespace(incarnation=20)),
            (self.c, "_emergency_controller", object()),
            (successor, "base_revision", 3), (successor, "result", EmergencyResult("unsaved_held")),
            (self.c, "_live_save_owner", object()))
        for owner, key, changed in cases:
            original = getattr(owner, key)
            try:
                setattr(owner, key, changed)
                self.assertFalse(self.session._terminal_successor_preserved())
                self.assertTrue(self.session._retain_interrupted_core())
                self.assertNotEqual(self.session.status.code, "host_loss_preserved")
            finally:
                setattr(owner, key, original)
        publish_admission_intent(self.session._profile_directory / FILENAME, self.intent)
        self.assertFalse(self.session._terminal_successor_preserved())
        self.assertTrue(self.session._retain_interrupted_core())


if __name__ == "__main__":
    unittest.main()
