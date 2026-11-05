"""PokeNav location privacy (Update 24; private by default since the owner's decision of 2026-11-05, docs/pokenav-privacy.md).

A player's precise place (map and position) reaches the other players only with the player's explicit permission. The choice is
made in the game (PokeNav > World > Players and weather > "Share my location") or with the launcher's "Share my location with other
players" checkbox; both edit the same file in the character's profile folder. Without a choice the character is private.

The companion says the choice in every presence message: ``share_location: true`` is the permission, ``false`` is not. The host is
the only party that can keep the promise, so it is the one that redacts, and it reads anything but an explicit ``true`` (``false``,
or no field at all) as private. Every other player's copy of the world view is built per viewer: a private player's place is the
unknown map ``255.255`` (the game's region map and its Players screens know it as "Location hidden"), their position is zero and
the weather at their position is dropped. The one exception is a viewer standing on the *same map*: their game draws that player's
avatar in front of them (the shared world itself), so it receives the real presence. Readouts are never exempt: the PokeNav text
(Players and weather, a player's page) says "Location hidden" to every other viewer, same map or not (``for_readout``).

What this cannot hide (stated in the doc): the host's own server process sees every presence (it is the authority; it shows them to
nobody, its operator's own game included); a player on the same map sees your avatar, and that game's own screens built from the
avatar's data (the PokeNav map's marker, the game's Players screen) place you on the map you both stand on.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HIDDEN_GROUP = 255
HIDDEN_NUMBER = 255
HIDDEN_PLACE = "Location hidden"
# Who another player sees battling a World Event when the one battling it keeps their place private: an id no player has (the
# claim itself still shows, so their game knows the Pokemon is taken).
SOMEBODY = "00000000-0000-0000-0000-000000000000"
_FORMAT = "emerald-privacy-settings-v1"
FILENAME = "privacy-settings.json"


def shares(presence: dict[str, Any] | None) -> bool:
    """Whether this presence carries the player's explicit permission to show their place to others."""
    return presence is not None and presence.get("share_location") is True


def is_hidden(presence: dict[str, Any] | None) -> bool:
    """A place this player has not given permission to show (no presence at all has no place to hide)."""
    return presence is not None and not shares(presence)


def is_redacted(presence: dict[str, Any] | None) -> bool:
    return is_hidden(presence) and (presence["map_group"], presence["map_number"]) == (HIDDEN_GROUP, HIDDEN_NUMBER)


def redact(presence: dict[str, Any] | None, viewer_presence: dict[str, Any] | None, *, own: bool = False) -> dict[str, Any] | None:
    """The presence of a player as one viewer's game may receive it (the viewer on the same map gets it: the avatar)."""
    if not is_hidden(presence) or own:
        return presence
    if viewer_presence is not None and (viewer_presence["map_group"], viewer_presence["map_number"]) == (
            presence["map_group"], presence["map_number"]):
        return presence
    result = {key: value for key, value in presence.items() if key != "weather"}
    result.update(map_group=HIDDEN_GROUP, map_number=HIDDEN_NUMBER, x=0, y=0, elevation=0)
    return result


def for_readout(presence: dict[str, Any] | None, *, own: bool = False) -> dict[str, Any] | None:
    """The presence a place *readout* (the PokeNav text) for another player is built from: no same-map exception."""
    return redact(presence, None, own=own)


def load(directory) -> bool:
    """Whether this character shares their location.

    No file means no (the default since 2026-11-05: a player who never chose is private). Migration: every file the earlier builds
    wrote was the player's own choice (the only writer was the PokeNav toggle, never a default), so a stored ``true`` (sharing
    turned off and on again) is kept as the explicit permission it was, and a stored ``false`` stays private. A file that cannot be
    read means no: a privacy setting that fails open would share what the player asked to keep."""
    try:
        raw = (Path(directory) / FILENAME).read_bytes()
    except OSError:          # missing (never chosen) or unreadable: private either way
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
    """Keep the player's own choice (only ever called for a choice the player made)."""
    from .live_checkpoint import _atomic, _json_bytes
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    _atomic(directory / FILENAME, _json_bytes(dict(format=_FORMAT, share_location=bool(share))))
