# Legendary Tickets: where the island legends' tickets come from (design, 2026-11-05)

The owner's decision of 2026-11-05 (`docs/owner-decisions.md` #11 and #40), final: *"Make tickets for personal static
legendary encounters obtainable through postgame achievements, challenging quests, and Battle Frontier milestones. Do not
make casino purchases the sole acquisition method."*

**Status.** Designed. Built and tested here: the host's half that needs no engine change
(`src/emerald_multiplayer/legendary_tickets.py`: the catalogue, the conditions read from saves and host records, the
setting, the ledger; `tests/test_legendary_tickets.py`, 30 tests, Linux only). **Not built: delivering a ticket into the
game**, which needs a small PC-only engine change (section 6.2); until it exists nothing is wired into the world server,
no ticket is sent and nothing in any world or save changes. No ticket has reached any game, so nothing below is verified
in play.

## 1. What a ticket is today

The four "tickets" are the game's own event key items. Nothing in this game gives them: in Emerald only Mystery Gift
(`data/scripts/gift_aurora_ticket.inc`, `gift_mystic_ticket.inc`, `gift_old_sea_map.inc`) and record mixing for the Eon
Ticket (`src/record_mixing.c` `ReceiveGiftItem`; the Pokemon Center's distribution variable `VAR_DISTRIBUTE_EON_TICKET` is
always zero) gave them, and both need a link cable, wireless adapter or e-Reader, which the PC game does not have
(`docs/gameplay-visual-updates-20261027.md`: link features "Not available").

| Ticket (item id) | Opens | Encounters (reset descriptors) |
| --- | --- | --- |
| Eon Ticket (728) | Southern Island | Latios `0x1018` or Latias `0x1019`, level 50 with Soul Dew: the one that is not roaming (the TV choice after the Hall of Fame, `VAR_ROAMER_POKEMON`); the two descriptors are exclusive branches |
| Mystic Ticket (729) | Navel Rock | Lugia `0x1014` (bottom) and Ho-Oh `0x1015` (top), level 70 |
| Aurora Ticket (730) | Birth Island | Deoxys `0x1017`, level 30, after the island's triangle puzzle |
| Old Sea Map (731) | Faraway Island | Mew `0x1016`, level 30, after the chase in the grass |

**What having a ticket means, exactly** (code read; the engine's `multiplayer_static_reset.c`,
`data/maps/LilycoveCity_Harbor/scripts.inc`, `src/script_menu.c`):

* Two things in the save, both needed: the **key item in the Bag** and the island's **ship flag**
  (`FLAG_ENABLE_SHIP_SOUTHERN_ISLAND`, `_NAVEL_ROCK`, `_BIRTH_ISLAND`, `_FARAWAY_ISLAND`). Mystery Gift set both (and
  `FLAG_RECEIVED_*` for the last three). Lilycove's ferry attendant offers an island only with both, and only after the
  Hall of Fame (`FLAG_SYS_GAME_CLEAR`). The reset adapter's `TicketReady` requires the item in the Bag (Navel Rock also
  `FLAG_ARRIVED_AT_NAVEL_ROCK`, set on arrival) and each island descriptor's prerequisite is its ship flag; Southern
  Island's stone also checks the ship flag.
* It grants the S.S. Tidal trip to its island, as often as the player likes, and with it the island's **personal**
  encounter(s), with the Local Soft Reset's unlimited counted attempts (the attempt ledger, `reset_attempts.py`; a ticket
  is never consumed by an attempt). Nothing else: no Pokemon, no other unlock.
* **Never consumed.** No script removes a ticket. Each encounter is once per character by the game's own flags (caught or
  defeated); a legend *defeated* without being caught comes back after the next Hall of Fame entry
  (`hall_of_fame.inc`, `ResetDefeatedEventLegendaries`), the ticket still in the Bag. So a ticket is earned **once per
  character** and a second copy would do nothing.
