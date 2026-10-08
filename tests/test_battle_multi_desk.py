"""Four independent consents and native receipts; no actual-core claim."""
from dataclasses import replace
import unittest
from uuid import uuid4

from emerald_multiplayer.native_battle import Kind, Opcode
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
import test_battle_desk as fixture


class MultiBattleDeskTests(unittest.TestCase):
    tearDown = fixture.BattleDeskTests.tearDown
    actor = fixture.BattleDeskTests.actor
    call = fixture.BattleDeskTests.call
    descriptor = fixture.BattleDeskTests.descriptor
    control = fixture.BattleDeskTests.control
    query = fixture.BattleDeskTests.query
    bind = fixture.BattleDeskTests.bind
    prepare = fixture.BattleDeskTests.prepare
    start = fixture.BattleDeskTests.start
    parts = fixture.BattleDeskTests.parts
    finish = fixture.BattleDeskTests.finish
    release = fixture.BattleDeskTests.release
    assert_code = fixture.BattleDeskTests.assert_code

    def setUp(self):
        fixture.BattleDeskTests.setUp(self)
        self.call("cancel",0)
        self.battle_id=str(uuid4())
        self.view=self.invite()
        self.generation=self.view["generation"]

    def invite(self, *, teammate=None, opponents=None, battle_id=None):
        return self.desk.invite_multi(*self.actor(0),teammate or self.players[2].player_id,
            opponents if opponents is not None else (self.players[1].player_id,self.players[3].player_id),
            battle_id or self.battle_id)

    def accepted(self):
        for i in (1,2,3):view=self.call("accept",i,self.view["fingerprint"])
        return view

    def registered(self):
        self.accepted()
        for i in range(4):self.call("register",i,100+i)

    def prepared(self):
        self.registered()
        for i in range(4):self.prepare(i)

    def running(self):
        self.prepared();self.desk.authorize_start(self.battle_id,self.generation)
        for i in range(4):self.start(i);self.parts(i)
        return self.desk.authorize_running(self.battle_id,self.generation)

    def test_fixed_duos_canonical_sources_and_no_inherited_consent(self):
        self.assertEqual(self.view["mode"],3)
        self.assertEqual(self.view["teams"],[sorted(self.players[i].player_id for i in (0,2)),
                                           sorted(self.players[i].player_id for i in (1,3))])
        self.assertEqual(self.view["consent"],[self.players[0].player_id])
        for i in range(4):
            descriptor=self.descriptor(i)
            self.assertEqual(descriptor.mode,3)
            self.assertEqual(descriptor.source_slot,self.view["players"].index(self.players[i].player_id))
            self.assertEqual(len(descriptor.party),600)
        for i in (1,2):
            self.assertEqual(self.call("accept",i,self.view["fingerprint"])["state"],"invited")
            self.assert_code("battle_state",self.call,"register",i,100+i)
            self.assert_code("battle_state",self.call,"authorize_bind",i)
        self.assertEqual(self.call("accept",3,self.view["fingerprint"])["state"],"accepted")
        self.assert_code("battle_not_registered",self.call,"authorize_bind",0)

    def test_exact_roster_retry_and_changed_team_or_format_conflict(self):
        self.assertEqual(self.invite(opponents=(self.players[3].player_id,self.players[1].player_id)),self.view)
        self.assert_code("request_conflict",self.invite,teammate=self.players[1].player_id,
                         opponents=(self.players[2].player_id,self.players[3].player_id))
        self.assert_code("request_conflict",self.desk.invite,*self.actor(0),self.players[1].player_id,self.battle_id)
        for opponents in ((self.players[1].player_id,), (self.players[1].player_id,self.players[1].player_id),
                          (self.players[0].player_id,self.players[3].player_id), list(self.view["players"])):
            self.assert_code("invalid_battle",self.invite,opponents=opponents,battle_id=str(uuid4()))

    def test_all_four_incarnations_and_preparations_required(self):
        self.accepted()
        for i in range(3):self.call("register",i,100+i)
        self.assert_code("battle_not_registered",self.call,"authorize_bind",0)
        self.call("register",3,103)
        for i in range(3):
            self.prepare(i)
            self.assert_code("battle_not_ready",self.desk.authorize_start,self.battle_id,self.generation)
        self.prepare(3)
        view=self.desk.authorize_start(self.battle_id,self.generation)
        self.assertEqual(view["state"],"starting")
        self.assertEqual(len(view["prepared"]),4)

    def test_all_four_complete_original_parties_precede_running(self):
        self.prepared();self.desk.authorize_start(self.battle_id,self.generation)
        for i in range(3):self.start(i);self.parts(i)
        self.start(3)
        self.assert_code("battle_not_ready",self.desk.authorize_running,self.battle_id,self.generation)
        descriptor=self.descriptor(3)
        for part in range(2):
            self.call("verify_startup",3,Kind.PARTY_0+part,part+3,descriptor.party[part*200:part*200+200])
        self.assert_code("battle_not_ready",self.desk.authorize_running,self.battle_id,self.generation)
        self.call("verify_startup",3,Kind.PARTY_2,5,descriptor.party[400:600])
        self.assertEqual(self.desk.authorize_running(self.battle_id,self.generation)["state"],"running")

    def test_four_matching_restored_results_and_four_releases_close(self):
        self.running()
        for i in range(3):
            view,*_=self.finish(i)
            self.assertEqual(view["state"],"finishing");self.assertIsNone(view["outcome"])
            self.assert_code("battle_state",self.release,i)
        view,*_=self.finish(3)
        self.assertEqual(view["state"],"release_authorized");self.assertEqual(view["outcome"],1)
        for i in range(3):
            view,*_=self.release(i)
            self.assertEqual(view["state"],"release_authorized")
            self.assertIn(self.battle_id,self.desk._active)
        view,*_=self.release(3)
        self.assertEqual(view["state"],"closed")
        self.assertNotIn(self.battle_id,self.desk._active)
        self.assertEqual(self.release(3)[0],view)
        for i in range(4):
            self.assertEqual(self.store.read_checkpoint(*self.actor(i)),self.heads[i])

    def test_missing_ack_keeps_every_possible_bind_reserved_until_abort(self):
        self.registered()
        for i in range(4):self.call("authorize_bind",i)
        view=self.call("cancel",2)
        self.assertEqual(set(view["abort_pending"]),{p.player_id for p in self.players})
        for i in range(4):
            request=self.control(i,Opcode.ABORT_PRE_START,2)
            view=self.call("aborted",i,request,replace(request,data=b""))
            self.assertEqual(view["state"],"aborted" if i==3 else "aborting")

    def test_fourth_changed_head_invalidates_readiness(self):
        self.accepted()
        head=self.heads[3]
        self.store.commit_checkpoint(*self.actor(3),str(uuid4()),1,head.payload,
            self.store.build_id,self.store.ruleset_id,OWNERSHIP_PROFILE)
        self.assertEqual(self.call("status",0)["state"],"aborted")
        self.assertFalse(self.call("status",0)["consent"])
        for i in range(3):self.assertEqual(self.store.read_checkpoint(*self.actor(i)),self.heads[i])

    def test_fourth_outcome_disagreement_stays_in_recovery(self):
        self.running()
        for i in range(3):self.finish(i)
        self.assert_code("battle_result_mismatch",self.finish,3,outcome=2)
        self.assertEqual(self.call("status",0)["state"],"recovery_required")
        for i in range(4):self.assert_code("battle_state",self.release,i)

    def test_exact_accept_retry_does_not_extend_deadline(self):
        for i in (1,2,3):
            self.now=i;self.call("accept",i,self.view["fingerprint"])
        self.now=12;self.call("accept",3,self.view["fingerprint"])
        self.now=13
        self.assertEqual(self.call("status",0)["state"],"aborted")
