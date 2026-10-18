"""Check an installed EmeraldTogether package and explain any problem in plain English.

``check_installation(installation)`` looks at every file the package pins - the game manifest,
the runtime record (runtime.json), each game file it lists (the game programs, SDL2.dll, the
battle picture pack, the game facts) - and, for an installation that uses the player's own
game.gba instead of game facts, that file. It never raises, never starts anything and never
writes: the menu calls it and shows ``report.text()`` or each problem's title, message and steps.

The problem codes are stable identifiers for the menu:

  manifest_missing, manifest_changed              game-manifest.json
  runtime_record_missing, runtime_record_changed  runtime\\runtime.json
  game_missing, game_changed                      the game program (runtime.json "executable")
  classic_game_missing, classic_game_changed      the Classic 2D game program
  sdl_missing, sdl_changed                        SDL2.dll
  sprites_missing, sprites_changed                the battle picture pack (*.ebsp)
  game_facts_missing, game_facts_changed          game-facts.json (stands in for the GBA ROM)
  battle_effects_missing, battle_effects_changed  a 3D battle effects file (runtime\\battlefx, runtime.json "data")
  runtime_file_missing, runtime_file_changed      any other pinned game file
  runtime_unlisted                                an unknown program, library or script in the game folder
  rom_missing, rom_changed                        the player's own game.gba (packages without facts)
  path_unsupported                                the installation path is too long for the game
  unverified                                      anything else the full check refused

Repairing (running the Setup file again) replaces the program files only. Saves, characters and
worlds live in %LOCALAPPDATA%\\PokemonPrivate and are never touched by Setup or the uninstaller.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

SAVES_KEPT = ("Your saves, characters and worlds are kept. They are stored separately "
              "(in %LOCALAPPDATA%\\PokemonPrivate), and neither repairing nor uninstalling removes them.")
REPAIR_STEPS = (
    "Close EmeraldTogether.",
    "Run the EmeraldTogether Setup file again (EmeraldTogether-Setup-<version>.exe, the file you installed from) "
    "and let it finish. It repairs the installation by putting back every program file.",
    "If you no longer have that file, ask the friend who shared EmeraldTogether for it again, or uninstall "
    "EmeraldTogether (Windows Settings, Apps) and install it again.",
    SAVES_KEPT,
)
ANTIVIRUS_STEP = ("If the file goes missing again after repairing, your antivirus program may have removed it. "
                  "Restore it from the antivirus quarantine, allow EmeraldTogether, and repair again.")
_MAX_FILE = 128 * 1024 * 1024


@dataclass(frozen=True)
class Problem:
    code: str
    title: str
    message: str
    steps: tuple = ()

    def text(self):
        lines = [self.title, "", self.message]
        if self.steps:
            lines += ["", "What to do:"] + [f"{number}. {step}" for number, step in enumerate(self.steps, 1)]
        return "\n".join(lines)


@dataclass(frozen=True)
class InstallationReport:
    ok: bool
    problems: tuple = ()
    uses_game_facts: bool = False

    @property
    def summary(self):
        if self.ok:
            return "EmeraldTogether is installed correctly: every game file matches this package."
        count = len(self.problems)
        return f"EmeraldTogether found {count} problem{'s' if count != 1 else ''} with its installed files."

    def text(self):
        if self.ok:
            return self.summary + "\nThis checks the files, not gameplay or your network."
        return "\n\n".join([self.summary] + [problem.text() for problem in self.problems])


# What each kind of pinned file is, in words a player knows.
_KINDS = {
    "game": ("the game program", "It is the game itself: nothing can start without it."),
    "classic_game": ("the Classic 2D game program", "It is the game in Classic 2D graphics mode."),
    "sdl": ("a file the game needs", "SDL2.dll opens the game window and plays its sound and music; "
            "the game cannot open without it."),
    "sprites": ("the battle picture pack", "It holds the Pokemon pictures shown in battles."),
    "game_facts": ("the game identity file", "It records which exact game build this package contains, "
                   "so your worlds, invitations and saves match it."),
    "runtime_file": ("a game file", "It is one of the files this package was built with."),
    "battle_effects": ("a 3D battle effects file", "The battlefx folder draws the moves' effects in 3D battles, and "
                       "EmeraldTogether checks every one of its files before starting the game."),
}


def _file_problem(kind, state, name):
    noun, why = _KINDS[kind]
    code = f"{kind}_{state}"
    if state == "missing":
        title = f"{noun[0].upper()}{noun[1:]} is missing ({name})"
        message = f"{name} is missing from the EmeraldTogether program folder. {why}"
        steps = REPAIR_STEPS + ((ANTIVIRUS_STEP,) if name.lower().endswith((".exe", ".dll")) else ())
    else:
        title = f"{noun[0].upper()}{noun[1:]} has changed ({name})"
        message = (f"{name} in the EmeraldTogether program folder is not the file this package was built with. "
                   f"It may be damaged or replaced by a different version. {why}")
        steps = REPAIR_STEPS
    return Problem(code, title, message, steps)


_FIXED = {
    "manifest_missing": ("The game description file is missing (game-manifest.json)",
                         "game-manifest.json tells EmeraldTogether which game build it runs and what that game can do "
                         "in multiplayer. It is missing from the program folder."),
    "manifest_changed": ("The game description file has changed (game-manifest.json)",
                         "game-manifest.json is not the file this package was built with, so EmeraldTogether cannot "
                         "trust what it says about the game."),
    "runtime_record_missing": ("The list of game files is missing (runtime.json)",
                               "runtime.json lists every game file with its fingerprint, so EmeraldTogether can check "
                               "them before each start. It is missing from the program folder."),
    "runtime_record_changed": ("The list of game files has changed (runtime.json)",
                               "runtime.json is not the file this package was built with, so the game files cannot be "
                               "checked."),
    "runtime_unlisted": ("An unknown program file is in the game folder",
                         "{names} {verb} in the game's folder but {verb_not} part of this package. EmeraldTogether does not "
                         "start the game next to unknown programs, libraries or scripts."),
    "path_unsupported": ("The installation folder's path is too long",
                         "Windows limits how long a file path the game can use, and this installation's folder (or "
                         "your Windows user folder) is too deep. Install EmeraldTogether in its default folder, "
                         "or another short one."),
    "unverified": ("The installed files could not be checked",
                   "EmeraldTogether could not confirm that its installed files match this package."),
}


def _fixed(code, **values):
    title, message = _FIXED[code]
    steps = REPAIR_STEPS
    if code == "path_unsupported":
        steps = ("Uninstall EmeraldTogether in Windows Settings, Apps.",
                 "Run the Setup file again and keep the folder it suggests "
                 "(%LOCALAPPDATA%\\Programs\\EmeraldTogether), or choose a shorter one.", SAVES_KEPT)
    return Problem(code, title, message.format(**values), steps)


def _rom_problem(code, importer):
    if code == "rom_missing":
        title = "Your game file is not installed (game.gba)"
        message = ("This package checks your own copy of the game, game.gba, which is not installed on this PC yet. "
                   "Current EmeraldTogether installers contain everything the game needs and do not use it.")
    else:
        title = "Your installed game file has changed (game.gba)"
        message = "The installed game.gba is not the game build this package was made for."
    if importer is not None:
        steps = ("Open Settings, Game files.",
                 "Enter the full path of your own Pokemon Emerald file. It is checked against this release and kept "
                 "only on this PC.", SAVES_KEPT)
    else:
        steps = ("Install EmeraldTogether with the Setup file your friend shared "
                 "(EmeraldTogether-Setup-<version>.exe): it needs no separate game file.", SAVES_KEPT)
    return Problem(code, title, message, steps)


def _sha(path):
    digest, size = hashlib.sha256(), 0
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            size += len(chunk)
            if size > _MAX_FILE:
                raise ValueError("file exceeds its size limit")
            digest.update(chunk)
    return digest.hexdigest()


def _bounded(path, maximum):
    with Path(path).open("rb") as source:
        data = source.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("file exceeds its size limit")
    return data


def _kind(name, record):
    if name == record.get("executable"):
        return "game"
    if name == record.get("classic_executable"):
        return "classic_game"
    if name == record.get("game_facts"):
        return "game_facts"
    if name.lower() == "sdl2.dll":
        return "sdl"
    if name.lower().endswith(".ebsp"):
        return "sprites"
    return "runtime_file"


def _check(installation, importer):
    from .companion import verify_rom_manifest
    from .player_runtime import data_parts, unlisted_data
    problems = []
    manifest_ok = False
    try:
        raw = _bounded(installation.manifest_path, 131072)
        manifest_ok = hashlib.sha256(raw).hexdigest() == installation.manifest_sha256
        if not manifest_ok:
            problems.append(_fixed("manifest_changed"))
    except FileNotFoundError:
        problems.append(_fixed("manifest_missing"))
    except (OSError, ValueError):
        problems.append(_fixed("manifest_changed"))

    bundle = installation.bundle
    root = Path(bundle.directory)
    record = None
    try:
        raw = _bounded(root / "runtime.json", 16384)
        if hashlib.sha256(raw).hexdigest() != bundle.manifest_sha256:
            problems.append(_fixed("runtime_record_changed"))
        else:
            record = json.loads(raw)
            if not isinstance(record, dict) or not isinstance(record.get("files"), dict):
                record = None
                problems.append(_fixed("runtime_record_changed"))
    except FileNotFoundError:
        problems.append(_fixed("runtime_record_missing"))
    except (OSError, ValueError):
        problems.append(_fixed("runtime_record_changed"))
    if record is not None:
        files = record["files"]
        for name, digest in sorted(files.items()):
            kind = _kind(name, record)
            try:
                actual = _sha(root / str(name))
            except FileNotFoundError:
                problems.append(_file_problem(kind, "missing", name))
                continue
            except (OSError, ValueError):
                actual = None
            if actual != digest:
                problems.append(_file_problem(kind, "changed", name))
        data = record.get("data", {})
        data = data if isinstance(data, dict) else {}
        for key, digest in sorted(data.items()):
            try:
                actual = _sha(root.joinpath(*data_parts(key)))
            except FileNotFoundError:
                problems.append(_file_problem("battle_effects", "missing", key))
                continue
            except (OSError, ValueError):
                actual = None
            if actual != digest:
                problems.append(_file_problem("battle_effects", "changed", key))
        try:
            unlisted = sorted(child.name for child in root.iterdir()
                              if child.suffix.lower() in {".exe", ".dll", ".lua"} and child.name not in files)
        except OSError:
            unlisted = []
        try:
            unlisted += unlisted_data(root, data)
        except (OSError, ValueError):
            pass                                                     # the full check below refuses it
        if unlisted:
            many = len(unlisted) > 1
            problems.append(_fixed("runtime_unlisted", names=", ".join(unlisted),
                                   verb="are" if many else "is", verb_not="are not" if many else "is not"))

    package_problem = bool(problems)
    source = Path(installation.rom_path)
    if installation.uses_game_facts:
        named = record.get("game_facts") if record is not None else None
        if record is not None and (not isinstance(named, str) or (root / named).resolve() != source.resolve()):
            # Facts count only as the file the pinned runtime record names.
            problems.append(_file_problem("game_facts", "changed", source.name))
        elif not package_problem:
            try:
                build, _ = verify_rom_manifest(source, Path(installation.manifest_path))
                if build != installation.rom_sha256:
                    problems.append(_file_problem("game_facts", "changed", source.name))
            except FileNotFoundError:
                problems.append(_file_problem("game_facts", "missing", source.name))
            except (OSError, ValueError):
                problems.append(_file_problem("game_facts", "changed", source.name))
    else:
        try:
            present = source.is_file()
        except OSError:
            present = False
        if not present:
            # A damaged package is repaired by its installer; only then does a missing ROM matter.
            if importer is not None or not package_problem:
                problems.append(_rom_problem("rom_missing", importer))
        elif manifest_ok:
            try:
                build, _ = verify_rom_manifest(source, Path(installation.manifest_path))
                if build != installation.rom_sha256:
                    problems.append(_rom_problem("rom_changed", importer))
            except (OSError, ValueError):
                problems.append(_rom_problem("rom_changed", importer))

    if not problems:
        # The same check that runs before every start, so a passing report means the game can start.
        try:
            installation.verify()
        except Exception as error:                                   # noqa: BLE001 - reported, never raised
            problems.append(_fixed("path_unsupported" if getattr(error, "code", None) == "runtime_path"
                                   else "unverified"))
    return problems


def check_installation(installation, *, importer=None):
    """Return an InstallationReport for ``installation`` (launcher_session.GameInstallation).

    ``importer`` is the package's game_import.GameImporter, if it ships one: then a missing
    game.gba is something the player can install from Settings, Game files."""
    try:
        problems = _check(installation, importer)
    except Exception:                                                # noqa: BLE001 - the menu gets a report, never a crash
        problems = [_fixed("unverified")]
    return InstallationReport(not problems, tuple(problems), bool(getattr(installation, "uses_game_facts", False)))
