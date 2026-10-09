# October 9 connected-feature batch

This continuation adds **12 source-level features and improvements**. They are
implemented but **UNTESTED**; optional native trade preparation remains an
internal integration rather than completed public trade evolution. No tests,
builds, app imports, UI/game sessions, dependency installs, commits or private
save/world edits were performed. The existing download has not been updated.

| # | Addition | Implementation evidence and practical boundary |
| --- | --- | --- |
| 1 | Inspect both Pokémon before trade confirmation | `trade_menu.py`, `trade_inspection.py`, `TradeDesk.inspect`, `trade_protocol.py`: exact frozen pair's names, shiny state, nature, held item, OT, moves/PP, IVs, EVs, saved stats and ability slot. Selecting details never confirms. [Details and provenance](trade-offer-inspection.md). |
| 2 | Explain unavailable trade offers | `prepared_choices` and blocked-entry pages in `trade_menu.py`: eggs, mail, evolution and unsupported species/forms remain refused, with a readable reason and return to selection. [Details](trade-offer-inspection.md). |
| 3 | Prepare a complete native trade-effect save candidate | `trade_effect_session.py`, `trade_effect_candidate.py`, `trade_effect_source.py`, native `multiplayer_save.c` / `multiplayer_trade_effects.c`: optional held-native candidate windows plus complete independent equality/ownership validation. No canonical publication or live Flash write. [Protocol and native patch](native-trade-save-transport.md). |
| 4 | Resume interrupted full-candidate preparation | `HeldTradeEffectClient.prepare_save` / `resume_save`: retained original context, READY record, ribbon context and generation-specific evidence on the same original core with a valid host proposal. A proposal lost on restart/lease change refuses new preparation. Full public evolution recovery still depends on publication/history work. [Limits](native-trade-save-transport.md). |
| 5 | Deliver durable canceled-entry handoff evidence | `battle_admission_cleanup.py`, `battle_admission_host.py`, codecs and companion delivery: exact original successful HANDOFF and host HOLD acknowledgment, durable host/local acknowledgments and retry after loss. This records completed history; it cannot release a replacement core. [Protocol and limits](admission-terminal-handoff.md). |
| 6 | Reconcile Championship rematches after confirmed cleanup | `BattleAdmissionHost.terminal`, `Championships._reconcile`, server connection: all originals' affirmative unreserved terminal proof permits a canceled attempt and an explicitly requested rematch after restart. Missing evidence and uncertain issue intents still wait. [Details](admission-terminal-handoff.md). |
| 7 | Browse connected peers' cards in the launcher | `launcher_player_panel.py`: exact selected peer's public PvP/tournament counters and viewer/peer shared records, with My card navigation and private sections cleared. [Details](windows-player-interactions.md). |
| 8 | Manage teams from the launcher | `PlayerPanelController`, launcher worker/session: invite, accept, decline, cancel and leave using existing host rules and one-use snapshot actions. Each participant still chooses for themselves. [Details](windows-player-interactions.md). |
| 9 | Filter and inspect launcher battle history | `PlayerPanel` plus `record_views.py`: mode/outcome filters, exact participants/sides and original party counts in the latest-eight window. No fabricated dates or complete-archive search. [Details](windows-player-interactions.md). |
| 10 | Search and inspect launcher personal hunts | `PlayerPanel` / `record_views.py`: source-name search, started/unstarted filters, sorting, totals and full source details from the existing owner-only counters. Capture/shiny outcomes remain UNKNOWN. [Details](windows-player-interactions.md). |
| 11 | Filter native battle results | `player_menu.py`: all/1v1/2v2 and win/loss/draw, both-way paging, clear and refresh with a retained browsing snapshot. [Details](record-browsers.md). |
| 12 | Browse detailed personal hunts in-game | `player_menu.py`: complete selected source names, counts, filters, sorting, aggregate attempts/sources started and both-way paging within six native rows. Catalogue entries do not enable reset sources. [Details](record-browsers.md). |

All application paths in the table are under `src/emerald_multiplayer/` unless
stated otherwise. Native paths refer to the existing editable WSL engine
`/home/kevin/src/pokemon/engine-admission-cleanup-20261008-1`, base
`aef47e4b28fd6d0e84376961e0cc6632996bb0be`, incorporating RHH
`bb1093a7c72d3961d9a37d8e02ad2abc2c866682`. Application HEAD remains
`31e5bf93ec8fb24e7cf522908b540b318890d365`. These are uncommitted extensions,
not new accepted releases. No save schema or gameplay balance was changed.

The new menus reuse existing native mailbox/Tk controls, authenticated services
and strict parsers. Trade preparation adapts the pinned engine's existing
record/Dex/stat/ribbon logic. Recovery composes existing admission/HOLD/HANDOFF
receipts and original-identity fences. The earlier research and compatible
project comparison remain in `customization-and-reuse.md`; incorporated sources
and distribution limits remain in `dependency-ledger.md`. No new third-party
code, assets or runtime dependency was imported. Source reviews are evidence of
inspection only; behavior, performance and integration acceptance remain UNKNOWN.

Independent source reviews covered the native/bridge save transport, client
candidate equality, trade detail layout/record offsets, launcher action binding,
native record browsing and admission delivery/terminal reconciliation. Review
corrections removed a new network wait from the native-to-saver transfer and
added capability negotiation before sending the new handoff operation to an
older host. No remaining concrete source-review blocker was identified. These
reviews did not execute the software. The final private source snapshot receipt
is recorded in `../PROJECT_STATUS_AND_HANDOFF.md`.

## What remains before playable delivery

1. Connect evolution presentation and complete trustworthy handler history to
   atomic two-player effect/history publication. The conservative ordinary trade
   gate still excludes evolution species, eggs and mail.
2. Resolve uncertain pre-invitation issue intents only with affirmative durable
   evidence; preserve original-core battle recovery. Power-loss reconstruction
   and replacement-core battle recovery remain separate unsupported work.
3. Integrate release configuration for the 25 personal reset sources without
   treating catalogue presence as ordinary-route qualification.
4. Supply the owner's original game dump path/hash for the import patch, then
   finish release packaging. Accepted private package 7 remains preserved.
5. When the owner resumes verification, qualify the combined ordinary-input
   trading/battle/recovery/reset/autosave flows, then separate-PC Wi-Fi/Internet
   and first-time friend installation. No such acceptance is claimed now.
