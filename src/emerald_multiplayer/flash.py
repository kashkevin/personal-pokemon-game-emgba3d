"""Read-only ordinary Flash inspection for one pinned RHH save layout.

Source: RHH bb1093a7c72d3961d9a37d8e02ad2abc2c866682, include/save.h,
src/save.c, include/global.h, include/pokemon_storage_system.h, and the matching
ELF sSaveSlotLayout. Presence patches do not change the layout. This parser does
not repair data, fall back past a torn bank, write a save, or infer ROM identity.
The caller must separately bind the ROM/ruleset/profile in its authenticated
checkpoint envelope. Engine sector checksums exclude SaveBlock3 and special
sectors 30/31; transport hashes preserve those bytes without claiming otherwise.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
import hashlib
import struct
import threading
import zlib

LAYOUT_ID = "rhh-1.17.1-bb1093-presence-v1"
OWNERSHIP_LAYOUT_ID = "rhh-1.17.1-bb1093-ownership-v1"
FLASH_SIZE = 131072
RTC_FOOTER_SIZE = 16
MAX_CONTAINER_SIZE = FLASH_SIZE + RTC_FOOTER_SIZE
SECTOR_SIZE = 4096
SECTOR_DATA_SIZE = 3968
SAVE_BLOCK_3_CHUNK_SIZE = 116
SECTIONS_PER_BANK = 14
SECTOR_SIGNATURE = 0x08012025
SPECIAL_SECTOR_SENTINEL = 0xB39D
SAVE_BLOCK_1_SIZE = 15568
SAVE_BLOCK_2_SIZE = 3884
SAVE_BLOCK_3_SIZE = 4
OWNERSHIP_SAVE_BLOCK_3_SIZE = 600
# Update 30: the PC game's SaveBlock3 carries the Day Care egg queue after the 600-byte ownership profile (the profile itself is
# unchanged): magic "QGGE", version, count, five whole Egg boxed Pokemon, CRC-32. All zeros (a save from before) means no Eggs.
EGG_QUEUE_OFFSET = OWNERSHIP_SAVE_BLOCK_3_SIZE
EGG_QUEUE_CAPACITY = 5
EGG_QUEUE_SIZE = 4 + 1 + 1 + 2 + EGG_QUEUE_CAPACITY * 80 + 4
EGG_QUEUE_MAGIC = 0x45474751
# Battle Tower: Legends (docs/battle-tower-legends.md 8.6): the save's mirror of its trainer's Tower record follows the egg
# queue (engine struct MPTowerRecord, PC game only). All zeros (every older save) means no record: floor 1, nothing claimed.
TOWER_RECORD_OFFSET = EGG_QUEUE_OFFSET + EGG_QUEUE_SIZE
TOWER_RECORD_SIZE = 64
TOWER_RECORD_MAGIC = 0x314C5754  # "TWL1"
TOWER_PENDING_OUTCOMES = {0: None, 2: "won", 3: "lost", 5: "drew"}
SAVE_BLOCK_3_FULL_SIZE = TOWER_RECORD_OFFSET + TOWER_RECORD_SIZE
STORAGE_SIZE = 34144
PARTY_SIZE = 6
POKEMON_SIZE = 100
BOX_POKEMON_SIZE = 80
BOX_COUNT = 14
BOX_CAPACITY = 30
MAX_SPECIES_ID = 1572  # Storage namespace only; this is not an acquisition pool.
OBJECT_COUNT = 16
OBJECT_SIZE = 36
SAVED_OBJECTS_OFFSET = 0xA30
SAVED_PARTY_COUNT_OFFSET = 0x234
SAVED_PARTY_OFFSET = 0x238
FUSIONS_OFFSET = 0x83D0
FUSION_CAPACITY = 4
REMOTE_LOCAL_IDS = frozenset((241, 242, 243))
SECTION_LENGTHS = (3884, 3968, 3968, 3968, 3664,
                   3968, 3968, 3968, 3968, 3968, 3968, 3968, 3968, 2400)
_FOOTER = struct.Struct("<HHII")
# magic, version, highest, progress, pendingOutcome, pendingTicket, pendingFloor, reserved0, claims, revision, reserved1,
# reserved[40], crc32 (of bytes 0-59): all little-endian
_TOWER_RECORD = struct.Struct("<IBBBBIBBHHH40sI")
_UINT32 = 0xFFFFFFFF
_ERASED_SECTOR = bytes([0xFF]) * SECTOR_SIZE
# Generated factual bounds from pinned data/maps/map_groups.json.
_MAP_COUNTS = (57, 5, 5, 6, 7, 8, 9, 7, 7, 14, 8, 17, 10, 23, 13, 15, 15,
               2, 2, 2, 3, 1, 1, 1, 108, 61, 89, 2, 1, 13, 1, 1, 3, 1, 5,
               123, 60, 62, 4, 6, 8, 10, 6, 8, 20, 10, 8, 2, 10, 4, 2, 2,
               1, 1, 1, 2, 2, 3, 2, 3, 2, 1, 1, 6, 5, 5, 8, 8, 5, 5, 1,
               1, 1, 2, 1)
# Generated width/height byte pairs from pinned data/layouts/layouts.json.
_LAYOUT_DIMENSIONS = bytes.fromhex(
    "1e1e283c2814283c2814502850283c3c285014141414141414141414141414281414321450162850285050143c143c14283f"
    "2864288c283c64142850285064143c145014288c2864501428288c1450505028505050507828502850283c28502850285028"
    "5050505078280b0909080b0909080d0d0a090b080e090e0a0b080a08121c11090a090b08111311130e090f07151208080101"
    "11080a090a0909700a08150f110f010101010e0b14091409180f0a150c09160b130913090b140c0b0c090d080b0908061419"
    "08060c09150e160d1f0c33210c0e1a24111a111a0d0e0d0e0d0e0d0e0d0d0b0d0f090d0c0a080d1a0b080a090c09120e1e2a"
    "1e201d260b122418140a11212a0f201a201a302c282f16130d0d0d0d0d0d0d0d0d0d1c1e331822180e0914141415120c1011"
    "12131414181717190b0e1b2e131a171717171515131513132e2d23232e26150f1f0e23232e26010101010101010101010101"
    "01010101010101010101010101010101090929291715120c12110d0a1b081208080809080911090715070b090b090b090b09"
    "0b090b0907100e090f070e0907100f070f080f0b0a110c0b11080d0b090f0e0c09110d0e0e0e0e0b0e090c09140a0e090f0b"
    "0101010101010101010101010f0b0f0b0f0b0f0b0f0b050528282828282828283a1a0f0a0c080c080f180f160f160f160f16"
    "0f160f160f160f1608060f0612081208120812081208120c5028190a3848050711050a091309130c140d140b05065050100a"
    "100a120d110d241211211121120a163015172e1f2e1f01010f0e0d0b211e1b181e2e23260e090e090e0908070f110c090c09"
    "0a092633322515170c0a0c090807080708072c0f0f1413130e080e080b221c1e3e1822183c2812121c170e0e0e0e0e0e0e0e"
    "1b2e0b08141e0a090e0e1b18171130070908140a25262127311c1c1818113b1c190c110e0f0a4848130c110e0d0c0b0d0e08"
    "0d0b09080508100d120e100b3c3c091401010f12080808080808080808080808080808080808080808080808080808080808"
    "08080808221721183c131511151115110d0a05080a090d090d0a8b17150f1105288c0f0c28282828350f0d080f0b090e2e36"
    "1516222e1d1a1e1e110d140a141414141b1e2850502850281b1e131110151015101510151910201815181520191c16160908"
    "0908170b1b56090a06081e200d0d0e0e0e0e0e0e0e0e0e0e1b180b080c090b080d0a0c090d0a0d0e0b090b090f0a0f0a0b09"
    "0b0911140b090d140e090b090f170b090b150b0a120f0d100b090b091d191e191418120e0e090c09140a0e09090928282828"
    "28281d1e0b080c090a091814302830283028181430283c2830281814181430281828185054146c1430281828181448144814"
    "1850481418784814183c4814301418a03c14183c78141832301818a018284814302831283028364546201f15221016071707"
    "18135550301633162d161c222016161b181a241624162416241624161f131f131f131f131113111426232626262326233324"
    "3623392830242817281728173028302826182617261826182618181418141814181418141814181431280f0b100e090a0d0a"
    "5007083f0b0d0608060905071c0b130a0a090a0a0f140f140f140e170a09090a0f0b110b0d100d0f0d0f0d0f0d0f130e0d0b"
    "0d0b140b0d0b0a0a1c0b0f0b0f0b0f0b4237090b0d090a080a0819120d0d0d0d0d0d1c180d140b0d18320d0b0f0c0f0c0d12"
    "0d0c05070d0a0c090d100507181430141828302818141814181e188c1828182860143014010101015414183c481448141828"
    "183c18504814186430287828182818509014183c9014183c18140f0c0b110b090c090a090f0b110b1210392f130b0c0a0c0c"
    "0c090c090b090c0926182618393613160f12302e0f0b1b130b17100b1f1706070806100f1d1b1e2414141814191a13111211"
    "1211121112111211121112111211121005070b09100b0d0b0d0b0d0b0d0b100f110d0f0a3c201e071e070b0b0b0b0b0b0b0b"
    "0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b1711171117111711171120180f101e1e1417111a1319151707070707"
    "07070707070707070707070707070707070707070707070707071711171111071e6412111211121112111211121112111211"
    "121112111211121112111211121112110b091b27"
)
_GROWTH_SUBSTRUCT_OFFSETS = (0, 0, 0, 0, 0, 0, 1, 1, 2, 3, 2, 3,
                             1, 1, 2, 3, 2, 3, 1, 1, 2, 3, 2, 3)


class FlashError(ValueError):
    """The input is not a complete checkpoint in the pinned ordinary-save format."""


@dataclass(frozen=True)
class FlashMetadata:
    bank: int
    counter: int
    trainer_id: int
    name: bytes  # Game-encoded name, excluding the 0xFF terminator.
    gender: int
    party_count: int
    current_box: int
    map_group: int
    map_number: int
    x: int
    y: int
    map_layout_id: int
    stored_pokemon_count: int
    fusion_count: int


@dataclass(frozen=True)
class TowerRecord:
    """A save's Battle Tower record: its trainer's progress floor P (1-101), highest cleared floor H (0-100), the prizes
    claimed (8.4 op 1's bits), the result waiting for the host to settle it (outcome "won"/"lost"/"drew", its ticket and
    floor; None when nothing waits) and the record's revision (+1 for every Tower word the save applied)."""
    progress: int
    highest: int
    claims: int
    pending: str | None
    pending_ticket: int
    pending_floor: int
    revision: int


