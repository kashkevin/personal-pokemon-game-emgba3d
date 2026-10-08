# Native four-trainer battles with independent full parties

On October 8, 2026, `native-multi-run-2` completed a four-human-format 2v2 development proof on engine `9009bcb45bd252fb93f934fcf41540dc2b0f3390`, using four actual mGBA cores and an explicit test coordinator. Its occupied party counts were **2, 1, 1 and 1**. This proves the exercised four-client battle and save/return path; actual battles with six occupied Pokémon per trainer remain required.

The owner's requested format remains up to six separately owned Pokémon per trainer, twelve per side. Fixed participant slots 0 and 2 form one side; slots 1 and 3 form the other. Each trainer controls their own battler and party. The proof coordinator authenticates and consents for its four development accounts through the server-owned BattleDesk. A player challenge menu, public battle endpoint and durable result settlement are not implemented by this proof.

## Native implementation and tests

Battle ABI 3 adds an exact four-participant full-Multi phase while retaining singles. Every participant supplies their trainer descriptor and three 200-byte party-pair blocks, covering all six original slots. The native startup maps the other three parties independently into partner and opponent parties, bypasses the legacy three-Pokémon selection screen, and installs the shared battle RNG after startup. Save layout and save mailbox ABI are unchanged.

The source-only delta from qualified singles `7efa2448ea19d8aca9946d6572931e97428f0c94` is [phase5-native-full-multi.patch](../engine-patches/phase5-native-full-multi.patch), SHA-256 `7d1a028889c422092762de4b2ddb2404825801a69e449966ec02c81f78c3f6c6`.

Only fixed master slot 0 supplies engine commands. Each battler's owner supplies its replies; all four renderers must finish a command before that battler advances. The transport acknowledges delivery to all three peers, checks typed startup and controller messages, and retains the startup barrier until every original party has been verified against its canonical checkpoint. The development router drains an admitted batch to every recipient before admitting a later batch, preventing a later command from overtaking a pending completion at a slower peer.

Native full Multi uses separate six-slot switch orders, selects each trainer's first usable Pokémon even when earlier slots are fainted or Eggs, and lets a side continue while either trainer has usable Pokémon. The phazing path considers all six slots of the target trainer's own party. Result handling normalizes all four reports to the fixed sides and restores each participant's exact original party and personal RNG before release. Native battles suppress unused recorded-battle snapshots and incidental recording/statistic writes that otherwise charge a teammate's actions to the master.

The frozen source passes **58 focused multiplayer engine tests**. These include six occupied slots across all four local views, controller ownership, first usable Pokémon in slot six, independent switch-order permutations, owner-only choices, four-renderer completion barriers, targets and party slots beyond the original singles/half-party limits, continuation after one trainer's party is exhausted, exact party/RNG return, and native recording/statistic guards. These fixtures supplement actual-core testing. They do not establish every move, phazing scenario or full-six battle as played successfully. The unfiltered engine regression was still running when this record was prepared; no result is claimed here.

## Actual four-core proof

- Four distinct trainers loaded ordinary Continue and enrolled at canonical checkpoint revision 1. Trainer descriptors and all original six-slot party bytes, including empty tails, matched their canonical owned saves. Every participant passed consent, native binding, preparation and startup barriers.
- The proof routed **1,139 validated complete blocks** and recorded **21 snapshots**. Ordinary joypad input selected native actions and moves. Battler 2 fainted while its teammate continued; battler 0 later fainted and selected its second Pokémon through the native party menu. Further turns completed with fixed-side outcome **2**, a win for slots 1 and 3. No move choice, switch reply, damage or outcome was injected.
- All four cores returned to their own original maps and coordinates. Before release, each participant's exact original 600 party bytes, party count, both personal RNG states and native save counter matched its held values. Flash remained unchanged during the battle; elapsed playtime advanced normally.
- All four matching result receipts and release acknowledgments closed the server-owned BattleDesk battle. Every client then committed an ordinary native checkpoint at revision 2, retaining its owned inventory. The four cores closed, canonical cold-start reconciliation ran, and four fresh cores loaded ordinary Continue with their canonical parties, maps and coordinates and no active battle hold.
- SQLite integrity passed, all four original source-save hashes remained unchanged, and all eight initial/fresh processes closed. The complete private evidence records **five passing checks**.

