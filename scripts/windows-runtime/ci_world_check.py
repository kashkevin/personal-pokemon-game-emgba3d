"""Host World > Create World on an INSTALLED EmeraldTogether, driven through its real menu window (Windows runner, CI only).

    python ci_world_check.py --setup EmeraldTogether-Setup-X.exe --work <new folder> --profile <folder> --expect fixed|crash
                             [--label name] [--leave-installed] [--delete-install]

What it does, as a player would:

  1. installs the Setup file silently into <work>\\EmeraldTogether with LOCALAPPDATA = --profile (a temporary player profile;
     it may already hold what an earlier version left there: that is the "leftover AppData" case);
  2. if the profile has no character yet, adds one the way a character made earlier would be kept (the library under
     PokemonPrivate\\launcher; a character is required before Host World), and remembers a trade friendship rule (so the
     form has the same rows on every build);
  3. starts the installed EmeraldTogether.exe and plays its in-game menu window (the game's own executable running
     ``--shell``) with keyboard messages sent to that window: Host World > Create a new world, once on the default network
     (this PC's local-network address) and once with a numeric public address typed in;
  4. --expect crash (the build of 2026-10-19, run 39180878911): passes only if the reported failure appears: the first world
     is refused with the misleading character-setup message and nothing is created, and the second world is created on disk
     while shell/last-error.txt records ``ValueError: invalid world record`` from world_registry;
     --expect fixed: both worlds are created AND in the world list with the local-network address as plain text, then the
     check copies an invite code (decoded: it points at that address), renames a world, deletes the other, starts hosting
     the renamed one up to the game opening for the character (this runner cannot run 3D: the menu asks first and the check
     chooses "Play in Classic 2D this time"), starts EmeraldTogether again and finds the worlds kept, and no error was
     recorded;
  5. --delete-install removes the program folder the way a person deletes it by hand (the profile stays); otherwise the
     check uninstalls silently unless --leave-installed.

The keyboard goes to the menu window as the messages a keyboard produces (WM_KEYDOWN/WM_CHAR posted to that window); no one
types on the runner. Results come from the files the installed launcher writes (worlds.json, the world folders, host.json,
last-error.txt), the clipboard and the process list. Writes <work>\\<label>-world-check.json and desktop pictures.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

PUBLIC_ADDRESS = "81.2.69.160"          # only written into the world's certificate and invite codes; nothing is sent to it
RULE = "gen6-stable-world-region-v1"


class CheckFailed(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailed(message)


# ------------------------------------------------------------------ Windows: processes, windows, keyboard messages, clipboard

def _user32():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    user32.MapVirtualKeyW.restype = wintypes.UINT
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    return user32


VK = dict(down=0x28, up=0x26, left=0x25, right=0x27, home=0x24, end=0x23, enter=0x0D, escape=0x1B, tab=0x09, backspace=0x08)
_EXTENDED = {0x25, 0x26, 0x27, 0x28, 0x24, 0x23}


def processes():
    """[(pid, parent pid, command line)] of every process (PowerShell/CIM: Python has no command lines without extras)."""
    script = ("Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, CommandLine | "
              "ConvertTo-Json -Compress")
    output = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                            text=True, timeout=120, check=False).stdout
    try:
        rows = json.loads(output or "[]")
    except ValueError:
        return []
    rows = [rows] if isinstance(rows, dict) else rows
    return [(int(row["ProcessId"]), int(row["ParentProcessId"]), row.get("CommandLine") or "") for row in rows
            if isinstance(row, dict) and row.get("ProcessId") is not None and row.get("ParentProcessId") is not None]


def children(pid):
    return [(child, command) for child, parent, command in processes() if parent == pid]


def window_of(pid):
    """The visible top-level window of process ``pid`` (the menu's SDL window), or None."""
    import ctypes
    from ctypes import wintypes
    user32 = _user32()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else None


def clipboard_text():
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32 = _user32()
    for _ in range(20):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.2)
    else:
        return ""
    try:
        handle = user32.GetClipboardData(13)                      # CF_UNICODETEXT
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(pointer) if pointer else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def clear_clipboard():
    user32 = _user32()
    if user32.OpenClipboard(None):
        user32.EmptyClipboard()
        user32.CloseClipboard()


