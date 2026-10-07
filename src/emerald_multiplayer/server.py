"""Four-player transient presence server for local/LAN development.

This prototype intentionally refuses public binds and public-source peers. It
has no authentication, TLS, save persistence, or gameplay transaction support.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
import ipaddress
import math
from typing import Any

from .protocol import (
    MAX_COUNTER, MAX_FRAME_BYTES, MAX_PLAYERS, PROTOCOL_VERSION, ProtocolError,
    encode_message, read_message, validate_heartbeat, validate_hello,
    validate_identity, validate_presence,
)

_LAN_NETWORKS = tuple(ipaddress.ip_network(network) for network in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7",
))


def is_local_address(value: str, allow_lan: bool = False) -> bool:
    """Allow loopback, plus explicit RFC1918/ULA addresses for LAN testing."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_loopback:
        return True
    return allow_lan and any(address.version == network.version and address in network for network in _LAN_NETWORKS)


@dataclass(frozen=True)
class ServerConfig:
    build_id: str
    ruleset_id: str
    heartbeat_interval: float = 5.0
    idle_timeout: float = 20.0
    presence_timeout: float = 3.0
    handshake_timeout: float = 5.0
    send_timeout: float = 1.0
    monitor_interval: float = 0.1
    reliable_limit: int = 8

    def __post_init__(self) -> None:
        validate_identity(self.build_id, "build_id")
        validate_identity(self.ruleset_id, "ruleset_id")
        for name in (
            "heartbeat_interval", "idle_timeout", "presence_timeout",
            "handshake_timeout", "send_timeout", "monitor_interval",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive duration")
        if self.heartbeat_interval >= self.idle_timeout:
            raise ValueError("heartbeat_interval must be shorter than idle_timeout")
        if type(self.reliable_limit) is not int or not 1 <= self.reliable_limit <= 64:
            raise ValueError("reliable_limit must be between 1 and 64")


class OutboundFull(Exception):
    """Reliable control capacity is exhausted; the connection must close."""


class OutboundClosed(Exception):
    """The owning connection is closed."""


class OutboundQueue:
    """Bounded control FIFO plus one replaceable current-world frame."""

    def __init__(self, reliable_limit: int) -> None:
        self.reliable_limit = reliable_limit
        self.controls: deque[bytes] = deque()
        self.world: bytes | None = None
        self.closed = False
        self._ready = asyncio.Event()

    def put_control(self, frame: bytes) -> None:
        if self.closed:
            raise OutboundClosed
        if len(self.controls) >= self.reliable_limit:
            raise OutboundFull
        self.controls.append(frame)
        self._ready.set()

    def put_world(self, frame: bytes) -> None:
        if not self.closed:
            self.world = frame
            self._ready.set()

    async def get(self) -> bytes:
        while True:
            if self.closed:
                raise OutboundClosed
            if self.controls:
                return self.controls.popleft()
            if self.world is not None:
                frame, self.world = self.world, None
                return frame
            self._ready.clear()
            await self._ready.wait()

    def close(self) -> None:
        self.closed = True
        self.controls.clear()
        self.world = None
        self._ready.set()


@dataclass
class PlayerSession:
    player_id: str
    display_name: str
    session_epoch: int
    writer: asyncio.StreamWriter
    outbox: OutboundQueue
    last_seen: float
    last_ping: float
    last_presence: float
    presence: dict[str, Any] | None = None
    ping_nonce: int = 0
    awaiting_ping: int | None = None
    closed: bool = False
    close_reason: str | None = None
    writer_task: asyncio.Task[None] | None = field(default=None, repr=False)

    def close(self, reason: str) -> None:
        if not self.closed:
            self.closed = True
            self.close_reason = reason
            self.outbox.close()
            self.writer.close()


class WorldServer:
    """One event-loop-owned world; UUIDs identify independent transient clients."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.sessions: dict[str, PlayerSession] = {}
        self.world_seq = 0
        self._session_epoch = 0
        self._server: asyncio.Server | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._handlers: set[asyncio.Task[None]] = set()
        self._connections: set[asyncio.StreamWriter] = set()
        self._allow_lan = False
        self._closing = False

    @property
    def address(self) -> tuple[str, int]:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("server is not listening")
        address = self._server.sockets[0].getsockname()
        return address[0], address[1]

    async def start(self, host: str = "127.0.0.1", port: int = 8765, *, allow_lan: bool = False) -> None:
        if self._server is not None:
            raise RuntimeError("server is already started")
        if not is_local_address(host, allow_lan):
            raise ValueError("bind a numeric loopback address, or an explicit LAN address with allow_lan; public/wildcard hosting is disabled")
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        self._allow_lan = allow_lan
        self._closing = False
        self._server = await asyncio.start_server(self._accept, host, port, limit=MAX_FRAME_BYTES + 4)
        self._monitor_task = asyncio.create_task(self._monitor(), name="world-heartbeat")

    async def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("server is not started")
        await self._server.serve_forever()

    async def close(self) -> None:
        self._closing = True
        listening_server = self._server
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None
        for writer in tuple(self._connections):
            writer.close()
        if self._handlers:
            pending = tuple(self._handlers)
            _, remaining = await asyncio.wait(pending, timeout=self.config.send_timeout + 0.5)
            for task in remaining:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        # Python 3.13+ waits for accepted transports as well as the listener.
        # Closing them above must precede this await to avoid shutdown deadlock.
        if listening_server is not None:
            await listening_server.wait_closed()

    async def _reject(self, writer: asyncio.StreamWriter, code: str, message: str) -> None:
        try:
            writer.write(encode_message({"type": "error", "protocol": PROTOCOL_VERSION, "code": code, "message": message}))
            await asyncio.wait_for(writer.drain(), timeout=self.config.send_timeout)
        except (ConnectionError, OSError, asyncio.TimeoutError):
            pass

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._handlers.add(task)
        self._connections.add(writer)
        session: PlayerSession | None = None
        try:
            peer = writer.get_extra_info("peername")
            if self._closing:
                return
            if peer is None or not is_local_address(peer[0], self._allow_lan):
                await self._reject(writer, "public_exposure_disabled", "this prototype permits local/LAN development only")
                return
            # Bound pre-hello sockets as well as the admitted player count.
            if len(self._connections) > MAX_PLAYERS + 8:
                await self._reject(writer, "connection_limit", "too many pending connections")
                return
            hello = await asyncio.wait_for(read_message(reader), self.config.handshake_timeout)
            if hello is None:
                return
            hello = validate_hello(hello, self.config.build_id, self.config.ruleset_id)
            if hello["player_id"] in self.sessions:
                await self._reject(writer, "player_already_connected", "this player identity already has a connection")
                return
            if len(self.sessions) >= MAX_PLAYERS:
                await self._reject(writer, "server_full", "the four-player server is full")
                return
            if self._session_epoch >= MAX_COUNTER:
                await self._reject(writer, "epoch_exhausted", "restart this development server before admitting more sessions")
                return
            self._session_epoch += 1
            now = asyncio.get_running_loop().time()
            session = PlayerSession(
                hello["player_id"], hello["display_name"], self._session_epoch,
                writer, OutboundQueue(self.config.reliable_limit), now, now, now,
            )
            # Admission has no await between checking and claiming the lease.
            self.sessions[session.player_id] = session
            self._control(session, {
                "type": "welcome", "protocol": PROTOCOL_VERSION,
                "build_id": self.config.build_id, "ruleset_id": self.config.ruleset_id,
                "player_id": session.player_id, "session_epoch": session.session_epoch,
                "max_players": MAX_PLAYERS,
                "heartbeat_interval": self.config.heartbeat_interval,
                "idle_timeout": self.config.idle_timeout,
            })
            session.writer_task = asyncio.create_task(self._write(session), name=f"world-writer-{session.session_epoch}")
            self._broadcast_world()
            while not session.closed:
                message = await read_message(reader)
                if message is None:
                    break
                self._receive(session, message)
        except asyncio.TimeoutError:
            await self._reject(writer, "hello_timeout", "hello was not received in time")
        except ProtocolError as error:
            await self._reject(writer, error.code, error.message)
        except (ConnectionError, OSError):
            pass
        finally:
            if session is not None:
                session.close("disconnected")
                if self.sessions.get(session.player_id) is session:
                    del self.sessions[session.player_id]
                    if not self._closing:
                        self._broadcast_world()
                if session.writer_task is not None:
                    session.writer_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await session.writer_task
            writer.close()
            with suppress(ConnectionError, OSError, asyncio.TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), timeout=self.config.send_timeout)
            self._connections.discard(writer)
            self._handlers.discard(task)

    def _control(self, session: PlayerSession, message: dict[str, Any]) -> None:
        try:
            session.outbox.put_control(encode_message(message))
        except (OutboundFull, OutboundClosed):
            session.close("control_backpressure")

    def _receive(self, session: PlayerSession, message: dict[str, Any]) -> None:
        kind = message.get("type")
        now = asyncio.get_running_loop().time()
        if kind == "presence":
            presence = validate_presence(message, session.session_epoch)
            session.last_seen = now
            previous = session.presence
            if previous is not None:
                if presence["seq"] <= previous["seq"] or presence["map_epoch"] < previous["map_epoch"]:
                    return
                changed_map = (presence["map_group"], presence["map_number"]) != (previous["map_group"], previous["map_number"])
                if changed_map and presence["map_epoch"] <= previous["map_epoch"]:
                    return
            session.presence = presence
            session.last_presence = now
            self._broadcast_world()
        elif kind in ("ping", "pong"):
            heartbeat = validate_heartbeat(message, session.session_epoch)
            if kind == "pong":
                if heartbeat["nonce"] != session.awaiting_ping:
                    raise ProtocolError("unexpected_pong", "pong does not match the outstanding heartbeat")
                session.awaiting_ping = None
            else:
                self._control(session, {**heartbeat, "type": "pong"})
            session.last_seen = now
        else:
            raise ProtocolError("invalid_type", "message type is unsupported")

    def _broadcast_world(self) -> None:
        self.world_seq += 1
        players = [{
            "player_id": session.player_id, "display_name": session.display_name,
            "session_epoch": session.session_epoch, "presence": session.presence,
        } for session in sorted(self.sessions.values(), key=lambda item: item.player_id) if not session.closed]
        frame = encode_message({"type": "world", "protocol": PROTOCOL_VERSION, "world_seq": self.world_seq, "players": players})
        for session in tuple(self.sessions.values()):
            session.outbox.put_world(frame)

    async def _write(self, session: PlayerSession) -> None:
        try:
            while not session.closed:
                frame = await session.outbox.get()
                session.writer.write(frame)
                # Never allow the transport buffer to grow through repeated writes
                # without completing (or timing out) the previous drain.
                await asyncio.wait_for(session.writer.drain(), timeout=self.config.send_timeout)
        except (OutboundClosed, ConnectionError, OSError, asyncio.TimeoutError):
            session.close("slow_or_disconnected_consumer")

    async def _monitor(self) -> None:
        while True:
            await asyncio.sleep(self.config.monitor_interval)
            now = asyncio.get_running_loop().time()
            changed = False
            for session in tuple(self.sessions.values()):
                if session.closed:
                    continue
                if now - session.last_seen >= self.config.idle_timeout:
                    session.close("heartbeat_timeout")
                    continue
                if session.presence is not None and now - session.last_presence >= self.config.presence_timeout and session.presence["activity"] != "unavailable":
                    session.presence = {**session.presence, "activity": "unavailable"}
                    changed = True
                if now - session.last_ping >= self.config.heartbeat_interval and session.awaiting_ping is None:
                    session.ping_nonce = session.ping_nonce % MAX_COUNTER + 1
                    session.awaiting_ping = session.ping_nonce
                    session.last_ping = now
                    self._control(session, {
                        "type": "ping", "protocol": PROTOCOL_VERSION,
                        "session_epoch": session.session_epoch, "nonce": session.ping_nonce,
                    })
            if changed:
                self._broadcast_world()


async def _run(args: argparse.Namespace) -> None:
    server = WorldServer(ServerConfig(args.build_id, args.ruleset_id))
    await server.start(args.host, args.port, allow_lan=args.allow_lan)
    host, port = server.address
    print(f"Phase 2 presence prototype listening at {host}:{port}; four players maximum.", flush=True)
    print("Local/LAN only. No authentication, TLS, persistence, trades, or battles.", flush=True)
    try:
        await server.serve_forever()
    finally:
        await server.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-id", required=True, help="exact compatible mailbox-ROM build identity")
    parser.add_argument("--ruleset-id", required=True, help="explicit ruleset identity; the clean baseline is not the future Gen 6 profile")
    parser.add_argument("--host", default="127.0.0.1", help="numeric loopback address, or explicit LAN address")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allow-lan", action="store_true", help="opt in to RFC1918/ULA LAN clients; public access remains disabled")
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except (ValueError, ProtocolError) as error:
        parser.error(str(error))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
