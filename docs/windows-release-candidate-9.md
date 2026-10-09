# Private Windows release candidate 9

October 9, 2026. This new import-enabled package includes the reviewed native
move-category correction. It supersedes candidate 8's application source;
[candidate 8](windows-release-candidate-8.md) and package 7 remain unchanged.
The complete runtime, native ROM and verified BPS were reused byte-for-byte.
No dependencies were installed, native code rebuilt, saves edited or worlds
migrated during this packaging pass.

## Download and pins

Physical Windows ZIP path:

```text
C:\Users\kashh\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\PokemonPrivate\artifacts\windows-release-candidate-20261009-2\package-1\EmeraldTogether.zip
```

Size: **77,658,804 bytes**. Extract the entire `EmeraldTogether` directory and
keep the executable beside `_internal`. This is a private candidate; it was
not distributed. The package includes its pinned BPS and runtime, never the
source/target ROM, player saves, invitations or a world database.

| Component | SHA-256 |
| --- | --- |
| `EmeraldTogether.zip` | `ae8c40ea8a4ec2f4a2f0b3cc936e9f42917c032d378510d8238675f072f4edf0` |
| `EmeraldTogether.exe` | `fb239ee2724362d70c1d55ef159b4cdf921df31f71980533634e312dffbe658e` |
| Native game target, not bundled | `f99bfa4e19ccb5ba998b54d2151986665c15bed3b2d28dab10340d59be3a1d65` |
| Game manifest | `f97dffa70c4edf93de4f90202f8fe08a5a3a499cb2113574c73881321b4bb7e1` |
| Installation BPS | `2bac367a4701087ec8c021dd8d5de1c747b6cdde08e228eb010b36717217fe22` |
| Required uncompressed owner dump, not bundled | `a9dec84dfe7f62ab2220bafaef7479da0929d066ece16a6885f6226db19085af` |
| Runtime manifest | `698dff484ded620615d4002c0758bf14379cdb01cf25750d69499dc1cc6a5a84` |
| Trusted replay worker | `43de0d1668a41c7e6c5aa6de2b43ba0228d3d719c5d528a62c3d2df9a0e6a14b` |

## Correction and preserved build boundary

Pinned native `include/constants/pokemon.h` defines damage categories NONE=0,
PHYSICAL=1, SPECIAL=2 and STATUS=3; `multiplayer_trade_effects.c` exports
`GetMoveCategory` directly. The Python parser had treated occupied moves as
0–2, and its display labels were shifted. The corrected parser accepts occupied
categories 1–3, reserves zero for empty slots, and displays their exact names.

Frozen corrected module hashes:

- `trade_effect_choice.py`:
  `66b2df58bc329fb45945127024407cc3f92eab2cfdbdba4c064132d08d7c0036`.
- `trade_effect_menu.py`:
  `a5391dcde643467ec3e82b6dd181466ca440f27bc15333bd0976c90032ca2111`.

These are the only production Python differences from candidate 8. The guide
also explicitly identifies the existing refusal of later-generation moves such
as Leafage. No move limit, gameplay rule, odds or Pokémon data was changed to
obtain a pass. The fix received independent source review and 19 focused tests;
that evidence belongs to the correction, not a full packaged gameplay test.

The new `frozen-project/` and `source-inputs.json` retain the exact build input.
Existing Python 3.14.4/PyInstaller 6.22.3 built a fresh `package-1` output using
the recorded `build-arguments.json`. Normal production preflight checked the
full reset/replay capabilities and reconstructed BPS before building;
`development_preview` is false and `import_enabled` true. Native build,
source/relink material, dependency pins and the repaired 32-file collection
layout are unchanged from [candidate 8](windows-release-candidate-8.md).

## Targeted verification

- Recursive directory and ZIP audits passed: 6,477 and 6,574 inspected
  files/archive members; 1,087 actual package files. The audit is bounded
  format/name inspection, not a universal content or distribution-rights check.
- The frozen production importer used the **new package's** BPS/resources and
  unchanged original owner ZIP in a fresh private `import-check` directory.
  It installed exact f99 target bytes, then passed idempotent retry and complete
  game/manifest/runtime verification. This was not a GUI-button test.
- The actual new executable opened its `Emerald Together` window under a fresh
  isolated `LOCALAPPDATA`. Its image path/hash, PID and creation time were
  verified before normal `CloseMainWindow`; it exited zero with no force or
  remaining owned child. No game, host or world was started. Standard error was
  empty. This verifies entry/window lifecycle, not visual or button coverage.
- Final verification rehashed all 1,087 package files unchanged, confirmed all
  119 frozen application modules still matched production source, and verified
  the old candidate 8 ZIP and all reused runtime files were unchanged.

The exact packaged worker/f99 ROM combination also passed a separate isolated
native computation proof: both recipient save images matched an independent
fixture, the host published atomically, synthetic Machoke evolved while
preserving identity/damage, and restart mutations stayed fenced until historical
native replay passed. All 269 indexed inputs remained unchanged. Its evidence
SHA-256 is `6c842bf59f4b48c5aecfb66d4771264068dad7fa754b2f68f2fe69f2f074a4e0`;
[details and limits](native-trade-replay-worker.md) distinguish it from a visible
player trade, evolution scene or public gameplay recovery.

Receipts under `windows-release-candidate-20261009-2`:

| Evidence | SHA-256 |
| --- | --- |
| `source-inputs.json` | `e453f6bf8041e389480b4d1cbe032d91096e9a6ffd79ea5320178332a8c07c89` |
| `import-checks.json` | `ddc2ab360d1b4d743d0432811a24e542a0b7ee3e7cb8b8a682a63a4a9d7d63a7` |
| `startup-checks.json` | `f664bbcb04e765ba01a6528b4b08bce0e81ae1aa1d89cd9f0d7677f4c2177dad` |
| `package-1/package-audit.json` | `db2b23a1215310d60c5cfab97b71a9b32e1502982e818058969785e5ae5300b4` |
| `package-1/package-hashes.json` | `642787253aaa379075220949a7728df83570a2e30a68e16ef105f6a6d707d00f` |
| `package-1/resources/package-provenance.json` | `d9705c77747968b06fe9a79c9de7253c4484dc80a340e85fda7ca60a6bef8b9f` |

## Limits

Existing Pokémon with unsupported later-generation moves, including Leafage
(633), remain ineligible for this Gen6 trade-effect adapter. Broader data/learnset
compatibility is unfinished; safe refusal does not complete that requirement.
Public actual-core trade evidence and its failed/proof-corrected runs are
recorded separately rather than inferred from this package's startup.

GUI import, clean-machine installation, all packaged trade/evolution/battle/reset/
recovery flows, physical input/audio, four separate PCs and Wi-Fi/Internet
acceptance remain distinct checks. No firewall/router or original world changed.
