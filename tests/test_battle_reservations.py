"""Real SQLite/Flash/TCP and simulated native receipts; no battle-resume claim."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.battle_desk import BattleDesk
from emerald_multiplayer.character_transfers import EXTENSION_VERSION as TRANSFERS
from emerald_multiplayer.battle_protocol import validate_battle_reply
from emerald_multiplayer.battle_reservations import (
    BattleReservations, SCOPE, enable_battle_reservations, validate_waiting,
)
from emerald_multiplayer.native_battle import Opcode
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.storage import StorageError
from emerald_multiplayer.trade_storage import TradeCheckpointStore
import test_battle_desk as fixture
import test_battle_arbitration as network


class ReservationMigrationTests(unittest.TestCase):
    def test_populated_trade_world_migration_preserves_owned_bytes_provenance_and_unacknowledged_fate(self):
        from test_trade_storage import TradeStorageTests
        legacy=TradeStorageTests(methodName="runTest")
        legacy.setUp()
        try:
            result=legacy.trade()
            for p,lease in zip(legacy.players,legacy.leases):legacy.store.release_lease(p.player_id,lease)
            original={table:[tuple(r) for r in legacy.store._connection.execute("SELECT * FROM "+table)]
                      for table in legacy.store._schema}
            backup=Path(legacy.temp.name)/"populated-legacy.sqlite3"
            enable_battle_reservations(legacy.store,backup)
            for table,rows in original.items():
                self.assertEqual([tuple(r) for r in legacy.store._connection.execute("SELECT * FROM "+table)],rows)
            legacy.store.integrity_check()
            with TradeCheckpointStore(backup,legacy.store.build_id,legacy.store.ruleset_id) as saved:
                self.assertEqual(saved._schema_version,3)
                for table,rows in original.items():
                    self.assertEqual([tuple(r) for r in saved._connection.execute("SELECT * FROM "+table)],rows)
            for p in legacy.players:
                lease=legacy.store.acquire_lease(p.player_id,p.credential)
                recoveries=legacy.store.pending_trade_recovery(p.player_id,lease)
                self.assertEqual(len(recoveries),1)
                self.assertEqual(recoveries[0].transaction_id,result.transaction_id)
        finally:
            legacy.tearDown()

    def test_existing_host_descriptor_and_credentials_reopen_after_explicit_capability_migration(self):
        from emerald_multiplayer.host_world import HostWorld
        from test_host_world import make_trade_files
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            rom,manifest=make_trade_files(root)
            host=HostWorld.create(root/"host",rom,manifest,player_names=["Owner","Friend"],endpoint="127.0.0.1",port=8765)
            with host.open_store() as store:
                enable_battle_reservations(store,root/"legacy-backup.sqlite3")
            reopened=HostWorld.open(host.directory,rom,manifest)
            self.assertEqual(reopened,host)
            with reopened.open_store() as store:
                self.assertEqual(store._schema_version,103+TRANSFERS)   # a new world takes its characters back too
                self.assertEqual(store.metadata.world_id,host.world_id)
                WorldServer(ServerConfig(host.build_id,host.ruleset_id),store=store)

    def test_explicit_102_and_103_migrations_keep_verified_legacy_backups_and_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            for cls, version in ((OwnershipCheckpointStore, 2), (TradeCheckpointStore, 3)):
                path = Path(directory)/f"world-{version}.sqlite3"
                backup = Path(directory)/f"before-{version}.sqlite3"
                with cls(path, "build", "rules") as store:
                    before = store.metadata
                    original = tuple(store._connection.iterdump())
                    self.assertFalse(store.battle_reservations_enabled)
                    self.assertTrue(enable_battle_reservations(store, backup))
                    self.assertEqual(store.metadata, before)
                    self.assertEqual(store._schema_version, 100+version)
                    self.assertFalse(enable_battle_reservations(store, Path(directory)/"unused.sqlite3"))
                    self.assertFalse((Path(directory)/"unused.sqlite3").exists())
                with cls(backup, "build", "rules") as old:
                    self.assertFalse(old.battle_reservations_enabled)
                    self.assertEqual(tuple(old._connection.iterdump()), original)
                with cls(path, "build", "rules") as reopened:
                    self.assertTrue(reopened.battle_reservations_enabled)
                    self.assertEqual(reopened.metadata, before)

    def test_open_never_enables_legacy_and_backup_collision_or_active_lease_cannot_migrate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TradeCheckpointStore(root/"world.sqlite3", "build", "rules") as store:
                store.begin_server_boot()
                p = store.create_player("Owner")
                lease = store.acquire_lease(p.player_id, p.credential)
                with self.assertRaisesRegex(StorageError, "close authenticated"):
                    enable_battle_reservations(store, root/"backup.sqlite3")
                self.assertFalse((root/"backup.sqlite3").exists())
                store.release_lease(p.player_id, lease)
                (root/"backup.sqlite3").write_bytes(b"keep")
                with self.assertRaises(StorageError): enable_battle_reservations(store, root/"backup.sqlite3")
                self.assertEqual((root/"backup.sqlite3").read_bytes(), b"keep")
                self.assertEqual(store._schema_version, 3)
            with TradeCheckpointStore(root/"world.sqlite3", "build", "rules") as reopened:
                self.assertFalse(reopened.battle_reservations_enabled)
                with self.assertRaises(StorageError):
                    WorldServer(ServerConfig("build", "rules"), store=reopened, development_battles=True)

    def test_existing_host_lock_blocks_migration_before_backup_or_schema_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TradeCheckpointStore(root/"world.sqlite3", "build", "rules") as owner:
                owner.begin_server_boot()
                with TradeCheckpointStore(owner.path, "build", "rules") as other:
                    with self.assertRaises(StorageError) as caught:
                        enable_battle_reservations(other, root/"blocked.sqlite3")
                    self.assertEqual(caught.exception.code, "host_active")
                    self.assertFalse((root/"blocked.sqlite3").exists())
                    self.assertFalse(other.battle_reservations_enabled)

    def test_failed_migration_rolls_back_tables_and_version_but_retains_verified_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with TradeCheckpointStore(root/"world.sqlite3","build","rules") as store:
                original=tuple(store._connection.iterdump())
                with patch.object(BattleReservations,"_integrity",side_effect=StorageError("test_failure","migration failed")):
                    with self.assertRaises(StorageError):enable_battle_reservations(store,root/"backup.sqlite3")
                self.assertFalse(store.battle_reservations_enabled)
                self.assertEqual(tuple(store._connection.iterdump()),original)
                store.integrity_check()
            with TradeCheckpointStore(root/"backup.sqlite3","build","rules") as old:
                self.assertEqual(tuple(old._connection.iterdump()),original)


class ReservationTests(unittest.TestCase):
    setUp = fixture.BattleDeskTests.setUp
    tearDown = fixture.BattleDeskTests.tearDown
    actor = fixture.BattleDeskTests.actor
    call = fixture.BattleDeskTests.call
    accept = fixture.BattleDeskTests.accept
    register = fixture.BattleDeskTests.register
    descriptor = fixture.BattleDeskTests.descriptor
    control = fixture.BattleDeskTests.control
    query = fixture.BattleDeskTests.query
    bind = fixture.BattleDeskTests.bind
    prepare = fixture.BattleDeskTests.prepare
    prepared = fixture.BattleDeskTests.prepared
    start = fixture.BattleDeskTests.start
    parts = fixture.BattleDeskTests.parts
    running = fixture.BattleDeskTests.running
    finish = fixture.BattleDeskTests.finish
    release = fixture.BattleDeskTests.release
    assert_code = fixture.BattleDeskTests.assert_code

    def reboot(self):
        path = self.store.path
        self.store.close()
        self.store = TradeCheckpointStore(path, "test-build", "test-rules")
        self.store.begin_server_boot()
        self.leases = {p.player_id:self.store.acquire_lease(p.player_id,p.credential) for p in self.players}
        self.desk = BattleDesk(self.store, self.leases.get)
        return self.desk.reservations

    def test_uncertain_first_bind_survives_backup_restart_new_lease_and_time_without_resume(self):
        self.register(); self.call("authorize_bind",0)
        waiting = self.desk.reservations.waiting(*self.actor(0))
        self.assertEqual(len(waiting),1)
        self.assertIs(waiting[0]["resume_supported"],False)
        self.assertEqual(waiting[0]["state"],"waiting")
        self.assertEqual(set(waiting[0]),{"scope","battle_id","generation","mode","players","state","resume_supported"})
        old_actor = self.actor(0)
        backup = self.store.backup(Path(self.temp.name)/"held-backup.sqlite3")
        registry = self.reboot()
        self.assertEqual(registry.waiting(*self.actor(0)),waiting)
        self.assert_code("stale_lease",registry.waiting,*old_actor)
        self.assertEqual(registry.waiting(*self.actor(2)),[])
        self.assert_code("battle_busy",self.desk.invite,*self.actor(2),self.players[0].player_id,str(uuid4()))
        for i in (0,1):
            cp = self.heads[i]
            self.assert_code("battle_busy",self.store.commit_checkpoint,*self.actor(i),str(uuid4()),1,
                cp.payload,self.store.build_id,self.store.ruleset_id,OWNERSHIP_PROFILE)
            self.assert_code("battle_busy",self.store.reserve_instances,*self.actor(i),str(uuid4()),1,100+i,32)
            self.assertEqual(self.store.read_checkpoint(*self.actor(i)),cp)
        with TradeCheckpointStore(backup,"test-build","test-rules") as copy:
            copy.begin_server_boot()
            lease=copy.acquire_lease(self.players[0].player_id,self.players[0].credential)
            self.assertEqual(BattleReservations(copy).waiting(self.players[0].player_id,lease),waiting)

    def test_durable_reservation_commits_before_in_memory_dispatch_authority(self):
        self.register()
        original = self.desk.reservations._reserve
        def uncertain(*args):
            original(*args)
            raise StorageError("test_uncertain","lost commit acknowledgment")
        with patch.object(self.desk.reservations,"_reserve",side_effect=uncertain):
            self.assert_code("test_uncertain",self.call,"authorize_bind",0)
        self.assertFalse(self.desk._active[self.battle_id].bind_intent)
        self.assertEqual(len(self.desk.reservations.waiting(*self.actor(1))),1)
        self.call("authorize_bind",0)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM battle_reservations").fetchone()[0],1)

    def test_terminal_commit_failure_keeps_barrier_and_exact_release_retry_finishes(self):
        self.running(); self.finish(0); self.finish(1); self.release(0)
        with patch.object(self.desk.reservations,"_finish",side_effect=StorageError("test_failure","write failed")):
            self.assert_code("test_failure",self.release,1)
        self.assertEqual(len(self.desk.reservations.waiting(*self.actor(0))),1)
        self.assertEqual(self.call("status",0)["state"],"release_authorized")
        result,request,response = self.release(1)
        self.assertEqual(result["state"],"closed")
        self.assertEqual(self.call("released",1,request,response),result)
        self.assertEqual(self.reboot().waiting(*self.actor(0)),[])
        self.assert_code("battle_reservation_conflict",self.desk.invite,*self.actor(0),self.players[1].player_id,self.battle_id)

    def test_terminal_uncertain_commit_still_recovers_as_closed_without_releasing_native_again(self):
        self.running(); self.finish(0); self.finish(1); self.release(0)
        original=self.desk.reservations._finish
        def uncertain(*args):
            original(*args)
            raise StorageError("test_uncertain","lost commit acknowledgment")
        with patch.object(self.desk.reservations,"_finish",side_effect=uncertain):
            self.assert_code("test_uncertain",self.release,1)
        self.assertEqual(self.call("status",0)["state"],"release_authorized")
        self.assertEqual(self.reboot().waiting(*self.actor(0)),[])

    def test_only_complete_prestart_abort_acknowledgments_clear_durable_barrier(self):
        self.prepared(); self.call("cancel",0)
        for i in (0,1):
            req=self.control(i,Opcode.ABORT_PRE_START,3)
            self.call("aborted",i,req,replace(req,data=b""))
            self.assertEqual(bool(self.desk.reservations.waiting(*self.actor(0))),i==0)
        self.assertEqual(self.reboot().waiting(*self.actor(1)),[])

    def test_corrupt_row_or_missing_actor_fails_before_listener_and_direct_mutations(self):
        self.register();self.call("authorize_bind",0)
        self.store._connection.execute("UPDATE battle_reservations SET sha256=?",("0"*64,))
        with self.assertRaises(StorageError):WorldServer(ServerConfig("test-build","test-rules"),store=self.store)
        self.assert_code("battle_reservation_invalid",self.desk.reservations.waiting,*self.actor(0))
        path=self.store.path;self.store.close()
        with self.assertRaises(StorageError):TradeCheckpointStore(path,"test-build","test-rules")

    def test_missing_registry_table_or_actor_is_not_treated_as_no_hold(self):
        self.register();self.call("authorize_bind",0)
        self.store._connection.execute("DELETE FROM battle_reservation_actors")
        with self.assertRaises(StorageError):self.store.reserve_instances(*self.actor(0),str(uuid4()),1,100,32)
        self.store._connection.execute("DROP TABLE battle_reservation_actors")
        with self.assertRaises(StorageError):WorldServer(ServerConfig("test-build","test-rules"),store=self.store)
        path=self.store.path;self.store.close()
        with self.assertRaises(StorageError):TradeCheckpointStore(path,"test-build","test-rules")

    def test_waiting_codec_rejects_foreign_identity_resume_authority_and_private_fields(self):
        self.register();self.call("authorize_bind",0)
        value=self.desk.reservations.waiting(*self.actor(0))[0]
        validate_waiting(value,self.actor(0)[0])
        with self.assertRaises(ProtocolError):validate_waiting(value,self.actor(2)[0])
        for field,data in (("resume_supported",True),("state","running"),("rng","00"*16),("leases",[1,2])):
            bad=deepcopy(value);bad[field]=data
            with self.subTest(field=field),self.assertRaises(ProtocolError):validate_waiting(bad,self.actor(0)[0])

    def test_archived_result_before_terminal_failure_retains_hold_and_retries_without_duplication(self):
        from emerald_multiplayer.battle_results import BattleResults
        archive=BattleResults(Path(self.temp.name)/"results.sqlite3",world_id=self.store.metadata.world_id,
            build_id=self.store.build_id,ruleset_id=self.store.ruleset_id)
        self.desk.results=archive
        self.running();self.finish(0);self.finish(1);self.release(0)
        with patch.object(self.desk.reservations,"_finish",side_effect=StorageError("test_failure","write failed")):
            self.assert_code("test_failure",self.release,1)
        before=archive.history(self.actor(0)[0])
        self.assertEqual(len(before),1)
        self.assertEqual(len(self.desk.reservations.waiting(*self.actor(0))),1)
        self.release(1)
        self.assertEqual(archive.history(self.actor(0)[0]),before)
        self.assertEqual(self.reboot().waiting(*self.actor(0)),[])


class ReservationNetworkTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=network.BattleArbitrationTests.asyncSetUp
    asyncTearDown=network.BattleArbitrationTests.asyncTearDown
    actor=network.BattleArbitrationTests.actor
    call=network.BattleArbitrationTests.call
    register=network.BattleArbitrationTests.register
    descriptor=network.BattleArbitrationTests.descriptor
    control=network.BattleArbitrationTests.control
    query=network.BattleArbitrationTests.query
    bind=network.BattleArbitrationTests.bind
    multi=network.BattleArbitrationTests.multi
    error=network.BattleArbitrationTests.error
    fingerprint=network.BattleArbitrationTests.fingerprint

    async def test_four_players_rejoin_disabled_host_and_stay_reserved_without_public_release(self):
        self.multi();self.register();self.bind(0,ack=False)
        before=[await a.rpc("battle_waiting") for a in self.actors]
        for result in before:
            self.assertEqual(len(result["result"]),1)
            self.assertIs(result["result"][0]["resume_supported"],False)
        old_leases=[a.lease for a in self.actors]
        for actor in self.actors:await actor.close()
        await self.server.close();self.store.close()
        self.store=TradeCheckpointStore(self.root/"world.sqlite3",network.BUILD,network.RULES)
        self.server=WorldServer(ServerConfig(network.BUILD,network.RULES,heartbeat_interval=.05,idle_timeout=20),store=self.store)
        await self.server.start(port=0)
        self.actors=[await network.Actor.connect(self.server.address,p) for p in self.players]
        self.assertIsNone(self.server.battle_desk)
        for i,actor in enumerate(self.actors):
            self.assertNotEqual(actor.lease,old_leases[i])
            result=await actor.rpc("battle_waiting")
            validate_battle_reply(result,self.players[i].player_id,self.store.metadata.world_id,actor.lease)
            self.assertEqual(result["result"],before[i]["result"])
            await self.error(i,"checkpoint_begin",**self.fingerprint(i))
            await self.error(i,"ownership_grant",expected_revision=1,incarnation=100+i,count=32)
            self.assertEqual((await actor.rpc("checkpoint_info"))["checkpoint"]["revision"],1)
            self.assertEqual((await actor.rpc("battle_history"))["result"],[])
        self.store.integrity_check()
