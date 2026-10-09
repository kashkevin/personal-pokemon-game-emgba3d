"""Explicit, closed, unassigned character copies for local host approval.

This is a file handoff, not enrollment or an offline canonical save export.
Only the existing host enrollment controller can assign multiplayer ownership.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import tempfile

from .checkpoint_mirror import MirrorLease
from .flash import LAYOUT_ID, MAX_CONTAINER_SIZE, inspect_flash
from .ownership import extract_source_inventory


class CharacterHandoffError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CharacterSource:
    path: Path = field(repr=False)
    sha256: str
    build_id: str
    manifest_sha256: str
    party_count: int


def _read_source(path):
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError()
        with path.open("rb") as source:
            before = os.fstat(source.fileno())
            payload = source.read(MAX_CONTAINER_SIZE + 1)
            after = os.fstat(source.fileno())
        # Refuse a changing file or a path switched while the handle was open.
        stamp = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        if stamp(before) != stamp(after) or stamp(after) != stamp(path.stat()):
            raise CharacterHandoffError("source_changed")
        snapshot = inspect_flash(payload, save_profile=LAYOUT_ID)
        extract_source_inventory(snapshot)
        if not 1 <= snapshot.metadata.party_count <= 6:
            raise CharacterHandoffError("starter_required")
        return payload, snapshot.metadata.party_count
    except CharacterHandoffError:
        raise
    except (OSError, ValueError):
        raise CharacterHandoffError("invalid_source") from None


def _installation(installation):
    from .launcher_session import GameInstallation
    try:
        if not isinstance(installation, GameInstallation):
            raise ValueError()
        installation.verify()
    except Exception:
        raise CharacterHandoffError("installation_changed") from None


def inspect_character_source(installation, source_path, *, expected=None):
    """Validate before showing Save As; optionally retain an earlier selection."""
    _installation(installation)
    try:
        path = Path(source_path).absolute()
        if path.is_symlink():
            raise CharacterHandoffError("invalid_source")
        path = path.resolve(strict=True)
        with MirrorLease(path):
            payload, party_count = _read_source(path)
        result = CharacterSource(path, hashlib.sha256(payload).hexdigest(),
            installation.rom_sha256, installation.manifest_sha256, party_count)
        if expected is not None and result != expected:
            raise CharacterHandoffError("source_changed")
        return result
    except CharacterHandoffError:
        raise
    except Exception as error:
        raise CharacterHandoffError("mirror_active" if getattr(error, "code", None) == "mirror_active"
                                    else "invalid_source") from None


def export_character_source(installation, private_root, selection, destination):
    """Publish a complete exact copy once, never overwrite a save or metadata.

    The cooperative save lease rejects a live launcher draft. Other emulators
    must also be closed by the user. No receipt grants ownership or host access.
    """
    _installation(installation)
    if (not isinstance(selection, CharacterSource)
            or selection.build_id != installation.rom_sha256
            or selection.manifest_sha256 != installation.manifest_sha256):
        raise CharacterHandoffError("source_changed")
    temporary = None
    try:
        destination = Path(destination).absolute()
        parent = destination.parent.resolve(strict=True)
        destination = parent / destination.name
        if (destination.suffix.lower() != ".sav" or destination.is_symlink()
                or destination == selection.path
                or destination.is_relative_to(Path(private_root).resolve())):
            raise CharacterHandoffError("character_destination")
        if destination.exists():
            raise CharacterHandoffError("character_exists")
        with MirrorLease(selection.path):
            payload, party_count = _read_source(selection.path)
            digest = hashlib.sha256(payload).hexdigest()
            if digest != selection.sha256 or party_count != selection.party_count:
                raise CharacterHandoffError("source_changed")
            with tempfile.NamedTemporaryFile(dir=parent, prefix=".character-", delete=False) as output:
                temporary = Path(output.name)
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            # Dialogs may stay open for minutes. Re-read under the lease before
            # publication; changed sources cannot silently replace the selection.
            if _read_source(selection.path)[0] != payload:
                raise CharacterHandoffError("source_changed")
            os.link(temporary, destination)
        return destination
    except CharacterHandoffError:
        raise
    except FileExistsError:
        raise CharacterHandoffError("character_exists") from None
    except Exception as error:
        raise CharacterHandoffError("mirror_active" if getattr(error, "code", None) == "mirror_active"
                                    else "character_destination") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
