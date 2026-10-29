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
import threading
import time

from .battle_execution_protocol import decode_control, encode_control
from .battle_journal import BattleJournalError
from .live_checkpoint import _json_bytes, _sync_directory
from .protocol import MAX_COUNTER
from .native_battle import NativeBinding, Opcode
from .native_battle_resume import ResumeAuthorization, ResumeQuery

# v2 (2026-10-15): the router sends KEEP only when the native deadline needs it (battle_execution
# KEEP_BELOW_FRAMES / KEEP_EVERY_STEPS). v1 journals were written by a router that sent KEEP on every
# step; recovery must replay a journal with the policy that wrote it, so the format names the policy.
# v3 (2026-10-23, KNOWN_ISSUES MS-62): the pipelined router (battle_execution._NativeRoute.round): every core gets its
# own next command each round, all at once, so one core's commands follow another order than v2's lock-step steps.
# v4 (2026-10-23, KNOWN_ISSUES MS-62): the observed router (battle_execution._NativeRoute.run_observed), for PC games with
# battle PEEK: each launcher sends its core's state and each new block as they happen ("observation" events, PEEK
# responses), and the router answers every response and observation in the order this journal records them, so
# recovery replays them in that order.
# v5 (2026-10-23, KNOWN_ISSUES MS-62): v4's router with RECEIVE_MANY (games with battle_receive_many_abi_version 1): with
# three or four cores a batch's whole small blocks for one core go in one command, so recovery must pack them the same.
# v6 (2026-10-24, KNOWN_ISSUES MS-62's battle speed): the delivering router (games with battle_deliver_abi_version 1): it
# acknowledges each block as soon as it holds it, hands a core its acknowledgement and every block it is owed in one
# DELIVER in one global order (no batches), lets slave cores take the others' replies and DONEs with the master's next
# command, and takes a launcher's observation while a command to it is outstanding; recovery must route the same way.
FORMAT = "native-battle-route-events-v3"
OBSERVED_FORMAT = "native-battle-route-events-v4"
MANY_FORMAT = "native-battle-route-events-v5"
DELIVER_FORMAT = "native-battle-route-events-v6"
LEGACY_FORMATS = ("native-battle-route-events-v1", "native-battle-route-events-v2")
# Records written without their own fsync (KNOWN_ISSUES MS-62: a battle has thousands of commands, and each fsync is slow
# on a player's Windows PC). Step 10 (the owner's decision of 2026-10-29: "do every other turn but do it as a background
# save, don't make players wait"): a transport command's record no longer waits for its fsync either. It is written
# before the command goes out, so a crash of a game, a launcher or the host itself loses nothing (the system holds what
# was written), and it is made durable in the background (FLUSH_SECONDS, flush()) or by the next lifecycle command's own
# fsync (BIND, RELEASE, ...: still fsynced before they go out, with every record before them). Only a power cut or a
# system crash can lose the newest records; recovery then finds a core past its journal and refuses (battle_order):
# the battle is abandoned with no result, as the owner accepted.
_TRANSPORT = frozenset((Opcode.QUERY, Opcode.PEEK, Opcode.READ_OUT, Opcode.RECEIVE, Opcode.RECEIVE_MANY, Opcode.DELIVER,
                        Opcode.ACK_OUT, Opcode.KEEP))
# The background flush's interval while records wait for it: about every other turn (a turn between players takes several
# seconds of commands); it never holds a command back.
FLUSH_SECONDS = 10.0
MAX_LINE = 16384
MAX_BYTES = 256 * 1024 * 1024
MAX_EVENTS = 500000
ZERO_HASH = "0" * 64