@dataclass(frozen=True)
class FlashSnapshot:
    container: bytes
    flash: bytes
    rtc_footer: bytes
    save_block1: bytes
    save_block2: bytes
    save_block3: bytes
    storage: bytes
    metadata: FlashMetadata
    sha256: str
    container_sha256: str
    state_sha256: str
    save_profile: str = LAYOUT_ID
    tower: TowerRecord | None = None   # the Battle Tower record of the selected bank, None when the save has none


@dataclass(frozen=True)
class _Bank:
    index: int
    counter: int
    rotation: int
    sections: tuple[bytes, ...]
    save_block3_size: int = SAVE_BLOCK_3_SIZE
    tower: TowerRecord | None = None


class _RecentResults:
    """The most recent results of a pure function of immutable bytes, kept by content (KNOWN_ISSUES MS-161: a world's
    integrity check reads each save several times: its older bank is usually the last save's newer one)."""

    def __init__(self, size: int):
        self._size, self._results, self._lock = size, OrderedDict(), threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self._results:
                self._results.move_to_end(key)
                return self._results[key]
        return None

    def put(self, key, value):
        with self._lock:
            self._results[key] = value
            self._results.move_to_end(key)
            while len(self._results) > self._size:
                self._results.popitem(last=False)
        return value


_recent_banks = _RecentResults(32)


