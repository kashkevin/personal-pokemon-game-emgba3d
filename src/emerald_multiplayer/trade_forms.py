"""The alternate forms a world trade carries, reviewed one by one.

The exact exchange (simple-owned-party-exchange-v1, trade_eligibility.py) moves a
Pokemon's record unchanged, so a form survives a trade as it is, and the
receiving game treats it as it treats any Pokemon it holds: its own evolution
table (MS-151's trade evolution reads the form's: a Small Pumpkaboo becomes a
Small Gourgeist), its held item and moves (an Origin Giratina keeps its Griseous
Orb, a Resolute Keldeo its Secret Sword), the days a trim or an Unbound Hoopa has
left (kept in the Pokemon's own record) and its clock (a Sky Shaymin turns back at
night as it would have at home). Its internal species ID is not a National Dex
number (the engine numbers forms after 905; species_national.py), so the standard
range 1..721 leaves every form out unless it is listed here, with the standard
species whose Pokedex number it has and the label the menus show.

Reviewed (2026-11-05, every form of a Kanto-to-Kalos species in the engine pin,
docs/trade-eligibility.md): the forms such a Pokemon keeps outside battle in the
Gen 6 games, which trade there as they are:
  Rotom's five appliance forms (the Rotom Catalog, 2026-10-30)
  Unown's letters; Burmy's, Wormadam's and Mothim's cloaks; East Sea Shellos and
  Gastrodon; Blue-Striped Basculin; Deerling's and Sawsbuck's seasons; Scatterbug's,
  Spewpa's and Vivillon's patterns; Flabebe's, Floette's and Florges's colours;
  Furfrou's trims; the female Meowstic; Pumpkaboo's and Gourgeist's sizes
  Deoxys's three formes, Origin Giratina, Sky Shaymin, Arceus's 17 types, the three
  Therian Formes, Resolute Keldeo, Genesect's four drives, Unbound Hoopa
Each is its standard species in its Pokedex number (checked against the engine
pin by tests/test_trade_forms.py) and none has the engine's cannotBeTraded.
Left out: forms that exist only in battle (Mega Evolutions, Primal Reversion,
Castform's weathers, Sunshine Cherrim, Zen Darmanitan, Pirouette Meloetta, Blade
Aegislash, Active Xerneas, Complete Zygarde); forms from later games (regional
forms, Zygarde's 10% and Power Construct, Ash- and Battle Bond Greninja, Pikachu's
caps, White-Striped Basculin, Origin Dialga and Palkia); the games' untradable ones
(Black and White Kyurem, Spiky-eared Pichu, the starter Pikachu and Eevee); and
event costumes no player here can have (Cosplay Pikachu, Eternal Floette).
Scatterbug, Spewpa and Mothim are named as the game names them: their pattern or
cloak shows only on the Vivillon or Wormadam they become.
"""
from __future__ import annotations

from .species_labels import species_label as standard_label

ROTOM = 479


def _named(first, standard, names, species_name):
    """Consecutive engine IDs from `first`, one per name: (standard species, "<name> <species>")."""
    return {first + index: (standard, f"{name} {species_name}".strip()) for index, name in enumerate(names)}


_SEASONS = ("Summer", "Autumn", "Winter")
_PATTERNS = ("Polar", "Tundra", "Continental", "Garden", "Elegant", "Meadow", "Modern", "Marine", "Archipelago",
             "High Plains", "Sandstorm", "River", "Monsoon", "Savanna", "Sun", "Ocean", "Jungle", "Fancy", "Poke Ball")
_COLOURS = ("Yellow", "Orange", "Blue", "White")
_TRIMS = ("Heart", "Star", "Diamond", "Debutante", "Matron", "Dandy", "La Reine", "Kabuki", "Pharaoh")
_SIZES = ("Small", "Large", "Super")
_ARCEUS = ("Fighting", "Flying", "Poison", "Ground", "Rock", "Bug", "Ghost", "Steel", "Fire", "Water", "Grass",
           "Electric", "Psychic", "Ice", "Dragon", "Dark", "Fairy")

REVIEWED_FORMS = {
    **{1024 + index: (201, f"Unown {letter}") for index, letter in enumerate("BCDEFGHIJKLMNOPQRSTUVWXYZ!?")},
    **_named(1054, 386, ("Attack", "Defense", "Speed"), "Deoxys"),
    **_named(1057, 412, ("Sandy", "Trash"), "Burmy"),
    **_named(1059, 413, ("Sandy", "Trash"), "Wormadam"),
    1062: (422, "East Shellos"),
    1063: (423, "East Gastrodon"),
    1064: (ROTOM, "Heat Rotom"),
    1065: (ROTOM, "Wash Rotom"),
    1066: (ROTOM, "Frost Rotom"),
    1067: (ROTOM, "Fan Rotom"),
    1068: (ROTOM, "Mow Rotom"),
    1071: (487, "Origin Giratina"),
    1072: (492, "Sky Shaymin"),
    **_named(1073, 493, _ARCEUS, "Arceus"),
    1090: (550, "Blue Basculin"),
    **_named(1094, 585, _SEASONS, "Deerling"),
    **_named(1097, 586, _SEASONS, "Sawsbuck"),
    1100: (641, "Therian Tornadus"),
    1101: (642, "Therian Thundurus"),
    1102: (645, "Therian Landorus"),
    1106: (647, "Resolute Keldeo"),
    **_named(1108, 649, ("Douse", "Shock", "Burn", "Chill"), "Genesect"),
    **_named(1114, 666, _PATTERNS, "Vivillon"),
    **_named(1133, 669, _COLOURS, "Flabebe"),
    **_named(1137, 670, _COLOURS, "Floette"),
    **_named(1142, 671, _COLOURS, "Florges"),
    **_named(1146, 676, _TRIMS, "Furfrou"),
    1155: (678, "Female Meowstic"),
    **_named(1157, 710, _SIZES, "Pumpkaboo"),
    **_named(1160, 711, _SIZES, "Gourgeist"),
    1168: (720, "Unbound Hoopa"),
    1436: (414, "Mothim"),
    1437: (414, "Mothim"),
    **{1438 + index: (664, "Scatterbug") for index in range(len(_PATTERNS))},
    **{1457 + index: (665, "Spewpa") for index in range(len(_PATTERNS))},
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


def species_level_label(species, level, width, prefix=""):
    """prefix + the species' label + " Lv<level>" in at most `width` characters: a long label is shortened, never the
    level (a cut "Continental Vivillon Lv100" would read Lv10)."""
    suffix = f" Lv{level}" if level is not None else ""
    return prefix + species_label(species)[:max(0, width - len(prefix) - len(suffix))] + suffix
