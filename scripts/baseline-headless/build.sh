#!/usr/bin/env bash
# Build a small frontend against an existing, pinned official mGBA checkout.
set -eu
mgba_root=${1:?Pass the mGBA 0.10.5 source checkout directory}
proof_root=${2:?Pass a dedicated directory whose path contains /baseline-proof/}
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
expected_commit=26b7884bc25a5933960f3cdcd98bac1ae14d42e2
actual_commit=$(git -C "$mgba_root" rev-parse HEAD)
if [ "$actual_commit" != "$expected_commit" ]; then
    printf '%s\n' "Expected pinned mGBA 0.10.5 ($expected_commit), got $actual_commit" >&2
    exit 1
fi
case "$proof_root/" in
    */baseline-proof/*) ;;
    *) printf '%s\n' 'Use a dedicated baseline-proof directory.' >&2; exit 1 ;;
esac
mkdir -p -- "$proof_root"
cmake -S "$mgba_root" -B "$mgba_root/build" \
    -DBUILD_QT=OFF -DBUILD_SDL=OFF -DBUILD_GL=OFF \
    -DBUILD_GLES2=OFF -DBUILD_GLES3=OFF -DBUILD_SHARED=ON \
    -DUSE_FFMPEG=OFF -DUSE_LIBZIP=OFF -DUSE_LZMA=OFF -DUSE_LUA=OFF \
    -DENABLE_SCRIPTING=OFF -DUSE_SQLITE3=OFF -DUSE_EDITLINE=OFF \
    -DUSE_ELF=OFF -DM_CORE_GB=OFF
cmake --build "$mgba_root/build" -j 4
cc -std=c11 -D_GNU_SOURCE \
    -I"$mgba_root/include" -I"$mgba_root/build/include" \
    "$source_dir/harness.c" -L"$mgba_root/build" \
    -Wl,-rpath,"$mgba_root/build" -lmgba -o "$proof_root/harness"