* **Proven so far:** with the game clear and each island's ship flag set for the test (not reached by play), each ticket
  shown to Lilycove's ferry attendant sailed to its island, and without the Eon Ticket there was no trip (engine `a5013203`,
  Classic 2D test build; `docs/item-audit-20261027.md`, `TEST_LEDGER.md`). The five ticket descriptors' reset adapters
  are source-only and unverified (`docs/local-reset-ticket-sources.md`).
* **The casino:** no ticket is sold anywhere, and none was proposed: the Game Corner's RARE GOODS deliberately leave
  tickets out (engine `tools/mp/gen_rare_goods.py`, `KEY_GOODS`: "Every other key item stays out (a story item, a
  ticket, ...)"). This design adds no casino source (decision D3).

## 2. The 25 reset descriptors

Only six of the 25 need a ticket. The other nineteen are reached by the game's own story and postgame, unchanged; giving
them a ticket would be a new restriction nobody asked for (decision D6).

| Descriptors | Encounter | Ticket | How the player gets there |
| --- | --- | --- | --- |
| `0x1001`-`0x1003` | New Mauville Voltorb x3, level 25 | none | Wattson's Basement Key (story) |
| `0x1004`-`0x1005` | Aqua Hideout Electrode x2, level 30 | none | Team Aqua's Hideout (story) |
| `0x1006`-`0x1008` | Registeel, Regirock, Regice, level 40 | none | the Sealed Chamber's braille riddle, then each cave's own |
| `0x1009` | Rayquaza, level 70 | none | Sky Pillar's top once Rayquaza has calmed Sootopolis (story) |
| `0x100A` | Sudowoodo, level 40 | none | the Battle Frontier (S.S. Ticket after the Hall of Fame), the Wailmer Pail |
| `0x100B`, `0x100C` | Kyogre, Groudon, level 70 | none | Marine and Terra Cave, through the Weather Institute's abnormal weather after the Hall of Fame |
| `0x100D`-`0x1013` | Kecleon x7 (Routes 119, 120), level 30 | none | Steven's Devon Scope (story) |
| `0x1018` / `0x1019` | Latios / Latias, level 50 | **Eon Ticket** | **postgame achievement: the Elite Four rematch** (section 3) |
| `0x1016` | Mew, level 30 | **Old Sea Map** | **challenging quest: the Sealed Chamber's three legends** |
| `0x1017` | Deoxys, level 30 | **Aurora Ticket** | **challenging quest: Kyogre, Groudon and Rayquaza** |
| `0x1014`, `0x1015` | Lugia, Ho-Oh, level 70 | **Mystic Ticket** | **Battle Frontier milestone: all seven Silver Symbols, or Battle Tower: Legends floor 75** |

`legendary_tickets.TICKETS` and `GAME_PROGRESSION` hold this table; a test checks that together they name exactly
`reset_protocol.SOURCES`.

## 3. The sources (proposed defaults)

Every ticket is **once per character, not repeatable** (section 1), and every default can be met by one player alone. A
ticket earned before the Hall of Fame waits in the Bag; the ferry sails after it, as for any ticket.

| Ticket | Kind | Exact condition (default) | Detected | Setting |
| --- | --- | --- | --- | --- |
| Eon Ticket | postgame achievement | **Two Hall of Fame entries**: the Elite Four and the Champion beaten again after becoming Champion. The game's own statistic `GAME_STAT_ENTERED_HOF` (incremented when the Hall of Fame is saved, `src/save.c`) is at least 2. | the player's last host save (`SaveBlock1.gameStats[10]` XOR `SaveBlock2.encryptionKey`) | `"eon": ("hall_of_fame:2",)` |
| Old Sea Map | challenging quest | **The Sealed Chamber**: Regirock, Regice and Registeel each caught or defeated (`FLAG_DEFEATED_REGIROCK`, `_REGICE`, `_REGISTEEL`: set by a catch or a win, not by running away) | the last host save (flags) | `"old_sea_map": ("regi_trio",)` |
| Aurora Ticket | challenging quest | **The weather trio**: Kyogre, Groudon and Rayquaza each caught or defeated (`FLAG_DEFEATED_KYOGRE`, `_GROUDON`, `_RAYQUAZA`) | the last host save (flags) | `"aurora": ("weather_trio",)` |
| Mystic Ticket | Battle Frontier milestone | **Either** all seven Silver Symbols of the island's Battle Frontier (`FLAG_SYS_TOWER_SILVER` ... `FLAG_SYS_PYRAMID_SILVER`; a Gold Symbol is only won after its Silver) **or** floor 75 of Battle Tower: Legends cleared | the last host save (flags; the save's Tower record) and the host's Tower book (`best`, which no save import lowers) | `"mystic": ("silver_symbols:7", "tower_floor:75")` |

