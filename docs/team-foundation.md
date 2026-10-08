# Team invitations: development foundation

`TeamDesk` and the authenticated team RPC channel implement session-local two-player teams behind `WorldServer(development_teams=True)`. The default is disabled. Two pairs can coexist, and joining a world never forms a team. Only the invited player can accept the current invitation generation; the sender cannot accept on their behalf. Decline, cancel, leave, and status are separate operations. Changing partners means explicitly leaving, then sending or accepting a new invitation.

Every operation derives its actor from the authenticated server connection and checks the current durable lease. Invitations expire, are bounded to two disjoint pairs, and cannot survive a changed lease or membership. Exact accepted retries return the existing pair while it remains current. Lost replies require authoritative status reconciliation. Team state touches no Pokémon, save payload, wallet, rewards, trade result, or permanent friendship.

This initial development scope dissolves a pair if either participant disconnects/reconnects and starts empty after server restart. Final membership persistence and player-facing interruption behavior remain to be selected before release. The response explicitly identifies this session-local scope; it is not a permanent relationship system.

The implementation reuses the existing authenticated companion reader, heartbeat, bounded message queues, and ownership-world leases. The pinned engine's native link multi-battle and AI-partner setup do not provide free-form server membership. Current RHH upstream `6057b187f946094d614e9c34bc12731ea6a5b7bb` still uses native link-player/controller transport. No external networking implementation was incorporated. Battle execution requires separate integration of those native systems.

## Verification

The 41 new tests pass on both Windows and WSL without skips: 18 coordinator tests, 10 strict protocol tests, and 13 gate/TCP tests. Four real authenticated Python companions form two simultaneous teams while presence and heartbeat continue. Tests cover role/actor rejection, stale socket/database leases, generation changes, expiry, reconnect/restart, explicit partner changes, a lost acceptance reply, the default-disabled gate, and independence from a pending local trade journal and server trade proposal. These are transport clients with fixture game data, not four actual ROMs participating in a battle.

The accompanying companion guard keeps a pending trade journal in charge of persistent mutations between live-coordinator calls. Read-only status remains available, and volatile team operations remain independent. Its affected eight-test companion set passes on both platforms. Actual trade/ownership integrity remains governed by the separate [trade foundation](trade-foundation.md).

Remaining work includes an in-game invitation/player menu, final reconnect persistence, native 1v1/2v2, battle interruption and party restoration, and actual four-core team/battle acceptance. This foundation alone does not complete roadmap item 2.
