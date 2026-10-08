# Native battle transport proposal

This architecture audit and implementation proposal is dated October 8, 2026. A separate [development diagnostic block channel](battle-channel-mailbox.md) now exercises the native link seam without battle entry or controller dispatch. Native singles/Multi battles, playable 1v1/2v2 acceptance, wager rules and automatic forfeits remain unimplemented. The separate development TeamDesk coordinates membership only.

The preferred first route is a ROM-owned virtual link **block** adapter, using the existing native battle engine above its serial/RFU transport. Prove 1v1 first, then four-human 2v2 with the owner's explicit October 8 decision: **up to six Pokemon per trainer**, potentially twelve per side, kept in four separate trainer parties. Exploration cores remain independent; only an explicitly consented battle roster participates in its block barriers.

## Pins and reuse

The audited local engine is trade foundation **b2cdd466abb8b142c3b75384133b5e6b3c3b982c**, based on accepted ownership **88c7ef798ab5f91a496099cc687252fa5c4b12a3**, RHH 1.17.1 baseline **bb1093a7c72d3961d9a37d8e02ad2abc2c866682**. Local line references below refer to that preserved engine. The later diagnostic implementation is isolated at `8c839171e1070ba31d66e74aae35bb207fe39b4a`; it does not modify the accepted worktrees.

