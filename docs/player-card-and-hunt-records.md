# Multiplayer Trainer Card and personal hunt records

October 8 implementation batch: source only, **not built or tested**, following
the owner's instruction to pause testing. This supplements the existing native
Trainer Card rather than rewriting the character's game statistics.

The October 9 [version 2 extension](trainer-card-shared-records.md) adds
Championship totals and viewer/peer shared battle/trade records, with matching
game pages and launcher totals. Version 1 remains available. This extension is
also source-only and does not inherit earlier runtime acceptance.

## Reuse decision before implementation

The pinned RHH `bb1093a7c72d3961d9a37d8e02ad2abc2c866682`
[`trainer_card.c`](https://github.com/rh-hideout/pokeemerald-expansion/blob/bb1093a7c72d3961d9a37d8e02ad2abc2c866682/src/trainer_card.c)
and inspected maintained revision
[`7b95be15d84a053948791ce91e5dec0b168947a5`](https://github.com/rh-hideout/pokeemerald-expansion/blob/7b95be15d84a053948791ce91e5dec0b168947a5/src/trainer_card.c)
already display local Link battle/trade counters. Those values cannot establish
that our host atomically committed a trade or released every battle participant.
Reuse our immutable `battle_results.py`, schema-3 `trade_transactions`,
`reset_attempts.py`, authenticated lease, native Players menu and bundled Tk
widgets. No new external code, library, asset or schema is imported. The
[existing community comparison](customization-and-reuse.md) found no compatible
replacement for the canonical host journals. The standard
[Tk Treeview](https://docs.python.org/3/library/tkinter.ttk.html#treeview) supplies
the launcher presentation. Existing dependency terms and attribution remain.

## Data and integration contract

The read-only extension to `battle_history` requests `player_card_version=1`
and a specific `card_player` UUID. Older hosts reject the extra fields through
their existing recoverable `battle_error` path; there is no new handshake or ROM
ABI, and ordinary history requests retain their original response shape. Only
the authenticated actor or another currently connected player can be selected.
Public peer cards expose battle records only. Your own card additionally shows
canonical checkpoint/party/storage counts, committed trades and personal hunts.
Neither save bytes, private roster credentials, RNG nor encounter properties
travel in the card. The read cannot admit an encounter, grant a reward, update
ownership or release a held battle.

Battle counters stream every archived, fully released result in sequence order;
the eight-row recent-history limit does not truncate lifetime records. Separate
1v1/2v2 and total wins, losses, draws and current/best win streaks are derived.
A draw ends a consecutive win streak. Interrupted or canceled challenges are
absent from the completed archive and do not enter these statistics. Coverage is
explicitly this world's recorded history, not earlier unarchived play.

Hunts are admitted attempts, including an attempt whose ACK was lost, not a
claim that every attempt reached a visible encounter. Counts come from the
durable host ledger. Full receipt replay runs at store boot; card reads check
per-source count/max continuity and the last receipt. Zero means no admission
recorded for a catalogue entry; a missing optional
ledger is displayed as unavailable. No shiny count or successful-shiny attempt
is invented. New source catalogue entries do not imply production flags enabled.

Committed trades count once per transaction even if delivery is awaiting either
player's recovery. Your pending recovery count is shown separately. Card
refresh cannot acknowledge a trade. Saved party/PC counts describe the latest
canonical checkpoint, not unsaved live changes. Both views say when they were
refreshed; they do not poll or claim that a disconnected snapshot is current.

The launcher panel and native menu use the same validated card. The UI provides
explicit refresh, recent results and source-by-source hunt counts. Two-player
team membership and up to four online players come from current authenticated
services, without asserting a friendship level or granting Lucky benefits.

## Limits

No avatar customization, achievements, tournament rewards, friendship thresholds
or balance values are inferred. No save migration or private database is run by
this source work. Battle totals are projected before the host listener opens
and incremented only after committed results. A failed or uncertain append
invalidates that projection until replay on retry/reopen; duplicates do not
increase it. Refresh copies the totals instead of replaying the archive. Hunt
refresh uses grouped SQL with one receipt check per source. Startup replay and
SQL scan costs grow with history; actual performance remains unmeasured. Playable
acceptance and performance remain UNKNOWN while testing is paused.
