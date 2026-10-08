"""Prepare legitimate Multi proof parties through ordinary single-core gameplay.

Uses the existing LockedCore, production bridge, and native save/Continue path.
Only bounded joypad input changes gameplay; core memory reads are diagnostics.
No save editing, arbitrary RAM writes, state loading, or synthetic Pokémon.
JSON lines on stdin support keys, snapshot, replay, and finish actions. Replay
reads an earlier preparation's recorded ordinary inputs, with optional inclusive
from_label/to_label bounds. All replayed inputs are recorded independently.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import secrets
import sys
from uuid import uuid4

from configure_bridge import configure
from live_checkpoint_proof import LockedCore
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.companion import Companion, CompanionConfig, verify_rom_manifest
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.mailbox import inspect_mailbox
from emerald_multiplayer.ownership import extract_source_inventory
from emerald_multiplayer.server import ServerConfig, WorldServer


async def run(args):
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    _, manifest = verify_rom_manifest(args.rom, args.manifest)
    source = args.source.read_bytes()
    original = inspect_flash(source)
    initial_inventory = extract_source_inventory(original)
    if any(mon.serial for mon in initial_inventory):
        raise ValueError("preparation accepts unowned source copies, not another world's checkpoint")
    root.mkdir(mode=0o700, parents=True)
    rom, save, manifest_path = root / "proof.gba", root / "prepared.sav", root / "manifest.json"
    rom.write_bytes(args.rom.read_bytes())
    save.write_bytes(source)
    manifest_path.write_bytes(args.manifest.read_bytes())
    (root / "controller.py").write_bytes(Path(__file__).read_bytes())
    bridge_source = args.bridge.read_text()
    (root / "bridge-source.lua").write_text(bridge_source)
    evidence = dict(scope="ordinary single-core party preparation, not multiplayer acceptance",
        engine_commit=manifest["engine_commit"], rom_sha256=manifest["rom_sha256"],
        controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        bridge_sha256=hashlib.sha256(bridge_source.encode()).hexdigest(),
        harness_sha256=hashlib.sha256(args.harness.read_bytes()).hexdigest(),
        source_path=str(args.source), source_sha256=hashlib.sha256(source).hexdigest(),
        original_trainer_id=original.metadata.trainer_id,
        initial_party_count=original.metadata.party_count, target_party_count=args.target_count,
        commands=[], snapshots=[], checks=[], passed=False, cores_closed=False)

    def persist():
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")

    def record(name, **fields):
        row = dict(verified=name, **fields)
        evidence["checks"].append(row)
        persist()
        print(json.dumps(row), flush=True)

    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"],
        heartbeat_interval=.2, idle_timeout=12))
    await server.start(port=0)
    companion = Companion(CompanionConfig(rom, manifest_path, str(uuid4()), "Party Preparation",
        secrets.token_bytes(32), server_port=server.address[1], ipc_port=0))
    await companion.start()
    core = lease = None
    all_cores = []

    async def launch():
        nonlocal core, lease
        lease = MirrorLease(save)
        lease.__enter__()
        script = root / f"bridge-{len(all_cores)}.lua"
        script.write_text(configure(manifest, companion.config.token.hex(), companion.ipc_address[1], bridge_source))
        process = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(save), str(script),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        core = LockedCore(process, root / f"core-{len(all_cores)}.log")
        all_cores.append(core)
        if not (await asyncio.wait_for(process.stdout.readline(), 30)).startswith(b"READY"):
            raise RuntimeError("actual core did not start")

    async def close_core():
        nonlocal core, lease
        if core is not None:
            await core.close()
            core = None
        if lease is not None:
            lease.__exit__(None, None, None)
            lease = None

    async def advance(keys, frames):
        if type(keys) is not int or not 0 <= keys <= 1023 or type(frames) is not int or not 0 <= frames <= 5000:
            raise ValueError("bounded ordinary GBA input required")
        for offset in range(0, frames, 24):
            await core.command(f"F {keys:x} {min(24, frames-offset)}")
            await asyncio.sleep(.003)

    async def boot_continue():
        for key, frames in ((0, 1000), (8, 8), (0, 480), (8, 8), (0, 180), (1, 8), (0, 300)):
            await advance(key, frames)

    async def snapshot(label):
        if not isinstance(label, str) or not label.isascii() or not 1 <= len(label) <= 96 or not all(c.isalnum() or c in "-_" for c in label):
            raise ValueError("short ASCII screenshot label required")
        pose, _ = inspect_mailbox(await core.read(manifest["mailbox_address"], 128))
        party_count = (await core.read(manifest["debug_party_counts_address"], 1))[0]
        party = await core.read(manifest["debug_parties_address"], manifest["debug_party_size"])
        row = dict(label=label, core_pid=core.process.pid, pose=asdict(pose), party_count=party_count,
            party_read_only_hex=party.hex(),
            party_health=[dict(level=party[i*100+84], hp=int.from_bytes(party[i*100+86:i*100+88], "little"),
                max_hp=int.from_bytes(party[i*100+88:i*100+90], "little")) for i in range(party_count)])
        evidence["snapshots"].append(row)
        await core.command(f"P {root / (label + '.png')}")
        persist()
        print(json.dumps({k: v for k, v in row.items() if k != "party_read_only_hex"}), flush=True)
        return row

    async def apply_input(command):
        if command.get("action", "keys") not in ("keys", "snapshot"):
            raise ValueError("replay accepts only ordinary keys/snapshot records")
        evidence["commands"].append(command)
        persist()
        if command.get("action", "keys") == "keys":
            repeat = command.get("repeat", 1)
            if type(repeat) is not int or not 1 <= repeat <= 100:
                raise ValueError("bounded repeat count required")
            for _ in range(repeat):
                await advance(command.get("keys", 0), command.get("frames", 18))
                await advance(0, command.get("release", 60))
        await snapshot(command.get("label", f"step-{len(evidence['commands']):03d}"))

    try:
        await launch()
        await boot_continue()
        await snapshot("original-continue")
        print(json.dumps(dict(ready=True, output=str(root))), flush=True)
        while line := await asyncio.to_thread(sys.stdin.readline):
            command = json.loads(line)
            action = command.get("action", "keys")
            if action == "finish":
                evidence["commands"].append(command)
                break
            if action == "replay":
                replay = json.loads(Path(command["evidence"]).read_text())["commands"]
                start = command.get("from_label")
                end = command.get("to_label")
                labels = [c.get("label") for c in replay]
                if start is not None and labels.count(start) != 1 or end is not None and labels.count(end) != 1:
                    raise ValueError("replay bounds must identify one recorded label")
                replay = replay[labels.index(start) if start else 0:(labels.index(end)+1) if end else len(replay)]
                for item in replay:
                    if item.get("action", "keys") in ("keys", "snapshot"):
                        await apply_input(item)
            else:
                await apply_input(command)
        else:
            raise RuntimeError("input ended before explicit finish")
        before = await snapshot("final-before-close")
        assert before["pose"]["activity"] == 1 and before["party_count"] == args.target_count
        await close_core()
        payload = save.read_bytes()
        saved = inspect_flash(payload, expected_trainer_id=original.metadata.trainer_id)
        inventory = extract_source_inventory(saved)
        assert saved.metadata.party_count == args.target_count
        assert saved.metadata.name == original.metadata.name and saved.metadata.gender == original.metadata.gender
        assert all(mon.ot_id == original.metadata.trainer_id and mon.serial == 0 for mon in inventory)
        for mon in initial_inventory:
            assert any((mon.personality, mon.ot_id, mon.species) == (new.personality, new.ot_id, new.species) for new in inventory)
        record("ordinary-native-save-keeps-trainer-and-legitimately-obtained-party", inventory=[asdict(m) for m in inventory],
            save_sha256=hashlib.sha256(payload).hexdigest(), save_path=str(save))
        await launch()
        await boot_continue()
        fresh = await snapshot("fresh-continue")
        fields = ("map_group", "map_number", "x", "y")
        assert tuple(fresh["pose"][f] for f in fields) == tuple(getattr(saved.metadata, f) for f in fields)
        assert fresh["pose"]["activity"] == 1 and fresh["party_count"] == args.target_count
        assert fresh["party_read_only_hex"] == before["party_read_only_hex"]
        assert fresh["core_pid"] != before["core_pid"]
        record("fresh-native-Continue-restores-exact-party-and-saved-position", core_pid=fresh["core_pid"], pose=fresh["pose"])
        await close_core()
        assert save.read_bytes() == payload and args.source.read_bytes() == source
        record("fresh-Continue-and-immutable-source-bytes-preserved")
        evidence["passed"] = True
    finally:
        await close_core()
        await companion.close()
        await server.close()
        evidence["cores_closed"] = all(c.process.returncode is not None for c in all_cores)
        evidence["original_source_unchanged"] = args.source.read_bytes() == source
        if not evidence["cores_closed"] or not evidence["original_source_unchanged"]:
            evidence["passed"] = False
        persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "manifest", "harness", "source", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--target-count", type=int, choices=range(1, 7), required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2] / "bridge/mgba.lua")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
