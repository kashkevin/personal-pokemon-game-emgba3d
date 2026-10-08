"""Four-player presence, with opt-in authenticated checkpoints and pinned TLS.

Public transport requires explicit TLS and a durable authenticated world. Checkpoints are ordinary
validated save containers; they are never imported into a running ROM here.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
import ipaddress
import hashlib
import math
from typing import Any, TYPE_CHECKING

from .battle_desk import BattleDesk, BattleError
from .protocol import (
    CHECKPOINT_TYPES, MAX_COUNTER, MAX_FRAME_BYTES, MAX_PLAYERS, PROTOCOL_VERSION, ProtocolError,
    encode_message, read_message, validate_heartbeat, validate_hello,
    validate_identity, validate_presence, validate_checkpoint_common, validate_checkpoint_request,
)
from .storage import StorageError
from .secure_transport import ServerTlsConfig, is_numeric_unicast_address
from .trade_protocol import TRADE_TYPES, validate_trade_common, validate_trade_request
from .team_protocol import TEAM_TYPES, validate_team_common, validate_team_request
from .battle_protocol import BATTLE_TYPES, challenge_view, validate_battle_common, validate_battle_request

if TYPE_CHECKING:
    from .storage import Checkpoint, CheckpointStore, WorldMetadata

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
    checkpoint_upload_timeout: float = 30.0

    def __post_init__(self) -> None:
        validate_identity(self.build_id, "build_id")
        validate_identity(self.ruleset_id, "ruleset_id")
        for name in (
            "heartbeat_interval", "idle_timeout", "presence_timeout",
            "handshake_timeout", "send_timeout", "monitor_interval", "checkpoint_upload_timeout",
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
class CheckpointUpload:
    upload_id: str
    expected_revision: int
    size: int
    sha256: str
    save_profile: str
    last_activity: float
    data: bytearray = field(default_factory=bytearray, repr=False)

    def matches(self, message: dict[str, Any]) -> bool:
        return all(getattr(self, name) == message[name] for name in (
            "expected_revision", "size", "sha256", "save_profile",
        ))


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
    upload: CheckpointUpload | None = field(default=None, repr=False)

    def close(self, reason: str) -> None:
        if not self.closed:
            self.closed = True
            self.close_reason = reason
            self.upload = None
            self.outbox.close()
            self.writer.close()


class _ServerBattleDesk(BattleDesk):
    """Trusted event-loop admission; public requests expose consent only."""

    def __init__(self, server):
        self.server = server
        super().__init__(server.store, server._connected_lease, results=server._battle_results)

    def authorize_bind(self, actor, lease, battle_id, generation):
        # _get authenticates and refreshes without dispatching any command.
        # Preflight and the inherited intent reservation are synchronous, so
        # no checkpoint/trade mutation can interleave between them.
        battle = self._get(actor, lease, battle_id, generation)
        self.server._preflight_battle_bind(battle.players, battle.leases)
        return super().authorize_bind(actor, lease, battle_id, generation)


class WorldServer:
    """Event-loop-owned presence; a supplied store adds durable player leases.

    The caller owns the store and provisions player credentials privately. There
    is no unauthenticated network registration endpoint or public transport mode.
    """

    def __init__(self, config: ServerConfig, *, store: CheckpointStore | None = None,
                 development_trades: bool = False, development_teams: bool = False,
                 development_battles: bool = False) -> None:
        self.config = config
        self.store = store
        self._world_metadata: WorldMetadata | None = None
        if store is not None:
            from .flash import LAYOUT_ID
            from .ownership_protocol import OWNERSHIP_PROFILE
            if store.build_id != config.build_id or store.ruleset_id != config.ruleset_id:
                raise ValueError("checkpoint store must match the server build and ruleset")
            if store.save_profile not in (LAYOUT_ID, OWNERSHIP_PROFILE):
                raise ValueError("checkpoint store save profile has no supported Flash parser")
            if store.save_profile == OWNERSHIP_PROFILE:
                from .ownership_storage import OwnershipCheckpointStore
                if not isinstance(store, OwnershipCheckpointStore):
                    raise ValueError("ownership profile requires an explicit ownership store")
        self.sessions: dict[str, PlayerSession] = {}
        # Explicit opt-in for integration proofs. Native side effects and the
        # cold-start recovery gate must pass before this becomes player-facing.
        self.trade_desk = None
        if type(development_trades) is not bool:
            raise ValueError("development_trades must be a boolean")
        from .trade_desk import TradeDesk
        from .trade_storage import TradeCheckpointStore
        # Existing committed outcomes must remain recoverable even when this
        # host does not permit new trade proposals. Only the authenticated
        # pending/status/ACK routes may use this private recovery desk.
        self._trade_recovery_desk = (TradeDesk(store, self._connected_lease)
            if isinstance(store, TradeCheckpointStore) else None)
        if development_trades:
            if self._trade_recovery_desk is None:
                raise ValueError("development trades require an explicit schema-3 world")
            self.trade_desk = self._trade_recovery_desk
        # Teams are session-local development state, separate from trades and
        # ordinary save profiles. Authentication still requires an owned world.
        self.team_desk = None
        if type(development_teams) is not bool:
            raise ValueError("development_teams must be a boolean")
        if development_teams:
            from .ownership_storage import OwnershipCheckpointStore
            from .team_desk import TeamDesk
            if not isinstance(store, OwnershipCheckpointStore):
                raise ValueError("development teams require an authenticated ownership world")
            self.team_desk = TeamDesk(self._team_roster)
        self.battle_desk = None
        self._battle_results = None
        if type(development_battles) is not bool:
            raise ValueError("development_battles must be a boolean")
        from .ownership_storage import OwnershipCheckpointStore
        if isinstance(store, OwnershipCheckpointStore):
            archive_path = store.path.with_name(store.path.name + ".battle-results.sqlite3")
            if development_battles or archive_path.exists():
                from .battle_results import BattleResults
                self._battle_results = BattleResults(archive_path, world_id=store.metadata.world_id,
                    build_id=store.build_id, ruleset_id=store.ruleset_id)
        if development_battles:
            from .ownership_storage import OwnershipCheckpointStore
            if not isinstance(store, OwnershipCheckpointStore):
                raise ValueError("development native battles require an authenticated ownership world")
            self.battle_desk = _ServerBattleDesk(self)
        self.world_seq = 0
        self._session_epoch = 0
        self._server: asyncio.Server | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._handlers: set[asyncio.Task[None]] = set()
        self._connections: set[asyncio.StreamWriter] = set()
        self._allow_lan = False
        self._public_transport = False
        self._closing = False

    @property
    def address(self) -> tuple[str, int]:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("server is not listening")
        address = self._server.sockets[0].getsockname()
        return address[0], address[1]

    def _connected_lease(self, player_id: str) -> int | None:
        session = self.sessions.get(player_id)
        return session.session_epoch if session is not None and not session.closed else None

    def _preflight_battle_bind(self, players, leases) -> None:
        assert self.store is not None
        for player, lease in zip(players, leases):
            session = self.sessions.get(player)
            if session is None or session.closed or session.session_epoch != lease:
                raise BattleError("stale_lease", "both battle participants must retain their authenticated leases")
            self.store.read_checkpoint(player, lease)
            if session.upload is not None:
                raise BattleError("checkpoint_busy", "finish or abort both participants' checkpoint uploads before native binding")
        if self.trade_desk is not None:
            self.trade_desk._prune()
            if any(set(players).intersection(proposal.players) for proposal in self.trade_desk._proposals.values()):
                raise BattleError("trade_busy", "resolve the participants' trade proposals before native binding")

    def _assert_battle_available(self, *players) -> None:
        if self.battle_desk is None:
            return
        self.battle_desk.refresh()
        # The first authorized BIND reserves both participants, even when its
        # ACK is lost or only one native hold may exist. Retain both through
        # partial abort/release and recovery; only terminal archival frees them.
        if any(battle.bind_intent and set(players).intersection(battle.players)
               for battle in self.battle_desk._active.values()):
            raise ProtocolError("battle_busy", "an unresolved native battle reserves this character's mutations")

    def _team_roster(self) -> dict[str, int]:
        """Bound current connected actors by their actual durable lease."""
        assert self.store is not None
        roster = {}
        for session in self.sessions.values():
            if session.closed:
                continue
            try:
                # A read verifies the lease even when there is no checkpoint.
                self.store.read_checkpoint(session.player_id, session.session_epoch)
            except StorageError as error:
                if error.code == "stale_lease":
                    continue
                raise
            roster[session.player_id] = session.session_epoch
        return roster

    async def start(self, host: str = "127.0.0.1", port: int = 8765, *, allow_lan: bool = False,
                    tls: ServerTlsConfig | None = None, public: bool = False) -> None:
        if self._server is not None:
            raise RuntimeError("server is already started")
        if type(allow_lan) is not bool or type(public) is not bool:
            raise ValueError("transport opt-ins must be booleans")
        if tls is not None and not isinstance(tls, ServerTlsConfig):
            raise ValueError("TLS requires a ServerTlsConfig")
        if public:
            from .storage import CheckpointStore
            if tls is None or not isinstance(self.store, CheckpointStore):
                raise ValueError("public transport requires TLS and a durable authenticated store")
            if not is_numeric_unicast_address(host):
                raise ValueError("public transport requires a specific numeric unicast bind address")
        elif not is_local_address(host, allow_lan):
            raise ValueError("bind a numeric loopback address, or an explicit LAN address with allow_lan; public/wildcard hosting is disabled")
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        self._allow_lan = allow_lan
        self._public_transport = public
        self._closing = False
        tls_options = {} if tls is None else {
            "ssl": tls.build_context(), "ssl_handshake_timeout": tls.handshake_timeout,
            "ssl_shutdown_timeout": tls.shutdown_timeout,
        }
        # Bind first so a failed bind cannot fence a currently serving world.
        listener = await asyncio.start_server(self._accept, host, port, limit=MAX_FRAME_BYTES + 4,
                                             start_serving=False, **tls_options)
        try:
            if self.store is not None:
                self._world_metadata = self.store.begin_server_boot()
            self._server = listener
            await listener.start_serving()
        except BaseException:
            self._server = None
            listener.close()
            await listener.wait_closed()
            raise
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
            peer_allowed = (is_numeric_unicast_address(peer[0]) if self._public_transport
                            else is_local_address(peer[0], self._allow_lan)) if peer else False
            if not peer_allowed:
                await self._reject(writer, "public_exposure_disabled", "this prototype permits local/LAN development only")
                return
            # Bound pre-hello sockets as well as the admitted player count.
            if len(self._connections) > MAX_PLAYERS + 8:
                await self._reject(writer, "connection_limit", "too many pending connections")
                return
            hello = await asyncio.wait_for(read_message(reader), self.config.handshake_timeout)
            if hello is None:
                return
            hello = validate_hello(hello, self.config.build_id, self.config.ruleset_id, require_credential=self.store is not None)
            if self.store is not None:
                credential = bytes.fromhex(hello["credential"])
                player = self.store.authenticate(hello["player_id"], credential)
            if hello["player_id"] in self.sessions:
                await self._reject(writer, "player_already_connected", "this player identity already has a connection")
                return
            if len(self.sessions) >= MAX_PLAYERS:
                await self._reject(writer, "server_full", "the four-player server is full")
                return
            if self.store is not None:
                epoch = self.store.acquire_lease(player.player_id, credential)
                display_name = player.display_name
            else:
                if self._session_epoch >= MAX_COUNTER:
                    await self._reject(writer, "epoch_exhausted", "restart this development server before admitting more sessions")
                    return
                self._session_epoch += 1
                epoch, display_name = self._session_epoch, hello["display_name"]
            now = asyncio.get_running_loop().time()
            session = PlayerSession(
                hello["player_id"], display_name, epoch,
                writer, OutboundQueue(self.config.reliable_limit), now, now, now,
            )
            # Admission has no await between checking and claiming the lease.
            self.sessions[session.player_id] = session
            welcome = {
                "type": "welcome", "protocol": PROTOCOL_VERSION,
                "build_id": self.config.build_id, "ruleset_id": self.config.ruleset_id,
                "player_id": session.player_id, "session_epoch": session.session_epoch,
                "max_players": MAX_PLAYERS,
                "heartbeat_interval": self.config.heartbeat_interval,
                "idle_timeout": self.config.idle_timeout,
            }
            if self.store is not None:
                assert self._world_metadata is not None
                welcome.update({
                    "world_id": self._world_metadata.world_id,
                    "server_epoch": self._world_metadata.server_epoch,
                    "save_profile": self.store.save_profile, "checkpoint_enabled": True,
                })
            self._control(session, welcome)
            session.writer_task = asyncio.create_task(self._write(session), name=f"world-writer-{session.session_epoch}")
            self._broadcast_world()
            while not session.closed:
                message = await read_message(reader)
                if message is None:
                    break
                self._receive(session, message)
        except asyncio.TimeoutError:
            await self._reject(writer, "hello_timeout", "hello was not received in time")
        except (ProtocolError, StorageError) as error:
            await self._reject(writer, error.code, error.message)
        except (ConnectionError, OSError):
            pass
        finally:
            if session is not None:
                session.close("disconnected")
                if self.sessions.get(session.player_id) is session:
                    del self.sessions[session.player_id]
                    if self.team_desk is not None:
                        with suppress(StorageError):
                            self.team_desk.refresh()
                    if not self._closing:
                        self._broadcast_world()
                if self.store is not None:
                    # An older server's cleanup cannot release a newer lease.
                    with suppress(StorageError):
                        self.store.release_lease(session.player_id, session.session_epoch)
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
        elif isinstance(kind, str) and kind in TEAM_TYPES and self.store is not None:
            validate_team_common(message, session.session_epoch)
            try:
                request = validate_team_request(message, session.session_epoch)
                session.last_seen = now
                self._team(session, request)
            except (ProtocolError, StorageError) as error:
                self._team_reply(session, message, error=error)
        elif isinstance(kind, str) and kind in BATTLE_TYPES and self.store is not None:
            validate_battle_common(message, session.session_epoch)
            try:
                request = validate_battle_request(message, session.session_epoch)
                session.last_seen = now
                self._battle_challenge(session, request)
            except (ProtocolError, StorageError) as error:
                self._battle_reply(session, message, error=error)
        elif isinstance(kind, str) and kind in TRADE_TYPES and self.store is not None:
            validate_trade_common(message, session.session_epoch)
            try:
                request = validate_trade_request(message, session.session_epoch)
                session.last_seen = now
                self._trade(session, request)
            except (ProtocolError, StorageError) as error:
                self._trade_reply(session, message, error=error)
        elif isinstance(kind, str) and kind in CHECKPOINT_TYPES and self.store is not None:
            # Invalid lease/correlation fields cannot safely receive an RPC reply.
            validate_checkpoint_common(message, session.session_epoch)
            try:
                request = validate_checkpoint_request(message, session.session_epoch)
                session.last_seen = now
                self._checkpoint(session, request, now)
            except (ProtocolError, StorageError) as error:
                self._checkpoint_error(session, message, error.code, error.message)
        else:
            raise ProtocolError("invalid_type", "message type is unsupported")

    @staticmethod
    def _checkpoint_metadata(checkpoint: Checkpoint | None) -> dict[str, Any] | None:
        if checkpoint is None:
            return None
        return {
            "revision": checkpoint.revision, "request_id": checkpoint.request_id,
            "size": len(checkpoint.payload), "sha256": checkpoint.sha256,
            "build_id": checkpoint.build_id, "ruleset_id": checkpoint.ruleset_id,
            "save_profile": checkpoint.save_profile,
        }

    def _team_reply(self, session, request, *, error=None, result=None):
        assert self._world_metadata is not None
        self._control(session, dict(
            type="team_error" if error is not None else "team_result",
            protocol=PROTOCOL_VERSION, session_epoch=session.session_epoch,
            request_id=request["request_id"], operation=request["type"].removeprefix("team_"),
            world_id=self._world_metadata.world_id, player_id=session.player_id,
            **({"code": error.code, "message": error.message} if error is not None else {"result": result})))

    def _team(self, session, request):
        if self.team_desk is None:
            raise ProtocolError("team_disabled", "this development world has not enabled teams")
        desk, actor = self.team_desk, (session.player_id, session.session_epoch)
        operation = request["type"].removeprefix("team_")
        if operation == "invite":
            result = desk.invite(*actor, request["peer"], request["invitation_id"])
        elif operation == "leave":
            result = desk.leave(*actor, request["team_id"], request["generation"])
        elif operation == "status":
            result = desk.status(*actor)
        else:
            result = getattr(desk, operation)(*actor, request["invitation_id"], request["generation"])
        self._team_reply(session, request, result=result)

    def _battle_reply(self, session, request, *, error=None, result=None):
        assert self._world_metadata is not None
        self._control(session, dict(
            type="battle_error" if error is not None else "battle_result",
            protocol=PROTOCOL_VERSION, session_epoch=session.session_epoch,
            request_id=request["request_id"], operation=request["type"].removeprefix("battle_"),
            world_id=self._world_metadata.world_id, player_id=session.player_id,
            **({"code": error.code, "message": error.message} if error is not None else {"result": result})))

    def _battle_challenge(self, session, request):
        # Public consent never authorizes BIND/START, supplies native receipts,
        # or claims a winner. Those remain trusted coordinator operations.
        operation = request["type"].removeprefix("battle_")
        if operation == "history":
            from .ownership_storage import OwnershipCheckpointStore
            if not isinstance(self.store, OwnershipCheckpointStore):
                raise ProtocolError("battle_disabled", "battle history requires an authenticated ownership world")
            self.store.read_checkpoint(session.player_id, session.session_epoch)
            if self._connected_lease(session.player_id) != session.session_epoch:
                raise ProtocolError("stale_lease", "battle history requires the current authenticated player")
            self._battle_reply(session, request, result=[] if self._battle_results is None
                else self._battle_results.history(session.player_id))
            return
        if self.battle_desk is None:
            raise ProtocolError("battle_disabled", "this development world has not enabled battle challenges")
        desk, actor = self.battle_desk, (session.player_id, session.session_epoch)
        if operation == "pending":
            result = [challenge_view(view) for view in desk.pending(*actor)]
        else:
            battle_id = request["battle_id"]
            if operation == "invite":
                view = desk.invite(*actor, request["peer"], battle_id)
            elif operation == "invite_multi":
                view = desk.invite_multi(*actor, request["teammate"], tuple(request["opponents"]), battle_id)
            elif operation == "status":
                view = desk.status(*actor, battle_id)
            elif operation == "accept":
                view = desk.accept(*actor, battle_id, request["generation"], request["fingerprint"])
            else:
                view = desk.cancel(*actor, battle_id, request["generation"])
            result = challenge_view(view)
        self._battle_reply(session, request, result=result)

    def _trade_reply(self, session, request, *, error=None, **fields):
        assert self._world_metadata is not None
        self._control(session, dict(
            type="trade_error" if error is not None else "trade_result",
            protocol=PROTOCOL_VERSION, session_epoch=session.session_epoch,
            request_id=request["request_id"], operation=request["type"].removeprefix("trade_"),
            world_id=self._world_metadata.world_id, player_id=session.player_id,
            **({"code": error.code, "message": error.message} if error is not None else fields)))

    def _trade(self, session, request):
        kind = request["type"].removeprefix("trade_")
        desk = self.trade_desk
        if desk is None:
            if kind not in {"pending", "status", "ack"} or self._trade_recovery_desk is None:
                raise ProtocolError("trade_disabled", "this development world has not enabled new trade operations")
            desk = self._trade_recovery_desk
        actor = (session.player_id, session.session_epoch)
        if kind not in {"status", "pending"}:
            players = [session.player_id]
            if kind == "open":
                players.append(request["peer"])
            else:
                proposal = desk._proposals.get(request["transaction_id"])
                if proposal is not None:
                    players.extend(proposal.players)
            self._assert_battle_available(*players)
        if kind == "pending":
            self._trade_reply(session, request, recoveries=[dict(
                transaction_id=r.transaction_id, sequence=r.sequence,
                outcome_fingerprint=r.outcome_fingerprint,
                checkpoint=self._checkpoint_metadata(r.checkpoint))
                for r in desk.store.pending_trade_recovery(*actor)])
            return
        txid = request["transaction_id"]
        if kind == "ack":
            desk.store.acknowledge_trade(*actor, txid, request["revision"], request["sha256"])
            result = dict(transaction_id=txid, state="acknowledged",
                          revision=request["revision"], sha256=request["sha256"])
        elif kind == "open":
            result = desk.open(*actor, request["peer"], txid)
        elif kind == "offer":
            result = desk.offer(*actor, txid, request["generation"], request["revision"],
                                request["sha256"], request["serial"])
        elif kind == "confirm":
            result = desk.confirm(*actor, txid, request["generation"], request["fingerprint"])
        elif kind == "cancel":
            result = desk.cancel(*actor, txid, request["generation"])
        else:
            result = desk.status(*actor, txid)
        self._trade_reply(session, request, trade=result)

    def _checkpoint_reply(self, session: PlayerSession, request: dict[str, Any], **fields: Any) -> None:
        self._control(session, {
            "type": "checkpoint_result", "protocol": PROTOCOL_VERSION,
            "session_epoch": session.session_epoch, "request_id": request["request_id"],
            "operation": request["type"].removeprefix("checkpoint_"), **fields,
        })

    def _checkpoint_error(self, session: PlayerSession, request: dict[str, Any], code: str, message: str) -> None:
        self._control(session, {
            "type": "checkpoint_error", "protocol": PROTOCOL_VERSION,
            "session_epoch": session.session_epoch, "request_id": request["request_id"],
            "operation": request["type"].removeprefix("checkpoint_"),
            "code": code, "message": message,
        })

    def _committed_retry(self, session: PlayerSession, request: dict[str, Any], upload_id: str) -> Checkpoint | None:
        """Find the exact historic transaction, never a superficially equal head."""
        assert self.store is not None
        if request["expected_revision"] >= MAX_COUNTER:
            return None
        checkpoint = self.store.read_checkpoint(session.player_id, session.session_epoch, revision=request["expected_revision"] + 1)
        if checkpoint is None or checkpoint.request_id != upload_id:
            return None
        if (checkpoint.sha256 != request["sha256"] or len(checkpoint.payload) != request["size"]
                or checkpoint.save_profile != request["save_profile"]
                or checkpoint.build_id != self.config.build_id or checkpoint.ruleset_id != self.config.ruleset_id):
            raise ProtocolError("request_conflict", "the committed upload has a different fingerprint")
        return checkpoint

    def _checkpoint(self, session: PlayerSession, request: dict[str, Any], now: float) -> None:
        """One bounded, stop-and-wait operation; commit is durable before ACK."""
        assert self.store is not None
        kind = request["type"]
        if kind not in {"checkpoint_info", "checkpoint_read"}:
            self._assert_battle_available(session.player_id)
        if kind == "ownership_grant":
            from dataclasses import asdict
            from .ownership_storage import OwnershipCheckpointStore
            if not isinstance(self.store, OwnershipCheckpointStore):
                raise ProtocolError("ownership_disabled", "this world has no ownership allocation profile")
            grant = self.store.reserve_instances(session.player_id, session.session_epoch, request["request_id"],
                request["expected_revision"], request["incarnation"], request["count"])
            self._checkpoint_reply(session, request, checkpoint=None, grant=asdict(grant))
            return
        if kind == "checkpoint_info":
            checkpoint = self.store.read_checkpoint(session.player_id, session.session_epoch)
            self._checkpoint_reply(session, request, checkpoint=self._checkpoint_metadata(checkpoint))
            return
        if kind == "checkpoint_read":
            checkpoint = self.store.read_checkpoint(session.player_id, session.session_epoch)
            if checkpoint is None or checkpoint.revision != request["expected_revision"]:
                raise ProtocolError("revision_conflict", "checkpoint head changed; request its metadata again")
            offset = request["offset"]
            if offset >= len(checkpoint.payload):
                raise ProtocolError("invalid_checkpoint_offset", "read offset must select bytes within the checkpoint")
            data = checkpoint.payload[offset:offset + request["length"]]
            self._checkpoint_reply(session, request, checkpoint=self._checkpoint_metadata(checkpoint),
                                   offset=offset,
                                   data_b64=base64.b64encode(data).decode("ascii"),
                                   eof=offset + len(data) == len(checkpoint.payload))
            return
        if kind in ("checkpoint_begin", "checkpoint_commit"):
            if request["save_profile"] != self.store.save_profile:
                raise ProtocolError("save_profile_mismatch", "checkpoint save profile is incompatible")
            if request["size"] > self.store.max_payload_bytes:
                raise ProtocolError("invalid_checkpoint_size", "checkpoint exceeds this world's payload limit")
        if kind == "checkpoint_begin":
            upload_id = request["request_id"]
            committed = self._committed_retry(session, request, upload_id)
            if committed is not None:
                self._checkpoint_reply(session, request, checkpoint=self._checkpoint_metadata(committed),
                                       upload_id=upload_id, next_offset=request["size"])
                return
            checkpoint = self.store.read_checkpoint(session.player_id, session.session_epoch)
            if request["expected_revision"] != (checkpoint.revision if checkpoint is not None else 0):
                raise ProtocolError("revision_conflict", "checkpoint head changed; this upload cannot replace it")
            if session.upload is not None:
                if session.upload.upload_id != upload_id:
                    raise ProtocolError("upload_active", "this player already has an active upload")
                if not session.upload.matches(request):
                    raise ProtocolError("request_conflict", "upload ID was reused with a different fingerprint")
                session.upload.last_activity = now
            else:
                session.upload = CheckpointUpload(upload_id, request["expected_revision"], request["size"],
                                                 request["sha256"], request["save_profile"], now)
            self._checkpoint_reply(session, request, checkpoint=self._checkpoint_metadata(checkpoint),
                                   upload_id=upload_id, next_offset=len(session.upload.data))
            return
        if kind == "checkpoint_abort":
            if session.upload is not None and session.upload.upload_id != request["upload_id"]:
                raise ProtocolError("upload_not_found", "that upload does not own this player's staging buffer")
            session.upload = None
            self._checkpoint_reply(session, request, checkpoint=None, upload_id=request["upload_id"])
            return
        upload = session.upload
        if upload is None or upload.upload_id != request["upload_id"]:
            if kind == "checkpoint_commit":
                checkpoint = self._committed_retry(session, request, request["upload_id"])
                if checkpoint is not None:
                    # The store checks the fresh lease and all exact retry bindings.
                    checkpoint = self.store.commit_checkpoint(
                        session.player_id, session.session_epoch, checkpoint.request_id,
                        request["expected_revision"], checkpoint.payload,
                        self.config.build_id, self.config.ruleset_id, self.store.save_profile,
                    )
                    self._checkpoint_reply(session, request, checkpoint=self._checkpoint_metadata(checkpoint),
                                           upload_id=request["upload_id"])
                    return
            raise ProtocolError("upload_not_found", "upload has expired, disconnected, or was never begun")
        if kind == "checkpoint_chunk":
            # No per-chunk metadata: even hostile one-byte chunks use bounded memory.
            offset, data = request["offset"], request["data"]
            end = offset + len(data)
            if end > upload.size:
                raise ProtocolError("invalid_checkpoint_offset", "chunk exceeds the declared checkpoint size")
            if offset == len(upload.data):
                upload.data.extend(data)
            elif end <= len(upload.data) and upload.data[offset:end] == data:
                pass  # Exact already-ACKed chunk retry.
            else:
                raise ProtocolError("checkpoint_offset_conflict", "chunks must be sequential or exact duplicates")
            upload.last_activity = now
            self._checkpoint_reply(session, request, checkpoint=None, upload_id=upload.upload_id, next_offset=len(upload.data))
            return
        if not upload.matches(request):
            raise ProtocolError("request_conflict", "commit fingerprint differs from the begun upload")
        if len(upload.data) != upload.size:
            raise ProtocolError("upload_incomplete", "checkpoint upload is incomplete")
        payload = bytes(upload.data)
        if hashlib.sha256(payload).hexdigest() != upload.sha256:
            session.upload = None
            raise ProtocolError("checkpoint_hash_mismatch", "uploaded bytes do not match their declared SHA256")
        from .flash import FlashError, inspect_flash
        previous = self.store.read_checkpoint(session.player_id, session.session_epoch)
        try:
            trainer_id = inspect_flash(previous.payload, save_profile=self.store.save_profile).metadata.trainer_id if previous is not None else None
            snapshot = inspect_flash(payload, expected_trainer_id=trainer_id, save_profile=self.store.save_profile)
        except FlashError as error:
            session.upload = None
            raise ProtocolError("invalid_checkpoint", "Flash is invalid or belongs to a different trainer") from error
        # No await separates validation, transaction commit, and clearing staging.
        checkpoint = self.store.commit_checkpoint(
            session.player_id, session.session_epoch, upload.upload_id,
            upload.expected_revision, snapshot.container,
            self.config.build_id, self.config.ruleset_id, upload.save_profile,
        )
        session.upload = None
        self._checkpoint_reply(session, request, checkpoint=self._checkpoint_metadata(checkpoint),
                               upload_id=upload.upload_id)

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
            if self.battle_desk is not None:
                self.battle_desk.refresh()
            changed = False
            for session in tuple(self.sessions.values()):
                if session.closed:
                    continue
                if session.upload is not None and now - session.upload.last_activity >= self.config.checkpoint_upload_timeout:
                    session.upload = None
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