def _checksum(data: bytes) -> int:
    # Exact CalculateChecksum: uint32 word sum, then fold to uint16 once.
    total = sum(struct.unpack(f"<{len(data) // 4}I", data)) & _UINT32
    return (total + (total >> 16)) & 0xFFFF


def _inspect_rtc(footer: bytes) -> None:
    # mGBA 0.10.5 GBASavedataRTCBuffer: time[7], control, uint64 LE lastLatch.
    # RTCControl uses only bits 3 (minute IRQ), 6 (24h), and 7 (power off).
    if len(footer) != RTC_FOOTER_SIZE or footer[7] & ~0xC8:
        raise FlashError("unrecognized mGBA RTC footer control")
    values = []
    for value in footer[:7]:
        if value & 0xF > 9 or value >> 4 > 9:
            raise FlashError("RTC footer contains invalid BCD")
        values.append((value >> 4) * 10 + (value & 0xF))
    year, month, day, weekday, hour, minute, second = values
    try:
        date(2000 + year, month, day)
    except ValueError as exc:
        raise FlashError("RTC footer has an invalid calendar date") from exc
    if weekday > 6 or minute > 59 or second > 59:
        raise FlashError("RTC footer has an invalid clock field")
    # mGBA writes hour % 12 in 12-hour mode, without a PM bit in its buffer.
    if hour >= (24 if footer[7] & 0x40 else 12):
        raise FlashError("RTC footer hour does not match its mode")
    if struct.unpack_from("<Q", footer, 8)[0] > 0x7FFFFFFFFFFFFFFF:
        raise FlashError("RTC footer timestamp is outside signed time bounds")


