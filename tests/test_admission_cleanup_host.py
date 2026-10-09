"""Real authenticated loopback/SQLite cancellation fences; no gameplay claim."""
import asyncio
from dataclasses import replace
import hashlib
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.battle_admission_cleanup_protocol import AdmissionCancellation
from emerald_multiplayer.battle_desk import BattleError
from emerald_multiplayer.battle_execution import BattleExecutionService, _Room
from emerald_multiplayer.battle_execution_protocol import encode_control
from emerald_multiplayer.live_checkpoint import _json_bytes
from emerald_multiplayer.native_battle import NativeControl, Opcode
from emerald_multiplayer.native_battle_resume import Admission
import test_battle_arbitration as fixture


class AdmissionCleanupHostTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = fixture.BattleArbitrationTests.asyncTearDown
    actor = fixture.BattleArbitrationTests.actor
    call = fixture.BattleArbitrationTests.call

    async def asyncSetUp(self):
        await fixture.BattleArbitrationTests.asyncSetUp(self)
        battle = self.desk._active[self.battle_id]
        second = next(index for index in range(2) if self.actors[index].player.player_id != battle.sender)
        self.call("accept", second, battle.fingerprint)
        self.execution = BattleExecutionService(self.desk, (None,) * 721, self.root / "cleanup-host", resume_enabled=True)
        self.server.battle_execution = self.execution
        self.identities = [dict(incarnation=100 + slot, runtime_id=str(uuid4())) for slot in range(2)]
        for index in range(2):
            self.execution.admission.capture(*self.actor(index), dict(battle_id=self.battle_id, **self.identities[index]))
        self.request = []
        for index, identity in enumerate(self.identities):
            actor, lease = self.actor(index)
            ready = NativeControl(identity['incarnation'], lease, self.battle_id, 1, Opcode.ADMISSION_CANCEL_READY,
                phase=battle.mode, source_slot=battle.players.index(actor),
                data=Admission(self.generation, actor, identity['runtime_id']).pack() + struct.pack('<I', lease))
            self.request.append(dict(battle_id=self.battle_id, generation=self.generation,
                **identity, cleanup_ready_b64=encode_control(ready), cleanup_receipt_b64=None))

    async def cancel(self, index=0, **changes):
        return await self.actors[index].rpc("battle_cancel_admission", **(self.request[index] | changes))

    async def test_terminal_digest_is_immutable_and_every_original_player_can_cleanup_independently(self):
        result = (await self.cancel())["result"]
        original = self.execution.admission._path(self.battle_id).read_bytes()
        self.assertEqual(hashlib.sha256(original).hexdigest(), result["tombstone_sha256"])
        for index in range(2):
            reply = await self.cancel(index)
            self.assertEqual(reply["result"]["tombstone_sha256"], result["tombstone_sha256"])
            actor, lease = self.actor(index)
            view = self.execution.admission._read(self.battle_id)["view"]
            payload = AdmissionCancellation(Admission(self.generation, actor, self.identities[index]["runtime_id"]),
                lease, result["tombstone_sha256"]).pack()
            command = NativeControl(100 + index, lease, self.battle_id, 1, Opcode.ADMISSION_CANCEL_HOLD,
                phase=view["mode"], source_slot=view["players"].index(actor), data=payload)
            ack = await self.cancel(index, cleanup_receipt_b64=encode_control(command))
            self.assertTrue(ack["result"]["acknowledged"], ack)
            self.assertEqual((await self.cancel(index))["result"]["tombstone_sha256"], result["tombstone_sha256"])
            with self.assertRaises(BattleError):
                self.execution.admission.capture(actor, lease, dict(battle_id=self.battle_id, **self.identities[index]))
            late = await self.actors[index].rpc("battle_claim", **{k:v for k,v in self.request[index].items() if k not in ("cleanup_receipt_b64", "cleanup_ready_b64")})
            self.assertEqual(late["type"], "battle_error")
        self.assertEqual(self.execution.admission._path(self.battle_id).read_bytes(), original)
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM battle_reservations").fetchone()[0], 0)

    async def test_missing_or_refused_ready_cannot_tombstone_or_archive(self):
        before = self.execution.admission._path(self.battle_id).read_bytes()
        request = dict(self.request[0]); request.pop('cleanup_ready_b64')
        reply = await self.actors[0].rpc('battle_cancel_admission', **request)
        self.assertEqual(reply['type'], 'battle_error')
        self.assertEqual(self.execution.admission._path(self.battle_id).read_bytes(), before)
        self.assertIn(self.battle_id, self.desk._active)

    async def test_changed_or_truncated_execution_identity_refuses_without_revocation(self):
        battle = self.desk._active[self.battle_id]
        room = _Room(battle, self.execution.directory / (self.battle_id + '.json'))
        self.execution._persist(room)
        from emerald_multiplayer.battle_terminal import _read
        record = _read(room.path)
        original = self.execution.admission._path(self.battle_id).read_bytes()
        for changed in (dict(record, generation=str(uuid4())), {k:v for k,v in record.items() if k != 'leases'}):
            room.path.write_bytes(_json_bytes(changed))
            reply = await self.cancel()
            self.assertEqual(reply['code'], 'battle_recovery_required', reply)
            self.assertEqual(self.execution.admission._path(self.battle_id).read_bytes(), original)

    async def test_reservation_without_any_route_file_is_already_too_late(self):
        for index in range(2):
            self.call("register", index, 100 + index)
        self.call("authorize_bind", 0)
        before = self.execution.admission._path(self.battle_id).read_bytes()
        result = await self.cancel()
        self.assertEqual(result["code"], "battle_recovery_required", result)
        self.assertEqual(self.execution.admission._path(self.battle_id).read_bytes(), before)
        self.assertFalse((self.execution.directory / (self.battle_id + ".events.jsonl")).exists())

    async def test_any_route_evidence_or_changed_original_identity_refuses_before_tombstone(self):
        before = self.execution.admission._path(self.battle_id).read_bytes()
        bad = await self.cancel(runtime_id=str(uuid4()))
        self.assertEqual(bad["code"], "battle_incarnation_changed", bad)
        (self.execution.directory / (self.battle_id + ".events.jsonl")).write_bytes(b"uncertain")
        bad = await self.cancel()
        self.assertEqual(bad["code"], "battle_recovery_required", bad)
        self.assertEqual(self.execution.admission._path(self.battle_id).read_bytes(), before)

    async def test_tombstone_precedes_archive_and_survives_restart_at_that_cut(self):
        with patch.object(self.desk, "_abort", side_effect=OSError("crash after fsync")):
            with self.assertRaises(OSError):
                self.execution.admission.cancel_admission(*self.actor(0), self.request[0])
        raw = self.execution.admission._path(self.battle_id).read_bytes()
        self.assertTrue(self.execution.admission._read(self.battle_id)["canceled"])
        # Reconstruct only service memory; original durable store and consent remain.
        self.server.battle_execution = self.execution = BattleExecutionService(self.desk, (None,) * 721,
            self.execution.directory, resume_enabled=True)
        reply = await self.cancel(1)
        self.assertEqual(reply["type"], "battle_result", reply)
        self.assertEqual(self.execution.admission._path(self.battle_id).read_bytes(), raw)
        with self.assertRaises(BattleError):
            self.execution.admission._reservation(self.execution.admission._read(self.battle_id))

    async def test_waiting_ready_room_cannot_authorize_late_bind_after_cancellation(self):
        battle = self.desk._active[self.battle_id]
        for index in range(2):
            self.call("register", index, 100 + index)
        room = _Room(battle, self.execution.directory / (self.battle_id + ".json"))
        room.ready[self.actor(0)[0]] = 100
        room.task = asyncio.create_task(asyncio.sleep(0))
        self.execution.rooms[self.battle_id] = room
        self.execution._persist(room)
        reply = await self.cancel()
        await room.task
        self.assertEqual(reply["type"], "battle_result", reply)
        self.assertEqual(room.state, "aborted")
        with self.assertRaises(BattleError):
            self.call("authorize_bind", 0)
        with self.assertRaises(BattleError):
            self.execution.exchange(*self.actor(1), dict(battle_id=self.battle_id, generation=self.generation))
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM battle_reservations").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
