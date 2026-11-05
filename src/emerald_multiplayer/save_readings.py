"""Each save's checked reading, remembered by the save's content: the world-open cache (KNOWN_ISSUES MS-161, the owner's
option (b), chosen 2026-11-05). Design and threat model: docs/world-open-cache.md.

Opening a world checks it whole (storage.CheckpointStore.integrity_check): the save reader reads every save again
(flash.inspect_flash and ownership.inspect_ownership, and trade_friendship_observations for a world with handler history)
and the ownership, order and handler-history replays are rebuilt from those readings. A save's reading depends only on its
bytes and on the reader's code, so it is remembered here, in a file beside the world's database
(``world.sqlite3.save-readings``), and a save is read once in its life. Everything else still runs on every open: the
database's own checks, every save's stored hash, and every replay in full.

Why it cannot make the check accept anything it refused before:

* An entry is found by the SHA-256 of the save's bytes, computed from the bytes on every open; only an exact match is
  used. A save whose bytes changed (damaged, edited, replaced) has another hash and is read by the reader again.
* Only readings the reader accepted are remembered, never a refusal, and what depends on more than the bytes (the
  enrolled trainer, the checkpoint's player and fields) is checked on every open as the reader checks it.
* The file is bound to the reader's code: READER_FINGERPRINT is a SHA-256 of the reader's source (READER_MODULES, this
  module included), pinned here and checked by tests/test_save_readings.py, so a change to any of them fails the suite
  until the pin is updated, and the new pin discards every older file. Run from source with a stale pin, the cache is
  off. Also bound: the file format, the Python version, the save profile and the world's id.
* The file is sealed (a SHA-256 over all of it): torn, truncated, damaged or edited, or from another version, profile or
  world, it is ignored whole and rebuilt. An entry that does not decode exactly, or whose Pokemon do not reproduce the
  manifest digest the reader computed from the bytes, is ignored and the save read again.
* Only an integrity check uses it (a save, trade or transfer reads the save itself), and only for a store opened with
  ``save_readings=True`` (HostWorld's). Nothing in it can stop a check: anything unexpected falls back to the reader, and
  a file that cannot be written is reported once and the next open reads every save again. It can always be deleted.
"""
from __future__ import annotations

from contextlib import suppress
import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import threading
import uuid

from .flash import MAX_SPECIES_ID, FlashError, inspect_flash
from .ownership import (
    OWNERSHIP_PROFILE, RETIRE_CAPACITY, SERIAL_LIMIT, SERIAL_MAX, OwnershipRecord, OwnershipSnapshot, Retirement,
    inspect_ownership, manifest_sha256,
)
from .windows_files import replace_file

SUFFIX = ".save-readings"                  # the file beside the database: world.sqlite3.save-readings
FORMAT = 1
MAGIC = b"EMERALD-SAVE-READINGS\n"
MAX_FILE_BYTES = 256 * 1024 * 1024
# The code a remembered reading depends on: the reader itself, the handler-history observation, and this module's own
# encoding of a reading. READER_FINGERPRINT is the SHA-256 of their source (reader_fingerprint), this line left out.
READER_MODULES = ("flash", "ownership", "trade_friendship_observations", "save_readings")
READER_FINGERPRINT = "14972b8a40290fd2b505c64a317235e7ca49a0c3e745a9d29be7b93503323bb1"
_PIN = re.compile(rb'^READER_FINGERPRINT = "[0-9a-f]{64}"$', re.M)
_PYTHON = "%d.%d" % sys.version_info[:2]
_FIELDS = frozenset({"format", "reader", "python", "profile", "world", "records", "observations", "saves"})
_HEX64 = re.compile(r"[0-9a-f]{64}")
_LOCATION = re.compile(r"party:[0-5]|box:(?:1[0-3]|[0-9]):(?:[12][0-9]|[0-9])|daycare:[01]|fusion:[0-3]")
_UINT32 = 0xFFFFFFFF


