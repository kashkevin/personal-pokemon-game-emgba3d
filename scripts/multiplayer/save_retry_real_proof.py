"""KNOWN_ISSUES MS-212 in a real game: a save file write that fails is tried again; the window's title and the 3D
pause menu's save say so, then the save is written once the disk has room.

The native game (the 3D test build, or the Classic 2D game) plays its own save, which lives on a small file system
of its own (a tmpfs the caller mounted and names with --fs), driven by ordinary key presses on its own X display; its
state is read from its memory (/proc/PID/mem at nm symbols), never written. Steps:

  1. Boot (title, CONTINUE) to the field; the save file's hash and the save counter in it.
  2. The file system filled to its last byte (a filler file of zeros, written until the disk refuses).
  3. START > SAVE > YES (> YES to overwrite): the game saves; the write of the file fails. Recorded: the window's
     title, the game's failed-try counter, the save screen's state (3D: ui_pause.c sSaveResult 3, "FILE NOT
     WRITTEN"), pictures, the file unchanged on the disk.
  4. --hold seconds later the filler is removed: the next try writes the file. Recorded: the title back, the
     counters, the 3D save screen's SAVED stamp, the file's save counter equal to the game's.
  5. A closes the save screen; the game closed normally (SIGTERM, an ordinary quit); started again on the same
     file, CONTINUE: the game runs the written save (its save counter).

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/save_retry_real_proof.py --game pokeemerald-mp-diorama-bfxtest \\
        --save bench.sav --fs /mnt/small --display :520 --output /private/multiplayer-proof/save-retry-1
"""
from __future__ import annotations

import argparse
import asyncio
import errno
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_battle_proof import NativeProbe, game_picture, symbols_of  # noqa: E402
from emerald_multiplayer.flash import inspect_flash  # noqa: E402

SAVE = 5                 # MENU_ACTION_SAVE (start_menu.c)
LIGHT_3D_SETTINGS = "\n".join(("resolution=640x360", "displayMode=windowed", "renderScale=50", "shadows=off",
                               "lighting=0", "effects=0", "details=0", "antialiasing=0")) + "\n"
FAILING_TITLE = "Pokemon Emerald - the save file could not be written: trying again"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def counter_of(path):
    return inspect_flash(Path(path).read_bytes()).metadata.counter


def u32(probe, name):
    return int.from_bytes(probe.mem(name, 4), "little")


def fill(fs: Path) -> int:
    """Zeros into a filler file until the file system refuses (ENOSPC); returns the bytes written."""
    filler = fs / "filler.bin"
    written = 0
    with open(filler, "wb", buffering=0) as out:
        for size in (1 << 20, 4096, 512, 1):
            chunk = b"\0" * size
            while True:
                try:
                    count = out.write(chunk)
                except OSError as error:
                    if error.errno != errno.ENOSPC:
                        raise
                    break
                written += count or 0
                if not count:
                    break
    return written


