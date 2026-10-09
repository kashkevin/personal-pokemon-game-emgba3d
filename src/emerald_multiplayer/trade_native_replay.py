"""Owned, bounded native replay against a verified ROM and packaged libmGBA.

SQLite is never accessed from this module's worker thread. Only immutable
canonical checkpoint snapshots and typed plans cross the event-loop boundary.
Every native call gets a new unbooted VM with no save file or player connection.
"""
from __future__ import annotations

import asyncio
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import time

from .companion import verify_rom_manifest
from .player_runtime import RuntimeBundle, _check_native_paths, _finish_even_if_cancelled
from .trade_effect_flash import prepare_effect_pair
from .trade_effect_witness import EvolutionMoveChoice
from .trade_replay_manifest import INPUT_MAX, OUTPUT_MAX, validate_trade_replay_manifest

WORKER_NAME = "emerald-trade-replay.exe"


def host_trade_effect_options(installation, store, manifest):
    """Compose the real adapter for every host lifecycle, including enrollment."""
    from .storage import StorageError
    from .trade_effect_storage import read_effect_policy
    supported = manifest.get("trade_replay_abi_version") == 1
    enabled = bool(getattr(store, "trade_effects_enabled", False))
    if not supported and not enabled:
        return {}
    if not supported:
        raise NativeReplayError("this world's native effect history needs its matching replay-enabled game")
    if not enabled:
        raise StorageError("trade_effect_migration_required", "run the explicit backed-up world trade history upgrade")
    policy = read_effect_policy(store)
    adapter = NativeTradeReplay(installation.rom_path, installation.manifest_path, installation.bundle)
    return dict(trade_effect_adapter=adapter, trade_effect_policy=policy)


class NativeReplayError(ValueError):
    code = "trade_native_replay_failed"


class NativeTradeReplay:
    profile_game_version = 3

    def __init__(self, rom_path, manifest_path, bundle):
        if not isinstance(bundle, RuntimeBundle):
            raise ValueError("native replay requires an application-pinned runtime")
        self.rom_path = Path(rom_path).resolve(strict=True)
        self.manifest_path = Path(manifest_path).resolve(strict=True)
        self.bundle = bundle
        self.engine_source_sha256, self.manifest = verify_rom_manifest(self.rom_path, self.manifest_path)
        if not validate_trade_replay_manifest(self.manifest, self.rom_path):
            raise ValueError("this build has no isolated native trade replay entry point")
        self._manifest_sha256 = hashlib.sha256(self.manifest_path.read_bytes()).hexdigest()
        self.worker = Path(bundle.directory).resolve(strict=True) / WORKER_NAME
        _check_native_paths(self.worker, self.rom_path)
        self._verify()
        self._job = None
        self._closed = False

    def _verify(self):
        self.bundle.verify()
        # verify() pins every file; require this additional executable by its
        # fixed name, never an executable or address supplied by a participant.
        with (self.worker.parent / "runtime.json").open("rb") as source:
            runtime = json.loads(source.read(16385))
        if WORKER_NAME not in runtime["files"]:
            raise NativeReplayError("the pinned runtime does not include native trade replay")
        if hashlib.sha256(self.manifest_path.read_bytes()).hexdigest() != self._manifest_sha256:
            raise NativeReplayError("the replay manifest changed")
        build, manifest = verify_rom_manifest(self.rom_path, self.manifest_path)
        if build != self.engine_source_sha256 or manifest != self.manifest:
            raise NativeReplayError("the replay engine changed")

    def _request(self, operation, body, friendship, choices, deadline, *, outgoing=0, incoming=0):
        if type(friendship) is not int or not 0 <= friendship <= 255 or type(choices) is not tuple or len(choices) > 16:
            raise NativeReplayError("invalid native replay policy or choice transcript")
        encoded = []
        for move, slot in choices:
            EvolutionMoveChoice(move, slot).validate()
            encoded.append(struct.pack("<HBB", move, slot, 0))
        if (type(outgoing) is not int or type(incoming) is not int
                or not 0 <= outgoing < 6 or not 0 <= incoming < 6):
            raise NativeReplayError("invalid native replay party slot")
        payload = struct.pack("<8I", 1, operation, friendship, len(choices), outgoing, incoming, 0, 0) + body + b"".join(encoded)
        if len(payload) > INPUT_MAX:
            raise NativeReplayError("native replay input exceeds its bound")
        timeout = min(15.0, deadline - time.monotonic())
        if timeout <= 0:
            raise NativeReplayError("native trade replay exceeded its deadline")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            result = subprocess.run([str(self.worker), str(self.rom_path),
                f"{self.manifest['trade_replay_descriptor_address']:08x}"],
                input=b"ETRQ" + struct.pack("<I", len(payload)) + payload,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.worker.parent,
                timeout=timeout, creationflags=flags, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise NativeReplayError("native replay worker could not finish; nothing was committed") from error
        raw = result.stdout
        expected = 100 if operation == 1 else OUTPUT_MAX
        if (result.returncode != 0 or len(raw) != 12 + expected
                or raw[:4] != b"ETRS" or struct.unpack_from("<II", raw, 4) != (0, expected)):
            raise NativeReplayError("native replay refused the complete candidate")
        return raw[12:]

    def _prepare(self, a, plan_a, b, plan_b, arguments):
        self._verify()
        if a.build_id != self.engine_source_sha256 or b.build_id != self.engine_source_sha256:
            raise NativeReplayError("canonical saves belong to another replay engine")
        deadline = time.monotonic() + 45

        def record(received, sent, friendship, choices):
            if type(received) is not bytes or len(received) != 100 or type(sent) is not bytes or len(sent) != 100:
                raise NativeReplayError("native replay needs two complete original party records")
            return self._request(1, received + sent, friendship, choices, deadline)

        def blocks(recipient1, recipient2, partner1, outgoing, incoming, friendship, choices):
            if any(type(value) is not bytes or len(value) != size for value, size in
                   ((recipient1, 15568), (recipient2, 3884), (partner1, 15568))):
                raise NativeReplayError("native replay needs complete original save blocks")
            result = self._request(2, recipient1 + recipient2 + partner1, friendship, choices,
                                   deadline, outgoing=outgoing, incoming=incoming)
            return result[:15568], result[15568:]

        result = prepare_effect_pair(a, plan_a, b, plan_b,
            engine_source_sha256=self.engine_source_sha256, profile_game_version=self.profile_game_version,
            replay_native=record, replay_save_native=blocks, **arguments)
        self._verify()  # Every worker reopened these paths; fence the entire replay.
        return result

    async def prepare_pair(self, a, plan_a, b, plan_b, **arguments):
        # Refuse excess work instead of retaining an unbounded queue of saves.
        if self._closed or self._job is not None:
            raise NativeReplayError("native replay is closed or already processing a trade")
        if type(a.payload) is not bytes or type(b.payload) is not bytes:
            raise NativeReplayError("native replay requires immutable canonical checkpoints")
        task = asyncio.create_task(asyncio.to_thread(partial(self._prepare, a, plan_a, b, plan_b, arguments)))
        self._job = task
        try:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # to_thread cannot safely be abandoned with an owned process.
                # The subprocess deadline kills/reaps it before releasing ownership.
                await _finish_even_if_cancelled(task)
                raise
        finally:
            self._job = None

    async def close(self):
        self._closed = True
        if self._job is not None:
            _, cancelled = await _finish_even_if_cancelled(self._job)
            if cancelled:
                raise asyncio.CancelledError
