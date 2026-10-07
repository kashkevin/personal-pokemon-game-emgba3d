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
from typing import Any
import zlib

from .bridge_protocol import BridgeError, LatestPacket, read_packet
from .mailbox import ABI_VERSION, CONNECTED, MAILBOX_SIZE, MailboxError, Peer, Pose, Snapshot
from .protocol import (
    MAX_COUNTER, MAX_PLAYERS, PROTOCOL_VERSION, ProtocolError, encode_message,
    read_message, validate_heartbeat, validate_hello, validate_presence,
)
from .server import is_local_address

BASELINE_RULESET = "baseline-rhh1.17.1-mailbox-v1"
_UINT32 = 0xFFFFFFFF


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
    build_id: str = field(init=False)
    ruleset_id: str = field(init=False, default=BASELINE_RULESET)

    def __post_init__(self) -> None:
        rom_path, manifest_path = Path(self.rom_path).resolve(), Path(self.manifest_path).resolve()
        object.__setattr__(self, "rom_path", rom_path)
        object.__setattr__(self, "manifest_path", manifest_path)
        build_id, _ = verify_rom_manifest(rom_path, manifest_path)
        object.__setattr__(self, "build_id", build_id)
        validate_hello({
            "type": "hello", "protocol": PROTOCOL_VERSION, "build_id": build_id,
            "ruleset_id": self.ruleset_id, "player_id": self.player_id,
            "display_name": self.display_name,
        }, build_id, self.ruleset_id)
        if not isinstance(self.token, bytes) or len(self.token) != 32:
            raise ValueError("IPC token must contain exactly 32 random bytes")
        if not is_local_address(self.ipc_host):
            raise ValueError("binary IPC must bind a numeric loopback address")
        if not is_local_address(self.server_host, allow_lan=True):
            raise ValueError("this prototype connects only to numeric local/LAN server addresses")
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
    _fields(message, {
        "type", "protocol", "build_id", "ruleset_id", "player_id", "session_epoch",
        "max_players", "heartbeat_interval", "idle_timeout",
    }, "welcome")
    if message["build_id"] != config.build_id or message["ruleset_id"] != config.ruleset_id:
        raise ProtocolError("identity_mismatch", "server build/ruleset is incompatible")
    if message["player_id"] != config.player_id:
        raise ProtocolError("identity_mismatch", "server assigned another player identity")
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
    outbox: LatestPacket
    incarnation: int
    writer_task: asyncio.Task[None] | None = None


class Companion:
    def __init__(self, config: CompanionConfig) -> None:
        self.config = config
        self.connected = False
        self.session_epoch: int | None = None
        self.last_error: str | None = None
        self._ipc_server: asyncio.Server | None = None
        self._remote_task: asyncio.Task[None] | None = None
        self._snapshot_task: asyncio.Task[None] | None = None
        self._remote_writer: asyncio.StreamWriter | None = None
        self._remote_lock = asyncio.Lock()
        self._bridge: BridgeSession | None = None
        self._bridge_incarnation = 0
        self._ipc_writers: set[asyncio.StreamWriter] = set()
        self._ipc_handlers: set[asyncio.Task] = set()
        self._closing = False
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
            if self._closing or peer is None or not is_local_address(peer[0]) or len(self._ipc_writers) > 4:
                return
            packet = await asyncio.wait_for(read_packet(reader), self.config.handshake_timeout)
            if packet is None or len(packet) != 33 or packet[:1] != b"H" or not hmac.compare_digest(packet[1:], self.config.token):
                return
            if self._bridge is not None:
                return
            self._bridge_incarnation += 1
            bridge = BridgeSession(writer, LatestPacket(), self._bridge_incarnation)
            self._bridge = bridge
            self._local_pose = None
            self._last_pose_time = 0.0
            bridge.writer_task = asyncio.create_task(self._write_bridge(bridge), name="companion-bridge-writer")
            self._publish_snapshot()
            while not writer.is_closing():
                packet = await read_packet(reader)
                if packet is None:
                    break
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
                if bridge.writer_task is not None:
                    bridge.writer_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await bridge.writer_task
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

    async def _send_remote(self, writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
        async with self._remote_lock:
            writer.write(encode_message(message))
            await asyncio.wait_for(writer.drain(), self.config.send_timeout)

    def _disconnect_remote(self) -> None:
        if self.connected or self._players:
            self._roster_epoch = self._roster_epoch % _UINT32 + 1
        self.connected = False
        self.session_epoch = None
        self._players = []
        self._peer_history.clear()
        self._roster_signature = None
        self._publish_snapshot()

    async def _remote_loop(self) -> None:
        while not self._closing:
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
            reader, writer = await asyncio.wait_for(asyncio.open_connection(self.config.server_host, self.config.server_port, limit=16_388), self.config.handshake_timeout)
            self._remote_writer = writer
            await self._send_remote(writer, {
                "type": "hello", "protocol": PROTOCOL_VERSION,
                "build_id": self.config.build_id, "ruleset_id": self.config.ruleset_id,
                "player_id": self.config.player_id, "display_name": self.config.display_name,
            })
            welcome = await asyncio.wait_for(read_message(reader), self.config.handshake_timeout)
            if welcome is None:
                raise ConnectionError("server closed before welcome")
            if welcome.get("type") == "error":
                raise ProtocolError("server_rejected", "server rejected this client")
            welcome = validate_welcome(welcome, self.config)
            self.session_epoch = welcome["session_epoch"]
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
            else:
                raise ProtocolError("invalid_server_message", "unexpected server message type")

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
