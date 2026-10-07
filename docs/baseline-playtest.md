# Baseline gameplay and save checks

This checks the unmodified RHH engine before multiplayer or custom gameplay. Automated build/tests alone do not complete Phase 1. Leave results pending until they are observed in mGBA.

## Gameplay

Use client A's isolated baseline ROM and save folder. Do not use savestates as evidence of ordinary saving.

Open `C:\Users\kashh\AppData\Local\PokemonPrivate\artifacts\baseline\playtest\client-a\Open-Client-a.cmd` to launch or reopen client A. Client B's matching shortcut is in the neighboring `client-b` folder. Each shortcut supplies its own save directory; use the same shortcut after closing mGBA.

| Check | Action and expected result | Result |
| --- | --- | --- |
| Boot | Reach the title screen, start a new game, and create a character. | Pending |
| Map transitions | Reach Littleroot and enter/leave buildings without a crash. | Pending |
| Starter | Obtain a starter, complete the introductory battle, and inspect the party. | Pending |
| Wild battle | Enter an ordinary wild encounter and complete it normally. | Pending |
| Capture | After obtaining Poké Balls, catch a Pokémon and verify it in the party. | Pending |
| Menus | Open party and bag; inspect the caught Pokémon and use an available item. | Pending |
| Storage | When available, deposit and withdraw a Pokémon and verify its identity. | Pending |
| Save/reload | Save through the game menu, close mGBA, reopen the same ROM, and choose Continue. Confirm name, map, party, and inventory. | Pending |

## Two-client isolation

Each emulator instance must use a different ROM directory and an explicit, different save directory. Label them A and B. These are two local single-player games; networking does not exist yet.

1. Create a different trainer name in each client.
2. Make the party or location visibly different and save each through the game menu.
3. Close both instances normally.
4. Reopen each with its own save directory and verify both trainer names and distinct progress.
5. Preserve both save files before experimentation.

Result: **Pending**. A second open window alone does not establish save isolation.

## Acceptance

Record the ROM hash, client identity, observed result, and any reproduction steps for a failure. Create `BASELINE_BUILD` only after the clean build reproduces, upstream checks pass or a specific upstream exception is documented, gameplay succeeds, and both independent saves survive close/reopen. The baseline is not a multiplayer release.
