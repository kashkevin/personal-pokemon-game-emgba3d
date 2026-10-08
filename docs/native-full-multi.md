# Native four-trainer battles with independent full parties

On October 8, 2026, `native-multi-full-six-run-2` completed a 2v2 development battle with **six occupied Pokémon per trainer, twelve per side**, using four actual mGBA cores on combined engine `afd92ce3a12204873e2f06a77a7bf1717d04f53b`. Three trainers switched through all five reserve slots; the fourth retained its starter. Exact personal restoration, four independent checkpoints and four fresh Continues passed. This accepts the exercised full-party battle path; broader effects, durable interruption settlement, player menus and Windows/network delivery remain separate gates.

The owner's requested format remains up to six separately owned Pokémon per trainer, twelve per side. Fixed participant slots 0 and 2 form one side; slots 1 and 3 form the other. Each trainer controls their own battler and party. The proof coordinator authenticates and consents for its four development accounts through the server-owned BattleDesk. A player challenge menu, public battle endpoint and durable result settlement are not implemented by this proof.

## Actual full-six proof on the combined source

All four trainers loaded ordinary Continue with party counts **6, 6, 6 and 6**, enrolled at canonical revision 1, and passed separate consent, binding, preparation and startup barriers. The completed run routed **5,085 validated blocks**, recorded **81 snapshots** and retained **240 party-menu joypad records**. Ordinary input selected the native moves and switches. Trainers 0, 1 and 2 each selected canonical zero-based party slots 1 through 5, including their sixth Pokémon; trainer 3 kept its initial Pokémon. The fixed-side outcome was **2**, a win for trainers 1 and 3.

Before release, every trainer's original 600 party bytes, party count, both personal RNG states and save counter matched the held state. Battle Flash remained unchanged. All four returned to their own original maps and coordinates, passed matching result/release barriers, and committed ordinary native checkpoints at revision 2 with unchanged owned inventories. Four fresh cores then loaded canonical Continue. SQLite integrity passed, original source saves remained unchanged and all eight initial/fresh cores closed. The run contains **five passing checks**.

The driver at project commit `0726888040a1f001c73a2cb3dfa382b6260c3668` observes native task/cursor readiness and sends ordinary 12-frame joypad pulses. These are read-only diagnostics followed by input, not injected menu replies, party edits, damage or outcomes. The earlier `native-multi-full-six-run-1` stalled after 2,093 routed blocks when the harness sent menu input in bursts. It was canceled with its cores closed and source saves unchanged. The successful rerun changed the driver; no engine fix was made for that test failure. Both runs remain archived.

The exact combined source passed **70 focused multiplayer tests** and the complete engine suite: **5,484 passing tests, zero unexpected failures**, with 18 known failures, 421 TODOs and nine expected failures across **5,932 cases**; exit code 0. The full log is `artifacts/local-reset/native-select-reset-full-afd92ce.log`, SHA-256 `cad47067ee3ce5e5c08d036ad7822198c4f1747cefa3e3de725f47b462c7477f`. The focused log SHA-256 is `bd8a32b3278044e0932721589ff9ccba1368b528d4908ed96003e2cf4aab94a8`.

