# Public native trade client

This integration connects the Players menu to the versioned native-recipient
effect backend. Compilation or the fixture checks below do not establish
actual multiplayer acceptance or an evolution cinematic. The later
[Windows two-client qualification](windows-menu-trade-effects-proof.md)
passed the supported non-evolving trade, manual-save and fresh-Continue flow;
its narrower actual-core scope is recorded separately below.

## Reachable flow

`companion.py:trade_rpc` negotiates `effects_version=1` through an existing
read operation before effect requests. A new offer requires the original
bridge's verified preparation, full-save window and move-choice capabilities
and menu ABI 2 (`trade_capability.py`). Explicit old-host `invalid_fields`
keeps ordinary trading available; timeout or another error does not authorize
a fallback mutation. Status/cancel probes use the exact transaction's status,
so a recovery-only host need not expose a proposal desk. Negotiation is bound
to world, server epoch and authenticated lease.

`NativeTradeMenu.run` prepares the original party and presents offers and both
explicit confirmations. Its effect eligibility admits the native supported
record set while still refusing Eggs, Mail, unsupported forms and moves. The
ordinary v1 exact-swap validator is unchanged. The host independently validates
the offers and supplies complete history plus an explicit world policy; the
client does not guess missing handler history or geography policy.

For a mutually confirmed v2 plan, the ordinary trade dialog must acknowledge
CLOSE before `prepare_effect_recipient` enters `HeldTradeEffectMenu` on that
same original `MenuSession` task. The player reviews the received/evolved
candidate, inspects move facts, explicitly chooses or declines each pending
move, and confirms the final candidate. Pausing keeps the original hold and
reopens an advanced-revision ordinary dialog with Resume evolution review.
There is no timeout auto-choice or peer consent.

The client renews the existing exact native trade hold while streaming all 32
Flash sectors. It retains the original source, host descriptor, original consent,
native READY record, explicit native screen decisions, READY review, complete
candidate bytes and completion context before `effect_prepared`. The wire's
`record_sha256` hashes the final 100-byte Pokémon, whereas the private native
record digest covers the 192-byte native response. They are intentionally
different values. The backend independently replays both candidates before its
atomic publication; the client receipt alone is not a commit.

## Recovery and completion

`trade_effect_recovery.py:retained_effect_candidate` verifies those retained
artifacts without native commands or a network call. Current authenticated
leases may be newer than the descriptor's original consent lease; the original
descriptor, history and consent bytes stay fixed. A missing or altered review,
choice, candidate, original consent or source causes refusal. Existing
`cold_start.py` calls the same `_prepared_candidate` path before restoring or
acknowledging a committed trade.

After commitment, the existing coordinator downloads only this character's
canonical result, requires exact equality with the reviewed candidate, imports
through the ordinary native mailbox, verifies readback, acknowledges, and
releases. The trade dialog is already closed before that import. A terminal
return includes the original `expected_revision` and `generation`, allowing
the launcher to check resumed prepared trades against their original base.

Only successful canonical apply/ACK/release produces an `Evolved: <species>`
or `Received: <species>` Players notice. A durable `.received-result.json`
binds the received identity/species/level to the exact candidate hash and
canonical revision. The launcher also reports that the trade completed and
saved. No animated evolution or cable-trade scene is implemented by this
client integration.

## Verification scope

`tests/test_public_trade_effect_client.py` covers positive/legacy capability
negotiation, changed-lease refusal, recovery-only host reads, original dialog
ordering, explicit pause/resume, retained candidate reconstruction under a new
lease, tampered evidence refusal and artifact-before-receipt ordering. Its
native records and menu events are fixtures, not emulator observations.

`tests/test_live_trade.py` uses real SQLite/codecs and a fake native endpoint.
It now exercises two original recipient preparations after mutual consent,
including lost second prepared receipt, reconnect/import/ACK/release faults.
The protocol itself was not weakened to retain obsolete commit-on-confirm
fixtures. The later actual-core run verified complete recipient save
readback, fresh Host/Join restart and the supported two-player flow. Actual
player-driven evolution and explicit native move selection remain unqualified.

After testing was reauthorized, the focused client run passed **41 tests in
35.542 seconds**: `test_public_trade_effect_client`, `test_trade_menu`,
`test_live_trade`, and `test_player_menu.PlayerMenuNetworkTests`, using the
existing qualified Windows Python. Eleven are new public-effect boundary
checks. The prior broader 90-test run had two subsequently corrected fixture
errors; its cold-start and menu-session checks passed. These results retain
the simulated-native scope above; they are not actual-core acceptance.

The pre-edit client source backup and disposable check logs are private under
`%LOCALAPPDATA%/PokemonPrivate/public-effect-client-source-before-20261009-1`.
No commercial ROM, private player save, credential or database is incorporated.

## Actual-native move category correction

The October 9 real Windows trade run exposed an enum mismatch before the
private review screen: the pinned engine's `DamageCategory` is None=0,
Physical=1, Special=2, Status=3, while the Python parser and labels assumed
0/1/2 for occupied moves. Actual Growl and String Shot therefore failed the
read-only opcode 29 reply validation. `trade_effect_choice.py` now requires
1–3 for occupied moves and zero only for an empty slot; `trade_effect_menu.py`
uses the matching labels. No native ABI, authority, deadline, or move
eligibility rule changed.

`test_trade_effect_choice`, `test_public_trade_effect_client` and
`test_trade_menu` passed **19 tests in 2.500 seconds**, including the complete
opcode 29 envelope, empty/unknown-category refusal and actual detail-page
labels. The fixture log and pre-edit source are retained privately under
`%LOCALAPPDATA%/PokemonPrivate/artifacts/native-trade-category-before-20261009-1`.
The frozen `wqte2` failure is preserved. Its successor `wqte3` reached both
real native review screens, paired publication and both canonical applications;
its later failure was the proof's missing ordinary Players reopening, not a
second product correction. The full qualification and remaining limits are
recorded in the [Windows proof report](windows-menu-trade-effects-proof.md).
