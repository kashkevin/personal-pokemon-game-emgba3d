"""Append-only native dispatch evidence for deterministic host reconstruction.

Each fsynced record precedes the action it publishes. A missing, truncated,
reordered or changed record blocks recovery; it never supplies a guessed reply.
The journal contains no executable snapshots or emulator RAM.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
import json
import os
from pathlib import Path
import stat

from .battle_execution_protocol import decode_control, encode_control
from .battle_journal import BattleJournalError
from .live_checkpoint import _json_bytes, _sync_directory
from .protocol import MAX_COUNTER
from .native_battle import NativeBinding, Opcode
from .native_battle_resume import ResumeAuthorization, ResumeQuery

FORMAT = "native-battle-route-events-v1"
MAX_LINE = 16384
MAX_BYTES = 256 * 1024 * 1024
MAX_EVENTS = 500000
ZERO_HASH = "0" * 64


class RouteJournal:
    def __init__(self, path, header, *, create=False):
        self.path = Path(path)
        self.header = header
        self.events = []
        self.digest = ZERO_HASH
        self.size = 0
        self._stamp = None
        self._tail = b""
        self._content_digest = hashlib.sha256()
        self.pending = {}
        self.admitted = {}
        self.ids = {}
        self.completed = []
        self.leases = tuple(header["leases"])
        self.lineage = [self.leases]
        self.renewal_epoch = 0
        self.renewal_digest = None
        if create:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.path, flags, 0o600)
            try:
                self._write_fd(fd, dict(kind="header", format=FORMAT, value=header))
            finally:
                os.close(fd)
            self._after_close()
            _sync_directory(self.path.parent)
        else:
            self._load()

    @staticmethod
    def _identity(info):
        # Windows Python's path stat and CRT descriptor stat disagree about
        # deprecated ctime (creation time versus change time). Both agree on
        # file identity, size and last-write time; POSIX also supplies ctime.
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                None if os.name == "nt" else info.st_ctime_ns)

    def _after_close(self):
        # Windows may publish final last-write metadata only after CloseHandle.
        # The identity and size must still be those of the fsynced descriptor.
        info = self.path.lstat()
        stamp = self._identity(info)
        if not stat.S_ISREG(info.st_mode) or stamp[:3] != self._stamp[:3]:
            raise BattleJournalError("battle_journal_changed", "native route evidence changed after its durable append")
        self._stamp = stamp

    @staticmethod
    def _record(sequence, previous, value):
        # Byte-identical to encoding dict(sequence, previous, value[, sha256]) with the canonical
        # sorted-key encoder (keys sort as previous < sequence < sha256 < value), but the large
        # value is encoded once instead of twice: loading a long journal does this per event.
        previous_json, value_json = _json_bytes(previous)[:-1], _json_bytes(value)[:-1]
        prefix = b'{"previous":' + previous_json + b',"sequence":' + str(sequence).encode()
        digest = hashlib.sha256(prefix + b',"value":' + value_json + b"}\n").hexdigest()
        raw = prefix + b',"sha256":"' + digest.encode() + b'","value":' + value_json + b"}\n"
        if len(raw) > MAX_LINE:
            raise BattleJournalError("battle_journal_limit", "native route event exceeds its byte bound")
        return raw, digest

    def _write_fd(self, fd, value):
        raw, digest = self._record(len(self.events), self.digest, value)
        if len(self.events) >= MAX_EVENTS or self.size + len(raw) > MAX_BYTES:
            raise BattleJournalError("battle_journal_limit", "native route evidence reached its safe bound")
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if not written:
                raise OSError("native route journal write made no progress")
            view = view[written:]
        os.fsync(fd)
        self._stamp = self._identity(os.fstat(fd))
        self._tail = raw
        self._content_digest.update(raw)
        self.events.append(value)
        self.digest, self.size = digest, self.size + len(raw)

    def _load(self):
        if not stat.S_ISREG(self.path.lstat().st_mode):
            raise BattleJournalError("battle_journal_invalid", "native route journal must be a regular file")
        try:
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(self.path, flags), "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("route evidence is not a regular file")
                initial = self._identity(info)
                while raw := source.readline(MAX_LINE + 1):
                    if len(raw) > MAX_LINE or not raw.endswith(b"\n"):
                        raise ValueError("truncated or oversized route evidence")
                    row = json.loads(raw)
                    if (type(row) is not dict or set(row) != {"sequence", "previous", "value", "sha256"}
                            or type(row["sequence"]) is not int or row["sequence"] != len(self.events)
                            or row["previous"] != self.digest):
                        raise ValueError("route evidence order changed")
                    expected, digest = self._record(len(self.events), self.digest, row["value"])
                    if raw != expected or row["sha256"] != digest:
                        raise ValueError("route evidence checksum or encoding changed")
                    value = row["value"]
                    if not self.events:
                        if value != dict(kind="header", format=FORMAT, value=self.header):
                            raise ValueError("route evidence belongs to another immutable battle")
                    else:
                        self._validate_event(value, apply=True)
                    self.events.append(value)
                    self.digest, self.size = digest, self.size + len(raw)
                    self._tail = raw
                    self._content_digest.update(raw)
                    if value.get("kind") == "renewal":
                        self.renewal_digest = digest
                    if len(self.events) > MAX_EVENTS or self.size > MAX_BYTES:
                        raise ValueError("route evidence exceeds its safe bound")
                if not self.events:
                    raise ValueError("route evidence has no committed header")
                self._stamp = self._identity(os.fstat(source.fileno()))
                if self._stamp != initial:
                    raise ValueError("route evidence changed while it was read")
        except (ValueError, KeyError, TypeError) as error:
            raise BattleJournalError("battle_journal_invalid", "native route evidence cannot be reconstructed exactly") from error

    def _validate_event(self, value, *, apply):
        if type(value) is dict and value.get("kind") == "admission":
            if (set(value) != {"kind", "actor", "control_sha256"}
                    or value["actor"] not in self.header["players"] or value["actor"] in self.admitted):
                raise ValueError("invalid or repeated durable native admission")
            pending = self.pending.get(value["actor"])
            if (pending is None or pending[1].opcode != Opcode.BIND
                    or value["control_sha256"] != hashlib.sha256(pending[1].pack()).hexdigest()):
                raise ValueError("native admission changed its exact first BIND")
            if apply:
                self.admitted[value["actor"]] = value["control_sha256"]
            return
        if type(value) is dict and value.get("kind") == "renewal":
            return self._validate_renewal(value, apply=apply)
        if (type(value) is not dict or set(value) != {"kind", "actor", "dispatch_id", "control_b64"}
                or value["kind"] not in ("command", "response")
                or value["actor"] not in self.header["players"]
                or type(value["dispatch_id"]) is not int or not 1 <= value["dispatch_id"] <= MAX_COUNTER):
            raise ValueError("invalid native route event")
        actor, ident = value["actor"], value["dispatch_id"]
        response = value["kind"] == "response"
        control = decode_control(value["control_b64"], response=response)
        slot = self.header["players"].index(actor)
        if (control.battle_id != self.header["battle_id"]
                or control.incarnation != self.header["incarnations"][slot]
                or control.session_epoch != self.leases[slot]
                or control.phase != self.header["mode"]):
            raise ValueError("route event changed its immutable battle binding")
        if response:
            pending = self.pending.get(actor)
            if pending is None or pending[0] != ident:
                raise ValueError("native reply has no outstanding exact dispatch")
            control.validate_response(pending[1])
            if apply:
                self.completed.append((actor, ident, pending[1], control))
                del self.pending[actor]
        else:
            if actor in self.pending or ident != self.ids.get(actor, 0) + 1:
                raise ValueError("native dispatch skipped or replaced an uncertain command")
            if apply:
                self.ids[actor] = ident
                self.pending[actor] = (ident, control)

    @staticmethod
    def rebind(command, leases):
        slot = command.source_slot
        # RECEIVE's source is the sending trainer, not the mailbox owner.
        # Callers supply the owning slot separately via the envelope below.
        if command.opcode == Opcode.BIND:
            binding = NativeBinding.unpack(command.data)
            return replace(command, session_epoch=leases[binding.local_slot],
                           data=replace(binding, leases=tuple(leases)).pack())
        return command

    def _renew_control(self, actor, command, leases):
        command = self.rebind(command, leases)
        return replace(command, session_epoch=leases[self.header["players"].index(actor)])

    def _validate_renewal(self, value, *, apply):
        if (set(value) != {"kind", "epoch", "leases", "proofs"}
                or type(value["epoch"]) is not int or not self.renewal_epoch < value["epoch"] <= MAX_COUNTER
                or type(value["leases"]) is not list or len(value["leases"]) != len(self.leases)
                or any(type(n) is not int or not old <= n <= MAX_COUNTER for n, old in zip(value["leases"], self.leases))
                or type(value["proofs"]) is not list or len(value["proofs"]) != len(self.leases)):
            raise ValueError("invalid native lease renewal lineage")
        token = None
        for slot, proof in enumerate(value["proofs"]):
            if type(proof) is not dict or set(proof) != {"suspend", "suspended", "authorize", "authorized"}:
                raise ValueError("lease renewal requires exact suspension and authorization receipts")
            suspend, suspended, authorize, authorized = [decode_control(proof[key], response=key in ("suspended", "authorized"))
                for key in ("suspend", "suspended", "authorize", "authorized")]
            suspended.validate_response(suspend); authorized.validate_response(authorize)
            old_query, new_query = ResumeQuery.unpack(suspended.data), ResumeQuery.unpack(authorized.data)
            auth = ResumeAuthorization.unpack(authorize.data)
            expected = NativeBinding(self.header["generation"], tuple(self.header["players"]), self.leases,
                tuple(self.header["incarnations"]), slot, mode=self.header["mode"], resumable=True)
            auth.validate_previous(expected)
            if (suspend.opcode != Opcode.SUSPEND or authorize.opcode != Opcode.REAUTHORIZE
                    or suspended.status or authorized.status
                    or not (old_query.suspended or old_query.released) or old_query.state != new_query.state
                    or auth.binding.leases != tuple(value["leases"]) or auth.epoch != value["epoch"]
                    or auth.last_sequence != old_query.query.last_sequence or auth.epoch <= old_query.epoch
                    or old_query.query != new_query.query or new_query.epoch != auth.epoch or new_query.token != auth.token
                    or (token is not None and token != auth.token)):
                raise ValueError("lease renewal does not prove the exact suspended quorum")
            if old_query.released:
                actor = self.header["players"][slot]
                possible = ([self.pending[actor][1]] if actor in self.pending else []) + [
                    command for owner, _, command, reply in self.completed if owner == actor and not reply.status]
                if not any(command.opcode == Opcode.RELEASE and command.sequence == auth.last_sequence for command in possible):
                    raise ValueError("released core lacks the exact previously authorized RELEASE")
            for control in (suspend, authorize):
                if (control.battle_id, control.incarnation, control.session_epoch, control.source_slot, control.phase) != (
                        self.header["battle_id"], self.header["incarnations"][slot], value["leases"][slot], slot, self.header["mode"]):
                    raise ValueError("lease renewal changed its authenticated original core")
            token = auth.token
        if apply:
            self.leases = tuple(value["leases"])
            self.lineage.append(self.leases)
            self.renewal_epoch = value["epoch"]
            self.pending = {actor: (ident, self._renew_control(actor, command, self.leases))
                            for actor, (ident, command) in self.pending.items()}

    def append(self, kind, actor, dispatch_id, control):
        self._append(dict(kind=kind, actor=actor, dispatch_id=dispatch_id, control_b64=encode_control(control)))

    def renew(self, epoch, leases, proofs):
        self._append(dict(kind="renewal", epoch=epoch, leases=list(leases), proofs=proofs))

    def admit(self, actor, control_sha256):
        self._append(dict(kind="admission", actor=actor, control_sha256=control_sha256))

    def verify_current(self):
        """Authenticate every current byte of an already validated journal.

        Per-append metadata and tail checks are bounded live-owner witnesses,
        not a whole-history integrity check: filesystem times can be coarse.
        The raw digest here matches the exact bytes validated at load/append.
        Cold reconstruction independently validates every record and link.
        """
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(self.path, flags), "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or self._identity(info) != self._stamp:
                raise BattleJournalError("battle_journal_changed", "native route evidence changed before use")
            digest = hashlib.sha256()
            size = 0
            while data := source.read(1024 * 1024):
                size += len(data)
                if size > self.size:
                    raise BattleJournalError("battle_journal_changed", "native route evidence grew outside its owner")
                digest.update(data)
            if (size != self.size or digest.digest() != self._content_digest.digest()
                    or self._identity(os.fstat(source.fileno())) != self._stamp
                    or self._identity(self.path.lstat()) != self._stamp):
                raise BattleJournalError("battle_journal_changed", "native route evidence differs from its committed bytes")

    def _append(self, value):
        self._validate_event(value, apply=False)
        info = self.path.lstat()
        if not stat.S_ISREG(info.st_mode) or self._identity(info) != self._stamp:
            raise BattleJournalError("battle_journal_changed", "native route evidence changed outside its owner")
        flags = os.O_RDWR | os.O_APPEND | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags)
        try:
            if self._identity(os.fstat(fd)) != self._stamp:
                raise BattleJournalError("battle_journal_changed", "native route evidence changed before append")
            # WSL/ext4 can give two writes the same mtime/ctime tick. Compare
            # the latest committed record as well, with at most MAX_LINE bytes
            # of extra I/O per append; do not hash a growing history each time.
            os.lseek(fd, self.size - len(self._tail), os.SEEK_SET)
            tail = bytearray()
            while len(tail) < len(self._tail):
                data = os.read(fd, len(self._tail) - len(tail))
                if not data:
                    break
                tail.extend(data)
            if bytes(tail) != self._tail or self._identity(os.fstat(fd)) != self._stamp:
                raise BattleJournalError("battle_journal_changed", "native route evidence tail changed before append")
            self._write_fd(fd, value)
        finally:
            os.close(fd)
        self._after_close()
        self._validate_event(value, apply=True)
        if value["kind"] == "renewal":
            self.renewal_digest = self.digest
