# Emulator baseline preserved before the native PC migration

Date: 2026-10-09. This records the working emulator-based game exactly as it stood
when the native PC migration began. It stays available as the fallback until the
native build passes equivalent gameplay tests (directive section 3, Milestone G).
Nothing here was deleted or rewritten to start the migration.

## What the baseline is

A GBA ROM built from our pokeemerald-expansion fork, run by a customized mGBA SDL
runtime, connected through the Lua bridge (`bridge/mgba.lua`) to the Python
companion, which talks to the Python host (TLS JSON, protocol 2, SQLite stores).
The ROM and the companion exchange data through EWRAM mailboxes (presence `EMP1`,
save, battle, menu, reset, world `EMW1`) located from the ELF-derived manifest.

## Exact revisions

| Component | Location | Branch | Commit | Tag |
| --- | --- | --- | --- | --- |
| App: companion, host, Lua bridge, runtime sources, tests, docs | cloud `/home/claude/pokemon` | `claude/continuation` | `7240c81` | `emulator-baseline-20261009` |
| Engine: pokeemerald-expansion fork | cloud `/home/claude/engine` | `claude/engine-continuation` | `761c9c27f` | `emulator-baseline-20261009` |
| Engine upstream base | rh-hideout/pokeemerald-expansion | `1.17.1 Release` | `bb1093a7c` | |
| mGBA runtime base | mgba-emu/mgba 0.10.5 | | `26b7884bc` | |
| PC working copy | `C:\Users\kashh\OneDrive\Documents\ChatGPT\Pokemon` | `codex/multiplayer-delivery` | `31e5bf9` plus Codex's uncommitted edits | left untouched |

Codex's uncommitted PC edits are captured in the cloud app repo as commit `3189faf`
("Checkpoint: Codex's final uncommitted work"); the engine equivalent is `62f0bae0f`.
History after those checkpoints: app `7056dd2..7240c81`, engine `5618a4aa9..761c9c27f`.

Migration branches `claude/native-pc` were created in both repositories at the
baseline commits. All native work happens there; `claude/continuation` and
`claude/engine-continuation` are not modified by the migration.

## Baseline build (private, never in Git)

Built with `make -j3 BUILD_NAME=dev` using arm-none-eabi-gcc 13.2.1 (Debian
13.2.rel1-2).

| File | SHA-256 |
| --- | --- |
| `pokedev.gba` | `f214735b64e113fd10730eacca5764d757f2c93a3685230aa905af7a7cdd3387` |
| `pokedev.elf` | `9267802b34633ca0c8ed25baa53da454694d8b26f9ef9935496f789e32106e1b` |
| `manifest.json` | `d6f91e98d46b0e1b63d9e223ba0c27fce1b96b85a4368259291004fc38bc2701` |
| `bridge/mgba.lua` | `e0ea655e9a966d25d5e967629dab3d8924c9e5ec5c1ae3476e01d493b2bb6915` |

## Private checkpoint on the owner's PC

`%LOCALAPPDATA%\PokemonPrivate\claude-checkpoints\emulator-baseline-20261009\`

- `app-full.bundle`: complete app history with `claude/continuation`,
  `claude/native-pc`, `claude/codex-final-wip`, `codex/multiplayer-delivery` and
  both checkpoint tags. Clones with no prerequisites.
- `engine-from-rhh-1.17.1.bundle`: engine commits on top of the public RHH 1.17.1
  release `bb1093a7c` (branches `claude/engine-continuation`, `claude/native-pc`,
  tag `emulator-baseline-20261009`).
- `engine-patches-from-rhh-1.17.1.zip`: the same 54 commits as `git am` patches.
- `rom-gba.zip` (`pokedev.gba`, `manifest.json`) and `rom-elf.zip` (`pokedev.elf`).
- `README.txt`: restore steps.

The earlier checkpoint `claude-checkpoints\2026-10-09-before-reuse-research\` is
kept as is.

## Codex's Windows artifacts (left untouched)

In `%LOCALAPPDATA%\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\PokemonPrivate\artifacts\`:
`windows-runtime`, `windows-release-candidate-20261009-1` to `-4`,
`gen6-player-build-20261009-1`, `gen6-defaults-20261009-1`,
`release-bps-visual-20261009-1`, `windows-trade-replay-native-20261009-1` and the
proof folders. The customized runtime there predates two baseline source changes
(Lua bridge presence/world frame alternation; the trade replay worker accepting the
Lucky Trade bit), so the emulator runtime must be rebuilt before the Oct 9 features
are exercised on Windows.

## Preservation checklist (directive section 3)

1. Current project identified: the table above.
2. Exact commit and branch recorded: the table above.
3. Known-good checkpoint: tags in both repos plus the private PC folder.
4. ROM build: `rom-gba.zip`, `rom-elf.zip`, hashes above.
5. Customized mGBA: sources in `native/windows-runtime/` (in the bundle); Codex's
   built runtime untouched in the LocalCache artifacts.
6. Lua bridge: `bridge/mgba.lua`, unchanged on the migration branch.
7. Python companion and host: `src/emerald_multiplayer/` (131 tracked files) and
   `tests/` (133 tracked files), unchanged except for additive native-bridge work.
8. Save data and formats: private saves untouched. The GBA save layout is pinned in
   `src/multiplayer_save.c` and `src/multiplayer_trade_effects.c`
   (SaveBlock1 15568 bytes, SaveBlock2 3884, SaveBlock3 600, daycare at 0x3030,
   flags at 0x1270, party at 0x238). The host and companion parse these offsets, so
   the native build must produce byte-identical save blocks.
9. Game assets: engine `graphics/`, `sound/`, `data/` at the tagged commit.
10. Implemented gameplay features: classified in `feature-status.md`.

## Restore

App: `git clone app-full.bundle pokemon` then `git checkout claude/continuation`.

Engine: clone rh-hideout/pokeemerald-expansion, `git checkout bb1093a7c`, then
`git fetch <path>\engine-from-rhh-1.17.1.bundle "refs/heads/*:refs/heads/*" "refs/tags/*:refs/tags/*"`
and `git checkout claude/engine-continuation`. Without the bundle, `git am` the
patches from the zip onto `bb1093a7c`.
