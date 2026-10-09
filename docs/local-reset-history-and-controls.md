# Personal hunt receipts, installed-source availability and admission retry

This October 9 source batch is implemented. Fresh normal ROMs now compile the
full 25-source catalogue, and the focused release/ledger/session/bridge checks
listed in [production verification](local-reset-production-flow.md) pass.
Actual-game acceptance of the receipt browsers, controls and all authored
encounters remains UNKNOWN; compilation and fixtures do not establish it.
The implementation reuses the personal-attempt ledger, authenticated battle
history request and native reset admission/controls. It adds no dependency,
save schema, migration or gameplay odds.

## Recorded history

`src/emerald_multiplayer/reset_attempts.py::ResetAttempts.history` reads only the
authenticated actor's existing `personal_reset_attempts` rows under the current
lease. A page contains 1–20 entries, newest first, with exact attempt number,
original request UUID, checkpoint revision and native observed count. The current
head, first receipt and latest receipt within the selected snapshot are separate
fields. Every returned receipt passes the existing digest/identity validation;
the expected contiguous numbers are read explicitly so a missing row is an error.
Startup already validates the complete ledger. No per-page writes are performed.

`src/emerald_multiplayer/reset_history.py` provides:

- `default_reset_history_request(encounter_id, limit=10)` selects the current head.
- `read_reset_history(companion, request)` returns a validated history extension
  over `battle_challenge_rpc("history", reset_history=request)` and rejects a
  changed world/server epoch/lease after awaiting the response.
- The next request retains `through_attempt` and sets `before_attempt` to
  `next_before`. The boundary is exclusive; newly admitted attempts cannot move
  or duplicate the retained page. Refresh starts a new snapshot.
- An explicit older-host `invalid_fields` response becomes
  `ResetHistoryUnsupported`. Timeout, corruption, absent ledger and authentication
  failures remain their actual errors, not an empty or unsupported history.

The request fields are `version=1`, `encounter_id`, `through_attempt` (initially
null), `before_attempt` (initially null), and `limit`. The response scope is
`personal-static-attempt-history-v1`; fields are `encounter_id`, `through_attempt`,
`current_attempt`, `before_attempt`, `limit`, `next_before`, `first`, `latest`,
and `entries`. Each receipt has `attempt`, `request_id`, `checkpoint_revision`
and `observed_count`. Empty history has head zero, null first/latest and no rows.

These are **pre-generation admitted attempts**. The stored revision is the
checkpoint current when admission committed, not a save of the encounter's
outcome. `observed_count` is the native request's existing mirror, not a second
attempt total. No timestamp, shiny sighting, generated PID, capture, success rate
or best hunt is recorded. All those outcomes remain UNKNOWN. An admission can
remain counted even when host loss prevents generation; retries never erase it.

## Exact installed catalogue

The additive native descriptor `gMultiplayerResetCatalogue` in
`src/multiplayer_static_reset.c` is six little-endian words: version 1, first ID
`0x1001`, count 25, enabled-source bitmask, control flags and build flags (bit 0
development encounter, bit 1 TESTING; no other bits).
The last ID is `0x1019`. A volatile read in the already-used cache initialization
retains the immutable descriptor even in a disabled build. It allocates no new
runtime state and does not alter the source guards. The subsequent
[production profile](local-reset-production-flow.md) enables the 25 existing
adapters by default while retaining explicit isolation overrides.

Static-enabled or TESTING builds advertise all 25 source bits; pilot-only builds
advertise Voltorb 1; other builds advertise zero personal-source bits. Development
only does not advertise the development encounter as a production hunt. Control
flags 3 describe the SELECT and traditional chord paths when the existing
`MP_LOCAL_RESET_ENABLED` condition compiles them; otherwise flags are zero.

`scripts/multiplayer/generate_manifest.py` extracts the compiler-located 24-byte
descriptor. `reset_catalogue.validate_reset_catalogue`, called through the
existing ROM manifest validator, checks exact bytes, version, source bounds,
mask, control/build marker consistency, alignment and ROM bounds. The normal
Companion configuration verifies the whole ROM hash before deriving these values.
Manifest fields are `reset_catalogue_version`, `reset_catalogue_address`,
`reset_source_mask`, `reset_control_flags` and `reset_build_flags`. No Lua packet
or RAM command is added.

`reset_source_catalogue(config)` supplies ordered human names and per-source
`availability` (`enabled`, `disabled`, `unknown`). Older manifests lacking the
descriptor are UNKNOWN, even when their application knows all 25 source names.
`eligibility` is always UNKNOWN here: compiled support does not prove tickets,
progression, a present object, unlocked maps, or the current first-action window.

## Controls and a stalled admission

`reset_controls(config)` describes the existing native controls: interact
normally; at the first battle action menu press SELECT or hold
A+B+START+SELECT; release all four chord buttons afterward. Confirmation starts
on No. Up chooses Yes, A confirms, and B cancels. Selecting an action/submenu
closes the window. World Events, random wild encounters and completed captures
remain excluded. A separate older input ABI marker can prove these controls
without proving source availability; missing evidence is UNKNOWN.

`reset_session.reset_status(companion)` observes the current retained request.
It reports source/name, request UUID, observed count, separate host/native attempt
receipts, native field-ready observation, retry availability and bounded error
code. It does not poll or mutate the game. States are `unavailable`, `idle`,
`queued`, `requesting`, `awaiting_native`, `retry_wait`, `blocked`,
`generation_released`, `denied`, `cancelled`, and `retained`. A released admission
is not a verified generated encounter or successful capture.

`retry_reset_admission(companion)` replays only the existing request UUID and
exact original world/server epoch/lease/bridge incarnation. It requires ABI2's
affirmative native WAITING receipt, a finished admission task and no overlapping
save/trade/battle owner. Under the existing checkpoint lock it rechecks authority,
then uses the existing three bounded RPC attempts. The host returns the original
count if an earlier reply was lost. The retry cannot allocate a new native request,
undo generation, reconnect a different core, lower a counter or issue reset by
itself. UI cancellation does not cancel an already-started admission owner.

An authoritative denial stays denied. An unknown host outcome stays stopped.
The existing emergency drain remains responsible for disconnected pre-generation
neutral return and refuses to undo ABI2 state 2. Attempt identity is retained in
this live session only; reconstructing an admission after whole-application or
core loss is not supplied by this retry feature.

## Preservation and future verification

Pre-edit source copies are in the private
`PokemonPrivate/reset-foundation-source-before-20261009-1` directory. The native
delta is `engine-patches/phase6-reset-catalogue.patch`; it layers on the existing
25-source adapters without replacing their patches or prior candidates.

When testing is authorized again, the meaningful gates are authenticated
cross-player refusal, pagination while a new attempt arrives, exact lost-reply
retry and duplicate count, original-native WAITING versus terminal receipts,
save/trade/battle ownership conflicts, host-loss drain composition, and catalogue
truth in disabled/pilot/static configurations. Native controls and source-specific
returns still require actual-core acceptance; source review is not that evidence.