The run uses the production Lua/companion mailbox transport and authenticated world sessions. Core memory and Flash diagnostics are read-only; external writes stay within allocated production mailboxes. No savestates, arbitrary RAM writes, injected parties or modified source saves are used. This faster-than-real-time headless proof is functional evidence, not Windows, latency or performance acceptance.

## Singles compatibility on the same ROM

`native-singles-abi3-run-1` passed five actual-core checks using the same frozen ABI 3 ROM in its two-participant singles phase. Two trainers with occupied parties of two and one Pokémon completed the ordinary-input battle after **362 routed blocks**, including fainting and a native party-menu switch, with fixed-side outcome 2. Both original parties and personal RNG states were restored, battle Flash remained unchanged, ordinary revision-2 checkpoints retained ownership, and two fresh cores passed canonical Continue. All four initial/fresh processes closed and the original source hashes remained unchanged.

The existing singles proof now requires explicit `--native-abi 3` to run this compatibility case; its default remains ABI 2. The private compatibility evidence SHA-256 is `368ab741523337a3d36d9ebdd98171a8797f9ae5286d348e5a49217a600bce33`, and its frozen controller SHA-256 is `92308d42a30240e6c9731a59a6d38beff2d908589800840b11814e7497c9599d`. All **60 run files** were copied to the physical Windows private `artifacts/battles/native-singles-abi3-run-1` archive and individually hash-verified. This is an exercised singles regression, not broad move or full-six acceptance.

## Frozen evidence

| Item | SHA-256 |
| --- | --- |
| ROM | `7db285540c388848f578c97f2b0b531b8c04e9f5ecf78cfc19dba1dc11e4ab7f` |
| ELF | `3c1267e62d1fa6c7394165fa754c418033bab091fbebf6cd0694c2f88c990968` |
| Manifest | `cb26b016604d064bd96f6a88749b0ef1f7c33a2ea45d68b19600bb6077ee8cac` |
| Complete private evidence | `54b0ff3ba7c84b27b55ff37d30d368a5b3f7d084c3a05efe43b880a13f8d8653` |
| Frozen proof controller | `72e06e3d6a3c3fa1f8d9d4bff36aed711a0711ca4ab4f097071ce72f69580ac2` |
| Production bridge | `33958119b9ed507fdbc6c131b31e93dae1e3122cea78b5ad3f8410cffae5be85` |
| Actual-core harness | `1de09f7821591065b5074a1f86ffb89ce369006c4adc5cd487668bc915f98c81` |
| Focused engine test log | `3feb7ce20e49ee83dd505779c61ea44af32f1a9f7702912f9a42402720311d73` |

The WSL build is frozen in `/home/kevin/src/pokemon/multiplayer-proof/native-multi-build-9009bcb`. The physical Windows private artifact directory contains `artifacts/battles/native-multi-run-2` with **160 individually hash-verified files**, five frozen build/source-patch files, and the separately hash-verified focused test log. The earlier `native-multi-run-1` remains archived with **35 individually hash-verified files**. Its older harness lacked the requested read-only Flash-dump command, so the proof stopped before battle entry; its cores closed and original saves remained unchanged. The accepted run uses the qualified harness without changing the frozen engine.

[Sanitized evidence metadata](../scripts/multiplayer/native-multi-evidence.json) contains verification and scope only. ROMs, player identities/credentials, original saves, databases and complete private packet evidence remain outside Git.

## Remaining acceptance

The opening VS display still uses the legacy three-Pokémon summary per trainer even though startup transports all six. Its presentation must be adapted before claiming an accurate twelve-per-side preview. Required gameplay coverage includes six occupied Pokémon per trainer, switches and knockouts into later slots, broader moves/status/items, and dedicated phazing scenarios.

The server-owned BattleDesk reservations protect all four characters against concurrent checkpoint/trade mutations during this live session. They do not supply durable interruption settlement. Host restart, disconnect policy and recovery, result/statistic settlement, the player interaction menu, Windows input/runtime integration and separate-PC Wi-Fi/Internet testing remain outstanding. The unresolved battle journal is a separate admission foundation and was not a complete durable coordinator in this proof.

The qualified Local Reset commits have also been integrated into a separate source worktree, `engine-multi-reset`, at `016cd8e64a8b01fc021c9483d0024710f4a5e7f0`. Its development encounter remains disabled by default. This source integration has no combined build or gameplay acceptance yet; the [Local Reset record](local-soft-reset-design.md) describes the separately qualified reset build.
