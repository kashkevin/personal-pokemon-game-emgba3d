"""Immutable evidence of a verified live ROM Flash apply.

Inputs are a validated downloaded checkpoint and Flash bytes read back through
the ROM mailbox. No active save or mirror file is read or written here. The
receipt distinguishes canonical container bytes, including any RTC footer, from
the native ROM's 128 KiB Flash readback and does not represent a schema-1 mirror.
The JSON checksum detects accidental metadata corruption; it is not a signature
or a replacement for the authenticated server's canonical checkpoint.
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
from typing import TYPE_CHECKING
import uuid

from .flash import FLASH_SIZE, FlashError, LAYOUT_ID, MAX_CONTAINER_SIZE, inspect_flash
from .ownership import OWNERSHIP_PROFILE
from .protocol import MAX_COUNTER
from .storage import _ExclusiveFileLock

if TYPE_CHECKING:
    from .checkpoint_client import DownloadedCheckpoint

RECEIPT_SCHEMA_VERSION = 1
RECEIPT_FORMAT = "emerald-live-apply-receipt-v1"
MAX_RECEIPT_BYTES = 4096
RTC_SEMANTICS = "native-footer-excluded"
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class LiveReceiptError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class LiveReceipt:
    world_id: str
    player_id: str
    build_id: str
    ruleset_id: str
    save_profile: str
    revision: int
    canonical_request_id: str
    canonical_container_sha256: str
    canonical_container_size: int
    canonical_flash_sha256: str
    normalized_state_sha256: str
    actual_rom_flash_sha256: str
    trainer_id: int
    operation_id: str
    rom_request_id: str
    session_epoch: int
    incarnation: int
    rtc_footer_present: bool
    rtc_semantics: str = RTC_SEMANTICS
    schema_version: int = RECEIPT_SCHEMA_VERSION


def _uuid(value, name: str) -> None:
    try:
        valid = isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise LiveReceiptError("invalid_metadata", f"{name} must be a canonical UUID")


def _identifier(value, name: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise LiveReceiptError("invalid_metadata", f"{name} must be a bounded identifier")


def _counter(value, name: str) -> None:
    maximum = 0xFFFFFFFF if name == "incarnation" else MAX_COUNTER
    if type(value) is not int or not 1 <= value <= maximum:
        raise LiveReceiptError("invalid_metadata", f"{name} is outside its integer bounds")


def _sha(value, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise LiveReceiptError("invalid_metadata", f"{name} must be a SHA256 digest")


def _validate_receipt(value: LiveReceipt) -> None:
    for name in ("world_id", "player_id", "canonical_request_id", "operation_id", "rom_request_id"):
        _uuid(getattr(value, name), name)
    for name in ("build_id", "ruleset_id", "save_profile"):
        _identifier(getattr(value, name), name)
    for name in ("revision", "session_epoch", "incarnation"):
        _counter(getattr(value, name), name)
    for name in ("canonical_container_sha256", "canonical_flash_sha256",
                 "normalized_state_sha256", "actual_rom_flash_sha256"):
        _sha(getattr(value, name), name)
    if value.save_profile not in (LAYOUT_ID, OWNERSHIP_PROFILE):
        raise LiveReceiptError("save_profile_mismatch", "live receipt requires the pinned ordinary Flash profile")
    if (type(value.schema_version) is not int or value.schema_version != RECEIPT_SCHEMA_VERSION
            or type(value.trainer_id) is not int or not 0 <= value.trainer_id <= 0xFFFFFFFF
            or type(value.canonical_container_size) is not int
            or value.canonical_container_size not in (FLASH_SIZE, MAX_CONTAINER_SIZE)
            or type(value.rtc_footer_present) is not bool
            or value.rtc_footer_present != (value.canonical_container_size == MAX_CONTAINER_SIZE)
            or value.rtc_semantics != RTC_SEMANTICS):
        raise LiveReceiptError("invalid_metadata", "live receipt schema, trainer, size, or RTC semantics is invalid")
    if (not value.rtc_footer_present
            and value.canonical_container_sha256 != value.canonical_flash_sha256):
        raise LiveReceiptError("invalid_metadata", "a Flash-only canonical container has inconsistent digests")


def _metadata_bytes(receipt: LiveReceipt) -> bytes:
    return json.dumps(asdict(receipt), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _receipt_path(path: str | Path) -> Path:
    value = Path(path).resolve()
    if value.suffix.casefold() != ".json":
        raise LiveReceiptError("invalid_path", "live receipts require a separate JSON path")
    return value


def _no_duplicates(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise LiveReceiptError("receipt_corrupt", "receipt JSON contains duplicate fields")
        result[name] = value
    return result


def _invalid_constant(value):
    raise LiveReceiptError("receipt_corrupt", "receipt JSON contains a non-finite number")


def read_live_receipt(path: str | Path) -> LiveReceipt:
    """Verify bounded exact metadata and its checksum, without save-file access."""
    destination = _receipt_path(path)
    try:
        with destination.open("rb") as source:
            data = source.read(MAX_RECEIPT_BYTES + 1)
    except FileNotFoundError:
        raise LiveReceiptError("receipt_missing", "live receipt is missing") from None
    except OSError as error:
        raise LiveReceiptError("receipt_io_error", "live receipt could not be read") from error
    if len(data) > MAX_RECEIPT_BYTES:
        raise LiveReceiptError("receipt_corrupt", "live receipt exceeds its byte limit")
    try:
        envelope = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates,
                              parse_constant=_invalid_constant)
        if (not isinstance(envelope, dict) or set(envelope) != {"format", "receipt", "receipt_sha256"}
                or envelope["format"] != RECEIPT_FORMAT or not isinstance(envelope["receipt"], dict)
                or set(envelope["receipt"]) != set(LiveReceipt.__dataclass_fields__)):
            raise LiveReceiptError("receipt_corrupt", "live receipt has an unknown format or unexpected fields")
        receipt = LiveReceipt(**envelope["receipt"])
        _validate_receipt(receipt)
        _sha(envelope["receipt_sha256"], "receipt_sha256")
        if hashlib.sha256(_metadata_bytes(receipt)).hexdigest() != envelope["receipt_sha256"]:
            raise LiveReceiptError("receipt_corrupt", "live receipt metadata checksum disagrees")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        if isinstance(error, LiveReceiptError):
            raise
        raise LiveReceiptError("receipt_corrupt", "live receipt JSON is invalid") from error
    return receipt


def _verified_apply(downloaded: DownloadedCheckpoint, applied_flash: bytes,
                    operation_id: str, session_epoch: int, incarnation: int,
                    rom_request_id: str | None) -> LiveReceipt:
    try:
        metadata, payload = downloaded.metadata, downloaded.payload
        required = {"revision", "request_id", "size", "sha256", "build_id", "ruleset_id", "save_profile"}
        if not isinstance(metadata, dict) or set(metadata) != required:
            raise LiveReceiptError("invalid_metadata", "canonical checkpoint metadata has unexpected fields")
        _uuid(downloaded.world_id, "world_id")
        _uuid(downloaded.player_id, "player_id")
        _uuid(metadata["request_id"], "canonical_request_id")
        _uuid(operation_id, "operation_id")
        rom_request_id = operation_id if rom_request_id is None else rom_request_id
        _uuid(rom_request_id, "rom_request_id")
        for name in ("build_id", "ruleset_id", "save_profile"):
            _identifier(metadata[name], name)
        _counter(metadata["revision"], "revision")
        _counter(session_epoch, "session_epoch")
        _counter(incarnation, "incarnation")
        _sha(metadata["sha256"], "canonical_container_sha256")
        if metadata["save_profile"] not in (LAYOUT_ID, OWNERSHIP_PROFILE):
            raise LiveReceiptError("save_profile_mismatch", "canonical checkpoint has an unsupported native save profile")
        if (type(metadata["size"]) is not int or metadata["size"] not in (FLASH_SIZE, MAX_CONTAINER_SIZE)
                or not isinstance(payload, bytes) or len(payload) != metadata["size"]
                or hashlib.sha256(payload).hexdigest() != metadata["sha256"]):
            raise LiveReceiptError("checkpoint_mismatch", "canonical checkpoint bytes disagree with their metadata")
    except (AttributeError, KeyError, TypeError) as error:
        raise LiveReceiptError("invalid_metadata", "canonical checkpoint fields are missing or invalid") from error
    try:
        canonical = inspect_flash(payload, save_profile=metadata["save_profile"])
    except FlashError as error:
        raise LiveReceiptError("invalid_checkpoint", "canonical container failed ordinary Flash validation") from error
    if not isinstance(applied_flash, bytes) or len(applied_flash) != FLASH_SIZE:
        raise LiveReceiptError("invalid_readback", "native readback must contain exactly 128 KiB Flash")
    try:
        applied = inspect_flash(applied_flash, save_profile=metadata["save_profile"])
    except FlashError as error:
        raise LiveReceiptError("invalid_readback", "native Flash readback failed strict validation") from error
    if applied.metadata.trainer_id != canonical.metadata.trainer_id:
        raise LiveReceiptError("trainer_mismatch", "native readback belongs to another trainer")
    if applied.state_sha256 != canonical.state_sha256:
        raise LiveReceiptError("state_mismatch", "native readback does not contain the canonical game state")
    if canonical.save_profile == OWNERSHIP_PROFILE:
        from .ownership import inspect_ownership
        owner = inspect_ownership(canonical)
        if (owner.world_id, owner.player_id) != (downloaded.world_id, downloaded.player_id):
            raise LiveReceiptError("ownership_mismatch", "canonical Pokémon belong to another world or character")
    result = LiveReceipt(downloaded.world_id, downloaded.player_id, metadata["build_id"],
                         metadata["ruleset_id"], metadata["save_profile"], metadata["revision"],
                         metadata["request_id"], canonical.container_sha256, len(payload),
                         canonical.sha256, applied.state_sha256, applied.sha256,
                         canonical.metadata.trainer_id, operation_id, rom_request_id,
                         session_epoch, incarnation, bool(canonical.rtc_footer))
    _validate_receipt(result)
    return result


def record_live_apply(path: str | Path, downloaded: DownloadedCheckpoint,
                      applied_flash: bytes, *, operation_id: str, session_epoch: int,
                      incarnation: int, rom_request_id: str | None = None) -> LiveReceipt:
    """Publish one immutable verified receipt; exact retries are idempotent.

    The caller supplies a private, separate JSON path and verifies that the live
    world/session/bridge operation is still current before recording. Applying
    RTC bytes is explicitly outside this native Flash receipt's semantics.
    """
    destination = _receipt_path(path)
    receipt = _verified_apply(downloaded, applied_flash, operation_id, session_epoch,
                              incarnation, rom_request_id)
    lock = _ExclusiveFileLock(destination.with_name(destination.name + ".receipt.lock"))
    try:
        lock.acquire()
    except OSError as error:
        raise LiveReceiptError("receipt_active", "another operation owns this receipt path") from error
    staging = None
    try:
        if destination.exists():
            existing = read_live_receipt(destination)
            if existing != receipt:
                raise LiveReceiptError("receipt_conflict", "an immutable receipt already records a different apply")
            return existing
        envelope = {"format": RECEIPT_FORMAT, "receipt": asdict(receipt),
                    "receipt_sha256": hashlib.sha256(_metadata_bytes(receipt)).hexdigest()}
        data = (json.dumps(envelope, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
        if len(data) > MAX_RECEIPT_BYTES:
            raise LiveReceiptError("invalid_metadata", "live receipt exceeds its byte limit")
        descriptor, name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".stage",
                                             dir=destination.parent)
        staging = Path(name)
        with os.fdopen(descriptor, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(staging, destination)
        if os.name != "nt":
            directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except OSError as error:
        raise LiveReceiptError("receipt_io_error", "atomic live receipt publication was interrupted") from error
    finally:
        if staging is not None:
            with suppress(FileNotFoundError):
                staging.unlink()
        lock.release()
    return receipt
