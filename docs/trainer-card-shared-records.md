# Championship and shared Trainer Card records

October 9, 2026: source implementation only, under the owner's testing pause.
No execution, build, test or new accepted game/package is claimed.

## Reuse and boundaries

This extends the existing [Trainer Card implementation](player-card-and-hunt-records.md),
the project's immutable released battle archive, canonical paired trade ledger
and [Championship bracket sidecar](championships.md). It uses their existing
authenticated actor/lease, full startup integrity checks and ordinary Players
menu/Tk rendering. There is no new persistence system, migration, imported
implementation, asset or dependency. The [reuse audit](customization-and-reuse.md)
already distinguishes native NPC contacts and Pokémon friendship from player
relationships; its research pins and licensing limits remain applicable.

Records do not grant friendship experience, levels, Lucky status, rewards or
Shiny Charm effects. Those balance and provenance decisions remain pending.
This displays actual already-recorded activity without treating participation
counts as an anti-spam or meaningful-friendship scoring policy.

## New records

`player_card.py` supplies an explicitly requested version 2 card. Version 1
retains its existing schema. `battle_protocol.py` requires the returned card,
outer version and requested version to agree. `read_player_card` tries v2 and
falls back to v1 only after a correlated older-host refusal, while retaining
the same world/server/player lease. Timeouts and malformed success replies do
not authorize a fallback or mutate anything.

- Championship entries require all four players' acceptance. A later canceled
  bracket remains an entry. Completed counts require a finished final, and wins
  require that trainer to be the final champion. Proposals and declined brackets
  do not count. `championship.py:statistics` derives these facts from validated
  bracket rows, independently of the four-record public history page.
- A connected peer's card shows only **your shared records**: committed trades
  between this exact pair and completed battles as teammates or opponents.
  Battle wins/losses/draws are from the viewing player's perspective. A 2v2
  teammate is selected by roster side, not current team membership.
- `battle_results.py` builds pair projections from all validated immutable
  results before the listener opens, updates only after committed publication,
  and never counts a repeated battle ID twice. Interrupted battles have no
  released result and contribute nothing. The shared cache is invalidated with
  the existing statistics cache on uncertain publication.
- `TradeCheckpointStore.trade_statistics` optionally filters both participant
  columns to the canonical pair. It counts committed transactions once, never
  proposals or recovery retries. Only the committed count appears on peer cards;
  the peer's own checkpoint, hunts, other trades and recovery state stay private.

No result/opponent/score can be submitted through this interface. The server
authenticates the current caller and requires the selected peer to remain
connected. Closed source archives do not make an offline player target readable.

## Displays and remaining evidence

`player_menu.py` separates format records, Championship totals and shared records
into bounded pages, retaining native six-row limits and immutable action/session
guards. The launcher `PlayerPanel` displays the user's Championship totals with
the existing explicit Refresh worker; the dedicated Championship panel owns
bracket management. Native peer cards expose shared records.

Performance and memory cost remain UNMEASURED. Pair projections grow with pairs
that actually share archived battles; no lifetime archive is replayed on each
card refresh. Cards are snapshots: refresh for new results. Future verification
must cover both 2v2 roster sides, draws, duplicate publication, cache recovery,
version fallback, privacy, session changes, bracket cancellation and all UI pages.
No previous tests or actual-core proofs qualify these new source changes.