class Run:
    def __init__(self, args):
        self.args = args
        self.output = args.output.resolve()
        if "/multiplayer-proof/" not in self.output.as_posix() + "/" or self.output.exists():
            raise SystemExit("choose a new private multiplayer-proof output directory")
        self.output.mkdir(parents=True)
        self.fs = args.fs.resolve()
        self.save = self.fs / "game.sav"
        self.evidence = dict(scope=__doc__.split("\n\n")[0], game=str(args.game), game_sha256=sha(args.game),
                             fs=str(self.fs), checks=[], passed=False)
        self.symbols = symbols_of(args.game)
        self.process = None
        self.probe = None
        self.pictures = 0

    def record(self, name, **fields):
        row = dict(verified=name, seconds=round(time.monotonic() - self.started, 1), **fields)
        self.evidence["checks"].append(row)
        (self.output / "evidence.json").write_text(json.dumps(self.evidence, indent=2) + "\n")
        print(json.dumps(row), flush=True)

    def title(self):
        try:
            window = self.probe._window()
        except RuntimeError:
            return None
        return subprocess.run(["xdotool", "getwindowname", window], env=self.probe.environment, capture_output=True,
                              text=True).stdout.strip()

    def picture(self, label):
        self.pictures += 1
        name = f"{self.pictures:02d}-{label}.png"
        game_picture(self.probe, self.output / name)
        return name

    def state(self):
        p = self.probe
        row = dict(title=self.title(), save_counter=u32(p, "gSaveCounter"),
                   flash_dirty=p.mem("gPlatformFlashDirty", 1)[0], failed_tries=u32(p, "sSaveFailedTries"),
                   lock_field=p.mem("sLockFieldControls", 1)[0])
        if "sSaveWritesDone" in self.symbols:
            row.update(writes_done=u32(p, "sSaveWritesDone"), writes_failed=u32(p, "sSaveWritesFailed"))
        if "sSaveResult" in self.symbols:
            row["pause_save_result"] = u32(p, "sSaveResult")     # 3D: 0 not yet, 1 written, 2 engine error, 3 file not written
        try:
            row.update(file_sha256=sha(self.save)[:16], file_counter=counter_of(self.save))
        except (OSError, ValueError) as error:
            row["file_error"] = repr(error)
        row["tmp_exists"] = (self.fs / "game.sav.tmp").exists()
        return row

    def start_game(self, label):
        env = dict(os.environ, DISPLAY=self.args.display, SDL_AUDIODRIVER="dummy")
        log = (self.output / f"game-{label}.log").open("wb")
        command = [str(self.args.game), "--save", str(self.save), "--config", str(self.output / "game-settings.cfg")]
        self.process = subprocess.Popen(command, cwd=self.output, stdout=log, stderr=subprocess.STDOUT, env=env)
        self.probe = NativeProbe(self.process.pid, self.symbols, self.args.display, lambda *a, **k: None)
        self.record("game-started", label=label, pid=self.process.pid, command=[Path(command[0]).name, *command[1:]])

    def in_field(self):
        callback2 = int.from_bytes(self.probe.mem("gMain", 4, 4), "little")
        return callback2 == self.symbols["CB2_Overworld"][0] and self.probe.mem("sLockFieldControls", 1)[0] == 0

    async def boot(self, label):
        await self.probe.boot(self.args.slow)
        deadline = time.monotonic() + 120 * self.args.slow
        while not self.in_field():
            if time.monotonic() > deadline:
                self.picture(f"{label}-boot-timeout")
                raise AssertionError("the game did not reach the field")
            await self.probe.press(1)
            await asyncio.sleep(3)
        await asyncio.sleep(2)
        self.record("in-the-field", label=label, **self.state())

    async def save_in_game(self):
        """START > SAVE > YES (> YES to overwrite), until the game's own save counter moves on."""
        p = self.probe
        before = u32(p, "gSaveCounter")
        await p.press(8, release=60)
        row = await p.snapshot(lambda r: 0 < r["count"] <= len(r["actions"]) and SAVE in r["actions"][:r["count"]],
                               timeout=30)
        target = row["actions"][:row["count"]].index(SAVE)
        for _ in range((target - row["start_cursor"]) % row["count"]):
            await p.press(128)
        self.picture("start-menu-on-save")
        presses = 0
        async with asyncio.timeout(90):
            while u32(p, "gSaveCounter") == before:
                await p.press(1)
                presses += 1
                await asyncio.sleep(.5)
        self.record("the-game-saved-in-memory", counter_before=before, presses=presses, **self.state())
        return before

    async def brief_outage(self, first_hash):
        """--free-after S: the disk has room again S seconds after the failure is first seen, while the 3D save screen
        still shows it (a brief hold, as an antivirus's): the next try (1 s after the first) writes the file, and the
        save screen turns to SAVED before it closes."""
        async with asyncio.timeout(30):
            while True:
                failing = self.state()
                if failing["failed_tries"] > 0:
                    break
                await asyncio.sleep(.05)
        seen_at = time.monotonic()
        failing["file_unchanged"] = sha(self.save) == first_hash
        self.record("write-failed", **failing)
        await asyncio.sleep(max(0.0, self.args.free_after - (time.monotonic() - seen_at)))
        (self.fs / "filler.bin").unlink()
        self.record("fs-freed", seconds_after_failure=round(time.monotonic() - seen_at, 2))
        rows, pictures = [], []
        async with asyncio.timeout(60):
            while True:
                now = self.state()
                now["t"] = round(time.monotonic() - seen_at, 2)
                if not rows or {k: v for k, v in now.items() if k != "t"} != {k: v for k, v in rows[-1].items() if k != "t"}:
                    rows.append(now)
                    if now.get("pause_save_result") == 1 and now["lock_field"] == 1 and len(pictures) < 2:
                        pictures.append(self.picture("saved-stamp"))
                if now["failed_tries"] == 0 and now["flash_dirty"] == 0 and now["lock_field"] == 0:
                    break
                await asyncio.sleep(.05)
        game_counter = u32(self.probe, "gSaveCounter")
        shown_saved = any(r.get("pause_save_result") == 1 and r["lock_field"] == 1 for r in rows)
        self.record("after-the-brief-outage", states=rows, pictures=pictures, shown_saved_on_the_save_screen=shown_saved,
                    file_counter=counter_of(self.save), game_counter=game_counter)
        os.kill(self.process.pid, signal.SIGTERM)
        code = self.process.wait(30)
        self.record("game-closed", exit_code=code, file_counter=counter_of(self.save))
        errors = self.output / "errors.log"
        self.evidence["errors_log"] = errors.read_text(errors="replace") if errors.exists() else None
        self.evidence["passed"] = bool(failing["file_unchanged"] and (shown_saved or "sSaveResult" not in self.symbols)
                                       and counter_of(self.save) == game_counter and code == 0)
        self.record("result", passed=self.evidence["passed"])

    async def run(self):
        self.started = time.monotonic()
        args = self.args
        (self.output / "game-settings.cfg").write_text(LIGHT_3D_SETTINGS if args.light_3d else "")
        self.save.write_bytes(args.save.read_bytes())
        source_counter = counter_of(self.save)
        self.record("save-on-small-fs", path=str(self.save), counter=source_counter,
                    df=subprocess.run(["df", "-B1", str(self.fs)], capture_output=True, text=True).stdout.splitlines()[-1])
        try:
            self.start_game("first")
            await self.boot("first")
            first_hash = sha(self.save)
            self.picture("field-before")
            # 2. The disk full.
            filled = fill(self.fs)
            self.record("fs-filled", filler_bytes=filled,
                        df=subprocess.run(["df", "-B1", str(self.fs)], capture_output=True, text=True).stdout.splitlines()[-1])
            # 3. The in-game save with the disk full.
            await self.save_in_game()
            if args.free_after is not None:
                await self.brief_outage(first_hash)
                return
            seen = []
            fail_deadline = time.monotonic() + 30
            while time.monotonic() < fail_deadline:
                now = self.state()
                if now["title"] not in seen:
                    seen.append(now["title"])
                if now["failed_tries"] > 0 and now["title"] == FAILING_TITLE and \
                        ("pause_save_result" not in now or now["pause_save_result"] == 3):
                    break
                await asyncio.sleep(.25)
            await asyncio.sleep(1.5)
            failing = self.state()
            failing["picture"] = self.picture("save-failed")
            failing["titles_seen"] = seen
            failing["file_unchanged"] = sha(self.save) == first_hash
            self.record("write-failed-and-said", **failing)
            ok = (failing["failed_tries"] > 0 and failing["title"] == FAILING_TITLE and failing["file_unchanged"]
                  and failing["flash_dirty"] == 1)
            if "pause_save_result" in failing:
                ok = ok and failing["pause_save_result"] == 3
            self.evidence["failure_shown"] = ok
            # Still failing a while later (the tries go on: 1 s, 2, 4 ...).
            hold_until = time.monotonic() + args.hold
            while time.monotonic() < hold_until:
                await asyncio.sleep(1)
            later = self.state()
            later["picture"] = self.picture("still-failing")
            self.record("still-failing-after-hold", hold=args.hold, **later)
            # 4. Room again.
            (self.fs / "filler.bin").unlink()
            freed_at = time.monotonic()
            self.record("fs-freed", df=subprocess.run(["df", "-B1", str(self.fs)], capture_output=True,
                                                      text=True).stdout.splitlines()[-1])
            written = None
            async with asyncio.timeout(60):
                while True:
                    now = self.state()
                    if now["failed_tries"] == 0 and now["flash_dirty"] == 0 and now["title"] == "Pokemon Emerald":
                        written = now
                        break
                    await asyncio.sleep(.25)
            written["seconds_after_freeing"] = round(time.monotonic() - freed_at, 1)
            await asyncio.sleep(1.0)
            written["picture"] = self.picture("written-after-freeing")
            written["after_picture"] = self.state()
            game_counter = u32(self.probe, "gSaveCounter")
            written["file_counter_matches_game"] = counter_of(self.save) == game_counter
            self.record("written-once-there-was-room", **written)
            # 5. Close the save screen, close the game, start again.
            for _ in range(6):
                if self.in_field():
                    break
                await self.probe.press(1)
                await asyncio.sleep(1)
            self.picture("field-after-save")
            os.kill(self.process.pid, signal.SIGTERM)
            code = self.process.wait(30)
            self.record("game-closed", exit_code=code, file_counter=counter_of(self.save), file_sha256=sha(self.save)[:16])
            self.start_game("again")
            await self.boot("again")
            again_counter = u32(self.probe, "gSaveCounter")
            self.picture("continued-again")
            self.record("continued-on-the-written-save", game_counter=again_counter, written_counter=game_counter)
            os.kill(self.process.pid, signal.SIGTERM)
            code2 = self.process.wait(30)
            self.record("game-closed-again", exit_code=code2)
            errors = self.output / "errors.log"
            self.evidence["errors_log"] = errors.read_text(errors="replace") if errors.exists() else None
            self.evidence["passed"] = bool(ok and written["file_counter_matches_game"] and again_counter == game_counter
                                           and code == 0 and code2 == 0)
            self.record("result", passed=self.evidence["passed"])
        finally:
            if self.process is not None and self.process.poll() is None:
                self.process.kill()
                self.process.wait(10)
            filler = self.fs / "filler.bin"
            if filler.exists():
                filler.unlink()
            (self.output / "evidence.json").write_text(json.dumps(self.evidence, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--save", type=Path, required=True, help="the save to play (copied onto --fs)")
    parser.add_argument("--fs", type=Path, required=True, help="a small file system of its own (a tmpfs)")
    parser.add_argument("--display", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--hold", type=float, default=20.0, help="seconds the disk stays full after the save")
    parser.add_argument("--light-3d", action="store_true", help="the light 3D settings (software OpenGL)")
    parser.add_argument("--free-after", type=float,
                        help="instead of --hold: room again this many seconds after the failure is first seen (a brief hold)")
    asyncio.run(Run(parser.parse_args()).run())


if __name__ == "__main__":
    main()
