from __future__ import annotations

from copy import deepcopy
import math
from types import SimpleNamespace
import unittest
from uuid import uuid4

from emerald_multiplayer.protocol import MAX_COUNTER, MAX_FRAME_BYTES, ProtocolError, encode_message
from emerald_multiplayer.team_protocol import (
    TEAM_OPERATIONS, validate_team_common, validate_team_request, validate_team_reply,
)


ACTOR, PEER, THIRD, FOURTH, WORLD, REQUEST, INVITE, GENERATION, TEAM, TEAM_GEN = (
    str(uuid4()) for _ in range(10)
)
EPOCH = 7


def request(operation, **changes):
    extra = {
        'invite': dict(peer=PEER, invitation_id=INVITE),
        'accept': dict(invitation_id=INVITE, generation=GENERATION),
        'decline': dict(invitation_id=INVITE, generation=GENERATION),
        'cancel': dict(invitation_id=INVITE, generation=GENERATION),
        'leave': dict(team_id=TEAM, generation=TEAM_GEN),
        'status': {},
    }[operation]
    return dict(type='team_' + operation, request_id=REQUEST, session_epoch=EPOCH, **extra, **changes)


def formed(sender=ACTOR, recipient=PEER):
    return dict(state='formed', team_id=TEAM, generation=TEAM_GEN,
                members=[sender, recipient], invitation_id=INVITE,
                invitation_generation=GENERATION)


def invited(sender=ACTOR, recipient=PEER):
    return dict(state='invited', invitation_id=INVITE, generation=GENERATION,
                sender=sender, recipient=recipient, expires_in=59.5)


def reply(operation, **changes):
    results = {
        'invite': invited(),
        'accept': formed(PEER, ACTOR),
        'cancel': dict(state='canceled', invitation_id=INVITE),
        'decline': dict(state='declined', invitation_id=INVITE),
        'leave': dict(state='left', team_id=TEAM),
        'status': dict(scope='session-local-development', team=formed(),
                       teams=[formed()], invitations=[]),
    }
    return dict(type='team_result', protocol=1, session_epoch=EPOCH,
                request_id=REQUEST, operation=operation, world_id=WORLD,
                player_id=ACTOR, result=results[operation], **changes)


