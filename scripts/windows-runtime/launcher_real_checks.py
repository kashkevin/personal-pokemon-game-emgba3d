"""Real-launcher checks of save integrity and setup fixes (KNOWN_ISSUES MS-214, MS-215, MS-216, NU-1, P15, NU-3) on the
player's own menu (shell_app, as EmeraldTogether.exe runs it) and the Linux game, two players on one PC, each on an X display
of their own (ci_play_check.py's Linux rehearsal: its desk, players and steps are reused unchanged).

    python launcher_real_checks.py --scenario disk-full-player --game pokeemerald-mp --rom pokedev.gba \\
        --manifest manifest.json --display :522 --display :523 --work <new folder>

Scenarios:
  disk-full-player  (MS-215) the friend's PokemonPrivate folder is a small tmpfs of its own. Both create a character, the host
                    hosts a world (This PC only) and the friend joins and saves (Save now). The friend's disk is then filled
                    to its last byte: the friend's in-game SAVE in the world (its banner, pictures) and Save now (the
                    launcher's text); nothing sent, nothing left; then room again: Save now saves.
  disk-full-host    (MS-214) the host's PokemonPrivate folder is a small tmpfs. After the friend's first save the host's disk
                    is filled: the friend's in-game SAVE (banner) and Save now (text), the world's head unchanged; room again,
                    the friend closes the game (the menu's text) and joins again: the save kept on the friend's PC commits.
  copies            (MS-216) one player: a character, a Solo world, Save now --saves times in one game, the game closed
                    (the menu prunes): the newest 40 copies remain; Continue plays the newest save.
  registration      (NU-1, P15) the host hosts; the friend creates a character and joins; the registration game is ended
                    with SIGKILL --kills times at varied moments (each time the menu's message is read: "The game closed
                    unexpectedly", never "The connection to the server was lost"); then the friend creates a second
                    character (a fresh New Game) and joins with it after one more killed attempt: registration succeeds.
  connection        (NU-3) the host's world; the friend's Join Friend with: a wrong port, the host stopped, a tampered code, a
                    different game version: each message read from the menu.
"""
from __future__ import annotations

import argparse
import asyncio
import errno
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(HERE), str(ROOT / "scripts" / "multiplayer")]

import ci_play_check as cp  # noqa: E402
from ci_play_check import CheckFailed, require, wait  # noqa: E402

SAVE_ACTION = 5


def _revision(world, slot):
    """ci_play_check.revision with its read-only connection closed (sqlite3's ``with`` commits but does not close: the
    connection held the host's world file open, so a small file system under it could not be unmounted)."""
    import sqlite3
    player_id = next(account["player_id"] for account in world["accounts"] if account["slot"] == slot)
    try:
        db = sqlite3.connect(f"file:{world['directory'] / 'world.sqlite3'}?mode=ro", uri=True, timeout=10)
        try:
            row = db.execute("SELECT latest_revision FROM players WHERE player_id=?", (player_id,)).fetchone()
        finally:
            db.close()
    except sqlite3.Error:
        return None
    return None if row is None else int(row[0])


cp.revision = _revision


class Desk(cp.LinuxDesk):
    """ci_play_check's Linux desk, whose launchers run this script's --linux-app (the same shell_app; with
    EMERALD_TEST_LAUNCHER_VERSION set, its hellos name another release, as a different EmeraldTogether version does)."""

    def launch(self, profile, screen_log):
        key = str(Path(profile).resolve())
        if key not in self.profile_display:
            self.profile_display[key] = self.displays[len(self.profile_display)]
        display = self.profile_display[key]
        env = dict(os.environ, DISPLAY=display, SDL_AUDIODRIVER="dummy", **{cp.SCREEN_LOG: str(screen_log)})
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests"), str(HERE)])
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--linux-app", str(self.application),
                                    str(profile)], env=env, cwd=str(profile))
        self.display_of[process.pid] = display
        return process


def linux_app(application, profile):
    version = os.environ.get("EMERALD_TEST_LAUNCHER_VERSION")
    if version:
        from emerald_multiplayer.protocol import set_launcher_version
        set_launcher_version(version)
    if os.environ.get("AUDIT_FAIL_SAVE_LOG"):
        # Proof instrumentation (the check's process only; the launcher's code runs unchanged): where each failed save
        # of the session came from - its stack - in <profile>/audit-fail-save.log.
        import traceback
        from emerald_multiplayer.launcher_session import LauncherSession
        real_fail = LauncherSession._fail_save
        log = Path(profile) / "audit-fail-save.log"

        def fail_save(self, *args, **kwargs):
            with log.open("a") as out:
                out.write(json.dumps(dict(t=round(time.time(), 3), kwargs=kwargs, revision=getattr(self, "_revision", None),
                                          game_alive=getattr(getattr(self, "_game", None), "process", None) is not None
                                          and self._game.process.returncode is None,
                                          closing=getattr(self, "_closing", None),
                                          stack="".join(traceback.format_stack(limit=12)))) + "\n")
            return real_fail(self, *args, **kwargs)
        LauncherSession._fail_save = fail_save
    return cp.linux_app(application, profile)


# ------------------------------------------------------------------ small file systems of their own

def mount_tmpfs(path: Path, size: str):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["mount", "-t", "tmpfs", "-o", f"size={size},mode=0755", "tmpfs", str(path)], check=True)


def umount(path: Path):
    for _ in range(60):
        if subprocess.run(["umount", str(path)], capture_output=True).returncode == 0:
            return True
        time.sleep(1)
    return False


def df(path: Path):
    return subprocess.run(["df", "-B1", str(path)], capture_output=True, text=True).stdout.splitlines()[-1].split()[1:4]


def fill(fs: Path) -> int:
    """Zeros into a filler file until the file system refuses (ENOSPC); returns the bytes written."""
    written = 0
    with open(fs / "filler.bin", "wb", buffering=0) as out:
        for size in (1 << 20, 4096, 512, 1):
            chunk = b"\0" * size
            while True:
                try:
                    count = out.write(chunk)
                except OSError as error:
                    if error.errno != errno.ENOSPC:
                        raise
                    break
                if not count:
                    break
                written += count
    return written


def free(fs: Path):
    filler = fs / "filler.bin"
    if filler.exists():
        filler.unlink()


# ------------------------------------------------------------------ the game: memory reads and keys (native_launcher_battle_proof)

