"""Read display facts from pinned C text; do not import or run game code."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unicodedata


TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*.*?\*/|[{}]', re.S)


def block(text, start):
    depth = 0
    beginning = None
    for token in TOKEN.finditer(text, start):
        if token.group() == "{":
            if beginning is None:
                if text[start:token.start()].strip():
                    return ""  # A macro needs a separate explicit adapter.
                beginning = token.end()
            depth += 1
        elif token.group() == "}":
            depth -= 1
            if beginning is not None and depth == 0:
                return text[beginning:token.start()]
    raise ValueError("unterminated source initializer")


def ascii_label(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    if not value or not value.isprintable() or len(value) > 32:
        raise ValueError("display label requires an explicit adapter")
    return value


def names(constants, data, prefix, macro, maximum):
    symbols = {name: int(number) for name, number in re.findall(
        rf"\b({prefix}_[A-Z0-9_]+)\s*=\s*(\d+)\s*,", constants)
        if int(number) <= maximum}
    found = {}
    for entry in re.finditer(rf"^\s*\[({prefix}_[A-Z0-9_]+)\]\s*=", data, re.M):
        name = entry.group(1)
        if name not in symbols:
            continue
        values = set(re.findall(rf'\.name\s*=\s*{macro}\("([^"\\\n]+)"\)', block(data, entry.end())))
        found.setdefault(symbols[name], set()).update(values)
    # Ambiguous conditional names and computed/macro IDs stay visibly numeric.
    return {number: ascii_label(next(iter(values))) for number, values in sorted(found.items()) if len(values) == 1}


def generate(engine, output, provenance):
    files = ("include/constants/moves.h", "src/data/moves_info.h", "include/constants/items.h",
             "src/data/items.h", "include/constants/pokemon.h", "include/pokemon.h", "src/pokemon.c", "charmap.txt")
    raw = {name: (engine / name).read_bytes() for name in files}
    text = {name: value.decode("utf-8") for name, value in raw.items()}
    base = subprocess.check_output(["git", "-C", str(engine), "rev-parse", "HEAD"], text=True).strip()
    upstream = "bb1093a7c72d3961d9a37d8e02ad2abc2c866682"
    subprocess.run(["git", "-C", str(engine), "merge-base", "--is-ancestor", upstream, base], check=True)
    moves = names(text[files[0]], text[files[1]], "MOVE", "COMPOUND_STRING", 621)
    items = names(text[files[2]], text[files[3]], "ITEM", "ITEM_NAME", 1023)
    natures = {int(number): name.title() for name, number in re.findall(
        r"^#define NATURE_([A-Z]+)\s+(\d+)\b", text[files[4]], re.M) if int(number) < 25}
    if set(natures) != set(range(25)) or len(moves) < 600 or len(items) < 600:
        raise ValueError("pinned display source coverage changed")
    if not re.search(r"^#define SHINY_ODDS 8\b", text[files[4]], re.M):
        raise ValueError("stored shiny display adapter needs review")
    chars = {}
    # The first charmap block is the Latin alphabet. Japanese codes overlap.
    latin = text["charmap.txt"].split("'あ'", 1)[0]
    for char, number in re.findall(r"^'([^'\\])'\s*=\s*([0-9A-F]{2})\s*$", latin, re.M):
        folded = unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode("ascii")
        if len(folded) == 1 and 32 <= ord(folded) <= 126:
            chars[int(number, 16)] = folded
    # Apostrophe and typographic quote aliases share source-defined codes.
    chars.update({0xB1: '"', 0xB2: '"', 0xB3: "'", 0xB4: "'"})
    sections = ['"""Generated display facts; docs/trade-labels-provenance.json records sources."""\n']
    for name, value in (("MOVE_NAMES", moves), ("ITEM_NAMES", items), ("NATURE_NAMES", natures), ("LATIN_CHARS", chars)):
        sections.append("\n" + name + " = {\n")
        sections.extend(f"    {key}: {json.dumps(label, ensure_ascii=True)},\n" for key, label in sorted(value.items()))
        sections.append("}\n")
    encoded = "".join(sections).encode("ascii")
    receipt = dict(format="emerald-trade-display-facts-v1", engine_base=base, incorporated_upstream=upstream,
                   input_sha256={name: hashlib.sha256(value).hexdigest() for name, value in raw.items()},
                   moves=len(moves), items=len(items), natures=len(natures),
                   output_sha256=hashlib.sha256(encoded).hexdigest(),
                   scope="Display only; ambiguous or computed IDs use explicit numeric fallback. No acquisition changes.")
    output.write_bytes(encoded)
    provenance.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("moves", "items", "natures", "output_sha256")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("provenance", type=Path)
    args = parser.parse_args()
    generate(args.engine, args.output, args.provenance)
