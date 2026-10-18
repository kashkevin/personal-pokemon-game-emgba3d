"""Shared fixtures for the networking tests: a real host world, its TLS identity, and small fake servers on loopback."""
import asyncio
import hashlib
from pathlib import Path
import socket

from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.launcher_session import GameInstallation
from emerald_multiplayer.protocol import PROTOCOL_VERSION, encode_message, read_message
from test_host_world import make_trade_files
from test_player_runtime import write_bundle


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_installation(root):
    root = Path(root)
    rom, manifest = make_trade_files(root)
    bundle = root / "bundle"
    bundle.mkdir(exist_ok=True)
    return GameInstallation(rom, manifest, digest(rom), digest(manifest), write_bundle(bundle))


def make_world(root, installation, *, name="world", names=("Host", "Friend", "Pal"), endpoint="192.168.70.50", port=None):
    return HostWorld.create(Path(root) / name, installation.rom_path, installation.manifest_path, player_names=names,
                            endpoint=endpoint, port=port or free_port())


class FakeWorldServer:
    """A TLS listener with a world's real certificate that answers like a world server in one chosen way:

    ``immediate`` - send this error code as soon as TLS is up (like the peer filter),
    ``on_hello`` - read a hello and answer with this error code (like validate_hello / authentication),
    neither - read and say nothing."""

    def __init__(self, world, *, immediate=None, on_hello=None, tls=True):
        self.world, self.immediate, self.on_hello, self.tls = world, immediate, on_hello, tls
        self.hellos = []
        self._server = None
        self._writers = []

    async def start(self, host="127.0.0.1", port=0):
        context = self.world.server_tls.build_context() if self.tls else None
        self._server = await asyncio.start_server(self._handle, host, port, ssl=context)
        return self

    @property
    def port(self):
        return self._server.sockets[0].getsockname()[1]

    async def _handle(self, reader, writer):
        self._writers.append(writer)
        try:
            if not self.tls:
                writer.write(b"HTTP/1.0 400 Bad Request\r\n\r\n")
                await writer.drain()
                return
            if self.immediate is not None:
                writer.write(encode_message({"type": "error", "protocol": PROTOCOL_VERSION, "code": self.immediate, "message": "x"}))
                await writer.drain()
                return
            hello = await read_message(reader)
            if hello is None:
                return
            self.hellos.append(hello)
            if self.on_hello is not None:
                writer.write(encode_message({"type": "error", "protocol": PROTOCOL_VERSION, "code": self.on_hello, "message": "x"}))
                await writer.drain()
                return
            await reader.read()
        except Exception:
            pass
        finally:
            writer.close()

    async def close(self):
        if self._server is not None:
            self._server.close()
            for writer in self._writers:
                writer.close()
            await self._server.wait_closed()
