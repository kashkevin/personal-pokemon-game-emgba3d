"""Offline verification of this recipient's durable native effect preparation."""
import base64
import hashlib
import json
import zlib

from .live_checkpoint import _json_bytes
from .trade_effect_session import _bytes
from .trade_effect_preparation import decode_effect_plan, validate_effect_receipt
from .trade_effect_source import effect_source_from_plan
from .trade_effect_candidate import validate_streamed_candidate
from .trade_effect_choice import NativeChoiceView


def client_for_plan(coordinator, description):
    from .trade_effect_preparation import validate_effect_preparation
    validate_effect_preparation(description)
    effects = description["effects"]
    peer = next(p for p in effects["offers"] if p["player_id"] != description["recipient_id"])
    plan = decode_effect_plan(peer)
    return coordinator.native_effect_preparation(plan.history, refresh_handler=plan.refresh_handler,
        profile_game_version=effects["profile_game_version"], engine_source_sha256=effects["engine_source_sha256"])


def _read_json(path):
    from .live_trade import _unique
    with path.open("rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("retained native evidence exceeds its bound")
    value = json.loads(raw, object_pairs_hook=_unique)
    if raw != _json_bytes(value):
        raise ValueError("retained native evidence changed its canonical encoding")
    return value


def retained_effect_candidate(co, intent, session, description):
    """No network/native dispatch; old committed recovery needs this exact proof."""
    source = co._bytes(intent["prepare_id"] + ".flash", intent["frozen_sha256"], 131072)
    client = client_for_plan(co, description)
    client.bind_description(intent, session, description, zlib.crc32(source))
    record = client._load()
    if record["phase"] != "active" or record["command"] is not None or record["response"] is None:
        raise ValueError("native effect preparation is incomplete or uncertain")
    ready_bytes = _bytes(record["response"], 192)
    ready = client._result(ready_bytes)
    if ready.state != 2 or list(map(list, ready.choices)) != record["choices"]:
        raise ValueError("native effect transcript is not the exact final READY record")
    # Public effect choices require their genuine, durable native screen events.
    if any(value is None for value in record["presentations"]):
        raise ValueError("public effects lack explicit native move decision evidence")
    peer_source = effect_source_from_plan(description)
    expected_context = dict(format="emerald-held-trade-save-context-v1", record_binding=client.binding,
        ready_record=record["response"], peer_source=peer_source,
        begin=base64.b64encode(_bytes(client.binding["begin"], 192)[:48]
            + bytes.fromhex(peer_source["sha256"]) + _bytes(peer_source["gift_ribbons"], 7) + b"\0").decode("ascii"))
    if _read_json(client.path.with_suffix(".save-context.json")) != expected_context:
        raise ValueError("native save preparation changed its original context")
    completion = _read_json(client.path.with_suffix(".candidate.json"))
    candidate = co._bytes(client.path.with_suffix(".candidate.flash").name,
                          completion["candidate_sha256"], 131072)
    verified = validate_streamed_candidate(source, description, peer_source, ready_bytes, candidate)
    expected_completion = dict(format="emerald-held-trade-save-candidate-v1", preparation_id=verified.preparation_id,
        effect_source_sha256=verified.effect_source_sha256, record_sha256=verified.record_sha256,
        context_sha256=hashlib.sha256(_json_bytes(expected_context)).hexdigest(),
        candidate_sha256=verified.sha256, size=len(candidate))
    if completion != expected_completion:
        raise ValueError("native candidate completion differs from its complete retained bytes")
    prefix = intent["transaction_id"] + "." + intent["generation"]
    publication = _read_json(co.directory / (prefix + ".effect-receipt.json"))
    if type(publication) is not dict or set(publication) != {"format", "preparation_id", "receipt", "review"}:
        raise ValueError("invalid retained public effect receipt")
    if publication["format"] != "emerald-public-effect-receipt-v1" or publication["preparation_id"] != description["preparation_id"]:
        raise ValueError("effect publication receipt names another preparation")
    receipt = publication["receipt"]
    validate_effect_receipt(receipt)
    expected_receipt = dict(choices=record["choices"], candidate_sha256=verified.sha256,
        candidate_size=len(candidate), record_sha256=hashlib.sha256(ready.candidate).hexdigest())
    if receipt != expected_receipt:
        raise ValueError("effect publication receipt differs from the final native record")
    review = publication["review"]
    if (type(review) is not dict or set(review) != {"format", "binding", "record", "view", "screen", "request_sequence", "session_epoch"}
            or review["format"] != "emerald-held-trade-candidate-review-v1" or review["binding"] != client.binding
            or review["record"] != record["response"]
            or any(type(review[key]) is not int or not 1 <= review[key] <= maximum for key, maximum in
                (("screen", 0xFFFFFFFF), ("request_sequence", 0xFFFFFFFF), ("session_epoch", session[1])))):
        raise ValueError("effect candidate lacks its exact native READY review")
    NativeChoiceView.parse(_bytes(review["view"], 84)).match(ready_bytes)
    review_path = client.path.with_suffix(f".review.{review['session_epoch']}.{review['screen']}.{review['request_sequence']}.json")
    if _read_json(review_path) != review:
        raise ValueError("retained native READY review changed")
    return candidate, receipt


def completed_effect_summary(co, intent, session, *, canonical_checkpoint=None):
    """Describe the exact retained candidate; caller proves live or cold apply."""
    prefix = intent["transaction_id"] + "." + intent["generation"]
    description = _read_json(co.directory / (prefix + ".recipient-preparation.json"))["preparation"]
    candidate = co._prepared_candidate(intent, session)
    checkpoint = intent["canonical"] if canonical_checkpoint is None else canonical_checkpoint
    from .checkpoint_client import validate_metadata
    checkpoint = validate_metadata(checkpoint, co.companion.config, intent["save_profile"])
    if (candidate is None or checkpoint is None or hashlib.sha256(candidate).hexdigest() != checkpoint["sha256"]
            or (checkpoint["request_id"], checkpoint["revision"]) !=
               (intent["transaction_id"], intent["expected_revision"] + 2)):
        raise ValueError("received result is not the applied canonical candidate")
    client = client_for_plan(co, description)
    source = co._bytes(intent["prepare_id"] + ".flash", intent["frozen_sha256"], 131072)
    client.bind_description(intent, session, description, zlib.crc32(source))
    ready = client._result(_bytes(client._load()["response"], 192))
    return dict(format="emerald-completed-trade-received-v1", transaction_id=intent["transaction_id"],
        generation=intent["generation"], serial=ready.received_serial,
        received_species=ready.received_species, species=ready.evolved_species or ready.received_species,
        evolved=bool(ready.evolved_species), level=ready.candidate[84],
        candidate_sha256=hashlib.sha256(candidate).hexdigest(), revision=checkpoint["revision"])
