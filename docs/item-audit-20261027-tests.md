# Item audit (2026-10-27): the expansion's item tests, file by file

The GBA test ROM's results for the item tests (`make check` on engine `000d7556`, this Linux machine, Gen 6 rules;
the summary and what it means: `docs/item-audit-20261027.md`, "Held items, battle items, Mega Stones in battle").
Each test's title in the `make check` log was looked up in the test files below. "To do" is a test the expansion has
not written yet (a placeholder title); "known failing" a test the expansion marks as failing; "assumption fail" a test
whose precondition does not hold in this build. A file with no tests points to another file, named in it.
A title printed twice counts once per file; a parametrized test's failure is printed with its parameter ("... 1/2").

## Held items in battle

| Test file | Passed | Failed | To do (not written upstream) | Other |
| --- | --- | --- | --- | --- |
| `test/battle/hold_effect/ability_shield.c` | 16 | 0 | 0 | - |
| `test/battle/hold_effect/absorb_bulb.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/adamant_orb.c` | 1 | 0 | 0 | - |
| `test/battle/hold_effect/adrenaline_orb.c` | 4 | 0 | 0 | - |
| `test/battle/hold_effect/air_balloon.c` | 10 | 1 | 0 | - |
| `test/battle/hold_effect/assault_vest.c` | 5 | 0 | 0 | - |
| `test/battle/hold_effect/attack_up.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/berserk_gene.c` | 12 | 0 | 0 | - |
| `test/battle/hold_effect/big_root.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/binding_band.c` | 2 | 0 | 1 | - |
| `test/battle/hold_effect/black_sludge.c` | 8 | 0 | 0 | - |
| `test/battle/hold_effect/blunder_policy.c` | 11 | 0 | 0 | - |
| `test/battle/hold_effect/booster_energy.c` | 13 | 0 | 0 | - |
| `test/battle/hold_effect/can_always_run.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/cell_battery.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/choice_band.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/choice_scarf.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/choice_specs.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/clear_amulet.c` | 4 | 0 | 0 | - |
| `test/battle/hold_effect/confuse_bitter.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/confuse_dry.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/confuse_sour.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/confuse_spicy.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/confuse_sweet.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/covert_cloak.c` | 7 | 0 | 0 | - |
| `test/battle/hold_effect/critical_up.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/cure_brn.c` | 0 | 0 | 0 | - |
| `test/battle/hold_effect/cure_confusion.c` | 0 | 0 | 0 | - |
| `test/battle/hold_effect/cure_frz.c` | 0 | 0 | 0 | - |
| `test/battle/hold_effect/cure_par.c` | 0 | 0 | 0 | - |
| `test/battle/hold_effect/cure_psn.c` | 0 | 0 | 0 | - |
| `test/battle/hold_effect/cure_slp.c` | 0 | 0 | 0 | - |
| `test/battle/hold_effect/cure_status.c` | 15 | 0 | 0 | - |
| `test/battle/hold_effect/custap_berry.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/damp_rock.c` | 1 | 0 | 0 | - |
| `test/battle/hold_effect/deep_sea_scale.c` | 2 | 0 | 0 | - |
| `test/battle/hold_effect/deep_sea_tooth.c` | 2 | 0 | 0 | - |
| `test/battle/hold_effect/defense_up.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/destiny_knot.c` | 5 | 0 | 0 | - |
| `test/battle/hold_effect/double_prize.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/drive.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/eject_button.c` | 13 | 0 | 0 | - |
| `test/battle/hold_effect/eject_pack.c` | 16 | 0 | 0 | - |
| `test/battle/hold_effect/enigma_berry.c` | 4 | 0 | 0 | - |
| `test/battle/hold_effect/evasion_up.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/eviolite.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/exp_share.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/expert_belt.c` | 2 | 0 | 0 | - |
| `test/battle/hold_effect/flame_orb.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/flinch.c` | 5 | 0 | 0 | - |
| `test/battle/hold_effect/float_stone.c` | 2 | 0 | 0 | - |
| `test/battle/hold_effect/focus_band.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/focus_sash.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/friendship_up.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/gems.c` | 5 | 0 | 0 | - |
| `test/battle/hold_effect/grip_claw.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/griseous_orb.c` | 1 | 0 | 0 | - |
| `test/battle/hold_effect/heat_rock.c` | 1 | 0 | 0 | - |
| `test/battle/hold_effect/heavy_duty_boots.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/icy_rock.c` | 2 | 0 | 0 | - |
| `test/battle/hold_effect/iron_ball.c` | 1 | 0 | 0 | - |
| `test/battle/hold_effect/jaboca_berry.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/kee_berry.c` | 5 | 0 | 0 | - |
| `test/battle/hold_effect/lagging_tail.c` | 1 | 0 | 0 | - |
| `test/battle/hold_effect/leek.c` | 1 | 0 | 0 | - |
| `test/battle/hold_effect/leftovers.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/life_orb.c` | 10 | 0 | 0 | - |
| `test/battle/hold_effect/light_ball.c` | 2 | 0 | 0 | - |
| `test/battle/hold_effect/light_clay.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/loaded_dice.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/lucky_egg.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/lucky_punch.c` | 1 | 0 | 0 | - |
| `test/battle/hold_effect/luminous_moss.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/lustrous_orb.c` | 1 | 0 | 0 | - |
| `test/battle/hold_effect/macho_brace.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/maranga_berry.c` | 5 | 0 | 0 | - |
| `test/battle/hold_effect/mega_stone.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/memory.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/mental_herb.c` | 8 | 0 | 0 | - |
| `test/battle/hold_effect/metal_powder.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/metronome.c` | 6 | 0 | 0 | - |
| `test/battle/hold_effect/micle_berry.c` | 5 | 0 | 0 | - |
| `test/battle/hold_effect/mirror_herb.c` | 9 | 0 | 0 | - |
| `test/battle/hold_effect/muscle_band.c` | 2 | 0 | 0 | - |
| `test/battle/hold_effect/ogerpon_mask.c` | 1 | 0 | 0 | - |
| `test/battle/hold_effect/plate.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/power_herb.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/power_item.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/prevent_evolve.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/primal_orb.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/protective_pads.c` | 5 | 0 | 0 | - |
| `test/battle/hold_effect/punching_glove.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/quick_claw.c` | 1 | 0 | 0 | - |
| `test/battle/hold_effect/quick_powder.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/random_stat_up.c` | 4 | 0 | 0 | - |
| `test/battle/hold_effect/red_card.c` | 26 | 0 | 0 | - |
| `test/battle/hold_effect/repel.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/resist_berry.c` | 4 | 0 | 0 | - |
| `test/battle/hold_effect/restore_hp.c` | 7 | 0 | 0 | - |
| `test/battle/hold_effect/restore_pct_hp.c` | 0 | 0 | 0 | - |
| `test/battle/hold_effect/restore_pp.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/ring_target.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/rocky_helmet.c` | 2 | 0 | 1 | - |
| `test/battle/hold_effect/room_service.c` | 1 | 0 | 0 | - |
| `test/battle/hold_effect/rowap_berry.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/safety_goggles.c` | 4 | 0 | 0 | - |
| `test/battle/hold_effect/scope_lens.c` | 1 | 0 | 0 | - |
| `test/battle/hold_effect/shed_shell.c` | 4 | 0 | 0 | - |
| `test/battle/hold_effect/shell_bell.c` | 15 | 0 | 0 | - |
| `test/battle/hold_effect/smooth_rock.c` | 1 | 0 | 0 | - |
| `test/battle/hold_effect/snowball.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/soul_dew.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/sp_attack_up.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/sp_defense_up.c` | 3 | 0 | 0 | - |
| `test/battle/hold_effect/speed_up.c` | 4 | 0 | 0 | - |
| `test/battle/hold_effect/sticky_barb.c` | 2 | 0 | 0 | - |
| `test/battle/hold_effect/terrain_extender.c` | 5 | 0 | 0 | - |
| `test/battle/hold_effect/terrain_seed.c` | 7 | 0 | 0 | - |
| `test/battle/hold_effect/thick_club.c` | 2 | 0 | 0 | - |
| `test/battle/hold_effect/throat_spray.c` | 10 | 0 | 0 | 1 assumption fail |
| `test/battle/hold_effect/toxic_orb.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/type_power.c` | 2 | 0 | 0 | - |
| `test/battle/hold_effect/utility_umbrella.c` | 2 | 0 | 0 | - |
| `test/battle/hold_effect/weakness_policy.c` | 1 | 0 | 1 | - |
| `test/battle/hold_effect/white_herb.c` | 8 | 2 | 0 | - |
| `test/battle/hold_effect/wide_lens.c` | 0 | 0 | 1 | - |
| `test/battle/hold_effect/wise_glasses.c` | 2 | 0 | 0 | - |
| `test/battle/hold_effect/z_crystal.c` | 0 | 0 | 0 | - |
| `test/battle/hold_effect/zoom_lens.c` | 2 | 0 | 0 | - |

