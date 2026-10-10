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
| 2026-10-09 | `native-wip-20261009-5` | tag on `claude/native-pc` (docs) | `claude/native-pc` unchanged (`3ebd6b3a0`, tag `native-wip-20261009-4`); tag `graphics-wip-20261009-3` = `7a200f33d` on `claude/native-graphics` | Milestone D4 in progress: 3DS modelled buildings, walkers whole in front of furniture, sun shadows (none indoors, half at night), shadow map kept between frames; 3DS gap analysis | Incremental bundles and two private Windows test builds (2D unchanged since -4, 3D new) on the PC |
| 2026-10-10 | `native-wip-20261010-1` | tag on `claude/native-pc` (proof scripts, docs) | tag `native-wip-20261010-1` = `edb755a26` on `claude/native-pc`; tag `graphics-wip-20261010-1` = `b02cf0e97` on `claude/native-graphics` | Milestone C progress: native live checkpoints into the ownership store (enroll, save, restart, save, live recovery), door map change, companion restart; bridge keeps up below 60 frames a second (M4) | Incremental bundles and two private Windows test builds (both new; the 3D exe passed a 2-client Wine presence run as shipped) on the PC |
| 2026-10-10 | `native-wip-20261010-2` | tag on `claude/native-pc` (docs, proof timing) | `claude/native-pc` unchanged (`edb755a26`, tag `native-wip-20261010-1`); tag `graphics-wip-20261010-2` = `8920f1f67` on `claude/native-graphics` | Milestone D: the 3DS project's doors, colour grade, cast shadows, weather light, sun dapples, sunlit dust, sun rays and bloom in the 3D view; scripted scenes and fades stay 3D; trees follow the night tint; follower's Poke Ball phase; keyboard zoom | Incremental bundles and a private Windows 3D test build (2D unchanged since -1) on the PC; the 3D exe passed a 2-client Wine presence run as shipped |
| 2026-10-10 | `native-wip-20261010-3` | tag on `claude/native-pc` (docs, evidence) | `claude/native-pc` unchanged (`edb755a26`, tag `native-wip-20261010-1`); tag `graphics-wip-20261010-3` = `3e39f2b15` on `claude/native-graphics` | Milestone D: F7/F8 switch the camera framing and the tree style while playing (kept in `pokeemerald.cfg` with the zoom); the 3DS fog banks and cave gloom; dark caves dark in 3D; 3DS tree crowns as bright as the 3DS shows them; live saves no longer follow the 3D drawing rate (M5) | Incremental bundles and a private Windows 3D test build (2D unchanged since -1) on the PC; the 3D exe passed a 2-client Wine live-checkpoint and recovery run as shipped (native-checkpoint-wine3d-1) |
| 2026-10-10 | `battle3d-wip-20261010-1` | tag on `claude/battle-3d` (docs) | tag `battle3d-wip-20261010-1` = `732fbef43` on `claude/battle-3d-integration` (3D battles merged with graphics `3e39f2b15`); `claude/battle-3d` = `b752d8e48` (the port on graphics `b02cf0e97`); local tag `battle3d-integ-on-8920f1f67` = `925b47933`; `claude/native-pc` and `claude/native-graphics` unchanged | 3D battles (the Emerald 3DS battle scene on one screen, graphics only, `docs/battle-3d.md`) on the newest 3D overworld; native crash fixes N26-N32 (Mega Evolution, PC storage, Fly map, Poké Ball, Trainer Card), candidates for `claude/native-pc` | Bundles, a private Windows test build (3D exe with 3D battles) and a separate, clearly labelled debug-menu test exe on the PC; the 3D exe passed a Wine battle run as shipped |

## GBA ROM identity guard

While native-port changes are `PORTABLE`-only, the GBA ROM must stay identical to
the baseline: `pokedev.gba` sha256
`f214735b64e113fd10730eacca5764d757f2c93a3685230aa905af7a7cdd3387`. Last confirmed
on 2026-10-10 for engine `edb755a26` (`claude/native-pc`) and `8920f1f67`
(`claude/native-graphics`), and for `b752d8e48` (`claude/battle-3d`) and `732fbef43`
(`claude/battle-3d-integration`, which contains `3e39f2b15`); re-check before every
native checkpoint.

## Rollback

* To the emulator game: restore `emulator-baseline-20261009` (see
  `docs/native-migration/baseline.md`). Codex's packaged Windows runtime and release
  candidates in the Codex LocalCache `PokemonPrivate\artifacts` folder are untouched.
* Native work: each `native-wip-*` tag is a rollback point on `claude/native-pc`;
  `graphics-wip-*` tags are rollback points on the engine's `claude/native-graphics`
  (the 3D renderer work, kept off the stable native branch until it reaches parity).
