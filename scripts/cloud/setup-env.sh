#!/usr/bin/env bash
# Idempotent build/test environment for the Emerald Together repositories on a fresh
# Ubuntu 24.04 machine (Claude cloud sessions, CI-like containers).
#
# Installs only what is missing, so a second run costs a few `dpkg`/`test` calls and
# no network. Safe to paste into the cloud environment's "Setup script" box (the
# result is then cached in the environment image) or to run from the SessionStart hook.
#
#   scripts/cloud/setup-env.sh              # toolchain, Python 3.12 venv, SDL2 for MinGW
#   EMERALD_WITH_WINE=1 scripts/cloud/setup-env.sh   # also Wine (in-game proofs of the .exe only)
#
# Variables (all optional):
#   EMERALD_VENV        venv path                      (default $HOME/venv)
#   EMERALD_SDL2_MINGW  SDL2 MinGW tree                (default $HOME/sdl2-mingw)
#   EMERALD_ENGINE_DIR  engine clone, only reported    (default: beside this checkout)
#
# After it runs (and in sessions, through CLAUDE_ENV_FILE) these are set:
#   PATH starts with the venv's bin, EMERALD_SDL_DIR=<tree>/i686-w64-mingw32
# so that   make -f Makefile_pc SDL_DIR="$EMERALD_SDL_DIR" DIORAMA=1   builds the Windows exe.
#
# It never clones the engine: the private engine repository is attached to a session
# (add_repo) or cloned with the owner's credentials, which a script must not hold.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${EMERALD_VENV:-$HOME/venv}"
SDL_ROOT="${EMERALD_SDL2_MINGW:-$HOME/sdl2-mingw}"
ENGINE_DIR="${EMERALD_ENGINE_DIR:-$(dirname "$APP_DIR")/personal-pokemon-game-emgba3d-engine}"

# Pinned: the SDL2 development package the Windows exe is linked against.
SDL_VERSION=2.30.7
SDL_URL="https://github.com/libsdl-org/SDL/releases/download/release-${SDL_VERSION}/SDL2-devel-${SDL_VERSION}-mingw.tar.gz"
SDL_SHA256=147c3dc03c9be6b23e625fd877421098e93487f1f55e0e1d4e3ce571e79b91c4

log() { printf '[emerald-setup] %s\n' "$*" >&2; }
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"

# ---- system packages ------------------------------------------------------------
PACKAGES=(
  build-essential make git curl ca-certificates xz-utils pkg-config
  gcc-arm-none-eabi binutils-arm-none-eabi libnewlib-arm-none-eabi   # GBA build
  gcc-multilib g++-multilib libsdl2-dev libsdl2-dev:i386 libgl1-mesa-dev:i386   # native Linux i386
  mingw-w64                                                          # Windows exe
  libpng-dev python3-venv python3-dev python3-tk xvfb xdotool imagemagick   # tools, tests, proofs
)
[ "${EMERALD_WITH_WINE:-0}" = 1 ] && PACKAGES+=(wine wine32:i386 wine64)

missing=()
for pkg in "${PACKAGES[@]}"; do
  dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q '^install ok installed' || missing+=("$pkg")
done
if [ "${#missing[@]}" -gt 0 ]; then
  log "installing ${#missing[@]} missing package(s): ${missing[*]}"
  export DEBIAN_FRONTEND=noninteractive
  $SUDO dpkg --add-architecture i386
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq --no-install-recommends "${missing[@]}"
else
  log "system packages present"
fi

# ---- Python 3.12 venv (requirements-dev.txt pins wheels that need 3.12) -----------
if ! command -v uv >/dev/null 2>&1; then
  log "installing uv"
  python3 -m pip install -q --break-system-packages uv 2>/dev/null || python3 -m pip install -q uv
  export PATH="$HOME/.local/bin:$PATH"
fi
want="$(sha256sum "$APP_DIR/requirements-dev.txt" | cut -d' ' -f1)"
if [ ! -x "$VENV/bin/python" ] || [ "$(cat "$VENV/.requirements-sha256" 2>/dev/null)" != "$want" ]; then
  log "creating Python 3.12 venv at $VENV"
  rm -rf "$VENV"
  uv venv --python 3.12 "$VENV" >&2
  uv pip install -q --python "$VENV/bin/python" -r "$APP_DIR/requirements-dev.txt"
  echo "$want" > "$VENV/.requirements-sha256"
else
  log "venv up to date"
fi

# ---- SDL2 for MinGW (Windows exe) -------------------------------------------------
if [ ! -f "$SDL_ROOT/i686-w64-mingw32/bin/SDL2.dll" ]; then
  log "fetching SDL2 $SDL_VERSION MinGW package"
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  curl -fsSL -o "$tmp/sdl.tgz" "$SDL_URL"
  echo "$SDL_SHA256  $tmp/sdl.tgz" | sha256sum -c - >&2
  mkdir -p "$tmp/x" && tar -xzf "$tmp/sdl.tgz" -C "$tmp/x"
  rm -rf "$SDL_ROOT" && mv "$tmp/x/SDL2-${SDL_VERSION}" "$SDL_ROOT"
else
  log "SDL2 MinGW tree present"
fi

# ---- environment for the session --------------------------------------------------
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export PATH=\"$VENV/bin:\$HOME/.local/bin:\$PATH\""
    echo "export EMERALD_SDL_DIR=\"$SDL_ROOT/i686-w64-mingw32\""
    echo "export EMERALD_ENGINE_DIR=\"$ENGINE_DIR\""
  } >> "$CLAUDE_ENV_FILE"
fi

[ -d "$ENGINE_DIR/.git" ] || log "engine not cloned at $ENGINE_DIR (attach kashkevin/personal-pokemon-game-emgba3d-engine to the session)"
log "ready: venv=$VENV sdl=$SDL_ROOT/i686-w64-mingw32"
