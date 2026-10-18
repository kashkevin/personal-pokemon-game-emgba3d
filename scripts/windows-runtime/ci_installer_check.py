"""Installation check for EmeraldTogether-Setup-<version>.exe on a Windows runner (CI only).

    python ci_installer_check.py --setup EmeraldTogether-Setup-X.exe --hashes package-hashes.json \\
        --work <new folder> [--expect-shell] [--seconds 20]

Runs, in order, and fails on the first thing that is wrong:

  1. a temporary player profile: LOCALAPPDATA points into --work for everything this check starts,
     and a sentinel file is planted in <profile>\\PokemonPrivate - the runner's real profile is
     never used for player data;
  2. silent install into <work>\\EmeraldTogether
     (/VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER /NORESTART /DIR=... /LOG=...);
  3. every installed file matches package-hashes.json (only Inno Setup's own unins000.* may be
     extra), and the Start menu shortcut exists;
  4. the installed EmeraldTogether.exe starts and stays up for --seconds; with --expect-shell (the
     full package) exactly one child runs the game's in-game menu (`--shell`); the launcher made its
     private folder in the temporary profile;
  5. silent upgrade/repair over it: a stray library planted in the game folder is removed, a deleted
     file comes back, and the files match again;
  6. silent uninstall: the program files, shortcut and uninstall entry are gone, and the planted
     sentinel and the launcher's private folder are still there, unchanged.

It refuses to run if EmeraldTogether is already installed for this Windows user (it would replace
that installation). Writes <work>\\installer-check.json and the Setup/uninstall logs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

APP_GUID = "CAC8954B-B6DB-4E29-AD98-412B39D18856"     # installer/EmeraldTogether.iss AppId
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{" + APP_GUID + "}_is1"
_INNO_FILES = re.compile(r"unins\d{3}\.(?:exe|dat|msg)")


class CheckFailed(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailed(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_installed(directory, hashes):
    """Problems (empty when good) between an installed folder and package-hashes.json."""
    directory = Path(directory)
    problems = []
    for name, digest in sorted(hashes.items()):
        path = directory / name
        if not path.is_file():
            problems.append(f"missing: {name}")
        elif sha(path) != digest:
            problems.append(f"changed: {name}")
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            name = path.relative_to(directory).as_posix()
            if name not in hashes and not _INNO_FILES.fullmatch(name):
                problems.append(f"unexpected: {name}")
    return problems


class Windows:
    """The real system calls; tests substitute a fake with the same methods."""

    def run(self, command, timeout):
        return subprocess.run(command, timeout=timeout, check=False).returncode

    def start(self, command, env, cwd):
        return subprocess.Popen(command, env=env, cwd=cwd)

    def shell_children(self, pid):
        script = (f"@(Get-CimInstance Win32_Process -Filter 'ParentProcessId={int(pid)}' | "
                  "Where-Object { $_.CommandLine -like '*--shell*' }).Count")
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=60, check=False)
        return int(result.stdout.strip() or 0)

    def stop_tree(self, pid):
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=60, check=False)

    def installed(self):
        import winreg
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY))
            return True
        except OSError:
            return False

    def start_menu_shortcut(self):
        return Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/EmeraldTogether.lnk"

    def sleep(self, seconds):
        time.sleep(seconds)


def check(setup, hashes, work, *, expect_shell=False, seconds=20, system=None, log=print):
    system = system or Windows()
    setup, work = Path(setup).resolve(), Path(work).resolve()
    hashes = json.loads(Path(hashes).read_text(encoding="utf-8"))
    report = dict(format="emerald-installer-check-v1", setup=setup.name, setup_sha256=sha(setup), steps=[])
    require(not system.installed(), "EmeraldTogether is already installed for this Windows user; "
                                    "this check would replace it, so it does not run here")
    work.mkdir(parents=True, exist_ok=False)
    try:
        _check(setup, hashes, work, expect_shell, seconds, system, log, report)
        report["result"] = "passed"
    except CheckFailed as error:
        report["result"] = "failed: " + str(error)
        raise
    finally:
        (work / "installer-check.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _check(setup, hashes, work, expect_shell, seconds, system, log, report):

    def step(name, **details):
        report["steps"].append(dict(step=name, **details))
        log(f"ok: {name}" + (f" {details}" if details else ""))

    profile = work / "LocalAppData"
    data = profile / "PokemonPrivate"
    data.mkdir(parents=True)
    sentinel = data / "installer-check-sentinel.txt"
    sentinel_text = "planted before install " + secrets.token_hex(16) + "\n"
    sentinel.write_text(sentinel_text, encoding="utf-8")
    env = dict(os.environ, LOCALAPPDATA=str(profile))
    target = work / "EmeraldTogether"
    step("temporary profile", localappdata=str(profile))

    def install(label):
        code = system.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/CURRENTUSER", "/NORESTART",
                           f"/DIR={target}", f"/LOG={work / (label + '.log')}"], timeout=900)
        require(code == 0, f"{label}: Setup exited with code {code}")
        problems = verify_installed(target, hashes)
        require(not problems, f"{label}: installed files differ from package-hashes.json: {problems[:20]}")
        require(system.installed(), f"{label}: no uninstall entry for this user")
        require(system.start_menu_shortcut().is_file(), f"{label}: no Start menu shortcut")
        require(sentinel.read_text(encoding="utf-8") == sentinel_text, f"{label}: the player's data changed")
        step(label, files=len(hashes))

    install("install")

    process = system.start([str(target / "EmeraldTogether.exe")], env, str(target))
    try:
        system.sleep(seconds)
        require(process.poll() is None, f"the installed EmeraldTogether.exe exited early with code {process.poll()}")
        shells = system.shell_children(process.pid)
        if expect_shell:
            require(shells == 1, f"expected exactly one in-game menu process (game --shell), found {shells}")
        step("start", seconds=seconds, menu_processes=shells)
    finally:
        system.stop_tree(process.pid)
        system.sleep(3)                                   # let the stopped processes release their files
    require((data / "launcher").is_dir(), "the launcher did not use the temporary profile's PokemonPrivate folder")
    kept = sorted(path.relative_to(data).as_posix() for path in data.rglob("*") if path.is_file())

    runtime = next(path.parent for path in target.rglob("runtime.json"))
    stray = runtime / "stray-from-an-old-version.dll"
    stray.write_bytes(b"left behind by an earlier version")
    removed = target / "README.txt"
    removed.unlink()
    install("repair")
    require(not stray.exists(), "repair kept a file from the old installation in the game folder")

    uninstaller = target / "unins000.exe"
    require(uninstaller.is_file(), "no uninstaller in the installation")
    code = system.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                       f"/LOG={work / 'uninstall.log'}"], timeout=600)
    require(code == 0, f"the uninstaller exited with code {code}")
    # The uninstaller hands over to a copy of itself and returns at once: wait for it to finish.
    for _ in range(180):
        if not uninstaller.exists() and not system.installed():
            break
        system.sleep(1)
    left = sorted(path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()) \
        if target.exists() else []
    require(not left, f"program files remain after uninstalling: {left[:20]}")
    require(not system.installed(), "the uninstall entry remains")
    require(not system.start_menu_shortcut().exists(), "the Start menu shortcut remains")
    require(sentinel.read_text(encoding="utf-8") == sentinel_text, "uninstalling changed or removed the player's data")
    after = sorted(path.relative_to(data).as_posix() for path in data.rglob("*") if path.is_file())
    require(after == kept, f"uninstalling removed player data: {sorted(set(kept) - set(after))}")
    step("uninstall", player_files_kept=len(after))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--setup", type=Path, required=True)
    parser.add_argument("--hashes", type=Path, required=True, help="package-hashes.json of the same build")
    parser.add_argument("--work", type=Path, required=True, help="a new folder")
    parser.add_argument("--expect-shell", action="store_true", help="full package: the in-game menu must start")
    parser.add_argument("--seconds", type=int, default=20)
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("the installation check runs on Windows")
    try:
        check(args.setup, args.hashes, args.work, expect_shell=args.expect_shell, seconds=args.seconds)
    except CheckFailed as error:
        print(f"installation check failed: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
