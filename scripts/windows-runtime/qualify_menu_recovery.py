"""Private Windows 1v1 host-service loss and real Recover battle qualification.

Two real LauncherWindows/SessionWorkers enter through ordinary Players menus.
The actual host service and store close during the match; a new real HostWorld,
store and WorldServer reopen the same private world, TLS identity and port on
the proof supervisor loop. Neither original LauncherSession nor its native
game/runtime/bridge is replaced, and no production method or receipt is mocked.
Each actual enabled Tk Recover battle widget is invoked programmatically, with
the second player withheld until both original cores demonstrate a sustained
native hold. Ordinary keys and read-only ELF-pinned diagnostics are reused from
the passing 1v1 qualifier. No native RAM, RNG or outcome is written or injected.

Verify resumed results, original personal parties, fresh saver handoff, manual
checkpoints and fresh Continue. Close ONLY reported play PIDs normally, friend
then host. Forced cleanup is failure. Use a 1200-second scenario envelope plus
an independent 1320-second watchdog and 120 seconds of cleanup grace; existing
production RPC deadlines are unchanged. Importing this file launches no core.

Scope is source-launched Windows on one PC, two/one-member parties, and graceful
host-service outage/restart with original game processes retained. It is NOT a
host-PC/process crash, GUI host-restart feature, physical keyboard/click, timed
autosave, installed-package, separate-PC, Internet, 2v2 or full-six acceptance.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import socket
import struct
import time
import traceback

from emerald_multiplayer import launcher_session as session_module
from emerald_multiplayer.battle_controller import read_string_lengths
from emerald_multiplayer.battle_journal import read_battle_intent
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.launcher_gui import LaunchRequest, LauncherWindow, SessionWorker
from emerald_multiplayer.launcher_session import GameInstallation
from emerald_multiplayer.launcher_setup import create_world, export_friend_invitation, host_enrollment
from emerald_multiplayer.player_runtime import RuntimeBundle
from emerald_multiplayer.server import ServerConfig, WorldServer
from qualify_admission_cleanup import on_worker, require
from qualify_launcher_session import checked_log, inspect_closed_head, output_event
from qualify_live_runtime import field_ready, lease_is_owned, party, proof_bundle, sha
from qualify_menu_battle import (SYMBOLS as BATTLE_SYMBOLS, PARTY_TASKS, BattleProbe,
    append_input_probe as append_battle_probe, drive_battle_input)


# Exact sizes from the existing native candidate, also used by its four-core
# recovery proof. Unknown layouts fail before starting any native process.
GAMEPLAY_SYMBOLS = dict(gBattleMainFunc=4, gBattleControllerExecFlags=4,
    gBattleMons=560, gBattlerPartyIndexes=8, gBattleCommunication=8)
SYMBOLS = dict(BATTLE_SYMBOLS, gRngValue=16, gRng2Value=16,
    gSaveCounter=4, **GAMEPLAY_SYMBOLS)
HOLD_HEADER = struct.Struct("<IIIIB")
HOLD_SIZE = HOLD_HEADER.size + 32 + 5 + 600 + sum(GAMEPLAY_SYMBOLS.values())


def decode_hold(raw):
    require(len(raw) == HOLD_SIZE, "retained diagnostic length changed")
    frame, state, hold, counter, count = HOLD_HEADER.unpack_from(raw)
    require(state <= 10 and count <= 6, "retained diagnostic enum/count changed")
    offset = HOLD_HEADER.size
    value = dict(frame=frame, state=state, hold=hold, counter=counter, count=count,
        rng=raw[offset:offset+16].hex(), rng2=raw[offset+16:offset+32].hex(),
        playtime=raw[offset+32:offset+37].hex(),
        party_sha256=hashlib.sha256(raw[offset+37:offset+637]).hexdigest())
    offset += 637
    value["gameplay"] = {}
    for name, size in GAMEPLAY_SYMBOLS.items():
        value["gameplay"][name] = hashlib.sha256(raw[offset:offset+size]).hexdigest()
        offset += size
    return value


def verify_stable_hold(first, second, *, minimum_frames=120):
    """Emulator frames advance; suspended gameplay and RNG must not advance."""
    require(first["state"] == second["state"] == 9 and first["hold"] == second["hold"] == 4,
            "both snapshots must show the real native suspended marker")
    require(second["frame"] - first["frame"] >= minimum_frames,
            "the native hold was not observed over sustained emulator frames")
    require({k: v for k, v in first.items() if k != "frame"} ==
            {k: v for k, v in second.items() if k != "frame"},
            "party, RNG, timer, save counter or gameplay progressed while held")


def verify_source_index(root, index):
    require(isinstance(index, dict) and index, "explicit frozen source index is missing")
    required = {path.relative_to(root).as_posix() for pattern in
                ("src/**/*.py", "bridge/*.lua", "scripts/windows-runtime/*.py")
                for path in root.glob(pattern)}
    require(required <= set(index), "source index omits a current production or proof helper file")
    hashes = {}
    for name, digest in index.items():
        require(type(name) is str, "invalid frozen source index path")
        path = Path(name)
        require(not path.is_absolute() and ".." not in path.parts
                and path.as_posix() == name and type(digest) is str and len(digest) == 64
                and all(c in "0123456789abcdef" for c in digest), "invalid frozen source index entry")
        target = (root / path).resolve()
        require(target.is_relative_to(root.resolve()) and target.is_file() and sha(target) == digest,
                "frozen source differs from its explicit pin: " + name)
        hashes[str(target)] = digest
    return hashes


def append_input_probe(bundle, bridge, output, symbols, manifest):
    bundle = append_battle_probe(bundle, bridge, output, symbols, manifest)
    path = bundle.directory / "mgba.lua"
    gameplay = "".join(f"..emu:readRange({symbols[name][0]},{size})"
                       for name, size in GAMEPLAY_SYMBOLS.items())
    appendix = f'''
do
local path={json.dumps(output.as_posix(), ensure_ascii=True)}.."/input-"..cfg.port..".hold"
callbacks:add("frame",function()
  if emu:currentFrame()<2400 or emu:currentFrame()%6~=0 then return end
  local ptr=emu:read32({manifest['debug_save_block2_ptr_address']})+{manifest['debug_play_time_offset']}
  if not (ptr>=0x02000000 and ptr+5<=0x02040000 or ptr>=0x03000000 and ptr+5<=0x03008000) then return end
  local raw=string.pack("<I4I4I4I4I1",emu:currentFrame(),emu:read32({manifest['battle_mailbox_address']+12}),
    emu:read32({symbols['gMultiplayerBattleHoldFlags'][0]}),emu:read32({symbols['gSaveCounter'][0]}),
    emu:read8({manifest['debug_party_counts_address']}))
    ..emu:readRange({symbols['gRngValue'][0]},16)..emu:readRange({symbols['gRng2Value'][0]},16)
    ..emu:readRange(ptr,5)..emu:readRange({manifest['debug_parties_address']},600){gameplay}
  local f=io.open(path,"wb");if f then f:write(raw);f:close() end
end)
end
'''
    path.write_bytes(path.read_bytes() + appendix.encode("utf-8"))
    metadata = bundle.directory / "runtime.json"
    value = json.loads(metadata.read_text())
    value["files"]["mgba.lua"] = sha(path)
    metadata.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    return RuntimeBundle(bundle.directory, sha(metadata))


class RecoveryProbe(BattleProbe):
    async def retained(self, *, after=-1, suspended=False, timeout=20):
        async with asyncio.timeout(timeout):
            while True:
                try:
                    value = decode_hold(self.base.with_suffix(".hold").read_bytes())
                    if (value["frame"] > after and
                            (not suspended or value["state"] == 9 and value["hold"] == 4)):
                        return value
                except (OSError, AssertionError):
                    pass  # A concurrent diagnostic writer may expose partial bytes.
                await asyncio.sleep(.03)


def read_heads(store, host):
    store.integrity_check()
    return [inspect_closed_head(store, account.player_id) for account in host.accounts]


def head_pins(heads):
    return [(head.revision, head.sha256) for head in heads]


class RestartedWorld:
    """Own only a new real host service/store; never overwrite session fields."""
    def __init__(self, host, installation, manifest, record):
        self.host, self.installation, self.manifest, self.record = host, installation, manifest, record
        self.server = self.store = None
        self.original_epoch = self.original_heads = None

    async def stop_original(self, worker):
        async def close(s):
            require(s._server is not None and s._store is not None, "original host service is absent")
            heads = head_pins(read_heads(s._store, self.host))
            epoch = s._store.metadata.server_epoch
            await s._server.close()
            require(head_pins(read_heads(s._store, self.host)) == heads,
                    "service shutdown changed the canonical characters")
            s._store.close()
            return epoch, heads
        self.original_epoch, self.original_heads = await on_worker(worker, close)
        self.record("real-host-service-and-store-closed", server_epoch=self.original_epoch,
                    checkpoint_pins=self.original_heads)

    async def start(self, blocks):
        require(self.server is None and self.store is None and self.original_epoch is not None,
                "replacement host must start once, after the original closes")
        self.host = HostWorld.open(self.host.directory, self.installation.rom_path, self.installation.manifest_path)
        self.store = self.host.open_store()
        require(head_pins(read_heads(self.store, self.host)) == self.original_heads,
                "reopening the durable host changed a character")
        require(self.store.battle_reservations_enabled, "durable native battle reservations required")
        self.server = WorldServer(ServerConfig(self.host.build_id, self.host.ruleset_id),
            store=self.store, development_teams=True, development_battles=True)
        lengths = read_string_lengths(self.installation.rom_path,
            table_address=self.manifest["battle_string_table_address"])
        self.server.enable_battle_execution(lengths, self.host.directory / "native-battle-execution",
                                           resume_enabled=True)
        self.server.battle_execution.observer = lambda block: blocks.append(dict(block))
        await self.server.start("127.0.0.1", self.host.port, allow_lan=True, tls=self.host.server_tls)
        require(self.store.metadata.server_epoch == self.original_epoch + 1,
                "recreated host did not perform one real durable boot")
        self.record("real-host-service-reopened-same-world", server_epoch=self.store.metadata.server_epoch,
                    world_id=self.store.metadata.world_id, port=self.host.port, tls=True,
                    original_session_fields_replaced=False)

    async def close(self):
        try:
            if self.server is not None:
                await self.server.close()
                self.server = None
        finally:
            if self.store is not None:
                self.store.close()
                self.store = None


async def native_menu_recovery(current, current_windows, probes, games, host, symbols, replacement, record):
    originals, old_savers = [], []
    async def identity(s):
        c = s._companion
        return (s._game, s._runtime, c._bridge, c._bridge.incarnation, c._live_battle_runtime_id)
    async def saver(s):
        return s._emergency
    async def check_identities():
        for i, worker in enumerate(current):
            after = await on_worker(worker, identity)
            require(all(after[n] is originals[i][n] for n in range(3)) and after[3:] == originals[i][3:]
                    and games[i].process.returncode is None, "recovery replaced an original game or authority")
    before = [await probe.battle() for probe in probes]
    await probes[0].open_players()
    await probes[0].choose("Battle Friend")
    await probes[0].choose("Challenge 1v1")
    await probes[1].open_players()
    await probes[1].choose("Pending challenge")
    await probes[1].choose("Accept challenge")
    async with asyncio.timeout(20):
        while not all(screen.admission_action for _, screen in await asyncio.gather(*(p.ready() for p in probes))):
            await asyncio.sleep(.05)
    async def descriptor(s):
        values = s._companion._bridge.menu_session.menu._battles
        require(len(values) == 1 and values[0]["state"] == "accepted", "native consent is not complete")
        return json.loads(json.dumps(values[0]))
    challenge = await on_worker(current[0], descriptor)
    require(challenge == await on_worker(current[1], descriptor) and challenge["mode"] == 2
            and len(challenge["players"]) == len(set(challenge["players"])) == 2
            and set(challenge["players"]) == {a.player_id for a in host.accounts}
            and len(challenge["consent"]) == 2 and set(challenge["consent"]) == set(challenge["players"]),
            "players disagree on the exact accepted singles roster")
    for worker in current:
        originals.append(await on_worker(worker, identity))
        old_savers.append(await on_worker(worker, saver))
    battle_id = challenge["battle_id"]
    slots = [challenge["players"].index(account.player_id) for account in host.accounts]
    blocks = []
    async def observe(s):
        require(s._server.battle_execution.observer is None, "a previous proof observer exists")
        s._server.battle_execution.observer = lambda block: blocks.append(dict(block))
    await on_worker(current[0], observe)
    await asyncio.gather(*(p.choose("Enter battle", wait=False) for p in probes))
    record("both-native-Enter-selected", battle_id=battle_id, original_pids=[g.process.pid for g in games])
    async def view(slot):
        def read(service):
            room = service.rooms.get(battle_id)
            return dict(state="waiting", pending=None) if room is None else dict(state=room.state,
                pending=None if room.route is None else room.route.validator.pending[slot])
        if replacement.server is not None:
            return read(replacement.server.battle_execution)
        async def original(s):
            return read(s._server.battle_execution)
        return await on_worker(current[0], original)
    stop = asyncio.Event()
    drivers = [asyncio.create_task(drive_battle_input(p, lambda slot=slot: view(slot), symbols, stop))
               for p, slot in zip(probes, slots)]
    started = time.monotonic()
    try:
        async with asyncio.timeout(120):
            while len(blocks) < 12 or not all(value["state"] == 5 for value in await asyncio.gather(*(p.battle() for p in probes))):
                for driver in drivers:
                    if driver.done():
                        await driver
                        raise AssertionError("native driver ended before the mid-battle fault")
                await asyncio.sleep(.05)
    finally:
        stop.set()
        await asyncio.gather(*drivers)
    require(all(row["state"] == "executing" for row in await asyncio.gather(*(view(slot) for slot in slots))),
            "match ended before host loss")
    original_intents = []
    async def intent_bytes(s):
        path = s.profile_directory / "pending-battle.json"
        value = read_battle_intent(path)
        require(value.battle_id == battle_id and value.runtime_id == s._companion._live_battle_runtime_id,
                "full original native battle intent is absent")
        return path, path.read_bytes()
    for worker in current:
        original_intents.append(await on_worker(worker, intent_bytes))
    record("mid-battle-loss-boundary", routed_blocks=len(blocks), input_commands_drained=True,
        original_intent_sha256=[hashlib.sha256(raw).hexdigest() for _, raw in original_intents])
    await replacement.stop_original(current[0])

    async def held_ready(s):
        require(s._game is not None and s._game.process.returncode is None, "original core exited on host loss")
        return (not s._companion.connected and s._interaction is None and s.can_recover_battle
                and not s.can_save and s._emergency.result.state == "battle_waiting")
    async with asyncio.timeout(60):
        while not all(await asyncio.gather(*(on_worker(w, held_ready) for w in current))):
            await asyncio.sleep(.05)
    async def sustained_hold(label):
        first = await asyncio.gather(*(p.retained(suspended=True) for p in probes))
        # Genuine directional input tests that the native hold prevents gameplay.
        ack = await asyncio.gather(*(p.press(16, frames=120, release=60) for p in probes))
        second = await asyncio.gather(*(p.retained(after=ack[i]["frame"]-1, suspended=True)
                                        for i, p in enumerate(probes)))
        for a, b in zip(first, second):
            verify_stable_hold(a, b)
        await check_identities()
        require(all(path.read_bytes() == raw for path, raw in original_intents),
                "host loss or partial renewal changed an original battle intent")
        record(label, before=first, after=second, ordinary_directional_frames=120,
               original_pids=[g.process.pid for g in games])
    await sustained_hold("both-original-cores-frozen-after-host-loss")
    await replacement.start(blocks)

    async def recovery_state(worker):
        async def read(s):
            future = worker._battle_recovery_future
            error = None
            if future is not None and future.done():
                try:
                    future.result()
                except BaseException as exc:
                    error = repr(exc)
            return dict(status=asdict(s.status), can_save=s.can_save, connected=s._companion.connected,
                active=future is not None and not future.done(), done=future is not None and future.done(),
                error=error, owned=s._interaction is not None)
        return await on_worker(worker, read)
    async def click_recover(i):
        button = current_windows[i].recover_battle_button
        async with asyncio.timeout(20):
            while str(button.cget("state")) != "normal":
                await asyncio.sleep(.05)
        button.invoke()  # Real Tk command -> SessionWorker -> LauncherSession.
        async with asyncio.timeout(20):
            while True:
                state = await recovery_state(current[i])
                require(not state["done"], f"recovery action ended before quorum: {state}")
                if state["active"]:
                    break
                await asyncio.sleep(.05)
        record("actual-Recover-battle-widget-invoked", account=i, physical_click=False)
    await click_recover(0)
    async def partial_quorum():
        first, second = await asyncio.gather(*(recovery_state(w) for w in current))
        require(not first["done"], f"first recovery action ended before the second player: {first}")
        require(not second["connected"] and not second["active"] and not second["done"],
                "second original reconnected without its explicit recovery action")
        require(not first["can_save"] and not second["can_save"], "partial quorum allowed saving")
        recovery = replacement.server.battle_execution.recovery
        room = None if recovery is None else recovery.rooms.get(battle_id)
        if room is None or not first["connected"]:
            return False
        require(room.state == "waiting" and room.stage == "recovery" and room.task is None
                and not room.pending and not room.acknowledged
                and set(room.ready) <= {host.accounts[0].player_id},
                "partial quorum issued or authorized native progress")
        return set(room.ready) == {host.accounts[0].player_id}
    async with asyncio.timeout(30):
        while not await partial_quorum():
            await asyncio.sleep(.05)
    before_blocks = len(blocks)
    await sustained_hold("first-recovered-original-still-waits-for-second")
    require(await partial_quorum() and len(blocks) == before_blocks,
            "partial quorum progressed the native route")
    require(head_pins(read_heads(replacement.store, host)) == replacement.original_heads,
            "interrupted battle altered a canonical character")
    record("missing-second-player-proved", native_route_blocks=before_blocks,
           waiting_player=host.accounts[0].player_id, withheld_player=host.accounts[1].player_id)
    await click_recover(1)
    stop = asyncio.Event()
    drivers = [asyncio.create_task(drive_battle_input(p, lambda slot=slot: view(slot), symbols, stop))
               for p, slot in zip(probes, slots)]
    try:
        async with asyncio.timeout(600):
            report_at = 0
            while True:
                for driver in drivers:
                    if driver.done():
                        await driver
                states = await asyncio.gather(*(recovery_state(w) for w in current))
                require(all(not row["done"] or row["status"]["code"] == "battle_recovered" for row in states),
                        f"actual Recover action ended without terminal adoption: {states}")
                if all(row["done"] and row["can_save"] and not row["owned"]
                       and row["status"]["code"] == "battle_recovered" for row in states):
                    break
                if time.monotonic() >= report_at:
                    record("resumed-native-1v1-progress", blocks=len(blocks),
                           elapsed_seconds=round(time.monotonic()-started, 3), statuses=states)
                    report_at = time.monotonic()+20
                await asyncio.sleep(.05)
    finally:
        stop.set()
        await asyncio.gather(*drivers)
    await check_identities()
    results = []
    for i, worker in enumerate(current):
        async def terminal(s):
            c = s._companion
            require(s._battle_retained is None and s._battle_handoff_successor is None
                    and not s._battle_recovery_failed, "launcher retains unfinished recovery ownership")
            require(s._emergency is not old_savers[i] and s._emergency.result.state == "armed"
                    and c._emergency_controller is s._emergency, "new terminal saver is not armed")
            require(not any((s.profile_directory / name).exists() for name in
                ("pending-battle.json", "pending-battle-admission.json", "pending-export.json", "pending-emergency.json")),
                "terminal recovery intent remains pending")
            history = (await c.battle_challenge_rpc("history"))["result"]
            values = [v for v in history if v["battle_id"] == battle_id]
            require(len(values) == 1 and values[0]["mode"] == 2
                    and values[0]["players"] == challenge["players"] and values[0]["outcome"] in (1, 2, 3),
                    "durable resumed singles result missing")
            return values[0], dict(status=asdict(s.status),
                completion_sha256=sha(s.profile_directory / (battle_id + ".battle-recovery-complete.json")),
                handoff_sha256=sha(s.profile_directory / (battle_id + ".battle-handoff.json")))
        result, detail = await on_worker(worker, terminal)
        results.append(result)
        row = await probes[i].snapshot(lambda r: r["hold"] == 0)
        state = await probes[i].battle(after=row["frame"]-1)
        require(state["count"] == before[i]["count"] and state["party_sha256"] == before[i]["party_sha256"],
                "recovery failed to restore the original personal party")
        record("launcher-native-battle-recovered", account=i, pid=games[i].process.pid, **detail)
    require(results[0] == results[1], "recovered players disagree on their durable result")
    record("real-resumed-native-1v1-result", result=results[0], routed_blocks=len(blocks),
           elapsed_seconds=round(time.monotonic()-started, 3))
    for i, probe in enumerate(probes):
        result = results[i]
        await probe.open_players()
        await probe.choose("Challenges")
        await probe.choose("Recent battle results")
        outcome = "Draw" if result["outcome"] == 3 else "Win" if result["outcome"] == 1+slots[i]%2 else "Loss"
        _, screen = await probe.choose(f"1v1 {outcome} #{result['sequence']}")
        require(screen.title == "Battle result" and screen.status ==
                ("Draw" if result["outcome"] == 3 else f"Team {result['outcome']} won"),
                "native history screen differs from the resumed result")
        record("recovered-native-result-screen-matches", account=i, title=screen.title, status=screen.status)
        async with asyncio.timeout(10):
            while (await probe.snapshot())["active"]:
                await probe.press(2)
    return results[0]


async def run(args):
    require(os.name == "nt", "this qualifier requires the existing Windows runtime")
    require(math.isfinite(args.timeout) and 600 <= args.timeout <= 1200, "timeout must be 600..1200 seconds")
    inputs = {name: getattr(args, name).resolve() for name in ("rom", "manifest", "elf", "symbols", "bridge", "source_a", "source_b", "source_index")}
    hashes = {name: sha(path) for name, path in inputs.items()}
    require(hashes == {name: getattr(args, name + "_sha256") for name in inputs}, "explicit input pins differ")
    manifest = json.loads(inputs["manifest"].read_text())
    require(manifest["elf_sha256"] == hashes["elf"], "ELF does not match the manifest")
    required = dict(menu_abi_version=2, battle_abi_version=3, battle_resume_abi_version=1,
        emergency_save_abi_version=2, battle_execution_abi_version=1, battle_admission_cleanup_abi_version=1)
    require(all(manifest.get(k) == v for k, v in required.items()), "combined cleanup-capable game required")
    symbols = {}
    for line in inputs["symbols"].read_text().splitlines():
        fields = line.split()
        if len(fields) == 4:
            symbols[fields[3]] = (int(fields[0], 16), int(fields[1], 16))
    require(all(symbols.get(k, (0, 0))[1] == v for k, v in SYMBOLS.items()), "diagnostic symbol sizes differ")
    for name in PARTY_TASKS:
        address, size = symbols.get(name, (0, 0))
        require(size > 0 and 0x08000000 <= (address & ~1)
                and (address & ~1) + size <= 0x08000000 + manifest["rom_size"],
                "party input task is outside the pinned ROM")
    action_size = symbols.get("sCurrentStartMenuActions", (0, 0))[1]
    require(3 <= action_size <= 64, "bounded start menu actions required")
    for name in (*SYMBOLS, "sCurrentStartMenuActions"):
        address, size = symbols[name]
        require(0x02000000 <= address and address + size <= 0x02040000 or
                0x03000000 <= address and address + size <= 0x03008000, "diagnostic is outside native RAM")
    parent = RuntimeBundle(args.bundle.resolve(), args.bundle_sha256)
    GameInstallation(inputs["rom"], inputs["manifest"], hashes["rom"], hashes["manifest"], parent).verify()
    output = args.output.resolve()
    require("PokemonPrivate" in output.parts, "use a new private PokemonPrivate output directory")
    output.mkdir(parents=True, exist_ok=False)
    for name, path in inputs.items():
        shutil.copyfile(path, output / ("input-" + name + path.suffix))
    source_root = Path(__file__).resolve().parents[2]
    source_index = json.loads(inputs["source_index"].read_text())
    source_hashes = verify_source_index(source_root, source_index)
    require(Path(session_module.__file__).resolve() == source_root / "src/emerald_multiplayer/launcher_session.py",
            "production imports did not come from the explicitly pinned source tree")
    for name in source_index:
        target = output / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source_root / name).read_bytes())
    # Supply current production Lua as the helper's parent bridge through a
    # new minimal runtime copy; executable/DLL originals remain pinned.
    staging = output / "base-runtime"
    staging.mkdir()
    executable, _ = parent.verify()
    for name in (executable.name, "SDL2.dll", "libwinpthread-1.dll"):
        shutil.copyfile(parent.directory / name, staging / name)
    bridge = inputs["bridge"].read_bytes().decode("utf-8")
    (staging / "mgba.lua").write_bytes(bridge.encode("utf-8"))
    value = dict(format="emerald-windows-runtime-v1", executable=executable.name, bridge="mgba.lua",
                 files={p.name: sha(p) for p in staging.iterdir()})
    (staging / "runtime.json").write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    bundle = proof_bundle(RuntimeBundle(staging, sha(staging / "runtime.json")), output, manifest)
    bundle = append_input_probe(bundle, bridge, output, symbols, manifest)
    installation = GameInstallation(output / "input-rom.gba", output / "input-manifest.json",
                                    hashes["rom"], hashes["manifest"], bundle)
    evidence = dict(passed=False, scope=__doc__, inputs=hashes, source_hashes=source_hashes,
        parent_runtime_pin=args.bundle_sha256, proof_runtime_pin=bundle.manifest_sha256,
        checks=[], statuses=[], forced_children=[], cleanup_errors=[],
        physical_input=False, physical_gui_click=False, timed_autosave=False,
        fault_recovery=True, host_fault="graceful-service-close-and-durable-reopen",
        host_pc_crash=False, host_process_crash=False, gui_host_restart=False,
        separate_pc=False, internet=False, production_deadlines_changed=False,
        source_index_pin=hashes["source_index"])
    def persist():
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    def record(name, **fields):
        evidence["checks"].append(dict(name=name, **fields))
        persist()
        output_event(check=name, **fields)
    workers, children, windows, roots = [], [], [], []
    enrollment_pids = set()
    completed = False
    replacement = None
    private = output / "private"

    async def poll_until(predicate, timeout=30):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(.05)

    async def gui_pump():
        while True:
            for root in roots:
                root.update()
            await asyncio.sleep(.02)

    pump = asyncio.create_task(gui_pump())
    try:
        async with asyncio.timeout(args.timeout):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            host = create_world(installation, private, player_names=("Battle Host", "Battle Friend"), endpoint="127.0.0.1", port=port)
            expected = []
            for slot, name in enumerate(("source_a", "source_b")):
                async with host_enrollment(installation, private, world_directory=host.directory, slot=slot, source_path=inputs[name]) as runtime:
                    children.append((runtime._game.process, asyncio.get_running_loop()))
                    record("enrollment-child", slot=slot, pid=runtime._game.process.pid)
                    await field_ready(runtime.companion, runtime._game)
                    enrolled = await runtime.enroll()
                    require(enrolled.metadata["revision"] == 1, "enrollment revision differs")
                    require(runtime._game.process.returncode is not None,
                            "production enrollment did not close its bootstrap child")
                    enrollment_pids.add(runtime._game.process.pid)
                    record("production-enrollment-closed-bootstrap", slot=slot,
                           pid=runtime._game.process.pid,
                           returncode=runtime._game.process.returncode)
                with MirrorLease(runtime.save_path):
                    pass
                with host.open_store() as store:
                    expected.append(party(inspect_closed_head(store, host.accounts[slot].player_id)))
            require([value["count"] for value in expected] == [2, 1],
                    "this bounded qualifier requires the pinned ordinary two/one-member parties")
            invitation = output / "friend-invitation.json"
            export_friend_invitation(installation, host.directory, 1, invitation)
            saved = []
            for phase in ("recover-and-save", "fresh-Continue"):
                current, current_windows, games, probes, mirrors = [], [], [], [], []
                for slot, mode in enumerate(("host", "join")):
                    worker = SessionWorker(installation, private)
                    workers.append(worker)
                    current.append(worker)
                    import tkinter as tk
                    root = tk.Tk() if not roots else tk.Toplevel(roots[0])
                    window = LauncherWindow(root, worker, version="Private 1v1 service recovery qualification")
                    root.title(f"Recovery proof {phase} {mode}")
                    roots.append(root)
                    windows.append(window)
                    current_windows.append(window)
                    selection = host.directory / "world.json" if slot == 0 else invitation
                    require(worker.start(LaunchRequest(mode, selection)), "real GUI worker did not start")
                    await poll_until(lambda: worker._active_session is not None or not worker.busy)
                    require(worker._active_session is not None, "launcher worker failed before play")
                    async def prepare(s):
                        async with asyncio.timeout(30):
                            while s._game is None:
                                await asyncio.sleep(.03)
                        # Register the child before any subsequent inspection
                        # can fail, so the qualifier always owns its cleanup.
                        children.append((s._game.process, worker._loop))
                        await s.set_autosave_enabled(False)
                        return s._game, s._companion.ipc_address[1], s.profile_directory / "character.sav"
                    game, ipc, mirror = await on_worker(worker, prepare)
                    games.append(game)
                    mirrors.append(mirror)
                    probes.append(RecoveryProbe(output, ipc, action_size, record))
                    async def ready(s):
                        await field_ready(s._companion, s._game)
                        async with asyncio.timeout(20):
                            while s._emergency is None or s._emergency.result.state != "armed":
                                await asyncio.sleep(.03)
                        lease_is_owned(s.profile_directory / "character.sav")
                        require(s._companion._remote_writer.get_extra_info("ssl_object") is not None, "TLS missing")
                        return s.status.revision
                    require(await on_worker(worker, ready) == (1 if phase == "recover-and-save" else 2), "startup revision differs")
                record("actual-launcher-workers-ready", phase=phase, pids=[g.process.pid for g in games])
                if phase == "recover-and-save":
                    replacement = RestartedWorld(host, installation, manifest, record)
                    await native_menu_recovery(current, current_windows, probes, games, host, symbols, replacement, record)
                    for slot, worker in enumerate(current):
                        async def save(s):
                            require(await s.save(), "manual save did not finish")
                            require(s.status.revision == 2, "manual save revision differs")
                        await on_worker(worker, save)
                async def heads(s):
                    rows = []
                    for slot, account in enumerate(host.accounts):
                        head = inspect_closed_head(s._store, account.player_id)
                        require(head.revision == 2 and party(head) == expected[slot], "canonical party or revision changed")
                        rows.append((head.revision, head.sha256, head.payload))
                    s._store.integrity_check()
                    return rows
                if phase == "recover-and-save":
                    actual = []
                    for slot, head in enumerate(read_heads(replacement.store, host)):
                        require(head.revision == 2 and party(head) == expected[slot], "resumed canonical party or revision changed")
                        actual.append((head.revision, head.sha256, head.payload))
                else:
                    actual = await on_worker(current[0], heads)
                if phase == "recover-and-save":
                    saved = actual
                else:
                    require(actual == saved, "fresh Continue changed canonical checkpoints")
                    require(all(g.startup.mirror.sha256 == actual[n][1] for n, g in enumerate(games)), "fresh native mirror differs")
                record("ready_for_normal_close", phase=phase, friend_pid=games[1].process.pid, host_pid=games[0].process.pid)
                await poll_until(lambda: not any(w.busy for w in current), 120)
                require([g.process.returncode for g in games] == [0, 0], "ordinary SDL exit failed")
                for slot, game in enumerate(games):
                    checked_log(game, expected[slot])
                    with MirrorLease(mirrors[slot]):
                        pass
                record("normal-close-and-native-party-verified", phase=phase, exit_codes=[0, 0])
                if phase == "recover-and-save":
                    require(head_pins(read_heads(replacement.store, host)) == [(v[0], v[1]) for v in saved],
                            "normal original-core closure changed resumed checkpoints")
                    await replacement.close()
                    record("replacement-host-service-closed-before-fresh-Continue")
            with host.open_store() as store:
                store.integrity_check()
                require([(h.revision, h.sha256, h.payload) for h in
                    (inspect_closed_head(store, a.player_id) for a in host.accounts)] == saved, "closed final heads differ")
            completed = True
    except BaseException as error:
        evidence["error"] = repr(error)
        evidence["traceback"] = traceback.format_exc()
        raise
    finally:
        # The supervisor owns the replacement independently of all GUI workers.
        if replacement is not None:
            try:
                await asyncio.wait_for(replacement.close(), 20)
            except BaseException as error:
                evidence["cleanup_errors"].append("replacement host: " + repr(error))
        # The normal path has no running children. Failure cleanup stops only
        # explicitly tracked test-owned processes and cannot earn acceptance.
        for child, owner_loop in children:
            if child.returncode is None:
                evidence["forced_children"].append(child.pid)
                async def stop(process=child):
                    if process.returncode is None:
                        process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), 5)
                    except TimeoutError:
                        process.kill()
                        await asyncio.wait_for(process.wait(), 5)
                try:
                    if owner_loop is asyncio.get_running_loop():
                        await stop()
                    elif owner_loop.is_running():
                        await asyncio.wait_for(asyncio.wrap_future(asyncio.run_coroutine_threadsafe(stop(), owner_loop)), 12)
                    else:
                        raise RuntimeError("test child owner loop stopped before child exit")
                except BaseException as error:
                    evidence["cleanup_errors"].append(repr(error))
        try:
            await poll_until(lambda: not any(w.busy for w in workers), 15)
        except BaseException as error:
            evidence["cleanup_errors"].append(repr(error))
        pump.cancel()
        pump_result = (await asyncio.gather(pump, return_exceptions=True))[0]
        if isinstance(pump_result, BaseException) and not isinstance(pump_result, asyncio.CancelledError):
            evidence["cleanup_errors"].append("GUI pump: " + repr(pump_result))
        for window in reversed(windows):
            try:
                window._destroy()
            except Exception as error:
                evidence["cleanup_errors"].append(repr(error))
        evidence["child_exits"] = [dict(pid=p.pid, returncode=p.returncode) for p, _ in children]
        evidence["automatically_closed_enrollment_pids"] = sorted(enrollment_pids)
        try:
            evidence["inputs_unchanged"] = all(sha(p) == hashes[n] for n, p in inputs.items())
            evidence["sources_unchanged"] = verify_source_index(source_root, source_index) == source_hashes
            evidence["input_copies_unchanged"] = all(sha(output / ("input-"+n+p.suffix)) == hashes[n] for n, p in inputs.items())
            evidence["source_copies_unchanged"] = all(sha(output / "source" / n) == digest for n, digest in source_index.items())
            installation.verify()
            parent.verify()
            bundle.verify()
        except BaseException as error:
            evidence["cleanup_errors"].append(repr(error))
        evidence["passed"] = (completed and evidence.get("inputs_unchanged") and evidence.get("sources_unchanged")
            and evidence.get("input_copies_unchanged") and evidence.get("source_copies_unchanged")
            and not evidence["forced_children"] and not evidence["cleanup_errors"]
            and all(p.returncode is not None and (p.pid in enrollment_pids or p.returncode == 0)
                    for p, _ in children) and not any(w.busy for w in workers))
        persist()
        output_event(passed=evidence["passed"], child_exits=evidence["child_exits"])
    require(evidence["passed"], "qualification failed; preserved private evidence records its scope")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "manifest", "elf", "symbols", "bridge", "bundle", "source-a", "source-b", "source-index"):
        parser.add_argument("--" + name, type=Path, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=1200)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
