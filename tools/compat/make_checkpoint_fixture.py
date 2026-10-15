#!/usr/bin/env python3
"""Write a checkpoint database (the host's copy of each player's save) with the code of an OLD checkout (Update 23).

    PYTHONPATH=/tmp/old/src python3 tools/compat/make_checkpoint_fixture.py tests/fixtures/compat/checkpoints_u14

Two players, three and one revisions of a synthetic payload (random bytes of the real save size: no real save is used).
The credential of each player is written to credentials.json next to the database, so the test can authenticate.
"""
import json
import random
import sys
from pathlib import Path

from emerald_multiplayer.storage import CheckpointStore

BUILD, RULES, PROFILE = "compat-build", "compat-rules", "compat-profile"
SAVE_SIZE = 131072   # the GBA save


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "world.sqlite3"
    for extra in out.glob("world.sqlite3*"):
        extra.unlink()
    store = CheckpointStore(path, BUILD, RULES, PROFILE)
    store.begin_server_boot()
    rng = random.Random(14)
    credentials = {}
    payloads = {}
    for name, revisions in (("ALICE", 3), ("BOB", 1)):
        identity = store.create_player(name)
        lease = store.acquire_lease(identity.player_id, identity.credential)
        credentials[name] = {"player_id": identity.player_id, "credential": identity.credential.hex()}
        for revision in range(revisions):
            payload = bytes(rng.getrandbits(8) for _ in range(SAVE_SIZE))
            store.commit_checkpoint(identity.player_id, lease, f"request-{name}-{revision}", revision, payload, BUILD, RULES, PROFILE)
            payloads[f"{name}-{revision + 1}"] = payload.hex()[:64]  # a prefix is enough to recognise it
    store.close()
    (out / "credentials.json").write_text(json.dumps({"players": credentials, "payload_prefixes": payloads,
                                                       "build": BUILD, "rules": RULES, "profile": PROFILE}, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