class Game:
    """One running game of a player's: its process number, window, and a probe on its memory."""

    def __init__(self, check, player, handle, symbols):
        from native_launcher_battle_proof import NativeProbe
        self.check, self.player, self.handle = check, player, handle
        self.pid = handle[0]
        self.symbols = symbols
        display = player.desk._display(self.pid)
        self.probe = NativeProbe(self.pid, symbols, display, lambda *a, **k: None, hold=.15, gap=.25)

    def u32(self, name):
        return int.from_bytes(self.probe.mem(name, 4), "little")

    def in_field(self):
        callback2 = int.from_bytes(self.probe.mem("gMain", 8)[4:8], "little")
        return callback2 == self.symbols["CB2_Overworld"][0] and self.probe.mem("sLockFieldControls", 1)[0] == 0

    def title(self):
        env = dict(os.environ, DISPLAY=self.probe.display)
        found = subprocess.run(["xdotool", "search", "--onlyvisible", "--pid", str(self.pid)], env=env, capture_output=True,
                               text=True).stdout.split()
        return subprocess.run(["xdotool", "getwindowname", found[-1]], env=env, capture_output=True,
                              text=True).stdout.strip() if found else None

    def state(self):
        return dict(save_counter=self.u32("gSaveCounter"), flash_dirty=self.probe.mem("gPlatformFlashDirty", 1)[0],
                    failed_tries=self.u32("sSaveFailedTries"), notice=self.u32("sShownNoticeId"), title=self.title(),
                    field=self.in_field())

    def picture(self, label):
        from native_launcher_battle_proof import game_picture
        self.check.count += 1
        path = self.check.pictures / f"{self.check.count:02d}-{self.player.name}-{label}.png"
        try:
            game_picture(self.probe, path)
        except Exception as error:                                      # noqa: BLE001 - a picture never fails a check
            self.check.log(f"picture {label} not taken: {error!r}")
        return path.name

    async def to_field(self, seconds=60):
        deadline = time.monotonic() + seconds
        while not self.in_field():
            if time.monotonic() > deadline:
                raise CheckFailed(f"{self.player.name}: the game is not in the field")
            await self.probe.press(2)
            await asyncio.sleep(.6)

    async def in_game_save(self, watch=12.0):
        """START > SAVE > YES (> YES to overwrite) in the game, as a player saves; then ``watch`` seconds of the game's state and
        pictures (the banner). Returns what was seen."""
        p = self.probe
        await self.to_field()
        before = self.state()
        await p.press(8, release=60)
        row = await p.snapshot(lambda r: 0 < r["count"] <= len(r["actions"]) and SAVE_ACTION in r["actions"][:r["count"]],
                               timeout=30)
        target = row["actions"][:row["count"]].index(SAVE_ACTION)
        for _ in range((target - row["start_cursor"]) % row["count"]):
            await p.press(128)
        presses = 0
        async with asyncio.timeout(90):
            while self.u32("gSaveCounter") == before["save_counter"]:
                await p.press(1)
                presses += 1
                await asyncio.sleep(.5)
        seen, pictures = [], []
        started = time.monotonic()
        while time.monotonic() - started < watch:
            now = self.state()
            now["t"] = round(time.monotonic() - started, 1)
            if not seen or {k: v for k, v in now.items() if k != "t"} != {k: v for k, v in seen[-1].items() if k != "t"}:
                seen.append(now)
                if now["notice"] != before["notice"] and len(pictures) < 3:
                    pictures.append(self.picture("banner"))
            await asyncio.sleep(.25)
        pictures.append(self.picture("after-in-game-save"))
        return dict(before=before, presses=presses, states=seen, pictures=pictures,
                    notice_shown=seen[-1]["notice"] != before["notice"] if seen else False)


# ------------------------------------------------------------------ the menu

def account_folder(folder):
    """The world account's own folder (players/<world>/<player>): the one directory named by a UUID (the folder also holds
    the account's outgoing-character file)."""
    from emerald_multiplayer.shell_store import is_uuid
    found = [entry for entry in Path(folder).iterdir() if entry.is_dir() and is_uuid(entry.name)]
    require(len(found) == 1, f"expected one account folder in {folder}: {[e.name for e in Path(folder).iterdir()]}")
    return found[0]


def session_status(player):
    screen = player.current()
    return None if screen is None else dict(id=screen["id"], status=screen["status"], notes=screen["notes"][:4],
                                            items=[i[1] for i in screen["items"]])


def save_now(player, record, slot, *, seconds=45, expect_saved=True):
    """Save now on the session screen. With ``expect_saved``, until the world's revision moves on (at most ``seconds``);
    otherwise ``seconds`` of watching. Returns (revision before, after, every status line shown meanwhile)."""
    screen = player.expect("session", 60, where=lambda s: any(item[1] == "save" for item in s["items"]))
    before = cp.revision(record, slot)
    player.choose(screen, "save")
    statuses = []

    def watch():
        current = player.current()
        status = current and current.get("status")
        text = status[1] if status else ""
        if text and (not statuses or statuses[-1] != text):
            statuses.append(text)
        return expect_saved and (cp.revision(record, slot) or 0) > (before or 0)
    deadline = time.time() + seconds
    while time.time() < deadline and not watch():
        time.sleep(0.25)
    time.sleep(1.5)
    watch()
    return before, cp.revision(record, slot), statuses


def statuses_since(player, mark):
    """Every distinct (screen, status) the menu showed since screen number ``mark``."""
    shown = []
    for screen in player.screens()[mark:]:
        row = [screen["id"], screen["status"][1] if screen.get("status") else None]
        if not shown or shown[-1] != row:
            shown.append(row)
    return shown


def reveal_status(player):
    """The session screen's status line under the "Saving..." the menu keeps after Save now until the next choice: the
    autosave row chosen twice (off, then on again: the setting as before); returns the status shown after each."""
    shown = []
    for _ in range(2):
        screen = player.expect("session", 30, where=lambda s: any(item[1] == "autosave" for item in s["items"]))
        player.choose(screen, "autosave")
        time.sleep(2.5)
        current = player.current()
        shown.append(dict(status=current.get("status"),
                          autosave=next((i[2] for i in current["items"] if i[1] == "autosave"), None)))
    return shown


def notes_of(screen):
    return None if screen is None else dict(id=screen["id"], title=screen["title"], status=screen["status"],
                                            notes=screen["notes"][:6])


# ------------------------------------------------------------------ set-up shared by the scenarios

class Setup:
    def __init__(self, args):
        self.args = args
        self.work = work = args.work.resolve()
        require("/multiplayer-proof/" in work.as_posix() + "/", "choose a folder under a multiplayer-proof directory")
        reuse = getattr(args, "reuse", False)
        require(reuse or not work.exists() or not any(work.iterdir()), "choose a new, empty --work folder")
        work.mkdir(parents=True, exist_ok=True)
        self.report = dict(format="cluster-b-shell-check-v1", scenario=args.scenario, checks=[])
        self.lines = []
        self.mounts = []
        installed = work / "application" / "installation.json"
        self.desk = Desk(installed if reuse and installed.exists() else cp.linux_application(args, work), args.display)
        self.check = cp.PlayCheck(self.desk, work, args.scenario, self.report, self.lines, loopback=True)
        from native_launcher_battle_proof import symbols_of
        self.symbols = symbols_of(args.game)

    def record(self, name, **fields):
        row = dict(verified=name, at=time.strftime("%H:%M:%S"), **fields)
        self.report["checks"].append(row)
        self.persist()
        self.check.log(json.dumps(row, default=str)[:4000])

    def persist(self):
        self.report["log"] = self.lines
        (self.work / f"{self.args.scenario}-report.json").write_text(json.dumps(self.report, indent=2, default=str) + "\n")

    def player(self, name, *, tmpfs=None):
        player = cp.Player(self.check, name, self.work / f"{name}-profile")
        if tmpfs is not None:
            folder = player.profile / "PokemonPrivate"
            mount_tmpfs(folder, tmpfs)
            self.mounts.append(folder)
            self.record("tmpfs-mounted", player=name, folder=str(folder), size=tmpfs, df=df(folder))
        player.private.mkdir(parents=True, exist_ok=True)
        cp.seed_rule(player)
        return player

    def game(self, player, handle):
        return Game(self.check, player, handle, self.symbols)

    def cleanup(self, players):
        for player in players:
            if player is not None and player.process is not None and player.process.poll() is None:
                children = [pid for pid, _ in player.desk.children(player.process.pid)]
                player.desk.kill(player.process)
                try:
                    player.process.wait(20)
                except subprocess.TimeoutExpired:
                    pass
                wait(lambda: not any(player.desk.alive(pid) for pid in children), 30, step=0.5)
        for folder in self.mounts:
            free(folder)
            ok = umount(folder)
            self.report.setdefault("unmounted", []).append([str(folder), ok])
        for player in players:
            if player is not None:
                error = player.error_text() if player.private.is_dir() else ""
                if error:
                    self.report.setdefault("errors", {})[player.name] = error[-4000:]
                self.report.setdefault("screens", {})[player.name] = [notes_of(s) for s in player.screens()[-12:]]
        self.persist()


