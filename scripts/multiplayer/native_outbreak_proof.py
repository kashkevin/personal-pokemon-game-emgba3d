"""Mass outbreaks (EmeraldTogether Phase 4) in two native games: a real world
server, real companions and two native game clients on Route 101.

The host starts an outbreak on Route 101 (the scheduler's own start, with the
map and species named instead of drawn), and the proof checks from the host,
the companions and the games' own spawn records ('g' frames: the spawn objects
each game draws, with their tiles):

  1. both games draw the host's Pokemon on the same tiles before the outbreak;
  2. the outbreak's notice reaches both games ("MASS OUTBREAK: ...");
  3. Route 101's board allows 12 Pokemon instead of 8 and fills past 8, most
     new ones the outbreak species (kind "outbreak");
  4. both games draw outbreak Pokemon, the same spawn ids on the host's tiles,
     no spawn id twice;
  5. the host ends it: the "has ended" notice reaches both games, the board is
     back to at most 8 (SpawnBoard.trim: open outbreak Pokemon first, the
     oldest first; claimed ones kept), and both games stop drawing the removed
     ones and draw the same remaining Pokemon as the host.

A notice reaching a companion is not yet a notice on the screen: the game shows
it once its overworld is calm (no script, menu or map-name pop-up; on software
OpenGL the pop-up after loading can last half a minute), for 360 frames, as the
native UI's toast. The games run with PKMN_NATIVE_UI_LOG=1, so each logs when
its notice toast comes up ("screen ... -> notice"); the proof screenshots the
game at that moment and checks the toast's fill colour is on screen. The ROM's
own one-time hint ("Make your own TRAINER look") is a notice too: the proof
lets it come and go before the outbreak, so the toasts after it are the host's.

Each client runs on its own X display (xdotool key presses for the title
screen only). With --wine (one prefix per client) the Windows executable runs
under Wine.

    PYTHONPATH=src python scripts/multiplayer/native_outbreak_proof.py \\
        --game ../engine/pokeemerald-mp-diorama --rom ../engine/pokeemerald.gba \\
        --manifest manifest.json --save route101.sav --display :98 --display :97 \\
        --output /private/multiplayer-proof/native-outbreak-1
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
from uuid import uuid4

from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.shared_spawns import KIND_OUTBREAK, NORMAL_SLOT_LIMIT, OUTBREAK_SLOT_LIMIT

from PIL import Image

from native_spawn_proof import _hold, _screenshot

ROUTE101 = "0.16"
OUTBREAK_SPECIES = 265  # Wurmple: one of Route 101's own species
TOAST_FILL = (248, 240, 216)  # the native UI's notice toast (ui_notice.c, UI_P_CREAM)


def _toast_pixels(path: Path) -> int:
    """Pixels of the toast's fill colour in the upper half of the game window."""
    image = Image.open(path).convert("RGB")
    x0, y0, x1, y1 = image.getbbox()
    return sum(1 for p in image.crop((x0, y0, x1, (y0 + y1) // 2)).getdata() if p == TOAST_FILL)


def _toasts_logged(log: Path) -> tuple[int, bool]:
    """How many times the game's notice toast came up, and whether it is up now
    (the native UI's screen log)."""
    count, up = 0, False
    for line in log.read_text(errors="replace").splitlines():
        if line.startswith("INFO: Native UI: screen "):
            to_notice = line.endswith("-> notice")
            count += to_notice
            up = to_notice
    return count, up


async def run(args: argparse.Namespace) -> None:
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    if len(args.display) != 2:
        raise ValueError("two X displays, one per client")
    root.mkdir(mode=0o700, parents=True)
    manifest = json.loads(args.manifest.read_text())
    if hashlib.sha256(args.rom.read_bytes()).hexdigest() != manifest["rom_sha256"]:
        raise ValueError("ROM differs from its manifest")
    game = args.game.resolve()
    evidence = dict(scope="mass outbreaks: a real world server, real companions, two native clients",
                    game_sha256=hashlib.sha256(game.read_bytes()).hexdigest(), build_id=manifest["rom_sha256"],
                    species=OUTBREAK_SPECIES, checks=[], passed=False)

    def record(name: str, **fields) -> None:
        row = dict(verified=name, **fields)
        evidence["checks"].append(row)
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(row), flush=True)

    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"],
                                      heartbeat_interval=.2, idle_timeout=12), store=None)
    await server.start(port=0)
    world = server.shared_world
    if world.outbreaks is None:
        raise AssertionError("the world has no outbreak scheduler (no spawn catalogue)")
    companions: list[Companion] = []
    processes: list[subprocess.Popen] = []
    try:
        for i, display in enumerate(args.display):
            copy = root / f"client-{i}.sav"
            shutil.copyfile(args.save, copy)
            copy.chmod(0o600)
            companion = Companion(CompanionConfig(args.rom, args.manifest, str(uuid4()), f"Native {'AB'[i]}",
                                                  secrets.token_bytes(32), server_port=server.address[1], ipc_port=0))
            await companion.start()
            companions.append(companion)
            bridge = root / f"bridge-{i}.txt"
            bridge.write_text(f"port={companion.ipc_address[1]}\ntoken={companion.config.token.hex()}\n")
            bridge.chmod(0o600)
            log = (root / f"client-{i}.log").open("wb")
            command = [str(game), "--save", str(copy), "--bridge", str(bridge)]
            environment = dict(os.environ, DISPLAY=display, SDL_AUDIODRIVER="dummy", PKMN_NATIVE_UI_LOG="1")
            if args.wine:
                command = ["wine"] + command
                environment.update(WINEPREFIX=str(args.wine[i % len(args.wine)]), WINEDEBUG="-all")
            processes.append(subprocess.Popen(command, cwd=root, env=environment, stdout=log,
                                              stderr=subprocess.STDOUT))
        loop = asyncio.get_running_loop()

        async def shots(tag: str) -> None:
            for i, display in enumerate(args.display):
                await asyncio.to_thread(_screenshot, display, root / f"{tag}-{i}.png")

        async def wait_for(name: str, condition, timeout: float, **fields) -> None:
            deadline = loop.time() + timeout
            while not condition():
                if any(p.poll() is not None for p in processes):
                    raise AssertionError(f"{name}: a client exited ({[p.poll() for p in processes]})")
                if loop.time() >= deadline:
                    await shots("timeout")
                    raise AssertionError(f"{name}: timed out; " + json.dumps(
                        {k: (v() if callable(v) else v) for k, v in fields.items()}, default=str))
                await asyncio.sleep(.25)
            record(name, **{k: (v() if callable(v) else v) for k, v in fields.items()})

        async def press(key: str, seconds: float = .2, clients=(0, 1)) -> None:
            await asyncio.gather(*(asyncio.to_thread(_hold, args.display[i], key, seconds) for i in clients))

        def in_overworld(i: int) -> bool:
            pose = companions[i]._local_pose
            return pose is not None and pose.activity == 1

        def shown_list(i: int) -> list[tuple[int, int, int]]:
            local = companions[i]._local_spawn
            if local is None or (local.map_group, local.map_number) != (0, 16):
                return []
            return list(local.shown)

        def shown(i: int) -> dict[int, tuple[int, int]]:
            return {spawn_id: (x, y) for spawn_id, x, y in shown_list(i)}

        def board():
            return world.spawn_boards.existing(ROUTE101)

        def host_slots() -> dict[int, tuple[int, int]]:
            b = board()
            return {} if b is None else {s.spawn_id: (s.x, s.y) for s in b.live()}

        def host_kinds() -> dict[int, str]:
            b = board()
            return {} if b is None else {s.spawn_id: f"{s.kind}:{s.species}" for s in b.live()}

        def notice_text(i: int) -> str:
            notice = companions[i]._world_notice
            return "" if notice is None else notice["text"]

        logs = [root / f"client-{i}.log" for i in range(2)]

        async def toast_on_screen(tag: str, before: list[int], timeout: float) -> list:
            """Wait until each game logs a new notice toast, screenshot it then and
            check the toast's colour is on screen."""
            seen: list[dict | None] = [None, None]
            deadline = loop.time() + timeout
            while None in seen and loop.time() < deadline:
                for i, display in enumerate(args.display):
                    count, up = _toasts_logged(logs[i])
                    if seen[i] is None and count > before[i] and up:
                        # it slides in over its first frames (seconds on a slow game)
                        path = root / f"{tag}-{i}.png"
                        for _ in range(20):
                            await asyncio.to_thread(_screenshot, display, path)
                            pixels = _toast_pixels(path)
                            if pixels >= 1000 or not _toasts_logged(logs[i])[1]:
                                break
                            await asyncio.sleep(.5)
                        seen[i] = dict(toast=count, fill_pixels=pixels)
                await asyncio.sleep(.2)
            if None in seen:
                await shots("timeout")
                raise AssertionError(f"{tag}: no new notice toast within {timeout:.0f} s ({seen})")
            if any(s["fill_pixels"] < 1000 for s in seen):
                raise AssertionError(f"{tag}: a toast was logged but its colour is not on screen ({seen})")
            return seen

        def drawn_by_both_like_the_host(minimum: int = 2) -> bool:
            host = host_slots()
            a, b = shown(0), shown(1)
            common = set(a) & set(b)
            return (len(common) >= minimum and all(a[s] == b[s] for s in common)
                    and all(s in host and host[s] == a[s] for s in common))

        def no_spawn_drawn_twice() -> bool:
            return all(len({s for s, _, _ in shown_list(i)}) == len(shown_list(i)) for i in range(2))

        await wait_for("native bridges authenticated to their companions",
                       lambda: all(c._bridge is not None for c in companions), 90)
        await wait_for("both native games announced the shared-spawn mailbox ('w')",
                       lambda: all(c._bridge is not None and c._bridge.spawn_capable for c in companions), 60)
        await wait_for("companions joined the world server",
                       lambda: all(c.connected for c in companions) and len(server.sessions) == 2, 30)

        await asyncio.sleep(12 * args.slow)
        await press("Return")
        await asyncio.sleep(5 * args.slow)
        await press("Return")
        await asyncio.sleep(12 * args.slow)
        await press("z")
        for _ in range(12):
            waiting = [i for i in range(2) if not in_overworld(i)]
            if not waiting:
                break
            await asyncio.sleep(5)
            waiting = [i for i in range(2) if not in_overworld(i)]
            if waiting:
                await press("z", clients=waiting)
        await wait_for("both games are on Route 101's overworld",
                       lambda: all(in_overworld(i) for i in range(2))
                       and all((c._local_pose.map_group, c._local_pose.map_number) == (0, 16) for c in companions), 30,
                       poses=lambda: [(c._local_pose.map_group, c._local_pose.map_number, c._local_pose.x,
                                       c._local_pose.y, c._local_pose.direction) for c in companions])
        await wait_for("the host made shared spawns active for both games (inbound 'enabled')",
                       lambda: all(c.spawn_inbound().enabled for c in companions), 30)

        # 1. Before the outbreak: the usual 8 at most, drawn alike.
        await wait_for("before the outbreak both games draw the host's Pokemon on the same tiles",
                       drawn_by_both_like_the_host, 90 * args.slow, host=host_slots, kinds=host_kinds,
                       client_a=lambda: shown(0), client_b=lambda: shown(1),
                       limit=lambda: board().limit())
        if board().limit() != NORMAL_SLOT_LIMIT or board().live_count() > NORMAL_SLOT_LIMIT:
            raise AssertionError(f"before the outbreak the board allows {board().limit()}, holds {board().live_count()}")
        await shots("01-before")
        # The ROM's one-time hint (a notice too) comes and goes first.
        hint_shots: list[dict | None] = [None, None]
        deadline = loop.time() + 300 * args.slow
        while loop.time() < deadline:
            states = [_toasts_logged(log) for log in logs]
            for i, (count, up) in enumerate(states):
                if up and hint_shots[i] is None:
                    path = root / f"01-hint-{i}.png"
                    for _ in range(20):
                        await asyncio.to_thread(_screenshot, args.display[i], path)
                        pixels = _toast_pixels(path)
                        if pixels >= 1000 or not _toasts_logged(logs[i])[1]:
                            break
                        await asyncio.sleep(.5)
                    hint_shots[i] = dict(toast=count, fill_pixels=pixels)
            if all(count >= 1 and not up for count, up in states):
                break
            await asyncio.sleep(.25)
        record("the ROM's one-time hint toast came and went before the outbreak (pictures 01-hint-*)",
               toasts=[_toasts_logged(log) for log in logs], pictures=hint_shots)

        # 2. The outbreak starts (the scheduler's start with the map and species
        # named) and its notice reaches both games.
        before = [_toasts_logged(log)[0] for log in logs]
        view = world.outbreaks.start(10, map_key=ROUTE101, species=OUTBREAK_SPECIES)
        if view is None:
            raise AssertionError("the scheduler refused to start the outbreak")
        world.save_spawns()
        server._broadcast_world()
        record("the host started an outbreak on Route 101", outbreak=view)
        await wait_for("the outbreak's notice reached both companions (the world notice the games show)",
                       lambda: all(notice_text(i).startswith("MASS OUTBREAK") for i in range(2)), 20,
                       notices=lambda: [notice_text(i) for i in range(2)])
        shown_toasts = await toast_on_screen("02-notice", before, 120 * args.slow)
        record("both games show the outbreak notice toast (pictures 02-notice-*)", toasts=shown_toasts)

        # 3. The board allows 12 and fills past 8, most new ones the outbreak's.
        await wait_for("Route 101 allows 12 Pokemon and holds more than 8 during the outbreak",
                       lambda: board().limit() == OUTBREAK_SLOT_LIMIT and board().live_count() > NORMAL_SLOT_LIMIT,
                       150 * args.slow, live=lambda: board().live_count(), kinds=host_kinds)
        outbreak_ids = {s for s, kind in host_kinds().items() if kind.startswith(KIND_OUTBREAK)}
        if not outbreak_ids:
            raise AssertionError(f"no outbreak Pokemon on the board: {host_kinds()}")

        # 4. Both games draw outbreak Pokemon, alike, none twice.
        def outbreak_drawn_by_both() -> bool:
            host_out = {s for s, kind in host_kinds().items() if kind.startswith(KIND_OUTBREAK)}
            a, b = shown(0), shown(1)
            return (drawn_by_both_like_the_host(3) and bool(host_out & set(a) & set(b))
                    and no_spawn_drawn_twice())

        await wait_for("both games draw outbreak Pokemon: the same spawn ids on the host's tiles, none twice",
                       outbreak_drawn_by_both, 120 * args.slow, host=host_slots, kinds=host_kinds,
                       client_a=lambda: shown(0), client_b=lambda: shown(1))
        await asyncio.sleep(1.5)
        await shots("03-outbreak")
        during = dict(host_slots())
        record("during the outbreak", host=during, kinds=host_kinds(), client_a=shown(0), client_b=shown(1))

        # 5. The host ends it: back to 8, the removed ones gone from both games.
        # (First the start's toast goes: a notice arriving while another is up
        # replaces its text in the same toast, which the screen log cannot tell.)
        await wait_for("the outbreak's toast is gone in both games", lambda: not any(_toasts_logged(log)[1] for log in logs),
                       240 * args.slow, toasts=lambda: [_toasts_logged(log) for log in logs])
        before = [_toasts_logged(log)[0] for log in logs]
        ended = world.outbreaks.end()
        world.save_spawns()
        server._broadcast_world()
        after = dict(host_slots())
        removed = sorted(set(during) - set(after))
        record("the host ended the outbreak", ended=ended["outbreak_id"] if ended else None,
               live=len(after), limit=board().limit(), removed=removed)
        if board().limit() != NORMAL_SLOT_LIMIT or len(after) > NORMAL_SLOT_LIMIT:
            raise AssertionError(f"after the end the board allows {board().limit()} and holds {len(after)}")
        await wait_for("the end notice reached both companions",
                       lambda: all("has ended" in notice_text(i) for i in range(2)), 20,
                       notices=lambda: [notice_text(i) for i in range(2)])
        shown_toasts = await toast_on_screen("04-end-notice", before, 120 * args.slow)
        record("both games show the end notice toast (pictures 04-end-notice-*)", toasts=shown_toasts)
        await wait_for("both games stopped drawing the removed Pokemon and draw the host's, none twice",
                       lambda: not (set(removed) & (set(shown(0)) | set(shown(1)))) and drawn_by_both_like_the_host(1)
                       and no_spawn_drawn_twice() and board().live_count() <= NORMAL_SLOT_LIMIT,
                       60 * args.slow, host=host_slots, client_a=lambda: shown(0), client_b=lambda: shown(1),
                       live=lambda: board().live_count())
        await asyncio.sleep(1.5)
        await shots("04-ended")
        await asyncio.sleep(10 * args.slow)
        record("ten seconds later the board still holds at most 8", live=board().live_count(), limit=board().limit(),
               kinds=host_kinds())
        if board().live_count() > NORMAL_SLOT_LIMIT:
            raise AssertionError("the board grew past 8 after the outbreak ended")
        evidence["passed"] = True
        record("passed")
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
        for companion in companions:
            await companion.close()
        await server.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="native executable built with the bridge")
    parser.add_argument("--rom", type=Path, required=True, help="GBA ROM of the same engine commit")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--save", type=Path, required=True, help="a test save standing on Route 101")
    parser.add_argument("--display", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.5, help="stretch the waits (3D build on software OpenGL)")
    parser.add_argument("--wine", type=Path, action="append",
                        help="Wine prefix, one per client: run the Windows executable under Wine")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