class RouteJournal:
    def __init__(self, path, header, *, create=False, format=None):
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
        # Every response and observation in journal order (observed router: what recovery replays it with).
        self.routed = []
        # Step 10: how many records an fsync has made durable, and the background flush (one at a time)
        self._synced = 0
        self._flush_lock = threading.Lock()
        self._flushing = False
        self._last_flush = time.monotonic()
        format = FORMAT if format is None else format
        if format not in (FORMAT, OBSERVED_FORMAT, MANY_FORMAT, DELIVER_FORMAT):
            raise ValueError("a new route journal takes a current format")
        self.format = format
        if create:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.path, flags, 0o600)
            try:
                self._write_fd(fd, dict(kind="header", format=format, value=header))
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

    def _write_fd(self, fd, value, sync=True):
        raw, digest = self._record(len(self.events), self.digest, value)
        if len(self.events) >= MAX_EVENTS or self.size + len(raw) > MAX_BYTES:
            raise BattleJournalError("battle_journal_limit", "native route evidence reached its safe bound")
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if not written:
                raise OSError("native route journal write made no progress")
            view = view[written:]
        if sync:
            os.fsync(fd)
        self._stamp = self._identity(os.fstat(fd))
        self._tail = raw
        self._content_digest.update(raw)
        self.events.append(value)
        self.digest, self.size = digest, self.size + len(raw)
        if sync:
            with self._flush_lock:
                self._synced = len(self.events)

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
                        if (type(value) is not dict or value.get("format") not in (FORMAT, OBSERVED_FORMAT, MANY_FORMAT, DELIVER_FORMAT) + LEGACY_FORMATS
                                or value != dict(kind="header", format=value["format"], value=self.header)):
                            raise ValueError("route evidence belongs to another immutable battle")
                        self.format = value["format"]
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
        if type(value) is dict and value.get("kind") == "observation":
            return self._validate_observation(value, apply=apply)
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
                or control.phase != self.header["mode"]
                or (control.opcode == Opcode.RECEIVE_MANY and not self.receive_many)
                or (control.opcode == Opcode.DELIVER and not self.deliver)):
            raise ValueError("route event changed its immutable battle binding")
        if response:
            pending = self.pending.get(actor)
            if pending is None or pending[0] != ident:
                raise ValueError("native reply has no outstanding exact dispatch")
            control.validate_response(pending[1])
            if apply:
                self.completed.append((actor, ident, pending[1], control))
                self.routed.append(("response", actor, ident, pending[1], control))
                del self.pending[actor]
        else:
            if actor in self.pending or ident != self.ids.get(actor, 0) + 1:
                raise ValueError("native dispatch skipped or replaced an uncertain command")
            if apply:
                self.ids[actor] = ident
                self.pending[actor] = (ident, control)

    def _validate_observation(self, value, *, apply):
        """An observed router's PEEK response from a launcher with no outstanding command (KNOWN_ISSUES MS-62); the
        delivering router's (v6) also while one is outstanding (BattleExecutionService.observe)."""
        from .native_battle import peek_parts
        if (not self.observed or set(value) != {"kind", "actor", "control_b64"}
                or value["actor"] not in self.header["players"] or (value["actor"] in self.pending and not self.deliver)):
            raise ValueError("invalid native route observation")
        actor = value["actor"]
        control = decode_control(value["control_b64"], response=True)
        slot = self.header["players"].index(actor)
        if (control.opcode != Opcode.PEEK or control.status or control.battle_id != self.header["battle_id"]
                or control.incarnation != self.header["incarnations"][slot]
                or control.session_epoch != self.leases[slot]
                or control.phase != self.header["mode"] or control.source_slot != slot):
            raise ValueError("route observation changed its immutable battle binding")
        peek_parts(control)
        if apply:
            self.routed.append(("observation", actor, control))

    @property
    def observed(self):
        """A v4, v5 or v6 journal's router answered pushed observations (_NativeRoute.run_observed)."""
        return self.format in (OBSERVED_FORMAT, MANY_FORMAT, DELIVER_FORMAT)

    @property
    def receive_many(self):
        """A v5 journal's router packed a batch's small blocks for a core into one RECEIVE_MANY."""
        return self.format == MANY_FORMAT

    @property
    def deliver(self):
        """A v6 journal's router delivered (_NativeRoute._next_delivered)."""
        return self.format == DELIVER_FORMAT

    def observe(self, actor, control):
        self._append(dict(kind="observation", actor=actor, control_b64=encode_control(control)), sync=False)

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

    @property
    def keeps_every_step(self):
        """A v1 journal's router sent KEEP on every step; replaying it needs the same."""
        return self.format == LEGACY_FORMATS[0]

    @property
    def pipelined(self):
        """A v3 journal's router ran its rounds (_NativeRoute.round); v1 and v2 ran its lock-step steps."""
        return self.format not in LEGACY_FORMATS and not self.observed

    def append(self, kind, actor, dispatch_id, control):
        self._append(dict(kind=kind, actor=actor, dispatch_id=dispatch_id, control_b64=encode_control(control)),
                     sync=control.opcode not in _TRANSPORT)

    @property
    def unsynced(self):
        """Records written that no fsync has made durable yet (step 10)."""
        return self._synced < len(self.events)

    def flush(self):
        """Make every record written so far durable (step 10): the background flush's work, also usable directly."""
        upto = len(self.events)
        flags = os.O_RDWR | os.O_APPEND | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        with self._flush_lock:
            self._synced = max(self._synced, upto)

    def _flush_in_background(self):
        try:
            self.flush()
        except OSError:
            pass  # the battle's files went away (closed and cleaned up): nothing is left to keep
        finally:
            with self._flush_lock:
                self._flushing = False

    def _flush_later(self):
        """After a record written without its fsync: a background flush once FLUSH_SECONDS have passed since the last
        one, in a thread of its own, so the command it follows goes out at once."""
        if not self.unsynced or time.monotonic() - self._last_flush < FLUSH_SECONDS:
            return
        with self._flush_lock:
            if self._flushing:
                return
            self._flushing = True
        self._last_flush = time.monotonic()
        threading.Thread(target=self._flush_in_background, name="battle-journal-flush", daemon=True).start()

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

    def _append(self, value, sync=True):
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
            self._write_fd(fd, value, sync)
        finally:
            os.close(fd)
        self._after_close()
        self._validate_event(value, apply=True)
        if value["kind"] == "renewal":
            self.renewal_digest = self.digest
        if not sync:
            self._flush_later()
