# Native trade eligibility boundary

**Update 2026-10-30 (the Rotom Catalog):** Rotom's five appliance forms (internal IDs 1064-1068) are exchanged like the
standard species: `trade_forms.py` lists them one by one (`REVIEWED_FORMS`, each with the standard species whose Pokédex
number it has and its menu label); every other form stays outside the standard range below. None is `cannotBeTraded`,
none evolves; the exact exchange carries the form as it is. `docs/rotom-catalog-20261030.md`.

**Update 2026-10-29 (KNOWN_ISSUES MS-151):** the species that evolve by trade are no longer refused. The exchange stays exactly the record exchange described here; the receiving game evolves the Pokémon it received by itself once the trade's save is loaded (engine `62154337`, `src/platform/mp_trade_evolution.c`: the native `EVO_MODE_TRADE` rule with the given-away Pokémon as its partner, the evolution scene, the held item it needs used up, the Everstone and its Kadabra exception), and its next checkpoint carries the evolution as any evolution. The four forms with a trade evolution stay outside the standard range below. The sections that follow describe the gate as it was audited; where they say the trade-evolution species are rejected, read this update.

The new `trade_eligibility.py` gate accepts only a simple, owned party-record exchange for development. `TradeDesk.offer()` applies it before changing an offer or its confirmations; `TradeDesk.confirm()` rechecks both complete current checkpoints before recording either actor's consent. The low-level `trade_flash.py` and schema-3 history/recovery remain unchanged. Trading is still disabled by default and has no player-facing offer UI. Passing this gate does not mean the complete native trade mechanics are implemented.

## Exact source audit

The inspected engine is trade-hold source `b2cdd466abb8b142c3b75384133b5e6b3c3b982c`, derived from the accepted ownership engine and RHH `bb1093a7c72d3961d9a37d8e02ad2abc2c866682`. No new engine code, dependency, asset, or upstream update is incorporated by this gate.

| Native seam | Actual behavior | Current exact exchange |
| --- | --- | --- |
| `src/trade.c:3096` `TradeMons` | Exchanges whole party records, resets received non-egg friendship to 70, clears outgoing mail, installs incoming mail through the recipient's mail array, and updates received Pokémon's Pokédex records. | Exchanges the offered 100-byte records only. Friendship is preserved; recipient mail/Pokédex effects are absent. |
| `src/trade.c:4428` `CB2_TryLinkTradeEvolution` | Evaluates `EVO_MODE_TRADE` after receipt, then invokes the ordinary evolution scene. | Since 2026-10-29 the receiving game does the same once the trade's save is loaded (`mp_trade_evolution.c`); the exchange itself is unchanged. |
| `src/pokemon.c:4507` and `DoesMonMeetAdditionalConditions` | Every trade evolution uses `EVO_TRADE`; held-item and trade-counterpart requirements are additional conditions. The native evaluator also considers Everstone, including its configured Kadabra exception. Qualifying evolution can consume the held item. | The gate rejects every species with any `EVO_TRADE` entry, including unmatched item/partner conditions or an Everstone. It does not predict, suppress, or simulate evolution. |
| `src/egg_hatch.c:308` `AddHatchedMonToParty` | Clears egg status, sets hatch name/language/location/friendship, updates Pokédex, changes OT ID/name/gender to the hatching player, restores PP, and recalculates stats. | Traded eggs are rejected. The immutable OT guard needs an explicit authorized hatch transition before this can be enabled. |
| `SaveTradeGiftRibbons`, `CheckPartnersMonForRibbons`, native save callbacks | Merge gift-ribbon presentation data, update ribbon/game statistics and applicable Mystery Gift trade statistics, and perform link saves. | These ancillary effects are absent. Native link saves must not replace the existing paired canonical transaction. |

The inherited cable UI also checks native link/version/National Dex conditions and a remaining non-egg party member. These UI restrictions are not copied into the direct multiplayer feature: the accepted specification requires early direct trades, and a reciprocal non-egg party replacement preserves party occupancy even for the one-member Treecko proof. The enrolled build's five legacy trade entry gates remain closed; this validator does not reopen the cable/NPC path.

## Implemented temporary capability

`validate_party_offer(payload, serial)` returns an immutable `EligibleTradeMon` containing the observed world/player, full-container hash, party slot, serial, species, PID/OT, held item and friendship. These observations do not authenticate a player or prove consent. `validate_trade_pair(payload_a, serial_a, payload_b, serial_b)` rechecks both offers and independent same-world inventories. Both functions are read-only and use the existing full Flash/ownership checksum and UID validation.

