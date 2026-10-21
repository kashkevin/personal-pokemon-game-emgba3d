"""Battle Tower: Legends' floor data as the app reads it (docs/battle-tower-legends.md section 7).

The engine's floor generator (``tools/tower_legends/generate.py``) writes the floors twice from one source: the game's own
compiled trainers, and the module ``emerald_multiplayer.tower_floors`` the app imports, with:

    TABLE_HASH          u32: CRC-32 of the canonical JSON's ``floors`` array (the game's TOWER_LEGENDS_TABLE_HASH)
    FLOORS              100 dicts in floor order: floor, level, kind ("regular", "boss", "special", "final"), checkpoint,
                        region, difficulty, music, intro, defeat, defeatB, victory, solo {id, name, class, pic, gender,
                        encounterMusic, ai, mons [...]} and duo [A, B] (two trainers of the same shape)
    MILESTONE_SPECIES   (species id, "SPECIES_X", "Display name", lowest legal level): the pool of floors 25, 50 and 75
    LEGENDARY_SPECIES   the same for floor 100's legendary

The host needs the hash (every solo command carries it; a game with another table refuses the battle) and the milestone
pools; the Players menu shows trainer names, regions, kinds and difficulty (never a team). The generator spells them as the
game does (a class constant such as TRAINER_CLASS_LEADER_FRLG, names in capitals, the region "kanto"); ``trainer()`` and
``region()`` give the menu's words ("Leader Brock", "Kanto"). The module is imported lazily and checked once: while it is
missing or malformed the Tower is unavailable and ``unavailable()`` says why. Tests install synthetic data (``install``)
instead of a generated module; nothing here invents floor data.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import importlib

MODULE = "emerald_multiplayer.tower_floors"
FLOORS = 100
KINDS = frozenset({"regular", "boss", "special", "final"})
CHECKPOINTS = frozenset({10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100})
CLASS_PREFIX = "TRAINER_CLASS_"


def display_class(value) -> str:
    """A trainer class as the menu names it. The generator writes the game's constant (TRAINER_CLASS_LEADER_FRLG): its
    words without the FRLG, gender and number suffixes, as the game's own name reads ("Leader", "Swimmer", "PKMN
    Breeder"; the rival class is the game's "PKMN Trainer"). Anything else (a display name) is kept as it is."""
    text = str(value or "").strip()
    if not text.startswith(CLASS_PREFIX):
        return text
    words = text[len(CLASS_PREFIX):].split("_")
    while len(words) > 1 and (words[-1] in ("FRLG", "M", "F") or words[-1].isdigit()):
        words.pop()
    if words == ["RIVAL"]:
        words = ["PKMN", "TRAINER"]
    return " ".join(word if word == "PKMN" else word.capitalize() for word in words)


def display_name(value) -> str:
    """A trainer's name as the menu writes it: the game's capitals ("BROCK") read "Brock"; a mixed-case name is kept."""
    text = str(value or "").strip()
    return text.title() if text.isupper() else text


class TowerDataError(ValueError):
    """The floor data cannot be used. ``reason`` fits a menu status line; the message says exactly what is wrong."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason


@dataclass(frozen=True)
class Species:
    species: int
    constant: str
    name: str
    min_level: int


@dataclass(frozen=True)
class TowerData:
    table_hash: int
    floors: tuple                 # the generator's 100 floor dicts, floor 1 first
    milestone_species: tuple      # Species: floors 25, 50 and 75 (no legendary or mythical)
    legendary_species: tuple      # Species: floor 100

    def floor(self, number: int) -> Mapping:
        return self.floors[number - 1]

    def trainer(self, number: int, which: str = "solo") -> str:
        """A floor's trainer as the menu names it ("Leader Brock"): the solo trainer, or "a"/"b" of the Duo pair."""
        entry = self.floor(number)
        trainer = entry["solo"] if which == "solo" else entry["duo"][0 if which == "a" else 1]
        klass = display_class(trainer.get("class"))
        name = display_name(trainer.get("name")) or "Trainer"
        return f"{klass} {name}" if klass and klass.lower() not in name.lower() else name

    def region(self, number: int) -> str:
        """A floor's region as the menu names it ("Kanto"; the generator writes "kanto")."""
        return str(self.floor(number).get("region") or "").strip().title()

    def bosses(self) -> tuple:
        """The floors that are not regular: the Gym Leaders, the specials and the final floor, in floor order."""
        return tuple(entry["floor"] for entry in self.floors if entry["kind"] != "regular")


_installed: TowerData | None = None
_loaded: TowerData | TowerDataError | None = None


