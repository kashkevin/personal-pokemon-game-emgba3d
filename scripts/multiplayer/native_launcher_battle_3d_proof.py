"""native_launcher_battle_proof.py on the native 3D build (DIORAMA=1, the native UI on).

The same production launcher, world creation, enrollment, Players-menu 1v1,
saves, normal close and fresh Continue as the committed proof; only the version
label and the games' settings differ: the launchers' shared game-settings.cfg
holds a light 3D configuration (640x360, render scale 50 %, shadows, lighting,
effects, details and anti-aliasing off), so two software-OpenGL games and both
launchers fit a two-core cloud workspace. Each player's character look, when
their source save has one, reaches the host as in play; the native games then
draw the other player's character in the battle (battle_looks.py).

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_battle_3d_proof.py \\
        --game ../engine/pokeemerald-mp-diorama --rom pokedev.gba --manifest manifest.json \\
        --source-a a.sav --source-b b.sav --display :97 --display :98 \\
        --output /private/multiplayer-proof/native-launcher-battle-3d-1

Set PKMN_BATTLE_SPRITES_PACK to the animated sprite pack to draw the battles
with it (the bundle holds only the executable and a placeholder SDL2.dll).
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import native_launcher_battle_proof as proof

LIGHT_3D_SETTINGS = "\n".join((
    "resolution=640x360",
    "displayMode=windowed",
    "renderScale=50",
    "shadows=off",
    "lighting=0",
    "effects=0",
    "details=0",
    "antialiasing=0",
)) + "\n"


async def run(args):
    await proof.launcher_proof(
        args, names=("Battle Host", "Battle Friend"), sources=(args.source_a, args.source_b),
        party_counts=(2, 1), match=proof.native_menu_match, version="Native 3D 1v1 proof",
        settings=LIGHT_3D_SETTINGS,
        scope="The committed native 1v1 launcher proof on the 3D build (native UI, character "
              "selection, battle looks), light game settings")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="the native 3D Linux executable, unstripped")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-a", type=Path, required=True)
    parser.add_argument("--source-b", type=Path, required=True)
    parser.add_argument("--display", action="append", required=True, help="an X display per player (twice)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--wine", type=Path, action="append", help="a Wine prefix per player: Windows clients")
    parser.add_argument("--sdl", type=Path, help="SDL2.dll for the Windows game")
    parser.add_argument("--elf", type=Path, help="the Linux build of the same engine commit (symbol sizes)")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
