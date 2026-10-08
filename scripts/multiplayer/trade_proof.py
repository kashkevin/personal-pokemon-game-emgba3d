"""Ordinary starter preparation and two actual cores' development strict swap.

Joypad inputs change gameplay; production mailboxes perform the authorized native
Flash import. This does not qualify native trade effects or a player-facing UI.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
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
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.live_trade import LiveTradeCoordinator
from emerald_multiplayer.mailbox import inspect_mailbox
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, extract_source_inventory, inspect_ownership
from emerald_multiplayer.save_mailbox import FLASH_SIZE, Opcode, SaveControl, State, Status, TradeHold
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_flash import validate_party_swap
from emerald_multiplayer.trade_storage import TradeCheckpointStore


async def run(args):
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof directory")
    root.mkdir(mode=0o700, parents=True)
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    rom_bytes = args.rom.read_bytes()
    if hashlib.sha256(rom_bytes).hexdigest() != manifest["rom_sha256"]:
        raise ValueError("frozen ROM differs from its verified manifest")
    source = args.save_b.read_bytes()
    original = inspect_flash(source)
    if original.metadata.party_count != 0 or extract_source_inventory(original):
        raise ValueError("starter preparation expects the original empty-party trainer")
    rom, save = root / "proof.gba", root / "b-with-starter.sav"
    rom.write_bytes(rom_bytes)
    save.write_bytes(source)
    manifest_path = root / "manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    bridge_source = args.bridge.read_text()
    evidence = dict(scope="one real core ordinary starter preparation; paired trade remains untested",
        engine_commit=manifest["engine_commit"], rom_sha256=manifest["rom_sha256"],
        source_path=str(args.save_b), source_sha256=hashlib.sha256(source).hexdigest(),
        original_trainer_id=original.metadata.trainer_id, commands=[], snapshots=[], checks=[], passed=False)

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
    companion = Companion(CompanionConfig(rom, manifest_path, str(uuid4()), "Starter B",
        secrets.token_bytes(32), server_port=server.address[1], ipc_port=0))
    await companion.start()
    core = lease = None
    generation = 0

    async def launch():
        nonlocal core, lease
        lease = MirrorLease(save)
        lease.__enter__()
        script = root / f"bridge-{generation}.lua"
        script.write_text(configure(manifest, companion.config.token.hex(),
            companion.ipc_address[1], bridge_source))
        process = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(save), str(script),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        core = LockedCore(process, root / f"core-{generation}.log")
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
        if not isinstance(label, str) or not label.isascii() or not 1 <= len(label) <= 64 or not all(c.isalnum() or c in "-_" for c in label):
            raise ValueError("short ASCII screenshot label required")
        frame = int((await core.command("F 0 0")).split()[1])
        pose, inbound = inspect_mailbox(await core.read(manifest["mailbox_address"], 128))
        party_count = (await core.read(manifest["debug_party_counts_address"], 1))[0]
        party = await core.read(manifest["debug_parties_address"], manifest["debug_party_size"])
        row = dict(label=label, core_pid=core.process.pid, frame=frame, pose=asdict(pose),
            inbound=asdict(inbound), party_count=party_count, party_read_only_hex=party.hex())
        evidence["snapshots"].append(row)
        await core.command(f"P {root / (label + '.png')}")
        persist()
        print(json.dumps({k:v for k,v in row.items() if k not in {"inbound", "party_read_only_hex"}}), flush=True)
        return row

    try:
        await launch()
        await boot_continue()
        await snapshot("01-original-b-continue")
        print(json.dumps(dict(ready=True, output=str(root))), flush=True)
        while line := await asyncio.to_thread(sys.stdin.readline):
            command = json.loads(line)
            evidence["commands"].append(command)
            persist()
            action = command.get("action", "keys")
            if action == "finish":
                break
            if action == "keys":
                await advance(command.get("keys", 0), command.get("frames", 18))
                await advance(0, command.get("release", 60))
            elif action != "snapshot":
                raise ValueError("unsupported preparation action")
            await snapshot(command.get("label", f"step-{len(evidence['commands']):03d}"))
        else:
            raise RuntimeError("input ended before an explicit finish")
        before_close = await snapshot("final-before-close")
        assert before_close["pose"]["activity"] == 1 and before_close["party_count"] == 1
        await close_core()
        payload = save.read_bytes()
        saved = inspect_flash(payload, expected_trainer_id=original.metadata.trainer_id)
        inventory = extract_source_inventory(saved)
        assert len(inventory) == 1 and inventory[0].location == "party:0" and inventory[0].species in {252, 258}
        assert inventory[0].ot_id == original.metadata.trainer_id and inventory[0].serial == 0
        assert saved.metadata.name == original.metadata.name and saved.metadata.gender == original.metadata.gender
        record("ordinary-native-starter-save-keeps-original-trainer", starter=asdict(inventory[0]),
            trainer_id=saved.metadata.trainer_id, save_sha256=hashlib.sha256(payload).hexdigest(), save_path=str(save))
        generation += 1
        await launch()
        await boot_continue()
        fresh = await snapshot("fresh-continue")
        fields = ("map_group", "map_number", "x", "y")
        assert tuple(fresh["pose"][f] for f in fields) == tuple(getattr(saved.metadata, f) for f in fields)
        assert fresh["pose"]["activity"] == 1 and fresh["party_count"] == 1
        assert fresh["core_pid"] != before_close["core_pid"]
        record("fresh-native-Continue-restores-starter-and-saved-position", core_pid=fresh["core_pid"], pose=fresh["pose"])
        await close_core()
        assert save.read_bytes() == payload and args.save_b.read_bytes() == source
        record("fresh-Continue-and-immutable-original-b-bytes-preserved")
        evidence["passed"] = True
        persist()
    finally:
        await close_core()
        await companion.close()
        await server.close()
        persist()


async def run_paired(args):
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof directory")
    if args.save_a is None:
        raise ValueError("paired phase requires two independent source saves")
    root.mkdir(mode=0o700, parents=True)
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    rom_bytes = args.rom.read_bytes()
    if (hashlib.sha256(rom_bytes).hexdigest() != manifest["rom_sha256"]
            or manifest.get("trade_abi_version") != 1):
        raise ValueError("a verified frozen trade-capable ROM is required")
    source_paths = [args.save_a, args.save_b]
    source_bytes = [p.read_bytes() for p in source_paths]
    source_parsed = [inspect_flash(p) for p in source_bytes]
    source_inventories = [extract_source_inventory(p) for p in source_parsed]
    if len({p.metadata.trainer_id for p in source_parsed}) != 2:
        raise ValueError("paired proof requires genuinely distinct native trainers")
    if (not any(r.location.startswith("party:") and r.species == 265 for r in source_inventories[0])
            or not any(r.location.startswith("party:") and r.species in {252, 258} for r in source_inventories[1])):
        raise ValueError("proof expects A's Wurmple and B's ordinarily obtained starter")
    rom = root / "proof.gba"
    rom.write_bytes(rom_bytes)
    manifest_path = root / "manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    bridge_source = args.bridge.read_text()
    (root / "bridge-source.lua").write_text(bridge_source)
    (root / "controller.py").write_bytes(Path(__file__).read_bytes())
    saves = [root / ("client-" + label + ".sav") for label in "ab"]
    for path, payload in zip(saves, source_bytes):
        path.write_bytes(payload)
    evidence = dict(scope="two real cores development strict party swap; native trade effects and player-facing trading remain untested",
        engine_commit=manifest["engine_commit"], build_id=manifest["rom_sha256"],
        ruleset_id=manifest["ruleset_id"], save_profile=OWNERSHIP_PROFILE,
        sources=[dict(path=str(p), sha256=hashlib.sha256(b).hexdigest(), trainer_id=s.metadata.trainer_id)
            for p, b, s in zip(source_paths, source_bytes, source_parsed)],
        commands=[], snapshots=[], checks=[], passed=False)

    def persist():
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")

    def record(name, **fields):
        row = dict(verified=name, **fields)
        evidence["checks"].append(row)
        persist()
        print(json.dumps(row), flush=True)

    store = TradeCheckpointStore(root / "world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
    identities = [store.create_player("Strict swap " + label) for label in "AB"]
    for identity, payload in zip(identities, source_bytes):
        store.enroll_player(identity.player_id, payload)
    (root / "profiles.json").write_text(json.dumps([dict(player_id=p.player_id,
        display_name=p.display_name, credential=p.credential.hex()) for p in identities], indent=2) + "\n")
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"],
        heartbeat_interval=.2, idle_timeout=12), store=store, development_trades=True)
    await server.start(port=0)
    cores, companions, leases, live, trades = [], [], [], [], []
    revisions = [0, 0]
    canonical = [None, None]
    pump = None
    keepers = []
    keeper_stops = {}
    generation = 0
    transaction_id = str(uuid4())

    async def launch(i):
        lease = MirrorLease(saves[i])
        lease.__enter__()
        leases.append(lease)
        script = root / f"bridge-{i}-{generation}.lua"
        script.write_text(configure(manifest, companions[i].config.token.hex(),
            companions[i].ipc_address[1], bridge_source))
        process = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(saves[i]), str(script),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        cores.append(LockedCore(process, root / f"core-{i}-{generation}.log"))
        if not (await asyncio.wait_for(process.stdout.readline(), 30)).startswith(b"READY"):
            raise RuntimeError("actual core did not start")

    async def advance(keys, frames):
        if (not isinstance(keys, list) or len(keys) != 2
                or any(type(k) is not int or not 0 <= k <= 1023 for k in keys)
                or type(frames) is not int or not 0 <= frames <= 5000):
            raise ValueError("bounded ordinary GBA inputs required")
        for start in range(0, frames, 24):
            await asyncio.gather(*(c.command(f"F {k:x} {min(24, frames-start)}") for c, k in zip(cores, keys)))
            await asyncio.sleep(.003)

    async def boot_continue():
        for key, frames in ((0, 1000), (8, 8), (0, 480), (8, 8), (0, 180), (1, 8), (0, 300)):
            await advance([key, key], frames)

    async def ready():
        for _ in range(500):
            if all(c.connected and c._bridge is not None and c._bridge.save_capable for c in companions):
                return
            await asyncio.sleep(.025)
        raise AssertionError([(c.connected, c.last_error) for c in companions])

    async def query_hold(i):
        c = companions[i]
        control = SaveControl(c.save_incarnation, c.session_epoch, transaction_id, 1, 0,
            FLASH_SIZE, revisions[i], Opcode.QUERY_TRADE)
        response = await c.save_rpc(control)
        assert response.status == Status.OK
        return TradeHold.parse(response)

    async def snapshot(label):
        if (not isinstance(label, str) or not label.isascii() or not 1 <= len(label) <= 64
                or not all(c.isalnum() or c in "-_" for c in label)):
            raise ValueError("short ASCII screenshot label required")
        clients = []
        for i, core in enumerate(cores):
            frame = int((await core.command("F 0 0")).split()[1])
            pose, inbound = inspect_mailbox(await core.read(manifest["mailbox_address"], 128))
            party_count = (await core.read(manifest["debug_party_counts_address"], 1))[0]
            party = await core.read(manifest["debug_parties_address"], manifest["debug_party_size"])
            row = dict(core_pid=core.process.pid, frame=frame, pose=asdict(pose), inbound=asdict(inbound),
                party_count=party_count, party_read_only_hex=party.hex(), connected=companions[i].connected,
                lease_epoch=companions[i].session_epoch, incarnation=companions[i].save_incarnation, revision=revisions[i])
            pointer = int.from_bytes(await core.read(manifest["debug_save_block2_ptr_address"], 4), "little")
            if not 0x02000000 <= pointer <= 0x02040000 - 64:
                raise ValueError("native SaveBlock2 diagnostic pointer is outside EWRAM")
            row["native_play_time_hex"] = (await core.read(pointer + manifest["debug_play_time_offset"],
                manifest["debug_play_time_size"])).hex()
            await core.command(f"P {root / (label + '-' + str(i) + '.png')}")
            clients.append(row)
        row = dict(label=label, clients=clients)
        evidence["snapshots"].append(row)
        persist()
        print(json.dumps(dict(label=label, clients=[{k:v for k,v in c.items()
            if k not in {"inbound", "party_read_only_hex"}} for c in clients])), flush=True)
        return row

    async def download(i):
        cp = await CheckpointClient(companions[i]).download()
        assert cp is not None
        parsed = inspect_flash(cp.payload, expected_trainer_id=source_parsed[i].metadata.trainer_id,
            save_profile=OWNERSHIP_PROFILE)
        owned = inspect_ownership(parsed)
        assert (owned.world_id, owned.player_id) == (store.metadata.world_id, identities[i].player_id)
        assert (parsed.metadata.name, parsed.metadata.gender) == (source_parsed[i].metadata.name, source_parsed[i].metadata.gender)
        canonical[i] = cp
        revisions[i] = cp.metadata["revision"]
        return cp, parsed, owned

    async def checkpoint(i, *, enroll=False):
        before = await CheckpointClient(companions[1-i]).info()
        receipt = await (live[i].enroll() if enroll else live[i].checkpoint(expected_revision=revisions[i]))
        cp, parsed, owned = await download(i)
        assert cp.metadata == receipt.metadata
        assert await CheckpointClient(companions[1-i]).info() == before
        record("explicit-source-enrollment" if enroll else "ordinary-post-trade-checkpoint",
            client=i, revision=revisions[i], records=[asdict(x) for x in owned.records], receipt=asdict(receipt))
        return cp, parsed, owned

    async def verify_party(i, parsed):
        actual = await cores[i].read(manifest["debug_parties_address"], manifest["debug_party_size"])
        offset = manifest["debug_saved_party_offset"]
        expected = parsed.save_block1[offset:offset+manifest["debug_party_size"]]
        count = (await cores[i].read(manifest["debug_party_counts_address"], 1))[0]
        assert count == parsed.metadata.party_count
        # Battle-only live stats can be recomputed by ordinary Continue; identity
        # proof compares the complete native encrypted BoxPokemon in each slot.
        for slot in range(count):
            assert actual[slot*100:slot*100+80] == expected[slot*100:slot*100+80], (i, slot)
        return actual

    def start_keeper(i):
        stop = asyncio.Event()
        async def keep():
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), .15)
                    break
                except asyncio.TimeoutError:
                    pass
                await trades[i].keepalive()
        task = asyncio.create_task(keep(), name=f"held-player-{i}-watchdog")
        keepers.append(task)
        keeper_stops[task] = stop
        return task

    async def stop_keeper(task):
        keeper_stops.pop(task).set()
        await task
        keepers.remove(task)

    async def stop_pump():
        nonlocal pump
        if pump is None:
            return
        deadline = asyncio.get_running_loop().time() + 5
        while any(c.command_lock.locked() for c in cores):
            if pump.task.done():
                await pump.task
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError("frame pump did not reach an idle command boundary")
            await asyncio.sleep(.001)
        await pump.close()
        pump = None

    async def close_cores():
        for core in cores:
            await core.close()
        cores.clear()
        for lease in reversed(leases):
            lease.__exit__(None, None, None)
        leases.clear()

    try:
        for i in range(2):
            identity = identities[i]
            companion = Companion(CompanionConfig(rom, manifest_path, identity.player_id, identity.display_name,
                secrets.token_bytes(32), server_port=server.address[1], ipc_port=0, server_credential=identity.credential))
            await companion.start()
            companions.append(companion)
            live.append(LiveCheckpointCoordinator(companion, root / f"private-{i}"))
            trades.append(LiveTradeCoordinator(companion, root / f"private-{i}"))
            await launch(i)
        await boot_continue()
        await ready()
        await snapshot("01-independent-legacy-continues")
        pump = Pump(cores, companions)
        pump.start()
        enrolled = [await checkpoint(i, enroll=True) for i in range(2)]
        assert revisions == [1, 1]
        offered = [next(r for r in enrolled[0][2].records if r.location.startswith("party:") and r.species == 265),
            next(r for r in enrolled[1][2].records if r.location.startswith("party:") and r.species in {252, 258})]
        assert offered[0].serial != offered[1].serial
        initial_ids = [{r.serial for r in entry[2].records} for entry in enrolled]
        evidence["transaction_id"] = transaction_id
        evidence["offered_instances"] = [asdict(r) for r in offered]
        opened = []
        for i in range(2):
            opened.append((await companions[i].trade_rpc("open", transaction_id=transaction_id,
                peer=identities[1-i].player_id))["trade"])
        assert opened[0] == opened[1] and opened[0]["state"] == "offering"
        proposal_generation = opened[0]["generation"]
        record("two-authenticated-actors-open-same-proposal", transaction_id=transaction_id, generation=proposal_generation)
        prepared = []
        for i in range(2):
            metadata = await trades[i].prepare(transaction_id, proposal_generation, expected_revision=1)
            cp, parsed, owned = await download(i)
            assert metadata == cp.metadata and revisions[i] == 2
            assert {r.serial for r in owned.records} == initial_ids[i]
            hold = await query_hold(i)
            assert hold.active and not hold.import_started and hold.transaction_id == transaction_id and hold.revision == 2
            prepared.append(cp)
            record("separate-native-frozen-preparation", client=i, metadata=metadata, hold=asdict(hold))
            if i == 0:
                keeper = start_keeper(0)
        await stop_keeper(keeper)
        frozen_before = await snapshot("02-both-held-before-consent")
        await pump.press(0, 16, 24, 120)
        await pump.press(1, 32, 24, 120)
        frozen_after = await snapshot("03-held-joypad-cannot-advance-game")
        for i in range(2):
            before, after = frozen_before["clients"][i], frozen_after["clients"][i]
            assert after["frame"] > before["frame"]
            # The presence timestamp remains live for networking while game
            # callbacks, movement, party and the native play clock are held.
            assert {k:v for k,v in after["pose"].items() if k != "frame"} == {
                k:v for k,v in before["pose"].items() if k != "frame"}
            assert after["party_read_only_hex"] == before["party_read_only_hex"]
            assert after["native_play_time_hex"] == before["native_play_time_hex"]
            assert (await query_hold(i)).active
        record("native-hold-freezes-both-games-while-emulator-frames-advance")
        one_offer = await trades[0].offer(offered[0].serial)
        assert len(one_offer["offers"]) == 1 and one_offer["fingerprint"] is None
        full_offer = await trades[1].offer(offered[1].serial)
        assert len(full_offer["offers"]) == 2 and full_offer["confirmations"] == []
        assert {r["serial"] for r in full_offer["offers"]} == {r.serial for r in offered}
        record("each-actor-offers-only-its-owned-party-instance", view=full_offer)
        first_consent = await trades[0].confirm(full_offer["fingerprint"])
        assert first_consent["state"] == "offering" and first_consent["confirmations"] == [identities[0].player_id]
        assert [await CheckpointClient(c).info() for c in companions] == [p.metadata for p in prepared]
        record("first-consent-does-not-commit-either-player", view=first_consent)
        second_consent = await trades[1].confirm(full_offer["fingerprint"])
        assert second_consent["state"] == "committed"
        posts = [await download(i) for i in range(2)]
        assert revisions == [3, 3]
        assert all(cp.metadata["request_id"] == transaction_id for cp, _, _ in posts)
        validate_party_swap(prepared[0].payload, offered[0].serial, prepared[1].payload,
            offered[1].serial, posts[0][0].payload, posts[1][0].payload)
        expected_ids = [(initial_ids[i] - {offered[i].serial}) | {offered[1-i].serial} for i in range(2)]
        for i, (cp, parsed, owned) in enumerate(posts):
            assert {r.serial for r in owned.records} == expected_ids[i]
            received = next(r for r in owned.records if r.serial == offered[1-i].serial)
            prior = offered[1-i]
            assert (received.personality, received.ot_id, received.species, received.content_sha256) == (
                prior.personality, prior.ot_id, prior.species, prior.content_sha256)
            assert len(store.pending_trade_recovery(identities[i].player_id, companions[i].session_epoch)) == 1
        record("second-distinct-consent-atomically-commits-exact-paired-post-images", transaction_id=transaction_id,
            metadata=[p[0].metadata for p in posts], inventories=[[asdict(r) for r in p[2].records] for p in posts])
        keeper = start_keeper(1)
        applied_a = await trades[0].resume()
        await stop_keeper(keeper)
        applied_b = await trades[1].resume()
        assert all(r["state"] == "applied" for r in (applied_a, applied_b))
        for i, (_, parsed, _) in enumerate(posts):
            hold = await query_hold(i)
            assert not hold.active and hold.phase == State.BOUND and hold.revision == 3
            assert not trades[i].trade_path.exists()
            assert not store.pending_trade_recovery(identities[i].player_id, companions[i].session_epoch)
            await verify_party(i, parsed)
        record("both-native-imports-readbacks-durable-acks-and-releases-complete", outcomes=[applied_a, applied_b])
        await snapshot("04-both-imported-and-released")
        print(json.dumps(dict(ready=True, phase="paired", output=str(root), core_pids=[c.process.pid for c in cores])), flush=True)
        while line := await asyncio.to_thread(sys.stdin.readline):
            command = json.loads(line)
            evidence["commands"].append(command)
            persist()
            action = command.get("action", "keys")
            if action == "finish":
                break
            if action == "keys":
                keys = command.get("keys", [0, 0])
                frames, release = command.get("frames", 18), command.get("release", 60)
                if (not isinstance(keys, list) or len(keys) != 2 or any(type(k) is not int or not 0 <= k <= 1023 for k in keys)
                        or any(type(n) is not int or not 0 <= n <= 5000 for n in (frames, release))):
                    raise ValueError("bounded ordinary joypad inputs required")
                pump.keys[:] = keys
                await pump.advance(frames)
                pump.keys[:] = [0, 0]
                await pump.advance(release)
            elif action == "checkpoint":
                i = command.get("client")
                if type(i) is not int or i not in (0, 1):
                    raise ValueError("client must be 0 or 1")
                _, _, owned = await checkpoint(i)
                assert {r.serial for r in owned.records} == expected_ids[i]
            elif action == "party_verified":
                # The operator views this native framebuffer before recording
                # its UI evidence; identity is independently checked in RAM.
                i = command.get("client")
                if type(i) is not int or i not in (0, 1):
                    raise ValueError("client must be 0 or 1")
                cp, parsed, owned = await download(i)
                await verify_party(i, parsed)
                record("actual-party-ui-and-readonly-native-inventory", client=i,
                    snapshot=evidence["snapshots"][-1]["label"], records=[asdict(r) for r in owned.records])
            elif action != "snapshot":
                raise ValueError("unsupported paired proof action")
            await snapshot(command.get("label", f"step-{len(evidence['commands']):03d}"))
        else:
            raise RuntimeError("proof input ended before explicit finish")
        before_close = await snapshot("final-before-close")
        assert revisions == [4, 4], revisions
        assert {c["client"] for c in evidence["checks"] if c["verified"] == "actual-party-ui-and-readonly-native-inventory"} == {0, 1}
        assert all(c["pose"]["activity"] == 1 for c in before_close["clients"])
        await stop_pump()
        await close_cores()
        closed_bytes = [p.read_bytes() for p in saves]
        closed = [inspect_flash(p, save_profile=OWNERSHIP_PROFILE) for p in closed_bytes]
        for i, parsed in enumerate(closed):
            cp_parsed = inspect_flash(canonical[i].payload, save_profile=OWNERSHIP_PROFILE)
            assert parsed.flash == cp_parsed.flash and parsed.state_sha256 == cp_parsed.state_sha256
            assert {r.serial for r in inspect_ownership(parsed).records} == expected_ids[i]
        record("closed-native-Flash-matches-each-canonical-revision-4", sha256=[hashlib.sha256(b).hexdigest() for b in closed_bytes],
            flash_sha256=[p.sha256 for p in closed], state_sha256=[p.state_sha256 for p in closed])
        generation += 1
        for i in range(2):
            await launch(i)
        await boot_continue()
        await ready()
        fresh = await snapshot("fresh-continue")
        for i, parsed in enumerate(closed):
            actual = fresh["clients"][i]
            assert actual["core_pid"] != before_close["clients"][i]["core_pid"]
            assert actual["pose"]["activity"] == 1
            assert tuple(actual["pose"][f] for f in ("map_group", "map_number", "x", "y")) == (
                parsed.metadata.map_group, parsed.metadata.map_number, parsed.metadata.x, parsed.metadata.y)
            await verify_party(i, parsed)
        record("two-fresh-Continue-processes-restore-transferred-instance-identities-and-positions")
        await close_cores()
        assert [p.read_bytes() for p in saves] == closed_bytes
        assert [p.read_bytes() for p in source_paths] == source_bytes
        store.integrity_check()
        record("source-immutability-fresh-close-and-schema-3-integrity", world_id=store.metadata.world_id)
        store.backup(root / "world-consistent-backup.sqlite3")
        for companion in companions:
            await companion.close()
        await server.close()
        store.close()
        evidence["passed"] = True
        persist()
        hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and not p.name.endswith(("-shm", "-wal"))}
        acceptance = dict(scope=evidence["scope"], passed=True, engine_commit=manifest["engine_commit"],
            rom_sha256=manifest["rom_sha256"], evidence_sha256=hashes["evidence.json"],
            check_count=len(evidence["checks"]), command_count=len(evidence["commands"]),
            snapshot_count=len(evidence["snapshots"]), transaction_id=transaction_id, artifact_sha256=hashes)
        (root / "acceptance.json").write_text(json.dumps(acceptance, indent=2) + "\n")
        print(json.dumps(dict(passed=True, output=str(root), evidence_sha256=hashes["evidence.json"], checks=len(evidence["checks"]))), flush=True)
    finally:
        for task in tuple(keepers):
            await stop_keeper(task)
        await stop_pump()
        await close_cores()
        for companion in companions:
            await companion.close()
        await server.close()
        store.close()
        persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "manifest", "harness", "save-b", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--phase", choices=("prepare", "paired"), default="prepare")
    parser.add_argument("--save-a", type=Path)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2] / "bridge/mgba.lua")
    args = parser.parse_args()
    asyncio.run(run(args) if args.phase == "prepare" else run_paired(args))


if __name__ == "__main__":
    main()
