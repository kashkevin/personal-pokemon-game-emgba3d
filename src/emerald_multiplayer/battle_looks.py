"""Battle looks: the other players' characters in the native PC game's battles.

The native PC game (the engine's src/platform/mp_bridge.c) announces ``A``
(version 1, four slots) after its battle capability. For each battle that game
binds, the companion then sends ``B``: the binding's generation (16 bytes) and
one 8-byte look per binding slot, taken from the host's roster, the same looks
the overworld already shows. The game draws a link player's trainer picture
from the look of their slot (character_customization.c).

The battle itself is untouched: no startup block, canonical record or host
check changes, so a battle with an emulator game (mgba.lua never announces
``A``), an older native game or an older host runs exactly as before. A player
the roster does not hold, or one without a look, gets eight zero bytes (the
engine's trainer of their gender).
"""
from __future__ import annotations

import struct
from typing import Any, Iterable
from uuid import UUID

VERSION = 1
SLOTS = 4
LOOK_BYTES = 8


def capability_packet() -> bytes:
    """The native game's announcement: version and slots per frame."""
    return b"A" + struct.pack("<HH", VERSION, SLOTS)


def looks_packet(binding_data: bytes, players: Iterable[dict[str, Any]]) -> bytes:
    """The ``B`` frame for a packed native BIND binding and the host's roster."""
    from .native_battle import NativeBinding

    binding = NativeBinding.unpack(binding_data)
    looks: dict[UUID, bytes] = {}
    for player in players:
        appearance = player.get("appearance")
        if not appearance:
            continue
        try:
            look, identity = bytes.fromhex(appearance), UUID(player["player_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if len(look) == LOOK_BYTES:
            looks[identity] = look
    slots = [looks.get(UUID(player), bytes(LOOK_BYTES)) for player in binding.players]
    slots += [bytes(LOOK_BYTES)] * (SLOTS - len(slots))
    return b"B" + UUID(binding.generation).bytes + b"".join(slots)
