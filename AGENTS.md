# Project working instructions

Read `docs/master-spec.md` and `docs/development-roadmap.md` before choosing major work. The original briefs and amendments in `docs/project-*.txt` are preserved user requirements. Later direct user instructions take precedence. Keep the accepted ownership milestone and private source saves intact.

Before building any major system from scratch, inspect the pinned engine and its current maintained upstream, official documentation, and compatible community projects. Record what is already provided, what can be reused, what needs adaptation, and what requires custom implementation. Prefer a maintained, compatible implementation when it reduces integration risk. Check exact revision, license and attribution, dependencies, maintenance, known issues, save compatibility, multiplayer conflicts, and measured performance before importing it. Record incorporated sources in `docs/dependency-ledger.md`; research references are not incorporated dependencies. See `docs/customization-and-reuse.md` for the initial audit.

Keep foundational multiplayer first. The current order is safe trading; battles and teams; four actual clients; Local Soft Reset with its necessary encounter/RNG foundation; automatic saving and disconnect handling; Windows Host/Join packaging; Wi-Fi/Internet acceptance and polish. Character customization, player friendship/Lucky Trades, and the personal Shiny Charm/Game Corner reward are accepted additions scheduled around those foundations. Existing Gen 1–6, Gen 6 mechanics, starters, Mega, follower, event, and campaign requirements remain in scope.

Do not remove or rebalance established gameplay rules while adding features. If a genuine compatibility conflict requires a gameplay-design change, explain the concrete conflict and obtain the user's decision before making that change. Routine implementation choices within accepted rules need no extra approval. Keep unapproved probabilities, friendship thresholds, IV floors, prices, and cooldowns explicitly pending.

Preserve small commits, meaningful tests, known-good tags, and private backups. No commercial ROM downloads, player credentials, save files, databases, or private build artifacts belong in Git. Do not infer playable acceptance from compilation, fixtures, or screenshots alone; record actual-core tests and their limits separately.

---

## Current direction (2026-10-09)

The game is being migrated to a native standalone Windows executable with the
enhanced dimensional overworld of ZallaxDev/pokeemerald-3Ds-dualscreen (graphics
only, single screen), using ZallaxDev/pokeemerald-voxel-project's native Diorama
renderer as the base. Directives: `docs/project-update-native-pc-migration-20261009.txt`
and `docs/project-update-dev-toolkit-20261009.txt`. The emulator build is the
fallback until the native build passes equivalent tests (Milestone G).

Main documents (keep them current; merge, never overwrite blindly):

| File | Purpose |
| --- | --- |
| `PROJECT_SPEC.md` | All agreed gameplay requirements and owner decisions |
| `ARCHITECTURE.md` | Engine, renderer, bridge, host, saves, system boundaries |
| `FEATURE_STATUS.md` | Per-feature status with evidence (six fixed labels) |
| `DEVELOPMENT_ROADMAP.md` | The main checklist, in dependency order |
| `TEST_PLAN.md` | How to run every test, what each proves, current results |
| `KNOWN_ISSUES.md` | Confirmed bugs with severity, reproduction, status |
| `CHECKPOINTS.md` | Known-good versions and rollback points |

## Repositories and branches

| Repo | Path (cloud workspace) | Native branch | Emulator fallback branch |
| --- | --- | --- | --- |
| App (host, companion, bridge, launcher, docs, tests) | `/home/claude/pokemon` | `claude/native-pc` | `claude/continuation` |
| Engine (pokeemerald-expansion 1.17.1 fork) | `/home/claude/engine` | `claude/native-pc` | `claude/engine-continuation` |

The owner's PC copy is `C:\Users\kashh\OneDrive\Documents\ChatGPT\Pokemon` (Codex's
state, left untouched). Private checkpoints go to
`%LOCALAPPDATA%\PokemonPrivate\claude-checkpoints\`. Use separate branches (and git
worktrees for long-running experiments: graphics, multiplayer, mechanics,
performance) so the stable native branch is never broken by an experiment. Never
let two agents edit the same files at the same time.

## Build commands (engine)

```sh
make -j2 BUILD_NAME=dev                        # GBA ROM (fallback; also generates assets)
make -f Makefile_pc NATIVE_LINUX=1 -j2         # native Linux i386 binary: pokeemerald-mp
make -f Makefile_pc NATIVE_LINUX=1 SANITIZE=1  # UBSan build for finding GBA-only behaviour
make -f Makefile_pc SDL_DIR=<sdl2-mingw>/i686-w64-mingw32   # Windows pokeemerald-mp.exe
make -f Makefile_pc NATIVE_LINUX=1 check-native check-abi   # native unit + layout tests
```

The GBA ROM must stay byte-identical while changes are PORTABLE-only; compare
`sha256sum pokedev.gba` with `CHECKPOINTS.md` after touching shared headers.

## Test commands (app)

```sh
/home/claude/venv312/bin/python -m pytest      # full suite (project venv has the pinned deps)
```

Details and current results: `TEST_PLAN.md`.

## Native port rules

* Guard PC-only code with `#ifdef PORTABLE`; keep the GBA build unchanged unless a
  gameplay change is intended. Platform code lives in `src/platform/` (see its README
  for provenance and licences).
* Types in save data, companion mailboxes, battle packets and assembler-built data
  must keep the GBA byte layout: mark them `ABI_ALIGN` and keep
  `tools/pc_port/abi_layout.py` passing.
* GBA-tolerated undefined behaviour crashes or misbehaves on x86: NULL reads
  (`NATIVE_NULL_GUARD`), shifts by 32 or more (`ARM_LSL32`/`ARM_LSR32`), division by
  zero (`fault_compat.c` gives the GBA result, but fix the source too). Find them with
  the UBSan build and `PKMN_NULL_TRAP=1`; fix the cause, do not suppress the report.
* Keep rendering separate from authoritative game state: the renderer decides how
  the game looks, never ownership, battle results, inventory, trades, wagers, shared
  events or save progression.

## Working loop for a major change

Inspect existing code and docs first; check for partial implementations; research
compatible existing implementations when useful; make a small plan; checkpoint;
change the smallest practical area; compile; run automated tests; run gameplay tests
where practical; fix verified causes (no stacked speculative fixes); run regression
tests; update the documents above; continue with the next roadmap item. Report
results with the distinctions Researched / Installed / Configured / Compiled /
Launched / Tested / Working / Fully verified.