def host_and_friend(s, host, friend):
    """Both menus, a character each, the host's world (This PC only, the host's game open) and the friend joined and saved
    (the friend's game open). Returns (world, code, slot, host_game, friend_game)."""
    check = s.check
    host.start()
    friend.start()
    check.create_character(host)
    check.create_character(friend)
    world, code, slot, host_game, hosted = check.host(host)
    s.record("hosted", world=world["name"], world_id=world["world_id"], slot=slot, result=hosted)
    friend_game, joined = check.join(friend, code, world, slot, keep_open=True)
    s.record("friend-joined-and-saved", result=joined)
    return world, code, slot, host_game, friend_game


# ------------------------------------------------------------------ MS-215

def folder_state(account):
    """The account folder's files: the copies (receipts), the save bytes without a receipt, the journals."""
    names = sorted(p.name for p in account.iterdir())
    flashes = {n[:-len(".flash")] for n in names if n.endswith(".flash")}
    receipts = {n[:-len(".export.json")] for n in names if n.endswith(".export.json")}
    return dict(files=len(names), receipts=len(receipts), flash_without_receipt=sorted(flashes - receipts),
                pending_export="pending-export.json" in names, journals=[n for n in names if n.startswith("pending")])


def receipt_for(account, sha256):
    """The receipt (operation, revision) of the copy whose bytes have this SHA-256, or None."""
    for path in account.glob("*.export.json"):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if record.get("checkpoint", {}).get("sha256") == sha256:
            return dict(operation=path.name[:-len(".export.json")], revision=record["checkpoint"]["revision"])
    return None


async def disk_full_player(s):
    host = s.player("host")
    friend = s.player("friend", tmpfs=s.args.tmpfs)
    try:
        world, code, slot, host_game, friend_handle = host_and_friend(s, host, friend)
        game = s.game(friend, friend_handle)
        account = account_folder(friend.private / "players" / world["world_id"])
        fs = friend.profile / "PokemonPrivate"
        s.record("friend-account-folder", folder=str(account), state=folder_state(account), df=df(fs), game=game.state())
        filled = fill(fs)
        s.record("friend-disk-filled", filler_bytes=filled, df=df(fs))
        head_before = cp.revision(world, slot)
        seen = await game.in_game_save(watch=s.args.watch)
        s.record("in-game-save-with-the-disk-full", head_before=head_before, head_after=cp.revision(world, slot),
                 session=session_status(friend), folder=folder_state(account), **seen)
        friend.picture("menu-after-in-game-save-disk-full")
        before, after, statuses = save_now(friend, world, slot, seconds=20, expect_saved=False)
        s.record("save-now-with-the-disk-full", revision_before=before, revision_after=after, statuses_shown=statuses,
                 session=session_status(friend), folder=folder_state(account), game=game.state())
        friend.picture("menu-after-save-now-disk-full")
        s.record("status-under-saving", revealed=reveal_status(friend))
        friend.picture("menu-status-revealed-disk-full")
        free(fs)
        s.record("friend-disk-freed", df=df(fs))
        await asyncio.sleep(3)
        before2, after2, statuses2 = save_now(friend, world, slot)
        s.record("save-now-with-room", revision_before=before2, revision_after=after2, statuses_shown=statuses2,
                 session=session_status(friend), game=game.state(), folder=folder_state(account))
        s.record("status-under-saving-with-room", revealed=reveal_status(friend))
        friend.picture("menu-saved-again")
        seen2 = await game.in_game_save(watch=8)
        s.record("in-game-save-with-room", head_after=cp.revision(world, slot), session=session_status(friend),
                 folder=folder_state(account), **seen2)
        s.check.close(friend, friend_handle)
        after_close = friend.expect(("join_list", "message", "main"), 120)
        s.record("friend-closed", menu=notes_of(after_close), head=cp.revision(world, slot))
        s.check.close(host, host_game)
        host.expect("host_list", 60)
        for player in (friend, host):
            s.check.finish(player)
        s.report["result"] = "completed"
    finally:
        s.cleanup((host, friend))


# ------------------------------------------------------------------ MS-214

async def disk_full_host(s):
    host = s.player("host", tmpfs=s.args.tmpfs)
    friend = s.player("friend")
    try:
        world, code, slot, host_game, friend_handle = host_and_friend(s, host, friend)
        game = s.game(friend, friend_handle)
        fs = host.profile / "PokemonPrivate"
        account = account_folder(friend.private / "players" / world["world_id"])
        head_before = cp.revision(world, slot)
        s.record("before-filling", head=head_before, folder=folder_state(account), df=df(fs))
        filled = fill(fs)
        s.record("host-disk-filled", filler_bytes=filled, df=df(fs), friend_head=head_before)
        mark = len(friend.screens())
        seen = await game.in_game_save(watch=s.args.watch)
        pending = account / "pending-export.json"
        pending_record = json.loads(pending.read_text()) if pending.exists() else None
        s.record("in-game-save-with-the-host-disk-full", head_before=head_before, head_after=cp.revision(world, slot),
                 session=session_status(friend), folder=folder_state(account), pending=pending_record,
                 menu_statuses=statuses_since(friend, mark), **seen)
        friend.picture("menu-after-in-game-save-host-full")
        screen = friend.current()
        offered = any(item[1] == "save" for item in screen["items"])
        if offered:
            before, after, statuses = save_now(friend, world, slot, seconds=20, expect_saved=False)
            s.record("save-now-with-the-host-disk-full", revision_before=before, revision_after=after,
                     statuses_shown=statuses, session=session_status(friend), folder=folder_state(account))
        else:
            s.record("save-now-not-offered", items=[i[1] for i in screen["items"]], status=screen.get("status"))
        mark = len(friend.screens())
        revealed = reveal_status(friend)
        s.record("status-under-saving", revealed=revealed, menu_statuses=statuses_since(friend, mark))
        friend.picture("menu-status-revealed-host-full")
        free(fs)
        s.record("host-disk-freed", df=df(fs), head=cp.revision(world, slot))
        await asyncio.sleep(5)
        screen = friend.current()
        s.record("after-room-before-reopening", items=[i[1] for i in screen["items"]], status=screen.get("status"),
                 head=cp.revision(world, slot), folder=folder_state(account))
        kept = pending_record or (json.loads(pending.read_text()) if pending.exists() else None)
        mark = len(friend.screens())
        s.check.close(friend, friend_handle)
        after_close = friend.expect(("join_list", "message", "main"), 120)
        s.record("friend-closed-the-game", menu=notes_of(after_close), menu_statuses=statuses_since(friend, mark),
                 head=cp.revision(world, slot), folder=folder_state(account))
        friend.picture("menu-after-closing")
        if after_close["id"] == "message":
            friend.key("enter")
        head_reopen = cp.revision(world, slot)
        mark = len(friend.screens())
        rejoin = s.check.rejoin(friend, world, slot)
        sha = (kept or {}).get("sha256")
        s.record("friend-joined-again", result=rejoin, head_before=head_reopen, head=cp.revision(world, slot),
                 folder=folder_state(account), kept_journal=kept, kept_save_receipt=receipt_for(account, sha) if sha else None,
                 menu_statuses=statuses_since(friend, mark))
        s.check.close(host, host_game)
        host.expect("host_list", 60)
        for player in (friend, host):
            s.check.finish(player)
        s.report["result"] = "completed"
    finally:
        s.cleanup((host, friend))


