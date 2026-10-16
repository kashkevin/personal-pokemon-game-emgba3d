# Battle FX audit matrix (Update 27)

One row per move animation (a two-turn move has a row per turn) and per battle animation. Columns: **gameplay tests** = tests in `test/battle` that name the move (the GBA test ROM decides whether they pass); **triggered** = the game's animation ran to its end; **parity** = every compared frame of the game's effect sprites equals the Battle FX core's replay (`n/a` = a move past the package, played by the game's own animation); **HD layers** = HD frames drawn; **presentation** = `hd` (Battle FX) or `gba` (the game's own animation in the 3D view); **lit** = the captures differ from the stage without an effect (something was drawn). **Inspected by eye** and **real GPU** are *not* filled in by the tools: see the audit document.

| id | turn | tests | triggered | parity | HD layers | presentation | lit |
|---|---|---|---|---|---|---|---|
| B_ANIM_AFFECTION_HANGED_ON | 0 | 0 | yes | True | 42 | hd | 0.1025 |
| B_ANIM_AQUA_RING_HEAL | 0 | 0 | yes | True | 108 | hd | 0.0945 |
| B_ANIM_BALL_THROW | 0 | 0 | yes | None | 36 | hd | None |
| B_ANIM_BALL_THROW_WITH_TRAINER | 0 | 0 | yes | None | 61 | hd | None |
| B_ANIM_BEAK_BLAST_SETUP | 0 | 0 | yes | True | 144 | hd | 0.1256 |
| B_ANIM_CRITICAL_CAPTURE_THROW | 0 | 0 | yes | None | 42 | hd | None |
| B_ANIM_DYNAMAX_GROWTH | 0 | 0 | yes | True | 146 | hd | 0.1592 |
| B_ANIM_FOCUS_PUNCH_SETUP | 0 | 0 | yes | True | 216 | hd | 0.1122 |
| B_ANIM_FOG_CONTINUES | 0 | 0 | yes | True | 382 | hd | 0.8211 |
| B_ANIM_FORM_CHANGE | 0 | 0 | yes | True | 181 | hd | 0.1011 |
| B_ANIM_FORM_CHANGE_DISGUISE | 0 | 0 | yes | True | 25 | hd | 0.0996 |
| B_ANIM_FORM_CHANGE_INSTANT | 0 | 0 | yes | True | 8 | hd | 0.0903 |
| B_ANIM_GHOST_GET_OUT | 0 | 0 | yes | True | 544 | hd | 0.9975 |
| B_ANIM_GULP_MISSILE | 0 | 0 | yes | True | 62 | hd | 0.1053 |
| B_ANIM_HAIL_CONTINUES | 0 | 0 | yes | True | 88 | hd | 0.9331 |
| B_ANIM_HANGED_ON | 0 | 0 | yes | True | 216 | hd | 0.0994 |
| B_ANIM_HELD_ITEM_BERRY | 0 | 0 | yes | True | 110 | hd | 0.0961 |
| B_ANIM_HELD_ITEM_EFFECT | 0 | 0 | yes | True | 176 | hd | 0.109 |
| B_ANIM_ILLUSION_OFF | 0 | 0 | yes | True | 135 | hd | 0.1034 |
| B_ANIM_INGRAIN_HEAL | 0 | 0 | yes | True | 349 | hd | 0.0942 |
| B_ANIM_ITEM_KNOCKOFF | 0 | 0 | yes | True | 31 | hd | 0.1035 |
| B_ANIM_ITEM_STEAL | 0 | 0 | yes | True | 48 | hd | 0.0899 |
| B_ANIM_LEECH_SEED_DRAIN | 0 | 0 | yes | True | 107 | hd | 0.0995 |
| B_ANIM_LVL_UP | 0 | 0 | yes | True | 36 | hd | 0.1064 |
| B_ANIM_MAGIC_ROOM | 0 | 0 | yes | True | 279 | hd | 0.9808 |
| B_ANIM_MAX_SET_WEATHER | 0 | 0 | yes | True | 0 | hd | None |
| B_ANIM_MEGA_EVOLUTION | 0 | 0 | yes | True | 610 | hd | 0.9548 |
| B_ANIM_MON_HIT | 0 | 0 | yes | True | 13 | hd | 0.1079 |
| B_ANIM_MON_SCARED | 0 | 0 | yes | True | 133 | hd | 0.1303 |
| B_ANIM_MON_TO_SUBSTITUTE | 0 | 0 | yes | True | 42 | hd | 0.1731 |
| B_ANIM_POKEBLOCK_THROW | 0 | 0 | yes | True | 61 | hd | 0.1546 |
| B_ANIM_POWER_CONSTRUCT | 0 | 0 | yes | True | 625 | hd | 0.8185 |
| B_ANIM_PRIMAL_REVERSION | 0 | 0 | yes | True | 568 | hd | 0.9505 |
| B_ANIM_PROTECTED_ITSELF | 0 | 0 | yes | True | 22 | hd | 0.1661 |
| B_ANIM_RAINBOW | 0 | 0 | yes | True | 548 | hd | 0.9803 |
| B_ANIM_RAIN_CONTINUES | 0 | 0 | yes | True | 69 | hd | 0.7954 |
| B_ANIM_RESTORE_BG | 0 | 0 | yes | True | 0 | hd | 0.9835 |
| B_ANIM_ROCK_THROW | 0 | 0 | yes | True | 61 | hd | 0.1447 |
| B_ANIM_SAFARI_REACTION | 0 | 0 | yes | True | 28 | hd | 0.1116 |
| B_ANIM_SALT_CURE_DAMAGE | 0 | 0 | yes | True | 178 | hd | 0.0956 |
| B_ANIM_SANDSTORM_CONTINUES | 0 | 0 | yes | True | 309 | hd | 0.1749 |
| B_ANIM_SEA_OF_FIRE | 0 | 0 | yes | True | 223 | hd | 0.986 |
| B_ANIM_SHELL_TRAP_SETUP | 0 | 0 | yes | True | 93 | hd | 0.0996 |
| B_ANIM_SILPH_SCOPED | 0 | 0 | yes | True | 170 | hd | 0.1502 |
| B_ANIM_SIMPLE_HEAL | 0 | 0 | yes | True | 35 | hd | 0.1316 |
| B_ANIM_SLIDE_OFFSCREEN | 0 | 0 | yes | True | 17 | hd | 0.1235 |
| B_ANIM_SMOKEBALL_ESCAPE | 0 | 0 | yes | True | 73 | hd | 0.1203 |
| B_ANIM_SNATCH_MOVE | 0 | 0 | yes | True | 40 | hd | 0.1339 |
| B_ANIM_SNOW_CONTINUES | 0 | 0 | yes | True | 323 | hd | 0.0853 |
| B_ANIM_STATS_CHANGE | 0 | 0 | yes | True | 137 | hd | 0.1062 |
| B_ANIM_STATUS_BRN | 0 | 0 | yes | True | 70 | hd | 0.0565 |
| B_ANIM_STATUS_CONFUSION | 0 | 0 | yes | True | 179 | hd | 0.0557 |
| B_ANIM_STATUS_CURSED | 0 | 0 | yes | True | 99 | hd | 0.0592 |
| B_ANIM_STATUS_FRB | 0 | 0 | yes | True | 148 | hd | 0.0612 |
| B_ANIM_STATUS_FRZ | 0 | 0 | yes | True | 210 | hd | 0.0603 |
| B_ANIM_STATUS_INFATUATION | 0 | 0 | yes | True | 178 | hd | 0.0549 |
| B_ANIM_STATUS_NIGHTMARE | 0 | 0 | yes | True | 93 | hd | 0.0817 |
| B_ANIM_STATUS_PRZ | 0 | 0 | yes | True | 61 | hd | 0.0677 |
| B_ANIM_STATUS_PSN | 0 | 0 | yes | True | 124 | hd | 0.0556 |
| B_ANIM_STATUS_SLP | 0 | 0 | yes | True | 185 | hd | 0.0514 |
| B_ANIM_STRONG_WINDS | 0 | 0 | yes | True | 128 | hd | 0.1129 |
| B_ANIM_SUBSTITUTE_APPEAR | 0 | 0 | yes | True | 38 | hd | 0.0621 |
| B_ANIM_SUBSTITUTE_FADE | 0 | 0 | yes | True | 40 | hd | 0.0551 |
| B_ANIM_SUBSTITUTE_TO_MON | 0 | 0 | yes | True | 0 | hd | 0.1072 |
| B_ANIM_SUN_CONTINUES | 0 | 0 | yes | True | 233 | hd | 0.2793 |
| B_ANIM_SWAMP | 0 | 0 | yes | True | 344 | hd | 0.9254 |
| B_ANIM_SWAP_FROM_SUBSTITUTE | 0 | 0 | yes | True | 0 | hd | 0.1434 |
| B_ANIM_SWAP_TO_SUBSTITUTE | 0 | 0 | yes | True | 40 | hd | 0.1967 |
| B_ANIM_SWITCH_OUT_OPPONENT_MON | 0 | 0 | yes | None | 36 | hd | None |
| B_ANIM_SWITCH_OUT_PLAYER_MON | 0 | 0 | yes | None | 36 | hd | None |
| B_ANIM_SYRUP_BOMB_SPEED_DROP | 0 | 0 | yes | True | 140 | hd | 0.1021 |
| B_ANIM_TAILWIND | 0 | 0 | yes | True | 84 | hd | 0.9825 |
| B_ANIM_TERA_ACTIVATE | 0 | 0 | yes | True | 139 | hd | 0.7463 |
| B_ANIM_TERA_CHARGE | 0 | 0 | yes | True | 626 | hd | 0.9178 |
| B_ANIM_TOTEM_FLARE | 0 | 0 | yes | True | 244 | hd | 0.1281 |
| B_ANIM_TRICK_ROOM | 0 | 0 | yes | True | 281 | hd | 0.9833 |
| B_ANIM_TURN_TRAP | 0 | 0 | yes | True | 99 | hd | 0.1096 |
| B_ANIM_ULTRA_BURST | 0 | 0 | yes | True | 905 | hd | 0.9837 |
| B_ANIM_WISH_HEAL | 0 | 0 | yes | True | 82 | hd | 0.9813 |
| B_ANIM_WONDER_ROOM | 0 | 0 | yes | True | 276 | hd | 0.9897 |
| B_ANIM_ZMOVE_ACTIVATE | 0 | 0 | yes | True | 461 | hd | 0.9845 |
| MOVE_ABSORB | 0 | 46 | yes | True | 102 | hd | 0.0868 |
| MOVE_ACCELEROCK | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.1635 |
| MOVE_ACID | 0 | 5 | yes | True | 208 | hd | 0.0786 |
| MOVE_ACID_ARMOR | 0 | 6 | yes | True | 213 | hd | 0.0648 |
| MOVE_ACID_SPRAY | 0 | 2 | yes | True | 160 | hd | 0.1729 |
| MOVE_ACROBATICS | 0 | 8 | yes | True | 108 | hd | 0.9888 |
| MOVE_ACUPRESSURE | 0 | 35 | yes | True | 107 | hd | 0.0774 |
| MOVE_AERIAL_ACE | 0 | 32 | yes | True | 20 | hd | 0.0755 |
| MOVE_AEROBLAST | 0 | 0 | yes | True | 124 | hd | 0.9893 |
| MOVE_AFTER_YOU | 0 | 24 | yes | True | 75 | hd | 0.0968 |
| MOVE_AGILITY | 0 | 44 | yes | True | 113 | hd | 0.0684 |
| MOVE_AIR_CUTTER | 0 | 26 | yes | True | 72 | hd | 0.0908 |
| MOVE_AIR_SLASH | 0 | 9 | yes | True | 39 | hd | 0.9876 |
| MOVE_ALLURING_VOICE | 0 | 16 | yes | n/a (the game's own animation) | 0 | gba | 0.8306 |
| MOVE_ALLY_SWITCH | 0 | 66 | yes | True | 168 | hd | 0.9853 |
| MOVE_AMNESIA | 0 | 15 | yes | True | 306 | hd | 0.9849 |
| MOVE_ANCHOR_SHOT | 0 | 5 | yes | n/a (the game's own animation) | 0 | gba | 0.1382 |
| MOVE_ANCIENT_POWER | 0 | 1 | yes | True | 172 | hd | 0.1384 |
| MOVE_APPLE_ACID | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.1686 |
| MOVE_AQUA_CUTTER | 0 | 2 | yes | n/a (the game's own animation) | 0 | gba | 0.0814 |
| MOVE_AQUA_JET | 0 | 28 | yes | True | 187 | hd | 0.0894 |
| MOVE_AQUA_RING | 0 | 19 | yes | True | 173 | hd | 0.0652 |
| MOVE_AQUA_STEP | 0 | 2 | yes | n/a (the game's own animation) | 0 | gba | 0.1296 |
| MOVE_AQUA_TAIL | 0 | 3 | yes | True | 76 | hd | 0.0542 |
| MOVE_ARMOR_CANNON | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9848 |
| MOVE_ARM_THRUST | 0 | 11 | yes | True | 32 | hd | 0.1565 |
| MOVE_ARM_THRUST | 1 | 11 | yes | True | 24 | hd | 0.1519 |
| MOVE_AROMATHERAPY | 0 | 34 | yes | True | 744 | hd | 0.4122 |
| MOVE_AROMATIC_MIST | 0 | 3 | yes | True | 330 | hd | 0.6067 |
| MOVE_ASSIST | 0 | 12 | yes | True | 76 | hd | 0.1479 |
| MOVE_ASSURANCE | 0 | 87 | yes | True | 22 | hd | 0.9954 |
| MOVE_ASTONISH | 0 | 2 | yes | True | 70 | hd | 0.0941 |
| MOVE_ASTRAL_BARRAGE | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9843 |
| MOVE_ATTACK_ORDER | 0 | 0 | yes | True | 113 | hd | 0.1132 |
| MOVE_ATTRACT | 0 | 39 | yes | True | 380 | hd | 0.1603 |
| MOVE_AURA_SPHERE | 0 | 24 | yes | True | 221 | hd | 0.9955 |
| MOVE_AURA_WHEEL | 0 | 20 | yes | n/a (the game's own animation) | 0 | gba | 0.0966 |
| MOVE_AURORA_BEAM | 0 | 5 | yes | True | 261 | hd | 0.916 |
| MOVE_AURORA_VEIL | 0 | 45 | yes | n/a (the game's own animation) | 0 | gba | 0.9835 |
| MOVE_AUTOTOMIZE | 0 | 24 | yes | True | 33 | hd | 0.0492 |
| MOVE_AVALANCHE | 0 | 2 | yes | True | 256 | hd | 0.2373 |
| MOVE_AXE_KICK | 0 | 9 | yes | n/a (the game's own animation) | 0 | gba | 0.1333 |
| MOVE_BABY_DOLL_EYES | 0 | 7 | yes | True | 50 | hd | 0.7092 |
| MOVE_BADDY_BAD | 0 | 6 | yes | n/a (the game's own animation) | 0 | gba | 0.9926 |
| MOVE_BANEFUL_BUNKER | 0 | 31 | yes | n/a (the game's own animation) | 0 | gba | 0.151 |
| MOVE_BARB_BARRAGE | 0 | 8 | yes | n/a (the game's own animation) | 0 | gba | 0.1234 |
| MOVE_BARRAGE | 0 | 0 | yes | True | 55 | hd | 0.662 |
| MOVE_BARRIER | 0 | 2 | yes | True | 131 | hd | 0.1072 |
| MOVE_BATON_PASS | 0 | 99 | yes | True | 77 | hd | 0.9553 |
| MOVE_BEAK_BLAST | 0 | 44 | yes | n/a (the game's own animation) | 0 | gba | 0.1122 |
| MOVE_BEAT_UP | 0 | 61 | yes | True | 24 | hd | 0.18 |
| MOVE_BEAT_UP | 1 | 61 | yes | True | 21 | hd | 0.1722 |
| MOVE_BEHEMOTH_BASH | 0 | 2 | yes | n/a (the game's own animation) | 0 | gba | 0.9169 |
| MOVE_BEHEMOTH_BLADE | 0 | 2 | yes | n/a (the game's own animation) | 0 | gba | 0.9852 |
| MOVE_BELCH | 0 | 25 | yes | True | 200 | hd | 0.3017 |
| MOVE_BELLY_DRUM | 0 | 118 | yes | True | 129 | hd | 0.1488 |
| MOVE_BESTOW | 0 | 26 | yes | True | 50 | hd | 0.0645 |
| MOVE_BIDE | 0 | 40 | yes | True | 32 | hd | 0.0566 |
| MOVE_BIDE | 1 | 40 | yes | True | 288 | hd | 0.0906 |
| MOVE_BIND | 0 | 0 | yes | True | 80 | hd | 0.0774 |
| MOVE_BITE | 0 | 83 | yes | True | 14 | hd | 0.0764 |
| MOVE_BITTER_BLADE | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9831 |
| MOVE_BITTER_MALICE | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.1793 |
| MOVE_BLAST_BURN | 0 | 0 | yes | True | 212 | hd | 0.9805 |
| MOVE_BLAZE_KICK | 0 | 1 | yes | True | 131 | hd | 0.1142 |
| MOVE_BLAZING_TORQUE | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.9851 |
| MOVE_BLEAKWIND_STORM | 0 | 2 | yes | n/a (the game's own animation) | 0 | gba | 0.1774 |
| MOVE_BLIZZARD | 0 | 13 | yes | True | 547 | hd | 0.9969 |
| MOVE_BLOCK | 0 | 0 | yes | True | 241 | hd | 0.1205 |
| MOVE_BLOOD_MOON | 0 | 9 | yes | n/a (the game's own animation) | 0 | gba | 0.998 |
| MOVE_BLUE_FLARE | 0 | 1 | yes | True | 457 | hd | 0.9996 |
| MOVE_BODY_PRESS | 0 | 32 | yes | n/a (the game's own animation) | 0 | gba | 0.1024 |
| MOVE_BODY_SLAM | 0 | 28 | yes | True | 126 | hd | 0.1058 |
| MOVE_BOLT_BEAK | 0 | 23 | yes | n/a (the game's own animation) | 0 | gba | 0.1262 |
| MOVE_BOLT_STRIKE | 0 | 1 | yes | True | 373 | hd | 0.9889 |
| MOVE_BONEMERANG | 0 | 0 | yes | True | 95 | hd | 0.0853 |
| MOVE_BONE_CLUB | 0 | 1 | yes | True | 44 | hd | 0.9977 |
| MOVE_BONE_RUSH | 0 | 0 | yes | True | 24 | hd | 0.1594 |
| MOVE_BOOMBURST | 0 | 32 | yes | True | 127 | hd | 0.9829 |
| MOVE_BOUNCE | 0 | 33 | yes | True | 24 | hd | 0.0774 |
| MOVE_BOUNCE | 1 | 33 | yes | True | 37 | hd | 0.1014 |
| MOVE_BOUNCY_BUBBLE | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9856 |
| MOVE_BRANCH_POKE | 0 | 7 | yes | n/a (the game's own animation) | 0 | gba | 0.1112 |
| MOVE_BRAVE_BIRD | 0 | 1 | yes | True | 55 | hd | 0.9875 |
| MOVE_BREAKING_SWIPE | 0 | 16 | yes | n/a (the game's own animation) | 0 | gba | 0.1143 |
| MOVE_BRICK_BREAK | 0 | 35 | yes | True | 140 | hd | 0.9321 |
| MOVE_BRICK_BREAK | 1 | 35 | yes | True | 215 | hd | 0.9348 |
| MOVE_BRINE | 0 | 6 | yes | True | 139 | hd | 0.0748 |
| MOVE_BRUTAL_SWING | 0 | 11 | yes | n/a (the game's own animation) | 0 | gba | 0.9835 |
| MOVE_BUBBLE | 0 | 39 | yes | True | 320 | hd | 0.0714 |
| MOVE_BUBBLE_BEAM | 0 | 6 | yes | True | 341 | hd | 0.0815 |
| MOVE_BUG_BITE | 0 | 42 | yes | True | 26 | hd | 0.0857 |
| MOVE_BUG_BUZZ | 0 | 6 | yes | True | 118 | hd | 0.9832 |
| MOVE_BULK_UP | 0 | 4 | yes | True | 159 | hd | 0.1255 |
| MOVE_BULLDOZE | 0 | 36 | yes | True | 319 | hd | 0.6241 |
| MOVE_BULLET_PUNCH | 0 | 5 | yes | True | 30 | hd | 0.1512 |
| MOVE_BULLET_SEED | 0 | 60 | yes | True | 92 | hd | 0.0925 |
| MOVE_BURNING_BULWARK | 0 | 25 | yes | n/a (the game's own animation) | 0 | gba | 0.1314 |
| MOVE_BURNING_JEALOUSY | 0 | 10 | yes | n/a (the game's own animation) | 0 | gba | 0.0851 |
| MOVE_BURN_UP | 0 | 60 | yes | n/a (the game's own animation) | 0 | gba | 0.9853 |
| MOVE_BUZZY_BUZZ | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9538 |
| MOVE_CALM_MIND | 0 | 10 | yes | True | 157 | hd | 0.9984 |
| MOVE_CAMOUFLAGE | 0 | 14 | yes | True | 47 | hd | 0.0717 |
| MOVE_CAPTIVATE | 0 | 15 | yes | True | 88 | hd | 0.103 |
| MOVE_CEASELESS_EDGE | 0 | 18 | yes | n/a (the game's own animation) | 0 | gba | 0.9999 |
| MOVE_CELEBRATE | 0 | 2053 | yes | True | 77 | hd | 0.0622 |
| MOVE_CHARGE | 0 | 14 | yes | True | 178 | hd | 0.6481 |
| MOVE_CHARGE_BEAM | 0 | 11 | yes | True | 396 | hd | 0.8299 |
| MOVE_CHARM | 0 | 74 | yes | True | 106 | hd | 0.1526 |
| MOVE_CHATTER | 0 | 1 | yes | True | 52 | hd | 0.1199 |
| MOVE_CHILLING_WATER | 0 | 3 | yes | n/a (the game's own animation) | 0 | gba | 0.0796 |
| MOVE_CHILLY_RECEPTION | 0 | 28 | yes | n/a (the game's own animation) | 0 | gba | 0.0774 |
| MOVE_CHIP_AWAY | 0 | 8 | yes | True | 83 | hd | 0.0753 |
| MOVE_CHLOROBLAST | 0 | 22 | yes | n/a (the game's own animation) | 0 | gba | 0.9999 |
| MOVE_CIRCLE_THROW | 0 | 2 | yes | True | 224 | hd | 0.1971 |
| MOVE_CLAMP | 0 | 0 | yes | True | 22 | hd | 0.1635 |
| MOVE_CLANGING_SCALES | 0 | 14 | yes | n/a (the game's own animation) | 0 | gba | 0.9834 |
| MOVE_CLANGOROUS_SOUL | 0 | 23 | yes | n/a (the game's own animation) | 0 | gba | 0.1067 |
| MOVE_CLEAR_SMOG | 0 | 2 | yes | True | 525 | hd | 0.0913 |
| MOVE_CLOSE_COMBAT | 0 | 40 | yes | True | 58 | hd | 0.9984 |
| MOVE_COACHING | 0 | 24 | yes | n/a (the game's own animation) | 0 | gba | 0.107 |
| MOVE_COIL | 0 | 3 | yes | True | 148 | hd | 0.0907 |
| MOVE_COLLISION_COURSE | 0 | 3 | yes | n/a (the game's own animation) | 0 | gba | 0.9767 |
| MOVE_COMBAT_TORQUE | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.9835 |
| MOVE_COMET_PUNCH | 0 | 27 | yes | True | 13 | hd | 0.0765 |
| MOVE_COMET_PUNCH | 1 | 27 | yes | True | 13 | hd | 0.0834 |
| MOVE_COMEUPPANCE | 0 | 2 | yes | n/a (the game's own animation) | 0 | gba | 0.985 |
| MOVE_CONFIDE | 0 | 22 | yes | True | 134 | hd | 0.1669 |
| MOVE_CONFUSE_RAY | 0 | 99 | yes | True | 202 | hd | 0.9859 |
| MOVE_CONFUSION | 0 | 25 | yes | True | 102 | hd | 0.9897 |
| MOVE_CONSTRICT | 0 | 3 | yes | True | 128 | hd | 0.0712 |
| MOVE_CONVERSION | 0 | 5 | yes | True | 152 | hd | 0.1497 |
| MOVE_CONVERSION_2 | 0 | 14 | yes | True | 196 | hd | 0.1581 |
| MOVE_COPYCAT | 0 | 17 | yes | True | 167 | hd | 0.0618 |
| MOVE_CORE_ENFORCER | 0 | 16 | yes | n/a (the game's own animation) | 0 | gba | 0.9835 |
| MOVE_CORROSIVE_GAS | 0 | 12 | yes | n/a (the game's own animation) | 0 | gba | 0.9065 |
| MOVE_COSMIC_POWER | 0 | 5 | yes | True | 316 | hd | 0.9994 |
| MOVE_COTTON_GUARD | 0 | 3 | yes | True | 133 | hd | 0.1515 |
| MOVE_COTTON_SPORE | 0 | 13 | yes | True | 362 | hd | 0.1771 |
| MOVE_COUNTER | 0 | 65 | yes | True | 90 | hd | 0.1068 |
| MOVE_COURT_CHANGE | 0 | 27 | yes | n/a (the game's own animation) | 0 | gba | 0.9845 |
| MOVE_COVET | 0 | 15 | yes | True | 68 | hd | 0.089 |
| MOVE_CRABHAMMER | 0 | 1 | yes | True | 190 | hd | 0.1005 |
| MOVE_CRAFTY_SHIELD | 0 | 23 | yes | True | 345 | hd | 0.4108 |
| MOVE_CROSS_CHOP | 0 | 3 | yes | True | 59 | hd | 0.1671 |
| MOVE_CROSS_POISON | 0 | 1 | yes | True | 48 | hd | 0.0795 |
| MOVE_CRUNCH | 0 | 56 | yes | True | 44 | hd | 0.9978 |
| MOVE_CRUSH_CLAW | 0 | 1 | yes | True | 32 | hd | 0.2513 |
| MOVE_CRUSH_GRIP | 0 | 5 | yes | True | 97 | hd | 0.0864 |
| MOVE_CURSE | 0 | 34 | yes | True | 258 | hd | 0.9844 |
| MOVE_CURSE | 1 | 34 | yes | True | 321 | hd | 0.062 |
| MOVE_CUT | 0 | 5 | yes | True | 18 | hd | 0.0667 |
| MOVE_DARKEST_LARIAT | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.9982 |
| MOVE_DARK_PULSE | 0 | 5 | yes | True | 74 | hd | 0.998 |
| MOVE_DARK_VOID | 0 | 21 | yes | True | 492 | hd | 0.9875 |
| MOVE_DAZZLING_GLEAM | 0 | 8 | yes | True | 111 | hd | 0.9377 |
| MOVE_DECORATE | 0 | 9 | yes | n/a (the game's own animation) | 0 | gba | 0.7744 |
| MOVE_DEFEND_ORDER | 0 | 0 | yes | True | 277 | hd | 0.1371 |
| MOVE_DEFENSE_CURL | 0 | 21 | yes | True | 85 | hd | 0.0713 |
| MOVE_DEFOG | 0 | 64 | yes | True | 371 | hd | 0.9345 |
| MOVE_DESTINY_BOND | 0 | 41 | yes | True | 137 | hd | 0.9933 |
| MOVE_DETECT | 0 | 22 | yes | True | 165 | hd | 0.977 |
| MOVE_DIAMOND_STORM | 0 | 1 | yes | True | 386 | hd | 0.9787 |
| MOVE_DIG | 0 | 65 | yes | True | 358 | hd | 0.0588 |
| MOVE_DIG | 1 | 65 | yes | True | 110 | hd | 0.0793 |
| MOVE_DIRE_CLAW | 0 | 13 | yes | n/a (the game's own animation) | 0 | gba | 0.126 |
| MOVE_DISABLE | 0 | 30 | yes | True | 197 | hd | 0.1231 |
| MOVE_DISARMING_VOICE | 0 | 14 | yes | True | 68 | hd | 0.7902 |
| MOVE_DISCHARGE | 0 | 64 | yes | True | 430 | hd | 0.9347 |
| MOVE_DIVE | 0 | 33 | yes | True | 122 | hd | 0.1126 |
| MOVE_DIVE | 1 | 33 | yes | True | 154 | hd | 0.1243 |
| MOVE_DIZZY_PUNCH | 0 | 1 | yes | True | 126 | hd | 0.1004 |
| MOVE_DOODLE | 0 | 35 | yes | n/a (the game's own animation) | 0 | gba | 0.1171 |
| MOVE_DOOM_DESIRE | 0 | 2 | yes | True | 19 | hd | 0.8313 |
| MOVE_DOOM_DESIRE | 1 | 2 | yes | True | 94 | hd | 0.8889 |
| MOVE_DOUBLE_EDGE | 0 | 60 | yes | True | 182 | hd | 0.9412 |
| MOVE_DOUBLE_HIT | 0 | 17 | yes | True | 26 | hd | 0.0944 |
| MOVE_DOUBLE_IRON_BASH | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.0937 |
| MOVE_DOUBLE_KICK | 0 | 33 | yes | True | 15 | hd | 0.0665 |
| MOVE_DOUBLE_SHOCK | 0 | 30 | yes | n/a (the game's own animation) | 0 | gba | 0.9835 |
| MOVE_DOUBLE_SLAP | 0 | 16 | yes | True | 14 | hd | 0.0796 |
| MOVE_DOUBLE_SLAP | 1 | 16 | yes | True | 16 | hd | 0.08 |
| MOVE_DOUBLE_TEAM | 0 | 30 | yes | True | 246 | hd | 0.1715 |
| MOVE_DRACO_METEOR | 0 | 4 | yes | True | 365 | hd | 0.9859 |
| MOVE_DRAGON_ASCENT | 0 | 31 | yes | True | 119 | hd | 0.9814 |
| MOVE_DRAGON_BREATH | 0 | 16 | yes | True | 127 | hd | 0.1012 |
| MOVE_DRAGON_CHEER | 0 | 23 | yes | n/a (the game's own animation) | 0 | gba | 0.1398 |
| MOVE_DRAGON_CLAW | 0 | 35 | yes | True | 212 | hd | 0.0923 |
| MOVE_DRAGON_DANCE | 0 | 86 | yes | True | 213 | hd | 0.0798 |
| MOVE_DRAGON_DARTS | 0 | 83 | yes | n/a (the game's own animation) | 0 | gba | 0.0963 |
| MOVE_DRAGON_ENERGY | 0 | 2 | yes | n/a (the game's own animation) | 0 | gba | 0.999 |
| MOVE_DRAGON_HAMMER | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9987 |
| MOVE_DRAGON_PULSE | 0 | 12 | yes | True | 53 | hd | 0.9795 |
| MOVE_DRAGON_RAGE | 0 | 217 | yes | True | 277 | hd | 0.109 |
| MOVE_DRAGON_RUSH | 0 | 1 | yes | True | 147 | hd | 0.5652 |
| MOVE_DRAGON_TAIL | 0 | 71 | yes | True | 49 | hd | 0.11 |
| MOVE_DRAINING_KISS | 0 | 21 | yes | True | 141 | hd | 0.1571 |
| MOVE_DRAIN_PUNCH | 0 | 19 | yes | True | 61 | hd | 0.1093 |
| MOVE_DREAM_EATER | 0 | 31 | yes | True | 219 | hd | 0.9944 |
| MOVE_DRILL_PECK | 0 | 2 | yes | True | 120 | hd | 0.1052 |
| MOVE_DRILL_RUN | 0 | 2 | yes | True | 209 | hd | 0.9971 |
| MOVE_DRUM_BEATING | 0 | 6 | yes | n/a (the game's own animation) | 0 | gba | 0.1195 |
| MOVE_DUAL_CHOP | 0 | 3 | yes | True | 19 | hd | 0.1314 |
| MOVE_DUAL_WINGBEAT | 0 | 5 | yes | n/a (the game's own animation) | 0 | gba | 0.0889 |
| MOVE_DYNAMAX_CANNON | 0 | 4 | yes | n/a (the game's own animation) | 0 | gba | 0.9851 |
| MOVE_DYNAMIC_PUNCH | 0 | 3 | yes | True | 208 | hd | 0.2322 |
| MOVE_EARTHQUAKE | 0 | 299 | yes | True | 335 | hd | 0.5799 |
| MOVE_EARTH_POWER | 0 | 12 | yes | True | 344 | hd | 0.9942 |
| MOVE_ECHOED_VOICE | 0 | 54 | yes | True | 46 | hd | 0.1786 |
| MOVE_EERIE_IMPULSE | 0 | 8 | yes | True | 79 | hd | 0.1609 |
| MOVE_EERIE_SPELL | 0 | 12 | yes | n/a (the game's own animation) | 0 | gba | 0.997 |
| MOVE_EGG_BOMB | 0 | 3 | yes | True | 75 | hd | 0.1573 |
| MOVE_ELECTRIC_TERRAIN | 0 | 112 | yes | True | 388 | hd | 0.3042 |
| MOVE_ELECTRIFY | 0 | 71 | yes | True | 43 | hd | 0.0917 |
| MOVE_ELECTROWEB | 0 | 1 | yes | True | 56 | hd | 0.9901 |
| MOVE_ELECTRO_BALL | 0 | 25 | yes | True | 80 | hd | 0.072 |
| MOVE_ELECTRO_DRIFT | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9835 |
| MOVE_ELECTRO_SHOT | 0 | 23 | yes | n/a (the game's own animation) | 0 | gba | 0.9849 |
| MOVE_EMBARGO | 0 | 41 | yes | True | 282 | hd | 0.1425 |
| MOVE_EMBER | 0 | 204 | yes | True | 107 | hd | 0.0761 |
| MOVE_ENCORE | 0 | 103 | yes | True | 426 | hd | 0.9942 |
| MOVE_ENDEAVOR | 0 | 11 | yes | True | 90 | hd | 0.1616 |
| MOVE_ENDURE | 0 | 33 | yes | True | 233 | hd | 0.1398 |
| MOVE_ENERGY_BALL | 0 | 9 | yes | True | 85 | hd | 0.9738 |
| MOVE_ENTRAINMENT | 0 | 52 | yes | True | 312 | hd | 0.1724 |
| MOVE_ERUPTION | 0 | 11 | yes | True | 775 | hd | 0.6417 |
| MOVE_ESPER_WING | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.9852 |
| MOVE_ETERNABEAM | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9999 |
| MOVE_EXPANDING_FORCE | 0 | 13 | yes | n/a (the game's own animation) | 0 | gba | 0.984 |
| MOVE_EXPLOSION | 0 | 179 | yes | True | 323 | hd | 0.9854 |
| MOVE_EXTRASENSORY | 0 | 10 | yes | True | 197 | hd | 0.9956 |
| MOVE_EXTREME_SPEED | 0 | 25 | yes | True | 148 | hd | 0.9967 |
| MOVE_FACADE | 0 | 14 | yes | True | 140 | hd | 0.1718 |
| MOVE_FAIRY_LOCK | 0 | 9 | yes | True | 106 | hd | 0.6821 |
| MOVE_FAIRY_WIND | 0 | 5 | yes | True | 36 | hd | 0.7721 |
| MOVE_FAKE_OUT | 0 | 132 | yes | True | 66 | hd | 0.9236 |
| MOVE_FAKE_TEARS | 0 | 14 | yes | True | 44 | hd | 0.0785 |
| MOVE_FALSE_SURRENDER | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9969 |
| MOVE_FALSE_SWIPE | 0 | 53 | yes | True | 36 | hd | 0.1465 |
| MOVE_FEATHER_DANCE | 0 | 9 | yes | True | 83 | hd | 0.1197 |
| MOVE_FEINT | 0 | 6 | yes | True | 33 | hd | 0.1035 |
| MOVE_FEINT_ATTACK | 0 | 5 | yes | True | 110 | hd | 0.9863 |
| MOVE_FELL_STINGER | 0 | 9 | yes | True | 35 | hd | 0.9858 |
| MOVE_FICKLE_BEAM | 0 | 4 | yes | n/a (the game's own animation) | 0 | gba | 0.1256 |
| MOVE_FIERY_DANCE | 0 | 37 | yes | True | 444 | hd | 0.9986 |
| MOVE_FIERY_WRATH | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.9962 |
| MOVE_FILLET_AWAY | 0 | 14 | yes | n/a (the game's own animation) | 0 | gba | 0.1043 |
| MOVE_FINAL_GAMBIT | 0 | 44 | yes | True | 301 | hd | 0.9987 |
| MOVE_FIRE_BLAST | 0 | 3 | yes | True | 309 | hd | 0.9851 |
| MOVE_FIRE_FANG | 0 | 10 | yes | True | 129 | hd | 0.6281 |
| MOVE_FIRE_LASH | 0 | 2 | yes | n/a (the game's own animation) | 0 | gba | 0.1354 |
| MOVE_FIRE_PLEDGE | 0 | 143 | yes | True | 302 | hd | 0.1109 |
| MOVE_FIRE_PUNCH | 0 | 14 | yes | True | 265 | hd | 0.0944 |
| MOVE_FIRE_SPIN | 0 | 5 | yes | True | 188 | hd | 0.1218 |
| MOVE_FIRST_IMPRESSION | 0 | 21 | yes | n/a (the game's own animation) | 0 | gba | 0.1576 |
| MOVE_FISHIOUS_REND | 0 | 2 | yes | n/a (the game's own animation) | 0 | gba | 0.1167 |
| MOVE_FISSURE | 0 | 59 | yes | True | 480 | hd | 0.9926 |
| MOVE_FLAIL | 0 | 53 | yes | True | 65 | hd | 0.1494 |
| MOVE_FLAMETHROWER | 0 | 68 | yes | True | 250 | hd | 0.1361 |
| MOVE_FLAME_BURST | 0 | 20 | yes | True | 157 | hd | 0.1179 |
| MOVE_FLAME_CHARGE | 0 | 12 | yes | True | 242 | hd | 0.1808 |
| MOVE_FLAME_WHEEL | 0 | 16 | yes | True | 185 | hd | 0.195 |
| MOVE_FLARE_BLITZ | 0 | 26 | yes | True | 222 | hd | 0.9991 |
| MOVE_FLASH | 0 | 0 | yes | True | 80 | hd | 0.7863 |
| MOVE_FLASH_CANNON | 0 | 16 | yes | True | 164 | hd | 0.1022 |
| MOVE_FLATTER | 0 | 16 | yes | True | 332 | hd | 0.9933 |
| MOVE_FLEUR_CANNON | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.995 |
| MOVE_FLING | 0 | 157 | yes | True | 24 | hd | 0.063 |
| MOVE_FLIP_TURN | 0 | 21 | yes | n/a (the game's own animation) | 0 | gba | 0.0814 |
| MOVE_FLOATY_FALL | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.1354 |
| MOVE_FLORAL_HEALING | 0 | 4 | yes | n/a (the game's own animation) | 0 | gba | 0.1382 |
| MOVE_FLOWER_SHIELD | 0 | 13 | yes | True | 299 | hd | 0.5561 |
| MOVE_FLOWER_TRICK | 0 | 3 | yes | n/a (the game's own animation) | 0 | gba | 0.9934 |
| MOVE_FLY | 0 | 83 | yes | True | 42 | hd | 0.0813 |
| MOVE_FLY | 1 | 83 | yes | True | 75 | hd | 0.0843 |
| MOVE_FLYING_PRESS | 0 | 10 | yes | True | 183 | hd | 0.1741 |
| MOVE_FOCUS_BLAST | 0 | 26 | yes | True | 364 | hd | 0.9869 |
| MOVE_FOCUS_ENERGY | 0 | 29 | yes | True | 121 | hd | 0.1679 |
| MOVE_FOCUS_PUNCH | 0 | 65 | yes | True | 272 | hd | 0.9959 |
| MOVE_FOLLOW_ME | 0 | 32 | yes | True | 358 | hd | 0.1636 |
| MOVE_FORCE_PALM | 0 | 4 | yes | True | 56 | hd | 0.0882 |
| MOVE_FORESIGHT | 0 | 23 | yes | True | 83 | hd | 0.1599 |
| MOVE_FORESTS_CURSE | 0 | 23 | yes | True | 414 | hd | 0.9994 |
| MOVE_FOUL_PLAY | 0 | 14 | yes | True | 78 | hd | 0.9973 |
| MOVE_FREEZE_DRY | 0 | 12 | yes | True | 264 | hd | 0.9788 |
| MOVE_FREEZE_SHOCK | 0 | 1 | yes | True | 122 | hd | 0.1921 |
| MOVE_FREEZE_SHOCK | 1 | 1 | yes | True | 63 | hd | 0.9929 |
| MOVE_FREEZING_GLARE | 0 | 5 | yes | n/a (the game's own animation) | 0 | gba | 0.9851 |
| MOVE_FREEZY_FROST | 0 | 4 | yes | n/a (the game's own animation) | 0 | gba | 0.11 |
| MOVE_FRENZY_PLANT | 0 | 1 | yes | True | 188 | hd | 0.9152 |
| MOVE_FROST_BREATH | 0 | 11 | yes | True | 287 | hd | 0.998 |
| MOVE_FRUSTRATION | 0 | 7 | yes | True | 130 | hd | 0.1455 |
| MOVE_FURY_ATTACK | 0 | 5 | yes | True | 26 | hd | 0.0877 |
| MOVE_FURY_ATTACK | 1 | 5 | yes | True | 22 | hd | 0.0841 |
| MOVE_FURY_CUTTER | 0 | 39 | yes | True | 35 | hd | 0.1562 |
| MOVE_FURY_SWIPES | 0 | 22 | yes | True | 34 | hd | 0.0777 |
| MOVE_FUSION_BOLT | 0 | 15 | yes | True | 244 | hd | 0.9962 |
| MOVE_FUSION_FLARE | 0 | 16 | yes | True | 326 | hd | 0.996 |
| MOVE_FUTURE_SIGHT | 0 | 93 | yes | True | 165 | hd | 0.9925 |
| MOVE_FUTURE_SIGHT | 1 | 93 | yes | True | 216 | hd | 0.9946 |
| MOVE_GASTRO_ACID | 0 | 67 | yes | True | 54 | hd | 0.0722 |
| MOVE_GEAR_GRIND | 0 | 0 | yes | True | 25 | hd | 0.1695 |
| MOVE_GEAR_UP | 0 | 12 | yes | n/a (the game's own animation) | 0 | gba | 0.1575 |
| MOVE_GEOMANCY | 0 | 11 | yes | True | 139 | hd | 0.9846 |
| MOVE_GEOMANCY | 1 | 11 | yes | True | 86 | hd | 0.9849 |
| MOVE_GIGATON_HAMMER | 0 | 11 | yes | n/a (the game's own animation) | 0 | gba | 0.1092 |
| MOVE_GIGA_DRAIN | 0 | 13 | yes | True | 96 | hd | 0.8528 |
| MOVE_GIGA_IMPACT | 0 | 2 | yes | True | 239 | hd | 0.997 |
| MOVE_GLACIAL_LANCE | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9982 |
| MOVE_GLACIATE | 0 | 1 | yes | True | 271 | hd | 0.9982 |
| MOVE_GLAIVE_RUSH | 0 | 17 | yes | n/a (the game's own animation) | 0 | gba | 0.9835 |
| MOVE_GLARE | 0 | 1 | yes | True | 336 | hd | 0.9856 |
| MOVE_GLITZY_GLOW | 0 | 5 | yes | n/a (the game's own animation) | 0 | gba | 0.9859 |
| MOVE_GRASSY_GLIDE | 0 | 7 | yes | n/a (the game's own animation) | 0 | gba | 0.1005 |
| MOVE_GRASSY_TERRAIN | 0 | 73 | yes | True | 411 | hd | 0.2386 |
| MOVE_GRASS_KNOT | 0 | 9 | yes | True | 44 | hd | 0.0827 |
| MOVE_GRASS_PLEDGE | 0 | 103 | yes | True | 204 | hd | 0.0896 |
| MOVE_GRASS_WHISTLE | 0 | 0 | yes | True | 184 | hd | 0.0811 |
| MOVE_GRAVITY | 0 | 36 | yes | True | 146 | hd | 0.997 |
| MOVE_GRAV_APPLE | 0 | 14 | yes | n/a (the game's own animation) | 0 | gba | 0.9835 |
| MOVE_GROWL | 0 | 141 | yes | True | 64 | hd | 0.0813 |
| MOVE_GROWTH | 0 | 6 | yes | True | 128 | hd | 0.0708 |
| MOVE_GRUDGE | 0 | 23 | yes | True | 128 | hd | 0.9887 |
| MOVE_GUARD_SPLIT | 0 | 19 | yes | True | 140 | hd | 0.9945 |
| MOVE_GUARD_SWAP | 0 | 6 | yes | True | 60 | hd | 0.1171 |
| MOVE_GUILLOTINE | 0 | 4 | yes | True | 57 | hd | 0.9854 |
| MOVE_GUNK_SHOT | 0 | 3 | yes | True | 124 | hd | 0.9959 |
| MOVE_GUST | 0 | 64 | yes | True | 163 | hd | 0.077 |
| MOVE_GYRO_BALL | 0 | 6 | yes | True | 286 | hd | 0.1678 |
| MOVE_HAIL | 0 | 103 | yes | True | 245 | hd | 0.9372 |
| MOVE_HAMMER_ARM | 0 | 12 | yes | True | 159 | hd | 0.1318 |
| MOVE_HAPPY_HOUR | 0 | 4 | yes | True | 51 | hd | 0.0771 |
| MOVE_HARDEN | 0 | 39 | yes | True | 9 | hd | 0.0569 |
| MOVE_HARD_PRESS | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9933 |
| MOVE_HAZE | 0 | 26 | yes | True | 364 | hd | 0.2208 |
| MOVE_HEADBUTT | 0 | 109 | yes | True | 16 | hd | 0.0667 |
| MOVE_HEADLONG_RUSH | 0 | 3 | yes | n/a (the game's own animation) | 0 | gba | 0.9835 |
| MOVE_HEAD_CHARGE | 0 | 0 | yes | True | 73 | hd | 0.9847 |
| MOVE_HEAD_SMASH | 0 | 5 | yes | True | 260 | hd | 0.9966 |
| MOVE_HEALING_WISH | 0 | 42 | yes | True | 472 | hd | 0.7093 |
| MOVE_HEAL_BELL | 0 | 42 | yes | True | 428 | hd | 0.1372 |
| MOVE_HEAL_BLOCK | 0 | 40 | yes | True | 160 | hd | 0.1058 |
| MOVE_HEAL_ORDER | 0 | 0 | yes | True | 170 | hd | 0.0788 |
| MOVE_HEAL_PULSE | 0 | 16 | yes | True | 151 | hd | 0.0831 |
| MOVE_HEART_STAMP | 0 | 1 | yes | True | 34 | hd | 0.0996 |
| MOVE_HEART_SWAP | 0 | 0 | yes | True | 233 | hd | 0.4633 |
| MOVE_HEAT_CRASH | 0 | 3 | yes | True | 162 | hd | 0.1766 |
| MOVE_HEAT_WAVE | 0 | 16 | yes | True | 122 | hd | 0.2812 |
| MOVE_HEAVY_SLAM | 0 | 2 | yes | True | 376 | hd | 0.0911 |
| MOVE_HELPING_HAND | 0 | 46 | yes | True | 69 | hd | 0.0732 |
| MOVE_HEX | 0 | 13 | yes | True | 109 | hd | 0.9993 |
| MOVE_HIDDEN_POWER | 0 | 41 | yes | True | 288 | hd | 0.0982 |
| MOVE_HIGH_HORSEPOWER | 0 | 4 | yes | n/a (the game's own animation) | 0 | gba | 0.9964 |
| MOVE_HIGH_JUMP_KICK | 0 | 2 | yes | True | 98 | hd | 0.0851 |
| MOVE_HOLD_BACK | 0 | 0 | yes | True | 24 | hd | 0.17 |
| MOVE_HOLD_HANDS | 0 | 4 | yes | True | 111 | hd | 0.1568 |
| MOVE_HONE_CLAWS | 0 | 16 | yes | True | 50 | hd | 0.0586 |
| MOVE_HORN_ATTACK | 0 | 6 | yes | True | 22 | hd | 0.1309 |
| MOVE_HORN_DRILL | 0 | 6 | yes | True | 138 | hd | 0.9923 |
| MOVE_HORN_LEECH | 0 | 0 | yes | True | 61 | hd | 0.1728 |
| MOVE_HOWL | 0 | 28 | yes | True | 120 | hd | 0.1226 |
| MOVE_HURRICANE | 0 | 15 | yes | True | 277 | hd | 0.9966 |
| MOVE_HYDRO_CANNON | 0 | 1 | yes | True | 304 | hd | 0.9924 |
| MOVE_HYDRO_PUMP | 0 | 7 | yes | True | 71 | hd | 0.1378 |
| MOVE_HYDRO_STEAM | 0 | 9 | yes | n/a (the game's own animation) | 0 | gba | 0.9269 |
| MOVE_HYPERSPACE_FURY | 0 | 18 | yes | True | 129 | hd | 0.9957 |
| MOVE_HYPERSPACE_HOLE | 0 | 2 | yes | True | 99 | hd | 0.9438 |
| MOVE_HYPER_BEAM | 0 | 4 | yes | True | 280 | hd | 0.994 |
| MOVE_HYPER_DRILL | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9862 |
| MOVE_HYPER_FANG | 0 | 1 | yes | True | 58 | hd | 0.9966 |
| MOVE_HYPER_VOICE | 0 | 144 | yes | True | 202 | hd | 0.1478 |
| MOVE_HYPNOSIS | 0 | 68 | yes | True | 225 | hd | 0.9982 |
| MOVE_ICE_BALL | 0 | 3 | yes | True | 134 | hd | 0.1526 |
| MOVE_ICE_BEAM | 0 | 45 | yes | True | 301 | hd | 0.9777 |
| MOVE_ICE_BURN | 0 | 1 | yes | True | 148 | hd | 0.9945 |
| MOVE_ICE_BURN | 1 | 1 | yes | True | 97 | hd | 0.9987 |
| MOVE_ICE_FANG | 0 | 12 | yes | True | 68 | hd | 0.9748 |
| MOVE_ICE_HAMMER | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9969 |
| MOVE_ICE_PUNCH | 0 | 4 | yes | True | 275 | hd | 0.9762 |
| MOVE_ICE_SHARD | 0 | 8 | yes | True | 40 | hd | 0.1708 |
| MOVE_ICE_SPINNER | 0 | 17 | yes | n/a (the game's own animation) | 0 | gba | 0.1091 |
| MOVE_ICICLE_CRASH | 0 | 7 | yes | True | 93 | hd | 0.9933 |
| MOVE_ICICLE_SPEAR | 0 | 1 | yes | True | 29 | hd | 0.114 |
| MOVE_ICY_WIND | 0 | 23 | yes | True | 308 | hd | 0.9891 |
| MOVE_IMPRISON | 0 | 15 | yes | True | 255 | hd | 0.9858 |
| MOVE_INCINERATE | 0 | 23 | yes | True | 133 | hd | 0.1307 |
| MOVE_INFERNAL_PARADE | 0 | 8 | yes | n/a (the game's own animation) | 0 | gba | 0.9949 |
| MOVE_INFERNO | 0 | 5 | yes | True | 510 | hd | 0.9999 |
| MOVE_INFESTATION | 0 | 6 | yes | True | 135 | hd | 0.1808 |
| MOVE_INGRAIN | 0 | 38 | yes | True | 311 | hd | 0.1543 |
| MOVE_INSTRUCT | 0 | 82 | yes | n/a (the game's own animation) | 0 | gba | 0.1105 |
| MOVE_ION_DELUGE | 0 | 24 | yes | True | 301 | hd | 0.2654 |
| MOVE_IRON_DEFENSE | 0 | 35 | yes | True | 132 | hd | 0.8227 |
| MOVE_IRON_HEAD | 0 | 32 | yes | True | 62 | hd | 0.1212 |
| MOVE_IRON_TAIL | 0 | 3 | yes | True | 17 | hd | 0.0534 |
| MOVE_IVY_CUDGEL | 0 | 5 | yes | n/a (the game's own animation) | 0 | gba | 0.1207 |
| MOVE_JAW_LOCK | 0 | 11 | yes | n/a (the game's own animation) | 0 | gba | 0.983 |
| MOVE_JET_PUNCH | 0 | 4 | yes | n/a (the game's own animation) | 0 | gba | 0.1206 |
| MOVE_JUDGMENT | 0 | 24 | yes | True | 287 | hd | 0.8947 |
| MOVE_JUMP_KICK | 0 | 20 | yes | True | 20 | hd | 0.0895 |
| MOVE_JUNGLE_HEALING | 0 | 6 | yes | n/a (the game's own animation) | 0 | gba | 0.9835 |
| MOVE_KARATE_CHOP | 0 | 39 | yes | True | 19 | hd | 0.0909 |
| MOVE_KINESIS | 0 | 0 | yes | True | 407 | hd | 0.9866 |
| MOVE_KINGS_SHIELD | 0 | 31 | yes | True | 176 | hd | 0.0851 |
| MOVE_KNOCK_OFF | 0 | 121 | yes | True | 26 | hd | 0.6503 |
| MOVE_KOWTOW_CLEAVE | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9849 |
| MOVE_LANDS_WRATH | 0 | 0 | yes | True | 595 | hd | 0.9986 |
| MOVE_LASER_FOCUS | 0 | 16 | yes | n/a (the game's own animation) | 0 | gba | 0.9845 |
| MOVE_LASH_OUT | 0 | 28 | yes | n/a (the game's own animation) | 0 | gba | 0.0801 |
| MOVE_LAST_RESORT | 0 | 60 | yes | True | 200 | hd | 0.999 |
| MOVE_LAST_RESPECTS | 0 | 9 | yes | n/a (the game's own animation) | 0 | gba | 0.9835 |
| MOVE_LAVA_PLUME | 0 | 28 | yes | True | 171 | hd | 0.1512 |
| MOVE_LEAFAGE | 0 | 16 | yes | n/a (the game's own animation) | 0 | gba | 0.1407 |
| MOVE_LEAF_BLADE | 0 | 3 | yes | True | 91 | hd | 0.1311 |
| MOVE_LEAF_STORM | 0 | 11 | yes | True | 234 | hd | 0.8531 |
| MOVE_LEAF_TORNADO | 0 | 1 | yes | True | 195 | hd | 0.1381 |
| MOVE_LEECH_LIFE | 0 | 3 | yes | True | 149 | hd | 0.9645 |
| MOVE_LEECH_SEED | 0 | 57 | yes | True | 205 | hd | 0.0646 |
| MOVE_LEER | 0 | 77 | yes | True | 77 | hd | 0.0871 |
| MOVE_LICK | 0 | 23 | yes | True | 48 | hd | 0.1463 |
| MOVE_LIFE_DEW | 0 | 16 | yes | n/a (the game's own animation) | 0 | gba | 0.1574 |
| MOVE_LIGHT_OF_RUIN | 0 | 0 | yes | True | 99 | hd | 0.9906 |
| MOVE_LIGHT_SCREEN | 0 | 57 | yes | True | 147 | hd | 0.1753 |
| MOVE_LIQUIDATION | 0 | 11 | yes | n/a (the game's own animation) | 0 | gba | 0.1591 |
| MOVE_LOCK_ON | 0 | 20 | yes | True | 101 | hd | 0.1668 |
| MOVE_LOVELY_KISS | 0 | 0 | yes | True | 163 | hd | 0.0818 |
| MOVE_LOW_KICK | 0 | 16 | yes | True | 19 | hd | 0.0943 |
| MOVE_LOW_SWEEP | 0 | 1 | yes | True | 23 | hd | 0.0806 |
| MOVE_LUCKY_CHANT | 0 | 4 | yes | True | 336 | hd | 0.1585 |
| MOVE_LUMINA_CRASH | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.1021 |
| MOVE_LUNAR_BLESSING | 0 | 4 | yes | n/a (the game's own animation) | 0 | gba | 0.9994 |
| MOVE_LUNAR_DANCE | 0 | 16 | yes | True | 568 | hd | 0.987 |
| MOVE_LUNGE | 0 | 9 | yes | n/a (the game's own animation) | 0 | gba | 0.1526 |
| MOVE_LUSTER_PURGE | 0 | 1 | yes | True | 430 | hd | 0.9998 |
| MOVE_MACH_PUNCH | 0 | 38 | yes | True | 31 | hd | 0.9955 |
| MOVE_MAGICAL_LEAF | 0 | 4 | yes | True | 60 | hd | 0.1271 |
| MOVE_MAGICAL_TORQUE | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.985 |
| MOVE_MAGIC_COAT | 0 | 47 | yes | True | 130 | hd | 0.2203 |
| MOVE_MAGIC_POWDER | 0 | 12 | yes | n/a (the game's own animation) | 0 | gba | 0.1011 |
| MOVE_MAGIC_ROOM | 0 | 31 | yes | True | 283 | hd | 0.9821 |
| MOVE_MAGMA_STORM | 0 | 2 | yes | True | 320 | hd | 1.0 |
| MOVE_MAGNETIC_FLUX | 0 | 8 | yes | True | 73 | hd | 0.2038 |
| MOVE_MAGNET_BOMB | 0 | 0 | yes | True | 216 | hd | 0.0781 |
| MOVE_MAGNET_RISE | 0 | 23 | yes | True | 113 | hd | 0.2184 |
| MOVE_MAGNITUDE | 0 | 9 | yes | True | 236 | hd | 0.5156 |
| MOVE_MAKE_IT_RAIN | 0 | 17 | yes | n/a (the game's own animation) | 0 | gba | 0.1161 |
| MOVE_MALIGNANT_CHAIN | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.1397 |
| MOVE_MATCHA_GOTCHA | 0 | 20 | yes | n/a (the game's own animation) | 0 | gba | 0.1334 |
| MOVE_MAT_BLOCK | 0 | 5 | yes | True | 186 | hd | 0.0925 |
| MOVE_MEAN_LOOK | 0 | 18 | yes | True | 262 | hd | 0.9892 |
| MOVE_MEDITATE | 0 | 6 | yes | True | 158 | hd | 0.9849 |
| MOVE_MEGAHORN | 0 | 0 | yes | True | 156 | hd | 0.9885 |
| MOVE_MEGA_DRAIN | 0 | 14 | yes | True | 98 | hd | 0.541 |
| MOVE_MEGA_KICK | 0 | 15 | yes | True | 258 | hd | 0.9937 |
| MOVE_MEGA_PUNCH | 0 | 3 | yes | True | 269 | hd | 0.9935 |
| MOVE_MEMENTO | 0 | 87 | yes | True | 334 | hd | 0.1545 |
| MOVE_METAL_BURST | 0 | 31 | yes | True | 31 | hd | 0.059 |
| MOVE_METAL_CLAW | 0 | 23 | yes | True | 58 | hd | 0.1516 |
| MOVE_METAL_SOUND | 0 | 0 | yes | True | 57 | hd | 0.1116 |
| MOVE_METEOR_ASSAULT | 0 | 17 | yes | n/a (the game's own animation) | 0 | gba | 0.898 |
| MOVE_METEOR_BEAM | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9843 |
| MOVE_METEOR_MASH | 0 | 5 | yes | True | 243 | hd | 0.9941 |
| MOVE_METRONOME | 0 | 18 | yes | True | 65 | hd | 0.0704 |
| MOVE_ME_FIRST | 0 | 24 | yes | True | 199 | hd | 0.0932 |
| MOVE_MIGHTY_CLEAVE | 0 | 7 | yes | n/a (the game's own animation) | 0 | gba | 0.9835 |
| MOVE_MILK_DRINK | 0 | 0 | yes | True | 245 | hd | 0.1795 |
| MOVE_MIMIC | 0 | 12 | yes | True | 157 | hd | 0.0656 |
| MOVE_MIND_BLOWN | 0 | 36 | yes | n/a (the game's own animation) | 0 | gba | 0.9926 |
| MOVE_MIND_READER | 0 | 2 | yes | True | 77 | hd | 0.8325 |
| MOVE_MINIMIZE | 0 | 12 | yes | True | 78 | hd | 0.1368 |
| MOVE_MIRACLE_EYE | 0 | 20 | yes | True | 107 | hd | 0.9955 |
| MOVE_MIRROR_COAT | 0 | 59 | yes | True | 84 | hd | 0.1125 |
| MOVE_MIRROR_MOVE | 0 | 21 | yes | True | 0 | hd | 0.137 |
| MOVE_MIRROR_SHOT | 0 | 1 | yes | True | 281 | hd | 0.5467 |
| MOVE_MIST | 0 | 36 | yes | True | 206 | hd | 0.0867 |
| MOVE_MISTY_EXPLOSION | 0 | 16 | yes | n/a (the game's own animation) | 0 | gba | 0.9855 |
| MOVE_MISTY_TERRAIN | 0 | 47 | yes | True | 417 | hd | 0.6386 |
| MOVE_MIST_BALL | 0 | 1 | yes | True | 247 | hd | 0.1037 |
| MOVE_MOONBLAST | 0 | 11 | yes | True | 163 | hd | 0.9845 |
| MOVE_MOONGEIST_BEAM | 0 | 6 | yes | n/a (the game's own animation) | 0 | gba | 0.9846 |
| MOVE_MOONLIGHT | 0 | 6 | yes | True | 531 | hd | 0.9864 |
| MOVE_MORNING_SUN | 0 | 6 | yes | True | 375 | hd | 0.6425 |
| MOVE_MORTAL_SPIN | 0 | 29 | yes | n/a (the game's own animation) | 0 | gba | 0.1044 |
| MOVE_MOUNTAIN_GALE | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.1114 |
| MOVE_MUDDY_WATER | 0 | 5 | yes | True | 258 | hd | 0.238 |
| MOVE_MUD_BOMB | 0 | 4 | yes | True | 204 | hd | 0.1549 |
| MOVE_MUD_SHOT | 0 | 11 | yes | True | 207 | hd | 0.0856 |
| MOVE_MUD_SLAP | 0 | 36 | yes | True | 60 | hd | 0.1599 |
| MOVE_MUD_SPORT | 0 | 7 | yes | True | 412 | hd | 0.1056 |
| MOVE_MULTI_ATTACK | 0 | 23 | yes | n/a (the game's own animation) | 0 | gba | 0.9845 |
| MOVE_MYSTICAL_FIRE | 0 | 5 | yes | True | 141 | hd | 0.9998 |
| MOVE_MYSTICAL_POWER | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.9838 |
| MOVE_NASTY_PLOT | 0 | 20 | yes | True | 257 | hd | 0.9839 |
| MOVE_NATURAL_GIFT | 0 | 49 | yes | True | 208 | hd | 0.1307 |
| MOVE_NATURES_MADNESS | 0 | 4 | yes | n/a (the game's own animation) | 0 | gba | 0.1289 |
| MOVE_NATURE_POWER | 0 | 9 | yes | True | 167 | hd | 0.0829 |
| MOVE_NEEDLE_ARM | 0 | 1 | yes | True | 112 | hd | 0.108 |
| MOVE_NIGHTMARE | 0 | 10 | yes | True | 212 | hd | 0.9897 |
| MOVE_NIGHT_DAZE | 0 | 1 | yes | True | 154 | hd | 0.9983 |
| MOVE_NIGHT_SHADE | 0 | 10 | yes | True | 117 | hd | 0.9922 |
| MOVE_NIGHT_SLASH | 0 | 2 | yes | True | 59 | hd | 0.9961 |
| MOVE_NOBLE_ROAR | 0 | 9 | yes | True | 99 | hd | 0.964 |
| MOVE_NOXIOUS_TORQUE | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.9848 |
| MOVE_NO_RETREAT | 0 | 12 | yes | n/a (the game's own animation) | 0 | gba | 0.1151 |
| MOVE_NUZZLE | 0 | 31 | yes | True | 130 | hd | 0.0747 |
| MOVE_OBLIVION_WING | 0 | 0 | yes | True | 279 | hd | 0.999 |
| MOVE_OBSTRUCT | 0 | 30 | yes | n/a (the game's own animation) | 0 | gba | 0.1798 |
| MOVE_OCTAZOOKA | 0 | 4 | yes | True | 117 | hd | 0.1597 |
| MOVE_OCTOLOCK | 0 | 30 | yes | n/a (the game's own animation) | 0 | gba | 0.1134 |
| MOVE_ODOR_SLEUTH | 0 | 0 | yes | True | 92 | hd | 0.1086 |
| MOVE_OMINOUS_WIND | 0 | 6 | yes | True | 133 | hd | 0.9945 |
| MOVE_ORDER_UP | 0 | 12 | yes | n/a (the game's own animation) | 0 | gba | 0.1193 |
| MOVE_ORIGIN_PULSE | 0 | 5 | yes | True | 209 | hd | 0.9973 |
| MOVE_OUTRAGE | 0 | 6 | yes | True | 164 | hd | 0.8228 |
| MOVE_OVERDRIVE | 0 | 3 | yes | n/a (the game's own animation) | 0 | gba | 0.1551 |
| MOVE_OVERHEAT | 0 | 36 | yes | True | 377 | hd | 0.8389 |
| MOVE_PAIN_SPLIT | 0 | 8 | yes | True | 113 | hd | 0.1699 |
| MOVE_PARABOLIC_CHARGE | 0 | 3 | yes | True | 256 | hd | 0.6622 |
| MOVE_PARTING_SHOT | 0 | 72 | yes | True | 79 | hd | 0.9917 |
| MOVE_PAYBACK | 0 | 2 | yes | True | 103 | hd | 0.9961 |
| MOVE_PAY_DAY | 0 | 11 | yes | True | 30 | hd | 0.0615 |
| MOVE_PECK | 0 | 15 | yes | True | 28 | hd | 0.0678 |
| MOVE_PERISH_SONG | 0 | 23 | yes | True | 322 | hd | 0.9912 |
| MOVE_PETAL_BLIZZARD | 0 | 5 | yes | True | 65 | hd | 0.1736 |
| MOVE_PETAL_DANCE | 0 | 16 | yes | True | 111 | hd | 0.0762 |
| MOVE_PHANTOM_FORCE | 0 | 20 | yes | True | 18 | hd | 0.9848 |
| MOVE_PHANTOM_FORCE | 1 | 20 | yes | True | 428 | hd | 0.9857 |
| MOVE_PHOTON_GEYSER | 0 | 15 | yes | n/a (the game's own animation) | 0 | gba | 0.1274 |
| MOVE_PIKA_PAPOW | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9994 |
| MOVE_PIN_MISSILE | 0 | 2 | yes | True | 35 | hd | 0.0619 |
| MOVE_PLASMA_FISTS | 0 | 21 | yes | n/a (the game's own animation) | 0 | gba | 0.985 |
| MOVE_PLAY_NICE | 0 | 1 | yes | True | 87 | hd | 0.1449 |
| MOVE_PLAY_ROUGH | 0 | 39 | yes | True | 62 | hd | 0.1787 |
| MOVE_PLUCK | 0 | 3 | yes | True | 55 | hd | 0.0685 |
| MOVE_POISON_FANG | 0 | 8 | yes | True | 131 | hd | 0.096 |
| MOVE_POISON_GAS | 0 | 12 | yes | True | 163 | hd | 0.1109 |
| MOVE_POISON_JAB | 0 | 16 | yes | True | 66 | hd | 0.0729 |
| MOVE_POISON_POWDER | 0 | 47 | yes | True | 379 | hd | 0.08 |
| MOVE_POISON_STING | 0 | 28 | yes | True | 43 | hd | 0.0636 |
| MOVE_POISON_TAIL | 0 | 1 | yes | True | 196 | hd | 0.1135 |
| MOVE_POLLEN_PUFF | 0 | 14 | yes | n/a (the game's own animation) | 0 | gba | 0.9734 |
| MOVE_POLTERGEIST | 0 | 17 | yes | n/a (the game's own animation) | 0 | gba | 0.9835 |
| MOVE_POPULATION_BOMB | 0 | 74 | yes | n/a (the game's own animation) | 0 | gba | 0.1147 |
| MOVE_POUNCE | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.0871 |
| MOVE_POUND | 0 | 341 | yes | True | 16 | hd | 0.0545 |
| MOVE_POWDER | 0 | 50 | yes | True | 326 | hd | 0.0848 |
| MOVE_POWDER_SNOW | 0 | 23 | yes | True | 317 | hd | 0.4367 |
| MOVE_POWER_GEM | 0 | 13 | yes | True | 145 | hd | 0.9605 |
| MOVE_POWER_SHIFT | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.1236 |
| MOVE_POWER_SPLIT | 0 | 13 | yes | True | 149 | hd | 0.9943 |
| MOVE_POWER_SWAP | 0 | 0 | yes | True | 56 | hd | 0.1422 |
| MOVE_POWER_TRICK | 0 | 6 | yes | True | 104 | hd | 0.1153 |
| MOVE_POWER_TRIP | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.1373 |
| MOVE_POWER_UP_PUNCH | 0 | 14 | yes | True | 74 | hd | 0.1021 |
| MOVE_POWER_WHIP | 0 | 0 | yes | True | 50 | hd | 0.9843 |
| MOVE_PRECIPICE_BLADES | 0 | 14 | yes | True | 396 | hd | 0.9961 |
| MOVE_PRESENT | 0 | 12 | yes | True | 167 | hd | 0.1608 |
| MOVE_PRISMATIC_LASER | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9852 |
| MOVE_PROTECT | 0 | 225 | yes | True | 220 | hd | 0.1626 |
| MOVE_PSYBEAM | 0 | 2 | yes | True | 126 | hd | 0.9977 |
| MOVE_PSYBLADE | 0 | 15 | yes | n/a (the game's own animation) | 0 | gba | 0.9852 |
| MOVE_PSYCHIC | 0 | 83 | yes | True | 139 | hd | 0.9907 |
| MOVE_PSYCHIC_FANGS | 0 | 31 | yes | n/a (the game's own animation) | 0 | gba | 0.9966 |
| MOVE_PSYCHIC_NOISE | 0 | 18 | yes | n/a (the game's own animation) | 0 | gba | 0.9856 |
| MOVE_PSYCHIC_TERRAIN | 0 | 57 | yes | n/a (the game's own animation) | 0 | gba | 0.4159 |
| MOVE_PSYCHO_BOOST | 0 | 0 | yes | True | 148 | hd | 0.9862 |
| MOVE_PSYCHO_CUT | 0 | 6 | yes | True | 254 | hd | 0.8185 |
| MOVE_PSYCHO_SHIFT | 0 | 24 | yes | True | 208 | hd | 0.1198 |
| MOVE_PSYCH_UP | 0 | 10 | yes | True | 337 | hd | 0.9851 |
| MOVE_PSYSHIELD_BASH | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.9974 |
| MOVE_PSYSHOCK | 0 | 14 | yes | True | 45 | hd | 0.1824 |
| MOVE_PSYSTRIKE | 0 | 0 | yes | True | 120 | hd | 0.98 |
| MOVE_PSYWAVE | 0 | 8 | yes | True | 202 | hd | 0.9964 |
| MOVE_PUNISHMENT | 0 | 0 | yes | True | 23 | hd | 0.064 |
| MOVE_PURIFY | 0 | 16 | yes | n/a (the game's own animation) | 0 | gba | 0.1321 |
| MOVE_PURSUIT | 0 | 105 | yes | True | 61 | hd | 0.991 |
| MOVE_PURSUIT | 1 | 105 | yes | True | 81 | hd | 0.9911 |
| MOVE_PYRO_BALL | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.9764 |
| MOVE_QUASH | 0 | 21 | yes | True | 213 | hd | 0.9999 |
| MOVE_QUICK_ATTACK | 0 | 172 | yes | True | 18 | hd | 0.1656 |
| MOVE_QUICK_GUARD | 0 | 23 | yes | True | 30 | hd | 0.0788 |
| MOVE_QUIVER_DANCE | 0 | 8 | yes | True | 255 | hd | 0.9787 |
| MOVE_RAGE | 0 | 35 | yes | True | 126 | hd | 0.0685 |
| MOVE_RAGE_FIST | 0 | 73 | yes | n/a (the game's own animation) | 0 | gba | 0.9848 |
| MOVE_RAGE_POWDER | 0 | 4 | yes | True | 383 | hd | 0.1786 |
| MOVE_RAGING_BULL | 0 | 24 | yes | n/a (the game's own animation) | 0 | gba | 0.1234 |
| MOVE_RAGING_FURY | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9991 |
| MOVE_RAIN_DANCE | 0 | 117 | yes | True | 335 | hd | 0.8593 |
| MOVE_RAPID_SPIN | 0 | 30 | yes | True | 229 | hd | 0.157 |
| MOVE_RAZOR_LEAF | 0 | 13 | yes | True | 78 | hd | 0.0864 |
| MOVE_RAZOR_SHELL | 0 | 2 | yes | True | 17 | hd | 0.0809 |
| MOVE_RAZOR_WIND | 0 | 16 | yes | True | 26 | hd | 0.0851 |
| MOVE_RAZOR_WIND | 1 | 16 | yes | True | 37 | hd | 0.0648 |
| MOVE_RECOVER | 0 | 45 | yes | True | 186 | hd | 0.0874 |
| MOVE_RECYCLE | 0 | 30 | yes | True | 112 | hd | 0.1475 |
| MOVE_REFLECT | 0 | 64 | yes | True | 124 | hd | 0.1219 |
| MOVE_REFLECT_TYPE | 0 | 23 | yes | True | 59 | hd | 0.0602 |
| MOVE_REFRESH | 0 | 13 | yes | True | 262 | hd | 0.1184 |
| MOVE_RELIC_SONG | 0 | 38 | yes | True | 105 | hd | 0.2044 |
| MOVE_REST | 0 | 72 | yes | True | 207 | hd | 0.1026 |
| MOVE_RETALIATE | 0 | 18 | yes | True | 133 | hd | 0.9973 |
| MOVE_RETURN | 0 | 13 | yes | True | 250 | hd | 0.942 |
| MOVE_REVELATION_DANCE | 0 | 39 | yes | n/a (the game's own animation) | 0 | gba | 0.985 |
| MOVE_REVENGE | 0 | 17 | yes | True | 126 | hd | 0.108 |
| MOVE_REVERSAL | 0 | 0 | yes | True | 202 | hd | 0.4329 |
| MOVE_REVIVAL_BLESSING | 0 | 24 | yes | n/a (the game's own animation) | 0 | gba | 0.9995 |
| MOVE_RISING_VOLTAGE | 0 | 11 | yes | n/a (the game's own animation) | 0 | gba | 0.805 |
| MOVE_ROAR | 0 | 25 | yes | True | 45 | hd | 0.0776 |
| MOVE_ROAR_OF_TIME | 0 | 0 | yes | True | 230 | hd | 0.9971 |
| MOVE_ROCK_BLAST | 0 | 6 | yes | True | 75 | hd | 0.0675 |
| MOVE_ROCK_CLIMB | 0 | 1 | yes | True | 177 | hd | 0.1383 |
| MOVE_ROCK_POLISH | 0 | 3 | yes | True | 154 | hd | 0.9851 |
| MOVE_ROCK_SLIDE | 0 | 64 | yes | True | 218 | hd | 0.1727 |
| MOVE_ROCK_SMASH | 0 | 7 | yes | True | 51 | hd | 0.1622 |
| MOVE_ROCK_THROW | 0 | 30 | yes | True | 133 | hd | 0.0767 |
| MOVE_ROCK_TOMB | 0 | 13 | yes | True | 296 | hd | 0.3828 |
| MOVE_ROCK_WRECKER | 0 | 0 | yes | True | 570 | hd | 0.9953 |
| MOVE_ROLE_PLAY | 0 | 29 | yes | True | 202 | hd | 0.9981 |
| MOVE_ROLLING_KICK | 0 | 1 | yes | True | 29 | hd | 0.114 |
| MOVE_ROLLOUT | 0 | 27 | yes | True | 304 | hd | 0.1532 |
| MOVE_ROOST | 0 | 47 | yes | True | 255 | hd | 0.1184 |
| MOVE_ROTOTILLER | 0 | 14 | yes | True | 305 | hd | 0.9739 |
| MOVE_ROUND | 0 | 127 | yes | True | 45 | hd | 0.0747 |
| MOVE_RUINATION | 0 | 8 | yes | n/a (the game's own animation) | 0 | gba | 0.118 |
| MOVE_SACRED_FIRE | 0 | 3 | yes | True | 391 | hd | 0.9811 |
| MOVE_SACRED_SWORD | 0 | 3 | yes | True | 48 | hd | 0.118 |
| MOVE_SAFEGUARD | 0 | 31 | yes | True | 125 | hd | 0.2151 |
| MOVE_SALT_CURE | 0 | 28 | yes | n/a (the game's own animation) | 0 | gba | 0.1026 |
| MOVE_SANDSEAR_STORM | 0 | 2 | yes | n/a (the game's own animation) | 0 | gba | 0.1778 |
| MOVE_SANDSTORM | 0 | 78 | yes | True | 148 | hd | 0.616 |
| MOVE_SAND_ATTACK | 0 | 48 | yes | True | 29 | hd | 0.0665 |
| MOVE_SAND_TOMB | 0 | 0 | yes | True | 220 | hd | 0.1279 |
| MOVE_SAPPY_SEED | 0 | 5 | yes | n/a (the game's own animation) | 0 | gba | 0.1228 |
| MOVE_SCALD | 0 | 57 | yes | True | 66 | hd | 0.3745 |
| MOVE_SCALE_SHOT | 0 | 32 | yes | n/a (the game's own animation) | 0 | gba | 0.1355 |
| MOVE_SCARY_FACE | 0 | 52 | yes | True | 157 | hd | 0.9955 |
| MOVE_SCORCHING_SANDS | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.0991 |
| MOVE_SCRATCH | 0 | 2386 | yes | True | 15 | hd | 0.0665 |
| MOVE_SCREECH | 0 | 50 | yes | True | 25 | hd | 0.0858 |
| MOVE_SEARING_SHOT | 0 | 1 | yes | True | 795 | hd | 0.9852 |
| MOVE_SECRET_POWER | 0 | 18 | yes | True | 125 | hd | 0.1276 |
| MOVE_SECRET_SWORD | 0 | 0 | yes | True | 107 | hd | 0.9933 |
| MOVE_SEED_BOMB | 0 | 15 | yes | True | 109 | hd | 0.1095 |
| MOVE_SEED_FLARE | 0 | 3 | yes | True | 274 | hd | 0.7569 |
| MOVE_SEISMIC_TOSS | 0 | 48 | yes | True | 211 | hd | 0.9901 |
| MOVE_SELF_DESTRUCT | 0 | 11 | yes | True | 231 | hd | 0.3881 |
| MOVE_SHADOW_BALL | 0 | 68 | yes | True | 83 | hd | 0.996 |
| MOVE_SHADOW_BONE | 0 | 3 | yes | n/a (the game's own animation) | 0 | gba | 0.9835 |
| MOVE_SHADOW_CLAW | 0 | 9 | yes | True | 28 | hd | 0.9953 |
| MOVE_SHADOW_FORCE | 0 | 12 | yes | True | 142 | hd | 0.9947 |
| MOVE_SHADOW_FORCE | 1 | 12 | yes | True | 202 | hd | 0.989 |
| MOVE_SHADOW_PUNCH | 0 | 5 | yes | True | 29 | hd | 0.9985 |
| MOVE_SHADOW_SNEAK | 0 | 6 | yes | True | 317 | hd | 0.985 |
| MOVE_SHARPEN | 0 | 0 | yes | True | 253 | hd | 0.0612 |
| MOVE_SHED_TAIL | 0 | 24 | yes | n/a (the game's own animation) | 0 | gba | 0.0621 |
| MOVE_SHEER_COLD | 0 | 32 | yes | True | 302 | hd | 0.999 |
| MOVE_SHELL_SIDE_ARM | 0 | 19 | yes | n/a (the game's own animation) | 0 | gba | 0.1144 |
| MOVE_SHELL_SMASH | 0 | 23 | yes | True | 76 | hd | 0.0663 |
| MOVE_SHELL_TRAP | 0 | 47 | yes | n/a (the game's own animation) | 0 | gba | 0.1087 |
| MOVE_SHELTER | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.1291 |
| MOVE_SHIFT_GEAR | 0 | 3 | yes | True | 109 | hd | 0.0616 |
| MOVE_SHOCK_WAVE | 0 | 29 | yes | True | 181 | hd | 0.9273 |
| MOVE_SHORE_UP | 0 | 3 | yes | n/a (the game's own animation) | 0 | gba | 0.9892 |
| MOVE_SIGNAL_BEAM | 0 | 2 | yes | True | 138 | hd | 0.1279 |
| MOVE_SILK_TRAP | 0 | 27 | yes | n/a (the game's own animation) | 0 | gba | 0.1274 |
| MOVE_SILVER_WIND | 0 | 1 | yes | True | 72 | hd | 0.991 |
| MOVE_SIMPLE_BEAM | 0 | 23 | yes | True | 121 | hd | 0.9968 |
| MOVE_SING | 0 | 10 | yes | True | 127 | hd | 0.0766 |
| MOVE_SIZZLY_SLIDE | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.064 |
| MOVE_SKETCH | 0 | 1 | yes | True | 129 | hd | 0.1518 |
| MOVE_SKILL_SWAP | 0 | 167 | yes | True | 217 | hd | 0.9969 |
| MOVE_SKITTER_SMACK | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.8983 |
| MOVE_SKULL_BASH | 0 | 12 | yes | True | 121 | hd | 0.0694 |
| MOVE_SKULL_BASH | 1 | 12 | yes | True | 158 | hd | 0.0795 |
| MOVE_SKY_ATTACK | 0 | 9 | yes | True | 142 | hd | 0.9889 |
| MOVE_SKY_ATTACK | 1 | 9 | yes | True | 87 | hd | 0.9879 |
| MOVE_SKY_DROP | 0 | 64 | yes | True | 104 | hd | 0.0707 |
| MOVE_SKY_DROP | 1 | 64 | yes | True | 78 | hd | 0.0972 |
| MOVE_SKY_UPPERCUT | 0 | 16 | yes | True | 174 | hd | 0.9986 |
| MOVE_SLACK_OFF | 0 | 0 | yes | True | 192 | hd | 0.1311 |
| MOVE_SLAM | 0 | 11 | yes | True | 24 | hd | 0.1019 |
| MOVE_SLASH | 0 | 16 | yes | True | 36 | hd | 0.1539 |
| MOVE_SLEEP_POWDER | 0 | 6 | yes | True | 379 | hd | 0.0687 |
| MOVE_SLEEP_TALK | 0 | 98 | yes | True | 320 | hd | 0.1446 |
| MOVE_SLUDGE | 0 | 3 | yes | True | 157 | hd | 0.0835 |
| MOVE_SLUDGE_BOMB | 0 | 23 | yes | True | 230 | hd | 0.1534 |
| MOVE_SLUDGE_WAVE | 0 | 1 | yes | True | 268 | hd | 0.2992 |
| MOVE_SMACK_DOWN | 0 | 29 | yes | True | 196 | hd | 0.9885 |
| MOVE_SMART_STRIKE | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.112 |
| MOVE_SMELLING_SALTS | 0 | 13 | yes | True | 83 | hd | 0.1557 |
| MOVE_SMOG | 0 | 2 | yes | True | 312 | hd | 0.0946 |
| MOVE_SMOKESCREEN | 0 | 0 | yes | True | 90 | hd | 0.1031 |
| MOVE_SNAP_TRAP | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.1102 |
| MOVE_SNARL | 0 | 4 | yes | True | 73 | hd | 0.9936 |
| MOVE_SNATCH | 0 | 35 | yes | True | 69 | hd | 0.1668 |
| MOVE_SNIPE_SHOT | 0 | 3 | yes | n/a (the game's own animation) | 0 | gba | 0.9944 |
| MOVE_SNORE | 0 | 23 | yes | True | 55 | hd | 0.1818 |
| MOVE_SNOWSCAPE | 0 | 80 | yes | n/a (the game's own animation) | 0 | gba | 0.0917 |
| MOVE_SOAK | 0 | 45 | yes | True | 52 | hd | 0.0693 |
| MOVE_SOFT_BOILED | 0 | 4 | yes | True | 248 | hd | 0.0976 |
| MOVE_SOLAR_BEAM | 0 | 54 | yes | True | 74 | hd | 0.1492 |
| MOVE_SOLAR_BEAM | 1 | 54 | yes | True | 379 | hd | 0.9976 |
| MOVE_SOLAR_BLADE | 0 | 7 | yes | n/a (the game's own animation) | 0 | gba | 0.1355 |
| MOVE_SONIC_BOOM | 0 | 19 | yes | True | 24 | hd | 0.1347 |
| MOVE_SPACIAL_REND | 0 | 0 | yes | True | 98 | hd | 0.9994 |
| MOVE_SPARK | 0 | 17 | yes | True | 178 | hd | 0.4764 |
| MOVE_SPARKLING_ARIA | 0 | 19 | yes | n/a (the game's own animation) | 0 | gba | 0.984 |
| MOVE_SPARKLY_SWIRL | 0 | 12 | yes | n/a (the game's own animation) | 0 | gba | 0.1279 |
| MOVE_SPECTRAL_THIEF | 0 | 24 | yes | n/a (the game's own animation) | 0 | gba | 0.9846 |
| MOVE_SPEED_SWAP | 0 | 13 | yes | n/a (the game's own animation) | 0 | gba | 0.1173 |
| MOVE_SPICY_EXTRACT | 0 | 21 | yes | n/a (the game's own animation) | 0 | gba | 0.1165 |
| MOVE_SPIDER_WEB | 0 | 0 | yes | True | 195 | hd | 0.9919 |
| MOVE_SPIKES | 0 | 70 | yes | True | 51 | hd | 0.1349 |
| MOVE_SPIKE_CANNON | 0 | 0 | yes | True | 51 | hd | 0.1472 |
| MOVE_SPIKY_SHIELD | 0 | 39 | yes | True | 148 | hd | 0.1863 |
| MOVE_SPIN_OUT | 0 | 23 | yes | n/a (the game's own animation) | 0 | gba | 0.0989 |
| MOVE_SPIRIT_BREAK | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.1731 |
| MOVE_SPIRIT_SHACKLE | 0 | 6 | yes | n/a (the game's own animation) | 0 | gba | 0.1486 |
| MOVE_SPITE | 0 | 5 | yes | True | 287 | hd | 0.9981 |
| MOVE_SPIT_UP | 0 | 25 | yes | True | 123 | hd | 0.1508 |
| MOVE_SPLASH | 0 | 124 | yes | True | 73 | hd | 0.0589 |
| MOVE_SPLISHY_SPLASH | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.8132 |
| MOVE_SPORE | 0 | 397 | yes | True | 360 | hd | 0.0909 |
| MOVE_SPOTLIGHT | 0 | 5 | yes | n/a (the game's own animation) | 0 | gba | 0.9936 |
| MOVE_SPRINGTIDE_STORM | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.1694 |
| MOVE_STEALTH_ROCK | 0 | 110 | yes | True | 157 | hd | 0.0885 |
| MOVE_STEAMROLLER | 0 | 8 | yes | True | 75 | hd | 0.1213 |
| MOVE_STEAM_ERUPTION | 0 | 1 | yes | True | 142 | hd | 0.99 |
| MOVE_STEEL_BEAM | 0 | 24 | yes | n/a (the game's own animation) | 0 | gba | 0.9834 |
| MOVE_STEEL_ROLLER | 0 | 16 | yes | n/a (the game's own animation) | 0 | gba | 0.1674 |
| MOVE_STEEL_WING | 0 | 7 | yes | True | 200 | hd | 0.1478 |
| MOVE_STICKY_WEB | 0 | 88 | yes | True | 350 | hd | 0.9784 |
| MOVE_STOCKPILE | 0 | 64 | yes | True | 153 | hd | 0.1484 |
| MOVE_STOMP | 0 | 3 | yes | True | 94 | hd | 0.087 |
| MOVE_STOMPING_TANTRUM | 0 | 44 | yes | n/a (the game's own animation) | 0 | gba | 0.6245 |
| MOVE_STONE_AXE | 0 | 18 | yes | n/a (the game's own animation) | 0 | gba | 0.158 |
| MOVE_STONE_EDGE | 0 | 16 | yes | True | 132 | hd | 0.1148 |
| MOVE_STORED_POWER | 0 | 3 | yes | True | 132 | hd | 0.9873 |
| MOVE_STORM_THROW | 0 | 6 | yes | True | 77 | hd | 0.0909 |
| MOVE_STRANGE_STEAM | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.1956 |
| MOVE_STRENGTH | 0 | 54 | yes | True | 129 | hd | 0.0774 |
| MOVE_STRENGTH_SAP | 0 | 28 | yes | n/a (the game's own animation) | 0 | gba | 0.1433 |
| MOVE_STRING_SHOT | 0 | 3 | yes | True | 208 | hd | 0.9816 |
| MOVE_STRUGGLE | 0 | 60 | yes | True | 66 | hd | 0.076 |
| MOVE_STRUGGLE_BUG | 0 | 1 | yes | True | 199 | hd | 0.0726 |
| MOVE_STUFF_CHEEKS | 0 | 39 | yes | n/a (the game's own animation) | 0 | gba | 0.1094 |
| MOVE_STUN_SPORE | 0 | 34 | yes | True | 379 | hd | 0.0958 |
| MOVE_SUBMISSION | 0 | 3 | yes | True | 115 | hd | 0.1019 |
| MOVE_SUBSTITUTE | 0 | 189 | yes | True | 85 | hd | 0.0809 |
| MOVE_SUCKER_PUNCH | 0 | 46 | yes | True | 18 | hd | 0.1941 |
| MOVE_SUNNY_DAY | 0 | 180 | yes | True | 226 | hd | 0.4892 |
| MOVE_SUNSTEEL_STRIKE | 0 | 22 | yes | n/a (the game's own animation) | 0 | gba | 0.872 |
| MOVE_SUPERCELL_SLAM | 0 | 2 | yes | n/a (the game's own animation) | 0 | gba | 0.1216 |
| MOVE_SUPERPOWER | 0 | 21 | yes | True | 464 | hd | 0.5686 |
| MOVE_SUPERSONIC | 0 | 0 | yes | True | 54 | hd | 0.0694 |
| MOVE_SUPER_FANG | 0 | 55 | yes | True | 71 | hd | 0.0624 |
| MOVE_SURF | 0 | 143 | yes | True | 268 | hd | 0.233 |
| MOVE_SURGING_STRIKES | 0 | 30 | yes | n/a (the game's own animation) | 0 | gba | 0.0897 |
| MOVE_SWAGGER | 0 | 17 | yes | True | 150 | hd | 0.1512 |
| MOVE_SWALLOW | 0 | 6 | yes | True | 149 | hd | 0.1679 |
| MOVE_SWALLOW | 1 | 6 | yes | True | 142 | hd | 0.1679 |
| MOVE_SWALLOW | 2 | 6 | yes | True | 142 | hd | 0.1677 |
| MOVE_SWALLOW | 3 | 6 | yes | True | 156 | hd | 0.1625 |
| MOVE_SWEET_KISS | 0 | 0 | yes | True | 121 | hd | 0.158 |
| MOVE_SWEET_SCENT | 0 | 26 | yes | True | 315 | hd | 0.1814 |
| MOVE_SWIFT | 0 | 92 | yes | True | 41 | hd | 0.0947 |
| MOVE_SWITCHEROO | 0 | 6 | yes | True | 104 | hd | 0.9986 |
| MOVE_SWORDS_DANCE | 0 | 201 | yes | True | 118 | hd | 0.1142 |
| MOVE_SYNCHRONOISE | 0 | 21 | yes | True | 86 | hd | 0.9917 |
| MOVE_SYNTHESIS | 0 | 8 | yes | True | 155 | hd | 0.3611 |
| MOVE_SYRUP_BOMB | 0 | 42 | yes | n/a (the game's own animation) | 0 | gba | 0.1746 |
| MOVE_TACHYON_CUTTER | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.1004 |
| MOVE_TACKLE | 0 | 364 | yes | True | 18 | hd | 0.0702 |
| MOVE_TAILWIND | 0 | 75 | yes | True | 42 | hd | 0.9843 |
| MOVE_TAIL_GLOW | 0 | 3 | yes | True | 119 | hd | 0.7465 |
| MOVE_TAIL_SLAP | 0 | 0 | yes | True | 13 | hd | 0.1767 |
| MOVE_TAIL_SLAP | 1 | 0 | yes | True | 14 | hd | 0.1653 |
| MOVE_TAIL_WHIP | 0 | 10 | yes | True | 24 | hd | 0.0629 |
| MOVE_TAKE_DOWN | 0 | 39 | yes | True | 50 | hd | 0.0906 |
| MOVE_TAKE_HEART | 0 | 11 | yes | n/a (the game's own animation) | 0 | gba | 0.128 |
| MOVE_TAR_SHOT | 0 | 7 | yes | n/a (the game's own animation) | 0 | gba | 0.1117 |
| MOVE_TAUNT | 0 | 64 | yes | True | 121 | hd | 0.1504 |
| MOVE_TEARFUL_LOOK | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.4952 |
| MOVE_TEATIME | 0 | 30 | yes | n/a (the game's own animation) | 0 | gba | 0.116 |
| MOVE_TECHNO_BLAST | 0 | 23 | yes | True | 165 | hd | 0.9843 |
| MOVE_TEETER_DANCE | 0 | 16 | yes | True | 254 | hd | 0.144 |
| MOVE_TELEKINESIS | 0 | 9 | yes | True | 421 | hd | 0.9932 |
| MOVE_TELEPORT | 0 | 22 | yes | True | 28 | hd | 0.9855 |
| MOVE_TEMPER_FLARE | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.1378 |
| MOVE_TERA_BLAST | 0 | 94 | yes | n/a (the game's own animation) | 0 | gba | 0.1045 |
| MOVE_TERA_STARSTORM | 0 | 14 | yes | n/a (the game's own animation) | 0 | gba | 0.9844 |
| MOVE_TERRAIN_PULSE | 0 | 25 | yes | n/a (the game's own animation) | 0 | gba | 0.9746 |
| MOVE_THIEF | 0 | 28 | yes | True | 53 | hd | 0.9934 |
| MOVE_THOUSAND_ARROWS | 0 | 16 | yes | True | 311 | hd | 0.9897 |
| MOVE_THOUSAND_WAVES | 0 | 0 | yes | True | 462 | hd | 0.9941 |
| MOVE_THRASH | 0 | 31 | yes | True | 179 | hd | 0.078 |
| MOVE_THROAT_CHOP | 0 | 31 | yes | n/a (the game's own animation) | 0 | gba | 0.9674 |
| MOVE_THUNDER | 0 | 53 | yes | True | 392 | hd | 0.9865 |
| MOVE_THUNDERBOLT | 0 | 145 | yes | True | 313 | hd | 0.9537 |
| MOVE_THUNDERCLAP | 0 | 9 | yes | n/a (the game's own animation) | 0 | gba | 0.9067 |
| MOVE_THUNDEROUS_KICK | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.9893 |
| MOVE_THUNDER_CAGE | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.0898 |
| MOVE_THUNDER_FANG | 0 | 7 | yes | True | 100 | hd | 0.9973 |
| MOVE_THUNDER_PUNCH | 0 | 11 | yes | True | 83 | hd | 0.9922 |
| MOVE_THUNDER_SHOCK | 0 | 65 | yes | True | 223 | hd | 0.9578 |
| MOVE_THUNDER_WAVE | 0 | 86 | yes | True | 180 | hd | 0.9511 |
| MOVE_TICKLE | 0 | 19 | yes | True | 296 | hd | 0.1163 |
| MOVE_TIDY_UP | 0 | 14 | yes | n/a (the game's own animation) | 0 | gba | 0.0752 |
| MOVE_TOPSY_TURVY | 0 | 22 | yes | True | 287 | hd | 0.8381 |
| MOVE_TORCH_SONG | 0 | 7 | yes | n/a (the game's own animation) | 0 | gba | 0.9826 |
| MOVE_TORMENT | 0 | 30 | yes | True | 258 | hd | 0.1616 |
| MOVE_TOXIC | 0 | 133 | yes | True | 374 | hd | 0.1484 |
| MOVE_TOXIC_SPIKES | 0 | 98 | yes | True | 145 | hd | 0.091 |
| MOVE_TOXIC_THREAD | 0 | 20 | yes | n/a (the game's own animation) | 0 | gba | 0.9782 |
| MOVE_TRAILBLAZE | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.0669 |
| MOVE_TRANSFORM | 0 | 78 | yes | True | 147 | hd | 0.082 |
| MOVE_TRICK | 0 | 78 | yes | True | 150 | hd | 0.1603 |
| MOVE_TRICK_OR_TREAT | 0 | 3 | yes | True | 190 | hd | 0.9873 |
| MOVE_TRICK_ROOM | 0 | 71 | yes | True | 276 | hd | 0.9851 |
| MOVE_TRIPLE_ARROWS | 0 | 14 | yes | n/a (the game's own animation) | 0 | gba | 0.1274 |
| MOVE_TRIPLE_AXEL | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.0788 |
| MOVE_TRIPLE_DIVE | 0 | 5 | yes | n/a (the game's own animation) | 0 | gba | 0.1328 |
| MOVE_TRIPLE_KICK | 0 | 19 | yes | True | 21 | hd | 0.1003 |
| MOVE_TRIPLE_KICK | 1 | 19 | yes | True | 17 | hd | 0.0991 |
| MOVE_TRIPLE_KICK | 2 | 19 | yes | True | 53 | hd | 0.1199 |
| MOVE_TRI_ATTACK | 0 | 33 | yes | True | 356 | hd | 0.9907 |
| MOVE_TROP_KICK | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.1163 |
| MOVE_TRUMP_CARD | 0 | 8 | yes | True | 32 | hd | 0.1124 |
| MOVE_TWINEEDLE | 0 | 12 | yes | True | 21 | hd | 0.0736 |
| MOVE_TWIN_BEAM | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.9995 |
| MOVE_TWISTER | 0 | 4 | yes | True | 322 | hd | 0.3549 |
| MOVE_UPPER_HAND | 0 | 44 | yes | n/a (the game's own animation) | 0 | gba | 0.8693 |
| MOVE_UPROAR | 0 | 20 | yes | True | 60 | hd | 0.2138 |
| MOVE_U_TURN | 0 | 135 | yes | True | 26 | hd | 0.1111 |
| MOVE_VACUUM_WAVE | 0 | 0 | yes | True | 12 | hd | 0.1456 |
| MOVE_VEEVEE_VOLLEY | 0 | 0 | yes | n/a (the game's own animation) | 0 | gba | 0.6782 |
| MOVE_VENOM_DRENCH | 0 | 7 | yes | True | 38 | hd | 0.1657 |
| MOVE_VENOSHOCK | 0 | 4 | yes | True | 56 | hd | 0.0684 |
| MOVE_VICTORY_DANCE | 0 | 3 | yes | n/a (the game's own animation) | 0 | gba | 0.123 |
| MOVE_VINE_WHIP | 0 | 51 | yes | True | 12 | hd | 0.0656 |
| MOVE_VISE_GRIP | 0 | 0 | yes | True | 14 | hd | 0.0845 |
| MOVE_VITAL_THROW | 0 | 11 | yes | True | 97 | hd | 0.1768 |
| MOVE_VOLT_SWITCH | 0 | 25 | yes | True | 105 | hd | 0.0874 |
| MOVE_VOLT_TACKLE | 0 | 4 | yes | True | 125 | hd | 0.9865 |
| MOVE_V_CREATE | 0 | 2 | yes | True | 504 | hd | 1.0 |
| MOVE_WAKE_UP_SLAP | 0 | 20 | yes | True | 31 | hd | 0.1051 |
| MOVE_WATERFALL | 0 | 15 | yes | True | 127 | hd | 0.1442 |
| MOVE_WATER_GUN | 0 | 387 | yes | True | 178 | hd | 0.0691 |
| MOVE_WATER_PLEDGE | 0 | 53 | yes | True | 287 | hd | 0.1235 |
| MOVE_WATER_PULSE | 0 | 11 | yes | True | 163 | hd | 0.7172 |
| MOVE_WATER_SHURIKEN | 0 | 10 | yes | True | 104 | hd | 0.0778 |
| MOVE_WATER_SPORT | 0 | 3 | yes | True | 419 | hd | 0.0797 |
| MOVE_WATER_SPOUT | 0 | 14 | yes | True | 172 | hd | 0.1442 |
| MOVE_WAVE_CRASH | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.1472 |
| MOVE_WEATHER_BALL | 0 | 63 | yes | True | 166 | hd | 0.0862 |
| MOVE_WHIRLPOOL | 0 | 0 | yes | True | 246 | hd | 0.219 |
| MOVE_WHIRLWIND | 0 | 13 | yes | True | 118 | hd | 0.1053 |
| MOVE_WICKED_BLOW | 0 | 3 | yes | n/a (the game's own animation) | 0 | gba | 0.0787 |
| MOVE_WICKED_TORQUE | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.985 |
| MOVE_WIDE_GUARD | 0 | 21 | yes | True | 84 | hd | 0.0809 |
| MOVE_WILDBOLT_STORM | 0 | 2 | yes | n/a (the game's own animation) | 0 | gba | 0.9885 |
| MOVE_WILD_CHARGE | 0 | 10 | yes | True | 160 | hd | 0.773 |
| MOVE_WILL_O_WISP | 0 | 81 | yes | True | 183 | hd | 0.1459 |
| MOVE_WING_ATTACK | 0 | 21 | yes | True | 55 | hd | 0.0794 |
| MOVE_WISH | 0 | 27 | yes | True | 470 | hd | 0.982 |
| MOVE_WITHDRAW | 0 | 0 | yes | True | 147 | hd | 0.1685 |
| MOVE_WONDER_ROOM | 0 | 27 | yes | True | 281 | hd | 0.9871 |
| MOVE_WOOD_HAMMER | 0 | 0 | yes | True | 339 | hd | 0.0971 |
| MOVE_WORK_UP | 0 | 5 | yes | True | 96 | hd | 0.1506 |
| MOVE_WORRY_SEED | 0 | 47 | yes | True | 50 | hd | 0.0926 |
| MOVE_WRAP | 0 | 19 | yes | True | 74 | hd | 0.0814 |
| MOVE_WRING_OUT | 0 | 0 | yes | True | 304 | hd | 0.1303 |
| MOVE_X_SCISSOR | 0 | 1 | yes | True | 17 | hd | 0.9966 |
| MOVE_YAWN | 0 | 88 | yes | True | 171 | hd | 0.1668 |
| MOVE_ZAP_CANNON | 0 | 1 | yes | True | 71 | hd | 0.1719 |
| MOVE_ZEN_HEADBUTT | 0 | 8 | yes | True | 103 | hd | 0.7503 |
| MOVE_ZING_ZAP | 0 | 1 | yes | n/a (the game's own animation) | 0 | gba | 0.1237 |
| MOVE_ZIPPY_ZAP | 0 | 2 | yes | n/a (the game's own animation) | 0 | gba | 0.1165 |
