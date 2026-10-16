"""Random Legendary and Mythical wild Pokemon on the host's shared spawns (Update 29).

The native game rolls one random Legendary/Mythical per random wild encounter (src/platform/mp_legend.c): exactly 1 in 6000,
one combined chance for the whole pool (not per species), the species drawn uniformly from the species whose habitat fits
the area. Connected to a world that shares wild Pokemon, the game makes no land encounters of its own, so the host makes
that roll for the shared land spawns, **when a player claims one** (not when it appears: nobody can pick a spawn for its
species, and the host alone rolls, so a reconnect or a second client cannot reroll). The Pokemon keeps the level the map's
table gave it and the shiny status it was created with. This module is the host-side port of mp_legend.c; the generated
tables (legend_pool.py) and a parity check against the native game (scripts/multiplayer/check_legend_pool.py) keep the two
equal.
"""
from __future__ import annotations

import random

from . import legend_pool as pool

# Same names as the game: MAP_TYPE_UNDERGROUND maps use the cave habitat instead of the land one.
UNDERGROUND = "MAP_TYPE_UNDERGROUND"


def area_tags(mapsec: str, map_type: str, weather: str | None) -> int:
    """Habitat tags of a land encounter area (MPLegend_AreaHabitats for WILD_AREA_LAND)."""
    underground = map_type == UNDERGROUND
    tags = pool.CAVE_DEFAULT if underground else pool.LAND_DEFAULT
    tags |= pool.LAND_TAGS.get(mapsec, 0)
    if not underground and weather is not None:
        tags |= pool.WEATHER_TAGS.get(weather, 0)
    return tags


def eligible(tags: int, night: bool) -> list[int]:
    """Species ids that may appear in an area with these tags, in the game's table order."""
    return [species for species, _name, habitats, night_only in pool.SPECIES
            if (habitats & tags) and (night or not night_only)]


def roll_hits(rng: random.Random, one_in: int = pool.ONE_IN_REGULAR) -> bool:
    """Exactly 1 in ``one_in``."""
    return rng.randrange(one_in) == 0


def pick(rng: random.Random, tags: int, night: bool) -> int | None:
    """A uniformly chosen eligible species, or None when the area has none (the encounter stays ordinary)."""
    species = eligible(tags, night)
    return rng.choice(species) if species else None
