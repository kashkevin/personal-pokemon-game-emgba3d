"""Apply the project-owned SDL integration to a clean pinned mGBA worktree."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

PIN = "26b7884bc25a5933960f3cdcd98bac1ae14d42e2"


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError("pinned SDL source does not match the reviewed replacement")
    return text.replace(before, after)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worktree", type=Path)
    args = parser.parse_args()
    root = args.worktree.resolve()
    revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if revision != PIN:
        raise ValueError("use a separate worktree at the exact qualified mGBA source")
    for relative in ("src/platform/sdl/main.c", "src/platform/sdl/sdl-events.c"):
        if subprocess.check_output(["git", "-C", str(root), "diff", "HEAD", "--", relative]):
            raise ValueError("preserve existing SDL edits; this preparation requires clean files")
    main_path = root / "src/platform/sdl/main.c"
    text = main_path.read_text()
    text = replace_once(text, '#include "main.h"', '#include "main.h"\n#include "sdl-multiplayer.h"')
    text = replace_once(text, 'struct mSubParser subparser;', 'struct mSubParser subparsers[2];')
    text = replace_once(text, 'mSubParserGraphicsInit(&subparser, &graphicsOpts);',
        'mSubParserGraphicsInit(&subparsers[0], &graphicsOpts);\n\tmSDLMultiplayerParserInit(&subparsers[1]);')
    text = text.replace('&subparser, 1', 'subparsers, 2')
    text = replace_once(text, 'if (!args.fname && !args.showVersion) {',
        'if ((!args.fname && !args.showVersion) || !mSDLMultiplayerValidate(&args)) {')
    text = replace_once(text, 'mCoreLoadConfig(renderer.core);',
        'mCoreLoadConfig(renderer.core);\n\tmSDLMultiplayerConfigure(renderer.core);')
    text = replace_once(text, 'mCoreAutoloadSave(renderer->core);\n\tmCoreAutoloadCheats(renderer->core);',
        'if (mSDLMultiplayerEnabled()) {\n\t\tif (!mSDLMultiplayerLoad(&thread, &_logger.d)) return 1;\n\t} else {\n\t\tmCoreAutoloadSave(renderer->core);\n\t\tmCoreAutoloadCheats(renderer->core);\n\t}')
    text = replace_once(text, '} else {\n\t\tmCoreAutoloadPatch(renderer->core);',
        '} else if (!mSDLMultiplayerEnabled()) {\n\t\tmCoreAutoloadPatch(renderer->core);')
    text = replace_once(text, '\trenderer->core->unloadROM(renderer->core);',
        '\tmSDLMultiplayerUnload();\n\trenderer->core->unloadROM(renderer->core);')
    events_path = root / "src/platform/sdl/sdl-events.c"
    events = events_path.read_text()
    events = '#include "sdl-multiplayer.h"\n' + events
    events = replace_once(events, '\tif (event->keysym.sym == SDLK_TAB) {',
        '\tif (mSDLMultiplayerBlockHotkey(&event->keysym)) return;\n\tif (event->keysym.sym == SDLK_TAB) {')
    project = Path(__file__).resolve().parents[2]
    adapters = []
    for name in ("sdl-multiplayer.h", "sdl-multiplayer.c"):
        target = root / "src/platform/sdl" / name
        if target.exists():
            raise ValueError("refusing to overwrite an existing project adapter")
        adapters.append((target, (project / "native" / "windows-runtime" / name).read_bytes()))
    # Check every transformation and destination before changing upstream files.
    main_path.write_text(text)
    events_path.write_text(events)
    for target, data in adapters:
        target.write_bytes(data)
    print("Prepared pinned SDL frontend; original mGBA core unchanged")


if __name__ == "__main__":
    main()
