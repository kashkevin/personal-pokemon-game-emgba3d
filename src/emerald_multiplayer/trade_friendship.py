"""Gated Gen6 friendship calculation and exact pinned-record transformation.

This module grants no trade eligibility, store mutation or native authority.
The caller must supply complete retained handler history, a qualified Gen6
species-base value and a separately validated handler-refresh decision.
"""
from dataclasses import dataclass, replace
import struct

from .flash import _inspect_party
from .ownership import SERIAL_MAX, _SUBSTRUCT_OFFSETS, _decode_box

CAPABILITY_ID = "gen6-handler-friendship-plan-v1"
RETURN, FRUSTRATION = 216, 218
MAX_GEN6_MOVE = 621


class FriendshipPlanError(ValueError):
    pass


def _integer(value, maximum, label):
    if type(value) is not int or not 0 <= value <= maximum:
        raise FriendshipPlanError(f"{label} is outside its bounded representation")


@dataclass(frozen=True)
class TrainerIdentity:
    """Canonical native OT name (before EOS), gender, ID32 and origin game."""
    name: bytes
    gender: int
    trainer_id: int
    version: int

    def validate(self):
        if not isinstance(self.name, bytes) or not 1 <= len(self.name) <= 7 or b"\xff" in self.name:
            raise FriendshipPlanError("trainer name must be canonical pinned native bytes before EOS")
        _integer(self.gender, 1, "trainer gender")
        _integer(self.trainer_id, 0xFFFFFFFF, "trainer ID")
        _integer(self.version, 15, "native origin game")
        return self

    @property
    def handler_key(self):
        # Gen6 handling-name/gender comparison differs from full OT identity.
        return self.name, self.gender


@dataclass(frozen=True)
class FriendshipHistory:
    serial: int
    original: TrainerIdentity
    original_friendship: int | None
    handler: TrainerIdentity | None
    handling_friendship: int | None
    current_handler: int | None
    known: bool = True
    # Historical provenance: these slots initially lacked a retained value.
    # They are usable after the owner's explicit base-friendship migration,
    # but must never be presented as recovered original history.
    initialized_fields: tuple[str, ...] = ()
    handler_identity_unknown: bool = False

    def validate(self):
        if type(self.serial) is not int or not 1 <= self.serial <= SERIAL_MAX:
            raise FriendshipPlanError("friendship history lacks its immutable owned serial")
        if not isinstance(self.original, TrainerIdentity):
            raise FriendshipPlanError("friendship history lacks original trainer identity")
        self.original.validate()
        if self.known is not True:
            raise FriendshipPlanError("legacy opposite-handler history is unknown; explicit migration is required")
        _integer(self.original_friendship, 255, "original friendship")
        _integer(self.handling_friendship, 255, "handling friendship")
        _integer(self.current_handler, 1, "current handler")
        if (type(self.initialized_fields) is not tuple
                or any(type(value) is not str or value not in ("original_friendship", "handling_friendship")
                       for value in self.initialized_fields)
                or self.initialized_fields != tuple(sorted(set(self.initialized_fields)))):
            raise FriendshipPlanError("invalid initialized friendship provenance")
        if type(self.handler_identity_unknown) is not bool or (self.handler is not None and self.handler_identity_unknown):
            raise FriendshipPlanError("invalid missing-handler identity provenance")
        if self.handler is None:
            if self.current_handler != 0 or (self.handling_friendship != 0
                    and "handling_friendship" not in self.initialized_fields and not self.handler_identity_unknown):
                raise FriendshipPlanError("absent handling identity lacks an explicit initialization policy")
        elif not isinstance(self.handler, TrainerIdentity):
            raise FriendshipPlanError("handling trainer identity is invalid")
        else:
            self.handler.validate()
        return self


@dataclass(frozen=True)
class FriendshipTransition:
    history: FriendshipHistory
    friendship: int
    handler_changed: bool
    initialized_handler: bool


