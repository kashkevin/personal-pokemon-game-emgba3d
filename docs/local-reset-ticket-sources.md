# Remaining authored personal ticket encounters

This source-only extension adds Ho-Oh, Mew, Deoxys and the two Southern Island species branches to the [previous twenty-source catalogue](local-reset-expanded-sources.md). The catalogue now contains twenty-five exact descriptors. **No build, test, GUI run or gameplay qualification was performed.** Existing default flags, accepted binaries, package pins, saves and private worlds are unchanged.

These are the engine's existing personal ticket encounters, not shared World Events. Native ship permissions and possession of the corresponding ticket/map remain prerequisites. No unlock, ticket, caught Pokémon, puzzle solution, roaming selection or new probability is granted. The existing authenticated durable attempt ledger, first-action reset window, independent native generation, protected ownership/party/inventory and capture fence remain mandatory.

| ID | Source | Exact native object at admission | Native generator |
| --- | --- | --- | --- |
| `0x1015` | Navel Rock Ho-Oh | `NavelRock_Top`, local 1 at 12,9 after approach | `seteventmon SPECIES_HO_OH, 70` |
| `0x1016` | Faraway Island Mew | `FarawayIsland_Interior`, local 1 at the retained chased X and chased Y minus 2 | `seteventmon SPECIES_MEW, 30` |
| `0x1017` | Birth Island Deoxys | `BirthIsland_Exterior`, local 2 at 15,10 after approach | `seteventmon SPECIES_DEOXYS_NORMAL, 30` |
| `0x1018` | Southern Island Latios | `SouthernIsland_Interior`, local 2 at 13,11; native roamer variable equals zero | `seteventmon SPECIES_LATIOS, 50, ITEM_SOUL_DEW` |
| `0x1019` | Southern Island Latias | Same exact object/position; native roamer variable is nonzero | `seteventmon SPECIES_LATIAS, 50, ITEM_SOUL_DEW` |

Each generated opponent must retain the native modern-fateful-encounter marker, exact source species/level and sole-opponent shape. The Southern Island guard additionally retains Soul Dew. Internal alternate Deoxys forms are not substituted or rerolled; the unchanged native script continues to choose Normal Forme. The two Lati IDs describe the existing opposite-to-roamer personal branch; the roaming encounter itself is excluded.

## Source-specific return behavior

**Ho-Oh:** The existing camera object is removed before admission. Its native animation has moved Ho-Oh from 12,4 to 12,9 and cleared the map's shade. Eligibility requires the original ship permission, arrived-at-Navel flag, Mystic Ticket, uncaught/undefeated visible source, exact graphic, `VAR_TEMP_1 == 1` and native weather-none state. A neutral return moves only that still-eligible source back to 12,4, restores the native approach trigger to zero and reapplies the map's original shade. The player must step onto the original coordinate trigger for a new approach. No player teleport, camera reconstruction or captured/defeated flag reset occurs.

**Mew:** Its source position is intentionally dynamic. Immediately after the original lock/face-player operation, before reveal/emergence, a new special captures only the exact local Mew object's chased coordinates, previous coordinates, elevation, facing, visibility and sprite priority/subsprite presentation, plus the native chase counter and temporary entry state. The source must be in native encounter grass, have the existing ship permission and Old Sea Map, and remain uncaught/undefeated. The native emergence then sets its chase counter to `0xFFFF` and moves Mew two tiles north; all four facing branches do this. Admission and reset recheck that exact captured destination and sentinel.

Mew's neutral return restores only this ephemeral source presentation and chase counter, leaving native pursuit logic to continue on the next player step. It closes the existing Mew text box before releasing the interaction, including pre-generation refusal. It never restores RNG, player position, character/save state or progression. The original emerging-grass sprite is destroyed before admission; its old index is deliberately never destroyed or reused by the return helper because battle return may have reused that slot. Ordinary outcomes discard the ephemeral anchor and retain the original won/run/player-teleport/Mew-teleport/caught handling.

**Deoxys:** Admission follows the existing completed-puzzle rock destruction, appearance, seven-tile approach and cry. The adapter requires the existing Birth Island permission, Aurora Ticket, solved-puzzle flag, final native rock level 10, removed triangle, original Normal Forme object at 15,10 and no battled/defeated result. The reset window also retains the puzzle step counter. Deoxys was explicitly spawned from a hidden map template; that hide flag remains set in native code and is required to remain set here.

