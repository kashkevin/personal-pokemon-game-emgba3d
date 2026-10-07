#!/bin/sh
set -eu
# Run in Ubuntu WSL. This separate build leaves the baseline frontend intact.
mgba_src=${1:?Pinned mGBA source path required}
output_dir=${2:?Private multiplayer-proof directory required}
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test "$(git -C "$mgba_src" rev-parse HEAD)" = 26b7884bc25a5933960f3cdcd98bac1ae14d42e2
git -C "$mgba_src" diff --quiet
case "$output_dir/" in */multiplayer-proof/*) ;; *) exit 2 ;; esac
mkdir -p "$output_dir"
cmake -S "$mgba_src" -B "$mgba_src/build-scripting" \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_QT=OFF -DBUILD_SDL=OFF \
  -DBUILD_GL=OFF -DBUILD_GLES2=OFF -DBUILD_GLES3=OFF \
  -DBUILD_SHARED=ON -DBUILD_STATIC=OFF -DBUILD_TEST=OFF -DBUILD_SUITE=OFF \
  -DBUILD_PERF=OFF -DBUILD_ROM_TEST=OFF -DENABLE_SCRIPTING=ON -DUSE_LUA=ON \
  -DUSE_FFMPEG=OFF -DUSE_LIBZIP=OFF -DUSE_SQLITE3=OFF -DUSE_LZMA=OFF \
  -DUSE_ELF=OFF -DUSE_DEBUGGERS=OFF -DUSE_DISCORD_RPC=OFF
cmake --build "$mgba_src/build-scripting" -j8
cc -std=gnu11 -Wall -Wextra -Werror \
  -I"$mgba_src/include" -I"$mgba_src/build-scripting/include" \
  "$script_dir/harness.c" -L"$mgba_src/build-scripting" \
  -Wl,-rpath,"$mgba_src/build-scripting" -lmgba -o "$output_dir/harness"
