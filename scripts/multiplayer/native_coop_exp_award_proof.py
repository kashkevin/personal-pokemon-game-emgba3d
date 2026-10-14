"""The co-op experience award's screens in the real native game (offline).

Co-op battles award experience (owner decision 2026-10-13). Each player's game
records, during the co-op battle, which of its own Pokemon faced each defeated
opposing Pokemon; after the battle has released the party it awards the
experience itself (engine src/multiplayer_coop.c, EventScript_MultiplayerCoopExp
in data/scripts/mp_coop_gym.inc, run by the co-op victory and defeat scripts).
The award's arithmetic is covered by the engine's --selftest-coop-exp; this run
covers what a self-test cannot: the script, its messages, the "forget a move?"
choice through the summary screen, the evolution scene started from the field
and the return to the field, in the actual game with its real save.

The game is started with --test-coop-exp-award: once the field has been calm
for two seconds it behaves as after a lost co-op battle in which its lead
knocked out two Lv. 100 Blissey (no battle is played; the defeat script runs
the award, then its own message). A copy of a test save is used whose second
Pokemon is changed to a Kirlia (a private fixture: species bits only), so the
award's level-up offers an evolution. A presses answer every message and YES
every prompt; in the summary screen the first move is forgotten.

Party, messages and screens are read from the game's memory (/proc/PID/mem at
the non-PIE executable's nm symbols; read only).

    PYTHONPATH=src python scripts/multiplayer/native_coop_exp_award_proof.py \\
        --game ../engine-stability/pokeemerald-mp-diorama --save route101-strongest-first.sav \\
        --display :98 --output /private/multiplayer-proof/native-coop-exp-award-1
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
from native_exp_share_proof import game_text, press  # noqa: E402
from native_spawn_proof import SAVEBLOCK1_DATA, _save_slots, _screenshot, _sector_checksum  # noqa: E402
from emerald_multiplayer.flash import POKEMON_SIZE, SAVED_PARTY_OFFSET  # noqa: E402
from emerald_multiplayer.ownership import _SUBSTRUCT_OFFSETS  # noqa: E402

SPECIES_KIRLIA, SPECIES_GARDEVOIR = 281, 282
SYMBOLS = ("gMain", "gParties", "gPartiesCount", "CB2_Overworld", "gStringVar4", "gSpecialVar_Result")


def symbols(game: Path) -> dict[str, int]:
    rows = subprocess.run(["nm", str(game)], capture_output=True, text=True, check=True).stdout
    found = {}
    for row in rows.splitlines():
        parts = row.split()
        if len(parts) == 3 and parts[2] in SYMBOLS:
            found[parts[2]] = int(parts[0], 16)
        if len(parts) == 3 and parts[1] in "tT":
            found.setdefault("callbacks", {})[int(parts[0], 16)] = parts[2]
    missing = set(SYMBOLS) - set(found)
    if missing:
        raise SystemExit(f"symbols not found in {game}: {sorted(missing)}")
    return found


def with_species(source: Path, target: Path, slot: int, species: int, moves: tuple[int, ...] | None = None) -> None:
    """A private test fixture: party slot `slot` of the copy becomes `species`
    (the growth substructure's species bits; the record's checksum and the
    sector checksum are recomputed). Everything else is the save's own."""
    data = bytearray(source.read_bytes())
    _, sectors = _save_slots(data)
    base = sectors[1]
    start = base + SAVED_PARTY_OFFSET + slot * POKEMON_SIZE
    if SAVED_PARTY_OFFSET + (slot + 1) * POKEMON_SIZE > SAVEBLOCK1_DATA:
        raise ValueError("party slot is outside the first SaveBlock1 sector")
    mon = bytearray(data[start:start + POKEMON_SIZE])
    personality, ot_id = struct.unpack_from("<II", mon)
    key = personality ^ ot_id
    words = [value ^ key for value in struct.unpack_from("<12I", mon, 32)]
    growth = [row[personality % 24] for row in _SUBSTRUCT_OFFSETS][0] * 3
    words[growth] = (words[growth] & ~0x7FF) | species
    if moves is not None:
        # The attacks substructure: four 16-bit moves, then four PP bytes.
        attacks = [row[personality % 24] for row in _SUBSTRUCT_OFFSETS][1] * 3
        words[attacks] = moves[0] | moves[1] << 16
        words[attacks + 1] = moves[2] | moves[3] << 16
        words[attacks + 2] = 0x14141414 | (words[attacks + 2] & 0)  # 20 PP each
    checksum = sum((value & 0xFFFF) + (value >> 16) for value in words) & 0xFFFF
    struct.pack_into("<H", mon, 28, checksum)
    struct.pack_into("<12I", mon, 32, *(value ^ key for value in words))
    data[start:start + POKEMON_SIZE] = mon
    struct.pack_into("<H", data, base + 0xFF6, _sector_checksum(data, base, SAVEBLOCK1_DATA))
    target.write_bytes(bytes(data))
    target.chmod(0o600)


