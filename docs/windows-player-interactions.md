# Launcher player cards, teams and records browsers

Status: implemented in source, **UNTESTED**. No project import, test, build,
launcher window or emulator was run for this batch. It does not update any
accepted package, runtime, private world or save.

## Connected peer cards and shared records

The Trainer Card & Players tab now has a selectable connected-player list.
View selected Trainer Card requests that exact player's card through the
existing authenticated `read_player_card` helper. My card returns to the
caller's own record. Refresh rereads the selected card and current team state;
there is no background card/team polling.

Peer cards display public PvP/streak and Championship counters. The Shared tab
shows only the authenticated viewer/selected-peer pair: battle counts together
as teammates or opponents, wins/losses/draws from the viewer's perspective, and
their committed trade count. These are recorded activity, not friendship XP,
Lucky eligibility or rewards.

The existing strict version-2 response validation and explicit unsupported-only
version-1 fallback are reused. Version-1 cards leave shared/Championship data
unavailable rather than inventing zero counters. Peer cards have no personal
checkpoint, saved-party, trade-recovery or hunt payload. The UI clears those
private sections when switching from the caller's own card to a peer. A peer
that disappears during the request is reported unavailable. Card support is
separate from existing team support: an older host's explicit card refusal
does not disable a valid team-status response.

## Explicit team management

Players & team shows up to four connected players, up to two formed teams and
the caller's single pending invitation. Invite selected Trainer records only
the sender's invitation. The recipient must explicitly Accept or Decline;
the sender can Cancel. A current member can explicitly Leave before selecting
another partner. These controls call existing `Companion.team_rpc` and
`TeamDesk` methods; the launcher does not invent a team, accept for a peer or
change team rules.

The UI states the existing scope: teams are session-local, dissolve if either
original authenticated lease disconnects/changes, and do not survive host
restart. Separate parties, money, items and progression remain separate. A
displayed expiry is the remaining time in the fetched snapshot, not a running
countdown or automatic acceptance. Trades and native battle consent/Enter
remain in the ordinary in-game Players flow.

`PlayerPanelController` owns the selected target and retained action parameters
on the existing session loop. Tk receives opaque one-use action tokens tied to
an exact snapshot, Companion, authenticated session signature, live game object
and bridge/incarnation. All displayed actions are consumed before an await.
Targets and names come from the retained roster; invitation/team IDs and
generations come from the validated host snapshot. Before a team mutation,
the controller fetches current status and compares membership and invitation
identity with the displayed status, excluding decreasing expiry seconds.
Changed membership, generation, session or core requires a fresh review.

Team mutations require the same ordinary live lifecycle as Championship
choices: no save in progress, trade/battle interaction, original admission
preparation, recovery or host restart owner. This is an eligibility guard,
not a new native hold or an automatic-save policy. Existing host checks remain
authoritative if state changes while the request is in flight.

The existing worker now captures the exact session when a request is queued,
serializes these operations against manual save/settings/recovery/restart,
Championship and other player requests, and drains its task before session
closure. A thirty-second outer bound accommodates status, mutation, optional
card-version fallback and refreshed team status; individual RPC bounds remain
unchanged. Closing suspends new choices. Lost replies invalidate actions and
require explicit Refresh; no mutation is automatically retried. A confirmed
mutation followed by a failed snapshot is reported as acknowledged but needing
refresh, not as an uncommitted operation.

## Own recent battle browser

My battles filters the existing latest-eight released-result window by 1v1/2v2
and the caller's win/loss/draw. Selecting a result shows both sides, the caller's
outcome and each accepted checkpoint's party count. Current roster names are
used when available; offline participants receive positional labels because
the result archive has no historical names. No timestamps are fabricated.

The history extension belongs to the authenticated caller even when the
selected card is a peer's. The UI labels it My battles and never presents a
peer's private history as fetched. Filtering and details make no RPC and grant
no replay, reward or recovery authority. An empty filter covers only this
bounded recent window, not the lifetime archive. An unavailable history
response is labeled unavailable rather than a verified zero-result history.

## Own personal hunt browser

My hunts reuses the existing own-card admitted counters and the shared pure
`record_views.py` presentation helpers. It provides source-name search,
all/started/no-attempt filters, source/most-attempts/name sorting, total admitted
attempts, and the number of catalogue sources with attempts. A selected source
shows its full name, count and counting scope.

The detail explicitly states that counts do not change odds, catalogue presence
does not establish that the installed build enables an encounter, and capture
or shiny outcomes are not recorded in this ledger. No new hunt API, per-attempt
history, species roll, capture result, probability, counter or game action is
created. Selecting a peer clears the personal hunt data; My card retrieves the
caller's own counters again.

## Reuse, provenance and limits

This extends the existing PlayerPanel/SessionWorker and reuses the project's
strict Trainer Card, team and result APIs. The native/team reuse audit is
retained in `team_desk.py`; the broader pinned-engine investigation is in
[customization and reuse](customization-and-reuse.md). Shared record semantics
remain documented in [Trainer Card shared records](trainer-card-shared-records.md).
No external component, dependency, schema, native ABI or save layout was added.

Owned files are `launcher_player_panel.py`, narrow player-action wiring in
`launcher_gui.py` and `launcher_session.py`, and this document. The concurrent
cold admission-HANDOFF publication in `LauncherSession._ready` belongs to the
separate recovery slice and is preserved. `record_views.py` is the shared pure
presentation module owned by the native records slice.

Exact pre-edit copies and SHA-256 receipt `originals.json` are preserved in
`%LOCALAPPDATA%/PokemonPrivate/artifacts/launcher-player-interactions-source-before-1`.
Original hashes:

- Player panel: `056899aeb61e3b97aca79d1a251083c56b2727353b3b16b35ff5537117edfd05`
- Launcher GUI: `12f31ff28d8cc2e0722502a5e5a02366a208e5d7a3b4befbf2143692be69a615`
- Launcher session: `6bcb6d03285ca245442b3d1c3d1ae198c5345298c81d25b0d9981543092f58d1`

Actual widget sizing/accessibility, connected peer changes, team expiration and
lost-reply behavior, old-host responses, filters/detail navigation, closure
races and multiplayer gameplay remain **UNVERIFIED**. Source review does not
qualify this as a tested Windows release.
