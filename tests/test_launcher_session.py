"""Real TLS/SQLite/companion lifecycle; Python child stands in for SDL only."""
import asyncio
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.checkpoint_mirror import MirrorError, MirrorLease
from emerald_multiplayer.checkpoint_client import CheckpointClient, CheckpointError
from emerald_multiplayer.companion import Companion, TradeError
from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.launcher_session import (
    GameInstallation, LauncherSession, LauncherSessionError, SessionState,
)
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.ownership import inspect_ownership
from emerald_multiplayer.trade_flash import build_party_swap
from emerald_multiplayer.trade_storage import TradeSide
from process_fixture import direct_python
from test_host_world import make_trade_files
from test_ownership_storage import owned_flash, source_flash
from test_player_runtime import write_bundle


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LauncherSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rom, self.manifest = make_trade_files(self.root)
        bundle = self.root / "bundle"
        bundle.mkdir()
        self.installation = GameInstallation(self.rom, self.manifest, digest(self.rom),
                                             digest(self.manifest), write_bundle(bundle))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.host = HostWorld.create(self.root / "world", self.rom, self.manifest,
            player_names=("Host", "Friend", "New Friend"), endpoint="192.168.70.50", port=port)
        self.payloads = {}
        with self.host.open_store() as store:
            store.begin_server_boot()
            for slot in (0, 1):
                account = self.host.accounts[slot]
                source = source_flash(personalities=(7+slot,))
                store.enroll_player(account.player_id, source)
                lease = store.acquire_lease(account.player_id, account.credential)
                grant = store.reserve_instances(account.player_id, lease, str(uuid4()), 0, 1, 32)
                payload = owned_flash(grant, personalities=(7+slot,), with_rtc=True)
                store.commit_checkpoint(account.player_id, lease, str(uuid4()), 0, payload,
                                        self.host.build_id, self.host.ruleset_id, OWNERSHIP_PROFILE)
                self.payloads[account.player_id] = payload
        self.private = self.root / "private"
        self.children, self.calls = [], []
        self.spawned = asyncio.Event()
        self.real_spawn = asyncio.create_subprocess_exec

    async def asyncTearDown(self):
        for child in self.children:
            if child.returncode is None:
                child.kill()
            await child.wait()
        self.temporary.cleanup()

    def session(self, **options):
        values = dict(world_directory=self.host.directory, bind_address="127.0.0.1",
                      host_route="127.0.0.1", development_trades=False)
        values.update(options)
        return LauncherSession(self.installation, self.private, **values)

    def friend(self, slot=1, **options):
        invitation = self.root / (str(uuid4()) + ".json")
        # Loopback test route only. The advertised endpoint and host.json
        # remain unchanged; both routes retain the same host certificate pin.
        replace(self.host.invitation(slot), endpoint="127.0.0.1").save(invitation)
        return LauncherSession(self.installation, self.private, invitation_path=invitation, **options)

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(LauncherSessionError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    async def spawn(self, *args, **kwargs):
        save = Path(args[4])
        player_id = save.parent.name
        self.assertEqual(save.read_bytes(), self.payloads[player_id])
        self.assertEqual(kwargs["cwd"].parent, (self.private / "launches").resolve())
        self.assertEqual(Path(args[2]).parent, kwargs["cwd"])
        with self.assertRaises(MirrorError):
            with MirrorLease(save):
                self.fail("native creation must retain the canonical save lease")
        self.assertNotIn("shell", kwargs)
        child = await self.real_spawn(direct_python(), "-c", "import time; time.sleep(60)", **kwargs)
        self.children.append(child)
        self.calls.append((args, kwargs))
        self.spawned.set()
        return child

    def committed_trade(self):
        """Durable pre-restart fixture; no public trade creation is enabled."""
        with self.host.open_store() as store:
            store.begin_server_boot()
            accounts = self.host.accounts[:2]
            leases = [store.acquire_lease(a.player_id, a.credential) for a in accounts]
            heads = [store.read_checkpoint(a.player_id, lease) for a, lease in zip(accounts, leases)]
            serials = [inspect_ownership(inspect_flash(h.payload, save_profile=OWNERSHIP_PROFILE)).records[0].serial
                       for h in heads]
            post = build_party_swap(heads[0].payload, serials[0], heads[1].payload, serials[1])
            sides = [TradeSide(a.player_id, lease, h.revision, serial, payload)
                     for a, lease, h, serial, payload in zip(accounts, leases, heads, serials, post)]
            result = store.commit_trade(str(uuid4()), *sides, self.host.build_id,
                                        self.host.ruleset_id, OWNERSHIP_PROFILE)
            for checkpoint in (result.checkpoint_a, result.checkpoint_b):
                self.payloads[checkpoint.player_id] = checkpoint.payload
            store.integrity_check()
            return result

    async def finish_game(self, session):
        self.spawned.clear()
        task = asyncio.create_task(session.play())
        await asyncio.wait_for(self.spawned.wait(), 10)
        self.children[-1].terminate()
        return await asyncio.wait_for(task, 10)

    async def test_host_local_route_keeps_advertised_identity_and_readiness_is_observational(self):
        original = (self.host.directory / "host.json").read_bytes()
        session = self.session()
        async with session.open():
            self.assertEqual(session.status.state, SessionState.READY)
            self.assertEqual(session.status.revision, 1)
            self.assertTrue(session.status.connected)
            c = session._companion
            self.assertEqual(c.config.server_host, "127.0.0.1")
            self.assertEqual(c.config.server_tls.certificate_sha256, self.host.certificate_sha256)
            c.config.server_tls.verify_peer(c._remote_writer)
            self.assertIsNotNone(c._remote_writer.get_extra_info("ssl_object"))
            self.assertFalse((session.profile_directory / "character.sav").exists())
            self.assertFalse(list(session.profile_directory.glob("closed-recoveries/*")))
            self.assertIsNone(session._server.battle_desk)
            self.assertFalse(c.config.development_battle_channel)
        self.assertEqual(session.status.state, SessionState.CLOSED)
        self.assertFalse(session.status.connected)
        self.assertEqual((self.host.directory / "host.json").read_bytes(), original)
        with self.host.open_store() as store:
            store.integrity_check()

    async def test_friend_uses_its_own_account_profile_and_pinned_tls(self):
        host, friend = self.session(), self.friend()
        async with host.open(), friend.open():
            self.assertEqual(friend.status.state, SessionState.READY)
            self.assertEqual(friend._companion.config.player_id, self.host.accounts[1].player_id)
            self.assertNotEqual(friend.profile_directory, host.profile_directory)
            self.assertIsNone(friend._server)
            self.assertEqual(len(host._server.sessions), 2)
            friend._companion.config.server_tls.verify_peer(friend._companion._remote_writer)

    async def test_new_trades_disabled_still_allow_ready_host_and_friend_to_launch(self):
        host, friend = self.session(development_trades=False), self.friend()
        async with host.open(), friend.open():
            for session in (host, friend):
                self.assertEqual(session.status.state, SessionState.READY)
                with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
                    self.spawned.clear()
                    task = asyncio.create_task(session.play())
                    await asyncio.wait_for(self.spawned.wait(), 10)
                    self.children[-1].terminate()
                    await asyncio.wait_for(task, 10)
                self.assertTrue((session.profile_directory / "character.sav").exists())
            self.assertIsNone(host._server.trade_desk)
        self.assertEqual(len(self.children), 2)

    async def test_committed_trade_recovers_each_current_save_over_tls_with_new_trades_disabled(self):
        outcome = self.committed_trade()
        host, friend = self.session(), self.friend()
        async with host.open(), friend.open():
            self.assertIsNone(host._server.trade_desk)
            for session in (host, friend):
                c = session._companion
                pending = (await c.trade_rpc("pending"))["recoveries"]
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0]["transaction_id"], outcome.transaction_id)
                self.assertEqual(session.status.revision, 2)
                self.assertFalse((session.profile_directory / "character.sav").exists())
                with self.assertRaises(CheckpointError) as caught:
                    await CheckpointClient(c).upload(self.payloads[c.config.player_id], 2)
                self.assertEqual(caught.exception.code, "trade_recovery_required")
                with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
                    await self.finish_game(session)
                self.assertEqual((await c.trade_rpc("pending"))["recoveries"], [])
                evidence, = session.profile_directory.glob("closed-recoveries/*/completed.json")
                record = json.loads(evidence.read_bytes())["record"]
                self.assertEqual(record["trade_ack"]["state"], "acknowledged")
                self.assertEqual(record["trade_fate"]["outcome_fingerprint"], outcome.outcome_fingerprint)
                self.assertEqual((session.profile_directory / "character.sav").read_bytes(), self.payloads[c.config.player_id])
            self.assertEqual(host._store._connection.execute("SELECT count(*) FROM trade_transactions").fetchone()[0], 1)
            host._store.integrity_check()

    async def test_recovery_ack_requires_exact_own_result_and_readiness_does_not_clear_it(self):
        outcome = self.committed_trade()
        host, stranger = self.session(), self.friend(2)
        async with host.open(), stranger.open():
            c = host._companion
            result = (await c.trade_rpc("status", transaction_id=outcome.transaction_id))["trade"]
            with self.assertRaises(TradeError) as caught:
                await c.trade_rpc("ack", transaction_id=outcome.transaction_id, revision=result["revision"], sha256="0"*64)
            self.assertEqual(caught.exception.code, "trade_ack_mismatch")
            for operation, fields in (("status", {}), ("ack", dict(revision=result["revision"], sha256=result["sha256"]))):
                with self.assertRaises(TradeError) as caught:
                    await stranger._companion.trade_rpc(operation, transaction_id=outcome.transaction_id, **fields)
                self.assertEqual(caught.exception.code, "trade_not_participant")
            self.assertEqual((await stranger._companion.trade_rpc("pending"))["recoveries"], [])
            await host.readiness()
            self.assertEqual(len((await c.trade_rpc("pending"))["recoveries"]), 1)
            with MirrorLease(host.profile_directory / "character.sav"):
                with self.assertRaises(LauncherSessionError) as caught:
                    await host.play()
            self.assertEqual(caught.exception.code, "mirror_active")
            self.assertEqual(len((await c.trade_rpc("pending"))["recoveries"]), 1)
            host._store.integrity_check()

    async def test_lost_recovery_ack_prevents_spawn_then_fresh_default_host_resumes(self):
        self.committed_trade()
        host = self.session()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with host.open():
                original = host._server._trade_reply
                dropped = []
                def drop_ack(session, request, **fields):
                    if request["type"] == "trade_ack" and fields.get("trade", {}).get("state") == "acknowledged":
                        dropped.append(True)
                        session.close("test_lost_recovery_ack")
                        return
                    return original(session, request, **fields)
                with patch.object(host._server, "_trade_reply", side_effect=drop_ack):
                    with self.assertRaises(LauncherSessionError):
                        await host.play()
                self.assertEqual(dropped, [True])
                self.assertFalse(self.children)
                self.assertTrue(list(host.profile_directory.glob("closed-recoveries/*/applied.json")))
            resumed = self.session()
            async with resumed.open():
                self.assertIsNone(resumed._server.trade_desk)
                self.assertEqual(resumed.status.revision, 2)
                await self.finish_game(resumed)
                self.assertEqual((await resumed._companion.trade_rpc("pending"))["recoveries"], [])
                resumed._store.integrity_check()

    async def test_unresolved_local_trade_intent_still_refuses_default_host_launch(self):
        session = self.session()
        async with session.open():
            pending = session.profile_directory / "pending-trade.json"
            raw = b"corrupt unresolved trade fixture"
            pending.write_bytes(raw)
            with self.assertRaises(LauncherSessionError):
                await session.play()
            self.assertEqual(pending.read_bytes(), raw)
            self.assertFalse((session.profile_directory / "character.sav").exists())
            self.assertFalse(self.children)

    async def test_missing_canonical_enrollment_never_creates_a_character(self):
        host, friend = self.session(), self.friend(2)
        async with host.open(), friend.open():
            self.assertEqual(friend.status.code, "enrollment_required")
            with self.assertRaises(LauncherSessionError) as caught:
                await friend.play()
            self.assertEqual(caught.exception.code, "enrollment_required")
            self.assertFalse((friend.profile_directory / "character.sav").exists())
            self.assertIsNone(host._store.read_checkpoint(self.host.accounts[2].player_id,
                                                         friend._companion.session_epoch))

    async def test_pending_battle_even_malformed_is_preserved_and_blocks_launch(self):
        session = self.session()
        directory = self.private / "players" / self.host.world_id / self.host.accounts[0].player_id
        directory.mkdir(parents=True)
        pending = directory / "pending-battle.json"
        pending.write_bytes(b"uncertain native hold, deliberately malformed fixture")
        before = pending.read_bytes()
        async with session.open():
            self.assertEqual(session.status.code, "pending_battle")
            with self.assertRaises(LauncherSessionError) as caught:
                await session.play()
            self.assertEqual(caught.exception.code, "pending_battle")
            self.assertEqual(pending.read_bytes(), before)
            self.assertFalse((directory / "character.sav").exists())

    async def test_runtime_owns_lock_until_normal_exit_and_single_launch_only(self):
        session = self.session()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with session.open():
                task = asyncio.create_task(session.play())
                await asyncio.wait_for(self.spawned.wait(), 10)
                await asyncio.sleep(0)
                save = session.profile_directory / "character.sav"
                with self.assertRaises(MirrorError):
                    with MirrorLease(save):
                        self.fail("running child lost its save lease")
                with self.assertRaises(LauncherSessionError) as caught:
                    await session.play()
                self.assertEqual(caught.exception.code, "game_active")
                self.children[0].terminate()
                result = await asyncio.wait_for(task, 10)
                self.assertEqual(session.status.state, SessionState.FINISHED)
                self.assertEqual(session.status.exit_code, result)
                self.assertEqual((await session.readiness()).state, SessionState.FINISHED)
                with MirrorLease(save):
                    pass
                with self.assertRaises(LauncherSessionError) as caught:
                    await session.play()
                self.assertEqual(caught.exception.code, "already_played")
                self.assertEqual(session._store.read_checkpoint(session._companion.config.player_id,
                    session._companion.session_epoch).payload, self.payloads[session._companion.config.player_id])
        self.assertEqual(len(self.children), 1)
        with self.assertRaises(LauncherSessionError) as caught:
            await session.readiness()
        self.assertEqual(caught.exception.code, "session_closed")
        self.assertEqual(session.status.state, SessionState.CLOSED)

    async def test_context_exit_drains_child_before_closing_companion_and_store(self):
        session = self.session()
        closed = []
        original_close = Companion.close
        async def close(companion):
            self.assertIsNotNone(self.children[0].returncode)
            with MirrorLease(session.profile_directory / "character.sav"):
                pass
            closed.append("companion")
            await original_close(companion)
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn), \
                patch.object(Companion, "close", close):
            async with session.open():
                task = asyncio.create_task(session.play())
                await asyncio.wait_for(self.spawned.wait(), 10)
        self.assertTrue(task.cancelled())
        self.assertEqual(closed, ["companion"])
        with self.host.open_store() as store:
            store.integrity_check()

    async def test_repeated_cancellation_during_creation_drains_child_and_save_lock(self):
        session = self.session()
        release_spawn = asyncio.Event()
        async def delayed(*args, **kwargs):
            child = await self.spawn(*args, **kwargs)
            await release_spawn.wait()
            return child
        async def run():
            async with session.open():
                await session.play()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", delayed):
            task = asyncio.create_task(run())
            await asyncio.wait_for(self.spawned.wait(), 10)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            save = session.profile_directory / "character.sav"
            with self.assertRaises(MirrorError):
                with MirrorLease(save):
                    self.fail("pending process creation lost the save lease")
            release_spawn.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 10)
        self.assertIsNotNone(self.children[0].returncode)
        with MirrorLease(save):
            pass
        self.assertFalse(session.status.connected)

    async def test_bundle_tamper_after_readiness_prevents_spawn(self):
        session = self.session()
        async with session.open():
            (self.installation.bundle.directory / "SDL2.dll").write_bytes(b"changed")
            with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
                with self.assertRaises(LauncherSessionError) as caught:
                    await session.play()
            self.assertEqual(caught.exception.code, "runtime_hash")
        self.assertFalse(self.children)

    async def test_another_controller_save_lock_prevents_native_creation(self):
        session = self.session()
        async with session.open():
            save = session.profile_directory / "character.sav"
            with MirrorLease(save), patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
                with self.assertRaises(LauncherSessionError) as caught:
                    await session.play()
            self.assertEqual(caught.exception.code, "mirror_active")
            self.assertFalse(save.exists())
        self.assertFalse(self.children)

    async def test_running_disconnect_reports_status_without_settling_or_releasing_game(self):
        session = self.session()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with session.open():
                task = asyncio.create_task(session.play())
                await asyncio.wait_for(self.spawned.wait(), 10)
                async with asyncio.timeout(10):
                    while session.status.state is not SessionState.RUNNING:
                        await asyncio.sleep(.01)
                session._companion._remote_writer.close()
                async with asyncio.timeout(10):
                    while session.status.code not in {"connection_lost", "session_changed"}:
                        await asyncio.sleep(.01)
                self.assertEqual(session.status.state, SessionState.RUNNING)
                self.assertIsNone(self.children[0].returncode)
                with self.assertRaises(MirrorError):
                    with MirrorLease(session.profile_directory / "character.sav"):
                        self.fail("transport loss released a live game's save lease")
                self.children[0].terminate()
                await asyncio.wait_for(task, 10)

    async def test_exact_application_game_pins_reject_manifest_or_rom_change_before_host_boot(self):
        for field in ("rom_sha256", "manifest_sha256"):
            session = self.session()
            session.installation = replace(self.installation, **{field: "0"*64})
            with self.assertRaises(LauncherSessionError) as caught:
                async with session.open():
                    self.fail("untrusted installation may not open")
            self.assertEqual(caught.exception.code, "installation_changed")
            self.assertIsNone(session._store)
            self.assertEqual(session.status.state, SessionState.FAILED)

    async def test_internet_world_listens_on_every_interface_and_the_host_game_uses_loopback(self):
        from emerald_multiplayer.network_settings import WorldNetwork
        session = self.session(bind_address="0.0.0.0", host_route=None, public=True, network=WorldNetwork(router_setup=False))
        async with session.open():
            self.assertEqual(session.status.state, SessionState.READY)
            self.assertEqual(session._server.address[0], "0.0.0.0")
            self.assertEqual(session.companion.config.server_host, "127.0.0.1")
            self.assertTrue(session.status.connected)

    async def test_unavailable_host_times_out_without_starting_a_game(self):
        session = self.friend(connection_timeout=.15)
        with self.assertRaises(LauncherSessionError) as caught:
            async with session.open():
                self.fail("unavailable host cannot authorize play")
        self.assertEqual(caught.exception.code, "connection_timeout")
        self.assertFalse(session.status.connected)
        self.assertIsNone(session._runtime)

    async def test_changed_authenticated_lease_refuses_launch_without_automatic_recovery(self):
        session = self.session()
        async with session.open():
            c = session._companion
            # Close the real transport and let the existing companion reconnect.
            # The host issues a fresh authenticated lease, without ROM edits.
            c._remote_writer.close()
            async with asyncio.timeout(10):
                while not c.connected or session._signature() == session._binding:
                    await asyncio.sleep(.01)
            self.assertEqual(session.status.code, "session_changed")
            with self.assertRaises(LauncherSessionError) as caught:
                await session.play()
            self.assertEqual(caught.exception.code, "session_changed")
            self.assertFalse((session.profile_directory / "character.sav").exists())

    async def test_status_and_errors_never_expose_credentials_or_raw_exception(self):
        statuses = []
        def observer(status):
            statuses.append(asdict(status))
            raise ValueError("observer must not cancel lifecycle")
        session = self.session(on_status=observer)
        async with session.open():
            secret = session._companion.config.server_credential.hex()
            token = session._companion.config.token.hex()
            with patch.object(session.installation.__class__, "verify", side_effect=ValueError(secret+token)):
                with self.assertRaises(LauncherSessionError) as caught:
                    await session.play()
            output = json.dumps(statuses) + str(caught.exception) + repr(caught.exception)
            self.assertNotIn(secret, output)
            self.assertNotIn(token, output)
            self.assertEqual(caught.exception.code, "session_failed")
            self.assertGreater(session.observer_errors, 0)

    async def test_reopen_and_conflicting_configuration_are_refused(self):
        session = self.session()
        async with session.open():
            with self.assertRaises(LauncherSessionError) as caught:
                async with session.open():
                    self.fail("one session cannot enter twice")
            self.assertEqual(caught.exception.code, "session_active")
        with self.assertRaises(LauncherSessionError):
            async with session.open():
                self.fail("closed sessions are single-use")
        for fields in ({}, {"world_directory": self.host.directory, "invitation_path": "both"},
                       {"world_directory": self.host.directory, "bind_address": "0.0.0.0"},
                       {"invitation_path": "friend", "development_trades": True},
                       {"invitation_path": "friend", "connection_timeout": True}):
            self.assert_code("invalid_configuration", LauncherSession, self.installation, self.private, **fields)
