# Baseline gameplay and save checks

This checks the unmodified RHH engine before multiplayer or custom gameplay. **Passed October 7, 2026**, through ordinary joypad input in the real pinned mGBA 0.10.5 core. Results were observed in emulator framebuffers and read-only samples, with fresh processes for ordinary Flash reload. [Build and acceptance evidence](baseline-build.md)

## Gameplay

Use client A's isolated baseline ROM and save folder. Do not use savestates as evidence of ordinary saving.

Manual desktop shortcuts remain at `C:\Users\kashh\AppData\Local\PokemonPrivate\artifacts\baseline\playtest\client-a\Open-Client-a.cmd` and the neighboring `client-b` folder. Each supplies its own save directory. The accepted automated gameplay evidence uses separate, private `headless-proof` saves; do not confuse those verified copies with the manual profiles.

| Check | Action and expected result | Result |
| --- | --- | --- |
| Boot | Reach the title screen, start a new game, and create a character. | Pass: Aaa and Aaaa created normally. |
| Map transitions | Reach Littleroot and enter/leave buildings without a crash. | Pass: houses, routes, Oldale Mart and Pokémon Center. |
| Starter | Obtain a starter, complete the introductory battle, and inspect the party. | Pass: Torchic defeated the introductory Zigzagoon. |
| Wild battle | Enter an ordinary wild encounter and complete it normally. | Pass: ordinary wild victories and capture. |
| Capture | After obtaining Poké Balls, catch a Pokémon and verify it in the party. | Pass: Wurmple acquired through normal capture. |
| Menus | Open party and bag; inspect the caught Pokémon and use an available item. | Pass: party, bag, Poké Balls, and Potion use. |
| Storage | When available, deposit and withdraw a Pokémon and verify its identity. | Pass: Wurmple deposited in Box 1 and withdrawn. |
| Save/reload | Save through the game menu, close mGBA, reopen the same ROM, and choose Continue. Confirm name, map, party, and inventory. | Pass: final fresh process restored both party records and four Poké Balls. |

## Two-client isolation

Each baseline instance uses an explicit, different Flash save path. Label them A and B. This test verifies two single-player characters; it is not evidence of connected multiplayer.

1. Create a different trainer name in each client.
2. Make the party or location visibly different and save each through the game menu.
3. Close both instances normally.
4. Reopen each with its own save directory and verify both trainer names and distinct progress.
5. Preserve both save files before experimentation.

Result: **Pass**. Fresh processes restored Aaa at Littleroot `(4,11)` with Torchic/Wurmple, and Aaaa at `(5,9)` with its separate early-game state. Different trainer IDs and Flash hashes were verified and archived. The owner's original save remained unchanged.

## Acceptance

The engine's `BASELINE_BUILD` tag preserves the exact unchanged source after reproducible builds, recorded upstream exceptions, observed gameplay, and independent Flash reloads. See the build record for hashes and the caught/corrected overwrite-confirmation mistake. This checkpoint is not a multiplayer release.
