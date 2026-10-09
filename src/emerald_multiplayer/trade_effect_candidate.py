"""Complete native-window candidate equality; no canonical publication authority."""
from dataclasses import dataclass, field
import base64
import hashlib

from .flash import FLASH_SIZE, inspect_flash
from .ownership import OWNERSHIP_PROFILE, inspect_ownership
from .trade_effect_flash import _private_blocks_with_gifts, _write_blocks
from .trade_effect_mailbox import PreparedRecord
from .trade_effect_source import validate_effect_source
from .trade_effect_witness import _record, _protected, lucky_conversion_ok
from .trade_flash import _party_record
from .trade_preparation import validate_preparation


@dataclass(frozen=True)
class HeldSaveCandidate:
    preparation_id: str
    effect_source_sha256: str
    record_sha256: str
    sha256: str
    payload: bytes = field(repr=False)


def validate_streamed_candidate(source, description, effect_source, record_bytes, candidate):
    """Require entire native Flash to equal exact independently applied effects.

    Native record readiness supplies computed evolution/explicit choices; the
    held client separately binds its authenticated native response and durable
    history/decision transcript. This function alone never authenticates a
    peer-supplied candidate or grants a prepared receipt to the trade store.
    """
    validate_preparation(description)
    gifts = validate_effect_source(effect_source, description["recipient_id"], description)
    own = next(p for p in description["players"] if p["player_id"] == description["recipient_id"])
    peer = next(p for p in description["players"] if p["player_id"] != description["recipient_id"])
    if (type(source) is not bytes or len(source) != FLASH_SIZE
            or hashlib.sha256(source).hexdigest() != own["sha256"]
            or type(candidate) is not bytes or len(candidate) != FLASH_SIZE):
        raise ValueError("full candidate lacks the exact original canonical Flash")
    snapshot = inspect_flash(source, save_profile=OWNERSHIP_PROFILE)
    owner = inspect_ownership(snapshot)
    if (owner.world_id, owner.player_id) != (description["world_id"], description["recipient_id"]):
        raise ValueError("full candidate source ownership differs")
    offset, sent = _party_record(snapshot, owner, own["serial"])
    incoming = base64.b64decode(description["incoming_record"], validate=True)
    prepared = PreparedRecord.parse(record_bytes)
    received, before, held = _record(incoming)
    result, after, item = _record(prepared.candidate)
    evolved = received[3] != result[3]
    lucky = False
    if "effects" in description:
        from .trade_effect_preparation import decode_effect_plan
        lucky = decode_effect_plan(next(p for p in description["effects"]["offers"]
                                        if p["player_id"] == peer["player_id"])).lucky
    if (prepared.state != 2 or prepared.pending_move
            or (prepared.received_serial, prepared.sent_serial) != (peer["serial"], own["serial"])
            or prepared.received_species != received[3] or result[:3] != received[:3]
            or result[3] != (prepared.evolved_species or received[3])
            or prepared.item_before != held or prepared.item_after != item or item not in {held, 0}
            or prepared.friendship != after[9] or not evolved and prepared.choices
            or prepared.lucky != lucky or (lucky and not lucky_conversion_ok(before, after))
            or _protected(incoming, before, evolved, lucky) != _protected(prepared.candidate, after, evolved, lucky)
            or hashlib.sha256(sent).hexdigest() != own["record_sha256"]):
        raise ValueError("full candidate is not bound to the READY offered record")
    expected = _write_blocks(snapshot, *_private_blocks_with_gifts(snapshot, gifts, offset, incoming, prepared.candidate))
    if candidate != expected:
        raise ValueError("native full candidate changed bytes outside exact record/Dex/stat/ribbon effects")
    parsed = inspect_flash(candidate, expected_trainer_id=snapshot.metadata.trainer_id, save_profile=OWNERSHIP_PROFILE)
    after_owner = inspect_ownership(parsed)
    if ((after_owner.world_id, after_owner.player_id) != (owner.world_id, owner.player_id)
            or {p.serial for p in after_owner.records} != {p.serial for p in owner.records} - {own["serial"]} | {peer["serial"]}):
        raise ValueError("native full candidate changed unrelated owned instances")
    return HeldSaveCandidate(description["preparation_id"], effect_source["sha256"],
        hashlib.sha256(record_bytes).hexdigest(), hashlib.sha256(candidate).hexdigest(), candidate)