# ------------------------------------------------------------------ MS-216

def copies_in(folder):
    from emerald_multiplayer.save_copies import save_copies
    return save_copies(folder, folder.parent.name, folder.name)


def is_whole(copy):
    from emerald_multiplayer.save_copies import is_whole as whole
    return whole(copy)


async def copies(s):
    host = s.player("host")
    try:
        check = s.check
        host.start()
        character = check.create_character(host)
        main = host.expect("main")
        host.choose(main, "solo")
        host.choose(host.expect("solo"), "new")
        screen = host.expect(("ask_text", "trade_rule"))
        if screen["id"] == "trade_rule":
            host.choose(screen, cp.RULE)
            screen = host.expect("ask_text")
        host.key("enter")
        host.key("enter")
        world = wait(lambda: host.world(host.worlds()[-1]["name"]) if host.worlds() else None, 60)
        require(world and world["kind"] == "adventure", "no Solo world was created")
        handle, played = check.enter_and_play(host, world, 0, keep_open=True)
        s.record("solo-world-played", world=world["name"], world_id=world["world_id"], result=played)
        folder = host.private / "players" / world["world_id"]
        account = account_folder(folder)
        revisions = []
        for n in range(s.args.saves):
            before, after, statuses = save_now(host, world, 0)
            require(after == (before or 0) + 1, f"Save now {n + 1}: revision {before} -> {after} ({statuses})")
            revisions.append(after)
            if n % 10 == 0:
                s.record("save-now", n=n + 1, revision=after, copies=len(copies_in(account)))
        found = copies_in(account)
        s.record("before-the-game-closes", revisions=[revisions[0], revisions[-1]], copies=len(found),
                 newest=found[0].revision, oldest=found[-1].revision,
                 flash_files=len(list(account.glob("*.flash"))), receipts=len(list(account.glob("*.export.json"))))
        check.close(host, handle)
        screen = host.expect(("main", "solo"), 120)
        time.sleep(3)
        found = copies_in(account)
        s.record("after-the-game-closed", menu=notes_of(screen), copies=len(found),
                 newest=found[0].revision if found else None, oldest=found[-1].revision if found else None,
                 whole=all(is_whole(c) for c in found), flash_files=len(list(account.glob("*.flash"))),
                 receipts=len(list(account.glob("*.export.json"))), files=len(list(account.iterdir())),
                 head=cp.revision(world, 0))
        latest = next(c for c in host.characters() if c["character_id"] == character["character_id"])
        s.record("character-latest", current=latest.get("current"))
        # Continue: the main menu's Continue plays the last world on the newest save.
        while host.current()["id"] != "main":
            host.key("escape")
            time.sleep(1.5)
        main = host.expect("main", 30)
        s.record("main-menu", items=[i[:3] for i in main["items"]], notes=main["notes"][:3])
        host.choose(main, "continue")
        handle2, again = check.play(host, world, 0, cp.revision(world, 0))
        s.record("continued", result=again)
        host.expect(("main", "solo"), 60)
        time.sleep(3)
        found = copies_in(account)
        s.record("after-continue", copies=len(found), newest=found[0].revision, oldest=found[-1].revision,
                 head=cp.revision(world, 0), whole=all(is_whole(c) for c in found))
        # At start-up: a few more saves, then the launcher ended outright (its game ends with it: no menu after the
        # game, so no pruning then); EmeraldTogether started again prunes at start-up.
        while host.current()["id"] != "main":
            host.key("escape")
            time.sleep(1.5)
        host.choose(host.expect("main", 30), "continue")
        host.graphics_choice()
        handle3 = host.game()
        host.press_until(handle3, "a", lambda: False, 40)
        for n in range(s.args.extra_saves):
            before, after, statuses = save_now(host, world, 0)
            require(after == (before or 0) + 1, f"extra Save now {n + 1}: revision {before} -> {after}")
        found = copies_in(account)
        s.record("before-the-launcher-is-ended", copies=len(found), newest=found[0].revision, oldest=found[-1].revision,
                 head=cp.revision(world, 0))
        host.desk.end_outright(host.process)
        require(wait(lambda: host.process.poll() is not None, 30, step=0.25), "the launcher did not end")
        wait(lambda: not host.desk.alive(handle3[0]), 30, step=0.25)
        if host.desk.alive(handle3[0]):
            host.desk.close_game(handle3[0], handle3[1])
        wait(lambda: not host.desk.alive(host.shell_pid), 30, step=0.25)
        found = copies_in(account)
        s.record("launcher-ended-outright", copies=len(found), newest=found[0].revision, oldest=found[-1].revision,
                 game_alive=host.desk.alive(handle3[0]))
        host.start()
        time.sleep(3)
        found = copies_in(account)
        latest = next(c for c in host.characters() if c["character_id"] == character["character_id"])
        s.record("after-start-up", copies=len(found), newest=found[0].revision, oldest=found[-1].revision,
                 whole=all(is_whole(c) for c in found), head=cp.revision(world, 0), character_current=latest.get("current"),
                 error=host.error_text()[-1500:])
        check.finish(host)
        s.report["result"] = "completed"
    finally:
        s.cleanup((host,))


# ------------------------------------------------------------------ NU-1 and P15

def kill_registration(s, friend, world, slot, *, wait_before=None, field_delay=None, label):
    """On the bring_character screen: Continue; the registration game opens; it is ended with SIGKILL (a crash) after
    ``wait_before`` seconds of A presses (the title, CONTINUE), or ``field_delay`` seconds after the game is in the field
    (where the registration's save is asked of it: a request in flight). Returns (the menu's screen after, whether the
    game had already closed by itself - the registration done)."""
    screen = friend.expect("bring_character", 180)
    friend.choose(screen, "go")
    friend.graphics_choice()
    handle = friend.game()
    game = s.game(friend, handle)
    started = time.monotonic()
    field_at = None
    if field_delay is None:
        friend.press_until(handle, "a", lambda: time.monotonic() - started >= wait_before, wait_before + 5, every=0.8)
    else:
        def in_field():
            try:
                return game.in_field()
            except OSError:
                return True                       # it ended
        friend.press_until(handle, "a", in_field, 90, every=0.8)
        field_at = round(time.monotonic() - started, 1)
        time.sleep(field_delay)
    alive = friend.desk.alive(handle[0])
    if alive:
        os.kill(handle[0], signal.SIGKILL)
    killed_at = round(time.monotonic() - started, 1)
    after = friend.expect(("message", "join_list", "main", "server", "bring_character", "characters", "session",
                           "graphics"), 120, where=lambda sc: sc["id"] != "busy")
    s.record("registration-killed", label=label, wait_before=wait_before, field_delay=field_delay, field_at=field_at,
             killed_after_seconds=killed_at, alive_when_killed=alive, head=cp.revision(world, slot), menu=notes_of(after))
    friend.picture(f"after-{label}")
    return after, not alive


