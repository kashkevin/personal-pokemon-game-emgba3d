#!/usr/bin/env python3
"""The native interface's audit (KNOWN_ISSUES MS-105) over a whole-game walk: what of the game's own GBA interface
showed with no native screen over it.

A test build run with PKMN_NATIVE_UI_AUDIT=1 logs, whenever it changes, "Native UI audit: frame F, ..." - none, or the
game's own text and menu windows on screen (id, size, place), a battle transition playing, the game's own screen (its
main callback) and the field script last started - and once "Native UI audit: on (CB2_Overworld at ADDR)".

    ui_audit.py summarize --nm TABLE [--min FRAMES] --out STATES.json LOG...
        the states of the logs, each with how many times and how many frames it lasted and in how many logs, those
        shorter than FRAMES (default 20) left out (a screen's loading frames); addresses named from TABLE (`nm -n` of
        the same build), moved by the log's CB2_Overworld against the table's (a program Windows loaded elsewhere)
    ui_audit.py compare --baseline STATES.json [--out REPORT.json] STATES.json...
        the walk's states (one file or several shards') against another build's: the game's own screens - a "screen"
        name - that showed uncovered here and never there fail it (exit 1); the rest is reported.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import re
import sys

LINE = re.compile(r"Native UI audit: frame (\d+), (.*)")
REFERENCE = re.compile(r"Native UI audit: on \(CB2_Overworld at (?:0x)?([0-9A-Fa-f]+)\)")
SCREEN = re.compile(r"\bscreen (\S+)")


def read_table(path):
    symbols = []
    with open(path, errors="replace") as table:
        for line in table:
            parts = line.split()
            if len(parts) >= 3 and parts[1] in "TtRrDdBb":
                try:
                    symbols.append((int(parts[0], 16), parts[2].lstrip("_")))
                except ValueError:
                    pass
    symbols.sort()
    return symbols


def namer(symbols):
    addresses = [address for address, _ in symbols]
    overworld = next((address for address, name in symbols if name == "CB2_Overworld"), None)

    def name(text, delta):
        if text in ("(nil)", "0x0", "0", "00000000"):
            return "-"
        value = int(text, 16) - delta
        i = bisect.bisect_right(addresses, value) - 1
        if i < 0:
            return text
        base, label = symbols[i]
        return label if value == base else f"{label}+{value - base:#x}"

    return name, overworld


def summarize(logs, symbols, minimum):
    name, overworld = namer(symbols)
    states = collections.defaultdict(lambda: [0, 0, set()])
    for path in logs:
        previous, delta = None, 0
        with open(path, errors="replace") as log:
            for text in log:
                match = REFERENCE.search(text)
                if match:
                    if overworld is not None:
                        delta = int(match.group(1), 16) - overworld
                    continue
                match = LINE.search(text)
                if not match:
                    continue
                frame, rest = int(match.group(1)), match.group(2).strip()
                if previous is not None:
                    start, key = previous
                    if key is not None and frame - start >= minimum:
                        state = states[key]
                        state[0] += 1
                        state[1] += frame - start
                        state[2].add(path)
                if rest.startswith("none"):
                    previous = (frame, None)
                    continue
                body = rest.split(":", 1)[1] if ":" in rest else rest
                body = re.sub(r"screen (0x[0-9a-fA-F]+|[0-9A-Fa-f]{8})", lambda m: "screen " + name(m.group(1), delta),
                              body)
                body = re.sub(r"script (0x[0-9a-fA-F]+|[0-9A-Fa-f]{8}|\(nil\))",
                              lambda m: "script " + name(m.group(1), delta), body)
                previous = (frame, body.strip())
    return {key: {"times": value[0], "frames": value[1], "logs": len(value[2])}
            for key, value in sorted(states.items(), key=lambda item: -item[1][1])}


def screens(states):
    found = set()
    for key in states:
        for match in SCREEN.finditer(key):
            found.add(match.group(1).split("+", 1)[0])
    return found


def merge(parts):
    merged = {}
    for part in parts:
        for key, value in part.items():
            into = merged.setdefault(key, {"times": 0, "frames": 0, "logs": 0})
            for field in into:
                into[field] += value.get(field, 0)
    return merged


def compare(states, baseline):
    here, there = screens(states), screens(baseline)
    new_screens = sorted(here - there)
    new_states = sorted(key for key in states if key not in baseline)
    return {"screens": sorted(here), "baseline_screens": sorted(there), "new_screens": new_screens,
            "new_states": new_states, "states": len(states), "baseline_states": len(baseline)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("summarize")
    one.add_argument("--nm", required=True)
    one.add_argument("--min", type=int, default=20)
    one.add_argument("--out", required=True)
    one.add_argument("logs", nargs="*")
    two = sub.add_parser("compare")
    two.add_argument("--baseline", required=True)
    two.add_argument("--out")
    two.add_argument("states", nargs="+")
    args = parser.parse_args(argv)
    if args.command == "summarize":
        states = summarize(args.logs, read_table(args.nm), args.min)
        with open(args.out, "w") as out:
            json.dump(states, out, indent=1)
        print(f"{len(states)} states of the game's own interface uncovered for {args.min} frames or more, "
              f"in {len(args.logs)} logs")
        for key, value in list(states.items())[:30]:
            print(f"  {value['times']:5d} times, {value['frames']:7d} frames, {value['logs']:3d} logs | {key}")
        return 0
    parts = []
    for path in args.states:
        with open(path) as part:
            parts.append(json.load(part))
    with open(args.baseline) as base:
        baseline = json.load(base)
    report = compare(merge(parts), baseline)
    if args.out:
        with open(args.out, "w") as out:
            json.dump(report, out, indent=1)
    print(f"the game's own screens uncovered: {len(report['screens'])} here, {len(report['baseline_screens'])} in "
          f"the baseline; {len(report['new_states'])} of {report['states']} states not in the baseline")
    for screen in report["new_screens"]:
        print(f"  NEW SCREEN uncovered here, never in the baseline: {screen}")
    return 1 if report["new_screens"] else 0


if __name__ == "__main__":
    sys.exit(main())
