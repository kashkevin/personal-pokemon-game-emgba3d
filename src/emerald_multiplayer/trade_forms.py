"""The alternate forms a world trade carries, reviewed one by one.

The exact exchange (simple-owned-party-exchange-v1, trade_eligibility.py) moves a
Pokemon's record unchanged, so a form survives a trade as it is. Its internal
species ID is not a National Dex number (the engine's include/constants/species.h
numbers forms after 1025), so the standard range 1..721 leaves every form out
unless it is listed here, with the standard species whose Pokedex number it has
and the label the menus show.

Rotom's five appliance forms (the Rotom Catalog, the owner's request of
2026-10-30): engine SPECIES_ROTOM_HEAT .. SPECIES_ROTOM_MOW. Each is Rotom (479)
in its Pokedex number, egg group, friendship base and ability; only its types,
stats and pictures differ, all the species ID's own. None has cannotBeTraded, none
evolves; a Rotom changes between them with the Rotom Catalog, outside battle.
"""
from __future__ import annotations

from .species_labels import species_label as standard_label

ROTOM = 479
REVIEWED_FORMS = {
    1064: (ROTOM, "Heat Rotom"),
    1065: (ROTOM, "Wash Rotom"),
    1066: (ROTOM, "Frost Rotom"),
    1067: (ROTOM, "Fan Rotom"),
    1068: (ROTOM, "Mow Rotom"),
}


def tradable_species(species) -> bool:
    """A standard species (1..721) or a reviewed form."""
    return type(species) is int and (1 <= species <= 721 or species in REVIEWED_FORMS)


def standard_species(species):
    """The standard species whose Pokedex number a reviewed form has; any other ID as it is."""
    return REVIEWED_FORMS[species][0] if type(species) is int and species in REVIEWED_FORMS else species


def species_label(species):
    """species_labels.species_label, with the reviewed forms by name ("Heat Rotom")."""
    if type(species) is int and species in REVIEWED_FORMS:
        return REVIEWED_FORMS[species][1]
    return standard_label(species)