def to_saved_server(friend, after=None):
    """From wherever the menu is (a message, the join list, the main menu) to the saved server's Join."""
    main = after or friend.expect(("main", "join_list", "message", "server"), 60)
    if main["id"] == "message":
        friend.key("enter")
        main = friend.expect(("main", "join_list", "server"), 60)
    if main["id"] == "main":
        friend.choose(main, "join")
        main = friend.expect("join_list", 60)
    if main["id"] == "join_list":
        rows = [item for item in main["items"] if item[1] not in ("new", "back")]
        friend.choose(main, rows[0][1])
        main = friend.expect("server", 60)
    friend.choose(main, "join")


async def registration(s):
    host = s.player("host")
    friend = s.player("friend")
    try:
        check = s.check
        host.start()
        friend.start()
        check.create_character(host)
        first = check.create_character(friend)
        world, code, slot, host_game, hosted = check.host(host)
        s.record("hosted", world=world["name"], slot=slot)
        rng = random.Random(s.args.seed)
        plan = [dict(wait_before=round(rng.uniform(1.0, 14.0), 1)) for _ in range(max(0, s.args.kills - 3))]
        plan += [dict(field_delay=d) for d in (0.0, 0.4, 1.0)][:s.args.kills]
        messages, done = [], False
        # The friend's first Join: the invite code (the server is saved), then the character's registration.
        main = friend.expect("main", 60)
        friend.choose(main, "join")
        friend.choose(friend.expect("join_list"), "new")
        friend.expect("join_new")
        friend.text(code)
        for _ in ("name", "address", "port", "join"):
            friend.key("enter")
        friend.key("enter")
        for n, when in enumerate(plan):
            if n > 0:
                to_saved_server(friend)
            after, done = kill_registration(s, friend, world, slot, label=f"kill-{n + 1}", **when)
            messages.append(dict(n=n + 1, **when, screen=after["id"], title=after["title"], status=after.get("status"),
                                 notes=after["notes"][:4], registered_before_the_kill=done))
            if done:
                break
        text = json.dumps(messages)
        s.record("p15-messages", messages=messages, kills=len(messages),
                 game_closed_unexpectedly=sum("closed unexpectedly" in json.dumps(m) for m in messages),
                 connection_lost=sum("connection to the server was lost" in json.dumps(m).lower() for m in messages),
                 different_character=sum("different character" in json.dumps(m) for m in messages))
        if done:
            # The registration finished before the kill (its game had closed by itself): the launcher went on into the
            # session; that game is closed so the check goes on from the menu (the audit of 2026-11-18: a kill planned
            # 9.5 s in came after a 9.4 s registration).
            friend.graphics_choice()
            check.close(friend, friend.game())
            friend.expect(("join_list", "main", "server", "message"), 60)
        # NU-1: after the unfinished attempts, a fresh New Game (a second character) joins: one more killed attempt,
        # then its registration must succeed (before the fix: "already started with a different character").
        screen = friend.current()
        if screen["id"] == "message":
            friend.key("enter")
        for _ in range(4):
            if friend.current()["id"] == "main":
                break
            friend.key("escape")
            time.sleep(1.5)
        second = check.create_character(friend, existing=1)
        s.record("second-character", character_name=second["name"], character_id=second["character_id"])
        to_saved_server(friend)
        after, done2 = kill_registration(s, friend, world, slot, wait_before=6.0, label="second-character-kill")
        s.record("second-character-killed", menu=notes_of(after), registered=done2)
        to_saved_server(friend, after)
        _, result = check.enter_and_play(friend, dict(name=world["name"]), slot, host_world=world)
        s.record("registered-after-the-unfinished-attempts", result=result, head=cp.revision(world, slot),
                 characters=[c["name"] for c in friend.characters()])
        friend.expect(("join_list", "main"), 60)
        check.close(host, host_game)
        host.expect("host_list", 60)
        for player in (friend, host):
            check.finish(player)
        s.report["result"] = "completed"
    finally:
        s.cleanup((host, friend))


# ------------------------------------------------------------------ NU-3

def reencode(code, **changes):
    """The invite code with some of its fields changed and a correct checksum (a code someone altered on purpose, which the
    checksum cannot catch): invite_code.encode_invite's layout."""
    import base64
    import struct
    import zlib
    from dataclasses import replace
    from uuid import UUID
    from emerald_multiplayer.invite_code import PREFIX, RULESETS, decode_invite
    c = replace(decode_invite(code), **changes)
    host_bytes, name = c.address.encode("ascii"), c.display_name.encode("utf-8")
    body = (struct.pack(">BBBBH", 1, 0, c.slot, RULESETS.index(c.ruleset_id), c.port) + UUID(c.world_id).bytes
            + UUID(c.player_id).bytes + c.credential + bytes.fromhex(c.build_id) + bytes.fromhex(c.certificate_sha256)
            + bytes([len(host_bytes)]) + host_bytes + bytes([len(name)]) + name)
    raw = body + struct.pack(">I", zlib.crc32(body))
    text = base64.b32encode(raw).decode("ascii").rstrip("=")
    return PREFIX + "-".join(text[i:i + 5] for i in range(0, len(text), 5))


def mistype(code):
    """One character of the code changed, as a typing mistake does."""
    body = list(code)
    at = len(PREFIX_TEXT) + 20
    while body[at] == "-":
        at += 1
    body[at] = "B" if body[at] != "B" else "C"
    return "".join(body)


PREFIX_TEXT = "ET1-"


def join_with(friend, code, *, port=None):
    """Join Friend > Join with an invite code: the code typed (and the port field when given), Check and join; returns the
    screens the menu shows until it settles (the problem screen, then the form's status after Back)."""
    main = friend.expect(("main", "join_list"), 60)
    if main["id"] == "main":
        friend.choose(main, "join")
        main = friend.expect("join_list")
    friend.choose(main, "new")
    friend.expect("join_new")
    friend.text(code)
    friend.key("enter")                       # -> the name
    friend.key("enter")                       # -> the address
    friend.key("enter")                       # -> the port
    if port is not None:
        friend.key("backspace", 8)
        friend.text(str(port))
    friend.key("enter")                       # -> Check and join
    friend.key("enter")                       # Check and join
    first = friend.expect(("offline", "join_new", "bring_character", "message", "characters", "create_character"), 120,
                          where=lambda sc: sc["id"] != "join_new" or bool(sc.get("status")))
    shown = [notes_of(first)]
    friend.picture(f"join-{first['id']}")
    if first["id"] == "bring_character":
        # the server check passed: the character's registration (Continue) is where the host is asked to sign in
        friend.choose(first, "go")
        second = friend.expect(("message", "offline", "join_list", "main", "graphics", "session"), 180,
                               where=lambda sc: sc["id"] != "busy")
        shown.append(notes_of(second))
        friend.picture(f"join-registration-{second['id']}")
        if second["id"] in ("message", "offline"):
            friend.key("escape" if second["id"] == "offline" else "enter")
        friend.expect(("join_list", "main", "join_new"), 60)
        if friend.current()["id"] == "join_new":
            friend.key("escape")
        return shown
    if first["id"] == "offline":
        friend.key("escape")
        form = friend.expect("join_new", 60, where=lambda sc: bool(sc.get("status")))
        shown.append(notes_of(form))
    friend.key("escape")
    friend.expect(("join_list", "main"), 60)
    return shown


def restart_menu(s, player, version=None):
    """The player's EmeraldTogether closed (Exit) and started again; ``version``: as another release would say it."""
    s.check.finish(player)
    if version is None:
        os.environ.pop("EMERALD_TEST_LAUNCHER_VERSION", None)
    else:
        os.environ["EMERALD_TEST_LAUNCHER_VERSION"] = version
    try:
        player.start()
    finally:
        os.environ.pop("EMERALD_TEST_LAUNCHER_VERSION", None)


