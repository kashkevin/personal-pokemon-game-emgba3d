"""Prove closed-game durable recovery with two real modified ROM cores.

Development-only WSL harness; inputs are preserved private copies. The host
stores ordinary saves, and restores happen before a fresh emulator boots.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import secrets

from control_proof import Core, objects, verify_expected
from configure_bridge import configure
from emerald_multiplayer.checkpoint_client import CheckpointClient, CheckpointError
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.flash import LAYOUT_ID, inspect_flash
from emerald_multiplayer.mailbox import inspect_mailbox
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.storage import CheckpointStore


async def wait_connected(companions):
    for _ in range(200):
        if all(c.connected for c in companions):
            return
        await asyncio.sleep(.02)
    raise AssertionError([c.last_error for c in companions])


async def run(args):
    from emerald_multiplayer.checkpoint_mirror import MirrorLease, restore_checkpoint, inspect_mirror
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("use a new private multiplayer-proof output directory")
    root.mkdir(mode=0o700, parents=True)
    manifest = json.loads(args.manifest.read_text())
    config = ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"], heartbeat_interval=.2, idle_timeout=5)
    store = CheckpointStore(root / "world.sqlite3", config.build_id, config.ruleset_id, LAYOUT_ID)
    identities = [store.create_player("Proof " + name) for name in ("A", "B")]
    # Private evidence contains bearer credentials and is never copied into Git.
    (root / "profiles.json").write_text(json.dumps([{"player_id": p.player_id, "display_name": p.display_name, "credential": p.credential.hex()} for p in identities]))
    server = WorldServer(config, store=store)
    await server.start(port=0)
    companions, cores, leases = [], [], []
    evidence = {"build_id": config.build_id, "ruleset_id": config.ruleset_id, "save_profile": LAYOUT_ID, "checks": [], "frames": []}
    def record(name, **fields):
        evidence["checks"].append({"name": name, **fields})
        print(json.dumps({"verified": name, **fields}), flush=True)
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    try:
        saves = [root / "client-a.sav", root / "client-b.sav"]
        original = [args.save_a.read_bytes(), args.save_b.read_bytes()]
        original_snapshots = [inspect_flash(data) for data in original]
        for identity in identities:
            c = Companion(CompanionConfig(args.rom, args.manifest, identity.player_id, identity.display_name, secrets.token_bytes(32), server_port=server.address[1], ipc_port=0, server_credential=identity.credential))
            await c.start()
            companions.append(c)
        await wait_connected(companions)
        clients = [CheckpointClient(c) for c in companions]
        initial = [await c.upload(data, 0) for c, data in zip(clients, original)]
        world_id = companions[0].world_id
        epochs = [c.session_epoch for c in companions]
        record("separate-player-canonical-enrollment", revisions=[m["revision"] for m in initial], container_sha256=[m["sha256"] for m in initial])
        for path, client in zip(saves, clients):
            downloaded = await client.download()
            restore_checkpoint(path, downloaded, world_id=world_id)
            inspect_mirror(path)
        record("validated-mirrors-created-before-boot")

        async def launch(index):
            lease = MirrorLease(saves[index])
            lease.__enter__()
            leases.append(lease)
            c = companions[index]
            script = root / f"bridge-{index}.lua"
            script.write_text(configure(manifest, c.config.token.hex(), c.ipc_address[1], args.bridge.read_text()))
            process = await asyncio.create_subprocess_exec(str(args.harness), str(args.rom), str(saves[index]), str(script), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            core = Core(process, root / f"core-{index}-{len(evidence['frames'])}.log")
            try:
                ready = await asyncio.wait_for(process.stdout.readline(), 20)
                if not ready.startswith(b"READY"):
                    raise RuntimeError("core did not boot")
            except BaseException:
                await core.close()
                raise
            return core

        for i in range(2):
            cores.append(await launch(i))
        async def frames(keys_a=0, keys_b=0, frames=6, repeat=1):
            for _ in range(repeat):
                await asyncio.gather(*(c.command(f"F {k:x} {frames}") for c, k in zip(cores, (keys_a, keys_b))))
                await asyncio.sleep(.02)
        async def boot():
            await frames(frames=50, repeat=20)
            await frames(8, 8, 8)
            await frames(frames=48, repeat=10)
            await frames(8, 8, 8)
            await frames(repeat=30)
            await frames(1, 1, 8)
            await frames(repeat=50)
        async def snapshot(label):
            result = {"clients": []}
            for i, core in enumerate(cores):
                pose, inbound = inspect_mailbox(await core.read(manifest["mailbox_address"], 128))
                raw = await core.read(manifest["debug_object_events_address"], manifest["debug_object_events_size"])
                sprites = await core.read(manifest["debug_sprites_address"], manifest["debug_sprites_size"])
                party = await core.read(manifest["debug_parties_address"], manifest["debug_party_size"])
                sb1 = int.from_bytes(await core.read(manifest["debug_save_block1_ptr_address"], 4), "little")
                saved = await core.read(sb1 + manifest["debug_saved_objects_offset"], 576)
                result["clients"].append({"pose": asdict(pose), "inbound": asdict(inbound), "objects": objects(raw, sprites), "party_sha256": hashlib.sha256(party).hexdigest(), "saved_object_local_ids": [saved[j * 36 + 8] for j in range(16)], "server_connected": companions[i].connected})
                await core.command(f"P {root / (label + '-' + str(i) + '.png')}")
            evidence["frames"].append({"label": label, **result})
            return result
        await boot()
        first = await snapshot("01-canonical-continue")
        verify_expected(first, {"remotes": [1, 1], "activity": [1, 1], "coordinates": [[6, 11], [5, 9]], "peer_positions_match": True, "peer_pixels_match": True})
        record("two-real-ROMs-continue-from-independent-checkpoints")
        await frames(32, 0, 16)
        await frames(repeat=25)
        moved = await snapshot("02-independent-movement")
        verify_expected(moved, {"coordinates": [[5, 11], [5, 9]], "peer_positions_match": True, "peer_pixels_match": True})
        # Normal START menu / SAVE / overwrite confirmation; no save RAM writes.
        await frames(8, 0, 8)
        await frames(repeat=15)
        for _ in range(4):
            await frames(128, 0, 8)
            await frames()
        for _ in range(4):
            await frames(1, 0, 8)
            await frames(repeat=20)
        await snapshot("03-overwrite-confirmation")
        await frames(64, 0, 8)
        await frames(repeat=5)
        await frames(1, 0, 30)
        await frames(repeat=200)
        saved = await snapshot("04-ordinary-save-finished")
        verify_expected(saved, {"activity": [1, 1], "coordinates": [[5, 11], [5, 9]], "saved_remote_ids_empty": True, "party_sha256": [c["party_sha256"] for c in first["clients"]]})
        for core in cores:
            await core.close()
        cores = []
        for lease in leases:
            lease.__exit__(None, None, None)
        leases = []
        new_payload = saves[0].read_bytes()
        changed = inspect_flash(new_payload)
        assert changed.state_sha256 != original_snapshots[0].state_sha256
        updated = await clients[0].upload(new_payload, 1)
        assert (await clients[1].info()) == initial[1]
        record("normal-save-A-revision2-B-revision1-unchanged", checkpoint=updated)
        try:
            await clients[0].upload(original[0], 1)
        except CheckpointError as error:
            assert error.code == "revision_conflict", error.code
        else:
            raise AssertionError("stale checkpoint unexpectedly replaced newer save")
        record("stale-local-revision-rejected-with-session-retained", connected=companions[0].connected)
        port = server.address[1]
        await server.close()
        store.close()
        store = CheckpointStore(root / "world.sqlite3", config.build_id, config.ruleset_id, LAYOUT_ID)
        server = WorldServer(config, store=store)
        await server.start(port=port)
        await asyncio.sleep(.3)
        await wait_connected(companions)
        assert companions[0].world_id == world_id
        assert all(c.session_epoch > epoch for c, epoch in zip(companions, epochs))
        downloaded = [await c.download() for c in clients]
        assert downloaded[0].metadata == updated and downloaded[0].payload == new_payload
        assert downloaded[1].metadata == initial[1] and downloaded[1].payload == original[1]
        record("durable-host-restart-preserves-world-and-both-independent-saves")
        saves[0].write_bytes(b"damaged-local-copy")
        for path, checkpoint in zip(saves, downloaded):
            restore_checkpoint(path, checkpoint, world_id=world_id)
            inspect_mirror(path)
        assert saves[0].read_bytes() == new_payload
        record("damaged-local-mirror-recovered-from-canonical-checkpoint")
        for i in range(2):
            cores.append(await launch(i))
        await boot()
        recovered = await snapshot("05-fresh-recovered-continue")
        verify_expected(recovered, {"remotes": [1, 1], "activity": [1, 1], "coordinates": [[5, 11], [5, 9]], "peer_positions_match": True, "peer_pixels_match": True, "party_sha256": [c["party_sha256"] for c in first["clients"]], "saved_remote_ids_empty": True})
        record("fresh-ROM-recovery-position-party-avatars-preserved")
        store.integrity_check()
        evidence["passed"] = True
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    finally:
        await asyncio.gather(*(c.close() for c in cores), return_exceptions=True)
        for lease in leases:
            lease.__exit__(None, None, None)
        await asyncio.gather(*(c.close() for c in companions), return_exceptions=True)
        await server.close()
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "manifest", "harness", "save-a", "save-b", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2] / "bridge/mgba.lua")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
