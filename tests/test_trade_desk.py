from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.ownership_protocol import OWNERSHIP_PROFILE
from emerald_multiplayer.storage import StorageError
from emerald_multiplayer.trade_desk import TradeDesk
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from emerald_multiplayer.trade_flash import TradeFlashError
from test_ownership_storage import source_flash, owned_flash


class TradeDeskTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = TradeCheckpointStore(Path(self.directory.name)/'world.sqlite3', 'test-build', 'test-rules')
        self.store.begin_server_boot()
        self.players, self.heads, self.grants = [], [], []
        self.leases = {}
        for i in range(3):
            player = self.store.create_player(f'Player {i}')
            pids = (i*2+7,i*2+8)
            lease = self.store.acquire_lease(player.player_id, player.credential)
            self.leases[player.player_id] = lease
            self.store.enroll_player(player.player_id,source_flash(('party:0','party:1'),personalities=pids))
            grant = self.store.reserve_instances(player.player_id,lease,str(uuid4()),0,1,32)
            payload = owned_flash(grant,(('party:0',grant.start),('party:1',grant.start+1)),personalities=pids)
            head = self.store.commit_checkpoint(player.player_id,lease,str(uuid4()),0,payload,
                self.store.build_id,self.store.ruleset_id,OWNERSHIP_PROFILE)
            self.players.append(player); self.heads.append(head); self.grants.append(grant)
        self.now = 0
        self.desk = TradeDesk(self.store,self.leases.get,timeout=10,clock=lambda:self.now)
        self.transaction = str(uuid4())
        self.view = self.desk.open(*self.actor(0),self.players[1].player_id,self.transaction)

    def tearDown(self):
        self.store.close(); self.directory.cleanup()

    def actor(self,index):
        player=self.players[index].player_id
        return player,self.leases[player]

    def offer(self,index,serial=None):
        return self.desk.offer(*self.actor(index),self.transaction,self.view['generation'],
            self.heads[index].revision,self.heads[index].sha256,serial or self.grants[index].start)

    def ready(self):
        self.offer(0)
        return self.offer(1)

    def confirm(self,index,view):
        return self.desk.confirm(*self.actor(index),self.transaction,view['generation'],view['fingerprint'])

    def assert_code(self,expected,call,*args):
        with self.assertRaises(StorageError) as caught:call(*args)
        self.assertEqual(caught.exception.code,expected)

    def test_only_two_separate_authenticated_confirmations_commit(self):
        ready=self.ready()
        first=self.confirm(0,ready)
        self.assertEqual(first['confirmations'],[self.players[0].player_id])
        self.assertEqual(self.confirm(0,ready),first)
        self.assertEqual(self.store.read_checkpoint(*self.actor(0)),self.heads[0])
        result=self.confirm(1,ready)
        self.assertEqual(result['state'],'committed')
        self.assertEqual(result['revision'],2)
        self.assertNotIn('payload',str(result))
        self.assertEqual(self.confirm(1,ready),result)
        self.assertEqual(self.desk.status(*self.actor(0),self.transaction)['revision'],2)
        self.store.integrity_check()

    def test_builder_failure_clears_all_consent_without_mutating_canonical_saves(self):
        ready = self.ready()
        self.confirm(0, ready)
        with patch('emerald_multiplayer.trade_desk.build_party_swap', side_effect=TradeFlashError('injected')):
            self.assert_code('invalid_trade', self.confirm, 1, ready)
        self.assertEqual(self.desk.status(*self.actor(0), self.transaction)['confirmations'], [])
        for index in (0, 1):
            self.assertEqual(self.store.read_checkpoint(*self.actor(index)), self.heads[index])
        self.assertEqual(self.confirm(1, ready)['state'], 'offering')
        self.assertEqual(self.confirm(0, ready)['state'], 'committed')

    def test_reopening_committed_transaction_cannot_change_peer(self):
        ready = self.ready()
        self.confirm(0, ready)
        self.confirm(1, ready)
        self.assert_code('request_conflict', self.desk.open, *self.actor(0),
                         self.players[2].player_id, self.transaction)
        self.assertEqual(self.desk.open(*self.actor(0), self.players[1].player_id,
                                      self.transaction)['state'], 'committed')

    def test_edit_clears_both_confirmations_and_old_fingerprint_stays_invalid(self):
        old=self.ready(); self.confirm(0,old)
        changed=self.offer(1,self.grants[1].start+1)
        self.assertEqual(changed['confirmations'],[])
        self.assertNotEqual(changed['fingerprint'],old['fingerprint'])
        self.assert_code('trade_offer_changed',self.confirm,0,old)
        restored=self.offer(1)
        self.assertNotEqual(restored['fingerprint'],old['fingerprint'])
        self.assert_code('trade_offer_changed',self.confirm,0,old)
        self.confirm(0,restored)
        self.assertEqual(self.confirm(1,restored)['state'],'committed')

    def test_unoffered_and_third_party_or_wrong_lease_cannot_confirm(self):
        self.assert_code('trade_offer_changed',self.confirm,0,self.view)
        ready=self.ready()
        self.assert_code('trade_not_participant',self.confirm,2,ready)
        self.assert_code('stale_lease',self.desk.confirm,self.players[0].player_id,
            self.actor(1)[1],self.transaction,ready['generation'],ready['fingerprint'])
        self.assertEqual(self.store.read_checkpoint(*self.actor(0)),self.heads[0])

    def test_cancel_and_reopen_reject_delayed_old_generation(self):
        old=self.ready()
        self.confirm(0,old)
        self.assertEqual(self.desk.cancel(*self.actor(1),self.transaction,old['generation'])['state'],'aborted')
        self.view=self.desk.open(*self.actor(0),self.players[1].player_id,self.transaction)
        new=self.ready()
        self.assertNotEqual(new['generation'],old['generation'])
        self.assert_code('trade_generation_mismatch',self.confirm,1,old)
        self.assert_code('trade_generation_mismatch',self.desk.cancel,*self.actor(0),self.transaction,old['generation'])
        self.assertEqual(self.desk.status(*self.actor(0),self.transaction)['state'],'offering')

    def test_disconnect_and_expiry_abort_only_uncommitted_proposals(self):
        ready=self.ready();self.confirm(0,ready)
        oldlease=self.leases.pop(self.players[1].player_id)
        self.assertEqual(self.desk.status(*self.actor(0),self.transaction)['state'],'aborted')
        self.leases[self.players[1].player_id]=oldlease
        self.view=self.desk.open(*self.actor(0),self.players[1].player_id,self.transaction)
        ready=self.ready(); self.now=11
        self.assertEqual(self.desk.status(*self.actor(0),self.transaction)['state'],'aborted')
        self.assert_code('trade_aborted',self.confirm,1,ready)
        self.assertEqual(self.store.read_checkpoint(*self.actor(0)),self.heads[0])

    def test_restart_drops_uncommitted_consent_but_retains_committed_fate(self):
        ready=self.ready();self.confirm(0,ready)
        self.desk=TradeDesk(self.store,self.leases.get)
        self.assertEqual(self.desk.status(*self.actor(0),self.transaction)['state'],'aborted')
        self.view=self.desk.open(*self.actor(0),self.players[1].player_id,self.transaction)
        self.assert_code('trade_generation_mismatch',self.confirm,1,ready)
        ready=self.ready(); self.confirm(0,ready);result=self.confirm(1,ready)
        self.desk=TradeDesk(self.store,self.leases.get)
        self.assertEqual(self.desk.status(*self.actor(1),self.transaction),result)
        self.assertEqual(self.desk.cancel(*self.actor(1),self.transaction,ready['generation']),result)
        self.assert_code('trade_recovery_required',self.desk.open,*self.actor(0),self.players[1].player_id,str(uuid4()))

    def test_new_head_invalidates_confirmation_and_busy_player_is_bounded(self):
        ready=self.ready();self.confirm(0,ready)
        self.assert_code('trade_busy',self.desk.open,*self.actor(2),self.players[0].player_id,str(uuid4()))
        head=self.heads[1]
        self.heads[1]=self.store.commit_checkpoint(*self.actor(1),str(uuid4()),1,head.payload,
            self.store.build_id,self.store.ruleset_id,OWNERSHIP_PROFILE)
        self.assert_code('revision_conflict',self.confirm,1,ready)
        self.assertEqual(self.desk.status(*self.actor(0),self.transaction)['confirmations'],[])


if __name__ == '__main__':unittest.main()