async def connection(s):
    host = s.player("host")
    friend = s.player("friend")
    try:
        check = s.check
        host.start()
        friend.start()
        check.create_character(host)
        world, code, slot, host_game, hosted = check.host(host)
        s.record("hosted", world=world["name"], port=world["descriptor"]["port"], slot=slot)
        results = {}
        results["wrong_port"] = join_with(friend, code, port=world["descriptor"]["port"] + 13)
        s.record("wrong-port", shown=results["wrong_port"])
        results["mistyped_code"] = join_with(friend, mistype(code))
        s.record("mistyped-code", shown=results["mistyped_code"])
        other_pin = hashlib.sha256(b"not this world").hexdigest()
        results["tampered_pin"] = join_with(friend, reencode(code, certificate_sha256=other_pin))
        s.record("tampered-certificate-pin", shown=results["tampered_pin"])
        results["tampered_world"] = join_with(friend, reencode(code, world_id="00000000-0000-4000-8000-000000000001"))
        s.record("tampered-world-id", shown=results["tampered_world"])
        restart_menu(s, friend, version="EmeraldTogether 0.0.1-other")
        results["other_version"] = join_with(friend, code)
        s.record("different-launcher-version", shown=results["other_version"])
        restart_menu(s, friend)
        # A code whose sign-in the host does not know (a code copied wrongly, then fixed up): the server check passes
        # (it sends no credential), the join itself is refused - the friend needs a character to get there.
        check.create_character(friend)          # it ends back on the main menu
        mark = len(friend.screens())
        results["wrong_credential"] = join_with(friend, reencode(code, credential=bytes(32)))
        results["wrong_credential_all"] = statuses_since(friend, mark)
        s.record("wrong-credential", shown=results["wrong_credential"], menu_statuses=results["wrong_credential_all"])
        s.check.close(host, host_game)
        host.expect("host_list", 60)
        mark = len(friend.screens())
        results["host_stopped"] = join_with(friend, code)
        s.record("host-stopped", shown=results["host_stopped"], menu_statuses=statuses_since(friend, mark))
        s.report["results"] = results
        for player in (friend, host):
            check.finish(player)
        s.report["result"] = "completed"
    finally:
        s.cleanup((host, friend))


async def registration_again(s):
    """--reuse of a registration run's folder: the host hosts its world again; the friend joins with the character whose
    registration was refused ("got further than it can safely restart"), then with a fresh New Game's character."""
    host = s.player("host")
    friend = s.player("friend")
    try:
        check = s.check
        host.start()
        friend.start()
        world = host.world("CI Hosted World")
        require(world is not None, "the earlier run's hosted world is missing")
        slot = next(a["slot"] for a in world["accounts"] if a["slot"] != 0)
        host.choose(host.expect("main"), "host")
        host.choose(host.expect("host_list"), world["world_id"])
        host.choose(host.expect("world"), "host")
        host_game, hosted = check.play(host, world, 0, cp.revision(world, 0) or 0, keep_open=True)
        s.record("hosted-again", head_host=cp.revision(world, 0), head_friend=cp.revision(world, slot))
        account = account_folder(friend.private / "players" / world["world_id"])
        s.record("friend-account-before", files=sorted(p.name for p in account.iterdir()))
        outcomes = []
        for attempt in range(2):
            mark = len(friend.screens())
            to_saved_server(friend)
            screen = friend.expect(("bring_character", "message", "join_list", "session", "graphics"), 180,
                                   where=lambda sc: sc["id"] != "busy")
            if screen["id"] == "bring_character":
                friend.choose(screen, "go")
                screen = friend.expect(("message", "join_list", "session", "graphics"), 180, where=lambda sc: sc["id"] != "busy")
            outcomes.append(dict(attempt=attempt + 1, character="first", screen=notes_of(screen),
                                 menu=statuses_since(friend, mark)))
            s.record("retry-with-the-first-character", **outcomes[-1])
            friend.picture(f"retry-first-{attempt + 1}")
            if screen["id"] != "message":
                break
            friend.key("enter")
        for _ in range(4):
            if friend.current()["id"] == "main":
                break
            friend.key("escape")
            time.sleep(1.5)
        second = check.create_character(friend, existing=1)
        s.record("second-character", character_name=second["name"])
        mark = len(friend.screens())
        to_saved_server(friend)
        screen = friend.expect(("bring_character", "message", "join_list", "session"), 180, where=lambda sc: sc["id"] != "busy")
        if screen["id"] == "bring_character":
            friend.choose(screen, "go")
            screen = friend.expect(("message", "join_list", "session", "graphics"), 180, where=lambda sc: sc["id"] != "busy")
        s.record("join-with-a-fresh-new-game", screen=notes_of(screen), menu=statuses_since(friend, mark),
                 files=sorted(p.name for p in account.iterdir()), head=cp.revision(world, slot))
        friend.picture("fresh-new-game")
        if screen["id"] == "message":
            friend.key("enter")
        else:
            handle = friend.game()
            friend.press_until(handle, "a", lambda: not friend.desk.alive(handle[0]), 300)
            s.record("fresh-new-game-registration", head=cp.revision(world, slot), alive=friend.desk.alive(handle[0]))
        check.close(host, host_game)
        host.expect("host_list", 60)
        s.report["result"] = "completed"
    finally:
        s.cleanup((host, friend))


async def registration_fresh(s):
    """--reuse of a registration run's folder whose friend already made a fresh New Game's character (the active one):
    the host hosts again; the friend joins with that character; what the menu says, and the game if it opens."""
    host = s.player("host")
    friend = s.player("friend")
    try:
        check = s.check
        host.start()
        friend.start()
        world = host.world("CI Hosted World")
        slot = next(a["slot"] for a in world["accounts"] if a["slot"] != 0)
        host.choose(host.expect("main"), "host")
        host.choose(host.expect("host_list"), world["world_id"])
        host.choose(host.expect("world"), "host")
        host_game, hosted = check.play(host, world, 0, cp.revision(world, 0) or 0, keep_open=True)
        account = account_folder(friend.private / "players" / world["world_id"])
        main = friend.expect("main", 60)
        s.record("friend-before", subtitle=main.get("title"), characters=[c["name"] for c in friend.characters()],
                 files=sorted(p.name for p in account.iterdir()))
        for attempt in range(2):
            mark = len(friend.screens())
            to_saved_server(friend)
            screen = friend.expect(("bring_character", "message", "join_list", "session"), 180, where=lambda sc: sc["id"] != "busy")
            first = notes_of(screen)
            if screen["id"] == "bring_character":
                friend.choose(screen, "go")
                screen = friend.expect(("message", "join_list", "session", "graphics"), 180, where=lambda sc: sc["id"] != "busy")
            s.record("join-with-the-fresh-character", attempt=attempt + 1, first=first, screen=notes_of(screen),
                     menu=statuses_since(friend, mark), files=sorted(p.name for p in account.iterdir()),
                     head=cp.revision(world, slot))
            friend.picture(f"fresh-{attempt + 1}")
            if screen["id"] != "message":
                break
            friend.key("enter")
        check.close(host, host_game)
        host.expect("host_list", 60)
        s.report["result"] = "completed"
    finally:
        s.cleanup((host, friend))


