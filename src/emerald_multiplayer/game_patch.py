"""Deterministic BPS creation for the private release builder.

This project-owned encoder follows byuu's public-domain BPS format. It uses
SourceRead for unchanged runs and TargetRead for changed bytes. It favors
bounded memory/work over the smallest possible delta and adds no dependency.
The launcher still authenticates source, patch and reconstructed game by SHA256.
"""
from __future__ import annotations

import struct
import zlib

from .game_import import MAX_ACTIONS, MAX_PATCH, MAX_ROM, GameImportError


MIN_COPY = 32
COMPARE_CHUNK = 4096


def _number(value: int) -> bytes:
    encoded = bytearray()
    while value >= 128:
        encoded.append(value & 127)
        value = (value >> 7) - 1
    encoded.append(value | 128)
    return bytes(encoded)


def create_bps(source: bytes, target: bytes) -> bytes:
    """Encode supplied bytes only; never discover/download a base game.

    Empty and oversized inputs are refused. A minimum unchanged run length
    bounds command count even for adversarial alternating input. Metadata is
    empty, so private paths, filenames and account data cannot enter it.
    """
    if (type(source) is not bytes or type(target) is not bytes
            or not 0 < len(source) <= MAX_ROM or not 0 < len(target) <= MAX_ROM):
        raise GameImportError("import_size")
    patch = bytearray(b"BPS1")
    patch.extend(_number(len(source)))
    patch.extend(_number(len(target)))
    patch.extend(_number(0))
    common = min(len(source), len(target))
    cursor = literal_start = actions = 0

    def emit(action: int, start: int, end: int):
        nonlocal actions
        if start == end:
            return
        actions += 1
        if actions > MAX_ACTIONS:
            raise GameImportError("patch_invalid")
        patch.extend(_number(((end - start - 1) << 2) | action))
        if action == 1:
            patch.extend(target[start:end])

    while cursor < common:
        if source[cursor] != target[cursor]:
            cursor += 1
            continue
        start = cursor
        # Skip long equal regions in C rather than comparing every byte in
        # Python. Short unequal blocks are scanned once below.
        while cursor + COMPARE_CHUNK <= common and (
                source[cursor:cursor + COMPARE_CHUNK]
                == target[cursor:cursor + COMPARE_CHUNK]):
            cursor += COMPARE_CHUNK
        while cursor < common and source[cursor] == target[cursor]:
            cursor += 1
        if cursor - start >= MIN_COPY:
            emit(1, literal_start, start)
            emit(0, start, cursor)
            literal_start = cursor
    emit(1, literal_start, len(target))
    patch.extend(struct.pack("<II", zlib.crc32(source), zlib.crc32(target)))
    patch.extend(struct.pack("<I", zlib.crc32(patch)))
    if len(patch) > MAX_PATCH:
        raise GameImportError("import_size")
    return bytes(patch)
