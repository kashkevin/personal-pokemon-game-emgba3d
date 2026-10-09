# Additional personal static Local Soft Reset sources

This source-only batch extends the ten-source catalogue to twenty exact personal encounters. It adds Kyogre, Groudon, seven ordinary Devon Scope Kecleon objects and Lugia. **No build, automated test, GUI run or gameplay qualification was performed for these additions.** Existing accepted ROMs, manifests, packages, saves and private worlds are unchanged. Compile-time defaults are unchanged; the static catalogue still requires the existing `MP_LOCAL_RESET_STATIC` capability (or native `TESTING`).

The existing [durable admission and counter design](local-reset-durable-admission.md), [catalogue guards](local-reset-production-catalogue.md) and [classic control adapter](local-reset-classic-input.md) are reused. No source may bypass enrollment, exact connection/binding, personal ownership, protected party/inventory, first-action confirmation, the capture fence or the host's durable attempt receipt. No generation parameters, seed or requested shiny value are added to the protocol. The existing attempt ledger remains the authority for each descriptor; the new in-memory observations do not change native save layout or database schema.

## Exact added catalogue

Coordinates below are map coordinates at admission, before the unchanged native battle generator. All source IDs through `0x100A`, including Sudowoodo, retain their existing meaning.

| ID | Personal source | Native map / local object | Admission coordinate | Native level |
| --- | --- | --- | --- | --- |
| `0x100B` | Kyogre | `MarineCave_End` / 1 | 9,25 | 70 |
| `0x100C` | Groudon | `TerraCave_End` / 1 | 17,25 | 70 |
| `0x100D` | Route 120 Kecleon 1 | `Route120` / 37 | 20,11 | 30 |
| `0x100E` | Route 120 Kecleon 2 | `Route120` / 38 | 27,2 | 30 |
| `0x100F` | Route 120 Kecleon 3 | `Route120` / 39 | 4,77 | 30 |
| `0x1010` | Route 120 Kecleon 4 | `Route120` / 41 | 19,48 | 30 |
| `0x1011` | Route 120 Kecleon 5 | `Route120` / 40 | 7,51 | 30 |
| `0x1012` | Route 119 Kecleon 1 | `Route119` / 35 | 31,6 | 30 |
| `0x1013` | Route 119 Kecleon 2 | `Route119` / 36 | 25,15 | 30 |
| `0x1014` | Lugia | `NavelRock_Bottom` / 1 | 11,13 | 70 |

Native evidence is `include/multiplayer_static_reset.h`, the exact descriptors and guards in `src/multiplayer_static_reset.c`, and the map `map.json` object entries. Application `src/emerald_multiplayer/reset_protocol.py:SOURCES` names the same IDs. Both bounded request/reply checks in `bridge/mgba.lua` now end at `0x1014`. The host does not obtain authority to create arbitrary species from these labels.

## Weather legends

`data/maps/MarineCave_End/scripts.inc` and `data/maps/TerraCave_End/scripts.inc` retain their coordinate-triggered approach, affine animation, cry and native level-70 `setwildbattle`. Admission occurs after that approach and before generation. In addition to the existing exact map/object/coordinate/availability checks, these two descriptors require game completion, the matching native abnormal-weather location range, the source's front graphic and `VAR_TEMP_1 == 1`. The reset window rechecks the original weather location, weather step counter, weather-end variable and source trigger state. These checks do not extend the weather lifetime or write weather state.

An explicit admission refusal or consumed accepted reset reaches the authored neutral return before the original outcome branches. New special `MultiplayerStaticReset_ReturnWeatherSource` accepts only the still-present eligible local object outside battle, frees a still-owned approach affine matrix, restores its normal sprite/subsprite representation and moves that source object back three tiles to its native starting point. It preserves `VAR_TEMP_1 == 1`; the player must step onto the original trigger again for a fresh attempt. It never moves the player, respawns a missing object, clears a hide/defeat flag or restores a world/save snapshot. If the exact source is no longer eligible, it refuses to manufacture eligibility; the ordinary map lifecycle remains responsible for that changed state.

Normal catch, defeat, escape and teleport still execute the original native branches. In particular, the ordinary caught/defeated path retains `VAR_SHOULD_END_ABNORMAL_WEATHER` and `FLAG_DEFEATED_KYOGRE` / `FLAG_DEFEATED_GROUDON` updates. On-resume removal still occurs only for the original caught outcome. The neutral result remains the existing separate reset sentinel, not a fabricated caught/won result.

## Seven Devon Scope Kecleon objects

Only `data/scripts/kecleon.inc`'s seven ordinary Route 119/120 interactions are adapted. Each descriptor requires its native selector (`VAR_0x8009` 1 through 7), individual hide/completion flag, Devon Scope receipt and possession, exact Kecleon graphic and visible object after the existing reveal animation. Kecleon has no separate defeat flag in these scripts; its individual hide flag is the completion guard.

