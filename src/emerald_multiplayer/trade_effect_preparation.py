"""Versioned public effect plans derived exclusively from canonical host data.

The v1 exact-swap descriptor is unchanged. A v2 plan has no candidate hash until
the recipient supplies its explicit move choices and the host replays native
code. Neither a plan nor a receipt alone authorizes publication.
"""
from __future__ import annotations

import base64
import hashlib
import json

from .flash import inspect_flash
from .gen6_friendship import TABLE_ID, VALUES_SHA256
from .ownership import OWNERSHIP_PROFILE, inspect_ownership
from .protocol import MAX_COUNTER
from .trade_effect_flash import EffectOfferPlan, PLAN_ID, GIFT_RIBBONS, GIFT_RIBBON_COUNT
from .trade_effect_witness import EvolutionMoveChoice, MAX_CHOICES, _history, _record
from .trade_flash import _party_record
from .trade_friendship_migration import _encode, _decode
from .trade_preparation import TradePreparationError, _FIELDS, _PLAYER_FIELDS, _hash, _uuid, _require

FORMAT = "emerald-trade-recipient-effects-v2"
VERSION = 1
POLICIES = frozenset({"gen6-stable-world-region-v1", "gen6-absent-geography-refresh-v1"})


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value):
    return hashlib.sha256(canonical(value).encode("ascii")).hexdigest()


def decode_effect_plan(value):
    _require(type(value) is dict and set(value) == {"player_id", "history", "refresh_handler", "gift_ribbons"},
             "invalid offered effect plan")
    _require(_uuid(value["player_id"]) and type(value["refresh_handler"]) is bool,
             "invalid effect owner or handler decision")
    history = _decode(value["history"])
    try:
        gifts = base64.b64decode(value["gift_ribbons"], validate=True)
    except (ValueError, TypeError) as error:
        raise TradePreparationError("invalid original gift ribbon bytes") from error
    _require(len(gifts) == 7 and base64.b64encode(gifts).decode("ascii") == value["gift_ribbons"],
             "effect source must contain exactly seven original ribbon bytes")
    return EffectOfferPlan(history, value["refresh_handler"])


def preparation_id(value):
    effects = value["effects"]
    sources = [[p["player_id"], p["lease_epoch"], p["revision"], p["request_id"], p["sha256"],
                _history(decode_effect_plan(plan).history), plan["refresh_handler"]]
               for p, plan in zip(value["players"], effects["offers"])]
    # Exactly the identity used by prepare_effect_pair / EffectContext.
    return digest([PLAN_ID, TABLE_ID, VALUES_SHA256, value["world_id"], value["build_id"], value["ruleset_id"],
        OWNERSHIP_PROFILE, value["transaction_id"], value["generation"], value["fingerprint"],
        effects["engine_source_sha256"], effects["profile_game_version"], sources])


def validate_effect_preparation(value):
    _require(type(value) is dict and set(value) == _FIELDS | {"effects"}, "invalid effect preparation fields")
    _require((value["format"], value["capability"], value["save_profile"]) == (FORMAT, PLAN_ID, OWNERSHIP_PROFILE),
             "unsupported recipient effect plan")
    for key in ("world_id", "transaction_id", "generation", "recipient_id"):
        _require(_uuid(value[key]), "invalid effect preparation identity")
    for key in ("build_id", "ruleset_id"):
        _require(type(value[key]) is str and 1 <= len(value[key]) <= 128 and value[key].isprintable(),
                 "invalid effect build identity")
    _require(_hash(value["fingerprint"]) and _hash(value["preparation_id"]), "invalid preparation digest")
    players = value["players"]
    _require(type(players) is list and len(players) == 2, "two effect recipients required")
    for p in players:
        _require(type(p) is dict and set(p) == _PLAYER_FIELDS, "invalid effect recipient fields")
        _require(_uuid(p["player_id"]) and _uuid(p["request_id"]), "invalid effect recipient identity")
        for key in ("lease_epoch", "revision"):
            _require(type(p[key]) is int and 1 <= p[key] <= MAX_COUNTER, "invalid effect recipient counter")
        _require(type(p["serial"]) is int and 1 <= p["serial"] <= 0xFFFFF, "invalid effect instance")
        _require(all(_hash(p[key]) for key in ("sha256", "record_sha256")) and p["candidate_sha256"] is None,
                 "effect candidates cannot be claimed before native replay")
        _require(type(p["candidate_size"]) is int and p["candidate_size"] in (131072, 131088), "invalid effect save size")
    ids = [p["player_id"] for p in players]
    _require(ids == sorted(set(ids)) and value["recipient_id"] in ids and players[0]["serial"] != players[1]["serial"],
             "invalid effect pair")
    effects = value["effects"]
    _require(type(effects) is dict and set(effects) == {"engine_source_sha256", "profile_game_version", "policy_id", "offers"},
             "invalid effect policy fields")
    _require(_hash(effects["engine_source_sha256"]) and type(effects["profile_game_version"]) is int
             and effects["profile_game_version"] == 3 and effects["policy_id"] in POLICIES,
             "unapproved or incompatible effect policy")
    _require(type(effects["offers"]) is list and len(effects["offers"]) == 2, "both effect histories required")
    for p, raw in zip(players, effects["offers"]):
        plan = decode_effect_plan(raw)
        _require(raw["player_id"] == p["player_id"] and plan.history.serial == p["serial"], "effect history names another offer")
        _require(plan.refresh_handler == (effects["policy_id"] == "gen6-absent-geography-refresh-v1"),
                 "effect handler decision contradicts world policy")
    try:
        incoming = base64.b64decode(value["incoming_record"], validate=True)
    except (ValueError, TypeError) as error:
        raise TradePreparationError("invalid incoming effect record") from error
    peer = next(p for p in players if p["player_id"] != value["recipient_id"])
    _require(len(incoming) == 100 and base64.b64encode(incoming).decode("ascii") == value["incoming_record"]
             and hashlib.sha256(incoming).hexdigest() == peer["record_sha256"], "incoming effect record differs")
    _require(_record(incoming)[0][0] == peer["serial"], "incoming effect identity differs")
    _require(preparation_id(value) == value["preparation_id"], "effect preparation identity differs")
    return value


