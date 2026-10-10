"""Collect a private runtime bundle of the native game for the launcher (Milestone B3).

The native game (engine `Makefile_pc`: `pokeemerald-mp.exe`, or the 3D
`pokeemerald-mp-diorama.exe`) is its own bridge (`src/platform/mp_bridge.c`), so
the bundle holds the executable and SDL2.dll, and names the GBA ROM build of the
same engine source, which the companion verifies and which the launcher checks
before every start (`player_runtime.NativeGame`, KNOWN_ISSUES M1). Optional extra
files (the host's `emerald-trade-replay.exe` and its DLLs) are pinned with them.
No ROM, save or player data is copied. Private: the executable contains game data.

    python scripts/windows-runtime/collect_native_bundle.py \\
        --game ../engine-graphics/pokeemerald-mp-diorama.exe --sdl SDL2.dll \\
        --rom ../engine/pokedev.gba --output runtime

Prints the directory and the runtime.json pin (the release record's runtime_sha256).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from emerald_multiplayer.player_runtime import NativeGame, RuntimeBundle  # noqa: E402

FORMAT = "emerald-native-runtime-v1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def collect(game, sdl, rom, output, extra=()):
    game, sdl, rom, output = Path(game).resolve(), Path(sdl).resolve(), Path(rom).resolve(), Path(output).resolve()
    if not game.name.lower().endswith(".exe"):
        raise ValueError("the native game must be a Windows .exe")
    if sdl.name != "SDL2.dll":
        raise ValueError("the SDL runtime must be SDL2.dll, the name the game loads")
    if any(Path(path).suffix.lower() == ".lua" for path in extra):
        raise ValueError("a native bundle has no Lua bridge")
    output.mkdir(parents=True, exist_ok=False)
    for path in (game, sdl, *map(Path, extra)):
        target = output / Path(path).name
        if target.exists():
            raise ValueError(f"two bundle files named {target.name}")
        shutil.copyfile(path, target)
    files = {path.name: sha(path) for path in sorted(output.iterdir()) if path.is_file()}
    if len(files) > 32:
        raise ValueError("bundle exceeds the launcher manifest's file bound")
    manifest = dict(format=FORMAT, executable=game.name, rom_sha256=sha(rom), files=files)
    (output / "runtime.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    pin = sha(output / "runtime.json")
    # The launcher's own check, as it will run before every start.
    executable, native = RuntimeBundle(output, pin).verify()
    if executable != output / game.name or native != NativeGame(manifest["rom_sha256"]):
        raise ValueError("the collected bundle does not verify as a native runtime")
    return dict(directory=str(output), manifest_sha256=pin, rom_sha256=manifest["rom_sha256"], files=len(files))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="the native game's .exe")
    parser.add_argument("--sdl", type=Path, required=True, help="SDL2.dll it was built against")
    parser.add_argument("--rom", type=Path, required=True, help="the GBA ROM of the same engine source")
    parser.add_argument("--output", type=Path, required=True, help="a new bundle directory")
    parser.add_argument("--extra", type=Path, action="append", default=[],
                        help="another file to pin (e.g. emerald-trade-replay.exe); repeatable")
    args = parser.parse_args()
    print(json.dumps(collect(args.game, args.sdl, args.rom, args.output, args.extra)))


if __name__ == "__main__":
    main()
