"""The whole game's gameplay check from its shards (engine tools/qa/gameplay_check.py, one report per CI job): the
results and blocked targets merged, a summary by kind, every failed target and the game's own last lines of any run
that ended before its targets, the blocked ones grouped by reason. Prints the summary; exit 1 when a target failed or
a shard is missing.

    python scripts/qa/merge_gameplay_shards.py --shards shards --expected 8 --engine-commit SHA --out gameplay_check.json
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys


def merge(paths):
    results, blocked, seconds, problems = [], {}, [], []
    for path in paths:
        with open(path) as source:
            report = json.load(source)
        results += report["results"]
        blocked.update({b["key"]: b for b in report["blocked"]})
        seconds.append(report["seconds"])
        for job, runs in sorted(report.get("runs", {}).items()):
            for run in runs:
                if run.get("problem"):
                    problems.append(dict(shard=os.path.basename(os.path.dirname(path)), job=job, run=run["run"],
                                         problem=run["problem"], exit=run["exit"], tail=run.get("tail", [])))
    summary = collections.defaultdict(collections.Counter)
    for result in results:
        summary[result["kind"]]["passed" if result["passed"] else "failed"] += 1
    for item in blocked.values():
        summary[item["kind"]]["blocked"] += 1
    return results, list(blocked.values()), seconds, problems, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shards", required=True, help="a folder holding one folder per shard (gameplay_check.json)")
    parser.add_argument("--expected", type=int, required=True, help="how many shards ran")
    parser.add_argument("--engine-commit", default="")
    parser.add_argument("--platform", default="", help="where the shards ran (the report says so)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    paths = sorted(glob.glob(os.path.join(args.shards, "*", "gameplay_check.json")))
    results, blocked, seconds, problems, summary = merge(paths)
    merged = dict(engine_commit=args.engine_commit, platform=args.platform, shards=len(seconds),
                  longest_shard_seconds=max(seconds, default=0), summary=summary, results=results, blocked=blocked,
                  problems=problems)
    with open(args.out, "w") as out:
        json.dump(merged, out, indent=1)
    print(json.dumps(dict(engine_commit=args.engine_commit, platform=args.platform, shards=len(seconds),
                          summary=summary)))
    for problem in problems:
        print(f"{problem['shard']} job {problem['job']} run {problem['run']}: {problem['problem']} (exit {problem['exit']})")
        for line in problem["tail"]:
            print("   ", line)
    failed = [r for r in results if not r["passed"]]
    for result in failed:
        print(f"FAILED {result['key']}: {result['reason']}")
    groups = collections.defaultdict(list)
    for item in blocked:
        if item.get("runtime"):
            groups[item["reason"]].append(item["key"])
    for reason, keys in sorted(groups.items()):
        print(f"BLOCKED-GROUP {reason}")
        keys.sort()
        for at in range(0, len(keys), 6):
            print("    " + " ".join(keys[at:at + 6]))
    if len(seconds) != args.expected:
        print(f"MISSING {args.expected - len(seconds)} of {args.expected} shards")
    return 0 if not failed and len(seconds) == args.expected else 1


if __name__ == "__main__":
    sys.exit(main())
