"""Bounded original peer metadata for private recipient save preparation."""
import base64
import hashlib
import json

from .flash import inspect_flash
from .ownership import OWNERSHIP_PROFILE
from .trade_preparation import validate_preparation, _uuid, _hash

FORMAT = "emerald-trade-effect-source-v1"
FIELDS = {"format", "world_id", "transaction_id", "generation", "recipient_id", "preparation_id",
          "peer_id", "peer_revision", "peer_request_id", "peer_sha256", "gift_ribbons", "sha256"}


def _digest(value):
    fields = {k: v for k, v in value.items() if k != "sha256"}
    return hashlib.sha256(b"EM-TRADE-EFFECT-SOURCE-1\0" + json.dumps(
        fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def validate_effect_source(value, actor, preparation=None):
    if type(value) is not dict or set(value) != FIELDS or value["format"] != FORMAT:
        raise ValueError("invalid recipient effect source fields")
    for key in ("world_id", "transaction_id", "generation", "recipient_id", "peer_id", "peer_request_id"):
        if not _uuid(value[key]):
            raise ValueError("invalid recipient effect source identity")
    if value["recipient_id"] != actor or value["peer_id"] == actor:
        raise ValueError("effect source belongs to another recipient")
    for key in ("preparation_id", "peer_sha256", "sha256"):
        if not _hash(value[key]):
            raise ValueError("invalid recipient effect source digest")
    if type(value["peer_revision"]) is not int or not 1 <= value["peer_revision"] <= 0x7FFFFFFF:
        raise ValueError("invalid effect source revision")
    if type(value["gift_ribbons"]) is not str or len(value["gift_ribbons"]) != 12:
        raise ValueError("effect source exceeds its seven-byte peer metadata bound")
    gifts = base64.b64decode(value["gift_ribbons"], validate=True)
    if len(gifts) != 7 or base64.b64encode(gifts).decode("ascii") != value["gift_ribbons"] or _digest(value) != value["sha256"]:
        raise ValueError("effect source encoding or context changed")
    if preparation is not None:
        validate_preparation(preparation)
        peer = next(p for p in preparation["players"] if p["player_id"] != actor)
        if (any(value[k] != preparation[k] for k in
                ("world_id", "transaction_id", "generation", "recipient_id", "preparation_id"))
                or (value["peer_id"], value["peer_revision"], value["peer_request_id"], value["peer_sha256"]) !=
                   (peer["player_id"], peer["revision"], peer["request_id"], peer["sha256"])):
            raise ValueError("effect source differs from original confirmed peer checkpoint")
        if "effects" in preparation:
            plan = next(p for p in preparation["effects"]["offers"] if p["player_id"] == peer["player_id"])
            if value["gift_ribbons"] != plan["gift_ribbons"]:
                raise ValueError("effect source changed the confirmed original peer ribbons")
    return gifts


def effect_source_from_plan(preparation):
    """The v2 authenticated plan already contains the exact bounded peer bytes."""
    validate_preparation(preparation)
    if "effects" not in preparation:
        raise ValueError("original effect metadata requires the v2 plan")
    actor = preparation["recipient_id"]
    peer = next(p for p in preparation["players"] if p["player_id"] != actor)
    plan = next(p for p in preparation["effects"]["offers"] if p["player_id"] == peer["player_id"])
    value = dict(format=FORMAT, **{key: preparation[key] for key in
        ("world_id", "transaction_id", "generation", "recipient_id", "preparation_id")},
        peer_id=peer["player_id"], peer_revision=peer["revision"], peer_request_id=peer["request_id"],
        peer_sha256=peer["sha256"], gift_ribbons=plan["gift_ribbons"])
    value["sha256"] = _digest(value)
    validate_effect_source(value, actor, preparation)
    return value


def describe_effect_source(preparation, peer_checkpoint):
    """Trusted host-only construction from the original immutable checkpoint."""
    validate_preparation(preparation)
    actor = preparation["recipient_id"]
    peer = next(p for p in preparation["players"] if p["player_id"] != actor)
    if ((peer_checkpoint.player_id, peer_checkpoint.revision, peer_checkpoint.request_id, peer_checkpoint.sha256) !=
            (peer["player_id"], peer["revision"], peer["request_id"], peer["sha256"])
            or hashlib.sha256(peer_checkpoint.payload).hexdigest() != peer["sha256"]):
        raise ValueError("effect source checkpoint does not match the retained offer")
    snapshot = inspect_flash(peer_checkpoint.payload, save_profile=OWNERSHIP_PROFILE)
    value = dict(format=FORMAT, **{key: preparation[key] for key in
        ("world_id", "transaction_id", "generation", "recipient_id", "preparation_id")},
        peer_id=peer["player_id"], peer_revision=peer["revision"], peer_request_id=peer["request_id"],
        peer_sha256=peer["sha256"], gift_ribbons=base64.b64encode(snapshot.save_block1[0x31A8:0x31AF]).decode("ascii"))
    value["sha256"] = _digest(value)
    validate_effect_source(value, actor, preparation)
    return value
