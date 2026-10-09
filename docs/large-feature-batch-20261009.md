# October 9 extended implementation batch

This continues the previous [12-addition batch](feature-batch-20261009.md). The
owner asked for as many connected features as practical and explicitly kept
testing paused. The entries below group real workflows; individual buttons,
filters and validation checks are not counted as separate completed game systems.
All new behavior is **implemented but UNTESTED**, and internal trade preparation
is still **partial integration**, not public effectful trading.

## Added source and its limits

Application paths below are relative to `src/emerald_multiplayer/`.

| Added workflow | Source evidence | Practical boundary |
| --- | --- | --- |
| Launcher 1v1 challenges | `launcher_battle_panel.py::BattlePanelController`, `launcher_session.py`, `launcher_gui.py` | Review a connected opponent, send a proposal, inspect saved parties and consent, accept or decline an unstarted proposal. Enter battle remains explicit in the original native game. |
| Launcher full-party 2v2 challenges | The same controller's `_duos`, preview and `invite_multi` paths | Uses both current two-person teams and independent parties of up to six each. Changed teams/roster invalidate the review; every other participant must consent. No automatic Enter or battle moves. |
| Full personal battle archive | `battle_archive.py`, `battle_results.py::BattleResults.archive`, `battle_protocol.py`, `server.py` | Eight-row bounded pages beyond the former latest-eight window; filters cover format, outcome, recorded peer, same/opposite side and exact record number. Only the requesting participant's released results are returned. |
| In-game archive navigation | `record_menu.py`, `player_menu.py` | Six-row menus with older/newer pages, filters, refresh/clear, recorded sides and original party counts. Stable sequence watermarks prevent newly released records moving an open page. |
| Launcher archive navigation | `launcher_record_archive.py`, launcher worker/session | Battle filters plus direct record-number lookup, details and stable older/newer navigation. Browsing is explicit, session-bound and read-only. |
| Personal committed trade journal | `trade_archive.py`, protocol/server extension | Six-row pages of the actor's actual paired commits. Peer, instance and commit-number filters; own acknowledgment status is as of the read. Both pre/post checkpoint pairs and the original exact-swap fingerprint are verified. |
| Inspect historical sent/received Pokémon | `record_menu.py`, `launcher_record_archive.py`, `trade_inspection.py` | Both interfaces show original as-traded snapshots, including names, nature, item, OT, shiny state, moves/PP, IVs/EVs and saved stats. These are not current-ownership claims; reading never applies or acknowledges a trade. |
| Trace an instance through your trades | `NativeRecordMenu` trace action and launcher instance filter | Searches only the actor's own committed trade journal, not another player's private ownership or save history. |
| Personal hunt admission receipts | `reset_attempts.py::ResetAttempts.history`, `reset_history.py`, protocol/server | Exact request UUID, attempt, checkpoint revision and observed prior count; contiguous bounded pages, frozen head, first/latest receipts and separate current head. No invented timestamp, shiny, capture or generated-Pokémon result. |
| Hunt receipt browsers | `record_menu.py`, `player_menu.py`, `launcher_record_archive.py` | Select any of the 25 named sources and browse its own authenticated receipts in-game or in the launcher. A source name alone does not enable that encounter. |
| Exact installed reset-source availability | `reset_catalogue.py`, `reset_mailbox.py`, `CompanionConfig`, `scripts/multiplayer/generate_manifest.py`; native `gMultiplayerResetCatalogue` | A compiler-located immutable 24-byte descriptor reports compiled source bits and controls. Native ROM/hash validation binds it to the installed build; older manifests display UNKNOWN. Live eligibility still depends on the authored encounter. |
| Reset status and same-admission retry | `reset_session.py`, `launcher_reset_panel.py`, launcher worker/session | Displays host/native receipts separately and retries only the same request UUID on the same world/lease/core with an affirmative WAITING receipt. Does not create a new encounter, undo generation or reboot anything. |
| Personal hunt favorites and retained display choices | `launcher_display.py`, `launcher_player_panel.py` | Favorite sources, favorites-only view, hunt display/order and recent-history filters persist in a separate local preference file. No autosave-schema, character or game-balance change. An unreadable preference file is preserved. |
| Launcher accessibility and help | `launcher_display.py`, `launcher_gui.py` | Three text sizes, scoped keyboard shortcuts, scrollable panels, topic-based controls/connection/recovery/import help. Physical layout and keyboard behavior remain unverified. |
| Installed-file readiness action | `SessionWorker.start_installation_check`, `Installation.verify` | Explicit idle-only ROM/manifest/runtime comparison against package pins. The action has not been run in this batch; it supplies no missing game-import patch and is not gameplay qualification. |
| Held-native evolution move presentation | `trade_effect_choice.py`, `trade_effect_menu.py`, `trade_effect_session.py`; native opcode 29 and additive patch | Exact native move facts, protected slots, complete-name review, explicit replace/decline confirmation, durable decisions, candidate review and pause. Callable internal held preparation only; ordinary `NativeTradeMenu` does not enable it. [Details](native-trade-choice-presentation.md). |
| Approved legacy friendship initialization | `trade_friendship_migration.py`, `trade_friendship.py`, `storage.py`, `trade_storage.py`, both history digest encoders | Explicit verified-backup migration and same-database history use species Gen6 bases only for missing values, preserve observed/known values, record provenance, exclude eggs, and follow subsequent canonical commits atomically. Implemented but never run on private worlds. [Policy and boundaries](trade-friendship-migration.md). |

