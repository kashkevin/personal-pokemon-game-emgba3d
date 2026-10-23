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

Windows clients (`--wine P1 --wine P2 --sdl SDL2.dll --elf <Linux build>`): the
bundle holds the Windows exe and its SDL2.dll, exactly as a release would; the
launcher's spawn goes through `wine` (one prefix per player, KNOWN_ISSUES M3,
chosen like the display); memory is read at the PE symbols' addresses (see
native_trade_proof.py); "normal close" is Alt+F4 to the game's window, the
ordinary Windows close (Wine's window procedure turns it into WM_CLOSE, SDL into
an ordinary quit, exit 0).

On Windows itself (the CI runner: `--game pokeemerald-mp.exe --sdl SDL2.dll
--pe-symbols <nm -n of the exe before its strip> --sizes <nm -S of the Linux
build>`): the launcher starts the Windows game as it does for a player; memory
is read with ReadProcessMemory at the PE symbols' addresses moved to where
Windows loaded the game (native_windows_process.py), keys are the keyboard's
messages posted to each game's own window, "normal close" is WM_CLOSE. All the
players' games share one desktop; nobody types on the PC.

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
from native_trade_proof import PE_IMAGE_BASE, parse_nm_sizes, parse_pe_symbols, pe_symbols  # noqa: E402
from emerald_multiplayer.checkpoint_mirror import MirrorLease  # noqa: E402
from emerald_multiplayer.launcher_gui import LaunchRequest, LauncherWindow, SessionWorker  # noqa: E402
from emerald_multiplayer.launcher_session import GameInstallation  # noqa: E402
from emerald_multiplayer.launcher_setup import create_world, export_friend_invitation, host_enrollment  # noqa: E402
from emerald_multiplayer.menu_mailbox import unpack_screen  # noqa: E402

KEYS = {1: "z", 2: "x", 4: "backslash", 8: "Return", 16: "Right", 32: "Left", 64: "Up", 128: "Down"}
PLAYER_OPTIONS, TRAINER_CARD, PLAYERS = 15, 16, 17
PARTY_TASKS = ("Task_HandleChooseMonInput", "Task_HandleSelectionMenuInput", "Task_PrintAndWaitForText")
NEEDED = ("sMultiplayerMenuActive", "sMultiplayerMenuWaiting", "sMultiplayerMenuCursor", "sMultiplayerMenuScreen",
          "sCurrentStartMenuActions", "sNumStartMenuActions", "sStartMenuCursorPos", "gMultiplayerBattleHoldFlags",
          "gMultiplayerBattleMailbox", "gTasks", "gPartyMenu", "gParties", "gPartiesCount", *PARTY_TASKS,
          "gBattlerControllerFuncs", "gActionSelectionCursor")
CHOOSE_ACTION = "HandleInputChooseAction"  # static in each battle controller: every address counts
# What the proofs built on this harness read beyond NEEDED (a PE symbol table gives only the names asked for).
EXTRA_NEEDED = ("gMain", "CB2_StarterChoose", "CB2_Overworld", "CB2_TrainerCard", "CB2_BagMenuRun",
                "CB2_UpdatePartyMenu", "sBattleAdmissionLatched", "gBattleTypeFlags", "gBattlersCount", "gBattleMons",
                "sRemotes", "sGlobalScriptContextStatus", "HandleInputChooseMove", "BattleMainCB2",
                "gSaveBlock1Ptr", "gSaveBlock2Ptr", "gSaveBlock3Ptr", "PlayerHandleYesNoInput", "sCoopAward", "sCoopExp",
                "gBattleStruct", "gSaveCounter", "sLockFieldControls")
WINDOWS = sys.platform == "win32"


def load_average():
    """The 1, 5 and 15 minute load (Linux); Windows has none."""
    return [round(v, 2) for v in os.getloadavg()] if hasattr(os, "getloadavg") else None


def pe_symbol_table(rows, sizes):
    """NEEDED, each fitting the Windows layout (native_trade_proof.parse_pe_symbols), and what of EXTRA_NEEDED fits:
    `rows` is `i686-w64-mingw32-nm -n` of the Windows game, `sizes` the Linux build's symbols."""
    symbols = parse_pe_symbols(rows, sizes, NEEDED)
    for name in EXTRA_NEEDED:
        try:
            symbols.update(parse_pe_symbols(rows, sizes, (name,)))
        except ValueError:
            pass                     # a proof that reads it fails on the missing name, with that name
    return symbols