def host_with_codes(check, host, count):
    """check.host (This PC only), copying the invite codes of the first ``count`` friends' places before hosting; returns
    (world, [(code, slot)], host_game)."""
    from emerald_multiplayer.invite_code import decode_invite
    main = host.expect("main")
    host.choose(main, "host")
    host.choose(host.expect("host_list"), "create")
    host.expect("create_world")
    host.key("backspace", 40)
    host.text("CI Hosted World")
    host.key("enter")
    host.key("backspace", 30)
    host.text("Host")
    host.key("enter")
    host.key("enter")
    host.key("enter")
    host.choose(host.expect("choose"), "127.0.0.1")
    host.choose(host.expect("create_world"), "create")
    world = wait(lambda: host.world("CI Hosted World"), 120)
    require(world, "the hosted world was not created")
    codes = []
    host.choose(host.expect("world", 60), "codes")
    for index in range(count):
        screen = host.expect("codes")
        check.desk.clear_clipboard()
        before = check.desk.clipboard().strip()
        host.choose(screen, screen["items"][index][1])
        code = wait(lambda: (lambda c: c if c and c != before else None)(check.desk.clipboard().strip()), 20)
        require(code, f"no invite code was copied for place {index + 1}")
        codes.append((code, decode_invite(code).slot))
        host.log(f"copied the invite code for {screen['items'][index][2]}: slot {codes[-1][1]}")
    host.expect("codes", 10)
    host.key("escape")
    host.choose(host.expect("world"), "host")
    game, result = check.enter_and_play(host, world, 0, keep_open=True)
    return world, codes, game


def join_code(friend, code):
    main = friend.expect("main", 60)
    friend.choose(main, "join")
    friend.choose(friend.expect("join_list"), "new")
    friend.expect("join_new")
    friend.text(code)
    for _ in ("name", "address", "port", "join"):
        friend.key("enter")
    friend.key("enter")


async def p15(s):
    """P15 (and NU-1's restart): three friends' places in one hosted world; each friend's registration game is ended with
    SIGKILL at a planned moment: before the field (the game restarts its setup), or a moment after it reaches the field
    (the registration's save requested of it: a request in flight). Every message is read."""
    host = s.player("host")
    friends = [s.player(f"friend{n}") for n in (1, 2, 3)]
    plans = {0: [dict(wait_before=w) for w in (1.5, 3.0, 4.5, 6.0, 7.0)] + [dict(field_delay=0.0)],
             1: [dict(field_delay=0.25)], 2: [dict(field_delay=0.6)]}
    try:
        check = s.check
        host.start()
        check.create_character(host)
        world, codes, host_game = host_with_codes(check, host, 3)
        s.record("hosted", world=world["name"], slots=[slot for _, slot in codes])
        messages = []
        for n, friend in enumerate(friends):
            friend.start()
            check.create_character(friend)
            code, slot = codes[n]
            join_code(friend, code)
            for k, when in enumerate(plans[n]):
                if k > 0:
                    to_saved_server(friend)
                after, done = kill_registration(s, friend, world, slot, label=f"friend{n + 1}-kill-{k + 1}", **when)
                messages.append(dict(friend=n + 1, kill=k + 1, **when, screen=after["id"], title=after["title"],
                                     notes=after["notes"][:2], registered_before_the_kill=done))
                if done or "got further" in json.dumps(after["notes"]):
                    break
                if after["id"] == "message":
                    friend.key("enter")
            # one more join after the last kill: restarted, or refused?
            mark = len(friend.screens())
            to_saved_server(friend)
            screen = friend.expect(("bring_character", "message", "join_list", "session"), 180,
                                   where=lambda sc: sc["id"] != "busy")
            if screen["id"] == "bring_character":
                friend.choose(screen, "go")
                screen = friend.expect(("message", "join_list", "session", "graphics", "busy"), 60,
                                       where=lambda sc: sc["id"] != "busy" or "stand in the field" in " ".join(sc["notes"]))
            s.record("join-after-the-kills", friend=n + 1, screen=notes_of(screen), menu=statuses_since(friend, mark),
                     files=sorted(p.name for p in account_folder(friend.private / "players" / world["world_id"]).iterdir()))
            friend.picture(f"friend{n + 1}-after-kills")
            if screen["id"] != "message":
                # a registration game is running: let it finish (CONTINUE) and close
                handle = friend.game()
                friend.press_until(handle, "a", lambda: not friend.desk.alive(handle[0]), 240)
                s.record("registered-after-the-kills", friend=n + 1, head=cp.revision(world, slot),
                         alive=friend.desk.alive(handle[0]))
                if friend.desk.alive(handle[0]):
                    check.close(friend, handle)
        s.record("p15-messages", messages=messages, kills=len(messages),
                 game_closed_unexpectedly=sum("closed unexpectedly" in json.dumps(m) for m in messages),
                 connection_lost=sum("connection to the server was lost" in json.dumps(m).lower() for m in messages))
        check.close(host, host_game)
        s.report["result"] = "completed"
    finally:
        s.cleanup([host] + friends)


# ------------------------------------------------------------------ MS-257

async def port_in_use(s):
    """KNOWN_ISSUES MS-257: the host's world is created (its port, 7777, free then); another program then listens on that
    port (a plain socket of this check's, on the world's own address) and the host enters the world for the first
    time: the character setup must stop with the port's own reason in the menu - not "Close the running host", not
    "could not finish" - and, once that program has closed, the same entry registers the character and plays."""
    import socket
    host = s.player("host")
    try:
        check = s.check
        host.start()
        check.create_character(host)
        main = host.expect("main")
        host.choose(main, "host")
        host.choose(host.expect("host_list"), "create")
        form = host.expect("create_world")
        host.key("backspace", 40)
        host.text("CI Hosted World")
        host.key("enter")
        host.key("backspace", 30)
        host.text("Host")
        host.key("enter")                          # Port (kept)
        host.key("enter")                          # the Network row
        if check.loopback:                         # as ci_play_check.host: This PC only
            host.key("enter")
            host.choose(host.expect("choose"), "127.0.0.1")
            host.choose(host.expect("create_world"), "create")
        else:
            focusable = [item[1] for item in form["items"] if "d" not in item[3]]
            host.key("down", focusable.index("create") - focusable.index("network"))
            host.key("enter")
        world = wait(lambda: host.world("CI Hosted World"), 120)
        require(world, f"the world was not created ({host.current() and host.current()['notes'][:2]})")
        address, port = world["bind_address"], world["descriptor"]["port"]
        s.record("world-created", world=world["name"], address=address, port=port)
        screen = host.expect("world", 60)
        other = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        other.bind((address, port))
        other.listen(1)
        s.record("another-program-listens", address=address, port=port)
        try:
            host.choose(screen, "host")
            first = host.expect(("bring_character", "graphics", "message", "host_list", "session"), 120)
            if first["id"] == "bring_character":       # the character's first visit: Continue, as a player does
                host.choose(first, "go")
                first = host.expect(("graphics", "message", "host_list", "session"), 120)
            refused = first
            if refused["id"] == "graphics":           # the 3D question (this PC cannot run 3D): Classic 2D
                host.choose(refused, "classic")
                refused = host.expect(("message", "host_list", "session"), 120)
            s.record("entered-with-the-port-taken", menu=notes_of(refused))
            host.picture("port-in-use-message")
            words = json.dumps(notes_of(refused))
            require(refused["id"] == "message" and "port is already in use" in words,
                    f"the menu did not give the port's reason: {notes_of(refused)}")
            require("Close the running host before" not in words and "could not finish" not in words,
                    f"the menu gave the old or no reason: {notes_of(refused)}")
        finally:
            other.close()
        s.record("the-other-program-closed")
        host.key("enter")
        for _ in range(4):
            current = host.current()
            if current and current["id"] == "world":
                break
            if current and current["id"] == "host_list":
                rows = [item for item in current["items"] if item[2] and "CI Hosted World" in item[2]]
                host.choose(current, rows[0][1] if rows else current["items"][0][1])
                continue
            host.key("escape")
            time.sleep(1.5)
        host.choose(host.expect("world", 60), "host")
        game, result = check.enter_and_play(host, world, 0, keep_open=True)
        s.record("entered-after-the-port-was-free", result=result, head=cp.revision(world, 0))
        check.close(host, game)
        host.expect("host_list", 60)
        check.finish(host)
        s.report["result"] = "completed"
    finally:
        s.cleanup((host,))


