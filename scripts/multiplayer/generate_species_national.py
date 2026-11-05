"""Extract every native species ID's National Pokedex number from the engine pin.

The game's species IDs are the National Pokedex numbers only up to 905; past that the engine numbers the alternate
forms (Mega Evolutions, regional forms, Rotom's appliances, Vivillon's patterns, ...) and the later species in its own
order (include/constants/species.h). The host's rules that mean "the same Pokemon" (the Frontier's Species Clause and
No Legendaries, the trade's reviewed forms) need the National Pokedex number of any ID a save can hold.

This reads Git objects, never edits the checkout or its configuration, and invokes the compiler only on temporary
probes (preprocessing the species table, then evaluating the ID and number constants). No ROM, graphics or save is
produced. Like generate_gen6_friendship.py, it never overwrites an output; --check verifies them.

    python scripts/multiplayer/generate_species_national.py --engine ../engine \\
        --module src/emerald_multiplayer/species_national.py --evidence docs/species-national-table.json --check
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import tarfile
import tempfile


REVISION = "67e39839c3d97af16e618c431c17976343cbd588"
TABLE_ID = "engine-67e39839-species-national-v1"
ARCHIVE_PATHS = ("include", "src/data/pokemon/species_info.h", "src/data/pokemon/species_info",
                 "src/data/pokemon/egg_data.h")
PROBE = '''#define TRUE 1
#define FALSE 0
#include "metaprogram.h"
#include "constants/global.h"
#include "constants/pokemon.h"
#include "constants/species.h"
#include "constants/pokedex.h"
#include "src/data/pokemon/species_info.h"
'''
IDENTITY_LAST = 905   # the engine's IDs 1..905 are their own National Pokedex numbers (checked below)
NATIONAL_LAST = 1025  # Pecharunt


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(args, **kwargs):
    result = subprocess.run(args, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    if result.returncode or result.stderr:
        raise ValueError(f"the species probe exited {result.returncode}: " + result.stderr.decode("utf-8", "replace"))
    return result.stdout


def extract_headers(archive, root):
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
        for member in source:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("Git archive path is not a relative source path")
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("pinned species inputs must be ordinary files")
            target = root.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(source.extractfile(member).read())


def _body(source, start):
    """Balance C initializer braces while ignoring quoted strings/characters."""
    depth, quote, escaped = 0, None, False
    for index in range(start, len(source)):
        char = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if not depth:
                return source[start + 1:index]
    raise ValueError("unterminated preprocessed species initializer")


def extract_national(preprocessed):
    """(species name, national dex name) of every species entry; only SPECIES_NONE and SPECIES_EGG may have none."""
    entries = {}
    for match in re.finditer(r"\[(SPECIES_[A-Z0-9_]+)\]\s*=\s*\{", preprocessed):
        name = match.group(1)
        if name in entries:
            raise ValueError("duplicate preprocessed species entry: " + name)
        body = _body(preprocessed, match.end() - 1)
        national = re.findall(r"\.natDexNum\s*=\s*(NATIONAL_DEX_[A-Z0-9_]+)\s*,", body)
        if len(national) > 1 or (not national and name not in ("SPECIES_NONE", "SPECIES_EGG")):
            raise ValueError("a species entry needs exactly one national dex field: " + name)
        if national:
            entries[name] = national[0]
    if len(entries) < IDENTITY_LAST:
        raise ValueError("preprocessing found too few species entries")
    return tuple(sorted(entries.items()))


def used_sources(preprocessed, root):
    sources = {}
    for filename in re.findall(r'^#\s+\d+\s+"([^"\n]+)"', preprocessed, re.M):
        if filename.startswith("<"):
            continue
        path = Path(filename)
        path = (path if path.is_absolute() else root / path).resolve()
        if path == root / "species-probe.c":
            continue
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError("species preprocessing read outside the pinned source archive") from error
        sources[relative] = digest(path.read_bytes())
    return dict(sorted(sources.items()))


def compile_values(root, compiler, objcopy, entries):
    """The compiler evaluates each pair of constants; one little-endian (u16 species, u16 national) per entry."""
    pairs = ",\n".join(f"{{{species}, {national}}}" for species, national in entries)
    source = ('#include "constants/species.h"\n#include "constants/pokedex.h"\n'
              f'const unsigned short table[{len(entries)}][2] __attribute__((section(".species_national"), used)) = {{\n'
              + pairs + "\n};\n")
    (root / "species-values.c").write_text(source, encoding="ascii")
    run([compiler, "-std=c11", "-ffreestanding", "-fno-lto", "-Werror", "-Iinclude", "-c",
         "species-values.c", "-o", "species-values.o"], cwd=root)
    run([objcopy, "-O", "binary", "--only-section=.species_national", "species-values.o", "species-values.bin"], cwd=root)
    values = (root / "species-values.bin").read_bytes()
    if len(values) != 4 * len(entries):
        raise ValueError("compiled species table has an unexpected byte size")
    return [struct.unpack_from("<HH", values, 4 * index) for index in range(len(entries))], digest(source.encode("ascii"))


def check_table(rows):
    """rows: (species id, species name, national name, national number). Returns the non-identity mapping."""
    ids = [row[0] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("two species entries share an ID")
    by_id = {row[0]: row for row in rows}
    for species in range(1, IDENTITY_LAST + 1):
        if species not in by_id or by_id[species][3] != species:
            raise ValueError(f"species ID {species} is not its own National Pokedex number")
    mapping = {}
    for species, _name, _national_name, national in rows:
        if species <= IDENTITY_LAST or national == 0:   # 0: no National Pokedex number (a placeholder entry)
            continue
        if not 1 <= national <= NATIONAL_LAST:
            raise ValueError(f"species ID {species} has an out-of-range National Pokedex number {national}")
        mapping[species] = national
    return mapping


def generate(engine, compiler, objcopy):
    archive = run(["git", "-C", str(engine), "archive", "--format=tar", REVISION, *ARCHIVE_PATHS])
    with tempfile.TemporaryDirectory(prefix="pokemon-species-national-") as temporary:
        root = Path(temporary).resolve()
        extract_headers(archive, root)
        native_defines = (root / "include/gba/defines.h").read_text(encoding="utf-8")
        for name, value in (("TRUE", "1"), ("FALSE", "0")):
            if re.findall(r"^#define\s+" + name + r"\s+(\d+)\s*$", native_defines, re.M) != [value]:
                raise ValueError("pinned native boolean definition changed: " + name)
        (root / "species-probe.c").write_text(PROBE, encoding="ascii")
        expanded = run([compiler, "-E", "-x", "c", "-nostdinc", "-Iinclude", "-I.", "species-probe.c"],
                       cwd=root).decode("utf-8")
        entries = extract_national(expanded)
        values, value_probe_hash = compile_values(root, compiler, objcopy, entries)
        sources = used_sources(expanded, root)
        sources["include/gba/defines.h"] = digest((root / "include/gba/defines.h").read_bytes())
    rows = sorted((species, name, national_name, national)
                  for (name, national_name), (species, national) in zip(entries, values))
    mapping = check_table(rows)
    packed = b"".join(struct.pack("<HH", species, national) for species, national in sorted(mapping.items()))
    evidence = dict(schema=1, table_id=TABLE_ID, engine_revision=REVISION,
        identity_last=IDENTITY_LAST, national_last=NATIONAL_LAST,
        source_files=sources, probe_sha256=digest(PROBE.encode("ascii")), value_probe_sha256=value_probe_hash,
        generator_sha256=digest(Path(__file__).read_bytes()),
        compiler=run([compiler, "--version"]).decode().splitlines()[0],
        objcopy=run([objcopy, "--version"]).decode().splitlines()[0],
        mapping_sha256=digest(packed),
        entries=[[species, name, national_name, national] for species, name, national_name, national in rows
                 if species > IDENTITY_LAST])
    lines = []
    for start in range(0, len(mapping), 8):
        chunk = sorted(mapping.items())[start:start + 8]
        lines.append("    " + " ".join(f"{species}: {national}," for species, national in chunk))
    module = ('"""Generated from the engine pin; see scripts/multiplayer/generate_species_national.py and\n'
              'docs/species-national-table.json. Do not edit by hand."""\n'
              f'TABLE_ID = "{TABLE_ID}"\nENGINE_REVISION = "{REVISION}"\n'
              f'MAPPING_SHA256 = "{digest(packed)}"\nIDENTITY_LAST = {IDENTITY_LAST}\n'
              '# Every species ID past IDENTITY_LAST with its National Pokedex number (placeholders without one left out).\n'
              'NATIONAL = {\n' + "\n".join(lines) + '\n}\n\n\n'
              'def national_number(species):\n'
              '    """The National Pokedex number of a native species ID, or None for an ID this table does not know."""\n'
              '    if type(species) is not int or species < 1:\n'
              '        return None\n'
              '    if species <= IDENTITY_LAST:\n'
              '        return species\n'
              '    return NATIONAL.get(species)\n')
    return module.encode("ascii"), (json.dumps(evidence, sort_keys=True, indent=2) + "\n").encode("ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--compiler", default="arm-none-eabi-gcc")
    parser.add_argument("--objcopy", default="arm-none-eabi-objcopy")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.module.resolve() == args.evidence.resolve():
        raise ValueError("generated module and provenance must use different paths")
    if not args.check and (args.module.exists() or args.evidence.exists()):
        raise ValueError("generation never overwrites existing outputs; use --check to verify")
    module, evidence = generate(args.engine, args.compiler, args.objcopy)
    for path, expected in ((args.module, module), (args.evidence, evidence)):
        if args.check:
            if path.read_bytes() != expected:
                raise ValueError("generated species output differs: " + str(path))
        else:
            with path.open("xb") as output:
                output.write(expected)
    print("Verified" if args.check else "Generated", TABLE_ID)


if __name__ == "__main__":
    main()
