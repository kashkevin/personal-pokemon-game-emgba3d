"""Build a private Windows onedir launcher from explicit trusted release pins.

No ROM, invitation, world database or player save is copied into the package.
A native-game package runs without any game.gba: its runtime bundle pins the
game facts recorded from the ROM (collect_native_bundle.py --manifest,
game_facts.py), and this build verifies them as well as the ROM itself.
Normal packaging requires a verified import patch and production game gates.
An explicit --development-preview keeps the earlier private, import-disabled
candidate workflow available. Base dumps may be raw GBA or bounded single-GBA ZIP.

With --installer the finished folder is also packed by Inno Setup
(installer/EmeraldTogether.iss) into EmeraldTogether-Setup-<version>.exe, and
player/ receives exactly what a friend downloads: that Setup file and QUICK-START.txt.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))

from emerald_multiplayer.game_import import ImportRelease, MAX_PATCH, MAX_ROM, apply_bps, read_game_source
from emerald_multiplayer.game_patch import create_bps
from emerald_multiplayer.launcher_gui import LauncherRelease
from package_audit import audit_files, audit_tree

PYINSTALLER = "6.22.3"
INSTALLER_SCRIPT = Path(__file__).resolve().parent / "installer" / "EmeraldTogether.iss"
# Everything the package folder holds beside _internal; the installer and the player guide use them.
GUIDES = ("README.txt", "QUICK-START.txt", "RELEASE-LIMITS.txt", "HOSTING.txt")

# QUICK-START.txt lists the emulator runtime's keys. The native PC game has its
# own (engine src/platform/sdl2.c), so a native package gets them instead.
EMULATOR_CONTROLS = ("Default game controls\n\n"
    "Arrow keys: move       X: A / confirm        Z: B / back\n"
    "Enter: Start          Backspace: Select     A / S: L / R\n")
NATIVE_CONTROLS = ("Default game controls (the PC game, no emulator)\n\n"
    "Arrow keys: move       Z: A / confirm        X: B / back\n"
    "Enter: Start          Backslash (\\): Select  A / S: L / R\n"
    "F10: display & graphics settings (resolution, display mode, quality)\n"
    "F11: fullscreen\n"
    "3D game: F4 3D or classic view, F7 camera (Adventure or Diorama), F8 trees,\n"
    "F9 photo mode (arrows move, Esc back), F12 picture (saved in screenshots),\n"
    "mouse wheel or - / =: zoom, comma / period: camera tilt\n"
    "Ctrl+R: the A+B+Select+Start chord (Local Soft Reset only)\n"
    "Click the game window before using the keyboard.\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bounded_bytes(path, maximum):
    with Path(path).open("rb") as handle:
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("release input exceeds the bounded import format")
    return data


def pinned_copy(source, target, digest):
    data = Path(source).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("input changed during package collection")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def quick_start_text(template, native):
    """The quick-start guide of a package: a native game lists its own keys."""
    if not native:
        return template
    newline = "\r\n" if "\r\n" in template else "\n"
    old, new = (block.replace("\n", newline) for block in (EMULATOR_CONTROLS, NATIVE_CONTROLS))
    if template.count(old) != 1:
        raise ValueError("QUICK-START.txt no longer has the emulator controls to replace")
    return template.replace(old, new)


def readme_text(release, runtime_manifest, native, development, import_enabled):
    """README.txt beside EmeraldTogether.exe: what this package is, honestly, in a few lines."""
    lines = [f"Emerald Together - {release.version}", ""]
    lines.append(("Private development preview" if development else "Private release candidate")
                 + ": the main menu in the game's own window (Continue Adventure,")
    lines += ["Solo, Host World, Join Friend, Characters, Settings, Exit), one character that plays",
              "everywhere with its Pokemon and progress, autosave every 5 minutes (on by default) and",
              "Save now in the session window.",
              "Read QUICK-START.txt (how to play), HOSTING.txt (friends outside your home) and",
              "RELEASE-LIMITS.txt (what this build is) first.", ""]
    if native:
        lines += [f"The game is the native PC game {runtime_manifest['executable']} (no emulator). Everything it",
                  "needs is in this installation; no game.gba or other file has to be added. The game's",
                  "graphics, music and text are compiled into its program files, so this package is a",
                  "private build for friends who own Pokemon Emerald: do not publish it, upload it",
                  "publicly or give it to anyone else.", ""]
    elif import_enabled:
        lines += ["Settings, Game files installs the game from your own matching Pokemon Emerald dump.", ""]
    else:
        lines += ["Game import is unavailable: this development package has no release patch.", ""]
    lines += ["Your saves, characters and worlds are stored in %LOCALAPPDATA%\\PokemonPrivate, not in this",
              "folder. Repairing, updating or uninstalling EmeraldTogether keeps them.",
              "If a file is missing or changed, run the EmeraldTogether Setup file again: it repairs the",
              "installation. Settings, Game files checks the installed files.", "",
              "This package contains no game ROM, player save, invitation or world database.",
              "Do not send your personal invite code or invitation to another player.",
              "See _internal/package-provenance.json and _internal/notices for exact components.", "",
              "Release identity (SHA-256):",
              f"Game build: {release.rom_sha256}",
              f"Game manifest: {release.manifest_sha256}",
              f"Runtime manifest: {release.runtime_sha256}"]
    return "\n".join(lines) + "\n"


def setup_version(version):
    """The version label as it appears in the Setup file's name (no spaces or other awkward characters)."""
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", version).strip("-.")
    return value or "preview"


