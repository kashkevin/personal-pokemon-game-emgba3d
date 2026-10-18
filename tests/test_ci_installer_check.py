"""ci_installer_check.py's logic against a simulated Inno Setup (the real one runs only in the Windows CI job)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/windows-runtime"))
import ci_installer_check as check_module  # noqa: E402
from ci_installer_check import CheckFailed, check, verify_installed  # noqa: E402


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FakeProcess:
    def __init__(self, code=None):
        self.pid, self.code = 4242, code

    def poll(self):
        return self.code


class FakeWindows:
    """Setup copies the package (removing _internal first, as [InstallDelete] does), the uninstaller
    removes what Setup installed; the started launcher creates its private folder under LOCALAPPDATA."""

    def __init__(self, package, root):
        self.package, self.root = package, root
        self.is_installed = False
        self.shortcut = root / "Start Menu" / "EmeraldTogether.lnk"
        self.exit_code, self.shells, self.stopped = None, 1, []
        self.uninstall_also = None
        self.setup_extra = None

    def run(self, command, timeout):
        program = Path(command[0])
        if program.name.startswith("EmeraldTogether-Setup"):
            target = Path(next(part[5:] for part in command if part.startswith("/DIR=")))
            shutil.rmtree(target / "_internal", ignore_errors=True)
            shutil.copytree(self.package, target, dirs_exist_ok=True)
            (target / "unins000.exe").write_bytes(b"uninstaller")
            (target / "unins000.dat").write_bytes(b"log")
            if self.setup_extra:
                (target / self.setup_extra).write_bytes(b"extra")
            self.shortcut.parent.mkdir(parents=True, exist_ok=True)
            self.shortcut.write_bytes(b"lnk")
            self.is_installed = True
            return 0
        if program.name == "unins000.exe":
            target = program.parent
            for path in sorted(self.package.rglob("*"), reverse=True):
                installed = target / path.relative_to(self.package)
                if installed.is_file():
                    installed.unlink()
                elif installed.is_dir() and not any(installed.iterdir()):
                    installed.rmdir()
            (target / "unins000.dat").unlink()
            program.unlink()
            self.shortcut.unlink()
            self.is_installed = False
            if self.uninstall_also:
                self.uninstall_also()
            return 0
        raise AssertionError(command)

    def start(self, command, env, cwd):
        assert Path(command[0]).name == "EmeraldTogether.exe" and Path(command[0]).is_file()
        (Path(env["LOCALAPPDATA"]) / "PokemonPrivate" / "launcher").mkdir(parents=True, exist_ok=True)
        (Path(env["LOCALAPPDATA"]) / "PokemonPrivate" / "launcher" / "shell-prefs.json").write_text("{}")
        return FakeProcess(self.exit_code)

    def shell_children(self, pid):
        return self.shells

    def stop_tree(self, pid):
        self.stopped.append(pid)

    def installed(self):
        return self.is_installed

    def start_menu_shortcut(self):
        return self.shortcut

    def sleep(self, seconds):
        pass


class InstallerCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "dist" / "EmeraldTogether"
        (self.package / "_internal" / "runtime").mkdir(parents=True)
        for name, data in (("EmeraldTogether.exe", b"MZ launcher"), ("README.txt", b"readme"),
                           ("QUICK-START.txt", b"guide"), ("_internal/runtime/runtime.json", b"{}"),
                           ("_internal/runtime/pokeemerald-mp-diorama.exe", b"MZ game")):
            (self.package / name).write_bytes(data)
        self.hashes = self.root / "package-hashes.json"
        self.hashes.write_text(json.dumps({path.relative_to(self.package).as_posix(): sha(path)
                                           for path in self.package.rglob("*") if path.is_file()}))
        self.setup = self.root / "EmeraldTogether-Setup-Smoke-test-7.exe"
        self.setup.write_bytes(b"setup")
        self.system = FakeWindows(self.package, self.root)
        self.work = self.root / "work"

    def run_check(self, **options):
        return check(self.setup, self.hashes, self.work, system=self.system, log=lambda *_: None, **options)

    def test_install_start_repair_uninstall_keeps_player_data(self):
        report = self.run_check(expect_shell=True)
        self.assertEqual([step["step"] for step in report["steps"]],
                         ["temporary profile", "install", "start", "repair", "uninstall"])
        self.assertEqual(report["result"], "passed")
        self.assertEqual(json.loads((self.work / "installer-check.json").read_text())["result"], "passed")
        data = self.work / "LocalAppData" / "PokemonPrivate"
        self.assertTrue((data / "installer-check-sentinel.txt").is_file())
        self.assertTrue((data / "launcher" / "shell-prefs.json").is_file())
        self.assertFalse((self.work / "EmeraldTogether" / "EmeraldTogether.exe").exists())
        self.assertEqual(self.system.stopped, [4242])

    def assert_fails(self, text, **options):
        with self.assertRaises(CheckFailed) as caught:
            self.run_check(**options)
        self.assertIn(text, str(caught.exception))
        return caught.exception

    def test_refuses_to_replace_a_real_installation(self):
        self.system.is_installed = True
        self.assert_fails("already installed")
        self.assertFalse(self.work.exists())

    def test_an_uninstaller_that_deletes_player_data_fails(self):
        self.system.uninstall_also = lambda: shutil.rmtree(self.work / "LocalAppData" / "PokemonPrivate" / "launcher")
        self.assert_fails("removed player data")
        self.assertIn("failed", json.loads((self.work / "installer-check.json").read_text())["result"])

    def test_extra_files_an_early_exit_or_a_missing_menu_fail(self):
        self.system.setup_extra = "surprise.dll"
        self.assert_fails("unexpected: surprise.dll")
        shutil.rmtree(self.work)
        self.system.setup_extra, self.system.is_installed = None, False
        self.system.exit_code = 3
        self.assert_fails("exited early with code 3")
        shutil.rmtree(self.work)
        self.system.exit_code, self.system.is_installed, self.system.shells = None, False, 0
        self.assert_fails("in-game menu", expect_shell=True)
        shutil.rmtree(self.work)
        self.system.is_installed = False
        self.assertEqual(self.run_check(expect_shell=False)["result"], "passed")   # smoke: no game to host the menu

    def test_verify_installed_names_each_difference(self):
        target = self.root / "installed"
        shutil.copytree(self.package, target)
        hashes = json.loads(self.hashes.read_text())
        self.assertEqual(verify_installed(target, hashes), [])
        (target / "unins000.exe").write_bytes(b"inno")
        (target / "README.txt").write_bytes(b"changed")
        (target / "QUICK-START.txt").unlink()
        (target / "_internal" / "runtime" / "old.dll").write_bytes(b"stale")
        self.assertEqual(verify_installed(target, hashes),
                         ["missing: QUICK-START.txt", "changed: README.txt", "unexpected: _internal/runtime/old.dll"])

    def test_the_guid_is_the_installer_scripts(self):
        script = (Path(check_module.__file__).parent / "installer" / "EmeraldTogether.iss").read_text()
        self.assertIn("AppId={{" + check_module.APP_GUID + "}", script)


if __name__ == "__main__":
    unittest.main()