A neutral return leaves Deoxys revealed and the completed puzzle intact. Its formerly empty object script now provides a guarded retry interaction only when the static-reset capability is compiled. Interacting again enters the same authenticated admission before generation; it does not repeat rock destruction, spawn a duplicate object, clear the puzzle solution or change form. With the capability disabled, the retry label ends immediately. Normal removal and battled/defeated flags still make the source unavailable. Leaving/reentering the map retains the engine's own puzzle transition policy.

**Southern Island:** Admission follows the native camera/approach sequence and precedes its unchanged species-selecting generator calls. The exact object, Eon Ticket/ship permission, native temporary encounter flag, permanent encounter flag, current species variable and opposite-to-roamer branch must match. As with Deoxys, the object was explicitly spawned from a hidden map template; its hide flag remains set.

A neutral return removes only that temporary object instance and clears `FLAG_TEMP_2` so the native stone interaction can replay. It does not write the template hide flag, permanent `FLAG_ENCOUNTERED_LATIAS_OR_LATIOS`, caught/defeated flags, roaming state, species variable or Soul Dew. The camera is already removed before admission. Normal catch, victory, escape and teleport keep their original progression/removal branches.

All return helpers refuse restoration if the exact source has become unavailable. They never clear progression to recreate eligibility or respawn a missing Pokémon. Such changed states fall back to the native map lifecycle.

## Reused code and provenance

This is an adaptation of the integrated engine's existing scripts and object APIs. Relevant local source is `src/multiplayer_static_reset.c`, its header and `data/specials.inc`; the four named map `scripts.inc` files; the Deoxys object's `BirthIsland_Exterior/map.json`; `src/faraway_island.c` (`SetMewAboveGrass`, pursuit and grass checks); `src/field_specials.c` (native eleven-position Deoxys puzzle); `src/field_effect.c` (rock removal); and `src/event_object_movement.c` (spawn versus removal flag semantics, object movement and sprite reconstruction).

Maintained upstream was read at exact revision `7b95be15d84a053948791ce91e5dec0b168947a5`: [Ho-Oh](https://github.com/rh-hideout/pokeemerald-expansion/blob/7b95be15d84a053948791ce91e5dec0b168947a5/data/maps/NavelRock_Top/scripts.inc), [Mew](https://github.com/rh-hideout/pokeemerald-expansion/blob/7b95be15d84a053948791ce91e5dec0b168947a5/data/maps/FarawayIsland_Interior/scripts.inc), [Deoxys](https://github.com/rh-hideout/pokeemerald-expansion/blob/7b95be15d84a053948791ce91e5dec0b168947a5/data/maps/BirthIsland_Exterior/scripts.inc), and [Southern Island](https://github.com/rh-hideout/pokeemerald-expansion/blob/7b95be15d84a053948791ce91e5dec0b168947a5/data/maps/SouthernIsland_Interior/scripts.inc). No external implementation, asset, dependency or new license obligation is incorporated; existing engine attribution remains applicable.

The worktree remains `/home/kevin/src/pokemon/engine-admission-cleanup-20261008-1`. Exact pre-edit copies of eight affected native files and two application files are preserved with SHA-256 at private `/home/kevin/src/pokemon/ticket-static-reset-source-before-1/before-index.json`. The application delta appends the five descriptors to `src/emerald_multiplayer/reset_protocol.py:SOURCES` and increases only the two Lua source bounds to `0x1019`. No ABI, counter schema or save-layout change is introduced.

The previous twenty-source patch remains intact. The new eight-file [phase6-ticket-static-local-reset.patch](../engine-patches/phase6-ticket-static-local-reset.patch) is additive to that exact before snapshot; SHA-256 is `174f2f5ce39964ccb1bc266a0f8618e407ea70784b4421cc182e66bb443b071c`. The private directory's `after-index.json` and `after/` preserve the resulting native/application bytes. There is no accepted binary for the new adapters.

An independent source-only review found no concrete blocker in the Mew chase/presentation anchor, Ho-Oh approach/weather return, Deoxys completed-puzzle retry or Southern Island temporary-object return. The review checked native object/spawn/remove helpers and preserved normal outcomes; it ran no tests or build.

## Still unverified

Compilation, memory/performance cost, all new denial/cancellation and counter paths, Mew's dynamic grass presentation across battle reload, Ho-Oh's weather transition, Deoxys retry and normal removal, both legitimate Southern Island branches, host-loss pending admission, native input, checkpoint/fresh Continue and simultaneous multiplayer operation remain **UNVERIFIED**. Future acceptance requires legitimately progressed private saves, native entry/reset/reinteraction/capture or defeat, and source-preservation evidence. No ticket injection, debug warp, puzzle bypass, downloaded commercial ROM or old fixture result can supply that acceptance.
