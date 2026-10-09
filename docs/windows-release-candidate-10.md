# Private Windows Gen6 defaults candidate 10

October 9, 2026. This preserved package built and passed its bounded installation
and startup checks. **It is blocked for friend release:** subsequent native
source review found the ordinary build still enables the overworld debug menu,
battle debug menu and sprite visualizer through `DISABLED_ON_RELEASE` with
`RELEASE=0`. Those menus require a new native output and ROM-bound release guard.
Candidate 10 is not retroactively changed or described as friends-ready.

This package uses the separately identified [Gen6 defaults profile](gen6-defaults-profile.md).
It does not complete the Gen6 roster, encounters, acquisition, forms or all
mechanics. [Candidate 9](windows-release-candidate-9.md), its different ROM,
existing worlds and all original saves remain unchanged. No world migration
or repinning was performed.

## Preserved artifact and pins

Physical Windows ZIP path:

```text
C:\Users\kashh\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\PokemonPrivate\artifacts\windows-release-candidate-20261009-3\package-1\EmeraldTogether.zip
```

Size: **77,687,074 bytes**. The internal version is
`Private Gen6 defaults candidate10 - 2026-10-09`. The package contains the
installation BPS, runtime and source/relink notices, not a source or target
ROM, player save, invitation or world database. It has not been distributed.

| Component | SHA-256 |
| --- | --- |
| `EmeraldTogether.zip` | `c8b6e63c1dcae79c9fd402c195c4c03d5bf51d235295549171462f726c706baf` |
| `EmeraldTogether.exe` | `cf30ceec33fcc1b1d62bb16a4b8eeecda353b0bda2806613dc7b4ee58ab6216c` |
| Native game target, not bundled | `0b13865da4947b855cfe8062fd624b284725fd1ccb1ff6172d5680b853fac8d2` |
| Game manifest | `999de8a5f20e4194befa59666508ec37b498dcb191ee54a60b9d8fe428611a70` |
| Installation BPS | `2e6b7e053f0ed06dd32b23b599d43496da31bacfcdf900f59658c8c9f55797a8` |
| Required uncompressed owner dump, not bundled | `a9dec84dfe7f62ab2220bafaef7479da0929d066ece16a6885f6226db19085af` |
| Reused runtime manifest | `698dff484ded620615d4002c0758bf14379cdb01cf25750d69499dc1cc6a5a84` |
| Trusted replay worker | `43de0d1668a41c7e6c5aa6de2b43ba0228d3d719c5d528a62c3d2df9a0e6a14b` |

## Application changes and build boundary

The frozen source has 122 production Python modules. Its provenance records
20 changed or added modules since candidate 9, covering the explicit Gen6
profile, [friend character handoff](windows-first-run-setup.md), selected-source
hash enforcement before enrollment, launcher layout, interrupted-trade
recovery, and Championship recovery. The corresponding implementation and
focused evidence are documented separately; packaging does not prove those
gameplay flows.

The bundled quick start explains explicit world trade policy, host approval of
a friend's exported unassigned character, personal invitations, and the exact
**Resolve interrupted trade** action. Recovery retains the original held game
until authoritative evidence permits normal closure and fresh Host/Join. It
does not promise same-core resumed trading or whole-PC reconstruction.

Existing Python 3.14.4/PyInstaller 6.22.3 built a new `package-1` output from
`frozen-project/`. No dependencies were installed or native runtime rebuilt.
The entire candidate 9 runtime and its relink/source material were reused
byte-for-byte. The build runs recorded in `build-candidate.py` and
`build-arguments.json` used the existing environment at below-normal priority.
The normal production preflight reported `import_enabled=true` and
`development_preview=false`, checked the then-existing full-reset/replay
requirements, and reconstructed the new ROM. **That preflight did not yet
check the three player debug menus identified after this build.**

