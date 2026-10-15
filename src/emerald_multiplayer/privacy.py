"""PokeNav location privacy (Update 24, docs/pokenav-privacy.md).

A player may choose not to share where they are. The default is sharing. The choice is made in the game (PokeNav > World >
"Share my location") and kept in the character's profile folder; the companion sends ``share_location: false`` in its presence
messages while it is off.

The host is the only party that can keep the promise, so it is the one that redacts: every other player's copy of the world
view (the player list's presences and the PokeNav text) is built here, per viewer. A hidden player's place is the unknown map
``255.255`` (the game's region map and the Players screens know it as "Location hidden"), their position is zero and the weather
at their position is dropped. The one exception is a viewer standing on the *same map*: that player is on the screen in front
of them anyway, so nothing is hidden from them that they cannot see.

What this cannot hide (stated in the doc): the host's own machine sees every presence; a player on the same map sees you.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HIDDEN_GROUP = 255
HIDDEN_NUMBER = 255
HIDDEN_PLACE = "Location hidden"
_FORMAT = "emerald-privacy-settings-v1"
FILENAME = "privacy-settings.json"


def is_hidden(presence: dict[str, Any] | None) -> bool:
    return presence is not None and presence.get("share_location") is False


def is_redacted(presence: dict[str, Any] | None) -> bool:
    return is_hidden(presence) and (presence["map_group"], presence["map_number"]) == (HIDDEN_GROUP, HIDDEN_NUMBER)


def redact(presence: dict[str, Any] | None, viewer_presence: dict[str, Any] | None, *, own: bool = False) -> dict[str, Any] | None:
    """The presence of a player as one viewer may see it."""
    if not is_hidden(presence) or own:
        return presence
    if viewer_presence is not None and (viewer_presence["map_group"], viewer_presence["map_number"]) == (
            presence["map_group"], presence["map_number"]):
        return presence
    result = {key: value for key, value in presence.items() if key != "weather"}
    result.update(map_group=HIDDEN_GROUP, map_number=HIDDEN_NUMBER, x=0, y=0, elevation=0)
    return result


def load(directory) -> bool:
    """Whether this character shares their location. A missing file means yes (the default); a file that cannot be
    read means no: a privacy setting that fails open would share what the player asked to keep."""
    try:
        raw = (Path(directory) / FILENAME).read_bytes()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    try:
        value = json.loads(raw)
        if (type(value) is not dict or set(value) != {"format", "share_location"} or value["format"] != _FORMAT
                or type(value["share_location"]) is not bool):
            raise ValueError
        return value["share_location"]
    except (ValueError, UnicodeError):
        return False


def save(directory, share: bool) -> None:
    from .live_checkpoint import _atomic, _json_bytes
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    _atomic(directory / FILENAME, _json_bytes(dict(format=_FORMAT, share_location=bool(share))))
