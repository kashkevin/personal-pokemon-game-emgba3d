"""Real ownership store/Flash recovery with a strict native mailbox fixture."""
import asyncio
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4
import zlib

from emerald_multiplayer.cold_start import ColdStartError, ColdStartRecovery
from emerald_multiplayer.companion import Companion
from emerald_multiplayer.emergency_save import EmergencySaveController, load_closed_emergency
from emerald_multiplayer.flash import FLASH_SIZE, inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, _atomic, _json_bytes
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.save_mailbox import Opcode, SaveControl, State, Status
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from test_cold_start import ClosedTradeCompanion
from test_live_checkpoint import FakeCompanion
from test_live_checkpoint import checkpoint_metadata
from test_live_trade import TradeCompanion
from test_ownership_storage import owned_flash, source_flash


class EmergencyCompanion(TradeCompanion):
    emergency_save_rpc = Companion.emergency_save_rpc

    def __init__(self, *args):
        super().__init__(*args)
        self._bridge = SimpleNamespace(save_capable=True, emergency_save_capable=True,
                                       window_capable=True, incarnation=self.save_incarnation)
        self.config.emergency_save_abi_version = 2
        self.config.save_window_enabled = True
        self._emergency_authority = self._emergency_controller = None
        self._reconnect_blocked = False
        self._save_pending = {}
        self.emergency_commands = []
        self.emergency_active = self.preserved = self.unsafe = self.lose_preserve = False
        self.command_wait = None
        self._fault_once = False

    async def checkpoint_rpc(self, operation, **fields):
        return await FakeCompanion.checkpoint_rpc(self, operation, **fields)

    def lose_host(self):
        self._reconnect_blocked = True
        self._emergency_controller.connection_lost()
        self.connected = False
        self.world_id = self.session_epoch = self.save_profile = None

    async def _dispatch_save_control(self, bridge, control, timeout):
        self.emergency_commands.append(control)
        self.assert_owner = self._live_save_owner is asyncio.current_task()
        if self.command_wait is not None:
            await self.command_wait.wait()
        if self.last_control == control:
            return self.last_response
        assert control.sequence > self.rom_sequence
        opcode = control.opcode
        data, offset, status, window = b"", control.offset, Status.OK, None
        if opcode == Opcode.BEGIN_EMERGENCY_EXPORT and getattr(self, "admission_latched", False):
            return replace(control, status=Status.BATTLE_ADMISSION)
        if opcode in (Opcode.BEGIN_EMERGENCY_EXPORT, Opcode.PROMOTE_EMERGENCY_EXPORT):
            if opcode == Opcode.PROMOTE_EMERGENCY_EXPORT:
                assert self.phase == State.EXPORTING
                assert (self.operation, self.revision) == (control.request_id, control.revision)
            else:
                assert self.phase == State.BOUND
            self.emergency_active = True
            self.operation, self.revision = control.request_id, control.revision
            self.offset = self.crc = 0
            if self.unsafe:
                self.phase, status = State.EMERGENCY_UNSAVED, Status.UNSAFE
            else:
                self.phase = State.EXPORTING
                parsed = inspect_flash(self.rom_flash, save_profile=OWNERSHIP_PROFILE)
                first = struct.unpack_from("<H", self.rom_flash, parsed.metadata.bank*14*4096+4084)[0]
                data = struct.pack("<II32s", parsed.metadata.counter, (-first)%14, self.rng)
        elif opcode in (Opcode.READ, Opcode.READ_WINDOW):
            assert self.emergency_active and self.phase == State.EXPORTING and control.offset == self.offset
            block = self.rom_flash[offset:offset + (4096 if opcode == Opcode.READ_WINDOW else 128)]
            self.offset += len(block)
            self.crc = zlib.crc32(block, self.crc)
            data = struct.pack("<I", zlib.crc32(block)) if opcode == Opcode.READ_WINDOW else block
            window = block if opcode == Opcode.READ_WINDOW else None
        elif opcode == Opcode.PRESERVE_EMERGENCY:
            assert self.phase == State.EXPORTING and self.offset == FLASH_SIZE
            # Native receipt must follow both durable files and local readback.
            intent = json.loads((self.directory / "pending-export.json").read_text())
            assert intent["operation_id"] == control.request_id
            assert (self.directory / (control.request_id + ".flash")).read_bytes() == self.rom_flash
            assert json.loads((self.directory / "pending-emergency.json").read_text())["state"] == "bytes_durable"
            self.phase, self.preserved = State.EMERGENCY_PRESERVED, True
            data = struct.pack("<I", self.crc)
        elif opcode == Opcode.QUERY_EMERGENCY:
            data = struct.pack("<II16sIIIIII", 7, self.phase, UUID(self.operation).bytes,
                               control.session_epoch, control.incarnation, self.revision, self.offset, self.crc, 0)
            offset = self.offset
        else:
            raise AssertionError("emergency authority attempted a release or mutation")
        response = replace(control, data=data, offset=offset, status=status)
        response = SaveControl.unpack(response.pack()).validate_response()
        result = (response, window) if opcode == Opcode.READ_WINDOW else response
        if opcode != Opcode.QUERY_EMERGENCY:
            self.rom_sequence, self.last_control, self.last_response = control.sequence, control, result
        if opcode == Opcode.PRESERVE_EMERGENCY and self.lose_preserve and not self._fault_once:
            self._fault_once = True
            raise asyncio.TimeoutError()
        return result


class EmergencySaveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.private = self.root / "private"
        self.private.mkdir()
        self.store = TradeCheckpointStore(self.root / "world.sqlite3", "a"*64, "rules-v1")
        self.store.begin_server_boot()
        self.player = self.store.create_player("One")
        self.lease = self.store.acquire_lease(self.player.player_id, self.player.credential)
        self.store.enroll_player(self.player.player_id, source_flash())
        self.grant = self.store.reserve_instances(self.player.player_id, self.lease, str(uuid4()), 0, 2, 32)
        payload = owned_flash(self.grant, next_serial=self.grant.start+1)
        self.store.commit_checkpoint(self.player.player_id, self.lease, str(uuid4()), 0, payload,
                                     self.store.build_id, self.store.ruleset_id, OWNERSHIP_PROFILE)
        self.c = EmergencyCompanion(self.store, self.player, self.lease, payload, self.private,
                                    {self.player.player_id: self.lease})
        _atomic(self.private / (self.grant.grant_id + ".grant.json"), _json_bytes(asdict(self.grant)))
        self.controller = EmergencySaveController(self.c, self.private)
        self.save = self.root / "character.sav"
        self.save.write_bytes(b"the running native file remains owned")

    async def asyncTearDown(self):
        if self.controller.task is not None and not self.controller.task.done():
            self.c.command_wait.set()
            await self.controller.drain()
        self.store.close()
        self.temp.cleanup()

    async def arm(self):
        self.assertEqual((await self.controller.arm(1)).state, "armed")

    async def preserve(self):
        self.c.lose_host()
        return await self.controller.drain()

    def closed(self):
        self.store.release_lease(self.player.player_id, self.lease)
        self.lease = self.store.acquire_lease(self.player.player_id, self.player.credential)
        return ClosedTradeCompanion(self.store, self.player, self.lease, None)

    async def test_preserves_exact_bytes_and_rejoins_under_new_lease_without_touching_live_save(self):
        await self.arm()
        before = self.save.read_bytes()
        result = await self.preserve()
        self.assertTrue(result.can_close)
        self.assertEqual(result.state, "preserved")
        self.assertEqual(self.save.read_bytes(), before)
        self.assertEqual(self.store.read_checkpoint(self.player.player_id, self.lease).revision, 1)
        self.assertTrue(self.c.assert_owner)
        self.assertTrue(self.c.preserved)
        self.assertFalse(self.c.connected)
        fresh = self.closed()
        async with ColdStartRecovery(fresh, self.private, self.save).open() as recovered:
            self.assertEqual(recovered.mirror.revision, 2)
            self.assertEqual(self.save.read_bytes(), self.c.rom_flash)
        self.assertFalse(self.controller.path.exists())
        self.assertFalse((self.private / "pending-export.json").exists())
        head = self.store.read_checkpoint(self.player.player_id, self.lease)
        self.assertEqual((head.request_id, head.sha256), (result.operation_id, result.sha256))
        self.store.integrity_check()

    async def test_lost_preservation_receipt_retries_exact_command(self):
        await self.arm()
        self.c.lose_preserve = True
        self.assertTrue((await self.preserve()).can_close)
        receipts = [c for c in self.c.emergency_commands if c.opcode == Opcode.PRESERVE_EMERGENCY]
        self.assertEqual(len(receipts), 2)
        self.assertEqual(receipts[0], receipts[1])

    async def test_unsafe_core_remains_unsaved_and_blocks_new_core(self):
        await self.arm()
        self.c.unsafe = True
        result = await self.preserve()
        self.assertEqual(result.state, "unsaved_held")
        self.assertFalse(result.can_close)
        self.assertTrue(self.c.emergency_active)
        self.assertFalse((self.private / "pending-export.json").exists())
        fresh = self.closed()
        with self.assertRaises(ColdStartError):
            async with ColdStartRecovery(fresh, self.private, self.save).open():
                self.fail("unsafe core must remain retained")

    async def test_neutral_reset_drain_precedes_freeze_under_the_same_authority(self):
        await self.arm()
        self.c.unsafe = True
        called = []
        async def drain(session):
            self.assertEqual(session, self.controller.session)
            self.assertIs(self.c._live_save_owner, asyncio.current_task())
            self.assertTrue(self.c.live_checkpoint_lock.locked())
            self.assertFalse(self.c.connected)
            self.assertTrue(self.c._reconnect_blocked)
            self.assertEqual(self.c.emergency_commands, [])
            self.assertEqual(json.loads(self.controller.path.read_text())["state"], "holding")
            called.append(session)
            self.c.unsafe = False
            return True
        self.c._bridge.reset_session = SimpleNamespace(drain_before_emergency=drain)
        self.assertTrue((await self.preserve()).can_close)
        self.assertEqual(called, [self.controller.session])
        self.assertEqual(self.c.emergency_commands[0].opcode, Opcode.BEGIN_EMERGENCY_EXPORT)

    async def test_reset_cancel_refusal_still_freezes_unsafe_core(self):
        await self.arm()
        self.c.unsafe = True
        async def drain(session):
            return False
        self.c._bridge.reset_session = SimpleNamespace(drain_before_emergency=drain)
        result = await self.preserve()
        self.assertEqual(result.state, "unsaved_held")
        self.assertFalse(result.can_close)
        self.assertTrue(self.c.emergency_active)
        self.assertEqual([c.opcode for c in self.c.emergency_commands], [Opcode.BEGIN_EMERGENCY_EXPORT])

    async def test_unknown_reset_cancel_receipt_still_freezes_unsafe_core(self):
        await self.arm()
        self.c.unsafe = True
        async def drain(session):
            raise asyncio.TimeoutError()
        self.c._bridge.reset_session = SimpleNamespace(drain_before_emergency=drain)
        result = await self.preserve()
        self.assertEqual(result.state, "unsaved_held")
        self.assertTrue(self.c.emergency_active)
        self.assertFalse(self.c.preserved)

    async def test_disk_failure_never_sends_preservation_receipt(self):
        await self.arm()
        original = _atomic
        def fail_payload(path, data):
            if str(path).endswith(".flash"):
                raise OSError("disk unavailable")
            return original(path, data)
        with patch("emerald_multiplayer.live_checkpoint._atomic", side_effect=fail_payload):
            result = await self.preserve()
        self.assertFalse(result.can_close)
        self.assertNotIn(Opcode.PRESERVE_EMERGENCY, [c.opcode for c in self.c.emergency_commands])

    async def test_initial_intent_disk_failure_still_stops_offline_play(self):
        await self.arm()
        with patch("emerald_multiplayer.emergency_save._atomic", side_effect=OSError("disk unavailable")):
            result = await self.preserve()
        self.assertEqual(result.state, "unsaved_held")
        self.assertFalse(result.can_close)
        self.assertTrue(self.c.assert_owner)
        self.assertTrue(self.c.emergency_active)
        self.assertFalse(self.c.preserved)
        self.assertEqual([c.opcode for c in self.c.emergency_commands], [Opcode.BEGIN_EMERGENCY_EXPORT])

    async def test_inflight_export_promotes_same_uuid_and_never_rewrites_an_existing_intent(self):
        await self.arm()
        operation = str(uuid4())
        self.controller.checkpoint_started(self.controller.session, operation, 1)
        self.c.phase, self.c.operation, self.c.revision = State.EXPORTING, operation, 2
        self.c.offset = 4096
        live = self.controller.coordinator
        intent = live._intent(self.controller.session, operation, 1, self.c.rom_flash)
        live._save_pending(intent, self.c.rom_flash)
        before = live.pending_path.read_bytes()
        drains = []
        async def drain(session):
            drains.append(session)
            return False
        self.c._bridge.reset_session = SimpleNamespace(drain_before_emergency=drain)
        result = await self.preserve()
        self.assertEqual(result.operation_id, operation)
        self.assertTrue(result.can_close)
        self.assertEqual(self.c.emergency_commands[0].opcode, Opcode.PROMOTE_EMERGENCY_EXPORT)
        self.assertEqual(live.pending_path.read_bytes(), before)
        self.assertEqual(drains, [])

    async def test_conflicting_previous_intent_retains_both_without_preserve_receipt(self):
        await self.arm()
        live = self.controller.coordinator
        intent = live._intent(self.controller.session, str(uuid4()), 1, self.c.rom_flash)
        live._save_pending(intent, self.c.rom_flash)
        before = live.pending_path.read_bytes()
        self.assertFalse((await self.preserve()).can_close)
        self.assertEqual(live.pending_path.read_bytes(), before)
        self.assertFalse(self.c.preserved)

    async def test_replacement_bridge_never_inherits_local_authority(self):
        await self.arm()
        self.c._bridge = SimpleNamespace(**vars(self.c._bridge))
        self.assertFalse((await self.preserve()).can_close)
        self.assertEqual(self.c.emergency_commands, [])

    async def test_authority_refuses_connected_release_wrong_operation_and_wrong_task(self):
        await self.arm()
        self.assertTrue((await self.preserve()).can_close)
        authority = self.c._emergency_authority
        command = self.c.emergency_commands[0]
        with self.assertRaises(ValueError):
            await self.c.emergency_save_rpc(authority, command)
        self.c._live_save_owner = asyncio.current_task()
        for changed in (replace(command, opcode=Opcode.CANCEL), replace(command, opcode=Opcode.END, offset=FLASH_SIZE)):
            with self.assertRaises(ValueError):
                await self.c.emergency_save_rpc(authority, changed)
        with self.assertRaises(ConnectionError):
            await self.c.emergency_save_rpc(authority, replace(command, request_id=str(uuid4())))
        self.c.connected = True
        with self.assertRaises(ConnectionError):
            await self.c.emergency_save_rpc(authority, command)
        self.c._live_save_owner = None

    async def test_repeated_cancellation_drains_preservation_before_propagating(self):
        await self.arm()
        self.c.command_wait = asyncio.Event()
        self.c.lose_host()
        task = asyncio.create_task(self.controller.drain())
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        self.assertFalse(self.controller.task.done())
        self.c.command_wait.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.controller.result.can_close)
        self.assertTrue(self.c.preserved)

    async def test_newer_head_cannot_rebase_preserved_candidate(self):
        await self.arm()
        self.assertTrue((await self.preserve()).can_close)
        self.store.commit_checkpoint(self.player.player_id, self.lease, str(uuid4()), 1, self.c.rom_flash,
                                     self.store.build_id, self.store.ruleset_id, OWNERSHIP_PROFILE)
        fresh = self.closed()
        with self.assertRaises(ValueError):
            async with ColdStartRecovery(fresh, self.private, self.save).open():
                self.fail("conflicting head must not authorize rebasing")
        self.assertTrue(self.controller.path.exists())

    async def test_completed_cleanup_retry_uses_exact_preserved_operation(self):
        await self.arm()
        result = await self.preserve()
        self.store.commit_checkpoint(self.player.player_id, self.lease, result.operation_id, 1, self.c.rom_flash,
                                     self.store.build_id, self.store.ruleset_id, OWNERSHIP_PROFILE)
        (self.private / "pending-export.json").unlink()
        fresh = self.closed()
        async with ColdStartRecovery(fresh, self.private, self.save).open() as recovered:
            self.assertEqual(recovered.mirror.revision, 2)
        self.assertFalse(self.controller.path.exists())

    async def test_bad_provenance_or_unqualified_build_never_arms(self):
        self.c.config.emergency_save_abi_version = 1
        with self.assertRaises(ValueError):
            await self.controller.arm(1)
        self.c.config.emergency_save_abi_version = 2
        grant = asdict(self.grant)
        grant["lease_epoch"] += 1
        _atomic(self.private / (self.grant.grant_id + ".grant.json"), _json_bytes(grant))
        with self.assertRaises(ValueError):
            await self.controller.arm(1)
        self.assertIsNone(self.c._emergency_controller)

    async def test_terminal_trade_adopts_only_exact_local_receipt_and_defers_grant_refresh(self):
        await self.arm()
        transaction, generation = str(uuid4()), str(uuid4())
        checkpoint = checkpoint_metadata(self.c.head())
        checkpoint.update(revision=3, request_id=transaction)
        intent = dict(expected_revision=1, transaction_id=transaction, generation=generation,
                      prepare_id=str(uuid4()), canonical=checkpoint, prepared=None,
                      world_id=self.c.world_id, player_id=self.player.player_id)
        with self.assertRaises(ValueError):
            self.controller.trade_completed(self.controller.session, intent, "applied")
        self.c._live_save_owner = asyncio.current_task()
        self.controller.trade_completed(self.controller.session, intent, "applied")
        self.assertEqual(self.controller.base_revision, 3)
        self.assertTrue(self.controller.needs_arm)
        # Exact terminal retry after a journal-unlink failure is idempotent.
        self.controller.trade_completed(self.controller.session, intent, "applied")
        changed = {**intent, "canonical": {**checkpoint, "sha256": "0"*64}}
        with self.assertRaises(ValueError):
            self.controller.trade_completed(self.controller.session, changed, "applied")
        self.assertEqual(self.controller.base_revision, 3)
        self.c._live_save_owner = None

    async def test_pending_trade_keeps_its_own_hold_without_export(self):
        await self.arm()
        (self.private / "pending-trade.json").write_text("{}")
        result = await self.preserve()
        self.assertEqual(result.state, "trade_waiting")
        self.assertFalse(result.can_close)
        self.assertEqual(self.c.emergency_commands, [])

    async def test_pending_battle_keeps_its_own_hold_without_export(self):
        await self.arm()
        (self.private / "pending-battle.json").write_text("{}")
        result = await self.preserve()
        self.assertEqual(result.state, "battle_waiting")
        self.assertFalse(result.can_close)
        self.assertEqual(self.c.emergency_commands, [])

    async def test_exact_native_enter_refusal_retires_only_unstarted_emergency_intent(self):
        await self.arm()
        self.c.config.battle_resume_abi_version = 1
        self.c.admission_latched = True
        original_sequence, original_flash = self.c.rom_sequence, self.c.rom_flash
        result = await self.preserve()
        self.assertEqual(result.state, "battle_waiting")
        self.assertFalse(result.can_close)
        self.assertFalse(self.c.emergency_active)
        self.assertEqual((self.c.rom_sequence, self.c.rom_flash), (original_sequence, original_flash))
        self.assertEqual([command.opcode for command in self.c.emergency_commands], [Opcode.BEGIN_EMERGENCY_EXPORT])
        self.assertFalse(self.controller.path.exists())
        self.assertFalse((self.private / "pending-export.json").exists())
        self.assertIsNone(self.c._emergency_authority)
        archives = list(self.private.glob("*.emergency-admission-refusal.json"))
        self.assertEqual(len(archives), 1)
        receipt = json.loads(archives[0].read_bytes())
        self.assertEqual(receipt["intent"]["state"], "holding")
        self.assertEqual(receipt["intent"]["operation_id"], self.c.emergency_commands[0].request_id)

    async def test_enter_refusal_requires_verified_resume_capability_and_exact_envelope(self):
        for capability, change in ((0, False), (1, True)):
            with self.subTest(capability=capability, changed_envelope=change):
                self.controller = EmergencySaveController(self.c, self.private)
                await self.arm()
                self.c.config.battle_resume_abi_version = capability
                async def refuse(bridge, control, timeout):
                    return replace(control, status=Status.BATTLE_ADMISSION,
                                   revision=control.revision + int(change))
                with patch.object(self.c, "_dispatch_save_control", refuse):
                    result = await self.preserve()
                self.assertEqual(result.state, "unsaved_held")
                self.assertFalse(result.can_close)
                self.assertTrue(self.controller.path.exists())
                self.assertEqual(list(self.private.glob("*.emergency-admission-refusal.json")), [])
                # Restore fixture authentication only; neither refusal is an
                # authorized production cleanup or a replacement-core path.
                self.controller.path.unlink()
                self.c._emergency_controller = self.c._emergency_authority = None
                self.c.connected = True
                self.c.world_id, self.c.session_epoch, self.c.save_profile = self.controller.identity["world_id"], self.lease, OWNERSHIP_PROFILE

    async def test_enter_refusal_archive_failure_keeps_uncertain_intent(self):
        await self.arm()
        self.c.config.battle_resume_abi_version = 1
        self.c.admission_latched = True
        def fail_archive(path, data):
            if str(path).endswith(".emergency-admission-refusal.json"):
                raise OSError("disk refused durable receipt")
            return _atomic(path, data)
        with patch("emerald_multiplayer.emergency_save._atomic", fail_archive):
            result = await self.preserve()
        self.assertEqual(result.state, "unsaved_held")
        self.assertFalse(result.can_close)
        self.assertEqual(json.loads(self.controller.path.read_bytes())["state"], "uncertain")
        self.assertIsNotNone(self.c._emergency_authority)
        self.assertFalse((self.private / "pending-export.json").exists())

    async def test_wrong_grant_range_never_grants_preservation_authority(self):
        grant = asdict(self.grant)
        grant["end_exclusive"] += 1
        _atomic(self.private / (self.grant.grant_id + ".grant.json"), _json_bytes(grant))
        with self.assertRaises(ValueError):
            await self.controller.arm(1)
        self.assertIsNone(self.c._emergency_controller)


if __name__ == "__main__":
    unittest.main()
