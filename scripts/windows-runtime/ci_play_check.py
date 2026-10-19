"""Create a character, Solo, Host World and Join Friend on an INSTALLED EmeraldTogether, played through its menu window and the
real game (Windows runner, CI only); or the same steps with the Linux game on X displays (--linux: a rehearsal on a Linux PC).

    python ci_play_check.py --setup EmeraldTogether-Setup-X.exe --work <new folder> [--label play]
    python ci_play_check.py --linux --game <pokeemerald-mp> --rom <pokedev.gba> --manifest <game-manifest.json>
                            --display :94 --display :95 --work <new folder> [--label play]

What it does, as two players on one PC would (two new profiles: a host and a friend; both menus open at once):

  1. Windows: installs the Setup file silently into <work>\\<label>-EmeraldTogether (LOCALAPPDATA = the host's profile; the friend
     starts the same installed program with their own profile). Linux: the Linux game is set up as the launcher's runtime.
  2. host, then friend: Characters > Create a new character > Create my character. The game opens on its New Game; the check
     presses A (Birch's speech, the name, the starter) until the game has saved the new trainer, then closes the game window.
  3. host: Solo > New world ("World 1", the name offered). The character enters it: the game opens on the character, the check
     chooses CONTINUE and the game closes by itself once the world has saved the character (revision 1). Then the Solo game:
     CONTINUE, "Save now" in the menu window (revision 2), close the game.
  4. host: Host World > Create a new world (this PC's local-network address), copies the first friend's invite code, then Host
     this world now: the character enters this world too (revision 1), then the hosted game: CONTINUE, "Save now" (revision 2).
     The game stays open.
  5. friend: Join Friend > Join with an invite code, types the copied code, Check and join: the friend's character enters the
     host's world over the connection (the host's world records the friend's account at revision 1), then the friend's game:
     CONTINUE, "Save now" (revision 2 in the host's world). The friend closes the game, then the host.
  6. both menus Exit with code 0; no error was recorded (shell/last-error.txt) and every character's latest save is the one
     its world holds.

On a PC whose graphics cannot run 3D (a hosted runner has Windows' OpenGL 1.1 software renderer) every game start first shows
"3D graphics cannot start"; the check chooses "Play in Classic 2D this time" there, once, as a player would.

How it plays: keys go to each window as the messages a keyboard produces (Windows: WM_KEYDOWN/WM_KEYUP/WM_CHAR posted to that
window; Linux: xdotool on that display); nobody types on the PC. The game's keys are the defaults (A = Z, Start = Enter). Before
a key, the check waits for the screen it means to answer: the launcher writes each screen it shows to a file when
EMERALD_SHELL_SCREEN_LOG names one (shell_protocol.SCREEN_LOG; automated checks only). Results come from the files the launcher
and the worlds write (characters, worlds.json, each world's database, last-error.txt, the games' runtime.log), the clipboard and
the process list. Writes <work>/<label>-play-check.json, the screen logs and pictures.

--loopback hosts the world on "This PC only" (Network row) and the friend joins over 127.0.0.1: for a PC whose only address is
one an invitation refuses (the cloud Linux workspace has only 192.0.2.2, a documentation address).

What it cannot say: one PC plays both players over its own network address (no second PC, no router, no Internet); a hosted
runner has no graphics card, so the games run in Classic 2D on Windows' software renderer; nothing about audio or a controller.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(HERE)]

from emerald_multiplayer.shell_protocol import SCREEN_LOG  # noqa: E402

RULE = "gen6-stable-world-region-v1"
INTRO_SAVED = "intro: saved (status 1)"


class CheckFailed(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailed(message)


def wait(condition, seconds, step=1.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(step)
    return condition()


# ------------------------------------------------------------------ the desk: windows, keys and processes (Windows or Linux)

class WindowsDesk:
    """The installed program; keys are posted to the windows (ci_world_check's helpers)."""

    GAME_KEYS = dict(a=0x5A, b=0x58, start=0x0D)

    def __init__(self, exe):
        self.exe = exe

    def launch(self, profile, screen_log):
        import ci_world_check as w
        w._user32().SetCursorPos(0, 0)            # a pointer resting over the menu would move its focus
        env = dict(os.environ, LOCALAPPDATA=str(profile), **{SCREEN_LOG: str(screen_log)})
        return subprocess.Popen([str(self.exe)], env=env, cwd=str(Path(self.exe).parent))

    def children(self, pid):
        import ci_world_check as w
        return w.children(pid)

    def window(self, pid):
        import ci_world_check as w
        return w.window_of(pid)

    def _post(self, hwnd, vk, down=True, up=True, hold=0.0):
        import ci_world_check as w
        user32 = w._user32()
        scan = user32.MapVirtualKeyW(vk, 0)
        lparam = 1 | (scan << 16) | ((1 << 24) if vk in w._EXTENDED else 0)
        if down:
            require(user32.PostMessageW(hwnd, 0x0100, vk, lparam), "a window refused a key")
        if hold:
            time.sleep(hold)
        if up:
            user32.PostMessageW(hwnd, 0x0101, vk, lparam | (1 << 30) | (1 << 31))

    def menu_key(self, hwnd, name):
        import ci_world_check as w
        self._post(hwnd, w.VK[name])

    def menu_text(self, hwnd, text):
        import ci_world_check as w
        user32 = w._user32()
        for ch in text:
            user32.PostMessageW(hwnd, 0x0102, ord(ch), 1)
            time.sleep(0.04)

    def game_key(self, hwnd, name, hold=0.12):
        self._post(hwnd, self.GAME_KEYS[name], hold=hold)

    def close_game(self, pid, hwnd):
        import ci_world_check as w
        w._user32().PostMessageW(hwnd, 0x0010, 0, 0)             # WM_CLOSE: the window's close button

    def alive(self, pid):
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel32.CloseHandle(handle)

    def clipboard(self):
        import ci_world_check as w
        return w.clipboard_text()

    def clear_clipboard(self):
        import ci_world_check as w
        w.clear_clipboard()

    def picture(self, path, display=None):
        import ci_world_check as w
        w.screenshot(path)

    def kill(self, process):
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=60, check=False)


