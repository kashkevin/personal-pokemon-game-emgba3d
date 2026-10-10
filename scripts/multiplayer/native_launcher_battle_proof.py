"""The real launcher with native games: host and friend battle 1v1 from the Players menu.

qualify_menu_battle.py (Windows, mGBA) on the native PC build, in the cloud
workspace: the real `LauncherWindow`, `SessionWorker` and `LauncherSession`,
production world creation, host enrollment and friend invitation, and a native
runtime bundle, so every game is the native executable the launcher starts (no
emulator, no Lua). Both players use the ordinary invite, consent and Enter of
the Players menu; the battle runs on the host's battle service and both games.

What differs from the Windows qualifier, and why:
  - The games are the Linux native executable (non-PIE, unstripped): the
    bundle names it `pokeemerald-mp.exe` and pins a placeholder SDL2.dll (the
    Linux game links the system's SDL), so the launcher's own bundle checks run.
  - Keys go to each game's own window (xdotool; each player's games on their
    own Xvfb display, as the other native proofs do, so two players' key
    presses never share a keyboard focus), where the Windows qualifier's Lua
    appendix pressed emulated buttons; the title screen and Continue are
    pressed the same way. The harness picks the display a game opens on
    through the environment the launcher's child inherits.
  - What is on screen (menus, tasks, the party menu, parties) is read from the
    games' memory (`/proc/PID/mem` at `nm` symbols), never written; the
    Windows qualifier read the same symbols through Lua. The party the closed
    game held is read before it closes instead of from a Lua log line.
  - "Normal close" is SIGTERM, which SDL turns into an ordinary quit (exit 0).

Steps: both sources enrolled by the launcher's host enrollment (each bootstrap
game closes itself); the friend's invitation exported; host and friend
launchers start their games, which Continue into the overworld; A challenges B
to 1v1, B accepts, both press Enter battle; default moves (A) until the
battle ends; both launchers report battle_finished, the durable result is the
same for both, each player's full personal party is back, and each game's
"Recent battle results" shows it; both save (revision 2); both games close
normally; fresh launchers Continue onto the same canonical saves; the store
passes its integrity check.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_battle_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source-a a.sav --source-b b.sav --display :98 --display :97 \\
        --output /private/multiplayer-proof/native-launcher-battle-1
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import traceback
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from collect_native_bundle import collect  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402
from qualify_launcher_session import inspect_closed_head, output_event  # noqa: E402
from qualify_live_runtime import field_ready, lease_is_owned, party, sha  # noqa: E402
from qualify_menu_battle import party_action  # noqa: E402
from emerald_multiplayer.checkpoint_mirror import MirrorLease  # noqa: E402
from emerald_multiplayer.launcher_gui import LaunchRequest, LauncherWindow, SessionWorker  # noqa: E402
from emerald_multiplayer.launcher_session import GameInstallation  # noqa: E402
from emerald_multiplayer.launcher_setup import create_world, export_friend_invitation, host_enrollment  # noqa: E402
from emerald_multiplayer.menu_mailbox import unpack_screen  # noqa: E402

KEYS = {1: "z", 2: "x", 8: "Return", 128: "Down"}
PLAYER_OPTIONS, TRAINER_CARD, PLAYERS = 15, 16, 17
PARTY_TASKS = ("Task_HandleChooseMonInput", "Task_HandleSelectionMenuInput", "Task_PrintAndWaitForText")
NEEDED = ("sMultiplayerMenuActive", "sMultiplayerMenuWaiting", "sMultiplayerMenuCursor", "sMultiplayerMenuScreen",
          "sCurrentStartMenuActions", "sNumStartMenuActions", "sStartMenuCursorPos", "gMultiplayerBattleHoldFlags",
          "gMultiplayerBattleMailbox", "gTasks", "gPartyMenu", "gParties", "gPartiesCount", *PARTY_TASKS)


def symbols_of(game):
    rows = subprocess.run(["nm", "-S", str(game)], capture_output=True, text=True, check=True).stdout
    symbols = {}
    for line in rows.splitlines():
        row = line.split()
        if len(row) == 4:
            symbols[row[3]] = (int(row[0], 16), int(row[1], 16))
    return symbols


class NativeProbe:
    """One launcher-started native game: keys to its window, reads of its memory."""

    def __init__(self, pid, symbols, display, record, *, hold=.15, gap=.2):
        self.pid, self.symbols, self.display, self.record = pid, symbols, display, record
        self.hold, self.gap, self.presses = hold, gap, 0
        self.environment = dict(os.environ, DISPLAY=display)

    def mem(self, name, size=None, offset=0):
        address, length = self.symbols[name]
        with open(f"/proc/{self.pid}/mem", "rb", buffering=0) as memory:
            memory.seek(address + offset)
            return memory.read(length if size is None else size)

    def read(self):
        count = self.mem("sNumStartMenuActions")[0]
        return dict(frame=time.monotonic(), active=self.mem("sMultiplayerMenuActive")[0],
                    waiting=self.mem("sMultiplayerMenuWaiting")[0], cursor=self.mem("sMultiplayerMenuCursor")[0],
                    count=count, start_cursor=self.mem("sStartMenuCursorPos")[0],
                    hold=int.from_bytes(self.mem("gMultiplayerBattleHoldFlags"), "little"),
                    actions=list(self.mem("sCurrentStartMenuActions")), screen=self.mem("sMultiplayerMenuScreen"))

    async def snapshot(self, predicate=lambda row: True, timeout=15):
        async with asyncio.timeout(timeout):
            while True:
                row = self.read()
                if predicate(row):
                    return row
                await asyncio.sleep(.03)

    def _window(self):
        found = subprocess.run(["xdotool", "search", "--pid", str(self.pid)], env=self.environment,
                               capture_output=True, text=True).stdout.split()
        for window in reversed(found):
            if subprocess.run(["xdotool", "windowfocus", "--sync", window], env=self.environment,
                              capture_output=True).returncode == 0:
                return window
        raise RuntimeError(f"no window of native game {self.pid}")

    def _press(self, key, seconds):
        self._window()
        subprocess.run(["xdotool", "keydown", key], env=self.environment, check=True)
        time.sleep(seconds)
        subprocess.run(["xdotool", "keyup", key], env=self.environment, check=True)

    async def press(self, key, frames=12, release=24):
        await asyncio.to_thread(self._press, KEYS[key], max(self.hold, frames / 60))
        await asyncio.sleep(max(self.gap, release / 60))
        self.presses += 1
        self.record("ordinary-input", pid=self.pid, key=KEYS[key], quiet=True)
        return self.read()

    async def ready(self, timeout=15):
        async with asyncio.timeout(timeout):
            while True:
                row = self.read()
                if row["active"] and not row["waiting"]:
                    try:
                        return row, unpack_screen(row["screen"], allow_battle_admission=True)[1]
                    except ValueError:
                        pass  # a screen being copied in
                await asyncio.sleep(.03)

    async def choose(self, label, *, wait=True, prefix=False):
        row, screen = await self.ready()
        indices = [n for n, item in enumerate(screen.rows) if item.action
                   and (item.label == label or (prefix and item.label.startswith(label + " ")))]
        require(len(indices) == 1, f"expected one displayed choice {label!r}: {[r.label for r in screen.rows]}")
        for _ in range((indices[0] - row["cursor"]) % len(screen.rows)):
            await self.press(128)
        require(self.read()["cursor"] == indices[0], f"cursor did not reach {label!r}")
        await self.press(1)
        if wait:
            return await self.ready()

    async def open_players(self):
        await self.press(8, release=60)
        row = await self.snapshot(lambda r: 0 < r["count"] <= len(r["actions"]) and PLAYER_OPTIONS in r["actions"][:r["count"]])
        target = row["actions"][:row["count"]].index(PLAYER_OPTIONS)
        for _ in range((target - row["start_cursor"]) % row["count"]):
            await self.press(128)
        await self.press(1, release=60)
        # This build's Player submenu: Trainer Card, Players, Style, Back.
        row = await self.snapshot(lambda r: r["actions"][0] == TRAINER_CARD and PLAYERS in r["actions"][:r["count"]])
        target = row["actions"][:row["count"]].index(PLAYERS)
        for _ in range((target - row["start_cursor"]) % row["count"]):
            await self.press(128)
        await self.press(1)
        _, screen = await self.ready()
        if screen.back:
            await self.press(2)
            _, screen = await self.ready()
            require(not screen.back, "Players did not reach its ordinary root")

    async def battle(self, *, after=-1, timeout=15):
        tasks = self.mem("gTasks", 640)
        raw_party = self.mem("gParties", 600)
        return dict(frame=time.monotonic(), state=int.from_bytes(self.mem("gMultiplayerBattleMailbox", 4, 12), "little"),
                    count=self.mem("gPartiesCount", 1)[0],
                    active=frozenset(int.from_bytes(tasks[o:o + 4], "little") & ~1 for o in range(0, 640, 40) if tasks[o + 4]),
                    cursor=self.mem("gPartyMenu", 20)[9], party_sha256=hashlib.sha256(raw_party).hexdigest())

    def party_now(self):
        count = self.mem("gPartiesCount", 1)[0]
        raw = self.mem("gParties", 600)
        boxes = b"".join(raw[i * 100:i * 100 + 80] for i in range(count))
        return dict(count=count, box_crc=f"{zlib.crc32(boxes):08x}")

    async def boot(self, slow=1.0):
        """Title screen, main menu, Continue: what a player presses."""
        await asyncio.sleep(10 * slow)
        await self.press(8)
        await asyncio.sleep(4 * slow)
        await self.press(8)
        await asyncio.sleep(6 * slow)
        await self.press(1)


async def drive_battle_input(probe, view, symbols, stop):
    """qualify_menu_battle.py's input policy: one key owner per game."""
    while not stop.is_set():
        room = await view()
        if room["state"] in ("closed", "aborted", "recovery_required"):
            return
        state = await probe.battle()
        action = party_action(room["pending"], state, symbols) if room["state"] == "executing" else "wait"
        if stop.is_set():
            return
        if action == "next-party":
            await probe.press(128, frames=12, release=18)
            moved = await probe.battle()
            current = await view()
            if (not stop.is_set() and current["state"] == "executing" and current["pending"] == 21
                    and moved["state"] == 5 and symbols["Task_HandleChooseMonInput"][0] & ~1 in moved["active"]
                    and moved["cursor"] != state["cursor"] and 0 <= moved["cursor"] < moved["count"]):
                await probe.press(1, frames=12, release=18)
        elif action != "wait":
            await probe.press(2 if action == "dismiss" else 1, frames=12, release=30 if action == "dismiss" else 18)
        else:
            await asyncio.sleep(.05)


