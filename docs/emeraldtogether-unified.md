# The unified EmeraldTogether game (`emeraldtogether-unified-20261013-1`)

The owner's request of 2026-10-13: integrate the finished graphics handoff
(`graphics-handoff-20261012`) into the newest combined EmeraldTogether game, with the battle
session's fix for battles on switched layouts (`5699d58b3`, V46), keeping everything the
combined game already had, and prepare one Windows game and launcher. Done in the overworld
(graphics) session on a new branch, so that no other session's branch is changed: the main
integration session's `claude/emeraldtogether-integration` stays at `8706f8f6c` and can take
this branch as a fast-forward.

## Branches

Engine `claude/emeraldtogether-unified` (tag `emeraldtogether-unified-20261013-1`):

| Commit | What |
| --- | --- |
| `8706f8f6c` | The combined game as it was: `claude/emeraldtogether-integration`, `emeraldtogether-integration-20261012-3` ("Native 3D preview 9"): the 3D overworld of `native-wip-20261012-2`, the 3D battles and the battle environments' round 4, the animated battle sprites, the native PC UI with the UI session's character screens, the character selection, the native crash fixes N37-N40, the link battles' freeze fix. Tag `emeraldtogether-pre-unified-20261013` (the rollback point). |
| `197e0e48d` | Merge of `claude/native-graphics` `53bb34a63` (`graphics-handoff-20261012`): V29, V32, V43, V47 and the renderer's README. No conflict. |
| `8c8c11ab2` | The battle session's `5699d58b3` cherry-picked (`-x`, its message kept, a note added): the battle frame takes the layout the game draws (V46, its E13). It was not in `8706f8f6c`: not an ancestor, no patch-equivalent commit (`git cherry`), `battle_capture.c` still read `gMapHeader.mapLayoutId`. |

App `claude/emeraldtogether-unified`: the integration's app branch (`8934371`) with the
handoff's docs merged (`3fd7f83`) and this report.

Nothing of the UI, sprites, characters or battle environments changed: the merge brought only
the graphics line's files (`scene_snapshot.c`, `terrain_mesh.c` and its test, the building
generator and its tests, the renderer's README) and the cherry-pick two battle files
(`battle_capture.c`, `gl_battle.c`). Battle FX: the combined game had none (as the integration's
notes say), so there was nothing of it to keep. The Battle FX integration's first checkpoint
appeared a minute after this one and is not in this game (see the last section).

The engine tree equals the one the graphics handoff's trial tested (`8706f8f6c` + `1d54639cf`
+ `5699d58b3`) but for the renderer's README.

## Conflicts and how they were resolved

- Engine: none (`git merge`; `git merge-tree` had predicted it).
- App docs: `CHECKPOINTS.md` - both sides added rows at the end of the table: every row kept
  (the integration's 2026-10-12 rows, then the handoff's 2026-10-13 row). `KNOWN_ISSUES.md`
  V37 - the integration's row was the merge base's text, the handoff's carries V47's numbers:
  the handoff's taken. Checked after the merge: every issue and checkpoint row of both sides is
  present - `KNOWN_ISSUES.md`: 107 issue IDs of the integration and 86 of the handoff (81 on
  both sides); where the two sides' rows differ, only one side had changed the row since their
  common base, and its row was kept (V29, V32 and V37 from the handoff; N33 and V9-V11 from the
  integration); `CHECKPOINTS.md`: the integration's 30 rows and the handoff's 19, all kept;
  `FEATURE_STATUS.md` and `TEST_PLAN.md` merged without a conflict, every line either side
  added kept.

## Verification (cloud computer: Linux with software OpenGL, the Windows programs under Wine)

