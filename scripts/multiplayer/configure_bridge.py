"""Write a private mGBA bridge script for one already-running loopback companion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


from emerald_multiplayer.bridge_config import configure


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2] / "bridge/mgba.lua")
    args = parser.parse_args()
    content = configure(json.loads(args.manifest.read_text(encoding="utf-8")), args.token,
                        args.port, args.bridge.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print(f"Private bridge script written: {args.output}")


if __name__ == "__main__":
    main()
