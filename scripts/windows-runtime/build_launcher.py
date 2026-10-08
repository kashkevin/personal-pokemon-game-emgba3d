"""Build a private Windows onedir launcher from explicit trusted release pins.

No ROM, invitation, world database or player save is copied into the package.
A patch is optional for a clearly labelled development package; enabling import
requires both an explicitly supplied owner's base dump and a verified BPS patch.
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

from emerald_multiplayer.game_import import ImportRelease, MAX_PATCH, MAX_ROM, apply_bps
from emerald_multiplayer.launcher_gui import LauncherRelease
from package_audit import audit_files, audit_tree

PYINSTALLER = "6.22.3"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
    import_release = None
    patch_options = (args.base, args.base_sha256, args.patch, args.patch_sha256)
    if any(value is not None for value in patch_options):
        if any(value is None for value in patch_options):
            raise ValueError("import requires explicit base, base SHA-256, patch and patch SHA-256")
        if args.base.stat().st_size > MAX_ROM or args.patch.stat().st_size > MAX_PATCH:
            raise ValueError("base or patch exceeds the bounded import format")
        source, patch = args.base.read_bytes(), args.patch.read_bytes()
        if hashlib.sha256(source).hexdigest() != args.base_sha256 or hashlib.sha256(patch).hexdigest() != args.patch_sha256:
            raise ValueError("base or patch differs from its explicit release pin")
        reconstructed = apply_bps(source, patch)
        if hashlib.sha256(reconstructed).hexdigest() != release.rom_sha256:
            raise ValueError("patch does not reconstruct the verified release ROM")
        import_release = ImportRelease(args.base_sha256, args.patch_sha256, release.rom_sha256,
                                       len(source), len(reconstructed))
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
        pinned_copy(args.patch, resources / "game.bps", import_release.patch_sha256)
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
        python=sys.version, dependencies=versions, rom_sha256=release.rom_sha256,
        manifest_sha256=release.manifest_sha256, runtime_sha256=release.runtime_sha256,
        import_enabled=import_release is not None, source_sha256=source_hashes,
        guide_sha256=guide_hashes,
        qualification="private executable only; clean-machine, gameplay and network acceptance remain separate")
    (resources / "package-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    (resources / "README.txt").write_text(
        "Emerald Together - " + release.version + "\n\n"
        "Private development preview: Host Game / Join Game, local character setup,\n"
        "autosave every 5 minutes (on by default), and launcher Save now.\n"
        "Your character's autosave toggle is remembered on this PC.\n"
        "Read QUICK-START.txt and RELEASE-LIMITS.txt before playing.\n"
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
    build(parser.parse_args())


if __name__ == "__main__":
    main()
