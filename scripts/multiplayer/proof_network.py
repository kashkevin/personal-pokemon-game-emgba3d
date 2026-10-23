"""A player's PC and the internet between the players, for the launcher proofs (KNOWN_ISSUES MS-62 and MS-64).

The proofs run every player's launcher and game on one machine, where the host answers at once and a disk sync costs
nothing; a real world has a friend tens of milliseconds away and a Windows PC whose every fsync waits. Both are
simulated in the host's own process (its WorldServer), from the match on: the world's set-up (enrollment) answers each
step at once, and a delayed connection handshake or rejoin would be refused (wrong_world), as a real one never is.

native_launcher_newcomers_proof.py has flags for them (--latency-ms, --remote-only, --latency-all, --disk-ms,
--no-hold); every other proof built on native_launcher_battle_proof.launcher_proof reads the same from the environment
(PROOF_LATENCY_MS, PROOF_REMOTE_ONLY=1, PROOF_LATENCY_ALL=1, PROOF_DISK_MS), so its battles can be run at internet speed
too without a flag of its own. (PROOF_LIGHT_3D=1, read by launcher_proof itself: --game is the 3D build, with the
light settings of native_launcher_battle_3d_proof.py.)
"""
from __future__ import annotations

import asyncio
import os
import time


def simulate_disk(disk_ms):
    """Every fsync waits `disk_ms` longer, as on a player's Windows PC (a consumer SSD's cache flush and the virus
    scanner's look at each new file; the CI runners and this machine flush at once)."""
    if disk_ms:
        real = os.fsync

        def slow_fsync(fd):
            time.sleep(disk_ms / 1000)
            return real(fd)
        os.fsync = slow_fsync


def simulate_internet(latency_ms, hold=True, host_player=None, everything=False):
    """Every battle message between the host and a player arrives `latency_ms` later, each way (the host's receive and
    send, in its own event loop), as over the internet. `host_player`: the host's own game talks to its server on the
    same PC, without the network's delay. `everything`: every message from the match on (trades, saves, presence), not
    only the battle's. `hold` False: the host answers a battle poll at once, as before MS-62's fix (for a comparison)."""
    from emerald_multiplayer.server import WorldServer
    if latency_ms:
        delay, receive, control = latency_ms / 1000, WorldServer._receive, WorldServer._control

        def lagged(session, message):
            kind = str(message.get("type", ""))
            return ((kind.startswith("battle_") or (everything and kind not in ("hello", "welcome")))
                    and (host_player is None or getattr(session, "player_id", None) != host_player))

        def late_receive(self, session, message):
            if lagged(session, message):
                asyncio.get_running_loop().call_later(delay, receive, self, session, message)
            else:
                receive(self, session, message)

        def late_control(self, session, message):
            if lagged(session, message):
                asyncio.get_running_loop().call_later(delay, control, self, session, message)
            else:
                control(self, session, message)
        WorldServer._receive, WorldServer._control = late_receive, late_control
    if not hold:
        WorldServer._hold_execute_reply = lambda self, session, request, result: self._battle_reply(
            session, request, result=result)


def from_environment():
    """(latency_ms, remote_only, everything, disk_ms) the environment asks for; all off when unset."""
    return (float(os.environ.get("PROOF_LATENCY_MS") or 0), os.environ.get("PROOF_REMOTE_ONLY") == "1",
            os.environ.get("PROOF_LATENCY_ALL") == "1", float(os.environ.get("PROOF_DISK_MS") or 0))


async def apply_environment(current, record):
    """launcher_proof, once the first phase's players are ready: the environment's PC and internet (none by default).
    `current[0]` is the host's launcher worker (its player is the one --remote-only spares)."""
    latency_ms, remote_only, everything, disk_ms = from_environment()
    if not (latency_ms or disk_ms):
        return
    host_player = None
    if remote_only:
        from qualify_admission_cleanup import on_worker

        async def player(s):
            return s._companion.config.player_id
        host_player = await on_worker(current[0], player)
    simulate_internet(latency_ms, host_player=host_player, everything=everything)
    simulate_disk(disk_ms)
    record("simulated-network", latency_ms=latency_ms, remote_only=remote_only, everything=everything,
           disk_ms=disk_ms)
