# Native singles with independent exploration clients

On October 8, 2026, `native-singles-run-4` passed the first complete two-core native 1v1 proof on engine `7efa2448ea19d8aca9946d6572931e97428f0c94`. This is development acceptance for that exercised battle and its save/return path. It does not qualify all moves, six-against-six gameplay, four-human Multi, the player interface or Internet play.

The proof uses two official mGBA cores, ordinary Continue and joypad inputs, the production Lua/companion mailbox transport, authenticated world accounts, real canonical checkpoints, the session-local BattleDesk and the stateful typed controller validator. The explicit development coordinator supplies consent for its two test accounts and routes complete validated blocks. It has no public battle endpoint, player challenge menu or durable battle settlement. Diagnostic memory and Flash reads are read-only; external writes remain confined to allocated production mailboxes. No savestate or arbitrary party/save injection is used.

## What passed

- Both independent trainers loaded normally and enrolled at canonical revision 1. One party contained Torchic and Wurmple; the other contained Treecko. Native trainer descriptors and every byte of each original six-slot party matched the acknowledged checkpoints before controller routing.
- Both exact challenges passed consent, binding, preparation and startup barriers. The coordinator checked all trainer/header/party/RNG blocks and routed **362 complete blocks**, with master commands, owner replies and both renderers' completion barriers validated independently in Python and C.
- Ordinary A presses selected actions and moves. Torchic fainted; an ordinary Down/A sequence selected Wurmple through the native party menu. Further turns completed and both cores reported fixed-side outcome 2: the second trainer won. No move, switch choice, damage or result was injected.
- Both cores returned through native field cleanup to their individual original maps/coordinates. Before release, the exact original 600 party bytes, party counts, primary/secondary personal RNG and native save counters matched their held values. The committed Flash images were unchanged during the battle. Elapsed battle playtime advanced normally.
- Both correlated result receipts authorized explicit release; BattleDesk closed only after both acknowledgments. Each client then created a normal native checkpoint at revision 2, preserving its complete owned Pokémon inventory. Both cores closed, canonical closed-start reconciliation ran, and two new cores loaded normal Continue with the original parties and no active battle hold. SQLite integrity and unchanged original source-save hashes were verified. All four original/fresh core processes closed.

These checks exercise partial occupied parties and all six transported/restored slots, including empty tails. They do not substitute for a six-versus-six battle or the requested up-to-six-per-trainer 2v2 proof. The functional headless frame pump is faster than ordinary game speed; this run is not a latency, save-duration or Windows performance measurement.

## Frozen evidence

| Item | SHA-256 |
| --- | --- |
| ROM | `195299be89b79bd2d3dbe178860c16895054c520fceb650a0a69ea28c071cdf4` |
| ELF | `31af065713516874f6e88054b690ac6f1e9096d552cd8c9743076b899e55f9e1` |
| Manifest | `2845125ee61b230b06a45e78b0e89b7b5f6532055162bf68fc0cb7f4f0a9286c` |
| Complete private evidence | `9fb4ba9810462b890cc61c9e249554de65612703ae7fc13b25b99867759a5779` |
| Frozen proof controller | `48b6cbae4ca5871f906c3148b7307ae3b78aababb5977985b2db0f0044752bb7` |
| Production bridge | `71e766d56da5ea49682a99b586248a9b95b190e3949c6e68868a264dbc69e208` |
| Actual-core harness | `1de09f7821591065b5074a1f86ffb89ce369006c4adc5cd487668bc915f98c81` |

All **60 private run files** were archived under the physical Windows private artifact directory, `artifacts/battles/native-singles-run-4`, and individually hash-compared with their WSL originals. The source saves, credentials, databases and ROM remain outside Git. [Sanitized evidence](../scripts/multiplayer/native-singles-evidence.json) contains scope and verification metadata only.

Earlier runs remain preserved. Run 1 exposed the native first-turn `B_ACTION_NONE` sentinel and an ignored stale item argument. Run 2 exposed an unused effect-battler loop sentinel in an empty-string controller. The narrow fixes canonicalize unused fields while retaining strict checks for fields that handlers consume. Run 3 completed the battle and both checkpoints but the proof attempted cold startup before the companion reauthenticated; the startup gate correctly refused. Run 4 fixes that test wait without changing the engine. All failed runs closed their cores and retained the original source saves.

## Four-core independence repeat

`native-singles-observers-3` passed six checks using the same frozen engine and battle rosters, with two additional independent trainers. While both battling cores remained RUNNING, C and D walked to different coordinates, D opened its ordinary menu, and C committed checkpoint revision 2. All four authenticated leases/incarnations remained unchanged. Neither observer acquired a battle hold, and both observers' canonical owned inventories remained unchanged.

The same ordinary-input battle completed after 362 routed blocks. Both participants restored their original party and personal RNG, acknowledged release, and saved normally. D closed its menu with B. Final canonical revisions were A2/B2/C3/D2; four fresh cores then loaded normal Continue with each canonical party, map and coordinates. All eight initial/fresh processes closed, database integrity passed, and all four immutable source saves retained their original hashes.

The complete private evidence hash is `54e903492efc26900eb7574dc7c2df6b5531e287a7e73f3912415ecce78228a2`; the exact controller hash is `d0b80e382abfd862249e80c0f4d83b99196fb1aa4d7f64b5d2b8b7bf4c0c8c31`. All 128 run files were copied to `artifacts/battles/native-singles-observers-3` under the physical Windows private directory and individually hash-verified. [Sanitized four-core metadata](../scripts/multiplayer/native-singles-observers-evidence.json) records this additional proof separately.

The two prior observer attempts are also preserved. One missed a short ordinary Down pulse in the proof's batched frame pump and timed out at the native switch menu. The other completed the battle but missed D's B pulse; the checkpoint guard correctly refused to save inside that menu. The accepted driver holds discrete menu keys across a possible in-flight frame batch. No engine change, injected choice or weakened checkpoint gate was needed.

The frozen source passes 51 focused engine tests and the unfiltered suite passes 5,465 tests with zero unexpected failures, retaining 18 known failures, 421 TODOs and nine expected failures. Full pins are in the [prototype source record](native-singles-prototype.md). Remaining acceptance includes broader moves/status/items/party sizes, full-six four-human Multi and team consent, durable battle settlement/interruption recovery, native Windows gameplay, and separate-PC network conditions. The unresolved-only local battle journal is a separate admission guard and was not used as a complete coordinator in these proofs.
