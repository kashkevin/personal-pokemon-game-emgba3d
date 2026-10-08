from __future__ import annotations

import math
import unittest
from uuid import uuid4

from emerald_multiplayer.protocol import MAX_COUNTER
from emerald_multiplayer.team_desk import TeamDesk, TeamError


class TeamDeskTests(unittest.TestCase):
    def setUp(self):
        self.players = [str(uuid4()) for _ in range(4)]
        self.leases = {player: index + 1 for index, player in enumerate(self.players)}
        self.now = 0.0
        self.desk = TeamDesk(lambda: dict(self.leases), timeout=10, clock=lambda: self.now)

    def actor(self, index):
        player = self.players[index]
        return player, self.leases[player]

    def invite(self, sender=0, recipient=1, invitation_id=None):
        return self.desk.invite(*self.actor(sender), self.players[recipient],
                                invitation_id or str(uuid4()))

    def form(self, sender=0, recipient=1, invitation_id=None):
        invitation = self.invite(sender, recipient, invitation_id)
        return self.desk.accept(*self.actor(recipient), invitation['invitation_id'],
                                invitation['generation'])

    def assert_code(self, code, operation, *args):
        with self.assertRaises(TeamError) as caught:
            operation(*args)
        self.assertEqual(caught.exception.code, code)

    def test_invitation_requires_designated_recipient_consent(self):
        self.assertIsNone(self.desk.status(*self.actor(0))['team'])
        invitation = self.invite()
        self.assertIsNone(self.desk.status(*self.actor(1))['team'])
        self.assertEqual(self.desk.status(*self.actor(2))['invitations'], [])
        self.assert_code('team_not_recipient', self.desk.accept, *self.actor(0),
                         invitation['invitation_id'], invitation['generation'])
        team = self.desk.accept(*self.actor(1), invitation['invitation_id'],
                                invitation['generation'])
        self.assertEqual(team['members'], self.players[:2])
        self.assertEqual(self.desk.status(*self.actor(0))['team'], team)
        self.assertEqual(self.desk.status(*self.actor(1))['team'], team)
        self.assertEqual(self.desk.status(*self.actor(0))['invitations'], [])

    def test_accepted_retries_do_not_create_another_team(self):
        invitation = self.invite()
        team = self.desk.accept(*self.actor(1), invitation['invitation_id'],
                                invitation['generation'])
        self.assertEqual(self.desk.accept(*self.actor(1), invitation['invitation_id'],
                                         invitation['generation']), team)
        self.assertEqual(self.invite(invitation_id=invitation['invitation_id']), team)
        self.assertEqual(len(self.desk.status(*self.actor(3))['teams']), 1)
        self.assert_code('team_not_recipient', self.desk.accept, *self.actor(0),
                         invitation['invitation_id'], invitation['generation'])

    def test_two_disjoint_teams_coexist_and_leaving_does_not_evict_other_team(self):
        first = self.form()
        second = self.form(2, 3)
        self.assertEqual(len(self.desk.status(*self.actor(0))['teams']), 2)
        self.assert_code('team_already_member', self.desk.invite, *self.actor(0),
                         self.players[2], str(uuid4()))
        self.desk.leave(*self.actor(0), first['team_id'], first['generation'])
        self.assertIsNone(self.desk.status(*self.actor(1))['team'])
        self.assertEqual(self.desk.status(*self.actor(2))['team'], second)
        self.assert_code('team_already_member', self.desk.invite, *self.actor(0),
                         self.players[2], str(uuid4()))
        self.desk.leave(*self.actor(3), second['team_id'], second['generation'])
        changed = self.form(0, 2)
        self.assertEqual(changed['members'], [self.players[0], self.players[2]])
        self.assertIsNone(self.desk.status(*self.actor(1))['team'])
        self.assertIsNone(self.desk.status(*self.actor(3))['team'])

    def test_unrelated_actor_and_wrong_roles_cannot_mutate_consent(self):
        invitation = self.invite()
        args = (invitation['invitation_id'], invitation['generation'])
        for operation in (self.desk.accept, self.desk.cancel, self.desk.decline):
            self.assert_code('team_not_participant', operation, *self.actor(2), *args)
        self.assert_code('team_not_sender', self.desk.cancel, *self.actor(1), *args)
        self.assert_code('team_not_recipient', self.desk.decline, *self.actor(0), *args)
        self.assertEqual(self.desk.status(*self.actor(0))['invitations'], [invitation])
        team = self.desk.accept(*self.actor(1), *args)
        self.assert_code('team_not_member', self.desk.leave, *self.actor(2),
                         team['team_id'], team['generation'])

    def test_decline_and_sender_cancel_allow_fresh_generation(self):
        invitation_id = str(uuid4())
        old = self.invite(invitation_id=invitation_id)
        self.desk.decline(*self.actor(1), invitation_id, old['generation'])
        fresh = self.invite(invitation_id=invitation_id)
        self.assertNotEqual(old['generation'], fresh['generation'])
        for operation, index in ((self.desk.accept, 1), (self.desk.cancel, 0)):
            self.assert_code('team_generation_mismatch', operation, *self.actor(index),
                             invitation_id, old['generation'])
        self.desk.cancel(*self.actor(0), invitation_id, fresh['generation'])
        self.assertEqual(self.desk.status(*self.actor(0))['invitations'], [])

    def test_timeout_boundary_and_retry_do_not_extend_consent(self):
        invitation = self.invite()
        self.now = 9
        retried = self.invite(invitation_id=invitation['invitation_id'])
        self.assertEqual(retried['generation'], invitation['generation'])
        self.assertEqual(retried['expires_in'], 1)
        self.now = 10
        self.assert_code('team_invitation_missing', self.desk.accept, *self.actor(1),
                         invitation['invitation_id'], invitation['generation'])
        self.assertEqual(self.desk.status(*self.actor(0))['invitations'], [])

    def test_reconnected_recipient_cannot_accept_previous_lease_invitation(self):
        invitation = self.invite()
        old_lease = self.leases[self.players[1]]
        self.leases[self.players[1]] += 10
        self.assert_code('stale_lease', self.desk.accept, self.players[1], old_lease,
                         invitation['invitation_id'], invitation['generation'])
        self.assert_code('team_invitation_missing', self.desk.accept, *self.actor(1),
                         invitation['invitation_id'], invitation['generation'])
        self.assertIsNone(self.desk.status(*self.actor(0))['team'])
        self.assertEqual(self.form()['members'], self.players[:2])

    def test_disconnected_sender_invitation_is_removed_by_refresh(self):
        invitation = self.invite()
        del self.leases[self.players[0]]
        self.desk.refresh()
        self.assert_code('team_invitation_missing', self.desk.accept, *self.actor(1),
                         invitation['invitation_id'], invitation['generation'])

    def test_either_member_reconnect_dissolves_team_without_automatic_rejoin(self):
        team = self.form()
        self.leases[self.players[0]] += 10
        self.desk.refresh()
        self.assertIsNone(self.desk.status(*self.actor(0))['team'])
        self.assertIsNone(self.desk.status(*self.actor(1))['team'])
        self.assert_code('team_invitation_missing', self.desk.accept, *self.actor(1),
                         team['invitation_id'], team['invitation_generation'])

    def test_server_restart_starts_empty_and_old_generation_cannot_accept(self):
        old = self.invite()
        self.desk = TeamDesk(lambda: dict(self.leases), timeout=10, clock=lambda: self.now)
        self.assertEqual(self.desk.status(*self.actor(0))['teams'], [])
        self.assert_code('team_invitation_missing', self.desk.accept, *self.actor(1),
                         old['invitation_id'], old['generation'])
        fresh = self.invite(invitation_id=old['invitation_id'])
        self.assertNotEqual(fresh['generation'], old['generation'])
        self.assert_code('team_generation_mismatch', self.desk.accept, *self.actor(1),
                         fresh['invitation_id'], old['generation'])

    def test_stale_team_leave_cannot_dissolve_reformed_pair(self):
        old = self.form()
        self.desk.leave(*self.actor(0), old['team_id'], old['generation'])
        fresh = self.form(invitation_id=old['invitation_id'])
        self.assertNotEqual(fresh['team_id'], old['team_id'])
        self.assert_code('team_not_member', self.desk.leave, *self.actor(1),
                         old['team_id'], old['generation'])
        self.assert_code('team_generation_mismatch', self.desk.leave, *self.actor(1),
                         fresh['team_id'], old['generation'])
        self.assert_code('team_generation_mismatch', self.desk.accept, *self.actor(1),
                         fresh['invitation_id'], old['invitation_generation'])
        self.assertEqual(self.desk.status(*self.actor(0))['team'], fresh)

    def test_invitation_id_cannot_be_reused_for_different_pair_or_direction(self):
        invitation = self.invite()
        self.assert_code('request_conflict', self.desk.invite, *self.actor(2),
                         self.players[3], invitation['invitation_id'])
        self.assert_code('request_conflict', self.desk.invite, *self.actor(1),
                         self.players[0], invitation['invitation_id'])
        team = self.desk.accept(*self.actor(1), invitation['invitation_id'],
                                invitation['generation'])
        self.assert_code('request_conflict', self.desk.invite, *self.actor(2),
                         self.players[3], team['invitation_id'])

    def test_pending_invites_are_disjoint_and_bounded_under_spam(self):
        first = self.invite()
        second = self.invite(2, 3)
        for index in range(32):
            self.assert_code('team_invite_busy', self.desk.invite, *self.actor(0),
                             self.players[2], str(uuid4()))
        self.assertEqual(self.desk.status(*self.actor(0))['invitations'], [first])
        self.assertEqual(self.desk.status(*self.actor(2))['invitations'], [second])
        self.now = 10
        replacement = self.invite(0, 2)
        self.assertEqual(replacement['recipient'], self.players[2])
        self.assertEqual(self.desk.status(*self.actor(3))['invitations'], [])

    def test_public_views_do_not_allow_mutation_of_membership(self):
        invitation = self.invite()
        invitation['recipient'] = self.players[2]
        team = self.desk.accept(*self.actor(1), invitation['invitation_id'],
                                invitation['generation'])
        team['members'].clear()
        team['generation'] = str(uuid4())
        view = self.desk.status(*self.actor(0))
        view['team']['members'].append(self.players[3])
        view['teams'].clear()
        self.assertEqual(self.desk.status(*self.actor(1))['team']['members'], self.players[:2])

    def test_offline_self_and_fifth_connected_player_are_refused(self):
        self.assert_code('invalid_team', self.desk.invite, *self.actor(0),
                         self.players[0], str(uuid4()))
        self.assert_code('player_offline', self.desk.invite, *self.actor(0),
                         str(uuid4()), str(uuid4()))
        self.leases[str(uuid4())] = 5
        self.assert_code('team_capacity', self.desk.status, *self.actor(0))

    def test_uuid_and_lease_boundaries_reject_bool_and_noncanonical_values(self):
        for invalid in (True, 1, None, '', '0'*36, str(uuid4()).upper(),
                        '00000000-0000-0000-0000-000000000000', 'x'*10000):
            with self.subTest(uuid=invalid):
                self.assert_code('invalid_field', self.desk.invite, *self.actor(0),
                                 invalid, str(uuid4()))
        for invalid in (True, False, 0, -1, 1.0, MAX_COUNTER+1, None):
            with self.subTest(lease=invalid):
                self.assert_code('invalid_field', self.desk.status, self.players[0], invalid)
        self.leases[self.players[0]] = MAX_COUNTER
        self.assertIsNone(self.desk.status(*self.actor(0))['team'])
        self.leases[self.players[0]] = True
        self.assert_code('invalid_field', self.desk.status, self.players[1], 2)

    def test_timeout_and_roster_configuration_fail_closed(self):
        for timeout in (True, 0, 3601, math.inf, math.nan, 10**1000, '60'):
            with self.subTest(timeout=str(timeout)[:24]):
                with self.assertRaises(ValueError):
                    TeamDesk(lambda: {}, timeout=timeout)
        with self.assertRaises(ValueError):
            TeamDesk(None)
        with self.assertRaises(ValueError):
            TeamDesk(lambda: {}, clock=None)
        desk = TeamDesk(lambda: [], clock=lambda: 0)
        self.assert_code('team_capacity', desk.refresh)

    def test_invalid_or_backwards_clock_cannot_form_team(self):
        invitation = self.invite()
        for now in (-1, True, math.inf, math.nan, 10**1000, '10'):
            self.now = now
            self.assert_code('team_clock', self.desk.accept, *self.actor(1),
                             invitation['invitation_id'], invitation['generation'])
        self.now = 2
        self.desk.status(*self.actor(0))
        self.now = 1
        self.assert_code('team_clock', self.desk.accept, *self.actor(1),
                         invitation['invitation_id'], invitation['generation'])
        self.now = 3
        self.assertEqual(self.desk.accept(*self.actor(1), invitation['invitation_id'],
                                         invitation['generation'])['members'], self.players[:2])


if __name__ == '__main__':
    unittest.main()