Admission follows the original Scope question/reveal/cry and precedes unchanged `setwildbattle SPECIES_KECLEON, 30`. The neutral return makes the current object visually invisible again and releases the interaction without setting its hide/completion flag or removing it. The next interaction uses the native Scope prompt/reveal again. Ordinary catch/removal, victory, run and teleport behavior stays intact. Steven's bridge/tutorial encounter and Fortree's fleeing object use different scripts and remain excluded.

## Personal Lugia

`data/maps/NavelRock_Bottom/scripts.inc` retains its camera shake, cry, native `seteventmon SPECIES_LUGIA, 70` and legendary battle setup. Admission is immediately before `seteventmon`. Eligibility additionally requires the existing ship-enable and arrived-at-Navel-Rock flags, Mystic Ticket possession, no caught/defeated/hide flag and the exact Lugia object. The generated-opponent guard also requires the native modern-fateful-encounter bit.

The neutral return releases the original interaction before caught/defeated/removal branches and writes no progression. Normal catch, defeat, escape and teleport remain native. No ticket, arrival, ship access or event unlock is granted; the player must legitimately reach this personal encounter. This does not add a shared legendary World Event.

## Reuse and exclusions

Implementation adapts the existing engine entry scripts, object APIs, normal generator and reset guards. Relevant pinned local source includes `src/event_object_movement.c` (`MovementAction_ClearAffineAnim`, `TryMoveObjectEventToMapCoords`, `ObjectEventTurn`), `src/pokemon.c`'s event-mon generator, `include/constants/weather.h`, and the map-specific resume/outcome callbacks. No external source or asset is imported and no dependency is added; existing engine licensing and attribution apply.

Maintained RHH scripts were read at exact revision `7b95be15d84a053948791ce91e5dec0b168947a5`: [Marine Cave](https://github.com/rh-hideout/pokeemerald-expansion/blob/7b95be15d84a053948791ce91e5dec0b168947a5/data/maps/MarineCave_End/scripts.inc), [shared Kecleon](https://github.com/rh-hideout/pokeemerald-expansion/blob/7b95be15d84a053948791ce91e5dec0b168947a5/data/scripts/kecleon.inc) and [Navel Rock Lugia](https://github.com/rh-hideout/pokeemerald-expansion/blob/7b95be15d84a053948791ce91e5dec0b168947a5/data/maps/NavelRock_Bottom/scripts.inc). Their native encounter and progression structure provides the reused foundation. This is an adaptation of existing project code, not a new reset-system implementation.

Ho-Oh, Mew, Deoxys and Southern Island are outside this particular expansion; their subsequent [source-only adapters](local-reset-ticket-sources.md) address approach/weather, chase restoration, completed-puzzle retry and the existing opposite-to-roamer species branch. Ordinary wild Pokémon, gifts, roamers and shared World Events remain excluded. No gameplay probabilities, cooldowns or ticket policies are invented.

## Source provenance and remaining verification

The source worktree is `/home/kevin/src/pokemon/engine-admission-cleanup-20261008-1`, on preserved base `aef47e4b28fd6d0e84376961e0cc6632996bb0be` with earlier additive changes. Before every edit, the seven affected native files and two application files were copied and SHA-256 recorded at private `/home/kevin/src/pokemon/static-reset-expansion-source-before-1`. Its `before-index.json`, `after-index.json` and `after/` snapshot preserve the exact delta independently of other agents' work.

Reviewable [phase6-expanded-static-local-reset.patch](../engine-patches/phase6-expanded-static-local-reset.patch) contains only the seven native files relative to that pre-edit snapshot. Its SHA-256 is `998624330329ae0f564875f975de8da35b060780ddc3ea9c41c2a64e5171e5f2`. It is additive to the existing cleanup, classic-input, starters and Sudowoodo patches; those artifacts are unchanged. Application changes are confined to the catalogue and the two Lua range bounds.

An independent source-only review found no concrete blocker in the weather object/affine restoration, exact Kecleon selector and visibility checks, Lugia event guard or preserved native outcome branches. That review performed no build or test.

All added-source compilation, runtime footprint, denial/cancellation behavior, counters, RNG behavior, normal catch/defeat and actual route replay remain **UNVERIFIED**. Future acceptance must use legitimately progressed private characters: ordinary source entry, No/Yes confirmation, repeat interaction, normal capture/defeat, save/checkpoint and fresh Continue. Weather expiry, Kecleon visual restoration, Lugia event metadata, pending-admission host loss and simultaneous personal encounters require explicit coverage. No such verification was run while testing is paused, and no old nine-source fixture or accepted multiplayer proof qualifies these new adapters.
