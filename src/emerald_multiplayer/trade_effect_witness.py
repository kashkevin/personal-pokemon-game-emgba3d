"""Bounded record-effect witness with mandatory trusted native recomputation.

This internal helper grants no mailbox, storage or trade eligibility capability.
The replay callback must be the pinned native adapter running on private copies,
never a function supplied over the network or a returned client candidate/hash.
Save-wide Dex/stat changes and durable atomic history remain separate work.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import struct
from uuid import UUID

from .flash import _inspect_party
from .gen6_friendship import TABLE_ID, VALUES_SHA256, base_friendship
from .ownership import _SUBSTRUCT_OFFSETS, _decode_box
from .protocol import MAX_COUNTER
from .trade_friendship import (
    FriendshipHistory, TrainerIdentity, transform_received_party_record,
)

WITNESS_FORMAT = "emerald-native-trade-record-witness-v1"
MAX_CHOICES = 16
DECLINE_MOVE = 4
MAX_GEN6_MOVE = 621
MAX_STORED_MOVE = 847  # pinned engine MOVES_COUNT - 1
# Lucky Trades (owner amendment): the resolved-friendship word passed to the
# native preparation carries the host's decision in bit 8. A Lucky received
# Pokemon has every IV raised to the floor (never lowered, max 31) and its
# permanent marker bit set (bit 31 of the IV word: the unused G-Max factor).
LUCKY_BIT = 0x100
LUCKY_IV_FLOOR = 12  # engine include/constants/multiplayer_balance.h MP_LUCKY_IV_FLOOR
_IV_WORD = 40        # logical offset of the IV/egg/G-Max word (misc substruct + 4)
_LUCKY_MARKER = 1 << 31
_EGG_BIT = 1 << 30


class TradeEffectWitnessError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise TradeEffectWitnessError(message)


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _identity(value):
    return [value.name.hex(), value.gender, value.trainer_id, value.version]


def _history(value):
    value.validate()
    from .trade_friendship_flash import _history as encode_history
    return encode_history(value)


@dataclass(frozen=True)
class EffectContext:
    """Trusted preparation binding; no field is inferred from the candidate."""
    world_id: str
    transaction_id: str
    generation: str
    recipient_id: str
    checkpoint_request_id: str
    lease_epoch: int
    checkpoint_revision: int
    checkpoint_sha256: str
    pair_preparation_sha256: str
    build_id: str
    ruleset_id: str
    engine_source_sha256: str

    def values(self):
        for value in (self.world_id, self.transaction_id, self.generation, self.recipient_id, self.checkpoint_request_id):
            try:
                valid = type(value) is str and str(UUID(value)) == value and UUID(value).int != 0
            except (ValueError, TypeError, AttributeError):
                valid = False
            _require(valid, "record effects require exact canonical preparation identities")
        for value in (self.lease_epoch, self.checkpoint_revision):
            _require(type(value) is int and 1 <= value <= MAX_COUNTER, "invalid preparation counter")
        for value in (self.checkpoint_sha256, self.pair_preparation_sha256, self.engine_source_sha256):
            _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
                     "record effects require exact source digests")
        for value in (self.build_id, self.ruleset_id):
            _require(type(value) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) is not None,
                     "invalid native build or rules binding")
        return [getattr(self, field) for field in self.__dataclass_fields__]


@dataclass(frozen=True)
class EvolutionMoveChoice:
    move: int
    slot: int

    def validate(self):
        _require(type(self.move) is int and 1 <= self.move <= MAX_GEN6_MOVE
                 and type(self.slot) is int and 0 <= self.slot <= DECLINE_MOVE,
                 "evolution choice must name one Gen6 move and replacement slot or decline")
        return self


@dataclass(frozen=True)
class RecordEffectWitness:
    context: EffectContext
    choices: tuple[EvolutionMoveChoice, ...]
    received_sha256: str
    sent_sha256: str
    friendship_input_sha256: str
    resulting_history: FriendshipHistory
    candidate: bytes
    sha256: str


def _record(mon):
    _require(type(mon) is bytes and len(mon) == 100 and _inspect_party(mon, "trade-effect"),
             "effects require a complete occupied immutable party record")
    serial, personality, ot, species, _ = _decode_box(mon[:80], "trade-effect")
    _require(serial != 0 and 1 <= species <= 721, "unassigned or uncatalogued effect record")
    physical = struct.pack("<12I", *(word ^ personality ^ ot for word in struct.unpack_from("<12I", mon, 32)))
    logical = b"".join(physical[row[personality % 24]*12:row[personality % 24]*12+12]
                       for row in _SUBSTRUCT_OFFSETS)
    _require(not mon[19] & 4 and not struct.unpack_from("<I", logical, 40)[0] & (1 << 30),
             "egg effects require a separate origin/hatch capability")
    held = struct.unpack_from("<H", logical, 2)[0] & 0x3FF
    _require(mon[85] == 0xFF and not 199 <= held <= 210, "mail needs recipient-local allocation")
    moves = tuple(word & 0x7FF for word in struct.unpack_from("<4H", logical, 12))
    # Existing later-generation moves are preserved unchanged (owner decision).
    _require(all(move <= MAX_STORED_MOVE for move in moves), "unknown stored move identifier")
    return (serial, personality, ot, species), logical, held


def lucky_ivs(word):
    """The IV word after a Lucky conversion: floors raised, marker set."""
    result = word & _EGG_BIT
    for stat in range(6):
        iv = (word >> (stat * 5)) & 31
        result |= max(iv, LUCKY_IV_FLOOR) << (stat * 5)
    return result | _LUCKY_MARKER


def lucky_conversion_ok(before_logical, after_logical):
    before = struct.unpack_from("<I", before_logical, _IV_WORD)[0]
    after = struct.unpack_from("<I", after_logical, _IV_WORD)[0]
    return after == lucky_ivs(before)


def _protected(mon, logical, evolved, lucky=False):
    """Independent exact mask of fields the pinned record adapter may change.

    Native replay still determines every allowed new value. Clearing a field
    here does not authorize arbitrary values or replace that replay.
    """
    header = bytearray(mon[:32])
    secure = bytearray(logical)
    party = bytearray(mon[80:])
    header[28:30] = b"\0\0"  # encrypted record checksum
    secure[9] = 0              # explicitly resolved friendship
    if lucky:
        # IVs and the marker follow lucky_ivs() exactly (checked separately);
        # the derived stats are recomputed natively from them.
        word = struct.unpack_from("<I", secure, _IV_WORD)[0]
        struct.pack_into("<I", secure, _IV_WORD, word & _EGG_BIT)
        party[6:20] = bytes(14)
    if evolved:
        header[8:18] = bytes(10)  # same-language unnicknamed evolution rename
        struct.pack_into("<H", header, 30, struct.unpack_from("<H", header, 30)[0] & 0xC000)
        for offset, mask in ((0, 0xF800), (2, 0xFC00), (10, 0xC03F)):
            struct.pack_into("<H", secure, offset, struct.unpack_from("<H", secure, offset)[0] & mask)
        struct.pack_into("<I", secure, 4, struct.unpack_from("<I", secure, 4)[0] & 0xE01FFFFF)
        secure[8] = 0  # only the replayed replaced slots may lose PP Ups
        for slot in range(4):
            offset = 12 + slot*2
            # First two upper five-bit fields are the reset evolution tracker;
            # other upper bits contain identity/hyper-training and must survive.
            mask = 0 if slot < 2 else 0xF800
            struct.pack_into("<H", secure, offset, struct.unpack_from("<H", secure, offset)[0] & mask)
            secure[20+slot] &= 0x80
        party[6:20] = bytes(14)  # derived HP and six stats, never status/level/mail
    return bytes(header + secure + party)


def prepare_record_effect(context, received, sent, history, recipient, *, refresh_handler,
                          choices, replay_native, lucky=False):
    """Compute a fully bound witness; unknown history remains an explicit refusal.

    The trusted native callback signature is (received100, sent100, friendship,
    ((move, slot), ...)) -> candidate100. It must reject missing/trailing/stale
    choices and use the exact engine source bound by context. No fallback to
    accepting caller-supplied output exists. This function never writes a save.
    """
    _require(type(context) is EffectContext, "typed native preparation context required")
    context_values = context.values()
    _require(type(history) is FriendshipHistory and type(recipient) is TrainerIdentity,
             "complete retained friendship and recipient identities required")
    _require(type(refresh_handler) is bool and callable(replay_native) and type(lucky) is bool,
             "explicit refresh policy, Lucky decision and trusted native replay required")
    _require(type(choices) is tuple and len(choices) <= MAX_CHOICES
             and all(type(choice) is EvolutionMoveChoice for choice in choices),
             "bounded typed native move transcript required")
    decisions = tuple((choice.validate().move, choice.slot) for choice in choices)
    original, before, held = _record(received)
    other, _, _ = _record(sent)
    _require(original[0] != other[0], "trade effects require two distinct owned instances")
    _, transition = transform_received_party_record(received, history, recipient,
        base_friendship=base_friendship(original[3]), refresh_handler=refresh_handler)
    candidate = replay_native(received, sent, transition.friendship | (LUCKY_BIT if lucky else 0), decisions)
    result, after, resulting_item = _record(candidate)
    _require(result[:3] == original[:3], "native preparation changed immutable instance identity")
    evolved = result[3] != original[3]
    _require(_protected(received, before, evolved, lucky) == _protected(candidate, after, evolved, lucky),
             "native preparation changed protected Pokémon data")
    _require(not lucky or lucky_conversion_ok(before, after),
             "native Lucky conversion differs from the exact IV floor and marker")
    _require(after[9] == transition.friendship and resulting_item in {held, 0},
             "native preparation changed resolved friendship or introduced an item")
    _require(evolved or not choices, "unevolved result cannot consume evolution decisions")
    policy = [TABLE_ID, VALUES_SHA256, _history(history), _identity(recipient), refresh_handler]
    policy_sha = _hash(_json(policy))
    receipt = [WITNESS_FORMAT, context_values, _hash(received), _hash(sent), policy_sha,
               decisions, _history(transition.history), _hash(candidate)]
    if lucky:
        receipt.append("lucky")  # absent for ordinary trades: earlier witnesses keep their digests
    return RecordEffectWitness(context, choices, _hash(received), _hash(sent), policy_sha,
                               transition.history, candidate, _hash(_json(receipt)))


def validate_record_effect(witness, received, sent, history, recipient, *, expected_context,
                           refresh_handler, replay_native, lucky=False):
    """Replay from authenticated sources, not from fields in a received result."""
    _require(type(witness) is RecordEffectWitness, "typed record-effect witness required")
    _require(type(expected_context) is EffectContext and witness.context == expected_context,
             "record-effect witness belongs to another authenticated preparation")
    rebuilt = prepare_record_effect(expected_context, received, sent, history, recipient,
        refresh_handler=refresh_handler, choices=witness.choices, replay_native=replay_native, lucky=lucky)
    _require(witness == rebuilt, "retained native candidate or witness changed")
    return rebuilt
