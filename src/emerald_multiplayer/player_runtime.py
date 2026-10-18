"""Verified development runtime process, gated by closed-game recovery.

This is the launcher lifecycle beneath a future Host/Join interface. It only
opens an already enrolled character. The application pins a runtime manifest;
the manifest pins every executable and DLL in its bundle, and either the Lua
bridge mGBA runs (emerald-windows-runtime-v1) or, for the native game with its
own bridge, the ROM build it pairs with (emerald-native-runtime-v1). A native
bundle may also pin its game facts (runtime.json "game_facts", game_facts.py),
which stand in for the GBA ROM: the native game never reads a ROM. It may also
pin data folders the game reads beside its executable (runtime.json "data",
DATA_DIRECTORIES: the 3D battle effects), file by file.
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

from .bridge_config import configure, configure_native
from .cold_start import ColdStartRecovery
from .companion import verify_rom_manifest
from .game_facts import is_game_facts
from .live_checkpoint import _atomic

_HASH = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")
_MAX_FILE = 128 * 1024 * 1024
_WINDOWS_NATIVE_PATHS = os.name == "nt"
_LAUNCH_ID_PLACEHOLDER = "00000000-0000-0000-0000-000000000000"
_WINDOWS_RUNTIME = "emerald-windows-runtime-v1"
_NATIVE_RUNTIME = "emerald-native-runtime-v1"
_NATIVE_REQUIRED = frozenset({"format", "executable", "rom_sha256", "files"})
_NATIVE_OPTIONAL = frozenset({"classic_executable", "game_facts", "data"})
# Folders the native game reads beside its executable (SDL_GetBasePath()): battlefx/ holds the 3D battle effects
# (engine battlefx/; without it every move plays its GBA animation). runtime.json "data" pins each file in them as
# "battlefx/<path>": sha256. Programs never live there, and an unlisted script in one is refused.
DATA_DIRECTORIES = frozenset({"battlefx"})
_MAX_DATA = 64
_MAX_DATA_ENTRIES = 1024
_PROGRAM = frozenset({".exe", ".dll", ".lua"})
_DATA_CODE = _PROGRAM | {".js"}
# The native bundle's pinned game facts (game_facts.FILE_NAME), named by runtime.json "game_facts".
GAME_FACTS_NAME = "game-facts.json"
# The native game's settings (window, sound, the 3D view's look): one file
# beside the launch folders, since every game starts in a new one.
SETTINGS_NAME = "game-settings.cfg"


class PlayerRuntimeError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _check_native_paths(*paths):
    """Pinned Windows mGBA uses wchar_t[260]; count UTF-16 units plus NUL.

    Python's long-path support does not make its native child support the same
    paths. Callers resolve paths before this check; do not rewrite identities,
    introduce extended-path prefixes, or silently relocate a character.
    """
    if not _WINDOWS_NATIVE_PATHS:
        return
    for path in paths:
        value = str(path)
        try:
            supported = "\0" not in value and len(value.encode("utf-16-le")) // 2 <= 259
        except UnicodeError:
            supported = False
        if not supported:
            raise PlayerRuntimeError("runtime_path", "a native game path exceeds the supported Windows path format")


def _preflight_launch(executable, rom_path, save_path, directory, *, launch_root=None):
    """Read-only refusal before recovery/enrollment can mutate private state."""
    root = Path(launch_root) if launch_root is not None else Path(directory) / "launches"
    prospective = root.resolve() / _LAUNCH_ID_PLACEHOLDER
    _check_native_paths(Path(executable).resolve(), Path(rom_path).resolve(),
                        Path(save_path).resolve(), prospective, prospective / "bridge.lua",
                        root.resolve().parent / SETTINGS_NAME)


def _check_pairing(bridge, build):
    """A native game was built from one engine source: refuse it next to the
    ROM of another (KNOWN_ISSUES M1), before anything is reconciled."""
    if isinstance(bridge, NativeGame) and bridge.rom_sha256 != build:
        raise PlayerRuntimeError("game_changed", "the native game was built for another ROM than the verified one")


def _read(path, maximum):
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    if len(data) > maximum:
        raise PlayerRuntimeError("runtime_size", "runtime component exceeds its size limit")
    return data


def data_parts(key):
    """The path components of a runtime.json "data" key ("battlefx/shaders/card.frag"); ValueError otherwise."""
    if not isinstance(key, str):
        raise ValueError("data key")
    parts = key.split("/")
    if (not 2 <= len(parts) <= 4 or parts[0] not in DATA_DIRECTORIES
            or any(not _NAME.fullmatch(part) or part.endswith(".") for part in parts)
            or Path(parts[-1]).suffix.lower() in _PROGRAM):
        raise ValueError("data key")
    return parts


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate manifest field")
        value[key] = item
    return value


@dataclass(frozen=True)
class NativeGame:
    """What a native runtime bundle stands for in place of a Lua bridge: the
    executable bridges itself (engine src/platform/mp_bridge.c) and was built
    from the engine source of this GBA ROM build, which the companion verifies
    (KNOWN_ISSUES M1: the bundle's own record is the pairing)."""
    rom_sha256: str


@dataclass(frozen=True)
class RuntimeBundle:
    directory: Path
    manifest_sha256: str
    # Which of the bundle's games verify() returns: "3d" (the main game, the 3D
    # Diorama game in a package that has both) or "2d" (Classic 2D). The
    # launcher's Graphics mode picks it per start (graphics_mode.py).
    graphics: str = "3d"

    def is_native(self):
        """Display only (help text, labels): whether runtime.json names the native PC game.
        Every launch still runs verify(), which decides what may start."""
        try:
            raw = _read(Path(self.directory) / "runtime.json", 16384)
            return json.loads(raw).get("format") == _NATIVE_RUNTIME
        except (OSError, ValueError, AttributeError, PlayerRuntimeError):
            return False

    def has_classic(self):
        """Display only (the launcher's Graphics mode): whether runtime.json names a
        Classic 2D game. Every launch still runs verify()."""
        try:
            raw = _read(Path(self.directory) / "runtime.json", 16384)
            return json.loads(raw).get("classic_executable") is not None
        except (OSError, ValueError, AttributeError, PlayerRuntimeError):
            return False

    def game_facts_path(self, *, pinned=True):
        """Where this native bundle's game facts are (runtime.json "game_facts"), or None.

        The facts stand in for the GBA ROM (game_facts.py). With ``pinned`` the runtime record
        must match the launcher's pin; ``pinned=False`` is for choosing the installation's game
        source only, since every start still runs verify(), which hashes the facts file too."""
        try:
            root = Path(self.directory)
            raw = _read(root / "runtime.json", 16384)
            if pinned and hashlib.sha256(raw).hexdigest() != self.manifest_sha256:
                return None
            record = json.loads(raw)
            name = record.get("game_facts")
            if (record.get("format") != _NATIVE_RUNTIME or name != GAME_FACTS_NAME
                    or name not in record.get("files", {})):
                return None
            return (root / name).resolve()
        except (OSError, ValueError, AttributeError, TypeError, PlayerRuntimeError):
            return None

    def verify(self, graphics=None):
        """Recheck the pinned bundle immediately before each process launch.

        ``graphics`` picks which pinned game comes back: "3d" is the bundle's
        main game (the 3D Diorama game in a package that has both), "2d" its
        Classic 2D game. Everything in the bundle is verified either way."""
        graphics = self.graphics if graphics is None else graphics
        if graphics not in ("3d", "2d"):
            raise PlayerRuntimeError("runtime_manifest", "unknown graphics mode")
        if not isinstance(self.manifest_sha256, str) or not _HASH.fullmatch(self.manifest_sha256):
            raise PlayerRuntimeError("runtime_hash", "launcher must supply its pinned runtime manifest hash")
        root = Path(self.directory).resolve(strict=True)
        raw = _read(root / "runtime.json", 16384)
        if hashlib.sha256(raw).hexdigest() != self.manifest_sha256:
            raise PlayerRuntimeError("runtime_hash", "runtime manifest differs from the launcher pin")
        try:
            manifest = json.loads(raw, object_pairs_hook=_unique)
            if not isinstance(manifest, dict):
                raise ValueError()
            native = manifest.get("format") == _NATIVE_RUNTIME
            if native:
                # "classic_executable" (optional) is the Classic 2D game of the same engine build;
                # "game_facts" (optional) the pinned record that stands in for its GBA ROM (game_facts.py).
                if (not _NATIVE_REQUIRED <= set(manifest) <= _NATIVE_REQUIRED | _NATIVE_OPTIONAL
                        or not isinstance(manifest["rom_sha256"], str) or not _HASH.fullmatch(manifest["rom_sha256"])):
                    raise ValueError()
            elif set(manifest) != {"format", "executable", "bridge", "files"} or manifest["format"] != _WINDOWS_RUNTIME:
                raise ValueError()
            files = manifest["files"]
            if not isinstance(files, dict) or not 2 <= len(files) <= 32:
                raise ValueError()
            if any(not isinstance(name, str) or not _NAME.fullmatch(name) or name in {".", "..", "runtime.json"}
                   or not isinstance(digest, str) or not _HASH.fullmatch(digest) for name, digest in files.items()):
                raise ValueError()
            if len({name.casefold() for name in files}) != len(files):
                raise ValueError()
            executable = manifest["executable"]
            if executable not in files or not executable.lower().endswith(".exe"):
                raise ValueError()
            classic = manifest.get("classic_executable")
            if classic is not None and (classic not in files or not classic.lower().endswith(".exe")
                                        or classic == executable or not native):
                raise ValueError()
            facts = manifest.get("game_facts")
            if facts is not None and (facts != GAME_FACTS_NAME or facts not in files):
                raise ValueError()
            data = manifest.get("data", {})
            if "data" in manifest and (not native or not isinstance(data, dict) or not 1 <= len(data) <= _MAX_DATA):
                raise ValueError()
            for key, digest in data.items():
                data_parts(key)
                if not isinstance(digest, str) or not _HASH.fullmatch(digest):
                    raise ValueError()
            if len({key.casefold() for key in data}) != len(data):
                raise ValueError()
            if native:
                # Nothing for an emulator to run: the game is its own bridge.
                if any(name.lower().endswith(".lua") for name in files):
                    raise ValueError()
            else:
                bridge = manifest["bridge"]
                if bridge not in files or executable == bridge or not bridge.lower().endswith(".lua"):
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
        _verify_data(root, data)
        if graphics == "2d":
            if classic is None:
                raise PlayerRuntimeError("classic_unavailable", "this package has no Classic 2D game")
            executable = classic
        if native:
            return root / executable, NativeGame(manifest["rom_sha256"])
        return root / executable, (root / bridge).read_text(encoding="utf-8")


def _verify_data(root, data):
    """Each pinned data file is a regular file at exactly its path (no link or junction on the way), with its
    hash; the data folders hold no unlisted program or script."""
    for key, digest in data.items():
        path = root.joinpath(*data_parts(key))
        try:
            if path.is_symlink() or path.resolve(strict=True) != path or not path.is_file():
                raise PlayerRuntimeError("runtime_path", "game data must be a regular file inside its bundle")
            content = _read(path, _MAX_FILE)
        except OSError:
            raise PlayerRuntimeError("runtime_hash", "a pinned game data file is missing") from None
        if hashlib.sha256(content).hexdigest() != digest:
            raise PlayerRuntimeError("runtime_hash", "game data differs from its pinned hash")
    if unlisted_data(root, data):
        raise PlayerRuntimeError("runtime_unlisted", "a game data folder contains an unlisted program or script")


def unlisted_data(root, data):
    """Programs and scripts in the bundle's data folders that runtime.json "data" does not pin (sorted relative
    paths). A link anywhere in them, or an unbounded folder, is refused outright."""
    root, listed, found = Path(root), {key.casefold() for key in data}, []
    for directory in sorted({data_parts(key)[0] for key in data}):
        for count, child in enumerate((root / directory).rglob("*"), 1):
            if count > _MAX_DATA_ENTRIES:
                raise PlayerRuntimeError("runtime_unlisted", "a game data folder holds too many files")
            if child.is_symlink():
                raise PlayerRuntimeError("runtime_path", "a game data folder contains a link")
            name = child.relative_to(root).as_posix()
            if child.suffix.lower() in _DATA_CODE and name.casefold() not in listed:
                found.append(name)
    return sorted(found)


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
                      check_session, startup=None, *, launch_root=None, role=None):
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
    root = Path(launch_root) if launch_root is not None else Path(directory) / "launches"
    launch_directory = (root.resolve() / str(uuid4())).resolve()
    rom_path, save_path = Path(companion.config.rom_path).resolve(), Path(save_path).resolve()
    native = isinstance(bridge, NativeGame)
    _check_pairing(bridge, build)
    if not native and is_game_facts(rom_path):
        # Only the native game has its data compiled in; mGBA runs the ROM itself.
        raise PlayerRuntimeError("game_changed", "the emulator runtime needs the GBA ROM, not the package's game facts")
    script = launch_directory / ("bridge.txt" if native else "bridge.lua")
    settings = root.resolve().parent / SETTINGS_NAME
    _check_native_paths(executable, rom_path, save_path, launch_directory, script, settings)
    launch_directory.mkdir(mode=0o700, parents=True)
    token, port = companion.config.token.hex(), companion.ipc_address[1]
    if native:
        # The native game reads its port and token from this private file
        # and keeps its settings beside the launch folders.
        _atomic(script, configure_native(manifest, token, port).encode())
        arguments = (str(executable), "--save", str(save_path), "--bridge", str(script),
                     "--config", str(settings))
        if role is not None:
            # The game's own link status (the pause menu's HOSTING / CONNECTED). An argument, not a bridge-file line:
            # a game older than this ignores unknown arguments but refuses unknown bridge lines.
            arguments += ("--link-role", role)
    else:
        _atomic(script, configure(manifest, token, port, bridge).encode())
        arguments = (str(executable), "--multiplayer-script", str(script),
                     "--multiplayer-save", str(save_path), str(rom_path))
    log_path = launch_directory / "runtime.log"
    options = dict(cwd=launch_directory, stdin=asyncio.subprocess.DEVNULL)
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    process = None
    with log_path.open("xb") as log:
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(
            *arguments, stdout=log, stderr=log, **options))
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

    def __init__(self, companion, bundle, private_directory, save_path, *, launch_root=None, role=None):
        """``role``: "host" or "join", shown by the native game's link status (``--link-role``)."""
        if role not in (None, "host", "join"):
            raise PlayerRuntimeError("invalid_role", "the game's link role is host or join")
        self.companion, self.bundle = companion, bundle
        self.role = role
        self.directory = Path(private_directory).resolve()
        self.save_path = Path(save_path).resolve()
        self.launch_root = Path(launch_root).resolve() if launch_root is not None else None
        self._active = False

    @asynccontextmanager
    async def open(self):
        if self._active:
            raise PlayerRuntimeError("game_active", "this launcher already owns a game process")
        self._active = True
        try:
            executable, bridge = self.bundle.verify()
            c = self.companion
            build, manifest = verify_rom_manifest(c.config.rom_path, c.config.manifest_path)
            if build != c.config.build_id:
                raise PlayerRuntimeError("game_changed", "the game changed after companion authentication")
            _check_pairing(bridge, build)
            _preflight_launch(executable, c.config.rom_path, self.save_path, self.directory,
                              launch_root=self.launch_root)
            gate = ColdStartRecovery(c, self.directory, self.save_path)
            async with gate.open() as startup:
                session = gate._session()
                def check_session():
                    if gate._session() != session:
                        raise ConnectionError("authenticated startup session changed during game creation")
                # Reconciliation can await the network. Recheck pins and the
                # authenticated lease immediately before and after creation.
                async with _open_child(c, self.bundle, self.directory, self.save_path,
                                       build, manifest, check_session, startup,
                                       launch_root=self.launch_root, role=self.role) as game:
                    yield game
        finally:
            self._active = False