The gate refuses:

- Eggs marked in either the native header or encrypted miscellaneous substructure; malformed/bad-egg/checksum/UID records already fail the shared parser.
- Any attached mail index other than native `MAIL_NONE` (`0xFF`), or any held mail item (exact internal item IDs 199–210). A mail index refers to the sender's mail array and cannot safely be copied alone.
- (Until 2026-10-29: all 29 pinned `EVO_TRADE` source IDs, 25 standard species plus Alolan Graveler and three additional Pumpkaboo sizes. The 25 are now accepted; the four forms fall under the standard range below.) The encrypted held-item field is masked to its native ten bits, so the ownership UID bits are never mistaken for an item.
- Species outside the exact standard native IDs 1–721. The source enum explicitly assigns those values; alternate forms use other internal IDs. All native `cannotBeTraded` entries lie outside this conservative range. Form support and later internal namespaces require a new explicit capability audit, rather than accidental admission through a National Dex assumption.
- Absent/non-party offers, different worlds, the same owner, or shared instance IDs anywhere in the two source inventories.

Torchic (native ID 255), Treecko (252), and Wurmple (265) are eligible when non-egg, without attached mail, and valid in their current party. Their ordinary friendship is preserved exactly. The accepted paired-core proofs therefore remain record-exchange evidence; they do not become evidence of complete native trade effects.

These temporary exclusions do not remove eggs, mail, legitimate Gen 6 trade evolutions, or accepted forms from the final specification. Unsupported choices need a clear explanation in the eventual offer UI. No probabilities, friendship values, IVs, Lucky rules, evolution targets, or gameplay balance are changed by this implementation.

## Native completion before player-facing acceptance

Reuse the native trade animation, species evolution table, evolution scene, Pokémon setters/stat recalculation, Pokédex and mail helpers through a transaction-aware ROM adapter. Avoid activating `TradeMons` wholesale: its link callbacks, party globals and native save sequence assume a different authority model. Extend the strict post-image validator to authorize only the deliberate native effects alongside the offered instance transfer; do not grant unrestricted save changes.

The intended generation is the specified Gen 6 profile. The current RHH pin includes `GEN_LATEST` configuration choices; this source audit alone does not certify that profile or authorize the hardcoded received-friendship value for the finished game. Confirm the Gen 6 rules and each relevant configuration before enabling native completion. Preserve UID/PID/OT/shiny, IVs, nature, EVs, ability and moves except for explicitly legitimate native transitions. Evolving the received instance retains its UID; item consumption, stat changes and evolution-learned moves need precise approved mutations and retry-safe completion. Traded eggs require a verified origin transition at hatch. Mail needs recipient-local allocation and payload transfer, without copying unrelated inventory or progression.

Pokédex, ribbon presentation and per-player trade/history statistics must update once for a committed trade, survive reconnect, and not repeat on receipt retries. Lucky/friendship authority remains a later server transaction feature with its unapproved numerical rules still pending. The current gate neither grants Lucky status nor consumes a Lucky Friends flag.

Player-facing acceptance still requires the native effects, eligible-form catalogue, ordinary offer/confirmation UI, and actual-core evidence for supported cases and every interruption boundary. The new encrypted fixtures and existing consent/network suites supplement those checks.

## Verification

The affected 97-test trade/parser/ownership/coordinator set passes without skips on both Windows and WSL (60.418 and 117.916 seconds). Ten new tests cover real encrypted layouts across all 24 permutations, both egg flags, every mail item, local mail indices, all pinned trade-evolution species/forms, invalid checksums/IDs/inputs, party-only admission, independent inventories, and rejection before offer/consent or paired publication. The shared synthetic Pokémon fixture now uses native `MAIL_NONE`; dedicated negative fixtures retain actual mail references.

A separate read-only check of the accepted `paired-trade-cold-1` current canonical checkpoints confirms that Torchic serial1, Treecko serial33 and Wurmple serial2 all pass. Their respective friendship values remain64,50,50. The immutable closed SQLite backup hash remains `87dfb5eb8461ee5fdbf2e55cf3573f5a39ed0e462e2fd485bc9879ee33bcf2ed`. This compatibility check changes no save, database, native artifact or prior acceptance claim.
