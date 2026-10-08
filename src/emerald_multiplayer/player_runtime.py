"""Verified development runtime process, gated by closed-game recovery.

This is the launcher lifecycle beneath a future Host/Join interface. It only
opens an already enrolled character. The application pins a runtime manifest;
the manifest pins every executable, DLL and the Lua bridge in its bundle.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from uuid import uuid4

from .bridge_config import configure
from .cold_start import ColdStartRecovery
from .companion import verify_rom_manifest
from .live_checkpoint import _atomic

_HASH = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")
_MAX_FILE = 128 * 1024 * 1024


class PlayerRuntimeError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _read(path, maximum):
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    if len(data) > maximum:
        raise PlayerRuntimeError("runtime_size", "runtime component exceeds its size limit")
    return data


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate manifest field")
        value[key] = item
    return value


@dataclass(frozen=True)
class RuntimeBundle:
    directory: Path
    manifest_sha256: str

    def verify(self):
        """Recheck the pinned bundle immediately before each process launch."""
        if not isinstance(self.manifest_sha256, str) or not _HASH.fullmatch(self.manifest_sha256):
            raise PlayerRuntimeError("runtime_hash", "launcher must supply its pinned runtime manifest hash")
        root = Path(self.directory).resolve(strict=True)
        raw = _read(root / "runtime.json", 16384)
        if hashlib.sha256(raw).hexdigest() != self.manifest_sha256:
            raise PlayerRuntimeError("runtime_hash", "runtime manifest differs from the launcher pin")
        try:
            manifest = json.loads(raw, object_pairs_hook=_unique)
            if (not isinstance(manifest, dict) or set(manifest) != {"format", "executable", "bridge", "files"}
                    or manifest["format"] != "emerald-windows-runtime-v1"):
                raise ValueError()
            files = manifest["files"]
            if not isinstance(files, dict) or not 2 <= len(files) <= 32:
                raise ValueError()
            if any(not isinstance(name, str) or not _NAME.fullmatch(name) or name in {".", "..", "runtime.json"}
                   or not isinstance(digest, str) or not _HASH.fullmatch(digest) for name, digest in files.items()):
                raise ValueError()
            if len({name.casefold() for name in files}) != len(files):
                raise ValueError()
            executable, bridge = manifest["executable"], manifest["bridge"]
            if (executable not in files or bridge not in files or executable == bridge
                    or not executable.lower().endswith(".exe") or not bridge.lower().endswith(".lua")):
                raise ValueError()
        except (TypeError, ValueError, KeyError, UnicodeError) as error:
            raise PlayerRuntimeError("runtime_manifest", "runtime manifest has an unsupported bounded format") from error
        # Reject unlisted DLLs rather than silently loading a different runtime.
        for child in root.iterdir():
            if child.suffix.lower() in {".exe", ".dll", ".lua"} and child.name not in files:
                raise PlayerRuntimeError("runtime_unlisted", "runtime bundle contains an unlisted executable component")
        for name, digest in files.items():
            path = root / name
            if path.is_symlink() or path.resolve(strict=True).parent != root or not path.is_file():
                raise PlayerRuntimeError("runtime_path", "runtime component must be a regular file inside its bundle")
            if hashlib.sha256(_read(path, _MAX_FILE)).hexdigest() != digest:
                raise PlayerRuntimeError("runtime_hash", "runtime component differs from its pinned hash")
        return root / executable, (root / bridge).read_text(encoding="utf-8")


@dataclass(frozen=True)
class RunningGame:
    process: asyncio.subprocess.Process
    startup: object
    log_path: Path

    async def wait(self):
        """Wait for the player to close the native game normally."""
        return await self.process.wait()


async def _stop(process):
    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), 5)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()


async def _finish_even_if_cancelled(task):
    """Retain ownership of a spawned child/lease through repeated cancellation."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    return result, cancelled


@asynccontextmanager
async def _open_child(companion, bundle, directory, save_path, build, manifest,
                      check_session, startup=None):
    """Private process owner. Caller must retain its admission gate/save lease.

    This helper grants no character admission and performs no save replacement.
    Both normal recovery and explicit first enrollment must establish their own
    distinct preconditions before using it.
    """
    executable, bridge = bundle.verify()
    final_build, final_manifest = verify_rom_manifest(companion.config.rom_path, companion.config.manifest_path)
    if final_build != build or final_manifest != manifest:
        raise PlayerRuntimeError("game_changed", "the game or mailbox manifest changed during startup recovery")
    check_session()
    launch_directory = Path(directory) / "launches" / str(uuid4())
    launch_directory.mkdir(mode=0o700, parents=True)
    script = launch_directory / "bridge.lua"
    _atomic(script, configure(manifest, companion.config.token.hex(), companion.ipc_address[1], bridge).encode())
    log_path = launch_directory / "runtime.log"
    options = dict(cwd=launch_directory, stdin=asyncio.subprocess.DEVNULL)
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    process = None
    with log_path.open("xb") as log:
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(
            str(executable), "--multiplayer-script", str(script),
            "--multiplayer-save", str(save_path), str(companion.config.rom_path),
            stdout=log, stderr=log, **options))
        try:
            process, cancelled = await _finish_even_if_cancelled(spawn)
            if cancelled:
                raise asyncio.CancelledError()
            check_session()
            yield RunningGame(process, startup, log_path)
        finally:
            if process is not None:
                cleanup = asyncio.create_task(_stop(process))
                _, cancelled = await _finish_even_if_cancelled(cleanup)
                if cancelled:
                    raise asyncio.CancelledError()


class PlayerRuntime:
    """Keep one owned game process inside one continuous verified save lease.

    Authenticate the companion first. Exit the context after ``game.wait()``
    for a normal close. On cancellation/error the child is terminated before
    releasing the lease; pending journals/canonical data remain for recovery.
    This class does not select an offline-play policy or imply a final save.
    """

    def __init__(self, companion, bundle, private_directory, save_path):
        self.companion, self.bundle = companion, bundle
        self.directory = Path(private_directory).resolve()
        self.save_path = Path(save_path).resolve()
        self._active = False

    @asynccontextmanager
    async def open(self):
        if self._active:
            raise PlayerRuntimeError("game_active", "this launcher already owns a game process")
        self._active = True
        try:
            self.bundle.verify()
            c = self.companion
            build, manifest = verify_rom_manifest(c.config.rom_path, c.config.manifest_path)
            if build != c.config.build_id:
                raise PlayerRuntimeError("game_changed", "the game changed after companion authentication")
            gate = ColdStartRecovery(c, self.directory, self.save_path)
            async with gate.open() as startup:
                session = gate._session()
                def check_session():
                    if gate._session() != session:
                        raise ConnectionError("authenticated startup session changed during game creation")
                # Reconciliation can await the network. Recheck pins and the
                # authenticated lease immediately before and after creation.
                async with _open_child(c, self.bundle, self.directory, self.save_path,
                                       build, manifest, check_session, startup) as game:
                    yield game
        finally:
            self._active = False