def screenshot(path):
    script = ("Add-Type -AssemblyName System.Windows.Forms, System.Drawing; "
              "$b = [System.Windows.Forms.SystemInformation]::VirtualScreen; "
              "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
              "[System.Drawing.Graphics]::FromImage($bmp).CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); "
              f"$bmp.Save('{path}')")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, timeout=60, check=False)


class Menu:
    """The installed launcher and its menu window; keys are posted to that window."""

    def __init__(self, exe, env, work, log, shots):
        self.exe, self.env, self.work, self.log, self.shots = exe, env, work, log, shots
        # The launcher writes each screen it shows here (shell_protocol.SCREEN_LOG; builds before 2026-10-19's play check
        # write nothing, and the check then only waits).
        self.screen_log = Path(shots) / "screens.jsonl"
        self.env = dict(env, EMERALD_SHELL_SCREEN_LOG=str(self.screen_log))
        self.process = None
        self.hwnd = None
        self.shell_pid = None
        self.count = 0

    def start(self):
        user32 = _user32()
        user32.SetCursorPos(0, 0)                  # a pointer resting over the menu would move its focus
        self.process = subprocess.Popen([str(self.exe)], env=self.env, cwd=str(Path(self.exe).parent))
        deadline = time.time() + 120
        while time.time() < deadline:
            require(self.process.poll() is None, f"EmeraldTogether.exe exited early with code {self.process.poll()}")
            shells = [pid for pid, command in children(self.process.pid) if "--shell" in command]
            if shells:
                self.shell_pid = shells[0]
                self.hwnd = window_of(self.shell_pid)
                if self.hwnd:
                    break
            time.sleep(1)
        require(self.hwnd, "the in-game menu window did not open within two minutes (launcher children: "
                           f"{[(pid, command[-80:]) for pid, command in children(self.process.pid)]})")
        time.sleep(6)                              # the first screen (the main menu) after the start-up checks
        self.log(f"menu window open (launcher pid {self.process.pid}, menu pid {self.shell_pid})")
        self.shot("main")

    def key(self, name, times=1, pause=0.35):
        user32 = _user32()
        vk = VK[name]
        scan = user32.MapVirtualKeyW(vk, 0)
        down = 1 | (scan << 16) | ((1 << 24) if vk in _EXTENDED else 0)
        for _ in range(times):
            require(user32.PostMessageW(self.hwnd, 0x0100, vk, down), f"the menu window refused a key ({name})")
            user32.PostMessageW(self.hwnd, 0x0101, vk, down | (1 << 30) | (1 << 31))
            time.sleep(pause)

    def text(self, value):
        user32 = _user32()
        for ch in value:
            user32.PostMessageW(self.hwnd, 0x0102, ord(ch), 1)
            time.sleep(0.05)
        time.sleep(0.3)

    def go(self, name="enter", wait=2.5):
        """A key that opens another screen; waits for it."""
        self.key(name, pause=wait)

    def shot(self, label):
        self.count += 1
        path = self.shots / f"{self.count:02d}-{label}.png"
        screenshot(path)

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def screens(self):
        try:
            text = self.screen_log.read_text(encoding="utf-8")
        except OSError:
            return []
        return [json.loads(line) for line in text.splitlines() if line.strip().endswith("}")]

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], capture_output=True, timeout=60, check=False)
            time.sleep(3)

    def quit(self):
        """Esc from the main menu is Exit: the launcher ends by itself."""
        self.go("escape", wait=1)
        for _ in range(30):
            if self.process.poll() is not None:
                return self.process.returncode
            time.sleep(1)
        return None


# ------------------------------------------------------------------ the player's files

