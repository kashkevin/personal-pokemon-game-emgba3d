"""Verified checkpoint mirrors replaced only while their game is closed.

The controller holds MirrorLease for the entire core lifetime. Restoring takes
the same exclusive OS lock, preserves an unbound/changed local copy, and stages
the full Flash/RTC container before replacing it. The payload and sidecar use
separate atomic replacements; disagreement after interruption fails closed.
"""
from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from .flash import FlashError, LAYOUT_ID, MAX_CONTAINER_SIZE, inspect_flash
from .ownership import OWNERSHIP_PROFILE
from .protocol import MAX_COUNTER
from .storage import _ExclusiveFileLock
from .windows_files import replace_file

MIRROR_SCHEMA_VERSION = 1
MAX_SIDECAR_BYTES = 4096
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class MirrorError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class MirrorInfo:
    world_id: str
    player_id: str
    build_id: str
    ruleset_id: str
    save_profile: str
    revision: int
    request_id: str
    sha256: str
    size: int
    schema_version: int = MIRROR_SCHEMA_VERSION


def sidecar_path(save_path: str | Path) -> Path:
    path = Path(save_path).resolve()
    return path.with_name(path.name + ".checkpoint.json")


def recoveries_path(save_path: str | Path) -> Path:
    return Path(save_path).resolve().parent / ".checkpoint-recoveries"


class MirrorLease:
    """Cooperative core-lifetime guard; this context never opens the save file."""

    def __init__(self, save_path: str | Path):
        self.save_path = Path(save_path).resolve()
        self._held = False
        self._lock = _ExclusiveFileLock(self.save_path.with_name(self.save_path.name + ".mirror.lock"))

    def __enter__(self) -> MirrorLease:
        if self._held:
            raise MirrorError("mirror_active", "this save lease is already held")
        try:
            self._lock.acquire()
        except OSError as error:
            raise MirrorError("mirror_active", "a game or another controller owns this save") from error
        self._held = True
        return self

    def __exit__(self, *args) -> None:
        if self._held:
            self._held = False
            self._lock.release()


def _uuid(value, name: str) -> None:
    try:
        valid = isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise MirrorError("invalid_metadata", f"{name} must be a canonical UUID")


def _validate_info(info: MirrorInfo) -> None:
    for name in ("world_id", "player_id", "request_id"):
        _uuid(getattr(info, name), name)
    for name in ("build_id", "ruleset_id", "save_profile"):
        value = getattr(info, name)
        if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
            raise MirrorError("invalid_metadata", f"{name} is not a bounded identifier")
    if (type(info.schema_version) is not int or info.schema_version != MIRROR_SCHEMA_VERSION
            or type(info.revision) is not int or not 1 <= info.revision <= MAX_COUNTER
            or type(info.size) is not int or info.size not in (131072, MAX_CONTAINER_SIZE)
            or not isinstance(info.sha256, str) or _SHA256.fullmatch(info.sha256) is None):
        raise MirrorError("invalid_metadata", "mirror schema, revision, size, or hash is invalid")
    if info.save_profile not in (LAYOUT_ID, OWNERSHIP_PROFILE):
        raise MirrorError("save_profile_mismatch", "mirror requires the pinned ordinary Flash profile")


def _checkpoint_info(checkpoint, world_id: str) -> tuple[MirrorInfo, bytes]:
    _uuid(world_id, "world_id")
    try:
        payload = checkpoint.payload
        if hasattr(checkpoint, "metadata"):
            metadata = checkpoint.metadata
            names = {"build_id", "ruleset_id", "save_profile", "revision", "request_id", "sha256", "size"}
            if not isinstance(metadata, dict) or set(metadata) != names:
                raise MirrorError("invalid_metadata", "downloaded checkpoint metadata has unexpected fields")
            if checkpoint.world_id != world_id:
                raise MirrorError("world_mismatch", "downloaded checkpoint belongs to another world")
            info = MirrorInfo(world_id, checkpoint.player_id, **metadata)
        else:
            info = MirrorInfo(world_id, checkpoint.player_id, checkpoint.build_id,
                              checkpoint.ruleset_id, checkpoint.save_profile,
                              checkpoint.revision, checkpoint.request_id,
                              checkpoint.sha256, len(payload))
    except (AttributeError, TypeError) as error:
        raise MirrorError("invalid_metadata", "checkpoint fields are missing or invalid") from error
    _validate_info(info)
    if (not isinstance(payload, bytes) or len(payload) != info.size
            or hashlib.sha256(payload).hexdigest() != info.sha256):
        raise MirrorError("checkpoint_mismatch", "checkpoint bytes disagree with their canonical metadata")
    try:
        snapshot = inspect_flash(payload, save_profile=info.save_profile)
        if info.save_profile == OWNERSHIP_PROFILE:
            from .ownership import inspect_ownership
            owner = inspect_ownership(snapshot)
            if (owner.world_id, owner.player_id) != (info.world_id, info.player_id):
                raise MirrorError("ownership_mismatch", "canonical Pokémon belong to another world or character")
    except FlashError as error:
        raise MirrorError("invalid_flash", "checkpoint failed ordinary Flash validation") from error
    return info, payload


def _no_duplicates(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise MirrorError("invalid_metadata", "mirror metadata contains duplicate fields")
        result[name] = value
    return result


def _read_sidecar(path: Path) -> MirrorInfo:
    try:
        with path.open("rb") as source:
            data = source.read(MAX_SIDECAR_BYTES + 1)
    except FileNotFoundError:
        raise MirrorError("mirror_missing", "mirror sidecar is missing") from None
    except OSError as error:
        raise MirrorError("mirror_io_error", "mirror sidecar could not be read") from error
    if len(data) > MAX_SIDECAR_BYTES:
        raise MirrorError("invalid_metadata", "mirror metadata exceeds its byte limit")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates)
        if not isinstance(value, dict) or set(value) != set(MirrorInfo.__dataclass_fields__):
            raise MirrorError("invalid_metadata", "mirror metadata has missing or unexpected fields")
        info = MirrorInfo(**value)
    except (UnicodeError, ValueError, TypeError, RecursionError) as error:
        if isinstance(error, MirrorError):
            raise
        raise MirrorError("invalid_metadata", "mirror metadata is not valid bounded JSON") from error
    _validate_info(info)
    return info


