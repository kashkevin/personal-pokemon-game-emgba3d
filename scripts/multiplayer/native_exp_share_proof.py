"""The permanent Exp. Share (EmeraldTogether expansion Phase 1) in the native game.

Offline (no world, no companion): a copy of a test save on Route 101 whose lead
knows a damaging first move (native_spawn_proof.strongest_first) walks up to a
wild Pokemon walking in the grass (the nearest overworld wild Pokemon, found in
the game's object table) until a wild battle starts, wins it with its first move
and returns to the overworld. The party's experience is read from the game's memory before
and after (/proc/PID/mem at the non-PIE executable's nm symbols; read only).

Expected with the Gen 9 Exp. Share: the lead (sent out) gains the full share
and every other Pokemon that can battle gains half of it, once, with no item
held; the game shows "The rest of your team gained EXP. Points ..." (a
screenshot is taken when the second Pokemon's experience changes). With
--expect-no-share the same run checks the game without it (only the lead
gains), for a before/after comparison.

    PYTHONPATH=src python scripts/multiplayer/native_exp_share_proof.py \\
        --game ../engine-graphics/pokeemerald-mp-diorama --save route101.sav \\
        --display :98 --output /private/multiplayer-proof/native-exp-share-1
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_spawn_proof import _focus, _screenshot, _xdotool, strongest_first  # noqa: E402
from emerald_multiplayer.ownership import _SUBSTRUCT_OFFSETS  # noqa: E402

POKEMON_SIZE = 100
ITEM_EXP_SHARE = 461  # include/constants/items.h
SYMBOLS = ("gMain", "gParties", "gPartiesCount", "CB2_Overworld", "BattleMainCB2", "gBattleTypeFlags",
           "gSaveBlock1Ptr", "gDisplayedStringBattle", "gObjectEvents")
OBJECT_EVENT_SIZE, OBJECT_EVENTS_COUNT, MAP_OFFSET = 36, 16, 7
OBJ_EVENT_MON, OBJ_EVENT_ID_FOLLOWER = 1 << 14, 0xFE


def game_text(raw: bytes) -> str:
    """The game's charset (letters, digits, common punctuation) to text."""
    out = []
    for byte in raw:
        if byte == 0xFF:
            break
        if 0xBB <= byte <= 0xD4:
            out.append(chr(ord("A") + byte - 0xBB))
        elif 0xD5 <= byte <= 0xEE:
            out.append(chr(ord("a") + byte - 0xD5))
        elif 0xA1 <= byte <= 0xAA:
            out.append(chr(ord("0") + byte - 0xA1))
        else:
            out.append({0x00: " ", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xB8: ",", 0xB4: "'", 0x1B: "e",
                        0xFA: " ", 0xFB: " ", 0xFE: " "}.get(byte, ""))
    return " ".join("".join(out).split())


def symbols(game: Path) -> dict[str, int]:
    rows = subprocess.run(["nm", str(game)], capture_output=True, text=True, check=True).stdout
    found = {}
    for row in rows.splitlines():
        parts = row.split()
        if len(parts) == 3 and parts[2] in SYMBOLS:
            found[parts[2]] = int(parts[0], 16)
    missing = set(SYMBOLS) - set(found)
    if missing:
        raise SystemExit(f"symbols not found in {game}: {sorted(missing)}")
    return found