async def native_menu_match(current, probes, games, host, symbols, record):
    """Both Enter operations remain entirely owned by production MenuSession."""
    async def identity(s):
        c = s._companion
        return (s._game, s._runtime, c._bridge, c._bridge.incarnation, c._live_battle_runtime_id)
    before = [await probe.battle() for probe in probes]
    await probes[0].open_players()
    await probes[0].choose("Battle Friend", prefix=True)
    await probes[0].choose("Challenge 1v1")
    await probes[1].open_players()
    await probes[1].choose("Pending challenge")
    await probes[1].choose("Accept challenge")
    async with asyncio.timeout(20):
        while not all(screen.admission_action for _, screen in [await p.ready() for p in probes]):
            await asyncio.sleep(.05)
    async def descriptor(s):
        values = s._companion._bridge.menu_session.menu._battles
        require(len(values) == 1 and values[0]["state"] == "accepted", "expected exact accepted native challenge")
        return json.loads(json.dumps(values[0]))
    challenge = await on_worker(current[0], descriptor)
    require(challenge == await on_worker(current[1], descriptor), "native consent descriptors differ")
    originals = [await on_worker(worker, identity) for worker in current]
    battle_id = challenge["battle_id"]
    slots = [challenge["players"].index(account.player_id) for account in host.accounts]
    blocks = []
    async def observe(s):
        service = s._server.battle_execution
        require(service.observer is None, "a previous proof observer exists")
        service.observer = lambda block: blocks.append(dict(block))
    await on_worker(current[0], observe)
    await asyncio.gather(*(p.choose("Enter battle", wait=False) for p in probes))
    record("both-native-Enter-selected", battle_id=battle_id, pids=[g.process.pid for g in games])
    async def view(slot):
        async def read(s):
            room = s._server.battle_execution.rooms.get(battle_id)
            if room is None:
                return dict(state="waiting", pending=None)
            return dict(state=room.state, pending=None if room.route is None else room.route.validator.pending[slot])
        return await on_worker(current[0], read)
    stop = asyncio.Event()
    drivers = [asyncio.create_task(drive_battle_input(p, lambda slot=slot: view(slot), symbols, stop))
               for p, slot in zip(probes, slots)]
    started = time.monotonic()
    async def finished(s):
        if (s._save_failed and s._interaction is None
                or s._game is None or s._game.process.returncode is not None):
            raise AssertionError("launcher retained a battle failure or lost its original game")
        return s.status.code == "battle_finished" and s.can_save and s._interaction is None
    try:
        async with asyncio.timeout(600):
            report_at = 0
            while True:
                for driver in drivers:
                    if driver.done():
                        await driver
                if all([await on_worker(w, finished) for w in current]):
                    break
                if time.monotonic() >= report_at:
                    record("native-1v1-progress", blocks=len(blocks), elapsed_seconds=round(time.monotonic() - started, 1))
                    report_at = time.monotonic() + 30
                await asyncio.sleep(.1)
    finally:
        stop.set()
        await asyncio.gather(*drivers)
    async def terminal(s):
        c = s._companion
        require(s._battle_retained is None and s._battle_handoff_successor is None, "launcher still retains battle ownership")
        require(s._emergency.result.state == "armed" and c._emergency_controller is s._emergency, "fresh terminal saver is not armed")
        require(not any((s.profile_directory / name).exists() for name in
            ("pending-battle.json", "pending-battle-admission.json", "pending-export.json", "pending-emergency.json")),
            "terminal recovery intent remains pending")
        history = (await c.battle_challenge_rpc("history"))["result"]
        values = [v for v in history if v["battle_id"] == battle_id]
        require(len(values) == 1 and values[0]["mode"] == 2 and values[0]["players"] == challenge["players"],
                "durable native singles result missing")
        return values[0], dict(status=asdict(s.status),
                               handoff_sha256=sha(s.profile_directory / (battle_id + ".battle-handoff.json")))
    results = []
    for slot, worker in enumerate(current):
        after = await on_worker(worker, identity)
        require(all(after[n] is originals[slot][n] for n in range(3)) and after[3:] == originals[slot][3:],
                "battle replaced the original game, bridge or native identity")
        require(games[slot].process.returncode is None, "original native process exited")
        result, details = await on_worker(worker, terminal)
        results.append(result)
        await probes[slot].snapshot(lambda r: r["hold"] == 0)
        state = await probes[slot].battle()
        require(state["count"] == before[slot]["count"] and state["party_sha256"] == before[slot]["party_sha256"],
                "original full personal party was not restored")
        record("launcher-native-battle-completed", slot=slot, pid=games[slot].process.pid, **details)
    require(results[0] == results[1], "players disagree on durable result")
    selected = [dict(owner=b["source"], slot=bytes.fromhex(b["data"])[9]) for b in blocks
                if b["kind"] == 8 and len(bytes.fromhex(b["data"])) > 9 and bytes.fromhex(b["data"])[0] == 1
                and bytes.fromhex(b["data"])[8] == 33]
    record("real-native-1v1-result", result=results[0], routed_blocks=len(blocks), selected_party_slots=selected,
           elapsed_seconds=round(time.monotonic() - started, 1))
    for index, probe in enumerate(probes):
        result = results[index]
        await probe.open_players()
        await probe.choose("Challenges")
        await probe.choose("Recent battle results")
        outcome = "Draw" if result["outcome"] == 3 else "Win" if result["outcome"] == 1 + slots[index] % 2 else "Loss"
        _, screen = await probe.choose(f"1v1 {outcome} #{result['sequence']}")
        require(screen.title == "Battle result" and screen.status ==
                ("Draw" if result["outcome"] == 3 else f"Team {result['outcome']} won"),
                "native history screen differs from durable outcome")
        record("native-result-screen-matches", slot=index, title=screen.title, status=screen.status)
        async with asyncio.timeout(15):
            while probe.read()["active"]:
                await probe.press(2)
    return results[0]


