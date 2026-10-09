# Four-player Championships — source implementation

Status: implemented, with focused server/controller recovery tests recorded in
[Championship recovery](championship-recovery.md). No actual native Championship
match or packaged four-person tournament qualification is claimed here.

The accepted format is four players, two 1v1 semifinals, then a 1v1 final.
The proposal shows the ordered participants and every player explicitly accepts
that bracket. Each match still uses the existing challenge acceptance, native
entry, canonical party checks, recovery, and release flow. Only the immutable
battle archive can provide a winner. Draws need another explicitly requested
challenge; no forfeits, wagers, prizes, or balance numbers are introduced.

## Reuse decision

Read-only source research inspected the pinned RHH expansion (original
`bb1093a7c72d3961d9a37d8e02ad2abc2c866682`, current local native base
`aef47e4b28fd6d0e84376961e0cc6632996bb0be`) and maintained RHH source
[`7b95be15d84a053948791ce91e5dec0b168947a5` battle_dome.c](https://github.com/rh-hideout/pokeemerald-expansion/blob/7b95be15d84a053948791ce91e5dec0b168947a5/src/battle_dome.c).
The Dome's sixteen-entrant player/CPU tournament does not supply independent
four-human consent, canonical host ownership, or interrupted native admission.
The compatible-community comparison remains Emerald Rogue
[`5ccb74cf1ef2c0349dfa5d70883b030bbc9ff803`](https://github.com/Pokabbie/pokeemerald-rogue/blob/5ccb74cf1ef2c0349dfa5d70883b030bbc9ff803/src/rogue_multiplayer.c):
its multiplayer architecture is not a replacement for this project's
four-player ownership and release barriers. Neither implementation is imported.

Reuse the project's `BattleDesk`, `BattleResults`, native admission/recovery,
bounded RPC framing and `PlayerMenu`. The new bracket is custom host-side
orchestration. Its SQLite sidecar follows the existing world-pinned result
archive and explicit transactions, using the installed Python standard library
([transaction documentation](https://docs.python.org/3/library/sqlite3.html#transaction-control)).
There are no new external dependencies, copied assets, license obligations,
native save-layout changes, or ROM requirements. Existing attribution remains
applicable. Performance is UNMEASURED; public history is bounded to four records.

The sidecar preserves issued match identities before inviting. An uncertain
issued match after host restart remains waiting for its original recovery/result;
it cannot silently issue a replacement. Bracket persistence does not reconstruct
lost native emulator processes. Active cancellation requires all four votes and
no outstanding match; proposed brackets may be declined by any participant.

## Source connection and limits

`src/emerald_multiplayer/championship.py` owns world/build/ruleset identity,
strict hashed records, immutable pairings, transactional consent, issued match
identities and result reconciliation. `BattleResults.get` supplies exact archived
results beyond the recent history page. Public history contains at most four
records belonging to the authenticated actor. Unchanged projections do not
rewrite records on polling. No character database or native save layout changes.

`championship_protocol.py` provides the bounded optional `battle_pending`
extension. Existing hosts refuse unsupported fields with a correlated error.
`server.py` authenticates the current lease and uses the same `BattleDesk.invite`
and original-core admission capture as ordinary challenges. `companion.py`
attaches the current native identity to match requests and checks that the core
has not changed across the await. The host issues each new battle ID; recovery
only references that exact previously issued ID. Clients cannot choose a new
match identity or supply an outcome.

`championship_menu.py` is composed into `player_menu.py` with the existing
immutable revisions, consumed choices, session guard and six-row limit. Players
open Championship from Challenges, review all four fixed seeds and explicitly
consent. The proposer is seed one; the current menu sorts the other three UUIDs
before showing the preview. There is one current bracket per world. Match
proposal returns to ordinary Challenges for native Accept/Enter. Championship
remains reachable during a pending 1v1 and its stored history remains reachable
when the host disables new battles. Cancel votes are reversible through explicit
withdrawal; a new match waits while a cancellation vote is outstanding.

The follow-up source batch connects a [Windows Championship panel](windows-championship-panel.md)
and [Trainer Card tournament counters](trainer-card-shared-records.md).
The recovery action has controller coverage, without packaged UI acceptance.
No buy-in, wagers or prizes are included.
This uses the game's existing party rules. [Durable abort reconciliation](championship-recovery.md)
now also consumes exact terminal reservation evidence after host restart.
Explicit **Recover waiting match** now resolves new durably pre-dispatch intents
and exact sender-only invitations whose original ledger proves no admission
began. Ambiguous dispatching/legacy intents, full consent or missing terminal
receipts remain waiting. Recovery never starts a replacement; a rematch is a
separate choice. Lost emulator processes remain outside retained-core recovery.
Native acceptance, unresolved dispatch uncertainty,
simultaneous semifinals, draws, final advancement and four-person usability all
remain UNVERIFIED. Source review corrected menu navigation; it is not gameplay
or compilation evidence.
