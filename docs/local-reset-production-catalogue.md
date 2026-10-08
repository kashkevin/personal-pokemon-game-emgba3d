# Production personal-encounter reset catalogue audit

This is a source audit and implementation proposal against combined engine `afd92ce3a12204873e2f06a77a7bf1717d04f53b`, retained by preview commit `bcb8ff837fcb333e72d5d84894bce7421e781ef2`. It does not enable a production encounter or establish actual-play acceptance. The [qualified development reset](local-soft-reset-design.md) remains first-action-only and default-off.

## Existing static sources

The following Hoenn scripts already create ordinary personal static encounters. Each candidate needs a compiled descriptor and its own script-return audit; a generic `setwildbattle` hook would affect unrelated encounters and miss `seteventmon` sources.

| Source under `data/maps` | Existing encounter | Required source-specific review |
| --- | --- | --- |
| `AncientTomb/scripts.inc:64`, `DesertRuins/scripts.inc:64`, `IslandCave/scripts.inc:97` | Registeel, Regirock, Regice, level 40 | Door prerequisites, exact local object, defeat/removal flags and resume callbacks. |
| `SkyPillar_Top/scripts.inc:49` | Rayquaza, level 70 | Sky Pillar state, object appearance, `FLAG_DEFEATED_RAYQUAZA`, caught removal on resume. |
| `MarineCave_End/scripts.inc:36`, `TerraCave_End/scripts.inc:36` | Kyogre, Groudon, level 70 | Cave availability, postbattle progression and dynamic cave lifecycle. |
| `NewMauville_Inside/scripts.inc:179,203,227` | Three distinct Voltorb objects, level 25 | Separate descriptor and `FLAG_DEFEATED_VOLTORB_n_NEW_MAUVILLE` for each object. |
| `AquaHideout_B1F/scripts.inc:32,56` | Two distinct Electrode objects, level 30 | Separate object/defeat flags, hideout access and native removal. |
| `Route120/scripts.inc:193` and shared invisible-object scripts | Kecleon, level 30 | Devon Scope interaction, object-specific visibility and scripted movement. Shared scripts need individual map/object identification. |
| `BattleFrontier_OutsideEast/scripts.inc:129` | Sudowoodo, level 40 | Watering prerequisite, exact field object and removal/defeat flow. |
| `FarawayIsland_Interior/scripts.inc:130` | Mew, level 30, `seteventmon` | Native search/grass movement, caught/defeated flags and ticket access. |
| `BirthIsland_Exterior/scripts.inc:83` | Deoxys, level 30, `seteventmon` | Puzzle state, form selection, caught/defeated flags and ticket access. |
| `NavelRock_Top/scripts.inc:58`, `NavelRock_Bottom/scripts.inc:54` | Ho-Oh/Lugia, level 70, `seteventmon` | Appearance animation, object restoration, individual flags and ticket access. |
| `SouthernIsland_Interior/scripts.inc:105,109` | Latios or Latias, level 50 with Soul Dew | Existing species branch, encounter/temp flags, camera/object sequence and ticket access. |

FRLG duplicate maps, roaming encounters, gifts, trainer/PvP/link battles, ordinary wild encounters and future shared World Events are outside this initial catalogue. Existing ticket encounters are only candidates for their native personal scripts; this audit neither unlocks tickets nor converts shared World Events into rerollable encounters.

## Minimal next implementation

Start with one exact New Mauville Voltorb object. Reuse the ordinary level/species generation and existing availability flag. A descriptor verifies the map, local object, species, level, absence of the object's defeated/captured state, ownership enrollment, current connection/binding and usable party. Begin immediately before native generation. An explicit accepted-reset branch immediately after native battle return must execute before the original defeat/capture/removal branches; it restores only the authored field interaction, never a character snapshot. Audit `MAP_SCRIPT_ON_RESUME` before enabling this path.

The first object's map-template index is native local ID **6**, at map coordinates **25,18**, using `NewMauville_Inside_EventScript_Voltorb1` and `FLAG_HIDE_NEW_MAUVILLE_VOLTORB_1`; IDs 7 and 8 are the other Voltorb objects. The resume script first reapplies existing blue/green barrier state and removes the talked-to object only for `B_OUTCOME_CAUGHT`. The adapter must preserve those barrier variables and return with the dedicated reset result before `FLAG_DEFEATED_VOLTORB_1_NEW_MAUVILLE` or the common removal script runs. These source findings narrow the candidate; they do not qualify its actual return behavior.

Keep the original generation, moves, IVs, shiny calculation, level, catch behavior and prerequisites unchanged. Preserve the existing first-action guard, confirmation, no rollback, connection checks and capture fence. Nonreset battle outcomes must execute the original script exactly. Entry effects that change protected inventory/party state remain ineligible rather than being undone.

Rayquaza illustrates why the return branch is mandatory: its ordinary script treats outcomes outside won/ran/teleported as progression, and other branches remove the object. A local quit disguised as an ordinary outcome can silently defeat or hide the target. Mew and Southern Island additionally change movement and encounter state before entry, making them poor first adapters.

## Counter/storage boundary

The development implementation uses global persistent vars `0x40F7–0x40FA` for a two-word attempt counter, magic and capture flag. Production descriptors cannot share those values or reinterpret existing development saves as species-specific history. Only 18 other persistent vars are named `VAR_UNUSED_*` before reference auditing, so a blanket two-word counter per encounter already needs a broader storage plan. Names alone do not establish that a variable is unused by scripts or configuration.

Reserve and reference-audit storage for the first descriptor, version it, and define how older saves remain compatible before enabling it. Broader durable attempts need the previously identified idempotent checkpoint/journal design; a RAM counter persisted only on the next ordinary Save is not crash-durable. No save layout, save ABI, canonical database schema, hunt probability or cooldown is changed by this proposal.

A textual reference audit across `include`, `src`, `data` and `test` found `0x40FB–0x40FF` only in the Hoenn unused-variable definitions and corresponding FRLG aliases (plus the range-end definition). Three of those words could hold one independently versioned two-word counter after explicit reservation and zero/magic validation. Dynamic variable access and alternate configurations still need review; this is a candidate allocation, not a reservation or a claim of complete cross-version save compatibility.

## Required evidence

Focused C tests should reject wrong map/object/species/prerequisites, changed binding, any committed action, entry-time protected mutations and captured/defeated targets; they should verify that No keeps the current roll, Yes does not restore RNG/character state, and original nonreset scripts retain their progression. Actual acceptance requires a legitimately progressed private save reaching the chosen object through ordinary gameplay, followed by reset/reinteraction, ordinary catch or defeat, save/checkpoint and fresh Continue. Current starter preparation saves do not supply that production acceptance. No debug warp, story-flag injection or downloaded commercial ROM is an acceptable substitute.

The existing [official pinned script sources](https://github.com/rh-hideout/pokeemerald-expansion/tree/bb1093a7c72d3961d9a37d8e02ad2abc2c866682/data/maps), native generator and prior maintained-upstream/community survey in the [reset design](local-soft-reset-design.md) provide the reused foundation. No new dependency is imported by this audit.
