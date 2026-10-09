# Current development roadmap

The owner's latest sequence prioritizes a usable private multiplayer build. This order follows the verified `OWNERSHIP_FOUNDATION_POC`; the full [master specification](master-spec.md) remains accepted scope. The [combined amendment](project-update-customization-friendship-shiny-charm.txt) is preserved byte-for-byte, including customization, reuse research, player friendship/Lucky trading, and the Shiny Charm/Game Corner reward. Adding these requirements does not mark them implemented.

The October 9 [visual/world amendment](project-update-maximum-visuals-visible-wild-riding-time.txt)
explicitly resumes testing of major additions, superseding the earlier test
pause. Use isolated outputs and disposable worlds/characters; preserve frozen
milestones and originals. New verification and its exact limits belong in the
[handoff report](../PROJECT_STATUS_AND_HANDOFF.md). No existing private world
migration, dependency installation or commit is implied.

Finish the active safe-trade/recovery/release integration while auditing existing
graphics and reusable resources. The amendment is additive: multiplayer remains
first. After its foundations, stage synchronized entities and the Gen 1–6 profile;
visible-wild prototype and shared claims; followers; shared clock and Gen 6 time
mechanics; ground mounts and peer rendering; then major Hoenn art/environment
passes and measured performance polish. Do not enable personal OWE/followers
globally and describe them as completed shared systems.

The current continuation integrates [public native trade effects](public-native-trade-effects.md),
[client recovery and result presentation](public-native-trade-client.md), the
[Windows replay worker](native-trade-replay-worker.md), production 25-source
reset configuration and explicit backed-up host feature setup. Targeted tests,
actual-ROM replay and actual-core [remote running](remote-running-animation.md)
have bounded evidence. The [supported two-client Windows trade flow](windows-menu-trade-effects-proof.md)
now passes through both received notices, saving and fresh Continue with genuine
non-evolving Pokémon; live evolution/move choices, interruptions and combined
packaged gameplay remain open.
The supplied owner dump now yields a reconstructing patch, bundled in
[private Windows candidate9](windows-release-candidate-9.md). Its package audits,
fresh packaged-resource import and actual executable startup/normal closure pass;
GUI import, clean-PC and combined packaged gameplay/network acceptance remain
open. Current classifications and five next priorities are in the handoff report
above. The following batch
paragraphs are historical; their test-paused/default-off states describe those
earlier snapshots.

The next continuation adds [friend-first setup and exact character approval](windows-first-run-setup.md)
and [provable unstarted Championship recovery](championship-recovery.md), with
focused file/UI/network/SQLite evidence. A separately identified
[Gen6 defaults candidate](gen6-defaults-profile.md) now has actual native tests
for selected ORAS/data/battle behavior and isolated native trade replay. It
preserves the compiled species/save layout and refuses automatic world repinning;
full Gen6 content remains a distinct dependency. Interrupted-trade host restart
and fresh Continue are being qualified against the retained baseline before
freezing the next package. No separate-PC acceptance is implied by these checks.

The broad implementation batch added source for Trainer Cards and recorded
battle/hunt/trade statistics, ten further personal static-reset sources (twenty
catalogue entries), Host/Join connection/recovery usability, and private native
trade-evolution record preparation. See the report's latest batch. This advances
implementation, not any acceptance gate below; full trade effects, production
encounter enabling, final Windows packaging and actual network play remain open.

The subsequent October 8–9 source batch adds [four-player Championships](championships.md)
over the existing native 1v1 service, [five ticket/static reset paths](local-reset-ticket-sources.md)
(25 descriptors total), and [complete paired recipient save-effect preparation](native-trade-save-effects.md).
These remain unexecuted. Next trade work connects the held scene/transport and
atomic effect-history publication; next reset work integrates release capability
and configuration. Championship wagers/rewards and automatic resolution of an
uncertain issued match are not supplied by bracket persistence.

The next October 9 batch connects optional [held native record preparation](native-trade-record-transport.md)
and explicit move decisions, [launcher bracket management](windows-championship-panel.md),
[durable Championship abort reconciliation](championship-recovery.md),
[tournament/shared Trainer Card records](trainer-card-shared-records.md), and
[source-derived species names in trade menus](species-menu-labels.md).
Full saved-block transport, native evolution presentation and atomic effect/history
publication remain the next trade dependencies. Unreserved entry cleanup and
uncertain issue intents still need affirmative evidence before replacement.
No new build, test or playable acceptance is claimed by these connections.

The preceding continuation implements [12 connected source improvements](feature-batch-20261009.md).
Full held-native save-candidate transport and durable retries now connect the
private computation; public effect/history publication and the evolution scene
remain open. All-original successful admission HANDOFF receipts now support
durable unreserved Championship cleanup, while incomplete identities/receipts
and pre-invitation issue gaps still wait. Player-facing work adds exact trade
inspection/reasons, launcher peer cards and team controls, and native/launcher
record browsers. Tests/builds remain paused; no release gate has advanced.

The latest [extended implementation batch](large-feature-batch-20261009.md) adds
launcher 1v1/2v2 proposal and consent workflows, full private battle/trade archives,
native and launcher receipt browsers, source-verified reset availability and
same-admission retry, local display/favorite preferences and held move review.
The owner selected Gen6 species bases for missing legacy handler values; the
[explicit history migration and canonical hooks](trade-friendship-migration.md)
are implemented but have never been run against private worlds. Geographic
handler adaptation and atomic public effect-history publication remain trade
dependencies. No acceptance criterion below is advanced by these untested sources.

## Immediate order

