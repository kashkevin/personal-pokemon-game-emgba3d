#!/usr/bin/env bash
# SessionStart hook: prepare the build/test environment in cloud sessions only.
# Synchronous on purpose: the session starts only when the toolchain is usable.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
exec "$CLAUDE_PROJECT_DIR/scripts/cloud/setup-env.sh"
