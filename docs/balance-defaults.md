# Multiplayer balance defaults

The numbers of the shared-world systems, as the code holds them. The owner approved the recommended values on
2026-10-09 ("use your recommended values"); later owner changes are noted where they apply. This page mirrors the code
and decides nothing: the code is what runs, a change to any value is the owner's decision, and
`tests/test_balance_doc.py` fails when the host's table below differs from `balance.py`.

Written on 2026-11-03 (KNOWN_ISSUES G2: `balance.py`, `wagers.py` and the engine's header cited this page, which did not
exist) from the host's `src/emerald_multiplayer/balance.py` (last changed 2026-10-17, app `b6b9a4e`) and the engine's
`include/constants/multiplayer_balance.h` (last changed 2026-10-25, engine `2912296c`). Changed since: on 2026-11-05
`event_claim_grace_seconds` went from 120 to 300 (the owner's five-minute reservation, KNOWN_ISSUES G3).

## The host (`src/emerald_multiplayer/balance.py`, `BALANCE`)

| Name | Value | What it is |
| --- | --- | --- |
| `clock_rate` | 12 | world seconds per real second: a world day in two real hours; the clock pauses while the world is empty |
| `clock_start_seconds` | 43200 | a new world's day 0 begins at 12:00 noon (owner, 2026-10-17; it was 08:00); only new worlds |
| `notice_seconds` | 8 | how long an overworld notice stays available to players returning to the field |
| `event_first_delay` | (600, 1200) | seconds before a world's first World Event, a range |
| `event_interval` | (1500, 2700) | seconds between World Events, a range |
| `event_duration_seconds` | 900 | how long a World Event lasts |
| `event_category_weights` | rare 50, legendary 28, mega 15, mythical 5, mega_legendary 2 | how often each kind of World Event is chosen |
| `event_shiny_chance` | 1/64 | a World Event Pokemon's chance to be shiny |
| `event_level_offset_rare` | 3 | a rare or mega event's level over the progression level (the average of each connected player's strongest party level), kept within the two below |
| `event_level_offset_legendary` | 8 | the same for a legendary, mythical or mega legendary event |
| `event_level_min` | 5 | lowest World Event level |
| `event_level_max` | 70 | highest World Event level |
| `event_claim_grace_seconds` | 300 | a claimant who disconnects (every claimant, after a host restart) keeps the event's Pokemon reserved this long (seconds while somebody is online), reclaims it by reconnecting in time, and loses it at that moment; never two claims at once (owner, 2026-11-05: five minutes; it was 120). `docs/legendary-catch-resolution.md` |
| `event_claim_away_seconds` | 60 | a connected claimant on another map lets the claim go after this |
| `event_condition_chance` | 0.6 | a legendary event's chance to start dormant (`event_conditions.py`) |
| `friendship_levels` | New Friends, Good Friends, Great Friends, Ultra Friends, Best Friends | a pair's friendship levels |
| `friendship_thresholds` | (0, 30, 120, 300, 600) | the points each level needs |
| `friendship_points` | trade 15, battle_together 12, battle_against 6, championship 10, event_together 10, gym_together 20, session_together 2 | points per shared activity |
| `friendship_daily_cap` | 60 | points per pair per real day |
| `friendship_session_minutes` | 30 | the "played together" credit's interval |
| `lucky_trade_chance` | (0.05, 0.08, 0.12, 0.2, 0.3) | a trade's chance to make Lucky Pokemon, by friendship level |
| `lucky_iv_floor` | 12 | a Lucky Pokemon's IVs are raised to at least this (of 31); the game's own copy is `MP_LUCKY_IV_FLOOR` below |
| `lucky_friends_chance` | 0.1 | per eligible Best Friends interaction |
| `lucky_friends_cooldown_hours` | 12 | hours between Lucky Friends chances |
| `wager_min` | 100 | the smallest PvP wager, in the game's own money (fictional) |
| `wager_max` | 100000 | the largest PvP wager |

The wagers' rules (`wagers.py`): the challenger proposes an amount, every other trainer must accept that exact amount;
each stakes it from their own wallet; a win moves each losing trainer's stake to the opposing winner in the same team
slot, a draw, cancellation or a battle that never starts moves nothing; money moves only after the host has a
verified, closed result.

## The game (engine `include/constants/multiplayer_balance.h`)

| Name | Value | What it is |
| --- | --- | --- |
| `MP_SHINY_CHARM_COINS_PC` | 15000 | the Shiny Charm's Game Corner price on the PC (2026-10-25: every Game Corner coin price is 15% of what it was, the owner: "way too high") |
| `MP_SHINY_CHARM_COINS_GBA` | 9000 | the same in the GBA ROM, unchanged |
| `MP_MEGA_RING_COINS` | 3750 | the Mega Ring's price in coins (PC) |
| `MP_COINS_PACK_LARGE` | 5000 | the coin counter's large pack (PC) ... |
| `MP_COINS_PACK_LARGE_YEN` | 100000 | ... at 20 yen a coin, as the other two packs |
| `MP_MEGA_STONE_PRICE` | 60000 | a Mega Stone's price at the Mauville City Poke Mart dealer, once the player has the Mega Ring; on the PC each stone has its own price (`src/platform/mp_mega_prices.h`) |
| `MP_LUCKY_IV_FLOOR` | 12 | a Lucky Pokemon's IV floor, the game's copy of the host's `lucky_iv_floor` |

The Shiny Charm's effect is the engine's own (1 + `I_SHINY_CHARM_ADDITIONAL_ROLLS` rolls of 1/4096: 3/4096 per
personal shiny roll); the Coin Case holds up to 999,999 coins on the PC.
