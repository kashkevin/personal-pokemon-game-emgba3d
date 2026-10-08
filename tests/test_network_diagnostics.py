import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.network_diagnostics import probe_invitation
from test_host_world import make_trade_files


class NetworkProbeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        rom, manifest = make_trade_files(self.root)
        self.host = HostWorld.create(self.root / "host", rom, manifest,
            player_names=["Host", "Friend"], endpoint="127.0.0.1", port=8765)
        self.received = asyncio.Queue()
        self.listener = None

    async def asyncTearDown(self):
        if self.listener:
            self.listener.close()
            await self.listener.wait_closed()

    async def listen(self):
        async def connected(reader, writer):
            try:
                self.received.put_nowait(await asyncio.wait_for(reader.read(1024), 2))
            finally:
                writer.close()
                await writer.wait_closed()
        self.listener = await asyncio.start_server(connected, "127.0.0.1", 0,
                                                  ssl=self.host.server_tls.build_context())
        return self.listener.sockets[0].getsockname()[1]

    async def test_real_tls_probe_sends_no_player_data_and_cannot_claim_lan(self):
        port = await self.listen()
        invitation = replace(self.host.invitation(1), port=port)
        path = self.root / "friend.json"
        invitation.save(path)
        result = await probe_invitation(path, self.root / "private")
        self.assertEqual((result.code, result.route_scope, result.tls_verified), ("tls_reachable", "loopback", True))
        self.assertFalse(result.player_authenticated)
        self.assertFalse(result.separate_device_proven)
        self.assertFalse(result.internet_path_proven)
        self.assertEqual(await asyncio.wait_for(self.received.get(), 2), b"")
        self.assertNotIn(invitation.credential.hex(), repr(result))
        self.assertEqual(list((self.root / "private").iterdir()), [])

    async def test_refused_connection_is_a_bounded_result(self):
        port = await self.listen()
        self.listener.close()
        await self.listener.wait_closed()
        path = self.root / "friend.json"
        replace(self.host.invitation(1), port=port).save(path)
        result = await probe_invitation(path, self.root / "private", timeout=.5)
        self.assertEqual(result.code, "unreachable")
        self.assertFalse(result.tls_verified)

    async def test_invalid_invitation_never_opens_network(self):
        path = self.root / "bad.json"
        path.write_text('{"credential":"secret"}')
        with patch("asyncio.open_connection") as connect:
            result = await probe_invitation(path, self.root / "private")
            connect.assert_not_called()
        self.assertEqual(result.code, "invalid_invitation")


if __name__ == "__main__":
    unittest.main()
