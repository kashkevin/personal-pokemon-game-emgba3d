"""Exact save-wide recipient trade effects, outside public commit capability.

Native record and saved-block replay callbacks must be trusted adapters pinned
by the authenticated engine digest, never a network-supplied callable/result.
This module reconstructs both complete Flash containers and compares the native
bookkeeping to an independent exact implementation. It never writes storage,
chooses unknown handler policy, or changes the ordinary exact-swap validator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
import struct

from .flash import (
    POKEMON_SIZE, SAVED_PARTY_OFFSET, SAVE_BLOCK_1_SIZE, SAVE_BLOCK_2_SIZE,
    SECTION_LENGTHS, SECTOR_SIZE, SECTIONS_PER_BANK, _checksum, inspect_flash,
)
from .gen6_friendship import TABLE_ID, VALUES_SHA256
from .ownership import OWNERSHIP_PROFILE, inspect_ownership
from .trade_effect_witness import (
    EffectContext, RecordEffectWitness, _history, _record, prepare_record_effect,
)
from .trade_flash import TradeFlashError, _party_record
from .trade_friendship import FriendshipHistory, TrainerIdentity
from .trade_friendship_flash import _source

PLAN_ID = "native-recipient-save-effects-v1"
# Pinned native global.h layout; matching native STATIC_ASSERTs refuse drift.
DEX_SEEN = 0x3598
DEX_CAUGHT = 0x3619
DEX_BYTES = 129
GAME_STATS = 0x159C
ENCRYPTION_KEY = 0xAC
UNOWN_PERSONALITY = 0x1C
SPINDA_PERSONALITY = 0x20
GIFT_RIBBONS = 0x31A8
GIFT_RIBBON_COUNT = 7
GIFT_RIBBON_MAX = 64
FLAGS = 0x1270
RIBBON_GET_FLAG = 0x89B
TRADE_STAT = 21
EVOLUTION_STAT = 14
STAT_MAX = 0xFFFFFF


@dataclass(frozen=True)
class EffectOfferPlan:
    """History/explicit handler decision follows the offered owned instance."""
    history: FriendshipHistory
    refresh_handler: bool


@dataclass(frozen=True)
class SaveEffectPair:
    """Recipient order is canonical player order; histories live in witnesses."""
    preparation_sha256: str
    outcome_sha256: str
    recipient_a: RecordEffectWitness
    recipient_b: RecordEffectWitness
    after_a: bytes = field(repr=False)
    after_b: bytes = field(repr=False)


def _require(condition, message):
    if not condition:
        raise TradeFlashError(message)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _digest(value):
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True).encode("ascii"))


def _increment(block1, key, stat):
    offset = GAME_STATS + stat * 4
    value = struct.unpack_from("<I", block1, offset)[0] ^ key
    struct.pack_into("<I", block1, offset, min(value + 1, STAT_MAX) ^ key)


def _private_blocks(snapshot, partner, outgoing_offset, incoming, candidate):
    """Reproduce only the audited native field operations on private copies."""
    _require(len(partner.save_block1) == SAVE_BLOCK_1_SIZE, "partner save-effect layout changed")
    gifts = partner.save_block1[GIFT_RIBBONS:GIFT_RIBBONS + GIFT_RIBBON_COUNT]
    return _private_blocks_with_gifts(snapshot, gifts, outgoing_offset, incoming, candidate)


def _private_blocks_with_gifts(snapshot, gifts, outgoing_offset, incoming, candidate):
    """Equivalent bookkeeping using only the seven authenticated peer bytes."""
    received, secure, _ = _record(incoming)
    result, _, _ = _record(candidate)
    _require(received[:3] == result[:3], "effects changed incoming instance identity")
    block1, block2 = bytearray(snapshot.save_block1), bytearray(snapshot.save_block2)
    _require(len(block1) == SAVE_BLOCK_1_SIZE and len(block2) == SAVE_BLOCK_2_SIZE
             and type(gifts) is bytes and len(gifts) == GIFT_RIBBON_COUNT, "save-effect layout changed")
    block1[outgoing_offset:outgoing_offset + POKEMON_SIZE] = candidate

    # UpdatePokedexForReceivedMon first sets seen, then HandleSetPokedexFlag
    # stores Unown/Spinda PID only for the first caught flag, not first seen.
    dex = received[3] - 1  # standard native species IDs == National Dex 1..721
    index, bit = dex // 8, 1 << (dex % 8)
    block1[DEX_SEEN + index] |= bit
    if not block1[DEX_CAUGHT + index] & bit:
        block1[DEX_CAUGHT + index] |= bit
        if received[3] in (201, 327):
            offset = UNOWN_PERSONALITY if received[3] == 201 else SPINDA_PERSONALITY
            struct.pack_into("<I", block2, offset, received[1])
    key = struct.unpack_from("<I", block2, ENCRYPTION_KEY)[0]
    if received[3] != result[3]:
        dex = result[3] - 1
        index, bit = dex // 8, 1 << (dex % 8)
        block1[DEX_SEEN + index] |= bit
        block1[DEX_CAUGHT + index] |= bit
        _increment(block1, key, EVOLUTION_STAT)
    _increment(block1, key, TRADE_STAT)

    # Native CheckPartnersMonForRibbons tests champion through world, not the
    # five contest-rank fields at lower bits. Never manufacture a Pokémon ribbon.
    if struct.unpack_from("<I", secure, 44)[0] & 0x07FF8000:
        block1[FLAGS + RIBBON_GET_FLAG // 8] |= 1 << (RIBBON_GET_FLAG % 8)
    # Native SaveTradeGiftRibbons fills missing descriptions from the partner's
    # original save. Both recipients use originals, never the other's candidate.
    for index in range(GIFT_RIBBON_COUNT):
        offset = GIFT_RIBBONS + index
        value = gifts[index]
        if block1[offset] == 0 and 0 < value < GIFT_RIBBON_MAX:
            block1[offset] = value
    return bytes(block1), bytes(block2)


def _write_blocks(snapshot, block1, block2):
    """Replace logical blocks in the validated active bank, preserving all else."""
    _require(type(block1) is bytes and len(block1) == SAVE_BLOCK_1_SIZE
             and type(block2) is bytes and len(block2) == SAVE_BLOCK_2_SIZE,
             "native save preparation returned incomplete immutable blocks")
    logical = {0: block2}
    offset = 0
    for section in range(1, 5):
        length = SECTION_LENGTHS[section]
        logical[section] = block1[offset:offset + length]
        offset += length
    _require(offset == len(block1), "save-block sections do not cover the pinned layout")
    first = snapshot.metadata.bank * SECTIONS_PER_BANK
    result = bytearray(snapshot.container)
    found = set()
    for sector in range(first, first + SECTIONS_PER_BANK):
        start = sector * SECTOR_SIZE
        section = struct.unpack_from("<H", snapshot.flash, start + 4084)[0]
        if section in logical:
            _require(section not in found, "duplicate recipient save section")
            data = logical[section]
            result[start:start + len(data)] = data
            struct.pack_into("<H", result, start + 4086, _checksum(data))
            found.add(section)
    _require(found == set(logical), "recipient save blocks are incomplete")
    return bytes(result)


def _recipient(snapshot, owner, partner, incoming_owner, outgoing_serial,
               incoming_serial, witness, *, replay_save_native):
    offset, outgoing = _party_record(snapshot, owner, outgoing_serial)
    peer_offset, incoming = _party_record(partner, incoming_owner, incoming_serial)
    _require(witness.sent_sha256 == _sha(outgoing)
             and witness.received_sha256 == _sha(incoming), "record witness does not match these saved offers")
    expected = _private_blocks(snapshot, partner, offset, incoming, witness.candidate)
    _, secure, _ = _record(witness.candidate)
    decisions = tuple((choice.move, choice.slot) for choice in witness.choices)
    # Independent native full-block replay is mandatory, not a hash assertion.
    native = replay_save_native(snapshot.save_block1, snapshot.save_block2,
        partner.save_block1, (offset - SAVED_PARTY_OFFSET) // POKEMON_SIZE,
        (peer_offset - SAVED_PARTY_OFFSET) // POKEMON_SIZE, secure[9], decisions)
    _require(type(native) is tuple and len(native) == 2
             and all(type(block) is bytes for block in native)
             and native == expected, "native save effects differ from exact authorized bookkeeping")
    payload = _write_blocks(snapshot, *expected)
    parsed = inspect_flash(payload, expected_trainer_id=snapshot.metadata.trainer_id,
                           save_profile=OWNERSHIP_PROFILE)
    after = inspect_ownership(parsed)
    expected_serials = {record.serial for record in owner.records} - {outgoing_serial} | {incoming_serial}
    _require(after.world_id == owner.world_id and after.player_id == owner.player_id
             and {record.serial for record in after.records} == expected_serials,
             "save effects changed unrelated ownership")
    return payload


def prepare_effect_pair(a, plan_a, b, plan_b, *, transaction_id, generation,
                        fingerprint, leases, engine_source_sha256, profile_game_version,
                        choices_a, choices_b, replay_native, replay_save_native):
    """Derive two entire recipient candidates from canonical immutable sources.

