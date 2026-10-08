"""Developer/friend TLS path check; no login, game join or firewall changes."""
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from emerald_multiplayer.launcher_gui import private_directory
from emerald_multiplayer.network_diagnostics import probe_invitation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("invitation", type=Path)
    args = parser.parse_args()
    result = asyncio.run(probe_invitation(args.invitation, private_directory() / "network-checks"))
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.tls_verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
