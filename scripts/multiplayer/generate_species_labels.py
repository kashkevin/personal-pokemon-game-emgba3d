"""Extract display-name facts from native source text, without compiling it.

This is deliberately not a C preprocessor. It accepts only a unique literal
speciesName for each standard ID, following textual shared-info macros. Missing
or conflicting names stop generation rather than guessing a translated name.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unicodedata


TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*.*?\*/|[{}]', re.S)
ENTRY = re.compile(r"^\s*\[(SPECIES_[A-Z0-9_]+)\]\s*=", re.M)
NAME = re.compile(r'\.speciesName\s*=\s*_\("([^"\n\\]+)"\)')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def body_after(text, start):
    invocation = re.match(r"\s*([A-Z][A-Z0-9_]*(?:\([^;\n{}]*\))?)\s*,", text[start:])
    if invocation is not None:
        return invocation.group(1)
    depth = 0
    beginning = None
    for token in TOKEN.finditer(text, start):
        if token.group() == "{":
            if beginning is None:
                if text[start:token.start()].strip():
                    raise ValueError("species entry needs an explicit source initializer")
                beginning = token.end()
            depth += 1
        elif token.group() == "}":
            depth -= 1
            if beginning is not None and depth == 0:
                return text[beginning:token.start()]
    raise ValueError("unterminated species initializer")


def macro_definitions(text):
    definitions = {}
    lines = iter(text.splitlines())
    for line in lines:
        match = re.match(r"^#define\s+([A-Z][A-Z0-9_]*)(?:\([^)]*\))?\s+(.*)", line)
        if match is None:
            continue
        name, body = match.groups()
        while body.rstrip().endswith("\\"):
            body = body.rstrip()[:-1] + "\n" + next(lines)
        definitions.setdefault(name, []).append(body)
    return definitions


def literal_names(body, macros, visited=frozenset()):
    names = set(NAME.findall(body))
    # Only macro definitions from these species files are traversed; no C code,
    # compiler, module import, shell or conditional expression is evaluated.
    for name in set(re.findall(r"\b[A-Z][A-Z0-9_]*\b", body)) & (macros.keys() - visited):
        for definition in macros[name]:
            names.update(literal_names(definition, macros, visited | {name}))
    return names


def display_name(name):
    value = name.replace("♀", " F").replace("♂", " M")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    if not value or not value.isprintable() or len(value) > 16:
        raise ValueError("native species name needs an explicit display adapter")
    return value


def generate(engine, output, provenance):
    engine_base = subprocess.check_output(["git", "-C", str(engine), "rev-parse", "HEAD"], text=True).strip()
    upstream_base = "bb1093a7c72d3961d9a37d8e02ad2abc2c866682"
    lineage = subprocess.run(["git", "-C", str(engine), "merge-base", "--is-ancestor", upstream_base, engine_base],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if lineage.returncode != 0:
        raise ValueError("engine does not retain the incorporated RHH source lineage")
    constants_path = engine / "include/constants/species.h"
    paths = [constants_path, *sorted((engine / "src/data/pokemon/species_info").glob("gen_*_families.h"))]
    sources = {str(path.relative_to(engine)): path.read_bytes() for path in paths}
    constants = {name: int(value) for name, value in re.findall(
        r"\b(SPECIES_[A-Z0-9_]+)\s*=\s*(\d+)\s*,", sources[str(constants_path.relative_to(engine))].decode("utf-8"))
        if 1 <= int(value) <= 721}
    if len(constants) != 721 or set(constants.values()) != set(range(1, 722)):
        raise ValueError("standard species numbering differs from 1 through 721")
    texts = [data.decode("utf-8") for name, data in sources.items() if name != "include/constants/species.h"]
    macros = {}
    for text in texts:
        for name, definitions in macro_definitions(text).items():
            macros.setdefault(name, []).extend(definitions)
    names = {}
    for text in texts:
        for entry in ENTRY.finditer(text):
            symbol = entry.group(1)
            if symbol not in constants:
                continue
            try:
                found = literal_names(body_after(text, entry.end()), macros)
            except ValueError as error:
                raise ValueError(f"{symbol}: {error}") from error
            if len(found) != 1 or constants[symbol] in names:
                raise ValueError(f"ambiguous/missing standard label: {symbol}: {sorted(found)}")
            names[constants[symbol]] = display_name(found.pop())
    if set(names) != set(range(1, 722)):
        raise ValueError("not every standard species has a source-derived label")
    lines = ['"""Source-derived Gen 1–6 menu labels; no eligibility or battle rules.\n',
             'Generated by scripts/multiplayer/generate_species_labels.py.\n',
             'Provenance: docs/species-labels-provenance.json.\n"""\n\n', 'NAMES = (\n    "Unknown",\n']
    lines.extend(f"    {json.dumps(names[index], ensure_ascii=True)},  # {index}\n" for index in range(1, 722))
    lines.append(')\n\n\ndef species_label(species):\n'
                 '    """Known standard IDs use names; unknown IDs stay explicit."""\n'
                 '    if type(species) is int and 1 <= species <= 721:\n'
                 '        return NAMES[species]\n'
                 '    return f"No.{species}"\n')
    data = "".join(lines).encode("utf-8")
    output.write_bytes(data)
    record = dict(format="source-derived-species-menu-labels-v1", standard_species=721,
        engine_base=engine_base, upstream_base=upstream_base,
        source_files={name: digest(raw) for name, raw in sources.items()},
        output_sha256=digest(data), generated_without_native_execution=True,
        display_adaptations="ASCII accent folding; Nidoran gender symbols become F/M")
    provenance.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(dict(labels=len(names), output_sha256=record["output_sha256"])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    args = parser.parse_args()
    generate(args.engine, args.output, args.provenance)
