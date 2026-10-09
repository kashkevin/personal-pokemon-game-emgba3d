from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.companion import BASELINE_RULESET, Companion, CompanionConfig, TeamError
from emerald_multiplayer.flash import LAYOUT_ID
from emerald_multiplayer.ownership_protocol import OWNERSHIP_PROFILE
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.protocol import ProtocolError, encode_message, read_message
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.storage import CheckpointStore
from emerald_multiplayer.team_protocol import validate_team_reply
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from test_companion import BinaryBridge, make_files, make_pose
from test_ownership_storage import source_flash, owned_flash
from emerald_multiplayer.protocol import PROTOCOL_VERSION
from emerald_multiplayer.trade_protocol import PREPARATION_OPERATIONS, PREPARATION_VERSION


async def wait_until(predicate, timeout=5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


class RawTeamClient:
    @classmethod
    async def connect(cls, address, player, build):
        self = cls()
        self.reader, self.writer = await asyncio.open_connection(*address)
        await self.send(dict(type='hello', protocol=PROTOCOL_VERSION, build_id=build,
            ruleset_id=BASELINE_RULESET, player_id=player.player_id,
            display_name=player.display_name, credential=player.credential.hex()))
        welcome = await self.next()
        assert welcome['type'] == 'welcome'
        self.epoch = welcome['session_epoch']
        return self

    async def send(self, value):
        self.writer.write(encode_message(value))
        await self.writer.drain()

    async def next(self):
        async with asyncio.timeout(5):
            while True:
                value = await read_message(self.reader)
                if value is None:
                    return None
                if value['type'] == 'ping':
                    await self.send({**value, 'type': 'pong'})
                elif value['type'] != 'world':
                    return value

    async def rpc(self, operation, **fields):
        request = dict(type='team_' + operation, session_epoch=self.epoch,
                       request_id=str(uuid4()), **fields)
        await self.send(request)
        while True:
            value = await self.next()
            if value is None or value['type'] == 'error' or value.get('request_id') == request['request_id']:
                return value

    async def close(self):
        self.writer.close()
        with suppress(ConnectionError, OSError):
            await self.writer.wait_closed()


class TeamNetworkTests(unittest.IsolatedAsyncioTestCase):
    """Four real TCP companions, synthetic ROM identity; no battle acceptance."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rom, self.manifest = make_files(self.temp.name)
        fixture = CompanionConfig(self.rom, self.manifest, str(uuid4()), 'Fixture', secrets.token_bytes(32))
        self.store = OwnershipCheckpointStore(Path(self.temp.name)/'world.sqlite3',
                                              fixture.build_id, BASELINE_RULESET)
        self.store.begin_server_boot()
        self.players = [self.store.create_player(f'Team player {index}') for index in range(4)]
        self.config = ServerConfig(fixture.build_id, BASELINE_RULESET, heartbeat_interval=0.05,
                                   idle_timeout=10, monitor_interval=0.01)
        self.server = WorldServer(self.config, store=self.store, development_teams=True)
        await self.server.start(port=0)
        self.companions, self.bridges, self.raw = [], [], []
        for player in self.players:
            config = CompanionConfig(self.rom, self.manifest, player.player_id, player.display_name,
                secrets.token_bytes(32), server_port=self.server.address[1], ipc_port=0,
                server_credential=player.credential, reconnect_delay=0.02, remote_timeout=15)
            companion = Companion(config)
            self.companions.append(companion)
            await companion.start()
        await wait_until(lambda: all(c.connected for c in self.companions))

    async def asyncTearDown(self):
        for client in self.raw:
            await client.close()
        for bridge in self.bridges:
            await bridge.close()
        for companion in self.companions:
            await companion.close()
        await self.server.close()
        self.store.close()
        self.temp.cleanup()

    async def rpc(self, index, operation, **fields):
        return (await self.companions[index].team_rpc(operation, **fields))['result']

    async def invite(self, sender=0, recipient=1, invitation_id=None):
        return await self.rpc(sender, 'invite', peer=self.players[recipient].player_id,
                              invitation_id=invitation_id or str(uuid4()))

    async def accept(self, recipient, invitation):
        return await self.rpc(recipient, 'accept', invitation_id=invitation['invitation_id'],
                              generation=invitation['generation'])

    async def form(self, sender=0, recipient=1):
        return await self.accept(recipient, await self.invite(sender, recipient))

    async def assert_error(self, code, index, operation, **fields):
        with self.assertRaises(TeamError) as caught:
            await self.rpc(index, operation, **fields)
        self.assertEqual(caught.exception.code, code)

    async def replace_with_raw(self, index=3):
        await self.companions[index].close()
        await wait_until(lambda: self.players[index].player_id not in self.server.sessions)
        raw = await RawTeamClient.connect(self.server.address, self.players[index], self.config.build_id)
        self.raw.append(raw)
        return raw

    async def test_four_authenticated_clients_form_two_teams_while_presence_and_heartbeat_continue(self):
        self.assertTrue(all(not c.config.ownership_enabled and not c.config.trade_enabled
                            for c in self.companions))  # No new game ABI dependency.
        invitation = await self.invite()
        self.assertIsNone((await self.rpc(1, 'status'))['team'])
        await self.assert_error('team_not_recipient', 0, 'accept',
                               invitation_id=invitation['invitation_id'], generation=invitation['generation'])
        first = await self.accept(1, invitation)
        second = await self.form(2, 3)
        status = await self.rpc(0, 'status')
        self.assertEqual(len(status['teams']), 2)
        self.assertEqual(status['team'], first)
        self.assertEqual((await self.rpc(3, 'status'))['team'], second)
        bridge = await BinaryBridge.connect(self.companions[0]); self.bridges.append(bridge)
        await bridge.pose(make_pose(frame=1, x=8))
        actor = self.players[0].player_id
        await wait_until(lambda: self.server.sessions[actor].presence is not None
                        and self.server.sessions[actor].presence['x'] == 8
                        and self.server.sessions[actor].ping_nonce > 0)
        self.assertTrue(all(c.connected for c in self.companions))
        for player, companion in zip(self.players, self.companions):
            self.assertIsNone(self.store.read_checkpoint(player.player_id, companion.session_epoch))
        self.store.integrity_check()

    async def test_partner_changes_require_explicit_leave_and_fresh_acceptance(self):
        first, second = await self.form(), await self.form(2, 3)
        await self.assert_error('team_already_member', 0, 'invite',
                               peer=self.players[2].player_id, invitation_id=str(uuid4()))
        await self.rpc(0, 'leave', team_id=first['team_id'], generation=first['generation'])
        self.assertEqual((await self.rpc(2, 'status'))['team'], second)
        await self.assert_error('team_already_member', 0, 'invite',
                               peer=self.players[2].player_id, invitation_id=str(uuid4()))
        await self.rpc(2, 'leave', team_id=second['team_id'], generation=second['generation'])
        invitation = await self.invite(0, 2)
        self.assertIsNone((await self.rpc(0, 'status'))['team'])
        changed = await self.accept(2, invitation)
        self.assertEqual(changed['members'], [self.players[0].player_id, self.players[2].player_id])
        self.assertIsNone((await self.rpc(1, 'status'))['team'])
        self.assertIsNone((await self.rpc(3, 'status'))['team'])

    async def test_reconnect_invalidates_pending_consent_and_existing_membership(self):
        invitation = await self.invite()
        old = self.companions[1].session_epoch
        config = self.companions[1].config
        await self.companions[1].close()
        await wait_until(lambda: self.players[1].player_id not in self.server.sessions)
        self.companions[1] = Companion(config)
        await self.companions[1].start()
        await wait_until(lambda: self.companions[1].connected)
        self.assertGreater(self.companions[1].session_epoch, old)
        await self.assert_error('team_invitation_missing', 1, 'accept',
                               invitation_id=invitation['invitation_id'], generation=invitation['generation'])
        team = await self.form()
        await self.companions[1].close()
        await wait_until(lambda: self.players[1].player_id not in self.server.sessions)
        self.assertIsNone((await self.rpc(0, 'status'))['team'])
        self.assertEqual((await self.rpc(2, 'status'))['teams'], [])

    async def test_restart_is_session_local_and_does_not_replay_old_acceptance(self):
        invitation = await self.invite()
        await self.form(2, 3)
        old_epochs = [c.session_epoch for c in self.companions]
        port = self.server.address[1]
        await self.server.close()
        self.server = WorldServer(self.config, store=self.store, development_teams=True)
        await self.server.start(port=port)
        await wait_until(lambda: all(c.connected and c.session_epoch != old
                                   for c, old in zip(self.companions, old_epochs)))
        self.assertEqual((await self.rpc(0, 'status'))['teams'], [])
        await self.assert_error('team_invitation_missing', 1, 'accept',
                               invitation_id=invitation['invitation_id'], generation=invitation['generation'])

    async def test_raw_actor_claims_are_refused_with_correlated_error_and_current_actor_survives(self):
        raw = await self.replace_with_raw()
        invitation = await self.invite()
        result = await raw.rpc('accept', invitation_id=invitation['invitation_id'],
                               generation=invitation['generation'], actor=self.players[1].player_id)
        self.assertEqual(result['type'], 'team_error')
        self.assertEqual(result['code'], 'invalid_fields')
        self.assertEqual(result['player_id'], self.players[3].player_id)
        result = await raw.rpc('accept', invitation_id=invitation['invitation_id'],
                               generation=invitation['generation'])
        self.assertEqual(result['code'], 'team_not_participant')
        self.assertIsNone((await self.rpc(1, 'status'))['team'])
        result = await raw.rpc('status')
        self.assertEqual(result['type'], 'team_result')
        validate_team_reply(result, self.players[3].player_id, self.store.metadata.world_id, raw.epoch)

    async def test_stale_epoch_on_actual_tcp_closes_actor_without_accepting(self):
        raw = await self.replace_with_raw()
        invitation = await self.invite(0, 3)
        await raw.send(dict(type='team_accept', request_id=str(uuid4()),
                            session_epoch=self.companions[0].session_epoch,
                            invitation_id=invitation['invitation_id'], generation=invitation['generation']))
        result = await raw.next()
        self.assertEqual(result['type'], 'error')
        self.assertEqual(result['code'], 'session_epoch_mismatch')
        await wait_until(lambda: self.players[3].player_id not in self.server.sessions)
        self.assertIsNone((await self.rpc(0, 'status'))['team'])

    async def test_database_revoked_lease_is_refused_even_with_live_tcp_session(self):
        team = await self.form()
        player, companion = self.players[0], self.companions[0]
        self.store.release_lease(player.player_id, companion.session_epoch)
        await self.assert_error('stale_lease', 0, 'status')
        self.assertIsNone((await self.rpc(1, 'status'))['team'])
        self.assertTrue(companion.connected)

    async def test_lost_accept_reply_is_uncertain_until_explicit_authoritative_status(self):
        invitation = await self.invite()
        reply = self.server._team_reply
        held = []
        def lose_once(session, request, **fields):
            if request['type'] == 'team_accept':
                held.append((session, request, fields))
            else:
                reply(session, request, **fields)
        with patch.object(self.server, '_team_reply', side_effect=lose_once):
            with self.assertRaises(TimeoutError):
                await self.companions[1].team_rpc('accept', timeout=0.02,
                    invitation_id=invitation['invitation_id'], generation=invitation['generation'])
        self.assertEqual(len(held), 1)
        self.assertEqual(self.companions[1]._team_pending, {})
        status = await self.rpc(1, 'status')
        self.assertEqual(status['team']['members'], [p.player_id for p in self.players[:2]])
        session, request, fields = held[0]
        reply(session, request, **fields)  # Valid late ACK cannot become a new operation.
        self.assertEqual((await self.rpc(1, 'status'))['team'], status['team'])
        self.assertTrue(self.companions[1].connected)

    async def test_default_disabled_world_returns_refusal_without_disrupting_checkpoint_info(self):
        epochs = [c.session_epoch for c in self.companions]
        port = self.server.address[1]
        await self.server.close()
        self.server = WorldServer(self.config, store=self.store)
        await self.server.start(port=port)
        await wait_until(lambda: all(c.connected and c.session_epoch != old
                                   for c, old in zip(self.companions, epochs)))
        self.assertIsNone(self.server.team_desk)
        await self.assert_error('team_disabled', 0, 'invite',
                               peer=self.players[1].player_id, invitation_id=str(uuid4()))
        info = await self.companions[0].checkpoint_rpc('info')
        self.assertIsNone(info['checkpoint'])
        self.assertTrue(all(c.connected for c in self.companions))

    async def test_unresolved_local_trade_journal_does_not_gate_transient_teams(self):
        companion = self.companions[0]
        pending = Path(self.temp.name)/'pending-trade.json'
        pending.write_text('{"pending": true}', encoding='utf-8')
        companion._live_trade_pending_path = pending
        invitation = await self.invite()
        team = await self.accept(1, invitation)
        self.assertEqual((await self.rpc(0, 'status'))['team'], team)
        await self.rpc(0, 'leave', team_id=team['team_id'], generation=team['generation'])
        self.assertIsNone((await self.rpc(1, 'status'))['team'])
        self.assertTrue(pending.exists())

    async def test_timeout_numeric_envelope_and_pending_capacity_are_bounded_before_send(self):
        companion = self.companions[0]
        for timeout in (True, 0, -1, float('inf'), 61, 10**1000):
            with self.assertRaises(ValueError):
                await companion.team_rpc('status', timeout=timeout)
        with self.assertRaises(ValueError):
            await companion.team_rpc('status', session_epoch=1)
        with self.assertRaises(ProtocolError):
            await companion.team_rpc('status', actor=self.players[1].player_id)
        futures = []
        for _ in range(8):
            future = asyncio.get_running_loop().create_future(); futures.append(future)
            companion._team_pending[str(uuid4())] = ({}, future)
        try:
            with self.assertRaises(ValueError):
                await companion.team_rpc('status')
        finally:
            companion._team_pending.clear()
            for future in futures:
                future.cancel()
        self.assertIsNone((await self.rpc(0, 'status'))['team'])


class TeamTradeIndependenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_pending_trade_and_team_consent_do_not_modify_each_other_or_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TradeCheckpointStore(Path(directory)/'world.sqlite3', 'build', BASELINE_RULESET)
            clients = []
            server = None
            try:
                store.begin_server_boot()
                players, heads = [], []
                for index in range(2):
                    player = store.create_player(f'Independent {index}')
                    lease = store.acquire_lease(player.player_id, player.credential)
                    source = source_flash(('party:0',), personalities=(index+7,))
                    store.enroll_player(player.player_id, source)
                    grant = store.reserve_instances(player.player_id, lease, str(uuid4()), 0, 1, 32)
                    payload = owned_flash(grant, (('party:0', grant.start),), personalities=(index+7,))
                    head = store.commit_checkpoint(player.player_id, lease, str(uuid4()), 0,
                                                   payload, 'build', BASELINE_RULESET, OWNERSHIP_PROFILE)
                    store.release_lease(player.player_id, lease)
                    players.append(player); heads.append(head)
                config = ServerConfig('build', BASELINE_RULESET, heartbeat_interval=0.05,
                                      idle_timeout=10, monitor_interval=0.01)
                server = WorldServer(config, store=store, development_trades=True, development_teams=True)
                await server.start(port=0)
                for player in players:
                    clients.append(await RawTeamClient.connect(server.address, player, 'build'))
                transaction = str(uuid4())
                async def trade(operation, **fields):
                    request_id = str(uuid4())
                    if operation in PREPARATION_OPERATIONS:
                        fields['preparation_version'] = PREPARATION_VERSION
                    await clients[0].send(dict(type='trade_' + operation, session_epoch=clients[0].epoch,
                                              request_id=request_id, **fields))
                    value = await clients[0].next()
                    self.assertEqual(value['request_id'], request_id)
                    self.assertEqual(value['type'], 'trade_result')
                    return value['trade']
                proposal = await trade('open', transaction_id=transaction, peer=players[1].player_id)
                invitation = (await clients[0].rpc('invite', peer=players[1].player_id,
                                                   invitation_id=str(uuid4())))['result']
                team = (await clients[1].rpc('accept', invitation_id=invitation['invitation_id'],
                                               generation=invitation['generation']))['result']
                self.assertEqual(await trade('status', transaction_id=transaction), proposal)
                await clients[0].rpc('leave', team_id=team['team_id'], generation=team['generation'])
                self.assertEqual(await trade('status', transaction_id=transaction), proposal)
                for index in range(2):
                    self.assertEqual(store.read_checkpoint(players[index].player_id, clients[index].epoch),
                                     heads[index])
                store.integrity_check()
            finally:
                for client in clients:
                    await client.close()
                if server is not None:
                    await server.close()
                store.close()


class TeamGateTests(unittest.TestCase):
    def test_gate_is_boolean_default_disabled_and_requires_authenticated_owned_world(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = CheckpointStore(Path(directory)/'legacy.sqlite3', 'build', BASELINE_RULESET, LAYOUT_ID)
            owned = OwnershipCheckpointStore(Path(directory)/'owned.sqlite3', 'build', BASELINE_RULESET)
            config = ServerConfig('build', BASELINE_RULESET)
            try:
                self.assertIsNone(WorldServer(config, store=owned).team_desk)
                self.assertIsNotNone(WorldServer(config, store=owned, development_teams=True).team_desk)
                for store in (None, legacy):
                    with self.assertRaisesRegex(ValueError, 'ownership world'):
                        WorldServer(config, store=store, development_teams=True)
                with self.assertRaisesRegex(ValueError, 'boolean'):
                    WorldServer(config, store=owned, development_teams=1)
            finally:
                owned.close(); legacy.close()


if __name__ == '__main__':
    unittest.main()
