"""A failed launcher proof's own diagnosis, printed where the job's log keeps it.

A Windows job's evidence goes to a private artifact, and a session that reads the job's log cannot always fetch that
artifact (windows-package run 138's ffa-exit: its rematch ran 30 minutes without a result, and the log said nothing
more). This prints the parts that say why, from the proof's output directory:

    *.diagnosis.json     a battle route that stopped (battle_execution.py): its reason, error, the traceback's end and
                         each player's last command hops
    loop-stalls.jsonl    a launcher loop that stalled over 1.5 s, with the stack that blocked it
    route-timeline.jsonl the count of each event, the last stall probes and the last events (route_timeline.py)

Long lines are cut. Exit 0 whatever it finds: the job has failed already.

    python scripts/multiplayer/proof_failure_summary.py <proof output directory> [...]
"""
from __future__ import annotations

from collections import Counter, deque
import json
from pathlib import Path
import sys

LINE = 600          # characters of an ordinary line
STALL = 3000        # characters of a stall probe (every thread's stack)


def cut(text, limit=LINE):
    return text if len(text) <= limit else text[:limit] + f" ... ({len(text) - limit} more characters)"


def diagnoses(root):
    for path in sorted(root.rglob("*.diagnosis.json")):
        print(f"== {path.relative_to(root)}")
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            print(f"   unreadable: {error}")
            continue
        print(f"   reason {value.get('reason')}, error {value.get('error')}, code {value.get('code')}")
        for line in value.get("traceback", [])[-8:]:
            print("   " + cut(line.rstrip()))
        for player in value.get("players", []):
            print(f"   slot {player.get('slot')}: pending {player.get('pending')}, polls {player.get('polls')}")
            for hop in player.get("hops", [])[-3:]:
                print("     " + cut(json.dumps(hop)))


def stalls(root):
    for path in sorted(root.rglob("loop-stalls.jsonl")):
        lines = path.read_text(errors="replace").splitlines()
        print(f"== {path.relative_to(root)}: {len(lines)} stalls over 1.5 s")
        for line in lines[-20:]:
            print("   " + cut(line, STALL))


def timeline(root):
    for path in sorted(root.rglob("route-timeline.jsonl")):
        counts, probes, last = Counter(), deque(maxlen=4), deque(maxlen=40)
        with path.open(errors="replace") as lines:
            for line in lines:
                try:
                    event = json.loads(line).get("ev")
                except ValueError:
                    event = "unreadable"
                counts[event] += 1
                if event in ("stall", "pause"):
                    probes.append(line.rstrip())
                last.append(line.rstrip())
        print(f"== {path.relative_to(root)}: " + ", ".join(f"{event} {n}" for event, n in counts.most_common()))
        if probes:
            print("   the last stall probes and process pauses:")
            for line in probes:
                print("   " + cut(line, STALL))
        print("   the last events:")
        for line in last:
            print("   " + cut(line))


def main(paths):
    for name in paths:
        root = Path(name)
        print(f"=== proof output {root}")
        if not root.is_dir():
            print("   (not there)")
            continue
        for part in (diagnoses, stalls, timeline):
            try:
                part(root)
            except OSError as error:
                print(f"   {part.__name__}: {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