| Order | Work | Completion evidence |
| --- | --- | --- |
| 1 | Safe player-to-player trading | Offers and explicit mutual confirmation; edits invalidate consent; both canonical saves and ownership changes commit together; cancellation, retry, disconnect, server restart, and fresh Continue neither duplicate nor lose Pokémon. Preserve ordinary Pokémon attributes. Exercise actual ROMs before claiming playable trading. |
| 2 | Multiplayer battles and team features | 1v1 and four-human 2v2 with each trainer's full party of up to six (owner choice October 8); independent parties/rewards; invite, accept, leave, and change two-player teams; two teams may coexist. Verify battle synchronization and interruption recovery. Championship, currency wagers, and custom 1v1v1v1 retain their specified designs and separate acceptance gates. |
| 3 | Four-player testing | Four actual game clients, independent maps/encounters/saves, simultaneous teams, trading and 1v1/2v2, join/leave/rejoin, capacity limits, and host restart. Synthetic clients supplement this proof. |
| 4 | Local encounter Soft Reset | Build the necessary personal/static encounter and independent RNG/shiny hooks; reset only an eligible local hunt while three other players continue unaffected. Preserve ownership, counters, and committed captures; exclude wild/event rerolls. Test cancellation and interruptions. |
| 5 | Automatic saving and disconnect handling | Safe-point scheduling, visible pending/recovery status, reconnect policy, interrupted interaction recovery, and migration/backup checks. Define outstanding offline and battle policies before enabling them. Earlier trade/battle milestones already require transaction-specific crash safety; this step completes the player-facing lifecycle. |
| 6 | Downloadable Windows Host Game / Join Game | Bundled runtime and usable launcher, isolated profiles, reviewed dependencies/assets and import/patch flow, clean-machine installation, hosting/joining, error messages, and updates. Friends need no compiler, Python, WSL, or manual Lua setup. |
| 7 | Wi-Fi/Internet testing and polish | Actual separate PCs, LAN/Wi-Fi and port-forwarded Internet, firewall/connection setup, latency/loss/reconnect, compatible builds, transport security, performance, and clear recovery. Test earlier locally as needed; this is the delivery acceptance gate. |

The sequence does not turn basic test builds into the completed game. Report actual supported features at each release. Hoenn remains first, with one to four total players including the host.

The owner subsequently asked to handle all seven together. Run independent implementation, research, and tests in parallel without asking for approval after each milestone; retain the dependent safety and acceptance gates. The [trade foundation record](trade-foundation.md) distinguishes implemented storage/transport from remaining playable trade work.

## Added feature placement

| Addition | Placement and boundaries |
| --- | --- |
| Trainer customization | Research and define the synchronized appearance contract now. Implement the creator and remote rendering after core multiplayer/four-client proof; complete before claiming the customization feature delivered. In the finished game, creation happens near the beginning, with later changes and optional cosmetic unlocks. Advanced Trainer Card work follows. |
| Player friendship and Lucky trades | Reserve compatible transaction/history hooks during safe trade design. Implement after ordinary trades are proven: pair persistence and meaningful progression, Lucky conversion and presentation, Best Friends/Lucky Friends, then Friends UI. It does not jump ahead of the owner's immediate multiplayer sequence or gate basic trades/teams. |
| Personal Shiny Charm | Establish encounter-source and personal-modifier boundaries alongside Local Soft Reset. Implement after Gen 6 shiny rules, personal encounter independence, and saves are verified. Research exact odds before enabling effects. |
| Game Corner reward | Later acquisition/content work: existing minigames, coins, and redemption components first; guaranteed purchase at a meaningful, later-balanced coin price. Multiplayer casino activities are optional. |
| Research and reuse | Applies before every major system, starting now. Check existing engine capabilities and current compatible projects, then record why integration/adaptation or custom work is selected. Never import a whole gameplay redesign just to reuse one component. |

Gen 1–6 roster restrictions, complete Gen 6 mechanics, 18 starters, eligible official Megas, randomized encounters/rarity, shinies, followers, Twin Gyms, events, Championship/wagers, custom four-way battles, and eventual additional regions remain on the full content backlog. Omission from the immediate seven-step list does not cancel them. Pull forward only the dependencies required for the selected milestone, and label partial coverage honestly.

## Decisions intentionally pending

The owner has selected host-loss saving/disconnection and waiting for every participant to reconnect after an interrupted battle; see [the save/recovery requirements](master-spec.md#saves-and-recovery). Those decisions replace the earlier undecided policies. Exact emergency preservation has separate actual-core evidence; combined-build coverage and durable battle resumption remain incomplete. Autosave is selected at five-minute intervals, enabled by default with a persistent per-character off switch and manual Save now retained. On October 8, frozen application `5a7afee` and combined native source `1a7a0cd` passed actual Windows Host/Join, the full five-minute interval, independent disabling, manual checkpoints and fresh Continue. A separate visible source-launched GUI check passed Host Game, the toggle, Save now and reopen; see [the exact evidence and limits](windows-launcher-gui.md#combined-native-save-and-visible-button-qualification). Measured pause performance, the packaged button path, complete first-character setup and separate-PC acceptance remain delivery gates.

No numerical friendship thresholds, Lucky odds or IV floor, Lucky eligibility/cooldowns, casino coin price, or final Charm odds are selected by this planning update. Secondary Lucky benefits, repeated Lucky conversion, the treatment of both sides of a Lucky trade, and IV changes that affect Hidden Power's type also require design/balance work. No existing gameplay rule may be changed for compatibility without first explaining the concrete conflict and obtaining the owner's decision.

Read the [reuse and customization audit](customization-and-reuse.md) before implementing the new features. Preserve the existing source/build pins and save profiles until a tested migration is ready.