## Items used in battle from the bag

| Test file | Passed | Failed | To do (not written upstream) | Other |
| --- | --- | --- | --- | --- |
| `test/battle/item_effect/cure_status.c` | 23 | 0 | 0 | - |
| `test/battle/item_effect/dire_hit.c` | 1 | 0 | 0 | - |
| `test/battle/item_effect/escape.c` | 3 | 0 | 0 | - |
| `test/battle/item_effect/heal_and_cure_status.c` | 6 | 0 | 0 | - |
| `test/battle/item_effect/increase_stat.c` | 14 | 0 | 0 | - |
| `test/battle/item_effect/poke_flute.c` | 2 | 0 | 0 | - |
| `test/battle/item_effect/restore_hp.c` | 11 | 0 | 0 | - |
| `test/battle/item_effect/restore_pp.c` | 4 | 0 | 2 | - |
| `test/battle/item_effect/revive.c` | 13 | 0 | 0 | - |
| `test/battle/item_effect/set_mist.c` | 1 | 0 | 0 | - |
| `test/battle/item_effect/throw_ball.c` | 0 | 0 | 4 | - |

## Moves that use or move items

| Test file | Passed | Failed | To do (not written upstream) | Other |
| --- | --- | --- | --- | --- |
| `test/battle/move_effect/belch.c` | 6 | 0 | 0 | - |
| `test/battle/move_effect/bestow.c` | 9 | 0 | 0 | - |
| `test/battle/move_effect/corrosive_gas.c` | 6 | 0 | 0 | - |
| `test/battle/move_effect/embargo.c` | 17 | 0 | 0 | 1 known failing |
| `test/battle/move_effect/fling.c` | 24 | 0 | 0 | - |
| `test/battle/move_effect/knock_off.c` | 34 | 0 | 0 | - |
| `test/battle/move_effect/magic_room.c` | 2 | 0 | 1 | - |
| `test/battle/move_effect/natural_gift.c` | 4 | 0 | 1 | - |
| `test/battle/move_effect/poltergeist.c` | 5 | 0 | 0 | - |
| `test/battle/move_effect/recycle.c` | 0 | 0 | 1 | - |
| `test/battle/move_effect/stuff_cheeks.c` | 7 | 0 | 0 | - |
| `test/battle/move_effect/teatime.c` | 12 | 0 | 0 | - |
| `test/battle/move_effect/trick.c` | 14 | 0 | 0 | - |