def _inspect_bank(flash: bytes, bank_index: int, save_profile: str = LAYOUT_ID) -> _Bank | None:
    physical = tuple(flash[(bank_index * 14 + i) * SECTOR_SIZE:
                           (bank_index * 14 + i + 1) * SECTOR_SIZE] for i in range(14))
    if all(sector == _ERASED_SECTOR for sector in physical):
        return None
    sections: list[bytes | None] = [None] * 14
    counters = set()
    rotations = set()
    for index, sector in enumerate(physical):
        if sector == _ERASED_SECTOR:
            raise FlashError("partial save bank; refusing an older fallback")
        section_id, checksum, signature, counter = _FOOTER.unpack_from(sector, 4084)
        if signature != SECTOR_SIGNATURE:
            raise FlashError("save bank contains an invalid or unfinished signature")
        if section_id >= 14 or sections[section_id] is not None:
            raise FlashError("save bank section IDs are invalid or duplicated")
        size = SECTION_LENGTHS[section_id]
        if checksum != _checksum(sector[:size]):
            raise FlashError("save bank section checksum mismatch")
        if any(sector[size:SECTOR_DATA_SIZE]):
            raise FlashError("save section padding does not match the pinned layout")
        # Both profiles may carry the egg queue (offset 600) and the Tower record after it: bytes below their end are
        # checked as a whole after the bank is assembled.
        chunk_used = max(0, min(SAVE_BLOCK_3_FULL_SIZE - section_id * 116, 116))
        if any(sector[SECTOR_DATA_SIZE + chunk_used:4084]):
            raise FlashError("SaveBlock3 padding does not match the pinned layout")
        sections[section_id] = sector
        counters.add(counter)
        rotations.add((index - section_id) % 14)
    if len(counters) != 1 or len(rotations) != 1 or any(item is None for item in sections):
        raise FlashError("mixed save bank counters or sector rotation")
    counter = next(iter(counters))
    if counter % 2 != bank_index:
        raise FlashError("save counter parity does not match its bank")
    size = SAVE_BLOCK_3_SIZE
    full_block3 = b"".join(sector[3968:4084] for sector in sections)[:SAVE_BLOCK_3_FULL_SIZE]  # type: ignore[index]
    _check_egg_queue(full_block3[EGG_QUEUE_OFFSET:EGG_QUEUE_OFFSET + EGG_QUEUE_SIZE])
    tower = parse_tower_record(full_block3[TOWER_RECORD_OFFSET:])
    if save_profile != OWNERSHIP_LAYOUT_ID and any(full_block3[SAVE_BLOCK_3_SIZE:EGG_QUEUE_OFFSET]):
        raise FlashError("SaveBlock3 padding does not match the pinned layout")
    if save_profile == OWNERSHIP_LAYOUT_ID:
        block3 = full_block3[:OWNERSHIP_SAVE_BLOCK_3_SIZE]
        if any(block3[SAVE_BLOCK_3_SIZE:]):
            from .ownership import _parse_metadata
            _parse_metadata(block3)
            size = OWNERSHIP_SAVE_BLOCK_3_SIZE
    return _Bank(bank_index, counter, next(iter(rotations)), tuple(sections), size, tower)  # type: ignore[arg-type]


