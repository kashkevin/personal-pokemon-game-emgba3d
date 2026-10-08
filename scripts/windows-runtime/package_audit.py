"""Bounded, read-only audit of packaged files and nested source archives.

This detects known ROM/save/state/credential/database formats and project
credential JSON. It is not a classifier for arbitrary renamed binary content.
No archive is extracted; object/static-library relink inputs remain opaque.
"""
from dataclasses import dataclass
import bz2
import gzip
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import struct
import tarfile
import zipfile


@dataclass(frozen=True)
class Limits:
    depth: int = 5
    members: int = 50_000
    file_bytes: int = 128 * 1024 * 1024
    stream_bytes: int = 256 * 1024 * 1024
    expanded_bytes: int = 2 * 1024 * 1024 * 1024


class PackageAuditError(ValueError):
    pass


_PRIVATE = {".gba", ".gb", ".gbc", ".sgb", ".nds", ".rom", ".nes", ".sfc", ".smc",
            ".n64", ".z64", ".v64", ".pce", ".sms", ".gg", ".sg", ".gen", ".32x",
            ".iso", ".gbs", ".sav", ".srm", ".dsv", ".dss",
            ".mvl", ".ss", ".state", ".sqlite", ".sqlite3", ".db", ".pem",
            ".key", ".p12", ".pfx"}
_SECRET_JSON = {"emerald-private-host-v1", "emerald-private-invitation-v1"}


