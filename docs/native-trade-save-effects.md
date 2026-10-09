# Recipient trade save effects — source implementation

This addition extends the [private native record helper](native-trade-record-preparation.md) into complete paired recipient Flash candidates. It is **source-only, unbuilt and untested** under the owner's instruction to stop testing. The ordinary published capability and exact-swap validator remain unchanged; this does not make trade evolution playable.

## Reuse and exact scope

The pinned RHH implementation supplies the behavior. `src/trade.c:UpdatePokedexForReceivedMon` and `src/pokemon.c:HandleSetPokedexFlag` provide received seen/caught registration and first-caught Unown/Spinda personality. `src/evolution_scene.c:T_EVOSTATE_SET_MON_EVOLVED` adds the evolved species and evolution statistic. `src/overworld.c:IncrementGameStat` supplies encrypted, 24-bit saturating counters. `src/trade.c:SaveTradeGiftRibbons` and `CheckPartnersMonForRibbons` supply gift-description merging and ribbon-menu visibility. The [reuse audit](native-trade-effects.md#reuse-audit) retains revision, license, upstream and compatibility findings. No dependency, external implementation or upstream revision was imported.

`MultiplayerTradeEffects_ReplaySaveBlocks` replays the record helper before changing any output. It copies the exact recipient SaveBlocks 1 and 2 into distinct caller-provided buffers, replaces the offered party slot and applies:

- Received seen/caught bits, with the original incoming PID for a first-caught Unown or Spinda. An existing caught entry preserves its recorded PID.
- Evolved seen/caught bits and one evolution-stat increment only when the result changes species.
- One trade-stat increment, using the recipient encryption key and native saturation behavior.
- The native champion-through-world ribbon visibility flag. It adds no Pokémon ribbons; that native range excludes the five contest-rank fields.
- Missing gift-ribbon descriptions copied from the partner's **original** save only for values 1–63. Existing recipient descriptions remain unchanged.

The API refuses output overlap with inputs, choices, the other output, live save blocks or global parties. Checks finish before output writes. It does not redirect global save pointers, invoke native scenes/saves/link callbacks, draw RNG, allocate memory or change live Dex/stat state. Both output buffers total 19,452 bytes; caller storage, stack cost and live-game memory budget remain unmeasured. The API does not allocate those buffers in EWRAM or establish that a future held-game transport can afford them.

Link-Room warp changes, native link save counters and wireless Mystery Gift/card bookkeeping remain unchanged in this direct-world candidate. Eggs, mail, uncatalogued forms, unqualified evolution conditions, missing handler history and unresolved geographic refresh remain gates. The helper follows the pinned configuration; it does not certify complete Gen6 mechanics.

## Exact Flash and pair validation

`src/emerald_multiplayer/trade_effect_flash.py` adds `EffectOfferPlan`, `SaveEffectPair`, `prepare_effect_pair` and `validate_effect_pair`. Each offer supplies complete retained friendship history and an explicit trusted handler-refresh decision. Checkpoints must be immutable and hash-correct, ordered by recipient ID, from one world/build/rules/profile, with disjoint inventories and current offered party instances. Recipient identities come from their canonical saves.

The preparation digest binds original consent fingerprint, transaction/generation, leases, checkpoint identities/revisions/hashes, offered histories, handler decisions, engine-source digest, game profile and pinned friendship table. Move choices are recipient-ordered; plans follow offered instances. Record witnesses additionally bind the complete original pair, resolved friendship/history, decisions and record output.

Two trusted native callbacks are mandatory: the existing record replay, and saved-block replay `(recipient_block1, recipient_block2, partner_block1, outgoing_slot, incoming_slot, friendship, choices) -> (block1, block2)` backed by `MultiplayerTradeEffects_ReplaySaveBlocks`. Neither may come from a network peer. There is no fallback accepting a client hash or output. Python independently reconstructs every permitted Dex/stat/ribbon operation and requires complete equality with native blocks, including the witnessed Pokémon record.

Validated active-bank section IDs locate logical sections 0–4. Only those payloads and native checksums are rewritten. The previous bank, SaveBlock3 ownership metadata, PC/daycare/fusion storage, padding, counters, special sectors, RTC footer, unrelated Pokémon and all other fields remain byte-identical. Both final Flash and ownership parsers run before returning a pair.

`validate_effect_pair` reconstructs from separately supplied authenticated inputs and expected decisions, then compares both entire containers, witnesses, histories and digests. Identical originals produce the same bytes and counters. This is deterministic preparation, **not durable exactly-once publication**: the future store must reuse a published result and never rebase a retry on that result.

## Layout and preservation evidence

The engine remains `/home/kevin/src/pokemon/engine-admission-cleanup-20261008-1`, base `aef47e4b28fd6d0e84376961e0cc6632996bb0be` plus preserved uncommitted patches. Read-only GDB expressions against the frozen `pokeemerald.elf` debug types confirmed SaveBlock sizes 15,568/3,884; Dex offsets `0x3598`/`0x3619`, gifts `0x31A8`, flags `0x1270`, stats `0x159C`, encryption key `0xAC`, Unown PID `0x1C`, and 129 Dex bytes. No inferior was started and no project code was executed. Source supplies Spinda PID `0x20`, ribbon flag `0x89B`, seven gift descriptions and stat IDs 21/14. New native static assertions bind these offsets/constants against future layout drift; they have not been compiled.

The preceding native files are preserved at `/home/kevin/src/pokemon/trade-save-effects-source-before-20261008-1`, header/C hashes `974d9b68d6721ecede8ce987b3fadd6fc82cf116d4a4a739aff51fea8a7de61a` and `96637b8fb475983d7df87ff740256febe722c339fb347354f910e9580ee5ab9f`. The new [incremental patch](../engine-patches/phase3-trade-save-effects.patch) applies **after** the [record-preparation patch](../engine-patches/phase3-trade-record-preparation.patch). It changes only the two trade-effect files; all other engine work, patches and builds are preserved.

| Source | SHA-256 |
| --- | --- |
| `trade_effect_flash.py` | `a33b5ad09a0e0246d3ba878e81b1bbc838393658fd5eff7492a3a8943ea1105c` |
| `phase3-trade-save-effects.patch` | `6f2c084c52455cca05b2c207b9730a64ffbdf52e746387cfef079cef711a5cc3` |
| `include/multiplayer_trade_effects.h` | `9c879e4413067bbb80aec7eb4c93c7ca7e9d7e815f335878f5eee109f0bfe9c4` |
| `src/multiplayer_trade_effects.c` | `ed7a0c85ef32a0544dceea1db7440f9f4d1c89167d9ee65af03029120c10eb28` |

## Remaining connection and verification

The later [full-save transport](native-trade-save-transport.md) now connects
native private sector overlays and independent whole-container comparison to
the held client. It retains the original helper and exact-swap publication gate;
the remaining native presentation/history/publication work is recorded there.

Subsequent source work adds a [held record/choice transport](native-trade-record-transport.md).
It connects only the record helper, leaving this full saved-block layer and
atomic effect/history publication unconnected. The following paragraph records
the original save-layer boundary; it is not a claim that record transport is
still absent.

This addition has no public effect capability, held preparation opcode, move-choice/evolution presentation, native replay transport, migration or atomic effect-history publication. `TradeCheckpointStore.commit_trade` and immutable-history replay still reject these modified candidates. The next connection must retain original frozen authority, both decision transcripts and candidate/history outputs, await both recipients, then publish or recover them together. Unknown legacy history cannot be reconstructed from one friendship byte.

No tests, builds, application imports, emulator/UI/game runs, installs, private save reads or commits occurred. Future verification needs native/Python differential cases for evolutions and encrypted permutations, counters/keys/saturation, first-caught PIDs, ribbons, bank rotations, existing bits, alias refusal, full-container tampering, interrupted preparation and durable publication. Historical preview tests do not cover this save layer.

Two independent source reviews found no concrete blocker for this internal computation-only scope. They compared native bookkeeping, packed ribbon fields, recipient/offer ordering, original-input bindings, full native/Python block agreement and active-bank preservation. These reviews did not execute the implementation or establish gameplay acceptance.
