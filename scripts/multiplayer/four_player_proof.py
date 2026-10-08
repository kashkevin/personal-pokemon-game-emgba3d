"""Ordinary New Game preparation and four actual libmGBA-client foundation proof.

Only joypad input changes gameplay. The production bridge uses its bounded
mailboxes; core reads and framebuffers are diagnostic. This does not qualify
cross-player trades, network battles, Windows packaging, or Internet play.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import secrets
import sys
from uuid import uuid4

from configure_bridge import configure
from control_proof import objects
from live_checkpoint_proof import LockedCore, Pump
from emerald_multiplayer.checkpoint_client import CheckpointClient
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.mailbox import inspect_mailbox
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.protocol import PROTOCOL_VERSION, encode_message, read_message
from emerald_multiplayer.server import ServerConfig, WorldServer


async def run(args):
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    root.mkdir(mode=0o700, parents=True)
    manifest = json.loads(args.manifest.read_text())
    rom_bytes = args.rom.read_bytes()
    if hashlib.sha256(rom_bytes).hexdigest() != manifest["rom_sha256"]:
        raise ValueError("frozen ROM differs from its manifest")
    rom = root / "proof.gba"
    rom.write_bytes(rom_bytes)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    preparation = args.phase == "prepare"
    source_paths = [args.save_a, args.save_b] if preparation else [args.save_a, args.save_b, args.save_c, args.save_d]
    if any(p is None for p in source_paths):
        raise ValueError("foundation phase requires four independent source saves")
    source_bytes = [p.read_bytes() for p in source_paths]
    source_hashes = [hashlib.sha256(b).hexdigest() for b in source_bytes]
    source_metadata = [inspect_flash(b).metadata for b in source_bytes]
    if len(set(m.trainer_id for m in source_metadata)) != len(source_metadata):
        raise ValueError("source trainers must be genuinely distinct")
    evidence = dict(scope="four actual cores foundation; trades and network battles pending",
        phase=args.phase, engine_commit=manifest["engine_commit"], build_id=manifest["rom_sha256"],
        sources=[dict(path=str(p), sha256=h) for p, h in zip(source_paths, source_hashes)],
        commands=[], snapshots=[], checks=[], passed=False)
    diagnostics = json.loads(args.diagnostics.read_text()) if args.diagnostics else {}
    if diagnostics:
        evidence["read_only_diagnostics"] = diagnostics

    def persist():
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")

    def record(name, **fields):
        row = dict(verified=name, **fields)
        evidence["checks"].append(row)
        persist()
        print(json.dumps(row), flush=True)

    count = 2 if preparation else 4
    store = None if preparation else OwnershipCheckpointStore(root / "world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
    identities = [None] * count if preparation else [store.create_player("Four " + name) for name in "ABCD"]
    if store is not None:
        for identity, payload in zip(identities, source_bytes):
            store.enroll_player(identity.player_id, payload)
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"], heartbeat_interval=.2, idle_timeout=12), store=store)
    await server.start(port=0)
    cores, companions, leases, coordinators = [], [], [], []
    saves = [root / ("client-" + name + ".sav") for name in ("cd" if preparation else "abcd")]
    revisions = [0] * count
    canonical = [None] * count
    pump = None
    core_generation = 0

    async def launch(i):
        lease = MirrorLease(saves[i])
        lease.__enter__()
        leases.append(lease)
        companion = companions[i]
        script = root / f"bridge-{i}.lua"
        script.write_text(configure(manifest, companion.config.token.hex(), companion.ipc_address[1], args.bridge.read_text()))
        process = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(saves[i]), str(script),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        core = LockedCore(process, root / f"core-{i}-{core_generation}.log")
        cores.append(core)
        if not (await asyncio.wait_for(process.stdout.readline(), 30)).startswith(b"READY"):
            raise RuntimeError(f"core startup failed: {core.log}")

    async def advance(keys, frames):
        if len(keys) != count or any(type(k) is not int or not 0 <= k <= 1023 for k in keys):
            raise ValueError("one valid GBA key mask per client required")
        if type(frames) is not int or not 0 <= frames <= 5000:
            raise ValueError("frames must be 0..5000")
        for start in range(0, frames, 24):
            await asyncio.gather(*(c.command(f"F {k:x} {min(24, frames-start)}") for c, k in zip(cores, keys)))
            await asyncio.sleep(.003)

    async def boot_continue():
        for keys, total in ((0, 1000), (8, 8), (0, 480), (8, 8), (0, 180), (1, 8), (0, 300)):
            await advance([keys] * count, total)

    async def ready():
        for _ in range(500):
            if all(c.connected and c._bridge is not None and c._bridge.save_capable for c in companions):
                return
            await asyncio.sleep(.025)
        raise AssertionError([(c.connected, c.last_error) for c in companions])

    async def snapshot(label):
        if not isinstance(label, str) or not label.isascii() or not 1 <= len(label) <= 64 or not all(c.isalnum() or c in "-_" for c in label):
            raise ValueError("short ASCII snapshot label required")
        clients = []
        for i, core in enumerate(cores):
            frame = await core.command("F 0 0")
            try:
                pose, inbound = inspect_mailbox(await core.read(manifest["mailbox_address"], 128))
                item = dict(pose=asdict(pose), inbound=asdict(inbound))
            except ValueError as e:
                item = dict(mailbox_pending=str(e))
            item.update(core_pid=core.process.pid, frame=int(frame.split()[1]),
                connected=companions[i].connected, lease_epoch=companions[i].session_epoch,
                incarnation=companions[i].save_incarnation, revision=revisions[i])
            if diagnostics.get("main_in_battle_address"):
                flags = (await core.read(diagnostics["main_in_battle_address"], 1))[0]
                item["native_in_battle"] = bool(flags & diagnostics["main_in_battle_mask"])
            if "debug_save_block2_ptr_address" in manifest:
                pointer = int.from_bytes(await core.read(manifest["debug_save_block2_ptr_address"], 4), "little")
                if 0x02000000 <= pointer <= 0x02040000 - 14:
                    header = await core.read(pointer, 14)
                    item["native_trainer"] = dict(name=header[:8].hex(), gender=header[8],
                        trainer_id=int.from_bytes(header[10:14], "little"))
            if "debug_object_events_address" in manifest:
                raw = await core.read(manifest["debug_object_events_address"], manifest["debug_object_events_size"])
                sprites = await core.read(manifest["debug_sprites_address"], manifest["debug_sprites_size"]) if "debug_sprites_address" in manifest else None
                item["objects"] = objects(raw, sprites)
            await core.command(f"P {root / (label + '-' + str(i) + '.png')}")
            clients.append(item)
        row = dict(label=label, clients=clients)
        evidence["snapshots"].append(row)
        persist()
        print(json.dumps(dict(label=label, clients=[{k: v for k, v in c.items() if k not in {"inbound", "objects"}} for c in clients])), flush=True)
        return row

    async def checkpoint(i, *, enroll=False):
        receipt = await (coordinators[i].enroll() if enroll else coordinators[i].checkpoint(expected_revision=revisions[i]))
        downloaded = await CheckpointClient(companions[i]).download()
        parsed = inspect_flash(downloaded.payload, save_profile=OWNERSHIP_PROFILE)
        owned = inspect_ownership(parsed)
        assert (owned.world_id, owned.player_id) == (store.metadata.world_id, identities[i].player_id)
        revisions[i] = receipt.metadata["revision"]
        canonical[i] = owned
        record("explicit-enrollment" if enroll else "independent-checkpoint", client=i, revision=revisions[i],
            trainer_id=parsed.metadata.trainer_id, records=[asdict(x) for x in owned.records], receipt=asdict(receipt))

    async def head_metadata():
        return [await CheckpointClient(c).info() for c in companions]

    async def fifth_refusal():
        identity = store.create_player("Refused Fifth")
        reader, writer = await asyncio.open_connection(*server.address)
        try:
            writer.write(encode_message(dict(type="hello", protocol=PROTOCOL_VERSION,
                build_id=manifest["rom_sha256"], ruleset_id=manifest["ruleset_id"],
                player_id=identity.player_id, display_name=identity.display_name,
                credential=identity.credential.hex())))
            await writer.drain()
            refusal = await asyncio.wait_for(read_message(reader), 5)
            assert refusal["type"] == "error" and refusal["code"] == "server_full", refusal
            assert len(server.sessions) == 4
            record("fifth-client-refused-with-four-real-cores-still-connected", error=refusal["code"])
        finally:
            writer.close()
            await writer.wait_closed()

    async def rejoin(i):
        before = await head_metadata()
        epochs = [c.session_epoch for c in companions]
        pids = [c.process.pid for c in cores]
        old = companions[i].config
        port = companions[i].ipc_address[1]
        await companions[i].close()
        for _ in range(200):
            if len(server.sessions) == 3:
                break
            await asyncio.sleep(.02)
        assert len(server.sessions) == 3
        await pump.advance(240)
        companions[i] = Companion(replace(old, ipc_port=port))
        await companions[i].start()
        coordinators[i] = LiveCheckpointCoordinator(companions[i], root / f"private-{i}")
        await ready()
        await pump.advance(240)
        after = await head_metadata()
        assert after == before and pids == [c.process.pid for c in cores]
        assert companions[i].session_epoch > epochs[i]
        assert all(c.session_epoch == epochs[j] for j, c in enumerate(companions) if j != i)
        record("one-client-disconnect-rejoin-retains-all-heads-and-other-leases", client=i, previous_epochs=epochs,
            current_epochs=[c.session_epoch for c in companions], core_pids=pids)

    async def close_cores():
        for core in cores:
            await core.close()
        cores.clear()
        for lease in reversed(leases):
            lease.__exit__(None, None, None)
        leases.clear()

    async def stop_pump():
        nonlocal pump
        if pump is None:
            return
        # Cancelling an outstanding command leaves its reply in stdout. The
        # next read would then mistake that frame reply for a RAM diagnostic.
        # The pump has a deliberate sleep between batches: stop in that gap.
        deadline = asyncio.get_running_loop().time() + 5
        while any(c.command_lock.locked() for c in cores):
            if pump.task.done():
                await pump.task
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError("frame pump did not reach an idle command boundary")
            await asyncio.sleep(.001)
        await pump.close()
        pump = None

    try:
        for i in range(count):
            if not preparation:
                saves[i].write_bytes(source_bytes[i])
            identity = identities[i]
            companion = Companion(CompanionConfig(rom, manifest_path,
                str(uuid4()) if preparation else identity.player_id,
                ("New C" if i == 0 else "New D") if preparation else identity.display_name,
                secrets.token_bytes(32), server_port=server.address[1], ipc_port=0,
                server_credential=None if preparation else identity.credential))
            await companion.start()
            companions.append(companion)
            if not preparation:
                coordinators.append(LiveCheckpointCoordinator(companion, root / f"private-{i}"))
            await launch(i)
        if preparation:
            await advance([0] * count, 1000)
            await snapshot("01-new-game-title")
        else:
            await boot_continue()
            await ready()
            await snapshot("01-four-legacy-continues")
            pump = Pump(cores, companions)
            pump.start()
            for i in range(count):
                await checkpoint(i, enroll=True)
            await fifth_refusal()
            await snapshot("02-four-enrolled")
        print(json.dumps(dict(ready=True, phase=args.phase, output=str(root))), flush=True)
        while line := await asyncio.to_thread(sys.stdin.readline):
            action = json.loads(line)
            evidence["commands"].append(action)
            persist()
            kind = action.get("action", "keys")
            previous = evidence["snapshots"][-1]
            if kind == "finish":
                break
            if kind == "keys":
                keys = action.get("keys", [0] * count)
                frames, release = action.get("frames", 18), action.get("release", 60)
                if pump is None:
                    await advance(keys, frames)
                    await advance([0] * count, release)
                else:
                    if len(keys) != count or any(type(k) is not int or not 0 <= k <= 1023 for k in keys):
                        raise ValueError("one GBA key mask per core required")
                    if any(type(n) is not int or not 0 <= n <= 5000 for n in (frames, release)):
                        raise ValueError("bounded frames/release required")
                    pump.keys[:] = keys
                    await pump.advance(frames)
                    pump.keys[:] = [0] * count
                    await pump.advance(release)
            elif kind == "checkpoint" and not preparation:
                await checkpoint(action.get("client", 0))
            elif kind == "rejoin" and not preparation:
                await rejoin(action.get("client", 2))
            elif kind != "snapshot":
                raise ValueError("unsupported proof action")
            snap = await snapshot(action.get("label", f"step-{len(evidence['commands']):03d}"))
            expect = action.get("expect", {})
            if "remote_counts" in expect:
                actual = [sum(241 <= o["local_id"] <= 243 and not o["invisible"] and o.get("sprite_active", True) and not o.get("sprite_invisible", False)
                    for o in c.get("objects", [])) for c in snap["clients"]]
                assert actual == expect["remote_counts"], actual
                record("actual-remote-actor-counts", label=snap["label"], counts=actual)
            if "activities" in expect:
                actual = [c.get("pose", {}).get("activity") for c in snap["clients"]]
                assert actual == expect["activities"], actual
                record("independent-game-activities", label=snap["label"], activities=actual)
            if expect.get("distinct_maps"):
                maps = {(c["pose"]["map_group"], c["pose"]["map_number"]) for c in snap["clients"]}
                assert len(maps) >= expect["distinct_maps"]
                record("independent-maps", label=snap["label"], maps=sorted(maps))
            if "moved_clients" in expect:
                moved = []
                for i in expect["moved_clients"]:
                    before, after = previous["clients"][i]["pose"], snap["clients"][i]["pose"]
                    fields = ("map_group", "map_number", "x", "y")
                    assert tuple(before[f] for f in fields) != tuple(after[f] for f in fields), i
                    moved.append(i)
                record("actual-independent-joypad-movement", label=snap["label"], clients=moved)
            if "native_battles" in expect:
                actual = [c.get("native_in_battle") for c in snap["clients"]]
                assert actual == expect["native_battles"], actual
                record("native-local-battle-with-other-cores-independent", label=snap["label"], battles=actual)
        else:
            raise RuntimeError("proof stdin ended without finish")
        before_close = await snapshot("final-before-close")
        await stop_pump()
        await close_cores()
        payloads = [p.read_bytes() for p in saves]
        parsed = [inspect_flash(b) if preparation else inspect_flash(b, save_profile=OWNERSHIP_PROFILE) for b in payloads]
        trainer_ids = [p.metadata.trainer_id for p in parsed]
        assert len(set(trainer_ids + ([m.trainer_id for m in source_metadata] if preparation else []))) == (4 if preparation else count)
        assert len(set(p.metadata.name for p in parsed)) == count
        record("distinct-native-trainers-and-closed-saves", trainer_ids=trainer_ids,
            names=[p.metadata.name.hex() for p in parsed], sha256=[hashlib.sha256(b).hexdigest() for b in payloads])
        core_generation += 1
        for i in range(count):
            await launch(i)
        await boot_continue()
        await ready()
        fresh = await snapshot("fresh-continue")
        for item, saved in zip(fresh["clients"], parsed):
            pose = item["pose"]
            assert (pose["map_group"], pose["map_number"], pose["x"], pose["y"]) == (
                saved.metadata.map_group, saved.metadata.map_number, saved.metadata.x, saved.metadata.y)
            assert pose["activity"] == 1
        record("fresh-Continue-restores-each-saved-map-and-position")
        if not preparation:
            checks = evidence["checks"]
            assert any(c["verified"] == "actual-remote-actor-counts" and c["counts"] == [3]*4 for c in checks)
            assert any(c["verified"] == "independent-maps" for c in checks)
            assert any(c["verified"] == "independent-game-activities" and len(set(c["activities"])) > 1 for c in checks)
            moved = {i for c in checks if c["verified"] == "actual-independent-joypad-movement" for i in c["clients"]}
            assert moved == {0, 1, 2, 3}, moved
            assert any(c["verified"] == "one-client-disconnect-rejoin-retains-all-heads-and-other-leases" for c in checks)
            assert all(r >= 2 for r in revisions), revisions
            for i, p in enumerate(parsed):
                assert inspect_ownership(p).records == canonical[i].records
            assert len({c["core_pid"] for c in fresh["clients"]}) == 4
            first = evidence["snapshots"][0]["clients"]
            assert all(b["frame"] > a["frame"] for a, b in zip(first, before_close["clients"]))
            assert all(a["core_pid"] == b["core_pid"] for a, b in zip(first, before_close["clients"]))
            record("four-independent-original-core-pids-advanced", core_pids=[c["core_pid"] for c in first],
                first_frames=[c["frame"] for c in first], final_frames=[c["frame"] for c in before_close["clients"]])
            store.integrity_check()
        await close_cores()
        assert payloads == [p.read_bytes() for p in saves]
        assert source_bytes == [p.read_bytes() for p in source_paths]
        record("fresh-Continue-and-original-source-bytes-preserved")
        evidence["passed"] = True
        persist()
    finally:
        await stop_pump()
        await close_cores()
        for c in companions:
            await c.close()
        await server.close()
        if store is not None:
            store.close()
        persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prepare", "foundation"), required=True)
    for name in ("rom", "manifest", "harness", "save-a", "save-b", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("save-c", "save-d"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2] / "bridge/mgba.lua")
    parser.add_argument("--diagnostics", type=Path, help="Matching ELF/source-derived read-only native flags")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
