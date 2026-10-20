"""Stateful singles/full-party Multi/co-op Gym admission for the pinned ARM layout.

This mirrors multiplayer_battle_controller.c. It permits no raw-memory, DMA,
debug, capture, bag or XP dispatch. Values are compiler/source-derived from the
native-singles development tree; a changed engine schema needs a new audit.
The receiving ROM independently validates every block before native dispatch.
"""
from __future__ import annotations

from pathlib import Path
import struct

from .battle_mailbox import BattleMailboxError, _integer
from .native_battle import COOP_PHASE, FFA_PHASES, PHASE, battler_count_for_phase, battler_owner, player_count_for_phase

MASTER_LENGTHS = {
    0: 4, 4: 4, 5: 4, 6: 2, 7: 4, 8: 4, 9: 4, 10: 4,
    14: 24, 15: 80, 16: 80, 17: 4, 19: 44, 21: 9,
    23: 4, 25: 5, 26: 6, 36: 4, 37: 4, 38: 4, 39: 4,
    40: 4, 41: 2, 42: 4, 43: 52, 44: 4, 45: 4,
    46: 4, 47: 12, 48: 4, 49: 2, 50: 6,
}
SET_FIELDS = {1: 2, 2: 2, 3: 16, 8: 5, 9: 1, 10: 1, 11: 1, 12: 1, 40: 4, 42: 2}
REPLY_LENGTHS = {28: 144, 32: 6, 33: 5}
_NEEDS_REPLY = frozenset((0, 17, 19, 21))
_SPECIES, _MOVES, _ABILITIES, _ITEMS, _TYPES = 1573, 935, 320, 874, 21
_STRINGS, _STRING_BUFFER = 721, 256


def _half(p, offset=0): return struct.unpack_from("<H", p, offset)[0]
def _word(p, offset=0): return struct.unpack_from("<I", p, offset)[0]


def read_string_lengths(rom_path, *, table_address):
    """Read the exact ROM's compiler-located table, never a network-supplied table.

    The caller first verifies ROM/ELF identity and the allocated table symbol.
    Lengths at/above the native output bound are capped there because such a
    token must be refused regardless of its full trusted ROM string length.
    """
    rom = Path(rom_path).read_bytes()
    _integer(table_address, 0x08000000, 0x09FFFFFF, "battle string table")
    offset = table_address-0x08000000
    if not 192 <= len(rom) <= 32*1024*1024 or offset % 4 or offset+4*_STRINGS > len(rom):
        raise BattleMailboxError("battle string table is outside the verified ROM")
    result = []
    for pointer in struct.unpack_from(f"<{_STRINGS}I", rom, offset):
        if pointer == 0:
            result.append(None)
            continue
        start = pointer-0x08000000
        if not 0 <= start < len(rom):
            raise BattleMailboxError("battle string pointer is outside the verified ROM")
        end = rom.find(b"\xff", start, min(start+_STRING_BUFFER, len(rom)))
        if end < 0 and start+_STRING_BUFFER > len(rom):
            raise BattleMailboxError("battle string runs beyond the verified ROM")
        result.append(_STRING_BUFFER if end < 0 else end-start)
    return tuple(result)


def _string_valid(p):
    for value in p:
        if value == 255:
            return True
        if value >= 252:
            return False
    return False


def _order_valid(p):
    return all((value & 15) < 6 and (value >> 4) < 6 for value in p)


def _animation_valid(p):
    # LinkBattleAnim8 starts with a four-byte transformed PID. Stockpile uses
    # bits2..5 of byte6; the low two bits are ordinary shiny booleans.
    return p[4] <= 5 and p[5] <= 5 and ((p[6] >> 2) & 15) <= 3 and not p[6] & 0xC0 and not p[7]