def plan_friendship(history: FriendshipHistory, recipient: TrainerIdentity, *, active_friendship: int,
                    base_friendship: int, moves: tuple[int, int, int, int], refresh_handler: bool):
    """Plan a recipient's friendship without changing any input.

    ``refresh_handler`` is an explicit adapter input for the Gen6 geographic
    refresh condition; this GBA profile has no qualified automatic mapping yet.
    History's active value is updated from the exact offered record before
    changing handler. Return/Frustration copy the opposite value only when the
    original-vs-handling selector changes, never merely for a different HT.
    """
    if not isinstance(history, FriendshipHistory) or not isinstance(recipient, TrainerIdentity):
        raise FriendshipPlanError("typed friendship history and recipient identity are required")
    history.validate()
    recipient.validate()
    _integer(active_friendship, 255, "active friendship")
    _integer(base_friendship, 255, "Gen6 base friendship")
    if type(refresh_handler) is not bool or type(moves) is not tuple or len(moves) != 4:
        raise FriendshipPlanError("four native moves and an explicit handler-refresh decision are required")
    for move in moves:
        _integer(move, MAX_GEN6_MOVE, "Gen6 move")
    state = replace(history, **{"original_friendship" if history.current_handler == 0 else "handling_friendship": active_friendship})
    initialized = False
    if recipient == state.original:
        state = replace(state, current_handler=0)
    else:
        initialized = state.handler is None or state.handler.handler_key != recipient.handler_key or refresh_handler
        if initialized:
            state = replace(state, handler=recipient, handling_friendship=base_friendship, handler_identity_unknown=False)
        state = replace(state, current_handler=1)
    changed = state.current_handler != history.current_handler
    if changed and (RETURN in moves or FRUSTRATION in moves):
        state = replace(state, **{"original_friendship" if state.current_handler == 0 else "handling_friendship":
                                 state.handling_friendship if state.current_handler == 0 else state.original_friendship})
    value = state.original_friendship if state.current_handler == 0 else state.handling_friendship
    return FriendshipTransition(state.validate(), value, changed, initialized)


def transform_received_party_record(mon: bytes, history: FriendshipHistory, recipient: TrainerIdentity, *,
                                    base_friendship: int, refresh_handler: bool):
    """Change only friendship, its encrypted word and checksum in a 100-byte record.

    Eggs are deliberately refused because their friendship byte stores hatch
    cycles. Other side effects (evolution, item use, Dex, mail, stats) are absent;
    the existing production trade capability remains unchanged and restrictive.
    """
    if not isinstance(mon, bytes) or len(mon) != 100:
        raise FriendshipPlanError("exact immutable pinned party record required")
    if not _inspect_party(mon, "received-party"):
        raise FriendshipPlanError("empty party slot has no friendship transition")
    serial, personality, ot_id, species, _ = _decode_box(mon[:80], "received-party")
    if not isinstance(history, FriendshipHistory) or history.serial != serial or not serial:
        raise FriendshipPlanError("retained friendship history names another owned instance")
    history.validate()
    key = personality ^ ot_id
    plain = bytearray(struct.pack("<12I", *(value ^ key for value in struct.unpack_from("<12I", mon, 32))))
    growth, attacks, misc = (_SUBSTRUCT_OFFSETS[index][personality % 24] * 12 for index in (0, 1, 3))
    origins = struct.unpack_from("<H", plain, misc + 2)[0]
    source_identity = TrainerIdentity(mon[20:27].split(b"\xff", 1)[0], origins >> 15, ot_id, (origins >> 7) & 15)
    if source_identity != history.original:
        raise FriendshipPlanError("retained original trainer differs from the exact encrypted record")
    if mon[19] & 4 or struct.unpack_from("<I", plain, misc + 4)[0] & (1 << 30):
        raise FriendshipPlanError("traded eggs require separate hatch-cycle and origin handling")
    # Bits above the native 11-bit move ID can contain immutable ownership UID.
    moves = tuple(value & 0x7FF for value in struct.unpack_from("<4H", plain, attacks))
    transition = plan_friendship(history, recipient, active_friendship=plain[growth + 9],
                                 base_friendship=base_friendship, moves=moves, refresh_handler=refresh_handler)
    plain[growth + 9] = transition.friendship
    result = bytearray(mon)
    struct.pack_into("<H", result, 28, sum(struct.unpack("<24H", plain)) & 0xFFFF)
    for index, value in enumerate(struct.unpack("<12I", plain)):
        struct.pack_into("<I", result, 32 + index*4, value ^ key)
    result = bytes(result)
    if _decode_box(result[:80], "received-party")[:4] != (serial, personality, ot_id, species):
        raise FriendshipPlanError("friendship transformation altered immutable instance identity")
    _inspect_party(result, "received-party")
    return result, transition
