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
import hashlib
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
        if size > 4096:
            return b"".join([await self.read(address + start, min(4096, size - start))
                             for start in range(0, size, 4096)])
        result = await self.command(f"R {address:x} {size}")
        return bytes.fromhex(result.split()[2])

    async def close(self):
        if self.process.returncode is None:
            with suppress(ConnectionError, asyncio.TimeoutError, RuntimeError):
                await self.command("Q")
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                self.process.terminate()
                await self.process.wait()
        await self.logs


def objects(data: bytes, sprites: bytes | None = None) -> list[dict]:
    result = []
    for index in range(len(data) // 36):
        obj = data[index * 36:(index + 1) * 36]
        if obj[0] & 1:
            x, y = struct.unpack_from("<hh", obj, 16)
            item = {"index": index, "local_id": obj[8], "map_number": obj[9],
                           "map_group": obj[10], "x": x - 7, "y": y - 7,
                           "sprite_id": obj[35], "invisible": bool(obj[1] & 32)}
            if sprites is not None and obj[35] * 68 + 68 <= len(sprites):
                sprite = sprites[obj[35] * 68:(obj[35] + 1) * 68]
                sx, sy, sx2, sy2 = struct.unpack_from("<hhhh", sprite, 32)
                item.update(sprite_x=sx, sprite_y=sy, sprite_x2=sx2, sprite_y2=sy2,
                            sprite_active=bool(sprite[62] & 1),
                            sprite_invisible=bool(sprite[62] & 4), animation=sprite[42])
            result.append(item)
    return result


def verify_expected(result: dict, expected: dict) -> None:
    clients = result["clients"]
    if "remotes" in expected:
        actual = [sum(241 <= obj["local_id"] <= 243 for obj in c.get("objects", [])) for c in clients]
        assert actual == expected["remotes"], f"Remote actor counts {actual} != {expected['remotes']}"
    if "activity" in expected:
        actual = [c.get("pose", {}).get("activity") for c in clients]
        assert actual == expected["activity"], f"Game activities {actual} != {expected['activity']}"
    if "same_map" in expected:
        actual = [(c.get("pose", {}).get("map_group"), c.get("pose", {}).get("map_number")) for c in clients]
        assert (actual[0] == actual[1]) == expected["same_map"], f"Map identities {actual}"
    if expected.get("peer_positions_match"):
        for i, client in enumerate(clients):
            other = clients[1 - i]["pose"]
            remote = [obj for obj in client.get("objects", []) if 241 <= obj["local_id"] <= 243]
            assert len(remote) == 1, "Expected one actual remote object"
            assert (remote[0]["x"], remote[0]["y"]) == (other["x"], other["y"]), "Remote coordinates did not settle"
            assert (remote[0].get("sprite_active") and not remote[0]["invisible"]
                    and not remote[0].get("sprite_invisible")), "Remote sprite is not visible"
    if "coordinates" in expected:
        actual = [[c["pose"]["x"], c["pose"]["y"]] for c in clients]
        assert actual == expected["coordinates"], f"Local coordinates {actual}"
    if "connected" in expected:
        assert [c["server_connected"] for c in clients] == expected["connected"]
    if expected.get("saved_remote_ids_empty"):
        for client in clients:
            assert not any(241 <= value <= 243 for value in client["saved_object_local_ids"])
    if "party_sha256" in expected:
        assert [c["party_sha256"] for c in clients] == expected["party_sha256"]
    if expected.get("peer_pixels_match"):
        for i, client in enumerate(clients):
            local = client["pose"]
            other = clients[1 - i]["pose"]
            player = next(o for o in client["objects"] if o["local_id"] == 255)
            remote = next(o for o in client["objects"] if 241 <= o["local_id"] <= 243)
            # Same walking graphics, settled steps: shared camera offsets cancel.
            for axis in ("x", "y"):
                expected_delta = (other[axis] - local[axis]) * 16
                actual_delta = (remote["sprite_" + axis] + remote["sprite_" + axis + "2"]
                                - player["sprite_" + axis] - player["sprite_" + axis + "2"])
                assert actual_delta == expected_delta, f"Peer pixel {axis} delta {actual_delta} != {expected_delta}"


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
    server_port = server.address[1]
    server_running = True
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
            if action.get("stop_server"):
                if not server_running:
                    raise ValueError("Server is already stopped")
                await server.close()
                server_running = False
            if action.get("start_server"):
                if server_running:
                    raise ValueError("Server is already running")
                candidate = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"]))
                await candidate.start(port=server_port)
                server, server_running = candidate, True
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
                    pose, inbound = inspect_mailbox(
                        data, presentation_version=manifest.get("presence_animation_abi_version", 0))
                    from dataclasses import asdict
                    item = {"pose": asdict(pose), "inbound": asdict(inbound)}
                except ValueError as error:
                    item = {"mailbox_pending": str(error)}
                item["server_connected"] = companions[i].connected
                item["session_epoch"] = companions[i].session_epoch
                if "debug_object_events_address" in manifest:
                    raw = await core.read(manifest["debug_object_events_address"], manifest["debug_object_events_size"])
                    sprites = None
                    if "debug_sprites_address" in manifest:
                        sprites = await core.read(manifest["debug_sprites_address"], manifest["debug_sprites_size"])
                    item["objects"] = objects(raw, sprites)
                if "debug_parties_address" in manifest:
                    party = await core.read(manifest["debug_parties_address"], manifest["debug_party_size"])
                    item["party_sha256"] = hashlib.sha256(party).hexdigest()
                    item["party_hex"] = party.hex()
                    item["party_count"] = (await core.read(manifest["debug_party_counts_address"], 1))[0]
                    save_block = int.from_bytes(await core.read(manifest["debug_save_block1_ptr_address"], 4), "little")
                    if 0x02000000 <= save_block <= 0x02040000 - 0x3CD0:
                        saved = await core.read(save_block + manifest["debug_saved_objects_offset"], 16 * 36)
                        item["saved_object_local_ids"] = [saved[j * 36 + 8] for j in range(16)]
                        item["saved_party_count"] = (await core.read(save_block + manifest["debug_saved_party_count_offset"], 1))[0]
                        saved_party = await core.read(save_block + manifest["debug_saved_party_offset"], manifest["debug_party_size"])
                        item["saved_party_sha256"] = hashlib.sha256(saved_party).hexdigest()
                result["clients"].append(item)
            label = action.get("label")
            if label:
                if not isinstance(label, str) or not label.isascii() or not all(c.isalnum() or c in "-_" for c in label) or len(label) > 64:
                    raise ValueError("Screenshot label must be a short ASCII filename")
                for name, core in zip(("a", "b"), cores):
                    await core.command(f"P {root / (label + '-' + name + '.png')}")
            with transcript.open("a", encoding="utf-8") as out:
                out.write(json.dumps(result) + "\n")
            print(json.dumps({"label": label, "clients": [
                {"pose": c.get("pose"), "server_connected": c["server_connected"],
                 "session_epoch": c["session_epoch"],
                 "party_count": c.get("party_count"), "party_sha256": c.get("party_sha256"),
                 "saved_object_local_ids": c.get("saved_object_local_ids"),
                 "remotes": [o for o in c.get("objects", []) if 241 <= o["local_id"] <= 243]}
                for c in result["clients"]]}), flush=True)
            if "expected" in action:
                verify_expected(result, action["expected"])
                print(json.dumps({"verified": True, "label": label}), flush=True)
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
