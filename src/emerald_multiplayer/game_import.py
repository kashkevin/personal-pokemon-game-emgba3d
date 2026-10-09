"""Bounded BPS application from an owner's dump, with compiled release pins.

Format reference: byuu's public-domain BPS specification, preserved by Flips.
No downloaded executable, patch metadata, save file or ROM enters the trust root.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import struct
import tempfile
import zlib
import zipfile

MAX_ROM = 32 * 1024 * 1024
MAX_PATCH = 64 * 1024 * 1024
MAX_METADATA = 1024 * 1024
MAX_ACTIONS = 2 * 1024 * 1024
MAX_SOURCE_ARCHIVE = 64 * 1024 * 1024


class GameImportError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _require(condition, code="patch_invalid"):
    if not condition:
        raise GameImportError(code)


def _read(path, maximum):
    try:
        with Path(path).open("rb") as handle:
            data = handle.read(maximum + 1)
    except OSError as error:
        raise GameImportError("import_file") from error
    _require(len(data) <= maximum, "import_size")
    return data


def read_game_source(path):
    """Read a raw dump or one bounded GBA member, without extracting an archive.

    ZIP CRC/size/header checks identify corruption; the package's explicit
    source SHA-256 still determines which owner's dump is accepted.
    """
    path = Path(path)
    if path.suffix.lower() != ".zip":
        return _read(path, MAX_ROM)
    try:
        # Bound the central directory as well as expanded member bytes. Reading
        # one fixed archive byte snapshot avoids races between listing/opening.
        import io
        raw = _read(path, MAX_SOURCE_ARCHIVE)
        # Refuse an oversized directory before ZipFile allocates ZipInfo
        # objects. ZIP64/multipart are unnecessary for one <=32 MiB dump.
        end = raw.rfind(b"PK\x05\x06", max(0, len(raw) - 65557))
        _require(end >= 0 and end + 22 <= len(raw), "source_archive")
        _, disk, central_disk, local_count, total_count, central_size, central_offset, comment = struct.unpack_from("<4s4H2IH", raw, end)
        _require(disk == central_disk == 0 and local_count == total_count
                 and 1 <= total_count <= 64 and central_size <= 1024 * 1024
                 and central_offset + central_size <= end and end + 22 + comment == len(raw), "source_archive")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            _require(len(members) == total_count, "source_archive")
            games = [member for member in members if not member.is_dir()
                     and Path(member.filename).suffix.lower() == ".gba"]
            _require(len(games) == 1, "source_archive")
            member = games[0]
            _require(not member.flag_bits & 1 and member.compress_type in
                     {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                     and 192 <= member.file_size <= MAX_ROM
                     and 0 < member.compress_size <= MAX_SOURCE_ARCHIVE, "source_archive")
            with archive.open(member, "r") as source:
                data = source.read(MAX_ROM + 1)
            _require(len(data) == member.file_size and len(data) <= MAX_ROM, "source_archive")
        # Header checksum covers title/game code/version. Names alone never
        # establish this is the supported release; the caller checks its pin.
        _require(data[0xB2] == 0x96
                 and (sum(data[0xA0:0xBD]) + 0x19 + data[0xBD]) & 0xFF == 0, "source_archive")
        return data
    except GameImportError:
        raise
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError) as error:
        raise GameImportError("source_archive") from error


def apply_bps(source: bytes, patch: bytes) -> bytes:
    """Apply all four BPS commands with strict bounds and all three CRCs.

    This format-level function is not the release trust gate. GameImporter adds
    independently supplied SHA-256 pins for the input, patch and output.
    """
    _require(type(source) is bytes and type(patch) is bytes)
    _require(len(source) <= MAX_ROM and 19 <= len(patch) <= MAX_PATCH)
    _require(patch[:4] == b"BPS1")
    source_crc, target_crc, patch_crc = struct.unpack("<III", patch[-12:])
    _require(zlib.crc32(patch[:-4]) == patch_crc)
    _require(zlib.crc32(source) == source_crc, "source_mismatch")
    cursor, end = 4, len(patch) - 12

    def number():
        nonlocal cursor
        value, scale = 0, 1
        for _ in range(10):
            _require(cursor < end)
            byte = patch[cursor]
            cursor += 1
            value += (byte & 127) * scale
            _require(value <= (1 << 63) - 1)
            if byte & 128:
                return value
            scale <<= 7
            value += scale
        raise GameImportError("patch_invalid")

    source_size, target_size, metadata_size = number(), number(), number()
    _require(source_size == len(source), "source_mismatch")
    _require(target_size <= MAX_ROM and metadata_size <= MAX_METADATA)
    _require(cursor + metadata_size <= end)
    cursor += metadata_size  # Metadata is inert; never XML-parsed or displayed.
    output = bytearray()
    source_offset = target_offset = actions = 0
    while cursor < end:
        actions += 1
        _require(actions <= MAX_ACTIONS)
        instruction = number()
        action, length = instruction & 3, (instruction >> 2) + 1
        position = len(output)
        _require(position + length <= target_size)
        if action == 0:
            _require(position + length <= len(source))
            output.extend(source[position:position + length])
        elif action == 1:
            _require(cursor + length <= end)
            output.extend(patch[cursor:cursor + length])
            cursor += length
        else:
            encoded = number()
            delta = -(encoded >> 1) if encoded & 1 else encoded >> 1
            if action == 2:
                source_offset += delta
                _require(0 <= source_offset and source_offset + length <= len(source))
                output.extend(source[source_offset:source_offset + length])
                source_offset += length
            else:
                target_offset += delta
                _require(0 <= target_offset < position)
                # BPS permits overlapping copies. Repeat the already-written
                # period in bounded chunks rather than a Python loop per byte.
                period = bytes(output[target_offset:min(position, target_offset + length)])
                output.extend((period * ((length + len(period) - 1) // len(period)))[:length])
                target_offset += length
    _require(cursor == end and len(output) == target_size)
    _require(zlib.crc32(output) == target_crc)
    return bytes(output)


@dataclass(frozen=True)
class ImportRelease:
    source_sha256: str
    patch_sha256: str
    target_sha256: str
    source_size: int
    target_size: int

    def __post_init__(self):
        _require(all(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value)
                     for value in (self.source_sha256, self.patch_sha256, self.target_sha256)))
        _require(all(type(value) is int and 0 < value <= MAX_ROM
                     for value in (self.source_size, self.target_size)))


class GameImporter:
    """Only the package entry point supplies release pins and the patch path."""
    def __init__(self, release: ImportRelease, patch_path: Path, private_directory: Path):
        self.release, self.patch_path, self.private_directory = release, Path(patch_path), Path(private_directory)

    @property
    def target_path(self):
        return self.private_directory / "games" / self.release.target_sha256 / "game.gba"

    def install(self, source_path):
        source = read_game_source(source_path)
        _require(len(source) == self.release.source_size and
                 hashlib.sha256(source).hexdigest() == self.release.source_sha256, "source_mismatch")
        patch = _read(self.patch_path, MAX_PATCH)
        _require(hashlib.sha256(patch).hexdigest() == self.release.patch_sha256, "patch_mismatch")
        output = apply_bps(source, patch)
        _require(len(output) == self.release.target_size and
                 hashlib.sha256(output).hexdigest() == self.release.target_sha256, "target_mismatch")
        destination = self.target_path
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _require(not destination.is_symlink(), "import_destination")
        if destination.exists():
            _require(_read(destination, MAX_ROM) == output, "import_destination")
            return destination
        # Publish a complete, fsynced file without replacing an existing file.
        # NTFS and the development filesystem support same-volume hard links.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".import-", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(output)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                _require(not destination.is_symlink() and _read(destination, MAX_ROM) == output,
                         "import_destination")
        except OSError as error:
            raise GameImportError("import_destination") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return destination
