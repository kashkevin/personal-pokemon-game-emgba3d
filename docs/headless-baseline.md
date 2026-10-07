# Ordinary ROM gameplay and save verification

Recorded October 7, 2026. The unmodified baseline completed the gameplay,
ordinary Flash save/reload, and independent-client checks below. This is a
single-player baseline checkpoint, before the multiplayer ROM modifications.

## Test runtime and preserved inputs

The project-owned [headless frontend](../scripts/baseline-headless/README.md)
uses the official [mGBA 0.10.5 core API](https://github.com/mgba-emu/mgba/blob/0.10.5/include/mgba/core/core.h),
pinned to commit `26b7884bc25a5933960f3cdcd98bac1ae14d42e2`. It was compiled
in Ubuntu WSL2 with the Qt, SDL, OpenGL, and GB frontends disabled. CMake
`3.28.3` and its package dependencies were installed; the existing C compiler
and libpng development package were used.

The frontend runs ordinary frames with `runFrame`, supplies joypad buttons
with `setKeys`, and captures the core's 240 × 160 framebuffer. It reads RAM
for evidence, and never writes it. No cheats, savestates, test ROM hooks,
desktop automation, or source changes were used to obtain gameplay progress.
The core uses its built-in BIOS implementation.

Both clients used copies of the ordinary `pokeemerald.gba`, SHA-256:

```text
b89a23a7758519d0768b87ad947a5cb3d8587f1f7bd547f983171b8520bae12a
```

The engine checkout remained tracked-source clean at RHH commit
`bb1093a7c72d3961d9a37d8e02ad2abc2c866682`. The upstream default generation
settings were retained. These checks do not establish the custom Gen 6 rules
or any multiplayer behavior.

The existing desktop client A save was copied into a separate proof folder;
it did not offer Continue at the start of this run. Its original file was
never modified. Its SHA-256 before and after verification was:

```text
b5a41c3758763bbec72769fab4a2533bf2db0b6312d93d25a695f9e4b9e02260
```

## Observed gameplay

| Check | Observed result |
| --- | --- |
| Boot and new game | Ordinary title screen, New Game, trainer creation, and moving truck completed. Separate trainers Aaa and Aaaa were created. |
| Map transitions | Entered/exited Littleroot houses, traversed both floors, entered the lab, walked Route 101 and Route 103, and entered/exited Oldale's Mart and Pokémon Center. |
| Starter | Selected Torchic through the unmodified starter bag and completed the introductory level 2 Zigzagoon battle. Torchic gained 14 EXP. |
| Ordinary wild battle | Defeated ordinary Poochyena, Wingull, and Zigzagoon encounters. Also completed the rival battle during normal story progression. |
| Capture | Caught a female level 2 Wurmple using a Poké Ball. A subsequent correction run caught a female level 3 Wurmple, which is the Pokémon in the final preserved save. |
| Party and bag | Inspected Torchic and Wurmple in the party, inspected bag pockets, and used a Potion normally; the game displayed 13 HP restored. |
| Storage | Deposited the level 2 Wurmple into Box 1 and withdrew it. The party again displayed the same visible species, nickname, gender, and level alongside Torchic. |
| Ordinary save/reload | Used the game menu to save, confirmed the overwrite prompt, closed the core, and booted a fresh process. Continue restored name, map, party, and inventory. |
| Separate saves | A and B had distinct names, trainer IDs, progression, locations, and Flash files. Each survived a normal close and fresh Continue. |

An initial attempt at the final save stopped at the overwrite confirmation;
the following B input cancelled it. The unchanged Flash hash exposed this
before acceptance. Progress was repeated with ordinary input, Yes was
explicitly selected on the overwrite prompt, and the resulting Flash was
verified through a fresh Continue. The cancelled attempt is not counted as
save evidence, and no save or ROM repair was needed.

## Final save evidence

| Field | Client A | Client B |
| --- | --- | --- |
| Trainer | Aaa | Aaaa |
| Trainer ID | `0x1cf9ff0f` | `0xc23617b7` |
| Saved map | Littleroot Town, group 0/map 9 | Littleroot Town, group 0/map 9 |
| Saved coordinates | `(4, 11)` | `(5, 9)` |
| Party | Torchic male level 7, 4/24 HP; Wurmple female level 3, 15/15 HP | Empty; independent early story progress |
| Inventory sampled after fresh Continue | 4 Poké Balls | Separate initial inventory |
| Latest ordinary save counter | 2 | 1 |

Client A's party count and 208-byte sampled party region matched before
closing and after fresh Continue, including Pokémon personality values
`0x68ee39ee` and `0x4462083f`. RAM locations were obtained from this baseline's
ELF/map and its live SaveBlock pointers; they are specific to this build and
must not become hard-coded multiplayer addresses. The latest signed sector
0 in each ordinary Flash file independently confirmed the distinct trainer
name bytes and trainer IDs.

Final 128 KiB Flash SHA-256 values:

```text
Client A: 1cb2b498bc2ee5f2bca31b66e3cec8333c2486786ace0930aee28e0b33b05d29
Client B: 5688844e0799be76a91183ef37429a52449f2104e9efbde6d2ac7a381ca9f910
```

The hashes remained unchanged after fresh Continue, inspecting menus, and
normal shutdown. Only ordinary in-game saving changed Flash contents.

## Local evidence files

The test working directory is `/home/kevin/src/pokemon/baseline-proof` in
Ubuntu WSL. ROM copies and Flash files are in its `client-a` and `client-b`
directories. The original desktop save remains in its existing playtest
directory.

Verified Flash copies are archived at:

```text
C:\Users\kashh\AppData\Local\PokemonPrivate\artifacts\baseline\headless-proof\client-a\baseline.sav
C:\Users\kashh\AppData\Local\PokemonPrivate\artifacts\baseline\headless-proof\client-b\baseline.sav
```

Independent copies with the same hashes were prepared for the upcoming
multiplayer proof at `/home/kevin/src/pokemon/multiplayer-proof/client-a.sav`
and `client-b.sav`.

Framebuffers are preserved in both the WSL proof directory and
`C:\Users\kashh\AppData\Local\PokemonPrivate\artifacts\baseline`. Relevant files:

| Evidence | File |
| --- | --- |
| Boot/title/new-game menu | `01-boot.png`, `02-menu.png`, `03-menu.png` |
| Introductory battle result | `06-starter-battle.png` |
| First ordinary save and Continue | `10-save.png`, `11-continue.png`, `12-reloaded.png` |
| B independent Continue and restored location | `14-b-continue.png`, `15-b-reloaded.png` |
| Potion used normally | `16-potion.png` |
| First capture | `17-capture.png` |
| Storage operation and restored party | `18-deposit-select.png`, `19-deposited.png`, `20-withdrawn.png`, `21-party-after-storage.png` |
| Final capture | `24-recapture.png` |
| Final party before saving | `26-a-party-before-save.png` |
| Overwrite prompt and completed save returning to the field | `27-overwrite-confirm.png`, `28-save-complete.png` |
| Fresh Continue and restored map | `29-final-continue.png`, `30-final-overworld.png` |
| Restored captured party and inventory | `31-final-party.png`, `33-final-pokeballs.png` |

These checks supplement the reproducible normal build and upstream test
results in [baseline-build.md](baseline-build.md). They establish the required
baseline behavior; they do not establish network movement, trading, PvP,
server persistence, or Windows package readiness.
