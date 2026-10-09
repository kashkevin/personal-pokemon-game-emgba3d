"""Inventory tracked native art without importing, changing, or rendering assets.

Run against the existing engine checkout. The output contains repository-relative
paths, hashes and PNG headers, never game/save bytes or private absolute paths.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


ROOTS = ("graphics", "data/tilesets")
SOURCE_PREFIXES = (
    "src/data/object_events/", "src/data/graphics/", "src/data/battle_anims/",
    "src/data/tilesets/", "src/data/field_effects/", "include/config/overworld",
    "include/config/wild_encounter", "include/config/follower",
)
SOURCE_FILES = (
    "include/constants/species.h", "include/constants/event_objects.h",
    "include/event_object_movement.h", "src/event_object_movement.c",
    "src/field_player_avatar.c", "src/field_effect.c", "src/field_effect_helpers.c",
    "src/field_weather.c", "src/field_weather_effect.c", "src/tileset_anims.c",
    "src/palette.c", "src/follower_helper.c", "src/follower_npc.c",
    "src/wild_encounter_ow.c", "data/scripts/follower.inc",
    "graphics_file_rules.mk", "spritesheet_rules.mk", "CREDITS.md", "docs/CREDITS.md",
)


def git(engine: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(engine), *args])


def fingerprint(engine: Path, relative: str) -> dict:
    path = engine / relative
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"inventory requires a regular tracked file: {relative}")
    data = path.read_bytes()
    row = {"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if path.suffix.lower() == ".png":
        if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise ValueError(f"invalid PNG header: {relative}")
        width, height, depth, color = struct.unpack(">IIBB", data[16:26])
        row["png"] = {"width": width, "height": height, "bit_depth": depth, "color_type": color}
    return row


def inventory(engine: Path) -> dict:
    tracked = sorted(p.decode("utf-8") for p in git(engine, "ls-files", "-z").split(b"\0") if p)
    names = [p for p in tracked if any(p.startswith(root + "/") for root in ROOTS)]
    # Report source modifications separately; ignored build products do not become art.
    status = git(engine, "status", "--porcelain=v1", "--untracked-files=all", "--", *ROOTS).decode("utf-8")
    assets = [fingerprint(engine, p) for p in names]
    sources = [fingerprint(engine, p) for p in tracked if p in SOURCE_FILES or p.startswith(SOURCE_PREFIXES)]
    groups: dict[str, list[dict]] = {}
    for row in assets:
        parts = row["path"].split("/")
        group = "/".join(parts[:2]) if parts[0] == "graphics" else "/".join(parts[:3])
        groups.setdefault(group, []).append(row)
    # Directory-name matches are discoverability, not an assertion of complete art
    # or runtime species support. Species with shared/form directories stay explicit.
    species_text = (engine / "include/constants/species.h").read_text(encoding="utf-8")
    species = []
    for name, value in re.findall(r"\bSPECIES_([A-Z0-9_]+)\s*=\s*(\d+)", species_text):
        if not 1 <= int(value) <= 721:
            continue
        prefix = "graphics/pokemon/" + name.lower() + "/"
        files = [p for p in names if p.startswith(prefix)]
        kinds = {Path(p).name for p in files}
        species.append({"species_id": int(value), "constant": "SPECIES_" + name,
                        "directory": prefix.rstrip("/") if files else None,
                        "files": len(files),
                        "battle_front_candidates": sorted(k for k in kinds if k.startswith(("front", "anim_front")) and k.endswith(".png")),
                        "battle_back_candidates": sorted(k for k in kinds if k.startswith("back") and k.endswith(".png")),
                        "overworld_candidates": sorted(p for p in files if Path(p).name == "overworld.png"),
                        "runtime_coverage": "UNKNOWN"})
    if len(species) != 721 or len({r["species_id"] for r in species}) != 721:
        raise ValueError("species enum does not give exactly one standard ID 1..721")
    config = []
    for path in tracked:
        if path.startswith("include/config/") and any(s in path for s in ("overworld", "wild_encounter", "follower")):
            for number, line in enumerate((engine / path).read_text(encoding="utf-8").splitlines(), 1):
                if line.startswith("#define "):
                    config.append({"path": path, "line": number, "text": line})
    if status != git(engine, "status", "--porcelain=v1", "--untracked-files=all", "--", *ROOTS).decode("utf-8"):
        raise ValueError("asset worktree changed during inventory; retry after edits stop")
    return {"schema": 1, "engine_base_commit": git(engine, "rev-parse", "HEAD").decode().strip(),
            "scope": "tracked graphics and data/tilesets in current checkout; source assets only",
            "asset_worktree_status": status.splitlines(), "runtime_coverage": "UNKNOWN",
            "total_files": len(assets), "total_bytes": sum(r["bytes"] for r in assets),
            "extensions": dict(sorted(Counter(Path(p).suffix.lower() for p in names).items())),
            "groups": [{"path": key, "files": len(rows), "bytes": sum(r["bytes"] for r in rows)} for key, rows in sorted(groups.items())],
            "standard_species_directory_audit": sorted(species, key=lambda r: r["species_id"]),
            "animation_and_configuration_sources": sources, "configuration_definitions": config,
            "assets": assets}


def markdown(data: dict) -> str:
    species = data["standard_species_directory_audit"]
    lines = ["# Generated native graphics file inventory", "",
             "Generated by `scripts/inventory_graphics.py`; see [interpretation and reuse review](graphics-resource-inventory.md).", "",
             f"Engine base: `{data['engine_base_commit']}`. Tracked asset worktree status: "
             + ("clean." if not data["asset_worktree_status"] else "modified; inspect JSON."), "",
             f"{data['total_files']:,} tracked files, {data['total_bytes']:,} bytes. "
             "The JSON lists every path, byte count, SHA-256 and PNG dimensions. Generated build products are excluded.", "",
             f"Standard species directory names resolve for {sum(r['directory'] is not None for r in species)}/721 IDs. "
             "This is a filename audit, not proof of palette, form, animation or playable completeness.", "",
             "| Asset group | Files | Bytes |", "| --- | ---: | ---: |"]
    lines += [f"| `{r['path']}` | {r['files']:,} | {r['bytes']:,} |" for r in data["groups"]]
    lines += ["", "## Player state sheets", "", "| File | PNG dimensions |", "| --- | --- |"]
    for row in data["assets"]:
        if any(row["path"].startswith(f"graphics/object_events/pics/people/{p}/") for p in ("brendan", "may")) and "png" in row:
            lines.append(f"| `{row['path']}` | {row['png']['width']} × {row['png']['height']} |")
    unresolved = [r["constant"] for r in species if r["directory"] is None]
    lines += ["", "## Unresolved direct directory names", "",
              ", ".join(f"`{name}`" for name in unresolved) if unresolved else "None.", "",
              "Shared folders, form names and source mappings require separate interpretation. "
              "No missing directory is labeled a missing Pokémon. No asset was copied or modified.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="compare existing outputs byte-for-byte without writing")
    args = parser.parse_args()
    data = inventory(args.engine)
    outputs = {args.json: json.dumps(data, ensure_ascii=False, indent=2) + "\n", args.markdown: markdown(data)}
    for path, value in outputs.items():
        raw = value.encode("utf-8")
        if args.check:
            if path.read_bytes() != raw:
                raise SystemExit(f"inventory output differs: {path.name}")
        else:
            path.write_bytes(raw)
    print(f"{'Verified' if args.check else 'Wrote'} {data['total_files']} asset records; asset changes: {len(data['asset_worktree_status'])}")


if __name__ == "__main__":
    main()