class _Audit:
    def __init__(self, limits):
        self.limits = limits
        self.members = self.expanded = self.archives = 0

    def name(self, name):
        normalized = name.replace("\\", "/")
        parts = PurePosixPath(normalized).parts
        if (not parts or normalized.startswith("/") or any(p == ".." or ":" in p for p in parts)
                or "\0" in normalized):
            raise PackageAuditError("unsafe package member path")
        leaf = parts[-1].casefold().rstrip(". ")
        suffix = PurePosixPath(leaf).suffix
        if (suffix in _PRIVATE or re.search(r"\.ss\d+$", leaf)
                or re.search(r"\.(?:db|sqlite3?)-(?:wal|shm|journal)$", leaf)
                or leaf in {"host.json", "credentials.json", "invitation.json"}):
            raise PackageAuditError("private game/player data unexpectedly entered package: " + normalized)
        return normalized

    def member(self):
        self.members += 1
        if self.members > self.limits.members:
            raise PackageAuditError("package member count exceeds audit limit")

    def read(self, source, maximum):
        chunks, size = [], 0
        while True:
            chunk = source.read(min(1024 * 1024, maximum - size + 1))
            if not chunk:
                break
            size += len(chunk)
            self.expanded += len(chunk)
            if size > maximum or self.expanded > self.limits.expanded_bytes:
                raise PackageAuditError("package expanded bytes exceed audit limit")
            chunks.append(chunk)
        return b"".join(chunks)

    def inspect(self, name, data, depth=0):
        name = self.name(name)
        lower = name.casefold()
        compression = None
        for endings, magic, opener, replacement in (
                ((".tar.gz", ".tgz", ".gz"), b"\x1f\x8b", lambda source, mode: gzip.GzipFile(fileobj=source, mode=mode), ".tar"),
                ((".tar.bz2", ".tbz2", ".bz2"), b"BZh", bz2.BZ2File, ".tar"),
                ((".tar.xz", ".txz", ".xz"), b"\xfd7zXZ\0", lzma.LZMAFile, ".tar")):
            ending = next((suffix for suffix in endings if lower.endswith(suffix)), None)
            if ending or data.startswith(magic):
                if not data.startswith(magic):
                    raise PackageAuditError("malformed compressed package archive")
                inner = name[:-len(ending)] + (replacement if ending in endings[:2] else "") if ending else "contents"
                compression = opener, inner
                break
        is_zip = lower.endswith((".zip", ".whl")) or data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
        is_tar = lower.endswith(".tar") or data[257:262] == b"ustar"
        if lower.endswith((".7z", ".rar")):
            raise PackageAuditError("unsupported package archive format")
        if compression or is_zip or is_tar:
            if depth >= self.limits.depth:
                raise PackageAuditError("package archive nesting exceeds audit limit")
            self.archives += 1
            try:
                if compression:
                    opener, inner = compression
                    with opener(io.BytesIO(data), "rb") as stream:
                        raw = self.read(stream, self.limits.stream_bytes)
                    self.inspect(inner, raw, depth + 1)
                elif is_zip:
                    self.zip(data, depth + 1)
                else:
                    self.tar(data, depth + 1)
            except PackageAuditError:
                raise
            except (OSError, EOFError, ValueError, tarfile.TarError, zipfile.BadZipFile,
                    NotImplementedError, RuntimeError, lzma.LZMAError):
                raise PackageAuditError("malformed or unsupported package archive") from None
        elif lower.endswith(".json"):
            try:
                value = json.loads(data)
            except (ValueError, UnicodeError):
                return  # Not an archive; this guard is not a JSON schema validator.
            if isinstance(value, dict) and type(value.get("format")) is str and value["format"] in _SECRET_JSON:
                raise PackageAuditError("private host/invitation JSON unexpectedly entered package")

    def zip(self, data, depth):
        # Bound the directory before ZipFile creates one object per entry.
        end = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
        if end < 0 or end + 22 > len(data):
            raise PackageAuditError("missing package ZIP directory")
        disk, directory_disk, on_disk, total, size, offset, comment = struct.unpack_from("<4H2IH", data, end + 4)
        if (disk or directory_disk or on_disk != total or total == 0xFFFF
                or size == 0xFFFFFFFF or offset == 0xFFFFFFFF
                or end + 22 + comment != len(data) or offset + size != end):
            raise PackageAuditError("unsupported or malformed package ZIP directory")
        if self.members + total > self.limits.members:
            raise PackageAuditError("package member count exceeds audit limit")
        position, count = offset, 0
        while position < end:
            if position + 46 > end or data[position:position + 4] != b"PK\x01\x02":
                raise PackageAuditError("malformed package ZIP directory entry")
            count += 1
            if self.members + count > self.limits.members:
                raise PackageAuditError("package member count exceeds audit limit")
            lengths = struct.unpack_from("<3H", data, position + 28)
            position += 46 + sum(lengths)
        if position != end or count != total:
            raise PackageAuditError("inconsistent package ZIP member count")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if len(archive.infolist()) != total:
                raise PackageAuditError("inconsistent package ZIP member count")
            for item in archive.infolist():
                self.member()
                self.name(item.filename)
                if item.flag_bits & 1 or stat.S_ISLNK(item.external_attr >> 16):
                    raise PackageAuditError("encrypted or linked package ZIP member")
                if item.file_size > self.limits.file_bytes:
                    raise PackageAuditError("package member exceeds audit limit")
                with archive.open(item) as stream:
                    raw = self.read(stream, self.limits.file_bytes)
                if len(raw) != item.file_size:
                    raise PackageAuditError("truncated package ZIP member")
                if not item.is_dir():
                    self.inspect(item.filename, raw, depth)

    def tar(self, data, depth):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for item in archive:
                self.member()
                self.name(item.name)
                if item.isdir():
                    continue
                if item.issym() or item.islnk():
                    # Metadata only; no target is followed or extracted.
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(item.name), item.linkname)
                                               if item.issym() else item.linkname)
                    self.name(target)
                    continue
                if not item.isfile() or item.sparse is not None or item.size > self.limits.file_bytes:
                    raise PackageAuditError("unsupported or oversized package TAR member")
                with archive.extractfile(item) as stream:
                    raw = self.read(stream, self.limits.file_bytes)
                if len(raw) != item.size:
                    raise PackageAuditError("truncated package TAR member")
                self.inspect(item.name, raw, depth)


def audit_files(paths, *, limits=Limits()):
    """Audit exactly the files to be copied; neighboring private files stay out."""
    audit = _Audit(limits)
    for path in paths:
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise PackageAuditError("package input must be a regular file")
        audit.member()
        with path.open("rb") as stream:
            audit.inspect(path.name, audit.read(stream, limits.file_bytes))
    return dict(files_and_members=audit.members, archives=audit.archives, inspected_bytes=audit.expanded)


def audit_tree(root, *, limits=Limits()):
    root = Path(root)
    paths = []
    for count, path in enumerate(root.rglob("*"), 1):
        if path.is_symlink():
            raise PackageAuditError("package tree cannot contain links")
        if path.is_file():
            paths.append(path)
        if count > limits.members:
            raise PackageAuditError("package file count exceeds audit limit")
    return audit_files(sorted(paths), limits=limits)