Choices are recipient ordered; plans are offered-instance ordered. Transaction,
consent fingerprint, leases, retained complete histories and engine/game-profile
identity must come from authenticated host state. Native callbacks must run the
bound engine on copies. This internal computation grants no consent or commit.
"""
    _require(callable(replay_native) and callable(replay_save_native),
             "trusted record and complete saved-block native replay are required")
    for plan in (plan_a, plan_b):
        _require(type(plan) is EffectOfferPlan and type(plan.history) is FriendshipHistory
                 and type(plan.refresh_handler) is bool, "both offers need typed complete handler policy")
        plan.history.validate()
    _require(type(leases) is tuple and len(leases) == 2, "exact authenticated lease pair required")
    _require(type(fingerprint) is str and re.fullmatch(r"[0-9a-f]{64}", fingerprint) is not None,
             "exact mutual-consent fingerprint required")
    sa, oa = _source(a)
    sb, ob = _source(b)
    _require(a.player_id < b.player_id and oa.world_id == ob.world_id
             and (a.build_id, a.ruleset_id, a.save_profile) == (b.build_id, b.ruleset_id, b.save_profile),
             "effects require canonical ordered recipients in one world/build/profile")
    _require(not ({record.serial for record in oa.records} & {record.serial for record in ob.records}),
             "original inventories share an owned instance")
    _, mon_a = _party_record(sa, oa, plan_a.history.serial)
    _, mon_b = _party_record(sb, ob, plan_b.history.serial)
    _record(mon_a)
    _record(mon_b)
    recipient_a = TrainerIdentity(sa.metadata.name, sa.metadata.gender, sa.metadata.trainer_id, profile_game_version)
    recipient_b = TrainerIdentity(sb.metadata.name, sb.metadata.gender, sb.metadata.trainer_id, profile_game_version)
    recipient_a.validate()
    recipient_b.validate()
    sources = [[cp.player_id, lease, cp.revision, cp.request_id, cp.sha256,
                _history(plan.history), plan.refresh_handler]
               for cp, lease, plan in ((a, leases[0], plan_a), (b, leases[1], plan_b))]
    preparation = _digest([PLAN_ID, TABLE_ID, VALUES_SHA256, oa.world_id, a.build_id, a.ruleset_id,
        OWNERSHIP_PROFILE, transaction_id, generation, fingerprint, engine_source_sha256,
        profile_game_version, sources])
    contexts = tuple(EffectContext(oa.world_id, transaction_id, generation, cp.player_id,
        cp.request_id, lease, cp.revision, cp.sha256, preparation, cp.build_id, cp.ruleset_id,
        engine_source_sha256) for cp, lease in ((a, leases[0]), (b, leases[1])))
    # Each context validates before any native work; a bad second lease/context
    # cannot cause only the first recipient to run an otherwise valid callback.
    for context in contexts:
        context.values()
    wa = prepare_record_effect(contexts[0], mon_b, mon_a, plan_b.history, recipient_a,
        refresh_handler=plan_b.refresh_handler, choices=choices_a, replay_native=replay_native)
    wb = prepare_record_effect(contexts[1], mon_a, mon_b, plan_a.history, recipient_b,
        refresh_handler=plan_a.refresh_handler, choices=choices_b, replay_native=replay_native)
    after_a = _recipient(sa, oa, sb, ob, plan_a.history.serial, plan_b.history.serial, wa,
                         replay_save_native=replay_save_native)
    after_b = _recipient(sb, ob, sa, oa, plan_b.history.serial, plan_a.history.serial, wb,
                         replay_save_native=replay_save_native)
    outcome = _digest([PLAN_ID, preparation, wa.sha256, wb.sha256, _sha(after_a), _sha(after_b)])
    return SaveEffectPair(preparation, outcome, wa, wb, after_a, after_b)


def validate_effect_pair(pair, a, plan_a, b, plan_b, *, transaction_id, generation,
                         fingerprint, leases, engine_source_sha256, profile_game_version,
                         choices_a, choices_b, replay_native, replay_save_native):
    """Reconstruct every output byte/history from separately authenticated inputs.

No field in the submitted pair supplies authority. Exact original inputs make
retries deterministic: a stored post-image must be reused, never incremented
again. Original-source binding is still the future transaction owner's duty.
"""
    _require(type(pair) is SaveEffectPair, "typed immutable save-effect pair required")
    rebuilt = prepare_effect_pair(a, plan_a, b, plan_b, transaction_id=transaction_id,
        generation=generation, fingerprint=fingerprint, leases=leases,
        engine_source_sha256=engine_source_sha256, profile_game_version=profile_game_version,
        choices_a=choices_a, choices_b=choices_b, replay_native=replay_native,
        replay_save_native=replay_save_native)
    _require(pair == rebuilt, "save-effect candidates, context, choices or histories changed")
    return rebuilt