class LinuxDesk:
    """The launcher's own code with the Linux game (a rehearsal of the Windows check); xdotool on each player's X display."""

    KEYS = dict(down="Down", up="Up", home="Home", end="End", enter="Return", escape="Escape", tab="Tab", backspace="BackSpace")
    GAME_KEYS = dict(a="z", b="x", start="Return")

    def __init__(self, application, displays):
        self.application, self.displays = application, displays
        self.display_of = {}

    def launch(self, profile, screen_log):
        display = self.displays[len(self.display_of)]
        env = dict(os.environ, DISPLAY=display, SDL_AUDIODRIVER="dummy", **{SCREEN_LOG: str(screen_log)})
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests"), str(HERE)])
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--linux-app", str(self.application),
                                    str(profile)], env=env, cwd=str(profile))
        self.display_of[process.pid] = display
        return process

    def _env(self, pid):
        return dict(os.environ, DISPLAY=self._display(pid))

    def _display(self, pid):
        while pid not in self.display_of:
            try:
                pid = int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
            except (OSError, ValueError, IndexError):
                return self.displays[0]
        return self.display_of[pid]

    def children(self, pid):
        found = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                parent = int((entry / "stat").read_text().rsplit(")", 1)[1].split()[1])
                if parent == pid:
                    command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
                    found.append((int(entry.name), command))
            except (OSError, ValueError, IndexError):
                continue
        return found

    def window(self, pid):
        result = subprocess.run(["xdotool", "search", "--onlyvisible", "--pid", str(pid)], env=self._env(pid),
                                capture_output=True, text=True)
        windows = result.stdout.split()
        return (pid, windows[-1]) if windows else None

    def _focus(self, handle):
        subprocess.run(["xdotool", "windowfocus", "--sync", handle[1]], env=self._env(handle[0]), capture_output=True, timeout=10)

    def menu_key(self, handle, name):
        self._focus(handle)
        subprocess.run(["xdotool", "key", self.KEYS[name]], env=self._env(handle[0]), check=True)

    def menu_text(self, handle, text):
        self._focus(handle)
        subprocess.run(["xdotool", "type", "--delay", "40", text], env=self._env(handle[0]), check=True)

    def game_key(self, handle, name, hold=0.12):
        self._focus(handle)
        # Keys go to the focused window: when the game has just closed, the menu has the focus and would take the key.
        focused = subprocess.run(["xdotool", "getwindowfocus"], env=self._env(handle[0]), capture_output=True, text=True)
        if focused.stdout.strip() != handle[1]:
            raise CheckFailed("the game window does not have the focus")
        key = self.GAME_KEYS[name]
        subprocess.run(["xdotool", "keydown", key], env=self._env(handle[0]), check=True)
        time.sleep(hold)
        subprocess.run(["xdotool", "keyup", key], env=self._env(handle[0]), check=True)

    def close_game(self, pid, handle):
        os.kill(pid, signal.SIGTERM)                              # SDL turns it into a quit, as a close button does

    def alive(self, pid):
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (OSError, IndexError):
            return False
        return state != "Z"

    def clipboard(self):
        env = dict(os.environ, DISPLAY=self.displays[0])
        result = subprocess.run([sys.executable, "-c", "import tkinter; r = tkinter.Tk(); r.withdraw(); print(r.clipboard_get())"],
                                env=env, capture_output=True, text=True, timeout=20)
        return result.stdout.strip()

    def clear_clipboard(self):
        pass

    def picture(self, path, display=None):
        for screen in ([display] if display else self.displays):
            target = path if display or len(self.displays) == 1 else path.with_name(f"{path.stem}-{screen[1:]}{path.suffix}")
            subprocess.run(["import", "-window", "root", str(target)], env=dict(os.environ, DISPLAY=screen), capture_output=True)

    def kill(self, process):
        for pid, _ in self.children(process.pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.kill()


# ------------------------------------------------------------------ one player: their profile, menu and games

class Player:
    def __init__(self, check, name, profile):
        self.check, self.desk, self.name, self.profile = check, check.desk, name, profile
        self.private = profile / "PokemonPrivate" / "launcher"
        self.screen_log = check.work / f"{check.label}-{name}-screens.jsonl"
        self.process = None
        self.menu = None
        self.mark = 0
        self.games = []

    def log(self, text):
        self.check.log(f"{self.name}: {text}")

    # The menu ----------------------------------------------------------
    def start(self):
        if not self.private.is_dir():
            self.private.mkdir(parents=True)
        self.mark = len(self.screens())
        self.process = self.desk.launch(self.profile, self.screen_log)
        shell = wait(lambda: next((pid for pid, command in self.desk.children(self.process.pid) if "--shell" in command), None), 120)
        require(shell, f"{self.name}: the menu window did not start (launcher exit code {self.process.poll()})")
        self.menu = wait(lambda: self.desk.window(shell), 60)
        require(self.menu, f"{self.name}: the menu window did not appear")
        self.shell_pid = shell
        self.expect("main", 90)
        self.log(f"menu window open (launcher pid {self.process.pid}, menu pid {shell})")

    def screens(self):
        try:
            text = self.screen_log.read_text(encoding="utf-8")
        except OSError:
            return []
        return [json.loads(line) for line in text.splitlines() if line.strip().endswith("}")]

    def current(self):
        shown = self.screens()
        return shown[-1] if shown else None

    def expect(self, ids, seconds=60, where=None):
        """The next screen with one of these ids shown after the last key (and ``where(screen)``); fails with what is up."""
        ids = (ids,) if isinstance(ids, str) else tuple(ids)

        def found():
            shown = self.screens()
            for screen in shown[self.mark:]:
                if screen["id"] in ids and (where is None or where(screen)):
                    latest = shown[-1]
                    return latest if latest["id"] in ids and (where is None or where(latest)) else None
            return None
        screen = wait(found, seconds, step=0.25)
        if not screen:
            latest = self.current()
            raise CheckFailed(f"{self.name}: expected the {'/'.join(ids)} screen; the menu shows "
                              f"{latest and (latest['id'], latest['title'], latest['status'], latest['notes'][:4])}")
        time.sleep(0.8)                            # the window draws it before the next key arrives
        return screen

    def key(self, name, times=1):
        for _ in range(times):
            self.mark = len(self.screens())
            self.desk.menu_key(self.menu, name)
            time.sleep(0.25)

    def text(self, value):
        self.desk.menu_text(self.menu, value)
        time.sleep(0.3)

    def choose(self, screen, item_id):
        """Move the focus from where the window puts it (the last item marked "s", else the first that is not disabled) to the item
        and press Enter."""
        items = screen["items"]
        focusable = [i for i, item in enumerate(items) if "d" not in item[3]]
        starts = [i for i in focusable if "s" in items[i][3]]
        start = starts[-1] if starts else focusable[0]
        target = next((i for i, item in enumerate(items) if item[1] == item_id), None)
        require(target in focusable, f"{self.name}: no {item_id!r} to choose on {screen['id']}: {[i[2] for i in items]}")
        steps = focusable.index(target) - focusable.index(start)
        self.key("down" if steps > 0 else "up", abs(steps))
        self.key("enter")

    def picture(self, label):
        self.check.picture(f"{self.name}-{label}")

    # The games ---------------------------------------------------------
    def game(self, seconds=90):
        """The game the menu just started (not the menu, not the 3D check): (pid, window)."""
        known = {pid for pid, _ in self.games}

        def started():
            for pid, command in self.desk.children(self.process.pid):
                if pid not in known and pid != self.shell_pid and "--shell" not in command and "--probe-graphics" not in command:
                    window = self.desk.window(pid)
                    if window:
                        return pid, window
            return None
        found = wait(started, seconds, step=1.0)
        require(found, f"{self.name}: no game window opened (last screen {self.current() and self.current()['id']})")
        self.games.append(found)
        return found

    def press_until(self, game, key, until, seconds, every=0.8):
        """Press a game key every ``every`` seconds until ``until()`` (or the game ends); returns until()'s last value."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            value = until()
            if value or not self.desk.alive(game[0]):
                return value or until()
            try:
                self.desk.game_key(game[1], key)
            except (CheckFailed, subprocess.CalledProcessError):
                pass                                # the window is closing
            time.sleep(every)
        return until()

    def graphics_choice(self, seconds=45):
        """After a start: the 3D question (this PC cannot run 3D) is answered with Classic 2D; otherwise nothing to do."""
        screen = self.expect(("graphics", "busy", "session"), seconds,
                             where=lambda s: s["id"] != "busy" or s["title"] != "Checking graphics")
        if screen["id"] == "graphics":
            self.check.report.setdefault("graphics", []).append(screen["notes"][:3])
            self.choose(screen, "classic")
            self.log("3D graphics cannot start here: chose Play in Classic 2D this time")
            return "2d"
        return None

    # What the files say ------------------------------------------------
    def characters(self):
        root = self.private / "characters"
        found = []
        for path in sorted(root.glob("*/character.json")) if root.is_dir() else []:
            try:
                found.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        return found

    def worlds(self):
        try:
            return json.loads((self.private / "shell" / "worlds.json").read_text(encoding="utf-8"))["worlds"]
        except (OSError, ValueError, KeyError):
            return []

    def world(self, name):
        entry = next((w for w in self.worlds() if w["name"] == name), None)
        if entry is None:
            return None
        folder = self.private / "worlds" / entry["folder"]
        descriptor = json.loads((folder / "host.json").read_text(encoding="utf-8"))
        return dict(entry, directory=folder, descriptor=descriptor, accounts=descriptor["accounts"])

    def error_text(self):
        try:
            return (self.private / "shell" / "last-error.txt").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""


def revision(world, slot):
    """The latest checkpoint revision of a world account (read only; the world may be running)."""
    player_id = next(account["player_id"] for account in world["accounts"] if account["slot"] == slot)
    try:
        with sqlite3.connect(f"file:{world['directory'] / 'world.sqlite3'}?mode=ro", uri=True, timeout=10) as db:
            row = db.execute("SELECT latest_revision FROM players WHERE player_id=?", (player_id,)).fetchone()
    except sqlite3.Error:
        return None
    return None if row is None else int(row[0])


# ------------------------------------------------------------------ the steps

class PlayCheck:
    def __init__(self, desk, work, label, report, lines, loopback=False):
        self.desk, self.work, self.label, self.report, self.lines = desk, work, label, report, lines
        self.loopback = loopback
        self.pictures = work / f"{label}-pictures"
        self.pictures.mkdir(exist_ok=True)
        self.count = 0

    def log(self, text):
        print(text, flush=True)
        self.lines.append(text)

    def picture(self, label):
        self.count += 1
        self.desk.picture(self.pictures / f"{self.count:02d}-{label}.png")

    def create_character(self, player):
        main = player.expect("main")
        player.choose(main, "characters")
        player.choose(player.expect("characters"), "create")
        drafts = player.private / "drafts"
        before = set(drafts.iterdir()) if drafts.is_dir() else set()
        player.choose(player.expect("create_character"), "go")
        player.graphics_choice()
        game = player.game()
        player.log(f"New Game: the game opened (pid {game[0]})")
        folder = wait(lambda: next(iter(set(drafts.iterdir()) - before), None) if drafts.is_dir() else None, 30)
        require(folder, f"{player.name}: the New Game has no drafts folder")
        log_file = folder / "runtime.log"
        saved = player.press_until(game, "a", lambda: log_file.is_file() and INTRO_SAVED in log_file.read_text("utf-8", "replace"),
                                   600)
        player.picture("new-game-saved")
        require(saved, f"{player.name}: the New Game did not save its trainer within ten minutes "
                       f"(runtime.log: {log_file.read_text('utf-8', 'replace')[-600:] if log_file.is_file() else 'none'})")
        time.sleep(3)
        player.desk.close_game(game[0], game[1])
        made = wait(lambda: player.characters(), 90)
        require(made, f"{player.name}: no character after the New Game was closed (last screen {player.current()['id']})")
        (character,) = made
        player.expect("characters", 30)
        player.log(f"created character {character['name']} (party from the New Game; {len(made)} in the library)")
        self.report.setdefault("characters", {})[player.name] = character["name"]
        player.key("escape")
        return character

    def enter_and_play(self, player, world, slot, *, host_world=None, keep_open=False):
        """After "<character> enters <world>": the registration game (CONTINUE; closes by itself), then the session game
        (CONTINUE, Save now). ``host_world``: the world's record when it is on another profile (a friend)."""
        record = host_world or world
        screen = player.expect("bring_character", 180)
        player.choose(screen, "go")
        player.graphics_choice()
        game = player.game()
        player.log(f"entering {world['name']}: the game opened on the character (pid {game[0]}); choosing CONTINUE")
        player.press_until(game, "a", lambda: not player.desk.alive(game[0]), 300)
        require(not player.desk.alive(game[0]), f"{player.name}: the registration game did not close by itself within five minutes "
                                                 f"(last screen {player.current() and player.current()['notes'][:2]})")
        first = wait(lambda: revision(record, slot), 30)
        if not first:
            after = player.expect(("message", "solo", "host_list", "join_list", "main", "busy", "graphics", "session"), 60)
            raise CheckFailed(f"{player.name}: the registration game ended and the world has no save of the character "
                              f"(revision {first}); the menu shows {after['id']}: {after['title']} {after['notes'][:4]}")
        player.log(f"the character entered {world['name']} (the world saved it: revision {first}); the game closed by itself")
        player.graphics_choice()
        game = player.game()
        player.log(f"playing {world['name']}: the game opened (pid {game[0]}); choosing CONTINUE")
        saved = None
        for attempt in range(4):
            player.press_until(game, "a", lambda: False, 40 if attempt == 0 else 10)
            screen = player.expect("session", 60, where=lambda s: any(item[1] == "save" for item in s["items"]))
            require(player.desk.alive(game[0]), f"{player.name}: the game closed while playing")
            player.choose(screen, "save")
            saved = wait(lambda: (revision(record, slot) or 0) > first and revision(record, slot), 45)
            if saved:
                break
        player.picture(f"playing-{world['name'].split()[0].lower()}")
        require(saved, f"{player.name}: Save now did not save to the world (revision still {revision(record, slot)})")
        session = player.current()
        player.log(f"Save now: the world saved the character (revision {first} -> {saved}); "
                   f"the menu says: {' '.join(session['notes'][1:3])}")
        result = dict(world=world["name"], slot=slot, registered=first, saved=saved, notes=session["notes"][:4])
        if keep_open:
            return game, result
        self.close(player, game)
        return None, result

    def close(self, player, game):
        player.desk.close_game(game[0], game[1])
        require(wait(lambda: not player.desk.alive(game[0]), 60), f"{player.name}: the game did not close")
        player.log("closed the game window")

    def solo(self, host):
        main = host.expect("main")
        host.choose(main, "solo")
        host.choose(host.expect("solo"), "new")
        screen = host.expect(("ask_text", "trade_rule"))
        if screen["id"] == "trade_rule":
            host.choose(screen, RULE)
            screen = host.expect("ask_text")
        host.key("enter")                          # the name offered ("World 1"): the field's Enter moves to Save
        host.key("enter")
        world = wait(lambda: host.world(host.worlds()[-1]["name"]) if host.worlds() else None, 60)
        require(world and world["kind"] == "adventure", f"{host.name}: no Solo world was created")
        host.log(f"Solo: created {world['name']} (this PC only: listens on {world['bind_address']})")
        _, result = self.enter_and_play(host, world, 0)
        host.expect("main", 60)
        return result

    def host(self, host):
        main = host.expect("main")
        host.choose(main, "host")
        host.choose(host.expect("host_list"), "create")
        form = host.expect("create_world")
        fields = {item[1]: i for i, item in enumerate(form["items"])}
        require("name" in fields, f"{host.name}: the create form has no world name")
        host.key("backspace", 40)
        host.text("CI Hosted World")
        host.key("enter")                          # Your name
        host.key("backspace", 30)
        host.text("Host")
        host.key("enter")                          # Port (kept)
        host.key("enter")                          # the Network row (the default: this PC's local-network address)
        if self.loopback:
            host.key("enter")                      # Network: This PC only (the friend plays on this PC too)
            host.choose(host.expect("choose"), "127.0.0.1")
            host.choose(host.expect("create_world"), "create")
        else:
            focusable = [item[1] for item in form["items"] if "d" not in item[3]]
            host.key("down", focusable.index("create") - focusable.index("network"))
            host.key("enter")                      # Create world
        world = wait(lambda: host.world("CI Hosted World"), 120)
        require(world, f"{host.name}: the hosted world was not created ({host.current() and host.current()['notes'][:2]})")
        require((world["bind_address"] == "127.0.0.1") == self.loopback,
                f"{host.name}: the world listens on {world['bind_address']}")
        host.log(f"Host World: created {world['name']} (listens on {world['bind_address']}:{world['descriptor']['port']})")
        screen = host.expect("world", 60)
        host.choose(screen, "codes")
        codes = host.expect("codes")
        self.desk.clear_clipboard()
        host.choose(codes, codes["items"][0][1])
        code = wait(lambda: self.desk.clipboard().strip() or None, 20)
        require(code, f"{host.name}: no invite code was copied")
        from emerald_multiplayer.invite_code import decode_invite
        decoded = decode_invite(code)
        require((decoded.port, decoded.world_id) == (world["descriptor"]["port"], world["world_id"]),
                f"{host.name}: the invite code points at {decoded.address}:{decoded.port}")
        host.log(f"copied the invite code for {codes['items'][0][2]}: {decoded.address}:{decoded.port}, slot {decoded.slot}")
        host.expect("codes", 10)
        host.key("escape")
        host.choose(host.expect("world"), "host")
        game, result = self.enter_and_play(host, world, 0, keep_open=True)
        return world, code, decoded.slot, game, result

    def join(self, friend, code, host_world, slot):
        main = friend.expect("main")
        friend.choose(main, "join")
        friend.choose(friend.expect("join_list"), "new")
        friend.expect("join_new")
        friend.text(code)
        for _ in ("name", "address", "port"):
            friend.key("enter")
        friend.key("enter")                        # Check and join
        friend.log("Join Friend: typed the invite code, Check and join")
        world = dict(name=host_world["name"])
        _, result = self.enter_and_play(friend, world, slot, host_world=host_world)
        friend.expect("join_list", 60)
        return result

    def finish(self, player):
        """Back to the main menu and Exit."""
        for _ in range(4):
            screen = player.current()
            if screen and screen["id"] == "main":
                break
            player.key("escape")
            time.sleep(1.5)
        player.expect("main", 30)
        player.key("escape")
        wait(lambda: player.process.poll() is not None, 60)
        require(player.process.poll() == 0, f"{player.name}: Exit should end EmeraldTogether with code 0, got {player.process.poll()}")
        player.log("Exit closed EmeraldTogether (code 0)")


def run(check, host, friend):
    report = check.report
    host.start()
    friend.start()
    check.picture("menus")
    host_character = check.create_character(host)
    friend_character = check.create_character(friend)
    report["solo"] = check.solo(host)
    world, code, slot, host_game, report["host"] = check.host(host)
    report["join"] = check.join(friend, code, world, slot)
    check.picture("after-join")
    check.close(host, host_game)
    host.expect("host_list", 60)
    # Every character's latest save is its world's.
    for player, character, name in ((host, host_character, world["name"]), (friend, friend_character, world["name"])):
        (latest,) = player.characters()
        require(latest["character_id"] == character["character_id"], f"{player.name}: the character changed identity")
        require(latest["current"]["world_id"] == world["world_id"],
                f"{player.name}: the character's latest save is not from {name} ({latest['current']['world_id']})")
    check.log("both characters' latest saves are the hosted world's")
    for player in (friend, host):
        check.finish(player)
    for player in (host, friend):
        require(player.error_text() == "", f"{player.name}: an error was recorded: {player.error_text()[-2000:]}")
    check.log("no error was recorded in either profile")


# ------------------------------------------------------------------ set-up: the installed program (Windows) or the Linux game

def seed_rule(player):
    """The trade friendship rule remembered (asked once per profile; the same rows on every build)."""
    prefs = player.private / "shell" / "preferences.json"
    prefs.parent.mkdir(parents=True, exist_ok=True)
    prefs.write_text(json.dumps({"format": "emerald-shell-preferences-v1", "trade_rule": RULE}), encoding="utf-8")


def linux_application(args, work):
    """The Linux game as the launcher's runtime (what native_launcher_battle_proof.py sets up)."""
    from collect_native_bundle import collect
    staging = work / "linux-game"
    staging.mkdir()
    (staging / "pokeemerald-mp.exe").write_bytes(args.game.read_bytes())
    (staging / "pokeemerald-mp.exe").chmod(0o755)
    (staging / "SDL2.dll").write_bytes(b"Linux rehearsal: the Linux game links the system's libSDL2.\n")
    info = collect(staging / "pokeemerald-mp.exe", staging / "SDL2.dll", args.rom, work / "application" / "runtime")
    (Path(info["directory"]) / "pokeemerald-mp.exe").chmod(0o755)
    sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    application = work / "application" / "installation.json"
    application.write_text(json.dumps(dict(runtime=info["directory"], runtime_sha256=info["manifest_sha256"],
                                           rom=str(args.rom.resolve()), rom_sha256=sha(args.rom),
                                           manifest=str(args.manifest.resolve()), manifest_sha256=sha(args.manifest))))
    return application


def linux_app(application, profile):
    """--linux-app: the menu as EmeraldTogether.exe runs it (shell_app.main), with this PC's Linux game."""
    from emerald_multiplayer.launcher_gui import SessionWorker
    from emerald_multiplayer.launcher_session import GameInstallation
    from emerald_multiplayer.player_runtime import RuntimeBundle
    from emerald_multiplayer.shell_app import ShellApp
    from emerald_multiplayer.shell_protocol import ShellProcess
    record = json.loads(Path(application).read_text())
    installation = GameInstallation(Path(record["rom"]), Path(record["manifest"]), record["rom_sha256"], record["manifest_sha256"],
                                    RuntimeBundle(Path(record["runtime"]), record["runtime_sha256"]))
    private = (Path(profile) / "PokemonPrivate" / "launcher").resolve()
    private.mkdir(parents=True, exist_ok=True)
    executable, _ = installation.bundle.verify()
    shell = ShellProcess([str(executable), "--shell"], cwd=private)
    app = ShellApp(installation, private, shell, version="Linux rehearsal", worker=SessionWorker(installation, private))
    try:
        return app.run()
    finally:
        shell.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--setup", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--label", default="play")
    parser.add_argument("--linux", action="store_true")
    parser.add_argument("--game", type=Path)
    parser.add_argument("--rom", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--display", action="append", default=[])
    parser.add_argument("--loopback", action="store_true",
                        help="host on this PC only (a PC whose only address is not one invitations take, e.g. 192.0.2.x)")
    parser.add_argument("--linux-app", nargs=2, metavar=("INSTALLATION", "PROFILE"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.linux_app:
        raise SystemExit(linux_app(*args.linux_app))
    require(args.work is not None, "--work is required")
    work = args.work.resolve()
    require(not work.exists() or not any(work.iterdir()), "choose a new, empty --work folder")
    work.mkdir(parents=True, exist_ok=True)
    report = dict(format="emerald-play-check-v1", label=args.label, platform="linux rehearsal" if args.linux else "windows",
                  setup=args.setup.name if args.setup else None)
    lines = []
    target = work / f"{args.label}-EmeraldTogether"
    check = host = friend = None
    try:
        if args.linux:
            require(args.game and args.rom and args.manifest and len(args.display) == 2, "--linux needs --game, --rom, --manifest "
                                                                                         "and two --display")
            desk = LinuxDesk(linux_application(args, work), args.display)
        else:
            require(os.name == "nt" and args.setup is not None, "this check runs on Windows with --setup (or use --linux)")
            import ci_world_check as w
            env = dict(os.environ, LOCALAPPDATA=str(work / "host-profile"))
            w.install(args.setup.resolve(), target, env, work, args.label)
            desk = WindowsDesk(target / "EmeraldTogether.exe")
        check = PlayCheck(desk, work, args.label, report, lines, loopback=args.loopback)
        report["hosted_on"] = "this PC only (--loopback)" if args.loopback else "this PC's local-network address"
        check.log(f"{report['platform']}: {'installed ' + args.setup.name + ' into ' + str(target) if not args.linux else 'Linux game'}")
        host = Player(check, "host", work / "host-profile")
        friend = Player(check, "friend", work / "friend-profile")
        for player in (host, friend):
            player.private.mkdir(parents=True, exist_ok=True)
            seed_rule(player)
        run(check, host, friend)
        report["result"] = "passed"
    except CheckFailed as error:
        report["result"] = "failed: " + str(error)
        print("check failed: " + str(error), flush=True)
        lines.append("check failed: " + str(error))
        if check is not None:
            check.picture("failure")
    finally:
        for player in (host, friend):
            if player is not None and player.process is not None and player.process.poll() is None:
                player.desk.kill(player.process)
            if player is not None:
                for name in ("runtime.log",):
                    logs = [*(player.private / "launches").glob(f"*/{name}"), *(player.private / "drafts").glob(f"*/{name}")] \
                        if player.private.is_dir() else []
                    for path in sorted(logs, key=lambda path: path.stat().st_mtime)[-3:]:
                        tail = [line for line in path.read_text("utf-8", "replace").splitlines() if line.strip()][-8:]
                        report.setdefault("game_logs", {}).setdefault(player.name, []).append(dict(folder=path.parent.name, tail=tail))
                error = player.error_text()
                if error:
                    report.setdefault("errors", {})[player.name] = error[-3000:]
                if report.get("result") != "passed":
                    # The job log is what a reader of a failed run sees first: the last screens and the newest games' output.
                    for screen in player.screens()[-6:]:
                        print(f"  {player.name} screen: {screen['id']} | {screen['title']} | {screen['status']} | "
                              f"{' '.join(screen['notes'][:3])[:300]}", flush=True)
                    for entry in report.get("game_logs", {}).get(player.name, []):
                        for line in entry["tail"]:
                            print(f"  {player.name} game {entry['folder'][:8]}: {line[:240]}", flush=True)
                    if error:
                        print(f"  {player.name} last-error.txt: {error[-1500:]}", flush=True)
        report["log"] = lines
        (work / f"{args.label}-play-check.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if not args.linux and target.exists():
            import ci_world_check as w
            w.uninstall(target, work, args.label)
    if report["result"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
