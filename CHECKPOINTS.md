# Checkpoints and rollback points

Private copies live in `%LOCALAPPDATA%\PokemonPrivate\claude-checkpoints\` on the
owner's PC (never in Git, never public). Each folder has a README with restore steps.

| Date | Name | App repo | Engine repo | What it is | Verified |
| --- | --- | --- | --- | --- | --- |
| 2026-10-09 | `checkpoint-before-reuse-research-20261009` | tag, `ba59c93` | tag, `761c9c27f` | Before the source-reuse research | Bundles restored and checked |
| 2026-10-09 | `emulator-baseline-20261009` | tag, `7240c81` (`claude/continuation`) | tag, `761c9c27f` (`claude/engine-continuation`) | **Emulator fallback**: ROM + mGBA + Lua bridge + Python companion/host, before the native migration | PC copy hashes match (`pokedev.gba` sha256 `f214735b…3387`) |
| 2026-10-09 | `native-wip-20261009-1` | tag on `claude/native-pc` (docs only) | tag `822ea59f9` on `claude/native-pc` | First native WIP: builds and launches natively on Linux | Incremental bundles on the PC |
| 2026-10-09 | `native-wip-20261009-2` | tag on `claude/native-pc` (docs) | tag `bdfe622da` on `claude/native-pc` | Native overworld, saves, battles, soft reset on Linux; Windows .exe runs the same checks under Wine | Incremental bundles and a private Windows test build on the PC |
| 2026-10-09 | `native-wip-20261009-3` | tag on `claude/native-pc` (docs) | tag `native-wip-20261009-3` = `5b2bcb7ce` on `claude/native-pc`; tag `graphics-wip-20261009-1` = `851f7e75a` on `claude/native-graphics` | Pokémon Center crash fixed (N24); Diorama 3D overworld integrated on the graphics branch (renders on Linux and on Windows under Wine) | Incremental bundles and two private Windows test builds (2D and 3D) on the PC |
| 2026-10-09 | `native-wip-20261009-4` | tag on `claude/native-pc` (docs) | tag `native-wip-20261009-4` = `3ebd6b3a0` on `claude/native-pc`; tag `graphics-wip-20261009-2` = `ac2ab84ba` on `claude/native-graphics` | Clear-save screen crash fixed (N25) and runaway HBlank DMA guard; battle from the 3D view verified | Incremental bundles and two private Windows test builds (2D and 3D) on the PC |

## GBA ROM identity guard

While native-port changes are `PORTABLE`-only, the GBA ROM must stay identical to
the baseline: `pokedev.gba` sha256
`f214735b64e113fd10730eacca5764d757f2c93a3685230aa905af7a7cdd3387`. Last confirmed
on 2026-10-09 for engine `3ebd6b3a0` (`claude/native-pc`) and `ac2ab84ba`
(`claude/native-graphics`); re-check before every native checkpoint.

## Rollback

* To the emulator game: restore `emulator-baseline-20261009` (see
  `docs/native-migration/baseline.md`). Codex's packaged Windows runtime and release
  candidates in the Codex LocalCache `PokemonPrivate\artifacts` folder are untouched.
* Native work: each `native-wip-*` tag is a rollback point on `claude/native-pc`;
  `graphics-wip-*` tags are rollback points on the engine's `claude/native-graphics`
  (the 3D renderer work, kept off the stable native branch until it reaches parity).
