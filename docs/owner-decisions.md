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
| 4 | **Co-op Gym EXP: farming** | The offer is blocked only for a player who already fought that Leader. EXP (and, for helpers, prize money) can repeat by losing again after knocking out foes, and in groups of three or four while someone who has not beaten the Leader asks a helper who has. Recommendation: accept it like wild-battle farming, or award EXP only on a first win per player. |
| 5 | **Co-op EXP persistence** | The pending award is memory only and is lost (never doubled) if the game resets in the few seconds before the award script. A fix needs a save-layout change that touches every save. Recommendation: accept the window. |
| 6 | **Co-op Battle Frontier / League (built in Updates 8 and 10)** | Built with defaults you may change (`docs/battle-frontier.md`, `docs/pokemon-league.md`): money-only prizes through the wallet channel; Level 50 default, 3-Pokémon opposing teams; no EXP in the Frontier; a draw ends a run; an aborted-after-start battle voids the round; repeating a cleared round pays 10%; League needs 8 badges for both, partner for Wallace is Steven, a first-clear bonus once per player, EXP only while someone is a first-timer. Items/BP as prizes and choosing a subset of a larger party inside the battle need new native-protocol channels (Opus-level design). Say which defaults to change. |
| 7 | **Secret Bases** | Built with defaults you may change (Update 2): every player's base is shared with everyone unless they pick teammate-only or nobody (Players > World and my base); visitors keep a copy in their own save (the original's storage); the owner's party is the base trainer; no NPC base teams; a base that clashes with your own location is not shown. Say if the default should be private. |
| 8 | **Dynamic legendary events** | Built with defaults you may change (Update 4): 60% of legendary / mythical / mega-legendary events start *dormant* (nobody sees the Pokémon) and wake once: by the type's condition (water/electric: rain, ground/rock: sandstorm, ghost/dark/psychic/fairy: night, fire: day, ice: dusk, others: two trainers on its map), 5 minutes are guaranteed after waking. Weather means *any connected player's game reports it*, wherever they are (Emerald's route weather is mostly scripted, so a per-route rule would rarely trigger); change `BALANCE.event_condition_chance` (0 = off) or the type table in `event_conditions.py`. **G3 is now decided by the default you asked for (Update 11):** the first valid reported catch wins, in the order the host receives reports (a report is valid when its sender claimed that event); the other trainer's battle ends with "X caught it first" and the Pokémon is gone for them. Limit: a game that already caught the Pokémon offline keeps its own copy in its save (the host cannot remove it), so a second *recorded* owner is impossible but a second physical copy is possible only if two games both finished the battle before either reported. See `docs/legendary-catch-resolution.md`. |
| 9 | **Day counters on the world clock (G13)** | The daily reset and berries follow real time; the Pacifidlog TM gift, Mossdeep's weekly events and match-call rematch timers still run 12x as fast while connected. Keep (world time) or move onto real time? |
| 10 | **Post-Gen-6 moves in trades (G1)** | Your decision was that they trade unchanged; the code still refuses an evolution trade that must choose a move for such a Pokémon. In a Gen 6 game a Pokémon cannot normally know one, so it is rare; say whether it is worth the fix. |
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
| 15 | **Four-player free-for-all (1v1v1v1)** | Not built: the engine is two-sided in about 700 places (`docs/free-for-all-feasibility.md`). It is a separate architecture project. Is it worth funding, and with real four-PC testing? |
| 16 | **Legendary catch ownership** | Rule implemented as you specified (first valid reported catch wins, host order). Limit: the host cannot remove a Pokémon from a save, so two games that both finished a catch before either reported could both hold a copy (`docs/legendary-catch-resolution.md`). |
| 17 | **Graphical PokéNav map with player markers** | Not built (needs Town Map sprites and a visual check); text locations and a habitat page exist. |
| 18 | **Gen 6 purity of expansion switches** | PC build now turns off Gen 9 running from trainer battles and Gen 8 thunderstorm terrain. Kept on: extrapolated move flags and X-item cross-use. Say if you want those off too. |
