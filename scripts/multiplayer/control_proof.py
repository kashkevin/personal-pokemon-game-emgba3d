"""Control two real ROM cores through joypad input and collect presence evidence.

Run in Ubuntu WSL with PYTHONPATH pointing at this project's src directory.
ROMs and copied saves must remain in the private multiplayer-proof directory.
JSON lines on stdin specify {keys_a, keys_b, frames, repeat, label}. Reads are
diagnostic; writes are performed only by the actual project Lua mailbox bridge.
This development tool is not the downloadable Windows player package.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
import json
from pathlib import Path
import secrets
import struct
import sys
import uuid

from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.mailbox import inspect_mailbox
from emerald_multiplayer.server import WorldServer, ServerConfig
from configure_bridge import configure


class Core:
    def __init__(self, process: asyncio.subprocess.Process, log: Path):
        self.process, self.log = process, log
        self.logs = asyncio.create_task(self._logs())

    async def _logs(self):
        with self.log.open("w", encoding="utf-8") as out:
            while line := await self.process.stderr.readline():
                out.write(line.decode(errors="replace"))
                out.flush()

    async def command(self, value: str) -> str:
        self.process.stdin.write((value + "\n").encode())
        await self.process.stdin.drain()
        result = await asyncio.wait_for(self.process.stdout.readline(), 20)
        if not result:
            raise RuntimeError(f"Core stopped unexpectedly; inspect {self.log}")
        text = result.decode().strip()
        if text.startswith("ERROR"):
            raise RuntimeError(text)
        if value.startswith("P ") and not text.startswith("PNG OK "):
            raise RuntimeError(f"Framebuffer capture failed: {text}")
        return text

    async def read(self, address: int, size: int) -> bytes:
        result = await self.command(f"R {address:x} {size}")
        return bytes.fromhex(result.split()[2])

    async def close(self):
        if self.process.returncode is None:
            with suppress(ConnectionError, asyncio.TimeoutError):
                await self.command("Q")
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                self.process.terminate()
                await self.process.wait()
        await self.logs


def objects(data: bytes) -> list[dict]:
    result = []
    for index in range(len(data) // 36):
        obj = data[index * 36:(index + 1) * 36]
        if obj[0] & 1:
            x, y = struct.unpack_from("<hh", obj, 16)
            result.append({"index": index, "local_id": obj[8], "map_number": obj[9],
                           "map_group": obj[10], "x": x - 7, "y": y - 7,
                           "sprite_id": obj[35], "invisible": bool(obj[1] & 32)})
    return result


async def run(args):
    manifest = json.loads(args.manifest.read_text())
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/":
        raise ValueError("Output must be inside the private multiplayer-proof directory")
    save_a, save_b = args.save_a.resolve(), args.save_b.resolve()
    if save_a == save_b or any("/multiplayer-proof/" not in str(p) for p in (save_a, save_b)):
        raise ValueError("Two different copied multiplayer-proof saves are required")
    root.mkdir(parents=True, exist_ok=True)
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"]))
    companions, cores = [], []
    configs, ipc_ports = [], []
    transcript = root / "actions.jsonl"
    await server.start(port=0)
    try:
        for name, save in (("a", save_a), ("b", save_b)):
            profile = root / f"identity-{name}.json"
            if not profile.exists():
                profile.write_text(json.dumps({"player_id": str(uuid.uuid4())}) + "\n")
            player_id = json.loads(profile.read_text())["player_id"]
            token = secrets.token_bytes(32)
            config = CompanionConfig(args.rom, args.manifest, player_id, f"Proof {name.upper()}",
                                     token, server_port=server.address[1], ipc_port=0)
            companion = Companion(config)
            await companion.start()
            ipc_ports.append(companion.ipc_address[1])
            configs.append(config)
            companions.append(companion)
            script = root / f"bridge-{name}.lua"
            script.write_text(configure(manifest, token.hex(), companion.ipc_address[1],
                                        args.bridge.read_text()), encoding="utf-8")
            process = await asyncio.create_subprocess_exec(str(args.harness), str(args.rom),
                str(save), str(script), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            core = Core(process, root / f"core-{name}.log")
            cores.append(core)
            ready = await asyncio.wait_for(process.stdout.readline(), 20)
            if not ready.startswith(b"READY"):
                raise RuntimeError(f"Core {name} failed Lua startup; inspect {core.log}")
        print(json.dumps({"ready": True, "output": str(root), "server": server.address}), flush=True)
        while line := await asyncio.to_thread(sys.stdin.readline):
            action = json.loads(line)
            if action.get("quit"):
                break
            frames, repeat = action.get("frames", 6), action.get("repeat", 1)
            per_core_frames = [action.get("frames_a", frames), action.get("frames_b", frames)]
            if any(type(f) is not int or not 0 <= f <= 60 for f in per_core_frames) or type(repeat) is not int or not 1 <= repeat <= 1000:
                raise ValueError("Actions require frames0..60 and repeat1..1000")
            keys = [action.get("keys_a", 0), action.get("keys_b", 0)]
            if any(type(k) is not int or not 0 <= k <= 1023 for k in keys):
                raise ValueError("Key masks must be GBA integers0..1023")
            if "close_companion" in action:
                target = action["close_companion"]
                if target not in (0, 1):
                    raise ValueError("Companion target must be0or1")
                await companions[target].close()
            if "rejoin_companion" in action:
                target = action["rejoin_companion"]
                if target not in (0, 1):
                    raise ValueError("Companion target must be0or1")
                # Reuse the loopback endpoint, character UUID, and private token.
                old = configs[target]
                from dataclasses import replace
                companions[target] = Companion(replace(old, ipc_port=ipc_ports[target]))
                await companions[target].start()
            for _ in range(repeat):
                await asyncio.gather(*(c.command(f"F {k:x} {f}")
                    for c, k, f in zip(cores, keys, per_core_frames) if f))
                await asyncio.sleep(0.02)
            result = {"action": action, "clients": []}
            for i, core in enumerate(cores):
                data = await core.read(manifest["mailbox_address"], 128)
                try:
                    pose, inbound = inspect_mailbox(data)
                    from dataclasses import asdict
                    item = {"pose": asdict(pose), "inbound": asdict(inbound)}
                except ValueError as error:
                    item = {"mailbox_pending": str(error)}
                item["server_connected"] = companions[i].connected
                item["session_epoch"] = companions[i].session_epoch
                if "debug_object_events_address" in manifest:
                    raw = await core.read(manifest["debug_object_events_address"], manifest["debug_object_events_size"])
                    item["objects"] = objects(raw)
                result["clients"].append(item)
            label = action.get("label")
            if label:
                if not isinstance(label, str) or not label.isascii() or not all(c.isalnum() or c in "-_" for c in label) or len(label) > 64:
                    raise ValueError("Screenshot label must be a short ASCII filename")
                for name, core in zip(("a", "b"), cores):
                    await core.command(f"P {root / (label + '-' + name + '.png')}")
            with transcript.open("a", encoding="utf-8") as out:
                out.write(json.dumps(result) + "\n")
            print(json.dumps(result), flush=True)
    finally:
        await asyncio.gather(*(c.close() for c in cores), return_exceptions=True)
        await asyncio.gather(*(c.close() for c in companions), return_exceptions=True)
        await server.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "manifest", "harness", "save-a", "save-b", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2] / "bridge/mgba.lua")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
