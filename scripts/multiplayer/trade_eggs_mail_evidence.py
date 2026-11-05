"""What the host's saves hold of a traded Pokemon's Mail and of a traded Egg (owner decision 39), for
native_launcher_newcomers_proof.py --scenario trade-mail and trade-egg.

Every save is read with the app's own code: flash.inspect_flash and ownership.inspect_ownership (checksums, serials,
the ownership record), trade_mail (the Mail array at SaveBlock1 0x2BE0, a party Pokemon's Mail, ClearMail's pattern) and
ownership.box_is_egg / box_at. Only the fields the app does not read itself (a record's IVs, moves, original trainer's
name and gender, the Bad Egg flag, its shininess) are decoded here, from the record's C layout (include/pokemon.h of the
engine pin: struct BoxPokemon and its four substructures, the ownership serial in their unused bits). Read-only: these
functions take bytes and return what they found and the problems they saw; the proof requires there are none.
"""
from __future__ import annotations

from collections import Counter
import struct

from emerald_multiplayer.flash import POKEMON_SIZE, SAVED_PARTY_OFFSET, FlashError, inspect_flash
from emerald_multiplayer.ownership import (OWNERSHIP_PROFILE, _SUBSTRUCT_OFFSETS, box_at, box_is_egg,
                                           inspect_ownership)
from emerald_multiplayer.trade_mail import (MAIL_COUNT, MAIL_NONE, PARTY_MAIL_SLOTS, cleared_mail, held_item,
                                            mail_item, mail_slot_bytes, party_mail)

SHINY_ODDS = 8          # include/constants/pokemon.h of the engine pin (Gen 3 odds): shiny below it
CHARSET = {**{0xBB + i: chr(ord("A") + i) for i in range(26)}, **{0xD5 + i: chr(ord("a") + i) for i in range(26)},
           **{0xA1 + i: chr(ord("0") + i) for i in range(10)}, 0x00: " ", 0x1B: "é", 0xAB: "!", 0xAC: "?", 0xAD: ".",
           0xAE: "-", 0xB4: "'", 0xB8: ","}


def text(raw: bytes) -> str:
    """Game text (charmap.txt) up to its EOS (0xFF), as ASCII; anything else as {hex}."""
    out = []
    for byte in raw:
        if byte == 0xFF:
            break
        out.append(CHARSET.get(byte, "{%02x}" % byte))
    return "".join(out)


def name_bytes(raw: bytes) -> bytes:
    """A name up to its EOS: the record's seven bytes or the save's eight compare equal when the name is."""
    return bytes(raw).split(b"\xff", 1)[0]


def decode_record(box: bytes) -> dict:
    """A boxed record's fields (struct BoxPokemon), from a decrypted copy."""
    personality, ot_id = struct.unpack_from("<II", box)
    raw = struct.unpack_from("<12I", box, 32)
    physical = struct.pack("<12I", *(word ^ personality ^ ot_id for word in raw))
    sub = [physical[_SUBSTRUCT_OFFSETS[k][personality % 24] * 12:_SUBSTRUCT_OFFSETS[k][personality % 24] * 12 + 12]
           for k in range(4)]
    growth, attacks, misc = sub[0], sub[1], sub[3]
    met, ivs = struct.unpack_from("<HI", misc, 2)
    shiny_value = (ot_id >> 16) ^ (ot_id & 0xFFFF) ^ (personality >> 16) ^ (personality & 0xFFFF)
    modifier = struct.unpack_from("<H", box, 30)[0] >> 14 & 1
    checksum = sum(struct.unpack("<24H", physical)) & 0xFFFF
    return dict(
        personality=personality, ot_id=ot_id, species=struct.unpack_from("<H", growth, 0)[0] & 0x7FF,
        held_item=struct.unpack_from("<H", growth, 2)[0] & 0x3FF, friendship=growth[9],
        ball=struct.unpack_from("<H", growth, 10)[0] & 0x3F,
        moves=[struct.unpack_from("<H", attacks, 2 * i)[0] & 0x7FF for i in range(4)],
        ivs=[ivs >> (5 * i) & 31 for i in range(6)],          # HP, Atk, Def, Speed, SpAtk, SpDef (the record's order)
        egg_flag_misc=bool(ivs >> 30 & 1), egg_flag_header=bool(box[19] & 4), bad_egg=bool(box[19] & 1),
        has_species=bool(box[19] & 2), egg=box_is_egg(box), checksum_ok=checksum == struct.unpack_from("<H", box, 28)[0],
        nickname=text(box[8:18]), nickname_hex=box[8:18].hex(), language=box[18] & 7,
        ot_name=text(box[20:27]), ot_name_bytes=name_bytes(box[20:27]).hex(), ot_gender=met >> 15,
        met_level=met & 0x7F, met_location=misc[1], shiny=bool((shiny_value < SHINY_ODDS) ^ modifier),
        shiny_modifier=modifier)