def _check_egg_queue(queue: bytes) -> None:
    """The Day Care egg queue (Update 30): zeros, or a sealed list of whole Eggs. Never repaired, only refused."""
    if len(queue) != EGG_QUEUE_SIZE:
        raise FlashError("the egg queue has the wrong size")
    if not any(queue):
        return
    magic, version, count, reserved = struct.unpack_from("<IBBH", queue)
    crc = struct.unpack_from("<I", queue, EGG_QUEUE_SIZE - 4)[0]
    if (magic != EGG_QUEUE_MAGIC or version != 1 or count > EGG_QUEUE_CAPACITY or reserved != 0
            or crc != zlib.crc32(queue[:EGG_QUEUE_SIZE - 4])):
        raise FlashError("the egg queue is damaged or unsupported")
    for index in range(EGG_QUEUE_CAPACITY):
        egg = queue[8 + index * BOX_POKEMON_SIZE:8 + (index + 1) * BOX_POKEMON_SIZE]
        if index >= count:
            if any(egg):
                raise FlashError("an unused egg queue slot is not empty")
            continue
        _box_species(egg, f"waiting egg {index}")
        if not egg[19] & 2 or not egg[19] & 4:
            raise FlashError(f"waiting egg {index} is not an Egg")


def parse_tower_record(record: bytes) -> TowerRecord | None:
    """The Battle Tower record (docs/battle-tower-legends.md 8.6): None for all zeros (a save from before the Tower), else
    the sealed record. Like the egg queue it is never repaired, only refused (FlashError)."""
    if len(record) != TOWER_RECORD_SIZE:
        raise FlashError("the Tower record has the wrong size")
    if not any(record):
        return None
    (magic, version, highest, progress, outcome, ticket, floor, reserved0, claims, revision, reserved1, reserved,
     crc) = _TOWER_RECORD.unpack(record)
    if (magic != TOWER_RECORD_MAGIC or version != 1 or crc != zlib.crc32(record[:TOWER_RECORD_SIZE - 4])
            or reserved0 or reserved1 or any(reserved)):
        raise FlashError("the Tower record is damaged or unsupported")
    if highest > 100 or not 1 <= progress <= 101 or outcome not in TOWER_PENDING_OUTCOMES:
        raise FlashError("the Tower record's floors or result are out of bounds")
    return TowerRecord(progress, highest, claims, TOWER_PENDING_OUTCOMES[outcome], ticket, floor, revision)


def _inspect_special_sectors(flash: bytes) -> None:
    for index in range(28, 32):
        sector = flash[index * SECTOR_SIZE:(index + 1) * SECTOR_SIZE]
        if sector == _ERASED_SECTOR:
            continue
        if index < 30:
            checksum, reserved, signature, counter = _FOOTER.unpack_from(sector, 4084)
            if signature != SECTOR_SIGNATURE or checksum != _checksum(sector[:3968]):
                raise FlashError("Hall of Fame sector signature or checksum mismatch")
            if reserved != 0 or counter != 0 or any(sector[3968:4084]):
                raise FlashError("Hall of Fame sector has unsupported footer data")
        elif struct.unpack_from("<I", sector)[0] != SPECIAL_SECTOR_SENTINEL:
            # These special records are deliberately not interpreted as normal
            # footer-bearing sectors; upstream writes opaque data after a sentinel.
            raise FlashError("special record does not have its pinned-format sentinel")