async def close_after_save(s):
    """KNOWN_ISSUES MS-259: CONTINUE, Save now, and the game closed as soon as the save is in the world - the play
    check's own sequence, in which the audit once saw "This save needs recovery" for 0.2 s - ``--cycles`` times. Every
    status the menu showed meanwhile is read from its screen log, so a status of a fraction of a second is caught. No
    cycle may show the recovery warning or "Connection to the host was lost": the game was closed normally, nothing was
    saving; each cycle's save must be in the world."""
    host = s.player("host")
    try:
        check = s.check
        host.start()
        check.create_character(host)
        main = host.expect("main")
        host.choose(main, "solo")
        host.choose(host.expect("solo"), "new")
        screen = host.expect(("ask_text", "trade_rule"))
        if screen["id"] == "trade_rule":
            host.choose(screen, cp.RULE)
            screen = host.expect("ask_text")
        host.key("enter")
        host.key("enter")
        world = wait(lambda: host.world(host.worlds()[-1]["name"]) if host.worlds() else None, 60)
        require(world and world["kind"] == "adventure", "no Solo world was created")
        handle, played = check.enter_and_play(host, world, 0, keep_open=True)
        s.record("solo-world-played", world=world["name"], result=played)
        check.close(host, handle)
        host.expect(("main", "solo"), 120)
        false_warnings = ("needs recovery", "Connection to the host was lost")
        cycles = []
        for n in range(s.args.cycles):
            while host.current()["id"] != "main":
                host.key("escape")
                time.sleep(1.5)
            mark = len(host.screens())
            host.choose(host.expect("main", 30), "continue")
            _, result = check.play(host, world, 0, cp.revision(world, 0))
            host.expect(("main", "solo"), 120)
            time.sleep(1.5)
            shown = statuses_since(host, mark)
            alarms = [row for row in shown if row[1] and any(text in row[1] for text in false_warnings)]
            cycles.append(dict(n=n + 1, saved=result["saved"], alarms=alarms))
            s.record("cycle", n=n + 1, saved=result["saved"], alarms=alarms, shown=shown[-6:])
        s.record("cycles", count=len(cycles), saved=[c["saved"] for c in cycles],
                 with_a_false_warning=[c["n"] for c in cycles if c["alarms"]])
        require(not any(c["alarms"] for c in cycles),
                "a normal close showed a false warning in cycle(s) " + ", ".join(str(c["n"]) for c in cycles if c["alarms"]))
    finally:
        s.cleanup([host])


async def close_after_save_joined(s):
    """KNOWN_ISSUES MS-259 for a friend in a hosted world (the audit saw it there, dfh-fix-1): the host's world (This PC
    only), the friend joined; then ``--cycles`` times the friend joins again through its saved server, CONTINUE, Save
    now and the game closed as soon as the save is in the world (the play check's rejoin). Every status the friend's
    menu showed is read from its screen log: no "This save needs recovery" and no "Connection to the host was lost" at
    a normal close; each save in the host's world."""
    host, friend = s.player("host"), s.player("friend")
    try:
        check = s.check
        world, code, slot, host_game, friend_game = host_and_friend(s, host, friend)
        check.close(friend, friend_game)
        after = friend.expect(("join_list", "message", "main"), 120)
        if after["id"] == "message":
            friend.key("enter")
        false_warnings = ("needs recovery", "Connection to the host was lost")
        cycles = []
        for n in range(s.args.cycles):
            head = cp.revision(world, slot)
            mark = len(friend.screens())
            result = check.rejoin(friend, world, slot)
            friend.expect(("join_list", "message", "main"), 120)
            time.sleep(1.5)
            shown = statuses_since(friend, mark)
            alarms = [row for row in shown if row[1] and any(text in row[1] for text in false_warnings)]
            saved = cp.revision(world, slot)
            cycles.append(dict(n=n + 1, head=[head, saved], alarms=alarms))
            s.record("cycle", n=n + 1, head=[head, saved], result=result, alarms=alarms, shown=shown[-6:])
            current = friend.current()
            if current and current["id"] == "message":
                friend.key("enter")
        s.record("cycles", count=len(cycles), heads=[c["head"] for c in cycles],
                 with_a_false_warning=[c["n"] for c in cycles if c["alarms"]])
        check.close(host, host_game)
        host.expect("host_list", 60)
        for player in (friend, host):
            check.finish(player)
        require(all(c["head"][1] > c["head"][0] for c in cycles), f"a save did not reach the host's world: {cycles}")
        require(not any(c["alarms"] for c in cycles),
                "a normal close showed a false warning in cycle(s) " + ", ".join(str(c["n"]) for c in cycles if c["alarms"]))
        s.report["result"] = "completed"
    finally:
        s.cleanup((host, friend))


SCENARIOS = {"disk-full-player": disk_full_player, "disk-full-host": disk_full_host, "copies": copies,
             "registration": registration, "connection": connection, "registration-again": registration_again,
             "registration-fresh": registration_fresh, "p15": p15, "port-in-use": port_in_use,
             "close-after-save": close_after_save, "close-after-save-joined": close_after_save_joined}


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--linux-app":
        raise SystemExit(linux_app(sys.argv[2], sys.argv[3]))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--display", action="append", default=[])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--tmpfs", default="24m", help="the small file system's size (disk-full scenarios)")
    parser.add_argument("--watch", type=float, default=15.0, help="seconds watched after an in-game save")
    parser.add_argument("--saves", type=int, default=44, help="copies: Save now this many times")
    parser.add_argument("--extra-saves", type=int, default=3, help="copies: Save now this many times before the launcher is ended")
    parser.add_argument("--kills", type=int, default=10, help="registration: killed attempts")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--cycles", type=int, default=8, help="close-after-save: play, Save now and close this many times")
    parser.add_argument("--reuse", action="store_true", help="registration-again: continue in an earlier run's --work")
    parser.add_argument("--linux-app", nargs=2, metavar=("INSTALLATION", "PROFILE"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.linux = True
    s = Setup(args)
    try:
        asyncio.run(SCENARIOS[args.scenario](s))
    except CheckFailed as error:
        s.report["result"] = "failed: " + str(error)
        s.check.log("check failed: " + str(error))
        try:
            s.check.picture("failure")
        except Exception:                                               # noqa: BLE001
            pass
        s.persist()
        raise SystemExit(1)
    except BaseException as error:
        s.report["result"] = "error: " + repr(error)
        import traceback
        s.report["traceback"] = traceback.format_exc()
        s.persist()
        raise
    s.persist()


if __name__ == "__main__":
    main()
