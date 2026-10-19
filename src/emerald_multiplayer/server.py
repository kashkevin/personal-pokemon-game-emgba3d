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
import time
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from .battle_desk import BattleDesk, BattleError
from .shared_world_protocol import WORLD_TYPES, validate_world_request
from . import privacy
from .protocol import (
    CHECKPOINT_TYPES, MAX_COUNTER, MAX_FRAME_BYTES, MAX_PLAYERS, PROTOCOL_VERSION, ProtocolError,
    encode_message, read_message, validate_heartbeat, validate_hello,
    validate_identity, validate_presence, validate_checkpoint_common, validate_checkpoint_request,
)
from .storage import StorageError
from .secure_transport import ServerTlsConfig, is_numeric_unicast_address
from .trade_protocol import TRADE_TYPES, validate_trade_common, validate_trade_request
from .enrollment_protocol import ENROLLMENT_TYPES, validate_enrollment_common, validate_enrollment_request
from .team_protocol import TEAM_TYPES, validate_team_common, validate_team_request
from .battle_protocol import BATTLE_TYPES, challenge_view, validate_battle_common, validate_battle_request
from .reset_protocol import RESET_TYPES, validate_reset_common, validate_reset_request

if TYPE_CHECKING:
    from .storage import Checkpoint, CheckpointStore, WorldMetadata

# A world open to the local network also accepts 100.64.0.0/10. Overlay VPNs (Tailscale and similar) number their members there
# and admit only devices their owner authorised, which is the same trust as the home network. The address is not what admits a
# player: the TLS host identity and the player's credential still decide that. Other public addresses still need Internet access.
_LAN_NETWORKS = tuple(ipaddress.ip_network(network) for network in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7", "100.64.0.0/10",
))
WILDCARD = "0.0.0.0"


def is_local_address(value: str, allow_lan: bool = False) -> bool:
    """Allow loopback, plus explicit RFC1918/ULA/overlay (100.64.0.0/10) addresses when the world is open to the network."""
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
    allow_enrollment: bool = True   # friends may send their New Game save to enroll themselves (enrollment_protocol.py)

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
        if type(self.allow_enrollment) is not bool:
            raise ValueError("allow_enrollment must be a boolean")


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
    mode: str = "enroll"           # enrollment uploads: "enroll" or "transfer" (character_transfers.py)

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
    enrollment_upload: CheckpointUpload | None = field(default=None, repr=False)

    def close(self, reason: str) -> None:
        if not self.closed:
            self.closed = True
            self.close_reason = reason
            self.upload = None
            self.enrollment_upload = None
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
        if self.server.battle_execution is not None:
            self.server.battle_execution.admission.assert_not_canceled(battle_id)
        self.server._preflight_battle_bind(battle.players, battle.leases)
        return super().authorize_bind(actor, lease, battle_id, generation)


