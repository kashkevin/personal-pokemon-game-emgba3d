"""Coordinator interruption proofs with real SQLite/client codecs, a fake ROM.

This endpoint enforces native command order and zero-offset trade controls; it
is not evidence of actual emulator trade animation, reload, or startup gating.
"""
from __future__ import annotations

import asyncio
from copy import copy
from dataclasses import replace
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

from emerald_multiplayer.companion import TradeError
from emerald_multiplayer.flash import FLASH_SIZE, inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, LiveSaveError, _atomic, _json_bytes
from emerald_multiplayer.live_trade import LiveTradeCoordinator, LiveTradeError
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.protocol import MAX_COUNTER
from emerald_multiplayer.save_mailbox import (Opcode, SaveControl, State, Status, SAVE_CHUNK_SIZE,
                                              import_window_packet, parse_import_window_packet)
from emerald_multiplayer.storage import StorageError
from emerald_multiplayer.trade_desk import TradeDesk
from emerald_multiplayer.trade_protocol import validate_trade_reply, validate_trade_request
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from test_live_checkpoint import FakeCompanion, checkpoint_metadata
from test_flash import _rewrite
from test_ownership_storage import source_flash, owned_flash
from emerald_multiplayer.protocol import PROTOCOL_VERSION


class TradeCompanion(FakeCompanion):
    def __init__(self, store, identity, lease, payload, directory, leases):
        self.store, self.identity, self.session_epoch = store, identity, lease
        self.world_id = store.metadata.world_id
        self.config = SimpleNamespace(build_id=store.build_id, ruleset_id=store.ruleset_id,
            player_id=identity.player_id, trade_enabled=True, ownership_enabled=True)
        self.connected, self.save_profile, self.save_incarnation = True, OWNERSHIP_PROFILE, 2
        self.live_checkpoint_lock = asyncio.Lock()
        self._live_save_owner = self._live_binding = None
        self._live_sequence = 0
        self.commands, self.server_calls, self.upload_payloads = [], [], []
        self.uploads, self.pending_journal = {}, None
        self.commit_hook = None
        self.lose_commit_ack = False
        self.rom_flash = inspect_flash(payload, save_profile=OWNERSHIP_PROFILE).flash
        self.rng = bytes(range(32))
        self.directory, self.leases = directory, leases
        self.phase, self.bound_epoch = State.UNBOUND, 0
        self.active = self.expired = self.import_started = False
        self.operation = None
        self.revision = self.offset = self.crc = self.rom_sequence = 0
        self.last_control = self.last_response = None
        self.stage = bytearray()
        self.import_tuple = None
        self.normal_saves = self.rom_commits = self.releases = self.aborts = 0
        self.faults, self.counts = {}, {}
        # The commands the game refuses as unsafe first (its field not calm yet): BEGIN_TRADE_EXPORT, QUERY_OWNERSHIP.
        self.unsafe_begins = self.unsafe_queries = 0
        self.command_hook = self.trade_hook = None
        self.desk = None
        self.window_sector = None

    def reconnect(self):
        self.store.release_lease(self.config.player_id, self.session_epoch)
        self.session_epoch = self.store.acquire_lease(self.config.player_id, self.identity.credential)
        self.leases[self.config.player_id] = self.session_epoch

    async def checkpoint_rpc(self, operation, *, request_id=None, **fields):
        if operation == "begin":
            journal = json.loads((self.directory / "pending-trade.json").read_text())["intent"]
            assert request_id == journal["prepare_id"] != journal["transaction_id"]
            frozen = (self.directory / (request_id + ".flash")).read_bytes()
            assert hashlib.sha256(frozen).hexdigest() == fields["sha256"]
        try:
            return await super().checkpoint_rpc(operation, request_id=request_id, **fields)
        except StorageError as error:
            from emerald_multiplayer.checkpoint_client import CheckpointError
            raise CheckpointError(error.code, error.message) from error

    async def trade_rpc(self, operation, *, request_id=None, **fields):
        from emerald_multiplayer.trade_protocol import PREPARATION_OPERATIONS
        request = dict(type="trade_"+operation, session_epoch=self.session_epoch,
            request_id=request_id or str(uuid4()), **fields)
        if operation in PREPARATION_OPERATIONS:
            request["preparation_version"] = 1
        validate_trade_request(request, self.session_epoch)
        self.server_calls.append(("trade_"+operation, fields))
        actor = (self.config.player_id, self.session_epoch)
        try:
            if operation == "pending":
                result = dict(recoveries=[dict(transaction_id=r.transaction_id, sequence=r.sequence,
                    outcome_fingerprint=r.outcome_fingerprint, checkpoint=checkpoint_metadata(r.checkpoint))
                    for r in self.store.pending_trade_recovery(*actor)])
            elif operation == "ack":
                intent = json.loads((self.directory / "pending-trade.json").read_text())["intent"]
                assert intent["receipt_id"] is not None and self.active
                assert (self.directory / (intent["receipt_id"] + ".live-apply.json")).exists()
                self.store.acknowledge_trade(*actor, fields["transaction_id"], fields["revision"], fields["sha256"])
                result = dict(trade=dict(transaction_id=fields["transaction_id"], state="acknowledged",
                    revision=fields["revision"], sha256=fields["sha256"]))
            else:
                parameters = {
                    "status": (), "cancel": ("generation",), "open": ("peer",),
                    "offer": ("generation", "revision", "sha256", "serial"),
                    "confirm": ("generation", "fingerprint"),
                    "prepare": ("generation",),
                    "prepared": ("generation", "fingerprint", "preparation_id", "candidate_sha256"),
                }[operation]
                if operation == "open":
                    view = self.desk.open(*actor, fields["peer"], fields["transaction_id"])
                elif operation == "prepare":
                    view = self.desk.preparation(*actor, fields["transaction_id"], fields["generation"])
                else:
                    view = getattr(self.desk, operation)(*actor, fields["transaction_id"],
                        *(fields[name] for name in parameters))
                result = dict(trade=view)
        except StorageError as error:
            raise TradeError(error.code, error.message) from error
        if operation in PREPARATION_OPERATIONS:
            result["preparation_version"] = 1
        reply = validate_trade_reply(dict(type="trade_result", protocol=PROTOCOL_VERSION, session_epoch=self.session_epoch,
            request_id=request["request_id"], operation=operation, world_id=self.world_id,
            player_id=self.config.player_id, **result), self.config, self.save_profile, self.world_id, self.session_epoch)
        if self.trade_hook is not None:
            await self.trade_hook(operation, reply)
        return reply

    def _query_data(self):
        return struct.pack("<IIII32s", self.phase, self.offset, self.crc,
            inspect_flash(self.rom_flash, save_profile=OWNERSHIP_PROFILE).metadata.counter, self.rng)

    def _reply(self, command, *, data=b"", offset=None):
        result = replace(command, data=data, offset=command.offset if offset is None else offset)
        return SaveControl.unpack(result.pack()).validate_response()

    async def save_import_window_rpc(self, control, sector, *, timeout=12):
        # The PC game's 'i' frame: the bridge writes the sector, then the command naming its CRC.
        control, self.window_sector = parse_import_window_packet(import_window_packet(control, sector))
        try:
            return await self.save_rpc(control, timeout=timeout)
        finally:
            self.window_sector = None

    async def save_rpc(self, control, *, timeout=12):
        control = SaveControl.unpack(control.pack()).validate_command()
        assert (control.opcode == Opcode.WRITE_WINDOW) == (self.window_sector is not None)
        self.commands.append(control)
        op = control.opcode
        self.counts[op] = self.counts.get(op, 0)+1
        if self.command_hook is not None:
            await self.command_hook(control)
        assert control.incarnation == self.save_incarnation and control.session_epoch == self.session_epoch
        if op == Opcode.QUERY_TRADE:
            assert self.phase != State.UNBOUND and control.session_epoch >= self.bound_epoch
            assert not self.active or control.request_id == self.operation
            raw_id = UUID(self.operation).bytes if self.active else bytes(16)
            data = struct.pack("<II16sIIIIII", int(self.active) | int(self.expired)<<1 | int(self.import_started)<<2,
                self.phase, raw_id, self.bound_epoch, self.save_incarnation, self.revision,
                self.offset, self.crc, 0 if self.expired or not self.active else 600)
            return self._reply(control, data=data, offset=self.offset)
        if self.last_control == control:
            return self.last_response
        if op == Opcode.BIND:
            assert not self.active and control.sequence == 1
            self.bound_epoch, self.rom_sequence, self.phase = control.session_epoch, 1, State.BOUND
            result = self._reply(control)
        elif op == Opcode.REBIND_TRADE:
            assert self.active and control.session_epoch > self.bound_epoch and control.sequence == 1
            assert (control.request_id, control.revision) == (self.operation, self.revision)
            self.bound_epoch, self.rom_sequence, self.expired = control.session_epoch, 1, False
            result = self._reply(control, data=self._query_data(), offset=self.offset)
        else:
            assert control.session_epoch == self.bound_epoch and control.sequence > self.rom_sequence
            self.rom_sequence = control.sequence
            if self.active:
                assert control.request_id == self.operation
                assert control.revision == self.revision or (op == Opcode.BEGIN_IMPORT and not self.import_started and control.revision == self.revision+1)
                assert not self.expired or op == Opcode.KEEP_TRADE
            if op == Opcode.QUERY_OWNERSHIP and self.unsafe_queries:
                self.unsafe_queries -= 1   # multiplayer_save.c: refused before the query, nothing changed
                result = SaveControl.unpack(replace(control, status=Status.UNSAFE, data=b"").pack()).validate_response()
            elif op == Opcode.QUERY_OWNERSHIP:
                assert self.phase == State.BOUND
                owner = inspect_ownership(inspect_flash(self.rom_flash, save_profile=OWNERSHIP_PROFILE))
                data = struct.pack("<IIII16s16s16sIIII", 3, 0, owner.end_exclusive-owner.next_serial,
                    len(owner.retirements), UUID(owner.world_id).bytes, UUID(owner.player_id).bytes,
                    UUID(owner.grant_id).bytes, owner.next_serial, owner.end_exclusive, self.session_epoch, self.save_incarnation)
                result = self._reply(control, data=data)
            elif op == Opcode.BEGIN_TRADE_EXPORT and self.unsafe_begins and not self.active:
                self.unsafe_begins -= 1   # multiplayer_save.c: refused before Hold, nothing changed
                result = SaveControl.unpack(replace(control, status=Status.UNSAFE, data=b"").pack()).validate_response()
            elif op == Opcode.BEGIN_TRADE_EXPORT:
                if self.active:
                    assert not self.import_started and self.phase in (State.EXPORTING, State.TRADE_HELD)
                else:
                    assert self.phase == State.BOUND
                    self.normal_saves += 1
                self.active, self.operation, self.revision = True, control.request_id, control.revision
                self.phase, self.offset, self.crc = State.EXPORTING, 0, 0
                parsed = inspect_flash(self.rom_flash, save_profile=OWNERSHIP_PROFILE)
                first = struct.unpack_from("<H", self.rom_flash, parsed.metadata.bank*14*4096+4084)[0]
                result = self._reply(control, data=struct.pack("<II32s", parsed.metadata.counter, (-first)%14, self.rng), offset=0)
            elif op == Opcode.READ:
                assert self.phase in (State.EXPORTING, State.COMMITTED) and control.offset == self.offset
                data = self.rom_flash[self.offset:self.offset+SAVE_CHUNK_SIZE]
                self.offset += SAVE_CHUNK_SIZE; self.crc = zlib.crc32(data, self.crc)
                result = self._reply(control, data=data)
            elif op == Opcode.END:
                assert self.phase == State.EXPORTING and control.offset == FLASH_SIZE and self.offset == FLASH_SIZE
                self.phase = State.TRADE_HELD
                result = self._reply(control, data=struct.pack("<I", self.crc), offset=self.offset)
            elif op == Opcode.KEEP_TRADE:
                assert self.active
                self.expired = False
                result = self._reply(control, data=self._query_data(), offset=self.offset)
            elif op == Opcode.BEGIN_IMPORT:
                values = struct.unpack("<IIII", control.data)
                assert self.phase in (State.TRADE_HELD, State.IMPORTING, State.COMMITTED)
                if self.import_started:
                    assert values == self.import_tuple
                self.import_started, self.import_tuple = True, values
                self.phase, self.revision, self.offset, self.crc = State.IMPORTING, control.revision, 0, 0
                self.stage = bytearray()
                result = self._reply(control, data=bytes(8), offset=0)
            elif op == Opcode.WRITE:
                assert self.phase == State.IMPORTING and control.offset == self.offset
                self.stage.extend(control.data); self.offset += SAVE_CHUNK_SIZE
                self.crc = zlib.crc32(control.data, self.crc)
                result = self._reply(control, offset=self.offset)
            elif op == Opcode.WRITE_WINDOW:
                sector = self.window_sector
                assert self.phase == State.IMPORTING and control.offset == self.offset and not self.offset % 4096
                assert struct.unpack("<I", control.data)[0] == zlib.crc32(sector)
                self.stage.extend(sector); self.offset += len(sector)
                self.crc = zlib.crc32(sector, self.crc)
                result = self._reply(control, offset=self.offset)
            elif op == Opcode.COMMIT:
                assert self.phase == State.IMPORTING and self.offset == FLASH_SIZE and self.crc == self.import_tuple[0]
                inspect_flash(bytes(self.stage), save_profile=OWNERSHIP_PROFILE, expected_trainer_id=self.import_tuple[3])
                self.rom_flash, self.phase, self.offset, self.crc = bytes(self.stage), State.COMMITTED, 0, 0
                self.rom_commits += 1
                result = self._reply(control, offset=0)
            elif op == Opcode.ABORT_TRADE:
                assert self.active and not self.import_started and self.phase in (State.EXPORTING, State.TRADE_HELD)
                self.active, self.phase, self.expired = False, State.BOUND, False
                self.aborts += 1
                result = self._reply(control, offset=self.offset)
            elif op == Opcode.RELEASE_TRADE:
                assert self.active and self.import_started and self.phase == State.COMMITTED and self.offset == FLASH_SIZE
                assert not self.store.pending_trade_recovery(self.config.player_id, self.session_epoch)
                self.active, self.import_started, self.expired, self.phase = False, False, False, State.BOUND
                self.releases += 1
                result = self._reply(control, data=struct.pack("<I", self.crc), offset=self.offset)
            else:
                raise AssertionError("unexpected command or generic cancel while held: " + str(op))
        self.last_control, self.last_response = control, result
        if self.faults.get(op) == self.counts[op]:
            raise asyncio.TimeoutError("applied command lost its reply")
        return result


class LiveTradeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.store = TradeCheckpointStore(self.directory/"world.sqlite3", "a"*64, "rules-v1")
        self.store.begin_server_boot()
        self.companions, self.coordinators, self.grants = [], [], []
        self.leases = {}
        for index in range(2):
            identity = self.store.create_player("Actor " + str(index))
            lease = self.store.acquire_lease(identity.player_id, identity.credential)
            self.leases[identity.player_id] = lease
            pids = (index*2+7, index*2+8)
            self.store.enroll_player(identity.player_id, source_flash(("party:0", "party:1"), personalities=pids))
            grant = self.store.reserve_instances(identity.player_id, lease, str(uuid4()), 0, 2, 32)
            payload = owned_flash(grant, (("party:0", grant.start), ("party:1", grant.start+1)), personalities=pids, with_rtc=True)
            self.store.commit_checkpoint(identity.player_id, lease, str(uuid4()), 0, payload, self.store.build_id,
                self.store.ruleset_id, OWNERSHIP_PROFILE)
            private = self.directory/str(index)
            companion = TradeCompanion(self.store, identity, lease, payload, private, self.leases)
            coordinator = LiveTradeCoordinator(companion, private)
            self.companions.append(companion); self.coordinators.append(coordinator); self.grants.append(grant)
        self.desk = TradeDesk(self.store, self.leases.get)
        for companion in self.companions:
            companion.desk = self.desk
        self.tx = str(uuid4())
        self.generation = self.desk.open(self.companions[0].config.player_id, self.companions[0].session_epoch,
            self.companions[1].config.player_id, self.tx)["generation"]

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def intent(self, index=0):
        return json.loads(self.coordinators[index].trade_path.read_text())["intent"]

    def ops(self, index=0):
        return [command.opcode for command in self.companions[index].commands]

    def replacement(self, index=0):
        self.coordinators[index] = LiveTradeCoordinator(self.companions[index], self.coordinators[index].directory)
        return self.coordinators[index]

    async def ready(self):
        for coordinator in self.coordinators:
            await coordinator.prepare(self.tx, self.generation, 1)
        await self.coordinators[0].offer(self.grants[0].start)
        return await self.coordinators[1].offer(self.grants[1].start)

    async def committed(self):
        view = await self.ready()
        await self.coordinators[0].confirm(view["fingerprint"])
        await self.coordinators[1].confirm(view["fingerprint"])
        await self.coordinators[0].prepare_recipient()
        await self.coordinators[1].prepare_recipient()
        return view

    async def test_two_explicit_consents_then_own_canonical_apply_ack_and_release(self):
        view = await self.ready()
        first = await self.coordinators[0].confirm(view["fingerprint"])
        self.assertEqual(first["state"], "offering")
        self.assertEqual(self.companions[0].head().revision, 2)
        second = await self.coordinators[1].confirm(view["fingerprint"])
        self.assertEqual(second["state"], "preparing")
        self.assertEqual(self.companions[0].head().revision, 2)
        await self.coordinators[0].prepare_recipient()
        self.assertEqual(self.companions[0].head().revision, 2)
        second = await self.coordinators[1].prepare_recipient()
        self.assertEqual(second["revision"], 3)
        for index in range(2):
            intent = self.intent(index)
            self.assertNotEqual(intent["prepare_id"], self.tx)
            self.assertEqual(intent["prepared"]["revision"], 2)
            self.assertTrue(self.companions[index].active)
            result = await self.coordinators[index].resume()
            self.assertEqual(result["state"], "applied")
            self.assertFalse(self.coordinators[index].trade_path.exists())
            self.assertEqual(self.companions[index].normal_saves, 1)
            self.assertEqual(self.companions[index].releases, 1)
            self.assertEqual(self.companions[index].rom_commits, 1)
            self.assertNotIn(Opcode.CANCEL, self.ops(index))
            owned = inspect_ownership(inspect_flash(self.companions[index].rom_flash, save_profile=OWNERSHIP_PROFILE))
            self.assertEqual({record.serial for record in owned.records}, {self.grants[1-index].start, self.grants[index].start+1})
        self.store.integrity_check()

    async def test_lost_bind_and_before_bind_intent_can_resume_without_duplicate_begin(self):
        c = self.companions[0]
        async def before_bind(command):
            if command.opcode == Opcode.BIND:
                c.command_hook = None
                raise asyncio.TimeoutError("before BIND execution")
        c.command_hook = before_bind
        with self.assertRaises(asyncio.TimeoutError):
            await self.coordinators[0].prepare(self.tx, self.generation, 1)
        self.assertEqual(self.intent()["phase"], "intent")
        await self.replacement().prepare(self.tx, self.generation, 1)
        self.assertEqual(c.normal_saves, 1)
        self.assertEqual(c.phase, State.TRADE_HELD)
        self.assertEqual(c.commands[0], c.commands[1])
        other = self.companions[1]
        other.faults[Opcode.BIND] = 1
        with self.assertRaises(asyncio.TimeoutError):
            await self.coordinators[1].prepare(self.tx, self.generation, 1)
        self.assertEqual(other.phase, State.BOUND)
        await self.replacement(1).prepare(self.tx, self.generation, 1)
        self.assertEqual(other.commands[0], other.commands[1])
        self.assertEqual(other.normal_saves, 1)

    async def test_a_field_not_yet_calm_delays_the_preparation_instead_of_ending_the_trade(self):
        # The owner's report (2026-10-23): the Players menu closes for the trade, the player walks on, and the game's
        # first answers to the ownership query and to the export are "unsafe": the trade used to end there (and its
        # cancellation, which prepares the party too, failed the same way and stopped saving; trade-walk-new-1).
        c = self.companions[0]
        c.unsafe_queries, c.unsafe_begins = 2, 3
        with patch("emerald_multiplayer.live_trade.CALM_RETRY_SECONDS", .001):
            await self.coordinators[0].prepare(self.tx, self.generation, 1)
        self.assertEqual(self.ops().count(Opcode.QUERY_OWNERSHIP), 3)
        self.assertEqual(self.ops().count(Opcode.BEGIN_TRADE_EXPORT), 4)
        self.assertEqual((c.phase, c.normal_saves), (State.TRADE_HELD, 1))
        self.assertEqual(self.intent()["phase"], "prepared")
        # A game that never calms down still ends it, after CALM_PATIENCE_SECONDS, with nothing held.
        other = self.companions[1]
        other.unsafe_queries = 10**6
        with patch("emerald_multiplayer.live_trade.CALM_RETRY_SECONDS", .001), \
                patch("emerald_multiplayer.live_trade.CALM_PATIENCE_SECONDS", .05), \
                self.assertRaises(LiveSaveError) as caught:
            await self.coordinators[1].prepare(self.tx, self.generation, 1)
        self.assertEqual(caught.exception.code, "rom_unsafe")
        self.assertFalse(other.active)
        self.assertEqual(other.normal_saves, 0)
        # Its cancellation waits for the calm field the same way, then aborts with nothing changed.
        other.unsafe_queries = 2
        with patch("emerald_multiplayer.live_trade.CALM_RETRY_SECONDS", .001):
            result = await self.coordinators[1].cancel()
        self.assertEqual(result["state"], "aborted")
        self.assertFalse(other.active)

    async def test_lost_begin_read_prefix_and_end_restarts_same_frozen_save(self):
        c = self.companions[0]
        c.faults[Opcode.BEGIN_TRADE_EXPORT] = 1
        with self.assertRaises(asyncio.TimeoutError):
            await self.coordinators[0].prepare(self.tx, self.generation, 1)
        self.assertTrue(c.active)
        c.faults[Opcode.READ] = 7
        with self.assertRaises(asyncio.TimeoutError):
            await self.replacement().prepare(self.tx, self.generation, 1)
        self.assertFalse(self.intent()["frozen_sha256"])
        c.faults[Opcode.END] = 1
        with self.assertRaises(asyncio.TimeoutError):
            await self.replacement().prepare(self.tx, self.generation, 1)
        frozen = (self.coordinators[0].directory/(self.intent()["prepare_id"]+".flash")).read_bytes()
        await self.replacement().prepare(self.tx, self.generation, 1)
        self.assertEqual(c.normal_saves, 1)
        self.assertEqual(c.rom_flash, frozen)
        self.assertEqual(c.head().revision, 2)
        self.assertTrue(self.intent()["export_ended"])

    async def test_uncertain_prepare_commit_reconnect_exact_retry_then_authoritative_abort(self):
        c = self.companions[0]
        c.lose_commit_ack = True
        with self.assertRaises(asyncio.TimeoutError):
            await self.coordinators[0].prepare(self.tx, self.generation, 1)
        intent = self.intent()
        self.assertEqual(c.head().request_id, intent["prepare_id"])
        frozen = c.head().payload
        c.reconnect()
        result = await self.replacement().resume()
        self.assertEqual(result["state"], "aborted")
        self.assertEqual(c.head().payload, frozen)
        self.assertEqual(c.head().revision, 2)
        self.assertEqual(c.normal_saves, 1)
        self.assertEqual(c.aborts, 1)
        self.assertIn(Opcode.REBIND_TRADE, self.ops())
        self.assertNotIn(Opcode.CANCEL, self.ops())
        self.assertEqual({entry[0] for entry in c.upload_payloads}, {intent["prepare_id"]})

    async def test_lost_second_prepared_reply_has_durable_fate_then_rebind_and_apply(self):
        view = await self.ready()
        await self.coordinators[0].confirm(view["fingerprint"])
        await self.coordinators[1].confirm(view["fingerprint"])
        await self.coordinators[0].prepare_recipient()
        c = self.companions[1]
        async def lose_confirm(operation, result):
            if operation == "prepared":
                c.trade_hook = None
                raise asyncio.TimeoutError("paired commit reply lost")
        c.trade_hook = lose_confirm
        # No patience: the lost reply surfaces (the retry with patience: test_lost_host_replies_are_asked_again).
        with self.assertRaises(asyncio.TimeoutError), patch("emerald_multiplayer.live_trade.HOST_PATIENCE_SECONDS", 0):
            await self.coordinators[1].prepare_recipient()
        self.assertEqual(c.head().revision, 3)
        c.reconnect()
        result = await self.replacement(1).recover()
        self.assertEqual(result["state"], "applied")
        self.assertIn(Opcode.REBIND_TRADE, self.ops(1))
        self.assertEqual(c.releases, 1)

    async def test_pc_import_window_stages_a_sector_per_command_with_the_same_result(self):
        # 2026-10-20: 1024 WRITEs kept the field frozen about 35 s after a trade. A PC game with the import window
        # takes 32 sectors; the post-image, the ROM's running CRC and the release are the same.
        for c in self.companions:
            c.config.save_import_window_abi_version = 1
        await self.committed()
        for index in range(2):
            c = self.companions[index]
            post = c.head().payload
            result = await self.coordinators[index].resume()
            self.assertEqual(result["state"], "applied")
            self.assertEqual(self.ops(index).count(Opcode.WRITE_WINDOW), FLASH_SIZE // 4096)
            self.assertNotIn(Opcode.WRITE, self.ops(index))
            self.assertEqual(c.rom_flash, inspect_flash(post, save_profile=OWNERSHIP_PROFILE).flash)
            self.assertEqual((c.rom_commits, c.releases), (1, 1))
        self.store.integrity_check()

    async def test_pc_import_window_lost_reply_restages_the_exact_postimage(self):
        for c in self.companions:
            c.config.save_import_window_abi_version = 1
        await self.committed()
        c = self.companions[0]
        c.faults[Opcode.WRITE_WINDOW] = 4
        with self.assertRaises(asyncio.TimeoutError):
            await self.coordinators[0].resume()
        self.assertTrue(c.import_started)
        post = c.head().payload
        c.reconnect()
        result = await self.replacement().resume()
        self.assertEqual(result["state"], "applied")
        self.assertEqual(c.rom_flash, inspect_flash(post, save_profile=OWNERSHIP_PROFILE).flash)
        self.assertEqual((c.rom_commits, c.releases), (1, 1))
        # Restaged from the first sector after BEGIN_IMPORT again; no 128-byte WRITE on the way.
        self.assertEqual(self.ops(0).count(Opcode.WRITE_WINDOW), 4 + FLASH_SIZE // 4096)
        self.assertNotIn(Opcode.WRITE, self.ops(0))

    async def test_import_write_commit_and_rebind_lost_ack_restages_exact_postimage(self):
        await self.committed()
        c = self.companions[0]
        c.faults[Opcode.WRITE] = 4
        with self.assertRaises(asyncio.TimeoutError):
            await self.coordinators[0].resume()
        self.assertTrue(c.import_started)
        post = c.head().payload
        c.reconnect()
        c.faults[Opcode.REBIND_TRADE] = 1
        with self.assertRaises(asyncio.TimeoutError):
            await self.replacement().resume()
        c.faults[Opcode.COMMIT] = 1
        with self.assertRaises(asyncio.TimeoutError):
            await self.replacement().resume()
        self.assertEqual(c.phase, State.COMMITTED)
        result = await self.replacement().resume()
        self.assertEqual(result["state"], "applied")
        self.assertEqual(c.rom_flash, inspect_flash(post, save_profile=OWNERSHIP_PROFILE).flash)
        self.assertEqual(c.rom_commits, 2)
        self.assertEqual(c.releases, 1)
        rebinds = [cmd for cmd in c.commands if cmd.opcode == Opcode.REBIND_TRADE]
        self.assertEqual(rebinds[0], rebinds[1])

    async def test_ack_timeout_retains_verified_receipt_and_release_timeout_replays_exact_control(self):
        await self.committed()
        c = self.companions[0]
        async def lose_ack(operation, result):
            if operation == "ack":
                c.trade_hook = None
                raise asyncio.TimeoutError("durable apply acknowledgment lost")
        c.trade_hook = lose_ack
        with self.assertRaises(asyncio.TimeoutError), patch("emerald_multiplayer.live_trade.HOST_PATIENCE_SECONDS", 0):
            await self.coordinators[0].resume()
        self.assertEqual(self.intent()["phase"], "applied")
        self.assertEqual(c.phase, State.COMMITTED)
        self.assertFalse(self.store.pending_trade_recovery(c.config.player_id, c.session_epoch))
        c.reconnect()
        c.faults[Opcode.RELEASE_TRADE] = 1
        with self.assertRaises(asyncio.TimeoutError):
            await self.replacement().resume()
        self.assertEqual(self.intent()["phase"], "releasing")
        self.assertFalse(c.active)
        result = await self.replacement().resume()
        self.assertEqual(result["state"], "applied")
        self.assertEqual(c.rom_commits, 1)
        self.assertEqual(c.releases, 1)
        release = [cmd for cmd in c.commands if cmd.opcode == Opcode.RELEASE_TRADE]
        self.assertEqual(release[0], release[1])

    async def test_cancel_timeout_never_aborts_and_lost_abort_ack_is_exactly_retryable(self):
        await self.coordinators[0].prepare(self.tx, self.generation, 1)
        c = self.companions[0]
        async def uncertain_cancel(operation, result):
            if operation == "cancel":
                c.trade_hook = None
                raise asyncio.TimeoutError("authoritative cancel reply lost")
        c.trade_hook = uncertain_cancel
        with self.assertRaises(asyncio.TimeoutError), patch("emerald_multiplayer.live_trade.HOST_PATIENCE_SECONDS", 0):
            await self.coordinators[0].cancel()
        self.assertTrue(c.active)
        self.assertNotIn(Opcode.ABORT_TRADE, self.ops())
        c.faults[Opcode.ABORT_TRADE] = 1
        with self.assertRaises(asyncio.TimeoutError):
            await self.replacement().resume()
        self.assertFalse(c.active)
        result = await self.replacement().resume()
        self.assertEqual(result["state"], "aborted")
        aborts = [cmd for cmd in c.commands if cmd.opcode == Opcode.ABORT_TRADE]
        self.assertEqual(aborts[0], aborts[1])
        self.assertEqual(c.aborts, 1)

    async def test_lost_host_replies_are_asked_again_and_the_hold_kept(self):
        # 2026-10-26: one host reply later than 5 s ended the trade for both players and left the game held. The first
        # reply of every kind of host request is lost here, on both sides: each is asked again (the host's answer to
        # the same request again is the same), the game's hold kept alive between the tries, and the trade completes
        # exactly once for both without a reconnect.
        lost = []
        def losing(index):
            async def hook(operation, reply):
                if (index, operation) not in lost and operation in {"status", "pending", "offer", "confirm", "prepare",
                                                                    "prepared", "ack"}:
                    lost.append((index, operation))
                    raise asyncio.TimeoutError("host reply lost")
            return hook
        for index, c in enumerate(self.companions):
            c.trade_hook = losing(index)
        with patch("emerald_multiplayer.live_trade.HOST_RETRY_SECONDS", .001):
            await self.committed()
            for index in range(2):
                result = await self.coordinators[index].resume()
                self.assertEqual(result["state"], "applied")
        for index in range(2):
            self.assertEqual({op for i, op in lost if i == index},
                             {"status", "pending", "offer", "confirm", "prepare", "prepared", "ack"})
            c = self.companions[index]
            self.assertIn(Opcode.KEEP_TRADE, self.ops(index))
            self.assertNotIn(Opcode.REBIND_TRADE, self.ops(index))
            self.assertEqual((c.normal_saves, c.rom_commits, c.releases, c.aborts), (1, 1, 1, 0))
            self.assertFalse(self.coordinators[index].trade_path.exists())
            owned = inspect_ownership(inspect_flash(c.rom_flash, save_profile=OWNERSHIP_PROFILE))
            self.assertEqual({record.serial for record in owned.records}, {self.grants[1-index].start, self.grants[index].start+1})
        self.store.integrity_check()

    async def test_host_patience_ends_and_a_new_lease_is_never_asked_again(self):
        await self.coordinators[0].prepare(self.tx, self.generation, 1)
        c = self.companions[0]
        calls = []
        async def silent(operation, reply):
            calls.append(operation)
            raise asyncio.TimeoutError("host silent")
        c.trade_hook = silent
        with patch("emerald_multiplayer.live_trade.HOST_RETRY_SECONDS", .001), \
                patch("emerald_multiplayer.live_trade.HOST_PATIENCE_SECONDS", .05), self.assertRaises(asyncio.TimeoutError):
            await self.coordinators[0].status()
        self.assertGreater(len(calls), 1)
        self.assertTrue(c.active)
        # A reconnect while the reply is awaited: the old lease's proposal is gone at the host, so the request is not
        # sent again under the new one (the trade resumes against its fate instead).
        calls.clear()
        async def reconnecting(operation, reply):
            calls.append(operation)
            c.trade_hook = None
            c.reconnect()
            raise asyncio.TimeoutError("reply lost as the connection was replaced")
        c.trade_hook = reconnecting
        with patch("emerald_multiplayer.live_trade.HOST_RETRY_SECONDS", .001), self.assertRaises(ConnectionError):
            await self.coordinators[0].status()
        self.assertEqual(calls, ["status"])
        result = await self.replacement().resume()
        self.assertEqual(result["state"], "aborted")
        self.assertFalse(c.active)

    async def test_changed_incarnation_new_companion_and_unproved_inactive_hold_fail_closed(self):
        await self.coordinators[0].prepare(self.tx, self.generation, 1)
        c, coordinator = self.companions[0], self.coordinators[0]
        journal = coordinator.trade_path.read_bytes()
        before = len(c.commands)
        c.save_incarnation += 1
        with self.assertRaises(LiveTradeError) as caught:
            await coordinator.resume()
        self.assertEqual(caught.exception.code, "recovery_required")
        c.save_incarnation -= 1
        recreated = copy(c)
        recreated._live_trade_runtime_id = None
        fresh = LiveTradeCoordinator(recreated, coordinator.directory)
        with self.assertRaises(LiveTradeError) as caught:
            await fresh.resume()
        self.assertEqual(caught.exception.code, "recovery_required")
        self.assertEqual(len(c.commands), before)
        self.assertEqual(coordinator.trade_path.read_bytes(), journal)
        c.active, c.phase = False, State.BOUND
        with self.assertRaises(LiveTradeError) as caught:
            await coordinator.resume()
        self.assertEqual(caught.exception.code, "recovery_required")
        self.assertTrue(coordinator.trade_path.exists())
        self.assertEqual(c.releases, 0)

    async def test_pending_trade_guards_all_ordinary_entry_points_in_other_directory(self):
        await self.coordinators[0].prepare(self.tx, self.generation, 1)
        ordinary = LiveCheckpointCoordinator(self.companions[0], self.directory/"different")
        before = len(self.companions[0].commands)
        for action in (ordinary.checkpoint, ordinary.enroll, ordinary.resolve_pending, ordinary.recover):
            with self.assertRaises(LiveSaveError) as caught:
                await action()
            self.assertEqual(caught.exception.code, "pending_trade")
        self.assertEqual(len(self.companions[0].commands), before)

    async def test_expired_hold_requires_keep_and_damaged_journal_or_frozen_bytes_cannot_release(self):
        await self.coordinators[0].prepare(self.tx, self.generation, 1)
        c, coordinator = self.companions[0], self.coordinators[0]
        c.expired = True
        await coordinator.keepalive()
        self.assertFalse(c.expired)
        journal = coordinator.trade_path.read_bytes()
        coordinator.trade_path.write_bytes(journal.replace(b'"schema":2', b'"schema":true'))
        with self.assertRaises(LiveTradeError) as caught:
            await coordinator.cancel()
        self.assertEqual(caught.exception.code, "invalid_journal")
        coordinator.trade_path.write_bytes(journal)
        intent = self.intent()
        path = coordinator.directory/(intent["prepare_id"]+".flash")
        payload = path.read_bytes(); path.write_bytes(bytes(FLASH_SIZE))
        with self.assertRaises(LiveTradeError) as caught:
            await coordinator.cancel()
        self.assertEqual(caught.exception.code, "journal_bytes")
        path.write_bytes(payload)
        self.assertTrue(c.active)
        self.assertEqual(c.aborts, 0)

    async def test_historical_committed_fate_cannot_overwrite_a_newer_head(self):
        await self.committed()
        c = self.companions[0]
        cp = c.head()
        self.store.acknowledge_trade(c.config.player_id, c.session_epoch, self.tx, cp.revision, cp.sha256)
        c.advance_head(cp.payload)
        with self.assertRaises(LiveTradeError) as caught:
            await self.coordinators[0].resume()
        self.assertEqual(caught.exception.code, "revision_conflict")
        self.assertNotIn(Opcode.BEGIN_IMPORT, self.ops())
        self.assertTrue(c.active)
        self.assertTrue(self.coordinators[0].trade_path.exists())

    async def test_final_release_lost_ack_then_remote_reconnect_uses_durable_receipt(self):
        await self.committed()
        c = self.companions[0]
        c.faults[Opcode.RELEASE_TRADE] = 1
        with self.assertRaises(asyncio.TimeoutError):
            await self.coordinators[0].resume()
        self.assertFalse(c.active)
        c.reconnect()
        self.assertEqual((await self.replacement().resume())["state"], "applied")
        self.assertEqual(c.rom_commits, 1)
        self.assertEqual(c.releases, 1)

    async def test_lost_postimage_read_prefix_restages_and_verifies_without_release(self):
        await self.committed()
        c = self.companions[0]
        c.faults[Opcode.READ] = c.counts[Opcode.READ]+7
        with self.assertRaises(asyncio.TimeoutError):
            await self.coordinators[0].resume()
        self.assertEqual(c.phase, State.COMMITTED)
        self.assertEqual(c.offset, 7*SAVE_CHUNK_SIZE)
        self.assertTrue(c.active)
        self.assertEqual(c.releases, 0)
        self.assertEqual((await self.replacement().resume())["state"], "applied")
        self.assertEqual(c.rom_commits, 2)

    async def test_valid_but_wrong_readback_and_changed_ipc_after_await_cannot_ack_or_release(self):
        await self.committed()
        c = self.companions[0]
        async def wrong_flash(command):
            if command.opcode == Opcode.READ and c.phase == State.COMMITTED:
                c.command_hook = None
                parsed = inspect_flash(c.rom_flash, save_profile=OWNERSHIP_PROFILE)
                c.rom_flash = _rewrite(c.rom_flash, parsed.metadata.bank, 1, 0, struct.pack("<h", 7))
        c.command_hook = wrong_flash
        with self.assertRaises(LiveTradeError) as caught:
            await self.coordinators[0].resume()
        self.assertEqual(caught.exception.code, "applied_state")
        self.assertTrue(c.active)
        self.assertEqual(c.releases, 0)
        self.assertEqual(len(self.store.pending_trade_recovery(c.config.player_id, c.session_epoch)), 1)
        other = self.companions[1]
        async def replace_after_rpc(operation, result):
            if operation == "status":
                other.trade_hook = None
                other.save_incarnation += 1
        other.trade_hook = replace_after_rpc
        with self.assertRaises(LiveTradeError) as caught:
            await self.coordinators[1].resume()
        self.assertEqual(caught.exception.code, "recovery_required")
        self.assertEqual(other.releases, 0)
        self.assertTrue(self.coordinators[1].trade_path.exists())

    async def test_before_bind_then_reconnect_aborted_proposal_preserves_game_before_release(self):
        c = self.companions[0]
        async def before_bind(command):
            if command.opcode == Opcode.BIND:
                c.command_hook = None
                raise asyncio.TimeoutError("before initial BIND")
        c.command_hook = before_bind
        with self.assertRaises(asyncio.TimeoutError):
            await self.coordinators[0].prepare(self.tx, self.generation, 1)
        self.assertEqual(self.intent()["phase"], "intent")
        self.assertEqual(c.phase, State.UNBOUND)
        c.reconnect()
        result = await self.replacement().resume()
        self.assertEqual(result["state"], "aborted")
        self.assertEqual(c.head().revision, 2)
        self.assertEqual(c.normal_saves, 1)
        self.assertEqual(c.aborts, 1)
        self.assertFalse(self.coordinators[0].trade_path.exists())

    async def test_inactive_release_with_wrong_retained_stream_crc_is_not_completion(self):
        await self.committed()
        c = self.companions[0]
        c.faults[Opcode.RELEASE_TRADE] = 1
        with self.assertRaises(asyncio.TimeoutError):
            await self.coordinators[0].resume()
        c.reconnect()
        c.crc ^= 1
        with self.assertRaises(LiveTradeError) as caught:
            await self.replacement().resume()
        self.assertEqual(caught.exception.code, "recovery_required")
        self.assertTrue(self.coordinators[0].trade_path.exists())
        self.assertEqual(c.releases, 1)