def describe_effect_pair(world_id, transaction_id, generation, fingerprint, checkpoints, leases, plans,
                         *, engine_source_sha256, profile_game_version, policy_id):
    _require(type(checkpoints) is tuple and len(checkpoints) == 2 and type(plans) is tuple and len(plans) == 2,
             "exact original pair required")
    first = checkpoints[0]
    players, records, offers = [], [], []
    for cp, lease, plan in zip(checkpoints, leases, plans):
        snapshot = inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)
        owned = inspect_ownership(snapshot)
        _require((owned.world_id, owned.player_id) == (world_id, cp.player_id)
                 and hashlib.sha256(cp.payload).hexdigest() == cp.sha256
                 and (cp.build_id, cp.ruleset_id, cp.save_profile) == (first.build_id, first.ruleset_id, OWNERSHIP_PROFILE),
                 "canonical effect checkpoint differs")
        _, record = _party_record(snapshot, owned, plan.history.serial)
        _record(record)
        records.append(record)
        players.append(dict(player_id=cp.player_id, lease_epoch=lease, revision=cp.revision,
            request_id=cp.request_id, sha256=cp.sha256, serial=plan.history.serial,
            record_sha256=hashlib.sha256(record).hexdigest(), candidate_sha256=None, candidate_size=len(cp.payload)))
        offers.append(dict(player_id=cp.player_id, history=_encode(plan.history), refresh_handler=plan.refresh_handler,
            gift_ribbons=base64.b64encode(snapshot.save_block1[GIFT_RIBBONS:GIFT_RIBBONS + GIFT_RIBBON_COUNT]).decode("ascii")))
    common = dict(format=FORMAT, capability=PLAN_ID, world_id=world_id, build_id=first.build_id,
        ruleset_id=first.ruleset_id, save_profile=OWNERSHIP_PROFILE, transaction_id=transaction_id,
        generation=generation, fingerprint=fingerprint, players=players,
        effects=dict(engine_source_sha256=engine_source_sha256, profile_game_version=profile_game_version,
                     policy_id=policy_id, offers=offers))
    common["preparation_id"] = preparation_id(common)
    descriptions = tuple(dict(common, recipient_id=cp.player_id,
        incoming_record=base64.b64encode(records[1 - i]).decode("ascii")) for i, cp in enumerate(checkpoints))
    for description in descriptions:
        validate_effect_preparation(description)
    return descriptions


def validate_effect_receipt(value):
    _require(type(value) is dict and set(value) == {"choices", "candidate_sha256", "candidate_size", "record_sha256"},
             "invalid native effect receipt fields")
    _require(_hash(value["candidate_sha256"]) and _hash(value["record_sha256"])
             and type(value["candidate_size"]) is int and value["candidate_size"] in (131072, 131088),
             "invalid effect candidate digest or size")
    choices = value["choices"]
    _require(type(choices) is list and len(choices) <= MAX_CHOICES, "effect choice transcript exceeds its native bound")
    for choice in choices:
        _require(type(choice) is list and len(choice) == 2, "invalid evolution move choice")
        EvolutionMoveChoice(*choice).validate()
    return tuple(EvolutionMoveChoice(*choice) for choice in choices)