class Memory:
    def __init__(self, pid: int, table: dict[str, int]):
        self.pid, self.table = pid, table

    def read(self, address: int, size: int) -> bytes:
        with open(f"/proc/{self.pid}/mem", "rb", buffering=0) as memory:
            memory.seek(address)
            return memory.read(size)

    def callback2(self) -> int:
        return struct.unpack("<I", self.read(self.table["gMain"] + 4, 4))[0]

    def overworld(self) -> bool:
        return self.callback2() == self.table["CB2_Overworld"]

    def in_battle(self) -> bool:
        return self.callback2() == self.table["BattleMainCB2"]

    def where(self) -> tuple[int, int]:
        """The player's tile (SaveBlock1 pos: the player in map coordinates)."""
        block = struct.unpack("<I", self.read(self.table["gSaveBlock1Ptr"], 4))[0]
        return struct.unpack("<hh", self.read(block, 4))

    def wild_objects(self) -> list[tuple[int, int, int]]:
        """(x, y, graphicsId) in map coordinates of the field's Pokemon objects
        other than the player's follower: the overworld wild Pokemon."""
        raw = self.read(self.table["gObjectEvents"], OBJECT_EVENT_SIZE * OBJECT_EVENTS_COUNT)
        found = []
        for i in range(OBJECT_EVENTS_COUNT):
            event = raw[i * OBJECT_EVENT_SIZE:(i + 1) * OBJECT_EVENT_SIZE]
            active, is_player = event[0] & 1, event[2] & 1
            graphics, local_id = struct.unpack_from("<H", event, 4)[0], event[8]
            x, y = struct.unpack_from("<hh", event, 0x10)
            if active and not is_player and graphics & OBJ_EVENT_MON and local_id != OBJ_EVENT_ID_FOLLOWER:
                found.append((x - MAP_OFFSET, y - MAP_OFFSET, graphics))
        return found

    def battle_text(self) -> str:
        return game_text(self.read(self.table["gDisplayedStringBattle"], 0x1A9))

    def battle_flags(self) -> int:
        return struct.unpack("<I", self.read(self.table["gBattleTypeFlags"], 4))[0]

    def party(self, side: int = 0) -> list[dict]:
        count = self.read(self.table["gPartiesCount"] + side, 1)[0]
        raw = self.read(self.table["gParties"] + side * 6 * POKEMON_SIZE, 6 * POKEMON_SIZE)
        return [decode(raw[i * POKEMON_SIZE:(i + 1) * POKEMON_SIZE], i) for i in range(min(count, 6))]


def decode(mon: bytes, slot: int) -> dict:
    personality, ot_id = struct.unpack_from("<II", mon)
    words = tuple(v ^ personality ^ ot_id for v in struct.unpack_from("<12I", mon, 32))
    physical = struct.pack("<12I", *words)
    logical = b"".join(physical[i * 12:i * 12 + 12] for i in (row[personality % 24] for row in _SUBSTRUCT_OFFSETS))
    species = struct.unpack_from("<H", logical, 0)[0] & 0x7FF
    held_item = struct.unpack_from("<H", logical, 2)[0] & 0x3FF
    experience = struct.unpack_from("<I", logical, 4)[0] & 0x1FFFFF
    level, hp = mon[84], struct.unpack_from("<H", mon, 86)[0]
    return dict(slot=slot, species=species, level=level, experience=experience, hp=hp, held_item=held_item)


