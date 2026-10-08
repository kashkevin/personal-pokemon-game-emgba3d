"""Binary loopback bridge framing, separate from the JSON world protocol."""

from __future__ import annotations

import asyncio
from collections import deque
import struct

MAX_BRIDGE_FRAME_BYTES = 256


class BridgeError(ValueError):
    pass


class BridgeBackpressure(BridgeError):
    """Reliable bridge capacity is exhausted; cancel/close the connection."""


def encode_packet(payload: bytes, *, maximum=MAX_BRIDGE_FRAME_BYTES) -> bytes:
    if maximum not in (256, 4337) or not isinstance(payload, bytes) or not 1 <= len(payload) <= maximum:
        raise BridgeError("bridge frame length is outside its bounds")
    return struct.pack("!I", len(payload)) + payload


async def read_packet(reader: asyncio.StreamReader, *, maximum=MAX_BRIDGE_FRAME_BYTES) -> bytes | None:
    if maximum not in (256, 4337):
        raise BridgeError("unsupported bridge frame bound")
    try:
        header = await reader.readexactly(4)
    except asyncio.IncompleteReadError as error:
        if not error.partial:
            return None
        raise BridgeError("truncated bridge header") from error
    size = struct.unpack("!I", header)[0]
    if not 1 <= size <= maximum:
        raise BridgeError("bridge frame length is outside its bounds")
    try:
        return await reader.readexactly(size)
    except asyncio.IncompleteReadError as error:
        raise BridgeError("truncated bridge payload") from error


class LatestPacket:
    """One replaceable downstream snapshot; slow readers cannot grow a queue."""

    def __init__(self) -> None:
        self.pending: bytes | None = None
        self.closed = False
        self.ready = asyncio.Event()

    def put(self, payload: bytes) -> None:
        frame = encode_packet(payload)
        if not self.closed:
            self.pending = frame
            self.ready.set()

    async def get(self) -> bytes | None:
        while not self.closed:
            if self.pending is not None:
                frame, self.pending = self.pending, None
                return frame
            self.ready.clear()
            await self.ready.wait()
        return None

    def close(self) -> None:
        self.closed = True
        self.pending = None
        self.ready.set()


class BridgeOutbox:
    """Bounded reliable controls and one current presence snapshot.

    Controls retain FIFO order. At most two controls precede an available
    snapshot, so an ongoing save transfer cannot starve presence updates.
    """

    def __init__(self, limit: int = 4) -> None:
        if type(limit) is not int or not 1 <= limit <= 4:
            raise ValueError("bridge reliable capacity must be between one and four")
        self.limit = limit
        self.controls: deque[bytes] = deque()
        self.pending: bytes | None = None
        self.closed = False
        self.ready = asyncio.Event()
        self._control_burst = 0

    def put(self, payload: bytes) -> None:
        frame = encode_packet(payload)
        if not self.closed:
            self.pending = frame
            self.ready.set()

    def put_control(self, payload: bytes) -> None:
        frame = encode_packet(payload)
        if self.closed:
            raise BridgeError("bridge outbox is closed")
        if len(self.controls) >= self.limit:
            raise BridgeBackpressure("bridge reliable queue is full")
        self.controls.append(frame)
        self.ready.set()

    async def get(self) -> bytes | None:
        while not self.closed:
            if self.controls and (self.pending is None or self._control_burst < 2):
                self._control_burst += 1
                return self.controls.popleft()
            if self.pending is not None:
                frame, self.pending = self.pending, None
                self._control_burst = 0
                return frame
            self.ready.clear()
            await self.ready.wait()
        return None

    def close(self) -> None:
        self.closed = True
        self.controls.clear()
        self.pending = None
        self.ready.set()