The initial proposed version string exceeded the existing 48-character bound.
Preflight refused it before creating package output; `input-preflight.log`
preserves that failure. The shorter label above passed without weakening the
validator. `guides-before/`, `inputs/`, `source-inputs.json` and
`input-copy-index.json` preserve the exact inputs and their original/copy hashes.

## Completed bounded checks

- Recursive directory and ZIP audits passed: 6,477 and 6,574 inspected
  files/archive members, across 14 and 15 archives. This is the existing bounded
  format/name audit, not a universal content or rights audit.
- PE inspection confirmed AMD64. All 1,087 packaged files matched the generated
  inventory after the checks; the frozen 122 application modules still matched
  the repository at that final verification boundary.
- The frozen production importer, using this package's actual BPS and metadata,
  imported the owner-supplied ZIP into a new private destination. It produced
  the exact `0b13865…` ROM; an identical retry and installation/runtime checks
  passed. The source ZIP retained its hash. This was not a GUI import check.
- The actual packaged executable opened with a new isolated `LOCALAPPDATA`.
  Exact image path, hash, PID, creation time and window title were verified.
  Normal `CloseMainWindow` returned exit 0, with no forced termination or
  retained child. No game, world or network session was opened. This check
  does not qualify the full setup layout or file-picker interaction.
- The original candidate 9 ZIP and every reused runtime file retained their
  hashes. No original world/save or the owner's ZIP was changed.

The new ROM also has independent [Gen6 native and replay evidence](gen6-defaults-profile.md):
five focused native tests and four isolated real-worker replay checks. The
packaging check verifies that replay evidence names this exact ROM, manifest,
runtime and worker. Synthetic replay is not a live player trade. Actual game
flow evidence is maintained separately; the package checks above do not
substitute for it.

| Private receipt | SHA-256 |
| --- | --- |
| `source-inputs.json` | `8cf235aa9f2b92ed208727ba124cc390ce06f8481ff106476ba3289627327f6d` |
| `input-copy-index.json` | `d572546a464040eca5c6e7dad37aea1a1c7b11e0eca9256915765573321fdb46` |
| `package-1/resources/package-provenance.json` | `aea8139bb4c0cff630c4e16561425f1088a70387069c1af3d8c6e399bc5a4eb4` |
| `package-1/package-audit.json` | `0fa5ad111847baee365fdb99acf5987ee2b8fc95c7d911f1357807dfdf90b591` |
| `import-checks.json` | `b2ad71ef3fe8ea15c938cddd6f74d2619de594a69261afb526d932e67ffad088` |
| `startup-checks.json` | `ff9e5abec0d1f12376eb229ff6599736399019aa1786ec794bbcf550d76cbc08` |
| `final-checks.json` | `2bc841a6d9d1c248dc17025de6e88666c7509299009b1238369e5b4e4e338875` |
| Exact-ROM `gen6-defaults-20261009-1/replay-3/evidence.json` | `4b927c82742c63695b4f2c0c6f9a9b23513eae2f5e375fcdcf600718b3b8e213` |

All receipts except the explicitly named Gen6 replay are under the candidate
artifact directory above. Startup recorded PID 53640, creation
`2026-10-09T07:13:06.5823249Z`, exit 0; process IDs are historical observations,
not authority to act on a later process with a reused ID.

## Remaining acceptance and gameplay limits

The three enabled debug menus are a concrete release blocker. A separately
built ROM, manifest, patch and package must address them; this package stays
preserved for diagnosis. Clean-PC installation, Defender/SmartScreen handling,
separate-PC Wi-Fi/Internet play, physical controllers, full four-client flows,
and end-to-end friend enrollment are not established by these receipts.
Actual interrupted-trade service-loss recovery remains a separately tracked
qualification and is not claimed by candidate 10's build/startup result.

The trade gate still refuses imported later-generation moves such as Leafage
633. The owner's policy decision is pending; no move was removed, substituted
or admitted to make the package pass. Gen6 acquisition/form/affection and
mechanic gaps remain as listed in the profile document. Existing worlds stay
pinned to their original build, and this package performs no migration.