class Files:
    def __init__(self, profile):
        self.private = Path(profile) / "PokemonPrivate" / "launcher"

    @property
    def error_file(self):
        return self.private / "shell" / "last-error.txt"

    def error_text(self):
        try:
            return self.error_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def worlds(self):
        try:
            return json.loads((self.private / "shell" / "worlds.json").read_text(encoding="utf-8"))["worlds"]
        except (OSError, ValueError, KeyError):
            return []

    def world_folders(self):
        root = self.private / "worlds"
        return sorted(p.name for p in root.iterdir() if (p / "host.json").is_file()) if root.is_dir() else []

    def descriptor(self, folder):
        return json.loads((self.private / "worlds" / folder / "host.json").read_text(encoding="utf-8"))

    def named(self, name):
        return next((world for world in self.worlds() if world["name"] == name), None)

    def wait(self, condition, seconds, step=1.0):
        deadline = time.time() + seconds
        while time.time() < deadline:
            value = condition()
            if value:
                return value
            time.sleep(step)
        return condition()


def seed_profile(files, log):
    """A character kept from before (Host World needs one) and a remembered friendship rule, unless the profile has them."""
    from emerald_multiplayer.character_library import CharacterLibrary
    from test_ownership_storage import source_flash
    files.private.mkdir(parents=True, exist_ok=True)
    library = CharacterLibrary(files.private)
    if not library.all():
        library.create(source_flash(personalities=(7,)))
        log("profile: added a character")
    prefs = files.private / "shell" / "preferences.json"
    if not prefs.exists():
        prefs.parent.mkdir(parents=True, exist_ok=True)
        prefs.write_text(json.dumps({"format": "emerald-shell-preferences-v1", "trade_rule": RULE}), encoding="utf-8")
        log("profile: remembered a trade friendship rule")


def install(setup, target, env, work, label):
    code = subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/CURRENTUSER", "/NORESTART", f"/DIR={target}",
                           f"/LOG={work / (label + '-install.log')}"], env=env, timeout=900, check=False).returncode
    require(code == 0, f"Setup exited with code {code}")
    require((target / "EmeraldTogether.exe").is_file(), "no EmeraldTogether.exe after installing")


def uninstall(target, work, label):
    uninstaller = target / "unins000.exe"
    if not uninstaller.is_file():
        return
    subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={work / (label + '-uninstall.log')}"],
                   timeout=600, check=False)
    for _ in range(180):
        if not uninstaller.exists():
            break
        time.sleep(1)


# ------------------------------------------------------------------ the menu steps

def open_create(menu):
    """Main menu > Host World > Create a new world (the first row of both)."""
    menu.key("home")
    menu.key("down")                    # Solo, then Host World (Continue Adventure is off: nothing was played)
    menu.go()
    menu.key("home")
    menu.go()                           # "Create a new world"
    menu.shot("create-form")


def fill_and_create(menu, name, host, *, address=None):
    """On the Create form (focus in the world name): name, your name, keep the port; optionally a public address; Create."""
    menu.key("backspace", 40, pause=0.03)
    menu.text(name)
    menu.key("enter")                   # a field's Enter moves on: Your name
    menu.key("backspace", 30, pause=0.03)
    menu.text(host)
    menu.key("enter")                   # Port (kept)
    menu.key("enter")                   # Network row
    if address is not None:
        menu.key("down", 2)             # Internet access, Public address
        menu.go()
        menu.key("backspace", 60, pause=0.03)
        menu.text(address)
        menu.key("enter")               # to Save
        menu.go()                       # Save: back on the form, focus in the world name (the fields are kept)
        menu.key("down", 3)             # Your name, Port, Network
    menu.key("end")                     # the last button is Back; the one before it is Create world
    menu.key("up")
    menu.shot(f"before-create-{name.split()[1].lower()}")
    menu.go(wait=1)


