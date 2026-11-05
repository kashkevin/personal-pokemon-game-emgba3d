"""Exact recipient candidates before the paired ownership commit.

The v1 candidate builder preserves the exact-record exchange. The validator
also dispatches authenticated v2 effect descriptions to their separate native
plan validator; v2 cannot use the v1 candidate builder. Both expose only one
incoming party record, never the peer's whole save.

A pair with an Egg or a Pokemon holding Mail (owner decision 39) uses the
Egg-and-Mail capability (EGGS_MAIL_CAPABILITY): the same format, each offer also
naming the SHA-256 of the Mail its Pokemon holds (``mail_sha256``, null without
one), and each recipient's description the whole incoming Mail
(``incoming_mail``: 36 bytes, base64; null), so the recipient rebuilds its own
post-image (trade_flash.recipient_post_image) as the host does. Every other pair
keeps the plain capability and its exact fields, which launchers from before
read as they did; such a launcher refuses an Egg-and-Mail description before
acknowledging it, so nothing moves.
"""
from __future__ import annotations

import base64
import hashlib
import json
from uuid import UUID

from .flash import POKEMON_SIZE, inspect_flash
from .ownership import OWNERSHIP_PROFILE, inspect_ownership
from .protocol import MAX_COUNTER
from .storage import Checkpoint
from .trade_eligibility import (
    CAPABILITY_ID as TRADE_CAPABILITY, EGGS_MAIL_CAPABILITY_ID as EGGS_MAIL_CAPABILITY,
    validate_party_offer, validate_trade_pair,
)
from .trade_flash import _party_record, build_party_swap, recipient_post_image
from .trade_mail import MAIL_SIZE

PREPARATION_FORMAT = "emerald-trade-recipient-preparation-v1"
_FIELDS = {"format", "capability", "world_id", "build_id", "ruleset_id", "save_profile",
    "transaction_id", "generation", "fingerprint", "players", "preparation_id",
    "recipient_id", "incoming_record"}
_PLAYER_FIELDS = {"player_id", "lease_epoch", "revision", "request_id", "sha256",
    "serial", "record_sha256", "candidate_sha256", "candidate_size"}
_MAIL_FIELDS = _FIELDS | {"incoming_mail"}
_MAIL_PLAYER_FIELDS = _PLAYER_FIELDS | {"mail_sha256"}
_MAIL_TEXT = 48  # base64 of the 36-byte Mail


class TradePreparationError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise TradePreparationError(message)


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value and UUID(value).int != 0
    except (ValueError, TypeError, AttributeError):
        return False