def setup_name(version):
    return f"EmeraldTogether-Setup-{setup_version(version)}.exe"


def installer_command(iscc, version, package, destination):
    """The Inno Setup compiler call for the finished package folder (see installer/EmeraldTogether.iss)."""
    return [str(iscc), "/Qp", f"/DAppVersion={version}", f"/DSetupVersion={setup_version(version)}",
            f"/DPackageDir={package}", f"/O{destination}", str(INSTALLER_SCRIPT)]


def build_installer(iscc, version, package, output):
    """Pack ``package`` into installer/EmeraldTogether-Setup-<version>.exe and fill player/ with the
    player-facing download: the Setup file and the package's QUICK-START.txt, nothing else."""
    destination = output / "installer"
    destination.mkdir()
    command = installer_command(iscc, version, package, destination)
    with (output / "installer.log").open("w", encoding="utf-8") as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, cwd=output)
    setup = destination / setup_name(version)
    produced = sorted(path.name for path in destination.iterdir())
    if produced != [setup.name] or setup.stat().st_size == 0:
        raise ValueError("the installer build did not produce exactly " + setup.name)
    audit_files([setup])
    player = output / "player"
    player.mkdir()
    pinned_copy(setup, player / setup.name, sha(setup))
    pinned_copy(package / "QUICK-START.txt", player / "QUICK-START.txt", sha(package / "QUICK-START.txt"))
    record = dict(format="emerald-installer-v1", version=version, setup=setup.name, setup_sha256=sha(setup),
                  setup_bytes=setup.stat().st_size, script_sha256=sha(INSTALLER_SCRIPT),
                  player_files=sorted(path.name for path in player.iterdir()))
    (output / "installer.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def collect_notices(destination):
    notices = destination / "notices"
    notices.mkdir()
    python_root = Path(sys.base_prefix)
    shutil.copyfile(python_root / "LICENSE.txt", notices / "LICENSE-Python.txt")
    # The official Windows Python LICENSE includes Tcl/Tk notices. Preserve the
    # additional installed Tk notice when available too.
    tk_notice = python_root / "tcl/tk8.6/license.terms"
    if tk_notice.is_file():
        shutil.copyfile(tk_notice, notices / "LICENSE-Tk.txt")
    versions = {}
    for name in ("cryptography", "cffi", "pycparser", "pyinstaller", "pyinstaller-hooks-contrib",
                 "altgraph", "packaging", "pefile", "pywin32-ctypes", "setuptools"):
        distribution = importlib.metadata.distribution(name)
        versions[name] = distribution.version
        for record in distribution.files or ():
            parts = Path(str(record)).parts
            if ".dist-info" not in str(record) or not any(
                    part.lower().startswith(("license", "copying", "notice")) for part in parts):
                continue
            source = distribution.locate_file(record)
            if source.is_file():
                # Keep separate distribution-relative paths to avoid overwrites.
                target = notices / name / Path(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    return versions


def build(args):
    if os.name != "nt" or importlib.metadata.version("pyinstaller") != PYINSTALLER:
        raise ValueError("build on Windows with the pinned PyInstaller version")
    output = args.output.resolve()
    if output == PROJECT or output.is_relative_to(PROJECT) or output.exists():
        raise ValueError("output must be a new private directory outside the repository")
    release = LauncherRelease(args.version, args.rom_sha256, args.manifest_sha256, args.runtime_sha256)
    if getattr(args, "installer", False) and not getattr(args, "preflight_only", False):
        iscc = getattr(args, "iscc", None) or shutil.which("iscc")
        if iscc is None or not Path(iscc).is_file():
            raise ValueError("--installer needs Inno Setup's compiler: install Inno Setup 6.3 or later or pass --iscc")
        args.iscc = Path(iscc)
    from emerald_multiplayer.launcher_session import GameInstallation
    from emerald_multiplayer.player_runtime import RuntimeBundle
    installation = GameInstallation(args.rom, args.manifest, release.rom_sha256,
                                    release.manifest_sha256, RuntimeBundle(args.runtime, release.runtime_sha256))
    installation.verify()
    runtime_manifest = json.loads((args.runtime / "runtime.json").read_bytes())
    audit_files([*(args.runtime / name for name in runtime_manifest["files"]),
                 *(args.runtime / key for key in runtime_manifest.get("data", {}))])
    game_manifest = json.loads(bounded_bytes(args.manifest, 131072))
    development = getattr(args, "development_preview", False)
    # The native PC game (collect_native_bundle.py) replaces mGBA and its Lua
    # bridge. Production gates still need the isolated trade replay worker, which
    # today runs a headless mGBA core (roadmap B4), so a native package is a
    # private development preview until a native replay exists.
    native = runtime_manifest.get("format") == "emerald-native-runtime-v1"
    if native:
        # A friend's PC has no game.gba: the package's pinned game facts stand in for it. Check them
        # the way the installed launcher will, and that they give the same build as the ROM itself.
        facts = runtime_manifest.get("game_facts")
        if facts is None:
            raise ValueError("a native package needs its game facts: collect the runtime with "
                             "collect_native_bundle.py --manifest")
        packaged = GameInstallation(args.runtime / facts, args.manifest, release.rom_sha256,
                                    release.manifest_sha256, RuntimeBundle(args.runtime, release.runtime_sha256))
        packaged.verify()
    if native and not development:
        raise ValueError("a native-game package is a --development-preview until the native trade replay worker exists")
    if not development:
        from emerald_multiplayer.player_build import require_production_player_build
        from emerald_multiplayer.reset_catalogue import require_production_reset_manifest
        from emerald_multiplayer.trade_replay_manifest import validate_trade_replay_manifest
        require_production_player_build(game_manifest, args.rom)
        require_production_reset_manifest(game_manifest, args.rom)
        if not validate_trade_replay_manifest(game_manifest, args.rom):
            raise ValueError("the production game must declare its pinned isolated trade replay entry point")
        if "emerald-trade-replay.exe" not in runtime_manifest["files"]:
            raise ValueError("the production runtime must include its pinned trusted trade replay worker")
    import_release = None
    patch = None
    patch_origin = None
    patch_options = (args.base, args.base_sha256, args.patch, args.patch_sha256)
    create_patch = getattr(args, "create_patch", False)
    if create_patch:
        if args.base is None or args.base_sha256 is None or args.patch is not None or args.patch_sha256 is not None:
            raise ValueError("create-patch requires explicit base and base SHA-256, without an external patch")
        source, target = read_game_source(args.base), bounded_bytes(args.rom, MAX_ROM)
        if hashlib.sha256(source).hexdigest() != args.base_sha256 or hashlib.sha256(target).hexdigest() != release.rom_sha256:
            raise ValueError("base or game differs from its explicit release pin")
        patch = create_bps(source, target)
        patch_digest = hashlib.sha256(patch).hexdigest()
        patch_origin = "project-linear-bps-v1"
    elif any(value is not None for value in patch_options):
        if any(value is None for value in patch_options):
            raise ValueError("import requires explicit base, base SHA-256, patch and patch SHA-256")
        source, patch = read_game_source(args.base), bounded_bytes(args.patch, MAX_PATCH)
        if hashlib.sha256(source).hexdigest() != args.base_sha256 or hashlib.sha256(patch).hexdigest() != args.patch_sha256:
            raise ValueError("base or patch differs from its explicit release pin")
        patch_digest = args.patch_sha256
        patch_origin = "explicit-pinned-patch"
    if patch is not None:
        reconstructed = apply_bps(source, patch)
        if hashlib.sha256(reconstructed).hexdigest() != release.rom_sha256:
            raise ValueError("patch does not reconstruct the verified release ROM")
        import_release = ImportRelease(args.base_sha256, patch_digest, release.rom_sha256,
                                       len(source), len(reconstructed))
    if import_release is None and not development:
        raise ValueError("an importable package requires the pinned owner's base plus --create-patch or a pinned BPS; use --development-preview only for a private candidate")
    if getattr(args, "preflight_only", False):
        print(json.dumps(dict(format="emerald-release-input-check-v1", preflight_only=True,
            package_created=False, development_preview=development, import_enabled=import_release is not None,
            rom_sha256=release.rom_sha256, manifest_sha256=release.manifest_sha256,
            runtime_sha256=release.runtime_sha256,
            base_sha256=import_release.source_sha256 if import_release else None,
            patch_sha256=import_release.patch_sha256 if import_release else None)))
        return
    output.mkdir(parents=True, exist_ok=False)
    resources = output / "resources"
    resources.mkdir()
    pinned_copy(args.manifest, resources / "game-manifest.json", release.manifest_sha256)
    runtime_record = args.runtime / "runtime.json"
    pinned_copy(runtime_record, resources / "runtime/runtime.json", release.runtime_sha256)
    record = json.loads((resources / "runtime/runtime.json").read_bytes())
    for name, digest in record["files"].items():
        pinned_copy(args.runtime / name, resources / "runtime" / name, digest)
    for key, digest in record.get("data", {}).items():
        # The 3D battle effects (runtime/battlefx); the launcher verifies each before every start.
        pinned_copy(args.runtime / key, resources / "runtime" / key, digest)
    # Verify the collected tree as well as its source. Arbitrary neighboring
    # files in a private runtime directory never enter the download.
    RuntimeBundle(resources / "runtime", release.runtime_sha256).verify()
    audit_tree(resources / "runtime")
    if import_release:
        # Keep the already verified bytes. Neither a changed source path nor a
        # second read can replace the patch after reconstruction above.
        with (resources / "game.bps").open("xb") as handle:
            handle.write(patch)
    versions = collect_notices(resources)
    source_hashes = {}
    frozen_source = output / "source/emerald_multiplayer"
    frozen_source.mkdir(parents=True)
    for path in sorted((PROJECT / "src/emerald_multiplayer").glob("*.py")):
        source_hashes[path.name] = sha(path)
        pinned_copy(path, frozen_source / path.name, source_hashes[path.name])
    entry = output / "EmeraldTogether.pyw"
    entry.write_text("from pathlib import Path\nimport sys\n"
        "from emerald_multiplayer.launcher_gui import LauncherRelease\nfrom emerald_multiplayer.shell_app import main\n"
        "from emerald_multiplayer.game_import import ImportRelease\n"
        f"release = {release!r}\nimport_release = {import_release!r}\n"
        "main(release, Path(sys._MEIPASS), import_release)\n", encoding="utf-8")
    guide_hashes = {}
    for name in GUIDES[1:]:
        source = Path(__file__).resolve().parent / "resources" / name
        guide_hashes[name] = sha(source)
        pinned_copy(source, resources / name, guide_hashes[name])
    if native:
        guide = resources / "QUICK-START.txt"
        guide.write_bytes(quick_start_text(guide.read_bytes().decode("utf-8"), True).encode("utf-8"))
        guide_hashes["QUICK-START.txt with the native game's keys"] = sha(guide)
    provenance = dict(format="emerald-launcher-private-package-v1", version=release.version,
        runtime_format=runtime_manifest.get("format"), game_executable=runtime_manifest.get("executable"),
        python=sys.version, dependencies=versions, rom_sha256=release.rom_sha256,
        manifest_sha256=release.manifest_sha256, runtime_sha256=release.runtime_sha256,
        game_facts=runtime_manifest.get("game_facts") is not None, needs_game_file=not native,
        import_enabled=import_release is not None, development_preview=development, source_sha256=source_hashes,
        import_release=(dict(source_sha256=import_release.source_sha256,
            source_size=import_release.source_size, patch_sha256=import_release.patch_sha256,
            target_sha256=import_release.target_sha256, target_size=import_release.target_size,
            patch_origin=patch_origin) if import_release else None),
        guide_sha256=guide_hashes,
        qualification="private executable only; clean-machine, gameplay and network acceptance remain separate")
    (resources / "package-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    (resources / "README.txt").write_text(readme_text(release, runtime_manifest, native, development,
                                                      import_release is not None), encoding="utf-8")
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--noupx",
        "--onedir", "--windowed", "--name", "EmeraldTogether", "--paths", str(frozen_source.parent),
        "--distpath", str(output / "dist"), "--workpath", str(output / "work"),
        "--specpath", str(output), "--add-data", str(resources) + os.pathsep + ".", str(entry)]
    with (output / "build.log").open("w", encoding="utf-8") as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, cwd=output)
    package = output / "dist/EmeraldTogether"
    # Put the readable entry instructions beside the executable as well as in
    # the frozen resource tree; friends need not discover PyInstaller internals.
    for name in GUIDES:
        pinned_copy(resources / name, package / name, sha(resources / name))
    files = {}
    package_audit = {"tree": audit_tree(package)}
    for path in sorted(package.rglob("*")):
        if not path.is_file():
            continue
        files[path.relative_to(package).as_posix()] = sha(path)
    (output / "package-hashes.json").write_text(json.dumps(files, sort_keys=True, indent=2) + "\n")
    archive = Path(shutil.make_archive(str(output / "EmeraldTogether"), "zip", root_dir=output / "dist"))
    package_audit["archive"] = audit_files([archive])
    (output / "package-audit.json").write_text(json.dumps(package_audit, sort_keys=True, indent=2) + "\n")
    installer = None
    if getattr(args, "installer", False):
        installer = build_installer(getattr(args, "iscc", None) or "iscc", release.version, package, output)
    print(json.dumps(dict(package=str(package), files=len(files), import_enabled=import_release is not None,
                         game_facts=runtime_manifest.get("game_facts") is not None,
                         executable_sha256=files["EmeraldTogether.exe"], archive_sha256=sha(archive),
                         installer=installer, package_audit=package_audit)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "manifest", "runtime", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("rom-sha256", "manifest-sha256", "runtime-sha256", "version"):
        parser.add_argument("--" + name, required=True)
    for name in ("base", "patch"):
        parser.add_argument("--" + name, type=Path)
        parser.add_argument("--" + name + "-sha256")
    parser.add_argument("--create-patch", action="store_true",
                        help="create the BPS from the explicitly pinned owner dump and verified release game")
    parser.add_argument("--development-preview", action="store_true",
                        help="explicit private candidate; permits missing import patch or production-only ROM capabilities")
    parser.add_argument("--preflight-only", action="store_true",
                        help="verify exact inputs and reconstruct BPS in memory; create no output and run no build or game")
    parser.add_argument("--installer", action="store_true",
                        help="also build EmeraldTogether-Setup-<version>.exe with Inno Setup (installer/EmeraldTogether.iss)")
    parser.add_argument("--iscc", type=Path,
                        help="the Inno Setup compiler (default: iscc on PATH, as on GitHub's windows-2022 runners)")
    build(parser.parse_args())


if __name__ == "__main__":
    main()
