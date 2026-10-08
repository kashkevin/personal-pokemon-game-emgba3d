# Durable personal reset delivery

Native reset source `7b3dbbe7f2c80e4d2af0e0332c333320fcda4589`, incorporated in combined source `1a7a0cdb5dadd2820a3b6c25c4ecafce1facd6eb`, implements nine explicit authored hunts on the preserved `de4ef98a` pilot. The current correction and qualification are described below; ordinary-route gameplay and the combined Windows release remain separate acceptance gates. Build flag `LOCAL_RESET_STATIC=1` enables the catalogue. Its default is zero, and the independent Littleroot development encounter is unchanged.

## Player behavior and source boundaries

The authored interaction waits for its durable attempt acknowledgment before generating a Pokémon. The first action screen displays `Attempt: <number>` and `SELECT: Reset`. Select opens the existing Yes/No confirmation with No selected. No/B preserves the same opponent and count; Yes returns through native battle cleanup and an authored neutral script branch. The next ordinary interaction requests the next count and fresh native RNG roll. The connection, other players and shared state are untouched. Choosing a battle action or entering a capture path permanently closes the reset window for that encounter.

| ID | Authored source | Native object and prerequisites |
| --- | --- | --- |
| `0x1001` | New Mauville Voltorb 1, level 25 | Local 6 at 25,18; opened generator state 1 or 2. |
| `0x1002` | New Mauville Voltorb 2, level 25 | Local 7 at 6,11; same generator prerequisite. |
| `0x1003` | New Mauville Voltorb 3, level 25 | Local 8 at 13,10; same generator prerequisite. |
| `0x1004` | Aqua Hideout Electrode 1, level 30 | B1F local 6 at 16,9. |
| `0x1005` | Aqua Hideout Electrode 2, level 30 | B1F local 8 at 16,10. |
| `0x1006` | Ancient Tomb Registeel, level 40 | Local 1 at 8,7; its native door puzzle complete. |
| `0x1007` | Desert Ruins Regirock, level 40 | Local 1 at 8,7; its native door puzzle complete. |
| `0x1008` | Island Cave Regice, level 40 | Local 1 at 8,7; its native door puzzle complete. |
| `0x1009` | Sky Pillar Rayquaza, level 70 | Local 2 at 14,6; native Sky Pillar state at least 2. |

Every descriptor requires its exact map, talked-to local object, fixed native coordinates, and clear hide/defeat flags. Availability is rechecked before reset. New Mauville also preserves generator and barrier variables; Rayquaza preserves its Sky Pillar state. Clone-based checks verify the actual species, level, non-egg valid record and absence of another opponent. Only the four authored legendary descriptors admit the native legendary battle flag. Trainer/link/PvP, ordinary wild, gifts, roaming and World Event sources remain excluded. No tickets, doors or story flags are unlocked by this feature.

The map resume callbacks already remove these targets only after an ordinary capture. Each adapter consumes the dedicated accepted-reset result before its original outcome/defeat/removal branches. Normal captures and other outcomes retain their original scripts. No save snapshot, RNG state, party, bag, money or progression is restored. Dynamic Marine/Terra Cave approach sequences, Kecleon visibility, Sudowoodo watering and ticket encounter movement/puzzles still need individual adapters; no generic static hook silently opts them in.

## Attempt durability and RNG

The lease-bound host ledger resides in the same SQLite database as checkpoints. It records a unique native request identity, request UUID, checkpoint revision and monotonic per-player/per-descriptor count. Exact retries return the existing receipt. It contains no encounter seed, PID, shiny status, rewards or arbitrary native pointer. An admitted interaction can remain unseen if its ACK is lost; it keeps its count and transport retries cannot add another. On fresh native Continue, the host count remains authoritative even if the ordinary save is older. A native counter ahead of the ledger refuses entry rather than silently rewriting history.

The original Voltorb1 versioned save variables remain a compatibility mirror. The eight additional descriptors use a small RAM cache of observed host counts, so no new persistent save variables or layout changes are required. The cache is not advertised as local crash durability: it is rebuilt from authenticated host receipts. Counts shown during generation are the acknowledged host numbers.

Before publishing a native request, the core checks enrollment, idle binding, usable party, source eligibility and absence of an active network battle. The same guards are rechecked after acknowledgment. The host fences active battle reservations, unresolved committed trades, active proposals and uploads. Admission changes neither canonical Pokémon bytes nor capture ownership.

