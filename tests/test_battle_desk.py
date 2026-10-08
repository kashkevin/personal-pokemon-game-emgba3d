from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import struct
import tempfile
import unittest
from uuid import UUID, uuid4

from emerald_multiplayer.battle_desk import BattleDesk, BattleError
from emerald_multiplayer.battle_reservations import enable_battle_reservations
from emerald_multiplayer.native_battle import Kind, NativeControl, Opcode
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.storage import StorageError
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from test_ownership_storage import source_flash, owned_flash


class BattleDeskTests(unittest.TestCase):
    """Real SQLite/Flash fixtures, correlated fake native receipts; no game proof."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TradeCheckpointStore(Path(self.temp.name)/"world.sqlite3", "test-build", "test-rules")
        enable_battle_reservations(self.store, Path(self.temp.name)/"before-battles.sqlite3")
        self.store.begin_server_boot()
        self.players, self.heads = [], []
        self.leases = {}
        for i in range(4):
            player = self.store.create_player(f"Trainer {i}")
            lease = self.store.acquire_lease(player.player_id, player.credential)
            self.leases[player.player_id] = lease
            self.store.enroll_player(player.player_id,
                source_flash(("party:0", "party:1"), personalities=(i*2+7,i*2+8)))
            grant = self.store.reserve_instances(player.player_id,lease,str(uuid4()),0,1,32)
            payload = owned_flash(grant,(("party:0",grant.start),("party:1",grant.start+1)),
                                  personalities=(i*2+7,i*2+8))
            checkpoint = self.store.commit_checkpoint(player.player_id,lease,str(uuid4()),0,payload,
                self.store.build_id,self.store.ruleset_id,OWNERSHIP_PROFILE)
            self.players.append(player); self.heads.append(checkpoint)
        self.now = 0
        self.desk = BattleDesk(self.store,self.leases.get,timeout=10,clock=lambda:self.now)
        self.battle_id = str(uuid4())
        self.view = self.desk.invite(*self.actor(0),self.players[1].player_id,self.battle_id)
        self.generation = self.view["generation"]

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def actor(self, index):
        player = self.players[index].player_id
        return player,self.leases[player]

    def call(self, method, index, *args, **kwargs):
        fields = () if method == "status" else (self.generation,)
        return getattr(self.desk,method)(*self.actor(index),self.battle_id,*fields,*args,**kwargs)

    def accept(self):
        return self.call("accept",1,self.view["fingerprint"])

    def register(self):
        self.accept()
        for i in (0,1):self.call("register",i,100+i)

    def descriptor(self,index):
        return self.call("descriptor",index)

    def control(self,index,opcode,seq,*,data=b""):
        descriptor = self.descriptor(index)
        return NativeControl(100+index,self.actor(index)[1],self.battle_id,seq,opcode,
                             source_slot=descriptor.source_slot,data=data,phase=descriptor.mode)

    def query(self,index,seq,flags=1,*,revision=0,outcome=0,generation=None):
        return struct.pack("<I16sBBBB10I",flags,UUID(generation or self.generation).bytes,
            len(self.view["players"]),self.descriptor(index).source_slot,self.descriptor(index).mode,
            0,seq,0,0,0,0,0,0,600,revision,outcome)

    def bind(self,index):
        binding = self.call("authorize_bind",index)
        request = self.control(index,Opcode.BIND,1,data=binding.pack())
        response = replace(request,data=self.query(index,1))
        self.call("bound",index,request,response)
        return request,response

    def prepare(self,index):
        self.bind(index)
        request = self.control(index,Opcode.PREPARE,2,data=self.call("preparation",index).pack())
        response = replace(request,data=self.query(index,2,9,revision=1))
        trainer = self.descriptor(index).trainer_descriptor
        self.call("prepared",index,request,response,trainer)
        return request,response,trainer

    def prepared(self):
        self.register()
        for i in (0,1):self.prepare(i)

    def start(self,index):
        request = self.control(index,Opcode.START,3)
        response = replace(request,data=self.query(index,3,25,revision=1))
        self.call("started",index,request,response)
        return request,response

    def parts(self,index):
        descriptor = self.descriptor(index)
        for part in range(3):
            self.call("verify_startup",index,Kind.PARTY_0+part,part+3,
                      descriptor.party[part*200:part*200+200])

    def running(self):
        self.prepared()
        self.desk.authorize_start(self.battle_id,self.generation)
        for i in (0,1):self.start(i);self.parts(i)
        return self.desk.authorize_running(self.battle_id,self.generation)

    def finish(self,index,*,outcome=1,seq=4,party=None,count=None):
        descriptor = self.descriptor(index)
        request = self.control(index,Opcode.QUERY,seq)
        response = replace(request,data=self.query(index,seq-1,57,revision=1,outcome=outcome))
        fields = dict(outcome=outcome,party=descriptor.party if party is None else party,
                      party_count=descriptor.party_count if count is None else count)
        result = self.call("finish",index,request,response,**fields)
        return result,request,response,fields

    def release(self,index,seq=4):
        request = self.control(index,Opcode.RELEASE,seq,
            data=struct.pack("<II",self.descriptor(index).party_crc32,1))
        response = replace(request,data=b"")
        result = self.call("released",index,request,response)
        return result,request,response

    def assert_code(self,code,function,*args,**kwargs):
        with self.assertRaises(StorageError) as caught:function(*args,**kwargs)
        self.assertEqual(caught.exception.code,code)

    def test_only_recipient_accepts_exact_fingerprint_and_no_implicit_readiness(self):
        self.assertEqual(self.view["consent"],[self.players[0].player_id])
        self.assert_code("battle_not_recipient",self.call,"accept",0,self.view["fingerprint"])
        self.assert_code("battle_not_participant",self.call,"accept",2,self.view["fingerprint"])
        self.assert_code("battle_offer_changed",self.call,"accept",1,"0"*64)
        self.assert_code("battle_not_ready",self.desk.authorize_start,self.battle_id,self.generation)
        first = self.accept()
        self.assertEqual(first,self.accept())
        self.assertEqual(set(first["consent"]),{p.player_id for p in self.players[:2]})
        self.assert_code("battle_not_registered",self.call,"authorize_bind",0)
        self.assertFalse(first["prepared"])

    def test_exact_acceptance_replay_does_not_refresh_challenge_deadline(self):
        self.now = 1;self.accept()
        self.now = 10;self.accept()
        self.now = 11
        self.assertEqual(self.call("status",0)["state"],"aborted")

    def test_captured_roles_canonical_bytes_and_single_issued_rng_are_immutable(self):
        self.register()
        a,b = self.call("authorize_bind",0),self.call("authorize_bind",1)
        self.assertEqual(a.players,tuple(sorted(p.player_id for p in self.players[:2])))
        self.assertEqual(a.players,b.players);self.assertEqual(a.generation,b.generation)
        self.assertEqual({a.local_slot,b.local_slot},{0,1})
        self.prepare(0);self.prepare(1)
        prep0,prep1 = self.call("preparation",0),self.call("preparation",1)
        self.assertEqual(prep0.rng,prep1.rng);self.assertTrue(any(prep0.rng))
        self.assertEqual(prep0,self.call("preparation",0))
        self.assertEqual(self.desk.invite(*self.actor(0),self.players[1].player_id,self.battle_id)["fingerprint"],self.view["fingerprint"])
        self.assertNotIn("'party':",str(self.call("status",0)))
        self.assertNotIn("rng",str(self.call("status",0)))
        self.assertEqual(self.descriptor(0).party_count,2)

    def test_both_bind_and_prepare_receipts_precede_start_and_party_transport(self):
        self.register();self.prepare(0)
        self.assert_code("battle_not_ready",self.desk.authorize_start,self.battle_id,self.generation)
        self.prepare(1)
        self.assertEqual(self.desk.authorize_start(self.battle_id,self.generation)["state"],"starting")
        self.start(0);self.parts(0)
        self.assert_code("battle_not_ready",self.desk.authorize_running,self.battle_id,self.generation)
        self.start(1);self.parts(1)
        self.assertEqual(self.call("status",0)["state"],"starting")
        self.assertEqual(self.desk.authorize_running(self.battle_id,self.generation)["state"],"running")

    def test_reserved_peer_checkpoint_refuses_without_changing_consent_or_hold(self):
        self.register();self.bind(0)
        old = self.heads[1]
        self.assert_code("battle_busy",self.store.commit_checkpoint,*self.actor(1),str(uuid4()),old.revision,
            old.payload,self.store.build_id,self.store.ruleset_id,OWNERSHIP_PROFILE)
        result = self.call("status",0)
        self.assertEqual(result["state"],"accepted")
        self.assertEqual(set(result["consent"]),{p.player_id for p in self.players[:2]})
        self.assertEqual(self.store.read_checkpoint(*self.actor(1)),old)
        self.assert_code("battle_busy",self.desk.invite,*self.actor(0),self.players[2].player_id,str(uuid4()))

    def test_unbound_cancel_has_terminal_retry_and_cannot_reuse_id_for_new_peer(self):
        result = self.call("cancel",1)
        self.assertEqual(result["state"],"aborted")
        self.assertEqual(result,self.call("cancel",0))
        self.assertEqual(result,self.desk.invite(*self.actor(0),self.players[1].player_id,self.battle_id))
        self.assert_code("request_conflict",self.desk.invite,*self.actor(0),self.players[2].player_id,self.battle_id)

    def test_lost_bind_ack_retains_abort_barrier_until_exact_success(self):
        self.register()
        self.call("authorize_bind",0)  # Command may have executed; no ACK yet.
        result = self.call("cancel",1)
        self.assertEqual(result["state"],"aborting")
        self.assert_code("battle_busy",self.desk.invite,*self.actor(0),self.players[2].player_id,str(uuid4()))
        request = self.control(0,Opcode.ABORT_PRE_START,2)
        response = replace(request,data=b"")
        result = self.call("aborted",0,request,response)
        self.assertEqual(result["state"],"aborted")
        self.assertEqual(result,self.call("aborted",0,request,response))
        self.desk.invite(*self.actor(0),self.players[2].player_id,str(uuid4()))

    def test_cancel_after_prepare_needs_both_abort_acknowledgments(self):
        self.prepared();result = self.call("cancel",0)
        self.assertEqual(set(result["abort_pending"]),{p.player_id for p in self.players[:2]})
        for index in (0,1):
            request = self.control(index,Opcode.ABORT_PRE_START,3)
            result = self.call("aborted",index,request,replace(request,data=b""))
            self.assertEqual(result["state"],"aborting" if index == 0 else "aborted")

    def test_refusal_during_partial_abort_does_not_reinsert_acknowledged_actor(self):
        self.prepared();self.call("cancel",0)
        request = self.control(0,Opcode.ABORT_PRE_START,3)
        self.call("aborted",0,request,replace(request,data=b""))
        result = self.call("refused",1)
        self.assertEqual(result["abort_pending"],[self.players[1].player_id])
        request = self.control(1,Opcode.ABORT_PRE_START,3)
        self.assertEqual(self.call("aborted",1,request,replace(request,data=b""))["state"],"aborted")

    def test_started_or_uncertain_start_never_cancels_or_auto_releases(self):
        self.prepared();self.desk.authorize_start(self.battle_id,self.generation)
        self.assert_code("battle_started",self.call,"cancel",0)
        self.now = 10
        result = self.call("status",0)
        self.assertEqual(result["state"],"recovery_required")
        self.assertEqual(result["released"],[]);self.assertIsNone(result["outcome"])
        self.assert_code("battle_busy",self.desk.invite,*self.actor(0),self.players[2].player_id,str(uuid4()))

    def test_disconnect_after_start_preserves_recovery_and_new_lease_can_only_observe(self):
        self.running()
        player = self.players[1]
        lease = self.leases.pop(player.player_id)
        self.assertEqual(self.call("status",0)["state"],"recovery_required")
        self.store.release_lease(player.player_id,lease)
        self.leases[player.player_id] = self.store.acquire_lease(player.player_id,player.credential)
        self.assertEqual(self.call("status",1)["state"],"recovery_required")
        self.assert_code("stale_lease",self.call,"register",1,101)
        self.assertEqual(self.call("status",0)["released"],[])

    def test_expiry_before_binding_aborts_but_after_binding_retains_hold(self):
        self.now = 10
        self.assertEqual(self.call("status",0)["state"],"aborted")
        self.battle_id = str(uuid4());self.view = self.desk.invite(*self.actor(0),self.players[1].player_id,self.battle_id)
        self.generation = self.view["generation"]
        self.register();self.bind(0)
        self.now = 20
        result = self.call("status",0)
        self.assertEqual(result["state"],"aborting")
        self.assertEqual(result["abort_pending"],[self.players[0].player_id])

    def test_incarnation_replacement_clears_consent_and_does_not_rebind_old_hold(self):
        self.register();self.bind(0)
        self.assert_code("battle_incarnation_changed",self.call,"register",0,999)
        result = self.call("status",0)
        self.assertEqual(result["state"],"aborting");self.assertEqual(result["consent"],[])
        self.assert_code("battle_state",self.call,"authorize_bind",0)

    def test_wrong_receipt_role_generation_counter_or_rng_cannot_prepare(self):
        self.register();request,response = self.bind(0)
        self.assert_code("invalid_receipt",self.call,"bound",0,request,replace(response,session_epoch=9))
        request = self.control(0,Opcode.PREPARE,2,data=self.call("preparation",0).pack())
        response = replace(request,data=self.query(0,2,9,revision=1,generation=str(uuid4())))
        self.assert_code("invalid_receipt",self.call,"prepared",0,request,response,self.descriptor(0).trainer_descriptor)
        changed = replace(self.call("preparation",0),rng=b"\x01"*16)
        request = replace(request,data=changed.pack())
        response = replace(request,data=self.query(0,2,9,revision=1))
        self.assert_code("canonical_mismatch",self.call,"prepared",0,request,response,self.descriptor(0).trainer_descriptor)
        self.assertEqual(self.call("status",0)["state"],"aborting")

    def test_native_refusal_clears_consent_without_claiming_no_hold(self):
        self.register();binding = self.call("authorize_bind",0)
        request = self.control(0,Opcode.BIND,1,data=binding.pack())
        response = replace(request,status=1,data=b"")
        self.assert_code("native_refused",self.call,"bound",0,request,response)
        result = self.call("status",0)
        self.assertEqual(result["state"],"aborting");self.assertEqual(result["consent"],[])

    def test_party_parts_are_exact_ordered_and_changed_replay_enters_recovery(self):
        self.prepared();self.desk.authorize_start(self.battle_id,self.generation);self.start(0)
        descriptor = self.descriptor(0)
        first = descriptor.party[:200]
        original = self.call("verify_startup",0,Kind.PARTY_0,3,first)
        self.assertEqual(original,self.call("verify_startup",0,Kind.PARTY_0,3,first))
        self.assert_code("canonical_mismatch",self.call,"verify_startup",0,Kind.PARTY_2,5,descriptor.party[400:])
        self.assertEqual(self.call("status",0)["state"],"recovery_required")

    def test_full_party_mismatch_after_start_stays_held(self):
        self.prepared();self.desk.authorize_start(self.battle_id,self.generation);self.start(0)
        changed = bytearray(self.descriptor(0).party[:200]);changed[199] ^= 1
        self.assert_code("canonical_mismatch",self.call,"verify_startup",0,Kind.PARTY_0,3,bytes(changed))
        self.assertEqual(self.call("status",0)["state"],"recovery_required")
        self.assertEqual(self.call("status",0)["released"],[])

    def test_two_equal_restored_results_authorize_but_two_release_acknowledgments_close(self):
        self.running()
        result,*_ = self.finish(0)
        self.assertEqual(result["state"],"finishing");self.assertIsNone(result["outcome"])
        result,*_ = self.finish(1)
        self.assertEqual(result["state"],"release_authorized");self.assertEqual(result["outcome"],1)
        result,*_ = self.release(0)
        self.assertEqual(result["state"],"release_authorized")
        self.assert_code("battle_busy",self.desk.invite,*self.actor(0),self.players[2].player_id,str(uuid4()))
        result,request,response = self.release(1)
        self.assertEqual(result["state"],"closed")
        self.assertEqual(result,self.call("released",1,request,response))
        for i in (0,1):self.assertEqual(self.store.read_checkpoint(*self.actor(i)),self.heads[i])
        self.store.integrity_check()

    def test_different_outcomes_and_changed_party_refuse_release(self):
        self.running();self.finish(0)
        self.assert_code("battle_result_mismatch",self.finish,1,outcome=2)
        self.assertEqual(self.call("status",0)["state"],"recovery_required")
        self.assertEqual(self.call("status",0)["released"],[])

    def test_released_actor_stays_reserved_until_every_release_ack(self):
        self.running();self.finish(0);self.finish(1);self.release(0)
        old = self.heads[0]
        self.assert_code("battle_busy",self.store.commit_checkpoint,*self.actor(0),str(uuid4()),old.revision,
            old.payload,self.store.build_id,self.store.ruleset_id,OWNERSHIP_PROFILE)
        self.assertEqual(self.call("status",1)["state"],"release_authorized")
        self.assertEqual(self.release(1)[0]["state"],"closed")
        current = self.store.commit_checkpoint(*self.actor(0),str(uuid4()),old.revision,
            old.payload,self.store.build_id,self.store.ruleset_id,OWNERSHIP_PROFILE)
        self.assertEqual(current.revision,2)

    def test_still_held_actor_cannot_change_head_after_peer_release(self):
        self.running();self.finish(0);self.finish(1);self.release(0)
        old = self.heads[1]
        self.assert_code("battle_busy",self.store.commit_checkpoint,*self.actor(1),str(uuid4()),old.revision,
            old.payload,self.store.build_id,self.store.ruleset_id,OWNERSHIP_PROFILE)
        self.assertEqual(self.call("status",0)["state"],"release_authorized")
        self.assertEqual(self.store.read_checkpoint(*self.actor(1)),old)

    def test_result_needs_exact_unused_party_tail_and_count(self):
        self.running()
        changed = bytearray(self.descriptor(0).party);changed[-1] ^= 1
        self.assert_code("battle_result_mismatch",self.finish,0,party=bytes(changed))
        self.assertEqual(self.call("status",0)["state"],"recovery_required")

    def test_exact_preparation_and_finished_retries_do_not_reseed_or_republish(self):
        self.register();receipt = self.prepare(0)
        self.assertEqual(self.call("prepared",0,*receipt),self.call("prepared",0,*receipt))
        self.prepare(1);self.desk.authorize_start(self.battle_id,self.generation)
        for i in (0,1):self.start(i);self.parts(i)
        self.desk.authorize_running(self.battle_id,self.generation)
        result,request,response,fields = self.finish(0)
        self.assertEqual(result,self.call("finish",0,request,response,**fields))
        before = self.call("status",0)
        self.assert_code("battle_result_mismatch",self.call,"finish",0,request,response,
            outcome=1,party=b"",party_count=2)
        self.assertEqual(before,self.call("status",0))

    def test_keepalive_cannot_revive_expired_and_valid_receipt_extends_deadline(self):
        self.running();self.now = 9
        request = self.control(0,Opcode.KEEP,4)
        response = replace(request,data=self.query(0,4,25,revision=1))
        self.call("keepalive",0,request,response)
        self.now = 11
        self.assertEqual(self.call("status",0)["state"],"running")
        self.now = 19
        self.assertEqual(self.call("status",0)["state"],"recovery_required")
        self.assert_code("battle_state",self.call,"keepalive",0,request,response)

    def test_duplicate_keepalive_is_observational_and_does_not_refresh_deadline(self):
        self.running();self.now = 5
        request = self.control(0,Opcode.KEEP,4)
        response = replace(request,data=self.query(0,4,25,revision=1))
        self.call("keepalive",0,request,response)
        self.now = 14
        self.call("keepalive",0,request,response)
        self.now = 15
        self.assertEqual(self.call("status",0)["state"],"recovery_required")

    def test_two_disjoint_rooms_capacity_history_and_third_party_are_bounded(self):
        other = str(uuid4())
        self.desk.invite(*self.actor(2),self.players[3].player_id,other)
        self.assertEqual(len(self.desk._active),2)
        self.assert_code("battle_busy",self.desk.invite,*self.actor(0),self.players[3].player_id,str(uuid4()))
        self.assert_code("battle_not_participant",self.call,"status",3)
        self.call("cancel",0)
        for _ in range(70):
            identifier = str(uuid4())
            view = self.desk.invite(*self.actor(0),self.players[1].player_id,identifier)
            self.desk.cancel(*self.actor(0),identifier,view["generation"])
        self.assertEqual(len(self.desk._history),64)
        self.assertEqual(len(self.desk._active),1)

    def test_invalid_types_stale_generation_and_bad_clock_never_advance_state(self):
        self.assert_code("invalid_field",self.desk.invite,*self.actor(0),True,str(uuid4()))
        self.assert_code("battle_generation_mismatch",self.desk.accept,*self.actor(1),
                         self.battle_id,str(uuid4()),self.view["fingerprint"])
        self.assert_code("stale_lease",self.desk.accept,self.players[1].player_id,self.actor(0)[1],
                         self.battle_id,self.generation,self.view["fingerprint"])
        for now in (True,-1,float("inf"),float("nan")):
            self.now = now
            self.assert_code("battle_clock",self.call,"status",0)
        self.now = 0
        self.assertEqual(self.call("status",0),self.view)


if __name__ == "__main__":unittest.main()
