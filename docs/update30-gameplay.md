# Update 30 — shiny odds, breeding, eggs, the Day Care queue, the economy audit and multiplayer isolation

Engine branch `claude/dev-update30-gameplay`, app branch `claude/dev-update30`. Everything here was measured in the cloud (headless, xvfb,
software rendering, no GPU, no second PC). The main menu, saved servers and character loading of the same update are in
[update30-main-menu.md](update30-main-menu.md). Wild levels, Legendary/Mythical spawns, the Safari Zone and Mega prices (phases 1–4 and 9) were
implemented and verified in [Update 29](update29-encounters.md) and are not repeated; this update re-ran their checks (section 8).

## 1. Shiny odds (phase 5)

| Case | Rolls / mechanism | Target | Measured, 20,000,000 each |
|---|---|---|---|
| normal wild | one 1/4096 roll | 1 in 4096 | 1 in 4131 (4,841 of 4,883 ± 70) |
| normal wild + Shiny Charm | one roll, plus a second roll that happens 41848/65536 of the time | 1 in 2500 | 1 in 2482 (8,058 of 8,000 ± 89) |
| Safari Zone | two rolls | 1 in 2048 | 1 in 2042 (9,794 of 9,764 ± 99) |
| Safari Zone + Charm | four rolls | 1 in 1024 | 1 in 1020 (19,611 of 19,524 ± 140) |
| shared wild Pokémon (multiplayer) + Charm | the host's 1/4096 roll, plus the Charm owner's own hash bonus | 1 in 2500 | 1 in 2500.0 (3,135 extra of 3,118 ± 56) |

All of it is `src/pokemon.c` `ComputePlayerShinyOdds` (PC only; the GBA ROM keeps the original odds and is byte-identical) and
`src/multiplayer_spawns.c`. The Charm adds nothing to the Legendary/Mythical chance (1,018 in 6,000,000 Route 101 encounters, expected 1,000 ± 32). Random Legendaries and
Mythicals use the same rolls, so a Safari Charm owner has 1/1024 for them too. A shiny already owned is never rerolled or rewritten; nothing changes a stored Pokémon. `--selftest-shiny`: 12 checks, 0 failed.

**The Charm.** A Key Item in the player's own bag: individual, never shared, not tradable (key items cannot be held or sold), not tossable. It costs **100,000
Game Corner coins** at the Mauville prize clerk (the Coin Case holds up to 999,999; coins can also be bought with money), is guaranteed, and the clerk's list marks it owned once the player has it
so it cannot be bought twice. `tools/pc_port/economy_check.py` runs the purchase headless. The coin economy audit of Update 29 stands (Mega Ring 25,000; common stones 30–40k, rare
60–100k; each stone's price is a fixed function of the stone).

## 2. Breeding and eggs (phases 6–8)

* **Egg checks come every 64 steps** (it was 256): the 64th step of a deposit runs one check, then every further 64. The old compatibility chances are untouched: 70 % same species from
  different trainers, 50 % different species from different trainers or the same species from the same trainer, 20 % different species of the same trainer, and 0 % incompatible pairs
  (two males, two females, two Ditto, a Ditto-less genderless pair, different egg groups, the "undiscovered" group, which holds every Legendary and Mythical, with or without Ditto).
  `--selftest-breeding`: 100,000 checks per class gave 69,811 / 50,138 / 19,965 eggs (expected 70,000 ± 145 / 50,000 ± 158 / 20,000 ± 126); 20,000 incompatible checks gave 0 eggs; 63 steps never make one.
* **Hatching takes a quarter of the steps**: an egg of C cycles hatches in 32 × (C + 1) steps (it was 128 × (C + 1)); each species keeps its own cycle count (a Pichu egg of 1 cycle: 64
  steps, a 40-cycle egg: 1,312). **Flame Body or Magma Armor** in the party halves the cycles once (two such Pokémon do not stack: 672 steps for the 40-cycle egg).
* **Every egg hatches at level 1**, whatever its parents' levels.
* **The Day Care holds up to five uncollected eggs.** They are made when they are due, kept in order, handed out oldest first, and never overwritten, duplicated or lost: a sixth is refused and the Day Care keeps
  breeding only as room is made. The woman's usual offer is made for the oldest; when the party is full she says so and every egg stays; turning an egg down (answering No twice) drops
  only the oldest. The queue is **part of the save**: 412 bytes after the 600-byte ownership profile in SaveBlock3 (a magic, a count, five eggs of 80 bytes each, a CRC-32), so it survives
  saving, quitting, host reconnects and the server's checkpoints (the Python save validator and the engine's multiplayer import both check it, and refuse a damaged queue). A save from before this
  update has zeros there and reads as an empty queue; the old "an egg is waiting" flag without a queue still gives one egg. The shape is checked by `check-abi` and the GBA ROM is untouched.
