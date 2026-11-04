# Decisions only the owner can make

Collected 2026-10-15 from the autonomous work queue (`DEVELOPMENT_LEDGER.md`) and the six-issue diagnosis. Nothing
below was decided or built by assumption; each row says what is waiting and a recommendation. Recommendations are not decisions.

## Needed before anyone else plays the Windows build

| # | Decision | Why it is open | Recommendation |
| --- | --- | --- | --- |
| 1 | **`src/platform/bios.c` licensing (N8)** | Contains code derived from VBA-M (GPL-2.0+) and mGBA (MPL-2.0); KNOWN_ISSUES says to replace it "before giving the build to anyone". **Reviewed in Update 7 (`docs/bios-licensing-review.md`): still unresolved, nothing changed.** This is a licensing judgment, not legal advice. | Keep every build private. Before any handover, have the 12 functions rewritten by someone who has not copied VBA-M/mGBA code, from GBATEK, validated by `check-decompress` and new tests (details and caveats in the review). |
| 2 | **Where the base game dump comes from for CI** | The full Windows package builds without the dump, but the *import of the owner's own game* is disabled without it (sha256 `a9dec84d…85af`). | Keep importing on the player's own PC (current design). For CI, a self-hosted runner or a private secret URL; never commit the dump. |
| 3 | **Whether to ship the Classic 2D game in every package** | The graphics-mode fallback needs the second executable (about 35 MB on top of 90 MB). | Yes: it is the only fallback when a PC's OpenGL is too old. |

## Gameplay rules left open

