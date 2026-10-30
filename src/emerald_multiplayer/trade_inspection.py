"""Read-only summaries of the two exact offered Pokemon, before consent.

No party/save bytes outside the selected records cross this interface. The
native pinned BoxPokemon layout is decoded on copies, never rewritten here.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, replace
import struct
from textwrap import wrap

from .flash import _inspect_party
from .ownership import _SUBSTRUCT_OFFSETS, _decode_box
from .protocol import ProtocolError, _fields
from .trade_forms import species_label
from .trade_labels import ITEM_NAMES, LATIN_CHARS, MOVE_NAMES, NATURE_NAMES


def move_label(move):
    return "Empty" if move == 0 else MOVE_NAMES.get(move, f"Move #{move}")


def item_label(item):
    return "None" if item == 0 else ITEM_NAMES.get(item, f"Item #{item}")


def _name(raw, language):
    if language == 1:  # Japanese uses an overlapping, different character map.
        return "Name unavailable"
    value = "".join(LATIN_CHARS.get(char, "?") for char in raw.split(b"\xff", 1)[0]).strip()
    return value or "Name unavailable"


@dataclass(frozen=True)
class PokemonSummary:
    serial: int
    species: int
    level: int | None
    nickname: str
    original_trainer: str
    trainer_id: int
    held_item: int
    nature: int
    stat_nature: int
    ability_slot: int
    shiny: bool
    moves: tuple[int, ...]
    pp: tuple[int, ...]
    ivs: tuple[int, ...]
    evs: tuple[int, ...]
    stats: tuple[int, ...] | None
    hp: int | None

    def pages(self):
        """At most four fact rows per page, leaving two native navigation rows."""
        nature = NATURE_NAMES.get(self.nature, f"#{self.nature}")
        stat_nature = NATURE_NAMES.get(self.stat_nature, f"#{self.stat_nature}")
        labels = ("HP", "Attack", "Defense", "Speed", "Sp. Atk", "Sp. Def")
        groups = (
            ("Pokemon", (species_label(self.species) + (f" Lv{self.level}" if self.level is not None else ""), self.nickname,
                         "Shiny: Yes" if self.shiny else "Shiny: No", f"Nature: {nature}")),
            ("Held item and origin", ("Held: " + item_label(self.held_item),
                         "OT: " + self.original_trainer, f"Trainer ID: {self.trainer_id & 0xFFFF:05d}",
                         f"Stat nature: {stat_nature}")),
            ("Moves", tuple(f"{move_label(move)} ({pp} PP)" for move, pp in zip(self.moves, self.pp))),
            ("IVs", tuple(f"{name}: {value}" for name, value in zip(labels[:3], self.ivs[:3]))),
            ("IVs continued", tuple(f"{name}: {value}" for name, value in zip(labels[3:], self.ivs[3:]))),
            ("EVs", tuple(f"{name}: {value}" for name, value in zip(labels[:3], self.evs[:3]))),
            ("EVs continued", tuple(f"{name}: {value}" for name, value in zip(labels[3:], self.evs[3:]))),
        )
        if self.stats is not None:
            groups += (
                ("Saved stats", (f"HP: {self.hp}/{self.stats[0]}",
                                 f"Attack: {self.stats[1]}", f"Defense: {self.stats[2]}", f"Speed: {self.stats[3]}")),
                ("Saved stats continued", (f"Sp. Atk: {self.stats[4]}", f"Sp. Def: {self.stats[5]}",
                             "Ability slot: " + ({0: "1", 1: "2", 2: "Hidden"}.get(self.ability_slot, "Unknown")),
                             f"Instance: {self.serial}")),
            )
        else:
            groups += (("Stored box record", ("Level/stats: game derived",
                "Ability slot: " + ({0: "1", 1: "2", 2: "Hidden"}.get(self.ability_slot, "Unknown")),
                f"Instance: {self.serial}")),)
        # Native rows have 25 printable columns. Preserve complete item/move
        # names and origin text across rows instead of silently truncating.
        pages = []
        for title, facts in groups:
            lines = [line for fact in facts for line in (wrap(fact, 25) or [""])]
            pages.extend((title, tuple(lines[start:start + 4])) for start in range(0, len(lines), 4))
        return tuple(pages)


def summarize_record(record):
    if type(record) is not bytes or len(record) != 100 or not _inspect_party(record, "trade inspection"):
        raise ValueError("trade inspection needs an occupied party record")
    return replace(summarize_box_record(record[:80]), level=record[84],
        stats=struct.unpack_from("<6H", record, 88), hp=struct.unpack_from("<H", record, 86)[0])


def summarize_box_record(record):
    """Read an owned stored record without inventing derived party level/stats."""
    if type(record) is not bytes or len(record) != 80:
        raise ValueError("stored Pokemon inspection requires exactly 80 bytes")
    serial, personality, trainer, species, _ = _decode_box(record, "stored Pokemon inspection")
    if serial == 0:
        raise ValueError("trade inspection requires an owned instance")
    physical = struct.pack("<12I", *(word ^ personality ^ trainer
        for word in struct.unpack_from("<12I", record, 32)))
    logical = b"".join(physical[row[personality % 24] * 12:row[personality % 24] * 12 + 12]
                       for row in _SUBSTRUCT_OFFSETS)
    packed_ivs = struct.unpack_from("<I", logical, 40)[0]
    packed_ribbons = struct.unpack_from("<I", logical, 44)[0]
    shiny_value = (trainer >> 16) ^ (trainer & 0xFFFF) ^ (personality >> 16) ^ (personality & 0xFFFF)
    # MON_DATA_IS_SHINY uses the pinned stored-format threshold plus modifier.
    # Personal Gen6 generation encodes its result into that modifier. Reading
    # an existing record does not roll RNG or choose a new shiny probability.
    shiny = bool((shiny_value < 8) ^ ((record[31] >> 6) & 1))
    nickname = record[8:18] + bytes(((struct.unpack_from("<I", logical, 4)[0] >> 21) & 0xFF,
                                   (struct.unpack_from("<H", logical, 10)[0] >> 6) & 0xFF))
    return PokemonSummary(serial, species, None, _name(nickname, record[18] & 7),
        _name(record[20:27], record[18] & 7), trainer, struct.unpack_from("<H", logical, 2)[0] & 0x3FF,
        personality % 25, (personality % 25) ^ (record[18] >> 3), (packed_ribbons >> 29) & 3, shiny,
        tuple(value & 0x7FF for value in struct.unpack_from("<4H", logical, 12)),
        tuple(value & 0x7F for value in logical[20:24]),
        tuple((packed_ivs >> (5 * index)) & 31 for index in range(6)), tuple(logical[24:30]),
        None, None)


def validate_inspection(view, actor):
    from .trade_protocol import _hash, _uuid
    _fields(view, {"transaction_id", "state", "generation", "fingerprint", "offers"})
    _uuid(view["transaction_id"], "transaction_id")
    _uuid(view["generation"], "generation")
    _hash(view["fingerprint"], "fingerprint")
    if view["state"] != "inspection" or type(view["offers"]) is not list or len(view["offers"]) != 2:
        raise ProtocolError("invalid_server_message", "inspection must contain two frozen offers")
    players, serials = [], []
    for offer in view["offers"]:
        _fields(offer, {"player_id", "serial", "record"})
        _uuid(offer["player_id"], "player_id")
        try:
            if type(offer["record"]) is not str or len(offer["record"]) != 136:
                raise ValueError()
            raw = base64.b64decode(offer["record"], validate=True)
            summary = summarize_record(raw)
            if (base64.b64encode(raw).decode("ascii") != offer["record"]
                    or type(offer["serial"]) is not int or offer["serial"] != summary.serial):
                raise ValueError()
        except (ValueError, TypeError) as error:
            raise ProtocolError("invalid_server_message", "invalid offered Pokemon inspection") from error
        players.append(offer["player_id"])
        serials.append(offer["serial"])
    if players != sorted(set(players)) or actor not in players or len(set(serials)) != 2:
        raise ProtocolError("identity_mismatch", "inspection names foreign or duplicated participants")
    return view


def summaries_for_view(inspection, view, actor):
    """Bind display facts to the exact previously displayed consent fingerprint."""
    validate_inspection(inspection, actor)
    if (any(inspection[key] != view[key] for key in ("transaction_id", "generation", "fingerprint"))
            or [entry["player_id"] for entry in inspection["offers"]] != view["players"]):
        raise ValueError("trade inspection belongs to a different offer pair")
    result = {}
    for inspected, offered in zip(inspection["offers"], view["offers"]):
        summary = summarize_record(base64.b64decode(inspected["record"], validate=True))
        if (inspected["player_id"], summary.serial, summary.species) != (offered["player_id"], offered["serial"], offered["species"]):
            raise ValueError("trade inspection changed an offered instance")
        result[inspected["player_id"]] = summary
    return result
