"""No game dump, save, BIOS image, sprite pack or other proprietary game data is tracked (KNOWN_ISSUES U31-13).

Game data reaches a build or a player's PC only from the owner's own copy, outside Git (docs/local-build-inputs.md).
This test reads the index (`git ls-files`, so a staged file counts before it is committed) and fails on a tracked
file that is

* named as game data: a dump or BIOS image, a save or save state, the battle sprite pack, a ROM patch (one made from
  the owner's dump carries most of the game), the decomp's binary graphics, a built game or another executable, an
  archive, or a world or save database;
* game data by its bytes, whatever its name: a GBA, DS or Game Boy ROM header, the Nintendo logo such a header
  carries anywhere in a file, a BPS, UPS or IPS patch, an EBSP sprite pack, an archive, an executable, an SQLite
  database, or the owner's base dump itself (its SHA-256 is public, windows-package.yml BASE_ROM_SHA256);
* binary (it holds a NUL byte) and not in ALLOWED_BINARY.

ALLOWED_BINARY is every binary file the repository tracks, reviewed on 2026-11-05 together with the whole history
(every blob of every branch and tag): the eight launcher screenshots of Update 28, the project's own Tk window with
no game graphics (the header's Poke Ball is drawn by launcher_menu.py). The committed test fixtures
(tests/fixtures/compat: SQL text, JSON and a README; tests/native: C sources) are text, so none needs an exception.
Add a path only after checking that it holds no game data.

The ignore rules are checked as well: .gitignore keeps each of these kinds out of a `git add`."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

ALLOWED_BINARY = frozenset(f"docs/update28-screenshots/{name}.png" for name in (
    "01-main-menu", "02-my-worlds", "03-host-multiplayer", "04-join-friend", "05-settings-display",
    "06-settings-audio", "07-exit-confirmation", "08-running-game-page"))

FORBIDDEN_SUFFIXES = {
    # game dumps and BIOS images
    ".gba", ".agb", ".gb", ".gbc", ".nds", ".bin", ".rom", ".bios",
    # saves and save states (mGBA writes .ss0-.ss9)
    ".sav", ".srm", ".sa1", ".flash", ".eep", ".dsv", ".state", *(f".ss{n}" for n in range(10)),
    # the battle sprite pack; ROM patches
    ".ebsp", ".bps", ".ips", ".ups", ".xdelta",
    # the decomp's binary graphics
    ".1bpp", ".4bpp", ".8bpp", ".gbapal", ".lz",
    # built games and other executables (the game's executables hold its data), archives, databases
    ".exe", ".dll", ".elf", ".zip", ".7z", ".rar", ".sqlite", ".sqlite3", ".db",
}
# the native game's executables have no suffix on Linux (engine Makefile_pc)
GAME_EXECUTABLE = re.compile(r"pokeemerald(-[a-z0-9]+)*(\.exe)?")
# a save's own records beside it (".sav.checkpoint.json", ".sav.<n>.stage"): private player data
SAVE_RECORD = re.compile(r"\.sav\.")

# the first 16 bytes of the Nintendo logo: at 0x04 of a GBA ROM, at 0xC0 of a DS ROM
GBA_LOGO = bytes.fromhex("24ffae51699aa2213d84820a84e409ad")
# the first 16 bytes of the Game Boy's logo, at 0x104 of a Game Boy ROM
GB_LOGO = bytes.fromhex("ceed6666cc0d000b03730083000c000d")
MAGIC = (  # (leading bytes, what they are, only in a binary file)
    (b"BPS1", "a BPS patch", False), (b"UPS1", "a UPS patch", False), (b"PATCH", "an IPS patch", True),
    (b"EBSP", "an EBSP sprite pack", False), (b"PK\x03\x04", "a ZIP archive", False),
    (b"PK\x05\x06", "a ZIP archive", False), (b"7z\xbc\xaf\x27\x1c", "a 7z archive", False),
    (b"Rar!\x1a\x07", "a RAR archive", False), (b"\x7fELF", "an ELF executable", False),
    (b"MZ", "a Windows executable", True), (b"SQLite format 3\x00", "an SQLite database", False),
)
# the owner's Emerald USA/Europe revision 0 dump (docs/release-patch-creation.md)
BASE_DUMP_SHA256 = "a9dec84dfe7f62ab2220bafaef7479da0929d066ece16a6885f6226db19085af"

# one name per kind of game data the ignore rules must keep out of `git add`
IGNORED_SAMPLES = (
    "base-emerald.gba", "dump.agb", "game.gb", "game.gbc", "game.nds", "gba_bios.bin", "game.rom", "gba.bios",
    "game.sav", "game.srm", "game.sa1", "game.flash", "game.eep", "game.dsv", "game.ss1", "game.state",
    "battle-sprites.ebsp", "game.bps", "game.ips", "game.ups", "game.xdelta",
    "tiles.1bpp", "tiles.4bpp", "tiles.8bpp", "palette.gbapal", "tiles.4bpp.lz",
    "pokeemerald-mp.exe", "SDL2.dll", "pokedev.elf", "pokeemerald-mp", "pokeemerald-mp-diorama",
    "pokeemerald-mp-bfxtest", "pokeemerald-mp-diorama-bfxtest", "EmeraldTogether.zip", "dump.7z", "dump.rar",
    "world.sqlite3", "worlds.db", "character.sav.checkpoint.json", "inputs/manifest.json",
    "native-inputs/manifest.json",
)


def base_dump_pins():
    pins = {BASE_DUMP_SHA256}
    for workflow in (ROOT / ".github" / "workflows").glob("*.y*ml"):
        pins.update(re.findall(r"BASE_ROM_SHA256:\s*([0-9a-f]{64})", workflow.read_text(encoding="utf-8")))
    return pins


def problems(root, paths, allowed=ALLOWED_BINARY, pins=frozenset({BASE_DUMP_SHA256})):
    """Every reason a path (relative, '/'-separated) under root holds game data, as "path: reason" lines."""
    found = []
    for path in paths:
        name = path.rsplit("/", 1)[-1].lower()
        suffix = os.path.splitext(name)[1]
        if suffix in FORBIDDEN_SUFFIXES:
            found.append(f"{path}: named as game data ({suffix})")
        elif GAME_EXECUTABLE.fullmatch(name) or SAVE_RECORD.search(name):
            found.append(f"{path}: named as game data")
        file = Path(root, path)
        try:
            mode = os.lstat(file).st_mode
        except FileNotFoundError:                     # staged, then deleted from the working tree: the name only
            continue
        if not stat.S_ISREG(mode):                    # a link or a submodule: the name only
            continue
        data = file.read_bytes()
        binary = b"\x00" in data
        if data[4:20] == GBA_LOGO:
            found.append(f"{path}: a GBA ROM header")
        if data[0xC0:0xD0] == GBA_LOGO:
            found.append(f"{path}: a DS ROM header")
        if data[0x104:0x114] == GB_LOGO:
            found.append(f"{path}: a Game Boy ROM header")
        if GBA_LOGO in data or GB_LOGO in data:
            found.append(f"{path}: holds the Nintendo logo of a ROM header")
        for magic, what, needs_binary in MAGIC:
            if data.startswith(magic) and (binary or not needs_binary):
                found.append(f"{path}: {what}")
        if hashlib.sha256(data).hexdigest() in pins:
            found.append(f"{path}: the owner's base dump")
        if binary and path not in allowed:
            found.append(f"{path}: binary and not in ALLOWED_BINARY (check it holds no game data, then add it)")
    return found


def git(*args, cwd=ROOT):
    executable = shutil.which("git")
    if executable is None:
        raise unittest.SkipTest("git is not installed")
    done = subprocess.run([executable, *args], cwd=cwd, capture_output=True)
    if done.returncode == 128 and b"not a git repository" in done.stderr:
        raise unittest.SkipTest("not a git checkout")
    return done


def tracked():
    done = git("ls-files", "-z")
    if done.returncode != 0:
        raise AssertionError(done.stderr.decode(errors="replace"))
    return [path for path in done.stdout.decode("utf-8", "surrogateescape").split("\0") if path]


class NoGameDataTrackedTests(unittest.TestCase):
    def test_no_tracked_file_holds_game_data(self):
        paths = tracked()
        self.assertGreater(len(paths), 500)
        self.assertEqual(problems(ROOT, paths, pins=frozenset(base_dump_pins())), [])

    def test_every_allowed_binary_file_is_still_tracked(self):
        # an entry whose file is gone is removed from the list, so the list stays exactly what is reviewed
        self.assertEqual(sorted(ALLOWED_BINARY - set(tracked())), [])

    def test_the_ignore_rules_keep_game_data_out(self):
        done = git("check-ignore", "--no-index", "--", *IGNORED_SAMPLES)
        ignored = set(done.stdout.decode("utf-8", "surrogateescape").splitlines())
        self.assertEqual(sorted(set(IGNORED_SAMPLES) - ignored), [])
        # the ignore rules do not hide the project's own files
        kept = ("src/emerald_multiplayer/game_import.py", "scripts/windows-runtime/make_smoke_inputs.py",
                "engine-patches/phase4-save-window.patch", "docs/local-build-inputs.md",
                "tests/fixtures/compat/shared_world_u14/world.sqlite3.shared-world.sql")
        done = git("check-ignore", "--no-index", "--", *kept)
        self.assertEqual(done.stdout.decode(), "")

    def test_the_check_finds_each_kind_of_game_data(self):
        # synthetic stand-ins made in a temporary folder (never tracked): each must be refused
        def header(at, logo, size=0x200):
            data = bytearray(size)
            data[at:at + len(logo)] = logo
            return bytes(data)

        samples = {
            "renamed/rom.txt": header(4, GBA_LOGO),
            "renamed/ds.dat": header(0xC0, GBA_LOGO),
            "renamed/gameboy.dat": header(0x104, GB_LOGO),
            "renamed/inside.dat": b"\x00" * 1000 + GBA_LOGO + b"\x00" * 100,
            "renamed/patch.dat": b"BPS1" + bytes(64),
            "renamed/pack.dat": b"EBSP" + bytes(64),
            "renamed/archive.dat": b"PK\x03\x04" + bytes(64),
            "renamed/program.dat": b"MZ" + bytes(64),
            "renamed/world.dat": b"SQLite format 3\x00" + bytes(64),
            "renamed/sprite.png": b"\x89PNG\r\n\x1a\n" + bytes(64),
            "named/game.sav": b"text",
            "named/battle-sprites.ebsp": b"text",
            "named/pokeemerald-mp": b"text",
            "named/character.sav.checkpoint.json": b"{}",
            "text/notes.md": b"MZ and PATCH at the start of a text file are only words",
        }
        with tempfile.TemporaryDirectory() as root:
            for path, data in samples.items():
                Path(root, path).parent.mkdir(parents=True, exist_ok=True)
                Path(root, path).write_bytes(data)
            Path(root, "dump.raw").write_bytes(b"stand-in")
            found = problems(root, [*samples, "dump.raw"],
                             pins=frozenset({hashlib.sha256(b"stand-in").hexdigest()}))
        flagged = {line.split(":", 1)[0] for line in found}
        self.assertEqual(flagged, {*samples, "dump.raw"} - {"text/notes.md"})
        self.assertIn("renamed/rom.txt: a GBA ROM header", found)
        self.assertIn("dump.raw: the owner's base dump", found)


if __name__ == "__main__":
    unittest.main()
