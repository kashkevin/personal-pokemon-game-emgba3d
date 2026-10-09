# Production Local Soft Reset flow

The October 9 implementation direction enables the existing authored personal
encounter adapters for the production game. Source is complete for this bounded
25-source flow. Fresh normal ROM builds now compile it with development content
off and all 25 catalogue bits verified; focused Python checks described below
also pass. Ordinary-route gameplay for the complete catalogue remains UNKNOWN.
No whole-application crash reconstruction or shiny/capture outcome history is
inferred from these checks.

## Verification update

The current normal candidate is ROM SHA-256
`f99bfa4e19ccb5ba998b54d2151986665c15bed3b2d28dab10340d59be3a1d65`,
manifest `f97dffa70c4edf93de4f90202f8fe08a5a3a499cb2113574c73881321b4bb7e1`.
It was built with `DEV=0 LOCAL_RESET_STATIC=1`; the full catalogue descriptor was
verified. See [candidate build evidence](remote-running-animation.md).

Five `test_reset_production_catalogue.py` checks pass for the production release
gate, exact descriptor/ROM binding, disabled/pilot/development rejection, missing
catalogue UNKNOWN behavior and explicit disposable-ledger migration. Another 31
checks pass across `test_reset_manifest.py`, `test_reset_attempts.py`,
`test_reset_session.py`, `test_reset_bridge.py` and
`test_reset_emergency_integration.py` (8.118 seconds). These cover codecs, receipts,
session/bridge boundaries and composed recovery fixtures. They do not prove that
all 25 encounters are reachable and reset correctly in the actual game.
Private logs are retained under
`%LOCALAPPDATA%/PokemonPrivate/public-effect-client-source-before-20261009-1/`
(`launcher-reset-new-final.log`, `reset-existing-1.log`).

## What closed the implementation gaps

The native Makefile and fallback `include/config/multiplayer_local_reset.h` now
default `LOCAL_RESET_STATIC`/`MP_LOCAL_RESET_STATIC` to 1. Development content stays
off. Explicit `LOCAL_RESET_STATIC=0` remains usable for a disabled build; the
single-source pilot uses `LOCAL_RESET_STATIC=0 LOCAL_RESET_NEW_MAUVILLE_PILOT=1`.
The pilot Make option is now wired explicitly and defaults to zero. No capture,
first-action, ticket, source object, progression, ownership, connection or native
safe-return guard is relaxed. No RNG seed, attempt odds or shiny modifier changes.

The immutable catalogue's build-flags word proves whether development/TESTING
content was compiled. `reset_catalogue.require_production_reset_manifest` requires
all 25 source bits, both controls, a normal build, reset ABI2, emergency ABI2 and
native battle execution support. The production packaging caller uses this
requirement after normal verified ROM/manifest checks. A missing catalogue or
older/partial ROM remains usable through its existing compatibility paths, but
cannot silently pass as the new complete production reset profile.

`HostWorld.create` already creates the attempt ledger, with a verified backup,
after battle reservations and before publishing the new host descriptor. It does
so while the new world has no player leases. No new migration is needed.
`reset_attempts.require_reset_ledger` supplies the host-start preflight for an
enabled catalogue: an existing world without the ledger is refused with
`reset_migration_required`. It never migrates an active world or guesses missing
historical attempts. Such a world needs an explicit offline backed-up upgrade.

## Player path

1. Create a world through Host Game and enroll your own character, or join the
   host with the matching build. The canonical attempt ledger belongs to that
   authenticated character, separately from the other players.
2. Reach a listed source through its ordinary progression. These hooks do not
   grant tickets, unlock caves, solve puzzles, alter roamers or spawn extra events.
3. Interact normally. The native authored script stops before generation and
   obtains the host's durable attempt number through its exact session and source.
   It resumes generation only after the matched acknowledgement.
4. At the first action window, read the acknowledged attempt number and press
   SELECT (or A+B+START+SELECT). Confirmation starts on No; Up chooses Yes, A
   confirms and B cancels. A selected battle action/submenu closes the reset
   window even if that submenu is later cancelled.
5. Confirming resets only the eligible personal encounter and performs its own
   neutral return. Interacting again requests the next attempt. Catching or
   completing the ordinary encounter follows its original completion branches;
   the reset path cannot recover it afterward.
6. The launcher Local Reset panel shows exact compiled availability, control
   help, retained admission state and a one-use Retry pending admission action.
   Retry is available only for the original still-connected WAITING request and
   reuses its existing UUID. The native and launcher record browsers display
   personal receipt history with stable pagination and original checkpoint facts.
7. Host loss follows the existing emergency preservation path. A pre-generation
   request can return neutrally only after an exact disconnected cancellation and
   safe-field observation. Already released generation is never undone. The
   attempt remains durably counted if admission committed before the loss.

Sources are the three New Mauville Voltorb, two Aqua Hideout Electrode, Registeel,
Regirock, Regice, Rayquaza, Sudowoodo, Kyogre, Groudon, seven Devon Scope Kecleon,
Lugia, Ho-Oh, Mew, Deoxys, and the Southern Island Latios/Latias branches. The two
Southern Island entries describe the ordinary exclusive story branches, not
permission to obtain both. World Events and random encounters are excluded.

## Evidence and remaining acceptance

The admitted-attempt history, availability and retry contracts are documented in
[history and controls](local-reset-history-and-controls.md). The source-specific
returns remain documented in the production catalogue, expanded-sources and
ticket-sources documents. They preserve their prior snapshots and evidence.

Pre-edit copies for this continuation are private under
`PokemonPrivate/reset-production-source-before-20261009-1`. The additive
`engine-patches/phase6-production-reset-profile.patch` applies after
`phase6-reset-catalogue.patch`; all prior source patches remain intact.

The original source-only continuation performed no tests or builds. Testing was
subsequently authorized; the build and focused verification above supersede that
earlier status. All 25 ordinary-route interactions, captures, source-specific
returns, simultaneous four-player independence and actual disconnect preservation
still require gameplay acceptance. Original private worlds and saves were not
modified by the disposable fixture checks.
