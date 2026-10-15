#!/usr/bin/env python3
"""Compare a ``make check`` log of the engine's GBA test ROM with the checked-in list of expected failures.

The project runs Gen 6 rules, so 39 upstream tests (written for later generations) fail by design
(docs/gba-test-failures.md). A bare "39 failed" hides a 40th, so this fails when a test outside the
list fails, and says when a listed test no longer fails. Usage:

    python scripts/diagnostics/check_gba_test_failures.py make-check.log [--expected docs/gba-test-expected-failures.txt]
    python scripts/diagnostics/check_gba_test_failures.py make-check.log --write   # regenerate the list
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;]*m")
ENTRY = re.compile(r"^\s+- (test/[^:]+):\d+: (.*)$")
DETAIL = re.compile(r": \d+: .*$")


def failed_tests(text):
    """The (file, title) of each test in the log's "FAILED tests:" block (not the assumption failures)."""
    found, inside = set(), False
    for line in ANSI.sub("", text).splitlines():
        if line.strip() == "FAILED tests:":
            inside = True
        elif inside and not line.strip():
            break
        elif inside:
            match = ENTRY.match(line)
            if match:
                found.add(f"{match[1]}: {DETAIL.sub('', match[2])}")
    return found


def read_expected(path):
    return {line.rstrip("\n") for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")}


def compare(failed, expected):
    return sorted(failed - expected), sorted(expected - failed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", type=Path)
    parser.add_argument("--expected", type=Path, default=Path(__file__).parents[2] / "docs" / "gba-test-expected-failures.txt")
    parser.add_argument("--write", action="store_true", help="write the failures in the log as the new expected list")
    args = parser.parse_args(argv)
    failed = failed_tests(args.log.read_text(encoding="utf-8", errors="replace"))
    if not failed and not args.write:
        print("no 'FAILED tests:' block in the log: was this a complete make check log?")
        return 2
    if args.write:
        args.expected.write_text("# Upstream GBA tests that fail under the project's Gen 6 profile (docs/gba-test-failures.md).\n"
                                 + "\n".join(sorted(failed)) + "\n", encoding="utf-8")
        print(f"wrote {len(failed)} expected failures to {args.expected}")
        return 0
    new, fixed = compare(failed, read_expected(args.expected))
    for name in new:
        print("NEW FAILURE:", name)
    for name in fixed:
        print("no longer fails (remove it from the list):", name)
    print(f"{len(failed)} failed, {len(failed) - len(new)} expected, {len(new)} new, {len(fixed)} listed but passing")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