def run_fixed(menu, files, report, log, lan_hint):
    errors_before = files.error_text()
    before = {world["world_id"] for world in files.worlds()}
    report["worlds_before"] = [dict(name=w["name"], bind_address=w["bind_address"]) for w in files.worlds()]
    report["folders_before"] = files.world_folders()
    for world in files.worlds():
        log(f"listed at start: {world['name']} (listens on {world['bind_address']}, world {world['world_id']})")

    open_create(menu)
    fill_and_create(menu, "CI LAN World", "Tester")
    lan = files.wait(lambda: files.named("CI LAN World"), 120)
    menu.shot("after-create-lan")
    require(lan, "the world on the default network was not added to the world list "
                 f"(last-error.txt: {files.error_text()[-1500:] if files.error_text() != errors_before else 'unchanged'})")
    bind = lan["bind_address"]
    require(bind != "127.0.0.1", f"the default network should be this PC's local-network address, not {bind}")
    require(lan_hint is None or bind in lan_hint, f"listen address {bind} is not one of this PC's addresses {lan_hint}")
    descriptor = files.descriptor(lan["folder"])
    require(descriptor["endpoint"] == bind, f"the world's certificate names {descriptor['endpoint']}, not {bind}")
    log(f"created on the default network: listens on {bind}:{descriptor['port']} (world {lan['world_id']})")
    report["lan_world"] = dict(bind_address=bind, endpoint=descriptor["endpoint"], port=descriptor["port"])
    time.sleep(3)

    # World screen (focus on "Host this world now"): Invite codes for friends.
    menu.key("down", 2)
    menu.go()
    clear_clipboard()
    menu.go()                           # the first friend's row: copy its code
    menu.shot("invite-code")
    from emerald_multiplayer.invite_code import InviteCodeError, decode_invite
    copied = files.wait(lambda: clipboard_text().strip() or None, 20)
    require(copied, "no invite code was copied to the clipboard")
    try:
        code = decode_invite(copied)
    except (InviteCodeError, ValueError) as error:
        raise CheckFailed(f"the copied text is not an invite code: {error}") from None
    require((code.address, code.port, code.world_id) == (bind, descriptor["port"], lan["world_id"]),
            f"the invite code points at {code.address}:{code.port} (world {code.world_id})")
    log(f"invite code copied and decoded: {code.address}:{code.port}, slot {code.slot}")
    report["invite_code"] = dict(address=code.address, port=code.port, slot=code.slot)
    menu.go("escape")                   # back to the world screen

    # Rename world.
    menu.key("down", 5)
    menu.go()
    menu.key("backspace", 40, pause=0.03)
    menu.text("CI Renamed World")
    menu.key("enter")
    menu.go()
    renamed = files.wait(lambda: files.named("CI Renamed World"), 20)
    require(renamed and renamed["world_id"] == lan["world_id"], "the rename was not saved")
    log("renamed: CI LAN World -> CI Renamed World (same world ID)")

    # Back to Host World and create the second world with a numeric public address (the reported traceback's path).
    menu.go("escape")
    menu.key("home")
    menu.go()
    menu.shot("create-form-2")
    fill_and_create(menu, "CI Public World", "Tester", address=PUBLIC_ADDRESS)
    public = files.wait(lambda: files.named("CI Public World"), 120)
    menu.shot("after-create-public")
    require(public, "the world with a public address was not added to the world list "
                    f"(last-error.txt: {files.error_text()[-1500:] if files.error_text() != errors_before else 'unchanged'})")
    descriptor2 = files.descriptor(public["folder"])
    require((public["bind_address"], public["address"], descriptor2["endpoint"]) == (bind, PUBLIC_ADDRESS, PUBLIC_ADDRESS),
            f"public world: listens on {public['bind_address']}, address {public['address']}, endpoint {descriptor2['endpoint']}")
    log(f"created with public address {PUBLIC_ADDRESS}: listens on {public['bind_address']} (world {public['world_id']})")
    time.sleep(3)

    # Delete it (asks first; the folder moves to worlds-deleted).
    menu.key("down", 6)
    menu.go()
    menu.key("up")                      # the confirmation starts on "Cancel"
    menu.go()
    gone = files.wait(lambda: files.named("CI Public World") is None, 20)
    require(gone, "the deleted world is still in the world list")
    deleted = files.private / "worlds-deleted"
    require(any(public["folder"] in p.name for p in deleted.iterdir()) if deleted.is_dir() else False,
            "the deleted world's folder was not kept in worlds-deleted")
    log("deleted CI Public World: its folder was moved to worlds-deleted")
    menu.shot("after-delete")

    # Host the renamed world: the world is prepared and the game opens for the character to enter it.
    menu.key("home")
    menu.key("down")                    # the newest world, under "Create a new world"
    menu.go()
    menu.shot("world-screen")
    known = {pid for pid, _ in children(menu.process.pid)}
    launches = files.private / "launches"
    launched_before = set(launches.iterdir()) if launches.is_dir() else set()
    menu.go(wait=10)                    # "Host this world now" (focused); the world is prepared (a backup first)
    menu.shot("hosting-1")
    shown = len(menu.screens())
    menu.go(wait=3)                     # "<character> enters <world>": Continue
    # The game starts after the 3D check. A PC without 3D (this runner) is asked first: Play in Classic 2D this time (focused).
    question = files.wait(lambda: next((s for s in menu.screens()[shown:] if s["id"] in ("graphics", "busy")
                                        and s["title"] != "Checking graphics"), None), 60, step=0.5)
    if question and question["id"] == "graphics":
        menu.shot("graphics-question")
        report["graphics_question"] = question["notes"][:3]
        menu.go(wait=3)
        log("3D graphics cannot start on this runner: chose Play in Classic 2D this time")

    def started():
        game = [(pid, command) for pid, command in children(menu.process.pid) if pid not in known and "--shell" not in command]
        folders = (set(launches.iterdir()) if launches.is_dir() else set()) - launched_before
        return (game, sorted(folders)) if game or folders else None
    seen = files.wait(started, 90, step=0.5)
    menu.shot("hosting-2")
    require(seen, "hosting did not open the game for the character "
                  f"(last-error.txt: {files.error_text()[-1500:] if files.error_text() != errors_before else 'unchanged'})")
    game, folders = seen
    log("hosting: the world was prepared and the game was started for the character to enter it "
        f"(game process {game[0][0] if game else 'already ended'}; launch folder {folders[0].name if folders else 'none yet'})")
    report["hosting"] = dict(game_process=bool(game), launch_folder=bool(folders))
    menu.stop()
    if folders:
        log_file = folders[0] / "runtime.log"
        if log_file.is_file():
            tail = [line for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()][-6:]
            report["hosting_runtime_log_tail"] = tail
            for line in tail:
                log("    game: " + line[:200])

    new = [w for w in files.worlds() if w["world_id"] not in before]
    report["worlds_created"] = [dict(name=w["name"], bind_address=w["bind_address"], address=w["address"]) for w in new]
    require(all(type(w["bind_address"]) is str for w in files.worlds()), "a listen address is not text")
    require(files.error_text() == errors_before, "an error was recorded: " + files.error_text()[-2000:])
    return lan["world_id"]