| Check | Result |
| --- | --- |
| GBA ROM | `pokeemerald.gba` built from `8c8c11ab2`: sha256 `f214735b...3387`, byte for byte the launcher's game file. |
| Builds | Linux 3D (native UI on), Windows 3D, the TEST build (the battle survey driver) and Linux 2D compile; only the engine's pre-existing warnings (none in a merged file). The Windows exe imports only `SDL2.dll` and Windows' own DLLs, large-address-aware. |
| `check-native`, `check-abi` | Pass: 1067 + 4203 + 244 + 176 checks; ABI parity 172 types. |
| Python tests (app) | 1408 passed, 1 skipped (1399 as on the graphics line, plus the integration's 9 battle-look tests). |
| `check-diorama` | Pass: every renderer test (terrain mesh with the undersides, battle stage, props 7984 checks, camera 403, far field 54,618, ...) and the compositor goldens (18,318 metatiles). |
| Game selftests (3D build; the four crash tests on the 2D build too) | `check-decompress` 7469 assets, `check-party-order` 1119, `check-battle-names` 1724, `check-cry-stop` 5, `check-shake-anim` 11 checks, 0 failed; `check-game-sections` passes. |
| Switched layouts (V46) | The TEST build (`PKMN_NATIVE_UI=0`: the survey drives the GBA menus), each battle's log naming its layout: Sky Pillar 1F, 3F, 5F and the top on their clean layouts (433, 435, 437, 438; the rubble round Rayquaza), Route 131 (319), Shoal Cave's entrance at 12:00 (high tide, 168) and 05:00 (low tide, 164), Route 111 without its Mirage Tower (392, one entry in five; the tower shows on a random half of entries) and with it (27): all drawn in 3D, foot error 0 px. Not tried: Route 130 with Mirage Island, Shoal Cave's inner room at high tide (warped in directly it keeps its low-tide layout 165: the tide is set by the entrance room), Sootopolis in the legends' battle - the same code path. |
| Other battles | Mt. Chimney, Jagged Pass (no cracks: void 0), Mauville, Lilycove, Sootopolis, Route 130, Shoal Cave's inner room at 12:00 and 05:00 (165 both times); Lilycove and Sootopolis at 22:00: all 3D. With the switched layouts' battles and Route 111's other entries (27): 22 battles, every one 3D. |
| The field | Sky Pillar's top with its rubble standing, Mt. Chimney with no cracks, Lilycove's windows lit at 22:00, both cameras; Rustboro's Gym sign keeping its last line with the native UI on (its box) and off (the game's box). |
| Multiplayer, Linux 3D build (native UI on) | The launcher 1v1 (`native_launcher_battle_3d_proof.py`, the animated sprite pack loaded): world creation, enrollment, both games started by the real launcher, a 1v1 from the Players screen played to the end (362 battle blocks through the host), the same result on both, saves (revision 2), normal close, fresh Continue, store check - passed (run 2; see below). The trade proof (trade, back-out, restart; 50.8 s from the first confirmation) and the live-save proof (enrol 1.66/1.72 s, saves 1.54-1.68 s, live recovery 41.3 s) - passed. |
| Multiplayer, Windows exe under Wine (native UI on) | The trade proof with two clients of the packaged exe: passed (51.3 s from the first confirmation). |
| The launcher package | "Native 3D preview 10" under Wine: starts, and "Check installed game files" says the installed game and runtime match its pins. Its launcher sources are file for file preview 9's (133 files, the same hashes), the same Python 3.14.0 and pinned dependencies; only the runtime pin and the version differ. |
| GPU frame rates | Not measured: no graphics card here. The frame-rate targets stay unverified (V39). |

The launcher proof's first run (unified run 1) stopped by hand: the host's lead fainted and the
harness, which picks the next Pokémon with Down as the GBA party menu does, cycled between the
fainted Pokémon and Back on the native party screen, whose grid puts the second Pokémon to the
right (`ui_party.c` `GridMove`). Run 2 used a copy of the harness that differs only in that key
(Right): passed. The committed harness needs that change before it can cover a fainted lead with
the native UI on; the game itself was not at fault (Right then A chose the next Pokémon).

## Checkpoints that appeared after this one

Read and merge-checked (`git merge-tree` on `8c8c11ab2`; their bundles fetched into private
`refs/coord/*` refs without tags, their folders only read). None of them is in this game.

- `battlefx-int-wip-20261012-1` (written a minute after this checkpoint's folder):
  `claude/battle-fx-integration` `2907a098b`, Battle FX on the battle environments' round 4
  (`aa63a98a3`), waiting for the owner's go (its `INTEGRATION_REPORT.md`). On `8c8c11ab2` the same
  four files conflict as on preview 9 (`Makefile_pc`, `gl_battle.c`, `battle_env_test.c`,
  `gba_easy_draw.c`) with identical conflicting hunks (compared with the markers' labels
  normalised): the graphics handoff and `5699d58b3` add none, so its COORDINATION.txt section 10
  holds on this tip. Its trial `claude/battle-fx-sprites-trial` `f6380dbb8` (preview 9 with
  Battle FX merged, the four files resolved) merges into `8c8c11ab2` without a conflict.
- `ui-native-wip-20261013-2` and `-3`: `claude/native-ui` `6c789cc3`, then `0b7523cdb`. `0b7523cdb`
  merges into `8c8c11ab2` without a conflict.
- U13, reported in `ui-native-wip-20261013-2` for the battle session and the native-PC owners (not
  the UI's code; `KNOWN_ISSUES.md`): a native crash in the battle text's automatic line breaking
  (`line_break.c` `BuildNewString`; Psychic Edward's defeat line on Route 110). This game's
  `line_break.c` is preview 9's (blob `1031b9b9a`), so it has the bug by the code; not reproduced
  here. The UI session's patch is not applied: as written it changes the GBA ROM (it needs
  `PORTABLE` and `#line`), and it was not part of this request - for the next integration round.
  U14 (Taunt's refusal message without the move's name) is upstream expansion code.
