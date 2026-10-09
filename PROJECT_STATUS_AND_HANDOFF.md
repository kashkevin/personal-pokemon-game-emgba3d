# Project status and handoff

Initial audit: October 8, 2026; updated October 9 (America/New_York). Initial application HEAD: `31e5bf93ec8fb24e7cf522908b540b318890d365`, branch `codex/multiplayer-delivery`. New work below remains uncommitted.

The owner clarified this request to **audit first, then implement the unfinished tasks**. This supersedes the earlier stop-after-audit instruction. No dependency installation, branch reset, commit, original-save mutation, replacement of accepted builds, or distribution is authorized by this report. Implementation and verification performed after the initial audit are recorded separately below.

## Executive assessment

This is a substantial working multiplayer foundation, not a completed friend-ready game. Actual mGBA-core proofs exist for ownership, simple paired trades, native trade menus, independent four-client play, full-six-per-trainer 2v2, a separate 1v1, a development Local Reset encounter, and Windows timed saving. These are **different frozen builds and different proof scopes**; they do not add up to a single accepted release. At takeover the README predated newer evidence and understated several implemented features; it has now been reconciled. [Trade menu](docs/native-trade-menu-delivery.md), [battle execution](docs/native-battle-execution.md), [Windows qualification](docs/windows-launcher-gui.md), [lifecycle regression](docs/lifecycle-validation.md).