def _box_species(box: bytes, label: str) -> int:
    if len(box) != BOX_POKEMON_SIZE:
        raise FlashError("invalid boxed Pokémon size")
    personality, ot_id = struct.unpack_from("<II", box)
    key = personality ^ ot_id
    words = tuple(value ^ key for value in struct.unpack_from("<12I", box, 32))
    checksum = sum((value & 0xFFFF) + (value >> 16) for value in words) & 0xFFFF
    if checksum != struct.unpack_from("<H", box, 28)[0]:
        raise FlashError(f"{label} boxed Pokémon checksum mismatch")
    has_species = bool(box[19] & 2)
    if box[19] & 1:
        raise FlashError(f"{label} is marked as a bad egg")
    growth = words[_GROWTH_SUBSTRUCT_OFFSETS[personality % 24] * 3]
    species = growth & 0x7FF
    if has_species:
        if not 1 <= species <= MAX_SPECIES_ID or not 1 <= (box[18] & 7) <= 7:
            raise FlashError(f"{label} has invalid species or language bounds")
    elif species != 0:
        raise FlashError(f"{label} species disagrees with its occupancy flag")
    return species


def _inspect_party(mon: bytes, label: str) -> bool:
    species = _box_species(mon[:80], label)
    if species:
        level = mon[84]
        hp, max_hp = struct.unpack_from("<HH", mon, 86)
        if not 1 <= level <= 100 or max_hp == 0 or hp > max_hp:
            raise FlashError(f"{label} has invalid level or HP bounds")
    return bool(species)


def _extract_bank(bank: _Bank) -> tuple[bytes, bytes, bytes, bytes, FlashMetadata]:
    key = (bank.index, bank.counter, bank.save_block3_size, bank.sections)
    return _recent_banks.get(key) or _recent_banks.put(key, _extract_bank_now(bank))


def _extract_bank_now(bank: _Bank) -> tuple[bytes, bytes, bytes, bytes, FlashMetadata]:
    data = tuple(sector[:size] for sector, size in zip(bank.sections, SECTION_LENGTHS))
    block2 = data[0]
    block1 = b"".join(data[1:5])
    storage = b"".join(data[5:14])
    block3 = b"".join(sector[3968:4084] for sector in bank.sections)[:bank.save_block3_size]
    name_field = block2[:8]
    if 0xFF not in name_field or name_field[0] == 0xFF:
        raise FlashError("trainer name is missing or unterminated")
    name = name_field[:name_field.index(0xFF)]
    gender = block2[8]
    trainer_id = struct.unpack_from("<I", block2, 10)[0]
    if gender > 1 or struct.unpack_from("<H", block2, 14)[0] > 999 or any(v > 59 for v in block2[16:19]):
        raise FlashError("trainer gender or play time is outside its bounds")
    count = block1[SAVED_PARTY_COUNT_OFFSET]
    if count > PARTY_SIZE:
        raise FlashError("party count exceeds six")
    for index in range(PARTY_SIZE):
        start = SAVED_PARTY_OFFSET + index * POKEMON_SIZE
        occupied = _inspect_party(block1[start:start + POKEMON_SIZE], f"party slot {index}")
        if occupied != (index < count):
            raise FlashError("party occupancy does not match its saved count")
    for index in range(OBJECT_COUNT):
        if block1[SAVED_OBJECTS_OFFSET + index * OBJECT_SIZE + 8] in REMOTE_LOCAL_IDS:
            raise FlashError("a temporary remote avatar was copied into the save")
    current_box = storage[0]
    if current_box >= BOX_COUNT:
        raise FlashError("current PC box is outside its bounds")
    stored_count = 0
    for index in range(BOX_COUNT * BOX_CAPACITY):
        start = 4 + index * BOX_POKEMON_SIZE  # BoxPokemon requires 4-byte alignment.
        stored_count += bool(_box_species(storage[start:start + 80], f"PC slot {index}"))
    fusion_count = 0
    for index in range(FUSION_CAPACITY):
        start = FUSIONS_OFFSET + index * POKEMON_SIZE
        fusion_count += _inspect_party(storage[start:start + 100], f"fusion slot {index}")
    group, number = block1[4:6]
    if group >= len(_MAP_COUNTS) or number >= _MAP_COUNTS[group]:
        raise FlashError("saved map identity is outside the pinned map table")
    layout_id = struct.unpack_from("<H", block1, 0x32)[0]
    if not 1 <= layout_id <= len(_LAYOUT_DIMENSIONS) // 2:
        raise FlashError("saved map layout is outside the pinned layout table")
    width, height = _LAYOUT_DIMENSIONS[(layout_id - 1) * 2:layout_id * 2]
    x, y = struct.unpack_from("<hh", block1)
    if not 0 <= x < width or not 0 <= y < height:
        raise FlashError("saved tile coordinates are outside their map layout")
    metadata = FlashMetadata(bank.index, bank.counter, trainer_id, name, gender, count,
                             current_box, group, number, x, y, layout_id,
                             stored_count, fusion_count)
    return block1, block2, block3, storage, metadata


