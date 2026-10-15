# Secret Bases and PokéNav (Update 12)

Everything below is **simulated-tested only** (engine native self-tests, app tests with scripted bridges). Nothing has been seen
in a running game window or on real hardware.

## Secret Bases

| Part | How it works | Evidence |
|---|---|---|
| Persistent decorations | A base is the game's own 160-byte `struct SecretBase` (location, owner, decorations + positions, party). The engine copies it into each visitor's save through the original's record rules, so decorations survive saving and are kept by every save that has the base. The host stores the owner's latest record (`secret_bases` table) and re-offers it. | `--selftest-secret-base`; `test_secret_bases.py` |
| NPC trainer team | The original defends a base with the owner's saved team (`SecretBase.party`) but only writes it when two games mix records, so a shared base would show an empty or stale team. The engine now refreshes the **own** base's party (`SetPlayerSecretBaseParty`) every ~5 s while the player is in the calm overworld (never inside a base, in a menu or script, or disconnected) and the changed record is republished. Visitors then meet the team the owner really carries, through the game's unmodified base-battle script. Only species/moves/held item/level/EVs/personality travel (the original's own fields). | `--selftest-secret-base` (36 checks, 7 on this) |
| Multiplayer visiting | A visitor receives the owner's record (only in the calm overworld outside every base), registers or walks to it like any original record-mixed base. | selftest mailbox checks; `test_secret_bases.py` |
| Visibility | Players > World > My Secret Base cycles **Everyone** (default) / **Teammate** / **Nobody**; the host filters what it offers each player. | `test_secret_bases.py` |
| Save / recovery | The base lives in the save; the host keeps the last record, so a reconnect or host restart re-publishes it. A Nobody base is withdrawn from others (tombstone record). | tests above |

**Not provided:** a base-battle result is not sent to the owner (the original has none), and bases are not editable by visitors.

## PokéNav (the "World" pages in the Players menu)

The pages are host-driven menu pages (≤ 6 rows) reached from Players > World and my base.

| Page | Data (all from the host, nothing invented) |
|---|---|
| World | host clock + time of day, players online |
| Players and weather | each player's place (map name from the game's map table) and weather |
| Outbreak / Event | the active outbreak or world event, remaining time, place |
| **This area's wild Pokemon** (new) | the host's own encounter tables for the map the player stands on: level range, the three most common species *now* (time of day and weather weighting, evolution stage by level), favoured types. It is the same table the shared wild Pokémon use (`scripts/multiplayer/check_engine_spawn_weights.py` compares it with the game). An area without a table says "No wild Pokemon data" instead of guessing. |
| My Secret Base | visibility cycle |
| Frontier and League | Frontier / League hub, entry rule |

### Graphical map (Update 18)

Delivered: see [graphical-pokenav-map.md](graphical-pokenav-map.md). The original Town Map now shows the other players, the World Event
and the outbreak, with SELECT jumping between them; the text pages above remain as the fallback. (The earlier "not delivered" note
here is superseded: the screen could be looked at once the engine gained a headless debug scene.)
