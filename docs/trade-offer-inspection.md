# Frozen offer details and unavailable-offer explanations

October 9, 2026 source implementation. No build, test, application import,
emulator session or UI run was performed for this addition. Its runtime behavior
and menu rendering remain **UNKNOWN**.

`NativeTradeMenu` in `src/emerald_multiplayer/trade_menu.py` now lets a player
select either complete offer to read its saved species/level, nickname, shiny
state, nature/stat nature, held item, original Trainer, moves/current PP, all six
IVs and EVs, saved party stats and ability slot. Details use the two original
frozen 100-byte records; they are not predictions of the post-trade result.
The ability slot is deliberately labeled as a slot, not an inferred ability name.
Japanese names are marked unavailable rather than decoded with the Latin map.

The existing party list's unavailable entries can be selected to explain egg,
mail, evolution or roster/form restrictions. This does not make them offerable.
The exact eligibility checks still run in `trade_eligibility.py` and again on the
host. B returns from an explanation to the party and from details to review;
B on the party/review screen retains cancellation semantics. Details never
confirm a trade. Both players still explicitly confirm the same offer fingerprint.

The host endpoint is `TradeDesk.inspect`, with `trade_protocol.py` validation and
the existing authenticated `WorldServer._trade` dispatcher. It returns only the
selected records after checking participant, generation, complete pair,
fingerprint and the two frozen canonical heads. It does not expose the peer's
whole save, party, storage or inventory. `trade_inspection.py` validates exact
record sizes, checksums/ownership identity and offered serial/species agreement.
The menu discards cached details when the fingerprint changes. Every screen
revision also includes that fingerprint, preventing an old button from being
interpreted as a choice on a changed pair.

Compatibility negotiation uses the existing `trade_status` operation with
`inspection_version=1`. Only an explicit matching acknowledgment permits the
new `trade_inspect` operation; an older host's field rejection leaves ordinary
trading available without details. Timeouts display a retry notice, never imply
success or consent, and do not silently disable the capability. World, server
epoch and lease are checked across the reads. Native screens retain six rows;
long facts wrap across detail pages rather than being cut off.

## Reused source and provenance

This extends the project's existing direct-trade service, menu mailbox, strict
owned-save parser and immutable consent design. The pinned engine already has
native summary/trade machinery, but its Link Room scene is not the owner of this
project's atomic two-save transaction. Reusing its record layout and display
facts avoids substituting a second ownership or trading system. The broader
upstream/community comparison remains in `customization-and-reuse.md` and
`native-trade-effects.md`; no community implementation or new dependency was
imported here.

`scripts/multiplayer/generate_trade_labels.py` and the retained
`trade-labels-provenance.json` describe the source-derived `trade_labels.py`:
617 move labels, 813 item labels and all 25 nature labels. Missing/ambiguous
names use explicit numeric labels. These are display facts, not acquisition or
battle-rule changes. Engine base is `aef47e4b28fd6d0e84376961e0cc6632996bb0be`,
incorporating RHH `bb1093a7c72d3961d9a37d8e02ad2abc2c866682`; all input hashes
and the generated output hash are in that provenance record. The existing
generator output was preserved during this continuation.

The record adapter was compared directly against this worktree's
`include/pokemon.h` (`PokemonSubstruct0..3` and `BoxPokemon`) and
`src/pokemon.c` (`MON_DATA_IS_SHINY`, `MON_DATA_HIDDEN_NATURE`,
`MON_DATA_ABILITY_NUM` and nickname handling). Shiny display reads the stored
threshold/modifier representation; it does not generate a roll or select odds.
Original code/asset attribution and distribution limits still apply. Neither
runtime cost nor visual layout has been measured.

Evolution publication, complete handler history, eggs, mail and extra forms
remain separate incomplete integrations. The optional native preparation
transport described in `native-trade-record-transport.md` is not enabled by
opening this screen. Source backups precede these menu edits in the private
`PokemonPrivate/artifacts/handoff-audit/source-menu-batch-before-20261009-1`
directory under `%LOCALAPPDATA%`.
