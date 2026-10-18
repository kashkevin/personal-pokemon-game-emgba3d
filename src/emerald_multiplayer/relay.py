"""A small TCP relay for homes where friends cannot reach the host directly (CGNAT, no router access, a locked-down network).

Someone the players trust runs the relay on a machine with a reachable address: a cheap VPS, or a PC with one forwarded port::

    python -m emerald_multiplayer.relay serve --port 7780
    EmeraldTogether.exe --relay-server --port 7780          (the packaged game; a console window shows the relay)

The host's game dials *out* to the relay (outgoing connections work behind any home router), registers its world's room and, for
every friend the relay announces, opens one more outgoing connection that the relay joins to the friend's. The friend's game runs
the normal TLS handshake through that pipe and checks the host's pinned certificate exactly as on a direct connection, so the TLS
session is end to end between the friend's game and the host's world server: **the relay only ever sees ciphertext**. It cannot
read or change game traffic, sign in as anyone, or impersonate the host (it has no certificate key). What it can do is refuse or
drop connections, and see who connects to which room and how much they send.

Wire protocol (version ETR1). Every preamble line is ASCII, at most ``MAX_LINE`` bytes, ending in ``\\n``:

* host control: ``ETR1 HOST <room> <token>`` -> ``OK`` (or ``ERR <code>``). The room is the world's UUID; the token is
  HMAC-SHA256(the world's relay secret, "emerald-relay-room:" + room). The first registrant holds the room for as long as the relay
  runs (``room_ttl`` after its host leaves); a registration with a different token is refused with ``ERR room_taken``, the same
  token replaces a stale control connection. The relay then sends ``CONNECT <id>`` per friend and ``PING`` (answered ``PONG``).
* host data: ``ETR1 DATA <room> <id>`` -> ``OK``, then raw bytes. ``<id>`` is a 128-bit random value sent only on that room's
  authenticated control connection.
* friend: ``ETR1 JOIN <room>`` -> ``OK`` once the host's data connection arrived, then raw bytes (TLS), or ``ERR host_offline``,
  ``ERR host_timeout``, ``ERR busy``, ``ERR full``, ``ERR bad_request``.

Limits: bounded preamble lines and preamble time, idle timeouts on pipes and control connections, maximum rooms, connections,
connections per address, waiting and active friends per room. Replies are never larger than requests (no amplification), and data
is only ever forwarded from one paired peer to the other with normal TCP flow control (no unbounded buffering).

The relay keeps nothing on disk. The room token travels in the clear between the host and the relay: someone who can watch that
traffic could take the room after a relay restart and so block it (they could block the traffic anyway), but never read or join the
game. Nothing in this module needs a package outside the Python standard library.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import hmac
import ipaddress
import math
import re
import secrets
import socket
import sys
import time

PROTOCOL = "ETR1"
MAX_LINE = 200
DEFAULT_PORT = 7780
_ROOM = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[0-9a-f]{32}")
_HOST_NAME = re.compile(r"(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*")
_CHUNK = 65_536

# Codes (the same strings as connection_diagnostics) for what a friend or host learns from the relay.
RELAY_UNREACHABLE = "relay_unreachable"
RELAY_HOST_OFFLINE = "relay_host_offline"
RELAY_BUSY = "relay_busy"
RELAY_FAILED = "relay_failed"
RELAY_ROOM_TAKEN = "relay_room_taken"
_REPLIES = {"host_offline": RELAY_HOST_OFFLINE, "host_timeout": RELAY_HOST_OFFLINE, "busy": RELAY_BUSY, "full": RELAY_BUSY,
            "room_taken": RELAY_ROOM_TAKEN}


class RelayError(ConnectionError):
    """The relay refused, did not answer correctly, or could not be reached (``reason`` names the network failure then)."""

    def __init__(self, code, message=None, *, reason=None):
        self.code = code
        self.reason_code = reason
        super().__init__(message or code)


class _LineError(Exception):
    pass


def valid_endpoint(address, port):
    """A relay address a person can type: a numeric unicast address or a host name, and a port."""
    if type(port) is not int or not 1 <= port <= 65535:
        return False
    if type(address) is not str or not address or len(address) > 253 or address != address.strip():
        return False
    try:
        value = ipaddress.ip_address(address)
    except ValueError:
        return _HOST_NAME.fullmatch(address) is not None and not address.replace(".", "").isdigit()
    from .secure_transport import is_numeric_unicast_address
    return "%" not in address and str(value) == address and is_numeric_unicast_address(address)


def room_token(secret, room):
    """What the host shows the relay to hold its room: never the secret itself."""
    if type(secret) is not bytes or len(secret) < 16 or type(room) is not str or not _ROOM.fullmatch(room):
        raise ValueError("relay secret or room is invalid")
    return hmac.new(secret, b"emerald-relay-room:" + room.encode("ascii"), hashlib.sha256).hexdigest()


async def _read_line(reader, timeout):
    """One preamble line, at most MAX_LINE bytes. Reads byte by byte so nothing after the newline is consumed."""
    line = bytearray()
    async with asyncio.timeout(timeout):
        while True:
            byte = await reader.read(1)
            if not byte:
                raise _LineError("closed")
            if byte == b"\n":
                break
            line += byte
            if len(line) > MAX_LINE:
                raise _LineError("line too long")
    try:
        text = line.decode("ascii")
    except UnicodeDecodeError:
        raise _LineError("not ascii") from None
    if not text.isprintable():
        raise _LineError("control characters")
    return text


async def _close(writer, timeout=1.0):
    if writer is None:
        return
    try:
        writer.close()
    except (OSError, RuntimeError):
        return
    try:
        async with asyncio.timeout(timeout):
            await writer.wait_closed()
    except (OSError, TimeoutError, asyncio.CancelledError, Exception):
        pass


async def pipe(a_reader, a_writer, b_reader, b_writer, *, idle_timeout=300.0, linger=2.0):
    """Copy bytes both ways until one side ends (then give the other ``linger`` seconds) or nothing moves for ``idle_timeout``."""
    loop = asyncio.get_running_loop()
    last = [loop.time()]

    async def one_way(source, target):
        while True:
            data = await source.read(_CHUNK)
            if not data:
                break
            last[0] = loop.time()
            target.write(data)
            await target.drain()
        try:
            if target.can_write_eof():
                target.write_eof()
        except (OSError, RuntimeError):
            pass

    tasks = {asyncio.create_task(one_way(a_reader, b_writer)), asyncio.create_task(one_way(b_reader, a_writer))}
    try:
        while tasks:
            done, _ = await asyncio.wait(tasks, timeout=min(idle_timeout, 5.0), return_when=asyncio.FIRST_COMPLETED)
            if done:
                for task in done:
                    tasks.discard(task)
                    if not task.cancelled():
                        task.exception()        # consume a reset/broken pipe: it ends this pipe like a close
                if tasks:
                    await asyncio.wait(tasks, timeout=linger)
                break
            if loop.time() - last[0] >= idle_timeout:
                break
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------------------------------------------- relay server


@dataclass(frozen=True)
class RelayLimits:
    max_rooms: int = 64
    max_connections: int = 256
    max_per_address: int = 32
    max_pending_per_room: int = 8
    max_pipes_per_room: int = 8
    preamble_timeout: float = 10.0
    pair_timeout: float = 6.0          # a friend waits this long for the host's data connection (under the friend's 8 s budget)
    idle_timeout: float = 300.0        # a pipe with no bytes either way for this long is closed (the game sends every few seconds)
    ping_interval: float = 20.0
    control_timeout: float = 60.0      # a host control connection that answers nothing for this long is closed
    room_ttl: float = 7 * 86_400.0     # how long a room stays reserved for its token after its host left

    def __post_init__(self):
        for name in ("max_rooms", "max_connections", "max_per_address", "max_pending_per_room", "max_pipes_per_room"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 100_000:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("preamble_timeout", "pair_timeout", "idle_timeout", "ping_interval", "control_timeout", "room_ttl"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive duration")
        if self.ping_interval >= self.control_timeout:
            raise ValueError("ping_interval must be shorter than control_timeout")


@dataclass
class _Room:
    token_hash: bytes
    control: asyncio.StreamWriter | None = None
    pending: dict = field(default_factory=dict)
    pipes: int = 0
    last_seen: float = 0.0


class RelayServer:
    def __init__(self, limits=None, *, clock=time.monotonic):
        self.limits = limits or RelayLimits()
        self.clock = clock
        self.rooms: dict[str, _Room] = {}
        self._server = None
        self._connections = 0
        self._per_address = defaultdict(int)
        self._writers = set()
        self._tasks = set()

    @property
    def address(self):
        if self._server is None or not self._server.sockets:
            raise RuntimeError("relay is not listening")
        return self._server.sockets[0].getsockname()[:2]

    async def start(self, host="0.0.0.0", port=DEFAULT_PORT):
        if self._server is not None:
            raise RuntimeError("relay is already started")
        self._server = await asyncio.start_server(self._accept, host, port, limit=_CHUNK)

    async def serve_forever(self):
        await self._server.serve_forever()

    async def close(self):
        server, self._server = self._server, None
        if server is not None:
            server.close()
        for writer in tuple(self._writers):
            try:
                writer.close()
            except (OSError, RuntimeError):
                pass
        if self._tasks:
            await asyncio.wait(tuple(self._tasks), timeout=2)
            for task in tuple(self._tasks):
                task.cancel()
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        if server is not None:
            await server.wait_closed()

    async def _reply(self, writer, text):
        writer.write(text.encode("ascii") + b"\n")
        async with asyncio.timeout(5):
            await writer.drain()

    async def _accept(self, reader, writer):
        task = asyncio.current_task()
        self._tasks.add(task)
        self._writers.add(writer)
        peer = writer.get_extra_info("peername")
        address = peer[0] if peer else "?"
        counted = False
        try:
            if self._connections >= self.limits.max_connections or self._per_address[address] >= self.limits.max_per_address:
                await self._reply(writer, "ERR busy")
                return
            self._connections += 1
            self._per_address[address] += 1
            counted = True
            try:
                parts = (await _read_line(reader, self.limits.preamble_timeout)).split(" ")
            except (_LineError, TimeoutError):
                await self._reply(writer, "ERR bad_request")
                return
            if len(parts) < 2 or parts[0] != PROTOCOL:
                await self._reply(writer, "ERR bad_request")
                return
            command, arguments = parts[1], parts[2:]
            if command == "HOST" and len(arguments) == 2 and _ROOM.fullmatch(arguments[0]) and _HEX64.fullmatch(arguments[1]):
                await self._host(reader, writer, *arguments)
            elif command == "DATA" and len(arguments) == 2 and _ROOM.fullmatch(arguments[0]) and _ID.fullmatch(arguments[1]):
                await self._data(reader, writer, *arguments)
            elif command == "JOIN" and len(arguments) == 1 and _ROOM.fullmatch(arguments[0]):
                await self._join(reader, writer, arguments[0])
            else:
                await self._reply(writer, "ERR bad_request")
        except (OSError, TimeoutError, _LineError, asyncio.IncompleteReadError):
            pass
        finally:
            if counted:
                self._connections -= 1
                self._per_address[address] -= 1
                if self._per_address[address] <= 0:
                    del self._per_address[address]
            self._writers.discard(writer)
            await _close(writer)
            self._tasks.discard(task)

    def _evict(self):
        now = self.clock()
        for room_id, room in list(self.rooms.items()):
            if room.control is None and not room.pending and room.pipes == 0 and now - room.last_seen >= self.limits.room_ttl:
                del self.rooms[room_id]
        if len(self.rooms) < self.limits.max_rooms:
            return True
        idle = [(room.last_seen, room_id) for room_id, room in self.rooms.items()
                if room.control is None and not room.pending and room.pipes == 0]
        if not idle:
            return False
        del self.rooms[min(idle)[1]]
        return True

    async def _host(self, reader, writer, room_id, token):
        token_hash = hashlib.sha256(token.encode("ascii")).digest()
        room = self.rooms.get(room_id)
        if room is None:
            if not self._evict():
                await self._reply(writer, "ERR full")
                return
            room = self.rooms[room_id] = _Room(token_hash)
        elif not hmac.compare_digest(room.token_hash, token_hash):
            await self._reply(writer, "ERR room_taken")
            return
        previous, room.control = room.control, writer
        room.last_seen = self.clock()
        if previous is not None:
            await _close(previous, .5)
        await self._reply(writer, "OK")
        loop = asyncio.get_running_loop()
        answered = [loop.time()]

        async def ping():
            while True:
                await asyncio.sleep(self.limits.ping_interval)
                await self._reply(writer, "PING")

        pinger = asyncio.create_task(ping())
        try:
            while True:
                remaining = self.limits.control_timeout - (loop.time() - answered[0])
                if remaining <= 0:
                    break
                try:
                    line = await _read_line(reader, remaining)
                except TimeoutError:
                    break
                if line != "PONG":
                    break
                answered[0] = loop.time()
                room.last_seen = self.clock()
        except (_LineError, OSError):
            pass
        finally:
            pinger.cancel()
            await asyncio.gather(pinger, return_exceptions=True)
            if room.control is writer:
                room.control = None
                room.last_seen = self.clock()
                for future in room.pending.values():
                    if not future.done():
                        future.set_exception(ConnectionError("host left"))

    async def _data(self, reader, writer, room_id, connection_id):
        room = self.rooms.get(room_id)
        future = room.pending.get(connection_id) if room is not None else None
        if future is None or future.done():
            await self._reply(writer, "ERR unknown_connection")
            return
        finished = asyncio.Event()
        future.set_result((reader, writer, finished))
        await finished.wait()

    async def _join(self, reader, writer, room_id):
        room = self.rooms.get(room_id)
        if room is None or room.control is None:
            await self._reply(writer, "ERR host_offline")
            return
        if len(room.pending) >= self.limits.max_pending_per_room or room.pipes >= self.limits.max_pipes_per_room:
            await self._reply(writer, "ERR busy")
            return
        connection_id = secrets.token_hex(16)
        future = asyncio.get_running_loop().create_future()
        room.pending[connection_id] = future
        host = None
        try:
            try:
                await self._reply(room.control, "CONNECT " + connection_id)
                async with asyncio.timeout(self.limits.pair_timeout):
                    host = await future
            except (TimeoutError, ConnectionError, OSError, AttributeError, asyncio.CancelledError) as error:
                if future.done() and not future.cancelled() and future.exception() is None:
                    future.result()[2].set()           # a data connection that arrived at the last moment is released
                if isinstance(error, asyncio.CancelledError):
                    raise
                await self._reply(writer, "ERR host_timeout")
                return
            finally:
                room.pending.pop(connection_id, None)
            host_reader, host_writer, finished = host
            room.pipes += 1
            try:
                await self._reply(host_writer, "OK")
                await self._reply(writer, "OK")
                await pipe(reader, writer, host_reader, host_writer, idle_timeout=self.limits.idle_timeout)
            finally:
                room.pipes -= 1
                room.last_seen = self.clock()
                finished.set()
        finally:
            if not future.done():
                future.cancel()


# ------------------------------------------------------------------------------------------------------------- friend connector


async def open_relay_connection(relay_host, relay_port, room, *, ssl=None, server_hostname=None, ssl_handshake_timeout=5.0,
                                limit=_CHUNK, connect_timeout=6.0, pair_timeout=7.0):
    """A stream to the world ``room`` through the relay, upgraded to TLS with ``ssl`` (the caller verifies the pinned certificate
    afterwards, exactly as on a direct connection). Raises RelayError for anything the relay says or does not say."""
    if not valid_endpoint(relay_host, relay_port) or type(room) is not str or not _ROOM.fullmatch(room):
        raise RelayError(RELAY_FAILED, "relay address or room is invalid")
    try:
        async with asyncio.timeout(connect_timeout):
            reader, writer = await asyncio.open_connection(relay_host, relay_port, limit=limit)
    except (OSError, TimeoutError) as error:
        from .connection_diagnostics import classify
        raise RelayError(RELAY_UNREACHABLE, reason=classify(error)[0]) from None
    try:
        writer.write(f"{PROTOCOL} JOIN {room}\n".encode("ascii"))
        try:
            async with asyncio.timeout(5):
                await writer.drain()
            line = await _read_line(reader, pair_timeout)
        except (TimeoutError, _LineError, OSError):
            raise RelayError(RELAY_FAILED, "the relay did not answer") from None
        if line.startswith("ERR "):
            raise RelayError(_REPLIES.get(line[4:], RELAY_FAILED), "relay refused: " + line[4:40])
        if line != "OK":
            raise RelayError(RELAY_FAILED, "unexpected relay answer")
        if ssl is not None:
            await writer.start_tls(ssl, server_hostname=server_hostname, ssl_handshake_timeout=ssl_handshake_timeout)
        return reader, writer
    except BaseException:
        await _close(writer, .5)
        raise


# ------------------------------------------------------------------------------------------------------------------ host agent


AGENT_MESSAGES = {
    "relay_off": "The relay is not used for this world.",
    "relay_connecting": "Connecting to the relay...",
    "relay_ready": "Connected to the relay. Friends can join through it.",
    "relay_unreachable": "The relay could not be reached. Friends cannot join through it until it answers; the game keeps trying.",
    "relay_room_taken": ("The relay already holds this world for a different relay key, so friends cannot join through it. Use "
                         "another relay, or ask its owner to restart it."),
    "relay_busy": "The relay is full. The game keeps trying; another relay may work better.",
    "relay_failed": "Something answered at the relay address, but it is not a compatible EmeraldTogether relay.",
}


@dataclass(frozen=True)
class RelayAgentStatus:
    code: str
    relay: str = ""              # "address:port" of the relay (public information, never the secret)
    friends: int = 0             # friends currently piped through the relay

    @property
    def message(self):
        return AGENT_MESSAGES.get(self.code, AGENT_MESSAGES["relay_failed"])

    @property
    def ready(self):
        return self.code == "relay_ready"


class RelayHostAgent:
    """The host's side: keeps the world's room on the relay and pipes each announced friend to the local world server.

    ``target`` is a callable returning the (address, port) of the world server's relayed-connection listener, read for every
    friend so a restarted host service is followed."""

    def __init__(self, relay_host, relay_port, room, secret, target, *, on_status=None, max_friends=8, idle_timeout=300.0,
                 retry_delays=(1.0, 2.0, 5.0, 10.0, 30.0), connect_timeout=8.0):
        if not valid_endpoint(relay_host, relay_port) or not callable(target):
            raise ValueError("relay address or target is invalid")
        self.relay_host, self.relay_port, self.room = relay_host, relay_port, room
        self._token = room_token(secret, room)
        self._target = target
        self._on_status = on_status
        self.max_friends = max_friends
        self.idle_timeout = idle_timeout
        self.retry_delays = tuple(retry_delays)
        self.connect_timeout = connect_timeout
        self._task = None
        self._pipes = set()
        self._control = None
        self.status = RelayAgentStatus("relay_connecting", self._label())

    def _label(self):
        host = f"[{self.relay_host}]" if ":" in self.relay_host else self.relay_host
        return f"{host}:{self.relay_port}"

    def _set(self, code):
        status = RelayAgentStatus(code, self._label(), len(self._pipes))
        if status == self.status:
            return
        self.status = status
        if self._on_status is not None:
            try:
                self._on_status(status)
            except Exception:                                     # noqa: BLE001 - an observer never stops the agent
                pass

    async def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="relay-host-agent")

    async def close(self):
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await _close(self._control, .5)
        for pipe_task in tuple(self._pipes):
            pipe_task.cancel()
        await asyncio.gather(*tuple(self._pipes), return_exceptions=True)

    async def _run(self):
        failures = 0
        while True:
            code = await self._session()
            if code == "relay_ready":       # a registered session that ended: reconnect quickly
                failures = 0
                code = "relay_unreachable"
            self._set(code)
            delay = self.retry_delays[min(failures, len(self.retry_delays) - 1)]
            if code in ("relay_room_taken", "relay_failed"):
                delay = max(delay, self.retry_delays[-1])
            failures += 1
            await asyncio.sleep(delay)

    async def _session(self):
        writer = None
        try:
            try:
                async with asyncio.timeout(self.connect_timeout):
                    reader, writer = await asyncio.open_connection(self.relay_host, self.relay_port, limit=_CHUNK)
                    self._control = writer
                    writer.write(f"{PROTOCOL} HOST {self.room} {self._token}\n".encode("ascii"))
                    await writer.drain()
                    line = await _read_line(reader, self.connect_timeout)
            except (OSError, TimeoutError):
                return "relay_unreachable"
            except _LineError:
                return "relay_failed"
            if line.startswith("ERR "):
                return {"room_taken": "relay_room_taken", "full": "relay_busy", "busy": "relay_busy"}.get(line[4:], "relay_failed")
            if line != "OK":
                return "relay_failed"
            self._set("relay_ready")
            while True:
                try:
                    line = await _read_line(reader, 120.0)
                except (TimeoutError, _LineError, OSError):
                    return "relay_ready"
                if line == "PING":
                    writer.write(b"PONG\n")
                    await writer.drain()
                elif line.startswith("CONNECT ") and _ID.fullmatch(line[8:]):
                    if len(self._pipes) < self.max_friends:
                        task = asyncio.create_task(self._bridge(line[8:]))
                        self._pipes.add(task)
                        task.add_done_callback(self._pipe_done)
                        self._set("relay_ready")
                else:
                    return "relay_ready"
        finally:
            self._control = None
            await _close(writer, .5)

    def _pipe_done(self, task):
        self._pipes.discard(task)
        if self.status.code == "relay_ready":
            self._set("relay_ready")

    async def _bridge(self, connection_id):
        relay_writer = local_writer = None
        try:
            async with asyncio.timeout(self.connect_timeout):
                relay_reader, relay_writer = await asyncio.open_connection(self.relay_host, self.relay_port, limit=_CHUNK)
                relay_writer.write(f"{PROTOCOL} DATA {self.room} {connection_id}\n".encode("ascii"))
                await relay_writer.drain()
                host, port = self._target()
                local_reader, local_writer = await asyncio.open_connection(host, port, limit=_CHUNK)
                if await _read_line(relay_reader, self.connect_timeout) != "OK":
                    return
            await pipe(relay_reader, relay_writer, local_reader, local_writer, idle_timeout=self.idle_timeout)
        except (OSError, TimeoutError, _LineError, RuntimeError, ValueError, TypeError):
            pass
        finally:
            await _close(relay_writer, .5)
            await _close(local_writer, .5)


# ------------------------------------------------------------------------------------------------------------------------- CLI


def _console():
    """A windowed (frozen) Windows program has no console; open one so the person running the relay can see and stop it."""
    if sys.stdout is not None:
        return
    try:
        import ctypes
        if ctypes.windll.kernel32.AllocConsole():
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")     # noqa: SIM115 - lives for the process
            sys.stderr = sys.stdout
    except Exception:                                                                  # noqa: BLE001 - nowhere to report it
        pass


def _say(text):
    if sys.stdout is not None:
        try:
            print(text, flush=True)
        except (OSError, ValueError):
            pass


async def _serve(args):
    limits = RelayLimits(max_rooms=args.max_rooms, max_connections=args.max_connections,
                         max_per_address=args.max_per_address, idle_timeout=float(args.idle_timeout))
    server = RelayServer(limits)
    await server.start(args.host, args.port)
    host, port = server.address
    _say(f"EmeraldTogether relay listening on {host}:{port} (TCP). Friends and hosts use this PC's reachable address and port {port}.")
    _say("The relay only forwards encrypted game traffic; it cannot read it. Press Ctrl+C or close this window to stop.")
    try:
        await server.serve_forever()
    finally:
        await server.close()


def run_cli(argv=None):
    parser = argparse.ArgumentParser(prog="emerald_multiplayer.relay", description="EmeraldTogether connection relay")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run a relay server")
    serve.add_argument("--host", default="0.0.0.0", help="address to listen on (default: every IPv4 address)")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"TCP port (default {DEFAULT_PORT})")
    serve.add_argument("--max-rooms", type=int, default=RelayLimits.max_rooms)
    serve.add_argument("--max-connections", type=int, default=RelayLimits.max_connections)
    serve.add_argument("--max-per-address", type=int, default=RelayLimits.max_per_address)
    serve.add_argument("--idle-timeout", type=int, default=int(RelayLimits.idle_timeout), help="seconds")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        asyncio.run(_serve(args))
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError) as error:
        _say(f"The relay could not start: {error}")
        return 1
    return 0


def frozen_main(argv):
    """``EmeraldTogether.exe --relay-server [--port N] [--host A] ...``"""
    _console()
    rest = [value for value in argv if value != "--relay-server"]
    code = run_cli(["serve", *rest])
    if code and sys.stdin is not None and sys.stdout is not None:
        try:
            input("Press Enter to close.")
        except (EOFError, OSError, RuntimeError):
            pass
    return code


__all__ = ["DEFAULT_PORT", "RelayAgentStatus", "RelayError", "RelayHostAgent", "RelayLimits", "RelayServer", "frozen_main",
           "open_relay_connection", "pipe", "room_token", "run_cli", "valid_endpoint"]


if __name__ == "__main__":
    sys.exit(run_cli())