The last confirmed milestone **at takeover** was **`NATIVE_BATTLE_ENTRY_HOLD_POC` at `d976ed6`**: two real cores proved the early Enter-battle/host-loss boundary, peer emergency preservation, frozen original input/state, offline admission and atomic menu closure. It intentionally ends before complete battle resumption. [Proof and exact hashes](docs/native-battle-resume-proof.md#native-entry-run-2--qualified-admission-boundary). New uncommitted results are recorded in [post-audit implementation and verification](#post-audit-implementation-and-verification), with an explicit [six-task completion matrix](#the-six-requested-delivery-tasks).

The last unfinished task **when the previous Codex chat stopped** was four-original-core battle recovery. The last prior chat and private `native-resume-all-run-2` evidence agree: all four froze on host loss; three reconnected players waited for the fourth; the fourth reconnect failed client validation of a valid provisional BIND. The run closed its disposable cores and preserved source saves. Complete resumed gameplay was **not** proved. The precise mismatch is described under Broken systems.

### Current continuation: complete trade integration and staged visuals

The latest [visual/world amendment](docs/project-update-maximum-visuals-visible-wild-riding-time.txt)
explicitly requires testing major additions and actual visual checks. It
supersedes the earlier testing pause. It adds visible ordinary encounters,
shared-entity ownership design, synchronized followers/ground mounts and time,
Gen6 time mechanics and a staged ambitious fake-2.5D direction. It retains the
Emerald engine and foundational multiplayer priority. The [specification](docs/master-spec.md)
and [roadmap](docs/development-roadmap.md) now preserve those requirements.

| Current classification | Evidence and practical scope |
| --- | --- |
| **Completed and verified, bounded stage:** dedicated remote running | Two actual mGBA cores, ordinary controls, four directions; observer native running frames 20–23, visible actors, matching settled tile/pixel positions, unchanged parties/saves. Reuses existing art. 31 Python checks and real Lua regression also passed. [Exact build, captures, hashes and limits](docs/remote-running-animation.md). Brendan/one map/two WSL cores only; not the complete animation overhaul. |
| **Implemented with focused and scoped gameplay verification:** public recipient trade effects | New actual Windows `wqte4` passed ordinary Players menus, eligible Torchic/Wurmple offers, mutual consent, explicit candidate review, real native-worker replay, atomic two-save/history commit, canonical apply/ACK/release, both Received notices, manual revision4 saves and exact fresh Continue. Original processes/identities preserved; all four play windows closed normally. [Exact proof and pins](docs/windows-menu-trade-effects-proof.md). This non-evolving pair had no pending move decisions; live evolution/move-learning, interruption and packaged gameplay remain unqualified. The backend (46), storage/history (64), client (41), terminal (4) and later category (19) focused checks retain their fixture scope. [Backend](docs/public-native-trade-effects.md), [client](docs/public-native-trade-client.md). |
| **Completed and verified, native computation boundary:** Windows trade replay | Actual-ROM Machoke→Machamp computation; paired full-save effect replay, production atomic publication and restart replay in disposable fixture databases. Repeated successfully with the complete candidate8/9 runtime and final visual ROM, closing the new-binary integration gap. Identity, OT and existing damage preserved; all 269 indexed inputs unchanged. Windows worker ABI/Unicode/refusal checks also pass. [Exact pins and limitations](docs/native-trade-replay-worker.md). Synthetic Pokémon/save fixtures; live menu evolution and move-choice gameplay remain UNKNOWN. |
| **Implemented, production encounter gameplay unverified:** Local Soft Reset | Production DEV=0 build now enables all 25 descriptors; exact manifest/ROM release gate, persistent ledger prerequisite and catalogue/recovery logic added. Existing31 reset tests plus5 new catalogue/ledger checks passed. [Production configuration](docs/local-reset-production-flow.md), [controls/history](docs/local-reset-history-and-controls.md). Enabling a descriptor does not prove every encounter, puzzle, ticket or reset path. |
| **Implemented, bounded installation checks passed:** import and packaging | Owner's read-only English USA revision0 ZIP produced a reconstructing BPS. [Private candidate9](docs/windows-release-candidate-9.md) includes the status-move correction, patch and pinned runtime/worker; recursive audits, fresh packaged-resource import/idempotent retry and actual executable startup/normal closure passed. Its later [actual GUI import](docs/windows-first-run-setup.md) also passed in isolated storage. Clean-PC and combined packaged gameplay remain UNKNOWN. Packages7/8/9 and the source dump are preserved. Candidate9's 119 module comparison belongs to its recorded snapshot; newer source work is separate. |
| **Implemented with focused verification, original worlds untouched:** host setup | Explicit geography-policy selection, backed-up friendship/effect/reset feature upgrade and owned-host locking; no default policy or silent world/build repin. Missing older handler values use the approved Gen6 species bases; known values remain intact. Nine disposable SQLite/setup checks passed with synthetic manifest/runtime fixtures, including same-build preservation, backups, policy immutability and live/stale-lock refusal. No original world was migrated. [Setup and exact evidence](docs/launcher-setup.md); `tests/test_world_effect_upgrade.py`. |
| **Implemented and verified at the file/UI boundary:** friend-first setup and source approval | Separate host/friend routes, ordinary draft receipt selection, verified closed/unassigned starter export, exclusive destination publication and exact selected source hash carried through host approval before enrollment. 51 affected Windows tests and an earlier 32-test draft cohort passed; actual Tk/worker/filesystem composition included. Native New Game through friend handoff and separate-PC enrollment remain unqualified. [Flow, pins and limits](docs/windows-first-run-setup.md). |
| **Implemented and verified at the server/controller boundary:** Championship recovery | Native and Windows menu actions now recover durably proven unstarted attempts using pre-dispatch intent or exact partial-consent revocation. Stale attempts cannot cancel replacements. Ambiguous dispatches/full consent/admitted battles remain waiting; no automatic winner/rematch. 45 focused tests passed, including four authenticated TCP actors and actual SQLite restart evidence. Live native Championship acceptance remains UNKNOWN. [Recovery evidence](docs/championship-recovery.md). |
| **Implemented and verified, selected native defaults:** separate Gen6 candidate | New ruleset with ROM-bound compiled settings, unchanged species/save layout and exact host/invitation/client compatibility. All five selected actual headless-core tests passed (ORAS creation, nonempty Gen1–6 level-up lists, data, burn and paralysis); four normal-ROM native replay/database checks passed. 20 Python profile/provisioning checks passed. This does not finish roster/acquisition/affection/all Gen6 mechanics or migrate existing worlds. [Exact normal/test builds, failures and limits](docs/gen6-defaults-profile.md). |
| **Design/research, not implemented as shared gameplay:** visible wild/followers/mounts/time | [Shared spawn and clock recommendations](docs/visible-world-design.md), [resource inventory](docs/graphics-resource-inventory.md). Existing native personal OWE/follower/time code and graphics are not evidence of synchronized gameplay. No external asset pack imported, no mount speed/clock speed/shiny odds selected. |

**Most recent confirmed stage:** source-launched two-client Windows public
native-effect trade flow through both received notices, saved results and fresh
Continue (`wqte4`), on ROM
`f99bfa4e19ccb5ba998b54d2151986665c15bed3b2d28dab10340d59be3a1d65`.
Dedicated remote running also has its separate two-core proof on that ROM.
The initial native replay proof uses effects ROM
`344aca56bbdc5f98b47ed3def6fe320c5ea03046d9694af0bcedb95f50318c3f`;
the subsequent packaged-worker proof also passed on the final visual ROM above.
These are uncommitted candidate qualifications, not a new known-good release tag.

**Last unfinished task:** extend the now-qualified supported trade workflow to
genuine evolution/move decisions and interruptions, then compose it with the
existing battle/recovery and new production reset paths in the packaged Windows
candidate. The live trade proof uses its own pinned diagnostic runtime;
candidate9's packaged gameplay still needs qualification. A single
accepted combined release still does not exist. Earlier battle/four-client proof
must not be silently attributed to today's candidate.

**Five next priorities and dependencies:**

1. Extend the successful actual public trade-flow proof to native evolution/move
   choice and interruption/recovery. Native replay is executable; genuine
   evolving playable sources and final geographic
   policy remain separate evidence/owner inputs.
2. Requalify the existing playable 1v1/full-six 2v2 and host-loss/rejoin lifecycle
   against that same candidate; resolve remaining uncertain Championship issue
   cases without replacing unresolved matches.
3. Exercise all production reset families through legitimate encounter access,
   cancellation, capture, disconnect and durable attempt counts with peers active.
4. Use the new pinned candidate9 runtime, launcher, notices and reconstructing patch
   for clean Windows import/Host/Join/controls/autosave and actual separate-PC
   LAN/Internet acceptance before distributing a friends' download.
5. After foundation acceptance, implement synchronized visible entities/followers,
   the complete Gen6 profile, shared clock/time mechanics and supported ground
   mounts, then staged environment/effect upgrades within measured budgets.
   Resolve shared shiny/Charm, progression and escape ownership rules first.

**Known limitations / UNKNOWN:** the preserved baseline uses later-generation
defaults. The separate [Gen6 defaults candidate](docs/gen6-defaults-profile.md)
now changes generation-dependent settings, while explicit later-mechanic
booleans, acquisition/form eligibility, affection and other content still need
work; full Gen6 conformity is unverified. No shared clock, shared ordinary
spawn ownership, synchronized follower/mount system, final art replacement or
four-player full-visual-load budget has been delivered. The native evolution
result is distinct from a complete cinematic scene. Eggs, mail and unsupported
forms remain explicit trade exclusions. Real separate-PC/network testing and
final asset distribution permissions remain open.

The first new two-window public trade run exposed a **confirmed compatibility
blocker**: its genuine Treecko knows `(1,43,633,0)`, including Leafage (633,
introduced after Gen6). `trade_effect_witness.py:_record` deliberately refuses
post-Gen6 moves; the native menu marked that offer ineligible before consent or
exchange. Original saves and the failed run were preserved. This is evidence
that the preserved baseline's learnset profile is not fully Gen6, not permission to
erase a move or weaken the gate. The owner has been asked whether existing
later-generation moves may remain unchanged in trades; the decision is pending.
The separate eligible Torchic/Wurmple run now qualifies the supported flow.
Resolve the legacy policy and native learnset profile before
claiming unrestricted Gen1–6 trading or a finished friends' release.

A second actual Windows run used eligible genuine Torchic/Wurmple, reached
both offers and mutual confirmation, then stalled on native choice description
(opcode29). The engine's `DamageCategory` enum is NONE=0, PHYSICAL=1,
SPECIAL=2, STATUS=3; the client incorrectly rejected status3 and shifted display
labels. `trade_effect_choice.py` and `trade_effect_menu.py` now match the native
enum, retaining strict validation. Nineteen focused checks passed, including
the full opcode29 envelope and invalid-category refusal. Both failed runs are
preserved and are not acceptance evidence. The next run (`wqte3`) committed
and applied both candidates but its proof forgot to reopen Players after import;
that failure is also retained. The corrected ordinary-input proof (`wqte4`)
passed through both final notices, manual saves and fresh Continue without
another product change. [Complete evidence and limits](docs/windows-menu-trade-effects-proof.md).

**Final source preservation for this continuation:**
`%LOCALAPPDATA%/PokemonPrivate/artifacts/handoff-audit/source-implementation-20261009-022742`
contains 464 repository source files, their individual hashes, complete application
and native working diffs, statuses and base commits. `source.zip` SHA-256:
`c6e5f4c53cd1f8e1174ebe8400229cc6bc314d93f6e6363cd11f15c0c35398b7`.
The archive predates only this receipt paragraph. Original private worlds/saves,
the owner's game ZIP and accepted artifacts remain preserved; no commit or
distribution was performed. All owned qualification processes are closed.

**Historical test pause (superseded above):** “stop testing, focus on completing and adding everything.” The following source-only batch records describe the state at that time; their old off/untested statements do not override the current evidence table.

**Previous extended implementation batch (October 9, before testing resumed):**
[The workflow/evidence table](docs/large-feature-batch-20261009.md) records launcher
1v1 and current-team full-party 2v2 proposal/consent controls; full personal battle
archives and committed-trade journals in both interfaces; historical sent/received
Pokémon inspection and own-journal instance tracing; paged personal hunt receipts;
exact installed reset-source availability, retained admission status/retry; local
favorites/display preferences, text-size/help improvements and an installed-file
readiness action. The held native trade path now has exact move facts, protected
slots, explicit replacement/decline confirmation and candidate review/pause.

The owner also explicitly selected **Gen6 species base friendship for missing
legacy handler values**. The [implemented migration](docs/trade-friendship-migration.md)
adds an opt-in +800 same-database history extension, a verified-backup/backfill
operation, canonical checkpoint/paired-trade hooks and initialized-value provenance.
It preserves known values and the actual active native byte. Missing historical
trainer identity stays unknown; eggs remain outside friendship initialization.
**No private world was migrated and no save bytes were changed.**

These are **implemented but UNTESTED source workflows**. Public trade effects are
still **partial**: ordinary trading remains exact-swap; geographic adaptation,
trusted effect/history publication, recovery and full evolution presentation are
unfinished. Production reset enabling is still off. Performance, composed UI and
actual-core behavior of this batch are **UNKNOWN**; the preserved download is unchanged.

The latest unfinished source task is now connecting the approved handler-history
policy and held move presentation to complete atomic public trade effects. The
five next priorities are: that trade integration; combined battle/recovery
integration and uncertain Championship issue handling; production reset
configuration; owner-supplied import-patch inputs and final Windows packaging;
then actual four-client/separate-PC/network/controls/autosave acceptance **when
the owner resumes testing**. Details and dependencies are in the linked batch
document. There is no new completed-and-verified milestone from this source work.

Read-only source review corrected the archive's doubles-mode predicate and
missing-continuation validation. An independent review covered the new friendship
policy, store transactions and provenance. Root reviewed the remaining helper
drafts after two helpers reached usage limits. These reviews are not tests.
No builds, tests, app imports, game/UI sessions, installations or commits ran.

Final private source backup for this extended batch:
`%LOCALAPPDATA%/PokemonPrivate/artifacts/handoff-audit/source-implementation-20261009-010757`.
It contains 428 repository source files with individual hashes, full application
and native working diffs, statuses and base commits. `source.zip` SHA-256:
`bd2381ed6c2fcabf5b3f3757fcc70ecf381fa6d20243704f6a94665c0fec701e`.
The snapshot predates only this receipt paragraph; it is source preservation,
not a test or new game build. Original private saves/worlds and accepted artifacts
remain untouched.

**Previous broad continuation (October 9): 12 source-level additions.**
[The complete feature/evidence table](docs/feature-batch-20261009.md) records:
paired trade-offer details; unavailable-offer reasons; full held-native save-effect
candidate transport and interruption retry; durable canceled-entry HANDOFF delivery;
Championship rematch reconciliation from all-original proof; launcher peer cards
and team controls; launcher battle/hunt browsers; and native battle/hunt browsers.
Every addition is **implemented but untested**. Full public trade evolution is
still **partial**, reset-source enabling remains off, and the existing download
has not changed. No source inspection is being counted as gameplay verification.

The source-level last task in that earlier continuation was connecting complete native
trade candidate preparation and affirmative admission cleanup to existing
services, with player-facing browsing and controls over their actual records.
Next priorities remain evolution presentation plus atomic history publication,
unresolved issue-intent recovery, release configuration, the owner's import-patch
input and eventual combined/network acceptance. See the linked batch document
for dependencies, exact files and remaining UNKNOWNs.

The final private source backup for this 12-addition batch is
`%LOCALAPPDATA%/PokemonPrivate/artifacts/handoff-audit/source-implementation-20261009-004400`:
410 repository source files with individual hashes, complete application/native
working diffs, statuses and base commits. `source.zip` SHA-256:
`61b1931fe25d1a3905b8241679508299d8445f28f1a4cf8e2544e40bf1fba6f3`.
It predates only this receipt paragraph. This is preservation evidence, not a
test, build or playable acceptance result. Independent source reviews found no
remaining concrete blocker; all new runtime behavior remains UNVERIFIED.

**Previously confirmed milestone:** the recovery mismatch and subsequent saver/journal defects are repaired; the frozen candidate passed all three host-loss stages and fresh Continue with four actual cores using parties 2/1/1/1. Source-launched Windows native-menu **1v1 and four-client 2v2**, neutral entry cancellation and elapsed five-minute saving also passed. That earlier production snapshot passed 1,144 Python tests without skips, plus 133 focused native tests and the separate Windows input-guard cases. Private package 7 passed archive/startup checks but remains unqualified for gameplay/import. These are bounded historical results, not completion of all six tasks or verification of today's further source additions. [Recovery](docs/native-battle-resume-proof.md), [Windows 1v1](docs/windows-menu-battle-proof.md), [Windows 2v2](docs/windows-menu-multi-proof.md), [saving](docs/windows-controls-audit.md), [package](docs/windows-recovery-package-candidate.md).

### Implementation after testing was stopped

The following are **implemented but untested**, separate from the accepted artifacts:

**Latest connection and presentation batch (October 9):**

- **Launcher Championship management:** a dedicated tab now displays participants, pairings, consent/cancel votes, match attempts, winners and recent brackets. Review/Create, Accept, Cancel/Withdraw and Propose match use the existing authenticated host API with session-bound, single-use actions. Matches still enter through normal in-game Accept/Enter. `src/emerald_multiplayer/launcher_championship_panel.py`, `launcher_gui.py`, `launcher_session.py`. **Implemented but untested and unpackaged.** [Workflow, source review and limits](docs/windows-championship-panel.md).
- **Championship abort recovery:** exact durable terminal reservation evidence can now reconcile an aborted round after host restart or in-memory history eviction. A bare canceled Desk state no longer implies a cleared provisional native hold. Explicit new-match consent remains required. `battle_reservations.py:BattleReservations.terminal`, `championship.py`. **Implemented but untested; pre-invite uncertainty and unreserved entry handoff remain UNKNOWN.** [Precise evidence boundaries](docs/championship-recovery.md).
- **Extended Trainer Cards:** version 2 adds Championship entries/completions/wins plus the viewing player's shared committed trades and completed battles as teammates/opponents with a connected peer. Game pages and the launcher display the new records. Version 1 fields remain unchanged and explicit older-host refusal permits fallback. These are recorded facts, not friendship XP, levels or Lucky rewards. `player_card.py`, `battle_results.py`, `trade_storage.py`, `battle_protocol.py`, `server.py`, `player_menu.py`, `launcher_player_panel.py`. **Implemented but untested.** [Privacy, cache and counting rules](docs/trainer-card-shared-records.md).
- **Held native trade-record transport:** an optional, explicitly verified capability connects private record preparation to the existing held-save mailbox and `LiveTradeCoordinator`. The companion can begin preparation, submit explicit move decisions, resume a retained-core reply and discard private scratch using a durable transcript. Source/generation/consent binding and current ownership gates remain intact. `trade_effect_session.py`, `trade_effect_mailbox.py`, `live_trade.py`, `companion.py`, native `multiplayer_save.c/.h`, bridge/config/manifest plumbing; additive `engine-patches/phase3-held-trade-record-transport.patch`. **Implemented but untested preparation transport, not playable trade evolution.** Full saved-block transport, native presentation, atomic effect/history publication and unresolved legacy history still prevent enabling effectful offers. [Interface and remaining integration](docs/native-trade-record-transport.md).
- **Named Pokémon in trade menus:** party choices and offer confirmation now show species names, with a visible disabled marker for ineligible choices. A reproducible text-only generator extracted all 721 standard labels from pinned engine source and retained input/output hashes. `species_labels.py`, `trade_menu.py`, `scripts/multiplayer/generate_species_labels.py`, `docs/species-labels-provenance.json`. **Source data generated; menu behavior untested.** This changes presentation only. [Provenance and scope](docs/species-menu-labels.md).

No tests, builds, application imports, emulator/game/UI sessions, installations,
commits, or private save/world mutations ran in this batch. The source-label
generator did execute as a source-data tool, reading text and Git lineage without
running game code. Independent source reviews found no concrete blocker in their
reviewed scopes; they do not establish runtime correctness. New performance and
playable acceptance remain **UNKNOWN**. The previously confirmed milestones and
private package 7 are unchanged.

This batch is preserved at
`%LOCALAPPDATA%/PokemonPrivate/artifacts/handoff-audit/source-implementation-20261009-002327`:
396 repository source files, individual hashes, full application/native working
diffs, statuses and base commits. `source.zip` SHA-256:
`a810852e4fee62890cc0570dc52fedd72be33beb25277129b5d3154447e45a56`.
The snapshot predates only this receipt paragraph and is a source backup, not a
new game, executable or verification result.

**Previous feature batch (October 8–9), still unbuilt/untested:**

- **Four-player Championship:** reviewed pairings, all-four bracket consent, two semifinals and a final, normal native 1v1 challenge/Accept/Enter integration, draw rematches, cancel-vote withdrawal, and recent champion history. A world-pinned sidecar retains each issued match before invitation and advances only from immutable released battle results. The existing native recovery/ownership barriers remain authoritative. New `src/emerald_multiplayer/championship.py`, `championship_protocol.py`, `championship_menu.py`; integration in `server.py`, `battle_results.py`, `battle_protocol.py`, `companion.py`, `player_menu.py`. **Implemented but untested.** An uncertain issue intent after host restart stays waiting; no automatic replacement or forfeit is authorized. No wager/reward system or dedicated launcher Championship panel is included. [Design, reuse and limits](docs/championships.md).
- **Five additional personal legendary reset paths:** Ho-Oh, Mew, Deoxys and both Southern Island branches increase the source catalogue to **25**. Exact access, object, chase/puzzle and ordinary outcome guards preserve the original progression. `reset_protocol.py`, `bridge/mgba.lua`, native `multiplayer_static_reset.c/.h`, `faraway_island.c` and five affected map scripts. Additive `engine-patches/phase6-ticket-static-local-reset.patch`, SHA-256 `174f2f5ce39964ccb1bc266a0f8618e407ea70784b4421cc182e66bb443b071c`. **Implemented but untested; production enabling remains off.** [Source details and private preservation](docs/local-reset-ticket-sources.md).
- **Whole-save trade effects preparation:** complete paired Flash candidates now include the evolved records, received/evolved Pokédex flags, first-caught Unown/Spinda personality, encrypted trade/evolution counters and native ribbon presentation. Mandatory trusted native replay is compared with exact independent Python reconstruction, then entire output containers and ownership are validated. New `src/emerald_multiplayer/trade_effect_flash.py` plus native `MultiplayerTradeEffects_ReplaySaveBlocks`. Additive `engine-patches/phase3-trade-save-effects.patch`, SHA-256 `6f2c084c52455cca05b2c207b9730a64ffbdf52e746387cfef079cef711a5cc3`. **Implemented but untested computation; player-facing trade evolution remains partial.** The native scene/transport, atomic effect/history publication and unresolved handler-history policies remain open. [Algorithms, memory limits and remaining connections](docs/native-trade-save-effects.md).

No tests, builds, application imports, native execution, installs, commits, or
private save/world mutations occurred in this batch. Independent source reviews
covered the new components and integration; they found and corrected Championship
menu reachability, not runtime acceptance. Existing frozen milestones are
unchanged. New runtime behavior, performance and multiplayer acceptance are
**UNKNOWN**.

The final source snapshot is preserved privately at
`%LOCALAPPDATA%/PokemonPrivate/artifacts/handoff-audit/source-implementation-20261009-000522`:
384 repository source files with individual hashes, full application/native
working diffs, statuses and base commits. `source.zip` SHA-256:
`8ae0c36e5cdcb63c67df2d40bd877ea65519c879877b9768905e25208e538f26`.
It predates only this receipt paragraph. This is preservation evidence, not a
game build or a test result.

**Previous broad feature batch (October 8), also unbuilt/untested:**

- **Trainer Cards in the game and launcher:** own and connected-peer battle cards in Players; a launcher tab with completed 1v1/2v2 wins/losses/draws, current/best win streaks and recent results. Totals include the complete recorded archive and advance only after all native releases. New `src/emerald_multiplayer/player_card.py` and `launcher_player_panel.py`; integration in `battle_results.py`, `battle_protocol.py`, `server.py`, `player_menu.py`, `launcher_gui.py`. [Data/reuse/limits](docs/player-card-and-hunt-records.md).
- **Personal hunt and saved-progress displays:** canonical per-source admitted attempt counts, committed trade/recovery counts, host save revision and saved party/PC counts; current online players and team membership in the launcher. Private details are available only to their authenticated owner. Peer cards expose battle statistics only. `reset_attempts.py`, `trade_storage.py`, `player_card.py`, `launcher_player_panel.py`; no new character schema, odds or rewards.
- **Ten additional personal reset adapters:** Kyogre, Groudon, seven ordinary Devon Scope Kecleon encounters, and Lugia expand the source catalogue from ten to twenty. Existing source-specific access/progression, weather and ordinary outcomes are retained. Source flags remain default-off; these are unbuilt/untested implementations, not twenty accepted playable hunts. `src/emerald_multiplayer/reset_protocol.py`, `bridge/mgba.lua`, native `src/multiplayer_static_reset.c`, `data/scripts/kecleon.inc`, Marine/Terra Cave and Navel Rock scripts. [Exact source catalogue, patch and limits](docs/local-reset-expanded-sources.md).
- **Host/Join usability:** verified connection address/port, credential-free copyable support details, specific connection failure messages, connection/checkpoint/save availability indicators, scrollable setup tabs and controls/recovery help. Existing invitation export now identifies its recipient clearly. `network_diagnostics.py`, `launcher_gui.py`, `launcher_session.py`, `launcher_setup_gui.py`. [Implementation and limits](docs/windows-launcher-usability.md).
- **Trade evolution computation:** private native record preparation now calculates evolution, permitted held-item consumption, nickname/stat updates and explicit move replacement/decline choices, with deterministic replay and a strictly bound Python witness. This remains **partially implemented overall**: no held native scene, save-wide Dex/stat/history commit or approved legacy-friendship fallback has been enabled. `src/emerald_multiplayer/trade_effect_witness.py`, native `src/multiplayer_trade_effects.c`/header. [Implementation and remaining connection work](docs/native-trade-record-preparation.md).

The latest user instruction to build as many features as practical continues the
source implementation scope. Tests, builds, game/UI sessions, dependency installs
and commits remain paused. Source review is the only new review evidence; all
new playable behavior and runtime performance remain **UNKNOWN**. Original saves,
worlds, frozen releases and package 7 remain preserved.

This batch is preserved at
`%LOCALAPPDATA%/PokemonPrivate/artifacts/handoff-audit/source-implementation-20261008-232119`:
375 repository source files plus complete application/native diffs, statuses,
base commits and individual file hashes. `source.zip` SHA-256:
`b6f8df190ad942f79da3ba89f9017ebddb4883e7826292339cb094b7e6348740`.
The snapshot predates only this receipt paragraph and the updated next-step
wording below. It is a source backup, not a game build or verification result.

**Earlier source batch, also still unbuilt/untested:**

- **Ordinary trade preparation and Host entry:** both recipients independently reconstruct and retain exact candidates before the host atomically publishes the paired saves. Explicit application protocol negotiation, generation-specific artifacts, consent checks, renewed-lease retries and live/cold-start candidate comparison are connected. Compatible Host sessions now expose ordinary trades. Native evolution, eggs/mail and complete friendship effects remain unsupported. [Implementation and remaining native work](docs/trade-recipient-preparation.md), `trade_preparation.py`, `trade_desk.py`, `trade_protocol.py`, `live_trade.py`, `cold_start.py`, `trade_storage.py`, `launcher_session.py`.
- **18 starter choices:** six pages using the existing bag screen, previews, cries and confirmation; ordinary starter grant and first battle. The saved species is separate from the existing rival-type branch. All original source files were backed up; no species/save layout or accepted binary was replaced. [Implementation and limits](docs/eighteen-starter-selection.md), `engine-patches/phase6-eighteen-starters.patch`.
- **Own-dump patch creation:** the existing package builder can now generate the BPS from explicitly pinned owner-supplied base and target, verify reconstruction, and freeze its exact bytes/provenance. A real owner-dump path/hash is still required. [Details](docs/release-patch-creation.md), `src/emerald_multiplayer/game_patch.py`, `scripts/windows-runtime/build_launcher.py`.
- **Named setup accounts:** the setup worker verifies the selected world's actual provisioned roster through `HostWorld.open`, without booting a service, acquiring player leases or sending credentials into UI events. The character selector now offers only those named accounts and invalidates approval on world/account changes. `src/emerald_multiplayer/launcher_setup.py`, `src/emerald_multiplayer/launcher_setup_gui.py`.
- **Classic Local Soft Reset controls:** a separate verified native capability permits the full reset chord; unsupported/disconnected/default-off cases remain suppressed. Native eligibility, confirmation and durable attempt accounting stay authoritative. [Implementation and limits](docs/local-reset-classic-input.md), `engine-patches/phase6-safe-local-reset-input.patch`, `native/windows-runtime/sdl-multiplayer.h`, `bridge/mgba.lua`.
- **Sudowoodo personal reset adapter:** the tenth authored source retains its Wailmer Pail, exact object/location, flags and ordinary outcomes, adding durable admission and a neutral accepted-reset return. No catalogue flags or probabilities were changed. [Source catalogue](docs/local-reset-production-catalogue.md), `engine-patches/phase6-sudowoodo-local-reset.patch`, `src/emerald_multiplayer/reset_protocol.py`.
- **Host-service restart:** a host-only launcher action reopens the same world/service while retaining the original waiting game and companion. Each original participant must still explicitly recover. It does not reconstruct an exited game or host application. [Implementation](docs/host-service-restart.md), `src/emerald_multiplayer/launcher_session.py`, `src/emerald_multiplayer/launcher_gui.py`.

The final interrupted runs earn **no acceptance**. Windows `wqmf2` ended with a retained timeout record after native menu admission; `wqr2` reached a resumed result and first save/normal-close phase but failed during fresh Continue. WSL full-six recovery reached 3,885 routed blocks after its early/mid-battle faults, without final release/result/reload. When the stop request was processed, their exact controller/native process identities were already absent; no unrelated processes were terminated. Private `user-directed-interruption.json` notes and original outer/log evidence are preserved. Exact termination cause is **UNKNOWN**; no normal-exit inference or rerun is made.

Source reviews caught and repaired cancelled/reopened trade artifact collisions,
missing cold-start recipient comparison before restore/acknowledgment, and
prepared-trade replay using renewed rather than original consent leases. Reviews
are not runtime verification. No dependency installation, branch reset, commit,
new executable, save edit or replacement of accepted artifacts occurred during
this implementation-only continuation.

The implementation source backup is retained privately at
`%LOCALAPPDATA%/PokemonPrivate/artifacts/handoff-audit/source-implementation-20261008-225523`:
366 repository source files, the application diff/status/base and the complete
current engine diff/status/base. `source.zip` SHA-256:
`4a1065c4832b75674733b4dacdff9229bdf10ce25831912673ae457e9b2aacdf`.
This is a source archive, not a built release or test result. The archive predates
only this backup-location paragraph; its receipt records individual file hashes.

## Inspection scope and repository state

| Area | Observed structure and evidence |
| --- | --- |
| Application | `src/emerald_multiplayer/`: Python host, authenticated transport, ownership/checkpoints, trade/team/battle services, journals/recovery, launcher, import and reset accounting. `bridge/mgba.lua`: bounded emulator mailbox bridge. |
| Native integration | `engine-patches/`: source-only Emerald deltas. `native/windows-runtime/`: mGBA SDL frontend adapter. Engine/assets are primarily in a **separate WSL Git repository**, not missing from this Windows checkout. |
| Tests/tools | `tests/`: Python/Lua protocol, storage, native-fixture and lifecycle tests. `scripts/multiplayer/`: actual-core controllers and manifest tools. `scripts/baseline-headless/` and `scripts/windows-runtime/`: existing core/runtime build, packaging, inspection and qualification tools. |
| Documentation | `AGENTS.md`, root and script READMEs, `docs/master-spec.md`, `docs/development-roadmap.md`, four preserved `docs/project-*.txt` requirements, component proof/recovery reports, dependency/reuse audits. Relevant source/test paths were inspected against those reports; the upstream asset corpus has not been visually approved item by item. |
| Initial tracked state | 324 tracked files; no tracked working-tree changes, no staged changes. One existing untracked file: `scripts/multiplayer/generate_gen6_friendship.py`. Preserve it; an untracked file is not a verified feature. `git diff --check` passed. |
| Application branches | Current `codex/multiplayer-delivery`; preserved `codex/live-checkpoint`, `codex/ownership-foundation`, `codex/project-additions-roadmap`, `codex/research-foundation`. One application worktree. No branch resets or checkouts were performed. |
| Engine | Base `/home/kevin/src/pokemon/engine`, RHH `bb1093a7c72d3961d9a37d8e02ad2abc2c866682` (`expansion/1.17.1`). Twenty engine worktrees retain separate milestones/candidates, including clean delivery integration `1a7a0cd` and combined battle-resume candidate `aef47e4`. `git worktree list --porcelain` and relevant worktree status/logs were inspected. |
| Private evidence | Ignored `artifacts/`, `runtime/`, local `a.sav`, WSL `multiplayer-proof/`, and `%LOCALAPPDATA%/PokemonPrivate/`. Original source saves, databases, invitations and private binaries remain outside Git. `git ls-files '*.gba' '*.sav' '*.sqlite' '*.db'` returned no tracked matches. This is a tracked-file check, not a claim to have audited every historical blob. |
| Session handoff | Accessible prior chat **Plan multiplayer Pokémon Emerald**, ID `01a117c9-f5ec-7a23-b893-45b4258473c9`. Last turn failed with usage-limit error, rather than a deliberate completed handoff. Its final commentary and failed proof agree with the files. No messages were sent to that chat. |

Historical known-good tags remain intact: `OWNERSHIP_FOUNDATION_POC`, `LIVE_CHECKPOINT_POC`, `DURABLE_CHECKPOINT_POC`, `MULTIPLAYER_POC`, `NATIVE_SINGLES_POC`, `LOCAL_RESET_DEV_POC`, `NATIVE_MULTI_DEV_POC`, `FULL_PARTY_MULTI_RESET_DEV_POC`, `NATIVE_PLAYERS_HISTORY_POC`, `WINDOWS_SAVE_DELIVERY_BASE_POC`, and `NATIVE_BATTLE_ENTRY_HOLD_POC`. The engine also preserves `BASELINE_BUILD`. [README](README.md), [baseline](docs/baseline-build.md), Git tag/worktree inventory.

Dependencies already present include the pinned RHH engine, mGBA 0.10.5, SDL2/Lua/native runtime dependencies, CPython/Tk, cryptography/cffi/pycparser, and isolated PyInstaller build dependencies. Exact pins, hashes, licenses and attribution are recorded in [dependency-ledger.md](docs/dependency-ledger.md), [requirements-host-provisioning.txt](requirements-host-provisioning.txt), and [requirements-launcher-build.txt](scripts/windows-runtime/requirements-launcher-build.txt). Reuse references are not incorporated dependencies. The final transitive binary and game-asset distribution review remains unfinished; existing notices do not establish permission for every game asset.

The numbered audit findings in sections 1–6 describe the **takeover snapshot**. Repairs and newer passing results are recorded in [post-audit implementation and verification](#post-audit-implementation-and-verification); the roadmap in section 7 is updated to reflect them. Historical failures below are retained as evidence and do not mean that a subsequently repaired defect still fails.

## 1. Completed and verified — bounded features

“Verified” below means the specific test scope passed, not that the complete game or latest combined candidate passed.

| Feature | Evidence and limits |
| --- | --- |
| Reproducible original engine and ordinary gameplay/save baseline | `BASELINE_BUILD` at `bb1093a7`; two identical builds; actual capture, PC storage, Flash saves, fresh Continue and independent A/B saves. Native baseline suite: 5,414 passed, 18 known failures, 421 TODOs, 9 expected failures. [Build](docs/baseline-build.md), [gameplay](docs/headless-baseline.md). |
| Persistent ownership/checkpoints | Actual-core ownership run 8 passed 22 checks: capture, box movement, withdrawal, release, live recovery, fresh Continue, independent other player, backup integrity and unchanged source saves. [Ownership](docs/phase3-ownership.md), `scripts/multiplayer/ownership-evidence.json`. This accepted milestone must be preserved. |
| Independent four-client foundation | Actual four-core presence/ownership proof and capacity/rejoin checks exist. It is an older scoped build, not four-PC acceptance and not an integrated completed gameplay matrix. [Four-player foundation](docs/four-player-foundation.md), `scripts/multiplayer/four-player-evidence.json`. |
| Simple safe paired trading | Atomic paired canonical saves, offer fingerprints, explicit consent invalidation, retries and committed recovery are implemented; ordinary-input native offer/confirmation, cancellation, exchange, independent saves and fresh Continue have actual-core evidence. [Trade foundation](docs/trade-foundation.md), [native menu delivery](docs/native-trade-menu-delivery.md), `trade_storage.py`, `trade_menu.py`. Only the conservative simple-exchange capability is qualified. |
| Native teams/challenge consent UI | Four-core ordinary-input proof of team invitation/accept/leave/change, independent four-player battle consents and pre-binding cancellation. [Players menu](docs/native-players-menu.md), `player_menu.py`, `team_desk.py`. Teams are session-local and dissolve on disconnect; tournament/co-op story rules are separate. |
| Four-core full-party 2v2 | Actual production execution run 5 completed with six Pokémon per trainer, sixth-slot choices, 5,232 native blocks, agreed outcome, original party/RNG restoration, four checkpoints and four fresh Continues. Application includes `18b6478`, native animation fix `fbe98dc`. [Execution](docs/native-battle-execution.md), [earlier full Multi](docs/native-full-multi.md). Input was automated through ordinary controls; this is not four-human or separate-PC acceptance. Recorded battle time 45.6 minutes is a performance concern, not release-speed acceptance. |
| Separate production 1v1 | Actual two-core singles passed on application `5a7afee` / native `1a7a0cd`, with legitimately obtained two-versus-one Pokémon parties, switch, result, save and Continue. [Execution](docs/native-battle-execution.md#actual-singles-execution-on-the-combined-build). Six-versus-six, concurrent observers and integrated Windows menu entry were not covered. |
| Durable completed result/history | Exactly one immutable result after all required restored-party releases, retry and host restart tested; corresponding actual-core proof documented. [History](docs/native-battle-history.md), `battle_results.py`. This is distinct from recovering an interrupted battle. |
| Development Local Soft Reset | Default-off test encounter passed 21 checks with four actual cores: local fresh rolls/reset, other-player independence, capture, checkpoint and fresh Continue. [Design/proof](docs/local-soft-reset-design.md), `scripts/multiplayer/local-reset-evidence.json`. This does not qualify production-route static encounters. |
| Windows timed autosave and manual checkpoint | Application `5a7afee` / native `1a7a0cd`: actual TLS Host/Join, elapsed five-minute save, independent off preference, manual saves, exact party reloads and fresh Continue. Source-launched visible GUI buttons/reopen passed separately. [Windows qualification](docs/windows-launcher-gui.md#combined-native-save-and-visible-button-qualification). |
| Host-loss field preservation | Combined native actual tests passed safe-field host loss and interrupted export, exact local candidate preservation, held core and authenticated rejoin. [Emergency save](docs/emergency-save.md#combined-native-build-qualification). Pending reset/trade/battle combinations retain separate gates. |
| Early native battle admission hold | `d976ed6` / `aef47e4`; two-core early Enter race/offline ADMIT proof passed. [Takeover milestone](docs/native-battle-resume-proof.md#native-entry-run-2--qualified-admission-boundary). Full wait-all resumption is excluded from that proof. |
| Private Windows launcher preview creation/audit | Existing package 6 is a hash-verified `5a7afee` preview with runtime/Python/Tk/notices; startup checked. [Launcher](docs/windows-launcher-gui.md), [recursive audit](docs/windows-package-content-audit.md). This is not a usable first-time friend download: real import patch and release acceptance are missing. |

## 2. Implemented but untested or not fully qualified

- **Retained-original-core battle recovery:** host/client reconstruction, renewed quorum, persistent route/command journals, native suspension and admission markers exist (`battle_recovery.py`, `battle_recovery_session.py`, `native_battle_resume.py`, `engine-patches/phase5-native-retained-recovery.patch`). Native candidate passed 129 focused tests, but the four-core all-fault controller failed. Process death/power-loss reconstruction is not supported. [Recovery](docs/native-battle-recovery.md), [proof controller](docs/native-battle-resume-proof.md).
- **Nine authored static hunts and durable counters:** descriptor catalogue, host admission ledger, count display, exact neutral cancellation, script-yield fix and personal Gen 6 shiny generation exist. Native focused and transport tests passed. Authored reset entry/capture via ordinary progression, Windows controls and combined host-loss acceptance remain unverified. Build flag is default off. [Durable admission](docs/local-reset-durable-admission.md), [catalogue](docs/local-reset-production-catalogue.md), `reset_attempts.py`, `reset_session.py`.
- **Bounded BPS import and launcher setup:** CRC/hash validation, atomic install, draft character/enrollment and isolated profiles exist with synthetic tests. A real source-dump-to-final-game patch, complete packaged first-character flow and clean-machine installation are unverified. [Setup](docs/launcher-setup.md), `game_import.py`, `launcher_setup.py`, `tests/test_game_import.py`.
- **Internet-capable TLS transport:** authenticated/pinned TLS code exists. A passive connection probe explicitly reports player authentication, separate-device proof and Internet-path proof as false (`network_diagnostics.py:22`). Loopback success does not certify a router, firewall, outside network or friend's PC. [Transport](docs/network-transport.md).
- **Gen 6 friendship groundwork:** pure planner, strict paired Flash candidates and immutable observations exist; no production effects capability or known complete handler history. The pre-existing untracked table generator was unfinished at audit entry. [Friendship plan](docs/trade-friendship-plan.md), `trade_friendship.py`, `trade_friendship_flash.py`, `trade_friendship_observations.py`.

## 3. Partially implemented

| System | What remains |
| --- | --- |
| Complete trading | Current `trade_eligibility.py:104` refuses eggs, mail, trade-evolving species and unsupported forms; `trade_flash.py` / `trade_storage.py` allow only an exact record swap. Native effects code is a read-only `CHECK_EVO` preview with `POLICY_REQUIRED`. Need real recipient evolution/move choices, strict prepared post-image validation, Pokédex/stat/mail/egg/handler handling, atomic history/recovery and actual-core tests. Do not remove the gate to claim success. [Effects audit](docs/native-trade-effects.md). |
| Battle menu → playable recovered matches | Menu handoff and executor are connected in source (`launcher_session.py:987`), and components have separate actual-core evidence. Full integrated native menu→match→interruption→result→save/reload on the release package remains unqualified. Admission-abort cleanup is explicitly missing. [Client recovery](docs/native-battle-client-recovery.md), [native recovery](docs/native-battle-recovery.md). |
| Local Reset production | Nine authored entries and durable counting are implemented; broader special-script adapters and ordinary-route acceptance remain. Traditional reset chord is suppressed in current Windows SDL adapter (`native/windows-runtime/sdl-multiplayer.c:73`); Select route and physical keyboard/gamepad behavior need qualification. [Backlog](docs/local-soft-reset.md). |
| Saving/recovery as one user flow | Five-minute/manual and two field loss cases passed. Interrupted battles, pending encounter admission, unsettled trades, automatic closure and Windows user recovery need combined coverage. Paced save-window measurement was 6.328 seconds, so saving pause/performance is still open. [Save performance](docs/save-performance.md), [autosave](docs/autosave-foundation.md). |
| Windows delivery | Standalone preview exists, but current release manifest has no real patch. Package 6 freezes older qualified code, not HEAD. Final source/native/bridge/manifest/bundle must be pinned and tested together. [Windows launcher](docs/windows-launcher-gui.md), `scripts/windows-runtime/build_launcher.py`. |
| Full Gen 6 game | Pinned upstream provides species/mechanics/Fairy/Mega support, but current networking builds retain baseline defaults in several areas. Gen 6 full configuration, every acquisition allowlist, move/evolution data, 18-starter menu and per-trainer Mega content must be qualified explicitly. [Gen 6 audit](docs/gen6-foundation-update.md). |

## 4. Intended-game comparison / not started

“Not started” means no project-specific implementation evidence found, not that the upstream engine has no related code or assets.

| Requested goal | Actual status and evidence |
| --- | --- |
| Independent cooperative exploration | Verified local foundation; full co-op story eligibility, Gym Twins, progression/rewards not started. `docs/phase2-presence.md`, `docs/four-player-foundation.md`, `docs/master-spec.md#campaign-and-gym-twins`. |
| PvP and two-player teams | Partial/verified slices above. Full six per trainer is accepted and must not be reduced to native three. `docs/native-full-multi.md`, `docs/native-battle-execution.md`. |
| Tournaments / wagers / four-way battles | Four-player Championship now has source-level host persistence, native menu and ordinary 1v1 integration; entirely untested, with uncertain issued matches retained waiting. Wagers and custom four-way battles remain not started as project gameplay systems. `docs/championships.md`, `src/emerald_multiplayer/championship.py`, `docs/master-spec.md#trading-and-battles`. |
| Multiple regions | Hoenn only as current foundation; extra regional campaigns not started. Upstream FRLG/map assets are not an integrated campaign. `docs/master-spec.md#regions`. |
| Gen 1–6 roster / modern mechanics / Fairy | Engine support exists; project-wide faithful Gen 6 ruleset and acquisition restriction not complete. `docs/gen6-foundation-update.md`. |
| Mega Evolutions | Upstream engine/data exists; complete eligible official catalogue, adaptations, unlock/economy and one-per-trainer multiplayer behavior unqualified. No blanket completion claim. `docs/master-spec.md#mega-evolution`, `docs/gen6-foundation-update.md`. |
| Fake 2.5D / Octopath-inspired graphics | Newly stated aspiration in this request; no implemented renderer/art conversion found. Prior master spec explicitly begins with GBA-style 2D. Compatibility/budget/design treatment is UNKNOWN until separately researched; no renderer change authorized by assumption. `docs/master-spec.md#game-identity-and-delivery`, `docs/customization-and-reuse.md`. |
| Improved sprites/movement/effects | Existing RHH assets and limited remote-avatar animation exist. A comprehensive project graphics/animation overhaul is not started or verified. `docs/phase2-presence.md`, `docs/customization-and-reuse.md`. |
| Visible roaming wild Pokémon | No project system found. Ordinary Emerald special encounters/roamers are not general visible roaming multiplayer Pokémon. Intended behavior and networking remain UNKNOWN. `docs/master-spec.md#wild-encounters-and-shinies`. |
| Followers and rides | Complete synchronized Gen 1–6/shiny/form followers not started; reuse/assets require audit. Dedicated rideable-Pokémon implementation not found; native Surf/bikes do not prove that feature. `docs/master-spec.md#followers`, `docs/customization-and-reuse.md`. |
| Day/night and timed encounters/evolutions | Engine RTC/time-dependent facilities may be reusable; a complete project day/night/encounter/evolution feature is UNKNOWN/unqualified. Not specified as completed in accepted scope or proof reports. `docs/gen6-foundation-update.md`, `docs/master-spec.md`. |
| Shiny hunting | Ordinary engine shinies plus tested development reset; authored Gen 6 personal hunts partial. Full wild profile, odds/modifiers and all display cases unqualified. `docs/local-reset-durable-admission.md`. |
| Purchasable personal Shiny Charm | Not implemented as accepted permanent personal reward/purchase. Upstream item/reroll/prize code is reuse evidence only. Price and final policy remain pending. `docs/master-spec.md#personal-shiny-charm-and-game-corner`, `docs/customization-and-reuse.md`. |
| Special Legendary/Mega/shiny world events | Not started as shared world event scheduler/claims/rewards. Native static legends are different content; no shared reroll system may be inferred. `docs/master-spec.md#world-events`. |
| Custom Trainers / friendship / Lucky trading | Accepted backlog, research and narrow ordinary-trade history prerequisites only. No creator, pair progression or Lucky gameplay is implemented. Balance decisions remain pending. `docs/customization-and-reuse.md`, `docs/trade-friendship-plan.md`. |

## 5. Broken systems / unresolved defects

1. **Four-core resume fails at fourth reconnect.** Private `native-resume-all-run-2.log` fails in `battle_recovery_session.py:468` with `replacement BIND lacks proof the original was never executed`. Host `battle_recovery.py:263` legitimately handles a provisional query, but the client accepts only a not-held, different-generation BIND. A native provisional query is deliberately held with the same generation (observed flags 129, sequence 0). Repair must distinguish exact provisional admission from an executed match; broad removal of held/generation checks would be unsafe. Source saves and frozen Python sources were unchanged in failed evidence.
2. **Admission cancellation cleanup missing.** A changed live party or cancellation racing Enter can leave a retained provisional game safely held, without a qualified neutral release path. [Native recovery](docs/native-battle-recovery.md). Do not silently forfeit or abandon original state.
3. **No clean complete regression at initial HEAD.** Frozen `a13f6e6` Windows full suite: 1,065/1,066 passed, one obsolete status fixture later corrected. Frozen `2dba880` WSL: 1,065/1,066 passed, one real same-size journal corruption failure; HEAD `31e5bf9` addresses it but initial audit found no subsequent full passing record. [Regression record](docs/battle-resume-regression.md). Earlier failures remain historical evidence, not proof current HEAD still fails those cases.
4. **Gameplay/performance qualification remains incomplete.** 45.6-minute headless full-party battle and 6.328-second paced checkpoint are measured limitations. Different frame-pump schedules confound a direct Windows-speed inference. [Execution timings](docs/native-battle-execution.md), [save performance](docs/save-performance.md).
5. **Windows import is deliberately unavailable.** No verified owner source dump or release BPS path was supplied/found in project evidence. The existing package cannot onboard friends. This is a missing input/integration gate, not a demonstrated BPS decoder bug. [Launcher preview](docs/windows-launcher-gui.md).
6. **Status summaries are stale.** README statements that timed saving, menu executor and Host/Join evidence are absent conflict with later frozen proof reports. Use exact build/evidence records until refreshed. No full latest-native build failure was newly reproduced by this audit; latest combined release build status is UNKNOWN beyond recorded scoped builds.

## 6. Last known development activity

Recent commits (October 8, local time): `d976ed6` corrected emergency refusal cursor identity (17:27); `e42b6bc` recorded failed entry/full WSL evidence (17:35); `f15f7bc` drained recovery operations between actual fault stages (17:36); `f36903e` recorded qualified early native entry (17:36); `31e5bf9` validated route tails/full journal bytes before closure (17:44). These reflect recovery qualification, not completed trade effects or a final release.

The previous chat then ran a frozen `31e5bf9` four-core `--scenario all` test. Its final statement reported the fourth-reconnect validation mismatch and intent to fix it; the usage limit ended the turn. No tracked fix was left behind. The untracked friendship-table generator is parallel unfinished trade groundwork. Evidence: Git log/status, prior chat last turn, private `native-resume-all-run-2/evidence.json` and log.

## 7. Prioritized next tasks and dependencies

This is the current roadmap; the numbered takeover findings above are historical.

1. **Complete supported trade acceptance and remaining adapters.** Public v2 native replay, reviewed candidates, atomic saves/history and terminal recovery are connected. Extend the passing supported client result/reload proof to genuine evolution/move-choice and interruption cases. Resolve existing post-Gen6 moves and select geography policy for any original-world upgrade. Eggs/mail/unsupported forms retain separate adapter work. [Client](docs/public-native-trade-client.md), [backend](docs/public-native-trade-effects.md), [worker](docs/native-trade-replay-worker.md).
2. **Qualify matches and recovery on the same candidate.** Existing full-party 1v1/2v2 and wait-for-originals recovery proofs retain their original pins. Exercise the current Windows candidate, including pending trade/battle/reset boundaries and uncertain Championship issue cases. Preserve unresolved matches; process/power-loss reconstruction remains a separate design. [Battle evidence](docs/native-battle-execution.md), [recovery](docs/native-battle-recovery.md), [Championships](docs/championship-recovery.md).
3. **Qualify production personal hunts.** The production build now enables the 25-source catalogue and requires its durable ledger. Exercise ordinary progression, reset controls, attempt counts, cancellation/capture and interruption with peers active. Descriptor/fixture checks do not qualify every event puzzle or ticket path. [Production flow](docs/local-reset-production-flow.md).
4. **Complete Windows and network acceptance.** The owner dump and reconstructing patch are available, and private import-enabled packages are being qualified. Finish GUI import, first-character/Host/Join flow, physical controls, timed saving, clean-PC and actual separate-PC Wi-Fi/Internet checks on one frozen candidate. Preserve packages7/8 and every failed proof; packaging alone is not gameplay acceptance. [Import](docs/release-patch-creation.md), current package/proof links in the executive table.
5. **Implement staged world and visual content after the foundations.** Reuse the completed resource inventory, existing native primitives and verified remote running. Complete the Gen6 ruleset, settle shared-spawn/shiny/Charm and clock decisions, then implement visible entities, followers, shared time/Gen6 time mechanics and supported ground mounts before broad Hoenn/environment changes. Measure the combined four-player resource budget. [World design](docs/visible-world-design.md), [inventory](docs/graphics-resource-inventory.md), [running](docs/remote-running-animation.md).

The accepted long-term backlog remains in scope. No unapproved friendship
thresholds, Lucky odds/IV floors, prices, cooldowns, mount speeds or clock rates
are selected by this roadmap. Testing is active under the latest amendment.
[Development order](docs/development-roadmap.md), [master spec](docs/master-spec.md).

## Verification performed in this takeover

- Initial read-only Git/status/history/worktree/tag inspection and `git diff --check` passed; no original saves were opened for writing.
- Existing Windows pinned interpreter ran `test_battle_recovery_session`, `test_native_battle_resume`, `test_native_resume_proof_controller`, `test_trade_menu`, `test_trade_eligibility`, `test_reset_attempts`, `test_game_import`, and `test_package_audit`: **79 tests passed in 18.771 seconds**, no failures/skips reported. Bytecode writes disabled. These tests use controlled fixtures; they do not reproduce the missing complete four-core recovery proof.
- No dependency installation, native rebuild, commits, branch resets, migration of private worlds or public network configuration occurred during the audit. Subsequent authorized implementation is recorded below.

## Missing inputs / previous-conversation questions

- Previous chat is accessible, so a wholesale transcript paste is unnecessary. Any off-chat accepted gameplay decisions not reflected in `master-spec.md` remain UNKNOWN.
- **Resolved:** the owner's Desktop/roms ZIP has been found, identified and used read-only to create the real release patch. Exact hashes and validation are in [release-patch-creation.md](docs/release-patch-creation.md); no replacement dump is needed for the current candidate.
- A legitimately progressed private save is needed to qualify production authored static hunts through ordinary gameplay. Existing starter-stage saves cannot establish this acceptance.
- Separate Windows PCs, another network/participant and real input devices are needed for multi-machine, Internet, clean-install and hardware acceptance.
- **Resolved:** missing legacy handler friendship initializes to Gen6 species bases, with known values preserved. **Pending:** original-world geography policy, treatment of existing post-Gen6 moves such as Treecko's Leafage, shared visible-spawn/Charm/progression/escape policies, world-clock rate, later Mega conflicts and remaining numerical balance choices. See the current evidence table and [visible-world-design.md](docs/visible-world-design.md); absent fields do not answer those questions.

The earlier missing host-service action now has a [retained-host restart implementation](docs/host-service-restart.md). Retained battle recovery still requires the original game and runtime objects to survive. A service-restart proof cannot establish recovery after host-PC power loss. The owner's wait-for-every-participant rule remains intact; actual latest-candidate acceptance is recorded separately from that source implementation.

## Post-audit implementation and verification

The audit findings above preserve the state found at takeover; executive links and the next-step roadmap reflect subsequent progress. The following changes are uncommitted working-tree changes on the original branch; no existing tag, branch, accepted binary or private player world was replaced.

A verified private source backup is retained at `%LOCALAPPDATA%/PokemonPrivate/artifacts/handoff-audit/implementation-backup-20261008-190541`, including 333 files, the tracked binary diff, status and base revision. `source.zip` SHA-256 is `993e636caf9a92d27318f726d604bc0e286b0ee52822d6b7837340b910212239`; index SHA-256 is `f22323f1dee3bf40116a82e1659180e480b811c1a1583726f1bcb65c0c12f2c1`. ZIP CRCs and every archived file hash were verified against unchanged working bytes. This snapshot predates the later admission-cancellation implementation and subsequent documentation updates. No commit was made.

| Change | Implementation and verification | Remaining limit |
| --- | --- | --- |
| Repair fourth-player provisional recovery BIND | `src/emerald_multiplayer/battle_recovery_session.py` now recognizes the exact provisional native hold while retaining original generation, participant, mode, sequence, roster and lease checks. `tests/test_battle_recovery_session.py`: 23 passing tests. Two frozen four-core all-fault proofs passed with populated parties 2/1/1/1, including post-release recovery, terminal handoff, checkpoints and fresh Continue; see the exact scope below. | Full-six run 3 timed out during gameplay. Longer run 4 reached post-RELEASE recovery, then failed a partial-quorum assertion; its discarded task exception is UNKNOWN. Copied-world diagnostics reproduced a large-journal timeout and motivated the separately verified asynchronous correction. The smaller-party proofs do not qualify six-per-trainer recovered completion, actual menu entry or Windows packaging. |
| Remove duplicate checkpoint validation within a recovery poll | `src/emerald_multiplayer/battle_recovery.py:_record` reuses the first authenticated immutable checkpoint within the same synchronous operation. All 12 `test_battle_recovery` methods passed on Windows in 87.536 seconds, including four new real SQLite integrity checks. There is no cache across polls. | A synthetic 100-call comparison reduced full-checkpoint reads from 200 to 100; it does not establish game speed. [Exact evidence](docs/native-battle-recovery.md). |
| Avoid repeatedly decoding an unchanged executed battle journal while waiting | `battle_recovery.py:exchange` retains validated parsed history after a native response exists, but calls `RouteJournal.verify_current` on every waiting poll. Incomplete provisional bootstrap still reloads. All 26 affected recovery/journal methods passed on Windows in 83.327 seconds, including same-size prefix corruption with masked metadata, replacement, append/truncation and mixed-prefix recovery. The final-source four-core smaller-party all-fault rerun also passed through checkpoints and fresh Continue. | This follow-up comes after both full regression snapshots. Native proof scope remains parties 2/1/1/1, separate from full-six and Windows qualification. [Details](docs/native-battle-recovery.md). |
| Retire completed Players-menu battle identity | `src/emerald_multiplayer/menu_session.py:finish_battle_admission` now clears its completed identity after verified terminal handoff. All 54 menu-session/launcher-recovery tests passed in 3.328 seconds, including a later non-menu completion and refusal to let an old completion clear a new admission. Sources were hash-verified unchanged. | Fixture coverage only. This one-line change follows the Windows full-regression snapshot and is included in the later WSL full suite. [Details](docs/native-players-menu.md). |
| Bound pending-reset cancellation retries | `src/emerald_multiplayer/reset_session.py` limits retransmission to once per second while awaiting the exact safe-field receipt. `tests/test_reset_emergency_integration.py` composes real controllers, SQLite attempt history and closed recovery with explicit native fixtures. 33 reset/emergency tests passed in 5.452 seconds. | Actual authored-route pending-reset host-loss and Windows physical input remain unqualified. [Details](docs/local-reset-durable-admission.md#handoff-follow-up-composed-cancellation-and-preservation). |
| Finish pinned Gen 6 trade friendship table | Repaired/preserved pre-existing generator; new `gen6_friendship.py` covers all 721 standard species with native compiler/provenance checks. `trade_friendship_flash.py` derives species bases itself and binds them to planner-v2 hashes, removing caller-selected bases. 19 tests passed on both Windows and WSL; independent regeneration matched. | This completes a trade prerequisite, not native evolution or the production effects transaction. Legacy handler/geographic decisions remain explicit. [Table and decisions](docs/gen6-friendship-table.md), [provenance](docs/gen6-friendship-table.json). |
| Correct Windows reset-chord input guard | `native/windows-runtime/sdl-multiplayer.c/.h` retain the unfiltered requested key state, suppress all chord buttons after detection until full release, and restore all callbacks on unload. `tests/native/windows-input-guard.c`: 37,889 compiled C cases passed on Linux and native Windows. A new isolated runtime candidate passed executable/bundle/relink checks and actual two-client Windows enrollment, TLS Host/Join, manual saving, normal closure and fresh Continue on native `1a7a0cd`. | Accepted runtime binaries unchanged; candidate not promoted into a launcher release. Classic chord still does not invoke Local Reset. This run did not repeat five-minute timing or qualify physical controls, battle-resume native `aef47e4`, new cancellation work, or a final package. [Controls audit](docs/windows-controls-audit.md). |
| Reconcile stale project summary | README now points to the actual later trade/menu/executor/Windows evidence and distinguishes the qualified delivery base from the resume candidate. | Individual historical reports retain their original build scope. |

A first full Windows regression ran 1,082 tests with three failures and zero skips. All three failed at child-process startup because the audit runner set only its own Python import path, not the inherited `PYTHONPATH`. The separate child-import diagnostic reproduced `ModuleNotFoundError` without that environment variable and successful imports with it. The three exact failed methods then passed unchanged in 0.934 seconds. This was a runner defect, not a demonstrated project failure. The failed run and diagnostics are preserved privately under `artifacts/handoff-audit/windows-regression-20261008-182318`; its evidence confirms every indexed source and both original saves were unchanged.

The corrected full Windows regression **passed all 1,086 tests in 532.412 seconds, with zero failures, errors or skips**, against a fresh frozen 333-file snapshot including the recovery-poll change. The runner inherited `PYTHONPATH`, disabled bytecode writes and verified BelowNormal priority. All indexed sources and both original saves were unchanged. Its private directory is `artifacts/handoff-audit/windows-regression-corrected-20261008-183632`; source-index SHA-256 is `dcd669fe87907248cc4d7af386699bf5ed9e96f7b319928891f44a724f500834`, test-log SHA-256 `49b9c7bfe6baf3d67e1f35f56a380e60d43f65885036cfd721833f143b815010`, evidence SHA-256 `e82efa286042417f7decb7c8c9795fda23e1943fc4fdf0aab39be162926575dd`. The later menu identity correction is covered by the separate 54-test cohort above, not retroactively included in this snapshot.

The next full **WSL suite passed all 1,088 tests in 379.320 seconds, with zero failures, errors or skips**, including the menu fix's two added regressions and the collector wording correction. Niceness 19, inherited import path and disabled bytecode were verified; all 333 frozen sources and both original saves remained unchanged. Private ext4 output: `multiplayer-proof/handoff-final-wsl-regression-20261008-1`. Source-index SHA-256: `a56fa813de5e4a012edcaa4e954553d7dd5ed5e522baa131be190cd046ca4191`; log: `75cf4d2f10262af0cd506679909dd35c259ead1d953dfdfb8189f651d752d732`; summary: `a6b2c9371ead117f53c79cd8d96f9a229077c0da99bd42c5d21c723971e40fc2`. The subsequently discovered waiting-journal performance change has its separate 26-test qualification above. [Complete regression record](docs/battle-resume-regression.md). None of these fixture suites proves separate-PC gameplay.

The first smaller-party actual-core recovery run **passed**: private `native-resume-handoff-small-run-1`, native `aef47e4`, frozen Python handoff source with the provisional-BIND correction. Four legitimate distinct trainers with populated parties **2/1/1/1** completed 1,144 routed blocks in 1,304.47 seconds. Pre-BIND, mid-battle and post-RELEASE host loss each preserved the same original cores and required three reconnected players to wait for the fourth. Exact terminal receipts, emergency-controller replacement, native handoff, original party/Flash preservation, canonical checkpoints and fresh Continue all passed. Evidence SHA-256 is `7a7fcbc5a317a1527672fe8560464d0164968c28cf337a0df148fe5b3e6d22c5`; it records `passed`, `cores_closed`, `original_sources_unchanged` and `python_sources_unchanged` as true. This first recovery-completion milestone is followed by the journal-corrected rerun below; it does not replace the earlier full-six proof or establish native-menu/Windows/network acceptance. [Native evidence record](docs/native-battle-resume-proof.md).

That proof exposed slow repeated parsing while waiting for the fourth player. The prior host reloaded its 14,074,184-byte route journal on every waiting poll. The bounded follow-up above preserves full-byte verification while avoiding repeated decoding after native execution has begun. It passed 26 affected tests; log SHA-256 is `7f14010f2d3aa7c583d259098079c6d48bf915ebd5b85489a23ace61951ec778`. Three alternating read-only measurements on the closed proof's unchanged journal had median costs of **1.138 seconds for reconstruction versus 0.00937 seconds for full-byte verification**. Header, digest, 23,328 events and 11,660 responses remained identical; this measures file-operation cost, not game speed. Private benchmark evidence SHA-256: `82e9aba66ac6556d14be0e403ccb8144220cac377cc1ffb8ab1f8c2d450332f9`.

The follow-up `native-resume-handoff-small-run-2` **passed** all three faults, terminal handoff, canonical checkpoints and fresh Continue using frozen source `handoff-recovery-final-source-20261008-230121` with that journal correction. It used the same native `aef47e4` and legitimate parties 2/1/1/1, completing 1,189 blocks in 1,016.478 seconds of execution/recovery. This timing is a different gameplay run, not a controlled game-speed benchmark. Evidence SHA-256 is `f0b86b2c43d15c010b3959495f65462a0ed0ad7653fda6230cbd0708c0584eb5`; root independently read the four passing integrity/completion flags and all three fault-stage names. All original cores closed and all original saves and frozen Python sources remained unchanged. The independently verified Windows archive contains 955 files / 68,317,553 bytes; inventory SHA-256 is `ca8aa0d58aae89d8a5d2a0bc5cc9dfed361aa5102394152596731c4322b49e26`. [Full scope and source pins](docs/native-battle-resume-proof.md#final-python-rerun--populated-party-recovery-completion).

The concurrent original full-six `native-resume-handoff-run-3` reached its unmodified 3,600-second limit during normal gameplay after 3,858 blocks and two sixth-slot switches. Pre-BIND and mid-battle recovery passed; post-RELEASE and final save/reload were not reached. Its preserved failed evidence is `8be0d53591fe92c0b43f9fa9ba124196dbe66b57af474ba272a8086ad886b79c`, with clean core closure and unchanged sources/saves. The separate 7,200-second `native-resume-handoff-full-run-4` used the immutable source from small-run-2. It later overlapped bounded native compilation/tests and cancellation proofs after resource measurements showed ample idle capacity; no performance comparison is inferred.

Full-six run 4 reached **5,037 blocks and post-RELEASE host loss**, then failed the controller's partial-quorum assertion. Evidence SHA-256 is `c6c8a0d630cf648289b0b99976d6372ea9f735a0559184be449d05814bfd93e9`; core closure and original/frozen-source checks passed. The assertion tested whether a client task had ended, which also includes exceptions: all three partial clients still had `executing/recovery` records with dispatch 0, no completed terminal records, and the fourth had not reconnected. This does **not** establish successful recovery without the fourth trainer; the discarded original exception is **UNKNOWN**. Read-only measurement found that its 66,444,796-byte journal takes over five seconds to decode; an isolated authenticated TCP reproduction then reproduced three request timeouts at 5.273 seconds, with no route dispatch or quorum completion. This supports the timeout diagnosis without proving the discarded exception. The closed run and source were independently archived: 2,215 files / 146,508,719 bytes, inventory `4c01af11f2b0d3eec198572abfcc6b6f681680cbea291d59117538a1ce75ad99`. All four original source saves were rehashed unchanged. [Evidence and scope](docs/native-battle-resume-proof.md).

The asynchronous correction now performs initial parsing in a single read-only worker while replying with the existing waiting status. It reauthenticates current participants and verifies every journal byte before dispatch; it changes no quorum or RPC deadline. The final frozen 57-test cohort passed, and a copied-world diagnostic using the exact final source handled **495 authenticated RPCs**, maximum 0.222 seconds, with 90 heartbeats per client and three waiting clients/no native dispatch. The full original match has not been rerun to completion. The subsequent final combined-candidate four-core smaller-party all-fault test passed, as recorded below. [Implementation, tests and diagnostic limits](docs/native-battle-recovery.md#uncommitted-follow-up-responsive-initial-journal-reconstruction).

The **final combined candidate** then passed `combined-recovery-final-20261008-1/run-small-all`: four original cores, legitimate parties **2/1/1/1**, all three fault stages, waiting for all four originals, 1,189 routed blocks, terminal saver handoff, original party/RNG/Flash restoration, checkpoints and fresh Continue. Execution/recovery took 1,195.338 seconds; outer setup/cleanup took 1,270.456 seconds. All original cores closed, all 207 frozen sources and eight original/copied inputs remained unchanged, and no watchdog termination occurred. Evidence: `7ef364142a031f274f2f7fa799d8a3c2e21c6b66bb882c5c0e6c7305581ee1c5`; source index: `57d5fbdeec57365e18473cfee0a7c3af1e9daf496d8a26889ad53ef709db29b0`. The verified private archive has 922 files / 168,047,511 bytes, inventory `0305411c0c5eb7d2f96e8c2c2ed37fb09547bad36aeb3b710cde2308bed3f735`. Native ROM `a46cb8ae...` is base `aef47e4` **plus** the retained seven-file cleanup patch, not bare `aef47e4`. Full-six recovery, native menu initiation, Windows and networking remain separate scopes. [Complete pins and acceptance](docs/native-battle-resume-proof.md#final-combined-candidate--populated-party-all-fault-recovery).

The new input-guard runtime then passed actual Windows qualification `PokemonPrivate/wq1` in 293.648 seconds: two ordinary copied-character enrollments, simultaneous authenticated TLS Host/Join, manual revision-2 saves, normal play-window closure, exact fresh Continue and store/lease/party verification. All six test processes were independently confirmed absent, and original inputs and 81 frozen Python sources were unchanged. Proof evidence SHA-256 is `c08ae5c09c7d46bf4c7fedf63a0c5eead1cf6e082e26cc4ae47362ab3cb56921`; outer-run evidence is `9753b43fca56076d03c0ac5452810649efec694c1d220d32283376b88caa5eb9`. This used native `1a7a0cd`, not the battle-resume binary or the later cancellation work. It did not test the five-minute interval, physical input, Internet, a real import patch or a final packaged launcher. [Exact candidate/runtime/UI evidence](docs/windows-controls-audit.md).

A new optional **Cancel battle entry** slice now has native acceptance for the narrow boundary before any reservation or routed BIND exists. The isolated source delta against `aef47e4` compiled, passed **133 native tests**, and passed three actual-core cases: genuine Enter before ADMIT; ADMIT with a lost HOLD response and host restart; and host loss after the old emergency saver retired but before its successor armed. Each required the retained original core, unchanged party/RNG/Flash, fresh saver before field release, a checkpoint and fresh Continue. An initial actual run found a duplicate save-BIND on the same authenticated lease; the fix preserves the exact progressed binding/cursor while still requiring fresh successor arming. A composed test reproduced and repaired the same defect after ordinary completed battles. Renewed leases still require a new BIND. The old failing run, native fixture failures, exact native patch/build hashes and all passing evidence are retained in [native-admission-cleanup.md](docs/native-admission-cleanup.md). Bound/prepared battle cancellation is still outside this capability.

**Actual Windows launcher cancellation passed** in private `wqc8`, 498.080 seconds: real native Players challenge/accept/Enter, the actual enabled Tk cancellation widget through `SessionWorker`, neutral hold and fresh saver handoff, two revision-2 saves, normal play-window closure and exact fresh Continue. Two enrollment children closed automatically under the existing production contract; all four play children exited normally with code 0. All six PIDs and test windows were independently absent, with unchanged source/input hashes and no forced qualifier cleanup. Evidence SHA-256: `63978250f8e81c95cdf6d2a5233d186ea852aacdbf51be7d7809be86241f78ea`. This uses a proof-only preparation lock gate and scripted ordinary joypad input; it does not establish physical controls, completed Windows battles or interrupted Windows cancellation. Earlier runner/API/newline failures are preserved individually. [Exact scope and pins](docs/windows-admission-cleanup-proof.md).

**Actual Windows menu-to-match 1v1 passed** in private `wqb1`, 643.067 seconds overall: ordinary native Challenge/Accept/Enter in both games, 362 routed blocks, a real second-slot switch, agreed result, two native history screens, fresh saver handoff, revision-2 saves and exact fresh Continue. All four play/reload games exited normally; two enrollment children closed under the existing bootstrap contract. No qualifier force/cleanup errors occurred and all source/input pins remained unchanged. Match/terminal time was 168.115 seconds. Evidence: `9655b9b2915010f942b5c882c97d7d41a2fda2c64d5c2349eb3df320e3cab337`. This is legitimate two-versus-one-party singles using source-launched Windows GUI workers and ordinary scripted input. 2v2 menu entry, interrupted Windows matches, physical controls, packaged gameplay and remote networking remain separate. [Complete scope and pins](docs/windows-menu-battle-proof.md).

**Actual Windows four-client menu-to-match 2v2 passed** in private `wqm1`: 1,547.312 seconds for the scenario and preservation checks, 1,550.822 seconds including its independent watchdog. Ordinary native menus formed two teams and collected all four consents/Enter actions. The match routed 1,197 blocks in 699.668 seconds, exercised a real second-slot switch, agreed on one durable result, restored every original personal party and completed all four saver handoffs. Native history screens, four revision-2 saves, exact fresh Continue and normal closure of all eight play/reload games passed. All twelve native PIDs and the controller were independently absent; 353 frozen source files and original inputs were unchanged. Evidence: `5df645dbbfab36ba93bfd46cb2a295882ff516cdbdc9eded8a8f885a1e0ff01d`. This uses legitimate 2/1/1/1 parties on one PC with ordinary scripted inputs. The later explicit full-six profile and 20 focused menu/recovery helper tests are separate from this actual acceptance. [Complete scope and pins](docs/windows-menu-multi-proof.md).

**Actual five-minute saving on the current Windows candidate passed** in private `wqt2`, 549.392 seconds overall. The host saved at its unchanged 300-second deadline, reaching revision 2 after 307.210 seconds; the friend remained at revision 1 with autosave off. Manual saves and fresh Continue retained exact revisions 3/2, native parties and both preferences. All four play/reload windows closed normally, source/input hashes and store/leases passed, and the watchdog did not force termination. Evidence: `8029007007f864ad7cb440cf93058e367b93adb4d285b2642726940fd5377b55`. The earlier wqt1 reached matching gameplay assertions but failed because the operator missed final closure during compaction; that failed evidence remains preserved. [Timed run evidence](docs/windows-controls-audit.md#timed-autosave-repeat-wqt2--complete-acceptance).

The cancellation-era full Python suite first found an obsolete protocol request fixture; that fixture was corrected and **1,135 tests passed**, before the saver-handoff fix. The next complete frozen snapshot including that fix passed **1,138 tests in 635.568 seconds with no failures, errors or skips** using the existing qualified Windows interpreter. Snapshot index: `b0d80734c50691a2a6d709d5dfd3a12ae237244ccf69134a50b9c89a743eaadf`; log: `a92a12f4024fd686c8b87e16b865b767ba08fd1fb4dbfa1212017b878fe32725`; private output: `%LOCALAPPDATA%/PokemonPrivate/artifacts/handoff-audit/windows-regression-cleanup-final-20261008-2`. All 346 frozen files and both original saves remained unchanged. An accidental run under the system interpreter, which lacks the already-installed private cryptography dependency, is retained separately with 95 errors and no acceptance claim. This full passing snapshot predates the later asynchronous journal-load correction and Windows proof-driver corrections.

The final application/native-adapter/bridge/test source then passed **1,144 tests in 653.061 seconds**, with no failures, errors or skips, including asynchronous journal loading. All 346 frozen files and both original saves remained unchanged. Snapshot index: `9b13d09576c6a9d91dc9d3ce71715ea2974c1f3fc45640b25e1523a687e388af`; log: `8245c344600e744d88139ddfc61f7cca364298981ebe9aa3070eebaee1f72919`; evidence: `93225209d4e6003a96bfa876578f07cbd80755bda93d17e210f944fde101a1f1`. Root subsequently compared every current `src`, `bridge`, `native` and `tests` file against this snapshot with no differences. Later documentation and qualification-driver changes retain separate scope. The subsequently added `tests/test_windows_menu_battle_qualifier.py` passed eight focused helper tests in 0.059 seconds; it is not included in the 1,144-test count. [Regression record](docs/battle-resume-regression.md#cancellation-saver-transfer-and-asynchronous-journal-loading).

The later complete menu-helper cohort passed **20 tests in 0.076 seconds**: eight singles-driver, eight Multi-profile and four retained-recovery diagnostic/source-index methods. The recovery observer's subsequent lazy-service check has a separate four-test repeat in 0.018 seconds and requires its own actual rerun. These additions are test-controller coverage, not additional production/gameplay acceptance; the 1,144-test production snapshot remains unchanged.

A new **private Windows package 7** now freezes the current 81 production Python modules, exact production Lua bridge, corrected input-guard runtime and cleanup-capable native manifest. All 1,086 package files, ZIP CRCs/member bytes, 101 frozen source files and 140 original inputs were independently verified. ZIP SHA-256: `8827a6a2b6f87da7e501a758bdd41cca393a749120665b0de9de3b71747c5c70`. Four no-ROM runtime checks and actual isolated packaged-GUI startup/normal closure passed. A separate copied-world check launched the bundled game through Host Game but did not establish Continue with automated Return/X; its input cause is **UNKNOWN**. It safely refused saving at the title screen, retained both canonical heads and closed without changing the 73 original files. Import remains disabled because the owner's real base dump/patch is missing. This is not a friend-ready download or packaged gameplay acceptance. [Package and limited Host evidence](docs/windows-recovery-package-candidate.md).

Still required to complete the owner's full request: native trade preparation/evolution and exact paired validation; cleanup for already-bound refused entry; full-six resumed result/reload and final integrated menu acceptance; ordinary-route static hunts; complete final-package input/setup/import; release content review; four separate PCs/Wi-Fi/Internet. The absent dump, progressed saves and hardware inputs remain pending the owner's response. No new numeric gameplay rule was selected.

### The six requested delivery tasks

| Requested task | Current completion boundary |
| --- | --- |
| Finish in-game trading | **Supported ordinary flow passed; full effect catalogue incomplete.** Public v2 offers, mutual consent, candidate review, native host replay, atomic paired saves/history, canonical apply/ACK/release, both received notices, manual saves and fresh Continue passed with two actual Windows clients and genuine non-evolving Pokémon. [Actual proof](docs/windows-menu-trade-effects-proof.md). Native Machoke evolution and restart replay passed separately on synthetic fixtures using the final packaged worker/ROM. Genuine evolving/move-learning gameplay, interruption, eggs/mail and later-generation compatibility remain separate gaps. [Client](docs/public-native-trade-client.md), [backend](docs/public-native-trade-effects.md), [worker](docs/native-trade-replay-worker.md). |
| Connect battle menus to playable 1v1/2v2 | **Both source-launched Windows menu flows now pass** through native results, saving and fresh Continue, with parties 2/1 for singles and 2/1/1/1 for Multi. This run also repairs menu identity retirement, provisional recovery and same-lease saver transfer, with qualified neutral pre-BIND cancellation. Full-six Windows menus, interrupted Windows matches, packaged acceptance and bound-entry cleanup remain separate; this is not a completed delivered release. |
| Finish disconnect recovery | **Partial.** Historical field/export and smaller-party all-fault proofs passed. Host-only retained-service restart is now implemented, untested, with original-game wait-all recovery preserved. Exited-game/whole-PC reconstruction remains unsupported. Later incomplete full-six/Windows qualification was stopped; no new acceptance is claimed. |
| Finish Local Soft Reset | **Production configuration implemented; encounter acceptance partial.** All 25 source descriptors are now enabled in the DEV=0 candidate, with exact-ROM capability checks and a required durable attempt ledger. Classic-input/catalogue/history/recovery paths have focused coverage. Legitimate progression, every source family, hardware controls and interruption with peers still need actual gameplay checks. [Production flow](docs/local-reset-production-flow.md), [controls/history](docs/local-reset-history-and-controls.md). |
| Complete installation | **Owner input resolved; corrected candidate9 built and verified within limits.** The supplied original ZIP produced a reconstructing BPS. Candidate9 passed recursive audits, fresh import with packaged resources and actual executable startup/normal closure. Complete GUI import/first-character flow, clean-PC setup and packaged gameplay remain unverified. Previous packages are preserved. [Patch](docs/release-patch-creation.md), [candidate9](docs/windows-release-candidate-9.md). |
| Test actual multiplayer | **Testing resumed by the latest visual/world amendment.** Targeted checks and new actual-core running/native-trade work are recorded at the top of this report. Earlier interrupted runs remain failed evidence. Four-PC, Wi-Fi/Internet, physical controls and combined final-package acceptance remain unverified. |
