# Generation 6 foundation audit

Recorded October 7, 2026 against RHH `expansion/1.17.1`, commit `bb1093a7c72d3961d9a37d8e02ad2abc2c866682`, and the owner's Generation 6 update. This audit changes the recommendation and future acceptance criteria; it does not claim that the gameplay profile or additional content has been implemented.

## Retain the existing foundation

Keep the pinned RHH engine, Windows mGBA, and external server/companion architecture. RHH already contains the complete Gen 1–6 species data, Fairy typing and chart, Mega Evolution, generation-selectable battle/data settings, and newer Mega definitions. The update does not justify discarding the reproducible build or migrating to a less-tested native runtime. Networking and persistence remain the highest-risk work. Hoenn remains the only initial region. [Pinned release](https://github.com/rh-hideout/pokeemerald-expansion/releases/tag/expansion/1.17.1), [configuration](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/include/config/pokemon.h), [type data](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/src/data/types_info.h)

The standard species allowlist becomes National Pokédex 1–721. Forms need separate eligibility records, including every officially released Mega whose base species is eligible. Species-family generation switches alone do not enforce that boundary: older families can include later evolutions and regional forms. No later base species enters the roster solely because it has a Mega. There are 18 starter choices, including Chespin, Fennekin, and Froakie; duplicate selections remain legal. [Species switches](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/include/config/species_enabled.h)

## Generation 6 profile requirements

Create a versioned project ruleset after preserving the unchanged baseline. These are the exact upstream knobs to audit; changing one generation constant is insufficient:

| Area | Required settings or checks |
| --- | --- |
| Default generation | Set `GEN_LATEST = GEN_6` in `include/config/general.h`; record the resulting configuration hash. |
| Species data | `P_UPDATED_TYPES`, `P_UPDATED_STATS`, `P_UPDATED_ABILITIES`, `P_UPDATED_EGG_GROUPS`, `P_UPDATED_FRIENDSHIP`, `P_UPDATED_EVS`, and `P_UPDATED_EXP_YIELDS` must resolve to `GEN_6`. |
| Learnsets and evolution | `P_LVL_UP_LEARNSETS = GEN_6` selects ORAS data. Audit `P_EVOLUTION_LEVEL_1_LEARN`, `P_FRIENDSHIP_EVO_THRESHOLD`, and breeding settings. TM/tutor/egg acquisition must be checked separately against the chosen Gen 6 source; modern teachable data is not made historical merely by selecting ORAS level-up data. |
| Roster | Enable `P_GEN_1_POKEMON` through `P_GEN_6_POKEMON`; disable Gen 7–9 families. Keep `P_GEN_2_CROSS_EVOS`, `P_GEN_3_CROSS_EVOS`, `P_GEN_4_CROSS_EVOS`, and `P_GEN_6_CROSS_EVOS`; disable `P_GEN_8_CROSS_EVOS` and `P_GEN_9_CROSS_EVOS`. Enforce the National Dex allowlist in every acquisition path. |
| Mega forms | Keep `P_MEGA_EVOLUTIONS` and `P_GEN_9_MEGA_EVOLUTIONS` enabled. The latter governs Z-A/DLC Mega forms independently of the normal Gen 9 species switch. Validate each form and its eligible base. |
| Later forms and mechanics | Disable regional-form switches and `P_CAP_PIKACHU_FORMS`; disable `P_ULTRA_BURST_FORMS`, `P_GIGANTAMAX_FORMS`, and `P_TERA_FORMS`; make `P_SHOW_TERA_TYPE` resolve to `GEN_6`. Gen 5 Kyurem fusions must not be lost by disabling `P_FUSION_FORMS` indiscriminately. Primal Reversion remains a separate scope decision, rather than an assumed Mega. |

Sources: [general settings](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/include/config/general.h), [Pokémon settings](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/include/config/pokemon.h), [species settings](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/include/config/species_enabled.h).

Battle checks must cover `B_UPDATED_MOVE_DATA`, `B_UPDATED_MOVE_TYPES`, `B_UPDATED_MOVE_FLAGS`, `B_UPDATED_ABILITY_DATA`, `B_UPDATED_TYPE_MATCHUPS`, `B_PHYSICAL_SPECIAL_SPLIT`, and the individual generation settings. Gen 6 requires 1.5× critical damage, quarter Speed while paralyzed, half confusion self-hit chance, 1/8 burn damage, temporary ordinary ability weather, Gen 6 Steel/Fairy interactions, Hidden Power 60 power, and Gen 6 Mega turn order. `B_MEGA_EVO_TURN_ORDER` must preserve the pre-Mega Speed on its activation turn; `B_PARENTAL_BOND_DMG` and `B_ATE_MULTIPLIER` preserve the stronger Gen 6 values. Later Champions paralysis/freeze/Knock Off settings must remain Gen 6. [Battle configuration](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/include/config/battle.h)

Audit booleans such as `B_EXTRAPOLATED_MOVE_FLAGS` and `B_X_ITEMS_CROSSUSE`, which do not track `GEN_LATEST`, before claiming a faithful profile. Disable the actual Z-Move/Dynamax/Tera access paths, items, trainer gimmicks, and scripts: disabling their species forms does not disable the mechanics themselves. Fairy already has engine support, so the prior no-Fairy/Mega conflict is resolved. A ruleset test build must verify actual battle results, learnability, evolution, and prohibited acquisitions. [Battle configuration](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/include/config/battle.h), [gimmick checks](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/src/battle_util.c)

## Official later Megas and existing code coverage

Later Megas are released content by this audit date. The official Legends site says Mega Dimension is available; it identifies Raichu X/Y, Chimecho, Lucario Z, and Garchomp Z. The official base-game site identifies further eligible forms including Dragonite, Victreebel, Hawlucha, Malamar, the Kalos starter Megas, Meganium, Emboar, Feraligatr, and Eelektross. This is positive official evidence, not a complete enumerated catalogue. [Official DLC](https://legends.pokemon.com/en-us/dlc), [official Pokémon pages](https://legends.pokemon.com/en-us/story-world/pokemon)

The pinned source contains **84 Mega species records across the Gen 1–6 family files**: 48 original Mega records and 36 later records. The later records include separate male/female Meowstic records; this code count is not an independently verified count of distinct official Mega designs. The later records inspected are:

| Family file | Later Mega records already defined |
| --- | --- |
| [Gen 1](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/src/data/pokemon/species_info/gen_1_families.h) | Raichu X, Raichu Y, Clefable, Victreebel, Starmie, Dragonite |
| [Gen 2](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/src/data/pokemon/species_info/gen_2_families.h) | Meganium, Feraligatr, Skarmory |
| [Gen 3](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/src/data/pokemon/species_info/gen_3_families.h) | Chimecho, Absol Z, Froslass |
| [Gen 4](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/src/data/pokemon/species_info/gen_4_families.h) | Staraptor, Garchomp Z, Lucario Z, Heatran, Darkrai |
| [Gen 5](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/src/data/pokemon/species_info/gen_5_families.h) | Emboar, Excadrill, Scolipede, Scrafty, Eelektross, Chandelure, Golurk |
| [Gen 6](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/src/data/pokemon/species_info/gen_6_families.h) | Chesnaught, Delphox, Greninja, Pyroar, Floette, Meowstic male/female, Malamar, Barbaracle, Dragalge, Hawlucha, Zygarde |

Presence in RHH does not certify official stats, abilities, release eligibility, follower art, or every transformation requirement. Before Mega content implementation, create a dated per-form ledger of official release evidence, type/stats/ability, stone, prerequisite form, source implementation, and tests. Reconcile the whole official catalogue at that point, using released game evidence where publisher pages omit details. Announcements, leaks, and upstream placeholders cannot silently enter the approved catalogue. This outstanding content gate does not prevent the movement prototype.

Mega Zeraora, Mega Baxcalibur, and other Megas of later base species remain excluded from the normal roster; their existence does not change the 721-species boundary. [Official DLC examples](https://legends.pokemon.com/en-us/dlc)

## Adaptation conflicts requiring explicit treatment

| Conflict | Evidence and proposed handling |
| --- | --- |
| Dragonize's power boost | The official Champions press release gives Mega Feraligatr Normal-to-Dragon conversion with a **20%** boost. RHH uses the shared `B_ATE_MULTIPLIER` for Dragonize; Gen 6 therefore produces **30%**. Propose an ability-specific 20% exception. Do not change the global multiplier, which would alter Gen 6 Pixilate/Aerilate/Refrigerate. [Official ability description](https://asia-press.portal-pokemon.com/press-release/pokemon-champions_20260324/), [damage implementation](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/src/battle_util.c#L6645) |
| New abilities | Champions gives Mega Meganium **Mega Sol**, making its moves behave as in sunlight, and Mega Emboar **Mold Breaker**. RHH defines Mega Sol and newer abilities such as Aura Guard, Eelevate, Fire Mane, and Piercing Drill. Verify every official assignment and implement these as scoped Mega exceptions. RHH's presence alone does not certify official behavior. [Official Champions press](https://asia-press.portal-pokemon.com/press-release/pokemon-champions_20260324/), [species data](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/src/data/pokemon/species_info/gen_2_families.h) |
| Real-time Z Mega behavior | Official Z-A rules describe quicker actions and faster consumption of Mega Power. Gen 6 has neither action cooldowns nor a Mega Power gauge. Propose the official form, stats, typing, ability, and stone with ordinary Gen 6 duration/turn order and one allowance per trainer; document that adaptation before implementing it. Do not import timed Mega depletion or Z-Moves. [Official Lucario Z description](https://legends.pokemon.com/en-us/news/mega_lucario_z) |
| Prerequisite forms | Official HOME promotion associates Floettite with **Eternal Flower Floette**, not every Floette. RHH links Mega Zygarde from its **Complete** form; reaching Complete currently involves later Power Construct behavior. Record the permitted special pre-Mega forms and a faithful obtainability/transform policy before enabling these paths. No ordinary Floette-to-Mega or silent Gen 7 form mechanics. [Official HOME promotion](https://news.pokemon-home.com/en/page/716.html), [RHH form changes](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/src/data/pokemon/form_change_tables.h) |

RHH already has `HasTrainerUsedGimmick`, `SetGimmickAsActivated`, and multi-battle trainer ownership checks. This is useful starting infrastructure for one Mega per trainer, but four distinct human controllers must demonstrate separate allowances and persistent usage after fainting/replacement. Custom FFA still requires its own trainer-identity audit. [Gimmick implementation](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/src/battle_gimmick.c)

## Measured headroom and migration cost

The unchanged default build already includes the broader upstream roster and newer Mega data. Its two reproducible builds measured the following usage. These numbers come from this project, not an illustrative upstream installation log. [Baseline evidence](baseline-build.md)

| Region | Linked usage | Remaining region bytes |
| --- | --- | --- |
| EWRAM | 226,416 / 262,144 bytes | 35,728 |
| IWRAM | 28,376 / 32,768 bytes | 4,392 |
| ROM | 26,748,420 / 33,554,432 bytes | 6,806,012 |

EWRAM includes the 115,968-byte reserved heap; remaining region space does not report heap availability. IWRAM needs stack headroom. Runtime peak heap, remote actors, follower palettes, and networking buffers remain unmeasured. Disabling unused families may reclaim ROM space, but quantify that with the actual configured build. Gen 6 support does not imply a larger build than the current all-generation baseline.

Retaining the stack costs a configuration/content audit, representative Gen 6 tests, a form ledger, and deliberate save migration. The species switch file warns that roster changes alter Dex flags/save layout. Preserve existing player saves and version the species mapping, configuration, and save schema; test migrations on copies. A native port would additionally require new runtime builds and expansion/network/save compatibility work, without evidence that it resolves the current risk better. Keep that fallback for a demonstrated resource blocker. [Save-layout warning](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/include/config/species_enabled.h)

The next engineering milestone remains independent multiplayer movement and map/disconnect handling, followed by durable saves/rejoin. The 18-starter menu, encounter weighting, world-event Megas, and complete follower catalogue belong after these proofs. The existing baseline is preserved, and its pending interactive gameplay/save checks still need to pass before accepting `BASELINE_BUILD`.