## Abilities that use or move items

| Test file | Passed | Failed | To do (not written upstream) | Other |
| --- | --- | --- | --- | --- |
| `test/battle/ability/ball_fetch.c` | 4 | 0 | 1 | - |
| `test/battle/ability/cheek_pouch.c` | 9 | 0 | 0 | - |
| `test/battle/ability/frisk.c` | 4 | 0 | 0 | - |
| `test/battle/ability/gluttony.c` | 0 | 0 | 1 | - |
| `test/battle/ability/harvest.c` | 15 | 0 | 0 | - |
| `test/battle/ability/klutz.c` | 0 | 0 | 1 | - |
| `test/battle/ability/magician.c` | 12 | 0 | 0 | - |
| `test/battle/ability/pickpocket.c` | 22 | 0 | 0 | 1 known failing |
| `test/battle/ability/pickup.c` | 16 | 0 | 0 | - |
| `test/battle/ability/sticky_hold.c` | 3 | 0 | 0 | - |
| `test/battle/ability/symbiosis.c` | 12 | 0 | 0 | - |
| `test/battle/ability/unburden.c` | 11 | 0 | 0 | - |
| `test/battle/ability/unnerve.c` | 7 | 0 | 0 | - |

## Mega Evolution and Primal Reversion (Mega Stones, the orbs)

| Test file | Passed | Failed | To do (not written upstream) | Other |
| --- | --- | --- | --- | --- |
| `test/battle/form_change/mega_evolution.c` | 14 | 0 | 0 | - |
| `test/battle/form_change/mega_every_form.c` | 8 | 0 | 0 | - |
| `test/battle/form_change/mega_evolution_multi.c` | 2 | 0 | 0 | - |
| `test/battle/form_change/mega_rules.c` | 16 | 0 | 0 | 1 known failing |
| `test/battle/form_change/primal_reversion.c` | 15 | 0 | 0 | - |

## The bag (sorting, pockets)

| Test file | Passed | Failed | To do (not written upstream) | Other |
| --- | --- | --- | --- | --- |
| `test/bag.c` | 3 | 0 | 0 | - |