async def run(args):
    output = args.output.resolve()
    require("/multiplayer-proof/" in str(output) + "/" and not output.exists(), "choose a new private proof directory")
    output.mkdir(parents=True)
    game = args.game.resolve()
    symbols = symbols_of(game)
    missing = [name for name in NEEDED if name not in symbols]
    require(not missing, f"the native game lacks symbols {missing}: build it unstripped")
    manifest = json.loads(args.manifest.read_text())
    require(len(args.display) == 2 and len(set(args.display)) == 2, "one X display per player")
    os.environ.update(DISPLAY=args.display[0], SDL_AUDIODRIVER="dummy")

    def use_display(slot):
        """The next game the launcher starts opens on this player's display."""
        os.environ["DISPLAY"] = args.display[slot]
    # The launcher's own bundle and installation checks, for the Linux game.
    staging = output / "linux-game"
    staging.mkdir()
    (staging / "pokeemerald-mp.exe").write_bytes(game.read_bytes())
    (staging / "pokeemerald-mp.exe").chmod(0o755)
    (staging / "SDL2.dll").write_bytes(b"Linux harness: the Linux game links the system's libSDL2.\n")
    info = collect(staging / "pokeemerald-mp.exe", staging / "SDL2.dll", args.rom, output / "application" / "runtime")
    # The collector copies bytes only; a Linux executable also needs its mode
    # (the bundle's pins are content hashes, unchanged by this).
    (Path(info["directory"]) / "pokeemerald-mp.exe").chmod(0o755)
    from emerald_multiplayer.player_runtime import RuntimeBundle
    bundle = RuntimeBundle(Path(info["directory"]), info["manifest_sha256"])
    installation = GameInstallation(args.rom.resolve(), args.manifest.resolve(), sha(args.rom), sha(args.manifest), bundle)
    installation.verify()
    sources = [args.source_a.resolve(), args.source_b.resolve()]
    source_hashes = [sha(p) for p in sources]
    evidence = dict(passed=False, scope=__doc__.split("\n\n")[0], game_sha256=sha(game), bundle=info,
                    build_id=manifest["rom_sha256"], sources=[dict(path=str(p), sha256=h) for p, h in zip(sources, source_hashes)],
                    checks=[], inputs=0, forced_children=[])
    def persist():
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    def record(name, quiet=False, **fields):
        if quiet:
            evidence["inputs"] += 1
            return
        evidence["checks"].append(dict(verified=name, **fields))
        persist()
        output_event(check=name, **fields)
    workers, windows, roots, children = [], [], [], []
    private = output / "private"
    completed = False

    async def poll_until(predicate, timeout=30):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(.05)

    async def gui_pump():
        while True:
            for root in roots:
                root.update()
            await asyncio.sleep(.02)

    async def boot_until_field(companion, game_process, slow, slot):
        probe = NativeProbe(game_process.pid, symbols, args.display[slot], record)
        await probe.boot(slow)
        for _ in range(12):
            pose = companion._local_pose
            if pose is not None and pose.activity == 1:
                break
            await asyncio.sleep(4)
            pose = companion._local_pose
            if pose is None or pose.activity != 1:
                await probe.press(1)
        return probe

    pump = asyncio.create_task(gui_pump())
    try:
        with socket.socket() as probe_socket:
            probe_socket.bind(("127.0.0.1", 0))
            port = probe_socket.getsockname()[1]
        host = create_world(installation, private, player_names=("Battle Host", "Battle Friend"),
                            endpoint="127.0.0.1", port=port)
        expected = []
        for slot, source in enumerate(sources):
            use_display(slot)
            async with host_enrollment(installation, private, world_directory=host.directory, slot=slot,
                                       source_path=source) as runtime:
                children.append(runtime._game.process)
                await boot_until_field(runtime.companion, runtime._game.process, args.slow, slot)
                await field_ready(runtime.companion, runtime._game)
                enrolled = await runtime.enroll()
                require(enrolled.metadata["revision"] == 1, "enrollment revision differs")
                require(runtime._game.process.returncode is not None, "production enrollment did not close its bootstrap child")
                record("production-enrollment-closed-bootstrap", slot=slot, pid=runtime._game.process.pid,
                       returncode=runtime._game.process.returncode)
            with MirrorLease(runtime.save_path):
                pass
            with host.open_store() as store:
                expected.append(party(inspect_closed_head(store, host.accounts[slot].player_id)))
        require([value["count"] for value in expected] == [2, 1],
                "this bounded proof requires the pinned ordinary two/one-member parties")
        invitation = output / "friend-invitation.json"
        export_friend_invitation(installation, host.directory, 1, invitation)
        saved = []
        for phase in ("battle-and-save", "fresh-Continue"):
            current, games, probes, mirrors = [], [], [], []
            for slot, mode in enumerate(("host", "join")):
                worker = SessionWorker(installation, private)
                workers.append(worker)
                current.append(worker)
                import tkinter as tk
                use_display(slot)  # Toplevels stay on the first root's display
                root = tk.Tk() if not roots else tk.Toplevel(roots[0])
                window = LauncherWindow(root, worker, version="Native 1v1 proof")
                root.title(f"Native battle proof {phase} {mode}")
                roots.append(root)
                windows.append(window)
                selection = host.directory / "world.json" if slot == 0 else invitation
                require(worker.start(LaunchRequest(mode, selection)), "real GUI worker did not start")
                await poll_until(lambda: worker._active_session is not None or not worker.busy)
                require(worker._active_session is not None, "launcher worker failed before play")
                async def prepare(s):
                    async with asyncio.timeout(30):
                        while s._game is None:
                            await asyncio.sleep(.03)
                    await s.set_autosave_enabled(False)
                    return s._game, s.profile_directory / "character.sav"
                game_handle, mirror = await on_worker(worker, prepare)
                children.append(game_handle.process)
                games.append(game_handle)
                mirrors.append(mirror)
                async def companion_of(s):
                    return s._companion
                companion = await on_worker(worker, companion_of)
                probes.append(await boot_until_field(companion, game_handle.process, args.slow, slot))
                async def ready(s):
                    await field_ready(s._companion, s._game)
                    async with asyncio.timeout(20):
                        while s._emergency is None or s._emergency.result.state != "armed":
                            await asyncio.sleep(.03)
                    lease_is_owned(s.profile_directory / "character.sav")
                    return s.status.revision
                require(await on_worker(worker, ready) == (1 if phase == "battle-and-save" else 2), "startup revision differs")
            record("actual-launcher-workers-ready", phase=phase, pids=[g.process.pid for g in games])
            if phase == "battle-and-save":
                await native_menu_match(current, probes, games, host, symbols, record)
                for worker in current:
                    async def save(s):
                        require(await s.save(), "manual save did not finish")
                        require(s.status.revision == 2, "manual save revision differs")
                    await on_worker(worker, save)
                record("both-saved-after-the-battle", revision=2)
            async def heads(s):
                rows = []
                for slot, account in enumerate(host.accounts):
                    head = inspect_closed_head(s._store, account.player_id)
                    require(head.revision == 2 and party(head) == expected[slot], "canonical party or revision changed")
                    rows.append((head.revision, head.sha256))
                s._store.integrity_check()
                return rows
            actual = await on_worker(current[0], heads)
            if phase == "battle-and-save":
                saved = actual
            else:
                require(actual == saved, "fresh Continue changed canonical checkpoints")
                require(all(g.startup.mirror.sha256 == actual[n][1] for n, g in enumerate(games)), "fresh native mirror differs")
            parties = [p.party_now() for p in probes]
            require(parties == [dict(count=e["count"], box_crc=e["box_crc"]) for e in expected],
                    "a running game's party differs from its canonical character")
            record("ready_for_normal_close", phase=phase, parties=parties)
            for g in reversed(games):  # friend, then host
                os.kill(g.process.pid, signal.SIGTERM)
                await poll_until(lambda g=g: g.process.returncode is not None, 30)
            await poll_until(lambda: not any(w.busy for w in current), 120)
            require([g.process.returncode for g in games] == [0, 0], "ordinary SDL exit failed")
            for mirror in mirrors:
                with MirrorLease(mirror):
                    pass
            record("normal-close", phase=phase, exit_codes=[0, 0])
        with host.open_store() as store:
            store.integrity_check()
        require([sha(p) for p in sources] == source_hashes, "a source save changed")
        completed = True
        record("store integrity check passed; source saves unchanged")
    except BaseException as error:
        evidence["error"] = repr(error)
        evidence["traceback"] = traceback.format_exc()
        raise
    finally:
        for child in children:
            if child.returncode is None:
                evidence["forced_children"].append(child.pid)
                try:
                    os.kill(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            await poll_until(lambda: not any(w.busy for w in workers), 20)
        except BaseException as error:
            evidence.setdefault("cleanup_errors", []).append(repr(error))
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        for window in reversed(windows):
            try:
                window._destroy()
            except Exception as error:
                evidence.setdefault("cleanup_errors", []).append(repr(error))
        evidence["passed"] = completed and not evidence["forced_children"] and not evidence.get("cleanup_errors")
        persist()
        output_event(passed=evidence["passed"])
    require(evidence["passed"], "proof failed; the private evidence records why")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="native Linux executable, unstripped")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-a", type=Path, required=True)
    parser.add_argument("--source-b", type=Path, required=True)
    parser.add_argument("--display", action="append", required=True, help="an X display per player (twice)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
