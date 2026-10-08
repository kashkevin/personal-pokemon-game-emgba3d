"""Verified-ROM companion connecting a loopback binary bridge to the world server.

The current ruleset identifies the unmodified RHH baseline plus the mailbox,
not a completed Gen 6 game. This component never writes ROM/RAM or save files.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import struct
from typing import Any
import zlib
from uuid import UUID, uuid4

from .bridge_protocol import BridgeError, BridgeOutbox, read_packet
from .mailbox import ABI_VERSION, CONNECTED, MAILBOX_SIZE, MailboxError, Peer, Pose, Snapshot
from .protocol import (
    MAX_COUNTER, MAX_PLAYERS, PROTOCOL_VERSION, ProtocolError, encode_message,
    read_message, validate_heartbeat, validate_hello, validate_presence,
)
from .server import is_local_address
from .secure_transport import ClientTlsConfig, is_numeric_unicast_address
from .battle_manifest import validate_battle_manifest
from .save_window import validate_window_manifest, WINDOW_FRAME_SIZE

BASELINE_RULESET = "baseline-rhh1.17.1-mailbox-v1"
_UINT32 = 0xFFFFFFFF


class TeamError(ValueError):
    """A server refusal; connection loss/timeout instead leaves RPC fate unknown."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class TradeError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class BattleChallengeError(ValueError):
    """Authoritative consent refusal; transport failure still has unknown fate."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def verify_rom_manifest(rom_path: Path, manifest_path: Path) -> tuple[str, dict[str, Any]]:
    """Hash the supplied game bytes; manifest identity alone is never trusted."""
    if manifest_path.stat().st_size > 65_536:
        raise ValueError("manifest exceeds its size limit")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    if type(manifest.get("abi_version")) is not int or manifest["abi_version"] != ABI_VERSION:
        raise ValueError("manifest ABI is incompatible")
    if type(manifest.get("mailbox_size")) is not int or manifest["mailbox_size"] != MAILBOX_SIZE:
        raise ValueError("manifest mailbox size is incompatible")
    if manifest.get("ruleset_id") != BASELINE_RULESET:
        raise ValueError("manifest ruleset must identify the baseline mailbox build")
    expected_hash = manifest.get("rom_sha256")
    if not isinstance(expected_hash, str) or re.fullmatch("[0-9a-f]{64}", expected_hash) is None:
        raise ValueError("manifest ROM SHA256 is invalid")
    size = rom_path.stat().st_size
    if not 1 <= size <= 32 * 1024 * 1024:
        raise ValueError("ROM size exceeds the supported GBA budget")
    if "rom_size" in manifest and (type(manifest["rom_size"]) is not int or manifest["rom_size"] != size):
        raise ValueError("manifest ROM size does not match the file")
    if "mailbox_address" in manifest:
        address = manifest["mailbox_address"]
        if type(address) is not int or address % 4 or not 0x02000000 <= address <= 0x02040000 - MAILBOX_SIZE:
            raise ValueError("manifest mailbox must be aligned and contained in EWRAM")
    save_fields = {"save_abi_version", "save_mailbox_size", "save_mailbox_address"}
    if save_fields & set(manifest):
        if not save_fields <= set(manifest) or "mailbox_address" not in manifest:
            raise ValueError("manifest save mailbox fields are incomplete")
        address = manifest["save_mailbox_address"]
        presence = manifest["mailbox_address"]
        if (type(manifest["save_abi_version"]) is not int or manifest["save_abi_version"] != 1
                or type(manifest["save_mailbox_size"]) is not int or manifest["save_mailbox_size"] != 512
                or type(address) is not int or address % 4
                or not 0x02000000 <= address <= 0x02040000 - 512
                or not (address + 512 <= presence or presence + MAILBOX_SIZE <= address)):
            raise ValueError("manifest save mailbox is incompatible or overlaps presence")
    digest, crc = hashlib.sha256(), 0
    with rom_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            crc = zlib.crc32(chunk, crc)
    actual_hash = digest.hexdigest()
    if not hmac.compare_digest(actual_hash, expected_hash):
        raise ValueError("ROM SHA256 does not match the generated manifest")
    if "rom_crc32" in manifest:
        if manifest["rom_crc32"] != f"{crc & _UINT32:08x}":
            raise ValueError("ROM CRC32 does not match the generated manifest")
    ownership_fields = {"ownership_abi_version", "save_profile"}
    if ownership_fields & set(manifest):
        if (not ownership_fields <= set(manifest) or "save_mailbox_address" not in manifest
                or type(manifest["ownership_abi_version"]) is not int or manifest["ownership_abi_version"] != 1
                or manifest["save_profile"] != "rhh-1.17.1-bb1093-ownership-v1"):
            raise ValueError("manifest ownership capability is incompatible")
    trade_fields = {"trade_abi_version", "trade_abi_address"}
    if trade_fields & set(manifest):
        marker = manifest.get("trade_abi_address")
        if (not trade_fields <= set(manifest) or not ownership_fields <= set(manifest)
                or type(manifest["trade_abi_version"]) is not int or manifest["trade_abi_version"] != 1
                or type(marker) is not int or marker % 4
                or not 0x08000000 <= marker <= 0x08000000 + size - 4):
            raise ValueError("manifest trade capability is incompatible")
        with rom_path.open("rb") as source:
            source.seek(marker - 0x08000000)
            if source.read(4) != b"\x01\x00\x00\x00":
                raise ValueError("trade capability marker does not match the verified ROM")
    validate_battle_manifest(manifest, rom_path)
    validate_window_manifest(manifest, rom_path)
    from .menu_mailbox import validate_menu_manifest
    validate_menu_manifest(manifest, rom_path)
    from .reset_mailbox import validate_reset_manifest
    validate_reset_manifest(manifest, rom_path)
    from .emergency_protocol import validate_emergency_manifest
    validate_emergency_manifest(manifest, rom_path)
    return actual_hash, manifest


@dataclass(frozen=True)
class CompanionConfig:
    rom_path: Path
    manifest_path: Path
    player_id: str
    display_name: str
    token: bytes = field(repr=False)
    server_host: str = "127.0.0.1"
    server_port: int = 8765
    ipc_host: str = "127.0.0.1"
    ipc_port: int = 8870
    pause_timeout: float = 0.5
    pose_interval: float = 0.05
    snapshot_interval: float = 0.1
    reconnect_delay: float = 0.25
    handshake_timeout: float = 3.0
    remote_timeout: float = 20.0
    send_timeout: float = 1.0
    server_credential: bytes | None = field(default=None, repr=False)
    server_tls: ClientTlsConfig | None = None
    public_server: bool = False
    expected_world_id: str | None = None
    development_battle_channel: bool = False
    build_id: str = field(init=False)
    ruleset_id: str = field(init=False, default=BASELINE_RULESET)
    save_enabled: bool = field(init=False, default=False)
    ownership_enabled: bool = field(init=False, default=False)
    trade_enabled: bool = field(init=False, default=False)
    battle_enabled: bool = field(init=False, default=False)
    battle_abi_version: int = field(init=False, default=0)
    save_window_enabled: bool = field(init=False, default=False)
    reset_enabled: bool = field(init=False, default=False)
    reset_abi_version: int = field(init=False, default=0)
    menu_enabled: bool = field(init=False, default=False)
    menu_abi_version: int = field(init=False, default=1)
    emergency_save_enabled: bool = field(init=False, default=False)
    emergency_save_abi_version: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        rom_path, manifest_path = Path(self.rom_path).resolve(), Path(self.manifest_path).resolve()
        object.__setattr__(self, "rom_path", rom_path)
        object.__setattr__(self, "manifest_path", manifest_path)
        build_id, manifest = verify_rom_manifest(rom_path, manifest_path)
        object.__setattr__(self, "build_id", build_id)
        object.__setattr__(self, "save_enabled", "save_mailbox_address" in manifest)
        object.__setattr__(self, "ownership_enabled", manifest.get("ownership_abi_version") == 1)
        object.__setattr__(self, "trade_enabled", manifest.get("trade_abi_version") == 1)
        object.__setattr__(self, "battle_enabled", manifest.get("battle_abi_version") in (1, 2, 3))
        object.__setattr__(self, "battle_abi_version", manifest.get("battle_abi_version", 0))
        object.__setattr__(self, "menu_enabled", manifest.get("menu_abi_version") in (1, 2))
        object.__setattr__(self, "menu_abi_version", manifest.get("menu_abi_version", 1))
        object.__setattr__(self, "save_window_enabled", manifest.get("save_window_abi_version") == 1)
        object.__setattr__(self, "reset_enabled", manifest.get("reset_abi_version") in (1, 2))
        object.__setattr__(self, "reset_abi_version", manifest.get("reset_abi_version", 0))
        object.__setattr__(self, "emergency_save_enabled", manifest.get("emergency_save_abi_version") in (1, 2))
        object.__setattr__(self, "emergency_save_abi_version", manifest.get("emergency_save_abi_version", 0))
        if type(self.development_battle_channel) is not bool:
            raise ValueError("development_battle_channel must be a boolean")
        if self.development_battle_channel and (not self.battle_enabled or self.server_credential is None):
            raise ValueError("development battle channel requires its verified ROM and authenticated world")
        validate_hello({
            "type": "hello", "protocol": PROTOCOL_VERSION, "build_id": build_id,
            "ruleset_id": self.ruleset_id, "player_id": self.player_id,
            "display_name": self.display_name,
        }, build_id, self.ruleset_id)
        if not isinstance(self.token, bytes) or len(self.token) != 32:
            raise ValueError("IPC token must contain exactly 32 random bytes")
        if self.server_credential is not None and (not isinstance(self.server_credential, bytes) or len(self.server_credential) != 32):
            raise ValueError("server credential must contain exactly 32 random bytes")
        if not is_local_address(self.ipc_host):
            raise ValueError("binary IPC must bind a numeric loopback address")
        if type(self.public_server) is not bool:
            raise ValueError("public_server must be a boolean")
        if self.server_tls is not None and not isinstance(self.server_tls, ClientTlsConfig):
            raise ValueError("server_tls requires a ClientTlsConfig")
        if self.public_server:
            if self.server_tls is None or self.server_credential is None:
                raise ValueError("public transport requires pinned TLS and a player credential")
            if not is_numeric_unicast_address(self.server_host):
                raise ValueError("public transport requires a specific numeric unicast destination")
        elif not is_local_address(self.server_host, allow_lan=True):
            raise ValueError("this prototype connects only to numeric local/LAN server addresses")
        if self.expected_world_id is not None:
            try:
                valid_world = str(UUID(self.expected_world_id)) == self.expected_world_id
            except (ValueError, TypeError, AttributeError):
                valid_world = False
            if not valid_world or self.server_credential is None:
                raise ValueError("expected_world_id requires a canonical world UUID and player credential")
        for name, low in (("ipc_port", 0), ("server_port", 1)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= 65535:
                raise ValueError(f"{name} is outside its port bounds")
        for name in (
            "pause_timeout", "pose_interval", "snapshot_interval", "reconnect_delay",
            "handshake_timeout", "remote_timeout", "send_timeout",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive duration")


def _integer(value: Any, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ProtocolError("invalid_server_message", f"{name} is outside its bounds")
    return value


def _fields(message: Any, names: set[str], kind: str) -> None:
    if not isinstance(message, dict) or set(message) != names or message.get("type") != kind:
        raise ProtocolError("invalid_server_message", f"invalid {kind} message fields")
    if type(message.get("protocol")) is not int or message["protocol"] != PROTOCOL_VERSION:
        raise ProtocolError("unsupported_protocol", "server protocol is incompatible")


def validate_welcome(message: dict[str, Any], config: CompanionConfig) -> dict[str, Any]:
    names = {
        "type", "protocol", "build_id", "ruleset_id", "player_id", "session_epoch",
        "max_players", "heartbeat_interval", "idle_timeout",
    }
    durable = {"world_id", "server_epoch", "save_profile", "checkpoint_enabled"}
    if isinstance(message, dict) and set(message) == names | durable:
        if config.server_credential is None or message["checkpoint_enabled"] is not True:
            raise ProtocolError("identity_mismatch", "durable world requires a player credential")
        try:
            if str(UUID(message["world_id"])) != message["world_id"]:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ProtocolError("invalid_server_message", "invalid world identity") from None
        _integer(message["server_epoch"], 1, MAX_COUNTER, "server_epoch")
        if not isinstance(message["save_profile"], str) or not 1 <= len(message["save_profile"]) <= 128:
            raise ProtocolError("invalid_server_message", "invalid save profile")
        names |= durable
    elif config.server_credential is not None:
        raise ProtocolError("identity_mismatch", "authenticated client requires a durable world")
    _fields(message, names, "welcome")
    if message["build_id"] != config.build_id or message["ruleset_id"] != config.ruleset_id:
        raise ProtocolError("identity_mismatch", "server build/ruleset is incompatible")
    if message["player_id"] != config.player_id:
        raise ProtocolError("identity_mismatch", "server assigned another player identity")
    if config.expected_world_id is not None and message.get("world_id") != config.expected_world_id:
        raise ProtocolError("identity_mismatch", "server world differs from the expected durable world")
    if type(message["max_players"]) is not int or message["max_players"] != MAX_PLAYERS:
        raise ProtocolError("invalid_server_message", "server player limit is incompatible")
    _integer(message["session_epoch"], 1, MAX_COUNTER, "session_epoch")
    for name in ("heartbeat_interval", "idle_timeout"):
        value = message[name]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
            raise ProtocolError("invalid_server_message", "server heartbeat durations are invalid")
    if message["heartbeat_interval"] >= message["idle_timeout"]:
        raise ProtocolError("invalid_server_message", "server heartbeat interval exceeds its timeout")
    return message


def validate_world(message: dict[str, Any], config: CompanionConfig, session_epoch: int) -> list[dict[str, Any]]:
    _fields(message, {"type", "protocol", "world_seq", "players"}, "world")
    _integer(message["world_seq"], 1, MAX_COUNTER, "world_seq")
    players = message["players"]
    if not isinstance(players, list) or not 1 <= len(players) <= MAX_PLAYERS:
        raise ProtocolError("invalid_server_message", "server roster exceeds its bounds")
    validated = []
    seen = set()
    for player in players:
        if not isinstance(player, dict) or set(player) != {"player_id", "display_name", "session_epoch", "presence"}:
            raise ProtocolError("invalid_server_message", "invalid player roster fields")
        validate_hello({
            "type": "hello", "protocol": PROTOCOL_VERSION, "build_id": config.build_id,
            "ruleset_id": config.ruleset_id, "player_id": player["player_id"],
            "display_name": player["display_name"],
        }, config.build_id, config.ruleset_id)
        if player["player_id"] in seen:
            raise ProtocolError("invalid_server_message", "duplicate player identity in roster")
        seen.add(player["player_id"])
        epoch = _integer(player["session_epoch"], 1, MAX_COUNTER, "player session_epoch")
        presence = player["presence"]
        if presence is not None:
            if not isinstance(presence, dict):
                raise ProtocolError("invalid_server_message", "invalid player presence")
            presence = validate_presence({"type": "presence", **presence}, epoch)
        validated.append({**player, "presence": presence})
    own = next((player for player in validated if player["player_id"] == config.player_id), None)
    if own is None or own["session_epoch"] != session_epoch:
        raise ProtocolError("session_epoch_mismatch", "server roster does not contain this session")
    return sorted(validated, key=lambda player: player["player_id"])


@dataclass
class BridgeSession:
    writer: asyncio.StreamWriter
    outbox: BridgeOutbox
    incarnation: int
    writer_task: asyncio.Task[None] | None = None
    save_capable: bool = False
    window_capable: bool = False
    emergency_save_capable: bool = False
    battle_capable: bool = False
    menu_session: Any = None
    reset_session: Any = None


class Companion:
    def __init__(self, config: CompanionConfig) -> None:
        self.config = config
        self._server_tls_context = config.server_tls.build_context() if config.server_tls is not None else None
        self.connected = False
        self.session_epoch: int | None = None
        self.last_error: str | None = None
        self._ipc_server: asyncio.Server | None = None
        self._remote_task: asyncio.Task[None] | None = None
        self._snapshot_task: asyncio.Task[None] | None = None
        self._remote_writer: asyncio.StreamWriter | None = None
        self._remote_lock = asyncio.Lock()
        self.world_id: str | None = None
        self.server_epoch: int | None = None
        self.save_profile: str | None = None
        self._checkpoint_pending: dict[str, tuple[str, int, asyncio.Future]] = {}
        self._trade_pending: dict[str, tuple[dict, asyncio.Future]] = {}
        self._team_pending: dict[str, tuple[dict, asyncio.Future]] = {}
        self._challenge_pending: dict[str, tuple[dict, asyncio.Future]] = {}
        self._reset_pending: dict[str, tuple[dict, asyncio.Future]] = {}
        self._save_pending: dict[int, tuple[Any, asyncio.Future]] = {}
        self._battle_pending: dict[int, tuple[Any, asyncio.Future]] = {}
        self.live_checkpoint_lock = asyncio.Lock()
        self._live_save_owner: asyncio.Task | None = None
        self._bridge: BridgeSession | None = None
        self._bridge_admission_blocked = False
        self._bridge_incarnation = 0
        self._ipc_writers: set[asyncio.StreamWriter] = set()
        self._ipc_handlers: set[asyncio.Task] = set()
        self._closing = False
        self._emergency_controller = None
        self._emergency_authority = None
        self._reconnect_blocked = False
        self._local_pose: Pose | None = None
        self._last_pose_time = 0.0
        self._network_seq = 0
        self._network_map_epoch = 0
        self._sent_source_signature: tuple | None = None
        self._sent_pose_signature: tuple | None = None
        self._players: list[dict[str, Any]] = []
        self._last_world_seq = 0
        self._peer_history: dict[tuple[str, int], dict[str, Any]] = {}
        self._roster_signature: tuple | None = None
        self._roster_epoch = 0
        self._heartbeat = 0

    @property
    def ipc_address(self) -> tuple[str, int]:
        if self._ipc_server is None or not self._ipc_server.sockets:
            raise RuntimeError("companion IPC is not listening")
        address = self._ipc_server.sockets[0].getsockname()
        return address[0], address[1]

    @property
    def snapshot(self) -> Snapshot:
        if not self.connected or self._roster_signature is None:
            return Snapshot(heartbeat=self._heartbeat, roster_epoch=self._roster_epoch)
        own_slot = next((index for index, player in enumerate(self._players) if player["player_id"] == self.config.player_id), 0)
        peers = tuple(Peer(index + 1, Pose.from_presence(player["presence"])) for index, player in enumerate(self._players) if player["player_id"] != self.config.player_id and player["presence"] is not None)
        return Snapshot(CONNECTED, self._heartbeat, self._roster_epoch, own_slot, peers)

    async def start(self) -> None:
        if self._ipc_server is not None:
            raise RuntimeError("companion is already started")
        self._closing = False
        self._ipc_server = await asyncio.start_server(self._accept_bridge, self.config.ipc_host, self.config.ipc_port, limit=260)
        self._remote_task = asyncio.create_task(self._remote_loop(), name="companion-world-connection")
        self._snapshot_task = asyncio.create_task(self._snapshot_loop(), name="companion-mailbox-snapshots")

    async def close(self) -> None:
        self._closing = True
        ipc_server = self._ipc_server
        if self._ipc_server is not None:
            self._ipc_server.close()
            self._ipc_server = None
        for writer in tuple(self._ipc_writers):
            writer.close()
        for task in (self._remote_task, self._snapshot_task):
            if task is not None:
                task.cancel()
        await asyncio.gather(*(task for task in (self._remote_task, self._snapshot_task) if task is not None), return_exceptions=True)
        if self._ipc_handlers:
            tasks = tuple(self._ipc_handlers)
            _, pending = await asyncio.wait(tasks, timeout=self.config.send_timeout + 0.2)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if ipc_server is not None:
            await ipc_server.wait_closed()
        self._disconnect_remote()

    def _publish_snapshot(self) -> None:
        if self._bridge is not None:
            self._bridge.outbox.put(b"S" + self.snapshot.pack())

    async def _snapshot_loop(self) -> None:
        while True:
            self._heartbeat = self._heartbeat % _UINT32 + 1
            self._publish_snapshot()
            await asyncio.sleep(self.config.snapshot_interval)

    async def _accept_bridge(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._ipc_handlers.add(task)
        self._ipc_writers.add(writer)
        bridge: BridgeSession | None = None
        try:
            peer = writer.get_extra_info("peername")
            if self._closing or self._bridge_admission_blocked or peer is None or not is_local_address(peer[0]) or len(self._ipc_writers) > 4:
                return
            packet = await asyncio.wait_for(read_packet(reader), self.config.handshake_timeout)
            if packet is None or len(packet) != 33 or packet[:1] != b"H" or not hmac.compare_digest(packet[1:], self.config.token):
                return
            if self._bridge is not None or self._bridge_admission_blocked:
                return
            self._bridge_incarnation += 1
            bridge = BridgeSession(writer, BridgeOutbox(), self._bridge_incarnation)
            self._bridge = bridge
            self._local_pose = None
            self._last_pose_time = 0.0
            bridge.writer_task = asyncio.create_task(self._write_bridge(bridge), name="companion-bridge-writer")
            self._publish_snapshot()
            while not writer.is_closing():
                packet = await read_packet(reader, maximum=WINDOW_FRAME_SIZE if self.config.save_window_enabled else 256)
                if packet is None:
                    break
                if packet[:1] == b"V":
                    if not self.config.save_enabled or packet != b"V" + struct.pack("<HHHH", 1, 512, 240, 192):
                        raise BridgeError("save capability disagrees with verified manifest")
                    bridge.save_capable = True
                    continue
                if packet[:1] == b"R":
                    if not bridge.save_capable:
                        raise BridgeError("save response arrived before its verified capability")
                    self._receive_save_response(packet[1:], bridge)
                    continue
                if packet[:1] == b"Z":
                    from .emergency_protocol import capability_packet
                    if (not bridge.save_capable or not self.config.emergency_save_enabled
                            or packet != capability_packet(self.config.emergency_save_abi_version)):
                        raise BridgeError("emergency save capability disagrees with verified manifest")
                    bridge.emergency_save_capable = True
                    continue
                if packet[:1] == b"X":
                    from .save_window import capability_packet
                    if not bridge.save_capable or not self.config.save_window_enabled or packet != capability_packet():
                        raise BridgeError("save window disagrees with verified manifest")
                    bridge.window_capable = True
                    continue
                if packet[:1] == b"F":
                    from .save_window import parse_window_packet
                    if not bridge.window_capable:
                        raise BridgeError("save window arrived before its verified capability")
                    try:
                        response, window = parse_window_packet(packet)
                    except ValueError as error:
                        raise BridgeError("invalid Flash window") from error
                    self._receive_save_response(response.pack(), bridge, window=window)
                    continue
                if packet[:1] == b"W":
                    from .battle_mailbox import capability_packet
                    if not self.config.battle_enabled or packet != capability_packet(self.config.battle_abi_version):
                        raise BridgeError("battle capability disagrees with verified manifest")
                    bridge.battle_capable = True
                    continue
                if packet[:1] == b"E":
                    if not bridge.battle_capable:
                        raise BridgeError("battle response arrived before its verified capability")
                    self._receive_battle_response(packet[1:], bridge)
                    continue
                if packet[:1] == b"Q":
                    from .reset_mailbox import capability
                    from .reset_session import ResetSession
                    if not self.config.reset_enabled or packet != capability(self.config.reset_abi_version) or bridge.reset_session is not None:
                        raise BridgeError("personal encounter capability differs from verified manifest")
                    bridge.reset_session = ResetSession(self, bridge)
                    continue
                if packet[:1] == b"T":
                    if bridge.reset_session is None:
                        raise BridgeError("personal encounter request precedes its capability")
                    try:
                        bridge.reset_session.feed(packet[1:])
                    except ValueError as error:
                        raise BridgeError("invalid personal encounter request") from error
                    continue
                if packet[:1] == b"Y":
                    if bridge.reset_session is None:
                        raise BridgeError("personal encounter receipt precedes its capability")
                    try:
                        bridge.reset_session.observe(packet[1:])
                    except ValueError as error:
                        raise BridgeError("invalid personal encounter receipt") from error
                    continue
                if packet[:1] == b"I":
                    if not self.config.menu_enabled or packet != b"I" + struct.pack("<HHHH", self.config.menu_abi_version, 512, 240, 16):
                        raise BridgeError("menu capability disagrees with verified manifest")
                    if bridge.menu_session is not None:
                        raise BridgeError("menu capability was repeated")
                    from .menu_session import MenuSession
                    bridge.menu_session = MenuSession(self, bridge)
                    continue
                if packet[:1] == b"J":
                    if bridge.menu_session is None:
                        raise BridgeError("menu request arrived before its verified capability")
                    try:
                        bridge.menu_session.feed(packet[1:])
                    except ValueError as error:
                        raise BridgeError("invalid native menu request") from error
                    continue
                if len(packet) != 21 or packet[:1] != b"P":
                    raise BridgeError("expected one bounded local pose")
                pose = Pose.unpack(packet[1:])
                previous = self._local_pose
                if previous is not None:
                    epoch_distance = (pose.map_epoch - previous.map_epoch) & _UINT32
                    frame_distance = (pose.frame - previous.frame) & _UINT32
                    if epoch_distance >= 0x80000000 or frame_distance >= 0x80000000:
                        continue
                    if not epoch_distance and not frame_distance:
                        continue
                    if not epoch_distance and (pose.map_group, pose.map_number) != (previous.map_group, previous.map_number):
                        continue
                self._local_pose = pose
                self._last_pose_time = asyncio.get_running_loop().time()
        except (BridgeError, MailboxError, ConnectionError, OSError, asyncio.TimeoutError):
            pass
        finally:
            if bridge is not None:
                bridge.outbox.close()
                if self._bridge is bridge:
                    self._bridge = None
                    self._last_pose_time = 0.0
                    self._fail_save_requests("local game bridge disconnected")
                    if self.config.trade_enabled:
                        # A new emulator incarnation must never inherit an old
                        # two-party confirmation bound to this network lease.
                        # Cold recovery still belongs to the launcher gate.
                        self._disconnect_remote()
                        if self._remote_writer is not None:
                            self._remote_writer.close()
                if bridge.writer_task is not None:
                    bridge.writer_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await bridge.writer_task
                if bridge.menu_session is not None:
                    await bridge.menu_session.close()
                if bridge.reset_session is not None:
                    await bridge.reset_session.close()
            writer.close()
            try:
                with suppress(ConnectionError, OSError, asyncio.TimeoutError):
                    await asyncio.wait_for(writer.wait_closed(), self.config.send_timeout)
            finally:
                self._ipc_writers.discard(writer)
                self._ipc_handlers.discard(task)

    async def _write_bridge(self, bridge: BridgeSession) -> None:
        try:
            while True:
                frame = await bridge.outbox.get()
                if frame is None:
                    return
                bridge.writer.write(frame)
                await asyncio.wait_for(bridge.writer.drain(), self.config.send_timeout)
        except (ConnectionError, OSError, asyncio.TimeoutError):
            bridge.writer.close()

    def _fail_save_requests(self, message: str) -> None:
        for _, future in self._save_pending.values():
            if not future.done():
                future.set_exception(ConnectionError(message))
        self._save_pending.clear()
        for _, future in self._battle_pending.values():
            if not future.done():
                future.set_exception(ConnectionError(message))
        self._battle_pending.clear()

    @property
    def save_incarnation(self) -> int:
        if self._bridge is None or not self._bridge.save_capable:
            raise ConnectionError("the running game has no verified live-save bridge")
        return self._bridge.incarnation

    def _guard_pending_trade_mutation(self, *, allow_battle_owner=False) -> None:
        """A durable unresolved trade owns mutations between coordinator calls."""
        from .battle_journal import pending_battle
        battle_owner = getattr(self, "_live_battle_owner", None)
        if (battle_owner is not None or pending_battle(self)) and not (allow_battle_owner
                and battle_owner is asyncio.current_task()
                and self._live_save_owner is asyncio.current_task()):
            raise ValueError("pending battle recovery owns this character's mutations")
        pending = getattr(self, "_live_trade_pending_path", None)
        if (pending is not None and Path(pending).exists()
                and self._live_save_owner is not asyncio.current_task()):
            raise ValueError("pending trade recovery owns this character's mutations")

    async def save_rpc(self, control: Any, *, timeout: float = 12.0):
        """One reliable command to the ROM-owned save mailbox, never save RAM."""
        from .save_mailbox import Opcode
        if getattr(control, "opcode", None) == Opcode.READ_WINDOW:
            self._guard_pending_trade_mutation()
            raise ValueError("use save_window_rpc for the separately verified read-only window")
        return await self._save_rpc(control, timeout=timeout)

    async def save_window_rpc(self, control, *, timeout=12.0):
        from .save_mailbox import Opcode
        self._guard_pending_trade_mutation()
        if (getattr(control, "opcode", None) != Opcode.READ_WINDOW or not self.config.save_window_enabled
                or self._bridge is None or not self._bridge.window_capable):
            raise ValueError("read window requires its verified capability and opcode")
        return await self._save_rpc(control, timeout=timeout)

    async def _save_rpc(self, control, *, timeout):
        from .save_mailbox import Opcode, SaveControl
        if not isinstance(control, SaveControl):
            raise ValueError("save command must be a validated SaveControl")
        control.validate_command()
        if control.opcode >= Opcode.BEGIN_EMERGENCY_EXPORT:
            # Capability advertisement alone never grants destructive/offline
            # lifecycle authority. A dedicated controller is required later.
            raise ValueError("emergency operations require their dedicated preservation controller")
        if control.opcode not in {Opcode.QUERY, Opcode.QUERY_OWNERSHIP, Opcode.QUERY_TRADE}:
            self._guard_pending_trade_mutation()
        if Opcode.BEGIN_TRADE_EXPORT <= control.opcode <= Opcode.QUERY_TRADE and not self.config.trade_enabled:
            raise ValueError("the verified game build has no trade hold capability")
        bridge = self._bridge
        if (not self.connected or bridge is None or not bridge.save_capable
                or control.incarnation != bridge.incarnation or control.session_epoch != self.session_epoch):
            raise ConnectionError("live-save command has no matching active session")
        if self._save_pending:
            raise ValueError("a live-save command is already pending")
        return await self._dispatch_save_control(bridge, control, timeout)

    async def emergency_save_rpc(self, authority, control, *, timeout=12.0):
        """Retained same-core authority permits preservation only after loss.

        The token is issued by EmergencySaveController after authenticated
        pre-arming. It cannot grant reconnect, binding, import, END or CANCEL.
        """
        from .save_mailbox import Opcode, SaveControl
        if (authority is None or authority is not self._emergency_authority
                or self._live_save_owner is not asyncio.current_task()):
            raise ValueError("emergency preservation requires its retained lifecycle owner")
        if not isinstance(control, SaveControl):
            raise ValueError("emergency command must be a validated SaveControl")
        control.validate_command()
        allowed = {Opcode.BEGIN_EMERGENCY_EXPORT, Opcode.PROMOTE_EMERGENCY_EXPORT,
                   Opcode.PRESERVE_EMERGENCY, Opcode.QUERY_EMERGENCY, Opcode.READ, Opcode.READ_WINDOW}
        if control.opcode not in allowed:
            raise ValueError("emergency authority cannot release, rebind or mutate canonical state")
        bridge = self._bridge
        if (self.connected or not self._reconnect_blocked or bridge is None
                or bridge is not authority.bridge or not bridge.emergency_save_capable
                or not bridge.save_capable or self.config.emergency_save_abi_version != 2
                or (control.incarnation, control.session_epoch) != (authority.session[2], authority.session[1])
                or (control.request_id, control.revision) != (authority.operation_id, authority.base_revision + 1)):
            raise ConnectionError("emergency authority no longer names the retained disconnected core")
        if control.opcode == Opcode.READ_WINDOW and (not self.config.save_window_enabled or not bridge.window_capable):
            raise ValueError("emergency Flash window requires its separately verified capability")
        if self._save_pending:
            raise ValueError("a live-save command is already pending")
        return await self._dispatch_save_control(bridge, control, timeout)

    async def _dispatch_save_control(self, bridge, control, timeout):
        future = asyncio.get_running_loop().create_future()
        self._save_pending[control.sequence] = (control, future)
        try:
            bridge.outbox.put_control(b"C" + control.pack())
            return await asyncio.wait_for(future, timeout)
        finally:
            self._save_pending.pop(control.sequence, None)
            if not future.done():
                future.cancel()

    def _receive_save_response(self, payload: bytes, bridge: BridgeSession, *, window=None) -> None:
        from .save_mailbox import SaveControl, Opcode, Status
        try:
            response = SaveControl.unpack(payload).validate_response()
        except ValueError as error:
            raise BridgeError("invalid live-save response") from error
        pending = self._save_pending.get(response.sequence)
        if pending is None:
            return  # Timed-out response or ROM watchdog notification.
        command, future = pending
        fields = ("incarnation", "session_epoch", "request_id", "sequence", "total_size", "revision", "opcode")
        if bridge is not self._bridge or any(getattr(response, key) != getattr(command, key) for key in fields):
            raise BridgeError("live-save response does not match its request")
        if response.opcode == Opcode.READ_WINDOW:
            if ((response.status == Status.OK and (window is None or response.offset != command.offset))
                    or (response.status != Status.OK and window is not None)):
                raise BridgeError("read window response lacks its matching bounded bytes")
        elif window is not None:
            raise BridgeError("unexpected Flash window for another save command")
        if not future.done():
            future.set_result((response, window or b"") if response.opcode == Opcode.READ_WINDOW else response)

    @property
    def battle_incarnation(self) -> int:
        if self._bridge is None or not self._bridge.battle_capable:
            raise ConnectionError("the running game has no verified diagnostic channel")
        return self._bridge.incarnation

    async def battle_rpc(self, control, *, timeout=5.0):
        """Explicit development mailbox access, gated by the verified ROM ABI.

        Native envelopes do not provide consent, canonical-roster validation or
        world-server routing; those belong to the native battle coordinator.
        """
        from .battle_mailbox import BattleControl, Opcode
        from .native_battle import NativeControl, supports_native_phase
        if (not self.config.development_battle_channel
                or not isinstance(control, (BattleControl, NativeControl))
                or (isinstance(control, NativeControl) and not supports_native_phase(self.config.battle_abi_version, control.phase))):
            raise ValueError("battle channel requires explicit development opt-in and a matching ABI control")
        control.validate_command(player_id=self.config.player_id)
        if control.opcode != Opcode.QUERY:
            self._guard_pending_trade_mutation(allow_battle_owner=True)
            from .battle_journal import pending_battle
            from .battle_session import NativeBattleSession
            executor = getattr(self, "_live_battle_executor", None)
            execution_authority = (isinstance(executor, NativeBattleSession)
                                   and executor._authorizes(control))
            if ((getattr(self, "_live_battle_owner", None) is not None or pending_battle(self))
                    and control != getattr(self, "_live_battle_admission_control", None)
                    and not execution_authority):
                raise ValueError("pending battle admission permits only its exact persisted BIND")
            if self._live_save_owner is not None and self._live_save_owner is not asyncio.current_task():
                raise ValueError("a live-save lifecycle owns this character's mutations")
        bridge = self._bridge
        if (not self.connected or self.world_id is None or bridge is None or not bridge.battle_capable
                or control.incarnation != bridge.incarnation or control.session_epoch != self.session_epoch):
            raise ConnectionError("diagnostic command has no matching authenticated session")
        if self._battle_pending:
            raise ValueError("a diagnostic command is already pending")
        if type(timeout) not in (float, int) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError("diagnostic timeout must be finite and at most 30 seconds")
        future = asyncio.get_running_loop().create_future()
        self._battle_pending[control.sequence] = (control, future)
        try:
            bridge.outbox.put_control(b"D" + control.pack())
            return await asyncio.wait_for(future, timeout)
        finally:
            self._battle_pending.pop(control.sequence, None)
            if not future.done():
                future.cancel()

    def _receive_battle_response(self, payload, bridge):
        from .battle_mailbox import BattleControl
        from .native_battle import NativeControl, supports_native_phase
        try:
            phase = payload[38] if len(payload) > 38 else 0
            codec = NativeControl if supports_native_phase(self.config.battle_abi_version, phase) else BattleControl
            response = codec.unpack(payload).validate_response()
            pending = self._battle_pending.get(response.sequence)
            if pending is None:
                return
            command, future = pending
            response.validate_response(command)
        except ValueError as error:
            raise BridgeError("invalid or uncorrelated diagnostic response") from error
        if bridge is not self._bridge:
            raise BridgeError("diagnostic response belongs to an old bridge")
        if not future.done():
            future.set_result(response)

    async def _send_remote(self, writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
        async with self._remote_lock:
            writer.write(encode_message(message))
            await asyncio.wait_for(writer.drain(), self.config.send_timeout)

    def _disconnect_remote(self) -> None:
        controller = self._emergency_controller
        if self.connected and controller is not None and self._bridge is not None and not self._closing:
            # Synchronous notification fences reconnect before authentication
            # fields are cleared. The controller owns/drains its async task.
            self._reconnect_blocked = True
            controller.connection_lost()
        self._fail_save_requests("world session disconnected during live-save operation")
        if self.connected or self._players:
            self._roster_epoch = self._roster_epoch % _UINT32 + 1
        self.connected = False
        self.session_epoch = None
        self.world_id = self.server_epoch = self.save_profile = None
        for _, _, future in self._checkpoint_pending.values():
            if not future.done():
                future.set_exception(ConnectionError("checkpoint connection lost; query the canonical revision before retrying"))
        self._checkpoint_pending.clear()
        for _, future in self._trade_pending.values():
            if not future.done():
                future.set_exception(ConnectionError("trade connection lost; obtain authoritative fate before releasing the game"))
        self._trade_pending.clear()
        for _, future in self._team_pending.values():
            if not future.done():
                future.set_exception(ConnectionError("team connection lost; query membership after reconnect"))
        self._team_pending.clear()
        for _, future in self._challenge_pending.values():
            if not future.done():
                future.set_exception(ConnectionError("battle connection lost; query the challenge after reconnect"))
        self._challenge_pending.clear()
        for _, future in self._reset_pending.values():
            if not future.done():
                future.set_exception(ConnectionError("personal encounter admission lost its host connection"))
        self._reset_pending.clear()
        self._players = []
        self._peer_history.clear()
        self._roster_signature = None
        self._publish_snapshot()

    async def _remote_loop(self) -> None:
        while not self._closing:
            if self._reconnect_blocked:
                return
            try:
                await self._remote_once()
            except (ProtocolError, ConnectionError, OSError, asyncio.TimeoutError) as error:
                self.last_error = error.code if isinstance(error, ProtocolError) else type(error).__name__
            finally:
                self._disconnect_remote()
            if not self._closing:
                await asyncio.sleep(self.config.reconnect_delay)

    async def _remote_once(self) -> None:
        writer: asyncio.StreamWriter | None = None
        tasks: list[asyncio.Task] = []
        try:
            tls = self.config.server_tls
            tls_options = {} if tls is None else {
                "ssl": self._server_tls_context, "server_hostname": self.config.server_host,
                "ssl_handshake_timeout": tls.handshake_timeout,
                "ssl_shutdown_timeout": tls.shutdown_timeout,
            }
            connect_timeout = min(self.config.handshake_timeout, tls.handshake_timeout) if tls else self.config.handshake_timeout
            reader, writer = await asyncio.wait_for(asyncio.open_connection(
                self.config.server_host, self.config.server_port, limit=16_388, **tls_options), connect_timeout)
            if tls is not None:
                # Verify after TLS chain validation and before constructing or
                # sending hello, which may contain the player's credential.
                tls.verify_peer(writer)
            self._remote_writer = writer
            hello = {
                "type": "hello", "protocol": PROTOCOL_VERSION,
                "build_id": self.config.build_id, "ruleset_id": self.config.ruleset_id,
                "player_id": self.config.player_id, "display_name": self.config.display_name,
            }
            if self.config.server_credential is not None:
                hello["credential"] = self.config.server_credential.hex()
            await self._send_remote(writer, hello)
            welcome = await asyncio.wait_for(read_message(reader), self.config.handshake_timeout)
            if welcome is None:
                raise ConnectionError("server closed before welcome")
            if welcome.get("type") == "error":
                raise ProtocolError("server_rejected", "server rejected this client")
            welcome = validate_welcome(welcome, self.config)
            self.session_epoch = welcome["session_epoch"]
            self.world_id = welcome.get("world_id")
            self.server_epoch = welcome.get("server_epoch")
            self.save_profile = welcome.get("save_profile")
            self.connected = True
            self.last_error = None
            self._network_seq = self._network_map_epoch = 0
            self._sent_pose_signature = self._sent_source_signature = None
            self._last_world_seq = 0
            self._publish_snapshot()
            tasks = [
                asyncio.create_task(self._read_world(reader, writer), name="companion-world-reader"),
                asyncio.create_task(self._send_presence(writer), name="companion-presence-sender"),
            ]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await task
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if writer is not None:
                writer.close()
                with suppress(ConnectionError, OSError, asyncio.TimeoutError):
                    await asyncio.wait_for(writer.wait_closed(), self.config.send_timeout)
            if self._remote_writer is writer:
                self._remote_writer = None

    async def _send_presence(self, writer: asyncio.StreamWriter) -> None:
        while True:
            pose = self._local_pose
            if pose is not None:
                fresh = self._bridge is not None and asyncio.get_running_loop().time() - self._last_pose_time <= self.config.pause_timeout
                fields = pose.network_fields(fresh)
                source_signature = (self._bridge_incarnation, pose.map_epoch, pose.map_group, pose.map_number)
                pose_signature = (source_signature, pose.frame, tuple(fields.values()))
                if pose_signature != self._sent_pose_signature:
                    if self._sent_source_signature is not None and source_signature != self._sent_source_signature:
                        self._network_map_epoch += 1
                    self._network_seq += 1
                    if self._network_seq > MAX_COUNTER or self._network_map_epoch > MAX_COUNTER:
                        raise ProtocolError("counter_exhausted", "reconnect before transport counters overflow")
                    await self._send_remote(writer, {
                        "type": "presence", "session_epoch": self.session_epoch,
                        "seq": self._network_seq, "map_epoch": self._network_map_epoch,
                        **fields,
                    })
                    self._sent_source_signature = source_signature
                    self._sent_pose_signature = pose_signature
            await asyncio.sleep(self.config.pose_interval)

    async def _read_world(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            message = await asyncio.wait_for(read_message(reader), self.config.remote_timeout)
            if message is None:
                raise ConnectionError("server disconnected")
            if message.get("type") == "ping":
                heartbeat = validate_heartbeat(message, self.session_epoch)
                await self._send_remote(writer, {**heartbeat, "type": "pong"})
            elif message.get("type") == "world":
                self._apply_world(message)
            elif message.get("type") in {"checkpoint_result", "checkpoint_error"}:
                self._receive_checkpoint(message)
            elif message.get("type") in {"team_result", "team_error"}:
                self._receive_team(message)
            elif message.get("type") in {"trade_result", "trade_error"}:
                self._receive_trade(message)
            elif message.get("type") in {"reset_result", "reset_error"}:
                self._receive_reset(message)
            elif message.get("type") in {"battle_result", "battle_error"}:
                self._receive_challenge(message)
            else:
                raise ProtocolError("invalid_server_message", "unexpected server message type")

    async def team_rpc(self, operation: str, *, request_id: str | None = None,
                       timeout: float = 5.0, **fields: Any) -> dict[str, Any]:
        """Explicit session-local development teams; no game ABI is required."""
        from .ownership_protocol import OWNERSHIP_PROFILE
        from .team_protocol import TEAM_OPERATIONS, validate_team_request
        if not isinstance(operation, str) or operation not in TEAM_OPERATIONS:
            raise ValueError("unsupported team operation")
        if (type(timeout) not in (int, float) or not 0 < timeout <= 60
                or not math.isfinite(timeout)):
            raise ValueError("team RPC timeout must be finite and between 0 and 60 seconds")
        if (not self.connected or self.world_id is None or self._remote_writer is None
                or self.config.server_credential is None or self.save_profile != OWNERSHIP_PROFILE):
            raise ConnectionError("no authenticated ownership team session")
        if set(fields) & {"type", "session_epoch"}:
            raise ValueError("team envelope fields cannot be overridden")
        if request_id is None:
            request_id = str(uuid4())
        request = dict(type="team_" + operation, session_epoch=self.session_epoch,
                       request_id=request_id, **fields)
        validate_team_request(request, self.session_epoch)
        if request_id in self._team_pending or len(self._team_pending) >= 8:
            raise ValueError("team request is pending or capacity is exhausted")
        future = asyncio.get_running_loop().create_future()
        self._team_pending[request_id] = (request, future)
        try:
            await self._send_remote(self._remote_writer, request)
            return await asyncio.wait_for(future, timeout)
        finally:
            self._team_pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    def _receive_team(self, message):
        from .team_protocol import validate_team_reply
        validated = validate_team_reply(message, self.config.player_id, self.world_id, self.session_epoch)
        pending = self._team_pending.get(validated["request_id"])
        if pending is None:
            return  # Lost/late replies require an explicit status reconciliation.
        request, future = pending
        validate_team_reply(validated, self.config.player_id, self.world_id, self.session_epoch, request)
        if not future.done():
            if validated["type"] == "team_error":
                future.set_exception(TeamError(validated["code"], validated["message"]))
            else:
                future.set_result(validated)

    async def reset_rpc(self, *, request_id=None, timeout=5.0, **fields):
        from .reset_protocol import validate_reset_request
        from .ownership_protocol import OWNERSHIP_PROFILE
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError("personal encounter RPC timeout is invalid")
        if (not self.connected or self.world_id is None or self._remote_writer is None
                or self.config.server_credential is None or self.save_profile != OWNERSHIP_PROFILE):
            raise ConnectionError("no authenticated personal encounter session")
        if set(fields) & {"type", "session_epoch", "request_id"}:
            raise ValueError("personal encounter envelope cannot be overridden")
        request_id = str(uuid4()) if request_id is None else request_id
        request = dict(type="reset_begin", session_epoch=self.session_epoch, request_id=request_id, **fields)
        validate_reset_request(request, self.session_epoch)
        if request_id in self._reset_pending or len(self._reset_pending) >= 4:
            raise ValueError("personal encounter request is pending or capacity is exhausted")
        future = asyncio.get_running_loop().create_future()
        self._reset_pending[request_id] = (request, future)
        try:
            await self._send_remote(self._remote_writer, request)
            return await asyncio.wait_for(future, timeout)
        finally:
            self._reset_pending.pop(request_id, None)
            if not future.done(): future.cancel()

    def _receive_reset(self, message):
        from .reset_protocol import validate_reset_reply
        validated = validate_reset_reply(message, self.config.player_id, self.world_id, self.session_epoch)
        pending = self._reset_pending.get(validated["request_id"])
        if pending is None: return
        request, future = pending
        validate_reset_reply(validated, self.config.player_id, self.world_id, self.session_epoch, request)
        if not future.done():
            if validated["type"] == "reset_error":
                future.set_exception(ProtocolError(validated["code"], validated["message"]))
            else:
                future.set_result(validated)

    async def battle_challenge_rpc(self, operation: str, *, request_id: str | None = None,
                                   timeout: float = 5.0, **fields: Any) -> dict[str, Any]:
        """Authenticated consent only; native execution has a separate owner."""
        from .ownership_protocol import OWNERSHIP_PROFILE
        from .battle_protocol import BATTLE_OPERATIONS, validate_battle_request
        if not isinstance(operation, str) or operation not in BATTLE_OPERATIONS:
            raise ValueError("unsupported battle challenge operation")
        if type(timeout) not in (int, float) or not 0 < timeout <= 60 or not math.isfinite(timeout):
            raise ValueError("battle challenge timeout must be finite and between 0 and 60 seconds")
        if (not self.connected or self.world_id is None or self._remote_writer is None
                or self.config.server_credential is None or self.save_profile != OWNERSHIP_PROFILE):
            raise ConnectionError("no authenticated ownership battle session")
        if set(fields) & {"type", "session_epoch"}:
            raise ValueError("battle envelope fields cannot be overridden")
        request_id = str(uuid4()) if request_id is None else request_id
        request = dict(type="battle_" + operation, session_epoch=self.session_epoch,
                       request_id=request_id, **fields)
        validate_battle_request(request, self.session_epoch)
        if request_id in self._challenge_pending or len(self._challenge_pending) >= 8:
            raise ValueError("battle challenge request is pending or capacity is exhausted")
        future = asyncio.get_running_loop().create_future()
        self._challenge_pending[request_id] = (request, future)
        try:
            await self._send_remote(self._remote_writer, request)
            return await asyncio.wait_for(future, timeout)
        finally:
            self._challenge_pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    def _receive_challenge(self, message):
        from .battle_protocol import validate_battle_reply
        validated = validate_battle_reply(message, self.config.player_id, self.world_id, self.session_epoch)
        pending = self._challenge_pending.get(validated["request_id"])
        if pending is None:
            return
        request, future = pending
        validate_battle_reply(validated, self.config.player_id, self.world_id, self.session_epoch, request)
        if not future.done():
            if validated["type"] == "battle_error":
                future.set_exception(BattleChallengeError(validated["code"], validated["message"]))
            else:
                future.set_result(validated)

    async def trade_rpc(self, operation: str, *, request_id: str | None = None,
                        timeout: float = 5.0, **fields: Any) -> dict[str, Any]:
        """Explicit development trade controls over the authenticated reader."""
        from .trade_protocol import TRADE_OPERATIONS, validate_trade_request
        if operation in {"open", "offer", "confirm", "cancel", "ack"}:
            self._guard_pending_trade_mutation()
        if not self.config.trade_enabled or operation not in TRADE_OPERATIONS:
            raise ValueError("trade operation requires a verified trade-capable build")
        if not self.connected or self.world_id is None or self._remote_writer is None:
            raise ConnectionError("no authenticated trade session")
        if set(fields) & {"type", "session_epoch"}:
            raise ValueError("trade envelope fields cannot be overridden")
        if self._live_save_owner is not None and self._live_save_owner is not asyncio.current_task() and operation not in {"status", "pending", "proposals"}:
            raise ValueError("a live-save lifecycle owns this character's mutations")
        request_id = request_id or str(uuid4())
        if request_id in self._trade_pending or len(self._trade_pending) >= 8:
            raise ValueError("trade request is pending or capacity is exhausted")
        request = dict(type="trade_" + operation, session_epoch=self.session_epoch,
                       request_id=request_id, **fields)
        validate_trade_request(request, self.session_epoch)
        future = asyncio.get_running_loop().create_future()
        self._trade_pending[request_id] = (request, future)
        try:
            await self._send_remote(self._remote_writer, request)
            return await asyncio.wait_for(future, timeout)
        finally:
            self._trade_pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    def _receive_trade(self, message):
        from .trade_protocol import validate_trade_reply
        validated = validate_trade_reply(message, self.config, self.save_profile, self.world_id, self.session_epoch)
        pending = self._trade_pending.get(validated["request_id"])
        if pending is None:
            return  # A timed-out RPC remains uncertain until an explicit status.
        request, future = pending
        if (validated["operation"] != request["type"].removeprefix("trade_")
                or validated["session_epoch"] != request["session_epoch"]
                or (validated["type"] == "trade_result" and "transaction_id" in request
                    and validated["trade"]["transaction_id"] != request["transaction_id"])):
            raise ProtocolError("invalid_server_message", "trade reply does not match its request")
        if not future.done():
            if validated["type"] == "trade_error":
                future.set_exception(TradeError(validated["code"], validated["message"]))
            else:
                future.set_result(validated)

    async def checkpoint_rpc(self, operation: str, *, request_id: str | None = None, timeout: float = 5.0, **fields: Any) -> dict[str, Any]:
        """Use the existing reader so heartbeat/presence continue during transfers."""
        from .protocol import validate_checkpoint_request
        if operation in {"begin", "chunk", "commit", "abort", "ownership_grant"}:
            self._guard_pending_trade_mutation()
        if (self._live_save_owner is not None and self._live_save_owner is not asyncio.current_task()
                and operation in {"begin", "chunk", "commit", "abort", "ownership_grant"}):
            raise ValueError("a live-save lifecycle owns this character's checkpoint writes")
        if set(fields) & {"type", "session_epoch"}:
            raise ValueError("checkpoint envelope fields cannot be overridden")
        if not self.connected or self.world_id is None or self._remote_writer is None:
            raise ConnectionError("no authenticated checkpoint session")
        request_id = request_id or str(uuid4())
        if request_id in self._checkpoint_pending:
            raise ValueError("checkpoint request is already pending")
        if len(self._checkpoint_pending) >= 8:
            raise ValueError("checkpoint request capacity is exhausted")
        epoch = self.session_epoch
        message = {"type": operation if operation == "ownership_grant" else "checkpoint_" + operation,
                   "session_epoch": epoch, "request_id": request_id, **fields}
        validate_checkpoint_request(message, epoch)
        future = asyncio.get_running_loop().create_future()
        self._checkpoint_pending[request_id] = (operation, epoch, future)
        try:
            await self._send_remote(self._remote_writer, message)
            return await asyncio.wait_for(future, timeout)
        finally:
            self._checkpoint_pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    def _receive_checkpoint(self, message: dict[str, Any]) -> None:
        from .checkpoint_client import validate_checkpoint_reply, CheckpointError
        if message.get("operation") == "ownership_grant":
            from .ownership_protocol import validate_ownership_reply
            validated = validate_ownership_reply(message, self.config, self.save_profile, self.world_id, self.session_epoch)
        else:
            validated = validate_checkpoint_reply(message, self.config, self.session_epoch, self.save_profile)
        pending = self._checkpoint_pending.get(validated["request_id"])
        # An RPC can time out while its reply remains queued. Never interpret
        # this as a fresh operation or replace the canonical save automatically.
        if pending is None:
            return
        operation, epoch, future = pending
        if validated["operation"] != operation or validated["session_epoch"] != epoch:
            raise ProtocolError("invalid_server_message", "checkpoint reply does not match its request")
        if not future.done():
            if validated["type"] == "checkpoint_error":
                future.set_exception(CheckpointError(validated["code"], validated["message"]))
            else:
                future.set_result(validated)

    def _apply_world(self, message: dict[str, Any]) -> None:
        players = validate_world(message, self.config, self.session_epoch)
        if message["world_seq"] <= self._last_world_seq:
            return
        history = {}
        for player in players:
            presence = player["presence"]
            if presence is None:
                continue
            key = (player["player_id"], player["session_epoch"])
            previous = self._peer_history.get(key)
            if previous is not None:
                changed_map = (presence["map_group"], presence["map_number"]) != (previous["map_group"], previous["map_number"])
                if presence["seq"] < previous["seq"] or presence["map_epoch"] < previous["map_epoch"] or (changed_map and presence["map_epoch"] <= previous["map_epoch"]):
                    raise ProtocolError("stale_server_presence", "server presence ordering is invalid")
                if presence["seq"] == previous["seq"]:
                    # The server may mark an unchanged pose unavailable after
                    # its game timeout. It cannot rewrite coordinates or resume
                    # gameplay under the same client sequence.
                    unchanged = all(presence[name] == value for name, value in previous.items() if name != "activity")
                    safe_activity = presence["activity"] == previous["activity"] or presence["activity"] == "unavailable"
                    if not unchanged or not safe_activity:
                        raise ProtocolError("stale_server_presence", "server rewrote a pose without advancing its sequence")
            history[key] = presence
        signature = tuple((player["player_id"], player["session_epoch"]) for player in players)
        if signature != self._roster_signature:
            self._roster_epoch = self._roster_epoch % _UINT32 + 1
            self._roster_signature = signature
        self._players, self._peer_history = players, history
        self._last_world_seq = message["world_seq"]
        self._publish_snapshot()


async def _run(config: CompanionConfig) -> None:
    companion = Companion(config)
    await companion.start()
    print(f"Verified baseline mailbox companion at {companion.ipc_address[0]}:{companion.ipc_address[1]}", flush=True)
    print("Local/LAN presence prototype. No game saves or completed Gen 6 profile.", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await companion.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--player-id", required=True, help="canonical UUID of this separate client profile")
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--token-hex", required=True, help="64 hex characters of a generated 32-byte loopback token")
    parser.add_argument("--server-host", default="127.0.0.1")
    parser.add_argument("--server-port", type=int, default=8765)
    parser.add_argument("--ipc-port", type=int, default=8870)
    args = parser.parse_args()
    try:
        token = bytes.fromhex(args.token_hex)
        config = CompanionConfig(
            args.rom, args.manifest, args.player_id, args.display_name, token,
            server_host=args.server_host, server_port=args.server_port,
            ipc_port=args.ipc_port,
        )
        asyncio.run(_run(config))
    except (ValueError, ProtocolError, OSError) as error:
        parser.error(str(error))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
