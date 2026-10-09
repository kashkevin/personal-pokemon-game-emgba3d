"""Exact native move facts bound to one retained private preparation record.

These observations grant no trade publication or standalone native authority.
Only the held client can obtain/consume a ChoiceSnapshot on its original core.
"""
from dataclasses import dataclass, field
import struct
import zlib

from .trade_effect_mailbox import PreparedRecord
from .trade_inspection import summarize_record


@dataclass(frozen=True)
class MoveInfo:
    move: int
    pp: int
    max_pp: int
    power: int
    accuracy: int
    type_id: int
    category: int
    protected: bool


@dataclass(frozen=True)
class NativeChoiceView:
    received_serial: int
    sent_serial: int
    record_crc: int
    pending_move: int
    learnset_cursor: int
    state: int
    choice_count: int
    replace_mask: int
    moves: tuple[MoveInfo, ...]

    @classmethod
    def parse(cls, raw):
        if type(raw) is not bytes or len(raw) != 84:
            raise ValueError("native move presentation must contain exactly 84 bytes")
        version, received, sent, crc, move, cursor, state, count, mask, zero = struct.unpack_from("<IIIIHHBBBB", raw)
        if (version != 1 or not 1 <= received <= 0xFFFFF or not 1 <= sent <= 0xFFFFF or received == sent
                or state not in (1, 2) or count > 16 or mask > 15 or zero or cursor > 256
                or (state == 1 and (count >= 16 or not 1 <= move <= 621))
                or (state == 2 and (move or mask))):
            raise ValueError("invalid native move presentation header")
        moves = []
        for index in range(5):
            ident, pp, maximum, power, accuracy, kind, category, flags, reserved = struct.unpack_from("<HBBHBBBBH", raw, 24 + index * 12)
            # Pinned DamageCategory enum includes NONE=0; occupied moves use
            # PHYSICAL=1, SPECIAL=2 and STATUS=3 (pokemon.h).
            if (ident > 621 or pp > maximum or accuracy > 100 or kind > 31 or category > 3 or flags > 1 or reserved
                    or (not ident and any((pp, maximum, power, accuracy, kind, category, flags)))
                    or (ident and (maximum == 0 or category == 0))
                    or (index == 4 and (ident != move or pp != maximum or flags))):
                raise ValueError("invalid native move facts")
            if index < 4 and bool(mask & (1 << index)) != bool(state == 1 and ident and not flags):
                raise ValueError("replacement mask differs from native protected slots")
            moves.append(MoveInfo(ident, pp, maximum, power, accuracy, kind, category, bool(flags)))
        return cls(received, sent, crc, move, cursor, state, count, mask, tuple(moves))

    def match(self, record_bytes):
        record = PreparedRecord.parse(record_bytes)
        summary = summarize_record(record.candidate)
        if ((self.received_serial, self.sent_serial, self.pending_move, self.learnset_cursor,
             self.state, self.choice_count, self.record_crc) !=
                (record.received_serial, record.sent_serial, record.pending_move, record.learnset_cursor,
                 record.state, len(record.choices), zlib.crc32(record_bytes))
                or tuple(move.move for move in self.moves[:4]) != summary.moves
                or tuple(move.pp for move in self.moves[:4]) != summary.pp):
            raise ValueError("native move facts no longer describe the exact retained record")
        return record


@dataclass(frozen=True)
class ChoiceSnapshot:
    record: PreparedRecord
    view: NativeChoiceView
    record_bytes: bytes = field(repr=False)
    view_bytes: bytes = field(repr=False)
    # The client also requires this exact object, never a reconstructed token.
    binding: tuple = field(repr=False)


def validate_presentation(value, move, slot, index):
    """Validate the optional durable native-screen evidence in a choice journal."""
    if value is None:
        return
    if (type(value) is not dict or set(value) != {"record", "view", "screen", "request_sequence", "slot"}
            or type(value["screen"]) is not int or not 1 <= value["screen"] <= 0xFFFFFFFF
            or type(value["request_sequence"]) is not int or not 1 <= value["request_sequence"] <= 0xFFFFFFFF
            or type(value["slot"]) is not int or value["slot"] != slot):
        raise ValueError("invalid retained native-screen decision")
    # Canonical byte decoding shared with the held journal; imported lazily to
    # avoid a module cycle during ordinary save-mailbox loading.
    from .trade_effect_session import _bytes
    record_raw, view_raw = _bytes(value["record"], 192), _bytes(value["view"], 84)
    view = NativeChoiceView.parse(view_raw)
    record = view.match(record_raw)
    if (record.state != 1 or record.pending_move != move or len(record.choices) != index
            or (slot < 4 and not view.replace_mask & (1 << slot))):
        raise ValueError("native-screen decision names a different pending move/slot")