This ROM uses `LOCAL_RESET_DEVELOPMENT=1` and is the same frozen ROM as the separate **21-check guarded Select/reset proof** in the [Local Reset record](local-soft-reset-design.md#combined-source-and-guarded-select-action). The normal build also compiles with the encounter disabled. Passing both runs does not establish the simultaneous trade/battle/reset matrix. The combined [source delta](../engine-patches/phase6-native-multi-local-reset.patch) from `9009bcb` has SHA-256 `bc29f8408dc5a83508edae716359624f0c9935b8652edd8263f44d1c954d4432`, recorded at project commit `2530aca18c6ed2a3ff4b2635f2725b12bcc5c22b`.

| Current full-six artifact | SHA-256 |
| --- | --- |
| Development ROM | `3c4dc8e4d76540935139b17cbe24eb5a8074db8a1cf0e94abc319970426591dc` |
| ELF | `2935fb293b668c3f601f2c1f1136133e034efdb0e4794789f1c5fc91b82bb21a` |
| Frozen build manifest | `3d28900ef0735e93711c7bacb6afa761b8696b96067b912a6b8981b9489d9bdb` |
| Complete private evidence | `69b0ddae513c5baec44361ed3b13073c2ddfe5dbd7ebf633cec3c29a2ef7db5f` |
| Frozen proof controller | `bd47293de994456a6c54f153fcb8c7cf44519bc733ae79abe9b5110e7fab3dea` |
| Canceled-run evidence | `4865308499ac6a79869a4a0511ae378917ca5e3f8a1fa7c59483010e355e47a1` |
| Canceled-run controller | `f8c4d20f4cb30d64c429333d45f108684c909fc0469b91bb4a2dd039c75d061c` |

The physical private `artifacts/battles/native-multi-full-six-run-2` archive contains **400 individually hash-verified files**; the preserved first run contains **292**. Build artifacts and the verified regression log are retained under `artifacts/local-reset`. This is functional headless-core acceptance, not Windows, separate-PC networking or performance qualification.

## Native implementation and tests

Battle ABI 3 adds an exact four-participant full-Multi phase while retaining singles. Every participant supplies their trainer descriptor and three 200-byte party-pair blocks, covering all six original slots. The native startup maps the other three parties independently into partner and opponent parties, bypasses the legacy three-Pokémon selection screen, and installs the shared battle RNG after startup. Save layout and save mailbox ABI are unchanged.

The source-only delta from qualified singles `7efa2448ea19d8aca9946d6572931e97428f0c94` is [phase5-native-full-multi.patch](../engine-patches/phase5-native-full-multi.patch), SHA-256 `7d1a028889c422092762de4b2ddb2404825801a69e449966ec02c81f78c3f6c6`.

Only fixed master slot 0 supplies engine commands. Each battler's owner supplies its replies; all four renderers must finish a command before that battler advances. The transport acknowledges delivery to all three peers, checks typed startup and controller messages, and retains the startup barrier until every original party has been verified against its canonical checkpoint. The development router drains an admitted batch to every recipient before admitting a later batch, preventing a later command from overtaking a pending completion at a slower peer.

Native full Multi uses separate six-slot switch orders, selects each trainer's first usable Pokémon even when earlier slots are fainted or Eggs, and lets a side continue while either trainer has usable Pokémon. The phazing path considers all six slots of the target trainer's own party. Result handling normalizes all four reports to the fixed sides and restores each participant's exact original party and personal RNG before release. Native battles suppress unused recorded-battle snapshots and incidental recording/statistic writes that otherwise charge a teammate's actions to the master.

The earlier frozen `9009bcb` source passed **58 focused multiplayer engine tests**. These include six occupied slots across all four local views, controller ownership, first usable Pokémon in slot six, independent switch-order permutations, owner-only choices, four-renderer completion barriers, targets and party slots beyond the original singles/half-party limits, continuation after one trainer's party is exhausted, exact party/RNG return, and native recording/statistic guards. Its full engine regression passed **5,472 tests with zero unexpected failures**, retaining 18 known failures, 421 TODOs and nine expected failures (5,920 total). Its archived log SHA-256 is `43380176392fee5b76f640cf93ef8f762032088f8d1045910d6418489ed9bb2b`.

A subsequent test-only commit, `703d63001e3adb9c29dc76daad062ea9691423e9`, adds the [phazing regression](../engine-patches/phase5-native-multi-phazing-test.patch): all four target battlers can be forced into their own sixth slot even when their teammate occupies index five in a separate party, without changing any other trainer's order. All **59 focused tests passed**; log SHA-256 `cb18a50f8e8913bc088ecd5e07ba98ce660110c23633fcb22b157ce234e02d61`. The first fixture iteration omitted native `gMain.inBattle`, accidentally exercising field-party ordering; the corrected fixture supplies the real callback precondition. Production source and the frozen actual-proof ROM are unchanged. These fixtures supplement actual-core testing and do not establish every move or a full-six battle as played successfully.

## Earlier four-core proof with starter parties

`native-multi-run-2` used engine `9009bcb45bd252fb93f934fcf41540dc2b0f3390` with occupied party counts **2, 1, 1 and 1**. This historical proof established the four-client battle/save path before the full-six run above.

- Four distinct trainers loaded ordinary Continue and enrolled at canonical checkpoint revision 1. Trainer descriptors and all original six-slot party bytes, including empty tails, matched their canonical owned saves. Every participant passed consent, native binding, preparation and startup barriers.
- The proof routed **1,139 validated complete blocks** and recorded **21 snapshots**. Ordinary joypad input selected native actions and moves. Battler 2 fainted while its teammate continued; battler 0 later fainted and selected its second Pokémon through the native party menu. Further turns completed with fixed-side outcome **2**, a win for slots 1 and 3. No move choice, switch reply, damage or outcome was injected.
- All four cores returned to their own original maps and coordinates. Before release, each participant's exact original 600 party bytes, party count, both personal RNG states and native save counter matched its held values. Flash remained unchanged during the battle; elapsed playtime advanced normally.
- All four matching result receipts and release acknowledgments closed the server-owned BattleDesk battle. Every client then committed an ordinary native checkpoint at revision 2, retaining its owned inventory. The four cores closed, canonical cold-start reconciliation ran, and four fresh cores loaded ordinary Continue with their canonical parties, maps and coordinates and no active battle hold.
- SQLite integrity passed, all four original source-save hashes remained unchanged, and all eight initial/fresh processes closed. The complete private evidence records **five passing checks**.

The run uses the production Lua/companion mailbox transport and authenticated world sessions. Core memory and Flash diagnostics are read-only; external writes stay within allocated production mailboxes. No savestates, arbitrary RAM writes, injected parties or modified source saves are used. This faster-than-real-time headless proof is functional evidence, not Windows, latency or performance acceptance.

## Singles compatibility on the earlier ROM

`native-singles-abi3-run-1` passed five actual-core checks using the same frozen ABI 3 ROM in its two-participant singles phase. Two trainers with occupied parties of two and one Pokémon completed the ordinary-input battle after **362 routed blocks**, including fainting and a native party-menu switch, with fixed-side outcome 2. Both original parties and personal RNG states were restored, battle Flash remained unchanged, ordinary revision-2 checkpoints retained ownership, and two fresh cores passed canonical Continue. All four initial/fresh processes closed and the original source hashes remained unchanged.

The existing singles proof now requires explicit `--native-abi 3` to run this compatibility case; its default remains ABI 2. The private compatibility evidence SHA-256 is `368ab741523337a3d36d9ebdd98171a8797f9ae5286d348e5a49217a600bce33`, and its frozen controller SHA-256 is `92308d42a30240e6c9731a59a6d38beff2d908589800840b11814e7497c9599d`. All **60 run files** were copied to the physical Windows private `artifacts/battles/native-singles-abi3-run-1` archive and individually hash-verified. This is an exercised singles regression, not broad move or full-six acceptance.

## Earlier frozen evidence

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

This historical build's opening VS display used the legacy three-Pokémon summary per trainer even though startup transported all six. The later [six-slot preview](native-multi-preview.md) implements and separately verifies the corrected presentation. The completed full-six run here covers reserve switches through slot six for trainers 0, 1 and 2; trainer 3's reserve switches, broader moves/status/items and dedicated phazing gameplay scenarios remain untested by this run.

The server-owned BattleDesk reservations protect all four characters against concurrent checkpoint/trade mutations during this live session. They do not supply durable interruption settlement. Host restart, disconnect policy and recovery, result/statistic settlement, the player interaction menu, Windows input/runtime integration and separate-PC Wi-Fi/Internet testing remain outstanding. The unresolved battle journal is a separate admission foundation and was not a complete durable coordinator in this proof.

## Combined battle and reset build

The earlier combined build integrated the qualified Local Reset commits and subsequent phazing fixture in `engine-multi-reset` at `3925ad29b685ed35acae36494a15b0736876700e`. The development encounter remains disabled by default. The normal build and all **66 focused multiplayer tests passed**. Copied build-cache timestamps initially produced a clock-skew warning; both builds were rerun after the timestamps elapsed, completing without that warning. The clean focused log SHA-256 is `06ed95769f6e780d9474e04c2f934b1f4b26bd1aad0a4ea9dcc02ca665e4503a`; the clean normal-build log is `c9571342276223fc6ec919a160774a4031e7e6ddabbc68c7ccfc451f0e4881d4`.

`native-singles-combined-run-1` passed five actual-core checks on that exact combined ROM: an ordinary-input 1v1 with fainting and switching, **362 routed blocks**, outcome 2, exact original party/RNG return, unchanged battle Flash, revision-2 ownership checkpoints and fresh canonical Continue. All original source hashes remained unchanged and all four initial/fresh cores closed. Its complete private evidence SHA-256 is `711204214d556855372d621b2a148251c6279bcfc83ca33cb4ef5e18969e0d91`. All **60 run files** were copied to the physical private Windows archive and individually hash-verified.

The default-off combined build is frozen in `native-multi-reset-build-3925ad2` and backed up as five hash-verified files. Its ROM SHA-256 is `2ee0b342cf2dc73f3a37af1ea0fdc08aa0c6144626ea8197680de59cf36425f6`, ELF `1fb08348277998d4992a866c20365a8b8f9cf65a8b5420a0ce774a253539037d`, and manifest `c6bfb8ad1f32f4d6df00eda3d52347ee4b238ba4e360121d4e9df2200ee3c5ec`. This historical run establishes its exercised singles integration only. The later `afd92ce` full-six and Select/reset runs above qualify their respective paths on the same development ROM; Windows input/runtime integration remains outstanding.
