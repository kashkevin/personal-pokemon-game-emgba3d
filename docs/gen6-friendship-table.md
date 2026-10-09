# Pinned Generation 6 friendship table

The paired trade planner now derives base friendship from the exact offered species and the generated table in `src/emerald_multiplayer/gen6_friendship.py`. Its preparation identifier is `gen6-paired-friendship-postimages-v2`; the input digest includes the table ID, table SHA-256, both observed species and both derived values. `FriendshipOfferPlan` no longer accepts a caller-selected base value. This is a preparation prerequisite, not an enabled trade-effects capability.

## Source and reproduction

The generator reads Git objects from the installed RHH pin `bb1093a7c72d3961d9a37d8e02ad2abc2c866682`, independently of worktree edits. It extracts source into a temporary directory, overrides only `P_UPDATED_FRIENDSHIP` to `GEN_6` inside its temporary preprocessing probe, and requires exactly 721 unique standard native IDs. The native compiler statically checks every species' National Dex mapping and every friendship byte. Only the resulting 721-byte data section is extracted; no ROM, graphics, save or native engine configuration is generated or changed.

The accompanying [machine-readable provenance](gen6-friendship-table.json) records each species/value, the original input-file hashes, generator/probe hashes and compiler/binutils versions. Table ID is `rhh-bb1093a7-gen6-standard-friendship-v1`; value SHA-256 is `b42adddfb53bcd89cb5e38b8319287dfede0d87751e31ff2d985db51f3c8bfe6`. The table contains the native configured values 0, 35, 70, 90, 100 and 140. Alternate forms and later standard species are refused by the lookup, as they remain outside this table's audited scope.

The existing untracked generator was first preserved byte-for-byte in a private artifact directory, with SHA-256 `1e23c09167c63cd96c303d21a0954e6582bf4259442fa2a3423f74c93cdfe2f9`. Its initial preprocessing failed because `-nostdinc` excluded a header required by `gba/types.h`. The corrected probe does not need native typedefs: it verifies the pinned native `TRUE`/`FALSE` definitions and substitutes their exact constants before preprocessing. Compiler diagnostics are now reported explicitly. Generation refuses to overwrite existing output paths; `--check` compares the complete existing module and provenance against a fresh extraction.

From WSL with the already installed toolchain:

```bash
python3 scripts/multiplayer/generate_gen6_friendship.py \
  --engine /home/kevin/src/pokemon/engine \
  --module src/emerald_multiplayer/gen6_friendship.py \
  --evidence docs/gen6-friendship-table.json --check
```

On October 8, 2026, native generation and the independent full-output `--check` both passed using GNU Arm GCC 13.2.1 and binutils 2.42. The nineteen table, encrypted-record and paired-Flash methods passed on Windows in 5.141 seconds and WSL in 4.117 seconds, with no skips. They cover complete provenance/value agreement, strict species bounds, all 24 encryption layouts, malformed generator input, canonical species-derived values, refusal of arbitrary base arguments, preserved unrelated bytes, and continued rejection of these post-images by the existing production exact-swap validator. These tests do not exercise native trade evolution or certify the entire engine's Generation 6 mechanics.

The implementation reuses the already incorporated RHH species facts and existing project planners; no new library, third-party code or art is imported. Read-only maintained upstream checks still returned RHH `7b95be15d84a053948791ce91e5dec0b168947a5` and PKHeX `66ef5983a5d349efa2dd615f2926a1b1ee97306e`. Their applicable terms, representation differences and reuse limits remain in [the native effects audit](native-trade-effects.md) and [dependency ledger](dependency-ledger.md).

## Remaining preparation and compatibility decisions

The production engine still has its existing friendship configuration, and `TradeCheckpointStore` still authorizes only `simple-owned-party-exchange-v1`. The native preview remains read-only. Evolution/item use, move-learning input, Pokédex flags, mail allocation, traded-egg origin changes, exact prepared-image publication and interruption recovery are unfinished. The new table resolves only the previously unqualified species-base input.

Two representation issues must be resolved before enabling complete Gen6 handler effects:

1. **Existing Pokémon without handler history.** Their GBA record contains one active byte, not both Gen6 original/handling values. Original-trainer matching and first ownership allocation do not prove that a Pokémon has never been traded; the existing observation ledger therefore correctly records unknown history. The faithful path is to retain unknown values and recover them only from valid prior evidence, while recording full history for new acquisitions once native provenance exists. If every legacy Pokémon must immediately use all handler transitions, an explicit migration rule is necessary. A concrete proposed fallback is to preserve the active value, initialize only the missing inactive value from this species table and mark the record as migrated. That fallback invents previously unavailable history and may change later Return/Frustration or return-to-original-trainer behavior; it is **not approved or implemented**. Discarding characters or silently setting both values is not a solution.
2. **Gen6 geography condition in a GBA game.** The inspected [PK6 implementation](https://github.com/kwsch/PKHeX/blob/66ef5983a5d349efa2dd615f2926a1b1ee97306e/PKHeX.Core/PKM/PK6.cs#L409) refreshes a handling trainer when both most-recent geographic fields are zero, except for its untraded Gen6 event case. This is not a general reset on travel between in-game maps. Our record has no matching fields. A concrete adaptation proposal is a permanent, game-local initialized-handler marker: new or explicitly migrated history establishes it once, and ordinary map changes never clear it. No real-world location is needed. This mapping and its legacy/event treatment remain **pending**, and the planner still requires an explicit trusted `refresh_handler` input.

These decisions do not prevent implementing the remaining native preparation, candidate validation and interruption mechanisms behind a disabled capability. They do prevent claiming complete, faithful handler behavior for arbitrary old saves or enabling effects with guessed history.
