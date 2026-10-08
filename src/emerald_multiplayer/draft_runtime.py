"""Ordinary offline New Game in a fresh, never-enrolled private save.

This is source preparation, not offline play of a canonical character. There is
no network/ownership bridge, imported save, synthetic save, or emulator input.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from .checkpoint_mirror import MirrorLease
from .flash import LAYOUT_ID, MAX_CONTAINER_SIZE, inspect_flash
from .launcher_session import GameInstallation
from .live_checkpoint import _atomic, _json_bytes
from .ownership import extract_source_inventory
from .player_runtime import RunningGame, PlayerRuntimeError, _check_native_paths, _finish_even_if_cancelled, _stop


# The verified SDL adapter requires a script/save pair. An empty Lua chunk
# retains its isolated-save and reset/state/cheat protections without attaching
# any callbacks, IPC, sockets, memory writes or ownership grants.
DRAFT_SCRIPT = "-- Ordinary New Game source preparation; no bridge or callbacks.\n"
_MESSAGES = {
    "invalid_configuration": "The new-character configuration is invalid.",
    "installation_changed": "The installed game could not be verified.",
    "runtime_path": "The game or character location is unsupported; use a shorter installation or private-data location.",
    "draft_used": "Start a fresh draft for another new character.",
    "draft_closed": "The new-character draft is not open.",
    "game_running": "Save through the game's menu and close the game first.",
    "game_failed": "The game did not close normally; the private draft is retained.",
    "save_required": "Create a character, choose a starter and save through the game's menu first.",
    "invalid_source": "The draft is not a valid, unassigned character save.",
    "starter_required": "Choose a starter and save through the game's menu before enrollment.",
    "draft_finished": "This draft already has its source receipt.",
    "draft_failed": "New-character preparation could not complete; its private files are retained.",
}


class DraftRuntimeError(ValueError):
    def __init__(self, code):
        self.code = code if code in _MESSAGES else "draft_failed"
        super().__init__(_MESSAGES[self.code])


@dataclass(frozen=True)
class DraftSource:
    source_path: Path = field(repr=False)
    sha256: str
    party_count: int


class DraftRuntime:
    """One new SDL child; finish after natural exit while its lease is held."""

    def __init__(self, installation, private_root):
        if not isinstance(installation, GameInstallation):
            raise DraftRuntimeError("invalid_configuration")
        self.installation = installation
        self.directory = Path(private_root).resolve() / "drafts" / str(uuid4())
        self.save_path = self.directory / "character.sav"
        self._entered = self._active = False
        self._process = None
        self.result = None

    def _verify(self):
        try:
            self.installation.verify()
            return self.installation.bundle.verify()[0]
        except Exception:
            raise DraftRuntimeError("installation_changed") from None

    @asynccontextmanager
    async def open(self):
        if self._entered:
            raise DraftRuntimeError("draft_used")
        self._entered = True
        executable = self._verify()
        try:
            rom_path = Path(self.installation.rom_path).resolve()
            script = self.directory / "draft.lua"
            _check_native_paths(executable, rom_path, self.save_path, self.directory, script)
            self.directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.directory.mkdir(mode=0o700, exist_ok=False)
            with MirrorLease(self.save_path):
                _atomic(script, DRAFT_SCRIPT.encode("ascii"))
                _atomic(self.directory / "draft-intent.json", _json_bytes(dict(
                    format="emerald-new-character-draft-v1",
                    build_id=self.installation.rom_sha256,
                    manifest_sha256=self.installation.manifest_sha256)))
                executable = self._verify()
                _check_native_paths(executable, rom_path, self.save_path, self.directory, script)
                log_path = self.directory / "runtime.log"
                options = dict(cwd=self.directory, stdin=asyncio.subprocess.DEVNULL)
                if os.name == "nt":
                    options["creationflags"] = subprocess.CREATE_NO_WINDOW
                with log_path.open("xb") as log:
                    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                        str(executable), "--multiplayer-script", str(script),
                        "--multiplayer-save", str(self.save_path), str(rom_path),
                        stdout=log, stderr=log, **options))
                    try:
                        self._process, cancelled = await _finish_even_if_cancelled(spawn)
                        if cancelled:
                            raise asyncio.CancelledError()
                        self._active = True
                        yield RunningGame(self._process, None, log_path)
                    finally:
                        self._active = False
                        if self._process is not None:
                            _, cancelled = await _finish_even_if_cancelled(
                                asyncio.create_task(_stop(self._process)))
                            if cancelled:
                                raise asyncio.CancelledError()
        except asyncio.CancelledError:
            raise
        except DraftRuntimeError:
            raise
        except PlayerRuntimeError as error:
            raise DraftRuntimeError("runtime_path" if error.code == "runtime_path" else "draft_failed") from None
        except Exception:
            raise DraftRuntimeError("draft_failed") from None

    def finish(self):
        """Return a source only after a normal exit and native Save validation.

        The caller exits open() before selecting this file for separate host
        approval. A receipt does not enroll, assign IDs or authorize normal play.
        """
        if not self._active:
            raise DraftRuntimeError("draft_closed")
        if self._process.returncode is None:
            raise DraftRuntimeError("game_running")
        if self._process.returncode != 0:
            raise DraftRuntimeError("game_failed")
        if self.result is not None:
            raise DraftRuntimeError("draft_finished")
        if not self.save_path.exists():
            raise DraftRuntimeError("save_required")
        try:
            if self.save_path.is_symlink() or not self.save_path.is_file():
                raise ValueError()
            with self.save_path.open("rb") as source:
                payload = source.read(MAX_CONTAINER_SIZE + 1)
            snapshot = inspect_flash(payload, save_profile=LAYOUT_ID)
            extract_source_inventory(snapshot)
        except Exception:
            raise DraftRuntimeError("invalid_source") from None
        if not 1 <= snapshot.metadata.party_count <= 6:
            raise DraftRuntimeError("starter_required")
        result = DraftSource(self.save_path, hashlib.sha256(payload).hexdigest(),
                             snapshot.metadata.party_count)
        try:
            _atomic(self.directory / "draft-completed.json", _json_bytes(dict(
                format="emerald-new-character-source-v1", build_id=self.installation.rom_sha256,
                manifest_sha256=self.installation.manifest_sha256, sha256=result.sha256,
                party_count=result.party_count)))
        except Exception:
            raise DraftRuntimeError("draft_failed") from None
        self.result = result
        return result
