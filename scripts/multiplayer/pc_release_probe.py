"""Release one Pokemon from the PC's first box slot as a player does it, in the Classic 2D game (a step of the MS-51
real-game check: making room without saving). Standalone calibration: the game plays a copy of a save standing below a
Pokemon Center PC (make_tower_saves.py ms51-full-b), and each key of the sequence is pictured with the game's state.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime python scripts/multiplayer/pc_release_probe.py \\
        --game pokeemerald-mp --save ms51-full-b.sav --display :522 --output /private/multiplayer-proof/pc-release-1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_battle_proof import NativeProbe, game_picture, symbols_of  # noqa: E402

A, B, START, RIGHT, LEFT, UP, DOWN = 1, 2, 8, 16, 32, 64, 128
BOX_MON = 80
STORAGE_BOXES = 4          # offsetof(struct PokemonStorage, boxes) in the PC build (boxNames at 0x8344 = 4 + 14*30*80)


def box_personalities(probe, box=0, count=30):
    pointer = int.from_bytes(probe.mem("gPokemonStoragePtr", 4), "little")
    with open(f"/proc/{probe.pid}/mem", "rb", buffering=0) as memory:
        memory.seek(pointer + STORAGE_BOXES + box * 30 * BOX_MON)
        raw = memory.read(count * BOX_MON)
    return [int.from_bytes(raw[i * BOX_MON:i * BOX_MON + 4], "little") for i in range(count)]


def stored_count(probe):
    pointer = int.from_bytes(probe.mem("gPokemonStoragePtr", 4), "little")
    with open(f"/proc/{probe.pid}/mem", "rb", buffering=0) as memory:
        memory.seek(pointer + STORAGE_BOXES)
        raw = memory.read(14 * 30 * BOX_MON)
    return sum(1 for i in range(14 * 30) if raw[i * BOX_MON:i * BOX_MON + 4] != b"\0\0\0\0")


def callback2(probe, symbols):
    value = int.from_bytes(probe.mem("gMain", 8)[4:8], "little")
    names = {symbols[n][0]: n for n in ("CB2_Overworld", "CB2_PokeStorage") if n in symbols}
    return names.get(value, hex(value))


def text(probe):
    raw = probe.mem("gStringVar4", 120)
    return raw.split(b"\xff")[0].hex()[:60]


# The release, as a player presses it: face the PC, A (booted up; the PC list), A (someone's PC: accessed, the storage
# system opened; its menu), A (WITHDRAW POKEMON: the box), A on the first slot (its menu), DOWN x3 (RELEASE), A ("Release
# this POKEMON?" NO first), UP (YES), A, then A through "was released outside" / "Bye-bye", B (leave the box: "Continue
# BOX operations?"), B (NO), B (SEE YA), B (LOG OFF).
SEQUENCE = (("up", UP, 1.0), ("a-pc", A, 2.0), ("a-msg", A, 2.0), ("a-someones-pc", A, 2.5), ("a-msg2", A, 2.0),
            ("a-msg3", A, 2.0), ("a-withdraw", A, 4.0), ("a-slot", A, 2.0), ("down1", DOWN, .8), ("down2", DOWN, .8),
            ("down3", DOWN, .8), ("a-release", A, 2.0), ("up-yes", UP, .8), ("a-yes", A, 3.0), ("a-msg4", A, 2.5),
            ("a-msg5", A, 2.5), ("b-leave", B, 2.5), ("b-no", B, 3.0), ("b-seeya", B, 2.5), ("b-logoff", B, 2.5),
            ("b-more", B, 2.0))


async def release_one(probe, symbols, picture=None, record=print, sequence=SEQUENCE):
    """The sequence above; returns the stored count before and after."""
    before = stored_count(probe)
    for label, key, settle in sequence:
        await probe.press(key)
        await asyncio.sleep(settle)
        row = dict(step=label, callback2=callback2(probe, symbols), stored=stored_count(probe),
                   lock=probe.mem("sLockFieldControls", 1)[0], first=f"{box_personalities(probe, 0, 1)[0]:08x}")
        if picture is not None:
            row["picture"] = picture(label)
        record(row)
    return before, stored_count(probe)


async def main_async(args):
    out = args.output.resolve()
    if "/multiplayer-proof/" not in out.as_posix() + "/" or out.exists():
        raise SystemExit("choose a new private multiplayer-proof output directory")
    out.mkdir(parents=True)
    save = out / "game.sav"
    save.write_bytes(args.save.read_bytes())
    symbols = symbols_of(args.game)
    env = dict(os.environ, DISPLAY=args.display, SDL_AUDIODRIVER="dummy")
    log = (out / "game.log").open("wb")
    process = subprocess.Popen([str(args.game), "--save", str(save)], cwd=out, env=env, stdout=log, stderr=subprocess.STDOUT)
    probe = NativeProbe(process.pid, symbols, args.display, lambda *a, **k: None)
    rows = []
    count = [0]

    def picture(label):
        count[0] += 1
        name = f"{count[0]:02d}-{label}.png"
        game_picture(probe, out / name)
        return name

    def record(row):
        rows.append(row)
        print(json.dumps(row), flush=True)
        (out / "steps.json").write_text(json.dumps(rows, indent=2))
    try:
        await probe.boot(args.slow)
        deadline = time.monotonic() + 90
        while callback2(probe, symbols) != "CB2_Overworld" or probe.mem("sLockFieldControls", 1)[0]:
            if time.monotonic() > deadline:
                raise SystemExit("not in the field")
            await probe.press(A)
            await asyncio.sleep(2)
        await asyncio.sleep(2)
        record(dict(step="field", stored=stored_count(probe), picture=picture("field"),
                    facing=list(probe.mem("gPlayerFacingPosition", 6))))
        before, after = await release_one(probe, symbols, picture, record)
        record(dict(step="result", before=before, after=after))
    finally:
        if process.poll() is None:
            os.kill(process.pid, signal.SIGTERM)
            try:
                process.wait(20)
            except subprocess.TimeoutExpired:
                process.kill()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--save", type=Path, required=True)
    parser.add_argument("--display", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.5)
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
