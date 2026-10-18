"""Collect a private runtime bundle of the native game for the launcher (Milestone B3).

The native game (engine `Makefile_pc`: `pokeemerald-mp.exe`, or the 3D
`pokeemerald-mp-diorama.exe`) is its own bridge (`src/platform/mp_bridge.c`), so
the bundle holds the executable and SDL2.dll, and names the GBA ROM build of the
same engine source (`player_runtime.NativeGame`, KNOWN_ISSUES M1). With
--manifest it also pins `game-facts.json` (game_facts.py): the ROM's identity,
capability markers and battle-message lengths, recorded after a full check of
the ROM against that manifest, so a player's PC needs no game.gba (the native
game never reads one). Optional extra files (the host's `emerald-trade-replay.exe`
and its DLLs) are pinned with them. With --battle-effects (the engine's battlefx/
folder) the 3D battle effects go into runtime/battlefx/, every file pinned in
runtime.json "data"; the game reads them beside its executable, and without them
every move plays its GBA animation. No ROM, save or player data is copied.
Private: the executable contains game data.

    python scripts/windows-runtime/collect_native_bundle.py \\
        --game ../engine-graphics/pokeemerald-mp-diorama.exe --sdl SDL2.dll \\
        --rom ../engine/pokedev.gba --manifest manifest.json \\
        --battle-effects ../engine-graphics/battlefx --output runtime

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
from emerald_multiplayer.companion import verify_rom_manifest  # noqa: E402
from emerald_multiplayer.game_facts import FILE_NAME as FACTS, write_facts  # noqa: E402
from emerald_multiplayer.player_runtime import NativeGame, RuntimeBundle, data_parts  # noqa: E402

FORMAT = "emerald-native-runtime-v1"
EFFECTS = "battlefx"
# The files the game cannot play its 3D battle effects without (engine src/diorama/battlefx/bfx_game.c).
EFFECTS_REQUIRED = ("bfx_core.js", "bfx_moves.json", "settings.cfg")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def copy_battle_effects(source, output):
    """Copy the engine's battlefx/ folder to ``output``/battlefx; return runtime.json "data" for it."""
    source = Path(source).resolve(strict=True)
    if not source.is_dir():
        raise ValueError("--battle-effects must be the engine's battlefx folder")
    missing = [name for name in EFFECTS_REQUIRED if not (source / name).is_file()]
    if missing:
        raise ValueError(f"the battle effects folder lacks {', '.join(missing)}")
    data = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"the battle effects folder contains a link: {path}")
        if not path.is_file():
            continue
        key = "/".join((EFFECTS, *path.relative_to(source).parts))
        data_parts(key)                     # the launcher's own rules: name, depth, never a program
        target = output.joinpath(*key.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        data[key] = sha(target)
    return data


def collect(game, sdl, rom, output, extra=(), classic_game=None, manifest=None, battle_effects=None):
    """``classic_game``: the Classic 2D game (`Makefile_pc` without DIORAMA) of the same engine
    build. The launcher's Graphics mode starts it instead of ``game`` when the player chooses 2D or
    the 3D game cannot start; both share the save, the ROM pairing and the settings file.
    ``manifest``: the game manifest of ``rom``; the bundle then pins the game facts recorded from
    both (runtime.json "game_facts"), which a package needs to run without a game.gba.
    ``battle_effects``: the engine's battlefx/ folder (3D battle effects), pinned in runtime.json "data"."""
    game, sdl, rom, output = Path(game).resolve(), Path(sdl).resolve(), Path(rom).resolve(), Path(output).resolve()
    if not game.name.lower().endswith(".exe"):
        raise ValueError("the native game must be a Windows .exe")
    if classic_game is not None:
        classic_game = Path(classic_game).resolve()
        if not classic_game.name.lower().endswith(".exe") or classic_game.name == game.name:
            raise ValueError("the Classic 2D game must be a Windows .exe with its own name")
        extra = (classic_game, *extra)
    if sdl.name != "SDL2.dll":
        raise ValueError("the SDL runtime must be SDL2.dll, the name the game loads")
    if any(Path(path).suffix.lower() == ".lua" for path in extra):
        raise ValueError("a native bundle has no Lua bridge")
    if any(Path(path).name.lower() == FACTS for path in (game, sdl, *map(Path, extra))):
        raise ValueError(f"{FACTS} is written by --manifest, not copied")
    output.mkdir(parents=True, exist_ok=False)
    for path in (game, sdl, *map(Path, extra)):
        target = output / Path(path).name
        if target.exists():
            raise ValueError(f"two bundle files named {target.name}")
        shutil.copyfile(path, target)
    if manifest is not None:
        # Fully verifies the ROM against the manifest first (companion.verify_rom_manifest).
        write_facts(rom, manifest, output / FACTS)
    data = copy_battle_effects(battle_effects, output) if battle_effects is not None else None
    files = {path.name: sha(path) for path in sorted(output.iterdir()) if path.is_file()}
    if len(files) > 32:
        raise ValueError("bundle exceeds the launcher manifest's file bound")
    game_manifest = manifest
    manifest = dict(format=FORMAT, executable=game.name, rom_sha256=sha(rom), files=files)
    if classic_game is not None:
        manifest["classic_executable"] = classic_game.name
    if game_manifest is not None:
        manifest["game_facts"] = FACTS
    if data is not None:
        manifest["data"] = data
    (output / "runtime.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    pin = sha(output / "runtime.json")
    # The launcher's own check, as it will run before every start.
    bundle = RuntimeBundle(output, pin)
    executable, native = bundle.verify()
    if executable != output / game.name or native != NativeGame(manifest["rom_sha256"]):
        raise ValueError("the collected bundle does not verify as a native runtime")
    if game_manifest is not None:
        facts = bundle.game_facts_path()
        if facts != (output / FACTS).resolve() or verify_rom_manifest(facts, Path(game_manifest))[0] != manifest["rom_sha256"]:
            raise ValueError("the collected game facts do not verify against the manifest")
    if classic_game is not None:
        classic, _ = RuntimeBundle(output, pin, graphics="2d").verify()
        if classic != output / classic_game.name:
            raise ValueError("the collected bundle does not verify its Classic 2D game")
    return dict(directory=str(output), manifest_sha256=pin, rom_sha256=manifest["rom_sha256"], files=len(files),
                game_facts=game_manifest is not None, battle_effects=len(data) if data is not None else 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="the native game's .exe")
    parser.add_argument("--sdl", type=Path, required=True, help="SDL2.dll it was built against")
    parser.add_argument("--rom", type=Path, required=True, help="the GBA ROM of the same engine source (never copied)")
    parser.add_argument("--manifest", type=Path,
                        help="the ROM's game manifest: pin game-facts.json so the package needs no game.gba")
    parser.add_argument("--output", type=Path, required=True, help="a new bundle directory")
    parser.add_argument("--classic-game", type=Path, help="the Classic 2D game's .exe (same engine build)")
    parser.add_argument("--extra", type=Path, action="append", default=[],
                        help="another file to pin (e.g. emerald-trade-replay.exe); repeatable")
    parser.add_argument("--battle-effects", type=Path,
                        help="the engine's battlefx folder: the 3D battle effects (runtime/battlefx, pinned)")
    args = parser.parse_args()
    print(json.dumps(collect(args.game, args.sdl, args.rom, args.output, args.extra, args.classic_game, args.manifest,
                             args.battle_effects)))


if __name__ == "__main__":
    main()
