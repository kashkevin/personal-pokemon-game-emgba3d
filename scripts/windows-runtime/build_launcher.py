"""Build a private Windows onedir launcher from explicit trusted release pins.

No ROM, invitation, world database or player save is copied into the package.
Normal packaging requires a verified import patch and production game gates.
An explicit --development-preview keeps the earlier private, import-disabled
candidate workflow available. Base dumps may be raw GBA or bounded single-GBA ZIP.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
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
    from emerald_multiplayer.launcher_session import GameInstallation
    from emerald_multiplayer.player_runtime import RuntimeBundle
    installation = GameInstallation(args.rom, args.manifest, release.rom_sha256,
                                    release.manifest_sha256, RuntimeBundle(args.runtime, release.runtime_sha256))
    installation.verify()
    runtime_manifest = json.loads((args.runtime / "runtime.json").read_bytes())
    audit_files(args.runtime / name for name in runtime_manifest["files"])
    game_manifest = json.loads(bounded_bytes(args.manifest, 131072))
    development = getattr(args, "development_preview", False)
    # The native PC game (collect_native_bundle.py) replaces mGBA and its Lua
    # bridge. Production gates still need the isolated trade replay worker, which
    # today runs a headless mGBA core (roadmap B4), so a native package is a
    # private development preview until a native replay exists.
    native = runtime_manifest.get("format") == "emerald-native-runtime-v1"
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
        "from emerald_multiplayer.launcher_gui import LauncherRelease, main\n"
        "from emerald_multiplayer.game_import import ImportRelease\n"
        f"release = {release!r}\nimport_release = {import_release!r}\n"
        "main(release, Path(sys._MEIPASS), import_release)\n", encoding="utf-8")
    guide_hashes = {}
    for name in ("QUICK-START.txt", "RELEASE-LIMITS.txt"):
        source = Path(__file__).resolve().parent / "resources" / name
        guide_hashes[name] = sha(source)
        pinned_copy(source, resources / name, guide_hashes[name])
    provenance = dict(format="emerald-launcher-private-package-v1", version=release.version,
        runtime_format=runtime_manifest.get("format"), game_executable=runtime_manifest.get("executable"),
        python=sys.version, dependencies=versions, rom_sha256=release.rom_sha256,
        manifest_sha256=release.manifest_sha256, runtime_sha256=release.runtime_sha256,
        import_enabled=import_release is not None, development_preview=development, source_sha256=source_hashes,
        import_release=(dict(source_sha256=import_release.source_sha256,
            source_size=import_release.source_size, patch_sha256=import_release.patch_sha256,
            target_sha256=import_release.target_sha256, target_size=import_release.target_size,
            patch_origin=patch_origin) if import_release else None),
        guide_sha256=guide_hashes,
        qualification="private executable only; clean-machine, gameplay and network acceptance remain separate")
    (resources / "package-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    (resources / "README.txt").write_text(
        "Emerald Together - " + release.version + "\n\n"
        + ("Private development preview: " if development else "Importable private release candidate: ")
        + "Host Game / Join Game, local character setup,\n"
        "autosave every 5 minutes (on by default), and launcher Save now.\n"
        "Your character's autosave toggle is remembered on this PC.\n"
        "Read QUICK-START.txt and RELEASE-LIMITS.txt before playing.\n"
        + ("\nThe game is the native PC game " + runtime_manifest["executable"] + " (no emulator,\n"
           "no mGBA). It contains game data, so this package is for your own PC only.\n"
           "The launcher still checks the matching game file (game.gba of the same build)\n"
           "before every start; install it separately (see the checkpoint README).\n\n" if native else "")
        + ("Use Import my game to select your own matching dump.\n" if import_release else
           "Game import is unavailable: this development package has no release patch.\n")
        + "It contains no game ROM, player save, invitation or world database.\n"
        "Do not send your personal invitation to another player.\n"
        "See _internal/package-provenance.json and notices for exact components.\n\n"
        "Release identity (SHA-256):\n"
        f"Game: {release.rom_sha256}\n"
        f"Game manifest: {release.manifest_sha256}\n"
        f"Runtime manifest: {release.runtime_sha256}\n", encoding="utf-8")
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--noupx",
        "--onedir", "--windowed", "--name", "EmeraldTogether", "--paths", str(frozen_source.parent),
        "--distpath", str(output / "dist"), "--workpath", str(output / "work"),
        "--specpath", str(output), "--add-data", str(resources) + os.pathsep + ".", str(entry)]
    with (output / "build.log").open("w", encoding="utf-8") as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, cwd=output)
    package = output / "dist/EmeraldTogether"
    # Put the readable entry instructions beside the executable as well as in
    # the frozen resource tree; friends need not discover PyInstaller internals.
    for name in ("README.txt", "QUICK-START.txt", "RELEASE-LIMITS.txt"):
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
    print(json.dumps(dict(package=str(package), files=len(files), import_enabled=import_release is not None,
                         executable_sha256=files["EmeraldTogether.exe"], archive_sha256=sha(archive),
                         package_audit=package_audit)))


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
    build(parser.parse_args())


if __name__ == "__main__":
    main()
