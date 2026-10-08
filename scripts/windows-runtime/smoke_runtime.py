"""Run a copied ROM/save in the native SDL frontend with a loopback bridge.

This checks frontend startup and transient presence only. It does not enroll,
restore a canonical checkpoint, or qualify a player launcher. Close the game
window normally after inspecting it; copied files and logs remain private.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import subprocess
from uuid import uuid4

from emerald_multiplayer.bridge_config import configure
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.server import ServerConfig, WorldServer


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = dict(rom=sha(args.rom), save=sha(args.save))
    rom, save, manifest = output / "game.gba", output / "character.sav", output / "manifest.json"
    shutil.copyfile(args.rom, rom)
    shutil.copyfile(args.save, save)
    shutil.copyfile(args.manifest, manifest)
    cfg = CompanionConfig(rom, manifest, str(uuid4()), "Windows smoke", secrets.token_bytes(32), ipc_port=0)
    server = WorldServer(ServerConfig(cfg.build_id, cfg.ruleset_id))
    await server.start(port=0)
    cfg = CompanionConfig(rom, manifest, cfg.player_id, cfg.display_name, cfg.token,
                          server_port=server.address[1], ipc_port=0)
    companion = Companion(cfg)
    process = None
    evidence = dict(source_hashes=before, rom_hash=sha(rom), native_frontend=str(args.executable.resolve()),
                    frontend_hash=sha(args.executable), transient_presence_only=True)
    try:
        await companion.start()
        rom_manifest = json.loads(manifest.read_text())
        bridge = configure(rom_manifest, cfg.token.hex(), companion.ipc_address[1],
                           args.bridge.read_text())
        evidence["scripted_joypad"] = args.scripted_start
        if args.scripted_start:
            # Test-only ordinary GBA button inputs; this does not write RAM,
            # inject a state, bypass Continue, or test Windows keyboard events.
            bridge += '\nlocal startPlan={{0,1000},{8,8},{0,480},{8,8},{0,180},{1,8},{0,300}}\n' \
                      'local startStep,startRemaining=1,1000\n' \
                      'callbacks:add("frame",function()\n' \
                      'if startStep<=#startPlan then\n' \
                      'emu:setKeys(startPlan[startStep][1])\nstartRemaining=startRemaining-1\n' \
                      'if startRemaining==0 then startStep=startStep+1\n' \
                      'if startStep<=#startPlan then startRemaining=startPlan[startStep][2]\n' \
                      'else emu:setKeys(0);console:log("RUNTIME_SMOKE scripted Continue completed") end\nend\nend\nend)\n'
            if "debug_party_counts_address" in rom_manifest:
                bridge += '\ncallbacks:add("frame",function()\nif emu:currentFrame()%120==0 then\n' \
                          f'console:log("RUNTIME_SMOKE party_count="..emu:read8({rom_manifest["debug_party_counts_address"]}))\n' \
                          'end\nend)\n'
        bridge += '\nlocal smokeFrames=0\ncallbacks:add("frame", function()\n' \
                  'smokeFrames=smokeFrames+1\nif smokeFrames%120==0 then\n' \
                  'console:log("RUNTIME_SMOKE frame="..smokeFrames.." keys="..emu:getKeys())\nend\nend)\n'
        script = output / "bridge.lua"
        script.write_text(bridge)
        with (output / "frontend.log").open("xb") as log:
            process = await asyncio.create_subprocess_exec(
                str(args.executable.resolve()), "-2", "-l", "15", "--multiplayer-script", str(script),
                "--multiplayer-save", str(save), str(rom), cwd=output,
                stdout=log, stderr=log, stdin=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            evidence["pid"] = process.pid
            print(json.dumps(dict(pid=process.pid, output=str(output))), flush=True)
            for _ in range(1200):
                if process.returncode is not None:
                    break
                if companion._bridge is not None and companion._local_pose is not None:
                    evidence["bridge_connected"] = True
                    evidence["presence_received"] = True
                    evidence["initial_pose"] = companion._local_pose.__dict__
                    print("Native Lua bridge and ROM presence received; inspect/close the game window.", flush=True)
                    break
                await asyncio.sleep(0.05)
            try:
                evidence["exit_code"] = await asyncio.wait_for(process.wait(), 180)
            except asyncio.TimeoutError:
                evidence["close_timeout"] = True
                process.terminate()
                evidence["exit_code"] = await process.wait()
    finally:
        if process is not None and process.returncode is None:
            process.terminate()
            await process.wait()
        await companion.close()
        await server.close()
        evidence["source_hashes_after"] = dict(rom=sha(args.rom), save=sha(args.save))
        evidence["source_unchanged"] = evidence["source_hashes_after"] == before
        evidence["copied_save_hash_after"] = sha(save)
        evidence["passed"] = bool(evidence.get("bridge_connected") and evidence.get("presence_received")
                                  and evidence.get("exit_code") == 0 and evidence["source_unchanged"]
                                  and not evidence.get("close_timeout"))
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(evidence), flush=True)
    return 0 if evidence["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("executable", "bridge", "rom", "manifest", "save", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--scripted-start", action="store_true",
                        help="proof-only ordinary Start/A joypad sequence through native Continue")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
