"""Extract the standard-species friendship table from the installed engine pin.

This reads Git objects, never edits the checkout/configuration, and invokes the
native compiler only on temporary probes. No ROM, graphics or save is produced.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile


REVISION = "bb1093a7c72d3961d9a37d8e02ad2abc2c866682"
TABLE_ID = "rhh-bb1093a7-gen6-standard-friendship-v1"
ARCHIVE_PATHS = ("include", "src/data/pokemon/species_info.h",
                 "src/data/pokemon/species_info", "src/data/pokemon/egg_data.h")
PROBE = '''#define TRUE 1
#define FALSE 0
#include "metaprogram.h"
#include "constants/global.h"
#include "constants/pokemon.h"
#include "constants/species.h"
#include "constants/pokedex.h"
#undef P_UPDATED_FRIENDSHIP
#define P_UPDATED_FRIENDSHIP GEN_6
#include "src/data/pokemon/species_info.h"
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(args, **kwargs):
    result = subprocess.run(args, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    if result.returncode or result.stderr:
        raise ValueError(f"the friendship probe exited {result.returncode}: "
                         + result.stderr.decode("utf-8", "replace"))
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
                raise ValueError("pinned friendship inputs must be ordinary files")
            target = root.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(source.extractfile(member).read())


def species_names(source):
    pairs = [(name, int(value)) for name, value in re.findall(
        r"^\s*(SPECIES_[A-Z0-9_]+)\s*=\s*(\d+)\s*,", source, re.M) if 1 <= int(value) <= 721]
    names = dict(pairs)
    if len(pairs) != 721 or len(names) != 721 or {value for _, value in pairs} != set(range(1, 722)):
        raise ValueError("the pinned native standard species IDs must cover 1 through 721 exactly once")
    return tuple(name for name, _ in sorted(pairs, key=lambda pair: pair[1]))


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
                return source[start+1:index]
    raise ValueError("unterminated preprocessed species initializer")


def extract_fields(preprocessed, names):
    """Extract only two fields; the C compiler evaluates friendship expressions."""
    wanted = set(names)
    entries = {}
    for match in re.finditer(r"\[(SPECIES_[A-Z0-9_]+)\]\s*=\s*\{", preprocessed):
        name = match.group(1)
        if name not in wanted:
            continue
        if name in entries:
            raise ValueError("duplicate preprocessed standard species")
        body = _body(preprocessed, match.end()-1)
        friendship = re.findall(r"\.friendship\s*=\s*([^,]+),", body)
        national = re.findall(r"\.natDexNum\s*=\s*(NATIONAL_DEX_[A-Z0-9_]+)\s*,", body)
        if len(friendship) != 1 or len(national) != 1:
            raise ValueError("standard species requires exactly one friendship and national dex field: " + name)
        expression = friendship[0].strip()
        # Preprocessing must have resolved every name. Keep this tiny numeric
        # expression surface; never compile a field containing arbitrary code.
        if not re.fullmatch(r"[0-9\s()?:<>=!&|+*/%~-]+", expression):
            raise ValueError("friendship expression contains unresolved or unexpected syntax: " + name)
        entries[name] = (expression, national[0])
    if set(entries) != wanted:
        raise ValueError("preprocessing omitted standard species: " + ",".join(sorted(wanted-set(entries))))
    return tuple(entries[name] for name in names)


def used_sources(preprocessed, root):
    sources = {}
    for filename in re.findall(r'^#\s+\d+\s+"([^"\n]+)"', preprocessed, re.M):
        if filename.startswith("<"):
            continue
        path = Path(filename)
        path = path if path.is_absolute() else root / path
        path = path.resolve()
        if path == root / "friendship-probe.c":
            continue
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError("friendship preprocessing read outside the pinned source archive") from error
        sources[relative] = digest(path.read_bytes())
    return dict(sorted(sources.items()))


def compile_probe(root, compiler, objcopy, names, fields):
    # National/native identity and bounds are checked by the native compiler.
    # The resulting section contains one byte per standard national species.
    checks, values = [], []
    for number, (name, (expression, national)) in enumerate(zip(names, fields), 1):
        checks.append(f'_Static_assert({name} == {number} && {national} == {number}, "species mapping");')
        checks.append(f'_Static_assert(({expression}) >= 0 && ({expression}) <= 255, "friendship byte");')
        values.append(expression)
    source = ('#include "constants/species.h"\n#include "constants/pokedex.h"\n'
              + "\n".join(checks) + '\nconst unsigned char table[721] __attribute__((section(".gen6_friendship"), used)) = {\n'
              + ",\n".join(values) + "\n};\n")
    (root / "friendship-values.c").write_text(source, encoding="ascii")
    run([compiler, "-std=c11", "-ffreestanding", "-fno-lto", "-Werror", "-Iinclude", "-c",
         "friendship-values.c", "-o", "friendship-values.o"], cwd=root)
    run([objcopy, "-O", "binary", "--only-section=.gen6_friendship", "friendship-values.o", "friendship-values.bin"], cwd=root)
    values = (root / "friendship-values.bin").read_bytes()
    if len(values) != 721:
        raise ValueError("compiled friendship table has an unexpected byte size")
    return values, digest(source.encode("ascii"))


def generate(engine, compiler, objcopy):
    archive = run(["git", "-C", str(engine), "archive", "--format=tar", REVISION, *ARCHIVE_PATHS])
    with tempfile.TemporaryDirectory(prefix="pokemon-gen6-friendship-") as temporary:
        root = Path(temporary).resolve()
        extract_headers(archive, root)
        # This is preprocessing, not compilation of the species structure.
        # Avoid irrelevant libc typedef headers while retaining the engine's
        # exact boolean conditions and proving these two substituted macros.
        native_defines = (root / "include/gba/defines.h").read_text(encoding="utf-8")
        for name, value in (("TRUE", "1"), ("FALSE", "0")):
            if re.findall(r"^#define\s+" + name + r"\s+(\d+)\s*$", native_defines, re.M) != [value]:
                raise ValueError("pinned native boolean definition changed: " + name)
        (root / "friendship-probe.c").write_text(PROBE, encoding="ascii")
        expanded = run([compiler, "-E", "-x", "c", "-nostdinc", "-Iinclude", "-I.",
                        "friendship-probe.c"], cwd=root).decode("utf-8")
        names = species_names((root / "include/constants/species.h").read_text(encoding="utf-8"))
        fields = extract_fields(expanded, names)
        values, value_probe_hash = compile_probe(root, compiler, objcopy, names, fields)
        sources = used_sources(expanded, root)
        sources["include/gba/defines.h"] = digest((root / "include/gba/defines.h").read_bytes())
    evidence = dict(schema=1, table_id=TABLE_ID, engine_revision=REVISION,
        source_url=f"https://github.com/rh-hideout/pokeemerald-expansion/tree/{REVISION}",
        config_override={"P_UPDATED_FRIENDSHIP": "GEN_6"},
        species_scope="standard native and national IDs 1..721 only",
        source_files=sources, probe_sha256=digest(PROBE.encode("ascii")),
        value_probe_sha256=value_probe_hash, generator_sha256=digest(Path(__file__).read_bytes()),
        compiler=run([compiler, "--version"]).decode().splitlines()[0],
        objcopy=run([objcopy, "--version"]).decode().splitlines()[0],
        values_sha256=digest(values),
        entries=[[number, name, national, value] for number, (name, (_, national), value)
                 in enumerate(zip(names, fields, values), 1)])
    module = ('"""Generated from pinned RHH species facts; see docs/gen6-friendship-table.md."""\n'
              + f'TABLE_ID = "{TABLE_ID}"\nENGINE_REVISION = "{REVISION}"\n'
              + f'VALUES_SHA256 = "{digest(values)}"\nVALUES = bytes.fromhex(\n'
              + "\n".join(f'    "{values[offset:offset+32].hex()}"' for offset in range(0, len(values), 32))
              + '\n)\n\n\ndef base_friendship(species):\n'
              + '    """Return the pinned Gen6 base for a standard native species ID."""\n'
              + '    if type(species) is not int or not 1 <= species <= 721:\n'
              + '        raise ValueError("Gen6 friendship requires a standard species ID from 1 through 721")\n'
              + '    return VALUES[species - 1]\n')
    return module.encode("ascii"), (json.dumps(evidence, sort_keys=True, indent=2)+"\n").encode("ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
                raise ValueError("generated friendship output differs: " + str(path))
        else:
            with path.open("xb") as output:
                output.write(expected)
    print("Verified" if args.check else "Generated", TABLE_ID, "(721 standard species)")


if __name__ == "__main__":
    main()