**Why these fit.**

* **Eon Ticket: the Elite Four rematch.** The Lati story starts at the Hall of Fame (the TV news that sets the roamer),
  the ferry to every island opens there, and returning to the Hall of Fame is the classic postgame achievement. The
  Hall of Fame is also where the game brings back a defeated island legend. The Eon Ticket was the original game's
  most widely given ticket and opens the lowest-level legend of the four, so it comes first.
* **Old Sea Map: the Sealed Chamber.** The Regi riddle is Emerald's longest puzzle quest (an underwater ruin found with
  Dive, braille, Relicanth and Wailord in the party, Dig, three caves with their own riddles). An ancient sea-floor
  riddle leading to an uncharted island fits a map of the old sea, and Mew is a reward of the same rarity.
* **Aurora Ticket: the weather trio.** Kyogre and Groudon are found only by tracking abnormal weather after the Hall of
  Fame, and Rayquaza at the top of the crumbling Sky Pillar: a long postgame quest about the sky. Deoxys came down
  through Rayquaza's sky; in the Generation 6 remakes Rayquaza fights it (the Delta Episode). "Aurora" is a light in
  that sky.
* **Mystic Ticket: the Battle Frontier.** It opens two level-70 legends, the most valuable ticket, so it asks for the
  hardest content. This game has two Battle Frontiers: the island's seven facilities (each Silver Symbol means beating
  its Frontier Brain once, in a streak) and the world's Battle Tower: Legends, so either counts. Floor 75 is a late
  checkpoint whose opponents are level 75 (`docs/battle-tower-legends.md`), a fair match for level-70 legends.

**Alternatives** (each a one-line change of that ticket's setting; any of a ticket's sources earns it):

| Ticket | Instead of, or beside, the default |
| --- | --- |
| Eon | `hall_of_fame:1` (at the first Hall of Fame: the most generous, like the original record-mixing ticket); `coop_league:1` (a co-op League clear, for players who play the League together; needs a teammate); `pokedex:N` |
| Old Sea Map | `trick_house` (all eight Trick House puzzles); `pokedex:N` (e.g. 150 kinds caught); `rayquaza` |
| Aurora | `rayquaza` (lighter: Rayquaza alone); `regi_trio`; `gold_symbols:1` |
| Mystic | only `silver_symbols:7`; `tower_floor:50` or `:100`; `gold_symbols:N`; `frontier_bp:N` (Battle Points the island's facilities paid, the Trainer Card's); `coop_frontier_streak:7` or `:14` (the co-op Battle Frontier's first or second Frontier Brain pair; needs a teammate); `championship_wins:1` (needs other players) |

**The conditions the code knows** (`legendary_tickets.CONDITIONS`):

| Condition | Kind | Read from | One player alone |
| --- | --- | --- | --- |
| `hall_of_fame:N` (1-999) | postgame | save: the Hall of Fame statistic (at least 1 once `FLAG_SYS_GAME_CLEAR`) | yes |
| `pokedex:N` (1-721) | postgame | save: `dexCaught`, kinds caught (National) | yes |
| `coop_league:N` | postgame | host: the co-op League's clears (`frontier.FrontierBook.league_record`) | no |
| `regi_trio`, `weather_trio`, `rayquaza` | quest | save: `FLAG_DEFEATED_*` | yes |
| `trick_house` | quest | save: `VAR_TRICK_HOUSE_LEVEL` = 8 | yes |
| `championship_wins:N` | quest | host: Championships won, four or eight places (`statistics()`) | no |
| `silver_symbols:N`, `gold_symbols:N` (1-7) | Frontier | save: `FLAG_SYS_*_SILVER` / `_GOLD` | yes |
| `frontier_bp:N` | Frontier | save: `SaveBlock2.frontier.cardBattlePoints` | yes |
| `tower_floor:N` (1-100) | Frontier | save's Tower record and the host's Tower book | yes |
| `coop_frontier_streak:N` | Frontier | host: the co-op Battle Frontier's best streak | no |

Not offered: **Trainer Card stars** (the second and third need the complete Hoenn Pokedex and the museum's paintings,
which the host does not read; the game could publish its star count, not planned) and the **eight-place Championship**
separately (counted in `championship_wins`).

## 4. Recording a grant: never twice, never lost

Detection is on the host, from two places it already reads: the player's **last save on the host** (the canonical
checkpoint the host parses for badges, Battle Points and the Tower record) and the host's **own records** (the Tower
book, the co-op Frontier and League book, the Championships). Every save offset used is pinned (section 6.4). The grant
is recorded in three places, each guarding a different failure:

