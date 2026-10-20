"""Hitches during a 3D battle, then a normal PC: do the water and flowers come back? (The owner's report of 2026-10-20:
the battle background's effects froze.)

Run beside native_launcher_battle_3d_proof.py with PKMN_DIORAMA_LOG=1 in its environment. Once a game's log says its
battle's glide is over, every 3D game of the proof is paused and resumed in short bursts for a few seconds (SIGSTOP
120 ms, SIGCONT 40 ms: frames that take four to ten times their budget, as a busy PC, a save or a window drag gives),
then left alone. Afterwards each game's runtime.log tells the step between the tile redraws (gl_battle.c): before the
2026-10-20 fix it went to "stand still" and never came back; now it is tried again and returns to every change.

    python scripts/multiplayer/diorama_stall_check.py --output <the 3D proof's --output> [--seconds 4] [--battles 1]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import time

GLIDE = "Diorama battle: the glide's frames took"


def games_of(output):
    """The proof's 3D game processes (their command lines name its private directory)."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        # The launcher runs its runtime copy of the game, application/runtime/pokeemerald-mp.exe, under the output.
        if command and os.path.basename(command[0]).startswith(b"pokeemerald-mp") and str(output).encode() in command[0]:
            found.append(int(entry.name))
    return found


def glides(output):
    count = 0
    for log in Path(output).glob("private/launches/*/runtime.log"):
        try:
            count += log.read_text(errors="replace").count(GLIDE)
        except OSError:
            pass
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--battles", type=int, default=1, help="hitch this many battles (each once its glide ends)")
    parser.add_argument("--timeout", type=float, default=3600)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    for battle in range(args.battles):
        while glides(args.output) < 2 * (battle + 1):        # both games' glides of this battle
            if time.monotonic() > deadline:
                raise SystemExit("no 3D battle glide was logged")
            time.sleep(.2)
        pids = games_of(args.output)
        if not pids:
            raise SystemExit("no 3D game of this proof is running")
        time.sleep(2)                                     # a little normal play first
        started = time.monotonic()
        bursts = 0
        while time.monotonic() - started < args.seconds:
            for pid in pids:
                os.kill(pid, signal.SIGSTOP)
            time.sleep(.12)
            for pid in pids:
                os.kill(pid, signal.SIGCONT)
            time.sleep(.04)
            bursts += 1
        print(json.dumps(dict(battle=battle + 1, games=pids, bursts=bursts,
                              seconds=round(time.monotonic() - started, 1), wall=time.strftime("%H:%M:%S"))), flush=True)


if __name__ == "__main__":
    main()