* **Eggs in the PC hatch too** (the owner's decision of 2026-10-27; until then they never hatched there). Every Egg in all 14 boxes spends its cycles on the same 32-step check as the
  party's Eggs, at the same rate: the party's Flame Body or Magma Armor halves the cycles for the boxes too, and an Egg never hatches sooner in a box than it would in the party
  (`--selftest-breeding`: the same step count as a party Egg for 0, 1, 7 and 20 cycles, with and without Flame Body). An Egg whose cycles have run out hatches **in its own box slot**:
  its species, form, IVs, nature, ability, moves, shininess, Poké Ball and personality are kept; it gets what a party hatch gives (the species name, the "hatched at" met data of the
  player's map, friendship 120, full PP, the Pokédex entry, the hatched-eggs count), except that it never changes the Pokémon's OT ID (the world's host treats a Pokémon's
  personality and OT ID as fixed; every Egg a player can have already carries their own). A banner names it ("PC EGG HATCHED! Pichu hatched in your PC.", or the count and names
  when several hatch on one step). Only the player's own steps count: another player's movement never moves anyone else's Eggs, and nothing accumulates while the game is closed (the
  game has no offline progress, so none was added). The progress is the Egg's own cycle counter, so it is saved with the box and survives quitting and loading. Eggs in the PC still
  cannot battle or be released (the storage system refuses an egg), and come out of the PC still Eggs with their progress. **Eggs cannot be traded** (a pre-existing rule in
  `trade_eligibility.py`: "traded eggs require native hatch/origin support"); that is unchanged.
* **A fixed old defect:** the Day Care's `offspringPersonality` was never written, so the sex flip of the Nidoran and Illumise lines (a male line egg that hatches either sex) never happened.
  It is written now (`--selftest-breeding`: Nidoran eggs come out either sex, about half each).

### Egg shiny odds (phase 7)

| Parents / owner | Target | Mechanism | Measured |
|---|---|---|---|
| neither parent shiny, no Charm | 1 in 4096 | one roll | 1 in 4199.6 (200 of 205 ± 14, 839,930 eggs) |
| at least one shiny parent | 1 in 1365.7 | three rolls | 1 in 1353.6 (336 of 333 ± 18) |
| the egg owner has the Charm | 1 in 1365.7 | three rolls | 1 in 1284.4 (354 of 333 ± 18) |
| a shiny parent and the Charm | 1 in 683 | six rolls | 1 in 664.6 (422 of 411 ± 20) |
| two shiny parents | 1 in 1365.7 (no extra for the second one) | three rolls | tested equal to one |

The roll is made once, when the egg is made, for the player who gets the egg (so only the egg owner's Charm counts, and the Charm of a player whose game did not make the egg does nothing); the result
is stored in the egg's personality like every other shiny, so it stays through the Day Care queue, a save, the PC (deposit and withdraw), a reconnect and hatching, and is not rolled again at any of them.
This is separate from the wild and Safari rolls. A player with no Charm gets no Charm bonus (tested).

### Modern (Gen 6+) breeding rules across the implemented roster (phase 8)

The Day Care code is the expansion's, which already follows the Gen 6 rules; `--selftest-breeding` checks them on the real code: 1,271 breedable species of the implemented roster each make a level-1 egg of an enabled
species with a first move and valid IVs (301 species have no egg: the undiscovered group, Ditto, no group; none that should breed fails); a Raichu mother gives a Pichu; **Everstone**
(one holder: always its nature; both: either, about half each); **Destiny Knot** (at least five inherited IVs in every egg; without it three); **Power items** (the holder's stat, always); the
**mother's Hidden Ability 60 %** (60.4 % in 15,031 eggs; 80 % for regular abilities); an **egg move** known by a parent is inherited; the egg is in the **mother's Poké Ball**; Nidoran and Illumise
eggs hatch either sex; Manaphy with a Ditto gives a Phione. The test reports every species whose egg species differs from its own line: only the sex-flipped lines, the baby species that need an incense
item and Manaphy's Phione, which is the rule.

## 3. 2× speed (phase 10)

Removed everywhere a player can reach it: the controls page and key list, `game-settings.cfg` key handling (an old `key.fastforward` line binds nothing and is dropped when the launcher writes the file), the keyboard (Space was the
default), the XInput right trigger and the settings text; `timeScale` is 1.0 in play and nothing sets it. The headless self-tests and the check scripts never relied on it (they do not wait for the frame limiter), so nothing development-only
had to be kept. Multiplayer synchronisation and battle timing were not touched.

## 4. Multiplayer isolation (phase 11)

Each player's party, PC boxes, Day Care queue, bag (Charm, Mega items) and progress live in that player's own canonical save, so the world keeps one head per player. `tests/test_personal_storage_isolation.py` (real server, store and
validator; two players): independent heads and downloads, a save made for one trainer cannot become the other's next revision, disconnect/reconnect and the other player's progress never mix, heads
survive a server restart, wrong credentials reach nothing; the profile folder of (world, player) is unique per world and per account. `tests/test_shell_e2e.py` adds three accounts with real enrollment: three sources, three checkpoints, each
save names its own account. Mega Rings, stones and the Charm are bag items of the owner's own save; there is no shared or world-level copy to leak.

## 5. RNG and save integrity (phase 12)

Existing authority was kept: the Legendary/Mythical roll for shared wild Pokémon is the host's, made once per Pokémon at its first claim and persisted (`tests/test_legend_spawns.py`); the Charm's bonus on a shared Pokémon
is made in the owner's own game from the Pokémon's id and personality (a hash, so releasing and reclaiming or a reconnect cannot reroll, and nobody else's game is affected); personal wild, Safari and egg rolls are made in
the owner's game and stored in the data they produce. Nothing a client says changes another player's odds. The egg queue is validated twice on the way to the server (the engine's import check and the Python container check).

## 6. Tests added or changed

Engine: `--selftest-breeding` (63 checks: sections 1–9, about 3 minutes; `PKMN_BREED_ONLY=9` runs one section), `check-breeding`, `check-keybinds`/`test_gamepad` without the removed speed key, `check-abi` (SaveBlock3's PC-only tail is allowed to be larger),
`--selftest-shiny` (12 checks). App: `tests/test_flash.py` (the queue is accepted when sealed and refused when not), `tests/test_ownership.py` (padding after the queue), `tests/test_game_controls.py`,
`tests/test_personal_storage_isolation.py`.

## 7. Not verified

Real-PC play of any of this; the Day Care woman's dialogue and the party-full path were exercised through the real scripts' data and the engine functions, not by walking to Route 117 on a real PC; breeding with
real multi-hour step counts; shiny rates beyond the sample sizes above; trading an egg (refused by design).

## 8. Re-run of the earlier checks

Wild encounter, Legendary and Safari statistics (`--selftest-legend`), the coin economy (`--selftest-coins`, `economy_check.py`), the species data integrity (`species_data_check.py` against the baseline) and the GBA ROM hash
are part of the final regression recorded in the delivery report.

## 9. A shop crash found by the regression, and its fix

The final regression's `economy_check.py` (Mart dealer scenario) crashed intermittently (3D 2 of 3 runs, Classic 2 of 8). Diagnosed with gdb watchpoints on `gSprites[0]`: the Mart buy menu (`BuyMenuDrawObjectEvents`, `src/shop.c`) draws every object event in the clerk's
7×5 viewport and starts a *facing* animation (index 0–3) on it. An **inanimate** object (Birch's bag in the debug scene's Mauville map; a sign or ball in other maps) has the one-entry `sAnimTable_Inanimate`, so index 2 reads past the table and `BeginAnim` dereferences
garbage. It is vanilla code (the table is at the same place in the GBA game; the original Marts have no inanimate object in view), which is why it only showed when a debug scene put one in front of the dealer, and why it flaked: the object's facing byte differed per run. The fix is PC-only
(`#ifdef PORTABLE`, `#line` marker kept, `check_gba_lines.py` 0 moved lines, GBA ROM still `f214735b…3387`): an inanimate object always gets animation 0. After it the economy check passed 28 of 28 in both builds in both complete repeat runs made after the fix (before it: 2 of 3 failed); the final-regression run at the combined revision repeats it.
