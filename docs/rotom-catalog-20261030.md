# The Rotom Catalog (2026-10-30)

The owner's request of 2026-10-30: a reusable Key Item, the Rotom Catalog, sold at the Game Corner's RARE GOODS for
15,000 coins, that changes any party Rotom between its six forms (Normal, Heat, Wash, Frost, Fan, Mow) outside battle,
showing the form's typing before the change, through the game's own form change and signature move rules; the form
kept through saves, restarts, trades, the PC and multiplayer sessions. Engine `ba6638dc` (PC only: the GBA ROM's
sha256 is unchanged), app (this change).

**L** below means the Linux test builds (the 3D one with Mesa's software OpenGL, and the Classic 2D one); nothing here
was run on Windows or on a player's PC unless it says so.

## What was there already

* The item: the expansion's `ITEM_ROTOM_CATALOG`, a Key Item (one each, never used up, no use in battle) used on a party
  Pokemon from the Bag, its form table (`FORM_CHANGE_ITEM_USE_MULTICHOICE`: Rotom and its five appliance forms, each a
  species of its own with its own types, stats and pictures, all Levitate) and its signature moves (Overheat, Hydro Pump,
  Blizzard, Air Slash, Leaf Storm; Thunder Shock back in the normal form, the Gen 9 rule).
* The shop: the Game Corner's prize clerk, RARE GOODS > EVOLUTION, lists it at 15,000 coins (the owner's RARE GOODS of
  2026-10-24, `tools/mp/gen_rare_goods.py`); a Key Item already owned shows SOLD OUT and is refused ("That item is sold
  out."), in the 3D shop screen too.
* Rotom itself is in the randomized wild pool (rare).

## What changed

In the game (`src/party_menu.c`, PC only):

* The catalog opens for a Rotom only. Anything else - an Egg too - says "It won't have any effect." before any list.
* The list names the six forms - Normal Rotom, Heat Rotom, Wash Rotom, Frost Rotom, Fan Rotom, Mow Rotom - under
  "Change to which form?" (it listed appliances before). With several Rotom in the party the player picks which one first,
  as for any item.
* The form chosen is named with its type before anything changes: "Turn Rotom into Heat Rotom? Its type will be
  Electric/Fire." with YES / NO. YES changes it through the catalog's own code (the form table, the animation and cry,
  "Rotom transformed!", the last form's signature move taken out and the new one taught; with four moves the usual
  "make room for Overheat?" question). NO goes back to the list. The form it has already: "Rotom is already Heat Rotom!"
  and back to the list.
* The 3D party screen shows the question's YES / NO and the list's prompt again after it.

In the launcher and host (`trade_forms.py`): world trades take Rotom's five appliance forms. The trade is the exact
exchange of the two Pokemon (`docs/trade-eligibility.md`), so a form arrives as it was sent; until now the eligibility
check refused every species number past 721, and the forms are numbered 1064-1068. They are listed one by one
(`REVIEWED_FORMS`: none can't be traded, none evolves), every other form is still refused, and the trade and record menus
name them ("Heat Rotom", not "No.1064"). The trade effect preparation (friendship history, the native record; prepared
only, never committed) keeps the standard range.

## Tests

| What | Where | Result |
| --- | --- | --- |
| `--selftest-rotom-catalog` (`make check-rotom-catalog`): the item; RARE GOODS (listed, 15,000 coins, 14,999 not enough, bought: 5,000 left, then SOLD OUT); each form's types, Levitate, base stats and pictures (front, back, icon: an appliance form's are its own); every form to every form (36: the question's form, types, Ability, stats recalculated, everything else kept); 28 changes in a row on one Rotom; a Pikachu and a Rotom Egg refused; a Wash Rotom put in the PC and taken out; its bytes copied as a save or trade carries them | L (3D and Classic 2D builds) | 73 of 73 |
| `tools/battle_env/rotom_check.py` in real game processes, keys pressed as a player does: bought at RARE GOODS (20,000 coins, 5,000 left, one in the Bag; a second refused as sold out), saved and loaded | L, 3D and 2D | passed |
| ... one Rotom through Heat, Wash, Frost, Fan, Mow and back to Normal through the Bag, each with its question and its signature move in the last one's place; saved and loaded: the form and moves as left; the second Rotom untouched; the catalog still in the Bag | L, 3D and 2D | passed |
| ... the second Rotom picked from three party Pokemon; the form it has, NO, CANCEL and a Pikachu: nothing changes | L, 3D and 2D | passed |
| ... a Rotom knowing four moves: it becomes Heat Rotom and asks about Overheat; declined, it keeps its four | L, 3D and 2D | passed |
| ... each of the six forms leading a wild battle against its own form: the 3D battle's picture (its back, the foe's front: each form's own sprite), won with the first move (the signature move), still that form afterwards | L, 3D | passed |
| Two real games through the real host and launchers (`native_launcher_newcomers_proof.py --scenario trade-forms`): a Heat Rotom traded for a Fan Rotom; the host's saves hold the swapped forms under the same serials; closing saves, a fresh Continue of both and the store's integrity check | L, Classic 2D | passed |
| The app's trade tests (`test_trade_eligibility.py`: the five forms accepted with their held item, 1063 and 1069 refused, a pair of forms; `test_trade_forms.py`) | L | passed |
| The Windows jobs (`windows-package` run 249, mode full, engine `ee84a646`): `--selftest-rotom-catalog` in the Windows build | Windows CI (GitHub-hosted runner) | 73 of 73 |
| ... `rotom_check.py` in Windows game processes of the Classic 2D test build, its default steps: bought and loaded, every form and back and loaded, the second Rotom, the paths that change nothing, four moves, the six forms' wild battles | Windows CI (GitHub-hosted runner) | passed (no problems) |
| The Windows build's self-test under Wine | Wine on Linux (not Windows) | 73 of 73 |

## Not verified

* On the owner's PC or any player's PC: nothing here. The Windows jobs run on a GitHub-hosted runner, not a player's PC;
  they ran the Classic 2D test build (the 3D game's battle pictures were taken on Linux only).
* The first Windows run (248) stopped at its build, on step 16's code, not the catalog's: a variable named `far`,
  which Windows' headers define away. Fixed in engine `ee84a646`; run 249 is the one above.
* Moving a Rotom through the PC's own storage screens by hand: the storage's own deposit and withdrawal (the code those
  screens call) are checked in the self-test; the screens themselves were not driven.
* A battle between two players with a Rotom form: the battle code is the same one the wild battles above ran, and a
  form travels in a player's party data as any Pokemon; not played between two games.
* The move question's other answer (forgetting a move for the signature move): the game's ordinary move-learning screen,
  not changed here.