Maintained RHH upstream was checked at **6057b187f946094d614e9c34bc12731ea6a5b7bb**. Its [battle controllers](https://github.com/rh-hideout/pokeemerald-expansion/blob/6057b187f946094d614e9c34bc12731ea6a5b7bb/src/battle_controllers.c) still use native link IDs and block transfer; its [Cable Club flow](https://github.com/rh-hideout/pokeemerald-expansion/blob/6057b187f946094d614e9c34bc12731ea6a5b7bb/src/cable_club.c) is not an independent-world coordinator. These are compatible architectural references, not imported upstream changes.

[Wired-Ariel v1.7.2](https://github.com/Wired-Ariel/gen3-poke-multiplayer/blob/v1.7.2/README.md) is a vanilla-game Lua/Cable Club reference. It does not establish compatibility with this expansion's party layout, ownership, ordinary Flash checkpoints or four-player world. No code was incorporated. Source/license/attribution and measured behavior still need review before any external implementation is imported.

## Why a virtual block adapter

Official [mGBA 0.10.5 documentation](https://github.com/mgba-emu/mgba/blob/0.10.5/README.md) lists same-computer cable support and networked cable support as a planned feature. Its [lockstep driver](https://github.com/mgba-emu/mgba/blob/0.10.5/src/gba/sio/lockstep.c) attaches in-process nodes and schedules serial events against shared lockstep state. The [Qt multiplayer controller](https://github.com/mgba-emu/mgba/blob/0.10.5/src/platform/qt/MultiplayerController.cpp) manages those local cores. This can provide a useful native-link reference test; it does not supply a tested cross-PC dynamic battle connection.

Adding a network SIO driver would require emulator work, serial timing/handshake recovery and a compatible runtime on each PC. Lockstepping all four exploration cores would violate the intended independent play. Joining only participants dynamically could be investigated, but is not a smaller verified dependency today. These are source-based inferences, not latency benchmarks.

The existing ROM already exchanges complete party/header/controller blocks and waits for them. Replacing that block transport can preserve move selection, targeting, switching, animations and the native battle calculations without reproducing mechanics in Python. The proposed server will control authenticated membership, ordering, routing and later result persistence; a designated native ROM master will compute battle mechanics. The current diagnostic caller supplies a roster of its authenticated companions and routes typed frames itself. WorldServer has no battle-roster consent or diagnostic-routing desk yet.

## Concrete native hooks

| Local source | Existing behavior to reuse or adapt |
| --- | --- |
| src/battle_main.c:472 | CB2_InitBattle allocates resources; Multi enters a partner showcase before normal initialization. The save-block/heap movement here means pointers retained by a new adapter must survive relocation or be reacquired. |
| src/battle_controllers.c:129 | HandleLinkBattleSetup starts physical link connection/send/receive tasks. A virtual-session branch must create the battle tasks without initiating serial or RFU handshakes. |
| src/link.c:984-1074 | Multiplayer ID, SendBlock, IsLinkTaskFinished, block received flags and reset/advance helpers are the main transport seams. Also adapt count/master/close/standby helpers at 724, 1328 and 1357. Dispatch virtual sessions before the wireless selector, which can remain set after ordinary Center scanning. |
| src/battle_main.c:866-1047 | Singles startup exchanges a header, six party mons in three 200-byte blocks, and recorded RNG state. |
| src/battle_main.c:1502-1721 | Native four-human Multi maps parity to two sides and separate player/partner/opponent parties. It currently exchanges three mons per trainer, in 200-byte then 100-byte blocks. |
| src/battle_controllers.c:618-839 | Native controller messages have an 8-byte header and padded payload; send/receive tasks maintain 4096-byte rings. Receivers also process their own transmitted blocks. Preserve that loopback semantics and acknowledgement order. |
| src/battle_controllers.c:216-407 | The master starts battle calculations; other participants use a dummy main battle function and local/link controllers. Each device's own trainer remains its B_TRAINER_PLAYER party. |
| src/battle_util.c:1143-1181 | Execution flags wait for controller completion from the participating link players. Transport acknowledgements alone are not controller completion. |
| src/main.c:368-392; src/battle_main.c:1790 | Link battle VBlank avoids ordinary random advancement. The new adapter must avoid hardware link work while retaining native display/audio and controller polling. |
| src/cable_club.c:811-875; 990-1020 | Current entry selects flags/reduces Multi party. Current return restores party, changes link stats, invokes Cable Club field return and saves. Reuse components rather than that entire callback. |
| src/load_save.c:171-195 | SavePlayerParty/LoadPlayerParty provide original-party backup/restore in existing SaveBlock1. Load updates encrypted HP/status consistently with the native representation. |
| src/multiplayer_ownership.c:128-137; src/multiplayer_save.c:149-162 | Owned saves refuse battle/rental states; live export requires an idle field. Add an explicit network-battle lifecycle guard around the pre-start and post-battle gaps. |

Native Multi currently transfers three selected mons; this must be adapted to meet the owner's now-explicit six-per-trainer requirement. Each original owned party stays separate and is restored afterwards. Current six-slot trainer arrays alone do not enable full-six network Multi. The following bounded adaptations can reuse existing engine components:

- Extend CB2_HandleStartMultiBattle's party exchange (battle_main.c:1597-1662) to three 200-byte rounds per source trainer, copying all six to each device's proper local player/partner/opponent array. Remove the half-party reduction from the dedicated network entry, preserving ordinary Cable Club behavior.
- Add an explicit full-party network-Multi case to AreMultiPartiesFullTeams (battle_util.c:9918). The ordinary runtime branch explicitly returns false for TRAINER_LINK_OPPONENT at 9955 despite B_MULTI_HALF_TEAMS already being false. A global configuration switch alone cannot fix this.
- Reuse party_menu.c's full-team paths (7484, 7611, 7684, 7933, 8594) after auditing partner showcase, individual indexes, switches and disallowing choices from another trainer's party. They must remain indexes 0-5 in the owning trainer array, rather than a merged twelve-mon array.
- Audit the remaining half-team assumptions: CanBattlerSwitch (battle_script_commands.c:3313), forced random switching (5539-5604), GetFirstFaintedPartyIndex (9245), battle intro party summary (battle_main.c:3218), and party showcase/correction loops. Forced-switch link-Multi currently unconditionally stops at PARTY_SIZE/2 and excludes the ally's numeric active index even when the trainers have separate parties. Changing the shared helper is insufficient; use the target trainer's six slots and exclude another battler's index only when BattlersShareParty is true.
- Adapt the network-Multi outcome path as well. WillPlayerWhiteOutIfPartnerWinsAlone (battle_script_commands.c:2488) returns true for full teams, and NoAliveMonsForPlayer (2514) can declare that side lost as soon as the calculating master's own party is exhausted despite its teammate surviving. Network Multi needs a whole-side exhaustion check; preserve the existing campaign partner/whiteout policy outside that session.
- Prove all four trainers can switch to slots 3, 4 and 5; phazing respects separate parties; one trainer exhausting all six leaves the teammate's surviving party usable; and each trainer's ownership/count/order is preserved after return. Full-party testing fixtures are useful but do not prove real native link paths.

These adaptations are specific to the dedicated network session and must preserve existing solo/Cable Club/Frontier rules. The six-per-trainer Multi work does not block the independent singles proof.

Four battler slots describe conventional two-sided doubles. They do not implement custom 1v1v1v1 or its targeting, victory and reward rules.

## Proposed admission and lifecycle contract

Before native battle entry edits, agree the exact ABI extension and states with the server/bridge owners. Keep presence/save ABIs stable and use the separately identified development battle capability/mailbox.

1. **Invite and consent.** A bounded development invitation names exactly two players for singles, or two current two-player teams for Multi. Capture player leases, bridge incarnations and team generations. The sender consents only for itself; every other participant must accept the exact immutable generation. Changing participants, selections or checkpoint heads invalidates consent. No friendship threshold is involved.

2. **Prepare.** Each ROM independently admits at the same proven field safe point, with at least one valid non-egg usable mon and no native link, wild/local battle, rental challenge, live checkpoint or unresolved trade. Capture an ordinary owned pre-battle checkpoint and durably retain its hash/revision. Backup the original six mons/count before reordering/reducing anything; preserve PC/daycare/fusion inventory, UIDs, OT/PID, held items and individual wallet. The server validates offered selections against each player's own canonical roster. A crashed preparation cannot expose temporary battle parties as an ordinary character.

3. **Start barrier.** Bind a battle UUID/generation, ruleset/build, ordered participants, exact leases/incarnations, sides, selected serial/order and checkpoint hashes. For Multi, native battler IDs 0/2 share one side and 1/3 the other. For singles, IDs are 0/1. Link-player indexes and trainer/battler IDs must be defined separately. Start only after all native preparation acknowledgements; retries cannot seed/start twice.

4. **Battle.** Let the pinned native engine run the battle and its controllers. The server-assigned slot 0 is the native master, never a peer-claimed authority. Route only roster blocks. The other exploration clients continue running, saving and encountering independently. Wait at native block/controller barriers while keeping display, menus, presence and network heartbeat responsive; never fast-forward a paused participant or synthesize a move.

5. **Result hold and restore.** Normalize native per-player win/loss projections to the fixed sides before comparing result acknowledgements. Restore each original local party and return to its original map through normal engine callbacks. Clear temporary remote parties. Avoid Cable Club's dynamic-warp/recording/save flow. Keep character mutation blocked until restoration and any later canonical result transaction are confirmed. No wager, currency deduction, forced loss or new reward amount is introduced by the first proof.

6. **Interruption.** Before start, cancellation may return safely only after every affected ROM is known restored. After start, a timeout produces an explicit interrupted/recovery-required state. It does not automatically declare a winner, forfeit, abort or reset the game. A bounded journal and the paused cold-start recovery barrier are needed before shipping restart recovery; the existing volatile hold alone cannot stop an old native Continue after a cold reset. Final interrupted-battle gameplay policy remains pending.

RNG needs a deliberate small adaptation, not world-global reseeding. The local engine uses a 16-byte SFC32 state (include/random.h:24-33); SeedRng initializes it (random.c:78). Native link has a single calculating master and separately exchanges recorded state (battle_main.c:1019 and 1687; recorded_battle.c:94). Proposed first proof: isolate a server-issued battle seed/state from every participant's pre-battle personal state, restore the personal stream after exit, and verify no nonparticipant state changes. Exact state-switch/recording hooks require C review; do not assume a vanilla 32-bit seed or accept reseeding on retries.

## Proposed bounded block channel

The first implemented diagnostic uses a dedicated **512-byte mailbox**, fixed commands and a 128-byte maximum read chunk, so framed bridge packets stay within the current 256-byte IPC cap. Its exact contract and frozen build evidence are in [battle-channel-mailbox.md](battle-channel-mailbox.md). The initial channel adds 1,188 bytes of EWRAM in total and no heap allocation; native battle extensions still require their own memory and frame-cost measurements. The implemented diagnostic accepts only one typed 40-byte frame, never native controllers or startup data.

The engine owns all destination buffers. External code writes only the dedicated command/inbound slots; no addresses, pointers, save offsets, controller buffers or party RAM are supplied by a client. A chunk is committed atomically by an even generation written last, validated by C, then copied through the legitimate virtual-link API.

Bind every block to battle UUID/generation, participant slot, lease/incarnation, monotonically increasing block sequence, phase, declared size, chunk offset and CRC. Stop and wait for complete block/consumption acknowledgements, bounded per-participant staging and bounded server queues. A reconnect needs an explicit authoritative session/recovery query; stale generations, changed payload retries, skipped chunks, overflow and unsolicited blocks cannot reach native callbacks. Native startup blocks observed in source are at most 200 bytes; adopt the pinned 256-byte receive-buffer ceiling only after auditing all enabled controller payload sizes. Never silently truncate larger messages.

Native wire data is **not** a safe opaque general-purpose RPC. In particular, battle_controller_player.c:2227 accepts a DMA destination, and battle_controllers.c:2354 exposes raw-mon setters; their emitters in battle_controllers.c are marked UNUSED but dispatch handlers remain reachable. GetMonData's generic handler at battle_controllers.c:2290 also trusts a six-bit selection mask despite a 256-byte local scratch buffer. Network validation must restrict permitted fields and selection masks to the bounded native call sites. Define a typed phase/command/length and sender-role allowlist in both server and C:

- Startup headers/party blocks come only from the bound source player and match its prepared snapshot/selection.
- Engine-to-controller instructions come only from the designated native master.
- Controller-to-engine choices come only from the player owning that battler, with valid move/party/target bounds.
- Controller-done messages identify the authenticated origin, not an embedded claimed player ID.
- Refuse DMA/arbitrary-pointer commands, raw-mon read/write and unsupported commands before copying to native queues; audit safe SetMonData request fields and exact lengths.
- Reject unknown battler IDs, invalid native lengths/padding, queue overwrite, received-flag reuse and deliveries after close.

This preserves legitimate battle-controller operations while refusing an arbitrary RAM write path. It does not prove anti-cheat or server-side damage calculation.

## Next bounded milestone and acceptance

The bounded two-ROM typed diagnostic and close-game recovery proof has passed on the isolated `8c839171` build; [its contract/evidence](battle-channel-mailbox.md) records the exact scope. Next, audit and extend typed native singles startup/controllers, then prove one ordinary native singles battle with joypad-selected moves and normal return. Keep development capabilities disabled in the normal player launcher until their own acceptance gates pass. Only after singles should the channel carry four-human Multi and team-bound consent.

Required evidence includes two actual battling ROMs plus two actual independently moving nonparticipants; all four local-party controls in Multi; target/switch/faint/status/held-item/animation paths; equal normalized outcomes; original party/count/UID/item/PC/wallet preservation; map-specific return and ordinary save/fresh Continue; late/duplicate/out-of-order and malformed role/length blocks; pause, lost connection, reboot and server restart; explicit recovery without accidental result/wager effects; and upstream engine regression checks. Record elapsed latency, queue peaks, EWRAM/heap and emulator CPU use. Synthetic transport or engine tests supplement these actual-core checks.
