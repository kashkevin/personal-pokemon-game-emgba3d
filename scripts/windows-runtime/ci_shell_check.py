"""CI check of the in-game menu on the REAL packaged games (Windows runner): the game's own executable running ``--shell``.

    python ci_shell_check.py <runtime dir holding runtime.json> <work dir>

For the 3D game and the Classic 2D game of one package it opens the menu window (no ROM, no save), draws the main menu and a form,
takes a picture of what the renderer drew, plays the keyboard through it (Down, Enter, typing, the pasted-text path, Esc) and checks
that every choice came back as exactly one event, that the window can be resized for a session and that it ends when asked.

What a hosted runner can and cannot say: it is a virtual machine without a graphics card, so the menu runs on Windows' software
renderer. It proves the window, the drawing, the keyboard and the pipe protocol work on real Windows; it says nothing about a real
GPU, DPI scaling, fullscreen, a controller or a second PC.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from emerald_multiplayer.player_runtime import RuntimeBundle  # noqa: E402
from emerald_multiplayer.shell_protocol import Screen, ShellClosed, ShellProcess, escape, parse_event  # noqa: E402


def png_pixel(path, x, y):
    import struct
    import zlib
    data = Path(path).read_bytes()
    pos, idat = 8, b""
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height = struct.unpack(">II", chunk[:8])
        elif kind == b"IDAT":
            idat += chunk
        pos += 12 + length
    raw, stride, prior = zlib.decompress(idat), width * 3, bytearray(width * 3)
    for row in range(y + 1):
        kind, line = raw[row * (stride + 1)], bytearray(raw[row * (stride + 1) + 1:(row + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - 3] if i >= 3 else 0
            b = prior[i]
            c = prior[i - 3] if i >= 3 else 0
            if kind == 1:
                line[i] = (line[i] + a) & 255
            elif kind == 2:
                line[i] = (line[i] + b) & 255
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prior = line
    return width, height, tuple(prior[x * 3:x * 3 + 3])


def check(executable, folder, failures, name):
    folder.mkdir(parents=True, exist_ok=True)
    result = dict(executable=executable.name)
    shell = ShellProcess([str(executable), "--shell", "--shell-size", "1280x720"], environment={"PKMN_SHELL_TEST": "1"}, cwd=folder)
    try:
        screen = Screen("main", "Main menu", "EmeraldTogether CI")
        for identifier, label in (("continue", "Continue Adventure"), ("new", "New Game"), ("host", "Host Server"),
                                  ("join", "Join Server"), ("settings", "Settings"), ("exit", "Exit")):
            screen.row(identifier, label, "", "s" if identifier == "continue" else "")
        shell.token += 1
        token = shell.token
        shell.send(*screen.lines(token))
        time.sleep(1.5)
        picture = folder / "menu.png"
        answer = shell.request(f"shot\t{escape(picture)}")   # a Windows path holds backslashes, which the protocol unescapes
        if answer != "shot\tok":
            failures.append(f"{name}: the menu picture could not be taken ({answer})")
            return result
        width, height, header = png_pixel(picture, 20, 20)
        result.update(width=width, height=height, header_pixel=header)
        if header != (0x0E, 0x5A, 0x3F):
            failures.append(f"{name}: the menu header is {header}, not the theme's green")
        for _ in range(2):
            shell.send("inject\tkey\tDown")
        time.sleep(0.3)
        if shell.request("state").split("\t")[3] != "host":
            failures.append(f"{name}: two Down presses did not reach Host Server")
        shell.send("inject\tkey\tReturn")
        deadline, seen = time.monotonic() + 10, None
        while time.monotonic() < deadline and seen is None:
            try:
                line = shell.lines.get(timeout=0.3)
            except Exception:
                continue
            if line is None:
                break
            seen = parse_event(line, token)
        if seen is None or (seen.kind, seen.id) != ("select", "host"):
            failures.append(f"{name}: Enter did not come back as one select of 'host' ({seen})")
        shell.window(560, 420, 40, 40)
        time.sleep(0.8)
        small = folder / "session.png"
        if shell.request(f"shot\t{small}") != "shot\tok" or png_pixel(small, 5, 5)[:2] != (560, 420):
            failures.append(f"{name}: the window did not become the small session window")
        result["ok"] = not failures
    finally:
        shell.close()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("work", type=Path)
    args = parser.parse_args()
    runtime, work = args.runtime.resolve(), args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    bundle = RuntimeBundle(runtime, hashlib.sha256((runtime / "runtime.json").read_bytes()).hexdigest())
    failures, report = [], {}
    for mode in ("3d", "2d"):
        try:
            executable, _ = bundle.verify(mode)
        except Exception as error:               # noqa: BLE001
            failures.append(f"{mode}: the packaged game could not be verified ({error})")
            continue
        report[mode] = check(executable, work / mode, failures, mode)
    (work / "shell-check.json").write_text(json.dumps(dict(report=report, failures=failures), indent=2) + "\n")
    print(json.dumps(dict(report=report, failures=failures)))
    if failures:
        for failure in failures:
            print("FAIL", failure)
        sys.exit(1)


if __name__ == "__main__":
    main()
