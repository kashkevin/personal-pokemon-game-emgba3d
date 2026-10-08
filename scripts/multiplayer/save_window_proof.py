"""Two actual ROMs: optional sector reads, legacy fallback and native persistence.

All game inputs are ordinary joypad commands. Flash clones and named memory
reads use official libmGBA diagnostics. Production Lua alone writes mailboxes.
Private fresh output preserves failed runs as well as successful evidence.
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
import time
from unittest.mock import patch
from uuid import uuid4
import zlib

from configure_bridge import configure
from live_checkpoint_proof import LockedCore, Pump
from emerald_multiplayer.checkpoint_client import CheckpointClient
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.flash import FLASH_SIZE, inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, LiveSaveError
from emerald_multiplayer.mailbox import inspect_mailbox
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.save_mailbox import Opcode, SaveControl, SaveMailboxError, State, Status
from emerald_multiplayer.save_window import validate_window_manifest
from emerald_multiplayer.server import ServerConfig, WorldServer


class PacedPump(Pump):
    """Purpose-built 60 fps callback pacing, still not a Windows frontend."""
    async def _run(self):
        loop = asyncio.get_running_loop()
        deadline = loop.time()
        while True:
            await asyncio.gather(*(core.command(f"F {key:x} 1")
                for core, key in zip(self.cores, self.keys)))
            self.frames += 1
            pose = self.companions[1]._local_pose
            if pose is not None and pose.activity:
                self.visited_b.add((pose.x, pose.y))
            deadline = max(deadline + 1/60, loop.time())
            await asyncio.sleep(max(0, deadline-loop.time()))


async def run(args):
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    rom_bytes = args.rom.read_bytes()
    if hashlib.sha256(rom_bytes).hexdigest() != manifest["rom_sha256"]:
        raise ValueError("frozen ROM differs from manifest")
    validate_window_manifest(manifest, args.rom)
    if hashlib.sha256(args.elf.read_bytes()).hexdigest() != manifest["elf_sha256"]:
        raise ValueError("diagnostic ELF differs from manifest")
    sources = [args.save_a, args.save_b]
    originals = [p.read_bytes() for p in sources]
    source_hashes = [hashlib.sha256(p).hexdigest() for p in originals]
    source_metadata = [inspect_flash(p).metadata for p in originals]
    assert source_metadata[0].trainer_id != source_metadata[1].trainer_id
    root.mkdir(mode=0o700, parents=True)
    rom, manifest_path = root / "proof.gba", root / "manifest.json"
    rom.write_bytes(rom_bytes)
    manifest_path.write_bytes(manifest_bytes)
    bridge_source = args.bridge.read_text()
    (root / "bridge-source.lua").write_text(bridge_source)
    (root / "controller.py").write_bytes(Path(__file__).read_bytes())
    evidence = dict(scope="two actual cores, readonly sector-window transport and explicit under-advertised legacy fallback; no automatic runtime autosave acceptance",
        timing_label=args.timing_label, frame_rate=args.frame_rate,
        engine_commit=manifest["engine_commit"], rom_sha256=manifest["rom_sha256"],
        elf_sha256=manifest["elf_sha256"], harness_sha256=hashlib.sha256(args.harness.read_bytes()).hexdigest(),
        bridge_sha256=hashlib.sha256(bridge_source.encode()).hexdigest(),
        sources=[dict(path=str(p), sha256=h, trainer_id=m.trainer_id)
            for p, h, m in zip(sources, source_hashes, source_metadata)],
        checks=[], snapshots=[], commands=[], reads=[], passed=False)

    def persist():
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")

    def record(name, **fields):
        row = dict(verified=name, **fields)
        evidence["checks"].append(row)
        persist()
        print(json.dumps(row), flush=True)

    names = {"gRngValue": 16, "gRng2Value": 16, "gSaveCounter": 4,
             "sStartMenuCursorPos": 1, "sNumStartMenuActions": 1, "sCurrentStartMenuActions": 9}
    nm_process = await asyncio.create_subprocess_exec("arm-none-eabi-nm", "-S", str(args.elf),
        stdout=asyncio.subprocess.PIPE)
    nm = (await nm_process.communicate())[0].decode()
    symbols = {}
    for line in nm.splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[3] in names:
            address, size = int(fields[0], 16), int(fields[1], 16)
            assert size == names[fields[3]]
            assert 0x02000000 <= address < 0x02040000 or 0x03000000 <= address < 0x03008000
            symbols[fields[3]] = address
    if nm_process.returncode or set(symbols) != set(names):
        raise ValueError("matching ELF diagnostic symbols are unavailable")
    evidence["read_only_symbols"] = symbols
    store = OwnershipCheckpointStore(root / "world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
    identities = [store.create_player("Window " + label) for label in "AB"]
    for identity, payload in zip(identities, originals):
        store.enroll_player(identity.player_id, payload)
    (root / "profiles.json").write_text(json.dumps([dict(player_id=p.player_id,
        display_name=p.display_name, credential=p.credential.hex()) for p in identities], indent=2) + "\n")
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"],
        heartbeat_interval=.2, idle_timeout=12), store=store)
    await server.start(port=0)
    saves = [root / "client-a.sav", root / "client-b.sav"]
    companions, cores, leases, live = [], [], [], []
    revisions = [0, 0]
    pump = None
    generation = 0

    async def ready():
        async with asyncio.timeout(15):
            while not all(c.connected and c._bridge and c._bridge.save_capable and c._bridge.window_capable
                          for c in companions):
                await asyncio.sleep(.02)

    async def launch(i):
        lease = MirrorLease(saves[i])
        lease.__enter__()
        leases.append(lease)
        c = companions[i]
        script = root / f"bridge-{generation}-{i}.lua"
        script.write_text(configure(manifest, c.config.token.hex(), c.ipc_address[1], bridge_source))
        process = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(saves[i]), str(script),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        core = LockedCore(process, root / f"core-{generation}-{i}.log")
        cores.append(core)
        if not (await asyncio.wait_for(process.stdout.readline(), 20)).startswith(b"READY"):
            raise RuntimeError(f"actual game failed: {core.log}")

    async def boot():
        for keys, total in ((0, 1000), (8, 8), (0, 480), (8, 8), (0, 180), (1, 8), (0, 300)):
            for start in range(0, total, 24):
                await asyncio.gather(*(c.command(f"F {keys:x} {min(24,total-start)}") for c in cores))
                await asyncio.sleep(.003)
        await ready()

    async def clone(label, i=0):
        destination = root / f"{label}-{i}.flash"
        response = await cores[i].command(f"D {destination}")
        assert response.startswith("FLASH OK 131072 "), response
        return destination.read_bytes()

    async def held_fields(i=0):
        core = cores[i]
        sb2 = int.from_bytes(await core.read(manifest["debug_save_block2_ptr_address"], 4), "little")
        rng = b"".join([await core.read(symbols[name], 16) for name in ("gRngValue", "gRng2Value")])
        party = await core.read(manifest["debug_parties_address"], manifest["debug_party_size"])
        playtime = await core.read(sb2 + manifest["debug_play_time_offset"], manifest["debug_play_time_size"])
        return dict(rng_hex=rng.hex(), party_sha256=hashlib.sha256(party).hexdigest(), playtime_hex=playtime.hex())

    async def snapshot(label):
        result = dict(label=label, clients=[])
        for i, core in enumerate(cores):
            pose, _ = inspect_mailbox(await core.read(manifest["mailbox_address"], 128))
            await core.command(f"P {root / (label + '-' + str(i) + '.png')}")
            result["clients"].append(dict(pose=asdict(pose), core_pid=core.process.pid,
                lease_epoch=companions[i].session_epoch, incarnation=companions[i].save_incarnation,
                checkpoint_revision=revisions[i], **await held_fields(i)))
        evidence["snapshots"].append(result)
        persist()
        print(json.dumps(result), flush=True)
        return result

    async def download(i=0):
        downloaded = await CheckpointClient(companions[i]).download()
        parsed = inspect_flash(downloaded.payload, save_profile=OWNERSHIP_PROFILE)
        owned = inspect_ownership(parsed)
        assert (owned.world_id, owned.player_id) == (store.metadata.world_id, identities[i].player_id)
        assert parsed.metadata.trainer_id == source_metadata[i].trainer_id
        return downloaded, parsed, owned

    async def verify_party(i, parsed):
        party = await cores[i].read(manifest["debug_parties_address"], manifest["debug_party_size"])
        count = (await cores[i].read(manifest["debug_party_counts_address"], 1))[0]
        assert count == parsed.metadata.party_count
        offset = manifest["debug_saved_party_offset"]
        expected = parsed.save_block1[offset:offset+manifest["debug_party_size"]]
        for slot in range(count):
            assert party[slot*100:slot*100+80] == expected[slot*100:slot*100+80]

    async def measured(i, action, *, legacy=False):
        coord, c = live[i], companions[i]
        original_read, rpc, window_rpc = coord._read_flash, c.save_rpc, c.save_window_rpc
        calls = []
        async def ordinary(control, **kwargs):
            if control.opcode == Opcode.READ:
                calls.append(dict(opcode=int(control.opcode), offset=control.offset))
            return await rpc(control, **kwargs)
        async def window(control, **kwargs):
            calls.append(dict(opcode=int(control.opcode), offset=control.offset))
            return await window_rpc(control, **kwargs)
        async def read(session, operation, revision):
            diagnostic = await clone(action + "-held", i)
            before = await held_fields(i)
            start, frames = time.monotonic(), pump.frames
            payload = await original_read(session, operation, revision)
            seconds, elapsed_frames = time.monotonic()-start, pump.frames-frames
            assert payload == diagnostic
            assert await held_fields(i) == before
            parsed = inspect_flash(payload, save_profile=OWNERSHIP_PROFILE)
            await verify_party(i, parsed)
            expected = [(int(Opcode.READ), n) for n in range(0, FLASH_SIZE, 128)] if legacy else [
                (int(Opcode.READ_WINDOW), n) for n in range(0, FLASH_SIZE, 4096)]
            assert [(row["opcode"], row["offset"]) for row in calls] == expected
            row = dict(action=action, client=i, path="legacy128-under-advertised" if legacy else "window4096",
                seconds=round(seconds, 6), emulated_frames=elapsed_frames, count=len(calls),
                native_sha256=parsed.sha256, state_sha256=parsed.state_sha256, held_fields=before,
                offsets=[row["offset"] for row in calls])
            evidence["reads"].append(row)
            persist()
            print(json.dumps(dict(read_verified={**row, "offsets": [row["offsets"][0], row["offsets"][-1]]})), flush=True)
            return payload
        start, frames = time.monotonic(), pump.frames
        with patch.object(coord, "_read_flash", read), patch.object(c, "save_rpc", ordinary), patch.object(c, "save_window_rpc", window):
            if legacy:
                # Proof-only under-advertisement. No ROM/manifest/Flash or game
                # memory changes; the production coordinator chooses READ128.
                with patch.object(c._bridge, "window_capable", False):
                    result = await (coord.enroll() if action.startswith("enroll") else
                                    coord.checkpoint(expected_revision=revisions[i]))
            else:
                result = await (coord.enroll() if action.startswith("enroll") else
                                coord.checkpoint(expected_revision=revisions[i]) if action != "recover" else coord.recover())
        return result, dict(seconds=round(time.monotonic()-start, 6), emulated_frames=pump.frames-frames)

    async def checkpoint(i, action, *, legacy=False):
        result, total = await measured(i, action, legacy=legacy)
        revisions[i] = result.metadata["revision"]
        cp, parsed, owned = await download(i)
        assert cp.metadata == result.metadata and parsed.sha256 == result.flash_sha256
        await verify_party(i, parsed)
        record("verified-full-checkpoint", action=action, client=i, legacy_under_advertised=legacy,
            total=total, metadata=result.metadata, records=[asdict(r) for r in owned.records])
        return cp, parsed, owned

    async def stop_cores():
        nonlocal pump
        if pump is not None:
            await pump.close()
            pump = None
        await asyncio.gather(*(c.close() for c in cores))
        cores.clear()
        for lease in leases:
            lease.__exit__(None, None, None)
        leases.clear()

    try:
        for i, identity in enumerate(identities):
            saves[i].write_bytes(originals[i])
            companion = Companion(CompanionConfig(rom, manifest_path, identity.player_id, identity.display_name,
                secrets.token_bytes(32), server_port=server.address[1], ipc_port=0, server_credential=identity.credential))
            await companion.start()
            companions.append(companion)
            live.append(LiveCheckpointCoordinator(companion, root / f"private-{i}"))
        for i in range(2):
            await launch(i)
        await boot()
        first = await snapshot("01-real-window-ready")
        assert all(p["pose"]["activity"] == 1 for p in first["clients"])
        initial_pids = [c.process.pid for c in cores]
        initial_leases = [c.session_epoch for c in companions]
        record("two-real-Lua-window-capabilities", core_pids=initial_pids, leases=initial_leases)
        pump = (PacedPump if args.frame_rate else Pump)(cores, companions)
        pump.start()
        enrolled = [await checkpoint(i, f"enroll-{i}") for i in range(2)]
        original_records = [p[2].records for p in enrolled]
        b_head = await CheckpointClient(companions[1]).info()
        pump.wander()

        # Native sequence/offset refusal and exact duplicate against real C,
        # plus malformed/old-session rejection at the client codec boundary.
        coord, c = live[0], companions[0]
        async with coord._own():
            session, operation, revision = coord._session(), str(uuid4()), revisions[0]+1
            await coord._bind(session)
            await coord._prepare_ownership(session, revisions[0], enroll=False)
            await coord._command(session, operation, revision, Opcode.BEGIN_EXPORT)
            before = await clone("fault-held-before")
            c._live_sequence += 1
            good = SaveControl(session[2], session[1], operation, c._live_sequence, 0, FLASH_SIZE, revision, Opcode.READ_WINDOW)
            response, chunk = await c.save_window_rpc(good)
            assert response.status == Status.OK and chunk == before[:4096]
            assert await c.save_window_rpc(good) == (response, chunk)
            conflict, data = await c.save_window_rpc(replace(good, offset=4096))
            assert conflict.status == Status.ORDER and not data
            query_before = await coord._command(session, operation, revision, Opcode.QUERY)
            assert struct.unpack_from("<I", query_before.data, 4)[0] == 4096
            for bad in (replace(good, sequence=c._live_sequence+1, offset=128),
                        replace(good, sequence=c._live_sequence+1, data=b"bad")):
                try:
                    await c.save_window_rpc(bad)
                except SaveMailboxError:
                    pass
                else:
                    raise AssertionError("malformed window passed the command codec")
            corrupt = bytearray(good.pack()); corrupt[44] ^= 1
            try:
                SaveControl.unpack(bytes(corrupt))
            except SaveMailboxError:
                pass
            else:
                raise AssertionError("bad control CRC passed its codec")
            try:
                await c.save_window_rpc(replace(good, sequence=c._live_sequence+1, incarnation=session[2]+1))
            except ConnectionError:
                pass
            else:
                raise AssertionError("stale incarnation reached the game")
            c._live_sequence += 1
            out_of_order, data = await c.save_window_rpc(replace(good, sequence=c._live_sequence, offset=8192))
            assert out_of_order.status == Status.ORDER and not data
            query_after = await coord._command(session, operation, revision, Opcode.QUERY)
            assert query_before.data == query_after.data
            assert await clone("fault-held-after") == before
            await coord._cancel(session, operation, revision)
        assert await CheckpointClient(c).info() == enrolled[0][0].metadata
        record("native-exact-retry-conflicting-replay-and-offset-refusal-without-Flash-or-cursor-change",
            cursor=4096, codec_rejections=["unaligned-offset", "payload-length", "control-CRC", "stale-incarnation"])

        # Corrupt only the already verified return envelope at the proof seam.
        # The actual native/Lua read happens; no game memory is injected.
        rpc = c.save_window_rpc
        async def bad_crc(control, **kwargs):
            response, data = await rpc(control, **kwargs)
            return replace(response, data=struct.pack("<I", zlib.crc32(data)^1)), data
        prior = await CheckpointClient(c).info()
        with patch.object(c, "save_window_rpc", bad_crc):
            try:
                await coord.checkpoint(expected_revision=revisions[0])
            except LiveSaveError as error:
                assert error.code == "read_position" and not error.safe_to_retry
            else:
                raise AssertionError("mismatched window CRC was accepted")
        assert await CheckpointClient(c).info() == prior and not coord.pending_path.exists()
        await pump.advance(120)
        record("coordinator-window-CRC-mismatch-discards-export-without-canonical-advance", revision=revisions[0])

        window_cp = await checkpoint(0, "checkpoint-window")
        legacy_cp = await checkpoint(0, "checkpoint-legacy", legacy=True)
        assert window_cp[2].records == legacy_cp[2].records == original_records[0]
        assert await CheckpointClient(companions[1]).info() == b_head
        record("same-ROM-explicit-under-advertisement-uses-1024-legacy-reads-and-same-identities")
        await pump.press(0, 16, 18, 90)
        moved = await snapshot("02-unsaved-movement")
        assert moved["clients"][0]["pose"]["x"] != legacy_cp[1].metadata.x
        receipt, duration = await measured(0, "recover")
        assert receipt.normalized_state_sha256 == legacy_cp[1].state_sha256
        await pump.advance(120)
        restored = await snapshot("03-recovered")
        assert tuple(restored["clients"][0]["pose"][k] for k in ("map_group", "map_number", "x", "y")) == (
            legacy_cp[1].metadata.map_group, legacy_cp[1].metadata.map_number, legacy_cp[1].metadata.x, legacy_cp[1].metadata.y)
        assert [p.process.pid for p in cores] == initial_pids and [c.session_epoch for c in companions] == initial_leases
        assert await CheckpointClient(companions[1]).info() == b_head
        assert len(pump.visited_b) > 1
        record("COMMITTED-window-readback-recovers-live-canonical-with-independent-peer", total=duration,
            receipt=asdict(receipt), other_positions=sorted(pump.visited_b))

        # Select native SAVE using source-audited read-only menu identifiers;
        # every cursor change/confirmation remains an ordinary joypad input.
        async def keys(value, frames=8, release=60):
            evidence["commands"].append(dict(keys=value, frames=frames, release=release, client=0))
            persist()
            await pump.press(0, value, frames, release)
        counter_before = int.from_bytes(await cores[0].read(symbols["gSaveCounter"], 4), "little")
        await keys(8, release=120)
        await snapshot("04-native-save-menu")
        count = (await cores[0].read(symbols["sNumStartMenuActions"], 1))[0]
        cursor = (await cores[0].read(symbols["sStartMenuCursorPos"], 1))[0]
        actions = await cores[0].read(symbols["sCurrentStartMenuActions"], 9)
        assert 0 <= cursor < count <= 9 and 5 in actions[:count]
        target = actions[:count].index(5)  # source enum MENU_ACTION_SAVE
        for _ in range((target-cursor) % count):
            await keys(128, release=30)
        await keys(1, release=180)
        await snapshot("05-native-save-question")
        await keys(1, release=180)
        await snapshot("06-native-overwrite-question")
        await keys(1, release=180)
        await snapshot("07-native-overwrite-choice")
        await keys(1, release=1200)
        await snapshot("08-native-save-completed")
        counter_after = int.from_bytes(await cores[0].read(symbols["gSaveCounter"], 4), "little")
        assert counter_after == counter_before+1
        await keys(2, release=180)
        after_save = await snapshot("09-native-field-after-save")
        assert after_save["clients"][0]["pose"]["activity"] == 1
        native = inspect_flash(await clone("native-save"), save_profile=OWNERSHIP_PROFILE)
        assert native.metadata.counter == counter_after and inspect_ownership(native).records == original_records[0]
        record("ordinary-native-Save-persists-original-instance-identities", counter_before=counter_before,
            counter_after=counter_after, native_sha256=native.sha256)
        await pump.stop_wander()
        await pump.advance(180)
        before_close = await snapshot("10-before-close")
        await stop_cores()
        closed = [p.read_bytes() for p in saves]
        parsed_closed = [inspect_flash(p, save_profile=OWNERSHIP_PROFILE) for p in closed]
        for i, p in enumerate(parsed_closed):
            assert p.metadata.trainer_id == source_metadata[i].trainer_id
            assert inspect_ownership(p).records == original_records[i]
        assert parsed_closed[0].flash == native.flash
        record("closed-native-writeback-matches-readonly-Flash-and-retains-independent-trainers",
            container_sha256=[hashlib.sha256(p).hexdigest() for p in closed])
        generation += 1
        for i in range(2):
            await launch(i)
        await boot()
        fresh = await snapshot("11-fresh-Continue")
        for i, p in enumerate(parsed_closed):
            assert fresh["clients"][i]["core_pid"] != before_close["clients"][i]["core_pid"]
            assert fresh["clients"][i]["pose"]["activity"] == 1
            assert tuple(fresh["clients"][i]["pose"][k] for k in ("map_group", "map_number", "x", "y")) == (
                p.metadata.map_group, p.metadata.map_number, p.metadata.x, p.metadata.y)
            await verify_party(i, p)
        record("two-fresh-Continue-processes-confirm-native-party-identities-and-coordinates")
        await stop_cores()
        assert [p.read_bytes() for p in saves] == closed
        assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources] == source_hashes
        store.integrity_check()
        record("source-saves-immutable-and-private-store-integrity-valid")
        evidence["passed"] = True
        persist()
    except BaseException as error:
        evidence["failure"] = dict(type=type(error).__name__, message=str(error))
        persist()
        raise
    finally:
        await stop_cores()
        await asyncio.gather(*(c.close() for c in companions), return_exceptions=True)
        await server.close()
        store.close()
        evidence["cores_closed"] = True
        persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "elf", "manifest", "harness", "save-a", "save-b", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2] / "bridge/mgba.lua")
    parser.add_argument("--timing-label", choices=("development", "quiet"), default="development")
    parser.add_argument("--frame-rate", type=int, choices=(0, 60), default=0,
                        help="0 is unthrottled;60 purpose-paces each official core callback")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
