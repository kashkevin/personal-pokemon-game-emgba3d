# Separately identified Gen6 defaults candidate

October 9, 2026. This is an implementation of the pinned engine's generation
defaults and exact client/host identity, **not completion of the Gen6 roster,
acquisition paths, all mechanics or the full game**. Existing worlds, saves and
the candidate9 build remain intact. No migration or world repinning was run.

## Reuse and scope

The pinned RHH engine already supplies generation-selectable move/species data,
ORAS level-up learnsets and battle rules. The [earlier audit](gen6-foundation-update.md)
identified these settings and the separate content/save-layout work. The current
maintained upstream was also inspected at
`7b95be15d84a053948791ce91e5dec0b168947a5`:
[general settings](https://raw.githubusercontent.com/rh-hideout/pokeemerald-expansion/7b95be15d84a053948791ce91e5dec0b168947a5/include/config/general.h),
[Pokémon settings](https://raw.githubusercontent.com/rh-hideout/pokeemerald-expansion/7b95be15d84a053948791ce91e5dec0b168947a5/include/config/pokemon.h),
[battle settings](https://raw.githubusercontent.com/rh-hideout/pokeemerald-expansion/7b95be15d84a053948791ce91e5dec0b168947a5/include/config/battle.h).
This change adapts the already incorporated engine; no new external source,
art, library or dependency installation is involved. Existing attribution and
distribution limits remain in [the dependency ledger](dependency-ledger.md).

The native change sets `include/config/general.h:GEN_LATEST` to `GEN_6`.
`src/multiplayer.c` exports an 80-byte descriptor containing a version, magic
and eighteen **compiled** configuration values. The manifest generator reads
the exact ELF symbol, checks those bytes in the ROM and assigns
`gen6-defaults-rhh1.17.1-mailbox-v1`. The companion checks the same descriptor;
host provisioning and invitations accept the new exact profile. Their normal
ROM hash, world identity, certificate and save-profile checks remain required.
An old world is not silently converted by installing this game.

`include/config/species_enabled.h` stays unchanged, SHA-256
`86a829d83a344bf23440a586706bf3c91ccef9a02c145afa0d1844c8824374eb`.
Disabling later species at compile time would change Dex arrays/save layout.
The required 721-species acquisition boundary therefore needs separate gates;
the broad compiled roster is not a claim that later species are allowed.
Existing Pokémon and their learned moves are not rewritten. The question of
trading imported Pokémon with post-Gen6 moves remains pending with the owner.

## Exact normal build

Native working tree: `engine-admission-cleanup-20261008-1`, based on
`aef47e4b28fd6d0e84376961e0cc6632996bb0be`; original incorporated RHH base
`bb1093a7c72d3961d9a37d8e02ad2abc2c866682`. New output name
`pokeemerald-gen6-20261009-1`, `LOCAL_RESET_DEVELOPMENT=0`,
`LOCAL_RESET_STATIC=1`. Existing visual outputs are preserved.

| Input/output | SHA-256 |
| --- | --- |
| Normal ROM | `0b13865da4947b855cfe8062fd624b284725fd1ccb1ff6172d5680b853fac8d2` |
| Normal ELF | `22ba5fa605ddf3011af2c2009c6f418eca894e608b09ca6af4fe8b361d3e98b3` |
| Manifest | `999de8a5f20e4194befa59666508ec37b498dcb191ee54a60b9d8fe428611a70` |
| `include/config/general.h` | `f6c1564b9cd89f686595e18d0f40f6b1ebbc3e9104aede015599e508747a20cd` |
| `src/multiplayer.c` | `3529c1516c94bc290c74c74e59ee00f707c7a9b9818ae1105867a03f8b41751c` |

Linked usage: EWRAM 235,100/262,144 bytes; IWRAM 28,376/32,768;
ROM 26,785,516/33,554,432. Remaining EWRAM does not measure heap peaks;
IWRAM needs stack headroom. Make returned success with its existing clock-skew
warning observed in the build output. The original `/tmp` compile/test logs
disappeared after WSL stopped; the repeated build and successful focused tests
are now retained in the permanent private directory below. Compilation alone
is not acceptance.
Before-source copies are under private
`PokemonPrivate/artifacts/gen6-defaults-20261009-1/source-before`.

## Verification and limits

Twenty focused Python checks passed (5.946 seconds), including new profile
descriptor corruption/missing-field refusal, old-client welcome refusal, fresh
host/invitation creation and exact-profile import. Opening an old disposable
world using the new profile failed without changing its file hashes. These
use synthetic ROM bytes and do not prove gameplay. Sources:
`tests/test_gen6_profile.py`, `tests/test_host_world.py`,
`tests/test_invitations.py`, `tests/test_companion.py:ConfigValidationTests`.

The engine's actual headless mGBA runner passed all **five selected tests** in
`tests/native/gen6_defaults.c`, copied to native `test/gen6_defaults.c`:

- Ordinary `CreateRandomMon` gives a new level 7 Treecko Pound/Leer/Absorb.
- Every standard National Dex entry 1–721 has a nonempty, bounded level-up list
  containing no post-Gen6 move.
- Actual creation/data reads give Pikachu 70 and Buneary 0 friendship, Gengar
  Levitate, Thunder Wave 100 accuracy and Clefairy Fairy typing.
- Battle turns take one eighth maximum HP from burn and quarter Speed for
  paralysis, without test configuration overrides.

The first Treecko check incorrectly called low-level `CreateMon`, which does
not assign moves; it failed 4/5. The corrected check uses the real ordinary
creation wrapper, with no production change. The 5/5 result was repeated into
permanent logs. Unselected later-mechanic assumption diagnostics remain in the
log; this is not a full upstream-suite pass. The test ELF is distinct from the
normal ROM above.

The normal ROM also passed **four real Windows native replay checks** using
the unchanged packaged worker: full recipient-save output versus an independent
non-evolution expectation, actual backend atomic paired publication/integrity,
Machoke→Machamp with identity/OT/damage preserved, and real historical replay
before enabling writes after restart. These are invented Pokémon/save fixtures
and an isolated computation core, not a live player trade. The paired replay
took 2.057 seconds; this is not a multiplayer frame-rate measurement.

Private evidence root:
`%LOCALAPPDATA%/PokemonPrivate/artifacts/gen6-defaults-20261009-1`.
`replay-3` freezes 241 source/test files and preserves the full runtime. Its
readback verifies frozen inputs rather than treating concurrently edited source
files as immutable; the receipt lists four unrelated setup/enrollment changes
in the working repository. Replay 1 passed its native checks but failed that
mutable-working-tree audit. Replay 2 passed those checks but failed a missing
prior-harness receipt. Both failed receipts are preserved; only replay 3 is
counted as an accepted isolated replay.

| Evidence | SHA-256 |
| --- | --- |
| Additive `engine-patches/phase7-gen6-defaults-profile.patch` | `1456e2a5ab88a4966de640eee50d297c7efa2fce03739e7b5e079a1d390de39c` |
| Repeated `build-verification.log` | `88642994e9b54055a1548c8a7a5628cf5d04784cf42ccedad0e529fa5a292737` |
| Successful `native-tests.log` | `c5ada46438d2bae34617b79ae6cc4ee698055ebc290b6e5bd0e0ca79ca717022` |
| Test ELF | `7dfd52fe905043e39295eeff03fd07e371f8529d2e017f7c0eac0dc55cbe06dc` |
| Headless test ELF | `0b1f43f44cb7cab1e33461a720baae1896302298302c0547c8270a761ac16523` |
| `replay-3/evidence.json` | `4b927c82742c63695b4f2c0c6f9a9b23513eae2f5e375fcdcf600718b3b8e213` |
| `replay-3/source-input-index.json` | `9b67fd704d6fdba7a518bdb1c58d327c31bc2e5c6effb2561d2db9cc144c2e7f` |
| Native focused test source | `e917eba426cfdee98ce4bd1922d91e279193f9e44c8e98df31a6d1330eb30855` |

Remaining Gen6 gaps include TM/tutor/egg acquisition, full encounter/form
eligibility, later-Mega adaptations, separate Gen6 affection versus friendship,
and explicit later-mechanic booleans that do not follow `GEN_LATEST`.
The global `SHINY_ODDS` literal remains 8; no new shiny rate was selected.
`B_EXTRAPOLATED_MOVE_FLAGS`, `B_X_ITEMS_CROSSUSE`,
`B_THUNDERSTORM_TERRAIN`, `B_RUN_TRAINER_BATTLE` and
`B_AFFECTION_MECHANICS` still need separate treatment. The upstream
`GetMonAffectionHearts` derives hearts from friendship, unlike Gen6's separate
affection system. Selecting Gen6 defaults does not fix that design mismatch.
New defaults must receive actual Continue/trade/battle/reset qualification
before this candidate can replace the existing multiplayer acceptance build.
