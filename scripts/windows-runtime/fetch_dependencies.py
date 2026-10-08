"""Fetch checksum-pinned, official Windows runtime dependencies into a build cache.

No ROM/game assets are downloaded. The SDL source archive is retained beside
its official MinGW development distribution for provenance and redistribution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

SOURCES = (
    ("SDL2-devel-2.32.10-mingw.tar.gz",
     "https://github.com/libsdl-org/SDL/releases/download/release-2.32.10/SDL2-devel-2.32.10-mingw.tar.gz",
     "83a5d74012311edc3c0d40ea6faecbe57ad692aa033fa5dc273cc937e3938ff2", "sdl-devel"),
    ("SDL2-2.32.10.tar.gz",
     "https://github.com/libsdl-org/SDL/releases/download/release-2.32.10/SDL2-2.32.10.tar.gz",
     "5f5993c530f084535c65a6879e9b26ad441169b3e25d789d83287040a9ca5165", None),
    ("lua-5.4.9.tar.gz", "https://www.lua.org/ftp/lua-5.4.9.tar.gz",
     "2335b6c582a52654f94612bf10d2f4672805d05329aa6568b1d8cd9e5c6fb8e6", "lua"),
    ("libepoxy-1.5.10.tar.gz", "https://github.com/anholt/libepoxy/archive/refs/tags/1.5.10.tar.gz",
     "a7ced37f4102b745ac86d6a70a9da399cc139ff168ba6b8002b4d8d43c900c15", "epoxy"),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    args = parser.parse_args()
    cache = args.cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    evidence = []
    for name, url, digest, extract_directory in SOURCES:
        archive = cache / name
        if not archive.exists():
            temporary = archive.with_suffix(archive.suffix + ".download")
            request = urllib.request.Request(url, headers={"User-Agent": "PokemonPrivate-build/1"})
            with urllib.request.urlopen(request, timeout=60) as source, temporary.open("wb") as target:
                total = 0
                while data := source.read(65536):
                    total += len(data)
                    if total > 32 * 1024 * 1024:
                        raise ValueError("dependency archive exceeds its download bound")
                    target.write(data)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                raise ValueError(f"download checksum mismatch: {name}")
            temporary.replace(archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            raise ValueError(f"cached dependency checksum mismatch: {name}")
        if extract_directory is not None:
            destination = cache / extract_directory
            marker = destination / ".source-sha256"
            if destination.exists():
                if not marker.is_file() or marker.read_text().strip() != digest:
                    raise ValueError(f"unrecognized existing extraction: {destination}")
            else:
                destination.mkdir()
                with tarfile.open(archive, "r:gz") as source:
                    if sum(member.size for member in source.getmembers()) > 256 * 1024 * 1024:
                        raise ValueError("dependency extraction exceeds its size bound")
                    source.extractall(destination, filter="data")
                marker.write_text(digest + "\n")
        evidence.append(dict(name=name, url=url, sha256=digest, bytes=archive.stat().st_size))
        print(f"Verified {name}", flush=True)
    (cache / "sources.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
