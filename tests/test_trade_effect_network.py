"""Real authenticated TCP with disposable SQLite/native-adapter fixtures."""
import asyncio
from types import SimpleNamespace
import unittest
from uuid import uuid4

from emerald_multiplayer.protocol import encode_message, read_message
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_protocol import PREPARATION_OPERATIONS, validate_trade_reply
import test_trade_effect_backend as effect_fixture
from test_trade_effect_backend import NonEvolvingFixtureReplay, POLICY
from test_trade_storage import BUILD, RULESET
from emerald_multiplayer.protocol import PROTOCOL_VERSION


class EffectNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = effect_fixture.PublicEffectBackendTests()
        await self.fixture.asyncSetUp()
        await self.fixture.backend.close()
        self.server = WorldServer(ServerConfig(BUILD, RULESET), store=self.fixture.store, development_trades=True,
            trade_effect_adapter=NonEvolvingFixtureReplay(), trade_effect_policy=POLICY)
        # The fixture replay emulates only ordinary trades. Lucky Trades are a
        # random host decision (friendship chance) with their own tests.
        self.server.trade_effects.lucky_decider = lambda players: False
        await self.server.start(port=0)
        self.clients = []
        for player in self.fixture.fixture.players:
            reader, writer = await asyncio.open_connection(*self.server.address)
            writer.write(encode_message(dict(type="hello", protocol=PROTOCOL_VERSION, build_id=BUILD, ruleset_id=RULESET,
                player_id=player.player_id, display_name=player.display_name, credential=player.credential.hex())))
            await writer.drain()
            welcome = await read_message(reader)
            self.assertEqual(welcome["type"], "welcome")
            self.clients.append((reader, writer, welcome["session_epoch"], player.player_id))
        self.tx = str(uuid4())

    async def asyncTearDown(self):
        for _, writer, _, _ in self.clients:
            writer.close(); await writer.wait_closed()
        await self.server.close()
        await self.fixture.asyncTearDown()

    async def rpc(self, i, operation, **fields):
        reader, writer, epoch, actor = self.clients[i]
        request = dict(type="trade_" + operation, request_id=str(uuid4()), session_epoch=epoch, effects_version=1, **fields)
        if operation in PREPARATION_OPERATIONS:
            request["preparation_version"] = 1
        writer.write(encode_message(request)); await writer.drain()
        async with asyncio.timeout(5):
            while True:
                response = await read_message(reader)
                if response["type"] == "ping":
                    writer.write(encode_message({**response, "type": "pong"})); await writer.drain()
                elif response.get("request_id") == request["request_id"]:
                    return validate_trade_reply(response, SimpleNamespace(player_id=actor, build_id=BUILD, ruleset_id=RULESET),
                        self.fixture.store.save_profile, self.fixture.store.metadata.world_id, epoch)

    async def test_negotiated_two_receipt_publication_and_actor_private_recovery(self):
        supported = await self.rpc(0, "proposals")
        self.assertEqual(supported["effects_version"], 1)
        view = (await self.rpc(0, "open", transaction_id=self.tx, peer=self.clients[1][3]))["trade"]
        self.assertEqual(view["capability"], "native-recipient-save-effects-v1")
        for i in (0, 1):
            cp = self.fixture.store.read_checkpoint(self.clients[i][3], self.clients[i][2])
            view = (await self.rpc(i, "offer", transaction_id=self.tx, generation=view["generation"], revision=cp.revision,
                sha256=cp.sha256, serial=self.fixture.fixture.grants[i].start))["trade"]
        for i in (0, 1):
            view = (await self.rpc(i, "confirm", transaction_id=self.tx, generation=view["generation"], fingerprint=view["fingerprint"]))["trade"]
        self.fixture.proposal = self.server.trade_desk._proposals[self.tx]
        self.fixture.tx = self.tx
        receipts = await self.fixture.receipts()
        for i in (0, 1):
            description = (await self.rpc(i, "prepare", transaction_id=self.tx, generation=view["generation"]))["trade"]["preparation"]
            view = (await self.rpc(i, "effect_prepared", transaction_id=self.tx, generation=view["generation"],
                fingerprint=view["fingerprint"], preparation_id=description["preparation_id"], **receipts[self.clients[i][3]]))["trade"]
            self.assertEqual(view["state"], "preparing")
        async with asyncio.timeout(5):
            while (await self.rpc(0, "status", transaction_id=self.tx))["trade"]["state"] != "committed":
                await asyncio.sleep(.01)
        for i in (0, 1):
            pending = (await self.rpc(i, "pending"))["recoveries"]
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["transaction_id"], self.tx)
            self.assertNotIn("payload", pending[0]["checkpoint"])
        self.fixture.store.integrity_check()
