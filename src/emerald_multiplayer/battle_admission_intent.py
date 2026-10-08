"""Immutable local admission before the host has exposed the complete BIND.

This module records the accepted challenge and exact original ADMIT. It does
not dispatch, renew, acknowledge, convert or remove either battle intent.
"""
from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import stat
from uuid import uuid4

from .battle_execution_protocol import decode_control, encode_control
from .battle_journal import BattleJournalError, _counter, _identifier, _uuid, path_present
from .battle_protocol import _view
from .battle_roster import CanonicalBattler
from .live_checkpoint import _atomic, _json_bytes, _sync_directory
from .native_battle import NativeControl, Opcode
from .native_battle_resume import Admission
from .ownership import OWNERSHIP_PROFILE

FILENAME = "pending-battle-admission.json"
FORMAT = "emerald-pending-battle-admission-v1"
MAX_JOURNAL_BYTES = 16384
MAX_CHALLENGE_BYTES = 8192
_SESSION_FIELDS = ("world_id", "player_id", "build_id", "ruleset_id", "save_profile",
                   "server_epoch", "lease_epoch", "incarnation", "runtime_id")
_FIELDS = {"schema", *_SESSION_FIELDS, "canonical_revision", "canonical_sha256", "challenge", "admit_b64"}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate admission field")
        result[key] = value
    return result


def _load(raw):
    return json.loads(raw, object_pairs_hook=_unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def _digest(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("admission requires an exact lowercase SHA256 digest")


@dataclass(frozen=True)
class BattleAdmissionIntent:
    world_id: str
    player_id: str
    build_id: str
    ruleset_id: str
    save_profile: str
    server_epoch: int
    lease_epoch: int
    incarnation: int
    runtime_id: str
    canonical_revision: int
    canonical_sha256: str
    challenge_bytes: bytes = field(repr=False)
    admit: NativeControl = field(repr=False)

    def __post_init__(self):
        try:
            for name in ("world_id", "player_id", "runtime_id"):
                _uuid(getattr(self, name))
            for name in ("build_id", "ruleset_id"):
                _identifier(getattr(self, name))
            for name in ("server_epoch", "lease_epoch", "canonical_revision"):
                _counter(getattr(self, name))
            _counter(self.incarnation, 0xFFFFFFFF)
            _digest(self.canonical_sha256)
            if self.save_profile != OWNERSHIP_PROFILE:
                raise ValueError("provisional admission requires owned saves")
            if type(self.challenge_bytes) is not bytes or len(self.challenge_bytes) > MAX_CHALLENGE_BYTES:
                raise ValueError("challenge must be immutable bounded bytes")
            challenge = _load(self.challenge_bytes)
            if _json_bytes(challenge) != self.challenge_bytes:
                raise ValueError("challenge bytes must be canonical")
            _view(challenge, self.player_id)
            if (challenge["state"] != "accepted" or challenge["outcome"] is not None
                    or set(challenge["consent"]) != set(challenge["players"])):
                raise ValueError("every original participant must accept this challenge")
            slot = challenge["players"].index(self.player_id)
            checkpoint = challenge["checkpoints"][slot]
            if (checkpoint["revision"], checkpoint["sha256"]) != (self.canonical_revision, self.canonical_sha256):
                raise ValueError("accepted checkpoint differs from the admission base")
            expected = NativeControl(self.incarnation, self.lease_epoch, challenge["battle_id"], 1,
                Opcode.ADMIT, phase=challenge["mode"], source_slot=slot,
                data=Admission(challenge["generation"], self.player_id, self.runtime_id).pack())
            if type(self.admit) is not NativeControl or self.admit != expected:
                raise ValueError("ADMIT differs from its exact original runtime and consent")
            self.admit.validate_command()
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as error:
            raise BattleJournalError("invalid_battle_admission", "provisional battle intent is malformed or inconsistent") from error

    @property
    def challenge(self):
        """Return a fresh object; callers cannot mutate the stored consent."""
        return _load(self.challenge_bytes)

    @property
    def battle_id(self):
        return self.admit.battle_id

    @property
    def generation(self):
        return Admission.unpack(self.admit.data).generation

    def value(self):
        return dict(schema=1, **{name: getattr(self, name) for name in _SESSION_FIELDS},
            canonical_revision=self.canonical_revision, canonical_sha256=self.canonical_sha256,
            challenge=self.challenge, admit_b64=encode_control(self.admit))

    @classmethod
    def from_value(cls, value):
        try:
            if type(value) is not dict or set(value) != _FIELDS or type(value["schema"]) is not int or value["schema"] != 1:
                raise ValueError("admission field set/version differs")
            return cls(**{name: value[name] for name in _SESSION_FIELDS},
                canonical_revision=value["canonical_revision"], canonical_sha256=value["canonical_sha256"],
                challenge_bytes=_json_bytes(value["challenge"]), admit=decode_control(value["admit_b64"]))
        except BattleJournalError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as error:
            raise BattleJournalError("invalid_battle_admission", "provisional battle value cannot be verified") from error


def read_admission_intent(path):
    """Read metadata without granting native or authenticated authority."""
    try:
        path = Path(path)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("admission must be a regular file")
        with path.open("rb") as source:
            raw = source.read(MAX_JOURNAL_BYTES + 1)
        if len(raw) > MAX_JOURNAL_BYTES:
            raise ValueError("admission exceeds its size bound")
        envelope = _load(raw)
        if (type(envelope) is not dict or set(envelope) != {"format", "intent", "sha256"}
                or envelope["format"] != FORMAT or _json_bytes(envelope) != raw):
            raise ValueError("admission envelope differs from its canonical format")
        _digest(envelope["sha256"])
        if hashlib.sha256(_json_bytes(envelope["intent"])).hexdigest() != envelope["sha256"]:
            raise ValueError("admission digest differs")
        return BattleAdmissionIntent.from_value(envelope["intent"])
    except BattleJournalError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, RecursionError, OverflowError) as error:
        raise BattleJournalError("invalid_battle_admission", "provisional battle intent cannot be read safely") from error


def create_admission_intent(companion, challenge, canonical_roster):
    """Construct only; the caller still owns current-head checking/publication."""
    c, canonical = companion, canonical_roster
    try:
        bridge = c._bridge
        if (c.connected is not True or c.config.development_battle_channel is not True
                or type(c.config.battle_abi_version) is not int or c.config.battle_abi_version != 3
                or type(c.config.battle_resume_abi_version) is not int or c.config.battle_resume_abi_version != 1
                or c.config.ownership_enabled is not True or type(c.config.server_credential) is not bytes
                or len(c.config.server_credential) != 32 or bridge is None or bridge.battle_capable is not True
                or type(canonical) is not CanonicalBattler or c.battle_incarnation != bridge.incarnation):
            raise ValueError("provisional admission requires the original authenticated capable core")
        _view(challenge, c.config.player_id)
        slot = challenge["players"].index(c.config.player_id)
        accepted = challenge["checkpoints"][slot]
        if ((canonical.world_id, canonical.player_id, canonical.source_slot, canonical.mode,
             canonical.revision, canonical.checkpoint_sha256, canonical.party_count) !=
            (c.world_id, c.config.player_id, slot, challenge["mode"], accepted["revision"],
             accepted["sha256"], accepted["party_count"])):
            raise ValueError("canonical roster differs from the accepted original challenge")
        command = NativeControl(c.battle_incarnation, c.session_epoch, challenge["battle_id"], 1,
            Opcode.ADMIT, phase=challenge["mode"], source_slot=slot,
            data=Admission(challenge["generation"], c.config.player_id, c._live_battle_runtime_id).pack())
        return BattleAdmissionIntent(c.world_id, c.config.player_id, c.config.build_id, c.config.ruleset_id,
            c.save_profile, c.server_epoch, c.session_epoch, c.battle_incarnation, c._live_battle_runtime_id,
            canonical.revision, canonical.checkpoint_sha256, _json_bytes(challenge), command)
    except BattleJournalError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, ConnectionError, RecursionError, OverflowError) as error:
        raise BattleJournalError("battle_admission_required", "provisional intent needs exact original authentication and consent") from error


