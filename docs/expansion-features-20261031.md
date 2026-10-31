# Emerald Expansion features report (2026-10-31)

The owner's request of 2026-10-31 asked, beside the item hub (`docs/item-hub-20261031.md`), for a separate report on the
Emerald Expansion: which of its features this game uses and which it does not. Researched on 2026-10-31 for the item hub's
proposal (engine `1abfe554`); updated the same day for what changed since (the TM catalogue, the owner's TM rule).
File and line references are to the engine at that commit.

Our engine **is** pokeemerald-expansion 1.17.1 (`include/constants/expansion.h:5-7,11`), and `expansion/1.17.1` is upstream's newest tag (`git ls-remote` of rh-hideout/pokeemerald-expansion, 2026-10-31); `include/constants/items.h` is byte-identical to upstream `master` and `upcoming` (sha256 `2d37d71f...`). Local changes to `src/data/items.h` are few: ball descriptions (Dream, Sport, Park, Cherish), the Ability Capsule's text, the Bottle Caps made usable for Hyper Training (upstream leaves them sell-only), Mega Stone money prices, the Coin Case text. Licensing: neither this tree nor upstream `master` has a licence file (checked 2026-10-31; `CREDITS.md` lists contributors); this proposal imports nothing, it only uses code already in the tree.

| Feature | In this build | Evidence (file:line) |
| --- | --- | --- |
| Rules generation | Gen 6 everywhere a switch follows GEN_LATEST | `include/config/general.h:75` `GEN_LATEST GEN_6`; e.g. `include/config/battle.h:5` crits, `:17` split Exp., `:46` paralysis, `:48` type matchups, `:73-74` move data and types; `include/config/item.h:6-23` |
| Mega Evolution | **On** (the only battle gimmick on PC); needs the Mega Ring in the Bag; Z-A Megas included | `include/config/species_enabled.h:23` `P_MEGA_EVOLUTIONS TRUE`, `:29` Gen 9 (Z-A) Megas; `src/battle_gimmick.c:39-48` PC: only `GIMMICK_MEGA` can activate; `src/battle_util.c:8701` Mega Ring check |
| Primal Reversion | **On** (Red/Blue Orb, RARE GOODS) | `species_enabled.h:24`; `src/battle_util.c:4962`; `src/data/pokemon/form_change_tables.h:738-739` |
| Z-Moves | **Off on PC**; no Z-Power Ring anywhere; 35 Z-Crystals unusable | `src/battle_gimmick.c:47`; `src/battle_z_move.c:118-122` (Z-Power Ring) |
| Ultra Burst | **Off on PC** (same gate; Necrozma not ownable) | `src/battle_gimmick.c:47`; `species_enabled.h:25` |
| Dynamax / Gigantamax | **Off**: forms present as data only | `include/config/battle.h:287` `B_FLAG_DYNAMAX_BATTLE 0`; `src/battle_dynamax.c:86-89`; `species_enabled.h:26`; PC gate `battle_gimmick.c:47` |
| Terastallization | **Off**: the orb can never be charged | `battle.h:288-289` flags 0, `:407` `B_TERA_ORB_ALWAYS_CHARGED FALSE`; `src/battle_terastal.c:63-65, 84-90`; `src/event_data.c:209-210` (`FlagGet(0)` is always FALSE); `species_enabled.h:27` |
| Form changes | **On**: item, held-item, battle and fusion changes (Rotom Catalog, Gracidea, Reveal Glass, DNA Splicers, Zygarde Cube, Prison Bottle, Meteorite, plates, Drives, Griseous Orb when held) | `src/data/pokemon/form_change_tables.h`; `species_enabled.h:32` fusions; `item.h:12` Griseous Orb rule (Gen 6: held changes form); tests `check-form-items`, `check-rotom-catalog` |
| Species | All generations' data compiled in, but a player can own only Gen 1-6 species and forms (729 species/forms from the wild pools, legend pool, gifts, trades and their evolutions; inferred by the generator's logic); Alolan/Galarian/Hisuian evolutions never happen here | `species_enabled.h:9-17`, `:35-39`; `tools/mp/gen_rare_goods.py:97-98, 295-323` |
| Abilities | The expansion's abilities with Gen 6 data | `battle.h:88` `B_UPDATED_ABILITY_DATA`; `include/config/pokemon.h:7` |
| Learnsets | Level-up learnsets of Gen 6; **TMs by the owner's Gen 1-6 rule (2026-10-31)**: a species learns a TM's move when a Gen 1-6 game taught it by TM, plus Ferroseed and Ferrothorn's Stealth Rock; tutors by the 2026-10-27 rule | `pokemon.h:14` `P_LVL_UP_LEARNSETS GEN_LATEST`; `src/data/pokemon/tm_learnsets_pc.h`, `teachable_learnsets_pc.h` |
| TMs and HMs | **Since 2026-10-31 (the TM catalogue): TM01-TM168**, every Gen 1-6 TM (TM01-TM50 Emerald's, TM51-TM100 the expansion's items with the catalogue's moves, TM101-TM168 items 874-941, PC only), HM01-HM08; TMs reusable on PC; TM51 and up kept in a save record | `include/constants/tms_hms.h`, `tms_hms_pc.h`; `include/config/item.h:26-30` `I_REUSABLE_TMS TRUE` (PC); `docs/tm-catalogue-20261031.md` |
| Move tutors | Emerald's tutors with the expansion's tutor data | `src/data/tutor_moves.h` |
| Held-item effects | Every hold effect an item uses has a handler (C or battle script); 131 GBA hold-effect test files | my reference count over `src/`, `include/`, `data/battle_scripts_*.s`; `test/battle/hold_effect/` |
| Item rules | Gen 6: healing amounts, gems x1.3, type boosters x1.2, Power items +4, Repels by the lead's level; the party Exp. Share always on | `item.h:8-23`; `src/battle_util.c:9782-9791` |
| Evolution methods | The expansion's methods and conditions (items, held items by time, trade, Linking Cord, defeat-with-item); friendship evolution at Gen 6's threshold | `pokemon.h:23`, `:38`; `src/pokemon.c:4480` |
| Overworld extras | Followers **on**; DexNav, HGSS Pokedex, berry mutations, mulch, item descriptions on pickup **off** | `include/config/overworld.h:61`, `:34`, `:38`, `:21`; `include/config/dexnav.h:4`; `include/config/pokedex_plus_hgss.h:4` |
| Item descriptions and icons | Every item has a description and an icon (TMs/HMs by pocket); TM51-TM168 are described by their moves (PC); placeholders left: three Legends Z-A foods ('?????') | `src/item_icon.c:157-171`; `src/data/items.h`; `src/item.c` `GetItemDescription` |

What could be reused: nothing is newer upstream at the item level. Present but off: DexNav, the HGSS Pokedex, berry mutations, mulch, ORAS dowsing (`item.h:51` `I_ORAS_DOWSING_FLAG 0`). Z-Moves, Dynamax and Terastallization stay off: the project is a Gen 6 game (`src/battle_gimmick.c:40-42` cites PROJECT_SPEC). Features the owner already asked for (learnsets and Switch Moves, TM compatibility, form moves) are other agents' work.

## Changed since the research (2026-10-31)

* The TM catalogue: TM01-TM168 (every Gen 1-6 TM), the owner's Gen 1-6 TM rule, the save record for TM51 and up
  (`docs/tm-catalogue-20261031.md`).
* The item hub: the Game Corner sells the RARE GOODS and 199 items found elsewhere in the owner's ten kinds
  (`docs/item-hub-20261031.md`). Nothing of the expansion was imported or switched on for either.
