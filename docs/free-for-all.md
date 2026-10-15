# 1v1v1v1 free-for-all (Update 15)

A real four-trainer free-for-all in the **native battle engine** (pokeemerald-expansion, `claude/dev-update15-20-engine`). It
replaces the "not implemented" result of `docs/free-for-all-feasibility.md` (Update 9). It is neither four 1v1 matches, nor a
renamed 2v2, nor a simplified simulator: it is the engine's own battle code with a fourth kind of battle side model.

## Rules (as implemented)
* Four human trainers, each with their own party, items, switches and decisions. Nobody is anybody's partner or teammate.
* Every battler is its own side for the **rules** (screens, hazards, allies, foes), while the **screen** keeps its two columns
  (a battler's position decides where it is drawn). This is the central design choice: `GetBattlerSide()` answers "which rules
  side" (the battler itself in a free-for-all) and `GetBattlerPositionSide()` answers "which column" (used by everything that
  draws or animates).
* Any other living Pokémon is a legal target; a move aimed at "the foes" (Swift, Surf, Intimidate...) reaches all three. A
  single-target move may name any one of the three.
* All four decisions are submitted for the same turn; the order of actions is the engine's own (priority, then Speed, ties by the
  engine's RNG), identical on every core.
* Abilities, items, weather, terrain, status, switching and fainting use the engine's normal code with "ally" meaning nobody.
  Helping Hand, Ally Switch, Pledge combos, Follow Me/Rage Powder and Commander have no one to act on and fail or do nothing.
  Reflect/Light Screen/Aurora Veil use the doubles factor (2/3) because four battlers are on the field.
* Entry hazards and Court Change: a hazard move aimed at a trainer lands on **that trainer's** side only; Court Change swaps the
  user's side with the side of the trainer it was aimed at. (Owner decision, see `docs/owner-decisions.md`.)
* A trainer is **eliminated** when their whole party has fainted; they keep watching (their core still renders the battle). The
  last trainer standing **wins**; two or more falling on the same turn with nobody left is a **draw**.
* **No running** (the menu does not offer it and a stray request does nothing); disconnects are handled by the battle
  recovery protocol, not by a forfeit.
* **No experience** (like all native PvP), no wager, no prize. The host keeps a durable win/draw/loss record
  (`ffa_results`, idempotent by battle ID) that is separate from the two-sided PvP archive.

## Architecture
| Layer | Change |
| --- | --- |
| Engine rules | `include/constants/battle.h` (`BATTLE_TYPE_FFA`, `NUM_BATTLE_LOGIC_SIDES`), `include/battle.h` (`GetBattlerSide`/`GetBattlerPositionSide`/`IsPartnerAlive`), new `src/battle_ffa.c` (foe counts, random foe, elimination, sole survivor, winner), and guarded changes in `battle_util.c`, `battle_move_resolution.c`, `battle_script_commands.c`, `battle_main.c`, `battle_end_turn.c`, `battle_controllers.c`, `battle_controller_player.c`, `battle_message.c`, `battle_ai_util.c`. |
| Native phase | `MP_BATTLE_PHASE_FFA` (5) reuses the four-core full-Multi infrastructure (party exchange, relay, journal). Each core draws itself at the bottom left and the others, counting on from it, at the opponent left, the second player slot and the opponent right. The result is the **winner's slot + 1** (1-4) or **5 = draw**, identical for all four cores; every core checks that its own local result (won/lost/drew) is the one the winner implies. |
| Host | `BattleDesk.invite_ffa` (mode 5, challenger = slot 0, the other three in canonical sorted order, four independent consents, consent fingerprint domain `EM-NATIVE-FFA-CONSENT-1`), protocol op `invite_ffa`, `ControllerValidator` (the end command carries the winner battler), `NativeBinding`/`NativeQuery` accept phase 5 and outcomes 1-5, manifest marker `gMultiplayerBattleFfaAbiVersion` (`battle_ffa_abi_*`), `FfaBook` durable results. |
| UI | In-game Players menu: *Challenges → Free-for-all 1v1v1v1* (offered when four trainers are connected). Launcher *Battle* panel: *Review 1v1v1v1 free-for-all with …*. Every trainer accepts for themselves. |

### GBA byte identity
All free-for-all code is behind `MP_FFA_ENABLED` (`TESTING || defined(PORTABLE)`), with the GBA originals kept in `#else`
branches, so the **release GBA ROM is unchanged** (sha256 `f214735b…3387`).

## Tests
Engine (GBA test ROM, real battle engine): `test/battle/ffa/ffa_basic.c`, `ffa_targets.c`, `ffa_mechanics.c`, `ffa_end.c`
(see `docs/automated-validation-matrix.md` for the counts of the latest run). Host: `tests/test_battle_ffa_desk.py` (four
independent consents, roster/retry conflicts, win/draw/invalid outcomes, publication once, no PvP archive, `FfaBook`),
`tests/test_battle_protocol.py`, `tests/test_battle_controller.py`, `tests/test_battle_manifest.py`,
`tests/test_battle_challenge_network.py`, `tests/test_player_menu.py`.

## Known limits (honest list)
* **Visuals (Update 21, `docs/four-player-battle-ui.md`):** the layout is the doubles layout with the second player's Pokémon facing you,
  trainer names on every healthbox / name tag, "BOB's Gardevoir …" in the battle text, FOE-only target plates and an OUT tag for an
  eliminated trainer. Looked at in a headless simulation only. Classic 2D target selection has no names (only the blinking sprite);
  the party-summary balls of the right-flank positions are skipped.
* **No forfeit.** A trainer who wants out must lose or disconnect (recovery rules then apply).
* **Not verified on a real display or a real network** (only simulated native receipts and the GBA test ROM).
* The 3D diorama and the 2D renderer use the same position model; neither was exercised with a live four-player session here.