def _species_pool(value, name: str) -> tuple:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise TowerDataError("Tower floor data is malformed", f"{name} must be a non-empty sequence")
    pool = []
    for entry in value:
        if (not isinstance(entry, Sequence) or isinstance(entry, (str, bytes)) or len(entry) != 4
                or type(entry[0]) is not int or not 1 <= entry[0] <= 2047
                or not isinstance(entry[1], str) or not entry[1].startswith("SPECIES_")
                or not isinstance(entry[2], str) or not entry[2]
                or type(entry[3]) is not int or not 1 <= entry[3] <= 100):
            raise TowerDataError("Tower floor data is malformed",
                                 f"{name} entries are (species 1-2047, SPECIES_X, name, lowest level 1-100): {entry!r}")
        pool.append(Species(*entry))
    if len({entry.species for entry in pool}) != len(pool):
        raise TowerDataError("Tower floor data is malformed", f"{name} names a species twice")
    return tuple(pool)


def _trainer(value, where: str) -> None:
    if not isinstance(value, Mapping) or not isinstance(value.get("name"), str) or not isinstance(value.get("class", ""), str):
        raise TowerDataError("Tower floor data is malformed", f"{where} needs a trainer with a name and a class")


def validate(table_hash, floors, milestone_species, legendary_species) -> TowerData:
    """The generator's data, checked for what the app relies on, or TowerDataError saying what is wrong."""
    if type(table_hash) is not int or not 0 <= table_hash <= 0xFFFFFFFF:
        raise TowerDataError("Tower floor data is malformed", f"TABLE_HASH must be a 32-bit integer, not {table_hash!r}")
    if not isinstance(floors, Sequence) or isinstance(floors, (str, bytes)) or len(floors) != FLOORS:
        raise TowerDataError("Tower floor data is malformed", "FLOORS must list exactly 100 floors")
    for index, entry in enumerate(floors):
        number = index + 1
        if not isinstance(entry, Mapping) or entry.get("floor") != number or type(entry.get("floor")) is not int:
            raise TowerDataError("Tower floor data is malformed", f"FLOORS[{index}] is not floor {number}")
        if entry.get("level") != number or type(entry.get("level")) is not int:
            raise TowerDataError("Tower floor data is malformed", f"floor {number}'s level is not {number}")
        if entry.get("kind") not in KINDS:
            raise TowerDataError("Tower floor data is malformed", f"floor {number} has an unknown kind {entry.get('kind')!r}")
        if entry.get("checkpoint") is not (number in CHECKPOINTS):
            raise TowerDataError("Tower floor data is malformed", f"floor {number}'s checkpoint flag disagrees with the design")
        if not isinstance(entry.get("region"), str):
            raise TowerDataError("Tower floor data is malformed", f"floor {number} has no region")
        _trainer(entry.get("solo"), f"floor {number}'s solo battle")
        duo = entry.get("duo")
        if not isinstance(duo, Sequence) or isinstance(duo, (str, bytes)) or len(duo) != 2:
            raise TowerDataError("Tower floor data is malformed", f"floor {number} needs a Duo pair")
        for which, trainer in zip("AB", duo):
            _trainer(trainer, f"floor {number}'s Duo trainer {which}")
    return TowerData(table_hash, tuple(floors), _species_pool(milestone_species, "MILESTONE_SPECIES"),
                     _species_pool(legendary_species, "LEGENDARY_SPECIES"))


def _import() -> TowerData:
    try:
        module = importlib.import_module(MODULE)
    except ModuleNotFoundError as error:
        if error.name != MODULE:
            raise TowerDataError("Tower floor data is malformed", f"{MODULE} could not be imported: {error}") from error
        raise TowerDataError("Tower floor data is missing",
                             f"{MODULE} is missing: run the engine's tools/tower_legends/generate.py") from error
    except Exception as error:  # noqa: BLE001 - any failure of the generated module is a reason, never a crash
        raise TowerDataError("Tower floor data is malformed", f"{MODULE} could not be imported: {error}") from error
    missing = [name for name in ("TABLE_HASH", "FLOORS", "MILESTONE_SPECIES", "LEGENDARY_SPECIES")
               if not hasattr(module, name)]
    if missing:
        raise TowerDataError("Tower floor data is malformed", f"{MODULE} lacks {', '.join(missing)}")
    return validate(module.TABLE_HASH, module.FLOORS, module.MILESTONE_SPECIES, module.LEGENDARY_SPECIES)


def load() -> TowerData:
    """The floor data (checked once per process), or TowerDataError: the Tower is unavailable and says why."""
    global _loaded
    if _installed is not None:
        return _installed
    if _loaded is None:
        try:
            _loaded = _import()
        except TowerDataError as error:
            _loaded = error
    if isinstance(_loaded, TowerDataError):
        raise _loaded
    return _loaded


def unavailable() -> str | None:
    """None when the floor data can be used, else the reason (a status line's 31 characters)."""
    try:
        load()
    except TowerDataError as error:
        return error.reason
    return None


def install(data: TowerData | None) -> None:
    """Tests: use this data instead of the generated module (None: back to the module)."""
    global _installed
    if data is not None and not isinstance(data, TowerData):
        raise TypeError("install a validated TowerData")
    _installed = data


def reset() -> None:
    """Forget the installed data and the module's checked result (tests)."""
    global _installed, _loaded
    _installed, _loaded = None, None