def _hash(value):
    return (type(value) is str and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _id(value):
    common = {k: v for k, v in value.items()
              if k not in {"preparation_id", "recipient_id", "incoming_record", "incoming_mail"}}
    return _sha(b"EM-TRADE-RECIPIENT-PREPARATION-1\0" + json.dumps(
        common, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii"))


def _mail_text(mail):
    return None if mail is None else base64.b64encode(mail).decode("ascii")


def incoming_mail(description):
    """The whole Mail the incoming Pokemon carries (36 bytes), or None; from a validated description."""
    text = description.get("incoming_mail")
    return None if text is None else base64.b64decode(text, validate=True)


def validate_preparation(value):
    """Validate a bounded descriptor, including the exact shared pair digest."""
    if type(value) is dict and value.get("format") == "emerald-trade-recipient-effects-v2":
        from .trade_effect_preparation import validate_effect_preparation
        return validate_effect_preparation(value)
    mail = type(value) is dict and value.get("capability") == EGGS_MAIL_CAPABILITY
    _require(type(value) is dict and set(value) == (_MAIL_FIELDS if mail else _FIELDS), "invalid preparation fields")
    _require(value["format"] == PREPARATION_FORMAT and value["capability"] in (TRADE_CAPABILITY, EGGS_MAIL_CAPABILITY)
             and value["save_profile"] == OWNERSHIP_PROFILE, "unqualified trade effect capability")
    for key in ("world_id", "transaction_id", "generation", "recipient_id"):
        _require(_uuid(value[key]), "invalid preparation identity")
    for key in ("build_id", "ruleset_id"):
        _require(type(value[key]) is str and 1 <= len(value[key]) <= 128
                 and value[key].isprintable(), "invalid preparation build binding")
    _require(_hash(value["fingerprint"]) and _hash(value["preparation_id"]),
             "invalid preparation digest")
    players = value["players"]
    _require(type(players) is list and len(players) == 2, "preparation needs both recipients")
    for player in players:
        _require(type(player) is dict and set(player) == (_MAIL_PLAYER_FIELDS if mail else _PLAYER_FIELDS),
                 "invalid recipient fields")
        if mail:
            _require(player["mail_sha256"] is None or _hash(player["mail_sha256"]), "invalid offered Mail digest")
        _require(_uuid(player["player_id"]) and _uuid(player["request_id"]), "invalid recipient identity")
        for key in ("lease_epoch", "revision"):
            _require(type(player[key]) is int and 1 <= player[key] <= MAX_COUNTER,
                     "invalid recipient counter")
        _require(type(player["serial"]) is int and 1 <= player["serial"] <= 0xFFFFF,
                 "invalid offered identity")
        for key in ("sha256", "record_sha256", "candidate_sha256"):
            _require(_hash(player[key]), "invalid recipient digest")
        _require(type(player["candidate_size"]) is int and player["candidate_size"] in (131072, 131088),
                 "invalid recipient container size")
    ids = [p["player_id"] for p in players]
    _require(ids == sorted(set(ids)) and value["recipient_id"] in ids
             and players[0]["serial"] != players[1]["serial"], "invalid paired recipients")
    _require(type(value["incoming_record"]) is str and len(value["incoming_record"]) == 136,
             "incoming record exceeds its exact party bound")
    try:
        incoming = base64.b64decode(value["incoming_record"], validate=True)
    except (ValueError, TypeError) as error:
        raise TradePreparationError("invalid incoming party record") from error
    _require(len(incoming) == POKEMON_SIZE and type(value["incoming_record"]) is str
             and base64.b64encode(incoming).decode("ascii") == value["incoming_record"],
             "incoming record is not a canonical bounded party record")
    peer = next(p for p in players if p["player_id"] != value["recipient_id"])
    _require(_sha(incoming) == peer["record_sha256"] and _id(value) == value["preparation_id"],
             "preparation does not bind the exact offered pair")
    if mail:
        text = value["incoming_mail"]
        if text is None:
            _require(peer["mail_sha256"] is None, "the incoming Mail is missing")
        else:
            _require(type(text) is str and len(text) == _MAIL_TEXT, "incoming Mail exceeds its exact bound")
            try:
                raw = base64.b64decode(text, validate=True)
            except (ValueError, TypeError) as error:
                raise TradePreparationError("invalid incoming Mail") from error
            _require(len(raw) == MAIL_SIZE and base64.b64encode(raw).decode("ascii") == text
                     and _sha(raw) == peer["mail_sha256"], "preparation does not bind the exact incoming Mail")
    return value


def prepare_pair(world_id, transaction_id, generation, fingerprint, checkpoints, leases, serials, *,
                 eggs=False, mail=False):
    """Derive both descriptions and complete candidates from canonical heads.

    ``eggs`` and ``mail`` (the host desk's allowances; the store passes both for a retained Egg-and-Mail description)
    admit Eggs and Pokemon holding Mail; a pair with any of them gets the Egg-and-Mail capability, every other pair the
    plain one with exactly the fields, digests and candidates of before."""
    _require(type(checkpoints) is tuple and len(checkpoints) == 2
             and all(type(cp) is Checkpoint for cp in checkpoints), "canonical checkpoint pair required")
    _require(type(leases) is tuple and type(serials) is tuple and len(leases) == len(serials) == 2,
             "exact lease and offer pairs required")
    _require(type(eggs) is bool and type(mail) is bool, "explicit Egg and Mail allowances are required")
    first, second = checkpoints
    _require(first.player_id < second.player_id and all(
        (cp.build_id, cp.ruleset_id, cp.save_profile) == (first.build_id, first.ruleset_id, OWNERSHIP_PROFILE)
        and _sha(cp.payload) == cp.sha256 for cp in checkpoints), "canonical preparation bindings differ")
    offers = validate_trade_pair(first.payload, serials[0], second.payload, serials[1], eggs=eggs, mail=mail)
    mail = any(offer.needs_eggs_and_mail for offer in offers)
    candidates = build_party_swap(first.payload, serials[0], second.payload, serials[1])
    records, players = [], []
    for cp, lease, serial, candidate, offer in zip(checkpoints, leases, serials, candidates, offers):
        snapshot = inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)
        owned = inspect_ownership(snapshot)
        _require((owned.world_id, owned.player_id) == (world_id, cp.player_id),
                 "canonical preparation belongs to another world or recipient")
        _, record = _party_record(snapshot, owned, serial)
        records.append(record)
        players.append(dict(player_id=cp.player_id, lease_epoch=lease, revision=cp.revision,
            request_id=cp.request_id, sha256=cp.sha256, serial=serial, record_sha256=_sha(record),
            candidate_sha256=_sha(candidate), candidate_size=len(candidate)))
        if mail:
            players[-1]["mail_sha256"] = None if offer.mail is None else _sha(offer.mail)
    common = dict(format=PREPARATION_FORMAT, capability=EGGS_MAIL_CAPABILITY if mail else TRADE_CAPABILITY,
        world_id=world_id, build_id=first.build_id, ruleset_id=first.ruleset_id, save_profile=first.save_profile,
        transaction_id=transaction_id, generation=generation, fingerprint=fingerprint, players=players)
    common["preparation_id"] = _id(common)
    descriptions = tuple(dict(common, recipient_id=cp.player_id,
        incoming_record=base64.b64encode(records[1-i]).decode("ascii"),
        **({"incoming_mail": _mail_text(offers[1-i].mail)} if mail else {})) for i, cp in enumerate(checkpoints))
    for description in descriptions:
        validate_preparation(description)
    return descriptions, candidates


def prepare_recipient(payload, description):
    """Independently reconstruct only this recipient's immutable post-image.

    An Egg-and-Mail description is rebuilt as the host built it: the recipient's own offered Mail must be the one the
    pair names, the incoming Mail the one its peer offered; its own slot is cleared and the incoming Mail takes the first
    free party slot (trade_flash.recipient_post_image). A retained description is rebuilt the same way in recovery."""
    validate_preparation(description)
    if description["format"] != PREPARATION_FORMAT:
        raise TradePreparationError("native effects require the retained native candidate and explicit move decisions")
    mail = description["capability"] == EGGS_MAIL_CAPABILITY
    actor = next(p for p in description["players"] if p["player_id"] == description["recipient_id"])
    peer = next(p for p in description["players"] if p["player_id"] != description["recipient_id"])
    _require(type(payload) is bytes and _sha(payload) == actor["sha256"]
             and len(payload) == actor["candidate_size"], "recipient's frozen source changed")
    snapshot = inspect_flash(payload, save_profile=OWNERSHIP_PROFILE)
    owned = inspect_ownership(snapshot)
    _require((owned.world_id, owned.player_id) == (description["world_id"], description["recipient_id"]),
             "frozen source belongs to another recipient")
    offset, outgoing = _party_record(snapshot, owned, actor["serial"])
    _require(_sha(outgoing) == actor["record_sha256"], "recipient's offered record changed")
    own = validate_party_offer(payload, actor["serial"], eggs=mail, mail=mail)
    if mail:
        _require(actor["mail_sha256"] == (None if own.mail is None else _sha(own.mail)),
                 "recipient's offered Mail changed")
    incoming = base64.b64decode(description["incoming_record"], validate=True)
    candidate = recipient_post_image(snapshot, offset, incoming, incoming_mail(description) if mail else None)
    parsed = inspect_ownership(inspect_flash(candidate, save_profile=OWNERSHIP_PROFILE))
    expected = {r.serial for r in owned.records} - {actor["serial"]} | {peer["serial"]}
    _require({r.serial for r in parsed.records} == expected
             and actor["serial"] not in expected, "recipient candidate changed unrelated ownership")
    validate_party_offer(candidate, peer["serial"], eggs=mail, mail=mail)
    _require(_sha(candidate) == actor["candidate_sha256"], "recipient candidate differs from the paired plan")
    return candidate
