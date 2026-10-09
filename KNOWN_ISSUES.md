# Known issues

Confirmed problems only. Severity: Blocker / High / Medium / Low.

## Native PC build (branch `claude/native-pc`)

| ID | Severity | Issue | Reproduction | Status |
| --- | --- | --- | --- | --- |
| N1 | High | Crash in Professor Birch's intro: `Task_HandleMonAnimation` read `gBattleStruct` (NULL outside battle). Harmless on the GBA (reads BIOS), fatal natively. | New game, advance Birch's speech until Lotad appears. | Fixed with `NATIVE_NULL_GUARD` (`src/pokemon_animation.c`). |
| N2 | High | Naming screen sprite and VBlank callbacks ran one frame after the screen data was freed (7 NULL accesses). | Confirm the player's name. | Fixed: callbacks return when the data is gone (`src/naming_screen.c`). |
| N3 | High | Menu cursor (▶) invisible and stray glyph pieces ("NO" showed as "NOI"); text at tile-aligned positions was also drawn into the next tile. Cause: `1 << 32` and `x >> 32` in the glyph copy, 0 on ARM but unchanged on x86. | Any YES/NO or list menu. | Fixed with `ARM_LSL32`/`ARM_LSR32` in `src/text.c`; needs a visual re-check. |
| N4 | Medium | The RHH "Powered by" logo in the intro looks corrupted. | Launch; first intro screen. | Open. |
| N5 | High | Every player would get the same Trainer ID and RNG seed: the GBA hardware timers used for seeding do not run natively. | New game. | Fixed: host-clock entropy seeds the RNG (`Platform_GetEntropy32`). |
| N6 | Medium | Soft reset (A+B+START+SELECT, Ctrl+R) exits the program instead of restarting. Local Soft Reset depends on a real in-process reset. | Press the reset chord in-game. | In progress: `src/platform/game_memory.c`. |
| N7 | Medium | Integer division by zero crashes on x86 but returns a value on the GBA. | Any such code path (none seen yet in play). | Mitigated at runtime by `fault_compat.c`; sites are logged and must be fixed in source (the compiler may still mis-optimise them). |
| N8 | Low | `src/platform/bios.c` contains code derived from VBA-M (GPL-2.0+) and mGBA (MPL-2.0). | — | Open: replace with an independent GBATEK-based implementation or comply before giving the build to anyone. |

## Emulator build and gameplay (from the 2026-10-09 audit)

| ID | Severity | Issue | Status |
| --- | --- | --- | --- |
| G1 | Medium | `trade_effect_choice.py:53` still refuses a trade where a Pokémon that knows a post-Gen-6 move evolves and must choose a move; the owner decided post-Gen-6 moves trade as-is. | Open |
| G2 | Medium | `docs/balance-defaults.md`, cited by four source files, does not exist. | Open |
| G3 | Medium | The 120-second World Event claim release after a disconnect could let two players catch the same event Pokémon. | Open (needs a test) |
| G4 | Low | World Event timers keep counting while nobody is online (the world clock pauses). | Open (owner to confirm intent) |
| G5 | Info | The in-game clock runs 12x for everything time-based, including berries and daily events (consequence of 1 world day = 2 real hours). | Confirm with owner |

Decision pending (not a bug): the newest directive lists "shared wild spawns"; the
owner earlier chose personal spawns. See `PROJECT_SPEC.md`.
