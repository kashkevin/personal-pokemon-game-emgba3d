"""The package's record of its game build, so a player's PC needs no game.gba.

The native PC game (runtime.json "executable") has all of its game data compiled in and is
started with --save/--bridge/--config only: it never reads a GBA ROM. The Python side used the
ROM for three things, all of which are fixed when the engine is built:

  identity      rom_sha256 (the world build id every world, invitation and save is pinned to),
                rom_size and rom_crc32, as recorded in the game manifest;
  markers       the capability markers and descriptors the manifest names, which
                companion.verify_rom_manifest compares with the ROM bytes;
  battle text   the host's battle-message bounds (battle_controller.read_string_lengths).

``build_facts`` runs the complete ROM verification when the package is built and records these
values in ``game-facts.json``. The file is bound to the exact game-manifest.json bytes
(manifest_sha256) and is pinned by the runtime bundle (runtime.json "files", whose own hash is
compiled into the launcher), so at run time the pinned manifest and runtime pins stand in for the
ROM. A development setup, the mGBA runtime or a package that imported the player's own game still
passes a real ROM, which is verified byte for byte as before.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re
import zlib

FORMAT = "emerald-game-facts-v1"
FILE_NAME = "game-facts.json"
MAX_BYTES = 65_536
STRING_COUNT = 721          # battle_controller._STRINGS
STRING_BUFFER = 256         # battle_controller._STRING_BUFFER
_ROM_BASE = 0x08000000
_HASH = re.compile(r"[0-9a-f]{64}")
_CRC = re.compile(r"[0-9a-f]{8}")
_REQUIRED = frozenset({"format", "rom_sha256", "rom_size", "rom_crc32", "manifest_sha256", "markers"})
_BATTLE = frozenset({"battle_string_table_address", "battle_string_lengths"})


class GameFactsError(ValueError):
    """The facts file is missing, malformed, or belongs to another manifest or game build."""


def is_game_facts(path) -> bool:
    """Whether a game source path names a facts file rather than a GBA ROM (always ``*.json``)."""
    try:
        return Path(path).name.lower().endswith(".json")
    except TypeError:
        return False


def _descriptor_lengths():
    from .gen6_profile import DESCRIPTOR as generation
    from .player_build import DESCRIPTOR as guard
    from .reset_catalogue import DESCRIPTOR as catalogue
    from .trade_replay_manifest import DESCRIPTOR as replay
    return {"player_build_guard_address": len(guard), "generation_profile_address": len(generation),
            "reset_catalogue_address": catalogue.size, "trade_replay_descriptor_address": replay.size}


def marker_fields(manifest, rom_size):
    """Every ROM-resident marker or descriptor the manifest names, with the length the companion
    checks (a 32-bit ABI word unless the field names a longer descriptor). The battle string table
    is recorded as its message lengths instead."""
    lengths = _descriptor_lengths()
    fields = {}
    for name, value in manifest.items():
        if (not name.endswith("_address") or name == "battle_string_table_address"
                or type(value) is not int or not _ROM_BASE <= value < _ROM_BASE + rom_size):
            continue
        fields[name] = min(lengths.get(name, 4), _ROM_BASE + rom_size - value)
    return fields


def build_facts(rom_path, manifest_path) -> dict:
    """Package build time: verify the ROM completely, then record what the runtime needs from it."""
    from .companion import verify_rom_manifest
    rom_path, manifest_path = Path(rom_path), Path(manifest_path)
    if is_game_facts(rom_path):
        raise GameFactsError("game facts are built from the GBA ROM itself")
    build, manifest = verify_rom_manifest(rom_path, manifest_path)
    rom = rom_path.read_bytes()
    if hashlib.sha256(rom).hexdigest() != build:
        raise GameFactsError("the ROM changed while its facts were recorded")
    facts = {
        "format": FORMAT,
        "rom_sha256": build,
        "rom_size": len(rom),
        "rom_crc32": f"{zlib.crc32(rom) & 0xFFFFFFFF:08x}",
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "markers": {name: rom[address - _ROM_BASE:address - _ROM_BASE + length].hex()
                    for name, length in sorted(marker_fields(manifest, len(rom)).items())
                    for address in (manifest[name],)},
    }
    if "battle_string_table_address" in manifest:
        from .battle_controller import read_string_lengths
        address = manifest["battle_string_table_address"]
        facts["battle_string_table_address"] = address
        facts["battle_string_lengths"] = list(read_string_lengths(rom_path, table_address=address))
    return facts


def encode_facts(facts) -> bytes:
    data = (json.dumps(facts, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    if len(data) > MAX_BYTES:
        raise GameFactsError("game facts exceed their size limit")
    return data


def write_facts(rom_path, manifest_path, output) -> dict:
    """Write ``output`` (a new file named game-facts.json) and return the facts."""
    output = Path(output)
    if output.name != FILE_NAME:
        raise GameFactsError("the game facts file is named " + FILE_NAME)
    facts = build_facts(rom_path, manifest_path)
    data = encode_facts(facts)
    with output.open("xb") as handle:
        handle.write(data)
    return facts


@dataclass(frozen=True)
class GameFacts:
    rom_sha256: str
    rom_size: int
    rom_crc32: str
    manifest_sha256: str
    markers: tuple
    battle_string_table_address: int | None = None
    battle_string_lengths: tuple | None = None


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise GameFactsError("game facts repeat a field")
        value[key] = item
    return value


def load_facts(path, manifest_raw: bytes, manifest: dict) -> GameFacts:
    """Read a facts file and bind it to these exact manifest bytes and their ROM identity.

    This proves the facts belong to the manifest; that the pair is the package's own is the
    caller's pin check (GameInstallation.verify: the manifest hash and the runtime bundle that
    pins the facts file)."""
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
    except FileNotFoundError:
        raise
    except OSError as error:
        raise GameFactsError("game facts could not be read") from error
    if len(raw) > MAX_BYTES:
        raise GameFactsError("game facts exceed their size limit")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
    except (UnicodeError, ValueError) as error:
        raise GameFactsError("game facts are not valid JSON") from error
    if (not isinstance(value, dict) or not _REQUIRED <= set(value) <= _REQUIRED | _BATTLE
            or value["format"] != FORMAT):
        raise GameFactsError("game facts have an unsupported format")
    sha, size, crc, pin = (value[key] for key in ("rom_sha256", "rom_size", "rom_crc32", "manifest_sha256"))
    if (type(sha) is not str or not _HASH.fullmatch(sha) or type(pin) is not str or not _HASH.fullmatch(pin)
            or type(size) is not int or not 192 <= size <= 32 * 1024 * 1024
            or type(crc) is not str or not _CRC.fullmatch(crc)):
        raise GameFactsError("game facts identity is invalid")
    if not hmac.compare_digest(pin, hashlib.sha256(manifest_raw).hexdigest()):
        raise GameFactsError("game facts belong to another game manifest")
    if not isinstance(manifest.get("rom_sha256"), str) or not hmac.compare_digest(sha, manifest["rom_sha256"]):
        raise GameFactsError("game facts belong to another game build")
    if manifest.get("rom_size") != size:
        raise GameFactsError("game facts and manifest disagree on the ROM size")
    if "rom_crc32" in manifest and manifest["rom_crc32"] != crc:
        raise GameFactsError("game facts and manifest disagree on the ROM CRC32")
    markers = value["markers"]
    expected = marker_fields(manifest, size)
    if (not isinstance(markers, dict) or set(markers) != set(expected)
            or any(type(data) is not str or re.fullmatch(r"(?:[0-9a-f]{2})+", data) is None
                   or len(data) != 2 * expected[name] for name, data in markers.items())):
        raise GameFactsError("game facts do not record this manifest's ROM markers")
    table = lengths = None
    if _BATTLE & set(value) or "battle_string_table_address" in manifest:
        table, lengths = value.get("battle_string_table_address"), value.get("battle_string_lengths")
        if (not _BATTLE <= set(value) or table != manifest.get("battle_string_table_address")
                or type(lengths) is not list or len(lengths) != STRING_COUNT
                or any(item is not None and (type(item) is not int or not 0 <= item <= STRING_BUFFER)
                       for item in lengths)):
            raise GameFactsError("game facts do not record this manifest's battle messages")
        lengths = tuple(lengths)
    return GameFacts(sha, size, crc, pin, tuple(sorted(markers.items())), table, lengths)
