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
from emerald_multiplayer.trade_eligibility import TradeEligibilityError
from test_flash import _rewrite
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

    def test_a_player_with_no_pokemon_yet_cannot_open_a_trade(self):
        # Update 32: a new character has no Pokemon until it claims its starter in Birch's lab.
        player = self.store.create_player('New Player')
        lease = self.store.acquire_lease(player.player_id, player.credential)
        self.leases[player.player_id] = lease
        self.store.enroll_player(player.player_id, source_flash(()))
        grant = self.store.reserve_instances(player.player_id, lease, str(uuid4()), 0, 1, 32)
        self.store.commit_checkpoint(player.player_id, lease, str(uuid4()), 0, owned_flash(grant, ()),
            self.store.build_id, self.store.ruleset_id, OWNERSHIP_PROFILE)
        for actor, peer, code in (((player.player_id, lease), self.players[2].player_id, 'no_pokemon'),
                                  (self.actor(2), player.player_id, 'peer_no_pokemon')):
            with self.subTest(code=code):
                with self.assertRaises(StorageError) as caught:
                    self.desk.open(*actor, peer, str(uuid4()))
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.desk.proposals(*self.actor(2)), [])

    def test_discovery_is_private_and_does_not_extend_expiry(self):
        self.assertEqual(self.desk.proposals(*self.actor(0)), [self.view])
        self.assertEqual(self.desk.proposals(*self.actor(1)), [self.view])
        self.assertEqual(self.desk.proposals(*self.actor(2)), [])
        self.now = 11
        self.assertEqual(self.desk.proposals(*self.actor(0)), [])
        self.assertEqual(self.desk.proposals(*self.actor(1)), [])

    def test_discovery_drops_old_lease_and_rejects_forged_lease(self):
        player, lease = self.actor(1)
        self.store.release_lease(player, lease)
        self.leases[player] = self.store.acquire_lease(player, self.players[1].credential)
        self.assertEqual(self.desk.proposals(*self.actor(0)), [])
        with self.assertRaises(StorageError):
            self.desk.proposals(player, lease)

    def offer(self,index,serial=None):
        return self.desk.offer(*self.actor(index),self.transaction,self.view['generation'],
            self.heads[index].revision,self.heads[index].sha256,serial or self.grants[index].start)

    def ready(self):
        self.offer(0)
        return self.offer(1)

    def confirm(self,index,view):
        return self.desk.confirm(*self.actor(index),self.transaction,view['generation'],view['fingerprint'])

    def finish_preparation(self, view):
        self.assertEqual(view['state'], 'preparing')
        for index in (0, 1):
            description = self.desk.preparation(*self.actor(index), self.transaction, view['generation'])['preparation']
            own = next(p for p in description['players'] if p['player_id'] == self.actor(index)[0])
            result = self.desk.prepared(*self.actor(index), self.transaction, view['generation'],
                description['fingerprint'], description['preparation_id'], own['candidate_sha256'])
        return result

    def assert_code(self,expected,call,*args):
        with self.assertRaises(StorageError) as caught:call(*args)
        self.assertEqual(caught.exception.code,expected)

    def test_two_confirmations_then_two_separate_recipient_receipts_commit(self):
        ready=self.ready()
        first=self.confirm(0,ready)
        self.assertEqual(first['confirmations'],[self.players[0].player_id])
        self.assertEqual(self.confirm(0,ready),first)
        self.assertEqual(self.store.read_checkpoint(*self.actor(0)),self.heads[0])
        result=self.confirm(1,ready)
        self.assertEqual(result['state'], 'preparing')
        self.assertEqual(self.store.read_checkpoint(*self.actor(0)),self.heads[0])
        result = self.finish_preparation(result)
        self.assertEqual(result['state'],'committed')
        self.assertEqual(result['revision'],2)
        self.assertNotIn('payload',str(result))
        self.assertEqual(self.confirm(1,ready),result)
        self.assertEqual(self.desk.status(*self.actor(0),self.transaction)['revision'],2)
        self.store.integrity_check()

    def test_builder_failure_clears_all_consent_without_mutating_canonical_saves(self):
        ready = self.ready()
        self.confirm(0, ready)
        with patch('emerald_multiplayer.trade_desk.prepare_pair', side_effect=TradeFlashError('injected')):
            self.assert_code('invalid_trade', self.confirm, 1, ready)
        self.assertEqual(self.desk.status(*self.actor(0), self.transaction)['confirmations'], [])
        for index in (0, 1):
            self.assertEqual(self.store.read_checkpoint(*self.actor(index)), self.heads[index])
        self.assertEqual(self.confirm(1, ready)['state'], 'offering')
        self.assertEqual(self.finish_preparation(self.confirm(0, ready))['state'], 'committed')

    def test_unsupported_mail_offer_is_rejected_before_proposal_or_head_changes(self):
        head = self.heads[0]
        # Party-only byte85 is a native attached-mail index. This remains a
        # valid ordinary checkpoint, but is outside the trade capability.
        payload = _rewrite(head.payload, 0, 1, 0x238 + 85, b'\x00')
        self.heads[0] = self.store.commit_checkpoint(*self.actor(0), str(uuid4()),
            head.revision, payload, self.store.build_id, self.store.ruleset_id,
            OWNERSHIP_PROFILE)
        self.assert_code('mail_unsupported', self.offer, 0)
        view = self.desk.status(*self.actor(0), self.transaction)
        self.assertEqual(view['offers'], [])
        self.assertEqual(view['confirmations'], [])
        for index in (0, 1):
            self.assertEqual(self.store.read_checkpoint(*self.actor(index)), self.heads[index])
        self.assertIsNone(self.store.read_trade(*self.actor(0), self.transaction))

    def test_final_eligibility_failure_clears_consent_before_paired_commit(self):
        ready = self.ready()
        self.confirm(0, ready)
        with patch('emerald_multiplayer.trade_desk.validate_trade_pair',
                side_effect=TradeEligibilityError('egg_unsupported', 'native egg support is pending')):
            self.assert_code('egg_unsupported', self.confirm, 1, ready)
        self.assertEqual(self.desk.status(*self.actor(0), self.transaction)['confirmations'], [])
        for index in (0, 1):
            self.assertEqual(self.store.read_checkpoint(*self.actor(index)), self.heads[index])
        self.assertIsNone(self.store.read_trade(*self.actor(0), self.transaction))
        self.assertEqual(self.confirm(1, ready)['state'], 'offering')
        self.assertEqual(self.finish_preparation(self.confirm(0, ready))['state'], 'committed')

    def test_reopening_committed_transaction_cannot_change_peer(self):
        ready = self.ready()
        self.confirm(0, ready)
        self.finish_preparation(self.confirm(1, ready))
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
        self.assertEqual(self.finish_preparation(self.confirm(1,restored))['state'],'committed')

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

    def test_participants_at_work_keep_the_proposal_alive(self):
        # The owner's report of 2026-10-24: the lifetime counted from the last offer only, and two players reading
        # details, confirming and preparing over the internet outlived it. Each trade window's status poll (about
        # once a second), confirmation, inspection and preparation now count; discovery still does not.
        ready = self.ready()
        for step in range(1, 6):
            self.now = step * 8                       # past the 10 s lifetime of the offers, many times over
            for index in (step % 2, 1 - step % 2):    # both trade windows poll
                self.assertEqual(self.desk.status(*self.actor(index), self.transaction)['state'], 'offering')
        self.now += 8
        view = self.confirm(0, ready)
        self.desk.status(*self.actor(1), self.transaction)    # the other window keeps polling meanwhile
        self.now += 8
        view = self.confirm(1, ready)
        self.desk.status(*self.actor(0), self.transaction)
        self.now += 8
        self.assertEqual(self.finish_preparation(view)['state'], 'committed')

    def test_one_window_polling_alone_never_keeps_an_unanswered_proposal(self):
        # The opener's own status polls (about once a second) kept a proposal the friend never entered alive for ever:
        # both players stayed busy, and the friend's soft reset was refused with "Finish the trade first".
        self.ready()                                  # both offered at time 0: 10 s left
        for step in range(1, 4):
            self.now = step * 3
            self.assertEqual(self.desk.status(*self.actor(0), self.transaction)['state'], 'offering')
        self.now = 11                                 # 10 s after the last offer, the other window silent all along
        self.assertEqual(self.desk.status(*self.actor(0), self.transaction)['state'], 'aborted')
        self.assertEqual(self.desk.end_reason(self.players[1].player_id, self.transaction), 'expired')
        # A friend who did enter and then went silent: the proposal ends one lifetime after their last request.
        fresh = str(uuid4())
        self.now = 20
        self.desk.open(*self.actor(0), self.players[1].player_id, fresh)
        self.desk.status(*self.actor(1), fresh)       # t=20: the friend's window, once
        for t in (25, 29):
            self.now = t
            self.assertEqual(self.desk.status(*self.actor(0), fresh)['state'], 'offering')
        self.now = 31
        self.assertEqual(self.desk.status(*self.actor(0), fresh)['state'], 'aborted')

    def test_an_automatic_cancel_is_recorded_as_such_and_never_as_the_players_choice(self):
        # A launcher that cancels on its own after an error in its trade window (end_reason_version 2): the friend is
        # told the trade stopped on the other side, not "Your friend cancelled the trade". An older trade window
        # (version 1) is told no reason for it rather than a wrong one.
        player0, player1 = self.players[0].player_id, self.players[1].player_id
        self.desk.cancel(*self.actor(1), self.transaction, self.view['generation'], automatic=True)
        self.assertEqual((self.desk.end_reason(player0, self.transaction), self.desk.end_reason(player1, self.transaction)),
                         ('partner_stopped', 'you_stopped'))
        self.assertIsNone(self.desk.end_reason(player0, self.transaction, 1))
        self.assertIsNone(self.desk.end_reason(player1, self.transaction, 1))

    def test_the_host_remembers_why_each_participant_s_trade_ended(self):
        player0, player1 = self.players[0].player_id, self.players[1].player_id
        self.assertIsNone(self.desk.end_reason(player0, self.transaction))
        self.desk.cancel(*self.actor(1), self.transaction, self.view['generation'])
        self.assertEqual((self.desk.end_reason(player0, self.transaction), self.desk.end_reason(player1, self.transaction)),
                         ('partner_cancelled', 'you_cancelled'))
        self.assertIsNone(self.desk.end_reason(self.players[2].player_id, self.transaction))
        expired = str(uuid4())
        self.desk.open(*self.actor(0), player1, expired)
        self.now += 11
        self.assertEqual(self.desk.status(*self.actor(0), expired)['state'], 'aborted')
        self.assertEqual(self.desk.end_reason(player1, expired), 'expired')
        dropped = str(uuid4())
        self.desk.open(*self.actor(0), player1, dropped)
        self.store.release_lease(player1, self.leases[player1])
        self.leases[player1] = self.store.acquire_lease(player1, self.players[1].credential)
        self.assertEqual(self.desk.status(*self.actor(0), dropped)['state'], 'aborted')
        self.assertEqual((self.desk.end_reason(player0, dropped), self.desk.end_reason(player1, dropped)),
                         ('partner_disconnected', 'you_disconnected'))
        self.now += 601                                # kept ten minutes
        self.assertIsNone(self.desk.end_reason(player0, dropped))

    def test_restart_drops_uncommitted_consent_but_retains_committed_fate(self):
        ready=self.ready();self.confirm(0,ready)
        self.desk=TradeDesk(self.store,self.leases.get)
        self.assertEqual(self.desk.status(*self.actor(0),self.transaction)['state'],'aborted')
        self.view=self.desk.open(*self.actor(0),self.players[1].player_id,self.transaction)
        self.assert_code('trade_generation_mismatch',self.confirm,1,ready)
        ready=self.ready(); self.confirm(0,ready);result=self.finish_preparation(self.confirm(1,ready))
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