class ControllerValidator:
    def __init__(self, string_lengths, *, mode=PHASE):
        if (type(string_lengths) is not tuple or len(string_lengths) != _STRINGS
                or any(value is not None and (type(value) is not int or not 0 <= value <= _STRING_BUFFER)
                       for value in string_lengths)):
            raise BattleMailboxError("controller validation needs the pinned ROM string lengths")
        self._string_lengths = string_lengths
        # Battler indices bound every header/message field; the cores that
        # exchange blocks bound sources and completions. Co-op Gym battles have
        # four battlers but two cores (the master owns both AI opponents).
        self._count = battler_count_for_phase(mode)
        self._cores = player_count_for_phase(mode)
        self._mode = mode
        self._mask = (1 << self._count)-1
        self._done_mask = (1 << self._cores)-1
        self._pending = [None]*self._count
        self._done = [0]*self._count
        self._replied = [False]*self._count

    @property
    def pending(self):
        return tuple(self._pending)

    def _text_valid(self, p):
        if p[0] != 253:
            return _string_valid(p)
        index, output = 1, 0
        while index < 18:
            token = p[index]
            if token == 255:
                return output < _STRING_BUFFER
            if token == 0:
                size = 3
                if index+size >= 18:
                    return False
                value = _half(p, index+1)
                if not 7 <= value < _STRINGS or self._string_lengths[value] is None:
                    return False
                output += self._string_lengths[value]
            elif token == 1:
                if index+3 >= 18 or p[index+1] not in (1, 2, 4) or not 1 <= p[index+2] <= 10:
                    return False
                size, output = 3+p[index+1], output+p[index+2]
            elif token in (2, 6, 9, 10):
                size = 3
                if index+size >= 18 or _half(p, index+1) >= {2: _MOVES, 6: _SPECIES, 9: _ABILITIES, 10: _ITEMS}[token]:
                    return False
                output += 64
            elif token in (4, 7, 11):
                size = 3
                if index+size >= 18 or p[index+1] >= self._count or p[index+2] >= 6:
                    return False
                output += 32
            elif token in (3, 5, 8):
                size = 2
                if index+size >= 18 or p[index+1] >= {3: _TYPES, 5: 8, 8: 5}[token]:
                    return False
                output += 32
            else:
                return False
            if index+size >= 18 or output >= _STRING_BUFFER:
                return False
            index += size
        return False

    def _message_valid(self, p):
        m = p[4:80]
        string_id = _half(p, 2)
        return (string_id < _STRINGS and string_id != 6
            and (string_id < 7 or self._string_lengths[string_id] is not None)
            and _half(m) < _MOVES and _half(m, 2) < _MOVES
            and _half(m, 4) < _ITEMS and _half(m, 6) < _ABILITIES
            and m[8] < self._count and m[9] < 6 and m[11] < self._count and m[12] < _TYPES
            and all(_half(m, 14+i*2) < _ABILITIES for i in range(4))
            and all(self._text_valid(m[22+i*18:40+i*18]) for i in range(3)))

    def _move_choice_valid(self, p):
        m = p[4:44]
        return (p[1] == int(self._mode != PHASE) and p[2] <= 1 and p[3] == 0 and _half(m, 16) < _SPECIES
            and m[24] >> 2 <= 6
            and all(_half(m, i*2) < _MOVES and m[8+i] <= m[12+i]
                    and _half(m, 30+i*2) < _MOVES and not m[25+i] & ~15 for i in range(4))
            and all(t < _TYPES for t in m[18:21]))

    def _mon_valid(self, p):
        m = p[4:144]
        return (p[1] == 28 and _half(p, 2) == 140 and 0 < _half(m) < _SPECIES
            and _half(m, 48) < _ITEMS and _half(m, 32) < _ABILITIES
            and 1 <= m[44] <= 100 and _half(m, 42) <= _half(m, 46)
            and _string_valid(m[50:63]) and _string_valid(m[64:72])
            and all(_half(m, 12+i*2) < _MOVES for i in range(4))
            and all(t < _TYPES for t in m[34:37]) and all(v <= 12 for v in m[24:32]))

    def _master_valid(self, p):
        command = p[0]
        if command == 0:
            return p[1] == 0 and not p[2] & ~63 and (not p[2] or not p[2] & (p[2]-1)) and not p[3]
        if command == 2:
            if p[2] & ~63:
                return False
            if p[1] == 1: return _half(p, 3) < _SPECIES
            if p[1] == 2: return _half(p, 3) < _ITEMS
            if p[1] == 3:
                return all(_half(p, 3+i*2) < _MOVES for i in range(4)) and not any(p[16:19])
            return True
        if command == 5: return p[1] < 6 and p[2] <= 1 and p[3] <= 1
        if command == 6: return p[1] <= 1
        if command == 14: return _half(p, 1) < _MOVES and not any(p[14:16]) and _animation_valid(p[16:24])
        if command in (15, 16): return self._message_valid(p)
        if command == 17:
            # FIRST_TURN_EVENTS_END uses B_ACTION_NONE before the trainer
            # chooses. Only USE_ITEM consumes the item argument; native virtual
            # packing canonicalizes that otherwise stale scratch field to zero.
            return (p[1] <= 3 or p[1] == 255) and (_half(p, 2) < _ITEMS if p[1] == 1 else _half(p, 2) == 0)
        if command == 19: return self._move_choice_valid(p)
        if command == 21:
            return p[1] <= 4 and p[2] <= 6 and (p[3] | p[7] << 8) < _ABILITIES and p[8] < self._count and _order_valid(p[4:7])
        if command == 25: return not _word(p, 1) & ~8191
        if command == 26: return p[1] <= 1
        if command in (38, 39): return _half(p, 1) <= 609 and (p[3] == 0 if command == 38 else p[3] <= 1)
        if command == 41: return p[1] < 35
        if command == 43: return p[1] <= 1 and p[2] <= 1 and all(not _word(p, 8+i*8) & ~8191 for i in range(6))
        if command == 46: return p[1] <= 1
        if command == 47: return p[1] < 65 and _animation_valid(p[4:12])
        if command == 48: return p[1] <= 2 and not any(p[2:4])
        if command == 49: return p[1] <= 2
        if command == 50:
            # Free-for-all: byte 2 names the winner's battler (255: a draw) and each core works out its own result from it.
            # The winner is one of the trainers' battlers (never the 1v1v1's empty place).
            winner_ok = (p[2] < self._cores or p[2] == 255) if self._mode in FFA_PHASES else not p[2]
            return p[1] in (1, 2, 3) and winner_ok and not any(p[3:6])
        return True

    def _ai_target(self, battler, action, choice):
        """Co-op Gym: the master's AI foes (battlers 1 and 3) answer a move
        action with their default Struggle target, an opposing player battler,
        in the high byte (AI_TrySwitchOrUseItem). Trainers send 0."""
        target = choice >> 8
        return (self._mode == COOP_PHASE and battler & 1 and action == 0 and not choice & ~0xFF00
                and target < self._count and not target & 1)

    def validate(self, data, source):
        """Check a whole block without advancing pending requests/completions."""
        _integer(source, 0, self._cores-1, "authenticated controller source")
        if type(data) is not bytes or not 12 <= len(data) <= 156:
            raise BattleMailboxError("native controller block has an invalid byte length")
        role, battler, attacker, target, padded, absent, effect = struct.unpack_from("<BBBBHBB", data)
        if any(v >= self._count for v in (battler, attacker, target, effect)) or absent & ~self._mask or padded+8 != len(data):
            raise BattleMailboxError("native controller header exceeds its bound trainer count")
        p, pending = data[8:], self._pending[battler]
        valid = False
        if role == 2:
            valid = (padded == 8 and p[0] == source and not any(p[1:])
                and pending is not None and not self._done[battler] & (1 << source)
                and (source != battler_owner(self._mode, battler) or pending not in _NEEDS_REPLY or self._replied[battler]))
        else:
            command = p[0]
            raw = (3+SET_FIELDS[p[1]] if command == 2 and p[1] in SET_FIELDS
                   else MASTER_LENGTHS.get(command, REPLY_LENGTHS.get(command, 0)))
            if not raw or padded != raw-raw%4+4 or any(p[raw:]):
                raise BattleMailboxError("native controller command/field/length/padding is not allowed")
            p = p[:raw]
            if role == 0:
                valid = source == 0 and command not in REPLY_LENGTHS and pending is None and self._master_valid(p)
            elif (role == 1 and source == battler_owner(self._mode, battler) and pending is not None
                  and not self._replied[battler]):
                if command == 28:
                    valid = pending == 0 and self._mon_valid(p)
                elif command == 33:
                    valid = pending == 21 and p[1] <= 6 and _order_valid(p[2:5])
                elif command == 32:
                    choice = _word(p, 2)
                    if pending == 17:
                        valid = (p[1] <= 3 or p[1] in (13, 14)) and (not choice or self._ai_target(battler, p[1], choice))
                    elif pending == 19:
                        choice_mask = 0x1FF if self._mode == PHASE else 0x3FF
                        valid = p[1] == 10 and (choice == 0xFFFF or (not choice & ~choice_mask and choice & 0x7F < 4))
        if not valid:
            raise BattleMailboxError("native controller violates its source, payload or pending-request role")
        return self

    def accept(self, data, source):
        """Validate and then advance one ordered, previously unconsumed block."""
        self.validate(data, source)
        role, battler = data[:2]
        if role == 0:
            self._pending[battler], self._done[battler], self._replied[battler] = data[8], 0, False
        elif role == 1:
            self._replied[battler] = True
        else:
            self._done[battler] |= 1 << source
            if self._done[battler] == self._done_mask:
                self._pending[battler] = None
        return self
