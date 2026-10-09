# Windows launcher Championship panel

Status: implemented in source, **UNTESTED**. No test, project import, build,
launcher window or emulator was run for this change. Existing private packages,
runtime bundles, worlds and saves are unchanged.

## Connected workflow

The launcher has a separate Championship tab alongside Host, Join and Trainer
Card. It uses the current `LauncherSession` and the existing authenticated
`battle_pending` Championship extension. It does not start another connection,
create a replacement character or supply a battle result.

An explicit Refresh reads the current bracket and the player's latest four
completed or canceled brackets. There is no background Championship polling.
The tab presents four participants, their individual acceptance and cancel
votes, the three matches, recorded attempts and winners. Selecting a match or
history row shows full Trainer names in a wrapping detail area. A vertical
scrollbar keeps these bounded sections reachable in the existing launcher.

When exactly four Trainers are connected, Review new four-Trainer bracket
creates a local preview. The proposing Trainer is the first seed; the remaining
three use the existing stable player-ID ordering. Both semifinal pairings are
shown before Create and accept these pairings sends anything. Create records
the proposer's consent; each other Trainer must explicitly accept the same
host-issued bracket. Discard preview sends no host request.

Proposed brackets can be explicitly canceled. Active brackets expose Vote to
cancel or Withdraw your cancel vote, according to the host snapshot. The host
requires all four votes and safe terminal matches before confirming whole
bracket cancellation. No button press is displayed as successful before its
validated reply. Outstanding cancellation votes suppress match proposals.

Only an assigned participant can propose an eligible semifinal, final or fresh
rematch. This calls the ordinary host invitation path, including Companion's
original-core consent identity where the build requires it. The panel directs
the players to **Players → Challenges in the game** for normal battle acceptance
and Enter. It never accepts the other player's invitation, presses Enter,
acquires a native battle owner, launches a match or substitutes a new core.
Draws require a fresh explicit proposal and mutual battle consent. No fees,
prizes, friendship progress, automatic forfeits or client-supplied winners are
added.

## Session and action ownership

`launcher_championship_panel.py` separates a session-loop controller from its
Tk presentation. The controller retains each displayed action's parameters
privately. Tk receives only public display data, a snapshot token and opaque
action tokens. The controller binds those tokens to the exact Companion,
authenticated session signature, live game object and bridge. It consumes the
entire action set before checking mutable state or awaiting a request. Stale
tokens, repeated clicks, a changed session or a changed core cannot replay the
displayed action.

Mutation parameters come from the retained validated bracket or reviewed
preview: exact championship ID, generation, fingerprint, round and observed
attempt. A create choice rechecks the four current IDs and displayed names.
Companion and the strict Championship reply validator correlate the actual
authenticated reply; UI fields do not provide authority.

`LauncherSession.can_manage_championship` requires the ordinary live saving
lifecycle, no current trade/battle interaction, no save in progress, no original
battle-menu preparation and no recovery or host restart owner. This is an
eligibility check when the action is consumed, not a new lock on automatic
saving or a change to existing native lifecycle ownership. Host and Companion
checks remain authoritative if state changes during the request.

`SessionWorker` schedules one Championship operation on its existing asyncio
loop, with a twelve-second outer deadline in addition to the normal RPC bound.
It excludes concurrent launcher save, settings, recovery, host restart and
Trainer Card requests. Closing suspends new tab actions; the worker drains its
retained task before leaving the session context. Recovery messages in the
main launcher are not replaced by the tab's separate status text.

Connection loss or an uncertain mutation reply invalidates all actions and
labels any displayed data as an earlier snapshot. The user must explicitly
Refresh and review the host's current record before choosing again. There is
no automatic mutation retry. Unsupported older-host responses get a fixed,
readable message; exception text, credentials, save paths and raw private
records are not put into the panel event.

## Reuse and source provenance

This adapts the existing `PlayerPanel`/`SessionWorker` threading pattern and
the project's Championship protocol, Companion, BattleDesk and native Players
flow. The earlier engine/community reuse investigation and backend limits are
recorded in [Championships](championships.md) and
[Championship recovery](championship-recovery.md). No dependency or borrowed
code was added; no native ABI, database schema or save format was changed.

Owned source changes are:

- `src/emerald_multiplayer/launcher_championship_panel.py`: retained controller
  and Tk presentation.
- `src/emerald_multiplayer/launcher_gui.py`: worker action/event lifecycle and
  tab placement.
- `src/emerald_multiplayer/launcher_session.py`: per-session controller and
  lifecycle availability projection.

Exact pre-edit copies and their SHA-256 receipt are preserved privately in
`%LOCALAPPDATA%/PokemonPrivate/artifacts/launcher-championship-source-before-1`.
`originals.json` records the original repository-relative paths and digests.
The original GUI digest is
`9042599a8d26ac3fa853d137c6f4b5cc2ac8292b9bf33a6bf54f68f0b5523b59`;
the original session digest is
`992708326a3bde88db91b8350ce54095d2c6593b62ab7dab484f8694b9624e2a`.

## Remaining limits

Widget layout, keyboard/accessibility behavior, request cancellation races,
older-host fallback, real four-person consent and a full native Championship
through this launcher tab remain **UNVERIFIED**. This source is not included in
an accepted Windows package by this change.

The panel intentionally inherits the backend's unresolved evidence boundary:
an issued-but-unknown match, or a bare volatile abort without terminal release
evidence, can remain waiting. Refresh, vote withdrawal and ordinary recovery
do not turn missing evidence into permission for another match. The tab adds
no way to clear a held core or force that bracket forward.
