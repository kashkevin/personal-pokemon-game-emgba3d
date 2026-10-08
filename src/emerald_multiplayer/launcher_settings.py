"""Private per-character launcher preferences; never canonical game state."""
from dataclasses import dataclass
import json
from pathlib import Path

from .live_checkpoint import _atomic, _json_bytes


AUTOSAVE_INTERVAL = 300
_FORMAT = "emerald-launcher-settings-v1"


class LauncherSettingsError(ValueError):
    code = "settings_unavailable"

    def __init__(self):
        super().__init__("The character's launcher settings could not be saved or read.")


@dataclass(frozen=True)
class LauncherSettings:
    autosave_enabled: bool = True

    @classmethod
    def load(cls, directory):
        try:
            with (Path(directory) / "launcher-settings.json").open("rb") as source:
                raw = source.read(4097)
            if len(raw) > 4096:
                raise ValueError()
            value = json.loads(raw)
            if (type(value) is not dict or set(value) != {"format", "autosave_enabled"}
                    or value["format"] != _FORMAT or type(value["autosave_enabled"]) is not bool):
                raise ValueError()
            return cls(value["autosave_enabled"])
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError, UnicodeError):
            raise LauncherSettingsError() from None

    def save(self, directory):
        if type(self.autosave_enabled) is not bool:
            raise LauncherSettingsError()
        try:
            directory = Path(directory)
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            _atomic(directory / "launcher-settings.json", _json_bytes(dict(
                format=_FORMAT, autosave_enabled=self.autosave_enabled)))
        except OSError:
            raise LauncherSettingsError() from None
