"""Private Windows proof of PlayerRuntime with a copied authenticated world.

Requires a closed consistent database backup and a matching private profile.
Never opens the source database, changes originals, or creates enrollment.
The separate proof bundle appends only ordinary joypad/read-only diagnostics.
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
from uuid import uuid4
import zlib

from emerald_multiplayer.checkpoint_mirror import MirrorError, MirrorLease
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.player_runtime import PlayerRuntime, RuntimeBundle
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = dict(database=args.database, profile=args.profile, rom=args.rom,
                   manifest=args.manifest, save=args.save)
    before = {name: sha(path) for name, path in sources.items()}
    evidence = dict(source_hashes=before, parent_runtime_pin=args.bundle_sha256,
                    scripted_joypad=True, windows_keyboard_qualified=False,
                    audible_playback_qualified=False)
    parent = RuntimeBundle(args.bundle, args.bundle_sha256)
    executable, bridge = parent.verify()
    bundle = output / "proof-bundle"
    bundle.mkdir()
    for name in (executable.name, "SDL2.dll", "libwinpthread-1.dll"):
        shutil.copyfile(parent.directory / name, bundle / name)
    native_manifest = json.loads(args.manifest.read_text())
    bridge += '\nlocal plan={{0,1000},{8,8},{0,480},{8,8},{0,180},{1,8},{0,300}}\n' \
              'local step,left=1,1000\ncallbacks:add("frame",function()\n' \
              'if step<=#plan then emu:setKeys(plan[step][1]);left=left-1\n' \
              'if left==0 then step=step+1;if step<=#plan then left=plan[step][2]\n' \
              'else emu:setKeys(0) end end\n' \
              'elseif emu:currentFrame()%120==0 then\n' \
              f'local count=emu:read8({native_manifest["debug_party_counts_address"]})\n' \
              f'local party=emu:readRange({native_manifest["debug_parties_address"]},600)\n' \
              'local boxes={};for i=0,count-1 do boxes[#boxes+1]=party:sub(i*100+1,i*100+80) end\n' \
              'console:warn(string.format("RUNTIME_PLAYER party_count=%d box_crc=%08x",count,crc32(table.concat(boxes))))\n' \
              'end\nend)\n'
    (bundle / "mgba.lua").write_text(bridge)
    proof_manifest = dict(format="emerald-windows-runtime-v1", executable=executable.name, bridge="mgba.lua",
                          files={path.name: sha(path) for path in sorted(bundle.iterdir())})
    (bundle / "runtime.json").write_text(json.dumps(proof_manifest, sort_keys=True, indent=2) + "\n")
    proof_pin = sha(bundle / "runtime.json")
    evidence["proof_runtime_pin"] = proof_pin
    for name in ("database", "profile", "rom", "manifest", "save"):
        shutil.copyfile(sources[name], output / {"database":"world.sqlite3", "profile":"profiles.json",
                                               "rom":"game.gba", "manifest":"manifest.json", "save":"character.sav"}[name])
    manifest = json.loads((output / "manifest.json").read_text())
    profile = json.loads((output / "profiles.json").read_text())[args.profile_index]
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
        for _ in range(400):
            if companion.connected:
                break
            await asyncio.sleep(.05)
        if not companion.connected:
            raise RuntimeError("private cloned world could not authenticate")
        head = store.read_checkpoint(profile["player_id"], companion.session_epoch)
        parsed = inspect_flash(head.payload, save_profile=OWNERSHIP_PROFILE)
        owned = inspect_ownership(parsed)
        expected_boxes = b"".join(parsed.save_block1[568+i*100:568+i*100+80]
                                  for i in range(parsed.metadata.party_count))
        expected_crc = f"{zlib.crc32(expected_boxes):08x}"
        evidence.update(canonical_revision=head.revision, canonical_sha256=head.sha256,
                        canonical_party_count=parsed.metadata.party_count, canonical_box_crc32=expected_crc,
                        canonical_party_serials=[r.serial for r in owned.records if r.location.startswith("party:")])
        runtime = PlayerRuntime(companion, RuntimeBundle(bundle, proof_pin), output / "private", save)
        async with runtime.open() as game:
            evidence["pid"] = game.process.pid
            evidence["startup_evidence"] = str(game.startup.evidence_path)
            evidence["installed_current_head"] = game.startup.mirror.revision == head.revision and sha(save) == head.sha256
            try:
                with MirrorLease(save):
                    raise RuntimeError("running game lost its exclusive save lease")
            except MirrorError:
                evidence["lease_blocked_while_running"] = True
            print(json.dumps(dict(pid=game.process.pid, revision=head.revision, output=str(output))), flush=True)
            deadline = asyncio.get_running_loop().time() + 75
            while game.process.returncode is None and asyncio.get_running_loop().time() < deadline:
                log = game.log_path.read_text(errors="replace")
                samples = re.findall(r"RUNTIME_PLAYER party_count=(\d+) box_crc=([0-9a-f]{8})", log)
                pose = companion._local_pose
                if (companion._bridge is not None and pose is not None and pose.activity == 1
                        and pose.frame >= 2400):
                    evidence["overworld_presence"] = pose.__dict__
                    print("Canonical startup reached native overworld; inspect/close window. Buffered party diagnostics verify after normal close.", flush=True)
                    break
                await asyncio.sleep(.1)
            evidence["log_path"] = str(game.log_path)
            try:
                evidence["exit_code"] = await asyncio.wait_for(game.wait(), 120)
            except asyncio.TimeoutError:
                evidence["close_timeout"] = True
            # The native stdio logger may buffer a short redirected log until
            # normal exit. Require the actual read-only party sample then.
            samples = re.findall(r"RUNTIME_PLAYER party_count=(\d+) box_crc=([0-9a-f]{8})",
                                 game.log_path.read_text(errors="replace"))
            evidence["native_party_matches_current_head"] = bool(
                samples and samples[-1] == (str(parsed.metadata.party_count), expected_crc))
        with MirrorLease(save):
            evidence["lease_released_after_close"] = True
        store.integrity_check()
        evidence["clone_integrity"] = True
        for _ in range(200):
            if companion.connected:
                break
            await asyncio.sleep(.05)
        evidence["head_unchanged"] = store.read_checkpoint(profile["player_id"], companion.session_epoch) == head
    finally:
        if companion is not None:
            await companion.close()
        await server.close()
        store.close()
        evidence["source_hashes_after"] = {name: sha(path) for name, path in sources.items()}
        evidence["sources_unchanged"] = evidence["source_hashes_after"] == before
        evidence["passed"] = bool(evidence.get("installed_current_head") and evidence.get("lease_blocked_while_running")
                                  and evidence.get("native_party_matches_current_head") and evidence.get("lease_released_after_close")
                                  and evidence.get("clone_integrity") and evidence.get("head_unchanged")
                                  and evidence.get("exit_code") == 0 and evidence["sources_unchanged"]
                                  and not evidence.get("close_timeout"))
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(evidence), flush=True)
    return 0 if evidence["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "database", "profile", "rom", "manifest", "save", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--profile-index", type=int, default=0)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