def reader_fingerprint() -> str | None:
    """SHA-256 of the save reader's source code: READER_MODULES in order, this module without its READER_FINGERPRINT
    line. None when the source is not at hand (the packaged app runs compiled modules: it trusts READER_FINGERPRINT,
    which the test suite checked against the source it was built from)."""
    digest = hashlib.sha256(b"emerald-save-reader\0")
    for name in READER_MODULES:
        source = getattr(importlib.import_module(f"{__package__}.{name}"), "__file__", None)
        if not source or not str(source).endswith(".py"):
            return None
        try:
            text = Path(source).read_bytes().replace(b"\r\n", b"\n")
        except OSError:
            return None
        if name == "save_readings":
            text, pins = _PIN.subn(b'READER_FINGERPRINT = ""', text)
            if pins != 1:
                return "the READER_FINGERPRINT line is missing or changed its form"
        digest.update(b"%s\0%d\0" % (name.encode("ascii"), len(text)))
        digest.update(text)
    return digest.hexdigest()


_reader_state: list[bool] = []
_reported: set[tuple[str, str]] = set()
_lock = threading.Lock()


def _reader_current() -> bool:
    """False when the reader's source is at hand and differs from READER_FINGERPRINT (code changed, pin not updated).
    Worked out once in a process."""
    if not _reader_state:
        try:
            actual = reader_fingerprint()
        except Exception:                                                 # noqa: BLE001 - the cache is optional
            actual = "unknown"
        with _lock:
            if not _reader_state:
                _reader_state.append(actual is None or actual == READER_FINGERPRINT)
    return _reader_state[0]


def _report_once(path: Path, what: str) -> None:
    """One line on stderr per file and kind of trouble in a process (the check itself goes on without the cache)."""
    key = (str(path), what.split(" (")[0])
    with _lock:
        if key in _reported:
            return
        _reported.add(key)
    with suppress(Exception):
        print(f"[launcher] world-open cache {path.name}: {what}", file=sys.stderr)


def _seal(body: bytes) -> bytes:
    digest = hashlib.sha256(b"emerald-save-readings-seal\0")
    digest.update(body)
    return digest.hexdigest().encode("ascii")


def _refuse_constant(_):
    raise ValueError("not a JSON number")


def _uint(value, low: int = 0, high: int = _UINT32) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("remembered number is outside its bounds")
    return value


def _uuid(value) -> str:
    if type(value) is not str or str(uuid.UUID(value)) != value or uuid.UUID(value).int == 0:
        raise ValueError("remembered identity is not a canonical nonzero UUID")
    return value


def _hex64(value) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise ValueError("remembered digest is not 64 lowercase hex digits")
    return value


def _list(value, length: int | None = None) -> list:
    if type(value) is not list or (length is not None and len(value) != length):
        raise ValueError("remembered value has the wrong shape")
    return value


def _read(path: Path) -> bytes | None:
    """The file's bytes; None when there is none. A file there that cannot be used gives b"" (it is replaced)."""
    try:
        status = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        _report_once(path, f"could not be read ({type(error).__name__}); every save is read again")
        return b""
    if not stat.S_ISREG(status.st_mode) or status.st_size > MAX_FILE_BYTES:
        _report_once(path, "is not a regular file of a usable size; it is rebuilt")
        return b""
    try:
        with open(path, "rb") as stream:                  # closed at once: Windows cannot replace a file held open
            return stream.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        return None
    except OSError as error:
        _report_once(path, f"could not be read ({type(error).__name__}); every save is read again")
        return b""


