"""Two actual ROMs: explicit enrollment, ownership lifecycle, live recovery.

All gameplay uses joypad input. Diagnostic reads and PNGs use the official core;
only the production bridge writes the allocated ROM-owned command mailboxes.
Run --interactive for JSON commands on stdin: keys/frames/release, checkpoint,
snapshot, recover, or finish. Commands and results are retained for review.
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
from live_checkpoint_proof import LockedCore, Pump
from emerald_multiplayer.checkpoint_client import CheckpointClient
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, LiveSaveError
from emerald_multiplayer.mailbox import inspect_mailbox
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.ownership_client import parse_status
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.save_mailbox import Opcode
from emerald_multiplayer.server import ServerConfig, WorldServer


async def run(args):
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    root.mkdir(mode=0o700, parents=True)
    manifest = json.loads(args.manifest.read_text())
    diagnostics = json.loads(args.diagnostics.read_text()) if args.diagnostics else {}
    if manifest.get("ownership_abi_version") != 1:
        raise ValueError("ownership proof requires a verified ownership ROM")
    # Pin this run's bytes even if an independent engine build replaces its ROM.
    rom = root / "proof.gba"
    rom.write_bytes(args.rom.read_bytes())
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    sources = [args.save_a, args.save_b]
    original = [p.read_bytes() for p in sources]
    source_hashes = [hashlib.sha256(data).hexdigest() for data in original]
    store = OwnershipCheckpointStore(root / "world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
    identities = [store.create_player("Ownership " + label) for label in ("A", "B")]
    enrollments = [store.enroll_player(player.player_id, data) for player, data in zip(identities, original)]
    (root / "profiles.json").write_text(json.dumps([dict(player_id=p.player_id, display_name=p.display_name,
        credential=p.credential.hex()) for p in identities]))
    evidence = dict(build_id=manifest["rom_sha256"], engine_commit=manifest["engine_commit"],
        save_profile=OWNERSHIP_PROFILE, source_sha256=source_hashes,
        enrollment=[asdict(item) for item in enrollments], checks=[], snapshots=[], commands=[])
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"], heartbeat_interval=.2, idle_timeout=8), store=store)
    await server.start(port=0)
    cores, companions, leases, coordinators = [], [], [], []
    pump = None
    saves = [root / "client-a.sav", root / "client-b.sav"]
    revisions = [0, 0]
    canonical_owners = [None, None]
    canonical_snapshots = [None, None]
    enrollment_owner = None

    def persist():
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")

    def record(name, **fields):
        item = dict(verified=name, **fields)
        evidence["checks"].append(item)
        persist()
        print(json.dumps(item), flush=True)

    async def ready():
        for _ in range(400):
            if all(c.connected and c._bridge is not None and c._bridge.save_capable for c in companions):
                return
            await asyncio.sleep(.025)
        raise AssertionError([(c.connected, c.last_error) for c in companions])

    async def launch(i):
        lease = MirrorLease(saves[i])
        lease.__enter__()
        leases.append(lease)
        companion = companions[i]
        script = root / f"bridge-{i}.lua"
        script.write_text(configure(manifest, companion.config.token.hex(), companion.ipc_address[1], args.bridge.read_text()))
        process = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(saves[i]), str(script),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        core = LockedCore(process, root / f"core-{i}-{len(evidence['snapshots'])}.log")
        cores.append(core)
        if not (await asyncio.wait_for(process.stdout.readline(), 20)).startswith(b"READY"):
            raise RuntimeError(f"core failed: {core.log}")

    async def boot():
        for keys, total in ((0, 1000), (8, 8), (0, 480), (8, 8), (0, 180), (1, 8), (0, 300)):
            for step in range(0, total, 24):
                await asyncio.gather(*(c.command(f"F {keys:x} {min(24, total-step)}") for c in cores))
                await asyncio.sleep(.003)
        await ready()

    async def snapshot(label):
        clients = []
        for i, core in enumerate(cores):
            pose, inbound = inspect_mailbox(await core.read(manifest["mailbox_address"], 128))
            await core.command(f"P {root / (label + '-' + str(i) + '.png')}")
            diagnostic_values = {}
            if i == 0:
                for name, spec in diagnostics.items():
                    diagnostic_values[name] = (await core.read(spec["address"], spec["size"])).hex()
            clients.append(dict(pose=asdict(pose), core_pid=core.process.pid, lease_epoch=companions[i].session_epoch,
                                incarnation=companions[i].save_incarnation, canonical_revision=revisions[i],
                                read_only_diagnostics=diagnostic_values))
        result = dict(label=label, clients=clients)
        evidence["snapshots"].append(result)
        persist()
        # Full diagnostic bytes stay in the private transcript, keeping the
        # interactive terminal readable while many joypad steps are replayed.
        display = dict(result, clients=[{key: value for key, value in item.items()
                                       if key != "read_only_diagnostics"} for item in clients])
        print(json.dumps(display), flush=True)
        return result

    async def checkpoint(i=0, *, enroll=False):
        nonlocal enrollment_owner
        result = await (coordinators[i].enroll() if enroll else coordinators[i].checkpoint(expected_revision=revisions[i]))
        revisions[i] = result.metadata["revision"]
        downloaded = await CheckpointClient(companions[i]).download()
        parsed = inspect_flash(downloaded.payload, save_profile=OWNERSHIP_PROFILE)
        owner = inspect_ownership(parsed)
        assert (owner.world_id, owner.player_id) == (store.metadata.world_id, identities[i].player_id)
        canonical_owners[i] = owner
        canonical_snapshots[i] = parsed
        if i == 0 and enroll:
            enrollment_owner = owner
        record("explicit-legacy-enrollment" if enroll else "ownership-checkpoint", client=i,
            revision=revisions[i], manifest=asdict(owner), metadata=result.metadata)
        return owner

    def verify_lifecycle(expect, owner):
        """Assert ordinary actions against immutable checkpoints and the ledger."""
        serial, location = expect["serial"], expect.get("location")
        by_id = {item.serial: item for item in owner.records}
        initial = {item.serial: item for item in enrollment_owner.records}
        assert len(owner.records) == expect["count"]
        for retained in set(initial) & set(by_id):
            assert (by_id[retained].personality, by_id[retained].ot_id, by_id[retained].species) == (
                initial[retained].personality, initial[retained].ot_id, initial[retained].species)
        if location is None:
            assert serial not in by_id
            assert (serial, 1) in {(item.serial, item.reason) for item in owner.retirements}
            row = store._connection.execute(
                "SELECT player_id, status, retirement_reason FROM ownership_instances WHERE serial = ?", (serial,)).fetchone()
            assert tuple(row) == (identities[0].player_id, "retired", 1)
        else:
            assert by_id[serial].location == location
        if expect.get("no_retirements"):
            assert not owner.retirements
        details = dict(step=expect["step"], revision=revisions[0], serial=serial, location=location,
                       records=[asdict(item) for item in owner.records])
        if expect.get("new_capture"):
            assert serial not in initial and serial != expect["distinct_from_serial"]
            # Inspect the previous ordinary-save bank from the downloaded Flash
            # copy, never the emulator's open save mapping.
            from emerald_multiplayer.flash import _extract_bank, _inspect_bank
            from emerald_multiplayer.ownership import _inspect_components
            selected = canonical_snapshots[0]
            previous = _inspect_bank(selected.flash, 1 - selected.metadata.bank, OWNERSHIP_PROFILE)
            assert previous is not None
            sb1, _, sb3, storage, metadata = _extract_bank(previous)
            older = _inspect_components(sb3, sb1, storage, allow_unassigned_inventory=True)
            source_mon = next(item for item in older.records if item.location == location)
            assert source_mon.serial == 0 and source_mon.content_sha256 == by_id[serial].content_sha256
            details.update(previous_bank_counter=metadata.counter, previous_unassigned=asdict(source_mon))
        assert canonical_owners[1].records == () and revisions[1] == 1
        record("ordinary-gameplay-ownership-lifecycle", **details)

    async def ownership_status(i):
        coord = coordinators[i]
        async with coord._own():
            session = coord._session()
            await coord._bind(session)
            return parse_status((await coord._command(session, str(uuid4()), revisions[i], Opcode.QUERY_OWNERSHIP)).data)

    async def recover():
        pids = [c.process.pid for c in cores]
        epochs = [c.session_epoch for c in companions]
        other = await CheckpointClient(companions[1]).info()
        receipt = await coordinators[0].recover()
        await pump.advance(120)
        authority = await ownership_status(0)
        assert authority.enrolled and not authority.active_grant and authority.remaining == 0
        assert pids == [c.process.pid for c in cores] and epochs == [c.session_epoch for c in companions]
        assert await CheckpointClient(companions[1]).info() == other
        record("live-recovery-invalidates-mint-authority-without-restarting-either-player", receipt=asdict(receipt))

    try:
        for i, identity in enumerate(identities):
            saves[i].write_bytes(original[i])
            companion = Companion(CompanionConfig(rom, root / "manifest.json", identity.player_id, identity.display_name,
                secrets.token_bytes(32), server_port=server.address[1], ipc_port=0, server_credential=identity.credential))
            await companion.start()
            companions.append(companion)
            coordinators.append(LiveCheckpointCoordinator(companion, root / ("private-" + str(i))))
        for i in range(2):
            await launch(i)
        await boot()
        await snapshot("01-legacy-continue")
        pump = Pump(cores, companions)
        pump.start()
        try:
            await coordinators[0].checkpoint(expected_revision=0)
        except LiveSaveError as error:
            assert error.code == "enrollment_required", error.code
        else:
            raise AssertionError("ordinary checkpoint silently enrolled legacy state")
        record("legacy-enrollment-requires-explicit-action")
        await checkpoint(0, enroll=True)
        await checkpoint(1, enroll=True)
        pump.wander()
        await snapshot("02-enrolled")
        if args.interactive:
            replay = []
            if args.replay:
                saved = json.loads(args.replay.read_text())
                replay = saved["commands"] if isinstance(saved, dict) else saved
                if args.replay_limit is not None:
                    replay = replay[:args.replay_limit]
            print(json.dumps(dict(ready=True, output=str(root))), flush=True)
            while True:
                if replay:
                    command = replay.pop(0)
                    print(json.dumps(dict(replaying=command)), flush=True)
                else:
                    line = await asyncio.to_thread(sys.stdin.readline)
                    if not line:
                        raise RuntimeError("interactive proof ended without finish")
                    command = json.loads(line)
                evidence["commands"].append(command)
                persist()
                action = command.get("action", "keys")
                if action == "finish":
                    break
                if action == "keys":
                    await pump.press(0, command.get("keys", 0), command.get("frames", 18), command.get("release", 60))
                elif action == "checkpoint":
                    try:
                        owner = await checkpoint()
                    except LiveSaveError as error:
                        if error.code != "rom_unsafe":
                            raise
                        # A rejected scene does not consume a checkpoint. Keep
                        # both cores alive so ordinary input can reach the field.
                        record("unsafe-scene-checkpoint-refused", error=error.code,
                               revision=revisions[0], label=command.get("label"))
                        await snapshot(command.get("label", "checkpoint") + "-unsafe")
                        continue
                    if "expect" in command:
                        verify_lifecycle(command["expect"], owner)
                elif action == "recover":
                    await recover()
                elif action != "snapshot":
                    raise ValueError("unknown interactive action")
                await snapshot(command.get("label", f"step-{len(evidence['commands']):03d}"))
        before = canonical_owners[0]
        prior_grant = before.grant_id
        await pump.press(0, 16, 18, 60)
        await recover()
        after = await checkpoint()
        assert after.records == before.records and after.grant_id != prior_grant
        assert after.start >= before.end_exclusive
        record("post-recovery-checkpoint-uses-new-permanently-burned-range", start=after.start, old_end=before.end_exclusive)
        assert len(pump.visited_b) > 1
        record("other-player-moves-through-ownership-operations", positions=sorted(pump.visited_b))
        await pump.stop_wander()
        await pump.advance(180)
        await pump.close()
        pump = None
        for core in cores:
            await core.close()
        cores.clear()
        for lease in leases:
            lease.__exit__(None, None, None)
        leases.clear()
        assert inspect_ownership(inspect_flash(saves[0].read_bytes(), save_profile=OWNERSHIP_PROFILE)).records == after.records
        for i in range(2):
            await launch(i)
        await boot()
        await snapshot("fresh-Continue")
        pump = Pump(cores, companions)
        pump.start()
        assert not (await ownership_status(0)).active_grant
        fresh = await checkpoint()
        assert fresh.records == after.records and fresh.start >= after.end_exclusive
        record("fresh-Continue-preserves-identities-and-refreshes-authority")
        store.integrity_check()
        assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources] == source_hashes
        record("source-saves-unchanged-and-database-integrity-valid")
        evidence["passed"] = True
        persist()
    finally:
        if pump is not None:
            await pump.close()
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
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--diagnostics", type=Path, help="Optional named read-only core ranges from the matching ELF")
    parser.add_argument("--replay", type=Path, help="Replay recorded joypad commands before reading stdin")
    parser.add_argument("--replay-limit", type=int, help="Replay only this many commands")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