class WorldServer:
    """Event-loop-owned presence; a supplied store adds durable player leases.

    The caller owns the store and provisions player credentials privately. There
    is no unauthenticated network registration endpoint or public transport mode.
    """

    def __init__(self, config: ServerConfig, *, store: CheckpointStore | None = None,
                 development_trades: bool = False, development_teams: bool = False,
                 development_battles: bool = False, trade_effect_adapter=None,
                 trade_effect_policy=None) -> None:
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
        from .reset_attempts import ResetAttempts
        self._reset_attempts = ResetAttempts(store) if store is not None and store.reset_attempts_enabled else None
        # The launcher enables only the qualified native/menu/ownership path.
        # Recipient preparation preserves eligible exact swaps; unsupported
        # native evolution, friendship, egg and mail effects remain refused.
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
        self.trade_effects = None
        if trade_effect_adapter is not None:
            if self._trade_recovery_desk is None:
                raise ValueError("native effects require an owned paired-trade world")
            from .trade_effect_backend import TradeEffectsBackend
            self.trade_effects = TradeEffectsBackend(self._trade_recovery_desk, trade_effect_adapter, trade_effect_policy)
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
        self.battle_execution = None
        self._battle_results = None
        self._championships = None
        self._rivals = None  # Update 31: world-level rival checkpoints (rival_checkpoints.py)
        # Update 31: rival battles name their checkpoint's battle environment in the native preparation, only when the
        # host's installed game says every core of this world's build reads it (manifest rival_abi_version 1).
        self._rival_battle_environment = False
        self._last_frontier_tick = 0.0
        from .frontier_rules import FrontierSettings
        self._frontier = (FrontierSettings.load(store.path.with_name(store.path.name + ".frontier.json"))
                          if store is not None else FrontierSettings())
        from .battle_reservations import BattleReservations
        self._battle_reservations = (BattleReservations(store)
            if store is not None and store.battle_reservations_enabled else None)
        if self._battle_reservations is not None:
            # Refuse a corrupt persisted barrier before opening a listener,
            # including hosts that have disabled new battle challenges.
            store.integrity_check()
        if type(development_battles) is not bool:
            raise ValueError("development_battles must be a boolean")
        from .ownership_storage import OwnershipCheckpointStore
        if isinstance(store, OwnershipCheckpointStore):
            archive_path = store.path.with_name(store.path.name + ".battle-results.sqlite3")
            championship_path = store.path.with_name(store.path.name + ".championships.sqlite3")
            rival_path = store.path.with_name(store.path.name + ".rival-checkpoints.sqlite3")
            if development_battles or archive_path.exists() or championship_path.exists() or rival_path.exists():
                from .battle_results import BattleResults
                self._battle_results = BattleResults(archive_path, world_id=store.metadata.world_id,
                    build_id=store.build_id, ruleset_id=store.ruleset_id)
            if development_battles or championship_path.exists():
                from .championship import Championships
                self._championships = Championships(championship_path, world_id=store.metadata.world_id,
                    build_id=store.build_id, ruleset_id=store.ruleset_id)
            if development_battles or rival_path.exists():
                from .rival_checkpoints import RivalCheckpoints
                self._rivals = RivalCheckpoints(rival_path, world_id=store.metadata.world_id,
                    build_id=store.build_id, ruleset_id=store.ruleset_id)
        if development_battles:
            from .ownership_storage import OwnershipCheckpointStore
            if not isinstance(store, OwnershipCheckpointStore):
                raise ValueError("development native battles require an authenticated ownership world")
            if self._battle_reservations is None:
                raise StorageError("battle_migration_required", "enable backed-up durable reservations before native battles")
            self.battle_desk = _ServerBattleDesk(self)
        # Shared-world state (clock, appearances, World Events, notices).
        from .shared_world import SharedWorld
        from .friendship import FriendshipStore
        from .wagers import Wagers
        if store is not None:
            world_path = store.path.with_name(store.path.name + ".shared-world.sqlite3")
            from .outbreaks import load_outbreak_settings
            from .event_settings import load_event_settings
            self.shared_world = SharedWorld(world_path, store.metadata.world_id, outbreak_settings=load_outbreak_settings(
                store.path.with_name(store.path.name + ".outbreaks.json")),
                event_settings=load_event_settings(store.path.with_name(store.path.name + ".events.json")))
            self.friendships = FriendshipStore(store.path.with_name(store.path.name + ".friendships.sqlite3"),
                                               store.metadata.world_id)
            self.wagers = Wagers(store.path.with_name(store.path.name + ".wagers.sqlite3"), store.metadata.world_id)
        else:
            self.shared_world = SharedWorld(":memory:", "00000000-0000-0000-0000-000000000000")
            self.friendships = FriendshipStore(":memory:", "00000000-0000-0000-0000-000000000000")
            self.wagers = Wagers(":memory:", "00000000-0000-0000-0000-000000000000")
        self.shared_world.on_event_finished = self._on_event_finished
        if self._trade_recovery_desk is not None:
            self._trade_recovery_desk.on_commit = self._on_trade_committed
        if self.trade_effects is not None:
            self.trade_effects.lucky_decider = self._decide_lucky_trade
            self.trade_effects.on_commit = self._on_trade_committed
        if self.battle_desk is not None:
            self.battle_desk.on_closed = self._on_battle_closed
            self.battle_desk.on_publish = self._on_battle_publish
            self.battle_desk.on_aborted = self._on_battle_aborted
            self.battle_desk.start_gate = self._wager_gate
        self._last_friendship_tick = time.monotonic()
        self._last_clock_broadcast = 0.0
        self.world_seq = 0
        self._session_epoch = 0
        self._server: asyncio.Server | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._handlers: set[asyncio.Task[None]] = set()
        self._connections: set[asyncio.StreamWriter] = set()
        self._allow_lan = False
        self._public_transport = False
        self._closing = False
        self._relay_server: asyncio.Server | None = None

    @property
    def relay_address(self) -> tuple[str, int]:
        """Where the host's relay agent delivers relayed connections (loopback; only with ``start(relay=True)``)."""
        if self._relay_server is None or not self._relay_server.sockets:
            raise RuntimeError("relayed connections are not enabled")
        address = self._relay_server.sockets[0].getsockname()
        return address[0], address[1]

    @property
    def address(self) -> tuple[str, int]:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("server is not listening")
        address = self._server.sockets[0].getsockname()
        return address[0], address[1]

    def _connected_lease(self, player_id: str) -> int | None:
        session = self.sessions.get(player_id)
        return session.session_epoch if session is not None and not session.closed else None

    def enable_battle_execution(self, string_lengths, directory, *, resume_enabled=False):
        """Application-only setup using the installed, hash-verified ROM table."""
        if self.battle_execution is not None or self._server is not None:
            raise ValueError("configure native execution once before starting the host")
        from .battle_execution import BattleExecutionService
        self.battle_execution = BattleExecutionService(self.battle_desk, string_lengths, directory,
                                                       resume_enabled=resume_enabled)

    def enable_rival_battle_environment(self):
        """Application-only: the installed, hash-verified game reads a rival battle's environment (rival_abi_version 1).

        Every player of a world runs the same build (hello build_id), so the host's own manifest speaks for every core.
        """
        if self._server is not None:
            raise ValueError("configure rival battles before starting the host")
        self._rival_battle_environment = True

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
        if self._battle_reservations is not None:
            self._battle_reservations.assert_available(*players)
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

    @property
    def is_serving(self):
        """Whether this service still owns its active listener and heartbeat."""
        return (not self._closing and self._server is not None and self._server.is_serving()
                and self._monitor_task is not None and not self._monitor_task.done())

    async def start(self, host: str = "127.0.0.1", port: int = 8765, *, allow_lan: bool = False,
                    tls: ServerTlsConfig | None = None, public: bool = False, wildcard: bool = False,
                    relay: bool = False) -> None:
        """Listen on ``host:port``. ``wildcard=True`` with host "0.0.0.0" listens on every IPv4 interface (router forwards and VPN
        adapters reach it); like ``public`` it requires TLS and a durable authenticated store, and the peer filter is unchanged:
        local network and overlay peers with ``allow_lan``, any unicast peer only with ``public``. ``relay=True`` adds a
        loopback-only listener (``relay_address``) for connections the host's relay agent carries; they are TLS-authenticated
        exactly like direct ones."""
        if self._server is not None:
            raise RuntimeError("server is already started")
        if type(allow_lan) is not bool or type(public) is not bool or type(wildcard) is not bool or type(relay) is not bool:
            raise ValueError("transport opt-ins must be booleans")
        if tls is not None and not isinstance(tls, ServerTlsConfig):
            raise ValueError("TLS requires a ServerTlsConfig")
        if public or wildcard or relay:
            from .storage import CheckpointStore
            if tls is None or not isinstance(self.store, CheckpointStore):
                raise ValueError("public, wildcard and relayed transport require TLS and a durable authenticated store")
        if wildcard:
            if host != WILDCARD or not (public or allow_lan):
                raise ValueError("a wildcard listener is the IPv4 any-address and needs the world open to the network")
        elif public:
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
        relay_listener = None
        if relay:
            try:
                relay_listener = await asyncio.start_server(self._accept_relayed, "127.0.0.1", 0, limit=MAX_FRAME_BYTES + 4,
                                                            start_serving=False, **tls_options)
            except BaseException:
                listener.close()
                await listener.wait_closed()
                raise
        try:
            if self.store is not None:
                self._world_metadata = self.store.begin_server_boot()
                if self.store.trade_effects_enabled and self.trade_effects is None:
                    raise StorageError("trade_effect_replay_required", "this effect-enabled world requires its pinned native worker")
            if self.trade_effects is not None:
                await self.trade_effects.start()
            self._server = listener
            await listener.start_serving()
            if relay_listener is not None:
                self._relay_server = relay_listener
                await relay_listener.start_serving()
        except BaseException:
            self._server = None
            self._relay_server = None
            listener.close()
            await listener.wait_closed()
            if relay_listener is not None:
                relay_listener.close()
                await relay_listener.wait_closed()
            if self.trade_effects is not None:
                await self.trade_effects.close()
            raise
        self._monitor_task = asyncio.create_task(self._monitor(), name="world-heartbeat")

    async def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("server is not started")
        await self._server.serve_forever()

    async def close(self) -> None:
        self._closing = True
        if self.trade_effects is not None:
            await self.trade_effects.close()
        if self.battle_execution is not None:
            await self.battle_execution.close()
        listening_server = self._server
        relay_server, self._relay_server = self._relay_server, None
        if relay_server is not None:
            relay_server.close()
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            # A crashed heartbeat is one reason a surviving launcher needs to
            # restart this service. Its old failure must not strand accepted
            # connections and the store owner on every subsequent close.
            await asyncio.gather(self._monitor_task, return_exceptions=True)
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
        if relay_server is not None:
            await relay_server.wait_closed()
        self.shared_world.close()
        self.friendships.close()
        self.wagers.close()

    async def _reject(self, writer: asyncio.StreamWriter, code: str, message: str) -> None:
        try:
            writer.write(encode_message({"type": "error", "protocol": PROTOCOL_VERSION, "code": code, "message": message}))
            await asyncio.wait_for(writer.drain(), timeout=self.config.send_timeout)
        except (ConnectionError, OSError, asyncio.TimeoutError):
            pass

    def peer_allowed(self, address: str | None, *, relayed: bool = False) -> bool:
        """Who may open a connection (TLS and the player's credential are still required afterwards).

        Direct: loopback always; the local network and overlay VPNs (RFC1918, ULA, 100.64.0.0/10) when the world is open to the
        network; any unicast address only when the world allows Internet connections. Relayed: only the host's own relay agent
        on loopback, and only while relayed connections are enabled (the listener exists only then)."""
        if address is None:
            return False
        if relayed:
            return self._relay_server is not None and is_local_address(address)
        if self._public_transport:
            return is_numeric_unicast_address(address)
        return is_local_address(address, self._allow_lan)

    async def _accept_relayed(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await self._accept(reader, writer, relayed=True)

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, relayed: bool = False) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._handlers.add(task)
        self._connections.add(writer)
        session: PlayerSession | None = None
        try:
            peer = writer.get_extra_info("peername")
            if self._closing:
                return
            if not self.peer_allowed(peer[0] if peer else None, relayed=relayed):
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
            self.shared_world.set_active_players(len(self.sessions))
            self.shared_world.player_connected(session.player_id)
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
                    self.shared_world.player_disconnected(session.player_id)
                    self.shared_world.set_active_players(len(self.sessions))
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
        elif isinstance(kind, str) and kind in WORLD_TYPES:
            request = validate_world_request(message, session.session_epoch)
            session.last_seen = now
            self._shared_world_request(session, request)
        elif isinstance(kind, str) and kind in RESET_TYPES and self.store is not None:
            validate_reset_common(message, session.session_epoch)
            try:
                request = validate_reset_request(message, session.session_epoch)
                session.last_seen = now
                if self._reset_attempts is None:
                    raise ProtocolError("reset_disabled", "this world has not enabled durable personal encounters")
                self._assert_battle_available(session.player_id)
                if session.upload is not None:
                    raise ProtocolError("checkpoint_busy", "finish the checkpoint before starting an encounter")
                if self.trade_desk is not None:
                    self.trade_desk._prune()
                    if any(session.player_id in proposal.players for proposal in self.trade_desk._proposals.values()):
                        raise ProtocolError("trade_busy", "resolve the trade proposal before starting an encounter")
                result = self._reset_attempts.begin(session.player_id, session.session_epoch, request)
                self._reset_reply(session, message, result=result)
            except (ProtocolError, StorageError) as error:
                self._reset_reply(session, message, error=error)
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
        elif isinstance(kind, str) and kind in ENROLLMENT_TYPES and self.store is not None:
            validate_enrollment_common(message, session.session_epoch)
            try:
                request = validate_enrollment_request(message, session.session_epoch)
                session.last_seen = now
                self._enrollment(session, request, now)
            except (ProtocolError, StorageError) as error:
                self._enrollment_reply(session, message, error=error)
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

    def _enrollment_reply(self, session, request, *, error=None, **fields):
        base = dict(protocol=PROTOCOL_VERSION, session_epoch=session.session_epoch, request_id=request["request_id"],
                    operation=request["type"].removeprefix("enrollment_"))
        if error is not None:
            self._control(session, dict(base, type="enrollment_error", code=error.code, message=error.message))
        else:
            self._control(session, dict(base, type="enrollment_result", **fields))

    def _enrollment(self, session, request, now):
        """A friend enrolls their own New Game save (enrollment_protocol.py). Everything is decided here, on the host."""
        from .ownership_storage import OwnershipCheckpointStore
        store = self.store
        if not isinstance(store, OwnershipCheckpointStore):
            raise ProtocolError("enrollment_unsupported", "this world cannot enroll characters over the network")
        if not self.config.allow_enrollment:
            raise ProtocolError("enrollment_disabled", "the host has turned off creating new characters over the network")
        from .character_transfers import pending_source, transfer_player
        kind = request["type"]
        head = store.read_checkpoint(session.player_id, session.session_epoch)
        enrolled = store.has_enrollment(session.player_id)
        state = "checkpointed" if head is not None else "enrolled" if enrolled else "open"
        transfers = bool(getattr(store, "character_transfers_enabled", False))
        if kind == "enrollment_status":
            pending = pending_source(store, session.player_id)
            wagers = getattr(self, "wagers", None)
            wallet = wagers.applied_seq(session.player_id) if wagers is not None and hasattr(wagers, "applied_seq") else 0
            self._enrollment_reply(session, request, state=state, revision=head.revision if head is not None else 0,
                                   pending=pending[0] if pending else None, pending_sha256=pending[2] if pending else None,
                                   wallet_seq=wallet, transfers=transfers)
            return
        # Chunks carry no mode: they belong to the upload its begin opened (and the commit must name the same mode).
        mode = request.get("mode", "enroll") if kind != "enrollment_chunk" else getattr(session.enrollment_upload, "mode", "enroll")
        if mode == "enroll" and head is not None:
            raise ProtocolError("already_enrolled", "this account already has a character")
        if mode == "transfer":
            if not transfers:
                raise ProtocolError("transfer_unsupported", "the host's world cannot take a character back yet; the host must update")
            if head is None:
                raise ProtocolError("enrollment_required", "this account has no character yet; enroll it instead")
        if kind == "enrollment_begin":
            upload_id = request["request_id"]
            if session.enrollment_upload is not None and session.enrollment_upload.upload_id != upload_id:
                raise ProtocolError("upload_active", "this player already has an enrollment upload in progress")
            if session.enrollment_upload is None:
                from .flash import LAYOUT_ID
                session.enrollment_upload = CheckpointUpload(upload_id, 0, request["size"], request["sha256"], LAYOUT_ID, now)
                session.enrollment_upload.mode = mode
            elif getattr(session.enrollment_upload, "mode", "enroll") != mode:
                raise ProtocolError("request_conflict", "upload ID was reused with a different mode")
            elif (session.enrollment_upload.size, session.enrollment_upload.sha256) != (request["size"], request["sha256"]):
                raise ProtocolError("request_conflict", "upload ID was reused with a different fingerprint")
            session.enrollment_upload.last_activity = now
            self._enrollment_reply(session, request, state=state, upload_id=upload_id,
                                   next_offset=len(session.enrollment_upload.data))
            return
        upload = session.enrollment_upload
        if upload is None or upload.upload_id != request["upload_id"]:
            raise ProtocolError("upload_not_found", "no enrollment upload is open")
        if kind == "enrollment_chunk":
            offset, data = request["offset"], request["data"]
            end = offset + len(data)
            if end > upload.size:
                raise ProtocolError("invalid_checkpoint_offset", "chunk exceeds the declared size")
            if offset == len(upload.data):
                upload.data.extend(data)
            elif not (end <= len(upload.data) and upload.data[offset:end] == data):
                raise ProtocolError("checkpoint_offset_conflict", "chunks must be sequential or exact duplicates")
            upload.last_activity = now
            self._enrollment_reply(session, request, state=state, upload_id=upload.upload_id, next_offset=len(upload.data))
            return
        # enrollment_commit
        if getattr(upload, "mode", "enroll") != mode:
            raise ProtocolError("request_conflict", "commit mode differs from the begun upload")
        if (request["size"], request["sha256"]) != (upload.size, upload.sha256):
            raise ProtocolError("request_conflict", "commit fingerprint differs from the begun upload")
        if len(upload.data) != upload.size:
            raise ProtocolError("upload_incomplete", "the enrollment upload is incomplete")
        payload = bytes(upload.data)
        session.enrollment_upload = None
        if hashlib.sha256(payload).hexdigest() != upload.sha256:
            raise ProtocolError("checkpoint_hash_mismatch", "uploaded bytes do not match their declared SHA256")
        if mode == "transfer":
            transfer = transfer_player(store, session.player_id, payload)
            self._enrollment_reply(session, request, state="transferred", upload_id=upload.upload_id,
                                   source_sha256=transfer.source_sha256, base_revision=transfer.base_revision)
            return
        # A first source that never reached its first checkpoint is replaced by a retry (another or a newer character).
        enrollment = store.enroll_player(session.player_id, payload, replace_unconsumed=True)
        self._enrollment_reply(session, request, state="enrolled", upload_id=upload.upload_id,
                               source_sha256=enrollment.source_sha256)

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

    def _reset_reply(self, session, request, *, result=None, error=None):
        self._control(session, dict(type="reset_error" if error is not None else "reset_result",
            protocol=PROTOCOL_VERSION, session_epoch=session.session_epoch, request_id=request["request_id"],
            world_id=self._world_metadata.world_id, player_id=session.player_id,
            **({"code": error.code, "message": error.message} if error is not None else {"result": result})))

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

    def _battle_reply(self, session, request, *, error=None, result=None, player_card=None, championship=None,
                      admission_handoff_version=None, history_extensions=None, rival=None):
        assert self._world_metadata is not None
        self._control(session, dict(
            type="battle_error" if error is not None else "battle_result",
            protocol=PROTOCOL_VERSION, session_epoch=session.session_epoch,
            request_id=request["request_id"], operation=request["type"].removeprefix("battle_"),
            world_id=self._world_metadata.world_id, player_id=session.player_id,
            **({"player_card_version": player_card["version"], "player_card": player_card} if player_card is not None and error is None else {}),
            **({"championship": championship} if championship is not None and error is None else {}),
            **({"rival": rival} if rival is not None and error is None else {}),
            **({"admission_handoff_version": admission_handoff_version}
               if admission_handoff_version is not None and error is None else {}),
            **(history_extensions if history_extensions is not None and error is None else {}),
            **({"code": error.code, "message": error.message} if error is not None else {"result": result})))

    def _championship_challenge(self, session, request):
        if self._championships is None:
            raise ProtocolError("championship_disabled", "This host has not enabled Championships")
        self.store.read_checkpoint(session.player_id, session.session_epoch)
        if self._connected_lease(session.player_id) != session.session_epoch:
            raise ProtocolError("stale_lease", "Championships require the current authenticated player")
        desk = self.battle_desk
        capture_original = self.battle_execution is not None and self.battle_execution.resume_enabled
        # Recovery only asks the original durable ledger to classify/revoke a
        # never-entered invitation. It grants no new native core or consent;
        # only a separately requested match may call the invitation callback.
        if capture_original and request["championship"]["operation"] == "match":
            self.battle_execution.admission.require_identity(request)

        def invite(battle_id, peer):
            desk.invite(session.player_id, session.session_epoch, peer, battle_id)
            if capture_original:
                self.battle_execution.admission.capture(session.player_id, session.session_epoch,
                    dict(request, battle_id=battle_id))

        authenticated = self._team_roster()
        roster = {player: self.sessions[player].display_name for player in authenticated}
        extension = self._championships.handle(session.player_id, request["championship"],
            roster=roster, desk=desk, results=self._battle_results, invite=invite,
            reservations=self._battle_reservations,
            admission=self.battle_execution.admission if self.battle_execution is not None else None,
            eligibility=self._frontier_eligibility if self._frontier.enabled else None)
        pending = [] if desk is None else [challenge_view(view) for view in
            desk.pending(session.player_id, session.session_epoch)]
        self._battle_reply(session, request, result=pending, championship=extension)

    def _rival_challenge(self, session, request):
        """Update 31 rival checkpoints over the authenticated battle pending RPC."""
        if self._rivals is None:
            raise ProtocolError("rival_disabled", "This host has not enabled rival checkpoints")
        self.store.read_checkpoint(session.player_id, session.session_epoch)
        if self._connected_lease(session.player_id) != session.session_epoch:
            raise ProtocolError("stale_lease", "Rival checkpoints require the current authenticated player")
        desk = self.battle_desk
        capture_original = self.battle_execution is not None and self.battle_execution.resume_enabled
        if capture_original and request["rival"]["operation"] == "match":
            self.battle_execution.admission.require_identity(request)
        actor, epoch = session.player_id, session.session_epoch

        def invite(match, battle_id):
            if desk is None:
                raise ProtocolError("battle_disabled", "This host has disabled new battle challenges")
            from .rival_catalogue import preparation_word
            environment = preparation_word(request["rival"]["checkpoint_id"]) if self._rival_battle_environment else 0
            if match.mode == 2:
                desk.invite(actor, epoch, next(player for player in match.players if player != actor), battle_id,
                            environment=environment)
            else:
                own = next(team for team in match.teams if actor in team)
                other = next(team for team in match.teams if actor not in team)
                desk.invite_multi(actor, epoch, next(player for player in own if player != actor), tuple(other), battle_id,
                                  environment=environment)
            if capture_original:
                self.battle_execution.admission.capture(actor, epoch, dict(request, battle_id=battle_id))

        roster = {player: self.sessions[player].display_name for player in self._team_roster()}
        extension = self._rivals.handle(actor, request["rival"], roster=roster,
            presences={player: self.sessions[player].presence for player in roster},
            strengths=self._party_strength, usable=self._party_usable, desk=desk, results=self._battle_results,
            invite=invite, reservations=self._battle_reservations,
            admission=self.battle_execution.admission if self.battle_execution is not None else None)
        pending = [] if desk is None else [challenge_view(view) for view in desk.pending(actor, epoch)]
        self._battle_reply(session, request, result=pending, rival=extension)

    def _saved_party(self, player):
        """(level, current HP, is egg) of each saved party Pokemon; [] when unreadable."""
        from .flash import POKEMON_SIZE, SAVED_PARTY_OFFSET, inspect_flash
        session = self.sessions.get(player)
        if session is None or session.closed:
            return []
        try:
            checkpoint = self.store.read_checkpoint(player, session.session_epoch)
            if checkpoint is None:
                return []
            snapshot = inspect_flash(checkpoint.payload, save_profile=checkpoint.save_profile)
            party = []
            for index in range(min(snapshot.metadata.party_count, 6)):
                mon = snapshot.save_block1[SAVED_PARTY_OFFSET + index * POKEMON_SIZE:][:POKEMON_SIZE]
                if mon[19] & 2:  # occupied
                    party.append((mon[84], int.from_bytes(mon[86:88], "little"), bool(mon[19] & 4)))
            return party
        except Exception:  # noqa: BLE001 - an unreadable save simply has no usable party
            return []

    def _party_strength(self, player):
        """The highest level in the last saved party (the rival 2v2 team balance)."""
        return max((level for level, _hp, egg in self._saved_party(player) if not egg), default=0)

    def _party_usable(self, player):
        """Whether the last saved party has a Pokemon that can battle (not an Egg, HP above 0)."""
        return any(hp > 0 and not egg for _level, hp, egg in self._saved_party(player))

    @property
    def frontier(self):
        """The cooperative Battle Frontier's host service (frontier_service.py)."""
        service = getattr(self, "_frontier_service", None)
        if service is None:
            from .frontier_service import FrontierService
            service = self._frontier_service = FrontierService(self, party_limit=self._frontier.party_limit)
        return service

    def _frontier_rule(self):
        """The Frontier rule in force now (None when the host has not enabled them)."""
        settings = self._frontier
        return settings.rule_at(self.shared_world.world_seconds()) if settings.enabled else None

    def _frontier_eligibility(self, players):
        """Refuse a Championship entry whose last saved party breaks today's rule."""
        from .flash import FlashError, inspect_flash
        from .frontier_rules import check_party, party_members
        rule = self._frontier_rule()
        for player in players:
            session = self.sessions.get(player)
            if session is None or session.closed:
                raise ProtocolError("championship_roster_changed", "All four proposed players must still be connected")
            checkpoint = self.store.read_checkpoint(player, session.session_epoch)
            if checkpoint is None:
                raise ProtocolError("championship_ineligible", f"{session.display_name[:8]}: no saved party")
            try:
                members = party_members(inspect_flash(checkpoint.payload, save_profile=checkpoint.save_profile).save_block1)
            except FlashError as error:
                raise ProtocolError("championship_ineligible", f"{session.display_name[:8]}: save unreadable") from error
            reason = check_party(rule, members)
            if reason is not None:
                raise ProtocolError("championship_ineligible", f"{session.display_name[:8]}: {reason}")

    def _battle_challenge(self, session, request):
        # Public consent never authorizes BIND/START, supplies native receipts,
        # or claims a winner. Those remain trusted coordinator operations.
        operation = request["type"].removeprefix("battle_")
        if operation == "pending" and "admission_handoff_version" in request:
            if self.battle_execution is None or not self.battle_execution.resume_enabled:
                raise ProtocolError("admission_handoff_unsupported", "this host has no original admission handoff ledger")
            result = [challenge_view(view) for view in self.battle_desk.pending(session.player_id, session.session_epoch)]
            self._battle_reply(session, request, result=result, admission_handoff_version=1)
            return
        if operation == "pending" and "championship" in request:
            self._championship_challenge(session, request)
            return
        if operation == "pending" and "rival" in request:
            self._rival_challenge(session, request)
            return
        if operation in ("cancel_admission", "admission_handoff"):
            if self.battle_execution is None or not self.battle_execution.resume_enabled:
                raise ProtocolError("battle_resume_disabled", "neutral cleanup requires native execution with original consent")
            dispatch = (self.battle_execution.admission.cancel_admission if operation == "cancel_admission"
                        else self.battle_execution.admission.admission_handoff)
            result = dispatch(session.player_id, session.session_epoch, request)
            self._battle_reply(session, request, result=result)
            return
        if operation in ("execute", "resume"):
            if self.battle_execution is None:
                raise ProtocolError("battle_execution_disabled", "this host has not enabled native battle execution")
            dispatch = self.battle_execution.reconnect if operation == "resume" else self.battle_execution.exchange
            result = dispatch(session.player_id, session.session_epoch, request)
            self._battle_reply(session, request, result=result)
            return
        if operation == "waiting":
            from .ownership_storage import OwnershipCheckpointStore
            if not isinstance(self.store, OwnershipCheckpointStore):
                raise ProtocolError("battle_disabled", "battle waiting status requires an authenticated ownership world")
            self.store.read_checkpoint(session.player_id, session.session_epoch)
            if self._connected_lease(session.player_id) != session.session_epoch:
                raise ProtocolError("stale_lease", "battle waiting status requires the current authenticated player")
            result = [] if self._battle_reservations is None else self._battle_reservations.waiting(
                session.player_id, session.session_epoch)
            self._battle_reply(session, request, result=result)
            return
        if operation == "history":
            from .ownership_storage import OwnershipCheckpointStore
            if not isinstance(self.store, OwnershipCheckpointStore):
                raise ProtocolError("battle_disabled", "battle history requires an authenticated ownership world")
            self.store.read_checkpoint(session.player_id, session.session_epoch)
            if self._connected_lease(session.player_id) != session.session_epoch:
                raise ProtocolError("stale_lease", "battle history requires the current authenticated player")
            extensions = {"battle_archive", "reset_history", "trade_archive"}.intersection(request)
            if extensions:
                key = next(iter(extensions))
                if key == "battle_archive":
                    if self._battle_results is None:
                        raise ProtocolError("battle_archive_unsupported", "this host has no released battle archive")
                    value = self._battle_results.archive(session.player_id, request[key])
                elif key == "reset_history":
                    if self._reset_attempts is None:
                        raise ProtocolError("reset_disabled", "this world has no personal attempt ledger")
                    value = self._reset_attempts.history(session.player_id, session.session_epoch, request[key])
                else:
                    from .trade_archive import read_trade_archive
                    value = read_trade_archive(self.store, session.player_id, session.session_epoch, request[key])
                self._battle_reply(session, request, result=[], history_extensions={key: value})
                return
            card = None
            if "player_card_version" in request:
                from .player_card import build_player_card
                card = build_player_card(self, session, request["card_player"], version=request["player_card_version"])
            self._battle_reply(session, request, result=[] if self._battle_results is None
                else self._battle_results.history(session.player_id), player_card=card)
            return
        if self.battle_desk is None:
            raise ProtocolError("battle_disabled", "this development world has not enabled battle challenges")
        desk, actor = self.battle_desk, (session.player_id, session.session_epoch)
        capture_original = (self.battle_execution is not None and self.battle_execution.resume_enabled
                            and operation in ("invite", "invite_multi", "invite_ffa", "accept"))
        if capture_original:
            self.battle_execution.admission.require_identity(request)
        if operation == "pending":
            result = [challenge_view(view) for view in desk.pending(*actor)]
        else:
            battle_id = request["battle_id"]
            if (operation in ("invite", "invite_multi", "invite_ffa") and self._championships is not None
                    and self._championships.claims_battle(battle_id)):
                raise ProtocolError("championship_match_owned", "Use the Championship page for this reserved match")
            if (operation in ("invite", "invite_multi", "invite_ffa") and self._rivals is not None
                    and self._rivals.claims_battle(battle_id)):
                raise ProtocolError("rival_match_owned", "Use the rival checkpoint page for this reserved match")
            if operation == "invite":
                view = desk.invite(*actor, request["peer"], battle_id)
            elif operation == "invite_multi":
                view = desk.invite_multi(*actor, request["teammate"], tuple(request["opponents"]), battle_id)
            elif operation == "invite_ffa":
                view = desk.invite_ffa(*actor, tuple(request["opponents"]), battle_id)
            elif operation == "status":
                view = desk.status(*actor, battle_id)
            elif operation == "accept":
                view = desk.accept(*actor, battle_id, request["generation"], request["fingerprint"])
            elif operation == "claim":
                if self.battle_execution is None or not self.battle_execution.resume_enabled:
                    raise ProtocolError("battle_resume_disabled", "provisional admission requires the verified resume capability")
                view = self.battle_execution.admission.claim(*actor, request)
            else:
                view = desk.cancel(*actor, battle_id, request["generation"])
                if self.battle_execution is not None and self.battle_execution.resume_enabled:
                    self.battle_execution.admission.canceled(battle_id)
            if capture_original:
                self.battle_execution.admission.capture(*actor, request)
            result = challenge_view(view)
        self._battle_reply(session, request, result=result)

    def _trade_reply(self, session, request, *, error=None, **fields):
        assert self._world_metadata is not None
        if "preparation_version" in request:
            from .trade_protocol import PREPARATION_VERSION
            fields["preparation_version"] = PREPARATION_VERSION
        if request.get("effects_version") == 1 and self.trade_effects is not None and self.trade_effects.ready:
            fields["effects_version"] = 1
        if error is None and request["type"] == "trade_status":
            for feature in ("inspection_version", "effect_source_version"):
                if request.get(feature) == 1:
                    fields[feature] = 1
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
            retained_effect = (self.trade_effects is not None and request.get("effects_version") == 1
                               and self.trade_effects.handles(request.get("transaction_id")))
            if (kind not in {"pending", "status", "ack"} and not retained_effect) or self._trade_recovery_desk is None:
                raise ProtocolError("trade_disabled", "this development world has not enabled new trade operations")
            desk = self._trade_recovery_desk
        actor = (session.player_id, session.session_epoch)
        effects = self.trade_effects
        requested_effects = request.get("effects_version") == 1
        tx = request.get("transaction_id")
        effect_transaction = effects is not None and tx is not None and effects.handles(tx)
        if effect_transaction and not requested_effects and kind not in {"pending", "ack"}:
            raise ProtocolError("trade_effect_negotiation_required", "this retained native trade requires version negotiation")
        if requested_effects and kind not in {"status", "proposals", "pending", "ack"} and (effects is None or not effects.ready):
            raise ProtocolError("trade_effect_unsupported", "native trade replay is unavailable on this host")
        if kind not in {"status", "pending", "proposals"}:
            players = [session.player_id]
            if kind == "open":
                players.append(request["peer"])
            else:
                proposal = desk._proposals.get(request["transaction_id"])
                if proposal is not None:
                    players.extend(proposal.players)
            self._assert_battle_available(*players)
        if kind == "proposals":
            proposals = desk.proposals(*actor)
            if requested_effects and effects is not None and effects.ready:
                proposals += effects.proposals(*actor)
            self._trade_reply(session, request, proposals=proposals)
            return
        if kind == "pending":
            self._trade_reply(session, request, recoveries=[dict(
                transaction_id=r.transaction_id, sequence=r.sequence,
                outcome_fingerprint=r.outcome_fingerprint,
                checkpoint=self._checkpoint_metadata(r.checkpoint))
                for r in desk.store.pending_trade_recovery(*actor)])
            return
        txid = request["transaction_id"]
        effect_route = effect_transaction or (kind == "open" and requested_effects)
        if effect_route:
            if kind == "prepared":
                raise ProtocolError("trade_effect_receipt_required", "native candidates require the recorded choice receipt")
            if kind == "open":
                result = effects.open(*actor, request["peer"], txid)
            elif kind == "offer":
                result = effects.offer(*actor, txid, request["generation"], request["revision"], request["sha256"], request["serial"])
            elif kind == "confirm":
                result = effects.confirm(*actor, txid, request["generation"], request["fingerprint"])
            elif kind == "prepare":
                result = effects.preparation(*actor, txid, request["generation"])
            elif kind == "inspect":
                result = effects.inspect(*actor, txid, request["generation"], request["fingerprint"])
            elif kind == "effect_source":
                result = effects.effect_source(*actor, txid, request["generation"], request["preparation_id"])
            elif kind == "effect_prepared":
                result = effects.prepared(*actor, txid, request["generation"], request["fingerprint"], request["preparation_id"],
                    {k: request[k] for k in ("choices", "candidate_sha256", "candidate_size", "record_sha256")})
            elif kind == "cancel":
                result = effects.cancel(*actor, txid, request["generation"])
            elif kind == "status":
                result = effects.status(*actor, txid)
            elif kind != "ack":
                raise ProtocolError("invalid_type", "unsupported native trade operation")
            if kind != "ack":
                self._trade_reply(session, request, trade=result)
                return
        if kind == "effect_prepared":
            raise ProtocolError("trade_effect_negotiation_required", "no effectful preparation exists for this transaction")
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
        elif kind == "prepare":
            result = desk.preparation(*actor, txid, request["generation"])
        elif kind == "inspect":
            result = desk.inspect(*actor, txid, request["generation"], request["fingerprint"])
        elif kind == "effect_source":
            result = desk.effect_source(*actor, txid, request["generation"], request["preparation_id"])
        elif kind == "prepared":
            result = desk.prepared(*actor, txid, request["generation"], request["fingerprint"],
                                   request["preparation_id"], request["candidate_sha256"])
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
            if trainer_id is not None and getattr(self.store, "character_transfers_enabled", False):
                from .character_transfers import pending_source
                pending = pending_source(self.store, session.player_id)
                if pending is not None and pending[0] == "transfer":
                    trainer_id = None      # a character coming back: the store checks it against its transferred save
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
        world = self.shared_world
        players = [{
            "player_id": session.player_id, "display_name": session.display_name,
            "session_epoch": session.session_epoch, "presence": session.presence,
            "appearance": world.appearance(session.player_id),
        } for session in sorted(self.sessions.values(), key=lambda item: item.player_id) if not session.closed]
        base = {"type": "world", "protocol": PROTOCOL_VERSION, "world_seq": self.world_seq,
                "players": players, "clock": world.clock_view(), "event": world.event_view(),
                "notice": world.notice_view()}
        hiding = any(privacy.is_hidden(player["presence"]) for player in players)
        # Shared wild Pokemon (protocol 3): each game receives the slots of the
        # map it stands on, with its own "mine"/"busy" view of every claim.
        self._last_clock_broadcast = asyncio.get_running_loop().time()
        roster = [player["player_id"] for player in players]
        try:
            nav = world.nav_view({s.player_id: s.presence for s in self.sessions.values() if not s.closed})
        except Exception:  # noqa: BLE001 - the PokeNav view never stops the world view
            nav = {"players": [], "outbreak": None, "event": None}
        try:
            from .frontier_rules import RULE_NAMES
            rule = self._frontier_rule()
            nav["rule"] = None if rule is None else RULE_NAMES[rule]
        except Exception:  # noqa: BLE001 - the rule label is advisory
            nav["rule"] = None
        for session in tuple(self.sessions.values()):
            view, view_nav = base, nav
            if hiding:
                # PokeNav privacy (Update 24): this viewer's copy of the world view, with every other player's place
                # that asked to be hidden taken out of it (privacy.py).
                viewer = session.presence
                view = {**base, "players": [
                    {**player, "presence": privacy.redact(player["presence"], viewer, own=player["player_id"] == session.player_id)}
                    for player in players]}
                try:
                    view_nav = {**world.nav_view({p["player_id"]: p["presence"] for p in view["players"]}),
                                "rule": nav.get("rule")}
                except Exception:  # noqa: BLE001 - the PokeNav view never stops the world view
                    view_nav = {"players": [], "outbreak": None, "event": None, "rule": None}
            # Each game receives only its own next wallet adjustment (wagers)
            # and its own host-formed teammate (co-op Gym offers).
            wallet = None
            if session.presence is not None:
                try:
                    wallet = self.wagers.next_adjustment(session.player_id, session.presence.get("wallet_seq"))
                except Exception:  # noqa: BLE001 - money waits; the world view still flows
                    wallet = None
            try:
                spawns = world.spawn_view(session.player_id, session.presence)
            except Exception:  # noqa: BLE001 - a spawn fault never stops the world view
                spawns = None
            teammate = self._teammate(session.player_id)
            try:
                bases = world.bases.view_for(session.player_id, teammate, roster)
            except Exception:  # noqa: BLE001 - secret bases never stop the world view
                bases = []
            session.outbox.put_world(encode_message({**view, "wallet": wallet, "teammate": teammate,
                                                     "spawns": spawns, "extras": {"bases": bases, "nav": view_nav}}))

    def _progression_level(self) -> int:
        """Average of each connected player's strongest party level."""
        levels = []
        if self.store is not None:
            from .flash import POKEMON_SIZE, SAVED_PARTY_OFFSET, inspect_flash
            for session in self.sessions.values():
                try:
                    checkpoint = self.store.read_checkpoint(session.player_id, session.session_epoch)
                    if checkpoint is None:
                        continue
                    snapshot = inspect_flash(checkpoint.payload, save_profile=checkpoint.save_profile)
                    count = min(snapshot.metadata.party_count, 6)
                    party = [snapshot.save_block1[SAVED_PARTY_OFFSET + i * POKEMON_SIZE + 84] for i in range(count)]
                    if party:
                        levels.append(max(party))
                except Exception:  # noqa: BLE001 - progression is advisory only
                    continue
        return int(sum(levels) / len(levels)) if levels else 10

    def _world_reply(self, session, request, *, result=None, error=None):
        if error is not None:
            reply = {"type": "world_error", "request_id": request["request_id"],
                     "code": error.code, "message": error.message}
        else:
            reply = {"type": "world_result", "request_id": request["request_id"], "result": result}
        self._control(session, reply)

    def _shared_world_request(self, session, request) -> None:
        from .shared_world import SharedWorldError
        from .wagers import WagerError
        world = self.shared_world
        kind = request["type"]
        try:
            if kind.startswith("wager_"):
                self._world_reply(session, request, result=self._wager_request(session, request))
                return
            if kind == "gym_coop":
                self._world_reply(session, request, result=self._gym_coop_request(session, request["gym"], request))
                return
            if kind == "wallet_applied":
                credits = self.wagers.applied(session.player_id, request["seq"], request["amount"])
                self._world_reply(session, request, result={"seq": request["seq"]})
                if credits:
                    self._broadcast_world()
                return
            if kind == "appearance_get":
                self._world_reply(session, request, result={"appearance": world.appearance(session.player_id)})
                return
            if kind == "spawn_action":
                outcome = world.spawn_action(session.player_id, request["action"], request["spawn_id"],
                                             request["result"])
                self._world_reply(session, request, result={"outcome": outcome, "seq": request["seq"]})
                self._broadcast_world()
                return
            if kind == "habitat_get":
                self._world_reply(session, request, result=world.habitat_view(session.presence))
                return
            if kind == "frontier":
                self._world_reply(session, request, result=self.frontier.request(session, request))
                return
            if kind in ("base_publish", "base_visibility", "base_get"):
                self._world_reply(session, request, result=self._secret_base_request(session, request))
                return
            if kind == "friendship_get":
                friends = self.friendships.view_for(session.player_id, list(self.sessions))
                self._world_reply(session, request, result={"friends": friends})
                return
            if kind == "appearance_set":
                value = world.set_appearance(session.player_id, request["appearance"])
                self._world_reply(session, request, result={"appearance": value})
                self._broadcast_world()
                return
            action = request["action"]
            if action == "claim":
                outcome = world.claim_event(session.player_id, request["event_id"])
            elif action == "result":
                outcome = world.event_result(session.player_id, request["event_id"], request["result"],
                                             session.display_name)
                self._record_activity("event_together", session.player_id, request["event_id"])
                if request["result"] == "caught":
                    self._catch_verdict(session, request["event_id"])
            else:
                outcome = world.event_result(session.player_id, request["event_id"], "cancelled",
                                             session.display_name)
            self._world_reply(session, request, result={"outcome": outcome, "seq": request["seq"]})
            self._broadcast_world()
        except (SharedWorldError, WagerError) as error:
            self._world_reply(session, request, error=error)

    def _catch_verdict(self, session, event_id: int) -> None:
        """Tell the game that reported a World Event catch what to do with its copy (Update 17): keep it, or release the
        duplicate when another trainer's report came first. Delivered on the numbered wallet stream, so it applies once per
        save, is re-sent after a reconnect, and survives a host restart (the verdict itself is stored)."""
        wagers = getattr(self, "wagers", None)
        if wagers is None:
            return
        from . import rewards
        verdict = self.shared_world.catch_verdict(event_id, session.player_id)
        kind = rewards.KIND_CATCH_RELEASE if verdict == "release" else rewards.KIND_CATCH_KEEP
        queued = wagers.grant_reward(session.player_id, kind, rewards.catch_number(event_id), f"catch:{event_id}")
        if queued is not None and verdict == "release":
            from .shared_world import _banner
            resolution = self.shared_world._resolution(event_id)
            name = self._player_name(resolution["winner"]).upper()[:14] if resolution else "SOMEONE"
            self.shared_world.post_notice(_banner(f"{name} caught it first!", "Your copy was released."),
                                          to=[session.player_id])

    def _secret_base_request(self, session, request) -> dict:
        """A game published its base, or the player chose who may see it (Phase 6)."""
        from .secret_bases import SecretBaseError
        from .shared_world import SharedWorldError
        book, kind = self.shared_world.bases, request["type"]
        try:
            if kind == "base_publish":
                changed = book.publish(session.player_id, request["base"])
                result = {"seq": request["seq"]}
            elif kind == "base_visibility":
                changed = book.set_visibility(session.player_id, request["mode"])
                result = book.state(session.player_id)
            else:
                return book.state(session.player_id)
        except SecretBaseError as error:
            raise SharedWorldError(error.code, error.message) from error
        if changed:
            self._broadcast_world()
        return result

    # ------------------------------------------------------------- co-op Gyms
    _GYM_LEADERS = {1: "ROXANNE", 2: "BRAWLY", 3: "WATTSON", 4: "FLANNERY", 5: "NORMAN",
                    6: "WINONA", 7: "TATE&LIZA", 8: "JUAN"}

    def _teammate(self, player_id) -> str | None:
        """This player's connected host-formed teammate, if any."""
        desk = self.team_desk
        if desk is None:
            return None
        try:
            desk.refresh()
            team = desk._team_for(player_id)
        except Exception:  # noqa: BLE001 - team display is advisory
            return None
        if team is None:
            return None
        mate = next((member for member in team.members if member != player_id), None)
        session = self.sessions.get(mate) if mate is not None else None
        return mate if session is not None and not session.closed else None

    def _gym_coop_request(self, session, gym, request=None) -> dict:
        """A Gym script asked to challenge the Leader with this player's teammate.

        The request is the challenger's consent. With resumable native battles
        that consent is bound to the requesting game's original core, as a
        battle invite's is (`admission.capture`); without it the challenger's
        Enter battle was later refused ("provisional core differs from durable
        accepted consent") and no co-op battle could start (combined game audit,
        2026-10-13)."""
        from .shared_world import SharedWorldError, _banner
        actor = session.player_id

        def refuse(code, message, hint):
            self.shared_world.post_notice(_banner("TEAM GYM CHALLENGE", hint), to=[actor])
            self._broadcast_world()
            raise SharedWorldError(code, message)

        if self.battle_desk is None:
            refuse("battle_disabled", "battles are not enabled on this host", "Battles are off on this host")
        teammate = self._teammate(actor)
        if teammate is None:
            refuse("no_teammate", "form a team in the Players menu first", "Form a team in PLAYERS first")
        here, there = session.presence, self.sessions[teammate].presence
        # On the field, as before players sent "battle" or "menu" (a teammate in either was "unavailable" then).
        if (here is None or there is None or there.get("activity") != "overworld"
                or (here["map_group"], here["map_number"]) != (there["map_group"], there["map_number"])):
            refuse("teammate_away", "your teammate must be in this Gym", "Your teammate must be here")
        capture = self.battle_execution is not None and self.battle_execution.resume_enabled
        if capture and (request is None or "runtime_id" not in request):
            refuse("battle_original_core_required", "the co-op request needs the requesting game's native core",
                   "Update your game files")
        try:
            self._assert_battle_available(actor, teammate)
            view = self.battle_desk.invite_coop(actor, session.session_epoch, teammate, gym, str(uuid4()))
            if capture:
                self.battle_execution.admission.capture(actor, session.session_epoch,
                                                        dict(request, battle_id=view["battle_id"]))
        except (BattleError, StorageError, ProtocolError) as error:
            refuse(error.code, error.message, "Finish other battles first")
        leader = self._GYM_LEADERS.get(gym, "the LEADER")
        name = self._player_name(actor).upper()[:10]
        self.shared_world.post_notice(_banner(f"TEAM GYM vs {leader}!", f"{name}: open PLAYERS to join"), to=[teammate])
        self.shared_world.post_notice(_banner(f"TEAM GYM vs {leader}!", "Open PLAYERS > Challenges"), to=[actor])
        self._broadcast_world()
        return {"battle_id": view["battle_id"]}

    # ---------------------------------------------------------------- wagers
    def _money(self, player_id) -> int | None:
        """Money in a connected player's canonical checkpoint (the same frozen
        save a battle challenge uses), or None when unknown."""
        session = self.sessions.get(player_id)
        if self.store is None or session is None or session.closed:
            return None
        try:
            checkpoint = self.store.read_checkpoint(player_id, session.session_epoch)
            if checkpoint is None:
                return None
            from .flash import inspect_flash
            from .wagers import money_from_snapshot
            return money_from_snapshot(inspect_flash(checkpoint.payload, save_profile=checkpoint.save_profile))
        except Exception:  # noqa: BLE001 - unknown money never allows a wager
            return None

    def _wager_request(self, session, request) -> dict:
        from .shared_world import _banner
        from .wagers import WagerError, format_money
        kind, actor = request["type"], session.player_id
        desk = self.battle_desk
        if desk is None:
            raise WagerError("battle_disabled", "battles are not enabled on this host")
        desk.refresh()
        battle = desk._active.get(request["battle_id"])
        if battle is None or actor not in battle.players:
            raise WagerError("no_battle", "that challenge is no longer pending")
        if self._championships is not None and self._championships.claims_battle(battle.battle_id):
            raise WagerError("championship_match", "Championship matches have no wagers")
        if self._rivals is not None and self._rivals.claims_battle(battle.battle_id):
            raise WagerError("rival_match", "Rival checkpoint battles have no wagers")
        if battle.mode == 4:
            raise WagerError("coop_gym", "Gym battles together have no wagers")
        if battle.mode == 5:
            raise WagerError("free_for_all", "free-for-all battles have no wagers")
        battle_id, players = battle.battle_id, list(battle.players)
        open_states = ("invited", "accepted", "prepared")
        if kind != "wager_get" and battle.state not in open_states:
            raise WagerError("wager_locked", "the battle has already started")
        name = self._player_name(actor).upper()[:12]
        others = [player for player in players if player != actor]
        current = self.wagers.view(battle_id)
        if kind == "wager_set":
            amount = request["amount"]
            if current is not None and current["sender"] != actor:
                raise WagerError("wager_owned", "decline this wager before proposing another")
            funds = {player: self._money(player) or 0 for player in players}
            view = self.wagers.propose(battle_id, actor, players, amount, funds)
            if view is not None:
                self.shared_world.post_notice(_banner(f"{name}: WAGER {format_money(amount)}",
                                                      "Accept it in PLAYERS"), to=others)
            elif current is not None:
                self.shared_world.post_notice(_banner("WAGER REMOVED", f"by {name}"), to=others)
        elif kind == "wager_accept":
            view = self.wagers.accept(battle_id, actor, request["amount"], self._money(actor) or 0)
            if set(view["accepted"]) == set(view["players"]):
                self.shared_world.post_notice(_banner(f"WAGER ON: {format_money(view['amount'])} EACH",
                                                      "Winner takes the stakes!"), to=players)
        elif kind == "wager_decline":
            self.wagers.decline(battle_id, actor)
            if current is not None and current["sender"] != actor:
                self.shared_world.post_notice(_banner("WAGER DECLINED", f"by {name}"), to=[current["sender"]])
        if kind != "wager_get":
            self._broadcast_world()
        return {"wager": self.wagers.view(battle_id), "money": self._money(actor)}

    def _wager_gate(self, battle) -> None:
        """START is refused until every trainer accepted the wager (and can pay)."""
        from .wagers import WagerError
        if self.wagers.view(battle.battle_id) is None:
            return
        try:
            if not self.wagers.ready(battle.battle_id):
                raise WagerError("wager_pending", "every trainer must accept the wager first")
            self.wagers.lock(battle.battle_id, {player: self._money(player) or 0 for player in battle.players})
        except WagerError as error:
            raise BattleError(error.code, error.message) from error

    def _on_battle_aborted(self, battle) -> None:
        from .shared_world import _banner
        current = self.wagers.view(battle.battle_id)
        if current is None or current["state"] not in ("proposed", "locked"):
            return
        self.wagers.cancel(battle.battle_id)
        self.shared_world.post_notice(_banner("WAGER CANCELED", "The battle never started"), to=list(battle.players))
        self._broadcast_world()

    def _settle_wager(self, battle, outcome) -> None:
        from .shared_world import _banner
        from .wagers import format_money
        players = list(battle.players)
        debits = self.wagers.settle(battle.battle_id, players, battle.mode, outcome)
        if not debits:
            return
        amount = debits[0][1]
        losers = [player for player, _ in debits]
        winners = [player for player in players if player not in losers]
        self.shared_world.post_notice(_banner("YOU WON THE WAGER!", f"{format_money(amount)} is on its way"), to=winners)
        self.shared_world.post_notice(_banner("WAGER LOST", f"{format_money(amount)} goes to the winner"), to=losers)

    def _record_activity(self, kind, player_id, reference) -> None:
        """Kept for compatibility: World Event results are credited once the
        event finishes, to the players who actually challenged it."""
        return None

    # ------------------------------------------------------------ friendship
    def _player_name(self, player_id) -> str:
        session = self.sessions.get(player_id)
        return session.display_name if session is not None else "a friend"

    def _friendship_notices(self, changes) -> None:
        from .shared_world import _banner
        for change in changes:
            a, b = change["pair"]
            if change.get("lucky_friends"):
                for me, other in ((a, b), (b, a)):
                    self.shared_world.post_notice(_banner(f"LUCKY FRIENDS with {self._player_name(other).upper()[:14]}!",
                                                          "Next trade together: LUCKY!"), to=[me])
            elif change.get("level_up"):
                for me, other in ((a, b), (b, a)):
                    self.shared_world.post_notice(_banner(f"{change['level'].upper()} with",
                                                          f"{self._player_name(other).upper()[:20]}!"), to=[me])

    def _decide_lucky_trade(self, players) -> bool:
        lucky, _ = self.friendships.lucky_trade_decision(*players)
        return lucky

    def _on_trade_committed(self, transaction_id, players, lucky) -> None:
        a, b = players
        guaranteed = self.friendships.pair(a, b)["lucky_friends"]
        change = self.friendships.commit_trade(transaction_id, a, b, lucky, guaranteed)
        if lucky:
            from .shared_world import _banner
            self.shared_world.post_notice(_banner("LUCKY TRADE!", "Both POKEMON are now LUCKY!"), to=list(players))
        self._friendship_notices([change])
        self._broadcast_world()

    def _on_battle_publish(self, battle) -> None:
        """Before a co-op battle closes: its outcome becomes durable (the PvP archive does not hold co-op battles)."""
        outcome = next(iter(battle.finished.values()), None)
        if outcome is not None:
            if battle.mode == 5:
                self.shared_world.ffa.record(battle.battle_id, outcome, battle.players)   # four-player free-for-all
            else:
                self.shared_world.frontier.record_result(battle.battle_id, outcome, battle.players)

    def _on_battle_closed(self, battle) -> None:
        players = list(battle.players)
        if battle.mode == 4:
            try:
                self.frontier.reconcile()   # a Frontier round's result settles once (frontier_service.py)
            except Exception:  # noqa: BLE001 - progress is reconciled again at the next read or tick
                pass
        outcome = next(iter(battle.finished.values()), None)
        if outcome is not None and battle.mode != 5:   # a free-for-all has no wager
            try:
                self._settle_wager(battle, outcome)
            except Exception:  # noqa: BLE001 - a wager never changes the battle record
                pass
        championship = self._championships is not None and self._championships.claims_battle(battle.battle_id)
        changes = []
        if battle.mode == 4:
            # A co-op Gym battle: completing a Gym together (won or not).
            changes.append(self.friendships.record_pair("gym_together", players[0], players[1], battle.battle_id))
        elif battle.mode == 3:
            teams = (players[::2], players[1::2])
            for team in teams:
                changes.append(self.friendships.record_pair("battle_together", team[0], team[1], battle.battle_id))
            kind = "championship" if championship else "battle_against"
            for x in teams[0]:
                for y in teams[1]:
                    changes.append(self.friendships.record_pair(kind, x, y, battle.battle_id))
        elif battle.mode == 5:
            # Four independent trainers: everyone fought everyone.
            for i, x in enumerate(players):
                for y in players[i + 1:]:
                    changes.append(self.friendships.record_pair("battle_against", x, y, battle.battle_id))
        elif len(players) == 2:
            kind = "championship" if championship else "battle_against"
            changes.append(self.friendships.record_pair(kind, players[0], players[1], battle.battle_id))
        self._friendship_notices(changes)
        self._broadcast_world()

    def _on_event_finished(self, participants, event_id) -> None:
        changes = []
        for i, x in enumerate(participants):
            for y in participants[i + 1:]:
                changes.append(self.friendships.record_pair("event_together", x, y, f"event:{event_id}"))
        self._friendship_notices(changes)

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
                if (session.enrollment_upload is not None
                        and now - session.enrollment_upload.last_activity >= self.config.checkpoint_upload_timeout):
                    session.enrollment_upload = None
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
            if self.shared_world.tick_events(len(self.sessions), self._progression_level):
                changed = True
            presences = {player_id: session.presence for player_id, session in self.sessions.items()
                         if not session.closed}
            try:
                if self.shared_world.tick_spawns(presences, self._progression_level):
                    changed = True
            except Exception:  # noqa: BLE001 - shared spawns never stop the host loop
                pass
            if self.shared_world.tick_event_claim(presences):
                changed = True
            if self.shared_world.tick_event_conditions(presences):
                changed = True
            if self.battle_desk is not None and time.monotonic() - self._last_frontier_tick >= 5:
                self._last_frontier_tick = time.monotonic()
                try:
                    self.frontier.reconcile()
                except Exception:  # noqa: BLE001 - never stops the host loop
                    pass
            # Online-together friendship time (small, daily capped).
            mono = time.monotonic()
            if mono - self._last_friendship_tick >= 60:
                elapsed, self._last_friendship_tick = mono - self._last_friendship_tick, mono
                # Time together on the field, as before players sent "battle" or "menu" (both were "unavailable").
                online = [pid for pid, session in self.sessions.items()
                          if session.presence is not None and session.presence.get("activity") == "overworld"]
                if len(online) > 1:
                    self._friendship_notices(self.friendships.add_time_together(online, min(elapsed, 120)))
                    changed = True
            if self.sessions and now - self._last_clock_broadcast >= 1.0:
                changed = True
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