def _snapshot(payload: bytes):
    parsed = inspect_flash(payload, save_profile=OWNERSHIP_PROFILE)
    return parsed, inspect_ownership(parsed)


def trainer(payload: bytes) -> dict:
    """The save's own player: its trainer ID, name and gender (SaveBlock2, as FlashMetadata reads them)."""
    meta = inspect_flash(payload, save_profile=OWNERSHIP_PROFILE).metadata
    return dict(trainer_id=meta.trainer_id, name=text(meta.name + b"\xff"), name_bytes=name_bytes(meta.name).hex(),
                gender=meta.gender)


def mail_fields(mail: bytes) -> dict:
    """struct Mail: nine Easy Chat words, its author's name and ID, the Pokemon it was written for, its item."""
    return dict(words=list(struct.unpack_from("<9H", mail)), author=text(mail[18:26]), author_id=mail[26:30].hex(),
                species=struct.unpack_from("<H", mail, 30)[0], item=mail_item(mail), hex=mail.hex())


def save_mail(payload: bytes) -> dict:
    """The save's 16 Mail slots and each party Pokemon's Mail reference, by its ownership serial."""
    parsed, owned = _snapshot(payload)
    block1 = parsed.save_block1
    party = {}
    for record in owned.records:
        if record.location.startswith("party:"):
            index = int(record.location.split(":")[1])
            mon = block1[SAVED_PARTY_OFFSET + index * POKEMON_SIZE:SAVED_PARTY_OFFSET + (index + 1) * POKEMON_SIZE]
            held = party_mail(block1, index)       # refuses a reference the game never makes (mail_invalid)
            party[record.serial] = dict(index=index, species=record.species, mail_slot=None if mon[85] == MAIL_NONE
                                        else mon[85], held_item=held_item(mon), mail=None if held is None else held.hex())
    return dict(slots=[mail_slot_bytes(block1, slot) for slot in range(MAIL_COUNT)], party=party)


def _held(view) -> Counter:
    """Every party Mail slot whose item is set, by its whole 36 bytes."""
    return Counter(slot for slot in view["slots"][:PARTY_MAIL_SLOTS] if mail_item(slot))


def census(payloads) -> list[int]:
    """How many times each Mail is held in these saves' parties together, sorted ([1, 1]: two Mails, each once)."""
    return sorted(sum((_held(save_mail(payload)) for payload in payloads), Counter()).values())


