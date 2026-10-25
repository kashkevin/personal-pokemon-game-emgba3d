"""Verified-ROM companion connecting a loopback binary bridge to the world server.

Rulesets distinguish the inherited baseline and the ROM-verified Gen6 defaults
profile. Neither claims a completed content catalogue. This component never
writes ROM/RAM or save files.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from dataclasses import dataclass, field, replace
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import struct
import time
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
from . import connection_diagnostics as _diagnostics
from .battle_manifest import validate_battle_manifest
from .save_window import validate_window_manifest, WINDOW_FRAME_SIZE

BASELINE_RULESET = "baseline-rhh1.17.1-mailbox-v1"
_UINT32 = 0xFFFFFFFF
# A shared-world action the host never received is forwarded again after this long.
_ACTION_RETRY_SECONDS = 1.0


class ServerRejected(ProtocolError):
    """The world server answered the hello with an error message. ``server_code`` is its code and ``reason`` the
    connection_diagnostics code a person is shown (rejected_public_exposure_disabled, version_mismatch, ...)."""

    def __init__(self, server_code: Any) -> None:
        super().__init__("server_rejected", "server rejected this client")
        self.server_code = server_code if type(server_code) is str and 0 < len(server_code) <= 64 else "unknown"
        self.reason = _diagnostics.rejection_code(self.server_code)


def _identity_error(code: str, message: str, reason: str) -> ProtocolError:
    error = ProtocolError(code, message)
    error.reason = reason
    return error


class TeamError(ValueError):
    """A server refusal; connection loss/timeout instead leaves RPC fate unknown."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class TradeError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class LobbyError(ValueError):
    """A host's refusal of a battle lobby operation (Update 32); a transport failure leaves its fate unknown."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class BattleChallengeError(ValueError):
    """Authoritative consent refusal; transport failure still has unknown fate."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def verify_rom_manifest(rom_path: Path, manifest_path: Path) -> tuple[str, dict[str, Any]]:
    """Hash the supplied game bytes; manifest identity alone is never trusted.

    ``rom_path`` is the GBA ROM, or in a packaged native installation the package's game facts
    (game_facts.py: recorded from the ROM when the package was built and bound to these exact
    manifest bytes). Facts have no ROM bytes to hash: the identity comes from the facts, every
    capability is checked against the manifest alone, and the caller's pins
    (GameInstallation.verify: the manifest hash, and the runtime bundle that pins the facts file)
    establish that the pair is the package's own. The build id is the same ROM SHA-256 either way.
    """
    if manifest_path.stat().st_size > 65_536:
        raise ValueError("manifest exceeds its size limit")
    with manifest_path.open("rb") as source:
        raw_manifest = source.read(65_537)
    if len(raw_manifest) > 65_536:
        raise ValueError("manifest exceeds its size limit")
    manifest = json.loads(raw_manifest.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    if type(manifest.get("abi_version")) is not int or manifest["abi_version"] != ABI_VERSION:
        raise ValueError("manifest ABI is incompatible")
    if type(manifest.get("mailbox_size")) is not int or manifest["mailbox_size"] != MAILBOX_SIZE:
        raise ValueError("manifest mailbox size is incompatible")
    from .gen6_profile import GEN6_DEFAULTS_RULESET
    if manifest.get("ruleset_id") not in (BASELINE_RULESET, GEN6_DEFAULTS_RULESET):
        raise ValueError("manifest ruleset is not a supported game profile")
    expected_hash = manifest.get("rom_sha256")
    if not isinstance(expected_hash, str) or re.fullmatch("[0-9a-f]{64}", expected_hash) is None:
        raise ValueError("manifest ROM SHA256 is invalid")
    from .game_facts import is_game_facts, load_facts
    facts = load_facts(rom_path, raw_manifest, manifest) if is_game_facts(rom_path) else None
    size = facts.rom_size if facts is not None else rom_path.stat().st_size
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
    if facts is None:
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
        game = rom_path
    else:
        # load_facts bound the facts to these manifest bytes, their ROM SHA-256, size and CRC32.
        actual_hash, game = facts.rom_sha256, None
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
        if game is not None:
            with game.open("rb") as source:
                source.seek(marker - 0x08000000)
                if source.read(4) != b"\x01\x00\x00\x00":
                    raise ValueError("trade capability marker does not match the verified ROM")
    validate_battle_manifest(manifest, game)
    validate_window_manifest(manifest, game)
    from .menu_mailbox import validate_menu_manifest
    validate_menu_manifest(manifest, game)
    from .reset_mailbox import validate_reset_manifest
    validate_reset_manifest(manifest, game)
    from .emergency_protocol import validate_emergency_manifest
    validate_emergency_manifest(manifest, game)
    from .trade_effect_mailbox import validate_effect_prepare_manifest, validate_effect_save_manifest, validate_effect_choice_manifest
    validate_effect_prepare_manifest(manifest, game)
    validate_effect_save_manifest(manifest, game)
    validate_effect_choice_manifest(manifest, game)
    from .trade_replay_manifest import validate_trade_replay_manifest
    validate_trade_replay_manifest(manifest, game)
    from .presence_animation import validate_presence_animation_manifest
    validate_presence_animation_manifest(manifest, game)
    from .gen6_profile import validate_generation_profile
    validate_generation_profile(manifest, game)
    from .player_build import validate_player_build_manifest
    validate_player_build_manifest(manifest, game)
    from .world_mailbox import validate_world_manifest
    validate_world_manifest(manifest, game)
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
    # TCP connect + TLS handshake (+ the relay's answer) for one attempt: the same budget as the menu's connection check, so a
    # route the check reached is not given up by the game sooner (connection_diagnostics.DEFAULT_TIMEOUT).
    connect_timeout: float = _diagnostics.DEFAULT_TIMEOUT
    remote_timeout: float = 20.0
    send_timeout: float = 1.0
    server_credential: bytes | None = field(default=None, repr=False)
    server_tls: ClientTlsConfig | None = None
    public_server: bool = False
    expected_world_id: str | None = None
    development_battle_channel: bool = False
    # A relay route (relay.py): connect to the relay and ask for the expected world's room; TLS and the pin stay end to end.
    relay_host: str | None = None
    relay_port: int | None = None
    build_id: str = field(init=False)
    ruleset_id: str = field(init=False, default=BASELINE_RULESET)
    save_enabled: bool = field(init=False, default=False)
    ownership_enabled: bool = field(init=False, default=False)
    trade_enabled: bool = field(init=False, default=False)
    trade_effect_prepare_abi_version: int = field(init=False, default=0)
    trade_effect_save_abi_version: int = field(init=False, default=0)
    trade_effect_choice_abi_version: int = field(init=False, default=0)
    presence_animation_abi_version: int = field(init=False, default=0)
    presence_detail_abi_version: int = field(init=False, default=0)
    battle_enabled: bool = field(init=False, default=False)
    battle_ffa_enabled: bool = field(init=False, default=False)   # the ROM can run the four-player free-for-all (phase 5)
    battle_ffa3_enabled: bool = field(init=False, default=False)  # ... and the three-player one (1v1v1, phase 6)
    battle_abi_version: int = field(init=False, default=0)
    battle_resume_abi_version: int = field(init=False, default=0)
    battle_admission_cleanup_abi_version: int = field(init=False, default=0)
    save_window_enabled: bool = field(init=False, default=False)
    reset_enabled: bool = field(init=False, default=False)
    reset_abi_version: int = field(init=False, default=0)
    reset_input_abi_version: int = field(init=False, default=0)
    reset_catalogue_version: int = field(init=False, default=0)
    reset_source_mask: int | None = field(init=False, default=None)
    reset_control_flags: int | None = field(init=False, default=None)
    reset_build_flags: int | None = field(init=False, default=None)
    menu_enabled: bool = field(init=False, default=False)
    menu_abi_version: int = field(init=False, default=1)
    menu_release_abi_version: int = field(init=False, default=0)   # PC game: a refused Enter battle releases its window
    save_import_window_abi_version: int = field(init=False, default=0)  # PC game: a trade's save a 4 KiB sector at a time
    save_party_query_abi_version: int = field(init=False, default=0)  # PC game: QUERY_PARTY (KNOWN_ISSUES MS-60)
    menu_open_page_abi_version: int = field(init=False, default=0)  # PC game: a Players OPEN may name a page (soft reset)
    emergency_save_enabled: bool = field(init=False, default=False)
    emergency_save_abi_version: int = field(init=False, default=0)
    world_enabled: bool = field(init=False, default=False)
    rival_abi_version: int = field(init=False, default=0)
    tower_abi_version: int = field(init=False, default=0)  # PC game: Battle Tower: Legends (bridge.txt tower=1)
    host_save_page_abi_version: int = field(init=False, default=0)  # PC game: an in-game SAVE saves on the host (MS-61)
    battle_peek_abi_version: int = field(init=False, default=0)  # PC game: battle PEEK, pushed observations (MS-62)
    battle_receive_many_abi_version: int = field(init=False, default=0)  # PC game: RECEIVE_MANY (MS-62)
    battle_deliver_abi_version: int = field(init=False, default=0)  # PC game: DELIVER (MS-62, battle speed)
    tower_next_page_abi_version: int = field(init=False, default=0)  # PC game: the Tower's "go on?" page 4

    def __post_init__(self) -> None:
        rom_path, manifest_path = Path(self.rom_path).resolve(), Path(self.manifest_path).resolve()
        object.__setattr__(self, "rom_path", rom_path)
        object.__setattr__(self, "manifest_path", manifest_path)
        build_id, manifest = verify_rom_manifest(rom_path, manifest_path)
        object.__setattr__(self, "build_id", build_id)
        object.__setattr__(self, "ruleset_id", manifest["ruleset_id"])
        object.__setattr__(self, "save_enabled", "save_mailbox_address" in manifest)
        object.__setattr__(self, "ownership_enabled", manifest.get("ownership_abi_version") == 1)
        object.__setattr__(self, "trade_enabled", manifest.get("trade_abi_version") == 1)
        object.__setattr__(self, "trade_effect_prepare_abi_version", manifest.get("trade_effect_prepare_abi_version", 0))
        object.__setattr__(self, "trade_effect_save_abi_version", manifest.get("trade_effect_save_abi_version", 0))
        object.__setattr__(self, "trade_effect_choice_abi_version", manifest.get("trade_effect_choice_abi_version", 0))
        object.__setattr__(self, "presence_animation_abi_version", manifest.get("presence_animation_abi_version", 0))
        # The PC game says why it is off the field (in battle, a menu, changing area) in its pose's last byte.
        detail = manifest.get("presence_detail_abi_version")
        object.__setattr__(self, "presence_detail_abi_version", 1 if type(detail) is int and detail == 1 else 0)
        object.__setattr__(self, "battle_enabled", manifest.get("battle_abi_version") in (1, 2, 3))
        object.__setattr__(self, "battle_abi_version", manifest.get("battle_abi_version", 0))
        object.__setattr__(self, "battle_ffa_enabled", manifest.get("battle_ffa_abi_version") == 1
                           and manifest.get("battle_abi_version") == 3)
        object.__setattr__(self, "battle_ffa3_enabled", self.battle_ffa_enabled
                           and manifest.get("battle_ffa3_abi_version") == 1)
        object.__setattr__(self, "battle_resume_abi_version", manifest.get("battle_resume_abi_version", 0))
        object.__setattr__(self, "battle_admission_cleanup_abi_version", manifest.get("battle_admission_cleanup_abi_version", 0))
        object.__setattr__(self, "menu_enabled", manifest.get("menu_abi_version") in (1, 2))
        object.__setattr__(self, "menu_abi_version", manifest.get("menu_abi_version", 1))
        # The native PC game ends a latched Enter battle window on a release screen (flags 3) when the companion
        # refused that Enter before any ADMIT; without it (an older game) a refusal still leaves the window waiting.
        release = manifest.get("menu_release_abi_version")
        object.__setattr__(self, "menu_release_abi_version", 1 if type(release) is int and release == 1
                           and manifest.get("menu_abi_version") == 2 and manifest.get("battle_resume_abi_version") == 1 else 0)
        object.__setattr__(self, "save_window_enabled", manifest.get("save_window_abi_version") == 1)
        # The native PC game stages an import a sector per frame ('i', WRITE_WINDOW); others take 1024 WRITEs.
        import_window = manifest.get("save_import_window_abi_version")
        object.__setattr__(self, "save_import_window_abi_version", 1 if type(import_window) is int and import_window == 1
                           and manifest.get("save_window_abi_version") == 1 else 0)
        # KNOWN_ISSUES MS-60: the PC game answers what a battle preparation checks (party_identity.py).
        party_query = manifest.get("save_party_query_abi_version")
        object.__setattr__(self, "save_party_query_abi_version", 1 if type(party_query) is int and party_query == 1
                           and manifest.get("save_abi_version") == 1 else 0)
        # Update 32: the PC game's soft reset key (MS-61) opens the Players menu on its soft reset page (the
        # launcher opts in with bridge.txt menu_open_page=1, bridge_config.configure_native).
        from .bridge_config import menu_open_page_enabled
        object.__setattr__(self, "menu_open_page_abi_version", 1 if menu_open_page_enabled(manifest) else 0)
        from .bridge_config import host_save_page_enabled
        object.__setattr__(self, "host_save_page_abi_version", 1 if host_save_page_enabled(manifest) else 0)
        # KNOWN_ISSUES MS-62: the PC game's battle PEEK (the launcher opts in with bridge.txt battle_peek=1): this game's
        # launcher sends its core's state and each new block to the host as they happen (battle_session.py).
        from .bridge_config import battle_peek_enabled
        object.__setattr__(self, "battle_peek_abi_version", 1 if battle_peek_enabled(manifest) else 0)
        from .bridge_config import battle_receive_many_enabled
        object.__setattr__(self, "battle_receive_many_abi_version", 1 if battle_receive_many_enabled(manifest) else 0)
        from .bridge_config import battle_deliver_enabled
        object.__setattr__(self, "battle_deliver_abi_version", 1 if battle_deliver_enabled(manifest) else 0)
        object.__setattr__(self, "reset_enabled", manifest.get("reset_abi_version") in (1, 2))
        object.__setattr__(self, "reset_abi_version", manifest.get("reset_abi_version", 0))
        object.__setattr__(self, "reset_input_abi_version", manifest.get("reset_input_abi_version", 0))
        object.__setattr__(self, "reset_catalogue_version", manifest.get("reset_catalogue_version", 0))
        object.__setattr__(self, "reset_source_mask", manifest.get("reset_source_mask"))
        object.__setattr__(self, "reset_control_flags", manifest.get("reset_control_flags"))
        object.__setattr__(self, "reset_build_flags", manifest.get("reset_build_flags"))
        object.__setattr__(self, "emergency_save_enabled", manifest.get("emergency_save_abi_version") in (1, 2))
        object.__setattr__(self, "emergency_save_abi_version", manifest.get("emergency_save_abi_version", 0))
        from .world_mailbox import validate_world_manifest
        object.__setattr__(self, "world_enabled", validate_world_manifest(manifest))
        # Update 31: an engine that reads the rival record in the world mailbox says so in its manifest.
        object.__setattr__(self, "rival_abi_version", manifest.get("rival_abi_version", 0)
                           if self.world_enabled and manifest.get("rival_abi_version") == 1 else 0)
        # Battle Tower: Legends: the game's Tower screens, world action 7 and reward words 6-7 (the launcher opts in with
        # bridge.txt tower=1, bridge_config.configure_native); without them none of it is ever sent to the game.
        from .bridge_config import tower_enabled
        object.__setattr__(self, "tower_abi_version", 1 if self.world_enabled and tower_enabled(manifest) else 0)
        # ... and its "go on to floor N?" after a solo floor: OPEN page 4 (bridge.txt tower_next_page=1).
        from .bridge_config import tower_next_page_enabled
        object.__setattr__(self, "tower_next_page_abi_version",
                           1 if self.tower_abi_version == 1 and tower_next_page_enabled(manifest) else 0)
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
        if self.relay_host is not None or self.relay_port is not None:
            from .relay import valid_endpoint
            if (not valid_endpoint(self.relay_host, self.relay_port) or self.server_tls is None
                    or self.server_credential is None or self.expected_world_id is None):
                raise ValueError("a relay route requires a valid relay address, pinned TLS, a credential and the expected world")
        for name in (
            "pause_timeout", "pose_interval", "snapshot_interval", "reconnect_delay",
            "handshake_timeout", "remote_timeout", "send_timeout", "connect_timeout",
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
            raise _identity_error("identity_mismatch", "durable world requires a player credential", "wrong_world")
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
        raise _identity_error("identity_mismatch", "authenticated client requires a durable world", "wrong_world")
    _fields(message, names, "welcome")
    if message["build_id"] != config.build_id or message["ruleset_id"] != config.ruleset_id:
        raise _identity_error("identity_mismatch", "server build/ruleset is incompatible", "version_mismatch")
    if message["player_id"] != config.player_id:
        raise _identity_error("identity_mismatch", "server assigned another player identity", "wrong_world")
    if config.expected_world_id is not None and message.get("world_id") != config.expected_world_id:
        raise _identity_error("identity_mismatch", "server world differs from the expected durable world", "wrong_world")
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
    names = {"type", "protocol", "world_seq", "players", "clock", "event", "notice", "wallet", "teammate", "spawns"}
    # "extras" (secret bases and the PokeNav view) is the one optional field: older hosts omit it.
    _fields(message, names | ({"extras"} if "extras" in message else set()), "world")
    from .shared_world_protocol import (validate_clock, validate_event, validate_extras, validate_notice,
                                        validate_appearance_hex, validate_spawns, validate_teammate, validate_wallet)
    validate_extras(message.get("extras"))
    validate_spawns(message["spawns"])
    validate_clock(message["clock"])
    validate_event(message["event"])
    validate_notice(message["notice"])
    validate_wallet(message["wallet"], tower=getattr(config, "tower_abi_version", 0) == 1)
    validate_teammate(message["teammate"])
    _integer(message["world_seq"], 1, MAX_COUNTER, "world_seq")
    players = message["players"]
    if not isinstance(players, list) or not 1 <= len(players) <= MAX_PLAYERS:
        raise ProtocolError("invalid_server_message", "server roster exceeds its bounds")
    validated = []
    seen = set()
    for player in players:
        if not isinstance(player, dict) or set(player) != {"player_id", "display_name", "session_epoch", "presence", "appearance"}:
            raise ProtocolError("invalid_server_message", "invalid player roster fields")
        validate_appearance_hex(player["appearance"])
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
    trade_effect_prepare_capable: bool = False
    trade_effect_save_capable: bool = False
    trade_effect_choice_capable: bool = False
    window_capable: bool = False
    emergency_save_capable: bool = False
    battle_capable: bool = False
    battle_looks_capable: bool = False
    spawn_capable: bool = False
    extras_capable: bool = False
    menu_session: Any = None
    reset_session: Any = None


class Companion:
    def __init__(self, config: CompanionConfig) -> None:
        self.config = config
        self._server_tls_context = config.server_tls.build_context() if config.server_tls is not None else None
        self.connected = False
        # PokeNav privacy (Update 24, privacy.py): TRUE shares this player's place with the others (the default).
        self.share_location = True
        self._privacy_directory = None
        self.session_epoch: int | None = None
        self.last_error: str | None = None
        # Why the last connection attempt failed, as a connection_diagnostics code (refused, timeout, version_mismatch,
        # rejected_public_exposure_disabled, relay_host_offline, ...), and ``failure_detail`` naming the exception.
        self.failure: str | None = None
        self.failure_detail: str = ""
        # Set when a permanent refusal during the handshake (wrong world, other game version, bad credential, a world closed to
        # this network) ended the reconnect loop: retrying cannot help until a person acts.
        self.stopped: str | None = None
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
        self._lobby_pending: dict[str, tuple[dict, asyncio.Future]] = {}
        self._enrollment_pending: dict[str, tuple[dict, asyncio.Future]] = {}
        self._challenge_pending: dict[str, tuple[dict, asyncio.Future]] = {}
        self._reset_pending: dict[str, tuple[dict, asyncio.Future]] = {}
        self._save_pending: dict[int, tuple[Any, asyncio.Future]] = {}
        self._battle_pending: dict[int, tuple[Any, asyncio.Future]] = {}
        self.live_checkpoint_lock = asyncio.Lock()
        self._live_save_owner: asyncio.Task | None = None
        self._bridge: BridgeSession | None = None
        self._bridge_admission_blocked = False
        self.last_bridge_refusal = None     # why the companion last refused the running game's bridge (diagnostics only)
        self._bridge_incarnation = 0
        self._ipc_writers: set[asyncio.StreamWriter] = set()
        self._ipc_handlers: set[asyncio.Task] = set()
        self._closing = False
        self._emergency_controller = None
        self._emergency_authority = None
        self._reconnect_blocked = False
        self._handshaking = False
        self._battle_recovery_authority = None
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
        # Protocol-2 shared world (EMW1 mailbox).
        self._local_world = None
        self._world_action_sent = 0
        self._world_action_ack = 0
        self._world_clock: dict | None = None
        self._world_clock_time = 0.0
        self._world_event: dict | None = None
        self._world_notice: dict | None = None
        self._local_notice: dict | None = None     # a banner for this player's own game (show_local_notice)
        self._local_notice_id = 0
        self._world_wallet: dict | None = None
        self._world_teammate: str | None = None
        self._world_pending: dict[str, tuple[dict, asyncio.Future]] = {}
        # Protocol-3 shared wild Pokemon (the native game's EMV1 mailbox).
        self._world_spawns: dict | None = None
        self._local_spawn = None
        self._spawn_action_sent = 0
        self._spawn_action_ack = 0
        # Secret Bases and the PokeNav view (the native game's EMX1 mailbox, Phase 6/7).
        self._world_extras: dict | None = None
        self._world_rival = None  # Update 31: world_mailbox.RivalRecord from the host's rival summary
        self._extras_local = None            # the game's latest own-base record
        self._extras_base_ack = 0            # the game's base sequence the host has stored
        self._extras_acked_epoch = None      # ... in this host session
        self._extras_task: asyncio.Task | None = None
        self._extras_records: list[tuple[int, bytes]] = []
        self._extras_cursor = 0
        self._extras_passes = 0
        self._extras_advanced = 0.0
        self._extras_record_seq = 0
        self._extras_current = (0, bytes(160))
        self._extras_sent: bytes | None = None

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
        peers = tuple(Peer(index + 1, self._game_pose(player["presence"]))
            for index, player in enumerate(self._players)
            if player["player_id"] != self.config.player_id and player["presence"] is not None)
        return Snapshot(CONNECTED, self._heartbeat, self._roster_epoch, own_slot, peers)

    def _game_pose(self, presence):
        """A roster player's pose as the game takes it. The game refuses a whole snapshot for one peer off the map's
        grid (a step over a map edge can report -1), so every other player would vanish with it: such a peer stays
        listed, hidden, at the grid's edge, until its next position."""
        pose = Pose.from_presence(presence, presentation_version=self.config.presence_animation_abi_version)
        if pose.x >= 0 and pose.y >= 0:
            return pose
        return replace(pose, x=max(pose.x, 0), y=max(pose.y, 0), activity=0)

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
            if self.config.world_enabled:
                self._bridge.outbox.put_world(b"N" + self.world_inbound().pack())
                if self._bridge.spawn_capable:
                    self._bridge.outbox.put_spawns(b"n" + self.spawn_inbound().pack())
                if self._bridge.extras_capable:
                    packet = b"y" + self.extras_inbound().pack()
                    if packet != self._extras_sent:
                        self._extras_sent = packet
                        self._bridge.outbox.put_extras(packet)

    def spawn_inbound(self):
        """The EMV1 inbound record: the host's shared wild Pokemon of this
        player's map. Enabled only while connected to a world (protocol 3), so
        a disconnected game falls back to its own offline encounters."""
        from .spawn_mailbox import SpawnInbound
        enabled = self.connected and self._roster_signature is not None
        return SpawnInbound.from_view(self._world_spawns if enabled else None, enabled=enabled,
                                      action_ack=self._spawn_action_ack)

    _EXTRAS_PASSES = 4          # each base is offered this many times (the game applies it idempotently)
    _EXTRAS_INTERVAL = 0.25     # seconds between two offered records
    _EXTRAS_REFRESH = 15.0      # then the list is offered once more this often (the game applies a base only
                                # in the calm overworld outside secret bases, so an offer may have to wait)

    def extras_inbound(self):
        """The EMX1 inbound record: one of the host's secret bases for this player
        (or a withdrawal). The game applies a record once per record number and
        a repeat of an unchanged base is a no-op, so the host's list is offered a
        few times over, one record at a time, rather than acknowledged per record."""
        from .extras_mailbox import ExtrasInbound
        enabled = self.connected and self._roster_signature is not None and self._world_extras is not None
        if not enabled:
            self._extras_records, self._extras_passes = [], 0
            return ExtrasInbound(enabled=False, base_ack=self._extras_base_ack)
        records = [(item["slot"], bytes.fromhex(item["record"])) for item in self._world_extras["bases"]]
        if records != self._extras_records:
            self._extras_records, self._extras_cursor, self._extras_passes = records, 0, self._EXTRAS_PASSES
            self._extras_advanced = 0.0
        now = time.monotonic()
        if not self._extras_passes and records and now - self._extras_advanced >= self._EXTRAS_REFRESH:
            self._extras_cursor, self._extras_passes = 0, 1
        if self._extras_passes and records and now - self._extras_advanced >= self._EXTRAS_INTERVAL:
            slot, record = records[self._extras_cursor]
            self._extras_record_seq = self._extras_record_seq % _UINT32 + 1
            self._extras_current = (slot, record)
            self._extras_advanced = now
            self._extras_cursor += 1
            if self._extras_cursor >= len(records):
                self._extras_cursor, self._extras_passes = 0, self._extras_passes - 1
        slot, record = self._extras_current
        return ExtrasInbound(enabled=True, base_ack=self._extras_base_ack,
                             record_seq=self._extras_record_seq if self._extras_record_seq else 0,
                             source_slot=slot, base=record)

    def _offer_bases_again(self) -> None:
        self._extras_passes = self._EXTRAS_PASSES
        self._extras_advanced = 0.0

    def world_inbound(self):
        """The EMW1 inbound record matching the current presence snapshot."""
        from .world_mailbox import (EVENT_BUSY, EVENT_MEGA, EVENT_MINE, EVENT_SHINY, EVENT_VISIBLE,
                                    WorldEventView, WorldInbound, WorldState)
        if not self.connected or self._roster_signature is None:
            return WorldInbound(action_ack=self._world_action_ack)
        own = next((p for p in self._players if p["player_id"] == self.config.player_id), None)
        appearance = bytes.fromhex(own["appearance"]) if own and own.get("appearance") else bytes(8)
        peers = []
        for index, player in enumerate(self._players):
            if player["player_id"] == self.config.player_id or player["presence"] is None:
                continue
            look = bytes.fromhex(player["appearance"]) if player.get("appearance") else bytes(8)
            peers.append((index + 1, WorldState.from_network(player["presence"], look)))
        seconds = 0
        clock = self._world_clock
        if clock is not None:
            seconds = clock["seconds"]
            if clock["running"]:
                from .balance import BALANCE
                elapsed = time.monotonic() - self._world_clock_time
                seconds += int(max(0.0, min(elapsed, 5.0)) * BALANCE.clock_rate)
        event = WorldEventView()
        current = self._world_event
        if current is not None:
            flags = EVENT_VISIBLE | (EVENT_SHINY if current["shiny"] else 0) | (EVENT_MEGA if current["mega"] else 0)
            if current["claimant"] == self.config.player_id:
                flags |= EVENT_MINE
            elif current["claimant"] is not None:
                flags |= EVENT_BUSY
            event = WorldEventView(current["event_id"] & 0xFFFFFFFF, current["species"], current["level"], flags,
                                   current["map_group"], current["map_number"], current["x"], current["y"],
                                   current["held_item"], current["seconds_left"], current["perfect_ivs"])
        notice_id, notice_text = self._host_notice()
        local = self._local_notice
        if local is not None:
            if notice_id not in (0, local["over"]) or time.monotonic() > local["until"]:
                self._local_notice = None             # the host's newer notice replaces it, or it is stale
            else:
                notice_id, notice_text = local["id"], local["text"]
        wallet = self._world_wallet or {"seq": 0, "delta": 0}
        # The teammate is published as its ordinary peer token (EMP1 index+1).
        teammate = next((index + 1 for index, player in enumerate(self._players)
                         if player["player_id"] == self._world_teammate
                         and player["player_id"] != self.config.player_id and player["presence"] is not None), 0)
        outbreak = None
        nav = (self._world_extras or {}).get("nav") or {}
        if (nav.get("outbreak") or {}).get("map") is not None:
            outbreak = tuple(nav["outbreak"]["map"])
        return WorldInbound(clock_valid=clock is not None, events_enabled=True, world_seconds=seconds & 0xFFFFFFFF,
                            action_ack=self._world_action_ack, self_appearance=appearance, peers=tuple(peers),
                            event=event, notice_id=notice_id, notice_text=notice_text,
                            wallet_seq=wallet["seq"], wallet_delta=wallet["delta"], teammate_token=teammate,
                            outbreak=outbreak,
                            rival=self._world_rival if self.config.rival_abi_version == 1 else None,
                            tower=getattr(self.config, "tower_abi_version", 0) == 1)

    def _host_notice(self) -> tuple[int, str]:
        notice = self._world_notice
        if notice is not None and (notice["to"] is None or self.config.player_id in notice["to"]):
            return notice["id"], notice["text"]
        return 0, ""

    def show_local_notice(self, text: str, *, seconds: float = 120.0) -> None:
        """A banner in this player's own game only, shown as the host's notices are (Update 32: the soft reset says
        what it did). The host's next notice replaces it, and it is dropped after `seconds` (a game that has not had a
        calm field by then). Its ids have the top bit set, which the host's never have (shared_world.post_notice), so
        the game cannot take one for a notice it has already shown."""
        self._local_notice_id = self._local_notice_id % 0x7FFFFFFF + 1
        self._local_notice = {"id": 0x80000000 | self._local_notice_id, "text": text,
                              "over": self._host_notice()[0], "until": time.monotonic() + seconds}

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
        refusal = None
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
                if packet[:1] == b"K":
                    from .trade_effect_mailbox import capability_packet
                    if (not bridge.save_capable or self.config.trade_effect_prepare_abi_version != 1
                            or packet != capability_packet()):
                        raise BridgeError("record preparation differs from verified manifest")
                    bridge.trade_effect_prepare_capable = True
                    continue
                if packet[:1] == b"L":
                    from .trade_effect_mailbox import save_capability_packet
                    if (not bridge.trade_effect_prepare_capable or not bridge.window_capable
                            or self.config.trade_effect_save_abi_version != 1 or packet != save_capability_packet()):
                        raise BridgeError("native save candidate differs from verified manifest")
                    bridge.trade_effect_save_capable = True
                    continue
                if packet[:1] == b"O":
                    from .trade_effect_mailbox import choice_capability_packet
                    if (not bridge.trade_effect_prepare_capable or self.config.trade_effect_choice_abi_version != 1
                            or packet != choice_capability_packet()):
                        raise BridgeError("native move presentation differs from verified manifest")
                    bridge.trade_effect_choice_capable = True
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
                        response, window = parse_window_packet(packet, allow_effect_save=bridge.trade_effect_save_capable)
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
                if packet[:1] == b"A":
                    # The native PC game draws the other players' characters in
                    # battles from their looks (battle_looks.py); mgba.lua never
                    # announces it.
                    from .battle_looks import capability_packet as looks_capability
                    if not bridge.battle_capable or bridge.battle_looks_capable or packet != looks_capability():
                        raise BridgeError("battle looks capability differs from this companion")
                    bridge.battle_looks_capable = True
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
                if packet[:1] == b"w":
                    # The native PC game announces its shared-spawn mailbox
                    # (spawn_mailbox.py); mgba.lua never does.
                    from .spawn_mailbox import capability_packet as spawn_capability
                    if not self.config.world_enabled or bridge.spawn_capable or packet != spawn_capability():
                        raise BridgeError("shared spawn capability differs from this companion")
                    bridge.spawn_capable = True
                    # A new game (or the same one on a new bridge) announces the
                    # mailbox: forward its current action again unless the host
                    # has already answered it (the ack guard below; M19).
                    self._spawn_action_sent = 0
                    self._publish_snapshot()
                    continue
                if packet[:1] == b"e":
                    # The native PC game announces its secret-base mailbox
                    # (extras_mailbox.py); mgba.lua never does.
                    from .extras_mailbox import capability_packet as extras_capability
                    if not self.config.world_enabled or bridge.extras_capable or packet != extras_capability():
                        raise BridgeError("secret base capability differs from this companion")
                    bridge.extras_capable = True
                    self._offer_bases_again()
                    self._extras_sent = None
                    self._publish_snapshot()
                    continue
                if packet[:1] == b"x":
                    from .extras_mailbox import ExtrasLocal, ExtrasMailboxError
                    if not bridge.extras_capable or len(packet) != 169:
                        raise BridgeError("secret base record precedes its capability")
                    try:
                        self._extras_local = ExtrasLocal.unpack(packet[1:])
                    except ExtrasMailboxError as error:
                        raise BridgeError("invalid secret base record") from error
                    self._start_base_publish()
                    continue
                if packet[:1] == b"g":
                    from .spawn_mailbox import SpawnLocal, SpawnMailboxError
                    if not bridge.spawn_capable or len(packet) != 117:
                        raise BridgeError("shared spawn record precedes its capability")
                    try:
                        local = SpawnLocal.unpack(packet[1:])
                    except SpawnMailboxError as error:
                        raise BridgeError("invalid shared spawn record") from error
                    self._local_spawn = local
                    action = local.action
                    if (action.seq != 0 and action.kind != 0 and action.seq != self._spawn_action_sent
                            and action.seq != self._spawn_action_ack):
                        self._spawn_action_sent = action.seq
                        self._spawn_spawn_action(action)
                    continue
                if packet[:1] == b"G":
                    from .world_mailbox import WorldMailboxError, unpack_local
                    if not self.config.world_enabled or len(packet) != 33:
                        raise BridgeError("shared-world state disagrees with verified manifest")
                    try:
                        state, action = unpack_local(packet[1:])
                    except WorldMailboxError as error:
                        raise BridgeError("invalid shared-world state") from error
                    self._local_world = state
                    if (action.seq != 0 and action.kind != 0 and action.seq != self._world_action_sent
                            and action.seq != self._world_action_ack):
                        self._world_action_sent = action.seq
                        self._spawn_world_action(action)
                    continue
                if len(packet) != 21 or packet[:1] != b"P":
                    raise BridgeError("expected one bounded local pose")
                pose = Pose.unpack(packet[1:], presentation_version=self.config.presence_animation_abi_version,
                                   detail_version=self.config.presence_detail_abi_version)
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
        except (BridgeError, MailboxError) as error:
            # The game said something this companion refuses (a capability its manifest does not have, a malformed record):
            # kept for whoever has to find out why the game keeps reconnecting.
            refusal = self.last_bridge_refusal = f"{type(error).__name__}: {error}"
        except (ConnectionError, OSError, asyncio.TimeoutError):
            pass
        finally:
            if bridge is not None:
                bridge.outbox.close()
                if self._bridge is bridge:
                    self._bridge = None
                    self._last_pose_time = 0.0
                    self._fail_save_requests("local game bridge disconnected" + (f" (refused: {refusal})" if refusal else ""))
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

    async def live_party_identity(self, *, timeout: float = 5.0):
        """KNOWN_ISSUES MS-60: what the running game's next battle PREPARE will compare (party_identity.PartyIdentity),
        under the live-save binding battle admission requires; None when the game cannot say (no QUERY_PARTY in its
        build, no binding, another save command pending, the mailbox busy) - the claim then goes as before."""
        from uuid import uuid4
        from .party_identity import PartyIdentity
        from .save_mailbox import FLASH_SIZE, Opcode, SaveControl, Status
        bridge, binding = self._bridge, getattr(self, "_live_binding", None)
        if (self.config.save_party_query_abi_version != 1 or not self.connected or bridge is None
                or not bridge.save_capable or binding is None or binding[2] != bridge.incarnation or self._save_pending):
            return None
        control = SaveControl(binding[2], binding[1], str(uuid4()), 1, 0, FLASH_SIZE, 0, Opcode.QUERY_PARTY)
        try:
            response = await self._dispatch_save_control(bridge, control.validate_command(), timeout)
            return PartyIdentity.unpack(response.data) if response.status == Status.OK else None
        except (asyncio.TimeoutError, ValueError, ConnectionError, BridgeError):
            return None

    async def save_window_rpc(self, control, *, timeout=12.0):
        from .save_mailbox import Opcode
        self._guard_pending_trade_mutation()
        if (getattr(control, "opcode", None) != Opcode.READ_WINDOW or not self.config.save_window_enabled
                or self._bridge is None or not self._bridge.window_capable):
            raise ValueError("read window requires its verified capability and opcode")
        return await self._save_rpc(control, timeout=timeout)

    async def save_import_window_rpc(self, control, sector, *, timeout=12.0):
        """WRITE_WINDOW: one staged import sector, for a PC game whose manifest has the import window."""
        from .save_mailbox import Opcode, SaveControl, import_window_packet
        if (not isinstance(control, SaveControl) or control.opcode != Opcode.WRITE_WINDOW
                or self.config.save_import_window_abi_version != 1):
            raise ValueError("import window requires its verified capability and opcode")
        frame = import_window_packet(control, sector)
        self._guard_pending_trade_mutation()
        bridge = self._bridge
        if (not self.connected or bridge is None or not bridge.save_capable
                or control.incarnation != bridge.incarnation or control.session_epoch != self.session_epoch):
            raise ConnectionError("live-save command has no matching active session")
        if self._save_pending:
            raise ValueError("a live-save command is already pending")
        return await self._dispatch_save_control(bridge, control, timeout, frame=frame)

    async def _save_rpc(self, control, *, timeout):
        from .save_mailbox import Opcode, SaveControl
        if not isinstance(control, SaveControl):
            raise ValueError("save command must be a validated SaveControl")
        control.validate_command()
        if control.opcode == Opcode.WRITE_WINDOW:
            raise ValueError("use save_import_window_rpc for an import window")
        if control.opcode == Opcode.QUERY_PARTY:
            raise ValueError("use live_party_identity for the party query")
        if control.opcode >= Opcode.BEGIN_EFFECT_RECORD:
            raise ValueError("record preparation requires its dedicated retained trade authority")
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

    async def trade_effect_rpc(self, authority, control, *, timeout=12.0):
        """Private record/choice operations only, under the original held trade."""
        from .save_mailbox import SaveControl, Opcode
        from .trade_effect_mailbox import OPS
        from .trade_effect_session import HeldTradeEffectClient
        if (type(authority) is not HeldTradeEffectClient or not isinstance(control, SaveControl)
                or control.opcode not in OPS or not authority.authorizes(self, control)):
            raise ValueError("record preparation lacks its exact retained trade authority")
        control.validate_command()
        self._guard_pending_trade_mutation()
        bridge = self._bridge
        if (self.config.trade_effect_prepare_abi_version != 1 or not self.connected or bridge is None
                or not bridge.save_capable or not bridge.trade_effect_prepare_capable
                or control.incarnation != bridge.incarnation or control.session_epoch != self.session_epoch):
            raise ConnectionError("record preparation has no verified live capability")
        if control.opcode in (Opcode.BEGIN_EFFECT_SAVE, Opcode.READ_EFFECT_WINDOW) and (self.config.trade_effect_save_abi_version != 1
                or not bridge.trade_effect_save_capable or not bridge.window_capable):
            raise ValueError("full save candidate requires its separately verified window capability")
        if control.opcode == Opcode.QUERY_EFFECT_CHOICE and (self.config.trade_effect_choice_abi_version != 1
                or not bridge.trade_effect_choice_capable):
            raise ValueError("native move presentation requires its separately verified capability")
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

    async def _dispatch_save_control(self, bridge, control, timeout, *, frame=None):
        future = asyncio.get_running_loop().create_future()
        self._save_pending[control.sequence] = (control, future)
        try:
            if frame is None:
                bridge.outbox.put_control(b"C" + control.pack())
            else:
                bridge.outbox.put_control(frame, maximum=len(frame))
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
        window_op = response.opcode in (Opcode.READ_WINDOW, Opcode.READ_EFFECT_WINDOW)
        if window_op:
            if ((response.status == Status.OK and (window is None or response.offset != command.offset))
                    or (response.status != Status.OK and window is not None)):
                raise BridgeError("read window response lacks its matching bounded bytes")
        elif window is not None:
            raise BridgeError("unexpected Flash window for another save command")
        if not future.done():
            future.set_result((response, window or b"") if window_op else response)

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
        from .native_battle import FFA3_PHASE, NativeControl, supports_native_phase
        from .native_battle import Opcode as NativeOpcode
        if (not self.config.development_battle_channel
                or not isinstance(control, (BattleControl, NativeControl))
                or (isinstance(control, NativeControl) and control.opcode > 13
                    and self.config.battle_resume_abi_version != 1)
                or (isinstance(control, NativeControl) and control.opcode > 21
                    and control.opcode not in (NativeOpcode.PEEK, NativeOpcode.RECEIVE_MANY, NativeOpcode.DELIVER)
                    and getattr(self.config, "battle_admission_cleanup_abi_version", 0) != 1)
                or (isinstance(control, NativeControl) and control.opcode == NativeOpcode.PEEK
                    and getattr(self.config, "battle_peek_abi_version", 0) != 1)
                or (isinstance(control, NativeControl) and control.opcode == NativeOpcode.RECEIVE_MANY
                    and getattr(self.config, "battle_receive_many_abi_version", 0) != 1)
                or (isinstance(control, NativeControl) and control.opcode == NativeOpcode.DELIVER
                    and getattr(self.config, "battle_deliver_abi_version", 0) != 1)
                or (isinstance(control, NativeControl) and control.opcode == Opcode.BIND
                    and len(control.data) == 116 and control.data[115]
                    and self.config.battle_resume_abi_version != 1)
                or (isinstance(control, NativeControl) and not supports_native_phase(self.config.battle_abi_version, control.phase))
                # Update 32: an older game has no 1v1v1 (its bridge would close on the first phase 6 command).
                or (isinstance(control, NativeControl) and control.phase == FFA3_PHASE
                    and not getattr(self.config, "battle_ffa3_enabled", False))):
            raise ValueError("battle channel requires explicit development opt-in and a matching ABI control")
        control.validate_command(player_id=self.config.player_id)
        if control.opcode != Opcode.QUERY and not (isinstance(control, NativeControl)
                                                    and control.opcode == NativeOpcode.PEEK):  # observations change nothing
            from .battle_journal import pending_battle
            from .battle_session import NativeBattleSession
            from .battle_recovery_session import NativeBattleRecoverySession
            from .battle_terminal import BattleHandoffAuthority
            from .battle_admission_session import AdmissionHoldAuthority
            from .battle_admission_cleanup import AdmissionCleanupSession, AdmissionCleanupHandoffAuthority
            from .battle_admission_cleanup import AdmissionCleanupReadinessAuthority
            from .battle_admission_cleanup import AdmissionCleanupOfflineHoldAuthority
            executor = getattr(self, "_live_battle_executor", None)
            execution_authority = (isinstance(executor, (NativeBattleSession, NativeBattleRecoverySession,
                                                        BattleHandoffAuthority, AdmissionHoldAuthority,
                                                        AdmissionCleanupSession, AdmissionCleanupHandoffAuthority,
                                                        AdmissionCleanupOfflineHoldAuthority))
                                   and executor._authorizes(control))
            readiness = getattr(self, "_live_battle_cleanup_readiness", None)
            cleanup_observation = (isinstance(control, NativeControl) and control.opcode == 24
                and type(readiness) is AdmissionCleanupReadinessAuthority and readiness._authorizes(control))
            if not cleanup_observation:
                self._guard_pending_trade_mutation(allow_battle_owner=True)
            execution_authority = execution_authority or cleanup_observation
            if isinstance(control, NativeControl) and control.opcode in (19, 20, 21, 22, 23, 24) and not execution_authority:
                raise ValueError("battle hold transitions require their exact persisted lifecycle authority")
            if ((getattr(self, "_live_battle_owner", None) is not None or pending_battle(self))
                    and control != getattr(self, "_live_battle_admission_control", None)
                    and not execution_authority):
                raise ValueError("pending battle admission permits only its exact persisted BIND")
            if self._live_save_owner is not None and self._live_save_owner is not asyncio.current_task() and not cleanup_observation:
                raise ValueError("a live-save lifecycle owns this character's mutations")
        bridge = self._bridge
        original_admission = (isinstance(control, NativeControl) and control.opcode == 19
            and execution_authority and isinstance(executor, AdmissionHoldAuthority))
        original_admission = original_admission or (isinstance(control, NativeControl) and control.opcode == 22
            and execution_authority and type(executor) is AdmissionCleanupOfflineHoldAuthority)
        if (not original_admission and (not self.connected or self.world_id is None or bridge is None or not bridge.battle_capable
                or control.incarnation != bridge.incarnation or control.session_epoch != self.session_epoch)):
            raise ConnectionError("diagnostic command has no matching authenticated session")
        if self._battle_pending:
            raise ValueError("a diagnostic command is already pending")
        if type(timeout) not in (float, int) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError("diagnostic timeout must be finite and at most 30 seconds")
        future = asyncio.get_running_loop().create_future()
        self._battle_pending[control.sequence] = (control, future)
        try:
            bridge.outbox.put_control(b"D" + control.pack())
            response = await asyncio.wait_for(future, timeout)
        finally:
            self._battle_pending.pop(control.sequence, None)
            if not future.done():
                future.cancel()
        self._send_battle_looks(bridge, control, response)
        return response

    def _send_battle_looks(self, bridge, control, response) -> None:
        """After the native PC game binds a battle: its players' looks (battle_looks.py).

        Cosmetic and best effort: it never delays, changes or fails a battle
        command; without room in the bridge queue the game shows default trainers.
        """
        from .battle_looks import looks_packet
        from .native_battle import NativeControl, Opcode as NativeOpcode
        if (not bridge.battle_looks_capable or bridge is not self._bridge or bridge.outbox.closed
                or not isinstance(control, NativeControl) or control.opcode != NativeOpcode.BIND
                or response.status != 0 or len(bridge.outbox.controls) >= bridge.outbox.limit):
            return
        try:
            bridge.outbox.put_control(looks_packet(control.data, self._battle_looks_roster()))
        except ValueError:
            return

    def _battle_looks_roster(self) -> tuple[dict[str, Any], ...]:
        """The host's roster: each player's id and look, as the overworld shows them."""
        return tuple(self._players)

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
        from .battle_journal import pending_battle, path_present
        try:
            terminal = getattr(self, "_live_battle_terminal_pending_path", None)
            if pending_battle(self) or (terminal is not None and path_present(terminal)):
                self._reconnect_blocked = True
        except ValueError:
            self._reconnect_blocked = True
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
        for _, future in self._lobby_pending.values():
            if not future.done():
                future.set_exception(ConnectionError("lobby connection lost; read the lobbies after reconnect"))
        self._lobby_pending.clear()
        for _, future in self._enrollment_pending.values():
            if not future.done():
                future.set_exception(ConnectionError("enrollment connection lost; ask for the account's state after reconnect"))
        self._enrollment_pending.clear()
        for _, future in self._challenge_pending.values():
            if not future.done():
                future.set_exception(ConnectionError("battle connection lost; query the challenge after reconnect"))
        self._challenge_pending.clear()
        for _, future in self._reset_pending.values():
            if not future.done():
                future.set_exception(ConnectionError("personal encounter admission lost its host connection"))
        self._reset_pending.clear()
        for _, future in self._world_pending.values():
            if not future.done():
                future.set_exception(ConnectionError("shared-world request lost its host connection"))
        self._world_pending.clear()
        self._world_clock = self._world_event = self._world_notice = self._world_wallet = None
        self._world_teammate = None
        self._world_extras = None
        self._world_rival = None
        self._extras_acked_epoch = None
        self._players = []
        self._peer_history.clear()
        self._roster_signature = None
        self._publish_snapshot()

    def _note_failure(self, error: BaseException, *, handshake: bool) -> None:
        """Record why an attempt failed. A permanent refusal during the handshake stops reconnection (``stopped``); anything
        transient, and anything after a completed handshake, keeps the existing reconnect behaviour."""
        code, detail = _diagnostics.classify(error)
        self.failure, self.failure_detail = code, detail
        if handshake and code in _diagnostics.PERMANENT:
            self.stopped = code

    def _retry_delay(self) -> float:
        # A refusal that clears by itself (a stale session of this player, a full world) is retried calmly, not hammered.
        if self.failure in _diagnostics.HELD:
            return min(max(self.config.reconnect_delay * 4, self.config.reconnect_delay), 2.0)
        return self.config.reconnect_delay

    async def _remote_loop(self) -> None:
        while not self._closing:
            if self._reconnect_blocked:
                return
            try:
                await self._remote_once()
            except (ProtocolError, ConnectionError, OSError, asyncio.TimeoutError) as error:
                self.last_error = error.code if isinstance(error, ProtocolError) else type(error).__name__
                self._note_failure(error, handshake=self._handshaking)
            finally:
                self._disconnect_remote()
            if self.stopped is not None:
                return
            if not self._closing:
                await asyncio.sleep(self._retry_delay())

    def resume_world_connection(self):
        """Reconnect to the world for abandoning an interrupted battle (battle_abandonment.py), or after it.

        The reconnect fence protects a game held in a native battle for same-core recovery. Abandoning gives that
        core up: its battle gets no result and the game is closed and started again from the canonical save. So the
        fence is lifted on request of that abandonment (the held game may still run until the host has answered),
        and after it with no battle intent left. A fresh authentication follows; the held core is never adopted.
        """
        if self._closing:
            raise ConnectionError("the companion is closing")
        if self.stopped is not None:
            raise ConnectionError("the host refused this character's connection")
        self._reconnect_blocked = False
        self._battle_recovery_authority = None
        self._emergency_authority = None
        if self._remote_task is None or self._remote_task.done():
            self._remote_task = asyncio.create_task(self._remote_loop(), name="companion-world-connection")

    async def reconnect_retained_battle(self, recovery):
        """One explicit authenticated reconnect for the exact retained core.

        Generic reconnect remains fenced. A current lifecycle owner, immutable
        original intent and verified optional native marker are all required.
        """
        from .battle_recovery_session import NativeBattleRecoverySession
        from .battle_admission_cleanup import AdmissionCleanupSession
        if not isinstance(recovery, (NativeBattleRecoverySession, AdmissionCleanupSession)) or not recovery._authorizes_reconnect():
            raise ValueError("battle reconnect requires its exact retained lifecycle authority")
        self._reconnect_blocked = True
        self._battle_recovery_authority = recovery
        if self.connected:
            recovery._session()
            return
        previous = self._remote_task
        if previous is not None and not previous.done():
            await asyncio.wait_for(asyncio.shield(previous), self.config.send_timeout + self.config.reconnect_delay + 1)
        if self._closing or not recovery._authorizes_reconnect():
            raise ConnectionError("retained battle reconnect authority expired")
        ready = asyncio.get_running_loop().create_future()
        async def connect_once():
            try:
                await self._remote_once(battle_recovery=recovery, ready=ready)
            except (ProtocolError, ConnectionError, OSError, asyncio.TimeoutError, ValueError) as error:
                self.last_error = getattr(error, "code", type(error).__name__)
                self._note_failure(error, handshake=False)
                if not ready.done():
                    ready.set_exception(error)
            finally:
                self._disconnect_remote()
                if not ready.done():
                    ready.set_exception(ConnectionError("host closed before retained battle authentication"))
        self._remote_task = asyncio.create_task(connect_once(), name="companion-retained-battle-connection")
        await ready

    async def _remote_once(self, *, battle_recovery=None, ready=None) -> None:
        writer: asyncio.StreamWriter | None = None
        tasks: list[asyncio.Task] = []
        self._handshaking = True
        try:
            tls = self.config.server_tls
            tls_options = {} if tls is None else {
                "ssl": self._server_tls_context, "server_hostname": self.config.server_host,
                "ssl_handshake_timeout": tls.handshake_timeout,
                "ssl_shutdown_timeout": tls.shutdown_timeout,
            }
            if self.config.relay_host is not None:
                from .relay import open_relay_connection
                reader, writer = await asyncio.wait_for(open_relay_connection(
                    self.config.relay_host, self.config.relay_port, self.config.expected_world_id, ssl=self._server_tls_context,
                    server_hostname=self.config.server_host, ssl_handshake_timeout=tls.handshake_timeout, limit=16_388,
                    connect_timeout=self.config.connect_timeout, pair_timeout=self.config.connect_timeout),
                    self.config.connect_timeout + tls.handshake_timeout)
            else:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(
                    self.config.server_host, self.config.server_port, limit=16_388, **tls_options), self.config.connect_timeout)
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
                closed = ConnectionError("server closed before welcome")
                closed.reason = "rejected"
                raise closed
            if welcome.get("type") == "error":
                raise ServerRejected(welcome.get("code"))
            try:
                welcome = validate_welcome(welcome, self.config)
            except ProtocolError as error:
                if getattr(error, "reason", None) is None:
                    error.reason = "version_mismatch"    # a welcome this game cannot read comes from another game version
                raise
            if battle_recovery is not None:
                battle_recovery._accept_welcome(welcome)
            self.session_epoch = welcome["session_epoch"]
            self.world_id = welcome.get("world_id")
            self.server_epoch = welcome.get("server_epoch")
            self.save_profile = welcome.get("save_profile")
            self.connected = True
            self._handshaking = False
            self.last_error = None
            self.failure, self.failure_detail = None, ""
            self._network_seq = self._network_map_epoch = 0
            self._sent_pose_signature = self._sent_source_signature = None
            self._last_world_seq = 0
            self._publish_snapshot()
            if ready is not None and not ready.done():
                ready.set_result(None)
            tasks = [
                asyncio.create_task(self._read_world(reader, writer), name="companion-world-reader"),
                asyncio.create_task(self._send_presence(writer), name="companion-presence-sender"),
            ]
            # Only the connection itself ends the session. An optional status poll that stops (a host without rival
            # checkpoints refuses it once) used to end it too: the companion then reconnected in a loop, and with the
            # terminal saver armed never again (docs/multiplayer-session-fix-20261019.md).
            optional = []
            if self.config.rival_abi_version == 1:
                optional.append(asyncio.create_task(self._poll_rival(), name="companion-rival-status"))
            essential = list(tasks)
            tasks.extend(optional)
            done, _ = await asyncio.wait(essential, return_when=asyncio.FIRST_COMPLETED)
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

    def set_share_location(self, share: bool) -> None:
        """The player's choice from PokeNav > World > Players: the next presence says it; the choice is kept in the profile."""
        from . import privacy
        self.share_location = bool(share)
        if self._privacy_directory is not None:
            privacy.save(self._privacy_directory, self.share_location)

    async def _send_presence(self, writer: asyncio.StreamWriter) -> None:
        while True:
            pose = self._local_pose
            if pose is not None:
                fresh = self._bridge is not None and asyncio.get_running_loop().time() - self._last_pose_time <= self.config.pause_timeout
                fields = pose.network_fields(fresh)
                if self.config.world_enabled and self._local_world is not None:
                    fields.update(self._local_world.network_fields())
                if self.config.world_enabled and self._local_spawn is not None:
                    fields["weather"] = self._local_spawn.weather
                if not self.share_location:
                    fields["share_location"] = False    # the host keeps this player's place from the others
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

    RIVAL_POLL_SECONDS = 1.5

    async def _poll_rival(self) -> None:
        """Update 31: keep the host's rival summary for the world mailbox (engines with rival_abi_version 1).

        Read-only status requests, one at a time, every 1.5 s; a host without rival
        checkpoints answers once with an error and the poller stops (no retry storm).
        """
        from .world_mailbox import RivalRecord
        while True:
            try:
                reply = await self.battle_challenge_rpc("pending", rival=dict(version=1, operation="status"))
                self._world_rival = RivalRecord.from_reply(reply["rival"], self.config.player_id)
            except BattleChallengeError:
                self._world_rival = None
                return
            except (ConnectionError, OSError, asyncio.TimeoutError, ValueError, KeyError, TypeError):
                # An unexpected reply shape is a missing rival record, never a reason to leave the world.
                self._world_rival = None
            await asyncio.sleep(self.RIVAL_POLL_SECONDS)

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
            elif message.get("type") in {"lobby_result", "lobby_error"}:
                self._receive_lobby(message)
            elif message.get("type") in {"enrollment_result", "enrollment_error"}:
                self._receive_enrollment(message)
            elif message.get("type") in {"trade_result", "trade_error"}:
                self._receive_trade(message)
            elif message.get("type") in {"reset_result", "reset_error"}:
                self._receive_reset(message)
            elif message.get("type") in {"battle_result", "battle_error"}:
                self._receive_challenge(message)
            elif message.get("type") in {"world_result", "world_error"}:
                self._receive_world(message)
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

    async def lobby_rpc(self, operation: str, *, request_id: str | None = None,
                        timeout: float = 5.0, **fields: Any) -> dict[str, Any]:
        """Update 32: battle lobbies (battle_lobby.py, lobby_protocol.py); the format follows who joined."""
        from .ownership_protocol import OWNERSHIP_PROFILE
        from .lobby_protocol import LOBBY_OPERATIONS, validate_lobby_request
        if not isinstance(operation, str) or operation not in LOBBY_OPERATIONS:
            raise ValueError("unsupported lobby operation")
        if type(timeout) not in (int, float) or not 0 < timeout <= 60 or not math.isfinite(timeout):
            raise ValueError("lobby RPC timeout must be finite and between 0 and 60 seconds")
        if (not self.connected or self.world_id is None or self._remote_writer is None
                or self.config.server_credential is None or self.save_profile != OWNERSHIP_PROFILE):
            raise ConnectionError("no authenticated ownership lobby session")
        if set(fields) & {"type", "session_epoch"}:
            raise ValueError("lobby envelope fields cannot be overridden")
        request_id = request_id or str(uuid4())
        request = dict(type="lobby_" + operation, session_epoch=self.session_epoch, request_id=request_id, **fields)
        validate_lobby_request(request, self.session_epoch)
        if request_id in self._lobby_pending or len(self._lobby_pending) >= 8:
            raise ValueError("lobby request is pending or capacity is exhausted")
        future = asyncio.get_running_loop().create_future()
        self._lobby_pending[request_id] = (request, future)
        try:
            await self._send_remote(self._remote_writer, request)
            return await asyncio.wait_for(future, timeout)
        finally:
            self._lobby_pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    def _receive_lobby(self, message):
        from .lobby_protocol import validate_lobby_reply
        validated = validate_lobby_reply(message, self.config.player_id, self.world_id, self.session_epoch)
        pending = self._lobby_pending.get(validated["request_id"])
        if pending is None:
            return  # a late reply: the menu reads the lobbies again
        request, future = pending
        validate_lobby_reply(validated, self.config.player_id, self.world_id, self.session_epoch, request)
        if not future.done():
            if validated["type"] == "lobby_error":
                future.set_exception(LobbyError(validated["code"], validated["message"]))
            else:
                future.set_result(validated)

    async def enrollment_rpc(self, operation, *, request_id=None, timeout=10.0, **fields):
        """A friend's first-time enrollment over the world connection (enrollment_protocol.py)."""
        from .enrollment_protocol import validate_enrollment_request
        from .ownership_protocol import OWNERSHIP_PROFILE
        if (type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60
                or operation not in {"status", "begin", "chunk", "commit"}):
            raise ValueError("unsupported enrollment operation")
        if (not self.connected or self.world_id is None or self._remote_writer is None
                or self.config.server_credential is None or self.save_profile != OWNERSHIP_PROFILE):
            raise ConnectionError("no authenticated enrollment session")
        if set(fields) & {"type", "session_epoch", "request_id"}:
            raise ValueError("enrollment envelope fields cannot be overridden")
        request_id = str(uuid4()) if request_id is None else request_id
        request = dict(type="enrollment_" + operation, session_epoch=self.session_epoch, request_id=request_id, **fields)
        validate_enrollment_request(request, self.session_epoch)
        if request_id in self._enrollment_pending or len(self._enrollment_pending) >= 4:
            raise ValueError("enrollment request is pending or capacity is exhausted")
        future = asyncio.get_running_loop().create_future()
        self._enrollment_pending[request_id] = (request, future)
        try:
            await self._send_remote(self._remote_writer, request)
            return await asyncio.wait_for(future, timeout)
        finally:
            self._enrollment_pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    def _receive_enrollment(self, message):
        pending = self._enrollment_pending.get(message.get("request_id"))
        if pending is None:
            return
        request, future = pending
        if (message.get("session_epoch") != self.session_epoch or message.get("operation") != request["type"].removeprefix("enrollment_")):
            raise ProtocolError("invalid_server_message", "enrollment reply does not match its request")
        if not future.done():
            if message["type"] == "enrollment_error":
                from .enrollment_protocol import EnrollmentRemoteError
                future.set_exception(EnrollmentRemoteError(str(message.get("code")), str(message.get("message"))))
            else:
                future.set_result(message)

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
        if operation == "pending" and ("championship" in fields or "rival" in fields):
            pending_path = getattr(self, "_live_battle_pending_path", None)
            if pending_path is not None:
                from .battle_admission_cleanup import publish_cleanup_handoffs
                await publish_cleanup_handoffs(self, Path(pending_path).parent)
        consent_core = None
        championship_match = (operation == "pending" and any(
            type(fields.get(extension)) is dict and fields[extension].get("operation") == "match"
            for extension in ("championship", "rival")))
        if (operation in {"invite", "invite_multi", "invite_ffa", "invite_ffa3", "accept"} or championship_match) and self.config.battle_resume_abi_version == 1:
            if self.config.battle_abi_version != 3 or self._bridge is None or not self._bridge.battle_capable:
                raise ValueError("resumable consent requires the current verified native core")
            if getattr(self, "_live_battle_runtime_id", None) is None:
                self._live_battle_runtime_id = str(uuid4())
            original = dict(incarnation=self.battle_incarnation, runtime_id=self._live_battle_runtime_id)
            if any(name in fields and fields[name] != value for name, value in original.items()):
                raise ValueError("battle consent cannot substitute another native runtime")
            fields = {**fields, **original}
            consent_core = (self._bridge, self.battle_incarnation, self._live_battle_runtime_id)
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
            result = await asyncio.wait_for(future, timeout)
            if consent_core is not None and consent_core != (self._bridge, self.battle_incarnation, self._live_battle_runtime_id):
                raise ConnectionError("battle consent lost its original native runtime")
            return result
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
        """Negotiate optional effects through a known read before any new operation."""
        from .trade_capability import native_effects_available
        effect_ops = {"status", "proposals", "open", "offer", "confirm", "prepare", "inspect",
                      "effect_source", "cancel", "effect_prepared"}
        if "effects_version" in fields:
            raise ValueError("effect capability negotiation is owned by the companion")
        if operation in {"open", "offer", "confirm", "prepare", "prepared", "effect_prepared", "cancel", "ack"}:
            # Fence mutations before any negotiation probe reaches the host.
            self._guard_pending_trade_mutation()
        native = native_effects_available(self)
        if operation in effect_ops and (native or operation in {"status", "cancel"}):
            binding = (self.world_id, self.server_epoch, self.session_epoch)
            cached = getattr(self, "_trade_effect_negotiation", None)
            if cached is None or cached[0] != binding:
                try:
                    # Recovery-only hosts intentionally expose status while
                    # disabling proposal creation. Probe the exact known fate
                    # operation for recovery instead of requiring a live desk.
                    if operation in {"status", "cancel"} and "transaction_id" in fields:
                        probe = await self._trade_rpc("status", timeout=timeout, effects_version=1,
                            transaction_id=fields["transaction_id"])
                    else:
                        probe = await self._trade_rpc("proposals", timeout=timeout, effects_version=1)
                    supported = probe.get("effects_version") == 1
                except TradeError as error:
                    if error.code != "invalid_fields":
                        raise
                    supported = False
                if not self.connected or binding != (self.world_id, self.server_epoch, self.session_epoch):
                    raise ConnectionError("trade effect negotiation changed authenticated session")
                cached = (binding, supported)
                self._trade_effect_negotiation = cached
            if cached[1]:
                fields["effects_version"] = 1
        if operation == "effect_prepared" and (not native or fields.get("effects_version") != 1):
            raise TradeError("trade_effect_unsupported", "matching host and original native effect capabilities are required")
        return await self._trade_rpc(operation, request_id=request_id, timeout=timeout, **fields)

    async def _trade_rpc(self, operation: str, *, request_id: str | None = None,
                        timeout: float = 5.0, **fields: Any) -> dict[str, Any]:
        """Validated trade controls over the authenticated reader."""
        from .trade_protocol import TRADE_OPERATIONS, PREPARATION_OPERATIONS, PREPARATION_VERSION, validate_trade_request
        if operation in {"open", "offer", "confirm", "prepare", "prepared", "effect_prepared", "cancel", "ack"}:
            self._guard_pending_trade_mutation()
        if not self.config.trade_enabled or operation not in TRADE_OPERATIONS:
            raise ValueError("trade operation requires a verified trade-capable build")
        if not self.connected or self.world_id is None or self._remote_writer is None:
            raise ConnectionError("no authenticated trade session")
        if set(fields) & {"type", "session_epoch", "preparation_version"}:
            raise ValueError("trade envelope fields cannot be overridden")
        if self._live_save_owner is not None and self._live_save_owner is not asyncio.current_task() and operation not in {"status", "pending", "proposals"}:
            raise ValueError("a live-save lifecycle owns this character's mutations")
        request_id = request_id or str(uuid4())
        if request_id in self._trade_pending or len(self._trade_pending) >= 8:
            raise ValueError("trade request is pending or capacity is exhausted")
        request = dict(type="trade_" + operation, session_epoch=self.session_epoch,
                       request_id=request_id, **fields)
        if operation in PREPARATION_OPERATIONS:
            request["preparation_version"] = PREPARATION_VERSION
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
        for feature in ("inspection_version", "effect_source_version", "effects_version", "end_reason_version"):
            if feature in validated and request.get(feature) != validated[feature]:
                raise ProtocolError("invalid_server_message", "unsolicited trade feature acknowledgement")
        if (validated["operation"] != request["type"].removeprefix("trade_")
                or validated["session_epoch"] != request["session_epoch"]
                or (validated["type"] == "trade_result" and "transaction_id" in request
                    and validated["trade"]["transaction_id"] != request["transaction_id"])):
            raise ProtocolError("invalid_server_message", "trade reply does not match its request")
        if not future.done():
            if validated["type"] == "trade_error":
                if (validated["operation"] == "proposals" and "preparation_version" in request
                        and validated["code"] == "invalid_field" and "preparation_version" not in validated):
                    future.set_exception(TradeError("trade_preparation_unsupported",
                        "host does not support recipient preparation version 1"))
                else:
                    future.set_exception(TradeError(validated["code"], validated["message"]))
            else:
                future.set_result(validated)

    async def checkpoint_rpc(self, operation: str, *, request_id: str | None = None, timeout: float = 5.0, **fields: Any) -> dict[str, Any]:
        """Use the existing reader so heartbeat/presence continue during transfers."""
        message, future = _checkpoint_request(self, operation, request_id, fields)
        try:
            await self._send_remote(self._remote_writer, message)
            return await asyncio.wait_for(future, timeout)
        finally:
            self._checkpoint_pending.pop(message["request_id"], None)
            if not future.done():
                future.cancel()

    async def checkpoint_pipeline(self, operation: str, requests, *, window: int, timeout: float = 5.0):
        """checkpoint_rpc for each field dict of the iterator `requests` in order, up to `window` of them sent before the oldest is
        answered; yields the answers in that order. All of it runs in the caller's task (a live-save lifecycle's
        transfer stays its own), and the host takes a connection's messages one by one in order, so each answer is
        that of its own request. Use under contextlib.aclosing: an early end forgets the requests still out."""
        pending = []
        try:
            while True:
                while len(pending) < window:
                    fields = next(requests, None)
                    if fields is None:
                        break
                    message, future = _checkpoint_request(self, operation, None, fields)
                    pending.append((message["request_id"], future))
                    await self._send_remote(self._remote_writer, message)
                if not pending:
                    return
                request_id, future = pending[0]
                answer = await asyncio.wait_for(future, timeout)
                pending.pop(0)
                self._checkpoint_pending.pop(request_id, None)
                yield answer
        finally:
            for request_id, future in pending:
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
        self._world_clock = message["clock"]
        self._world_clock_time = time.monotonic()
        self._world_event = message["event"]
        self._world_wallet = message["wallet"]
        self._world_teammate = message["teammate"]
        self._world_spawns = message["spawns"]
        self._world_extras = message.get("extras")
        if (self._extras_local is not None and self._extras_acked_epoch != self.session_epoch
                and (self._extras_task is None or self._extras_task.done())):
            self._start_base_publish()  # a new host session has not stored this game's base yet
        if message["notice"] is not None:
            self._world_notice = message["notice"]
        self._publish_snapshot()

    # ----------------------------------------------------------- shared world
    def _spawn_world_action(self, action) -> None:
        from .world_mailbox import ACTION_KINDS, RESULT_NAMES
        kind = ACTION_KINDS.get(action.kind)
        if kind == "appearance":
            self._spawn_appearance_save(action.seq)
            return
        if kind == "wallet":
            self._spawn_wallet_receipt(action)
            return
        if kind == "coop_gym":
            self._spawn_coop_gym_request(action)
            return
        if kind == "tower" and getattr(self.config, "tower_abi_version", 0) == 1:
            self._spawn_tower_result(action)
            return
        if kind in (None, "tower") or action.event_id == 0:
            self._world_action_ack = action.seq
            return
        result = RESULT_NAMES.get(action.result) if kind == "result" else None
        if kind == "result" and result is None:
            self._world_action_ack = action.seq
            return

        async def run():
            # Acknowledged only once the host has answered (a refusal is an
            # answer). A claim or a battle result that never reached the host
            # is sent again: the game keeps it posted until it is acknowledged,
            # and the host applies a repeat once (KNOWN_ISSUES M16).
            if await self._deliver_world_request("world_action", action=kind, event_id=action.event_id,
                                                 result=result, seq=action.seq):
                self._world_action_ack = action.seq
                self._publish_snapshot()
            else:
                await asyncio.sleep(_ACTION_RETRY_SECONDS)
                if self._world_action_sent == action.seq:
                    self._world_action_sent = 0  # forwarded again from the game's next record

        task = asyncio.create_task(run(), name="companion-world-action")
        self._ipc_handlers.add(task)
        task.add_done_callback(self._ipc_handlers.discard)

    def _start_base_publish(self) -> None:
        """Tell the host about the game's own base (or that it has none), until it answers."""
        if self._extras_task is not None and not self._extras_task.done():
            return  # the running task always sends the latest record

        async def run():
            while self._extras_local is not None and self.connected:
                local, epoch = self._extras_local, self.session_epoch
                if local.base_seq == self._extras_base_ack and epoch == self._extras_acked_epoch:
                    return
                from .extras_mailbox import validate_base, ExtrasMailboxError
                base = None
                if local.has_base:
                    try:
                        base = validate_base(local.base).hex()
                    except ExtrasMailboxError:
                        base = None  # an invalid base is not shared (the game keeps playing with it)
                if await self._deliver_world_request("base_publish", seq=local.base_seq, base=base):
                    self._extras_base_ack, self._extras_acked_epoch = local.base_seq, epoch
                    self._publish_snapshot()
                    if self._extras_local is local:
                        return
                else:
                    await asyncio.sleep(_ACTION_RETRY_SECONDS)

        task = self._extras_task = asyncio.create_task(run(), name="companion-secret-base")
        self._ipc_handlers.add(task)
        task.add_done_callback(self._ipc_handlers.discard)

    def world_nav(self) -> dict | None:
        """The host's PokeNav view (players' places and weather, outbreak, World Event)."""
        extras = self._world_extras
        return None if extras is None or not self.connected else extras["nav"]

    async def secret_base_rpc(self, mode: str | None = None) -> dict:
        """The player's base sharing: read it, or choose everyone / team / nobody."""
        result = await self.world_rpc("base_get" if mode is None else "base_visibility",
                                      **({} if mode is None else {"mode": mode}))
        if (type(result) is not dict or type(result.get("published")) is not bool
                or result.get("visibility") not in ("everyone", "team", "nobody")):
            raise ProtocolError("invalid_server_message", "invalid secret base view")
        return {"published": result["published"], "visibility": result["visibility"]}

    def _spawn_spawn_action(self, action) -> None:
        """The game claimed, reported or released a shared wild Pokemon."""
        from .spawn_mailbox import ACTION_KINDS, RESULT_NAMES
        kind = ACTION_KINDS.get(action.kind)
        result = RESULT_NAMES.get(action.result) if kind == "result" else None
        if kind is None or action.spawn_id == 0 or (kind == "result" and result is None):
            self._spawn_action_ack = action.seq
            self._publish_snapshot()
            return

        async def run():
            # As _spawn_world_action: acknowledged only once the host answered;
            # otherwise forwarded again (claims, results and releases are
            # idempotent on the host: a repeated "caught" is "gone").
            if await self._deliver_world_request("spawn_action", action=kind, spawn_id=action.spawn_id,
                                                 result=result, seq=action.seq):
                self._spawn_action_ack = action.seq
                self._publish_snapshot()
            else:
                await asyncio.sleep(_ACTION_RETRY_SECONDS)
                if self._spawn_action_sent == action.seq:
                    self._spawn_action_sent = 0  # forwarded again from the game's next record

        task = asyncio.create_task(run(), name="companion-spawn-action")
        self._ipc_handlers.add(task)
        task.add_done_callback(self._ipc_handlers.discard)

    async def _deliver_world_request(self, operation: str, **fields) -> bool:
        """True once the host has answered the request (its refusal included);
        False when it never arrived or its answer was lost (no session, a
        timeout, a closed link), so the caller sends it again."""
        try:
            await self.world_rpc(operation, **fields)
        except ProtocolError:
            return True
        except Exception:  # noqa: BLE001 - not delivered; retried
            return False
        return True

    def _spawn_appearance_save(self, seq: int) -> None:
        """The in-game STYLE editor saved a look: store it in the host profile."""
        look = self._local_world.appearance if self._local_world is not None else None

        async def run():
            try:
                if look is not None:
                    await self.appearance_rpc(look)
            except Exception:  # noqa: BLE001 - the ROM re-offers the look until the host confirms it
                pass
            finally:
                self._world_action_ack = seq
                self._publish_snapshot()

        task = asyncio.create_task(run(), name="companion-appearance-save")
        self._ipc_handlers.add(task)
        task.add_done_callback(self._ipc_handlers.discard)

    def _spawn_wallet_receipt(self, action) -> None:
        """The save applied a wager wallet adjustment: tell the host exactly
        what moved so a winner is credited only money that was collected."""
        seq, amount = action.event_id, action.amount

        async def run():
            try:
                if 1 <= seq <= 0xFFFF:
                    await self.world_rpc("wallet_applied", seq=seq, amount=amount)
            except Exception:  # noqa: BLE001 - the ROM re-posts its last receipt on every connection
                pass
            finally:
                self._world_action_ack = action.seq
                self._publish_snapshot()

        task = asyncio.create_task(run(), name="companion-wallet-receipt")
        self._ipc_handlers.add(task)
        task.add_done_callback(self._ipc_handlers.discard)

    def _spawn_coop_gym_request(self, action) -> None:
        """A Gym Leader script asked the host for a co-op Gym challenge."""
        gym = action.event_id

        async def run():
            try:
                if 1 <= gym <= 8:
                    await self.world_rpc("gym_coop", gym=gym)
            except Exception:  # noqa: BLE001 - the host posts its own refusal banner
                pass
            finally:
                self._world_action_ack = action.seq
                self._publish_snapshot()

        task = asyncio.create_task(run(), name="companion-coop-gym")
        self._ipc_handlers.add(task)
        task.add_done_callback(self._ipc_handlers.discard)

    def _spawn_tower_result(self, action) -> None:
        """Battle Tower: Legends (docs/battle-tower-legends.md 8.3): a solo Tower battle started, ended or was refused by
        the game. Acknowledged only once the host has answered (its refusal included), like a World Event result: the
        game keeps a won, lost or drawn result in its save and posts it again until the host's Tower word settles it."""
        from .world_mailbox import TOWER_RESULTS

        async def run():
            if await self._deliver_world_request("tower_result", ticket=action.event_id, floor=action.species,
                                                 outcome=TOWER_RESULTS[action.result], seq=action.seq):
                self._world_action_ack = action.seq
                self._publish_snapshot()
            else:
                await asyncio.sleep(_ACTION_RETRY_SECONDS)
                if self._world_action_sent == action.seq:
                    self._world_action_sent = 0  # forwarded again from the game's next record

        task = asyncio.create_task(run(), name="companion-tower-result")
        self._ipc_handlers.add(task)
        task.add_done_callback(self._ipc_handlers.discard)

    async def wager_rpc(self, operation: str, **fields) -> dict:
        """Read, propose, accept or decline the wager on a pending challenge."""
        result = await self.world_rpc(operation, **fields)
        wager, money = result.get("wager"), result.get("money")
        if (wager is not None and (type(wager) is not dict
                or not {"battle_id", "amount", "sender", "players", "accepted", "state"} <= set(wager)
                or type(wager["amount"]) is not int or type(wager["accepted"]) is not list)) \
                or (money is not None and (type(money) is not int or not 0 <= money <= 999_999)):
            raise ProtocolError("invalid_server_message", "invalid wager view")
        return {"wager": wager, "money": money}

    async def world_rpc(self, operation: str, *, timeout: float = 5.0, **fields):
        from .shared_world_protocol import validate_world_request
        if not self.connected or self._remote_writer is None or self.session_epoch is None:
            raise ConnectionError("no shared-world session")
        if ((operation == "gym_coop" or (operation == "frontier" and fields.get("op") == "battle")
                or (operation == "tower" and fields.get("op") == "duo_ready"))
                and self.config.battle_resume_abi_version == 1
                and self.config.battle_abi_version == 3 and self._bridge is not None
                and self._bridge.battle_capable):
            # The co-op request is the challenger's consent: bind it to this
            # game's original native core, exactly as battle_challenge_rpc does
            # for an invite (the host captures it for native admission).
            if getattr(self, "_live_battle_runtime_id", None) is None:
                self._live_battle_runtime_id = str(uuid4())
            fields = {**fields, "incarnation": self.battle_incarnation, "runtime_id": self._live_battle_runtime_id}
        request_id = str(uuid4())
        request = dict(type=operation, session_epoch=self.session_epoch, request_id=request_id, **fields)
        validate_world_request(request, self.session_epoch)
        if len(self._world_pending) >= 8:
            raise ValueError("shared-world request capacity is exhausted")
        future = asyncio.get_running_loop().create_future()
        self._world_pending[request_id] = (request, future)
        try:
            await self._send_remote(self._remote_writer, request)
            return await asyncio.wait_for(future, timeout)
        finally:
            self._world_pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    def _receive_world(self, message):
        from .shared_world_protocol import validate_world_reply
        validated = validate_world_reply(message)
        pending = self._world_pending.get(validated["request_id"])
        if pending is None:
            return
        _, future = pending
        if not future.done():
            if validated["type"] == "world_error":
                future.set_exception(ProtocolError(validated["code"], validated["message"]))
            else:
                future.set_result(validated["result"])

    async def friendship_rpc(self) -> dict:
        """This player's friendship with every connected player (host-owned)."""
        result = await self.world_rpc("friendship_get")
        friends = result.get("friends")
        if type(friends) is not dict:
            raise ProtocolError("invalid_server_message", "invalid friendship view")
        for player, view in friends.items():
            if (type(view) is not dict or not {"level", "name", "points", "next", "lucky_friends"} <= set(view)
                    or type(view["level"]) is not int or not 0 <= view["level"] <= 4
                    or type(view["points"]) is not int or type(view["lucky_friends"]) is not bool):
                raise ProtocolError("invalid_server_message", "invalid friendship view")
        return friends

    async def habitat_rpc(self) -> dict:
        """What the host knows about the wild Pokemon of the map this player stands on (shared_world.habitat_view)."""
        result = await self.world_rpc("habitat_get")
        if type(result) is not dict or type(result.get("known")) is not bool or type(result.get("place")) is not str:
            raise ProtocolError("invalid_server_message", "invalid habitat view")
        return result

    async def frontier_rpc(self, op: str = "status", mode: str | None = None, slot: int | None = None,
                           mask: int | None = None) -> dict:
        """The cooperative Battle Frontier (frontier_service.py): read it, or propose / accept / cancel / retire a run
        or ask for the next round's battle. Refusals arrive as ProtocolError with the host's reason."""
        extra = ({} if mode is None else {"mode": mode}) | ({} if slot is None else {"slot": slot}) \
            | ({} if mask is None else {"mask": mask})
        result = await self.world_rpc("frontier", op=op, **extra)
        run, record = result.get("run"), result.get("record")
        if (type(record) is not dict or type(result.get("party_limit")) is not int
                or (run is not None and (type(run) is not dict or run.get("state") not in ("forming", "active", "ended")
                                         or type(run.get("round")) is not int or type(run.get("streak")) is not int))):
            raise ProtocolError("invalid_server_message", "invalid Frontier view")
        return result

    async def tower_rpc(self, op: str = "status", **fields) -> dict:
        """Battle Tower: Legends (tower_service.py): read it, ask for a solo battle (the reply carries the command this
        game's window takes), form and ready a Duo, choose the Duo team, buy from the shop or send an owed milestone
        Pokemon again. Refusals arrive as ProtocolError with the host's reason."""
        result = await self.world_rpc("tower", op=op, **fields)
        player, command = result.get("player"), result.get("command")
        if (type(player) is not dict or type(player.get("progress")) is not int or type(player.get("highest")) is not int
                or type(player.get("claims")) is not int
                or (command is not None and (type(command) is not dict or set(command) != {"ticket", "floor", "table_hash"}
                                             or command["floor"] != fields.get("floor")))):
            raise ProtocolError("invalid_server_message", "invalid Battle Tower view")
        return result

    async def appearance_rpc(self, appearance: bytes | None = None) -> bytes | None:
        """Read or replace this player's customized trainer look on the host."""
        if appearance is None:
            result = await self.world_rpc("appearance_get")
        else:
            from .appearance import validate_appearance
            result = await self.world_rpc("appearance_set", appearance=validate_appearance(appearance).hex())
        value = result.get("appearance")
        return None if value is None else bytes.fromhex(value)


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


def _checkpoint_request(companion, operation, request_id, fields):
    """Companion.checkpoint_rpc's checks; registers the request's answer and returns (message, future). A function, so the
    tests' stand-in companions that call Companion.checkpoint_rpc directly meet the same live-save owner guard."""
    from .protocol import validate_checkpoint_request
    if operation in {"begin", "chunk", "commit", "abort", "ownership_grant"}:
        companion._guard_pending_trade_mutation()
    if (companion._live_save_owner is not None and companion._live_save_owner is not asyncio.current_task()
            and operation in {"begin", "chunk", "commit", "abort", "ownership_grant"}):
        raise ValueError("a live-save lifecycle owns this character's checkpoint writes")
    if set(fields) & {"type", "session_epoch"}:
        raise ValueError("checkpoint envelope fields cannot be overridden")
    if not companion.connected or companion.world_id is None or companion._remote_writer is None:
        raise ConnectionError("no authenticated checkpoint session")
    request_id = request_id or str(uuid4())
    if request_id in companion._checkpoint_pending:
        raise ValueError("checkpoint request is already pending")
    if len(companion._checkpoint_pending) >= 8:
        raise ValueError("checkpoint request capacity is exhausted")
    epoch = companion.session_epoch
    message = {"type": operation if operation == "ownership_grant" else "checkpoint_" + operation,
               "session_epoch": epoch, "request_id": request_id, **fields}
    validate_checkpoint_request(message, epoch)
    future = asyncio.get_running_loop().create_future()
    companion._checkpoint_pending[request_id] = (operation, epoch, future)
    return message, future


if __name__ == "__main__":
    main()