def run_crash(menu, files, report, log):
    """The reported failure on the build of 2026-10-19."""
    before = files.world_folders()
    open_create(menu)
    fill_and_create(menu, "CI LAN World", "Tester")
    time.sleep(20)                      # the world is refused before anything is made
    menu.shot("refused-lan")
    require(files.world_folders() == before, "expected the default-network world to be refused, but a world folder appeared")
    require(files.named("CI LAN World") is None, "expected the default-network world to be refused, but it was listed")
    log("reproduced 1: on the default network the world was refused and nothing was created")
    menu.go()                           # dismiss the message: back on the form (the fields are kept)
    menu.key("home")
    fill_and_create(menu, "CI Public World", "Tester", address=PUBLIC_ADDRESS)
    error = files.wait(lambda: "invalid world record" in files.error_text() and files.error_text(), 120)
    menu.shot("crash-public")
    require(error, "expected 'invalid world record' in shell/last-error.txt; it says: " + files.error_text()[-1500:])
    folders = [f for f in files.world_folders() if f not in before]
    require(len(folders) == 1, f"expected one new world folder left unlisted, found {folders}")
    require(files.named("CI Public World") is None, "expected the world to be missing from the list")
    for frame in ("world_registry.py", "shell_store.py", "_create_world", "create_world_menu"):
        require(frame in error, f"the recorded traceback does not pass through {frame}")
    log("reproduced 2: with a public address the world was created on disk, then the list refused it:")
    lines = [line for line in error.splitlines() if line.strip()]
    for line in lines[-14:]:
        log("    " + line)
    report["crash_traceback_tail"] = lines[-14:]
    report["orphan_folder"] = folders[0]
    # Dismissing the message returns to the main menu, whose listing now meets the unlisted folder: it fails again.
    first = files.error_file.stat().st_mtime
    menu.go(wait=4)
    again = files.wait(lambda: files.error_file.stat().st_mtime != first and files.error_text(), 30)
    menu.shot("main-menu-fails")
    if again and "entries" in again:
        log("reproduced 3: back at the main menu the world list fails again (registry.entries), so the menu keeps failing")
        report["main_menu_fails_again"] = True
    else:
        report["main_menu_fails_again"] = False
    menu.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--setup", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True, help="the temporary LOCALAPPDATA (kept between runs)")
    parser.add_argument("--expect", choices=("fixed", "crash"), required=True)
    parser.add_argument("--label", default="check")
    parser.add_argument("--leave-installed", action="store_true")
    parser.add_argument("--delete-install", action="store_true", help="remove the program folder by hand instead of uninstalling")
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("this check runs on Windows")
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    shots = work / f"{args.label}-pictures"
    shots.mkdir(exist_ok=True)
    profile = args.profile.resolve()
    profile.mkdir(parents=True, exist_ok=True)
    report = dict(format="emerald-world-check-v1", label=args.label, setup=args.setup.name, expect=args.expect,
                  leftover_profile=(profile / "PokemonPrivate").exists())
    lines = []

    def log(text):
        print(text, flush=True)
        lines.append(text)

    env = dict(os.environ, LOCALAPPDATA=str(profile))
    target = work / f"{args.label}-EmeraldTogether"
    files = Files(profile)
    menu = None
    try:
        from emerald_multiplayer.launcher_worlds import lan_addresses
        lan_hint = [str(a) for a in lan_addresses()]
        log(f"this runner's local-network addresses: {lan_hint or 'none'}")
        report["runner_addresses"] = lan_hint
        require(lan_hint, "the runner has no local-network address, so the reported case cannot happen here")
        log(f"profile {'with data an earlier version left' if report['leftover_profile'] else 'new'}: {profile}")
        install(args.setup.resolve(), target, env, work, args.label)
        log(f"installed {args.setup.name} into {target}")
        seed_profile(files, log)
        menu = Menu(target / "EmeraldTogether.exe", env, work, log, shots)
        menu.start()
        if args.expect == "crash":
            run_crash(menu, files, report, log)
        else:
            world_id = run_fixed(menu, files, report, log, lan_hint)
            # Start again: the worlds are kept and the menu opens without an error.
            errors_before = files.error_text()
            menu = Menu(target / "EmeraldTogether.exe", env, work, log, shots)
            menu.start()
            require(menu.alive(), "EmeraldTogether did not stay up after a restart")
            kept = {w["world_id"]: w for w in files.worlds()}
            require(world_id in kept and kept[world_id]["name"] == "CI Renamed World", "the renamed world was not kept")
            code = menu.quit()
            require(code == 0, f"Exit from the main menu should end EmeraldTogether with code 0, got {code}")
            require(files.error_text() == errors_before, "the restart recorded an error: " + files.error_text()[-2000:])
            log("restarted: the worlds are listed as they were and Exit closed EmeraldTogether")
            report["worlds_after"] = [dict(name=w["name"], bind_address=w["bind_address"]) for w in files.worlds()]
            for world in report["worlds_after"]:
                log(f"kept: {world['name']} (listens on {world['bind_address']})")
        report["result"] = "passed"
    except CheckFailed as error:
        report["result"] = "failed: " + str(error)
        log("check failed: " + str(error))
        if menu is not None:
            menu.shot("failure")
    finally:
        if menu is not None:
            menu.stop()
        report["log"] = lines
        (work / f"{args.label}-world-check.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if args.delete_install:
            import shutil
            shutil.rmtree(target, ignore_errors=True)
            log("removed the program folder by hand (the profile is kept)")
        elif not args.leave_installed:
            uninstall(target, work, args.label)
    if report["result"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
