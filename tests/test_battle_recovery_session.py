"""Retained-core client fences over real loopback authentication and binary IPC.

Native receipts and host quorum decisions are explicit synthetic fixtures.
Optional ROM-marker parsing and actual native suspension are separate tests.
"""
import asyncio
import copy
import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import fields, replace
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from emerald_multiplayer.battle_execution_protocol import encode_control, execution_view
from emerald_multiplayer.battle_journal import BattleJournalError, read_battle_intent
from emerald_multiplayer.battle_recovery_session import NativeBattleRecoverySession, verify_recovery_completion
from emerald_multiplayer.battle_session import NativeBattleSession
from emerald_multiplayer.battle_terminal import complete_battle_handoff
from emerald_multiplayer.bridge_protocol import encode_packet, read_packet
from emerald_multiplayer.battle_mailbox import response_packet
from emerald_multiplayer.emergency_save import EmergencySaveController
from emerald_multiplayer.live_checkpoint import _json_bytes
from emerald_multiplayer.native_battle import NativeControl, Opcode
from emerald_multiplayer.native_battle_resume import ResumeAuthorization
import test_battle_admission as admission_fixture
from test_companion import wait_until


class RetainedBattleRecoveryTests(unittest.IsolatedAsyncioTestCase):
    abi_version = 3
    echo = admission_fixture.CompanionBattleAdmissionTests.echo

    async def asyncSetUp(self):
        await admission_fixture.CompanionBattleAdmissionTests.asyncSetUp(self)
        self.addAsyncCleanup(admission_fixture.CompanionBattleAdmissionTests.asyncTearDown, self)
        # Marker verification has independent ROM/manifest cases. This fixture
        # supplies the already-verified optional capability to the real IPC.
        self.c.config = SimpleNamespace(**{**{field.name: getattr(self.c.config, field.name)
                                             for field in fields(self.c.config)}, "battle_resume_abi_version": 1})
        self.binding = replace(self.binding, resumable=True)
        self.bind = replace(self.bind, data=self.binding.pack())
        async with self.journal.bind_intent(self.binding, self.bind, self.canonical) as intent:
            self.intent = intent
        session = NativeBattleSession(self.c, self.directory)
        session.intent, session._command, session._dispatch_id = intent, self.bind, 1
        session._response = replace(self.bind, data=self.query())
        session._persist()
        self.original_intent = self.journal.path.read_bytes()

    def query(self, *, flags=1, sequence=1, remaining=600):
        return struct.pack("<I16sBBBB10I", flags, UUID(self.binding.generation).bytes,
            len(self.binding.players), self.binding.local_slot, self.binding.mode, 0,
            sequence, 0, 0, 0, 0, 0, 0, remaining, 0, 0)

    def recovery_query(self, *, suspended=True, epoch=0, token=bytes(16)):
        return self.query(flags=67 if suspended else 1, remaining=0 if suspended else 600) + struct.pack(
            "<II", (9 if suspended else 2) | 256 | (2 << 16), epoch) + token

    def accepted_challenge(self):
        return dict(scope="session-local-native-challenges-v1", battle_id=self.bind.battle_id,
            generation=self.binding.generation, sender=self.binding.players[0], mode=self.binding.mode,
            state="accepted", reason=None, players=list(self.binding.players), fingerprint="a"*64,
            consent=list(self.binding.players), outcome=None, checkpoints=[dict(player_id=player,
                source_slot=slot, revision=self.canonical.revision, sha256=self.canonical.checkpoint_sha256,
                party_count=self.canonical.party_count) for slot, player in enumerate(self.binding.players)])

    def seed_provisional(self):
        from emerald_multiplayer.battle_admission_intent import create_admission_intent, publish_admission_intent
        from emerald_multiplayer.battle_admission_session import FORMAT
        self.c._live_binding = (self.c.world_id, self.c.session_epoch, self.c.battle_incarnation)
        intent = create_admission_intent(self.c, self.accepted_challenge(), self.canonical)
        publish_admission_intent(self.directory / "pending-battle-admission.json", intent)
        response = replace(intent.admit, data=self.query(flags=129, sequence=0, remaining=0))
        (self.directory / (intent.battle_id + ".battle-admission-receipt.json")).write_bytes(_json_bytes(dict(
            format=FORMAT, intent=intent.value(), command_b64=encode_control(intent.admit), response_b64=encode_control(response))))
        return intent, response

    async def test_resumable_bind_cannot_skip_durable_admission_barrier(self):
        self.journal.path.unlink()
        self.seed_provisional()
        session = NativeBattleSession(self.c, self.directory)
        async def host(operation, **fields):
            if operation == "claim":
                return {"result": self.accepted_challenge()}
            return {"result": execution_view(self.bind.battle_id, self.binding.generation,
                "executing", self.bind, 1)}
        with patch.object(self.c, "battle_challenge_rpc", host), \
             patch.object(self.c, "battle_rpc", side_effect=AssertionError("unadmitted native BIND")):
            with self.assertRaisesRegex(BattleJournalError, "admission barrier"):
                await session.run(self.accepted_challenge())
        self.assertFalse(self.journal.path.exists())

    async def test_admission_ack_requires_exact_durable_intent_and_does_not_mutate_native(self):
        self.journal.path.unlink()
        self.seed_provisional()
        session = NativeBattleSession(self.c, self.directory)
        calls = 0
        class Interrupted(Exception): pass
        async def host(operation, **fields):
            nonlocal calls
            if operation == "claim":
                return {"result": self.accepted_challenge()}
            calls += 1
            if calls == 1:
                self.assertNotIn("admission_sha256", fields)
                return {"result": execution_view(self.bind.battle_id, self.binding.generation,
                    "admitting", self.bind, 1)}
            self.assertEqual(fields["admission_sha256"], hashlib.sha256(self.bind.pack()).hexdigest())
            self.assertEqual(read_battle_intent(self.journal.path).bind, self.bind)
            value = json.loads(session.path.read_bytes())
            self.assertEqual((value["state"], value["command_b64"], value["response_b64"]),
                ("admitting", encode_control(self.bind), None))
            self.assertFalse(session._authorizes(self.bind))
            raise Interrupted()
        with patch.object(self.c, "battle_challenge_rpc", host), \
             patch.object(self.c, "battle_rpc", side_effect=AssertionError("admitting mutated native")):
            with self.assertRaises(Interrupted):
                await session.run(self.accepted_challenge())
        self.assertEqual(read_battle_intent(self.journal.path).bind, self.bind)
        self.assertEqual(calls, 2)

    async def test_executing_uses_exact_admitted_dispatch_and_real_binary_ipc(self):
        self.journal.path.unlink()
        self.seed_provisional()
        session = NativeBattleSession(self.c, self.directory)
        calls = 0
        echoes = []
        class Interrupted(Exception): pass
        async def host(operation, **fields):
            nonlocal calls
            if operation == "claim":
                return {"result": self.accepted_challenge()}
            calls += 1
            if calls == 1:
                state = "admitting"
            elif calls == 2:
                self.assertEqual(fields["admission_sha256"], hashlib.sha256(self.bind.pack()).hexdigest())
                state = "executing"
                echo = asyncio.create_task(self.echo(self.bind, self.query()))
                echoes.append(echo); self.tasks.append(echo)
            else:
                self.assertNotIn("admission_sha256", fields)
                self.assertEqual((fields["response_id"], fields["response_b64"]),
                    (1, encode_control(replace(self.bind, data=self.query()))))
                raise Interrupted()
            return {"result": execution_view(self.bind.battle_id, self.binding.generation,
                state, self.bind, 1)}
        with patch.object(self.c, "battle_challenge_rpc", host):
            with self.assertRaises(Interrupted):
                await session.run(self.accepted_challenge())
        await asyncio.gather(*echoes)
        self.assertEqual(calls, 3)
        self.assertEqual(json.loads(session.path.read_bytes())["state"], "executing")

    @asynccontextmanager
    async def own(self, session):
        async with self.c.live_checkpoint_lock:
            self.c._live_save_owner = self.c._live_battle_owner = asyncio.current_task()
            self.c._live_battle_executor = session
            session._active, session._owner = True, asyncio.current_task()
            try:
                yield
            finally:
                session._active = False
                self.c._live_save_owner = self.c._live_battle_owner = None
                self.c._live_battle_executor = None
                self.c._battle_recovery_authority = None

    async def disconnect(self):
        self.c._remote_writer.close()
        await wait_until(lambda: not self.c.connected)
        self.assertTrue(self.c._reconnect_blocked)

    async def test_pending_battle_blocks_automatic_reconnect_without_emergency_controller(self):
        original_bridge = self.c._bridge
        lease = self.c.session_epoch
        await self.disconnect()
        await asyncio.sleep(self.c.config.reconnect_delay + .1)
        self.assertFalse(self.c.connected)
        with self.assertRaises(ValueError):
            await self.c.reconnect_retained_battle(object())
        session = NativeBattleRecoverySession(self.c, self.directory)
        with self.assertRaises(ValueError):
            await self.c.reconnect_retained_battle(session)
        async with self.own(session):
            await self.c.reconnect_retained_battle(session)
            self.assertGreater(self.c.session_epoch, lease)
            self.assertIs(self.c._bridge, original_bridge)
            self.assertEqual(self.journal.path.read_bytes(), self.original_intent)
            self.assertTrue(self.c._reconnect_blocked)

    async def test_disconnected_provisional_admit_is_exact_original_bound_core_over_real_ipc(self):
        from emerald_multiplayer.battle_admission_session import FORMAT, hold_admission
        self.journal.path.unlink()
        admission, response = self.seed_provisional()
        receipt_path = self.directory / (admission.battle_id + ".battle-admission-receipt.json")
        receipt_path.write_bytes(_json_bytes(dict(format=FORMAT, intent=admission.value(),
            command_b64=encode_control(admission.admit), response_b64=None)))
        original = (self.directory / "pending-battle-admission.json").read_bytes()
        await self.disconnect()
        session = NativeBattleRecoverySession(self.c, self.directory, original_intent=admission)
        with self.assertRaises(ValueError):
            await self.c.battle_rpc(admission.admit)
        async with self.own(session):
            echo = asyncio.create_task(self.echo(admission.admit, response.data)); self.tasks.append(echo)
            self.assertEqual(await hold_admission(self.c, self.directory, admission, self.c._bridge), response)
            await echo
        self.assertFalse(self.c.connected)
        self.assertEqual((self.directory / "pending-battle-admission.json").read_bytes(), original)
        self.assertFalse(self.journal.path.exists())

    async def test_delayed_enter_preparation_finishes_original_admit_offline_without_network(self):
        from emerald_multiplayer.battle_admission_session import prepare_battle_admission, read_admission_receipt
        self.journal.path.unlink()
        admission, response = self.seed_provisional()
        (self.directory / (admission.battle_id + ".battle-admission-receipt.json")).unlink()
        original = (self.directory / "pending-battle-admission.json").read_bytes()
        await self.disconnect()
        echo = asyncio.create_task(self.echo(admission.admit, response.data)); self.tasks.append(echo)
        with patch.object(self.c, "battle_challenge_rpc", side_effect=AssertionError("offline Enter used host RPC")), \
             patch("emerald_multiplayer.checkpoint_client.CheckpointClient.download", side_effect=AssertionError("offline Enter downloaded canonical bytes")):
            result = await prepare_battle_admission(self.c, self.directory, admission.challenge)
        await echo
        self.assertEqual(result, admission)
        self.assertEqual(read_admission_receipt(self.directory, admission), response)
        self.assertEqual((self.directory / "pending-battle-admission.json").read_bytes(), original)
        self.assertIsNone(self.c._live_save_owner)
        self.assertFalse(self.c.connected)

    async def test_enter_publication_precedes_lost_claim_and_exact_native_hold(self):
        from emerald_multiplayer.battle_admission_session import prepare_battle_admission, read_admission_receipt
        from emerald_multiplayer.battle_admission_intent import read_admission_intent
        self.journal.path.unlink()
        self.c._live_binding = (self.c.world_id, self.c.session_epoch, self.c.battle_incarnation)
        calls = []
        async def lost_claim(operation, **fields):
            self.assertEqual(operation, "claim")
            intent = read_admission_intent(self.directory / "pending-battle-admission.json")
            self.assertEqual((fields["battle_id"], fields["generation"], fields["runtime_id"]),
                (intent.battle_id, intent.generation, intent.runtime_id))
            self.assertFalse((self.directory / (intent.battle_id + ".battle-admission-receipt.json")).exists())
            calls.append(intent)
            echo = asyncio.create_task(self.echo(intent.admit, self.query(flags=129, sequence=0, remaining=0)))
            self.tasks.append(echo)
            raise ConnectionError("claim reply lost")
        with patch.object(self.c, "battle_challenge_rpc", lost_claim), \
             patch("emerald_multiplayer.checkpoint_client.CheckpointClient.download", side_effect=AssertionError("Enter downloaded before hold")):
            with self.assertRaisesRegex(ConnectionError, "claim reply lost"):
                await prepare_battle_admission(self.c, self.directory, self.accepted_challenge())
        self.assertEqual(len(calls), 1)
        self.assertEqual(read_admission_receipt(self.directory, calls[0]).opcode, Opcode.ADMIT)

    async def test_synchronous_enter_publication_may_overlap_only_its_exact_lost_saver(self):
        from emerald_multiplayer.battle_admission_session import publish_battle_admission
        from emerald_multiplayer.battle_terminal import authenticated_session
        from emerald_multiplayer.emergency_save import EmergencyResult
        self.journal.path.unlink()
        self.c._live_binding = (self.c.world_id, self.c.session_epoch, self.c.battle_incarnation)
        original = authenticated_session(self.c)
        saver = EmergencySaveController(self.c, self.directory)
        # This synthetic saver is positioned at the real controller's already
        # fenced BEGIN await below, without launching a second preservation task.
        self.c._reconnect_blocked = True
        await self.disconnect()
        blocked = asyncio.Event()
        owner = asyncio.create_task(blocked.wait()); self.tasks.append(owner)
        saver.task, saver.bridge, saver.session = owner, self.c._bridge, self.c._live_binding
        saver.identity = {key: getattr(original, key) for key in ("world_id", "player_id", "build_id", "ruleset_id", "save_profile")}
        saver.lost.set(); saver.result = EmergencyResult("preserving")
        self.c._emergency_controller, self.c._live_save_owner = saver, owner
        try:
            saver.active_export = (str(uuid4()), self.canonical.revision)
            with self.assertRaises(BattleJournalError):
                publish_battle_admission(self.c, self.directory, self.accepted_challenge(), original, self.c._bridge)
            self.assertFalse((self.directory / "pending-battle-admission.json").exists())
            saver.active_export = None
            intent = publish_battle_admission(self.c, self.directory, self.accepted_challenge(), original, self.c._bridge)
            self.assertEqual(intent.runtime_id, original.runtime_id)
            self.assertIs(self.c._live_save_owner, owner)
            self.assertEqual(list(self.directory.glob("*.battle-admission-receipt.json")), [])
        finally:
            self.c._live_save_owner = self.c._emergency_controller = None
            blocked.set(); await owner

    async def test_provisional_recovery_converts_only_original_bind_then_acks_durable_hash(self):
        from emerald_multiplayer.battle_admission_session import verify_admission_conversion
        self.journal.path.unlink()
        (self.directory / "native-battle-execution.json").unlink()
        admission, receipt = self.seed_provisional()
        await self.disconnect()
        entered = asyncio.Event()
        async def host(operation, **fields):
            self.assertEqual(operation, "resume")
            self.assertGreater(self.c.session_epoch, admission.lease_epoch)
            if "admission_b64" in fields:
                self.assertEqual((fields["runtime_id"], fields["admission_b64"], fields["admission_receipt_b64"]),
                    (admission.runtime_id, encode_control(admission.admit), encode_control(receipt)))
                return {"result": dict(scope="native-battle-recovery-v1", battle_id=admission.battle_id,
                    generation=admission.generation, state="admitting", stage="admission", command_id=0,
                    command_b64=None, admission=dict(bind_b64=encode_control(self.bind), original_server_epoch=admission.server_epoch))}
            self.assertEqual(fields["admission_sha256"], hashlib.sha256(self.bind.pack()).hexdigest())
            full = read_battle_intent(self.journal.path)
            self.assertEqual(full.lease_epoch, admission.lease_epoch)
            self.assertEqual(verify_admission_conversion(self.directory, admission, full), full)
            execution = json.loads((self.directory / "native-battle-execution.json").read_bytes())
            self.assertEqual(execution["state"], "admitting")
            self.assertIsNone(execution["response_b64"])
            entered.set()
            return {"result": dict(scope="native-battle-recovery-v1", battle_id=admission.battle_id,
                generation=admission.generation, state="waiting", stage="recovery", command_id=0, command_b64=None)}
        session = NativeBattleRecoverySession(self.c, self.directory, original_intent=admission)
        with patch.object(self.c, "battle_challenge_rpc", host), \
             patch.object(self.c, "battle_rpc", side_effect=AssertionError("bootstrap executed an unapproved full BIND")):
            task = asyncio.create_task(session.run()); self.tasks.append(task)
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(session.intent, self.intent)
        self.assertFalse((self.directory / "pending-battle-admission.json").exists())
        self.assertTrue(self.journal.path.exists())

    async def test_only_exact_unanswered_fsynced_command_and_same_task_can_mutate(self):
        session = NativeBattleRecoverySession(self.c, self.directory)
        command = replace(self.bind, opcode=Opcode.SUSPEND, sequence=2, data=b"")
        async with self.own(session):
            session.renewed_session = session._session()
            session._command, session._dispatch_id = command, 1
            with self.assertRaises(ValueError):
                await self.c.battle_rpc(command)
            session._persist()
            saved = session.path.read_bytes()
            session.path.write_bytes(b"{}")
            with self.assertRaises(ValueError):
                await self.c.battle_rpc(command)
            session.path.write_bytes(saved)
            async def outsider():
                with self.assertRaises(ValueError):
                    await self.c.battle_rpc(command)
                with self.assertRaises(ValueError):
                    await self.c.reconnect_retained_battle(session)
            await asyncio.create_task(outsider())
            echo = asyncio.create_task(self.echo(command, self.recovery_query()))
            self.tasks.append(echo)
            reply = await self.c.battle_rpc(command)
            await echo
            session._response = reply
            session._persist()
            with self.assertRaises(ValueError):
                await self.c.battle_rpc(command)
        self.assertEqual(self.journal.path.read_bytes(), self.original_intent)

    async def test_replacement_runtime_bridge_marker_and_changed_original_intent_refuse(self):
        session = NativeBattleRecoverySession(self.c, self.directory)
        for key, changed in (("_live_battle_runtime_id", str(uuid4())), ("_bridge", object())):
            before = getattr(self.c, key)
            setattr(self.c, key, changed)
            try:
                with self.assertRaises((ValueError, AttributeError)):
                    session._retained()
            finally:
                setattr(self.c, key, before)
        self.c.config.battle_resume_abi_version = 0
        with self.assertRaises(ValueError):
            session._retained()
        self.c.config.battle_resume_abi_version = 1
        self.journal.path.write_bytes(b"{}")
        with self.assertRaises(ValueError):
            session._retained()
        self.journal.path.write_bytes(self.original_intent)

    async def run_scripted_completion(self, *, lose_host=True, closed_early=False):
        if lose_host:
            await self.disconnect()
        session = NativeBattleRecoverySession(self.c, self.directory)
        issued, replies = [], []
        commands = None
        response_stage, response_id, response_b64 = None, 0, None
        async def host(operation, **fields):
            nonlocal commands, response_stage, response_id, response_b64
            self.assertEqual(operation, "resume")
            self.assertEqual(self.journal.path.read_bytes(), self.original_intent)
            self.assertEqual((fields["response_stage"], fields["response_id"], fields["response_b64"]),
                             (response_stage, response_id, response_b64))
            if commands is None:
                leases = tuple(self.c.session_epoch if slot == self.binding.local_slot else lease
                               for slot, lease in enumerate(self.binding.leases))
                bound = replace(self.binding, leases=leases)
                renewal = ResumeAuthorization(bound, b"q"*16, 1, 1)
                base = replace(self.bind, session_epoch=self.c.session_epoch)
                commands = [
                    ("recovery", 1, replace(base, opcode=Opcode.QUERY, data=b"", sequence=2)),
                    ("recovery", 2, replace(base, opcode=Opcode.SUSPEND, data=b"", sequence=2)),
                    ("recovery", 3, replace(base, opcode=Opcode.REAUTHORIZE, data=renewal.pack(), sequence=2)),
                    ("recovery", 4, replace(base, opcode=Opcode.RESUME, data=b"q"*16+struct.pack("<I", 1), sequence=2)),
                    ("route", 2, replace(base, opcode=Opcode.KEEP, data=b"", sequence=2)),
                    ("route", 3, replace(base, opcode=Opcode.RELEASE,
                        data=struct.pack("<II", self.canonical.party_crc32, 2), sequence=3)),
                ]
            if closed_early or not commands:
                if not closed_early:
                    release = issued[-1]
                    payload = UUID(self.intent.generation).bytes + struct.pack("<I", release.sequence) + release.data
                    retire = replace(release, opcode=Opcode.RETIRE, sequence=1, data=payload)
                    echo = asyncio.create_task(self.echo(retire, payload))
                    replies.append(echo); self.tasks.append(echo)
                return {"result": dict(scope="native-battle-recovery-v1", battle_id=self.intent.battle_id,
                    generation=self.intent.generation, state="closed", stage="route", command_id=0, command_b64=None)}
            stage, dispatch, command = commands.pop(0)
            issued.append(command)
            response_stage, response_id = stage, dispatch
            data = {
                Opcode.QUERY: self.query(), Opcode.SUSPEND: self.recovery_query(),
                Opcode.REAUTHORIZE: self.recovery_query(epoch=1, token=b"q"*16),
                Opcode.RESUME: self.recovery_query(suspended=False, epoch=1, token=b"q"*16),
                Opcode.KEEP: self.query(sequence=2), Opcode.RELEASE: b"",
            }[command.opcode]
            response_b64 = encode_control(replace(command, data=data))
            echo = asyncio.create_task(self.echo(command, data))
            replies.append(echo); self.tasks.append(echo)
            return {"result": dict(scope="native-battle-recovery-v1", battle_id=self.intent.battle_id,
                generation=self.intent.generation, state="executing", stage=stage,
                command_id=dispatch, command_b64=encode_control(command))}
        with patch.object(self.c, "battle_challenge_rpc", host):
            completion = await asyncio.wait_for(session.run(), 10)
        await asyncio.gather(*replies)
        return session, completion, issued

    async def test_new_authenticated_lease_exact_ipc_and_terminal_adoption_retry(self):
        session, completion, commands = await self.run_scripted_completion()
        self.assertGreater(completion.renewed_session.lease_epoch, self.intent.lease_epoch)
        self.assertEqual([command.opcode for command in commands],
            [Opcode.QUERY, Opcode.SUSPEND, Opcode.REAUTHORIZE, Opcode.RESUME, Opcode.KEEP, Opcode.RELEASE])
        self.assertFalse(self.journal.path.exists())
        self.assertEqual(completion.canonical_sha256, self.intent.canonical_sha256)
        verify_recovery_completion(self.c, self.directory, completion, self.intent, session.bridge)
        retry = NativeBattleRecoverySession(self.c, self.directory, original_intent=self.intent)
        with patch.object(self.c, "reconnect_retained_battle", side_effect=AssertionError("terminal retry reconnected")), \
             patch.object(self.c, "battle_rpc", side_effect=AssertionError("terminal retry dispatched native command")):
            self.assertEqual(await retry.run(), completion)

    async def test_terminal_only_retry_renews_just_original_core_without_finished_peers(self):
        from emerald_multiplayer.battle_execution_protocol import decode_control
        session, completed, _ = await self.run_scripted_completion(lose_host=False)
        prior = json.loads((self.directory / (self.intent.battle_id + ".battle-retirement.json")).read_bytes())
        release = decode_control(prior["release_command_b64"])
        response = decode_control(prior["release_response_b64"], response=True)
        await self.disconnect()
        retry = NativeBattleRecoverySession(self.c, self.directory, original_intent=self.intent)
        replies = []
        async def closed(operation, **fields):
            self.assertEqual(operation, "resume")
            self.assertIsNone(fields["response_b64"])
            self.assertGreater(self.c.session_epoch, completed.renewed_session.lease_epoch)
            retire = replace(decode_control(prior["command_b64"]), session_epoch=self.c.session_epoch)
            echo = asyncio.create_task(self.echo(retire, retire.data)); replies.append(echo); self.tasks.append(echo)
            return {"result": dict(scope="native-battle-recovery-v1", battle_id=self.intent.battle_id,
                generation=self.intent.generation, state="closed", stage="terminal", command_id=0, command_b64=None,
                terminal=dict(release_b64=encode_control(release), receipt_b64=encode_control(response),
                              retire_b64=encode_control(retire)))}
        with patch.object(self.c, "battle_challenge_rpc", closed):
            renewed = await asyncio.wait_for(retry.run(), 5)
        await asyncio.gather(*replies)
        verify_recovery_completion(self.c, self.directory, renewed, self.intent, session.bridge)
        self.assertGreater(renewed.renewed_session.lease_epoch, completed.renewed_session.lease_epoch)
        self.assertFalse(self.journal.path.exists())
        archive = self.directory / (self.intent.battle_id + ".battle-retirement."
            + str(completed.renewed_session.server_epoch) + "." + str(completed.renewed_session.lease_epoch) + ".json")
        self.assertEqual(json.loads(archive.read_bytes()), prior)

    async def test_normal_resumable_completion_retires_before_pending_unlink_and_uses_shared_proof(self):
        session = NativeBattleSession(self.c, self.directory)
        session.intent = self.intent
        session._command = replace(self.bind, opcode=Opcode.RELEASE, sequence=3,
            data=struct.pack("<II", self.canonical.party_crc32, 2))
        session._response = replace(session._command, data=b"")
        session._dispatch_id = 3
        session._persist()
        payload = UUID(self.intent.generation).bytes + struct.pack("<I", 3) + session._command.data
        retire = replace(session._command, opcode=Opcode.RETIRE, sequence=1, data=payload)
        echo = asyncio.create_task(self.echo(retire, payload)); self.tasks.append(echo)
        async with self.own(session):
            completion = await session._terminal(execution_view(self.intent.battle_id, self.intent.generation, "closed"))
        await echo
        self.assertEqual(completion.renewed_session.lease_epoch, self.intent.lease_epoch)
        self.assertFalse(self.journal.path.exists())
        verify_recovery_completion(self.c, self.directory, completion, self.intent, self.c._bridge)
        retry = NativeBattleRecoverySession(self.c, self.directory, original_intent=self.intent)
        with patch.object(self.c, "battle_rpc", side_effect=AssertionError("normal terminal adoption replayed native state")):
            self.assertEqual(await retry.run(), completion)

    async def test_host_closed_without_local_release_keeps_intent(self):
        with self.assertRaisesRegex(BattleJournalError, "RELEASE"):
            await self.run_scripted_completion(closed_early=True)
        self.assertEqual(self.journal.path.read_bytes(), self.original_intent)
        self.assertFalse((self.directory / (self.intent.battle_id + ".battle-recovery-complete.json")).exists())

    async def test_retirement_uncertainty_keeps_original_intent_and_forbids_generic_handoff(self):
        original_rpc = self.c.battle_rpc
        async def uncertain(command, **kwargs):
            if command.opcode == Opcode.RETIRE:
                raise asyncio.TimeoutError()
            return await original_rpc(command, **kwargs)
        with patch.object(self.c, "battle_rpc", uncertain):
            with self.assertRaises(asyncio.TimeoutError):
                await self.run_scripted_completion(lose_host=False)
        self.assertEqual(self.journal.path.read_bytes(), self.original_intent)
        value = json.loads((self.directory / (self.intent.battle_id + ".battle-retirement.json")).read_bytes())
        self.assertIsNone(value["response_b64"])
        from emerald_multiplayer.battle_execution_protocol import decode_control
        command = decode_control(value["command_b64"])
        for opcode in (Opcode.RETIRE, Opcode.HANDOFF):
            with self.assertRaises(ValueError):
                await self.c.battle_rpc(replace(command, opcode=opcode))
        self.assertFalse(self.c._battle_pending)

    def successor_fixture(self, completion):
        # Native arm/grant behavior has separate emergency-controller tests.
        # Supply its exact typed and durable result to test the final authority.
        successor = EmergencySaveController(self.c, self.directory)
        session = completion.renewed_session
        successor.session = (session.world_id, session.lease_epoch, session.incarnation)
        successor.bridge = self.c._bridge
        successor.base_revision = self.intent.canonical_revision
        successor.identity = dict(world_id=session.world_id, player_id=session.player_id,
            build_id=session.build_id, ruleset_id=session.ruleset_id, save_profile=session.save_profile)
        successor.needs_arm = False
        successor._publish("armed")
        self.c._emergency_controller = successor
        self.c._live_binding = successor.session
        self.c._live_bind_pending = None
        grant = dict(world_id=session.world_id, player_id=session.player_id, lease_epoch=session.lease_epoch,
            incarnation=session.incarnation, grant_id=str(uuid4()), start=100, end_exclusive=120,
            expected_revision=self.intent.canonical_revision)
        (self.directory / "emergency-arm.json").write_bytes(_json_bytes(dict(schema=1, **successor.identity,
            session_epoch=session.lease_epoch, incarnation=session.incarnation,
            expected_revision=successor.base_revision, grant=grant)))
        return successor

    async def test_handoff_requires_registered_durable_arm_and_is_idempotent(self):
        session, completion, _ = await self.run_scripted_completion(lose_host=False)
        successor = self.successor_fixture(completion)
        from emerald_multiplayer.battle_execution_protocol import decode_control
        retired = json.loads((self.directory / (self.intent.battle_id + ".battle-retirement.json")).read_bytes())
        command = replace(decode_control(retired["command_b64"]), opcode=Opcode.HANDOFF)
        with self.assertRaisesRegex(ValueError, "lifecycle authority"):
            await self.c.battle_rpc(command)
        successor.needs_arm = True
        with self.assertRaises(ValueError):
            await complete_battle_handoff(self.c, self.directory, completion, self.intent, session.bridge, successor)
        successor.needs_arm = False
        armed = (self.directory / "emergency-arm.json").read_bytes()
        (self.directory / "emergency-arm.json").write_bytes(b"{}")
        with self.assertRaises(ValueError):
            await complete_battle_handoff(self.c, self.directory, completion, self.intent, session.bridge, successor)
        (self.directory / "emergency-arm.json").write_bytes(armed)
        echo = asyncio.create_task(self.echo(command, command.data)); self.tasks.append(echo)
        result = await complete_battle_handoff(self.c, self.directory, completion, self.intent, session.bridge, successor)
        await echo
        self.assertEqual(result, completion)
        with patch.object(self.c, "battle_rpc", side_effect=AssertionError("replayed settled HANDOFF")):
            self.assertEqual(await complete_battle_handoff(self.c, self.directory, completion,
                self.intent, session.bridge, successor), completion)
        self.assertIs(self.c._emergency_controller, successor)
        self.assertIsNone(self.c._live_battle_owner)

    async def test_missing_peer_wait_has_no_timeout_and_cancellation_retains_original(self):
        entered = asyncio.Event()
        async def waiting(operation, **fields):
            entered.set()
            return {"result": dict(scope="native-battle-recovery-v1", battle_id=self.intent.battle_id,
                generation=self.intent.generation, state="waiting", stage="recovery", command_id=0, command_b64=None)}
        session = NativeBattleRecoverySession(self.c, self.directory)
        with patch.object(self.c, "battle_challenge_rpc", waiting):
            task = asyncio.create_task(session.run()); self.tasks.append(task)
            await asyncio.wait_for(entered.wait(), 3)
            await asyncio.sleep(.12)
            self.assertFalse(task.done())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.journal.path.read_bytes(), self.original_intent)
        self.assertIsNone(self.c._live_save_owner)
        self.assertIsNone(self.c._live_battle_executor)
        self.assertFalse(self.c._battle_pending)

    async def test_no_unproven_bind_or_reauthorization_or_route_skip(self):
        session = NativeBattleRecoverySession(self.c, self.directory)
        session.renewed_session = session._session()
        session._load()
        renewal = ResumeAuthorization(self.binding, b"q"*16, 1, 1)
        for stage, dispatch, command in (
            ("recovery", 1, self.bind),
            ("recovery", 1, replace(self.bind, opcode=Opcode.REAUTHORIZE, data=renewal.pack())),
            ("recovery", 1, replace(self.bind, opcode=Opcode.RESUME, data=b"q"*16+struct.pack("<I", 1))),
            ("route", 3, replace(self.bind, opcode=Opcode.KEEP, data=b"", sequence=2))):
            with self.subTest(opcode=command.opcode), self.assertRaises(ValueError):
                session._validate_command(stage, command, dispatch)

    async def test_loaded_recovery_rejects_malformed_identity_dispatch_and_receipt_evidence(self):
        session = NativeBattleRecoverySession(self.c, self.directory)
        session.renewed_session = session._session()
        session._load()
        original = session._record()
        session._persist()
        NativeBattleRecoverySession(self.c, self.directory)._load()
        cases = []
        def changed(**fields):
            value = copy.deepcopy(original)
            value.update(fields)
            cases.append(value)
        changed(extra=True)
        changed(route_id=True)
        changed(route_response_b64=None, route_command_b64=None)
        changed(renewed_session={})
        changed(renewed_session={**original["renewed_session"], "world_id": str(uuid4())})
        changed(route_command_b64=encode_control(replace(self.bind, session_epoch=self.intent.lease_epoch+1)))
        changed(route_command_b64=encode_control(replace(self.bind, opcode=Opcode.SUSPEND, data=b"")))
        changed(response_b64=encode_control(replace(self.bind, data=self.query())))
        changed(state="closed")
        for index, value in enumerate(cases):
            session.path.write_bytes(_json_bytes(value))
            with self.subTest(index=index), self.assertRaises(ValueError):
                NativeBattleRecoverySession(self.c, self.directory)._load()
        # Canonical JSON is part of the record: duplicate fields and appendages
        # cannot turn a malformed local record into an accepted parsed object.
        for raw in (_json_bytes(original)+b" ", b'{"format":1,"format":2}'):
            session.path.write_bytes(raw)
            with self.assertRaises(ValueError):
                NativeBattleRecoverySession(self.c, self.directory)._load()
        self.assertEqual(self.journal.path.read_bytes(), self.original_intent)
        self.assertIsNone(self.c._live_battle_owner)

    async def test_successful_retirement_is_exact_and_idempotent_without_rearming_old_controller(self):
        controller = EmergencySaveController(self.c, self.directory)
        controller.session = (self.intent.world_id, self.intent.lease_epoch, self.intent.incarnation)
        controller.bridge, controller.base_revision = self.c._bridge, self.intent.canonical_revision
        controller._publish("armed")
        self.c._emergency_controller = controller
        self.c._live_binding = controller.session
        session, completion, _ = await self.run_scripted_completion()
        self.assertEqual(controller.result.state, "battle_waiting")
        with self.assertRaises(ValueError):
            await controller.retire_after_battle_recovery(replace(completion, canonical_sha256="0"*64), self.intent, session.bridge)
        result = await controller.retire_after_battle_recovery(completion, self.intent, session.bridge)
        self.assertEqual(result.state, "retired_after_battle")
        self.assertEqual(await controller.retire_after_battle_recovery(completion, self.intent, session.bridge), result)
        self.assertTrue(controller.lost.is_set())
        self.assertIsNone(self.c._emergency_controller)
        self.assertIsNone(self.c._live_binding)
        with self.assertRaises(ValueError):
            await controller.arm(self.intent.canonical_revision)


if __name__ == "__main__":
    unittest.main()
