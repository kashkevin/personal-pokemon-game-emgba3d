"""Where native_launcher_minigame_proof.py reads one game build: its functions and variables by address, its structures'
fields by offset, from the build's own symbol table (nm) and debug information (gdb; read only: nothing runs).

A Linux build is read as the proof starts. A Windows build is stripped before it is packaged, and its layout is not the
Linux build's, so the engine job writes its facts from the Windows game before the strip (windows-package.yml), as it
does mega_facts.py's, and the proof on Windows reads that file (--minigame-facts).

    python scripts/multiplayer/minigame_facts.py --game pokeemerald-mp.exe --pe --out minigame-facts.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

MULTICHOICE_TASKS = ("Task_HandleScrollingMultichoiceInput", "Task_HandleMultichoiceInput")
BERRY_CRUSH_STEPS = (
    "Cmd_BeginNormalPaletteFade", "Cmd_WaitPaletteFade", "Cmd_PrintMessage", "Cmd_ShowGameDisplay",
    "Cmd_HideGameDisplay", "Cmd_SignalReadyToBegin", "Cmd_AskPickBerry", "Cmd_GoToBerryPouch",
    "Cmd_WaitForOthersToPickBerries", "Cmd_DropBerriesIntoCrusher", "Cmd_DropLid", "Cmd_Countdown",
    "Cmd_PlayGame_Leader", "Cmd_PlayGame_Member", "Cmd_FinishGame", "Cmd_HandleTimeUp", "Cmd_TabulateResults",
    "Cmd_ShowResults", "Cmd_SaveGame", "Cmd_AskPlayAgain", "Cmd_CommunicatePlayAgainResponses", "Cmd_PlayAgain",
    "Cmd_StopGame", "Cmd_CloseLink", "Cmd_Quit")
JUMP_FIELDS = ("comm.funcId", "helperState", "vineState", "isLeader", "comm.jumpScore", "comm.jumpsInRow",
               "players[0].monState", "players[1].monState")
DODRIO_FIELDS = ("funcId", "state", "isLeader", "numPlayers", "numGraySquares", "berryResults", "berriesEaten")
PRINTER_FIELDS = ("active", "state", "nextPrinter")

FUNCTIONS = (*MULTICHOICE_TASKS, "SaveConfirmInputCallback", "SaveOverwriteInputCallback", "CB2_LinkError",
             "CB2_Overworld", "CB2_BagMenuRun", "CB2_Bag", "CB2_PokemonJump", "CB2_UpdatePartyMenu", "CB2_DodrioGame",
             *BERRY_CRUSH_STEPS)
# sGame: every one (Berry Crush's among several files' statics); gMain: the callbacks' structure
DATA = ("sSaveDialogCallback", "sLocalLinkActive", "sFirstTextPrinter", "sGame", "sPokemonJump", "gMain")
STRUCTS = {"TextPrinter": PRINTER_FIELDS, "PokemonJump": JUMP_FIELDS, "DodrioGame": DODRIO_FIELDS}
STATICS = (("dodrio_berry_picking.c", "sGame"),)   # two files have an sGame: Dodrio Berry Picking's by its file


def _addresses(rows: str, name: str, kinds: str) -> list[int]:
    """Every address of `name` (a MinGW build's C names have a leading underscore) of the nm kinds `kinds`."""
    found = set()
    for line in rows.splitlines():
        row = line.split()
        if len(row) == 3 and row[1] in kinds and row[2] in (name, "_" + name):
            found.add(int(row[0], 16))
    return sorted(found)


def game_facts(game, pe: bool = False) -> dict:
    """The facts of one build: {"functions": {name: [address]}, "data": {name: [address]}, "structs": {struct:
    {field: offset}}, "statics": {"file::name": address}} (code addresses without the Thumb bit, as the proof
    compares them)."""
    rows = subprocess.run(["i686-w64-mingw32-nm" if pe else "nm", str(game)], capture_output=True, text=True,
                          check=True).stdout
    functions = {name: sorted({a & ~1 for a in _addresses(rows, name, "Tt")}) for name in FUNCTIONS}
    data = {name: _addresses(rows, name, "bBdD") for name in DATA}
    keys, expressions = [], []
    for struct, fields in STRUCTS.items():
        for field in fields:
            keys.append((struct, field))
            expressions.append(f"(int)&((struct {struct} *)0)->{field}")
    for file, name in STATICS:
        keys.append((None, f"{file}::{name}"))
        expressions.append(f"(int)&'{file}'::{name}")
    command = ["gdb", "-batch", "-nx"]
    for expression in expressions:
        command += ["-ex", f"print {expression}"]
    output = subprocess.run(command + [str(game)], capture_output=True, text=True, timeout=600).stdout
    values = [int(line.split("=", 1)[1]) for line in output.splitlines() if line.startswith("$")]
    if len(values) != len(expressions):
        raise RuntimeError(f"gdb answered {len(values)} of {len(expressions)} (a build with debug information?): "
                           f"{output[-300:]!r}")
    structs, statics = {}, {}
    for (struct, name), value in zip(keys, values):
        if struct is None:
            statics[name] = value
        else:
            structs.setdefault(struct, {})[name] = value
    return dict(functions=functions, data=data, structs=structs, statics=statics)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="the game, unstripped")
    parser.add_argument("--pe", action="store_true", help="a Windows build (MinGW's nm)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    facts = game_facts(args.game, args.pe)
    missing = [name for kind in ("functions", "data") for name, found in facts[kind].items()
               if not found and name not in ("CB2_Bag",)]
    if missing:
        sys.exit(f"{args.game} lacks {missing}")
    args.out.write_text(json.dumps(facts, indent=1, sort_keys=True) + "\n")
    print(f"{args.out}: {sum(map(len, facts['functions'].values()))} function addresses, "
          f"{sum(map(len, facts['data'].values()))} data addresses, "
          f"{sum(map(len, facts['structs'].values()))} fields, {len(facts['statics'])} statics")
    return 0


if __name__ == "__main__":
    sys.exit(main())
