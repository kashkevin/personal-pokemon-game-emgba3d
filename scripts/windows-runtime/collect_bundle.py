"""Collect a private pinned SDL runtime with source, notices and relink inputs.

Run in the WSL build environment after build_runtime.sh. No ROM or player data
is copied. A successful collection is not game/distribution acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

from fetch_dependencies import SOURCES
from prepare_frontend import PIN
from sanitize_source import sanitize


def command(*args):
    return subprocess.check_output(args)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(source, dependencies, output):
    source, dependencies, output = source.resolve(), dependencies.resolve(), output.resolve()
    project = Path(__file__).resolve().parents[2]
    if command("git", "-C", str(source), "rev-parse", "HEAD").decode().strip() != PIN:
        raise ValueError("unexpected core source revision")
    modified = command("git", "-C", str(source), "diff", "HEAD", "--name-only").decode().splitlines()
    if set(modified) != {"src/platform/sdl/main.c", "src/platform/sdl/sdl-events.c"}:
        raise ValueError("only the reviewed SDL frontend files may modify tracked mGBA source")
    untracked = command("git", "-C", str(source), "ls-files", "--others", "--exclude-standard").decode().splitlines()
    if set(untracked) != {"src/platform/sdl/sdl-multiplayer.c", "src/platform/sdl/sdl-multiplayer.h"}:
        raise ValueError("unexpected source outside the reviewed frontend adapter")
    for name in ("sdl-multiplayer.c", "sdl-multiplayer.h"):
        if (source / "src/platform/sdl" / name).read_bytes() != (project / "native/windows-runtime" / name).read_bytes():
            raise ValueError("build adapter differs from project source")
    archives = []
    for name, url, digest, _ in SOURCES:
        archive = dependencies / name
        if sha(archive) != digest:
            raise ValueError("source archive differs from its pin")
        archives.append(dict(name=name, url=url, sha256=digest))
    build = source / "build-windows"
    worker_source = project / "native/windows-runtime/trade-replay-worker.c"
    if (build / "trade-replay-worker.c").read_bytes() != worker_source.read_bytes():
        raise ValueError("replay worker build source differs from project source")
    cache = (build / "CMakeCache.txt").read_text()
    for setting in ("BUILD_LTO:BOOL=OFF", "BUILD_STATIC:BOOL=ON", "BUILD_SHARED:BOOL=OFF",
                    "ENABLE_SCRIPTING:BOOL=ON", "USE_LUA:BOOL=ON",
                    "BUILD_TEST:BOOL=OFF", "BUILD_CINEMA:BOOL=OFF", "BUILD_PERF:BOOL=OFF"):
        if setting not in cache.splitlines():
            raise ValueError("unexpected runtime build settings")
    sdl = dependencies / "sdl-devel/SDL2-2.32.10/x86_64-w64-mingw32"
    pthread = Path(command("x86_64-w64-mingw32-gcc", "-print-file-name=libwinpthread-1.dll").decode().strip()).resolve()
    components = {"mgba-sdl.exe": build / "mgba-sdl.exe", "SDL2.dll": sdl / "bin/SDL2.dll",
                  "libwinpthread-1.dll": pthread, "mgba.lua": project / "bridge/mgba.lua",
                  "emerald-trade-replay.exe": build / "emerald-trade-replay.exe"}
    system_dlls = {"advapi32.dll", "gdi32.dll", "imm32.dll", "kernel32.dll", "msvcrt.dll", "ole32.dll",
                   "oleaut32.dll", "setupapi.dll", "shell32.dll", "shlwapi.dll", "user32.dll",
                   "version.dll", "winmm.dll", "ws2_32.dll"}
    imports = {}
    for name in ("mgba-sdl.exe", "emerald-trade-replay.exe", "SDL2.dll", "libwinpthread-1.dll"):
        text = command("x86_64-w64-mingw32-objdump", "-p", str(components[name])).decode()
        imports[name] = re.findall(r"DLL Name:\s*(\S+)", text)
        if any(dll.lower() not in system_dlls | {"sdl2.dll", "libwinpthread-1.dll"} for dll in imports[name]):
            raise ValueError("runtime has an uncollected non-system DLL")
    output.mkdir(parents=True, exist_ok=False)
    for name, path in components.items():
        shutil.copyfile(path, output / name)
    notices = {
        "LICENSE-mGBA.txt": source / "LICENSE",
        "LICENSE-blip-buf.txt": source / "src/third-party/blip_buf/license.txt",
        "LICENSE-inih.txt": source / "src/third-party/inih/LICENSE.txt",
        "LICENSE-libepoxy.txt": dependencies / "epoxy/libepoxy-1.5.10/COPYING",
        "Lua-5.4.9-readme.html": dependencies / "lua/lua-5.4.9/doc/readme.html",
        "LICENSE-MinGW-package.txt": Path("/usr/share/doc/mingw-w64-common/copyright"),
        "LICENSE-GCC-package.txt": Path("/usr/share/doc/gcc-mingw-w64-base/copyright"),
    }
    for name, path in notices.items():
        shutil.copyfile(path, output / name)
    with tarfile.open(dependencies / "SDL2-2.32.10.tar.gz", "r:gz") as archive:
        with archive.extractfile("SDL2-2.32.10/LICENSE.txt") as notice:
            (output / "LICENSE-SDL2.txt").write_bytes(notice.read())
    (output / "frontend.patch").write_bytes(command("git", "-C", str(source), "diff", "HEAD", "--",
                                                   "src/platform/sdl/main.c", "src/platform/sdl/sdl-events.c"))
    for name in ("sdl-multiplayer.c", "sdl-multiplayer.h"):
        shutil.copyfile(project / "native/windows-runtime" / name, output / name)
    with tempfile.TemporaryDirectory(prefix="emerald-mgba-source-") as temporary:
        original_archive = Path(temporary) / "upstream.tar.gz"
        command("git", "-C", str(source), "archive", "--format=tar.gz", "-o", str(original_archive), "HEAD")
        sanitize(original_archive, output / "mGBA-source.tar.gz", output / "source-packaging.json")
    for archive in archives:
        shutil.copyfile(dependencies / archive["name"], output / archive["name"])
    # Keep the work using LGPL blip_buf relinkable. These are private build
    # inputs, with matching source/recipes above; review recipient packaging too.
    relink = {"libmgba.a": build / "libmgba.a",
              "liblua.a": dependencies / "lua/lua-5.4.9/src/liblua.a",
              "libepoxy.a": dependencies / "epoxy-windows/lib/libepoxy.a",
              "libSDL2main.a": sdl / "lib/libSDL2main.a",
              "libSDL2.dll.a": sdl / "lib/libSDL2.dll.a",
              "libwinpthread.dll.a": pthread.parent / "libwinpthread.dll.a",
              "frontend-objects.a": build / "sdl/CMakeFiles/mgba-sdl.dir/objects.a",
              "trade-replay-worker.c": build / "trade-replay-worker.c",
              "trade-replay-worker.obj": build / "trade-replay-worker.obj",
              # Retain build documentation inside the existing source/relink
              # archive so the additional executable fits the strict 32-file
              # runtime manifest without dropping notices or raising the bound.
              "README.md": Path(__file__).with_name("README.md")}
    relink.update({"frontend/" + path.name: path for path in sorted((build / "sdl/CMakeFiles/mgba-sdl.dir").glob("*.obj"))})
    with tarfile.open(output / "relink-inputs.tar.gz", "w:gz") as archive:
        for name, path in relink.items():
            archive.add(path, arcname=name, recursive=False)
    (output / "relink-command.txt").write_text(
        "Extract relink-inputs.tar.gz to one directory. With the qualified MinGW toolchain, run:\n"
        "x86_64-w64-mingw32-gcc -static-libgcc -static-libstdc++ -mwindows "
        "-Wl,--undefined=WinMain -Wl,--whole-archive frontend-objects.a -Wl,--no-whole-archive "
        "-o mgba-sdl.exe libmgba.a libSDL2main.a libSDL2.dll.a libepoxy.a liblua.a "
        "-limm32 -lsetupapi -lversion -lwinmm -lopengl32 -lglu32 -lgdi32 -lws2_32 -lshlwapi "
        "-lm -lkernel32 -luser32 -lwinspool -lshell32 -lole32 -loleaut32 -luuid -lcomdlg32 -ladvapi32\n"
        "Keep the original SDL2.dll and libwinpthread-1.dll beside the relinked executable.\n\n"
        "The independent trusted replay worker uses its retained source/object and the same core/libraries:\n"
        "x86_64-w64-mingw32-gcc -municode -static-libgcc -static-libstdc++ trade-replay-worker.obj "
        "libmgba.a libepoxy.a liblua.a -lopengl32 -lglu32 -lgdi32 -lws2_32 -lshlwapi -lole32 -luuid -lm "
        "libwinpthread.dll.a -o emerald-trade-replay.exe\n"
        "Keep libwinpthread-1.dll beside the worker. It opens no player save or window.\n")
    for name in ("build_runtime.sh", "mingw64.cmake", "mingw64-meson.ini", "prepare_frontend.py",
                 "fetch_dependencies.py", "sanitize_source.py", "source-fixtures.json"):
        shutil.copyfile(Path(__file__).with_name(name), output / name)
    provenance = dict(mgba_commit=PIN, core_source_unchanged=True, dll_imports=imports,
                      dependency_sources=archives, compiler=command("x86_64-w64-mingw32-gcc", "--version").decode(),
                      toolchain_packages=command("dpkg-query", "-W", "mingw-w64-common", "mingw-w64-x86-64-dev",
                                                "gcc-mingw-w64-x86-64-posix-runtime").decode(),
                      frontend_source={name: sha(project / "native/windows-runtime" / name)
                                       for name in ("sdl-multiplayer.c", "sdl-multiplayer.h")},
                      replay_worker_source=sha(worker_source),
                      replay_worker_object=sha(build / "trade-replay-worker.obj"),
                      qualification="private native build; runtime smoke and player release acceptance not established by collection")
    (output / "build-provenance.json").write_text(json.dumps(provenance, sort_keys=True, indent=2) + "\n")
    files = {path.name: sha(path) for path in sorted(output.iterdir()) if path.is_file()}
    if len(files) > 32:
        raise ValueError("bundle exceeds launcher manifest file bound")
    manifest = dict(format="emerald-windows-runtime-v1", executable="mgba-sdl.exe", bridge="mgba.lua", files=files)
    (output / "runtime.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    print(json.dumps(dict(directory=str(output), manifest_sha256=sha(output / "runtime.json"), files=len(files))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "dependencies", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    collect(args.source, args.dependencies, args.output)


if __name__ == "__main__":
    main()
