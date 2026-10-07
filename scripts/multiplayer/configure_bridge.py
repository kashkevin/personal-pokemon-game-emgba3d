"""Write a private mGBA bridge script for one already-running loopback companion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


def configure(manifest: dict, token: str, port: int, bridge: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", token) or not 1 <= port <= 65535:
        raise ValueError("Invalid bridge token or port")
    address = manifest["mailbox_address"]
    if type(address) is not int or address % 4 or not 0x02000000 <= address <= 0x02040000 - 128:
        raise ValueError("Invalid mailbox address")
    if manifest["abi_version"] != 1 or manifest["mailbox_size"] != 128:
        raise ValueError("Unsupported mailbox ABI")
    crc = manifest["rom_crc32"]
    if not isinstance(crc, str) or not re.fullmatch(r"[0-9a-f]{8}", crc):
        raise ValueError("Invalid ROM CRC")
    size = manifest["rom_size"]
    if type(size) is not int or not 192 <= size <= 32 * 1024 * 1024:
        raise ValueError("Invalid ROM size")
    return (
        f'EMERALD_BRIDGE = {{address={address}, rom_size={size}, rom_crc32="{crc}", '
        f'port={port}, token="{token}"}}\n' + bridge
    )


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
