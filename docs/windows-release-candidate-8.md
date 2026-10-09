# Private Windows release candidate 8

October 9, 2026. A new **import-enabled** ZIP was built in a fresh private
directory using the existing installed Windows/WSL toolchains and cached pinned
dependencies. This is a reviewable installation candidate, not clean-PC,
friends' network or complete gameplay acceptance. Package 7 and previous runtime
artifacts remain unchanged; nothing was distributed or migrated.

**Superseded source snapshot:** a subsequent actual trade attempt exposed the
native damage-category enum mismatch in `trade_effect_choice.py` and
`trade_effect_menu.py`. Candidate 8 predates that correction and remains a
preserved diagnostic package. Its installation/startup results below remain
valid for its exact pins; do not use them to claim working native move review.
The corrected source is now frozen in [candidate 9](windows-release-candidate-9.md)
rather than replacing these files or this ZIP.

## Download and exact identity

Physical Windows archive path (the Codex sandbox's LocalCache path):

```text
C:\Users\kashh\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\PokemonPrivate\artifacts\windows-release-candidate-20261009-1\package-1\EmeraldTogether.zip
```

The logical private-artifact alias is
`%LOCALAPPDATA%/PokemonPrivate/artifacts/windows-release-candidate-20261009-1`.
The ZIP is **77,657,859 bytes** and contains the `EmeraldTogether` directory,
its executable, `_internal` resources and readable guides. Extract the whole
directory; keep the executable beside `_internal`.

| Component | SHA-256 |
| --- | --- |
| `EmeraldTogether.zip` | `bd57a7d98d58321ca6689e4480de51487a7354731b3d6a9fc4a07b1d53de03f6` |
| `EmeraldTogether.exe` | `d945e137fb43a27663540e812df747ca68a5df236dfaf45e707d3982e448d868` |
| Game target (not in ZIP) | `f99bfa4e19ccb5ba998b54d2151986665c15bed3b2d28dab10340d59be3a1d65` |
| Game manifest | `f97dffa70c4edf93de4f90202f8fe08a5a3a499cb2113574c73881321b4bb7e1` |
| Installation BPS | `2bac367a4701087ec8c021dd8d5de1c747b6cdde08e228eb010b36717217fe22` |
| Uncompressed original source (not in ZIP) | `a9dec84dfe7f62ab2220bafaef7479da0929d066ece16a6885f6226db19085af` |
| Runtime manifest | `698dff484ded620615d4002c0758bf14379cdb01cf25750d69499dc1cc6a5a84` |
| `mgba-sdl.exe` | `adc56b8ca9a4337fb4fb9bd953d691884aecc314e61ac2ee8ada82ee890639e4` |
| `emerald-trade-replay.exe` | `43de0d1668a41c7e6c5aa6de2b43ba0228d3d719c5d528a62c3d2df9a0e6a14b` |

The package's own `_internal/package-provenance.json` records all 119 frozen
application module hashes, dependencies, guide hashes, exact game/runtime pins,
`import_enabled: true`, and `development_preview: false`. Import requires the
owner's matching GBA or bounded single-GBA ZIP. The package contains the patch,
not a commercial source/target ROM, player save, invitation or world database.
The recursive audit is a bounded format/name detector, not a universal binary
content classifier or a determination of distribution rights.

## Build and collection

The native core is a new detached worktree at pinned mGBA
`26b7884bc25a5933960f3cdcd98bac1ae14d42e2`, under
`/home/kevin/src/pokemon/windows-release-candidate-20261009-1/mgba`.
`prepare_frontend.py`, `build_runtime.sh` and `collect_bundle.py` ran from frozen
source. `EMERALD_REUSE_BUILT_DEPS=1` used the existing pinned Lua 5.4.9, SDL
2.32.10 and libepoxy 1.5.10 cache; no fetch/install step ran. Four original
dependency libraries were hashed before/after and unchanged. The recipe uses
low priority, two build workers, LTO off, static core, Lua on, Qt off and
`BUILD_TEST`, `BUILD_CINEMA`, `BUILD_PERF` off. The separate replay executable
links the same libmGBA and receives no live player save/process.

The build completed with inherited compiler warnings retained in
`runtime-build.log`; it was not warning-free. The first collection preserved in
`runtime/` correctly refused 33 top-level files. The collector was repaired to
retain its README inside the existing `relink-inputs.tar.gz`, preserving source
and notices within the unchanged 32-file runtime bound. The complete second
collection is `runtime-2/`; the old failed output remains. Revised collector
SHA-256: `3c0d3a6ab2b307d44346e878b652d49fe0479d72c7e7c2ca2e6ef984a084119f`.

Both programs were independently relinked into a separate directory using the
retained inputs and documented commands. All seven `frontend-objects.a` members
matched the individually retained frontend objects. The build README and worker
C bytes matched their frozen source inside the relink archive. Executable/DLL
headers are AMD64, and imported DLLs passed the collector's existing allowlist.
Source sanitizer metadata, notices and covered source archives accompany the
runtime; none of these checks grants gameplay acceptance.

The launcher used existing Python 3.14.4 and PyInstaller 6.22.3. Its normal
release preflight verified the full 25-source production reset capability,
isolated replay descriptor/worker, and exact BPS reconstruction before output
creation. It used the existing pinned patch rather than an import-disabled
development override. Exact arguments and inputs are preserved in
`build-arguments.json`, `source-inputs.json`, `frozen-project/` and
`frozen-project-collection-2/`. Package work/output are separate from source.

## Completed checks and limits

- Runtime verification and recursive content audit passed. Both newly built
  and separately relinked executables passed bounded no-ROM CLI checks (SDL
  version/help, worker version); no game launched in those checks.
- Recursive package directory and ZIP audits passed: 6,477 and 6,574 inspected
  files/archive members respectively. There are 1,087 actual package files.
- The frozen production `GameImporter` read the original supplied ZIP and the
  **packaged** BPS into a fresh `import-check` private directory, installed the
  exact target, then passed idempotent retry and complete game/manifest/runtime
  verification. Original ZIP bytes remained unchanged. This used the same
  importer/resources as the package, not the packaged GUI button.
- The actual packaged executable started with a fresh isolated `LOCALAPPDATA`.
  Its exact image path/hash, PID and creation time were checked; its native
  window title was `Emerald Together`. After readiness it received normal
  `CloseMainWindow`, exited zero and left no owned child. No forced termination,
  game launch, host/world creation or migration occurred. Standard error was
  empty. This is entry/window-lifecycle evidence, not visual or button QA.
- All 1,087 package files were rehashed unchanged after startup/import checks;
  all 119 frozen application module hashes still matched the working source at
  final verification. Original accepted artifacts were never build targets.

Retained receipts under the candidate directory:

| Evidence file | SHA-256 |
| --- | --- |
| `runtime-checks.json` | `6c71f4c7e45b9f47e9cae09a5fd0ceccc6a94143c93f787678ecc8eb05bde248` |
| `relink-checks.json` | `6c86a09fde868039d0a807bcb13f56969660e55fe46b6f0d59d734b463fda310` |
| `import-checks.json` | `ddc2ab360d1b4d743d0432811a24e542a0b7ee3e7cb8b8a682a63a4a9d7d63a7` |
| `startup-checks.json` | `05292e3e14750285cf67748a7740da287949547f2b51ac575f0d25f891023cd8` |
| `package-1/package-audit.json` | `4583856f0a6550e1fee39247a8a811496ada9289615499d71457c15a46942c46` |
| `package-1/package-hashes.json` | `80dc341fe0b0be412e457b2cb440e97c8a3d4b50f085f95785774835af520aab` |
| `package-1/resources/package-provenance.json` | `c974434fa317ba522e37a471a84686f5cb050517aece9cd0290e10b91c60cd62` |

## Remaining acceptance and known restriction

The parallel actual public trade attempt found a genuine original Treecko with
Leafage (move 633), outside the existing Gen6 effect adapter. That record was
refused; no move, Pokémon or gameplay rule was rewritten to obtain a pass.
Unsupported later-generation moves remain a practical trade restriction in
this candidate. Broader Gen6 data/learnset compatibility is not established by
packaging, and safe refusal is not completion of the full trading requirement.

The [isolated native replay proof](native-trade-replay-worker.md) and
[remote running proof](remote-running-animation.md) retain their own exact
binaries/scopes. They are not silently upgraded to qualification of this new
SDL/worker/package build. Complete packaged trade/evolution/battle/reset/recovery
flows, GUI import, physical keyboard/gamepad/audio, clean-machine setup, four
separate PCs and Wi-Fi/Internet acceptance remain separate checks. No firewall,
router, world or saved character was changed by this package work.