1. **The host's ledger** (`legendary_tickets` table, in the world's SQLite file beside the Frontier and Tower tables): one
   row per (player, ticket) from the moment a source is met: `earned` -> `sent` (a reward word with reference
   `ticket:<name>:<attempt>` is on the player's wallet stream) -> `delivered` (receipt 1 given or 2 already owned, or a
   save showing the island open), or `owed` (receipt 0: no room) and sent again with the next attempt once the player
   has saved since. A delivered ticket is never sent again, whatever later saves or settings say.
2. **The wallet stream** (`wagers.py`, the same channel as Battle Frontier and Tower prizes): one word per (player,
   reference); the game applies each adjustment exactly once per save (`VAR_MP_WALLET_SEQ`) and answers with a receipt
   of what really happened.
3. **The save**: the ticket and its island's flags land together (engine section 6.2) and travel with the character.

| What goes wrong | What happens |
| --- | --- |
| The host stops between recording `earned`/`sent` and queueing the word | The reference is recorded first; the next pass queues it (queueing is idempotent per reference). Tested. |
| The game applies the word, then crashes before saving | Its save still holds the older wallet sequence, so the host serves the same word again and the ticket lands again, once. |
| The game saved, but its receipt was lost (disconnect, host restart) | The game reports its last receipt again on every connection (`UpdateWallet`); the ledger settles then. Tested for the ledger (restart from the same file). |
| A reloaded older save (the launcher's earlier saves) | The wallet stream re-applies the words after that save's sequence; the game never adds a second copy (it checks Bag and PC first). |
| The key-item pocket (30) and the PC are full | Receipt 0, nothing changes in the save (item and flags are all or nothing); `owed`, offered again after the player's next save on the host. Tested. |
| The character goes to another world, or comes back | The save carries the ticket and its ship flag; the other world's host sees the island open and sends nothing. Tested for the ledger. |
| The save already opens the island (any earlier source) | No row, no word. Tested. |
| A stale receipt of an earlier attempt | Ignored: only the current attempt's reference settles. Tested. |
| The owner changes the setting later | Delivered tickets stay; a ticket already earned is still delivered; the new setting applies from the next evaluation. |
| A save the host cannot read | Receipts still settle; nothing new is earned until a readable save; a "no room" settled meanwhile is offered again at the next readable save. Tested. |

The in-game banner says, for a ticket just given (receipt 1): `EON TICKET!` / `Show it at LILYCOVE's port.`

## 5. The setting: one line per ticket

`src/emerald_multiplayer/legendary_tickets.py`, `DEFAULT_SOURCES` (any of a ticket's sources earns it; 1 to 4 sources):

```python
DEFAULT_SOURCES = {
    "eon": ("hall_of_fame:2",),
    "old_sea_map": ("regi_trio",),
    "aurora": ("weather_trio",),
    "mystic": ("silver_symbols:7", "tower_floor:75"),
}
```

A world may replace whole lines with `<world>.tickets.json` beside its database (like `<world>.frontier.json`):
`{"sources": {"eon": ["hall_of_fame:1", "coop_league:1"]}}`. A file that cannot be used stops the host from starting
with half a setting (`TicketError`), naming the problem. `CASINO_PRICES = {}`: no ticket is sold.

## 6. Implementation plan

### 6.1 The contract between the engine and the app

* **Reward word kind 8** (`MP_REWARD_TICKET`) on the wallet stream: `0x48000000 | index`, index 1 Eon Ticket, 2 Mystic
  Ticket, 3 Aurora Ticket, 4 Old Sea Map, bits 8-23 zero (`rewards.py` layout: bit 30, kind in bits 24-27).
* **The game applies it** (PC only): if neither the Bag nor the PC holds the item, add one to the Bag, else to the PC; if
  neither has room, change nothing and answer 0. Then set the ship flag and the `FLAG_RECEIVED_*` flag (none for the Eon
  Ticket), exactly what the Mystery Gift scripts did. Receipt: **1** given, **2** already owned (flags made sure, nothing
  added), **0** nothing (no room, or a payload it does not know).
* **Capability**: a ROM marker `gMultiplayerTicketAbiVersion` = 1; `scripts/multiplayer/generate_manifest.py` records
  `ticket_abi_version: 1` (it needs `world_abi_version` 1). No `bridge.txt` opt-in: the game applies kind 8 whenever it
  has the code; the host sends it only when the manifest says so. **An older game must never get kind 8**: it would
  answer 0 and the ledger would offer it again at every save.

### 6.2 Engine (PC only; the GBA ROM stays byte-identical)

| File | Change |
| --- | --- |
| `include/multiplayer_world.h` | `#define MP_REWARD_TICKET 8` beside kinds 1-5 |
| `src/multiplayer_world.c` | in `MultiplayerWorld_ApplyRewardWord` (already inside `#ifdef PORTABLE`): kind 8 calls `MultiplayerTickets_Grant(payload)` |
| `src/platform/mp_tickets.c`, `include/mp_tickets.h` (new, PC build only) | the four tickets (item, ship flag, received flag), `MultiplayerTickets_Grant` (all-or-nothing as in 6.1), the ABI marker (kept with a volatile read, as the reset catalogue's) |
| `Makefile_pc` | the new file (the GBA `Makefile` does not build `src/platform`) |
| `src/platform/native_selftest_tickets.c` (new), the self-test list | `--selftest-tickets`, run by the Linux and Windows CI self-test jobs |

Checks of `--selftest-tickets`: each word on a fresh save gives one ticket in the Bag, its ship and received flags,
receipt 1; again gives receipt 2 and still one ticket; a full key pocket puts it in the PC; a full pocket and PC answer 0
and set no flag; payloads 0, 5 and nonzero bits 8-23 answer 0 and change nothing; with the ticket given, Lilycove's
ferry lists the island (the destination list in `src/script_menu.c`; the harbor script's `Get*TicketState`) and the
reset adapter's ticket check (`TicketReady` in `multiplayer_static_reset.c`) passes for its descriptors; and the
offsets of 6.4. Then: `sha256sum pokedev.gba` equal to `CHECKPOINTS.md`,
`tools/pc_port/check_gba_lines.py`, `check-native`, the MinGW build.

Only if the owner asks (decision D3): a Game Corner ticket would need the coin shop to call the same grant after a
purchase (a ticket bought must set its ship flag, which a plain shop item does not).

### 6.3 App (after the engine)

| File | Change |
| --- | --- |
| `rewards.py` | `KIND_TICKET = 8`; `encode`/`decode`/`valid_wallet_delta` accept it only with `tickets=True`, as the Tower's kinds take `tower=True` |
| `wagers.py` | `grant_reward(..., tickets=False)` passed through |
| `shared_world_protocol.validate_wallet`, `world_mailbox.WorldInbound`, `companion.CompanionConfig` | `ticket_abi_version` from the manifest; the companion passes kind 8 to the game only then |
| `bridge_config.py` | `tickets_enabled(manifest)` |
| `scripts/multiplayer/generate_manifest.py` | the marker -> `ticket_abi_version` |
| `shared_world.py` | the ledger's `SCHEMA` and `self.tickets = TicketBook(...)` (a new table: existing worlds open unchanged) |
| `ticket_service.py` (new) | per connected player: the last checkpoint parsed once per checkpoint (as `tower_service._snapshot`), `save_facts` + `with_host_records` (Tower book `best`, `frontier.record()["best_streak"]`, `league_record()["clears"]`, `_championships.statistics()["wins"]`), `reconcile` with `grant = wagers.grant_reward(player, KIND_TICKET, ticket.index, ref, tickets=True)` and `receipt = wagers.entry(player, ref)["applied"]`, the banner for each ticket given |
| `server.py` | `enable_tickets()` (like `enable_tower`), `reconcile` every 5 s and after a checkpoint commit; a fault never stops the host loop |
| `launcher_session.py` (beside its `enable_tower()` call) | enable from the manifest; load `<world>.tickets.json` before the host opens |
| `player_menu.py` | PLAYERS > World and my base > Frontier and League > **Legendary Tickets**: each ticket, its island, given / how to earn it with progress ("Enter the Hall of Fame 2 time(s): 1/2") |

### 6.4 Save offsets the host reads

Asserted at compile time today (`src/multiplayer_trade_effects.c` `STATIC_ASSERT`s): `SaveBlock1.flags` 0x1270,
`gameStats` 0x159C, `dexCaught` 0x3619 (129 bytes), `SaveBlock2.encryptionKey` 0xAC; flags 0x1270 and the game clear
flag 0x864 also by `--selftest-ladder`. To add to `--selftest-tickets`: `SaveBlock1.vars` 0x139C,
`SaveBlock2.frontier.cardBattlePoints` 0xEBA, `GAME_STAT_ENTERED_HOF` 10, `VAR_TRICK_HOUSE_LEVEL` 0x4044, the flags
`FLAG_DEFEATED_REGIROCK`..`_RAYQUAZA` 0x1BB-0x1C0, `FLAG_SYS_TOWER_SILVER` 0x8C4 (each Gold right after its Silver),
the ship flags 0x8B3, 0x8E0, 0x8D5, 0x8D6, the received flags 0x13A-0x13C and the items 728-731
(`legendary_tickets.py` names each). A test checks that these agree with the host's other readers
(`frontier_service`, `character_transfer`, `trade_effect_flash`, `tower_rules`).

### 6.5 Tests

* Built: `tests/test_legendary_tickets.py`, **30 tests, all passed** (Linux): the catalogue against the 25 descriptors
  and the item names; the offsets against the host's other readers; every fact from synthetic save blocks and once
  through `flash.inspect_flash` of a full synthetic flash container with a Tower record; parsing and refusing sources;
  the defaults (all three kinds, a solo source for every ticket, no casino); world files; the ledger (one word per
  ticket, receipts 1/2/0, owed and offered again only after a newer save, a refusal settled while no save could be
  read, a save already open, a stale receipt, a crash between recording and queueing, a host restart from the same
  file, two players, settings changed after delivery). Eleven deliberate mutations of the module (an offset, a flag,
  the receipt rules, the re-offer rules, the defaults) each made the suite fail. With `test_flash.py`,
  `test_tower_contract.py` and `test_reset_production_catalogue.py`: 87 passed, 1 skipped (`test_flash.py`'s check of
  private saves, which are not configured here).
* To add with 6.3: kind 8 in `test_rewards.py` (refused without `tickets=True`); a contract test like
  `test_tower_contract.py` (word layout, manifest marker, companion configuration); `test_ticket_service.py` with a
  real `WorldServer`, a real `Wagers` and scripted game receipts (a grant end to end, a restart, a reconnect, a game
  without the capability never receives kind 8).

### 6.6 Real-game proof (outline)

1. Engine: `--selftest-tickets` in the Linux 3D and Classic 2D test builds and under Wine; the GBA ROM's hash.
2. Two native Linux games through the real launcher and world server, test build: a test character whose conditions
   the test harness sets in its save (test code, as the ticket ferry check of `docs/item-audit-20261027.md` did; **not**
   a legitimately progressed save), saved on the host. Expected: the banner, the ticket in the Bag, the ship flag in
   the next host save; Lilycove's ferry sails to the island; the island's encounter shows `Attempt: 1` and the reset
   works (that is also the first real run of a ticket descriptor's reset adapter).
3. In the same run: kill the game after the banner and before saving (the ticket arrives again, exactly one in the
   Bag); disconnect and reconnect after saving (no second word); a full key pocket and PC (owed, then delivered after
   making room and saving); the same character in a second world (nothing sent); the other player gets nothing.
4. The same checks in the Windows CI's game processes (runners, not a PC).
5. Not claimable without the owner: a legitimately progressed character meeting a condition in real play (no recorded
   run has reached the Hall of Fame), the island Battle Frontier's Silver Symbols on the PC game, a real Windows PC.

## 7. Decisions: which need the owner

| # | Decision | Kind | Default here | Alternatives |
| --- | --- | --- | --- | --- |
| D1 | Which achievement opens which ticket, and how much (section 3) | **Major (gameplay)** | Eon: two Hall of Fame entries; Old Sea Map: the Sealed Chamber's three; Aurora: the weather trio; Mystic: all seven Silver Symbols or Tower floor 75 | per ticket, section 3's alternatives |
| D2 | May a source need other players (co-op League, co-op Frontier, Championships)? | **Major** | only as extra ways beside a solo one; none by default | add `coop_league:1` to the Eon line, `coop_frontier_streak:14` to the Mystic line, ... |
| D3 | A Game Corner ticket | **Major** (economy) | none (none exists or was proposed) | a coin price per ticket, sold only beside an achievement; needs the engine's grant in the coin shop (6.2); the price is yours (the Shiny Charm and key RARE GOODS cost 15,000 coins) |
| D4 | A character that already meets a condition gets the ticket at its next save on the host | routine | yes | only achievements made after this version (would need a recorded baseline per character) |
| D5 | Delivered by the host with a banner, like Frontier and Tower prizes | routine | yes | collected from an NPC (Lilycove's sailor or the Pokemon Center's Mystery Gift man): an engine script per ticket |
| D6 | Tickets only for the six island encounters; the other nineteen keep the game's own access | routine (reading of the decision) | yes | if "tickets for personal static legendaries" meant a new permit for all 25, that is a different, restrictive feature: say so |
| D7 | The Lati: only the one that is not roaming, as in Emerald | routine (unchanged) | yes | - |

## 8. Files

* `src/emerald_multiplayer/legendary_tickets.py`: the catalogue, `GAME_PROGRESSION`, the conditions, `save_facts`,
  `with_host_records`, `DEFAULT_SOURCES`, `load_sources`, `earned_by`, the ledger (`SCHEMA`, `TicketBook`) and
  `reconcile`. Imported by nothing yet.
* `tests/test_legendary_tickets.py`.
* Background: `docs/local-reset-ticket-sources.md` (the five island adapters), `docs/local-reset-production-flow.md`,
  `docs/battle-tower-legends.md` (the wallet stream's prize pattern this follows), `docs/battle-frontier.md`.
