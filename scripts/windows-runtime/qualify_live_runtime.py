"""Private Windows cold-start/live-checkpoint/fresh-Continue qualification.

Reuse the established smoke_player_runtime proof's ordinary joypad and read-only
party diagnostics. Inputs are a CLOSED actual-core proof, its frozen game, and
an independently pinned runtime. No HostWorld or GUI acceptance is inferred.
Close each native window normally when the printed phase requests it.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import zlib

from emerald_multiplayer.checkpoint_mirror import MirrorError, MirrorLease
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.launcher_session import GameInstallation
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.player_runtime import PlayerRuntime, RuntimeBundle
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def party(checkpoint):
    parsed = inspect_flash(checkpoint.payload, save_profile=OWNERSHIP_PROFILE)
    owned = inspect_ownership(parsed)
    boxes = b"".join(parsed.save_block1[568 + i * 100:568 + i * 100 + 80]
                     for i in range(parsed.metadata.party_count))
    return dict(count=parsed.metadata.party_count, box_crc=f"{zlib.crc32(boxes):08x}",
                serials=[r.serial for r in owned.records if r.location.startswith("party:")])


def proof_bundle(parent, output, manifest):
    executable, _ = parent.verify()
    parent_manifest = json.loads((parent.directory / "runtime.json").read_bytes())
    bridge = (parent.directory / parent_manifest["bridge"]).read_bytes().decode("utf-8")
    bundle = output / "proof-bundle"
    bundle.mkdir()
    for name in (executable.name, "SDL2.dll", "libwinpthread-1.dll"):
        shutil.copyfile(parent.directory / name, bundle / name)
    # Test-only native button API; never RAM writes, save injection, states, or
    # a Windows-keyboard test. The production bridge remains byte-for-byte prefix.
    bridge += '\nlocal plan={{0,1000},{8,12},{0,480},{8,12},{0,180},{1,12},{0,300}}\n' \
              'local step,left=1,1000\ncallbacks:add("frame",function()\n' \
              'if step<=#plan then emu:setKeys(plan[step][1]);left=left-1\n' \
              'if left==0 then step=step+1;if step<=#plan then left=plan[step][2]\n' \
              'else emu:setKeys(0) end end\n' \
              'elseif emu:currentFrame()%120==0 then\n' \
              f'local count=emu:read8({manifest["debug_party_counts_address"]})\n' \
              f'local party=emu:readRange({manifest["debug_parties_address"]},600)\n' \
              'local boxes={};for i=0,count-1 do boxes[#boxes+1]=party:sub(i*100+1,i*100+80) end\n' \
              'console:warn(string.format("WINDOWS_LIVE party_count=%d box_crc=%08x",count,crc32(table.concat(boxes))))\n' \
              'end\nend)\n'
    (bundle / "mgba.lua").write_bytes(bridge.encode("utf-8"))
    value = dict(format="emerald-windows-runtime-v1", executable=executable.name, bridge="mgba.lua",
                 files={path.name: sha(path) for path in sorted(bundle.iterdir())})
    (bundle / "runtime.json").write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    return RuntimeBundle(bundle, sha(bundle / "runtime.json"))


async def field_ready(companion, game, *, timeout=90):
    async with asyncio.timeout(timeout):
        while game.process.returncode is None:
            bridge, pose = companion._bridge, companion._local_pose
            if (bridge is not None and bridge.save_capable and bridge.window_capable
                    and bridge.battle_capable and bridge.menu_session is not None
                    and pose is not None and pose.activity == 1 and pose.frame >= 2400):
                return dict(save=True, window=True, battle=True, menu=True,
                            incarnation=bridge.incarnation, pose=pose.__dict__)
            await asyncio.sleep(.05)
    raise RuntimeError("native child exited before verified capabilities and ordinary field Continue")


def lease_is_owned(save):
    try:
        with MirrorLease(save):
            raise RuntimeError("native child did not retain its exclusive mirror lease")
    except MirrorError as error:
        if error.code != "mirror_active":
            raise


async def run(args):
    source, output = args.source.resolve(), args.output.resolve()
    index = args.profile_index
    if not 0 <= index <= 3:
        raise ValueError("profile index must select one of four actual players")
    for suffix in ("-wal", "-shm"):
        if (source / ("world.sqlite3" + suffix)).exists():
            raise ValueError("source database must be a closed consistent proof")
    source_private = source / f"private-{index}"
    source_save = source / ("client-" + "abcd"[index] + ".sav")
    files = dict(database=source / "world.sqlite3", profiles=source / "profiles.json",
                 rom=args.rom.resolve(), manifest=args.manifest.resolve(), save=source_save,
                 mirror=source_save.with_name(source_save.name + ".checkpoint.json"))
    files.update({"recovery/" + str(path.relative_to(source_private)): path
                  for path in source_private.rglob("*") if path.is_file()})
    before = {name: sha(path) for name, path in files.items()}
    if before["rom"] != args.rom_sha256 or before["manifest"] != args.manifest_sha256:
        raise ValueError("game source does not match the explicit qualification pins")
    parent = RuntimeBundle(args.bundle.resolve(), args.bundle_sha256)
    GameInstallation(args.rom, args.manifest, args.rom_sha256, args.manifest_sha256, parent).verify()
    output.mkdir(parents=True, exist_ok=False)
    evidence = dict(parent_runtime_pin=args.bundle_sha256, source_hashes=before,
                    scripted_ordinary_joypad=True, windows_keyboard_qualified=False,
                    gui_save_button_qualified=False, launcher_session_qualified=False,
                    audible_playback_qualified=False, transport="authenticated development loopback",
                    passed=False, phases=[])
    shutil.copyfile(__file__, output / "controller.py")
    for name, destination in (("database", "world.sqlite3"), ("profiles", "profiles.json"),
                              ("rom", "game.gba"), ("manifest", "manifest.json"),
                              ("save", "character.sav"), ("mirror", "character.sav.checkpoint.json")):
        shutil.copyfile(files[name], output / destination)
    shutil.copytree(source_private, output / "private")
    manifest = json.loads((output / "manifest.json").read_text())
    bundle = proof_bundle(parent, output, manifest)
    evidence["proof_runtime_pin"] = bundle.manifest_sha256
    profile = json.loads((output / "profiles.json").read_text())[index]
    store = TradeCheckpointStore(output / "world.sqlite3", build_id=manifest["rom_sha256"],
                                ruleset_id=manifest["ruleset_id"], save_profile=OWNERSHIP_PROFILE)
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"]),
                         store=store, development_trades=True)
    companion = None
    save = output / "character.sav"
    try:
        await server.start(port=0)
        config = CompanionConfig(output / "game.gba", output / "manifest.json", profile["player_id"],
                                 profile["display_name"], secrets.token_bytes(32), server_port=server.address[1],
                                 ipc_port=0, server_credential=bytes.fromhex(profile["credential"]),
                                 expected_world_id=store.metadata.world_id)
        companion = Companion(config)
        await companion.start()
        async with asyncio.timeout(20):
            while not companion.connected:
                await asyncio.sleep(.05)
        initial = store.read_checkpoint(profile["player_id"], companion.session_epoch)
        expected = party(initial)
        evidence.update(initial_revision=initial.revision, initial_sha256=initial.sha256,
                        initial_party=expected)
        head = initial
        for number, label in enumerate(("live-checkpoint", "fresh-Continue")):
            phase = dict(name=label, expected_revision=head.revision)
            evidence["phases"].append(phase)
            runtime = PlayerRuntime(companion, bundle, output / "private", save)
            async with runtime.open() as game:
                phase.update(pid=game.process.pid, installed_revision=game.startup.mirror.revision,
                             installed_sha256=sha(save), startup_evidence=str(game.startup.evidence_path))
                assert phase["installed_revision"] == head.revision and phase["installed_sha256"] == head.sha256
                lease_is_owned(save)
                phase["lease_blocked_while_running"] = True
                print(json.dumps(dict(phase=label, pid=game.process.pid, output=str(output))), flush=True)
                phase["capabilities_and_field"] = await field_ready(companion, game)
                if number == 0:
                    coordinator = LiveCheckpointCoordinator(companion, output / "private")
                    result = await coordinator.checkpoint(expected_revision=head.revision)
                    saved = store.read_checkpoint(profile["player_id"], companion.session_epoch)
                    assert saved.revision == head.revision + 1
                    assert saved.sha256 == result.flash_sha256 and not coordinator.pending_path.exists()
                    assert party(saved) == expected
                    phase.update(saved_revision=saved.revision, saved_sha256=saved.sha256,
                                 completed_operation=result.operation_id, native_checkpoint_completed=True)
                    (output / "saved-head.flash").write_bytes(saved.payload)
                    head = saved
                print(json.dumps(dict(phase=label, ready_for_normal_window_close=True,
                                      canonical_revision=head.revision)), flush=True)
                phase["exit_code"] = await asyncio.wait_for(game.wait(), 120)
                samples = re.findall(r"WINDOWS_LIVE party_count=(\d+) box_crc=([0-9a-f]{8})",
                                     game.log_path.read_text(errors="replace"))
                phase["party_matches_canonical"] = bool(samples and samples[-1] == (str(expected["count"]), expected["box_crc"]))
                phase["log_path"] = str(game.log_path)
                assert phase["exit_code"] == 0 and phase["party_matches_canonical"]
            with MirrorLease(save):
                phase["lease_released_after_close"] = True
            async with asyncio.timeout(10):
                while companion._bridge is not None:
                    await asyncio.sleep(.05)
            # Closing a trade-capable bridge invalidates its network lease.
            # Let the normal authenticated reconnect establish the next epoch.
            async with asyncio.timeout(20):
                while not companion.connected:
                    await asyncio.sleep(.05)
            assert store.read_checkpoint(profile["player_id"], companion.session_epoch) == head
            phase["head_unchanged_after_close"] = True
        store.integrity_check()
        evidence.update(final_revision=head.revision, final_sha256=head.sha256, clone_integrity=True)
        evidence["passed"] = True
    finally:
        if companion is not None:
            await companion.close()
        await server.close()
        store.close()
        evidence["source_hashes_after"] = {name: sha(path) for name, path in files.items()}
        evidence["sources_unchanged"] = before == evidence["source_hashes_after"]
        evidence["passed"] = evidence["passed"] and evidence["sources_unchanged"]
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(dict(passed=evidence["passed"], sources_unchanged=evidence["sources_unchanged"],
                              evidence=str(output / "evidence.json"))), flush=True)
    return 0 if evidence["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "rom", "manifest", "bundle", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("rom-sha256", "manifest-sha256", "bundle-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--profile-index", type=int, default=0)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
