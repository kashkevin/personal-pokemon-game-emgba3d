"""Actual first-action development Local Reset, ordinary capture and persistence.

Joypad input only. Official libmGBA reads native state and framebuffer; production
Lua owns mailbox writes. Requires a freshly copied development-enabled build.
Interactive commands: keys, snapshot, remember, verify, checkpoint, finish.
"""
from __future__ import annotations

import argparse
from contextlib import suppress
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import secrets
import struct
import sys
import traceback
from uuid import uuid4

from control_proof import objects
from configure_bridge import configure
from live_checkpoint_proof import LockedCore
from save_window_proof import PacedPump as Pump
from emerald_multiplayer.checkpoint_client import CheckpointClient
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, LiveSaveError
from emerald_multiplayer.mailbox import inspect_mailbox
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership, _decode_box, _SUBSTRUCT_OFFSETS
from emerald_multiplayer.ownership_client import parse_status
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.save_mailbox import Opcode
from emerald_multiplayer.server import ServerConfig, WorldServer


class ObserverPump(Pump):
    def __init__(self, cores, companions):
        super().__init__(cores,companions)
        self.observer_positions={i:set() for i in range(1,len(cores))}
        self.extra_wander=None

    async def _run(self):
        loop=asyncio.get_running_loop();deadline=loop.time()
        while True:
            await asyncio.gather(*(core.command(f"F {key:x} 1") for core,key in zip(self.cores,self.keys)))
            self.frames+=1
            for i in self.observer_positions:
                pose=self.companions[i]._local_pose
                if pose is not None:
                    self.observer_positions[i].add((pose.map_group,pose.map_number,pose.x,pose.y,pose.activity))
                    if i==1 and pose.activity:self.visited_b.add((pose.x,pose.y))
            deadline=max(deadline+1/60,loop.time())
            await asyncio.sleep(max(0,deadline-loop.time()))

    async def _wander_c(self):
        while True:
            await self.press(2,32,18,24)
            await self.press(2,16,18,24)

    def wander(self):
        super().wander()
        if len(self.cores)==4:self.extra_wander=asyncio.create_task(self._wander_c())

    async def stop_wander(self):
        if self.extra_wander is not None:
            self.extra_wander.cancel()
            with suppress(asyncio.CancelledError):await self.extra_wander
            self.extra_wander=None;self.keys[2]=0
        await super().stop_wander()

    async def close(self):
        if self.extra_wander is not None:
            self.extra_wander.cancel()
            with suppress(asyncio.CancelledError):await self.extra_wander
            self.extra_wander=None
        await super().close()