Only new rolls within an admitted personal source use the approved Gen 6 shiny xor range of 16, through the engine's existing stored shiny modifier. Existing owned Pokémon and the global eight-value predicate remain intact. Force-shiny/force-not-shiny flags retain priority. Normal wild, event, gift, lure, fishing and DexNav rules remain unchanged; the future personal Shiny Charm remains separate work. The native per-core RNG keeps advancing and is never seeded from the attempt counter.

## Exact host-loss cancellation

Reset ABI2 retains the 128-byte mailbox. `Q` advertises it, `T` carries the exact 32-byte request, `U` carries an ACK/refusal/cancel and `Y` relays a read-only native receipt. `V` remains reserved for the existing save capability. Lua writes only the inbound generation and 32-byte reply. It never writes receipt, counter, RNG or character memory.

Cancellation is accepted only for the exact waiting request, with matching retained session/incarnation and an idle native save binding, after the native connection is disconnected. It resumes only the neutral authored cleanup branch. An already accepted ACK cannot be reversed, and repeated cancellation is inert. The native receipt distinguishes waiting, admitted, denied and cancelled. A neutral receipt becomes field-ready only after the same field-safety predicate used by native saving succeeds.

The emergency controller owns the existing checkpoint lock and retained bridge authority. Before beginning a new emergency export it invokes `drain_before_emergency`, fences any queued admission, and awaits an exact neutral receipt plus safe-field observation. It does not wait for an admission task queued behind that same lock. Unknown or refused cancellation still goes through the independent native emergency hold; receipt readiness alone never authorizes serialization. Promotion of an already frozen ordinary export skips reset drain. The combined actual-core host-loss scenario is not yet qualified on the composed native source.

## Reuse and checks