class Memory:
    def __init__(self, pid: int, table: dict):
        self.pid, self.table = pid, table

    def read(self, address: int, size: int) -> bytes:
        with open(f"/proc/{self.pid}/mem", "rb", buffering=0) as memory:
            memory.seek(address)
            return memory.read(size)

    def callback2(self) -> str:
        address = struct.unpack("<I", self.read(self.table["gMain"] + 4, 4))[0]
        return self.table.get("callbacks", {}).get(address, hex(address))

    def text(self) -> str:
        return game_text(self.read(self.table["gStringVar4"], 1000))

    def party(self) -> list[dict]:
        count = self.read(self.table["gPartiesCount"], 1)[0]
        raw = self.read(self.table["gParties"], 6 * POKEMON_SIZE)
        return [decode(raw[i * POKEMON_SIZE:(i + 1) * POKEMON_SIZE], i) for i in range(min(count, 6))]


def decode(mon: bytes, slot: int) -> dict:
    personality, ot_id = struct.unpack_from("<II", mon)
    words = tuple(v ^ personality ^ ot_id for v in struct.unpack_from("<12I", mon, 32))
    physical = struct.pack("<12I", *words)
    logical = b"".join(physical[i * 12:i * 12 + 12] for i in (row[personality % 24] for row in _SUBSTRUCT_OFFSETS))
    return dict(slot=slot, species=struct.unpack_from("<H", logical, 0)[0] & 0x7FF,
                experience=struct.unpack_from("<I", logical, 4)[0] & 0x1FFFFF,
                moves=list(struct.unpack_from("<4H", logical, 12)),
                level=mon[84], hp=struct.unpack_from("<H", mon, 86)[0], max_hp=struct.unpack_from("<H", mon, 88)[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game", type=Path, required=True, help="the native Linux game (non-PIE, with symbols)")
    parser.add_argument("--save", type=Path, required=True, help="a test save (route101-strongest-first.sav)")
    parser.add_argument("--display", default=":98")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=420)
    parser.add_argument("--four-moves", action="store_true", help="the lead knows four moves (the forget-a-move path)")
    args = parser.parse_args()

    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise SystemExit("choose a new private multiplayer-proof output directory")
    root.mkdir(parents=True)
    args.game = args.game.resolve()
    table = symbols(args.game)
    save = root / "route101-kirlia.sav"
    with_species(args.save, save, 1, SPECIES_KIRLIA)
    if args.four_moves:
        # The lead knows four moves (Tackle, Growl, Tail Whip, Surf): its new
        # moves ask "forget a move?"; YES, and the summary's first move goes.
        with_species(save, save, 0, 321, moves=(33, 45, 39, 57))
    log = (root / "game.log").open("wb")
    process = subprocess.Popen([str(args.game), "--save", str(save), "--test-coop-exp-award"], cwd=root,
                               stdout=log, stderr=subprocess.STDOUT,
                               env=dict(os.environ, DISPLAY=args.display, SDL_AUDIODRIVER="dummy"))
    memory = Memory(process.pid, table)
    evidence: dict = dict(scope="the co-op experience award's screens in the native game (offline, "
                                "--test-coop-exp-award: no battle is played)", game=str(args.game), checks=[],
                          messages=[], screens=[])
    checks = evidence["checks"]

    def check(text: str, ok: bool, **fields) -> None:
        checks.append(dict(verified=text, passed=bool(ok), **fields))
        print(("ok   " if ok else "FAIL ") + text, json.dumps(fields) if fields else "", flush=True)

    try:
        time.sleep(12)
        press(args.display, "Return")
        time.sleep(5)
        press(args.display, "Return")
        time.sleep(10)
        deadline = time.monotonic() + 60
        while memory.callback2() != "CB2_Overworld" and time.monotonic() < deadline:
            press(args.display, "z")
            time.sleep(3)
        before = memory.party()
        evidence["party_before"] = before
        check("the game is on the overworld with the fixture's party (slot 1 a Kirlia)",
              memory.callback2() == "CB2_Overworld" and len(before) >= 2 and before[1]["species"] == SPECIES_KIRLIA,
              party=before)
        _screenshot(args.display, root / "01-overworld.png")

        seen_text, shots, last_screen, done = "", 1, "CB2_Overworld", False
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline and process.poll() is None:
            screen, text = memory.callback2(), memory.text()
            if screen != last_screen:
                evidence["screens"].append(screen)
                shots += 1
                time.sleep(1.0)
                _screenshot(args.display, root / f"{shots:02d}-{screen}.png")
                last_screen = screen
            if text and text != seen_text and screen == "CB2_Overworld":
                seen_text = text
                evidence["messages"].append(text)
                print("     message:", text, flush=True)
                time.sleep(1.2)  # let it print
                shots += 1
                _screenshot(args.display, root / f"{shots:02d}-message.png")
                if "lost" in text.lower() or "defeat" in text.lower() or "better luck" in text.lower():
                    press(args.display, "z")
                    time.sleep(2)
                    done = True
                    break
            press(args.display, "z")
            time.sleep(.6)
        time.sleep(3)
        after = memory.party()
        evidence["party_after"] = after
        _screenshot(args.display, root / f"{shots + 1:02d}-after.png")
        check("the game is running and back on the overworld", process.poll() is None
              and memory.callback2() == "CB2_Overworld", screen=memory.callback2(), defeat_message_seen=done)
        gains = [a["experience"] - b["experience"] for a, b in zip(after, before)]
        evidence["gains"] = gains
        check("the lead (it faced the defeated Pokemon) gained experience", gains[0] > 0, gains=gains)
        check("the second Pokemon (never sent out) gained the Exp. Share's share, less than the lead's",
              0 < gains[1] < gains[0], gains=gains)
        check("only once: no other Pokemon's gain exceeds the lead's, and a second award never ran",
              all(g <= gains[0] for g in gains) and sum("gained" in m for m in evidence["messages"]) <= len(before),
              gains=gains)
        check("level-ups with new stats", after[0]["level"] > before[0]["level"]
              and after[0]["max_hp"] > before[0]["max_hp"], levels=[(b["level"], a["level"]) for a, b in zip(after, before)])
        check("the Kirlia evolved into Gardevoir (the evolution scene from the field)",
              after[1]["species"] == SPECIES_GARDEVOIR and "CB2_EvolutionSceneUpdate" in evidence["screens"],
              species=after[1]["species"], screens=evidence["screens"])
        check("the award's messages were shown (experience, level, moves)",
              any("Exp. Points" in m for m in evidence["messages"]) and any("grew to Lv" in m for m in evidence["messages"]),
              messages=evidence["messages"])
        moves_changed = [a["moves"] != b["moves"] for a, b in zip(after, before)]
        evidence["moves_changed"] = moves_changed
        check("a new move was learned (directly, or by forgetting one in the summary screen)",
              any(moves_changed), moves=[(b["moves"], a["moves"]) for a, b in zip(after, before)],
              summary_screen=any("Summary" in s or "summary" in s for s in evidence["screens"]))
        if args.four_moves:
            check("with four moves known: asked, the summary screen chose the move to forget, the new move replaced it",
                  any("forgotten" in m for m in evidence["messages"]) and any("Summary" in s or "summary" in s for s in evidence["screens"])
                  and any("forgot" in m for m in evidence["messages"]) and 33 not in after[0]["moves"]
                  and 0 not in after[0]["moves"], moves=after[0]["moves"], screens=evidence["screens"])
    finally:
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
        evidence["passed"] = all(row["passed"] for row in checks) and bool(checks)
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print("PASSED" if evidence["passed"] else "FAILED", root)
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