## Source review and preservation

Application HEAD remains `31e5bf93ec8fb24e7cf522908b540b318890d365` on
`codex/multiplayer-delivery`. Native edits remain in
`/home/kevin/src/pokemon/engine-admission-cleanup-20261008-1`, base
`aef47e4b28fd6d0e84376961e0cc6632996bb0be`, incorporating RHH
`bb1093a7c72d3961d9a37d8e02ad2abc2c866682`. No new commit, branch reset, dependency,
third-party code, imported art, accepted-build replacement or distribution was made.

The work adapts existing authenticated services, SQLite ledgers, native menu and
save mailboxes, pinned move/species facts and bundled Tk. Previous current-upstream
and compatible-project research is retained in [the reuse audit](customization-and-reuse.md),
[native effects audit](native-trade-effects.md), and [dependency ledger](dependency-ledger.md).
The existing source pin and license/attribution obligations remain unchanged.

Independent source review covered the native trade descriptor/codec, launcher
challenge controller, reset catalogue/history, native archives and friendship
migration/store hooks. Root reviewed the held client/menu and remaining launcher
connections after two helper agents reached usage limits. Review corrected the
archive's doubles mode (native mode 3) and rejected first pages that claim more
records but omit their continuation cursor. This is source inspection only.

No tests, builds, application imports, native execution, UI/game sessions,
dependency installs, commits or private save/world migrations were run. Private
source backup creation and read-only Git/source inspection are preservation
operations, not verification of gameplay. The final backup receipt is in
`../PROJECT_STATUS_AND_HANDOFF.md`; the preserved package 7 is unchanged.

## Remaining dependencies

1. **Public trade effects:** the ordinary path remains exact-swap. It still needs
   a selected GBA adaptation for Gen6 geographic handler refresh, trusted native
   recomputation integrated with atomic two-save/effect-history publication,
   recovery, and the complete evolution presentation. The migration policy is now
   selected and implemented; its runtime acceptance remains UNKNOWN.
2. **Battle/recovery integration:** all new launcher/archive paths need combined
   native integration acceptance. Uncertain Championship issue intents still
   require affirmative original evidence; they cannot silently create a replacement.
3. **Production reset configuration:** 25 source descriptors are present, but
   production source enabling remains off. Catalogue availability does not prove
   actual encounter eligibility or generated/captured/shiny outcomes.
4. **Windows distribution:** owner-provided import-patch inputs, final package,
   dependency/asset review and clean-machine installation remain unfinished.
5. **Acceptance when testing is resumed:** combined four actual clients, separate
   PCs, Wi-Fi/Internet, physical controls, interrupted interactions and five-minute
   autosaving. New archive/migration storage, memory and event-loop costs remain
   unmeasured. No new completed/verified milestone is asserted.

The larger content goals—additional regions, 2.5D presentation, roaming/following/
rideable Pokémon, customization, player friendship/Lucky trading, Charm rewards
and the remaining Gen6/event/campaign work—are not claimed complete by these menus
or ledgers. Their earlier status and dependencies remain in the master report.
