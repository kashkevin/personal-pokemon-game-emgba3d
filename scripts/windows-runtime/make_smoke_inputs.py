"""Synthetic, asset-free inputs for the packaging smoke test.

Writes the files the real pipeline takes from the engine build, but with stand-ins
that contain no game data, so the Windows packaging steps (collect_native_bundle.py,
build_launcher.py, PyInstaller, the package audit, the Inno Setup installer, starting the
frozen and the installed launcher) can be proven on any runner without the private engine,
ROM, base dump or sprite pack:

  pokeemerald-mp-diorama.exe   a copy of the given executable (CI passes python.exe)
  pokeemerald-mp.exe           another copy: the Classic 2D game's stand-in
  SDL2.dll                     placeholder bytes
  pokedev.gba                  a few KiB of text; only its game facts enter the package
  manifest.json                identity of that file in the real manifest format
  battlefx/                    stand-ins for the 3D battle effects folder (a few lines of text)

The manifest passes the companion's own verify_rom_manifest. The result is a package that
cannot play anything; it proves the pipeline only.

    python make_smoke_inputs.py --exe C:\\Python314\\python.exe --output inputs
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from emerald_multiplayer.companion import ABI_VERSION, BASELINE_RULESET, MAILBOX_SIZE  # noqa: E402

FIXTURE = (b"EMERALD TOGETHER CI SMOKE FIXTURE - NOT A GAME - NO COPYRIGHTED DATA\n") * 64


def make(exe: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(exe, output / "pokeemerald-mp-diorama.exe")
    shutil.copyfile(exe, output / "pokeemerald-mp.exe")  # stands in for the Classic 2D game
    (output / "SDL2.dll").write_bytes(b"smoke-test placeholder, not SDL\n")
    (output / "pokedev.gba").write_bytes(FIXTURE)
    manifest = dict(abi_version=ABI_VERSION, mailbox_size=MAILBOX_SIZE, mailbox_address=0x02000000,
                    rom_sha256=hashlib.sha256(FIXTURE).hexdigest(), rom_crc32=f"{zlib.crc32(FIXTURE) & 0xFFFFFFFF:08x}",
                    rom_size=len(FIXTURE), ruleset_id=BASELINE_RULESET, engine_commit="smoke-test")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    effects = output / "battlefx"
    (effects / "shaders").mkdir(parents=True)
    (effects / "bfx_core.js").write_text("// smoke-test placeholder, not the effect core\n", encoding="utf-8")
    (effects / "bfx_moves.json").write_text("{}\n", encoding="utf-8")
    (effects / "settings.cfg").write_text("# smoke-test placeholder\n", encoding="utf-8")
    (effects / "shaders/card.frag").write_text("// smoke-test placeholder\n", encoding="utf-8")
    from emerald_multiplayer.companion import verify_rom_manifest
    verify_rom_manifest(output / "pokedev.gba", output / "manifest.json")
    return dict(directory=str(output), rom_sha256=manifest["rom_sha256"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="a new directory")
    args = parser.parse_args()
    print(json.dumps(make(args.exe, args.output)))


if __name__ == "__main__":
    main()
