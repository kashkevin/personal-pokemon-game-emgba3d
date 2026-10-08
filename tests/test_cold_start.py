"""Closed-start interruption tests: real SQLite/Flash/client, no emulator."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.checkpoint_client import CheckpointError
from emerald_multiplayer.checkpoint_mirror import (
    MirrorError, MirrorLease, inspect_mirror, inspect_mirror_held,
    recoveries_path, restore_checkpoint, restore_checkpoint_held, sidecar_path,
)
from emerald_multiplayer.cold_start import ColdStartError, ColdStartRecovery
from emerald_multiplayer.companion import TradeError
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.live_trade import LiveTradeCoordinator, LiveTradeError
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.storage import StorageError
from emerald_multiplayer.trade_desk import TradeDesk
from emerald_multiplayer.trade_flash import build_party_swap
from emerald_multiplayer.trade_protocol import validate_trade_reply
from emerald_multiplayer.trade_storage import TradeCheckpointStore, TradeSide
from test_flash import make_flash
from test_live_checkpoint import FakeCompanion, checkpoint_metadata
from test_ownership_storage import source_flash, owned_flash


class ClosedCompanion(FakeCompanion):
    def __init__(self, directory, *, enroll=True):
        super().__init__(directory, enroll=enroll)
        self.config.server_credential = self.identity.credential
        self.config.trade_enabled = False
        self.server_epoch = self.store.metadata.server_epoch
        self._bridge = None
        self.checkpoint_hook = None

    async def checkpoint_rpc(self, operation, **fields):
        response = await super().checkpoint_rpc(operation, **fields)
        if self.checkpoint_hook is not None:
            await self.checkpoint_hook(operation, response)
        return response

    async def save_rpc(self, *args, **kwargs):
        raise AssertionError("closed recovery must never call a ROM mailbox")


class ClosedTradeCompanion(ClosedCompanion):
    def __init__(self, store, player, lease, desk):
        self.store, self.identity, self.session_epoch, self.desk = store, player, lease, desk
        self.world_id, self.server_epoch = store.metadata.world_id, store.metadata.server_epoch
        self.config = SimpleNamespace(build_id=store.build_id, ruleset_id=store.ruleset_id,
            player_id=player.player_id, server_credential=player.credential,
            trade_enabled=True, ownership_enabled=True)
        self.connected, self.save_profile, self._bridge = True, OWNERSHIP_PROFILE, None
        self.live_checkpoint_lock = asyncio.Lock()
        self._live_save_owner = None
        self.commands, self.server_calls, self.upload_payloads = [], [], []
        self.uploads, self.pending_journal = {}, None
        self.commit_hook = self.checkpoint_hook = self.trade_hook = None
        self.lose_commit_ack = False

    async def trade_rpc(self, operation, *, request_id=None, **fields):
        self.server_calls.append(("trade_"+operation, fields))
        actor = (self.config.player_id, self.session_epoch)
        try:
            if operation == "pending":
                result = dict(recoveries=[dict(transaction_id=r.transaction_id, sequence=r.sequence,
                    outcome_fingerprint=r.outcome_fingerprint, checkpoint=checkpoint_metadata(r.checkpoint))
                    for r in self.store.pending_trade_recovery(*actor)])
            elif operation == "ack":
                self.store.acknowledge_trade(*actor, fields["transaction_id"], fields["revision"], fields["sha256"])
                result = dict(trade=dict(transaction_id=fields["transaction_id"], state="acknowledged",
                    revision=fields["revision"], sha256=fields["sha256"]))
            elif operation == "status":
                result = dict(trade=self.desk.status(*actor, fields["transaction_id"]))
            elif operation == "cancel":
                result = dict(trade=self.desk.cancel(*actor, fields["transaction_id"], fields["generation"]))
            else:
                raise AssertionError("cold recovery cannot offer or confirm")
        except StorageError as error:
            raise TradeError(error.code, error.message) from error
        response = validate_trade_reply(dict(type="trade_result", protocol=1, session_epoch=self.session_epoch,
            request_id=request_id or str(uuid4()), operation=operation, world_id=self.world_id,
            player_id=self.config.player_id, **result), self.config, self.save_profile, self.world_id, self.session_epoch)
        if self.trade_hook is not None:
            await self.trade_hook(operation, response)
        return response


class ColdStartTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.private = self.root / "private"
        self.private.mkdir()
        self.save = self.root / "player.sav"
        self.c = ClosedCompanion(self.root)
        self.gate = ColdStartRecovery(self.c, self.private, self.save)

    def tearDown(self):
        self.c.close()
        self.temp.cleanup()

    def pending(self, *, base=1, payload=None):
        live = LiveCheckpointCoordinator(self.c, self.private)
        payload = payload or make_flash(counter=3)
        intent = live._intent((self.c.world_id, self.c.session_epoch, 2), str(uuid4()), base, payload)
        live._save_pending(intent, payload)
        return intent, payload

    async def assert_failure(self, error, code=None, gate=None):
        with self.assertRaises(error) as caught:
            async with (gate or self.gate).open():
                self.fail("failure must never authorize core startup")
        if code is not None:
            self.assertEqual(caught.exception.code, code)

    async def test_current_full_container_archives_invalid_local_and_holds_whole_core_lifetime(self):
        self.save.write_bytes(b"local progress is preserved")
        sidecar_path(self.save).write_bytes(b"invalid sidecar")
        async def inspect_lock(operation, response):
            with self.assertRaises(MirrorError) as caught:
                with MirrorLease(self.save):
                    self.fail("lock gap during network reconciliation")
            self.assertEqual(caught.exception.code, "mirror_active")
        self.c.checkpoint_hook = inspect_lock
        async with self.gate.open() as result:
            self.assertEqual(inspect_mirror_held(result.lease), result.mirror)
            self.assertEqual(self.save.read_bytes(), self.c.head().payload)
            self.assertEqual(len(self.save.read_bytes()), 131088)
            self.assertTrue(result.evidence_path.exists())
            with self.assertRaises(MirrorError):
                inspect_mirror(self.save)
            alternate = ColdStartRecovery(self.c, self.private, self.root / "another.sav")
            await self.assert_failure(ColdStartError, "startup_active", alternate)
        archive, = recoveries_path(self.save).iterdir()
        self.assertEqual((archive / self.save.name).read_bytes(), b"local progress is preserved")
        self.assertEqual((archive / sidecar_path(self.save).name).read_bytes(), b"invalid sidecar")
        self.assertEqual(inspect_mirror(self.save), result.mirror)
        self.assertIsNone(self.c._live_save_owner)

    async def test_active_lock_rejects_before_rpc_or_file_change(self):
        self.save.write_bytes(b"original")
        with MirrorLease(self.save):
            await self.assert_failure(MirrorError, "mirror_active")
        self.assertFalse(self.c.server_calls)
        self.assertEqual(self.save.read_bytes(), b"original")

    async def test_uncertain_ordinary_commit_exact_retry_after_restart(self):
        intent, payload = self.pending()
        self.c.store.commit_checkpoint(self.c.config.player_id, self.c.session_epoch,
            intent["operation_id"], 1, payload, self.c.config.build_id, self.c.config.ruleset_id, self.c.save_profile)
        self.c.restart(); self.c.server_epoch = self.c.store.metadata.server_epoch
        self.save.write_bytes(b"newer unsynchronized native bytes")
        raw = self.gate.export_path.read_bytes()
        async def original_archived(operation, response):
            if operation == "begin":
                copies = list((self.private / "closed-recoveries").glob("*/pending-export.json"))
                self.assertEqual([copy.read_bytes() for copy in copies], [raw])
        self.c.checkpoint_hook = original_archived
        async with self.gate.open() as result:
            self.assertEqual(result.mirror.request_id, intent["operation_id"])
            self.assertEqual(result.mirror.revision, 2)
        self.assertEqual(self.c.upload_payloads, [(intent["operation_id"], 1, payload)])
        self.assertFalse(self.gate.export_path.exists())

    async def test_lost_ordinary_commit_ack_retains_journal_then_exactly_recovers(self):
        intent, payload = self.pending()
        raw = self.gate.export_path.read_bytes()
        self.c.lose_commit_ack = True
        await self.assert_failure(asyncio.TimeoutError)
        self.assertEqual(self.gate.export_path.read_bytes(), raw)
        self.assertFalse(self.save.exists())
        async with self.gate.open() as result:
            self.assertEqual(result.mirror.revision, 2)
            self.assertEqual(result.mirror.request_id, intent["operation_id"])
        self.assertEqual(self.c.head().payload, payload)
        self.assertEqual(self.c.head().revision, 2)

    async def test_current_head_installed_after_historical_ordinary_retry(self):
        intent, payload = self.pending()
        self.c.store.commit_checkpoint(self.c.config.player_id, self.c.session_epoch,
            intent["operation_id"], 1, payload, self.c.config.build_id, self.c.config.ruleset_id, self.c.save_profile)
        newer = self.c.advance_head(make_flash(counter=4, with_rtc=True))
        async with self.gate.open() as result:
            self.assertEqual(result.mirror.revision, 3)
            self.assertEqual(self.save.read_bytes(), newer.payload)

    async def test_missing_canonical_and_credentials_never_open_or_replace_save(self):
        self.c.store.release_lease(self.c.config.player_id, self.c.session_epoch)
        self.c.store.close()
        self.c = ClosedCompanion(self.root / "empty", enroll=False)
        self.gate = ColdStartRecovery(self.c, self.private, self.save)
        await self.assert_failure(ColdStartError, "enrollment_required")
        self.assertFalse(self.save.exists())
        self.c.config.server_credential = None
        self.c.server_calls.clear()
        await self.assert_failure(ColdStartError, "authentication_required")
        self.assertFalse(self.c.server_calls)

    async def test_bridge_connecting_during_download_blocks_restore(self):
        self.pending()
        self.save.write_bytes(b"original native save")
        async def bridge_joins(operation, response):
            if operation == "read":
                self.c._bridge = object()
        self.c.checkpoint_hook = bridge_joins
        await self.assert_failure(ColdStartError, "game_active")
        self.assertEqual(self.save.read_bytes(), b"original native save")
        self.assertTrue(self.gate.export_path.exists())

    async def test_changed_lease_and_head_during_download_preserve_intent(self):
        self.pending()
        async def reconnect(operation, response):
            if operation == "read":
                self.c.session_epoch += 1
        self.c.checkpoint_hook = reconnect
        await self.assert_failure(ConnectionError)
        self.assertTrue(self.gate.export_path.exists())
        self.assertFalse(self.save.exists())

    async def test_restore_interruption_and_changed_head_never_clear_intent(self):
        self.pending()
        restore_checkpoint(self.save, self.c.head(), self.c.world_id)
        from emerald_multiplayer import checkpoint_mirror
        original = checkpoint_mirror.os.replace
        def interrupt_sidecar(source, target):
            if Path(target) == sidecar_path(self.save):
                raise OSError("power loss between mirror replacements")
            return original(source, target)
        with patch.object(checkpoint_mirror.os, "replace", side_effect=interrupt_sidecar):
            await self.assert_failure(MirrorError, "mirror_io_error")
        self.assertTrue(self.gate.export_path.exists())
        with self.assertRaises(MirrorError):
            inspect_mirror(self.save)
        async with self.gate.open() as result:
            self.assertEqual(result.mirror.revision, 2)
        self.assertFalse(self.gate.export_path.exists())

    async def test_head_changes_after_restore_blocks_yield_and_retry_uses_latest(self):
        self.pending()
        original = restore_checkpoint_held
        def advancing(lease, downloaded, world_id):
            info = original(lease, downloaded, world_id)
            self.c.advance_head(make_flash(counter=4))
            return info
        with patch("emerald_multiplayer.cold_start.restore_checkpoint_held", side_effect=advancing):
            await self.assert_failure(ColdStartError, "revision_conflict")
        self.assertTrue(self.gate.export_path.exists())
        async with self.gate.open() as result:
            self.assertEqual(result.mirror.revision, 3)

    async def test_corrupt_duplicate_foreign_and_changed_pending_never_discard(self):
        intent, payload = self.pending()
        original = self.gate.export_path.read_bytes()
        self.gate.export_path.write_bytes(original[:-2]+b',"schema":1}\n')
        await self.assert_failure(ValueError)
        self.gate.export_path.write_bytes(original)
        (self.private / (intent["operation_id"]+".flash")).write_bytes(payload[:-1]+b"x")
        await self.assert_failure(ValueError)
        self.assertTrue(self.gate.export_path.exists())
        self.assertFalse(self.c.server_calls)
        (self.private / (intent["operation_id"]+".flash")).write_bytes(payload)
        async def changed(operation, response):
            if operation == "read":
                self.gate.export_path.write_bytes(original+b" ")
        self.c.checkpoint_hook = changed
        await self.assert_failure(ColdStartError, "journal_changed")
        self.assertTrue(self.gate.export_path.exists())
        self.assertFalse(self.save.exists())

    async def test_cancelled_network_task_retains_intent_and_releases_lock(self):
        self.pending()
        async def interrupted(operation, response):
            raise asyncio.CancelledError()
        self.c.checkpoint_hook = interrupted
        await self.assert_failure(asyncio.CancelledError)
        with MirrorLease(self.save):
            pass
        self.assertTrue(self.gate.export_path.exists())
        self.assertIsNone(self.c._live_save_owner)
        self.assertFalse(self.c._cold_start_active)

    async def test_foreign_journal_and_incompatible_authenticated_profile_fail_before_rpc(self):
        intent, _ = self.pending()
        intent["world_id"] = str(uuid4())
        self.gate.export_path.write_text(json.dumps(intent))
        await self.assert_failure(ValueError, "journal_identity")
        self.assertFalse(self.c.server_calls)
        self.assertTrue(self.gate.export_path.exists())
        self.c.save_profile = OWNERSHIP_PROFILE
        await self.assert_failure(ColdStartError, "authentication_required")
        self.assertFalse(self.c.server_calls)


class ColdTradeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.private = self.root / "private"
        self.private.mkdir()
        self.save = self.root / "player.sav"
        self.store = TradeCheckpointStore(self.root / "world.sqlite3", "a"*64, "rules-v1")
        self.store.begin_server_boot()
        self.players, self.leases, self.grants = [], [], []
        for index, pid in enumerate((7, 9)):
            player = self.store.create_player("Player "+str(index))
            lease = self.store.acquire_lease(player.player_id, player.credential)
            self.store.enroll_player(player.player_id, source_flash(personalities=(pid,)))
            grant = self.store.reserve_instances(player.player_id, lease, str(uuid4()), 0, 2, 32)
            payload = owned_flash(grant, personalities=(pid,))
            self.store.commit_checkpoint(player.player_id, lease, str(uuid4()), 0, payload,
                                         self.store.build_id, self.store.ruleset_id, OWNERSHIP_PROFILE)
            self.players.append(player); self.leases.append(lease); self.grants.append(grant)
        self.current_leases = dict(zip((p.player_id for p in self.players), self.leases))
        self.desk = TradeDesk(self.store, self.current_leases.get)
        self.c = ClosedTradeCompanion(self.store, self.players[0], self.leases[0], self.desk)
        self.gate = ColdStartRecovery(self.c, self.private, self.save)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def commit(self, player, lease, payload, base, request_id=None):
        return self.store.commit_checkpoint(player.player_id, lease, request_id or str(uuid4()), base,
            payload, self.store.build_id, self.store.ruleset_id, OWNERSHIP_PROFILE)

    def journal(self, *, frozen=True, commit_prepare=False):
        tx = str(uuid4())
        proposal = self.desk.open(self.players[0].player_id, self.leases[0], self.players[1].player_id, tx)
        live = LiveTradeCoordinator(self.c, self.private)
        payload = owned_flash(self.grants[0], personalities=(7,), counter=3)
        intent = dict(schema=1, world_id=self.c.world_id, player_id=self.c.config.player_id,
            build_id=self.c.config.build_id, ruleset_id=self.c.config.ruleset_id, save_profile=OWNERSHIP_PROFILE,
            transaction_id=tx, generation=proposal["generation"], prepare_id=str(uuid4()), expected_revision=1,
            incarnation=2, runtime_id=self.c._live_trade_runtime_id,
            phase="frozen" if frozen else "intent", frozen_sha256=hashlib.sha256(payload).hexdigest() if frozen else None,
            prepared=None, fate=None, canonical=None, receipt_id=None, applied_sha256=None, control=None, export_ended=False)
        if frozen:
            (self.private / (intent["prepare_id"]+".flash")).write_bytes(payload)
        if commit_prepare:
            cp = self.commit(self.players[0], self.leases[0], payload, 1, intent["prepare_id"])
            intent["prepared"], intent["phase"], intent["export_ended"] = checkpoint_metadata(cp), "prepared", True
        live._save(intent)
        return intent, payload

    def paired(self, intent, payload):
        if self.c.head().revision == 1:
            self.commit(self.players[0], self.leases[0], payload, 1, intent["prepare_id"])
        other = owned_flash(self.grants[1], personalities=(9,), counter=3)
        self.commit(self.players[1], self.leases[1], other, 1)
        heads = [self.store.read_checkpoint(p.player_id, lease) for p, lease in zip(self.players, self.leases)]
        post = build_party_swap(heads[0].payload, self.grants[0].start, heads[1].payload, self.grants[1].start)
        sides = [TradeSide(p.player_id, lease, 2, grant.start, data)
                 for p, lease, grant, data in zip(self.players, self.leases, self.grants, post)]
        return self.store.commit_trade(intent["transaction_id"], *sides,
            self.store.build_id, self.store.ruleset_id, OWNERSHIP_PROFILE)

    async def failure(self, error, code=None):
        with self.assertRaises(error) as caught:
            async with self.gate.open():
                self.fail("unsafe startup was authorized")
        if code is not None:
            self.assertEqual(caught.exception.code, code)

    async def test_intent_without_frozen_bytes_authoritatively_cancels_and_archives_native(self):
        intent, _ = self.journal(frozen=False)
        self.save.write_bytes(b"closed native save may include unsynchronized progress")
        raw = self.gate.trade_path.read_bytes()
        async with self.gate.open() as result:
            self.assertEqual(result.mirror.revision, 1)
            self.assertEqual((result.evidence_path.parent / "pending-trade.json").read_bytes(), raw)
        self.assertFalse(self.gate.trade_path.exists())
        self.assertFalse(self.c.upload_payloads)
        self.assertEqual(self.desk.status(self.players[0].player_id, self.leases[0], intent["transaction_id"])["state"], "aborted")
        archive, = recoveries_path(self.save).iterdir()
        self.assertEqual((archive / self.save.name).read_bytes(), b"closed native save may include unsynchronized progress")

    async def test_status_or_cancel_timeout_never_means_absence(self):
        self.journal(frozen=False)
        self.save.write_bytes(b"native")
        async def lost(operation, reply):
            if operation in {"status", "cancel"}:
                raise asyncio.TimeoutError("uncertain server fate")
        self.c.trade_hook = lost
        await self.failure(asyncio.TimeoutError)
        self.assertTrue(self.gate.trade_path.exists())
        self.assertEqual(self.save.read_bytes(), b"native")
        self.c.trade_hook = None
        async with self.gate.open() as result:
            self.assertEqual(result.mirror.revision, 1)

    async def test_aborted_frozen_prepare_exact_upload_after_fresh_runtime(self):
        intent, payload = self.journal()
        self.c._live_trade_runtime_id = str(uuid4())
        self.store.release_lease(self.c.config.player_id, self.c.session_epoch)
        self.c.session_epoch = self.store.acquire_lease(self.c.config.player_id, self.c.identity.credential)
        self.current_leases[self.c.config.player_id] = self.c.session_epoch
        async with self.gate.open() as result:
            self.assertEqual(result.mirror.revision, 2)
            self.assertEqual(result.mirror.request_id, intent["prepare_id"])
        self.assertEqual(self.c.upload_payloads, [(intent["prepare_id"], 1, payload)])

    async def test_committed_pair_resolves_lost_prepare_ack_and_installs_only_own_result_before_ack(self):
        old = self.c.head()
        restore_checkpoint(self.save, old, self.c.world_id)
        intent, payload = self.journal()
        self.paired(intent, payload)
        async def applied_before_ack(operation, reply):
            if operation == "ack":
                applied, = (self.private / "closed-recoveries").glob("*/applied.json")
                envelope = json.loads(applied.read_bytes())
                self.assertEqual(envelope["record"]["mirror"]["revision"], 3)
                self.assertEqual(self.save.read_bytes(), self.c.head().payload)
        self.c.trade_hook = applied_before_ack
        async with self.gate.open() as result:
            self.assertEqual(result.mirror.revision, 3)
            self.assertEqual(result.mirror.request_id, intent["transaction_id"])
        self.assertEqual(self.c.upload_payloads, [(intent["prepare_id"], 1, payload)])
        self.assertFalse(self.gate.trade_path.exists())
        self.assertEqual(self.store.pending_trade_recovery(self.c.config.player_id, self.c.session_epoch), ())
        owner = inspect_ownership(inspect_flash(self.save.read_bytes(), save_profile=OWNERSHIP_PROFILE))
        self.assertEqual([r.serial for r in owner.records], [self.grants[1].start])
        self.store.integrity_check()

    async def test_server_pending_without_local_intent_recovers_current_head(self):
        intent, payload = self.journal()
        self.paired(intent, payload)
        self.gate.trade_path.unlink()
        async with self.gate.open() as result:
            self.assertEqual(result.mirror.revision, 3)
        self.assertFalse(self.c.upload_payloads)
        self.assertEqual(self.store.pending_trade_recovery(self.c.config.player_id, self.c.session_epoch), ())

    async def test_lost_trade_ack_retains_intent_and_durable_evidence_then_idempotent_retry(self):
        intent, payload = self.journal()
        self.paired(intent, payload)
        async def lost(operation, reply):
            if operation == "ack":
                raise asyncio.TimeoutError("durable ACK reply lost")
        self.c.trade_hook = lost
        await self.failure(asyncio.TimeoutError)
        self.assertTrue(self.gate.trade_path.exists())
        self.assertEqual(len(list((self.private / "closed-recoveries").glob("*/applied.json"))), 1)
        self.assertEqual(self.store.pending_trade_recovery(self.c.config.player_id, self.c.session_epoch), ())
        self.c.trade_hook = None
        async with self.gate.open() as result:
            self.assertEqual(result.mirror.revision, 3)
        self.assertFalse(self.gate.trade_path.exists())
        self.store.integrity_check()

    async def test_historical_committed_fate_never_overwrites_newer_head(self):
        intent, payload = self.journal()
        self.paired(intent, payload)
        head = self.c.head()
        self.store.acknowledge_trade(self.c.config.player_id, self.c.session_epoch,
            intent["transaction_id"], head.revision, head.sha256)
        self.commit(self.players[0], self.leases[0], head.payload, 3)
        self.save.write_bytes(b"untouched local newer progress")
        await self.failure(ColdStartError, "revision_conflict")
        self.assertTrue(self.gate.trade_path.exists())
        self.assertEqual(self.save.read_bytes(), b"untouched local newer progress")
        self.assertEqual(self.c.head().revision, 4)

    async def test_damaged_trade_bytes_and_failed_evidence_do_not_ack_or_clear(self):
        intent, payload = self.journal()
        self.paired(intent, payload)
        immutable = self.private / (intent["prepare_id"]+".flash")
        immutable.write_bytes(b"changed")
        await self.failure(LiveTradeError, "journal_bytes")
        self.assertFalse(self.c.server_calls)
        immutable.write_bytes(payload)
        with patch.object(self.gate, "_record", side_effect=OSError("disk unavailable")):
            await self.failure(OSError)
        self.assertTrue(self.gate.trade_path.exists())
        self.assertEqual(len(self.store.pending_trade_recovery(self.c.config.player_id, self.c.session_epoch)), 1)
        self.assertFalse(any(op == "trade_ack" for op, _ in self.c.server_calls))

    async def test_installed_file_changed_during_ack_prevents_launch_and_retains_intent(self):
        intent, payload = self.journal()
        self.paired(intent, payload)
        async def corrupt(operation, reply):
            if operation == "ack":
                self.save.write_bytes(b"interrupted native file")
        self.c.trade_hook = corrupt
        await self.failure(MirrorError, "mirror_mismatch")
        self.assertTrue(self.gate.trade_path.exists())
        self.c.trade_hook = None
        async with self.gate.open() as result:
            self.assertEqual(result.mirror.revision, 3)
        self.assertFalse(self.gate.trade_path.exists())


class HeldMirrorTests(unittest.TestCase):
    def test_held_operations_require_real_acquired_lease_and_keep_it_held(self):
        with tempfile.TemporaryDirectory() as root:
            c = ClosedCompanion(Path(root))
            try:
                lease = MirrorLease(Path(root) / "held.sav")
                with self.assertRaises(MirrorError) as caught:
                    restore_checkpoint_held(lease, c.head(), c.world_id)
                self.assertEqual(caught.exception.code, "mirror_not_held")
                with lease:
                    info = restore_checkpoint_held(lease, c.head(), c.world_id)
                    self.assertEqual(inspect_mirror_held(lease), info)
                    with self.assertRaises(MirrorError):
                        inspect_mirror(lease.save_path)
                with self.assertRaises(MirrorError):
                    inspect_mirror_held(lease)
                self.assertEqual(inspect_mirror(lease.save_path), info)
            finally:
                c.close()