def _write(path: Path, data: bytes) -> None:
    """``path`` replaced whole: a new file beside it, synced, then moved over it (a reader sees the old or the new)."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        replace_file(temporary, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(temporary)
        raise


class SaveReadings:
    """The remembered readings of one world, for one integrity check: opened as the check starts, kept (written when the
    check learned or dropped something) when it has passed, then forgotten. Not shared between threads."""

    def __init__(self, database_path: Path, world_id: str, save_profile: str):
        database_path = Path(database_path)
        self.path = database_path.with_name(database_path.name + SUFFIX)
        self.world_id, self.save_profile = world_id, save_profile
        self._saves: dict = {}            # digest -> {"o": ..., "f": ...}, as read from the file
        self._records: list = []          # the file's table of Pokemon records
        self._observations: list = []     # the file's table of handler-history observations
        self._record_memo: dict = {}
        self._observation_memo: dict = {}
        self._identities: set = set()     # identities already checked (a world's few repeat in every save)
        self._used: dict = {}             # digest -> {"o": (trainer_id, OwnershipSnapshot), "f": (player_id, values)}
        self._learned = False             # a reading was made by the reader in this check
        self._replace = False             # a file is there that could not be used
        self._load()

    @classmethod
    def open(cls, database_path: Path, world_id: str, save_profile: str) -> SaveReadings | None:
        """The cache for one check, or None when it is off (the reader's source differs from READER_FINGERPRINT)."""
        path = Path(database_path)
        if not _reader_current():
            _report_once(path.with_name(path.name + SUFFIX),
                         "is off: the save reader's code differs from READER_FINGERPRINT (save_readings.py)")
            return None
        try:
            return cls(path, world_id, save_profile)
        except Exception:                                                 # noqa: BLE001 - the cache is optional
            return None

    # ------------------------------------------------------------------------------------------------ the file

    def _load(self) -> None:
        data = _read(self.path)
        if data is None:
            return
        try:
            if not data.startswith(MAGIC):
                raise ValueError("not a save readings file")
            seal, body = data[len(MAGIC):len(MAGIC) + 65], data[len(MAGIC) + 65:]
            if seal[64:] != b"\n" or not hmac.compare_digest(seal[:64], _seal(body)):
                raise ValueError("the seal does not match")
            value = json.loads(body, parse_constant=_refuse_constant)
            if type(value) is not dict or set(value) != _FIELDS:
                raise ValueError("unknown layout")
            header = (value["format"], value["reader"], value["python"], value["profile"], value["world"])
            if type(value["format"]) is not int or header != (FORMAT, READER_FINGERPRINT, _PYTHON, self.save_profile,
                                                              self.world_id):
                self._replace = True
                _report_once(self.path, "was made by another version of the reader or for another world; it is rebuilt")
                return
            records, observations, saves = _list(value["records"]), _list(value["observations"]), value["saves"]
            if type(saves) is not dict or any(_HEX64.fullmatch(digest) is None or type(parts) is not dict or not parts
                                              or not set(parts) <= {"o", "f"} for digest, parts in saves.items()):
                raise ValueError("unknown layout")
        except Exception:                                                 # noqa: BLE001 - never trusted, only rebuilt
            self._replace = True
            _report_once(self.path, "is damaged or incomplete; it is ignored and rebuilt")
            return
        self._records, self._observations, self._saves = records, observations, saves

    def keep(self) -> None:
        """After the check passed: write the readings this check used, when it made one or the file differs."""
        try:
            used = {digest: set(parts) for digest, parts in self._used.items()}
            if not self._learned and not self._replace and used == {d: set(p) for d, p in self._saves.items()}:
                return
            _write(self.path, self._encode())
        except Exception as error:                                        # noqa: BLE001 - the cache is optional
            _report_once(self.path, f"could not be written ({type(error).__name__}); every save is read on every open")

    def _encode(self) -> bytes:
        records: dict = {}
        observations: dict = {}
        saves = {}
        for digest in sorted(self._used):
            parts, entry = self._used[digest], {}
            if "o" in parts:
                trainer_id, owned = parts["o"]
                refs = [records.setdefault((r.serial, r.location, r.personality, r.ot_id, r.species, r.content_sha256),
                                           len(records)) for r in owned.records]
                entry["o"] = [trainer_id, owned.world_id, owned.player_id, owned.grant_id, owned.start, owned.end_exclusive,
                              owned.next_serial, owned.lease_epoch, owned.incarnation,
                              [[r.serial, r.reason] for r in owned.retirements], owned.manifest_sha256, refs]
            if "f" in parts:
                player_id, values = parts["f"]
                entry["f"] = [player_id, [observations.setdefault(value, len(observations)) for value in values]]
            saves[digest] = entry
        body = json.dumps(dict(format=FORMAT, reader=READER_FINGERPRINT, python=_PYTHON, profile=self.save_profile,
                               world=self.world_id, records=[list(r) for r in records],
                               observations=[list(o) for o in observations], saves=saves),
                          sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
        return MAGIC + _seal(body) + b"\n" + body

    # ------------------------------------------------------------------------------------------------ ownership

    def ownership(self, payload: bytes, expected_trainer_id: int, save_profile: str) -> OwnershipSnapshot:
        """``inspect_ownership(inspect_flash(payload, expected_trainer_id=..., save_profile=...))``: the same reading or
        the same refusal, from the reading remembered for these exact bytes when there is one."""
        if type(payload) is not bytes or save_profile != self.save_profile:
            return inspect_ownership(inspect_flash(payload, expected_trainer_id=expected_trainer_id,
                                                   save_profile=save_profile))
        digest = hashlib.sha256(payload).hexdigest()
        remembered = self._ownership_part(digest)
        if remembered is not None and type(expected_trainer_id) is int and 0 <= expected_trainer_id <= _UINT32:
            trainer_id, owned = remembered
            if trainer_id != expected_trainer_id:
                # inspect_flash's refusal for these bytes and this trainer: the reading passed every other check.
                raise FlashError("checkpoint trainer identity does not match its enrolled owner")
            return owned
        snapshot = inspect_flash(payload, expected_trainer_id=expected_trainer_id, save_profile=save_profile)
        owned = inspect_ownership(snapshot)
        self._learn(digest, "o", (snapshot.metadata.trainer_id, owned))
        return owned

    def _ownership_part(self, digest: str):
        used = self._used.get(digest)
        if used is not None and "o" in used:
            return used["o"]
        raw = self._saves.get(digest, {}).get("o")
        if raw is None:
            return None
        try:
            part = self._decode_ownership(raw)
        except Exception:                                                 # noqa: BLE001 - read the save again
            _report_once(self.path, "has an entry that does not check out; that save is read again")
            return None
        self._used.setdefault(digest, {})["o"] = part
        return part

    def _decode_ownership(self, raw) -> tuple[int, OwnershipSnapshot]:
        (trainer_id, world_id, player_id, grant_id, start, end_exclusive, next_serial, lease_epoch, incarnation,
         retired, manifest, refs) = _list(raw, 12)
        # The bounds the reader itself enforces (ownership._parse_metadata); the manifest below covers the Pokemon.
        _uint(trainer_id)
        for identity in (world_id, player_id, grant_id):
            if identity not in self._identities:
                self._identities.add(_uuid(identity))
        _hex64(manifest)
        _uint(start, 1, SERIAL_LIMIT - 1)
        _uint(end_exclusive, start + 1, SERIAL_LIMIT)
        _uint(next_serial, start, end_exclusive)
        _uint(lease_epoch, 1)
        _uint(incarnation, 1)
        retirements = tuple(Retirement(_uint(serial, 1, SERIAL_MAX), _uint(reason, 1, 2))
                            for serial, reason in (_list(item, 2) for item in _list(retired)))
        if len(retirements) > RETIRE_CAPACITY or len({r.serial for r in retirements}) != len(retirements):
            raise ValueError("remembered retirements are not a valid journal")
        records = tuple(self._record(index) for index in _list(refs))
        if len({r.serial for r in records}) != len(records) or len({r.location for r in records}) != len(records):
            raise ValueError("remembered Pokemon repeat a serial or a location")
        if manifest_sha256(world_id, player_id, records) != manifest:
            raise ValueError("remembered Pokemon differ from the reader's manifest")
        return trainer_id, OwnershipSnapshot(world_id, player_id, grant_id, start, end_exclusive, next_serial, lease_epoch,
                                             incarnation, retirements, records, manifest)

    def _record(self, index) -> OwnershipRecord:
        if type(index) is not int or not 0 <= index < len(self._records):
            raise ValueError("remembered record index is outside the table")
        if index not in self._record_memo:
            self._record_memo[index] = None
            serial, location, personality, ot_id, species, content = _list(self._records[index], 6)
            if type(location) is not str or _LOCATION.fullmatch(location) is None:
                raise ValueError("remembered location is not an owned slot")
            self._record_memo[index] = OwnershipRecord(_uint(serial, 1, SERIAL_MAX), location, _uint(personality),
                                                       _uint(ot_id), _uint(species, 1, MAX_SPECIES_ID), _hex64(content))
        record = self._record_memo[index]
        if record is None:
            raise ValueError("remembered record does not check out")
        return record

    # ------------------------------------------------------------------------------------------------ handler history

    def observations(self, checkpoint) -> tuple[tuple[int, str], ...]:
        """``(serial, observation)`` of each row of ``checkpoint_observations(checkpoint)``, in its order: the same values
        or the same refusal, from the values remembered for the checkpoint's exact bytes when there are some."""
        from .trade_friendship_observations import checkpoint_observations
        digest = self._observable(checkpoint)
        if digest is not None:
            remembered = self._observation_part(digest)
            if remembered is not None and remembered[0] == checkpoint.player_id:
                return remembered[1]
        values = tuple((serial, raw) for _, _, serial, raw, _ in checkpoint_observations(checkpoint))
        if digest is not None:
            # checkpoint_observations accepted it: the bytes hash to ``digest`` and belong to the checkpoint's player.
            self._learn(digest, "f", (checkpoint.player_id, values))
        return values

    def _observable(self, checkpoint) -> str | None:
        """The payload's SHA-256 when every check checkpoint_observations makes before reading the save holds, else None
        (the observation then runs and refuses as it does)."""
        from .storage import Checkpoint, StorageError, _counter, _player_id
        if (type(checkpoint) is not Checkpoint or type(checkpoint.payload) is not bytes
                or checkpoint.save_profile != OWNERSHIP_PROFILE or self.save_profile != OWNERSHIP_PROFILE):
            return None
        try:
            _player_id(checkpoint.player_id)
            _counter(checkpoint.revision, "revision", 1)
        except StorageError:
            return None
        digest = hashlib.sha256(checkpoint.payload).hexdigest()
        return digest if digest == checkpoint.sha256 else None

    def _observation_part(self, digest: str):
        used = self._used.get(digest)
        if used is not None and "f" in used:
            return used["f"]
        raw = self._saves.get(digest, {}).get("f")
        if raw is None:
            return None
        try:
            part = self._decode_observations(raw, digest)
        except Exception:                                                 # noqa: BLE001 - read the save again
            _report_once(self.path, "has an entry that does not check out; that save is read again")
            return None
        self._used.setdefault(digest, {})["f"] = part
        return part

    def _decode_observations(self, raw, digest: str) -> tuple[str, tuple[tuple[int, str], ...]]:
        player_id, refs = _list(raw, 2)
        if player_id not in self._identities:
            self._identities.add(_uuid(player_id))
        values = tuple(self._observation(index) for index in _list(refs))
        serials = [serial for serial, _ in values]
        owned = self._ownership_part(digest)
        if serials != sorted(set(serials)) or owned is not None and (
                owned[1].player_id != player_id or serials != sorted(r.serial for r in owned[1].records)):
            raise ValueError("remembered observations differ from the save's Pokemon")
        return player_id, values

    def _observation(self, index) -> tuple[int, str]:
        if type(index) is not int or not 0 <= index < len(self._observations):
            raise ValueError("remembered observation index is outside the table")
        if index not in self._observation_memo:
            self._observation_memo[index] = None
            serial, text = _list(self._observations[index], 2)
            if type(text) is not str or type(json.loads(text, parse_constant=_refuse_constant)) is not dict:
                raise ValueError("remembered observation is not a JSON object")
            self._observation_memo[index] = (_uint(serial, 1, SERIAL_MAX), text)
        value = self._observation_memo[index]
        if value is None:
            raise ValueError("remembered observation does not check out")
        return value

    # ------------------------------------------------------------------------------------------------ learning

    def _learn(self, digest: str, part: str, value) -> None:
        """A reading the reader has just made (and accepted) for the bytes with this digest."""
        self._used.setdefault(digest, {})[part] = value
        self._learned = True