class TeamProtocolTests(unittest.TestCase):
    def validate(self, value, expected=None):
        return validate_team_reply(value, ACTOR, WORLD, EPOCH, expected)

    def test_every_exact_request_and_result_are_bounded_and_preserved(self):
        for operation in TEAM_OPERATIONS:
            req = request(operation)
            self.assertEqual(validate_team_request(req, EPOCH), req)
            value = reply(operation)
            self.assertEqual(self.validate(value, req), value)
            self.assertLess(len(encode_message(value)) - 4, MAX_FRAME_BYTES)

    def test_no_actor_claims_payload_or_extra_envelope_fields(self):
        for operation in TEAM_OPERATIONS:
            for field, value in (('actor', PEER), ('player_id', PEER), ('lease', 2),
                                 ('credential', 'a'*64), ('payload', 'save'), ('friendship', 99)):
                with self.subTest(operation=operation, field=field), self.assertRaises(ProtocolError):
                    validate_team_request({**request(operation), field: value}, EPOCH)
            for field in request(operation):
                value = request(operation); del value[field]
                with self.assertRaises(ProtocolError):
                    validate_team_request(value, EPOCH)

    def test_common_correlation_errors_are_fatal_before_body_reply(self):
        value = {**request('invite'), 'peer': False}
        self.assertEqual(validate_team_common(value, EPOCH), value)
        with self.assertRaises(ProtocolError):
            validate_team_request(value, EPOCH)
        for change in ({'session_epoch': True}, {'session_epoch': EPOCH+1},
                       {'request_id': 'bad'}, {'type': 'trade_status'}):
            with self.assertRaises(ProtocolError):
                validate_team_common({**request('invite'), **change}, EPOCH)

    def test_noncanonical_uuid_bool_and_counter_boundaries_reject(self):
        for invalid in (True, 7, None, '', str(uuid4()).upper(),
                        '00000000-0000-0000-0000-000000000000', 'x'*10000):
            for field in ('peer', 'invitation_id'):
                with self.subTest(field=field, value=invalid), self.assertRaises(ProtocolError):
                    validate_team_request({**request('invite'), field: invalid}, EPOCH)
        for epoch in (True, 0, -1, MAX_COUNTER+1, 1.0):
            with self.assertRaises(ProtocolError):
                validate_team_request({**request('status'), 'session_epoch': epoch}, EPOCH)
        validate_team_request({**request('status'), 'session_epoch': MAX_COUNTER}, MAX_COUNTER)

    def test_error_envelope_is_correlated_and_has_bounded_safe_text(self):
        value = reply('accept')
        del value['result']
        value.update(type='team_error', code='team_invitation_missing', message='Invite expired.')
        self.assertEqual(self.validate(value, request('accept')), value)
        for change in ({'code': 'x'*129}, {'message': 'x'*513}, {'message': 'bad\ntext'},
                       {'result': {}}, {'player_id': PEER}, {'world_id': str(uuid4())}):
            with self.assertRaises(ProtocolError):
                self.validate({**value, **change}, request('accept'))

    def test_reply_identity_operation_and_request_target_correlation(self):
        for change in ({'protocol': True}, {'protocol': 2}, {'session_epoch': EPOCH+1},
                       {'request_id': str(uuid4())}, {'operation': 'accept'},
                       {'type': 'trade_result'}, {'payload': 'save'}, {'player_id': PEER}):
            with self.subTest(change=change), self.assertRaises(ProtocolError):
                self.validate({**reply('invite'), **change}, request('invite'))
        for change in ({'invitation_id': str(uuid4())}, {'recipient': THIRD}):
            value = reply('invite'); value['result'].update(change)
            with self.assertRaises(ProtocolError):
                self.validate(value, request('invite'))
        value = reply('accept'); value['result']['invitation_generation'] = str(uuid4())
        with self.assertRaises(ProtocolError):
            self.validate(value, request('accept'))

    def test_exactly_two_unique_members_and_correct_accepting_actor(self):
        for members in ([ACTOR], [ACTOR, ACTOR], [ACTOR, PEER, THIRD], [PEER, THIRD]):
            value = reply('accept'); value['result']['members'] = members
            with self.assertRaises(ProtocolError):
                self.validate(value)
        value = reply('accept'); value['result']['members'] = [ACTOR, PEER]
        with self.assertRaises(ProtocolError):
            self.validate(value)  # This actor cannot claim the sender accepted.

    def test_status_requires_two_disjoint_teams_consistent_own_membership(self):
        other = formed(THIRD, FOURTH)
        other.update(team_id=str(uuid4()), generation=str(uuid4()),
                     invitation_id=str(uuid4()), invitation_generation=str(uuid4()))
        value = reply('status'); value['result']['teams'].append(other)
        self.validate(value)
        for mutation in (
            lambda v: v['teams'].append(deepcopy(other)),
            lambda v: v['teams'][1]['members'].append(ACTOR),
            lambda v: v['teams'][1]['members'].__setitem__(0, PEER),
            lambda v: v.__setitem__('team', None),
            lambda v: v.__setitem__('scope', 'permanent'),
        ):
            changed = deepcopy(value); mutation(changed['result'])
            with self.assertRaises(ProtocolError):
                self.validate(changed)
        outsider = reply('status')
        outsider['result'].update(team=None, teams=[other])
        self.validate(outsider)

    def test_only_own_pending_invitation_without_teamed_participants_is_visible(self):
        value = reply('status')
        value['result'].update(team=None, teams=[], invitations=[invited()])
        self.validate(value)
        for invitations in ([invited(), invited()], [invited(THIRD, FOURTH)]):
            changed = deepcopy(value); changed['result']['invitations'] = invitations
            with self.assertRaises(ProtocolError):
                self.validate(changed)
        changed = deepcopy(value); changed['result'].update(team=formed(), teams=[formed()])
        with self.assertRaises(ProtocolError):
            self.validate(changed)

    def test_invitation_time_state_and_returned_field_bounds(self):
        for duration in (True, -1, 3601, math.inf, math.nan, 10**1000):
            value = reply('invite'); value['result']['expires_in'] = duration
            with self.assertRaises(ProtocolError):
                self.validate(value)
        for change in ({'state': 'formed'}, {'sender': PEER}, {'recipient': ACTOR},
                       {'generation': True}, {'lease': 1}):
            value = reply('invite'); value['result'].update(change)
            with self.assertRaises(ProtocolError):
                self.validate(value)
        for operation in ('cancel', 'decline', 'leave'):
            value = reply(operation); value['result']['state'] = 'formed'
            with self.assertRaises(ProtocolError):
                self.validate(value)


if __name__ == '__main__':
    unittest.main()
