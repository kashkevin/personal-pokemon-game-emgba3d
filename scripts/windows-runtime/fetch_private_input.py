"""Bring one private release input (sprite pack, owner's base dump) into a CI job.

The input is never in Git. It comes from, in order:
  1. --local-dir/--local-name: a folder on the machine running the job (a self-hosted
     runner on the owner's own PC), so the file never leaves that PC; or
  2. an HTTPS URL held in an environment variable (a repository secret), e.g. a private
     cloud-storage link the owner controls. The URL is masked in the job log and the
     download is bounded.
Either way the bytes must match the pinned SHA-256 before the file is accepted.

Exit status: 0 supplied and verified, 3 not supplied (optional input; the job goes on
without it), 1 supplied but wrong (the job must stop). Nothing is printed except
the file name, the size and the hash.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys
import urllib.request

NOT_SUPPLIED = 3
CHUNK = 1 << 20


def verified_copy(read, destination: Path, sha256: str, maximum: int) -> int:
    """Stream `read(n)` into a temporary file beside `destination`; rename on a hash match."""
    temp = destination.with_name(destination.name + ".part")
    digest, size = hashlib.sha256(), 0
    try:
        with temp.open("wb") as out:
            while True:
                block = read(CHUNK)
                if not block:
                    break
                size += len(block)
                if size > maximum:
                    raise ValueError(f"input is larger than the {maximum}-byte bound")
                digest.update(block)
                out.write(block)
        if digest.hexdigest() != sha256.lower():
            raise ValueError("input does not match its pinned SHA-256")
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)
    return size


def fetch(destination: Path, sha256: str, maximum: int, local_dir: str | None, local_name: str | None,
          url_env: str | None) -> int:
    if len(sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in sha256):
        raise ValueError("a 64-digit SHA-256 pin is required")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if local_dir and local_name:
        source = Path(local_dir) / local_name
        if source.is_file():
            with source.open("rb") as stream:
                return verified_copy(stream.read, destination, sha256, maximum)
    url = os.environ.get(url_env or "", "").strip()
    if not url:
        return -1
    if not url.lower().startswith("https://"):
        raise ValueError("the private input URL must be https")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::add-mask::{url}")
    request = urllib.request.Request(url, headers={"User-Agent": "emerald-together-ci"})
    with urllib.request.urlopen(request, timeout=300) as response:
        return verified_copy(response.read, destination, sha256, maximum)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--max-bytes", type=int, required=True)
    parser.add_argument("--local-dir", help="folder on this machine (self-hosted runner)")
    parser.add_argument("--local-name", help="file name inside --local-dir")
    parser.add_argument("--url-env", help="name of the environment variable that holds an https URL")
    args = parser.parse_args()
    try:
        size = fetch(args.dest, args.sha256, args.max_bytes, args.local_dir, args.local_name, args.url_env)
    except Exception as error:  # never echo a URL or a path a secret might sit in
        print(f"{args.dest.name}: refused: {error.__class__.__name__}: {error}", file=sys.stderr)
        return 1
    if size < 0:
        print(f"{args.dest.name}: not supplied")
        return NOT_SUPPLIED
    print(f"{args.dest.name}: {size} bytes, sha256 {args.sha256.lower()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