def function_addresses_in(rows, name):
    """function_addresses() from a saved `i686-w64-mingw32-nm -n` of the Windows game."""
    found = set()
    for line in rows.splitlines():
        row = line.split()
        if len(row) == 3 and row[1] in ("T", "t") and row[2] in (name, "_" + name):
            found.add(int(row[0], 16) & ~1)
    return frozenset(found)


def function_addresses(game, name, *, pe=False):
    """All addresses of a (possibly static, so repeated) function in the game's symbol table."""
    rows = subprocess.run(["i686-w64-mingw32-nm" if pe else "nm", str(game)], capture_output=True, text=True,
                          check=True).stdout
    found = set()
    for line in rows.splitlines():
        row = line.split()
        if len(row) == 3 and row[1] in ("T", "t") and row[2] in (name, "_" + name):
            found.add(int(row[0], 16) & ~1)
    return frozenset(found)


def symbols_of(game):
    rows = subprocess.run(["nm", "-S", str(game)], capture_output=True, text=True, check=True).stdout
    symbols = {}
    for line in rows.splitlines():
        row = line.split()
        if len(row) == 4:
            symbols[row[3]] = (int(row[0], 16), int(row[1], 16))
    return symbols


def game_picture(probe, path, settle=.3):
    """A game's window as a person sees it (evidence for a person; the checks read memory), at `path` (a .png); returns
    its file name. Linux: xdotool raises the window and ImageMagick's import takes it. Windows: the runner's desktop,
    where every player's game is (ci_world_check.py's capture; windows-package run 129's Mega proof stopped on the X11
    commands after both Charizard had Mega Evolved), with this game's window kept above the others while it is taken."""
    if WINDOWS:
        from ci_world_check import screenshot
        try:
            window = probe._window()
            raised = probe._windows.keep_on_top(window)
            time.sleep(settle)
        except (RuntimeError, OSError, AttributeError):
            window, raised = None, False
        try:
            screenshot(str(path))
        finally:
            if raised:
                probe._windows.keep_on_top(window, False)
        return Path(path).name
    try:
        window = probe._window()
        subprocess.run(["xdotool", "windowraise", window], env=probe.environment, capture_output=True, timeout=10)
        time.sleep(settle)
    except (RuntimeError, subprocess.SubprocessError):
        window = "root"
    subprocess.run(["import", "-window", window, str(path)], capture_output=True, timeout=30, env=probe.environment)
    return Path(path).name


