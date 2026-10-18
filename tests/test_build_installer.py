"""build_launcher.py's package and installer outputs, from the smoke pipeline's synthetic inputs.

PyInstaller and Inno Setup only run on Windows, so the two tool calls are stood in for: the
PyInstaller stand-in lays out dist\\EmeraldTogether the way --onedir --add-data does (the frozen
exe beside _internal holding the staged resources), and the iscc stand-in writes the Setup file
the script names. Everything else - staging, pins, the game facts check, guides, hashes, the zip,
the audit, installer.json and the player folder - is the real code. The lint tests check that
installer/EmeraldTogether.iss references only files this build produces.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/windows-runtime"))
import build_launcher  # noqa: E402
import collect_native_bundle  # noqa: E402
import make_smoke_inputs  # noqa: E402

from emerald_multiplayer.installation_check import check_installation  # noqa: E402
from emerald_multiplayer.launcher_gui import LauncherRelease  # noqa: E402

VERSION = "Smoke test 7"
ISS = build_launcher.INSTALLER_SCRIPT


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def option(command, prefix):
    values = [part[len(prefix):] for part in command if part.startswith(prefix)]
    assert len(values) == 1, (prefix, command)
    return values[0]


class FakeTools:
    """Records the PyInstaller and iscc calls and produces what each would."""

    def __init__(self, iscc):
        self.iscc, self.calls = str(iscc), []

    def __call__(self, command, **options):
        self.calls.append(command)
        if command[1:3] == ["-m", "PyInstaller"]:
            dist = Path(command[command.index("--distpath") + 1]) / command[command.index("--name") + 1]
            source = Path(command[command.index("--add-data") + 1].rsplit(build_launcher.os.pathsep, 1)[0])
            assert Path(command[-1]).name == "EmeraldTogether.pyw"
            shutil.copytree(source, dist / "_internal")
            (dist / "EmeraldTogether.exe").write_bytes(b"MZ frozen launcher stand-in")
        elif command[0] == self.iscc:
            assert Path(command[-1]) == ISS and ISS.is_file()
            package = Path(option(command, "/DPackageDir="))
            assert (package / "EmeraldTogether.exe").is_file(), "iscc runs on the finished package folder"
            target = Path(option(command, "/O")) / f"EmeraldTogether-Setup-{option(command, '/DSetupVersion=')}.exe"
            target.write_bytes(b"MZ Inno Setup stand-in for " + package.name.encode())
        else:
            raise AssertionError(f"unexpected tool call {command}")
        return SimpleNamespace(returncode=0)


def notices(destination):
    (destination / "notices").mkdir()
    (destination / "notices" / "LICENSE-Python.txt").write_text("notice stand-in\n")
    return {"pyinstaller": build_launcher.PYINSTALLER}


def smoke_inputs(root, *, facts=True):
    stand_in = root / "stand-in.exe"
    stand_in.write_bytes(b"MZ smoke stand-in, never executed")
    inputs = root / "inputs"
    make_smoke_inputs.make(stand_in, inputs)
    collect_native_bundle.collect(inputs / "pokeemerald-mp-diorama.exe", inputs / "SDL2.dll", inputs / "pokedev.gba",
                                  root / "runtime", classic_game=inputs / "pokeemerald-mp.exe",
                                  manifest=inputs / "manifest.json" if facts else None,
                                  battle_effects=inputs / "battlefx")
    return inputs, root / "runtime"


def build_args(root, inputs, runtime, **changes):
    values = dict(rom=inputs / "pokedev.gba", manifest=inputs / "manifest.json", runtime=runtime,
                  output=root / "launcher", rom_sha256=sha(inputs / "pokedev.gba"),
                  manifest_sha256=sha(inputs / "manifest.json"), runtime_sha256=sha(runtime / "runtime.json"),
                  version=VERSION, base=None, base_sha256=None, patch=None, patch_sha256=None, create_patch=False,
                  development_preview=True, preflight_only=False, installer=True, iscc=root / "iscc.exe")
    values.update(changes)
    return argparse.Namespace(**values)


def run_build(args, tools):
    with patch.object(build_launcher, "os", SimpleNamespace(name="nt", pathsep=";")), \
            patch.object(build_launcher.importlib.metadata, "version", return_value=build_launcher.PYINSTALLER), \
            patch.object(build_launcher, "collect_notices", notices), \
            patch.object(build_launcher.subprocess, "run", tools):
        build_launcher.build(args)


class BuildOutputsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.inputs, cls.runtime = smoke_inputs(cls.root)
        (cls.root / "iscc.exe").write_bytes(b"compiler stand-in")
        cls.args = build_args(cls.root, cls.inputs, cls.runtime)
        cls.tools = FakeTools(cls.args.iscc)
        run_build(cls.args, cls.tools)
        cls.output = cls.args.output
        cls.package = cls.output / "dist" / "EmeraldTogether"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_the_package_has_its_game_facts_and_no_rom(self):
        hashes = json.loads((self.output / "package-hashes.json").read_text())
        self.assertIn("_internal/runtime/game-facts.json", hashes)
        self.assertIn("_internal/game-manifest.json", hashes)
        self.assertFalse([name for name in hashes if name.lower().endswith((".gba", ".sav", ".db", ".sqlite3"))])
        names = zipfile.ZipFile(self.output / "EmeraldTogether.zip").namelist()
        self.assertIn("EmeraldTogether/_internal/runtime/game-facts.json", names)
        self.assertFalse([name for name in names if name.lower().endswith(".gba")])
        provenance = json.loads((self.package / "_internal" / "package-provenance.json").read_text())
        self.assertTrue(provenance["game_facts"])
        self.assertFalse(provenance["needs_game_file"])

    def test_the_package_carries_the_pinned_battle_effects(self):
        # Without runtime/battlefx the game plays every move's GBA animation (the Windows packages before this one).
        hashes = json.loads((self.output / "package-hashes.json").read_text())
        names = zipfile.ZipFile(self.output / "EmeraldTogether.zip").namelist()
        record = json.loads((self.package / "_internal/runtime/runtime.json").read_text())
        self.assertEqual(sorted(record["data"]), ["battlefx/bfx_core.js", "battlefx/bfx_moves.json",
                                                  "battlefx/settings.cfg", "battlefx/shaders/card.frag"])
        for key, digest in record["data"].items():
            self.assertEqual(sha(self.package / "_internal/runtime" / key), digest)
            self.assertIn("_internal/runtime/" + key, hashes)
            self.assertIn("EmeraldTogether/_internal/runtime/" + key, names)

    def test_the_installed_package_verifies_without_a_game_file(self):
        release = LauncherRelease(VERSION, self.args.rom_sha256, self.args.manifest_sha256, self.args.runtime_sha256)
        private = self.root / "LocalAppData" / "PokemonPrivate" / "launcher"
        private.mkdir(parents=True, exist_ok=True)
        installation = release.installation(self.package / "_internal", private)
        self.assertTrue(installation.uses_game_facts)
        installation.verify()
        self.assertTrue(check_installation(installation).ok)
        entry = (self.output / "EmeraldTogether.pyw").read_text()
        self.assertIn(repr(release), entry)                       # the pins the frozen exe is built with

    def test_readme_and_guides_tell_the_truth(self):
        readme = (self.package / "README.txt").read_text()
        self.assertIn("no game.gba", readme)
        self.assertIn("do not publish", readme)
        self.assertIn("PokemonPrivate", readme)
        self.assertNotIn("install it separately", readme)
        for name in build_launcher.GUIDES:
            self.assertTrue((self.package / name).is_file(), name)
        guide = (self.package / "QUICK-START.txt").read_text()
        self.assertIn("Z: A / confirm", guide)                    # the native game's keys

    def test_installer_and_player_download(self):
        setup = build_launcher.setup_name(VERSION)
        self.assertEqual(setup, "EmeraldTogether-Setup-Smoke-test-7.exe")
        self.assertEqual(sorted(path.name for path in (self.output / "installer").iterdir()), [setup])
        player = sorted(path.name for path in (self.output / "player").iterdir())
        self.assertEqual(player, ["EmeraldTogether-Setup-Smoke-test-7.exe", "QUICK-START.txt"])
        self.assertEqual((self.output / "player" / "QUICK-START.txt").read_bytes(),
                         (self.package / "QUICK-START.txt").read_bytes())
        record = json.loads((self.output / "installer.json").read_text())
        self.assertEqual(record["setup"], setup)
        self.assertEqual(record["setup_sha256"], sha(self.output / "player" / setup))
        self.assertEqual(record["script_sha256"], sha(ISS))
        command = self.tools.calls[-1]
        self.assertEqual(command[0], str(self.args.iscc))
        self.assertIn(f"/DAppVersion={VERSION}", command)
        self.assertIn(f"/DPackageDir={self.package}", command)
        self.assertEqual([call[1:3] for call in self.tools.calls[:-1]], [["-m", "PyInstaller"]])

    def test_setup_versions_are_file_name_safe(self):
        for label, expected in (("Native 3D CI 41", "Native-3D-CI-41"), ("1.2.3", "1.2.3"), ("Smoke test", "Smoke-test")):
            self.assertEqual(build_launcher.setup_version(label), expected)
        self.assertNotIn(" ", build_launcher.setup_name("A b c"))

    # ---- lint: the installer script and the build agree

    def iss(self):
        return ISS.read_text(encoding="utf-8")

    def sections(self):
        current, result = None, {}
        for line in self.iss().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(";") or stripped.startswith("#"):
                continue
            if re.fullmatch(r"\[[A-Za-z]+\]", stripped):
                current = stripped[1:-1]
                result.setdefault(current, [])
            elif current is not None:
                result[current].append(stripped)
        return result

    def test_iss_references_only_files_the_build_produces(self):
        references = re.findall(r"\{#PackageDir\}\\([^\";\r\n]+)", self.iss())
        self.assertTrue(references)
        for reference in references:
            target = self.package / reference.strip().replace("\\", "/")
            if reference.strip() == "*":
                self.assertTrue(self.package.is_dir())
            else:
                self.assertTrue(target.is_file(), reference)
        sources = [line for line in self.sections()["Files"] if line.startswith("Source:")]
        self.assertTrue(sources)
        for line in sources:
            self.assertRegex(line, r'^Source: "\{#PackageDir\}\\')
        for line in self.sections().get("Icons", []) + self.sections().get("Run", []):
            for path in re.findall(r'Filename: "\{app\}\\([^"]+)"', line):
                path = path.replace("{#AppExe}", "EmeraldTogether.exe")
                self.assertTrue((self.package / path).is_file(), path)

    def test_iss_defines_come_from_the_build_or_the_script(self):
        text = self.iss()
        used = set(re.findall(r"\{#(\w+)\}", text))
        defined = set(re.findall(r"^#define (\w+)", text, re.M))
        passed = {match for part in build_launcher.installer_command("iscc", VERSION, self.package, self.output)
                  for match in re.findall(r"^/D(\w+)=", part)}
        self.assertEqual(passed, {"AppVersion", "SetupVersion", "PackageDir"})
        self.assertLessEqual(used, defined | passed)
        self.assertEqual(set(re.findall(r"^#ifndef (\w+)", text, re.M)), passed)
        self.assertIn("OutputBaseFilename=EmeraldTogether-Setup-{#SetupVersion}", text)

    def test_iss_installs_per_user_and_never_touches_player_data(self):
        setup = dict(line.split("=", 1) for line in self.sections()["Setup"])
        self.assertEqual(setup["PrivilegesRequired"], "lowest")
        self.assertEqual(setup["DefaultDirName"], "{userpf}\\{#AppName}")
        guid = re.fullmatch(r"\{\{([0-9A-F-]{36})\}", setup["AppId"]).group(1)
        self.assertIn("Uninstall\\{" + guid + "}_is1", self.iss())     # the repair notice finds the same AppId
        self.assertNotIn("UninstallDelete", self.sections())
        for line in self.sections()["InstallDelete"]:
            self.assertRegex(line, r'Name: "\{app\}\\')
        code = "\n".join(line for line in self.iss().splitlines() if not line.lstrip().startswith(";"))
        for forbidden in ("PokemonPrivate", "{localappdata}", "{userappdata}", "DelTree", "DeleteFile"):
            self.assertNotIn(forbidden, code)
        self.assertIn("desktopicon", self.sections()["Tasks"][0])
        self.assertIn("unchecked", self.sections()["Tasks"][0])
        self.assertTrue(any(line.startswith('Name: "{autoprograms}') for line in self.sections()["Icons"]))


class BuildRefusalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_a_native_runtime_without_game_facts_is_refused_before_any_build(self):
        inputs, runtime = smoke_inputs(self.root, facts=False)
        (self.root / "iscc.exe").write_bytes(b"compiler stand-in")
        args = build_args(self.root, inputs, runtime)
        tools = FakeTools(args.iscc)
        with self.assertRaisesRegex(ValueError, "needs its game facts"):
            run_build(args, tools)
        self.assertEqual(tools.calls, [])
        self.assertFalse(args.output.exists())

    def test_installer_needs_the_compiler(self):
        inputs, runtime = smoke_inputs(self.root)
        args = build_args(self.root, inputs, runtime, iscc=self.root / "missing" / "iscc.exe")
        tools = FakeTools(args.iscc)
        with patch.object(build_launcher.shutil, "which", return_value=None), \
                self.assertRaisesRegex(ValueError, "Inno Setup"):
            run_build(args, tools)
        self.assertEqual(tools.calls, [])
        self.assertFalse(args.output.exists())


if __name__ == "__main__":
    unittest.main()
