"""Remove only reviewed, hash-pinned upstream test fixtures from a new tar.

No extraction, source mutation, runtime rebuilding, or automatic discovery-based
deletion occurs. The adjacent inventory is specific to one upstream archive.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import tarfile

POLICY = Path(__file__).with_name("source-fixtures.json")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _inventory(archive):
    rows = {}
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or member.name in rows:
            raise ValueError("unsafe or repeated archive path")
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise ValueError("unsupported archive member type")
        row = dict(path=member.name, size=member.size, type=member.type.hex(),
                   mode=member.mode, uid=member.uid, gid=member.gid,
                   uname=member.uname, gname=member.gname, mtime=member.mtime,
                   linkname=member.linkname, pax_headers=member.pax_headers)
        if member.isfile():
            with archive.extractfile(member) as stream:
                row["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        rows[member.name] = row
    return rows


def sanitize(source, output, provenance, *, policy_path=POLICY):
    source, output, provenance = map(Path, (source, output, provenance))
    if output.resolve() == provenance.resolve() or output.exists() or provenance.exists():
        raise ValueError("outputs must be distinct new paths")
    policy = json.loads(Path(policy_path).read_text())
    if policy.get("format") != "emerald-mgba-source-filter-v1" or sha(source) != policy["source_sha256"]:
        raise ValueError("source archive differs from reviewed pin")
    removed = {row["path"]: row for row in policy["removed"]}
    if len(removed) != len(policy["removed"]) or not removed:
        raise ValueError("invalid removal inventory")
    with tarfile.open(source, "r:gz") as original:
        before = _inventory(original)
        for name, row in removed.items():
            actual = before.get(name, {})
            if (not name.startswith("cinema/") or PurePosixPath(name).suffix not in {".gb", ".gba", ".sav", ".mvl"}
                    or actual.get("type") != tarfile.REGTYPE.hex()
                    or actual.get("size") != row["size"] or actual.get("sha256") != row["sha256"]):
                raise ValueError("removal member differs from reviewed inventory")
        for member in original.getmembers():
            if member.issym() or member.islnk():
                target = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname)
                                           if member.issym() else member.linkname)
                if target.startswith("/") or target == ".." or target.startswith("../"):
                    raise ValueError("archive link escapes source root")
                if target in removed:
                    raise ValueError("retained link depends on removed fixture")
        # Exclusive creation keeps the input and every previous artifact intact.
        with output.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT,
                              pax_headers=original.pax_headers) as cleaned:
                for member in original.getmembers():
                    if member.name not in removed:
                        if member.isfile():
                            with original.extractfile(member) as stream:
                                cleaned.addfile(member, stream)
                        else:
                            cleaned.addfile(member)
    with tarfile.open(output, "r:gz") as cleaned:
        after = _inventory(cleaned)
    expected = {name: row for name, row in before.items() if name not in removed}
    if after != expected or sha(source) != policy["source_sha256"]:
        raise ValueError("retained content/metadata or original source changed")
    record = dict(format="emerald-mgba-source-derivative-v1",
                  upstream_commit=policy["upstream_commit"], original_source_sha256=policy["source_sha256"],
                  derivative_source_sha256=sha(output), policy_sha256=sha(policy_path),
                  retained_members=len(after), retained_members_sha256=hashlib.sha256(
                      json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                  retained_bytes_and_metadata_identical=True, removed=policy["removed"],
                  scope="Packaging only: test fixtures excluded; production source, notices and relink inputs retained.")
    with provenance.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, sort_keys=True, indent=2) + "\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "output", "provenance"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result = sanitize(args.source, args.output, args.provenance)
    print(json.dumps({key: result[key] for key in ("derivative_source_sha256", "retained_members")}))