class NativeProbe:
    """One launcher-started native game: keys to its window, reads of its memory."""

    def __init__(self, pid, symbols, display, record, *, hold=.15, gap=.2, choose_action=frozenset()):
        self.pid, self.symbols, self.display, self.record = pid, symbols, display, record
        self.choose_action = choose_action
        self.hold, self.gap, self.presses = hold, gap, 0
        self.environment = dict(os.environ, DISPLAY=display)

    def mem(self, name, size=None, offset=0):
        address, length = self.symbols[name]
        with open(f"/proc/{self.pid}/mem", "rb", buffering=0) as memory:
            memory.seek(address + offset)
            return memory.read(length if size is None else size)

    def code(self, value):
        """A code pointer read from the game (a callback, a task's function) as the build's own address, the
        symbols' numbering: a Linux game (or the Windows one under Wine) runs where it was linked."""
        return value

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
        # Visible windows only: Wine also gives the process hidden helper windows.
        found = subprocess.run(["xdotool", "search", "--onlyvisible", "--pid", str(self.pid)],
                               env=self.environment, capture_output=True, text=True).stdout.split()
        for window in reversed(found):
            try:
                if subprocess.run(["xdotool", "windowfocus", "--sync", window], env=self.environment,
                                  capture_output=True, timeout=5).returncode == 0:
                    return window
            except subprocess.TimeoutExpired:
                pass
        raise RuntimeError(f"no window of native game {self.pid}")

    def _close_window(self):
        self._window()
        subprocess.run(["xdotool", "key", "alt+F4"], env=self.environment, check=True)

    async def close_window(self):
        """Alt+F4, the ordinary Windows close."""
        await asyncio.to_thread(self._close_window)

    def _press(self, key, seconds):
        self._window()
        subprocess.run(["xdotool", "keydown", key], env=self.environment, check=True)
        time.sleep(seconds)
        subprocess.run(["xdotool", "keyup", key], env=self.environment, check=True)

    def _chord(self, keys, seconds):
        self._window()
        for key in keys:
            subprocess.run(["xdotool", "keydown", key], env=self.environment, check=True)
        time.sleep(seconds)
        for key in keys:
            subprocess.run(["xdotool", "keyup", key], env=self.environment, check=True)

    async def press_reset_key(self, frames=12, release=60):
        """MS-61: the soft reset key, A+B+START+SELECT held together (Ctrl+R sends the same)."""
        await asyncio.to_thread(self._chord, ("z", "x", "Return", "backslash"), max(self.hold, frames / 60))
        await asyncio.sleep(max(self.gap, release / 60))
        self.record("ordinary-input", pid=self.pid, key="reset-key", quiet=True)
        return self.read()

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
                    active=frozenset(self.code(int.from_bytes(tasks[o:o + 4], "little")) & ~1
                                     for o in range(0, 640, 40) if tasks[o + 4]),
                    cursor=self.mem("gPartyMenu", 20)[9], party_sha256=hashlib.sha256(raw_party).hexdigest())

    def party_now(self):
        count = self.mem("gPartiesCount", 1)[0]
        raw = self.mem("gParties", 600)
        boxes = b"".join(raw[i * 100:i * 100 + 80] for i in range(count))
        return dict(count=count, box_crc=f"{zlib.crc32(boxes):08x}")

    def in_choose_action(self):
        """The player's battle controller waits on its action menu (Fight, Bag, Pokemon, Run)."""
        funcs = self.code(int.from_bytes(self.mem("gBattlerControllerFuncs", 4), "little")) & ~1
        return funcs in self.choose_action

    async def run_from_wild_battle(self, in_field, timeout=120):
        """A wild Pokemon walked up to the player: Run, as a player would (no move is used, so
        nothing in the party changes). Text is advanced with B, which selects nothing."""
        async with asyncio.timeout(timeout):
            while not in_field():
                if self.in_choose_action():
                    cursor = self.mem("gActionSelectionCursor", 1)[0]
                    # Fight 0, Bag 1, Pokemon 2, Run 3 (two by two).
                    await self.press(1 if cursor == 3 else 128 if cursor == 1 else 16)
                else:
                    await self.press(2)
                await asyncio.sleep(.2)

    async def wait_for_window(self, timeout):
        """The game's window once it is there. The 3D game opens it after loading its world: the first start after a
        restart (a cold disk) took longer than the boot's ten seconds, and the first press found no window."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                return await asyncio.to_thread(self._window)
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(1)

    async def boot(self, slow=1.0):
        """Title screen, main menu, Continue: what a player presses."""
        await asyncio.sleep(10 * slow)
        await self.wait_for_window(60 * slow)
        await self.press(8)
        await asyncio.sleep(4 * slow)
        await self.press(8)
        await asyncio.sleep(6 * slow)
        await self.press(1)


class WindowsProbe(NativeProbe):
    """NativeProbe for the Windows game run on Windows (native_windows_process.py): its memory through
    ReadProcessMemory at the build's symbols moved to the game's image base, keys posted to the game's own window
    (the players' games share one desktop and its focus), WM_CLOSE as its close button."""

    def __init__(self, pid, symbols, display, record, *, exe, **options):
        super().__init__(pid, symbols, display, record, **options)
        import native_windows_process
        self._windows = native_windows_process
        self.memory = native_windows_process.ProcessMemory(pid, exe)

    def mem(self, name, size=None, offset=0):
        address, length = self.symbols[name]
        return self.memory.read(address + offset, length if size is None else size)

    def code(self, value):
        # Windows may load the game elsewhere than its preferred base (ASLR): the reads above move each symbol by that
        # delta, and every code pointer the game holds is moved by it too. Compared with the symbols, a callback read
        # as it is never matched (the runner's newcomers claims waited for CB2_StarterChoose until they timed out).
        return value - self.memory.delta if value else value

    def _window(self):
        window = self._windows.window_of(self.pid)
        if window is None:
            raise RuntimeError(f"no window of native game {self.pid}")
        return window

    def _close_window(self):
        self._windows.close(self._window())

    def _press(self, key, seconds):
        self._windows.press(self._window(), key, seconds)

    def _chord(self, keys, seconds):
        self._windows.chord(self._window(), keys, seconds)


async def drive_battle_input(probe, view, symbols, stop, seen=None):
    """qualify_menu_battle.py's input policy: one key owner per game. `seen` (a dict, if given) keeps what the driver
    last read and did, for a proof's record while the battle runs: the room's state and pending request, the game's
    battle phase, the action, the presses so far and when the last one was (time.monotonic())."""
    if seen is not None:
        seen.update(presses=0, pressed=None)
    while not stop.is_set():
        room = await view()
        if seen is not None:
            seen.update(room=room["state"], pending=room["pending"])
        if room["state"] in ("closed", "aborted", "recovery_required"):
            return
        state = await probe.battle()
        action = party_action(room["pending"], state, symbols) if room["state"] == "executing" else "wait"
        if seen is not None:
            seen.update(phase=state["state"], action=action)
            if action != "wait":
                seen.update(presses=seen["presses"] + 1, pressed=time.monotonic())
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
    await probes[0].choose("Rival Battle - 1v1")
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


class Player:
    """One player's launcher worker, its native game and the probe on that game."""

    def __init__(self, slot, worker, game, probe, mirror, companion):
        self.slot, self.worker, self.game, self.probe, self.mirror = slot, worker, game, probe, mirror
        self.companion = companion


class LauncherHarness:
    """The whole launcher with one native game per player (2 or 4): setup, players, cleanup.

    `settings` is written to the launchers' shared settings file before any game
    starts (window size only); `after_boot(phase, slot, probe, companion)` runs
    once each game is in the field (ordinary play, such as walking somewhere);
    `environment` is added to the environment the games inherit (display
    plumbing only). A save failure inside a launcher (`LauncherSession._fail_save`)
    is recorded with where it came from: a pass-through wrapper that calls it
    unchanged. Every exit records evidence; a failure also screenshots each display."""

    def __init__(self, args, *, names, sources, party_counts, version, settings=None, scope=None,
                 after_boot=None, environment=None):
        self.args, self.names, self.party_counts, self.version = args, tuple(names), tuple(party_counts), version
        self.settings, self.after_boot, self.environment = settings, after_boot, environment
        self.count = count = len(names)
        self.output = output = args.output.resolve()
        require("/multiplayer-proof/" in output.as_posix() + "/" and not output.exists(),
                "choose a new private proof directory")
        output.mkdir(parents=True)
        self.game = game = args.game.resolve()
        self.wine = wine = bool(args.wine)
        # The Windows game on Windows itself (the CI runner): no Wine, no X displays, no binutils.
        self.native_windows = native_windows = WINDOWS
        if native_windows:
            require(not wine and getattr(args, "pe_symbols", None) and getattr(args, "sizes", None) and args.sdl,
                    "on Windows: --sdl, --pe-symbols (nm -n of the game before its strip) and --sizes (nm -S of the "
                    "Linux build of the same engine commit)")
            rows = args.pe_symbols.read_text()
            self.symbols = pe_symbol_table(rows, parse_nm_sizes(args.sizes.read_text()))
            self.choose_action = function_addresses_in(rows, CHOOSE_ACTION)
        elif wine:
            require(len(args.wine) == count and len(set(args.wine)) == count and args.sdl and args.elf,
                    "Windows clients need a Wine prefix per player, --sdl and --elf")
            self.symbols = pe_symbols(game, args.elf.resolve(), NEEDED)
            self.choose_action = function_addresses(game, CHOOSE_ACTION, pe=True)
        else:
            self.symbols = symbols_of(game)
            self.choose_action = function_addresses(game, CHOOSE_ACTION)
        missing = [name for name in NEEDED if name not in self.symbols]
        require(self.choose_action, f"the native game lacks {CHOOSE_ACTION}: build it unstripped")
        require(not missing, f"the native game lacks symbols {missing}: build it unstripped")
        manifest = json.loads(args.manifest.read_text())
        require(len(args.display) == count and len(set(args.display)) == count, "one X display per player")
        os.environ.update(DISPLAY=args.display[0], SDL_AUDIODRIVER="dummy", **(environment or {}))
        if wine:
            os.environ["WINEDEBUG"] = "-all"
        self.hold, self.gap = (.5, .3) if wine else (.15, .2)
        self.ready_seconds = 20 if count == 2 else 90
        if wine or native_windows:
            # The release's own files: the Windows exe and its SDL2.dll (and what a test runner adds beside them:
            # Mesa's software OpenGL for the 3D game on a runner whose own OpenGL is 1.1).
            info = collect(game, args.sdl.resolve(), args.rom, output / "application" / "runtime",
                           extra=tuple(path.resolve() for path in getattr(args, "runtime_extra", None) or ()))
        else:
            # The launcher's own bundle and installation checks, for the Linux game.
            staging = output / "linux-game"
            staging.mkdir()
            (staging / "pokeemerald-mp.exe").write_bytes(game.read_bytes())
            (staging / "pokeemerald-mp.exe").chmod(0o755)
            (staging / "SDL2.dll").write_bytes(b"Linux harness: the Linux game links the system's libSDL2.\n")
            info = collect(staging / "pokeemerald-mp.exe", staging / "SDL2.dll", args.rom,
                           output / "application" / "runtime")
            # The collector copies bytes only; a Linux executable also needs its mode
            # (the bundle's pins are content hashes, unchanged by this).
            (Path(info["directory"]) / "pokeemerald-mp.exe").chmod(0o755)
        from emerald_multiplayer.player_runtime import RuntimeBundle
        bundle = RuntimeBundle(Path(info["directory"]), info["manifest_sha256"])
        self.installation = GameInstallation(args.rom.resolve(), args.manifest.resolve(), sha(args.rom),
                                             sha(args.manifest), bundle)
        self.installation.verify()
        self.sources = [Path(path).resolve() for path in sources]
        self.source_hashes = [sha(p) for p in self.sources]
        self.evidence = dict(passed=False, scope=scope or __doc__.split("\n\n")[0], game_sha256=sha(game), bundle=info,
                             wine=wine, windows=native_windows, key_hold_seconds=self.hold,
                             elf_sha256=sha(args.elf) if wine else None,
                             build_id=manifest["rom_sha256"],
                             sources=[dict(path=str(p), sha256=h) for p, h in zip(self.sources, self.source_hashes)],
                             checks=[], inputs=0, forced_children=[], players=list(names),
                             expected_party_counts=list(party_counts), settings=settings, environment=environment,
                             save_failures=[])
        self.workers, self.windows, self.roots, self.children = [], [], [], []
        self.started = time.monotonic()
        self.private = output / "private"
        self.completed = False
        self.host = None
        self.expected = []
        self.invitations = [None]

    # Evidence -------------------------------------------------------------
    def persist(self):
        (self.output / "evidence.json").write_text(json.dumps(self.evidence, indent=2) + "\n")

    def record(self, name, quiet=False, **fields):
        if quiet:
            self.evidence["inputs"] += 1
            return
        self.evidence["checks"].append(dict(verified=name, **fields))
        self.persist()
        output_event(check=name, **fields)

    # Plumbing -------------------------------------------------------------
    def use_display(self, slot):
        """The next game the launcher starts opens on this player's display (and Wine prefix)."""
        os.environ["DISPLAY"] = self.args.display[slot]
        if self.wine:
            os.environ["WINEPREFIX"] = str(self.args.wine[slot].resolve())

    async def poll_until(self, predicate, timeout=30):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(.05)

    async def _gui_pump(self):
        while True:
            for root in self.roots:
                root.update()
            await asyncio.sleep(.02)

    async def __aenter__(self):
        self._real_spawn = real_spawn = asyncio.create_subprocess_exec

        async def spawn_with_wine(program, *arguments, **options):
            # The launcher (player_runtime / enrollment) starts the bundle's exe;
            # on this Linux workspace Wine runs it. Nothing else is redirected.
            if str(program).lower().endswith(".exe"):
                return await real_spawn("wine", program, *arguments, **options)
            return await real_spawn(program, *arguments, **options)

        if self.wine:
            asyncio.create_subprocess_exec = spawn_with_wine
        from emerald_multiplayer.launcher_session import LauncherSession
        self._session_class = LauncherSession
        self._original_fail_save = original = LauncherSession._fail_save
        harness = self

        def recorded_fail_save(session, *values, **options):
            checks = harness.evidence["checks"]
            harness.evidence["save_failures"].append(dict(
                status=getattr(getattr(session, "status", None), "code", None), exception=repr(sys.exc_info()[1]),
                # When: seconds into the proof and the last check recorded before it.
                seconds=round(time.monotonic() - harness.started, 1),
                after_check=checks[-1]["verified"] if checks else None,
                stack=traceback.format_stack(limit=12)[:-1]))
            harness.persist()
            return original(session, *values, **options)

        LauncherSession._fail_save = recorded_fail_save
        self._pump = asyncio.create_task(self._gui_pump())
        return self

    async def __aexit__(self, kind, error, tb):
        evidence = self.evidence
        if error is not None:
            evidence["error"] = repr(error)
            evidence["traceback"] = "".join(traceback.format_exception(kind, error, tb))
            evidence["load_average"] = load_average()
            if self.native_windows:
                try:                              # the one desktop all the games share
                    import ci_world_check
                    ci_world_check.screenshot(self.output / "failure.png")
                except Exception as picture_error:  # noqa: BLE001 - a picture never hides the failure
                    evidence["picture_error"] = repr(picture_error)
            else:
                for slot, display in enumerate(self.args.display):
                    subprocess.run(["import", "-window", "root", str(self.output / f"failure-{slot}.png")],
                                   env=dict(os.environ, DISPLAY=display), capture_output=True)
        for child in self.children:
            if child.returncode is None:
                evidence["forced_children"].append(child.pid)
                try:
                    child.kill()                  # SIGKILL; TerminateProcess on Windows (which has no SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            await self.poll_until(lambda: not any(w.busy for w in self.workers), 20)
        except BaseException as cleanup_error:
            evidence.setdefault("cleanup_errors", []).append(repr(cleanup_error))
        self._pump.cancel()
        await asyncio.gather(self._pump, return_exceptions=True)
        for window in reversed(self.windows):
            try:
                window._destroy()
            except Exception as cleanup_error:
                evidence.setdefault("cleanup_errors", []).append(repr(cleanup_error))
        asyncio.create_subprocess_exec = self._real_spawn
        self._session_class._fail_save = self._original_fail_save
        evidence["passed"] = (error is None and self.completed and not evidence["forced_children"]
                              and not evidence.get("cleanup_errors"))
        self.persist()
        output_event(passed=evidence["passed"])
        if error is None:
            require(evidence["passed"], "proof failed; the private evidence records why")
        return False

    # Steps ----------------------------------------------------------------
    def probe_of(self, pid, slot):
        options = dict(hold=self.hold, gap=self.gap, choose_action=self.choose_action)
        if self.native_windows:
            return WindowsProbe(pid, self.symbols, self.args.display[slot], self.record, exe=self.game, **options)
        return NativeProbe(pid, self.symbols, self.args.display[slot], self.record, **options)

    async def boot_until_field(self, companion, game_process, slot):
        probe = self.probe_of(game_process.pid, slot)
        probe.output = self.output  # for pictures taken when a step fails
        await probe.boot(self.args.slow)
        for _ in range(20):
            pose = companion._local_pose
            if pose is not None and pose.activity == 1:
                break
            await asyncio.sleep(4)
            pose = companion._local_pose
            if probe.in_choose_action():
                # A visible wild Pokemon reached a player idling in grass; A would fight.
                await probe.run_from_wild_battle(lambda: companion._local_pose is not None
                                                 and companion._local_pose.activity == 1)
                self.record("ran-from-a-wild-battle", slot=slot, during="startup")
            elif pose is None or pose.activity != 1:
                await probe.press(1)
        if self.wine:
            with open(f"/proc/{game_process.pid}/mem", "rb", buffering=0) as memory:
                memory.seek(PE_IMAGE_BASE)
                require(memory.read(2) == b"MZ", "the Windows game is not mapped at its preferred base")
        return probe

    async def setup_world(self):
        """Production world creation, host enrollment of every source, friends' invitations."""
        with socket.socket() as probe_socket:
            probe_socket.bind(("127.0.0.1", 0))
            port = probe_socket.getsockname()[1]
        if self.settings is not None:
            self.private.mkdir(parents=True, exist_ok=True)
            (self.private / "game-settings.cfg").write_text(self.settings)
        self.host = host = create_world(self.installation, self.private, player_names=self.names,
                                        endpoint="127.0.0.1", port=port)
        for slot, source in enumerate(self.sources):
            self.use_display(slot)
            async with host_enrollment(self.installation, self.private, world_directory=host.directory, slot=slot,
                                       source_path=source) as runtime:
                self.children.append(runtime._game.process)
                try:
                    probe = await self.boot_until_field(runtime.companion, runtime._game.process, slot)
                    if self.after_boot is not None:
                        # Enrollment saves the running game, so the character is enrolled
                        # where it then stands; walking changes no party.
                        await self.after_boot("enrollment", slot, probe, runtime.companion)
                    await field_ready(runtime.companion, runtime._game)
                    enrolled = await runtime.enroll()
                except BaseException:
                    # host_enrollment reports only a safe summary; keep the cause.
                    self.evidence["enrollment_error"] = dict(slot=slot, traceback=traceback.format_exc())
                    self.persist()
                    raise
                require(enrolled.metadata["revision"] == 1, "enrollment revision differs")
                require(runtime._game.process.returncode is not None, "production enrollment did not close its bootstrap child")
                self.record("production-enrollment-closed-bootstrap", slot=slot, pid=runtime._game.process.pid,
                            returncode=runtime._game.process.returncode)
            with MirrorLease(runtime.save_path):
                pass
            with host.open_store() as store:
                self.expected.append(party(inspect_closed_head(store, host.accounts[slot].player_id)))
        require([value["count"] for value in self.expected] == list(self.party_counts),
                "the sources' parties differ from this proof's party profile")
        for slot in range(1, self.count):
            invitation = self.output / ("friend-invitation.json" if self.count == 2 else f"friend-{slot}-invitation.json")
            export_friend_invitation(self.installation, host.directory, slot, invitation)
            self.invitations.append(invitation)

    async def start(self, phase, slot):
        """Host Game (slot 0) or Join Game through a real launcher worker and window; boot to the field."""
        worker = SessionWorker(self.installation, self.private)
        self.workers.append(worker)
        import tkinter as tk
        self.use_display(slot)  # Toplevels stay on the first root's display
        root = tk.Tk() if not self.roots else tk.Toplevel(self.roots[0])
        window = LauncherWindow(root, worker, version=self.version)
        root.title(f"{self.version} {phase} {self.names[slot]}")
        self.roots.append(root)
        self.windows.append(window)
        mode = "host" if slot == 0 else "join"
        selection = self.host.directory / "world.json" if slot == 0 else self.invitations[slot]
        require(worker.start(LaunchRequest(mode, selection)), "real GUI worker did not start")
        await self.poll_until(lambda: worker._active_session is not None or not worker.busy)
        require(worker._active_session is not None, "launcher worker failed before play")
        async def prepare(s):
            async with asyncio.timeout(30):
                while s._game is None:
                    await asyncio.sleep(.03)
            await s.set_autosave_enabled(False)
            return s._game, s.profile_directory / "character.sav", s._companion
        game_handle, mirror, companion = await on_worker(worker, prepare)
        self.children.append(game_handle.process)
        probe = await self.boot_until_field(companion, game_handle.process, slot)
        if self.after_boot is not None:
            await self.after_boot(phase, slot, probe, companion)
        return Player(slot, worker, game_handle, probe, mirror, companion)

    async def ready(self, player):
        """Field, capabilities, the terminal saver armed and the save lease held; the startup revision."""
        ready_seconds = self.ready_seconds
        async def ready(s):
            await field_ready(s._companion, s._game, timeout=180)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + ready_seconds
            while s._emergency is None or s._emergency.result.state != "armed":
                if loop.time() >= deadline:
                    c, pose = s._companion, s._companion._local_pose
                    raise AssertionError("the launcher did not arm its terminal saver: " + json.dumps(dict(
                        state=None if s._emergency is None else s._emergency.result.state,
                        connected=c.connected, bridge=c._bridge is not None,
                        emergency_capable=getattr(c._bridge, "emergency_save_capable", None),
                        activity=None if pose is None else pose.activity,
                        pose_age=round(loop.time() - c._last_pose_time, 2),
                        checkpoint_locked=c.live_checkpoint_lock.locked(),
                        interaction=s._interaction is not None, save_failed=s._save_failed)))
                await asyncio.sleep(.03)
            lease_is_owned(s.profile_directory / "character.sav")
            return s.status.revision
        return await on_worker(player.worker, ready)

    async def save(self, player, revision):
        async def save(s):
            require(await s.save(), "manual save did not finish: " + json.dumps(dict(
                code=s.status.code, error=getattr(s, "last_save_error", None))))
            require(s.status.revision == revision, "manual save revision differs")
        await on_worker(player.worker, save)

    async def close_game(self, game, probe):
        """One game's ordinary close: SIGTERM (SDL turns it into a quit), on Windows its window's WM_CLOSE."""
        if self.native_windows:
            await probe.close_window()
        else:
            os.kill(game.process.pid, signal.SIGTERM)

    async def close(self, players):
        """Ordinary close in the given order (SIGTERM, which SDL turns into a quit; Alt+F4 under Wine; WM_CLOSE on
        Windows)."""
        for player in players:
            if self.wine:
                await player.probe.close_window()
            else:
                await self.close_game(player.game, player.probe)
            await self.poll_until(lambda g=player.game: g.process.returncode is not None, 30)
        await self.poll_until(lambda: not any(p.worker.busy for p in players), 120)
        codes = [p.game.process.returncode for p in players]
        require(codes == [0] * len(players), f"ordinary SDL exit failed: {codes}")
        for player in players:
            with MirrorLease(player.mirror):
                pass
        return codes

    def finish(self):
        with self.host.open_store() as store:
            store.integrity_check()
        require([sha(p) for p in self.sources] == self.source_hashes, "a source save changed")
        self.completed = True
        self.record("store integrity check passed; source saves unchanged")


async def launcher_proof(args, *, names, sources, party_counts, match, version, settings=None, scope=None,
                         after_boot=None, environment=None, after_save=None, on_harness=None, after_continue=None):
    """World and enrollment, then two phases of real launcher workers (host, then
    each friend): `match(current, probes, games, host, symbols, record)` and manual
    saves in the first, then `after_save(current, host, record)` if given, fresh
    Continue in the second (every process started again, the world's host first; then
    `after_continue(current, probes, host, record)` if given: what the restarted world
    kept); both end with a normal close, friends first.
    `on_harness(harness)` gets the harness first (a match that closes and restarts a
    player's game: `harness.players` is the phase's players; a match that replaces one
    updates the lists it was given in place)."""
    if os.environ.get("PROOF_LIGHT_3D") == "1":
        # --game is the 3D build: the light settings of native_launcher_battle_3d_proof.py (software OpenGL here)
        from native_launcher_battle_3d_proof import LIGHT_3D_SETTINGS
        settings = LIGHT_3D_SETTINGS
    harness = LauncherHarness(args, names=names, sources=sources, party_counts=party_counts, version=version,
                              settings=settings, scope=scope, after_boot=after_boot, environment=environment)
    if on_harness is not None:
        on_harness(harness)
    async with harness:
        await harness.setup_world()
        host, expected, record = harness.host, harness.expected, harness.record
        saved, revisions = [], [2] * harness.count
        for phase in ("battle-and-save", "fresh-Continue"):
            players = []
            for slot in range(harness.count):
                player = await harness.start(phase, slot)
                players.append(player)
                require(await harness.ready(player) == (1 if phase == "battle-and-save" else revisions[slot]),
                        "startup revision differs")
            current = [p.worker for p in players]
            games = [p.game for p in players]
            probes = [p.probe for p in players]
            record("actual-launcher-workers-ready", phase=phase, pids=[g.process.pid for g in games],
                   load_average=load_average())
            if phase == "fresh-Continue" and after_continue is not None:
                await after_continue(current, probes, host, record)
            if phase == "battle-and-save":
                harness.players = players
                from proof_network import apply_environment
                await apply_environment(current, record)      # PROOF_LATENCY_MS and the others (none by default)
                outcome = await match(current, probes, games, host, harness.symbols, record)
                if isinstance(outcome, dict) and "expected" in outcome:
                    # A battle that changes parties (co-op experience): its own
                    # game's new party is what the next save must hold.
                    # (Owned serials never change with experience.)
                    expected[:] = [dict(old, count=new["count"], box_crc=new["box_crc"])
                                   for old, new in zip(expected, outcome["expected"])]
                    if "revisions" in outcome:
                        # A match that saved on its way (the Tower Duo's floors): the revision the closing save makes.
                        revisions = list(outcome["revisions"])
                    record("expected-parties-after-the-match", parties=expected, revisions=revisions)
                if isinstance(outcome, dict) and "parties" in outcome:
                    # A match that trades: the canonical parties (and their owned serials) it left, and the
                    # revision the next save makes (a trade applies at base + 2).
                    expected[:] = outcome["parties"]
                    revisions = list(outcome["revisions"])
                    record("expected-parties-after-the-match", parties=expected, revisions=revisions)
                for slot, player in enumerate(players):
                    await harness.save(player, revisions[slot])
                record("all-saved-after-the-battle", revisions=revisions, players=harness.count)
                if after_save is not None:
                    await after_save(current, host, record)
            async def heads(s):
                rows = []
                for slot, account in enumerate(host.accounts):
                    head = inspect_closed_head(s._store, account.player_id)
                    require(head.revision == revisions[slot] and party(head) == expected[slot], "canonical party or revision changed")
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
            codes = await harness.close(list(reversed(players)))  # friends, then host
            record("normal-close", phase=phase, exit_codes=codes)
        harness.finish()


async def run(args):
    await launcher_proof(args, names=("Battle Host", "Battle Friend"), sources=(args.source_a, args.source_b),
                         party_counts=(2, 1), match=native_menu_match, version="Native 1v1 proof")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True,
                        help="native Linux executable, unstripped (or the Windows exe with --wine)")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-a", type=Path, required=True)
    parser.add_argument("--source-b", type=Path, required=True)
    parser.add_argument("--display", action="append", required=True, help="an X display per player (twice)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--wine", type=Path, action="append", help="a Wine prefix per player: Windows clients")
    parser.add_argument("--sdl", type=Path, help="SDL2.dll for the Windows game")
    parser.add_argument("--elf", type=Path, help="the Linux build of the same engine commit (symbol sizes)")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
