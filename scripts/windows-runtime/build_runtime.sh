#!/usr/bin/env bash
# Build only the isolated player frontend. No source ROM is included or fetched.
set -euo pipefail
if [[ $# -ne 2 ]]; then
    echo 'Usage: build_runtime.sh prepared-mGBA-worktree verified-dependency-cache' >&2
    exit 2
fi
runtime_source=$(realpath "$1")
runtime_deps=$(realpath "$2")
runtime_scripts=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
runtime_build="$runtime_source/build-windows"
lua_source="$runtime_deps/lua/lua-5.4.9/src"
sdl_prefix="$runtime_deps/sdl-devel/SDL2-2.32.10/x86_64-w64-mingw32"
epoxy_source="$runtime_deps/epoxy/libepoxy-1.5.10"
epoxy_prefix="$runtime_deps/epoxy-windows"
epoxy_build="$runtime_deps/build-epoxy-windows"
export PKG_CONFIG_LIBDIR="$epoxy_prefix/lib/pkgconfig:$sdl_prefix/lib/pkgconfig"

test "$(git -C "$runtime_source" rev-parse HEAD)" = 26b7884bc25a5933960f3cdcd98bac1ae14d42e2
test -f "$runtime_source/src/platform/sdl/sdl-multiplayer.c"
cmp -s "$runtime_source/src/platform/sdl/sdl-multiplayer.c" "$runtime_scripts/../../native/windows-runtime/sdl-multiplayer.c"
cmp -s "$runtime_source/src/platform/sdl/sdl-multiplayer.h" "$runtime_scripts/../../native/windows-runtime/sdl-multiplayer.h"
test "$(cat "$runtime_deps/lua/.source-sha256")" = 2335b6c582a52654f94612bf10d2f4672805d05329aa6568b1d8cd9e5c6fb8e6
test "$(cat "$runtime_deps/sdl-devel/.source-sha256")" = 83a5d74012311edc3c0d40ea6faecbe57ad692aa033fa5dc273cc937e3938ff2
test "$(cat "$runtime_deps/epoxy/.source-sha256")" = a7ced37f4102b745ac86d6a70a9da399cc139ff168ba6b8002b4d8d43c900c15

case "${EMERALD_REUSE_BUILT_DEPS:-0}" in
    0|1) ;;
    *) echo 'EMERALD_REUSE_BUILT_DEPS must be 0 or 1' >&2; exit 2 ;;
esac

# Upstream's Windows standalone frontend requires its normal WGL dispatcher.
# Keep that dependency rather than weakening the upstream platform guard.
if [[ "${EMERALD_REUSE_BUILT_DEPS:-0}" == 1 ]]; then
    # Explicit offline rebuild: never mutate or reinstall the qualified cache.
    # Collection still verifies the original dependency archive hashes.
    for library in "$lua_source/liblua.a" "$epoxy_prefix/lib/libepoxy.a" \
        "$sdl_prefix/lib/libSDL2main.a" "$sdl_prefix/lib/libSDL2.dll.a"; do
        test -s "$library"
    done
    test -f "$lua_source/lua.h"
    test -f "$epoxy_prefix/include/epoxy/gl.h"
    test -f "$epoxy_prefix/lib/pkgconfig/epoxy.pc"
    test -f "$sdl_prefix/lib/cmake/SDL2/sdl2-config.cmake"
else
    if [[ ! -f "$epoxy_build/build.ninja" ]]; then
        meson setup "$epoxy_build" "$epoxy_source" \
            --cross-file "$runtime_scripts/mingw64-meson.ini" \
            --prefix "$epoxy_prefix" --libdir lib --buildtype release \
            -Ddefault_library=static -Dtests=false -Ddocs=false -Dglx=no -Degl=no -Dx11=false
    fi
    nice -n 15 meson compile -C "$epoxy_build" -j2
    meson install -C "$epoxy_build" --no-rebuild

    nice -n 15 make -C "$lua_source" -j2 a CC=x86_64-w64-mingw32-gcc \
        AR='x86_64-w64-mingw32-ar rcu' RANLIB=x86_64-w64-mingw32-ranlib
fi

cmake -S "$runtime_source" -B "$runtime_build" \
    -DCMAKE_TOOLCHAIN_FILE="$runtime_scripts/mingw64.cmake" \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_LTO=OFF -DBUILD_QT=OFF -DBUILD_SDL=ON \
    -DBUILD_GL=ON -DBUILD_GLES2=OFF -DBUILD_GLES3=OFF -DUSE_EPOXY=ON \
    -DBUILD_STATIC=ON -DBUILD_SHARED=OFF -DENABLE_SCRIPTING=ON -DUSE_LUA=ON \
    -DLUA_INCLUDE_DIR="$lua_source" -DLUA_LIBRARY="$lua_source/liblua.a" \
    -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON -DSDL2_DIR="$sdl_prefix/lib/cmake/SDL2" \
    -DM_CORE_GBA=ON -DM_CORE_GB=OFF -DUSE_DEBUGGERS=OFF -DUSE_GDB_STUB=OFF \
    -DUSE_FFMPEG=OFF -DUSE_ZLIB=OFF -DUSE_MINIZIP=OFF -DUSE_PNG=OFF \
    -DUSE_LIBZIP=OFF -DUSE_SQLITE3=OFF -DUSE_ELF=OFF -DUSE_LZMA=OFF \
    -DBUILD_TEST=OFF -DBUILD_CINEMA=OFF -DBUILD_PERF=OFF \
    -DUSE_DISCORD_RPC=OFF -DCMAKE_EXE_LINKER_FLAGS='-static-libgcc -static-libstdc++'
nice -n 15 cmake --build "$runtime_build" --parallel 2
# A separate console helper uses only fresh libmGBA cores. It never shares the
# player's SDL process, save file or scripting surface. Keep its exact compiled
# source/object for reproduction and LGPL relinking alongside the core archive.
cp "$runtime_scripts/../../native/windows-runtime/trade-replay-worker.c" "$runtime_build/trade-replay-worker.c"
nice -n 15 x86_64-w64-mingw32-gcc -std=c11 -O2 -Wall -Wextra \
    -Werror=implicit-function-declaration -D_GNU_SOURCE -D_WIN32_WINNT=0x0600 \
    -DBUILD_STATIC -I"$runtime_build/include" -I"$runtime_source/include" \
    -c "$runtime_build/trade-replay-worker.c" -o "$runtime_build/trade-replay-worker.obj"
nice -n 15 x86_64-w64-mingw32-gcc -municode -static-libgcc -static-libstdc++ \
    "$runtime_build/trade-replay-worker.obj" "$runtime_build/libmgba.a" \
    "$epoxy_prefix/lib/libepoxy.a" "$lua_source/liblua.a" \
    -lopengl32 -lglu32 -lgdi32 -lws2_32 -lshlwapi -lole32 -luuid -lm -lpthread \
    -o "$runtime_build/emerald-trade-replay.exe"
printf 'Runtime built at %s\n' "$runtime_build"