def _inspect_unlocked(path: Path) -> MirrorInfo:
    info = _read_sidecar(sidecar_path(path))
    try:
        with path.open("rb") as source:
            data = source.read(MAX_CONTAINER_SIZE + 1)
    except FileNotFoundError:
        raise MirrorError("mirror_missing", "mirror save file is missing") from None
    except OSError as error:
        raise MirrorError("mirror_io_error", "mirror save file could not be read") from error
    if len(data) != info.size or hashlib.sha256(data).hexdigest() != info.sha256:
        raise MirrorError("mirror_mismatch", "local save and canonical sidecar disagree; preserve and recover")
    try:
        snapshot = inspect_flash(data, save_profile=info.save_profile)
        if info.save_profile == OWNERSHIP_PROFILE:
            from .ownership import inspect_ownership
            owner = inspect_ownership(snapshot)
            if (owner.world_id, owner.player_id) != (info.world_id, info.player_id):
                raise MirrorError("ownership_mismatch", "local mirror metadata belongs to another world or character")
    except FlashError as error:
        raise MirrorError("invalid_flash", "local mirror failed ordinary Flash validation") from error
    return info


def inspect_mirror(save_path: str | Path) -> MirrorInfo:
    """Inspect a closed save, failing on active use or interrupted replacement."""
    with MirrorLease(save_path) as lease:
        return inspect_mirror_held(lease)


def _held_path(lease: MirrorLease) -> Path:
    if (not isinstance(lease, MirrorLease) or not lease._held
            or lease._lock._file is None or lease._lock._file.closed):
        raise MirrorError("mirror_not_held", "this operation requires an acquired save lease")
    return lease.save_path


def inspect_mirror_held(lease: MirrorLease) -> MirrorInfo:
    """Inspect through the caller's uninterrupted closed/core-lifetime lease."""
    return _inspect_unlocked(_held_path(lease))


def _fsync_directory(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _archive_existing(path: Path) -> None:
    sources = [source for source in (path, sidecar_path(path)) if source.exists()]
    if not sources:
        return
    root = recoveries_path(path)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    archive = root / str(uuid.uuid4())
    archive.mkdir(mode=0o700)
    for source in sources:
        with source.open("rb") as old, (archive / source.name).open("xb") as recovered:
            while chunk := old.read(65536):
                recovered.write(chunk)
            recovered.flush()
            os.fsync(recovered.fileno())
    _fsync_directory(archive)
    _fsync_directory(root)


def _stage(path: Path, data: bytes) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".stage", dir=path.parent)
    staging = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
    except BaseException:
        with suppress(OSError):
            staging.unlink()
        raise
    return staging


def restore_checkpoint(save_path: str | Path, checkpoint, world_id: str) -> MirrorInfo:
    """Restore a canonical checkpoint under an exclusive closed-game lease.

    A verified mirror cannot change identity or move backwards. A changed or
    unbound local file is archived before replacement, enabling explicit recovery
    without merging it into server state. DownloadedCheckpoint and storage's
    Checkpoint records are both accepted; credentials never enter the sidecar.
    """
    with MirrorLease(save_path) as lease:
        return restore_checkpoint_held(lease, checkpoint, world_id)


def restore_checkpoint_held(lease: MirrorLease, checkpoint, world_id: str) -> MirrorInfo:
    """Restore while retaining an already acquired lease for the future core.

    The caller must keep the game closed until this returns and its own network
    reconciliation completes. The lease is never released or reacquired here.
    """
    path = _held_path(lease)
    info, payload = _checkpoint_info(checkpoint, world_id)
    try:
        # A readable sidecar still binds identity and revision when the
        # local payload is damaged or absent. Recovery cannot bypass it.
        previous = _read_sidecar(sidecar_path(path))
    except MirrorError as error:
        if error.code in ("mirror_io_error", "save_profile_mismatch"):
            raise
        previous = None
    if previous is not None:
        fields = ("world_id", "player_id", "build_id", "ruleset_id", "save_profile")
        if any(getattr(previous, key) != getattr(info, key) for key in fields):
            raise MirrorError("identity_mismatch", "verified mirror belongs to another world, player, or build")
        if info.revision < previous.revision or (info.revision == previous.revision and info != previous):
            raise MirrorError("revision_conflict", "canonical restore would replace a verified newer or conflicting revision")
        if info == previous:
            try:
                _inspect_unlocked(path)
            except MirrorError as error:
                if error.code == "mirror_io_error":
                    raise
            else:
                return info
    staged_save = staged_sidecar = None
    try:
        _archive_existing(path)
        sidecar = sidecar_path(path)
        staged_save = _stage(path, payload)
        metadata = (json.dumps(asdict(info), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        staged_sidecar = _stage(sidecar, metadata)
        replace_file(staged_save, path)
        _fsync_directory(path.parent)
        replace_file(staged_sidecar, sidecar)
        _fsync_directory(path.parent)
    except OSError as error:
        raise MirrorError("mirror_io_error", "offline checkpoint replacement was interrupted; inspect preserved recovery files") from error
    finally:
        for staging in (staged_save, staged_sidecar):
            if staging is not None:
                with suppress(FileNotFoundError):
                    staging.unlink()
    return info
