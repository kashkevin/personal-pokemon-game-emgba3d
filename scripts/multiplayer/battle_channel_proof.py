"""Two actual ROMs exercising only the typed development native-block channel.

This explicitly opted-in coordinator routes bytes between two authenticated
companions. There is no server battle-routing desk, invitation consent, native
battle entry or controller dispatch in this proof. Gameplay uses ordinary keys;
only the production Lua bridge writes allocated mailbox command slots.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import secrets
import struct
from uuid import uuid4
import zlib

from configure_bridge import configure
from live_checkpoint_proof import LockedCore, Pump
from emerald_multiplayer.battle_mailbox import (
    BattleBinding, BattleControl, BattleQuery, DiagnosticBlock,
    Kind, Opcode, State, Status, inspect_battle_mailbox,
)
from emerald_multiplayer.checkpoint_client import CheckpointClient
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.cold_start import ColdStartRecovery
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.mailbox import inspect_mailbox
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.save_mailbox import (
    FLASH_SIZE, Opcode as SaveOpcode, SaveControl, Status as SaveStatus,
)
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore


class DiagnosticPump(Pump):
    async def _run(self):
        # Bounded frame progress keeps the 600-frame idle hold observable rather
        # than accidentally consuming it at maximum headless emulation speed.
        while True:
            await asyncio.gather(*(core.command(f"F {key:x} 6")
                for core, key in zip(self.cores, self.keys)))
            self.frames += 6
            await asyncio.sleep(.03)


async def run(args):
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    rom_bytes = args.rom.read_bytes()
    if (manifest.get("battle_abi_version") != 1
            or hashlib.sha256(rom_bytes).hexdigest() != manifest["rom_sha256"]):
        raise ValueError("a verified frozen diagnostic ROM is required")
    sources = [args.save_a, args.save_b]
    originals = [p.read_bytes() for p in sources]
    original_hashes = [hashlib.sha256(p).hexdigest() for p in originals]
    source_metadata = [inspect_flash(p).metadata for p in originals]
    if source_metadata[0].trainer_id == source_metadata[1].trainer_id:
        raise ValueError("two independent native trainers are required")
    root.mkdir(parents=True, mode=0o700)
    rom, manifest_path = root / "proof.gba", root / "manifest.json"
    rom.write_bytes(rom_bytes)
    manifest_path.write_bytes(manifest_bytes)
    bridge_source = args.bridge.read_text()
    (root / "bridge-source.lua").write_text(bridge_source)
    (root / "controller.py").write_bytes(Path(__file__).read_bytes())
    evidence = dict(scope="two actual ROM typed diagnostics routed by an explicit development coordinator; no native battles or server battle consent/routing",
        engine_commit=manifest["engine_commit"], rom_sha256=manifest["rom_sha256"],
        sources=[dict(path=str(p), sha256=h, trainer_id=m.trainer_id)
            for p, h, m in zip(sources, original_hashes, source_metadata)],
        bridge_sha256=hashlib.sha256(bridge_source.encode()).hexdigest(),
        harness_sha256=hashlib.sha256(args.harness.read_bytes()).hexdigest(),
        checks=[], snapshots=[], commands=[], passed=False)

    def persist():
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")

    def record(name, **fields):
        row = dict(verified=name, **fields)
        evidence["checks"].append(row)
        persist()
        print(json.dumps(row), flush=True)

    names = {"gRngValue": 16, "gBlockRecvBuffer": 1024, "gBlockSendBuffer": 256,
        "gSoftResetDisabled": 1, "gSaveCounter": 4, "gBattleTypeFlags": 4,
        "gReceivedRemoteLinkPlayers": 1}
    process = await asyncio.create_subprocess_exec("arm-none-eabi-nm", "-S", str(args.elf),
        stdout=asyncio.subprocess.PIPE)
    nm = (await process.communicate())[0].decode()
    if process.returncode:
        raise RuntimeError("matching ELF symbol inspection failed")
    symbols = {}
    for line in nm.splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[3] in names:
            address, size = int(fields[0], 16), int(fields[1], 16)
            # gBlockRecvBuffer includes an additional native scratch row. This
            # diagnostic reads only the four bounded participant rows.
            if size < names[fields[3]]:
                raise ValueError("ELF diagnostic symbol is undersized")
            symbols[fields[3]] = address
    if set(symbols) != set(names) or hashlib.sha256(args.elf.read_bytes()).hexdigest() != manifest["elf_sha256"]:
        raise ValueError("ELF does not match the frozen diagnostic manifest")
    evidence["read_only_symbols"] = symbols
    # Canonical cold startup queries authoritative pending-trade status even
    # when no trade occurred. Enable that existing read API only in this slice.
    store_type = TradeCheckpointStore if args.reconnect else OwnershipCheckpointStore
    store = store_type(root / "world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
    identities = [store.create_player("Diagnostic " + label) for label in "AB"]
    for identity, payload in zip(identities, originals):
        store.enroll_player(identity.player_id, payload)
    (root / "profiles.json").write_text(json.dumps([dict(player_id=p.player_id,
        display_name=p.display_name, credential=p.credential.hex()) for p in identities], indent=2) + "\n")
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"],
        heartbeat_interval=.2, idle_timeout=12), store=store, development_trades=args.reconnect)
    await server.start(port=0)
    saves = [root / ("client-" + label + ".sav") for label in "ab"]
    companions, cores, leases, live = [], [], [], []
    pump = None
    battle_id, generation = str(uuid4()), str(uuid4())
    sequences = [0, 0]
    bindings = []
    cold_contexts = []

    async def launch(i, held_lease=None):
        if held_lease is None:
            lease = MirrorLease(saves[i])
            lease.__enter__()
            leases.append(lease)
        elif not held_lease._held or held_lease.save_path != saves[i].resolve():
            raise ValueError("cold startup must retain the correct closed-save lease")
        script = root / f"bridge-{i}.lua"
        script.write_text(configure(manifest, companions[i].config.token.hex(),
            companions[i].ipc_address[1], bridge_source))
        proc = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(saves[i]), str(script),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        core = LockedCore(proc, root / f"core-{i}-{len(evidence['snapshots'])}.log")
        cores.append(core)
        if not (await asyncio.wait_for(proc.stdout.readline(), 30)).startswith(b"READY"):
            raise RuntimeError("actual core failed to start")

    async def boot():
        for key, frames in ((0, 1000), (8, 8), (0, 480), (8, 8), (0, 180), (1, 8), (0, 300)):
            for offset in range(0, frames, 24):
                await asyncio.gather(*(c.command(f"F {key:x} {min(24, frames-offset)}") for c in cores))
                await asyncio.sleep(.003)
        for _ in range(400):
            if all(c.connected and c._bridge and c._bridge.save_capable and c._bridge.battle_capable for c in companions):
                return
            await asyncio.sleep(.025)
        raise AssertionError([(c.connected, c.last_error) for c in companions])

    async def snapshot(label):
        result = []
        for i, core in enumerate(cores):
            pose, _ = inspect_mailbox(await core.read(manifest["mailbox_address"], 128))
            mailbox = inspect_battle_mailbox(await core.read(manifest["battle_mailbox_address"], 512))
            await core.command(f"P {root / (label + '-' + str(i) + '.png')}")
            result.append(dict(pose=asdict(pose), state=int(mailbox.state), frame=mailbox.frame,
                core_pid=core.process.pid, lease=companions[i].session_epoch,
                incarnation=companions[i].battle_incarnation))
        evidence["snapshots"].append(dict(label=label, clients=result))
        persist()
        return result

    async def read_state(i):
        core = cores[i]
        rng = await core.read(symbols["gRngValue"], 16)
        party = await core.read(manifest["debug_parties_address"], 600)
        ptr = int.from_bytes(await core.read(manifest["debug_save_block2_ptr_address"], 4), "little")
        playtime = await core.read(ptr + manifest["debug_play_time_offset"], 5)
        fields = {name: (await core.read(address, names[name])).hex()
            for name, address in symbols.items() if name not in {"gRngValue", "gBlockRecvBuffer", "gBlockSendBuffer"}}
        return dict(rng=rng.hex(), party_sha256=hashlib.sha256(party).hexdigest(),
            playtime=playtime.hex(), **fields)

    async def rpc(i, opcode, *, expected=Status.OK, **fields):
        sequences[i] += 1
        c = companions[i]
        source_slot = fields.pop("source_slot", i)
        command = BattleControl(c.battle_incarnation, c.session_epoch, battle_id,
            sequences[i], opcode, source_slot=source_slot, **fields)
        response = await c.battle_rpc(command)
        assert response.status == expected, (opcode, response.status, expected)
        evidence["commands"].append(dict(client=i, command_hex=command.pack().hex(), response_hex=response.pack().hex()))
        persist()
        return command, response

    async def query(i):
        c = companions[i]
        response = await c.battle_rpc(BattleControl(c.battle_incarnation, c.session_epoch,
            battle_id, max(1, sequences[i]), Opcode.QUERY, source_slot=i))
        assert response.status == Status.OK
        return BattleQuery.unpack(response.data)

    async def flash_clone(i, label):
        path = root / f"{label}-{i}.flash"
        assert (await cores[i].command(f"D {path}")).startswith("FLASH OK ")
        return path.read_bytes()

    try:
        for i, identity in enumerate(identities):
            saves[i].write_bytes(originals[i])
            companion = Companion(CompanionConfig(rom, manifest_path, identity.player_id, identity.display_name,
                secrets.token_bytes(32), server_port=server.address[1], ipc_port=0,
                server_credential=identity.credential, development_battle_channel=True))
            await companion.start()
            companions.append(companion)
            live.append(LiveCheckpointCoordinator(companion, root / f"private-{i}"))
        for i in range(2):
            await launch(i)
        await boot()
        before = await snapshot("01-independent-legacy-Continue")
        assert all(item["pose"]["activity"] == 1 for item in before)
        pump = DiagnosticPump(cores, companions)
        pump.start()
        inventories = []
        for i in range(2):
            receipt = await live[i].enroll()
            parsed = inspect_flash((await CheckpointClient(companions[i]).download()).payload, save_profile=OWNERSHIP_PROFILE)
            inventories.append(inspect_ownership(parsed))
            assert receipt.metadata["revision"] == 1
        record("two-native-Continue-and-explicit-independent-ownership-enrollment",
            core_pids=[c.process.pid for c in cores], counts=[len(o.records) for o in inventories])
        flash_before = [await flash_clone(i, "before-channel") for i in range(2)]
        native_before = [await read_state(i) for i in range(2)]
        for i in range(2):
            binding = BattleBinding(generation, tuple(p.player_id for p in identities),
                tuple(c.session_epoch for c in companions), tuple(c.battle_incarnation for c in companions), i)
            bindings.append(binding)
            _, response = await rpc(i, Opcode.BIND, data=binding.pack())
            assert BattleQuery.unpack(response.data).held
        held = [await read_state(i) for i in range(2)]
        for i in range(2):
            assert held[i]["party_sha256"] == native_before[i]["party_sha256"]
            assert held[i]["gSaveCounter"] == native_before[i]["gSaveCounter"]
            assert held[i]["gSoftResetDisabled"] == "01"
            assert held[i]["gBattleTypeFlags"] == "00000000" and held[i]["gReceivedRemoteLinkPlayers"] == "00"
        record("diagnostic-bind-holds-safely-without-party-save-or-battle-entry", held=held)

        for source, token in ((0, 0xDEADBEEF), (1, 0x12345678)):
            target = 1 - source
            _, emitted = await rpc(source, Opcode.EMIT_DIAGNOSTIC, data=struct.pack("<I", token))
            outgoing = BattleQuery.unpack(emitted.data)
            assert outgoing.outbound_pending and outgoing.received_mask & (1 << source)
            _, _ = await rpc(source, Opcode.EMIT_DIAGNOSTIC, data=struct.pack("<I", token+1), expected=Status.BUSY)
            read_command, response = await rpc(source, Opcode.READ_OUT, block_sequence=1, total_size=40, kind=Kind.DIAGNOSTIC)
            frame = DiagnosticBlock.unpack(response.data).validate_binding(bindings[source])
            assert frame.source_slot == source and frame.token == token
            replay = await companions[source].battle_rpc(read_command)
            assert replay == response and (await query(source)).read_offset == 40
            assert await cores[source].read(symbols["gBlockSendBuffer"], 40) == response.data
            assert await cores[source].read(symbols["gBlockRecvBuffer"] + source*256, 40) == response.data
            if source == 1:
                wrong = replace(frame, generation=str(uuid4())).pack()
                _, _ = await rpc(target, Opcode.RECEIVE, block_sequence=1, total_size=40,
                    kind=Kind.DIAGNOSTIC, data=wrong, expected=Status.ROLE, source_slot=source)
            _, received = await rpc(target, Opcode.RECEIVE, block_sequence=1, total_size=40,
                kind=Kind.DIAGNOSTIC, data=response.data, source_slot=source)
            assert received.status == Status.OK
            assert await cores[target].read(symbols["gBlockRecvBuffer"] + source*256, 40) == response.data
            assert (await query(target)).received_mask & (1 << source)
            _, _ = await rpc(source, Opcode.ACK_OUT, block_sequence=1, total_size=40, offset=40,
                kind=Kind.DIAGNOSTIC, data=struct.pack("<II", zlib.crc32(response.data)^1, 1 << target), expected=Status.CRC)
            assert (await query(source)).outbound_pending
            _, _ = await rpc(source, Opcode.ACK_OUT, block_sequence=1, total_size=40, offset=40,
                kind=Kind.DIAGNOSTIC, data=struct.pack("<II", zlib.crc32(response.data), 1 << target))
            assert not (await query(source)).outbound_pending
            _, _ = await rpc(target, Opcode.CLEAR_RX, data=struct.pack("<I", 1 << source))
            _, _ = await rpc(target, Opcode.RECEIVE, block_sequence=1, total_size=40,
                kind=Kind.DIAGNOSTIC, data=response.data, source_slot=source)
            assert not (await query(target)).received_mask & (1 << source)
            _, _ = await rpc(target, Opcode.RECEIVE, block_sequence=3, total_size=40,
                kind=Kind.DIAGNOSTIC, data=response.data, source_slot=source, expected=Status.ORDER)
            _, _ = await rpc(source, Opcode.CLEAR_RX, data=struct.pack("<I", 1 << source))
            record("typed-native-block-roundtrip-and-replay-flow-control", source=source,
                frame=asdict(frame), block_sha256=hashlib.sha256(response.data).hexdigest())
            await rpc(0, Opcode.KEEP)
            await rpc(1, Opcode.KEEP)

        for i in range(2):
            c = companions[i]
            refused = await c.save_rpc(SaveControl(c.save_incarnation, c.session_epoch,
                str(uuid4()), 1, 0, FLASH_SIZE, 0, SaveOpcode.BIND))
            assert refused.status == SaveStatus.BUSY
        record("ordinary-save-bind-cannot-bypass-diagnostic-hold")
        await pump.press(0, 15, 18, 12)  # A+B+Start+Select: reset remains disabled.
        for i in range(2):
            await rpc(i, Opcode.KEEP)
        await pump.advance(660)
        expired = [await query(i) for i in range(2)]
        assert all(q.held and q.expired and q.remaining_frames == 0 for q in expired)
        for i in range(2):
            await rpc(i, Opcode.KEEP, expected=Status.TIMEOUT)
            assert await read_state(i) == held[i]
            assert await flash_clone(i, "expired-channel") == flash_before[i]
        expired_snap = await snapshot("02-expired-held-no-reset-or-callback-progress")
        assert all(item["pose"]["activity"] == 0 and item["state"] == State.EXPIRED for item in expired_snap)
        record("idle-expiration-remains-held-and-freezes-rng-playtime-party-Flash")
        for i in range(2):
            await rpc(i, Opcode.CLOSE)
        await pump.advance(120)
        resumed = await snapshot("03-channel-close-resumed")
        assert all(item["pose"]["activity"] == 1 and item["state"] == State.IDLE for item in resumed)
        await pump.press(0, 16, 18, 48)
        moved = await snapshot("04-ordinary-local-movement-after-close")
        assert moved[0]["pose"]["x"] != resumed[0]["pose"]["x"]
        for i in range(2):
            state = await read_state(i)
            assert state["rng"] != held[i]["rng"] and state["party_sha256"] == held[i]["party_sha256"]
            assert state["gSoftResetDisabled"] == native_before[i]["gSoftResetDisabled"]
            receipt = await live[i].checkpoint(expected_revision=1)
            parsed = inspect_flash((await CheckpointClient(companions[i]).download()).payload, save_profile=OWNERSHIP_PROFILE)
            assert inspect_ownership(parsed).records == inventories[i].records
            assert receipt.metadata["revision"] == 2
        record("close-restores-reset-clock-movement-and-ordinary-checkpoint-with-identities")
        if args.reconnect:
            # A fresh generation enters a second hold after the ordinary saved
            # checkpoint. A network lease change deliberately cannot release it.
            battle_id, generation = str(uuid4()), str(uuid4())
            old_lease = companions[0].session_epoch
            old_incarnation = companions[0].battle_incarnation
            for i in range(2):
                binding = BattleBinding(generation, tuple(p.player_id for p in identities),
                    tuple(c.session_epoch for c in companions), tuple(c.battle_incarnation for c in companions), i)
                await rpc(i, Opcode.BIND, data=binding.pack())
            reconnect_held = await read_state(0)
            companions[0]._remote_writer.close()
            for _ in range(200):
                if companions[0].connected and companions[0].session_epoch > old_lease:
                    break
                await asyncio.sleep(.025)
            else:
                raise AssertionError("authenticated companion failed to obtain a new lease")
            assert companions[0].battle_incarnation == old_incarnation
            observed = await query(0)
            assert observed.held and observed.generation == generation
            await rpc(0, Opcode.CLOSE, expected=Status.SESSION)
            assert await read_state(0) == reconnect_held
            record("new-authenticated-lease-can-observe-but-cannot-release-old-hold",
                old_lease=old_lease, new_lease=companions[0].session_epoch,
                incarnation=old_incarnation, held_query=asdict(observed))
            await pump.close()
            pump = None
            old_pids = [c.process.pid for c in cores]
            for core in cores:
                await core.close()
            cores.clear()
            for lease in leases:
                lease.__exit__(None, None, None)
            leases.clear()
            for _ in range(200):
                if all(c.connected and c._bridge is None for c in companions):
                    break
                await asyncio.sleep(.025)
            else:
                raise AssertionError("closed bridge failed to detach before startup reconciliation")
            for i in range(2):
                recovery = ColdStartRecovery(companions[i], root / f"private-{i}", saves[i])
                context = recovery.open()
                verified = await context.__aenter__()
                cold_contexts.append(context)
                await launch(i, verified.lease)
            await boot()
            fresh = await snapshot("05-canonical-closed-start-fresh-Continue")
            assert all(row["pose"]["activity"] == 1 and row["state"] == State.UNBOUND for row in fresh)
            for i in range(2):
                assert cores[i].process.pid != old_pids[i]
                assert (await read_state(i))["party_sha256"] == held[i]["party_sha256"]
                canonical = await CheckpointClient(companions[i]).download()
                assert canonical.metadata["revision"] == 2
                assert inspect_ownership(inspect_flash(canonical.payload, save_profile=OWNERSHIP_PROFILE)).records == inventories[i].records
            record("canonical-startup-reconciliation-precedes-fresh-Continue-after-unreleasable-diagnostic-hold",
                previous_pids=old_pids, current_pids=[c.process.pid for c in cores])
        store.integrity_check()
        assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources] == original_hashes
        record("original-source-saves-unchanged-and-owned-database-integrity-valid")
        evidence["passed"] = True
        persist()
    finally:
        if pump is not None:
            await pump.close()
        await asyncio.gather(*(c.close() for c in cores), return_exceptions=True)
        for lease in leases:
            lease.__exit__(None, None, None)
        for context in reversed(cold_contexts):
            await context.__aexit__(None, None, None)
        await asyncio.gather(*(c.close() for c in companions), return_exceptions=True)
        await server.close()
        store.close()
        evidence["cores_closed"] = all(c.process.returncode is not None for c in cores)
        persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "elf", "manifest", "harness", "save-a", "save-b", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2] / "bridge/mgba.lua")
    parser.add_argument("--reconnect", action="store_true", help="Also prove new-lease refusal and guarded canonical cold startup")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
