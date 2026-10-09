"""Exact paired friendship candidates, with production effects still disabled.

The future store must supply authenticated canonical checkpoints and retained
history, validate leases/consent, and publish both outputs/history atomically.
This module performs no storage mutation and grants no new trade capability.
"""
from dataclasses import dataclass, field
import hashlib
import json

from .flash import FlashError, inspect_flash
from .gen6_friendship import TABLE_ID, VALUES_SHA256, base_friendship
from .ownership import OWNERSHIP_PROFILE, inspect_ownership
from .ownership_storage import _uuid
from .protocol import MAX_COUNTER
from .storage import Checkpoint, StorageError, _counter, _identifier, _player_id
from .trade_eligibility import validate_trade_pair
from .trade_flash import TradeFlashError, _party_record, _replace_record
from .trade_friendship import (
    FriendshipHistory, FriendshipPlanError, FriendshipTransition,
    TrainerIdentity, transform_received_party_record,
)

PLAN_ID = "gen6-paired-friendship-postimages-v2"


@dataclass(frozen=True)
class FriendshipOfferPlan:
    """Retained history and refresh policy; species bases are never caller input."""
    history: FriendshipHistory
    refresh_handler: bool


@dataclass(frozen=True)
class FriendshipPair:
    after_a: bytes = field(repr=False)
    after_b: bytes = field(repr=False)
    # Transitions retain offered-instance order: a is now received by b.
    offered_a: FriendshipTransition
    offered_b: FriendshipTransition
    input_sha256: str
    outcome_sha256: str


def _identity(identity):
    return [identity.name.hex(), identity.gender, identity.trainer_id, identity.version]


def _history(history):
    value = [history.serial, _identity(history.original), history.original_friendship,
            None if history.handler is None else _identity(history.handler),
            history.handling_friendship, history.current_handler, history.known]
    # Preserve existing complete-history fingerprints; initialized histories
    # carry an additional explicit policy/provenance field in every digest.
    if history.initialized_fields or history.handler_identity_unknown:
        value.append(["gen6-base-missing-handler-values-v1", list(history.initialized_fields), history.handler_identity_unknown])
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def _source(checkpoint):
    if type(checkpoint) is not Checkpoint or type(checkpoint.payload) is not bytes:
        raise TradeFlashError("friendship preparation needs immutable canonical checkpoint records")
    _player_id(checkpoint.player_id)
    _counter(checkpoint.revision, "revision", 1)
    _uuid(checkpoint.request_id, "request_id")
    _identifier(checkpoint.build_id, "build_id")
    _identifier(checkpoint.ruleset_id, "ruleset_id")
    if (checkpoint.revision == MAX_COUNTER or checkpoint.save_profile != OWNERSHIP_PROFILE
            or hashlib.sha256(checkpoint.payload).hexdigest() != checkpoint.sha256):
        raise TradeFlashError("canonical friendship source revision, profile or payload hash differs")
    snapshot = inspect_flash(checkpoint.payload, save_profile=OWNERSHIP_PROFILE)
    owner = inspect_ownership(snapshot)
    if owner.player_id != checkpoint.player_id:
        raise TradeFlashError("canonical envelope and native ownership identify different players")
    return snapshot, owner


def build_friendship_pair(a: Checkpoint, plan_a: FriendshipOfferPlan,
                          b: Checkpoint, plan_b: FriendshipOfferPlan, *, profile_game_version: int):
    """Construct both exact full-Flash outputs and immutable history transitions.

    Recipient name, gender and trainer ID come only from its canonical Flash.
    Gen6 species bases come from the generated pinned table using each exact
    offered record's species. Origin-game version and geographic refresh remain
    explicit trusted adapter inputs until their native profile is pinned.
    Existing egg/mail/evolution/form eligibility restrictions remain enforced.
    """
    try:
        for plan in (plan_a, plan_b):
            if type(plan) is not FriendshipOfferPlan or type(plan.history) is not FriendshipHistory:
                raise TradeFlashError("typed retained history and species policy are required for both offers")
            plan.history.validate()
        sa, oa = _source(a)
        sb, ob = _source(b)
        if (a.build_id, a.ruleset_id, a.save_profile) != (b.build_id, b.ruleset_id, b.save_profile):
            raise TradeFlashError("friendship sources have different build, rules or save profile")
        offered_a, offered_b = validate_trade_pair(a.payload, plan_a.history.serial,
                                                  b.payload, plan_b.history.serial)
        base_a, base_b = base_friendship(offered_a.species), base_friendship(offered_b.species)
        offset_a, mon_a = _party_record(sa, oa, plan_a.history.serial)
        offset_b, mon_b = _party_record(sb, ob, plan_b.history.serial)
        recipient_a = TrainerIdentity(sa.metadata.name, sa.metadata.gender, sa.metadata.trainer_id, profile_game_version)
        recipient_b = TrainerIdentity(sb.metadata.name, sb.metadata.gender, sb.metadata.trainer_id, profile_game_version)
        received_b, transition_a = transform_received_party_record(mon_a, plan_a.history, recipient_b,
            base_friendship=base_a, refresh_handler=plan_a.refresh_handler)
        received_a, transition_b = transform_received_party_record(mon_b, plan_b.history, recipient_a,
            base_friendship=base_b, refresh_handler=plan_b.refresh_handler)
        after_a = _replace_record(sa, offset_a, received_a)
        after_b = _replace_record(sb, offset_b, received_b)
        for snapshot, payload in ((sa, after_a), (sb, after_b)):
            inspect_ownership(inspect_flash(payload, expected_trainer_id=snapshot.metadata.trainer_id,
                                            save_profile=OWNERSHIP_PROFILE))
        sources = [[cp.player_id, cp.revision, cp.request_id, cp.sha256, _history(plan.history),
                    species, base, plan.refresh_handler]
                   for cp, plan, species, base in ((a, plan_a, offered_a.species, base_a),
                                                   (b, plan_b, offered_b.species, base_b))]
        input_sha = _digest([PLAN_ID, TABLE_ID, VALUES_SHA256, oa.world_id, a.build_id,
                            a.ruleset_id, a.save_profile, profile_game_version, sources])
        outcome_sha = _digest([input_sha, hashlib.sha256(after_a).hexdigest(), hashlib.sha256(after_b).hexdigest(),
                               _history(transition_a.history), _history(transition_b.history)])
        return FriendshipPair(after_a, after_b, transition_a, transition_b, input_sha, outcome_sha)
    except (FlashError, FriendshipPlanError, StorageError) as error:
        if isinstance(error, TradeFlashError):
            raise
        raise TradeFlashError(str(error)) from error


def validate_friendship_pair(a: Checkpoint, plan_a: FriendshipOfferPlan,
                             b: Checkpoint, plan_b: FriendshipOfferPlan,
                             after_a: bytes, after_b: bytes, *, profile_game_version: int):
    """Reconstruct both complete candidates; changed unrelated bytes are refused."""
    if type(after_a) is not bytes or type(after_b) is not bytes:
        raise TradeFlashError("friendship post-images must be immutable complete Flash bytes")
    expected = build_friendship_pair(a, plan_a, b, plan_b, profile_game_version=profile_game_version)
    if (after_a, after_b) != (expected.after_a, expected.after_b):
        raise TradeFlashError("friendship post-images differ from the exact paired preparation")
    return expected
