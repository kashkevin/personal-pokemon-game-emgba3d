# Unmodified Emerald baseline build

Recorded October 7, 2026. Phase 1 is in progress. Two clean builds have reproduced exactly; the unfiltered upstream automated suite completed with exit code 0 and its declared exceptions recorded below. Gameplay and independent save/reload checks remain pending. **Do not create `BASELINE_BUILD` yet.**

## Source and environment

- Engine: RHH `expansion/1.17.1`, commit `bb1093a7c72d3961d9a37d8e02ad2abc2c866682`.
- Source: `/home/kevin/src/pokemon/engine` in Ubuntu WSL2, branch `codex/baseline`; upstream history retained. Tracked source/configuration remained unchanged after both builds.
- OS: Ubuntu 24.04.4 LTS; kernel `6.6.87.2-microsoft-standard-WSL2`, x86-64.
- Arm GCC: `13.2.1 20231009`, package `15:13.2.rel1-2`; binutils `2.42-1ubuntu1+23`.
- newlib and newlib development files: `4.4.0.20231231-2`; libpng development files: `1.6.43-5ubuntu0.6`.
- Host GCC: `13.3.0-6ubuntu2~24.04.1`; make 4.3; Git `1:2.43.0-1ubuntu7.3`; Python `3.12.3-0ubuntu2.1`; build-essential `12.10ubuntu1`.
- Desktop mGBA: `0.10.5.0`, Windows x86, installed at `C:\Program Files\mGBA\mGBA.exe`. Binary SHA-256: `feb3695aea18a57841a5058729fb1a679ad12a5a4e00f0de00ff1c0ba1a6798c`.

The upstream default generation profile is retained for this baseline. The now-requested Gen 6 profile, roster restrictions, networking, and custom content have not been applied. The Gen 6 specification update does not alter or discard this unmodified build. See [the dependency ledger](dependency-ledger.md) for provenance and distribution review status.

## Reproducibility

The first build ran from a clean clone. The second used the upstream `make clean` target, followed by the same normal build. Artifacts from the first build were archived before cleaning. These commands ran in the pinned engine directory:

```bash
make -j8 -O all
# Archive .gba, .elf, .map, and build log before cleaning.
make clean
make -j8 -O all
```

Both builds returned exit code 0. All three SHA-256 hashes matched:

| Artifact | SHA-256 |
| --- | --- |
| `pokeemerald.gba` | `b89a23a7758519d0768b87ad947a5cb3d8587f1f7bd547f983171b8520bae12a` |
| `pokeemerald.elf` | `c9c57008bd99ded951402c7f9622328f15af76cbc068eec633439077785ecf72` |
| `pokeemerald.map` | `921fdcd4ee662f0f1473f2dbd975bf314ab1122586563b20d7e8c19788e78c7a` |

## Measured memory

Normal build linker output, identical in both builds:

| Region | Linked usage | Region size | Usage |
| --- | --- | --- | --- |
| EWRAM | 226,416 bytes | 262,144 bytes | 86.37% |
| IWRAM | 28,376 bytes | 32,768 bytes | 86.60% |
| ROM | 26,748,420 bytes | 33,554,432 bytes | 79.72% |

The `.gba` is padded to 33,554,432 bytes. EWRAM usage includes the reserved 115,968-byte `gHeap`; this is not a measurement of runtime heap availability or peak allocation. IWRAM still needs stack headroom. No remote-player/follower memory budget has been tested yet.

## Automated checks

The full upstream suite ran with no custom filters or exclusions:

```bash
make -j8 -Otarget check TESTS= \
  ROMTEST=tools/mgba/mgba-rom-test \
  ROMTESTHYDRA=tools/mgba-rom-test-hydra/mgba-rom-test-hydra
```

Result: **Exit code 0**. The runner reported these categories:

| Upstream category | Count |
| --- | --- |
| Passed | 5,414 |
| Known failing | 18 |
| To do | 421 |
| Expected failing | 9 |
| Total | 5,862 |

The expected-failure category includes runner self-tests that deliberately fail or crash. These are the upstream runner's declared categories, not a project exclusion list. This result does not mean all 5,862 tests passed. The complete report and the named declared exceptions are preserved with the private artifacts. Tracked source remained unchanged, and the normal ROM hash was verified again after the checks.

The check target uses separate test ELF files. Its test instrumentation is not the normal gameplay baseline.

## Private artifacts and playtest

Artifacts and logs are outside OneDrive and Git, at `C:\Users\kashh\AppData\Local\PokemonPrivate\artifacts\baseline`. `build-1` and `build-2` contain the archived normal outputs; `checks` contains the test log.

`playtest\client-a` and `playtest\client-b` contain identical baseline ROMs and `Open-Client-a.cmd` / `Open-Client-b.cmd`. These are local test shortcuts, not the proposed downloadable multiplayer launcher. Each passes an explicit, different `savegamePath` and `savestatePath` to mGBA. No player saves have been overwritten.

Complete [the gameplay and save checklist](baseline-playtest.md) in the actual GUI before accepting the milestone. A successful compile does not establish gameplay, save isolation, or multiplayer readiness.