def mail_trade(before: tuple[bytes, bytes], after: tuple[bytes, bytes], serials: tuple[int, int]) -> tuple[dict, list]:
    """One exact trade of serials[0] (side 0's) for serials[1] (side 1's), each side's canonical save before and after it:
    each received Pokemon points at a party Mail slot holding exactly its sender's 36 bytes (or none when it held none),
    the sender's slot holds ClearMail's pattern of its Mail or, the slot taken again, the Mail received; no Mail of
    either side is duplicated or lost (the party slots holding Mail, both saves together, are the same 36-byte Mails
    before and after); every other Mail slot, the PC's mailbox included, unchanged."""
    try:
        views_before = [save_mail(payload) for payload in before]
        views_after = [save_mail(payload) for payload in after]
    except FlashError as error:     # includes a Mail reference the game never makes (trade_mail's mail_invalid)
        return dict(sides=[]), [f"a save does not read: {error}"]
    problems, sides = [], []
    for side in (0, 1):
        other = 1 - side
        sent = views_before[side]["party"].get(serials[side])
        received = views_after[other]["party"].get(serials[side])
        if sent is None or received is None:
            problems.append(f"serial {serials[side]} is not in side {side}'s party before or side {other}'s after")
            continue
        sent_mail = None if sent["mail"] is None else bytes.fromhex(sent["mail"])
        row = dict(serial=serials[side], from_side=side, sent_slot=sent["mail_slot"], received_slot=received["mail_slot"],
                   mail=None if sent_mail is None else mail_fields(sent_mail))
        if sent_mail is None:
            if received["mail_slot"] is not None:
                problems.append(f"serial {serials[side]} held no Mail but points at slot {received['mail_slot']}")
        else:
            got = views_after[other]["slots"][received["mail_slot"]] if received["mail_slot"] is not None else None
            row["received_bytes_equal"] = got == sent_mail
            if got != sent_mail:
                problems.append(f"serial {serials[side]}'s Mail did not arrive whole in slot {received['mail_slot']}")
            left = views_after[side]["slots"][sent["mail_slot"]]
            incoming = views_before[other]["party"][serials[other]]["mail"]
            row["sender_slot_after"] = ("cleared" if left == cleared_mail(sent_mail)
                                        else "the received Mail" if incoming is not None and left.hex() == incoming
                                        else "other")
            if row["sender_slot_after"] == "other":
                problems.append(f"side {side}'s slot {sent['mail_slot']} is neither cleared nor the received Mail")
            if any(slot == sent_mail for slot in views_after[side]["slots"]):
                problems.append(f"serial {serials[side]}'s Mail is still in its sender's save")
        sides.append(row)
    held_before = _held(views_before[0]) + _held(views_before[1])
    held_after = _held(views_after[0]) + _held(views_after[1])
    if held_before != held_after:
        problems.append("the Mails held in the two parties differ before and after (one duplicated or lost)")
    if any(count != 1 for count in held_after.values()):
        problems.append("a Mail is held twice")
    used = {side: {s["sent_slot"] for s in sides if s["from_side"] == side and s["sent_slot"] is not None}
            | {s["received_slot"] for s in sides if s["from_side"] != side and s["received_slot"] is not None}
            for side in (0, 1)}
    for side in (0, 1):
        for slot in range(MAIL_COUNT):
            if slot not in used[side] and views_before[side]["slots"][slot] != views_after[side]["slots"][slot]:
                problems.append(f"side {side}'s Mail slot {slot} changed though no traded Mail used it")
    summary = dict(sides=sides, held_before=len(held_before), held_after=len(held_after),
                   held_after_slots=[[side, slot] for side in (0, 1) for slot in range(PARTY_MAIL_SLOTS)
                                     if mail_item(views_after[side]["slots"][slot])])
    return summary, problems


def where_is(payload: bytes, serial: int) -> tuple[str, dict] | None:
    """The location and decoded record of an owned serial in a save, or None."""
    parsed, owned = _snapshot(payload)
    record = next((r for r in owned.records if r.serial == serial), None)
    if record is None:
        return None
    return record.location, decode_record(box_at(parsed.save_block1, parsed.storage, record.location))


def hatch(before: bytes, after: bytes, serial: int) -> tuple[dict, list]:
    """A traded Egg (serial) in its receiver's save before its hatch and the hatched Pokemon after it, in the same save:
    no Bad Egg (checksum, flag), an Egg before and none after; its original trainer the save's own player now (ID,
    name, gender); species, personality, IVs, moves and shininess as they were; the game's hatch fields (the species
    name, friendship 120, met level 0)."""
    problems = []
    try:
        found_before, found_after = where_is(before, serial), where_is(after, serial)
    except FlashError as error:     # a record the save's own checks refuse: a Bad Egg's checksum, a damaged serial
        return dict(serial=serial), [f"a save does not read: {error}"]
    if found_before is None or found_after is None:
        return dict(serial=serial), [f"serial {serial} is missing before or after the hatch"]
    (where_before, egg), (where_after, mon) = found_before, found_after
    own = trainer(after)
    if not egg["egg"]:
        problems.append("the record was not an Egg before")
    if mon["egg"] or mon["egg_flag_misc"] or mon["egg_flag_header"]:
        problems.append("the record is still an Egg")
    if mon["bad_egg"] or not mon["checksum_ok"] or not mon["has_species"]:
        problems.append("the hatched record is a Bad Egg")
    for key in ("species", "personality", "ivs", "moves", "shiny"):
        if mon[key] != egg[key]:
            problems.append(f"{key} changed: {egg[key]} -> {mon[key]}")
    if mon["ot_id"] != own["trainer_id"]:
        problems.append(f"the original trainer ID is {mon['ot_id']:#010x}, not the hatcher's {own['trainer_id']:#010x}")
    if mon["ot_name_bytes"] != own["name_bytes"]:
        problems.append(f"the original trainer's name is {mon['ot_name']!r}, not the hatcher's {own['name']!r}")
    if mon["ot_gender"] != own["gender"]:
        problems.append(f"the original trainer's gender is {mon['ot_gender']}, not the hatcher's {own['gender']}")
    if mon["friendship"] != 120 or mon["met_level"] != 0:
        problems.append(f"the hatch's own fields: friendship {mon['friendship']}, met level {mon['met_level']}")
    return dict(serial=serial, before=dict(location=where_before, **egg), after=dict(location=where_after, **mon),
                hatcher=own), problems