def press(display: str, key: str, hold: float = .12) -> None:
    _focus(display)
    _xdotool(display, "keydown", key)
    time.sleep(hold)
    _xdotool(display, "keyup", key)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game", type=Path, required=True, help="the native Linux game (non-PIE, with symbols)")
    parser.add_argument("--save", type=Path, required=True, help="a test save standing on Route 101")
    parser.add_argument("--display", default=":98")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expect-no-share", action="store_true", help="the game without the Exp. Share")
    parser.add_argument("--walk-seconds", type=float, default=240)
    args = parser.parse_args()

    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise SystemExit("choose a new private multiplayer-proof output directory")
    root.mkdir(parents=True)
    table = symbols(args.game)
    save = root / "route101-strongest-first.sav"
    strongest_first(args.save, save)
    log = (root / "game.log").open("wb")
    process = subprocess.Popen([str(args.game), "--save", str(save)], cwd=root, stdout=log, stderr=subprocess.STDOUT,
                               env=dict(os.environ, DISPLAY=args.display, SDL_AUDIODRIVER="dummy"))
    memory = Memory(process.pid, table)
    evidence: dict = dict(scope="the permanent Exp. Share in the native game, offline, one wild battle",
                          game=str(args.game), expect_share=not args.expect_no_share, checks=[])
    checks = evidence["checks"]

    def check(text: str, ok: bool, **fields) -> None:
        checks.append(dict(verified=text, passed=bool(ok), **fields))
        print(("ok   " if ok else "FAIL ") + text, json.dumps(fields) if fields else "", flush=True)

    try:
        time.sleep(12)
        press(args.display, "Return")
        time.sleep(5)
        press(args.display, "Return")
        time.sleep(12)
        press(args.display, "z")
        deadline = time.monotonic() + 60
        while not memory.overworld() and time.monotonic() < deadline:
            time.sleep(4)
            if not memory.overworld():
                press(args.display, "z")
        check("the game is on the overworld", memory.overworld())
        before = memory.party()
        evidence["party_before"] = before
        check("the party: two or more Pokemon, none holding the Exp. Share item", len(before) >= 2
              and all(mon["held_item"] != ITEM_EXP_SHARE for mon in before), party=before)
        _screenshot(args.display, root / "01-overworld.png")

        # Into Route 101's western grass (left of and below the save's spot),
        # then back and forth through it, row by row, until a wild Pokemon there
        # meets the player. Moves are held until the tile changes (the cloud's
        # software 3D runs the game slowly).
        def walk(key: str, done, timeout: float = 25.0) -> None:
            _focus(args.display)
            _xdotool(args.display, "keydown", key)
            stop = time.monotonic() + timeout
            try:
                while time.monotonic() < stop and memory.overworld() and not done(memory.where()):
                    time.sleep(.03)
            finally:
                _xdotool(args.display, "keyup", key)

        # Walk up to the nearest wild Pokemon on the field (its object read from
        # memory) and into it, re-aiming after every tile, until a battle starts.
        evidence["start_tile"] = memory.where()
        deadline, step, blocked = time.monotonic() + args.walk_seconds, 0, 0
        while memory.overworld() and time.monotonic() < deadline:
            here, wild = memory.where(), memory.wild_objects()
            if not wild:
                walk(("Left", "Down", "Right", "Up")[step % 4], lambda p, h=here: p != h, 3)
                step += 1
                continue
            tx, ty, _ = min(wild, key=lambda w: abs(w[0] - here[0]) + abs(w[1] - here[1]))
            dx, dy = tx - here[0], ty - here[1]
            horizontal = abs(dx) >= abs(dy) if blocked % 2 == 0 else abs(dx) < abs(dy) or dy == 0
            if horizontal and dx:
                key = "Right" if dx > 0 else "Left"
            elif dy:
                key = "Down" if dy > 0 else "Up"
            else:
                key = "Right" if dx > 0 else "Left"
            walk(key, lambda p, h=here: p != h, 2.5)
            if memory.overworld() and memory.where() == here:
                blocked += 1
                if abs(dx) + abs(dy) == 1:
                    press(args.display, "z")  # facing it: talk to it
                    time.sleep(1.5)
            step += 1
        deadline = time.monotonic() + 20
        while not memory.in_battle() and time.monotonic() < deadline:
            time.sleep(.2)
        flags = memory.battle_flags()
        check("a wild battle started (no trainer, no link)", memory.in_battle() and not flags & (1 << 3)
              and not flags & (1 << 1), battle_type_flags=hex(flags), steps=step)
        time.sleep(6)
        evidence["wild"] = memory.party(1)[:1]
        _screenshot(args.display, root / "02-battle.png")

        # The lead's first move until the battle ends. The battle's messages are
        # read as the game prints them (gDisplayedStringBattle), with a picture
        # of the Exp. Share message.
        messages: list[str] = []
        shot = False
        deadline = time.monotonic() + 180
        while not memory.overworld() and time.monotonic() < deadline:
            press(args.display, "z")
            stop = time.monotonic() + 1.0
            while time.monotonic() < stop:
                if memory.in_battle():
                    text = memory.battle_text()
                    if text and (not messages or messages[-1] != text):
                        messages.append(text)
                        if "Exp. Share" in text and not shot:
                            time.sleep(.4)
                            _screenshot(args.display, root / "03-exp-share-message.png")
                            shot = True
                time.sleep(.1)
        evidence["battle_messages"] = messages
        time.sleep(3)
        check("back on the overworld after the battle", memory.overworld())
        after = memory.party()
        evidence["party_after"] = after
        _screenshot(args.display, root / "04-after.png")

        gains = [a["experience"] - b["experience"] for a, b in zip(after, before)]
        evidence["gains"] = gains
        check("the lead (sent out) gained experience", gains[0] > 0, gains=gains)
        others = [g for mon, g in zip(before[1:], gains[1:]) if mon["hp"] > 0 and mon["level"] < 100]
        if args.expect_no_share:
            check("without the Exp. Share the others gained none", all(g == 0 for g in others), gains=gains)
        else:
            check("every other Pokemon that can battle gained experience, with no item held",
                  others and all(g > 0 for g in others), gains=gains)
            check("each of them half the lead's share (Gen 6+ split, no duplicate award)",
                  all(abs(g - gains[0] // 2) <= 1 for g in others), gains=gains)
            check("the game printed the Exp. Share message", any("rest of your team gained" in m and "Exp. Share" in m
                                                               for m in messages), messages=messages)
        if args.expect_no_share:
            check("and no Exp. Share message", not any("Exp. Share" in m for m in messages), messages=messages)
    finally:
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()
        evidence["passed"] = bool(checks) and all(c["passed"] for c in checks)
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print("PASSED" if evidence["passed"] else "FAILED", flush=True)
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
