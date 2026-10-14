"""CI check of Graphics mode against the REAL packaged games (Windows runner).

    python ci_graphics_check.py <runtime dir holding runtime.json> <work dir> [--expect-3d unsupported|supported|any]

For the 3D and the Classic 2D game of one package it checks, using the launcher's own code
(`graphics_mode`, `RuntimeBundle`):

 1. the 3D check gives a definite answer (supported, or "unsupported" with exit 78 and a reason):
    never a hang, a crash or garbage;
 2. the launch decision that answer leads to: 3D when supported; otherwise "ask", and Launch in
    Classic 2D then selects the pinned 2D game while the saved preference stays 3D;
 3. the Classic 2D game passes its own check and stays running;
 4. the real 3D game agrees with its check: when 3D is unsupported it exits 78 with a message
    (never silently); when supported it stays running;
 5. a forced renderer failure (PKMN_GRAPHICS_FORCE_FAIL) exits 78 in both games, and the failed
    start creates no save or settings file;
 6. the Classic 2D game keeps the 3D view's settings lines when it rewrites the settings file.

What a hosted runner can and cannot say: it is a virtual machine without a graphics card, whose
OpenGL is Windows' built-in 1.1 software renderer. So it proves the FAILURE path and the 2D
fallback work on a PC whose driver cannot do 3D (the case this feature is for). It says nothing
about real GPUs, vendor drivers, DPI, fullscreen, audio or controllers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from emerald_multiplayer.graphics_mode import (EXIT_GRAPHICS_UNAVAILABLE, GraphicsPreference, choose_launch,  # noqa: E402
                                               explain_failure, probe_graphics)
from emerald_multiplayer.player_runtime import RuntimeBundle  # noqa: E402

KEEP = "cameraMode=diorama treeStyle=1 adventureZoom=3 adventureTilt=-2 dioramaZoom=1 dioramaTilt=2".split()
SECONDS_UP = 20


def run_game(executable, work, name, env_extra=None, *, stay=SECONDS_UP, limit=90):
    """Start a game as the launcher does (a save and settings path, no bridge). Returns
    (exit code or None while it was still running, its output)."""
    folder = work / name
    folder.mkdir(parents=True)
    env = dict(os.environ, PKMN_GRAPHICS_NO_DIALOG="1", **(env_extra or {}))
    log = folder / "output.txt"
    with log.open("wb") as out:
        process = subprocess.Popen([str(executable), "--save", str(folder / "game.sav"), "--config",
                                    str(folder / "game-settings.cfg")], cwd=folder, env=env,
                                   stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + (stay if stay else limit)
        code = None
        while time.monotonic() < deadline:
            code = process.poll()
            if code is not None:
                break
            time.sleep(0.25)
        if code is None:
            process.kill()
            process.wait()
    return code, log.read_text("utf-8", "replace"), folder


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("--expect-3d", choices=("unsupported", "supported", "any"), default="any")
    args = parser.parse_args()
    runtime, work = args.runtime.resolve(), args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    pin = hashlib.sha256((runtime / "runtime.json").read_bytes()).hexdigest()
    bundle = RuntimeBundle(runtime, pin)
    game3d, _ = bundle.verify("3d")
    game2d, _ = bundle.verify("2d")
    report, failures = dict(game_3d=game3d.name, game_2d=game2d.name), []

    def check(name, ok, detail=""):
        report.setdefault("checks", []).append(dict(check=name, passed=bool(ok), detail=detail))
        print(("PASS " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""), flush=True)
        if not ok:
            failures.append(name)

    # 1. the 3D check
    probe3 = probe_graphics(game3d)
    report["probe_3d"] = probe3.__dict__
    print("3D check:", probe3, flush=True)
    check("3D check gives a definite answer (not a hang, crash or garbage)",
          probe3.supported or (probe3.reason != "probe_failed" and probe3.reason != ""), str(probe3.reason))
    if args.expect_3d != "any":
        check(f"3D is {args.expect_3d} here, as expected", probe3.supported == (args.expect_3d == "supported"))

    # 2. the decision that follows, with the real bundle and a real (temporary) preference
    preference = GraphicsPreference(work / "private")
    choice = choose_launch(preference.mode, lambda: probe3)
    if probe3.supported:
        check("decision: 3D supported -> starts 3D without asking", choice.mode == "3d" and not choice.ask)
    else:
        check("decision: 3D unsupported -> the player is asked first", choice.mode is None and choice.ask)
        text = explain_failure(probe3)
        check("the explanation names Classic 2D and promises the save is unchanged",
              "Classic 2D" in text and "saves, Pokémon, items" in text)
        fallback = RuntimeBundle(runtime, pin, graphics="2d").verify()[0]
        check("Launch in Classic 2D selects the pinned 2D game", fallback == game2d)
        check("the saved preference is still 3D (not forced to 2D)", GraphicsPreference(work / "private").mode == "3d"
              and not (work / "private" / "graphics-mode.json").exists())
    check("manual 2D never runs the 3D check", choose_launch("2d", lambda: 1 / 0).mode == "2d")

    # 3. Classic 2D
    probe2 = probe_graphics(game2d)
    report["probe_2d"] = probe2.__dict__
    print("2D check:", probe2, flush=True)
    check("Classic 2D passes its own check", probe2.supported, f"{probe2.reason} {probe2.detail}")
    code, output, _ = run_game(game2d, work, "classic-start")
    check(f"Classic 2D game stays running for {SECONDS_UP} s", code is None, f"exit {code}: {output[-300:]}")

    # 4. the real 3D game agrees with its check
    if probe3.supported:
        code, output, _ = run_game(game3d, work, "diorama-start")
        check(f"3D game stays running for {SECONDS_UP} s", code is None, f"exit {code}: {output[-300:]}")
    else:
        code, output, folder = run_game(game3d, work, "diorama-start", stay=0)
        check("3D game with unsupported graphics exits 78, not silently or by crash",
              code == EXIT_GRAPHICS_UNAVAILABLE, f"exit {code}")
        check("it says why (message printed)", "could not start its 3D graphics" in output and "untouched" in output,
              output[-300:])
        check("the failed 3D start created no save", not (folder / "game.sav").exists())

    # 5. a forced failure, both games
    for label, game in (("3D", game3d), ("Classic 2D", game2d)):
        code, output, folder = run_game(game, work, "forced-" + label.replace(" ", "").lower(),
                                        dict(PKMN_GRAPHICS_FORCE_FAIL="ci"), stay=0)
        check(f"{label} game: forced renderer failure exits 78 with an explanation",
              code == EXIT_GRAPHICS_UNAVAILABLE and "could not start" in output, f"exit {code}")
        check(f"{label} game: a failed start creates no save or settings file",
              not (folder / "game.sav").exists() and not (folder / "game-settings.cfg").exists())

    # 6. settings pass-through in Classic 2D
    folder = work / "keep"
    folder.mkdir()
    (folder / "game-settings.cfg").write_text("\n".join(KEEP + ["volume=5"]) + "\n")
    env = dict(os.environ, PKMN_GRAPHICS_NO_DIALOG="1")
    process = subprocess.Popen([str(game2d), "--save", str(folder / "game.sav"), "--config",
                                str(folder / "game-settings.cfg")], cwd=folder, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    time.sleep(8)
    process.kill()
    process.wait()
    lines = (folder / "game-settings.cfg").read_text().splitlines()
    missing = [line for line in KEEP if line not in lines]
    check("Classic 2D keeps the 3D view's settings lines", not missing and "volume=5" in lines, f"missing {missing}")

    report["environment"] = ("GitHub-hosted Windows runner: a virtual machine without a graphics card (Windows' "
                             "built-in OpenGL 1.1 software renderer). Proves the failure path and the Classic 2D "
                             "fallback on such a PC; real GPUs and drivers are not covered.")
    (work / "graphics-check.json").write_text(json.dumps(report, indent=2))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("### Graphics mode check (real packaged games)\n")
            handle.write(f"- 3D check on this runner: `{'supported' if probe3.supported else 'unsupported'}`"
                         f" ({probe3.reason}: {probe3.detail or probe3.renderer})\n")
            handle.write(f"- Classic 2D check: `{'supported' if probe2.supported else 'unsupported'}` ({probe2.renderer})\n")
            handle.write(f"- {len(report['checks']) - len(failures)} of {len(report['checks'])} checks passed\n")
            handle.write(f"- {report['environment']}\n")
    print(f"{len(report['checks']) - len(failures)} of {len(report['checks'])} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
