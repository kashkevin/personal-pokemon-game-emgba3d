"""Two actual cores attempting native singles through bounded production IPC.

An explicit development coordinator routes authenticated participants' typed
blocks and compares startup to canonical owned checkpoints. This is not the
server challenge UI or an Internet/2v2 proof. Gameplay uses ordinary joypad
inputs. Core memory and Flash access below is read-only diagnostic evidence.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import secrets
import struct
import time
import traceback
from uuid import uuid4
import zlib

from configure_bridge import configure
from live_checkpoint_proof import LockedCore
from battle_channel_proof import DiagnosticPump
from emerald_multiplayer.battle_controller import ControllerValidator, read_string_lengths
from emerald_multiplayer.battle_desk import BattleDesk
from emerald_multiplayer.battle_mailbox import Status
from emerald_multiplayer.battle_roster import CanonicalBattler, validate_auxiliary_startup
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.cold_start import ColdStartRecovery
from emerald_multiplayer.companion import Companion, CompanionConfig, verify_rom_manifest
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.mailbox import inspect_mailbox
from emerald_multiplayer.native_battle import NativeControl, NativeQuery, Kind, Opcode
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore


async def run(args):
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root)+"/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    _, manifest = verify_rom_manifest(args.rom, args.manifest)
    if manifest.get("battle_abi_version") != args.native_abi:
        raise ValueError("native singles require the explicitly selected development ABI")
    if hashlib.sha256(args.elf.read_bytes()).hexdigest() != manifest["elf_sha256"]:
        raise ValueError("ELF does not match the native build manifest")
    if (args.observer_c is None) != (args.observer_d is None):
        raise ValueError("provide both independent observer saves together")
    sources = [args.save_a, args.save_b] + ([args.observer_c, args.observer_d] if args.observer_c else [])
    originals = [path.read_bytes() for path in sources]
    source_meta = [inspect_flash(payload).metadata for payload in originals]
    if len({m.trainer_id for m in source_meta}) != len(sources) or not all(m.party_count for m in source_meta[:2]):
        raise ValueError("two independent trainers with ordinary obtained Pokémon are required")
    original_hashes = [hashlib.sha256(data).hexdigest() for data in originals]
    root.mkdir(parents=True, mode=0o700)
    rom, manifest_path = root/"proof.gba", root/"manifest.json"
    rom.write_bytes(args.rom.read_bytes())
    manifest_path.write_bytes(args.manifest.read_bytes())
    (root/"controller.py").write_bytes(Path(__file__).read_bytes())
    bridge_source = args.bridge.read_text()
    (root/"bridge-source.lua").write_text(bridge_source)
    evidence = dict(scope="two actual native singles cores with session-local BattleDesk consent; explicit development typed router, no player challenge UI, 2v2 or Internet claim",
        engine_commit=manifest["engine_commit"], rom_sha256=manifest["rom_sha256"],
        elf_sha256=manifest["elf_sha256"], controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        bridge_sha256=hashlib.sha256(bridge_source.encode()).hexdigest(),
        harness_sha256=hashlib.sha256(args.harness.read_bytes()).hexdigest(),
        observer_count=len(sources)-2,
        sources=[dict(path=str(p), sha256=h, trainer_id=m.trainer_id)
                 for p, h, m in zip(sources, original_hashes, source_meta)],
        checks=[], snapshots=[], commands=[], blocks=[], passed=False, cores_closed=False)

    def persist():
        (root/"evidence.json").write_text(json.dumps(evidence, indent=2)+"\n")

    def record(name, **fields):
        row = dict(verified=name, **fields)
        evidence["checks"].append(row)
        persist()
        print(json.dumps(row), flush=True)

    process = await asyncio.create_subprocess_exec("arm-none-eabi-nm", "-S", str(args.elf), stdout=asyncio.subprocess.PIPE)
    symbols = {}
    for line in (await process.communicate())[0].decode().splitlines():
        parts = line.split()
        if len(parts) == 4:
            symbols[parts[3]] = (int(parts[0], 16), int(parts[1], 16))
    required = {"gBattleStringsTable": 721*4, "gRngValue": 16, "gRng2Value": 16,
                "gSaveCounter": 4, "gPartiesCount": 4, "gBattleTypeFlags": 4}
    if process.returncode or any(name not in symbols or symbols[name][1] != size for name, size in required.items()):
        raise ValueError("native proof symbols do not match the pinned ARM layout")
    validator = ControllerValidator(read_string_lengths(rom, table_address=symbols["gBattleStringsTable"][0]))
    store = TradeCheckpointStore(root/"world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
    from emerald_multiplayer.battle_reservations import enable_battle_reservations
    enable_battle_reservations(store, root/"before-battle-reservations.sqlite3")
    identities = sorted([store.create_player("Native Singles "+name) for name in "AB"], key=lambda p: p.player_id)
    if len(sources) == 4:
        identities.extend(store.create_player("Independent "+name) for name in "CD")
    for identity, payload in zip(identities, originals):
        store.enroll_player(identity.player_id, payload)
    (root/"profiles.json").write_text(json.dumps([dict(player_id=i.player_id,
        display_name=i.display_name, credential=i.credential.hex()) for i in identities], indent=2)+"\n")
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"],
        heartbeat_interval=.2, idle_timeout=12), store=store, development_trades=True)
    await server.start(port=0)
    saves = [root/f"client-{name}.sav" for name in "abcd"[:len(sources)]]
    companions, live, cores, all_cores, leases, rosters = [], [], [], [], [], []
    pump = None
    battle_id, generation, rng = str(uuid4()), None, None
    desk = None
    receipts, cold_contexts = {}, []
    running_authorized = False
    sequences = [0, 0]
    next_kind, next_block, pending = [2, 2], [1, 1], [None, None]
    last_keep = [0, 0]
    party_input = [None, None]
    observer_task = None
    revisions = [0]*len(sources)

    async def boot():
        for key, frames in ((0, 1000), (8, 8), (0, 480), (8, 8), (0, 180), (1, 8), (0, 300)):
            for offset in range(0, frames, 24):
                await asyncio.gather(*(c.command(f"F {key:x} {min(24, frames-offset)}") for c in cores))
                await asyncio.sleep(.003)
        for _ in range(400):
            if all(c.connected and c._bridge and c._bridge.save_capable and c._bridge.battle_capable for c in companions):
                return
            await asyncio.sleep(.025)
        raise AssertionError("native bridge capability did not become available")

    async def launch(i, held_lease=None):
        if held_lease is None:
            lease = MirrorLease(saves[i])
            lease.__enter__()
            leases.append(lease)
        elif not held_lease._held or held_lease.save_path != saves[i].resolve():
            raise ValueError("cold startup must retain the correct closed-save lease")
        script = root/f"bridge-{i}-{len(all_cores)}.lua"
        script.write_text(configure(manifest, companions[i].config.token.hex(), companions[i].ipc_address[1], bridge_source))
        proc = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(saves[i]), str(script),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        core = LockedCore(proc, root/f"core-{i}-{len(all_cores)}.log")
        cores.append(core)
        all_cores.append(core)
        if not (await asyncio.wait_for(proc.stdout.readline(), 30)).startswith(b"READY"):
            raise RuntimeError("actual native core failed to start")

    async def snapshot(label):
        rows = []
        for i, core in enumerate(cores):
            pose, _ = inspect_mailbox(await core.read(manifest["mailbox_address"], 128))
            state = int.from_bytes(await core.read(manifest["battle_mailbox_address"]+12, 4), "little")
            await core.command(f"P {root/(label+'-'+str(i)+'.png')}")
            rows.append(dict(player=i, pid=core.process.pid, pose=asdict(pose), state=state))
        evidence["snapshots"].append(dict(label=label, rows=rows))
        persist()
        return rows

    async def exercise_observers():
        captured = [(c.session_epoch, c.battle_incarnation) for c in companions]
        before = await snapshot("observers-before-movement")
        pump.keys[2:] = [0x80, 0x20]  # C walks down; D walks left.
        await pump.advance(48)
        pump.keys[2:] = [0, 0]
        await pump.advance(60)
        moved = await snapshot("observers-independent-movement")
        for i in (2, 3):
            assert moved[i]["state"] == 0 and moved[i]["pose"]["activity"] == 1
            assert tuple(moved[i]["pose"][k] for k in ("x", "y")) != tuple(before[i]["pose"][k] for k in ("x", "y"))
        pump.keys[3] = 8
        await pump.advance(18)  # Include a possible already queued six-frame batch.
        pump.keys[3] = 0
        await pump.advance(60)
        menu = await snapshot("observer-D-menu-during-native-battle")
        assert all(menu[i]["state"] == 5 for i in (0, 1))
        assert menu[2]["pose"]["activity"] == 1 and menu[3]["pose"]["activity"] != 1
        receipt = await live[2].checkpoint(expected_revision=1)
        assert receipt.metadata["revision"] == 2
        revisions[2] = 2
        during = await snapshot("observer-C-checkpoint-during-native-battle")
        assert all(during[i]["state"] == 5 for i in (0, 1))
        assert [(c.session_epoch, c.battle_incarnation) for c in companions] == captured
        for i in (2, 3):
            cp = store.read_checkpoint(identities[i].player_id, companions[i].session_epoch)
            assert cp.revision == revisions[i]
            assert inspect_ownership(inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)).records == inventories[i].records
        record("two-uninvolved-cores-move-menu-and-checkpoint-during-native-battle",
            observer_pids=[cores[i].process.pid for i in (2, 3)], revisions=revisions[2:])

    async def drive_party_menu(i):
        # An independent joypad task avoids missing a short Down press when
        # routing/snapshot work spans several native frames. Retry ordinary
        # menu inputs only while this owner still has a CHOOSEPOKEMON request.
        pump.keys[i] = 0
        await pump.advance(240)
        while validator.pending[i] == 21:
            for key, duration in ((2, 18), (0, 12), (0x80, 18), (0, 12)):
                pump.keys[i] = key
                await pump.advance(duration)
            for _ in range(20):
                if validator.pending[i] != 21:
                    break
                pump.keys[i] = 1
                await pump.advance(6)
                pump.keys[i] = 0
                await pump.advance(6)
        pump.keys[i] = 0

    async def native_state(i):
        core = cores[i]
        party = await core.read(manifest["debug_parties_address"], 600)
        ptr = int.from_bytes(await core.read(manifest["debug_save_block2_ptr_address"], 4), "little")
        return dict(party_sha256=hashlib.sha256(party).hexdigest(),
            party_count=(await core.read(symbols["gPartiesCount"][0], 1))[0],
            rng=(await core.read(symbols["gRngValue"][0], 16)).hex(),
            rng2=(await core.read(symbols["gRng2Value"][0], 16)).hex(),
            playtime=(await core.read(ptr+manifest["debug_play_time_offset"], 5)).hex(),
            counter=int.from_bytes(await core.read(symbols["gSaveCounter"][0], 4), "little"))

    async def query(i):
        c = companions[i]
        command = NativeControl(c.battle_incarnation, c.session_epoch, battle_id,
            max(1, sequences[i]), Opcode.QUERY, source_slot=i)
        response = await c.battle_rpc(command)
        if response.status != Status.OK:
            raise AssertionError(("query", i, int(response.status)))
        receipts[i, Opcode.QUERY] = (command, response)
        return NativeQuery.unpack(response.data)

    async def rpc(i, opcode, *, allow_busy=False, **fields):
        c = companions[i]
        source = fields.pop("source_slot", i)
        command = NativeControl(c.battle_incarnation, c.session_epoch, battle_id,
            sequences[i]+1, opcode, source_slot=source, **fields)
        response = await c.battle_rpc(command)
        evidence["commands"].append(dict(client=i, command=command.pack().hex(), response=response.pack().hex()))
        if response.status != Status.OK and not (allow_busy and response.status == Status.BUSY):
            persist()
            raise AssertionError(("native command refused", i, int(opcode), int(response.status), sequences[i]))
        if response.status == Status.OK:
            sequences[i] += 1
            receipts[i, opcode] = (command, response)
            callback = {Opcode.BIND: "bound", Opcode.START: "started",
                        Opcode.KEEP: "keepalive", Opcode.RELEASE: "released"}.get(opcode)
            if callback:
                getattr(desk, callback)(identities[i].player_id, c.session_epoch,
                    battle_id, generation, command, response)
        return response

    async def route_once():
        nonlocal running_authorized
        queries = [await query(i) for i in range(2)]
        for source, q in enumerate(queries):
            if q.expired or q.recovery_required:
                raise AssertionError(("native recovery hold", source, asdict(q)))
            if pending[source] is None and q.outbound_pending:
                if q.outbound_sequence != next_block[source] or q.outbound_kind != next_kind[source]:
                    raise AssertionError(("native startup/order mismatch", source, asdict(q), next_block, next_kind))
                # A core may produce its first controller immediately after it
                # consumes RNG while the peer's final startup ACK is in flight.
                if q.outbound_kind == Kind.CONTROLLER and any(value < 8 for value in next_kind):
                    continue
                data = b""
                for offset in range(0, q.outbound_size, 128):
                    response = await rpc(source, Opcode.READ_OUT, block_sequence=q.outbound_sequence,
                        offset=offset, total_size=q.outbound_size, kind=q.outbound_kind)
                    data += response.data
                if zlib.crc32(data) != q.outbound_crc32:
                    raise AssertionError("complete native outbound CRC mismatch")
                if q.outbound_kind in (Kind.TRAINER, Kind.PARTY_0, Kind.PARTY_1, Kind.PARTY_2):
                    rosters[source].verify_startup(q.outbound_kind, data)
                    actor, lease = identities[source].player_id, companions[source].session_epoch
                    if q.outbound_kind == Kind.TRAINER:
                        desk.prepared(actor, lease, battle_id, generation,
                            *receipts[source, Opcode.PREPARE], data)
                    else:
                        desk.verify_startup(actor, lease, battle_id, generation,
                            q.outbound_kind, q.outbound_sequence, data)
                elif q.outbound_kind in (Kind.START_HEADER, Kind.RNG):
                    validate_auxiliary_startup(q.outbound_kind, data, issued_rng=rng)
                else:
                    if not running_authorized:
                        raise AssertionError("controller routing requires the trusted startup barrier")
                    validator.accept(data, source)
                    if data[0] == 0 and data[8] == 21 and rosters[data[1]].party_count > 1:
                        # This ordinary source party has Torchic in slot0 and
                        # Wurmple in slot1. After a forced-switch menu opens,
                        # press Down once then select normally with A.
                        party_input[data[1]] = asyncio.create_task(drive_party_menu(data[1]))
                pending[source] = dict(sequence=q.outbound_sequence, kind=q.outbound_kind,
                    data=data, offset=0, crc32=q.outbound_crc32)
                evidence["blocks"].append(dict(source=source, sequence=q.outbound_sequence,
                    kind=q.outbound_kind, data=data.hex(), frame=pump.frames))
        for source in range(2):
            block, target = pending[source], 1-source
            if block is None:
                continue
            offset, data = block["offset"], block["data"]
            response = await rpc(target, Opcode.RECEIVE, source_slot=source,
                block_sequence=block["sequence"], offset=offset, total_size=len(data),
                kind=block["kind"], data=data[offset:offset+128], allow_busy=True)
            if response.status == Status.BUSY:
                continue
            block["offset"] += len(data[offset:offset+128])
            if block["offset"] == len(data):
                await rpc(source, Opcode.ACK_OUT, block_sequence=block["sequence"], offset=len(data),
                    total_size=len(data), kind=block["kind"], data=struct.pack("<II", block["crc32"], 1 << target))
                next_block[source] += 1
                if next_kind[source] < 8:
                    next_kind[source] += 1
                pending[source] = None
        if not running_authorized and next_kind == [8, 8] and pending == [None, None]:
            desk.authorize_running(battle_id, generation)
            running_authorized = True
        for i in range(2):
            if pump.frames-last_keep[i] >= 180:
                await rpc(i, Opcode.KEEP)
                last_keep[i] = pump.frames
        return queries

    try:
        for i, identity in enumerate(identities):
            saves[i].write_bytes(originals[i])
            c = Companion(CompanionConfig(rom, manifest_path, identity.player_id, identity.display_name,
                secrets.token_bytes(32), server_port=server.address[1], ipc_port=0,
                server_credential=identity.credential, development_battle_channel=True))
            await c.start()
            companions.append(c)
            live.append(LiveCheckpointCoordinator(c, root/f"private-{i}"))
        for i in range(len(sources)): await launch(i)
        await boot()
        initial = await snapshot("01-native-Continue")
        assert all(row["pose"]["activity"] == 1 for row in initial)
        pump = DiagnosticPump(cores, companions)
        pump.start()
        inventories, original_flash = [], []
        for i in range(len(sources)):
            receipt = await live[i].enroll()
            assert receipt.metadata["revision"] == 1
            revisions[i] = 1
            cp = store.read_checkpoint(identities[i].player_id, companions[i].session_epoch)
            if i < 2:
                rosters.append(CanonicalBattler.from_checkpoint(cp, world_id=store.metadata.world_id,
                    build_id=store.build_id, ruleset_id=store.ruleset_id, source_slot=i))
            inventories.append(inspect_ownership(inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)))
            flash_path = root/f"before-battle-{i}.flash"
            await cores[i].command(f"D {flash_path}")
            original_flash.append(flash_path.read_bytes())
        record("two-ordinary-Continue-and-canonical-owned-parties", counts=[r.party_count for r in rosters])
        desk = BattleDesk(store, lambda actor: next(
            (c.session_epoch for c in companions if c.connected and c.config.player_id == actor), None))
        offer = desk.invite(identities[0].player_id, companions[0].session_epoch, identities[1].player_id, battle_id)
        generation = offer["generation"]
        desk.accept(identities[1].player_id, companions[1].session_epoch, battle_id, generation, offer["fingerprint"])
        for i in range(2):
            desk.register(identities[i].player_id, companions[i].session_epoch,
                battle_id, generation, companions[i].battle_incarnation)
        for i in range(2):
            bound = desk.authorize_bind(identities[i].player_id, companions[i].session_epoch, battle_id, generation)
            await rpc(i, Opcode.BIND, data=bound.pack())
        held = [await native_state(i) for i in range(2)]
        for i in range(2):
            assert held[i]["party_sha256"] == hashlib.sha256(rosters[i].party).hexdigest()
            preparation = desk.preparation(identities[i].player_id, companions[i].session_epoch, battle_id, generation)
            if rng is None:
                rng = preparation.rng
            assert preparation == rosters[i].preparation(rng)
            await rpc(i, Opcode.PREPARE, data=preparation.pack())
        for _ in range(30):
            await route_once()
            if next_kind == [3, 3] and pending == [None, None]: break
        else: raise AssertionError("prepared trainer descriptors did not complete")
        record("both-prepared-and-exact-canonical-trainers-routed")
        desk.authorize_start(battle_id, generation)
        for i in range(2): await rpc(i, Opcode.START)
        await snapshot("02-native-battle-entry")
        if len(sources) == 4:
            observer_task = asyncio.create_task(exercise_observers())
        deadline, last_snapshot = time.monotonic()+args.timeout, time.monotonic()
        while time.monotonic() < deadline:
            # Ordinary repeated A presses select the default action/move. No
            # controller choice or move is injected by the proof coordinator.
            for i, selection in enumerate(party_input):
                if selection is not None and selection.done():
                    await selection
                    party_input[i] = None
                if party_input[i] is None:
                    pump.keys[i] = 1 if pump.frames//12 % 2 else 0
            if observer_task is not None and observer_task.done():
                await observer_task
            queries = await route_once()
            if all(q.restored for q in queries) and pending == [None, None] and not any(q.outbound_pending for q in queries):
                break
            if time.monotonic()-last_snapshot > 10:
                await snapshot(f"battle-{len(evidence['snapshots']):03}")
                print(json.dumps(dict(progress="native battle", blocks=len(evidence["blocks"]), frames=pump.frames)), flush=True)
                last_snapshot = time.monotonic()
            await asyncio.sleep(.01)
        else:
            raise AssertionError("native singles did not reach the restored field hold before timeout")
        pump.keys[:] = [0]*len(sources)
        if observer_task is not None:
            await observer_task
            pump.keys[:] = [0]*len(sources)
        after = [await native_state(i) for i in range(2)]
        # Native battle time is ordinary elapsed playtime; restoring the
        # protected party/RNG must not rewind that clock or world progress.
        for before_state, after_state in zip(held, after):
            for key in ("party_sha256", "party_count", "rng", "rng2", "counter"):
                assert before_state[key] == after_state[key], (key, before_state, after_state)
        assert queries[0].outcome == queries[1].outcome and queries[0].outcome in (1, 2, 3)
        for i in range(2):
            flash_path = root/f"after-battle-held-{i}.flash"
            await cores[i].command(f"D {flash_path}")
            assert flash_path.read_bytes() == original_flash[i]
        await snapshot("03-exact-party-RNG-restored-field-held")
        record("native-battle-result-and-exact-personal-restoration", outcome=queries[0].outcome,
            playtime_before=[s["playtime"] for s in held], playtime_after=[s["playtime"] for s in after],
            routed_blocks=len(evidence["blocks"]),
            master_commands=sorted({b["data"][16:18] for b in evidence["blocks"] if b["kind"] == 8 and b["data"].startswith("00")}),
            owner_reply_commands=sorted({b["data"][16:18] for b in evidence["blocks"] if b["kind"] == 8 and b["data"].startswith("01")}))
        for i in range(2):
            desk.finish(identities[i].player_id, companions[i].session_epoch, battle_id, generation,
                *receipts[i, Opcode.QUERY], outcome=queries[i].outcome,
                party=await cores[i].read(manifest["debug_parties_address"], 600), party_count=held[i]["party_count"])
        for i in range(2):
            await rpc(i, Opcode.RELEASE, data=struct.pack("<II", rosters[i].party_crc32, queries[i].outcome))
        assert desk.status(identities[0].player_id, companions[0].session_epoch, battle_id)["state"] == "closed"
        if len(sources) == 4:
            pump.keys[3] = 2  # Close D's ordinary menu with B.
            await pump.advance(18)
            pump.keys[3] = 0
        await pump.advance(120)
        returned = await snapshot("04-independent-current-map-return")
        for before, after_row in zip(initial[:2], returned[:2]):
            assert after_row["pose"]["activity"] == 1
            for key in ("map_group", "map_number", "x", "y"):
                assert before["pose"][key] == after_row["pose"][key]
        for i in range(len(sources)):
            receipt = await live[i].checkpoint(expected_revision=revisions[i])
            assert receipt.metadata["revision"] == revisions[i]+1
            revisions[i] += 1
            cp = store.read_checkpoint(identities[i].player_id, companions[i].session_epoch)
            assert inspect_ownership(inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)).records == inventories[i].records
        record("both-current-maps-and-ordinary-native-checkpoints-preserve-owned-inventories")
        await pump.close()
        pump = None
        for core in cores: await core.close()
        cores.clear()
        for lease in leases: lease.__exit__(None, None, None)
        leases.clear()
        for _ in range(200):
            if all(c.connected and c._bridge is None for c in companions): break
            await asyncio.sleep(.025)
        else: raise AssertionError("closed cores failed to detach and reauthenticate")
        for i in range(len(sources)):
            recovery = ColdStartRecovery(companions[i], root/f"private-{i}", saves[i])
            context = recovery.open()
            verified = await context.__aenter__()
            cold_contexts.append(context)
            await launch(i, verified.lease)
        await boot()
        fresh = await snapshot("05-fresh-native-Continue")
        assert all(row["pose"]["activity"] == 1 and row["state"] == 0 for row in fresh)
        for i in range(len(sources)):
            cp = store.read_checkpoint(identities[i].player_id, companions[i].session_epoch)
            parsed = inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)
            assert cp.revision == revisions[i]
            assert (await native_state(i))["party_sha256"] == hashlib.sha256(parsed.save_block1[0x238:0x238+600]).hexdigest()
            for key in ("map_group", "map_number", "x", "y"):
                assert fresh[i]["pose"][key] == getattr(parsed.metadata, key)
        store.integrity_check()
        assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources] == original_hashes
        record("fresh-Continue-and-original-source-hashes-preserved")
        evidence["passed"] = True
    except BaseException:
        evidence["error"] = traceback.format_exc()
        diagnostics = []
        for core in cores:
            state = {}
            for name in ("gBattleControllerExecFlags", "gBattleMainFunc", "gBattlerControllerFuncs",
                         "gBattlerControllerEndFuncs", "gBattlerAttacker", "gBattlerTarget", "gEffectBattler",
                         "gAbsentBattlerFlags", "gActiveBattler", "gTasks", "gBattleOutcome",
                         "gLinkBattleSendBuffer", "gLinkBattleRecvBuffer", "gMultiplayerBattleFailure"):
                if name not in symbols:
                    continue
                address, size = symbols[name]
                if not (0x02000000 <= address < 0x02040000 or 0x03000000 <= address < 0x03008000) or size > 4096:
                    continue
                try:
                    data = await core.read(address, size)
                    state[name] = data.hex()
                    if name in ("gLinkBattleSendBuffer", "gLinkBattleRecvBuffer") and size == 4:
                        pointer = int.from_bytes(data, "little")
                        if 0x02000000 <= pointer <= 0x0203F000:
                            state[name+"_bytes"] = (await core.read(pointer, 4096)).hex()
                except BaseException:
                    pass
            diagnostics.append(state)
        evidence["failure_diagnostics"] = diagnostics
        try: await snapshot("failure")
        except BaseException: pass
        raise
    finally:
        for task in party_input:
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(t for t in party_input if t is not None), return_exceptions=True)
        if observer_task is not None and not observer_task.done():
            observer_task.cancel()
            await asyncio.gather(observer_task, return_exceptions=True)
        if pump is not None: await pump.close()
        await asyncio.gather(*(core.close() for core in all_cores), return_exceptions=True)
        for lease in leases: lease.__exit__(None, None, None)
        for context in reversed(cold_contexts): await context.__aexit__(None, None, None)
        await asyncio.gather(*(c.close() for c in companions), return_exceptions=True)
        await server.close()
        store.close()
        evidence["cores_closed"] = all(c.process.returncode is not None for c in all_cores)
        evidence["original_sources_unchanged"] = [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources] == original_hashes
        if not evidence["cores_closed"] or not evidence["original_sources_unchanged"]:
            evidence["passed"] = False
        persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "elf", "manifest", "harness", "save-a", "save-b", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2]/"bridge/mgba.lua")
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--native-abi", type=int, choices=(2, 3), default=2,
        help="Explicitly opt into the singles compatibility proof on an ABI3 build")
    parser.add_argument("--observer-c", type=Path)
    parser.add_argument("--observer-d", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
