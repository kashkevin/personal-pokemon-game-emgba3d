"""Bounded pre-generation mailbox; an ACK contains only an attempt number."""
from dataclasses import dataclass
from pathlib import Path
import struct
from .reset_protocol import ENCOUNTERS

FIELDS = frozenset({"reset_abi_version", "reset_abi_address", "reset_mailbox_address", "reset_mailbox_size"})
INPUT_FIELDS = frozenset({"reset_input_abi_version", "reset_input_abi_address"})
CAPABILITY = b"Q" + struct.pack("<HHHH", 1, 128, 32, 32)
_REQUEST = struct.Struct("<IIIII12s")
_REPLY = struct.Struct("<IIIIII8s")


def capability(version):
    if type(version) is not int or version not in (1, 2):
        raise ValueError("unsupported personal encounter capability")
    return b"Q" + struct.pack("<HHHH", version, 128, 32, 32)


@dataclass(frozen=True)
class ResetRequest:
    sequence: int
    session: int
    incarnation: int
    encounter: int
    observed_count: int

    def pack(self):
        for value in (self.sequence, self.session, self.incarnation, self.encounter):
            if type(value) is not int or not 1 <= value <= 0xFFFFFFFF:
                raise ValueError("invalid personal encounter request integer")
        if self.encounter not in ENCOUNTERS or type(self.observed_count) is not int or not 0 <= self.observed_count <= 0xFFFFFFFF:
            raise ValueError("invalid personal encounter descriptor or count")
        return _REQUEST.pack(self.sequence, self.session, self.incarnation, self.encounter, self.observed_count, bytes(12))

    @classmethod
    def unpack(cls, value):
        if type(value) is not bytes or len(value) != 32:
            raise ValueError("personal encounter request must be 32 bytes")
        *fields, reserved = _REQUEST.unpack(value)
        if any(reserved):
            raise ValueError("personal encounter request padding is nonzero")
        result = cls(*fields)
        result.pack()
        return result

    def reply(self, attempt, *, denied=False):
        self.pack()
        if type(denied) is not bool or type(attempt) is not int:
            raise ValueError("invalid personal encounter reply")
        if (denied and attempt != 0) or (not denied and not self.observed_count < attempt <= 0xFFFFFFFF):
            raise ValueError("invalid personal encounter attempt number")
        return _REPLY.pack(self.sequence, self.session, self.incarnation, self.encounter, attempt, int(denied), bytes(8))

    def cancel(self):
        self.pack()
        return _REPLY.pack(self.sequence, self.session, self.incarnation, self.encounter, 0, 2, bytes(8))


@dataclass(frozen=True)
class ResetReceipt:
    sequence: int
    session: int
    incarnation: int
    encounter: int
    attempt: int
    state: int
    field_ready: bool

    @classmethod
    def unpack(cls, payload):
        if type(payload) is not bytes or len(payload) != 32:
            raise ValueError("personal encounter receipt must be 32 bytes")
        sequence, session, incarnation, encounter, attempt, state, ready, reserved = struct.unpack("<8I", payload)
        ResetRequest(sequence, session, incarnation, encounter, 0).pack()
        if (reserved or state not in (1, 2, 3, 4) or ready not in (0, 1)
                or (state != 2 and attempt) or (state == 2 and not attempt)
                or (ready and state not in (3, 4))):
            raise ValueError("invalid personal encounter receipt")
        return cls(sequence, session, incarnation, encounter, attempt, state, bool(ready))

    def matches(self, request):
        return ((self.sequence, self.session, self.incarnation, self.encounter) ==
                (request.sequence, request.session, request.incarnation, request.encounter))


def validate_reset_manifest(manifest, rom_path=None):
    from .reset_catalogue import FIELDS as CATALOGUE_FIELDS, validate_reset_catalogue
    if not FIELDS.intersection(manifest):
        if INPUT_FIELDS.intersection(manifest) or CATALOGUE_FIELDS.intersection(manifest):
            raise ValueError("reset input requires the personal encounter mailbox")
        return False
    if not FIELDS <= set(manifest):
        raise ValueError("personal encounter manifest is incomplete")
    if (type(manifest.get("ownership_abi_version")) is not int or manifest["ownership_abi_version"] != 1
            or manifest.get("save_profile") != "rhh-1.17.1-bb1093-ownership-v1"
            or type(manifest.get("save_abi_version")) is not int or manifest["save_abi_version"] != 1):
        raise ValueError("personal encounters require the verified ownership/save profile")
    if type(manifest["reset_abi_version"]) is not int or manifest["reset_abi_version"] not in (1, 2) or type(manifest["reset_mailbox_size"]) is not int or manifest["reset_mailbox_size"] != 128:
        raise ValueError("unsupported personal encounter ABI")
    address, marker = manifest["reset_mailbox_address"], manifest["reset_abi_address"]
    if type(address) is not int or address % 4 or not 0x02000000 <= address <= 0x02040000 - 128:
        raise ValueError("personal encounter mailbox must be allocated in EWRAM")
    for key, size in (("mailbox_address", 128), ("save_mailbox_address", 512), ("battle_mailbox_address", 512),
                      ("menu_mailbox_address", 512), ("save_window_address", 4096)):
        if key in manifest:
            start = manifest[key]
            if type(start) is not int or not (address + 128 <= start or start + size <= address):
                raise ValueError("personal encounter mailbox overlaps another channel")
    size = Path(rom_path).stat().st_size if rom_path is not None else manifest.get("rom_size")
    if type(size) is not int or not 192 <= size <= 32 * 1024 * 1024:
        raise ValueError("personal encounter marker needs a valid ROM size")
    if type(marker) is not int or marker % 4 or not 0x08000000 <= marker <= 0x08000000 + size - 4:
        raise ValueError("personal encounter marker must be inside the ROM")
    if rom_path is not None:
        with Path(rom_path).open("rb") as source:
            source.seek(marker - 0x08000000)
            if source.read(4) != struct.pack("<I", manifest["reset_abi_version"]):
                raise ValueError("personal encounter ROM marker differs")
    if INPUT_FIELDS.intersection(manifest):
        input_marker = manifest.get("reset_input_abi_address")
        if (not INPUT_FIELDS <= set(manifest) or manifest["reset_abi_version"] != 2
                or type(manifest.get("reset_input_abi_version")) is not int
                or manifest["reset_input_abi_version"] != 1
                or type(input_marker) is not int or input_marker % 4
                or not 0x08000000 <= input_marker <= 0x08000000 + size - 4
                or input_marker == marker):
            raise ValueError("invalid separate native reset input capability")
        if rom_path is not None:
            with Path(rom_path).open("rb") as source:
                source.seek(input_marker - 0x08000000)
                if source.read(4) != struct.pack("<I", 1):
                    raise ValueError("native reset input ROM marker differs")
    validate_reset_catalogue(manifest, rom_path)
    return True