The adapter reuses the pinned native generator, shiny modifier, battle cleanup and original scripts. The maintained source was checked at `7b95be15d84a053948791ce91e5dec0b168947a5`: [Sky Pillar](https://github.com/rh-hideout/pokeemerald-expansion/blob/7b95be15d84a053948791ce91e5dec0b168947a5/data/maps/SkyPillar_Top/scripts.inc), [Ancient Tomb](https://github.com/rh-hideout/pokeemerald-expansion/blob/7b95be15d84a053948791ce91e5dec0b168947a5/data/maps/AncientTomb/scripts.inc) and [Aqua Hideout](https://github.com/rh-hideout/pokeemerald-expansion/blob/7b95be15d84a053948791ce91e5dec0b168947a5/data/maps/AquaHideout_B1F/scripts.inc) retain the relevant caught-only resume and source-specific removal branches. The prior upstream/community audit remains in the [reset design](local-soft-reset-design.md). No third-party code or new dependency is incorporated.

The historical default-off normal build and **103/103 native Multiplayer tests** passed on `3dcfd103`. The nine-source cases exercise exact object/prerequisite refusals, all nine neutral returns and all nine original caught branches, trainer/capture/action fences and an unsigned high counter. Admission/cancellation fixtures cover foreign identity, unknown host loss, no generation/count before ACK, exact once-only count, neutral cancellation and inability to reverse an accepted ACK. They are controlled native fixtures, not ordinary-route play. These checks missed the authored script's asynchronous yield boundary, so this historical build is not production admission evidence.

Read-only review before enabled combined qualification found that `ScriptContext_Stop()` changes global scheduling status without yielding the current `special` bytecode loop. The admission specials had no implicit `waitstate`, so their callers could consume the initial false result immediately. Correction `7b3dbbe7f2` publishes a distinct pending result and conditionally executes `waitstate` in all nine authored scripts. Immediate refusals skip the wait and exit neutrally. The test-only direct-admission wrapper bypass is removed. Three new regression methods step the actual authored bytecode through pending, immediate refusal, exact denial and disconnected cancellation for all nine descriptors, plus stale/exact acknowledgment and native generation for all five Voltorb/Electrode sources. The generation cases stop at the original sound-effect yield; they do not simulate a completed production battle or ordinary progression.

The corrected combined source `1a7a0cdb5d` passes the enabled normal build and **122/122 native Multiplayer tests**, including these three regressions and the composed trade-menu/emergency changes. `LOCAL_RESET_STATIC=1` was used for both targets. A bounded incremental recheck also passes with no warnings or errors in `normal-3.log` and `focused-3.log`; post-recheck ROM/ELF hashes exactly match the ELF-derived manifest. That manifest reports menu ABI2, emergency ABI2, reset ABI2, battle ABI3/execution ABI1 and save-window ABI1. It does not contain the later battle-resume capability. Fourteen files plus a re-read/hash-verified evidence record are preserved in private `artifacts/local-reset/combined-delivery-reset-static-1`. The pre-correction clock-skew normal log and interrupted focused-compilation log are explicitly historical. The clean source trees and both reusable/combined patch lineages are preserved.

| Corrected combined enabled artifact | SHA-256 |
| --- | --- |
| Normal ROM | `4fcdae904ad4f0f49e805096c932c0a8f6ba7f753b1d038cd51c7854142d4fa2` |
| Normal ELF | `4d331c224e54d3bf1b61497a978a9524861a1d5657775fa1726746f7832234df` |
| Exact manifest | `aa680a0caf452a95d90b6802cf51da47ee917a97180d37560e6d74154e286325` |
| Clean normal log | `e59115cd730c4259068a275b5fb8b328fcd09ba84e7d1a4f2b36c9c31d93679b` |
| Clean 122-case log | `c5175d3c8be1314ebf5b1dc3a32db14d5b17a3429d5e06922907e21263d4deae` |
| Evidence record | `c7ce03d52435f07087553a9b0b0fcdeb417e82289077348ea3601eafaea85369` |
| [Source-only correction](../engine-patches/phase6-personal-reset-script-yield.patch), `3dcfd103` to `7b3dbbe7f2` | `b8bdf79102b97cd7d7316694b3473de6f4fa1069254b9bfbe8cce89036200676` |

Initial catalogue test builds exposed invalid text initializer placement; corrected source passed all tests. A first passing log retained Windows/WSL clock-skew warnings, so completed incremental rechecks were run. Only warning-free `normal-3.log` and `focused-4.log` are qualification evidence. An earlier ABI2 build's unused marker was removed by linker garbage collection; the final source now uses the established volatile marker read, and its actual ELF-derived manifest validates successfully. Synthetic manifest tests alone did not establish that property.

Thirteen files plus the evidence record are hash-verified in private `artifacts/local-reset/durable-reset-delivery-1`, including historical failures/warnings, clean logs, normal ROM/ELF, test ELFs, manifest and source patch. No ROM, save, database or player credential is committed.

| Historical default-off artifact (`3dcfd103`, before script-yield correction) | SHA-256 |
| --- | --- |
| Normal ROM | `39b3e1e343b07df6b1fdd3e92238cf204da33aaecf503c9f3bb4dae1b8c47918` |
| Normal ELF | `3770de0285c0a54c344ee43b392eb2d8aff72909826101ae90dde4b2819b53f9` |
| Exact manifest | `f00ce1056786a223627b1777acf6dc847a83ab03fc356db079cf6751f40cf8b9` |
| Clean normal log | `60c09bc713ebe2c24c6399f81f428266e2d312216f7721c443bfa8bf2a4bda69` |
| Clean 103-case log | `0f8ebbaf02a94b06a91a64e831272e670cd1029e7998fa9e956e9404c8d7fa1a` |
| Evidence record | `78cfdb505b842d5368b8c25c5ca0ede294648c3f64e6d6df862743da2cc88a4f` |
| [Source-only patch](../engine-patches/phase6-durable-personal-reset.patch) from `de4ef98a` | `97e3b8ea6a684ba6de1db8f7a731708abcd5dbf1aa9579f9c93052c8d794680f` |

All **28 reset Python methods** passed in the composed Windows focus: SQLite migration in both orders, fresh-world capability provisioning with preserved backup accounts, nine independent descriptor histories, exact retries, stale leases, corruption rejection, graceful restart and abrupt `os._exit` recovery, four authenticated TLS companions, real Lua and binary IPC, ABI2 receipts/cancellation authority and ELF-derived manifest validation. Character checkpoint bytes remain unchanged by admission. These tests use synthetic save/mailbox fixtures; they establish transport and persistence behavior, not production gameplay. The encompassing 173-method run retained nine errors in five separate friendship-Flash fixture methods and is not recorded as a full passing regression. Its private log is `root-delivery-windows-3.log`, SHA-256 `836e408b84d3c30bdb17c1429626b65a8407440b32bb3885ab9c9e68ef0f684c`.

Ordinary-route source interactions/capture/fresh Continue, composed pending-reset host-loss saving, Windows control/render checks and simultaneous four-player trade/battle/hunt remain required. The known starter-stage source characters have not reached these story-gated hunts. No debug warp, story injection, downloaded save or savestate substitutes for those acceptance tests.
