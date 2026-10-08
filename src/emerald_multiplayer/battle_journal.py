"""Durable admission intent for an unresolved development native battle.

This module never settles a battle, dispatches a command, declares a result,
releases a hold or deletes an intent. Its only mutating context persists the
exact BIND first and retains character admission ownership through dispatch.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from uuid import UUID, uuid4

from .battle_roster import CanonicalBattler
from .checkpoint_client import CheckpointClient, validate_metadata
from .native_battle import NativeBinding, NativeControl, Opcode, supports_native_phase
from .ownership import OWNERSHIP_PROFILE
from .protocol import MAX_COUNTER

FORMAT = "emerald-pending-native-battle-v1"
MAX_JOURNAL_BYTES = 16384
FILENAME = "pending-battle.json"
_SHA = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_FIELDS = {"schema", "world_id", "player_id", "build_id", "ruleset_id", "save_profile",
    "server_epoch", "lease_epoch", "incarnation", "runtime_id", "generation", "battle_id",
    "canonical_revision", "canonical_sha256", "bind_b64"}


class BattleJournalError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def path_present(path) -> bool:
    """A malformed, unreadable or dangling path is never an absent intent."""
    try:
        Path(path).lstat()
        return True
    except FileNotFoundError:
        return False
    except (OSError, TypeError, ValueError) as error:
        raise BattleJournalError("pending_battle", "pending battle intent cannot be inspected safely") from error


def pending_battle(companion, directory=None) -> bool:
    paths = [] if directory is None else [Path(directory) / FILENAME, Path(directory) / "pending-battle-admission.json"]
    registered = getattr(companion, "_live_battle_pending_path", None)
    if registered is not None:
        paths.extend((registered, Path(registered).with_name("pending-battle-admission.json")))
    return any(path_present(path) for path in paths)


def register_battle_path(companion, path):
    path = Path(path)
    previous = getattr(companion, "_live_battle_pending_path", None)
    if previous is not None and Path(previous) != path and (path_present(previous)
            or path_present(Path(previous).with_name("pending-battle-admission.json"))):
        raise BattleJournalError("pending_battle", "another private directory owns pending battle recovery")
    companion._live_battle_pending_path = path
    return path


def _uuid(value):
    if type(value) is not str or str(UUID(value)) != value or not UUID(value).int:
        raise ValueError("UUID must be canonical and nonzero")


def _counter(value, maximum=MAX_COUNTER):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("counter must be a bounded positive integer")


def _identifier(value):
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("identity must be a bounded protocol identifier")


def _validate(value):
    try:
        if type(value) is not dict or set(value) != _FIELDS or type(value["schema"]) is not int or value["schema"] != 1:
            raise ValueError("intent field set/version is invalid")
        for key in ("world_id", "player_id", "runtime_id", "generation", "battle_id"):
            _uuid(value[key])
        for key in ("build_id", "ruleset_id"):
            _identifier(value[key])
        if value["save_profile"] != OWNERSHIP_PROFILE:
            raise ValueError("intent requires the exact ownership profile")
        for key in ("server_epoch", "lease_epoch", "canonical_revision"):
            _counter(value[key])
        _counter(value["incarnation"], 0xFFFFFFFF)
        if type(value["canonical_sha256"]) is not str or _SHA.fullmatch(value["canonical_sha256"]) is None:
            raise ValueError("canonical checkpoint digest is invalid")
        encoded = value["bind_b64"]
        if type(encoded) is not str or len(encoded) != 320:
            raise ValueError("intent must contain exactly one 240-byte BIND")
        raw = base64.b64decode(encoded, validate=True)
        if base64.b64encode(raw).decode("ascii") != encoded:
            raise ValueError("BIND encoding is not canonical")
        command = NativeControl.unpack(raw)
        if command.opcode != Opcode.BIND:
            raise ValueError("admission intent must contain BIND")
        binding = NativeBinding.unpack(command.data)
        command.validate_command(binding=binding, player_id=value["player_id"])
        if (command.battle_id, binding.generation, command.session_epoch, command.incarnation) != (
                value["battle_id"], value["generation"], value["lease_epoch"], value["incarnation"]):
            raise ValueError("BIND correlation differs from its intent")
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        raise BattleJournalError("invalid_battle_journal", "pending battle intent is malformed or inconsistent") from error
    return command


@dataclass(frozen=True)
class BattleIntent:
    world_id: str
    player_id: str
    build_id: str
    ruleset_id: str
    save_profile: str
    server_epoch: int
    lease_epoch: int
    incarnation: int
    runtime_id: str
    generation: str
    battle_id: str
    canonical_revision: int
    canonical_sha256: str
    bind: NativeControl = field(repr=False)

    @classmethod
    def from_value(cls, value):
        command = _validate(value)
        return cls(**{key: value[key] for key in _FIELDS - {"schema", "bind_b64"}}, bind=command)

    def value(self):
        return dict(schema=1, **{key: getattr(self, key) for key in _FIELDS - {"schema", "bind_b64"}},
                    bind_b64=base64.b64encode(self.bind.pack()).decode("ascii"))


def read_battle_intent(path) -> BattleIntent:
    """Read immutable bounded metadata without granting any action authority."""
    from .live_checkpoint import _json_bytes
    try:
        path = Path(path)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("an intent must be a regular file")
        with path.open("rb") as source:
            raw = source.read(MAX_JOURNAL_BYTES + 1)
        if len(raw) > MAX_JOURNAL_BYTES:
            raise ValueError("intent exceeds its bound")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate intent field")
                result[key] = value
            return result
        envelope = json.loads(raw, object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if (type(envelope) is not dict or set(envelope) != {"format", "intent", "sha256"}
                or envelope["format"] != FORMAT or type(envelope["sha256"]) is not str
                or _SHA.fullmatch(envelope["sha256"]) is None
                or hashlib.sha256(_json_bytes(envelope["intent"])).hexdigest() != envelope["sha256"]):
            raise ValueError("intent format/digest is invalid")
        return BattleIntent.from_value(envelope["intent"])
    except BattleJournalError:
        raise
    except (OSError, ValueError, TypeError, RecursionError, OverflowError) as error:
        raise BattleJournalError("invalid_battle_journal", "pending battle intent cannot be verified") from error


class BattleJournal:
    """Only matching development ABI2/3 may persist BIND; no settlement API.

    Call ``async with journal.bind_intent(binding, command, canonical) as intent``
    before dispatching ``intent.bind``. The lock and exact battle owner remain
    held across the caller's await. Cancellation or any uncertain reply leaves
    the durable intent. A fresh process/core/lease cannot rebind this journal.
    """

    def __init__(self, companion, private_directory):
        self.companion = companion
        self.directory = Path(private_directory).resolve()
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.path = register_battle_path(companion, self.directory / FILENAME)
        if getattr(companion, "_live_battle_runtime_id", None) is None:
            companion._live_battle_runtime_id = str(uuid4())

    def _session(self):
        c = self.companion
        try:
            if (c.connected is not True or c.config.development_battle_channel is not True
                    or type(c.config.battle_abi_version) is not int or c.config.battle_abi_version not in (2, 3)
                    or c.config.ownership_enabled is not True
                    or type(c.config.server_credential) is not bytes or len(c.config.server_credential) != 32
                    or c.save_profile != OWNERSHIP_PROFILE):
                raise ValueError()
            _uuid(c.world_id); _uuid(c.config.player_id); _uuid(c._live_battle_runtime_id)
            _identifier(c.config.build_id); _identifier(c.config.ruleset_id)
            _counter(c.server_epoch); _counter(c.session_epoch); _counter(c.battle_incarnation, 0xFFFFFFFF)
        except (ValueError, TypeError, AttributeError, ConnectionError) as error:
            raise BattleJournalError("battle_admission_required", "intent needs an authenticated development ABI2/3 game") from error
        return (c.world_id, c.config.player_id, c.config.build_id, c.config.ruleset_id, c.save_profile,
                c.server_epoch, c.session_epoch, c.battle_incarnation, c._live_battle_runtime_id)

    def _current(self, intent):
        fields = (intent.world_id, intent.player_id, intent.build_id, intent.ruleset_id, intent.save_profile,
                  intent.server_epoch, intent.lease_epoch, intent.incarnation, intent.runtime_id)
        if self._session() != fields or not supports_native_phase(self.companion.config.battle_abi_version, intent.bind.phase):
            raise BattleJournalError("battle_recovery_required", "pending battle belongs to a prior authenticated runtime; retain intent")

    def load(self):
        intent = read_battle_intent(self.path)
        self._current(intent)
        return intent

    def _candidate(self, binding, command, canonical):
        from .live_checkpoint import _json_bytes
        try:
            session = self._session()
            if not isinstance(binding, NativeBinding) or not isinstance(command, NativeControl) or not isinstance(canonical, CanonicalBattler):
                raise ValueError()
            command.validate_command(binding=binding, player_id=session[1])
            if (command.opcode != Opcode.BIND or canonical.world_id != session[0] or canonical.player_id != session[1]
                    or canonical.source_slot != binding.local_slot or canonical.mode != binding.mode
                    or not supports_native_phase(self.companion.config.battle_abi_version, command.phase)
                    or command.session_epoch != session[6]
                    or command.incarnation != session[7]):
                raise ValueError()
            value = dict(schema=1, **dict(zip(("world_id", "player_id", "build_id", "ruleset_id", "save_profile",
                "server_epoch", "lease_epoch", "incarnation", "runtime_id"), session)),
                generation=binding.generation, battle_id=command.battle_id,
                canonical_revision=canonical.revision, canonical_sha256=canonical.checkpoint_sha256,
                bind_b64=base64.b64encode(command.pack()).decode("ascii"))
            intent = BattleIntent.from_value(value)
            raw = _json_bytes(dict(format=FORMAT, intent=value,
                sha256=hashlib.sha256(_json_bytes(value)).hexdigest()))
            if len(raw) > MAX_JOURNAL_BYTES:
                raise ValueError()
        except BattleJournalError:
            raise
        except (ValueError, TypeError, AttributeError) as error:
            raise BattleJournalError("battle_intent_mismatch", "BIND and canonical party must match this authenticated actor") from error
        return intent, raw

    def _other_recovery(self):
        paths = [self.directory / "pending-export.json", self.directory / "pending-trade.json"]
        for name in ("_live_export_pending_path", "_live_trade_pending_path"):
            registered = getattr(self.companion, name, None)
            if registered is not None:
                paths.append(registered)
        if any(path_present(path) for path in paths):
            raise BattleJournalError("character_recovery_pending", "resolve save or trade recovery before native battle admission")

    async def _canonical_head(self, candidate):
        # Metadata belongs to the authenticated actor. World/player and all
        # session pins are rechecked after the await; metadata itself carries
        # the exact build/rules/profile and current revision/container hash.
        self._current(candidate)
        metadata = await CheckpointClient(self.companion).info()
        self._current(candidate)
        try:
            metadata = validate_metadata(metadata, self.companion.config, candidate.save_profile)
            if metadata is None or (metadata["revision"], metadata["sha256"]) != (
                    candidate.canonical_revision, candidate.canonical_sha256):
                raise ValueError("canonical descriptor is not the current checkpoint")
        except (ValueError, TypeError, KeyError) as error:
            raise BattleJournalError("canonical_head_mismatch", "native battle admission requires this actor's exact current canonical checkpoint") from error

    async def _admit(self, binding, command, canonical):
        from .live_checkpoint import _atomic, _sync_directory
        candidate, raw = self._candidate(binding, command, canonical)
        self._other_recovery()
        if path_present(self.path):
            intent = self.load()
            if intent != candidate:
                raise BattleJournalError("battle_intent_conflict", "pending battle cannot be replaced by another BIND")
        # Fence both first publication and exact uncertain-BIND retries.
        # No further await occurs between this check and durable admission.
        await self._canonical_head(candidate)
        self._other_recovery()
        if path_present(self.path):
            intent = self.load()
            if intent != candidate:
                raise BattleJournalError("battle_intent_conflict", "pending battle changed during canonical admission")
        else:
            stage = self.directory / (str(uuid4()) + ".battle-intent.stage")
            try:
                _atomic(stage, raw)
                try:
                    # Same-directory exclusive atomic publication. Never
                    # replace another process's unresolved intent.
                    os.link(stage, self.path)
                except FileExistsError:
                    if self.load() != candidate:
                        raise BattleJournalError("battle_intent_conflict", "another pending battle owns admission")
                _sync_directory(self.directory)
            finally:
                with suppress(FileNotFoundError):
                    stage.unlink()
            intent = self.load()
        self._current(intent)
        return intent

    @asynccontextmanager
    async def bind_intent(self, binding, command, canonical):
        c = self.companion
        async with c.live_checkpoint_lock:
            if getattr(c, "_live_save_owner", None) is not None or getattr(c, "_live_battle_owner", None) is not None:
                raise BattleJournalError("character_busy", "another lifecycle owns this character's admission")
            # Fence direct companion mutators during the awaited head lookup,
            # before a pending file exists. No BIND authority exists yet.
            c._live_save_owner = c._live_battle_owner = asyncio.current_task()
            c._live_battle_admission_control = None
            try:
                intent = await self._admit(binding, command, canonical)
                c._live_battle_admission_control = intent.bind
                yield intent
                self._current(intent)
            finally:
                c._live_save_owner = c._live_battle_owner = None
                c._live_battle_admission_control = None