async def run(args):
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    root.mkdir(mode=0o700, parents=True)
    manifest = json.loads(args.manifest.read_text())
    if manifest.get("local_reset_development") is not True:
        raise ValueError("explicit development probe build required")
    if __import__('hashlib').sha256(args.rom.read_bytes()).hexdigest() != manifest["rom_sha256"]:
        raise ValueError("frozen ROM hash mismatch")
    if __import__('hashlib').sha256(args.elf.read_bytes()).hexdigest() != manifest["elf_sha256"]:
        raise ValueError("frozen diagnostic ELF hash mismatch")
    nm = await asyncio.create_subprocess_exec("arm-none-eabi-nm", "-S", str(args.elf), stdout=asyncio.subprocess.PIPE)
    lines = (await nm.communicate())[0].decode().splitlines()
    expected = {"sLocalReset"+name: 1 for name in ("Active", "Window", "Requested", "Confirming", "Accepted", "Closed")}
    expected.update({"gBattleTypeFlags":4, "gSaveCounter": 4, "sStartMenuCursorPos": 1, "sNumStartMenuActions": 1, "sCurrentStartMenuActions": 9})
    diagnostics = {}
    for line in lines:
        f = line.split()
        if len(f) == 4 and f[3] in expected:
            assert f[3] not in diagnostics and int(f[1], 16) == expected[f[3]]
            address = int(f[0], 16)
            assert 0x02000000 <= address < 0x02040000 or 0x03000000 <= address < 0x03008000
            diagnostics[f[3]] = dict(address=address, size=int(f[1], 16))
    assert nm.returncode == 0 and set(diagnostics) == set(expected)
    remembered = {}
    required = set()

    if manifest.get("ownership_abi_version") != 1:
        raise ValueError("ownership proof requires a verified ownership ROM")
    # Pin this run's bytes even if an independent engine build replaces its ROM.
    rom = root / "proof.gba"
    rom.write_bytes(args.rom.read_bytes())
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if bool(args.save_c) != bool(args.save_d): raise ValueError("provide both distinct C/D sources")
    sources = [args.save_a, args.save_b]+([args.save_c,args.save_d] if args.save_c else [])
    player_count=len(sources)
    (root/"controller.py").write_bytes(Path(__file__).read_bytes())
    bridge_source = args.bridge.read_bytes()
    (root/"bridge-source.lua").write_bytes(bridge_source)
    original = [p.read_bytes() for p in sources]
    source_hashes = [hashlib.sha256(data).hexdigest() for data in original]
    store = OwnershipCheckpointStore(root / "world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
    identities = [store.create_player("Reset " + label) for label in "ABCD"[:player_count]]
    enrollments = [store.enroll_player(player.player_id, data) for player, data in zip(identities, original)]
    (root / "profiles.json").write_text(json.dumps([dict(player_id=p.player_id, display_name=p.display_name,
        credential=p.credential.hex()) for p in identities]))
    evidence = dict(build_id=manifest["rom_sha256"], engine_commit=manifest["engine_commit"],
        scope="first-action-only gated development personal encounter; no production statics, shiny profile, four-player matrix or Windows input acceptance",
        development=True, elf_sha256=manifest["elf_sha256"], read_only_diagnostics=diagnostics,
        save_profile=OWNERSHIP_PROFILE, source_sha256=source_hashes,
        enrollment=[asdict(item) for item in enrollments], checks=[], snapshots=[], commands=[],
        controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        bridge_sha256=hashlib.sha256(bridge_source).hexdigest(),
        harness_sha256=hashlib.sha256(args.harness.read_bytes()).hexdigest(),
        passed=False, cores_closed=False, original_sources_unchanged=False)
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"], heartbeat_interval=.2, idle_timeout=8), store=store)
    await server.start(port=0)
    cores, all_cores, companions, leases, coordinators = [], [], [], [], []
    pump = None
    saves = [root/f"client-{label.lower()}.sav" for label in "ABCD"[:player_count]]
    revisions = [0]*player_count
    canonical_owners = [None]*player_count
    canonical_snapshots = [None]*player_count
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
        script.write_text(configure(manifest, companion.config.token.hex(), companion.ipc_address[1], bridge_source.decode()))
        process = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(saves[i]), str(script),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        core = LockedCore(process, root / f"core-{i}-{len(evidence['snapshots'])}.log")
        cores.append(core)
        all_cores.append(core)
        if not (await asyncio.wait_for(process.stdout.readline(), 20)).startswith(b"READY"):
            raise RuntimeError(f"core failed: {core.log}")

    async def boot():
        for keys, total in ((0, 1000), (8, 8), (0, 480), (8, 8), (0, 180), (1, 8), (0, 300)):
            for step in range(0, total, 24):
                await asyncio.gather(*(c.command(f"F {keys:x} {min(24, total-step)}") for c in cores))
                await asyncio.sleep(.003)
        await ready()

    async def joypad(value, frames=8, release=30):
        evidence["commands"].append(dict(action="joypad-step",keys=value,frames=frames,release=release))
        persist()
        await pump.press(0,value,frames,release)

    async def reach_first_menu():
        for _ in range(6):
            state=await reset_state()
            if state["sLocalResetWindow"]:
                return
            assert not state["sLocalResetClosed"], "ordinary intro press reached an already closed action menu"
            await joypad(1,8,300)
            await snapshot(f"native-intro-{len(evidence['commands'])}")
        raise AssertionError("eligible first action menu did not open")

    async def native_save():
        remembered["before-save"] = await reset_state()
        await joypad(8,8,120)
        await snapshot("native-save-menu")
        core=cores[0]
        count=(await core.read(diagnostics["sNumStartMenuActions"]["address"],1))[0]
        cursor=(await core.read(diagnostics["sStartMenuCursorPos"]["address"],1))[0]
        actions=await core.read(diagnostics["sCurrentStartMenuActions"]["address"],9)
        assert 0<=cursor<count<=9 and 5 in actions[:count]
        target=actions[:count].index(5)
        for _ in range((target-cursor)%count): await joypad(128,8,30)
        for n in range(3):
            await joypad(1,8,180)
            await snapshot(f"native-save-prompt-{n}")
        await joypad(1,8,1200)
        await snapshot("native-save-complete")
        await verify_case("native-save")
        await joypad(2,8,180)

    async def complete_capture():
        for n in range(24):
            state=await reset_state()
            if state["captured"] and state["party_count"]==3 and not state["sLocalResetActive"]:
                pose,_=inspect_mailbox(await cores[0].read(manifest["mailbox_address"],128))
                if pose.activity==1:return
                await pump.advance(12)
                continue
            await joypad(2,8,180)
            await snapshot(f"capture-message-{n}")
        raise AssertionError("capture did not complete through ordinary reward/nickname messages")

    async def approach_npc():
        for _ in range(80):
            state = await reset_state()
            if state["sLocalResetActive"]:
                await pump.advance(300)
                await reach_first_menu()
                return
            pose,_=inspect_mailbox(await cores[0].read(manifest["mailbox_address"],128))
            npc=next(o for o in objects(await cores[0].read(manifest["debug_object_events_address"],manifest["debug_object_events_size"])) if o["local_id"]==3)
            dx,dy=npc["x"]-pose.x,npc["y"]-pose.y
            if abs(dx)+abs(dy)==1:
                await joypad(16 if dx==1 else 32 if dx==-1 else 128 if dy==1 else 64,6,24)
                await joypad(1,8,600)
            else:
                await joypad(16 if dx>0 else 32 if dx<0 else 128 if dy>0 else 64,18,24)
        raise AssertionError("ordinary NPC approach did not enter the development encounter")

    async def reset_state():
        core = cores[0]
        values = {}
        for name, spec in diagnostics.items():
            values[name] = int.from_bytes(await core.read(spec["address"], spec["size"]), "little")
        sb1 = int.from_bytes(await core.read(manifest["debug_save_block1_ptr_address"], 4), "little")
        variables = await core.read(sb1+manifest["local_reset_vars_offset"]+(0x40F7-0x4000)*2, 8)
        lo, hi, magic, captured = struct.unpack("<4H", variables)
        values.update(count=lo|(hi<<16), magic=magic, captured=captured)
        party = await core.read(manifest["debug_parties_address"], 600)
        enemy = await core.read(manifest["debug_parties_address"]+600, 100)
        count = (await core.read(manifest["debug_party_counts_address"], 1))[0]
        assert count <= 6
        records = [_decode_box(party[i*100:i*100+80], f"party:{i}") for i in range(count)]
        sb2=int.from_bytes(await core.read(manifest["debug_save_block2_ptr_address"],4),"little")
        encryption_key=int.from_bytes(await core.read(sb2+manifest["local_reset_encryption_key_offset"],4),"little")
        bag=bytearray(await core.read(sb1+manifest["local_reset_bag_offset"],744))
        for offset in range(2,len(bag),4):
            struct.pack_into("<H",bag,offset,struct.unpack_from("<H",bag,offset)[0]^(encryption_key&0xFFFF))
        money_coins=bytearray(await core.read(sb1+manifest["local_reset_money_offset"],6))
        struct.pack_into("<I",money_coins,0,struct.unpack_from("<I",money_coins)[0]^encryption_key)
        struct.pack_into("<H",money_coins,4,struct.unpack_from("<H",money_coins,4)[0]^(encryption_key&0xFFFF))
        enemy_pid,enemy_ot=struct.unpack_from("<II",enemy)
        ivs=()
        if enemy_pid or enemy_ot:
            words=[value^enemy_pid^enemy_ot for value in struct.unpack_from("<12I",enemy,32)]
            physical=struct.pack("<12I",*words)
            index=_SUBSTRUCT_OFFSETS[3][enemy_pid%24]
            iv_word=struct.unpack_from("<I",physical,index*12+4)[0]
            ivs=tuple((iv_word>>(5*n))&31 for n in range(6))
        values.update(enemy_ivs=ivs,party_count=count, party_box_hashes=[hashlib.sha256(party[i*100:i*100+80]).hexdigest() for i in range(count)],
            party_records=records, player_party_hex=party.hex(), enemy_hex=enemy.hex(), enemy_pid=int.from_bytes(enemy[:4], "little"),
            bag_sha256=hashlib.sha256(bag).hexdigest(),
            money_coins_hex=money_coins.hex())
        return values

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
        result = dict(label=label, clients=clients, reset=await reset_state())
        evidence["snapshots"].append(result)
        persist()
        # Full diagnostic bytes stay in the private transcript, keeping the
        # interactive terminal readable while many joypad steps are replayed.
        display = dict(result, reset={k:v for k,v in result["reset"].items() if k not in ("player_party_hex", "enemy_hex", "party_box_hashes", "party_records")}, clients=[{key: value for key, value in item.items()
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

    async def verify_case(case):
        state = await reset_state()
        first = remembered.get("first")
        second = remembered.get("second")
        if case in ("prompt", "cancel", "accepted", "second-roll"):
            assert first is not None
            assert state["player_party_hex"] == first["player_party_hex"]
            assert state["bag_sha256"] == first["bag_sha256"] and state["money_coins_hex"] == first["money_coins_hex"]
        if case == "prompt":
            assert state["sLocalResetConfirming"] == 1 and state["count"] == 1 and state["enemy_hex"] == first["enemy_hex"]
        elif case == "cancel":
            assert state["sLocalResetActive"] == state["sLocalResetWindow"] == 1
            assert state["sLocalResetConfirming"] == state["sLocalResetAccepted"] == 0
            assert state["count"] == 1 and state["enemy_hex"] == first["enemy_hex"]
        elif case == "accepted":
            assert state["sLocalResetActive"] == state["sLocalResetAccepted"] == 0
            assert state["count"] == 1 and state["captured"] == 0 and _decode_box(bytes.fromhex(state["enemy_hex"])[:80],"cleared-enemy")[3] == 0
            assert [c.process.pid for c in cores] == initial_pids
            assert [c.session_epoch for c in companions] == initial_epochs and [c.save_incarnation for c in companions] == initial_incarnations
        elif case == "second-roll":
            assert state["count"] == 2 and state["sLocalResetWindow"] == 1
            assert state["enemy_pid"] != first["enemy_pid"] and state["enemy_hex"] != first["enemy_hex"]
            assert state["enemy_ivs"]!=first["enemy_ivs"]
        elif case == "after-action-refused":
            assert second is not None and state["count"] == 2 and state["sLocalResetActive"] == state["sLocalResetClosed"] == 1
            assert state["sLocalResetWindow"] == state["sLocalResetConfirming"] == state["sLocalResetAccepted"] == 0
            assert state["enemy_pid"] == second["enemy_pid"]
        elif case == "capture-locked":
            assert second is not None and state["captured"] == 1 and state["count"] == 2 and state["party_count"] == 3
            assert state["sLocalResetActive"] == state["sLocalResetWindow"] == 0
            assert state["party_records"][-1][1] == second["enemy_pid"] and state["party_records"][-1][3] == 265
        elif case == "native-save":
            before = remembered["before-save"]
            assert state["gSaveCounter"] == before["gSaveCounter"]+1
            assert state["count"] == 2 and state["captured"] == 1
        else:
            raise ValueError("unknown verification case")
        required.add(case)
        for i,head in enumerate(observer_heads,1):
            assert await CheckpointClient(companions[i]).info()==head
            sb2=int.from_bytes(await cores[i].read(manifest["debug_save_block2_ptr_address"],4),"little")
            assert int.from_bytes(await cores[i].read(sb2+10,4),"little")==inspect_flash(original[i]).metadata.trainer_id
            assert (await cores[i].read(manifest["debug_party_counts_address"],1))[0]==0
        record("actual-local-reset-"+case, count=state["count"], captured=state["captured"],
            enemy_pid=state["enemy_pid"], enemy_ivs=state["enemy_ivs"], party_count=state["party_count"], core_pids=[c.process.pid for c in cores],
            leases=[c.session_epoch for c in companions], incarnations=[c.save_incarnation for c in companions])

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
        for i in range(player_count):
            await launch(i)
        await boot()
        await snapshot("01-legacy-continue")
        initial_pids = [c.process.pid for c in cores]
        initial_epochs = [c.session_epoch for c in companions]
        initial_incarnations = [c.save_incarnation for c in companions]
        pump = ObserverPump(cores, companions)
        pump.start()
        try:
            await coordinators[0].checkpoint(expected_revision=0)
        except LiveSaveError as error:
            assert error.code == "enrollment_required", error.code
        else:
            raise AssertionError("ordinary checkpoint silently enrolled legacy state")
        record("legacy-enrollment-requires-explicit-action")
        await checkpoint(0, enroll=True)
        for i in range(1,player_count):await checkpoint(i,enroll=True)
        observer_heads=[await CheckpointClient(companions[i]).info() for i in range(1,player_count)]
        assert len({inspect_flash(data).metadata.trainer_id for data in original})==player_count
        pump.wander()
        if player_count==4:
            evidence["commands"].append(dict(action="observer",client=3,keys=64,frames=18,release=180));persist()
            await pump.press(3,64,18,180)
            d,_=inspect_mailbox(await cores[3].read(manifest["mailbox_address"],128))
            assert (d.map_group,d.map_number)!=(0,9), "ordinary D house entry failed"
            evidence["commands"].append(dict(action="observer",client=3,keys=8,frames=8,release=90));persist()
            await pump.press(3,8,8,90)
        observer_initial=await snapshot("02-enrolled")
        if True:
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
                    client=command.get("client",0)
                    if not 0<=client<player_count:raise ValueError("unknown joypad client")
                    await pump.press(client, command.get("keys", 0), command.get("frames", 18), command.get("release", 60))
                elif action == "approach":
                    await approach_npc()
                elif action == "native_save":
                    await native_save()
                elif action == "complete_capture":
                    await complete_capture()
                elif action == "remember":
                    remembered[command["name"]] = await reset_state()
                elif action == "verify":
                    await verify_case(command["case"])
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
                    if canonical_snapshots[0].metadata.party_count == 3:
                        selected = canonical_snapshots[0]
                        lo, hi, magic, captured = struct.unpack_from("<4H",selected.save_block1,manifest["local_reset_vars_offset"]+(0x40F7-0x4000)*2)
                        assert lo|(hi<<16) == 2 and magic == 0x4C52 and captured == 1
                        assert len(owner.records)==3
                        last = next(r for r in owner.records if r.location == "party:2")
                        assert last.serial not in (1,2) and last.personality == remembered["second"]["enemy_pid"]
                        record("capture-counter-canonical-checkpoint", revision=revisions[0], serial=last.serial, personality=last.personality)
                        required.add("capture-checkpoint")
                elif action == "recover":
                    await recover()
                elif action != "snapshot":
                    raise ValueError("unknown interactive action")
                await snapshot(command.get("label", f"step-{len(evidence['commands']):03d}"))
        assert required >= {"prompt", "cancel", "accepted", "second-roll", "after-action-refused", "capture-locked", "native-save", "capture-checkpoint"}
        before = canonical_owners[0]
        assert len(before.records) == 3
        await recover()
        state = await reset_state()
        assert state["count"] == 2 and state["captured"] == 1
        after = await checkpoint()
        assert after.records == before.records
        record("captured-identity-and-counter-survive-live-canonical-recovery")
        assert len(pump.visited_b) > 1
        for i in range(1,player_count):
            assert await CheckpointClient(companions[i]).info()==observer_heads[i-1]
            pose,_=inspect_mailbox(await cores[i].read(manifest["mailbox_address"],128))
            assert pose.frame>observer_initial["clients"][i]["pose"]["frame"]
            if i in (1,2):assert len(pump.observer_positions[i])>1
        record("other-players-advance-with-independent-positions-scenes-and-canonical-heads", player_count=player_count,
            observer_positions={str(i):sorted(v) for i,v in pump.observer_positions.items()},
            canonical_heads=observer_heads)
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
        for i in range(player_count):
            await launch(i)
        await boot()
        await snapshot("fresh-Continue")
        pump = ObserverPump(cores, companions)
        pump.start()
        assert not (await ownership_status(0)).active_grant
        fresh = await checkpoint()
        assert fresh.records == after.records and fresh.start >= after.end_exclusive
        state = await reset_state()
        assert state["count"] == 2 and state["magic"] == 0x4C52 and state["captured"] == 1 and state["party_count"] == 3
        record("fresh-Continue-preserves-captured-identities-and-counter", count=state["count"], captured=state["captured"], party_count=state["party_count"])

        store.integrity_check()
        assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources] == source_hashes
        record("source-saves-unchanged-and-database-integrity-valid")
        evidence["passed"] = True
        persist()
    except BaseException:
        evidence["error"] = traceback.format_exc()
        raise
    finally:
        if pump is not None:
            await pump.close()
        await asyncio.gather(*(c.close() for c in all_cores), return_exceptions=True)
        for lease in leases:
            lease.__exit__(None, None, None)
        await asyncio.gather(*(c.close() for c in companions), return_exceptions=True)
        await server.close()
        store.close()
        evidence["cores_closed"] = all(c.process.returncode is not None for c in all_cores)
        evidence["total_cores"] = len(all_cores)
        evidence["original_sources_unchanged"] = [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources] == source_hashes
        if not evidence["cores_closed"] or not evidence["original_sources_unchanged"]:
            evidence["passed"] = False
        persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "elf", "manifest", "harness", "save-a", "save-b", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2] / "bridge/mgba.lua")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--save-c",type=Path)
    parser.add_argument("--save-d",type=Path)
    parser.add_argument("--diagnostics", type=Path, help="Optional named read-only core ranges from the matching ELF")
    parser.add_argument("--replay", type=Path, help="Replay recorded joypad commands before reading stdin")
    parser.add_argument("--replay-limit", type=int, help="Replay only this many commands")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