def publish_admission_intent(path, intent):
    """Exclusive atomic publication; exact retry never replaces original bytes."""
    if type(intent) is not BattleAdmissionIntent:
        raise BattleJournalError("invalid_battle_admission", "publication requires a verified provisional intent")
    path = Path(path)
    value = intent.value()
    if BattleAdmissionIntent.from_value(value) != intent:
        raise BattleJournalError("invalid_battle_admission", "provisional intent changed before publication")
    raw = _json_bytes(dict(format=FORMAT, intent=value, sha256=hashlib.sha256(_json_bytes(value)).hexdigest()))
    if len(raw) > MAX_JOURNAL_BYTES:
        raise BattleJournalError("invalid_battle_admission", "provisional intent exceeds its size bound")
    if path_present(path):
        if read_admission_intent(path) != intent:
            raise BattleJournalError("battle_admission_conflict", "another unresolved provisional battle owns this path")
        # A prior publication may have linked successfully but lost its
        # directory-sync receipt. Reconfirm durability without replacing it.
        _sync_directory(path.parent)
        return intent
    stage = path.with_name(str(uuid4()) + ".battle-admission.stage")
    try:
        _atomic(stage, raw)
        try:
            os.link(stage, path)
        except FileExistsError:
            if read_admission_intent(path) != intent:
                raise BattleJournalError("battle_admission_conflict", "another original admission won publication")
        _sync_directory(path.parent)
    finally:
        with suppress(FileNotFoundError):
            stage.unlink()
    if read_admission_intent(path) != intent:
        raise BattleJournalError("battle_admission_conflict", "published provisional admission changed")
    return intent