def inspect_flash(data: bytes, *, expected_trainer_id: int | None = None,
                  save_profile: str = LAYOUT_ID) -> FlashSnapshot:
    """Validate and preserve a complete ordinary checkpoint without changing it.

    Both non-erased banks must be complete and coherent. This intentionally
    rejects a newer interrupted save instead of returning the game's older
    recovery bank. The server can then request a new completed in-game save.
    """
    if save_profile not in (LAYOUT_ID, OWNERSHIP_LAYOUT_ID):
        raise FlashError("save profile is unknown; explicit migration is required")
    if not isinstance(data, bytes) or len(data) not in (FLASH_SIZE, MAX_CONTAINER_SIZE):
        raise FlashError("checkpoint must contain exactly 128 KiB Flash, with at most its known 16-byte RTC footer")
    if expected_trainer_id is not None and (type(expected_trainer_id) is not int or not 0 <= expected_trainer_id <= _UINT32):
        raise FlashError("expected trainer ID is outside uint32 bounds")
    flash, footer = data[:FLASH_SIZE], data[FLASH_SIZE:]
    if footer:
        _inspect_rtc(footer)
    banks = tuple(bank for index in range(2) if (bank := _inspect_bank(flash, index, save_profile)) is not None)
    if not banks:
        raise FlashError("checkpoint has no complete ordinary save bank")
    _inspect_special_sectors(flash)
    decoded = tuple(_extract_bank(bank) for bank in banks)
    if len({parts[-1].trainer_id for parts in decoded}) != 1:
        raise FlashError("save banks belong to different trainer identities")
    if len(banks) == 2:
        first, second = banks
        delta = (second.counter - first.counter) & _UINT32
        if delta == 1:
            latest_index, older, latest = 1, first, second
        elif delta == _UINT32:
            latest_index, older, latest = 0, second, first
        else:
            raise FlashError("ordinary save banks do not have adjacent coherent counters")
        if latest.rotation != (older.rotation + 1) % 14:
            raise FlashError("ordinary save bank rotations do not advance together")
    else:
        latest_index = 0
    block1, block2, block3, storage, metadata = decoded[latest_index]
    tower = banks[latest_index].tower
    if expected_trainer_id is not None and metadata.trainer_id != expected_trainer_id:
        raise FlashError("checkpoint trainer identity does not match its enrolled owner")
    if save_profile == OWNERSHIP_LAYOUT_ID:
        from .ownership import _inspect_components, _inspect_inventory
        selected = _inspect_components(block3, block1, storage)
        for index, parts in enumerate(decoded):
            if index != latest_index and len(parts[2]) == OWNERSHIP_SAVE_BLOCK_3_SIZE:
                previous = _inspect_components(parts[2], parts[0], parts[3], allow_unassigned_inventory=True)
                if (previous.world_id, previous.player_id) != (selected.world_id, selected.player_id):
                    raise FlashError("ownership save banks belong to different world or player identities")
            elif index != latest_index:
                _inspect_inventory(parts[0], parts[3], require_ids=False)
    state = bytearray(b"EMP-SAVE-STATE\0" + save_profile.encode("ascii"))
    for payload in (block2, block1, block3, storage, flash[28 * SECTOR_SIZE:]):
        state.extend(struct.pack("<I", len(payload)))
        state.extend(payload)
    return FlashSnapshot(data, flash, footer, block1, block2, block3, storage, metadata,
                         hashlib.sha256(flash).hexdigest(), hashlib.sha256(data).hexdigest(),
                         hashlib.sha256(state).hexdigest(), save_profile, tower)