| # | Decision | Detail |
| --- | --- | --- |
| 4 | **Co-op Gym EXP: farming** | **Decided 2026-11-04 (the owner: "fix the co-op EXP farming exploit"); built, engine `1b2c0089`:** a co-op Gym battle awards its experience only with the win that earns this player the badge, the option this row recommended ("award EXP only on a first win per player"). A loss or a draw awards none, and neither does a helper's win (a helper who already beat the Leader, or for Norman cannot yet challenge him alone); the helper's prize money is unchanged (once per teammate who earns the badge, so at most three times per Gym in a world of four). Ladder battles (Frontier, League, Tower Duo) keep the host's rules. Was: the offer was blocked only for a player who had fought the Leader, so EXP (and, for helpers, prize money) repeated by losing again after knocking out foes, and in groups of three or four. If you would rather keep some EXP for a lost attempt (as a solo loss gives in the original game), the other option is "each of the Leader's Pokemon gives its EXP once per player" (a small save record per Gym); say so. |
| 5 | **Co-op EXP persistence** | **Decided 2026-11-04 (the owner: "ensure pending EXP cannot be lost during resets"); built, engine `1b2c0089`:** a co-op battle's result waiting for its script (the Gym or ladder, the outcome and the EXP it awards) is in every save made meanwhile (a 76-byte PC-only record in SaveBlock3, all zeros when nothing waits, as in every older save); the game asks for the host save as soon as the battle has released the field and runs the result script once it is made, and saves on the host again after the script; a save loaded with a result waiting runs it once. Left: a game that crashes in the second or two between the battle's end and that first host save still goes back to the save before the battle (for a Gym, without the badge too, so the battle can be fought again; for the Tower Duo the floor stays the host's, its EXP is lost). Was: the award was in memory only and lost (never doubled) if the game reset before the award script. |
| 6 | **Co-op Battle Frontier / League (built in Updates 8 and 10, completed in Update 16)** | Built with defaults you may change (`docs/battle-frontier.md`, `docs/pokemon-league.md`): Level 50 default, 3-Pokémon teams (you now choose them from a larger party; the full party returns exactly afterwards); money prizes plus **Battle Points** (to your save's own BP counter) and a **first-clear item per Brain round**, a **BP shop** (its own prices: vitamins 16 BP, Quick Claw/King's Rock/Focus Band 32, Leftovers 48, Choice Band 64; the game's own corner charges 1 BP for vitamins and 48-64 for held items, see `docs/balance-and-controls-review.md`); no EXP in the Frontier; a draw ends a run; an aborted-after-start battle voids the round; repeating a cleared round pays 10% money and half the BP; League needs 8 badges, is money-only, partner for Wallace is Steven, a first-clear bonus once per player, EXP only while someone is a first-timer. Say which defaults to change (BP rates, the item table, shop prices, the party limit).
| 7 | **Secret Bases** | Built with defaults you may change (Update 2): every player's base is shared with everyone unless they pick teammate-only or nobody (Players > World and my base); visitors keep a copy in their own save (the original's storage); the owner's party is the base trainer; no NPC base teams; a base that clashes with your own location is not shown. Say if the default should be private. |
| 8 | **Dynamic legendary events** | Built with defaults you may change (Update 4): 60% of legendary / mythical / mega-legendary events start *dormant* (nobody sees the Pokémon) and wake once: by the type's condition (water/electric: rain, ground/rock: sandstorm, ghost/dark/psychic/fairy: night, fire: day, ice: dusk, others: two trainers on its map), 5 minutes are guaranteed after waking. Weather means *any connected player's game reports it*, wherever they are (Emerald's route weather is mostly scripted, so a per-route rule would rarely trigger); change `BALANCE.event_condition_chance` (0 = off) or the type table in `event_conditions.py`. **G3 is now decided by the default you asked for (Update 11):** the first valid reported catch wins, in the order the host receives reports (a report is valid when its sender claimed that event); the other trainer's battle ends with "X caught it first" and the Pokémon is gone for them. Limit: a game that already caught the Pokémon offline keeps its own copy in its save (the host cannot remove it), so a second *recorded* owner is impossible but a second physical copy is possible only if two games both finished the battle before either reported. See `docs/legendary-catch-resolution.md`. |
| 9 | **Day counters on the world clock (G13)** | The daily reset and berries follow real time; the Pacifidlog TM gift, Mossdeep's weekly events and match-call rematch timers still run 12x as fast while connected. Keep (world time) or move onto real time? |
| 10 | **Post-Gen-6 moves in trades (G1)** | Your decision was that they trade unchanged. **Done 2026-11-04** under your instruction to fix what keeps the intended gameplay: an evolution trade that must choose a move no longer refuses a Pokémon that knows one (KNOWN_ISSUES G1). Nothing for you to decide. |
| 11 | **Personal static legendaries: ticket path** | 25 reset descriptors exist but no ticket source is granted. Where do tickets come from? |
| 12 | **Character customization scope** | A roster of selectable characters and a palette editor exist; free-form hair/clothing mixing and creation at game start do not. Is the roster enough? |

## Test and polish policy

| # | Decision | Detail |
| --- | --- | --- |
| 13 | **The 39 upstream GBA test failures (GEN_6 profile)** | All pass under upstream's `GEN_LATEST GEN_9`; they differ because this game runs Gen 6 rules. Pin the tests to Gen 9, mark them expected failures, or leave them listed? Recommendation: keep a checked-in expected-failure list so a new failure is noticed (see the ledger). |
| 14 | **M27 wording** | Done as PC-only text ("START menu: PLAYER, then STYLE"); the GBA text is unchanged. Say if you prefer an arrow glyph added to the banner font instead. |

## Needs your PC or your data

* Real-hardware play on Windows: the 3D game with a real GPU, audio, fullscreen and DPI, the rebinding page with a real keyboard, the graphics-mode fallback on an old GPU.
* The full-six interrupted-battle recovery proof (your four private source parties, about two hours).
* Two real PCs over a real network (M25's real-game gain, 2v2).
* The sprite pack (`SPRITE_PACK_SHA256`) for the packaged battle sprites.


## Added by Updates 8-14

| # | Decision | Detail |
| --- | --- | --- |
| 15 | **Four-player free-for-all (1v1v1v1) — built in Update 15** | Built with defaults you may change (`docs/free-for-all.md`): a hazard move lands only on the side of the trainer it was aimed at and Court Change swaps with that trainer's side; Follow Me/Rage Powder/Helping Hand/Ally Switch do nothing; no running or forfeit; a simultaneous last faint is a draw; no EXP and no wager; the host keeps a win/draw/loss record only. Visuals reuse the doubles layout (polish would need new four-position art/layout work). Say which rules to change. |
| 16 | **Legendary catch ownership** | Rule implemented as you specified (first valid reported catch wins, host order). Update 17 closes the old limit: the game records the catch in its own save, the host decides once, and the losing copy is released by a verdict sent over the wallet stream (only that Pokémon, never the last party member; a traded/evolved copy and record-less older saves are left alone). Decision for you: keep this automatic release, or make the losing player confirm it? (`docs/legendary-catch-resolution.md`). |
| 17 | **Graphical PokéNav map with player markers** | Built in Update 18 with the game's own art only (`docs/graphical-pokenav-map.md`). Your calls: (a) the borrowed event/outbreak markers versus new art (list of missing art in the doc); (b) whether other players' places should be hideable (today everyone connected is visible, as in the text page); (c) whether SELECT needs a help-bar hint. |
| 19 | **Update 20 build** | Private Windows package built by GitHub Actions only; bios.c licensing still unresolved, so nothing is cleared for distribution. |
| 18 | **Gen 6 purity of expansion switches** | PC build now turns off Gen 9 running from trainer battles and Gen 8 thunderstorm terrain. Kept on: extrapolated move flags and X-item cross-use. Say if you want those off too. |

## Added by Updates 21-25
| # | Decision | State |
|---|---|---|
| 21 | **Xbox B as Cancel.** Update 24 made the right face button (B) a GBA B too (it did nothing; X was the only B). One line in `gamepad.c` and its test oracle to revert. | Built; your call |
| 22 | **3D vehicles.** Trucks (Littleroot at the start), Cable Car, S.S. Tidal, Seagallop, Rayquaza are drawn from several sprite pieces: the 3D view falls back to 2D while one is on screen. Build a composite texture (moderate work) or accept. | Open |
| 23 | **Loudness.** The audio audit showed music about -18 dBFS peak at full volume; the make-up gain went from 2 to 4 (+6 dB, no clipping measured). Needs your ears. | Built; your call |
| 24 | **BP shop prices** differ from the game's Exchange Service Corner (vitamins 16 vs 1 BP; Quick Claw 32 vs 48; King's Rock and Focus Band 32 vs 64) and BP rates look generous (39 BP for 21 rounds). `docs/balance-and-controls-review.md`. | Open |
| 25 | **Location privacy** is in the PokeNav Players page (default ON, per character). A launcher checkbox was not built. A hidden player is still visible to the host's operator and to players on the same map. | Built |

## Decided 2026-10-31 (the owner's answers on the TM catalogue and the Game Corner item hub)

The proposals: `docs/` will hold them with the implementation; the TM proposal (168 TMs, prices, categories) and the
item hub proposal (198 items) were sent to the owner on 2026-10-31.

| # | Decision | The owner's answer |
| --- | --- | --- |
| 26 | **TM prices** | The tiers as written: 1,000 / 2,500 / 5,000 / 7,500 / 10,000 coins (not the 15% scale of 2026-10-25). The five TM prizes keep their prices. |
| 27 | **Which Pokemon a TM teaches** | "any pokemon that can actually learn the tm, from gen 1-6 ... if it was able to learn some from gen 1-6 they can learn it": a TM teaches a move to a species that learned that move by TM in any Gen 1-6 game (the union of those games). Replaces the 2026-10-27 rule for TMs (tutors keep it); the original request's custom extension, Ferrothorn and Stealth Rock, stays, documented. Pokemon that already know a move keep it. |
| 28 | **The save** | Yes: a PC-only "TMs owned" record so all 168 TMs and 8 HMs fit (the Bag's TM pocket has 64 slots). |
| 29 | **When the TMs are sold** | All tiers from the start. |
| 30 | **New items' prices** | "dont change existing price ... make items cost appropriate if their good items not cheap": existing prices unchanged; new items priced by how good they are. Master Ball sold for 200,000 coins; Rare Candy 5,000; Bottle Cap 2,500 and Ability Capsule 5,000 (the "cheaper" choice). The revised table goes to the owner before it is applied. |
| 31 | **The item hub's price table** | "yes approve" (2026-10-31, the revised table: 198 new items and the Town Map, nothing sold today changed): as written, so the vitamins at 300 coins (as the Mochi), the Psychic Seed on sale at 750 (like the other Seeds, though nothing here sets Psychic Terrain), the Floettite left on sale, the Master Ball 200,000 with repeat purchases. |

## Decided 2026-11-03 (the owner's answers on step 18, the next package and the rooms' furniture)

| # | Decision | The owner's answer |
| --- | --- | --- |
| 32 | **Who fills places 5-8 of the eight-competitor Championships** (step 18; worlds stay at 4 players) | "Computer trainers": Battle Frontier trainers under the same entry rules fill the empty places. A player against one is a normal battle in that player's own game; two players still use the existing challenge flow; when two computer trainers meet, the higher-ranked one goes through without a battle. Bracket 8 -> 4 -> final. |
| 33 | **A new Windows package with step 15c** (engine `b1a94915`) | "Wait for more changes": 15c goes into a later package together with the next fixes (a package still needs the owner's go-ahead). |
| 34 | **The rooms' furniture in 3D** (MS-164; the try of 2026-10-30 was reverted after the owner's Game Corner and Lilycove report, MS-173) | "Go ahead": rework the rooms and commit the ones that pass the checks; the owner looks at them in the next package. |

Step 18 as built (engine `a978b0c5`, app `3851488`; `docs/championships-eight.md`) follows #32 and fills in what the
answer left open with defaults the owner can change. Each is one setting.

| Default | As built | Why |
| --- | --- | --- |
| Experience in a match against a computer trainer | None (neither experience nor effort values) | A Championship has no prizes, a link battle between two players gives none, and a level-capped rule stays fair (a level-50 Pokemon would otherwise reach 51 mid-bracket). The host's command carries the choice, so turning it on needs no game change. |
| Fewest players | 2 | One player alone could otherwise win a Championship (and its Trainer Card counter) against computer trainers only. |
| Which Tower floors | An even spread from the strongest player's best level down to the weakest's, under the rule, ranked by floor | Each player meets trainers near their own strength. |
| A started match whose result never came | A loss once the player gives it up (15 s after their game connects) or after 24 hours | The Battle Tower's own rule (quitting forfeits). |
| The entry rule | The rule in force at the proposal, kept with the bracket; checked at proposal, acceptance and before every match | A rule that rotates mid-bracket changes nothing. |

