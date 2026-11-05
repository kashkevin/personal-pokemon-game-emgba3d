# Native trade eligibility boundary

**Update 2026-11-05 (Eggs and Mail, owner decision 39; KNOWN_ISSUES "Trades: eggs and Mail", option (b) for both):**
the exact exchange (the trades every packaged world makes) now carries Mail always, and Eggs where the world's game
hatches a traded Egg correctly. What the sections below say about refusing Eggs and Mail is history; this is the rule.

* **Mail.** A party Pokemon holding Mail names one of its trainer's six party Mail slots (party record byte 85,
  `MON_DATA_MAIL`; `SaveBlock1.mail` at 0x2BE0, 16 slots of 36 bytes, the first six the party's, verified in the engine's
  DWARF for the GBA and the PC build). The host does what the link trade does (`trade.c` `TradeMons`): the sender's slot
  is cleared exactly as `ClearMail` clears it, and the whole 36-byte Mail (words, author's name and ID, the Pokemon it was
  written for, the item, the padding) is copied into the receiving save's first party slot whose item is `ITEM_NONE`,
  the outgoing Pokemon's own slot counting as freed (`GiveMailToMon2` / `GiveMailToMonByItemId`); the received record
  points at it (its byte 85, the only byte of the 100 that differs from the sender's record). Nothing else changes; the
  PC's mailbox is untouched (`trade_mail.py`, `trade_flash.recipient_post_image`). Refused before anything moves: Mail
  the game itself never makes (a slot outside the party's six, a slot whose item is not the Pokemon's held Mail item, a
  slot two party Pokemon name, an Egg naming a slot: `mail_invalid`) and a receiving party with no free party Mail slot
  once its own offered Pokemon has left (`mail_slots_full`, checked at each confirmation). A Mail item held without a
  reference is an ordinary held item and travels with its record. The trade's save import already carries the Mail
  array (the game writes and reloads the whole save), so Mail needs no engine change; every player of a world runs the
  host's launcher version (MS-28), so each recipient rebuilds the same post-image.
* **Eggs.** An Egg trades as the record it is: every byte kept (species, egg cycles left, IVs, personality, moves, both
  Egg flags, its original trainer as it was). Offered only when the host's game declares that it hatches a traded Egg
  correctly (manifest `trade_egg_abi_version` 1, from the engine's PC-only `gMultiplayerTradeEggAbiVersion`;
  `bridge_config.trade_eggs_enabled`, `WorldServer.enable_egg_trades`, `CompanionConfig.trade_egg_abi_version`): the
  pinned engine's party hatch (`egg_hatch.c` `AddHatchedMonToParty`) sets a new trainer ID without re-encrypting the
  record, which turns another trainer's Egg into a Bad Egg, and its PC-box hatch keeps another trainer's ID. A launcher
  whose game lacks the capability refuses a preparation bringing it an Egg before acknowledging anything.
* **The one change of original trainer the host accepts.** When a game hatches an Egg, its own player becomes the original
  trainer. The store accepts exactly that, and only that, in an ordinary checkpoint: the same serial and personality, an
  Egg (either flag) in the owner's previous checkpoint and no Egg now, its new trainer ID the save's own, and an Egg that
  came to this owner by a trade of this world or with the character itself (the first checkpoint of an enrolled source or
  of a character coming back, which can only hold another trainer's Egg by a trade elsewhere); an Egg born in the owner's
  own play already has the owner's ID and may change nothing (`TradeCheckpointStore._origin_change_allowed`,
  `trade_storage._hatched_egg`). Any other change of personality or trainer ID is still `immutable_identity_changed`. The
  instance's current trainer ID follows (`ownership_instances.ot_id`); its earlier memberships keep the Egg's trainer, the
  history audit replays the same rule, and a character coming back with a copy of the unhatched Egg is still refused
  (`character_transfers.transfer_player` also matches a Pokemon's earlier trainer IDs).
* **Lucky Trades and trade friendship skip Eggs.** The exact exchange applies neither (no Lucky conversion, no friendship
  write); the handler-friendship ledger already records an Egg's byte as hatch cycles and starts its history at the hatch.
* **Preparations.** A pair with an Egg, a Pokemon holding Mail or a Mail item uses the capability
  `owned-party-exchange-eggs-mail-v1`: the same format, each offer also naming the SHA-256 of its Mail (`mail_sha256`,
  null without one) and each description the whole incoming Mail (`incoming_mail`, base64, null). Every other pair keeps
  `simple-owned-party-exchange-v1` with exactly the fields, digests and candidates of before. The store rebuilds a
  retained preparation under its own capability; the history audit also accepts the record-only exchange it committed
  before trades carried Mail (no such trade could hold Mail through the desk).
* **Atomic and recoverable, as every exact trade.** Both post-images, with the Mail cleared on one side and installed on
  the other, are one SQLite transaction; before it neither canonical save changed, after it each player's next
  checkpoint is refused until its game applied the post-image (`trade_recovery`), so a game's old save (the Mail and the
  Pokemon still there) can never become canonical again. Each recipient retains its description (with the incoming Mail)
  and rebuilds the same candidate in live and cold-start recovery; a changed retained description is refused.
* **Native trade effects (development worlds with the replay worker) still refuse Eggs and Mail**: their record and
  save-block replay runs in the engine, which refuses both (`MultiplayerTradeEffects_BeginRecord`).
* Tests: `tests/test_trade_eggs_mail.py` (Mail layout and reading, eligibility, byte-for-byte exchange, preparations,
  desk, the hatch rule and its audit, the transfer copy check, interrupted live trades carrying Mail both ways, the
  manifest marker).
* Real games (Linux, the 3D test build of engine `23887292`, two games through real launchers and a real world host;
  `native_launcher_newcomers_proof.py --scenario trade-mail` and `--scenario trade-egg --hatch-in party|box`, the
  fixtures `make_tower_saves.py` trade-mail-a/-b and trade-egg-a/-b, the host's saves read with the app's own code by
  `trade_eggs_mail_evidence.py`): a Wingull holding Wave Mail for a Treecko holding Wood Mail, each Mail whole in its
  receiver's slot, then the Treecko for a Zigzagoon, its sender's slot left as ClearMail leaves it; each receiving game
  reading its Mail (MAIL > READ); the first trade cut before the host's commit (nothing committed, both Mails where they
  were, then made again) and after it (the launcher held the committed trade until Resolve interrupted trade, the
  reopened game had it; or the stopped game took it once running); a shiny Togepi Egg traded and hatched by its
  receiver in the party and, moved to the PC, in a box: no Bad Egg, the hatcher its original trainer (ID, name, gender),
  everything else kept, the host's saves accepted; the hatched Togepi traded on; the Egg's first trainer's old save,
  the copy of the Egg unhatched, refused as a character coming back. Each with closing saves, a fresh Continue and
  the world's integrity check. Not shown: Windows, two PCs, the Classic 2D game, a receiving party with no free Mail
  slot (unit tests only), a hatcher's ID that alone would change the Egg's shininess (the engine's self-test only).

**Update 2026-11-05 (every form reviewed):** every form of a Kanto-to-Kalos species in the engine pin was reviewed
(the engine's compiled species table: its National Pokedex number, `cannotBeTraded`, its form changes and evolutions),
and the 163 that such a Pokemon keeps outside battle in the Gen 6 games, where they trade as they are, are now
exchanged like Rotom's: Unown's letters; Burmy's, Wormadam's and Mothim's cloaks; East Sea Shellos and Gastrodon;
Blue-Striped Basculin; Deerling's and Sawsbuck's seasons; Scatterbug's, Spewpa's and Vivillon's patterns; Flabebe's,
Floette's and Florges's colours; Furfrou's trims; the female Meowstic; Pumpkaboo's and Gourgeist's sizes (the receiving
game evolves a Pumpkaboo into the Gourgeist of its size, MS-151's rule on the form's own evolution table); Deoxys's
three formes, Origin Giratina, Sky Shaymin, Arceus's 17 types, the three Therian Formes, Resolute Keldeo, Genesect's four
drives and Unbound Hoopa (each keeps its held item, moves and the days a form has left, all in its own record).
`trade_forms.py` lists them with the standard species and a menu label; `tests/test_trade_forms.py` checks each against
the engine pin's own name and number (`species_national.py`, generated by
`scripts/multiplayer/generate_species_national.py`). Still refused: battle-only forms (Megas, Primal Reversion,
Castform, Cherrim, Zen Darmanitan, Pirouette Meloetta, Blade Aegislash, Active Xerneas, Complete Zygarde), forms from
later games (regional forms, Zygarde's 10% and Power Construct, Greninja's Battle Bond and Ash, Pikachu's caps,
White-Striped Basculin, Origin Dialga and Palkia), the games' untradable Black and White Kyurem, Spiky-eared Pichu and
the starter Pikachu and Eevee, and the event-only Cosplay Pikachu and Eternal Floette. Eggs and Mail stayed refused
until the update above (KNOWN_ISSUES "Trades: eggs and Mail").

**Update 2026-10-30 (the Rotom Catalog):** Rotom's five appliance forms (internal IDs 1064-1068) are exchanged like the
standard species: `trade_forms.py` lists them one by one (`REVIEWED_FORMS`, each with the standard species whose Pokédex
number it has and its menu label); every other form stays outside the standard range below. None is `cannotBeTraded`,
none evolves; the exact exchange carries the form as it is. `docs/rotom-catalog-20261030.md`.

**Update 2026-10-29 (KNOWN_ISSUES MS-151):** the species that evolve by trade are no longer refused. The exchange stays exactly the record exchange described here; the receiving game evolves the Pokémon it received by itself once the trade's save is loaded (engine `62154337`, `src/platform/mp_trade_evolution.c`: the native `EVO_MODE_TRADE` rule with the given-away Pokémon as its partner, the evolution scene, the held item it needs used up, the Everstone and its Kadabra exception), and its next checkpoint carries the evolution as any evolution. The four forms with a trade evolution stayed outside the standard range below; since 2026-11-05 Pumpkaboo's three other sizes are reviewed forms (the update above) and evolve the same way, Alolan Graveler stays outside. The sections that follow describe the gate as it was audited; where they say the trade-evolution species are rejected, read this update.

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
