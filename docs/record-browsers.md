# Native battle and personal hunt browsers

October 9, 2026 source implementation only. No tests, builds, application imports
or UI/game sessions were run; runtime correctness and presentation are **UNKNOWN**.

`src/emerald_multiplayer/record_views.py` provides pure, bounded projections of
already authenticated data. `player_menu.py` and `launcher_player_panel.py`
share them. They never open a database, change a Pokémon, submit an encounter,
award a reward or create a gameplay event.

## Recent battle browser

The native Players → Battles and records → Recent battle results page now has
format filters (all/1v1/2v2), personal outcome filters (all/win/loss/draw), forward
and backward navigation, filter clearing and explicit refresh. Selecting a
result shows its participant sides. Results retain their immutable battle ID;
navigation does not become a rematch or an Enter command.

Filters apply only to the existing host API's latest eight completed results.
They do not search the whole lifetime archive. Empty results therefore mean no
match in this retained window. The card's lifetime counts can legitimately be
larger. Native browsing freezes its history snapshot until refresh or re-entry;
the ordinary presence refresh does not keep replacing the selected record.
Results are validated with `battle_results.validate_result`; duplicate IDs or
sequences are refused. Win/loss is calculated from the viewer's original side,
including the alternating human slots in a 2v2.

## Personal hunt browser

The native card's hunt list now opens complete source names and individual
counters, navigates both ways, filters all/started/unstarted sources, sorts by
catalogue/most attempts/name, shows total admitted attempts and sources started,
and explicitly refreshes the owner's card. The launcher also has case-insensitive
source-name search and full selected-source explanations; see
`windows-player-interactions.md`.

The data remains the existing 25-row `ResetAttempts.summary` catalogue in
`reset_protocol.SOURCES`. Each row is validated against its exact source ID and
32-bit counter. Summed totals use Python integers without narrowing. Names come
from the authored source catalogue, not an inferred encounter map. A row with
zero attempts is not proof that an encounter is available, reachable or enabled
in the current native build. Counts mean durable admissions; the ledger has no
capture, shiny-success, timestamp or reset-success observation. The screens and
detail contract state these limits. No probabilities or source-enable flags
were changed.

## Compatibility and reuse

This is an extension of the already researched project-owned player menu,
Trainer Card and released-result/reset-ledger systems. It uses their existing
authenticated APIs and exact card schemas with no new wire fields, world/save
migration, imported code or external dependency. Native screens remain within
six rows and 25-column labels; full hunt names are available on detail pages.
The project's engine pins, license/attribution inventory and upstream reuse
analysis in `dependency-ledger.md` and `customization-and-reuse.md` remain the
baseline. No new rendering framework or battle/encounter implementation was
substituted. Performance remains unmeasured while execution is paused.

The private pre-edit menu snapshot is
`%LOCALAPPDATA%/PokemonPrivate/artifacts/handoff-audit/source-menu-batch-before-20261009-1`.
This preservation and source inspection do not establish gameplay acceptance.
