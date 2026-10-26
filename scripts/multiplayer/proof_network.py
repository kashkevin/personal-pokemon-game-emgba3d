"""A player's PC and the internet between the players, for the launcher proofs (KNOWN_ISSUES MS-62 and MS-64).

The proofs run every player's launcher and game on one machine, where the host answers at once and a disk sync costs
nothing; a real world has a friend tens of milliseconds away and a Windows PC whose every fsync waits. Both are
simulated in the host's own process (its WorldServer), from the match on: the world's set-up (enrollment) answers each
step at once, and a delayed connection handshake or rejoin would be refused (wrong_world), as a real one never is.

native_launcher_newcomers_proof.py has flags for them (--latency-ms, --remote-only, --latency-all, --disk-ms,
--no-hold, --jitter-ms, --stall-every, --stall-ms); every other proof built on native_launcher_battle_proof.launcher_proof
reads the same from the environment (PROOF_LATENCY_MS, PROOF_REMOTE_ONLY=1, PROOF_LATENCY_ALL=1, PROOF_DISK_MS,
PROOF_JITTER_MS, PROOF_STALL_EVERY, PROOF_STALL_MS), so its battles can be run at internet speed too without a flag of
its own. A rough connection (owner priority 2026-10-24: trades and battles between two real PCs): each message is late
by the latency plus a random share of the jitter, and every `stall_every` seconds the connection stalls for `stall_ms`
(a Wi-Fi hiccup); a message never overtakes an earlier one of the same session and direction, as on TCP. (PROOF_LIGHT_3D=1, read by launcher_proof itself: --game is the 3D build, with the
light settings of native_launcher_battle_3d_proof.py.)
"""
from __future__ import annotations

import asyncio
import os
import random
import threading
import time
import traceback


def simulate_disk(disk_ms):
    """Every fsync waits `disk_ms` longer, as on a player's Windows PC (a consumer SSD's cache flush and the virus
    scanner's look at each new file; the CI runners and this machine flush at once). PROOF_FSYNC_TRACE=<file>: each
    fsync of the proof process (the host's and the launchers' journals) is also written there as "fsync START_MS
    DURATION_MS THREAD CALLERS", START_MS on the monotonic clock the games' PKMN_LINK_TRACE lines use (Linux), for
    tools/pc_port/link_latency.py --fsync."""
    trace = os.environ.get("PROOF_FSYNC_TRACE")
    if disk_ms or trace:
        real = os.fsync
        out = open(trace, "a", buffering=1) if trace else None

        def slow_fsync(fd):
            started = time.monotonic()
            try:
                if disk_ms:
                    time.sleep(disk_ms / 1000)
                return real(fd)
            finally:
                if out is not None:
                    # who asked (the nearest emerald_multiplayer functions): which journal or record it was
                    callers = [f"{os.path.basename(f.filename)[:-3]}.{f.name}" for f in traceback.extract_stack(limit=8)
                               if "emerald_multiplayer" in f.filename][-3:]
                    out.write(f"fsync {started * 1000:.2f} {(time.monotonic() - started) * 1000:.2f} "
                              f"{threading.current_thread().name.replace(' ', '_')} {'<'.join(reversed(callers)) or '-'}\n")
        os.fsync = slow_fsync


class RoughLink:
    """When each message arrives: `latency_ms` plus a random share of `jitter_ms` late, held to the end of a stall of
    `stall_ms` every `stall_every` seconds, and never before an earlier message of the same session and direction."""

    def __init__(self, latency_ms=0.0, jitter_ms=0.0, stall_every=0.0, stall_ms=0.0, *, start=0.0, rng=None):
        self.latency, self.jitter = latency_ms / 1000, jitter_ms / 1000
        self.every, self.stall = (stall_every, stall_ms / 1000) if stall_every and stall_ms else (0.0, 0.0)
        self.start, self.rng, self.last = start, rng or random.Random(0), {}

    def arrival(self, now, key):
        """When (on `now`'s clock) the message of `key` (session, direction) is delivered: strictly after the one before
        it, so timers due at once (every message held by a stall) still run in order, as on TCP (an event loop runs
        timers due at the same instant in no fixed order: run 214's trade-rough had its save's chunks overtake)."""
        at = now + self.latency + (self.rng.uniform(0, self.jitter) if self.jitter else 0.0)
        if self.every:
            phase = (at - self.start) % self.every
            if phase < self.stall:
                at += self.stall - phase          # sent during a stall: it goes when the stall ends
        previous = self.last.get(key)
        if previous is not None and at <= previous:
            at = previous + 1e-6
        self.last[key] = at
        return at

    def delay(self, now, key):
        """Seconds from `now` until the message of `key` is delivered."""
        return max(0.0, self.arrival(now, key) - now)


def simulate_internet(latency_ms, hold=True, host_player=None, everything=False, *, jitter_ms=0.0, stall_every=0.0,
                      stall_ms=0.0, seed=0):
    """Every battle message between the host and a player arrives `latency_ms` later, each way (the host's receive and
    send, in its own event loop), as over the internet. `host_player`: the host's own game talks to its server on the
    same PC, without the network's delay. `everything`: every message from the match on (trades, saves, presence), not
    only the battle's. `hold` False: the host answers a battle poll at once, as before MS-62's fix (for a comparison).
    `jitter_ms`, `stall_every` (seconds) and `stall_ms`: a rough connection (RoughLink)."""
    from emerald_multiplayer.server import WorldServer
    if latency_ms or jitter_ms or (stall_every and stall_ms):
        receive, control = WorldServer._receive, WorldServer._control
        link = RoughLink(latency_ms, jitter_ms, stall_every, stall_ms, start=time.monotonic(), rng=random.Random(seed))

        def lagged(session, message):
            kind = str(message.get("type", ""))
            return ((kind.startswith("battle_") or (everything and kind not in ("hello", "welcome")))
                    and (host_player is None or getattr(session, "player_id", None) != host_player))

        def later(session, direction, call, *args):
            loop = asyncio.get_running_loop()
            # call_at, not call_later: arrival times strictly increase per direction, and a relative delay would add
            # each call's own reading of the clock.
            loop.call_at(link.arrival(loop.time(), (id(session), direction)), call, *args)

        def late_receive(self, session, message):
            if lagged(session, message):
                later(session, "in", receive, self, session, message)
            else:
                receive(self, session, message)

        def late_control(self, session, message):
            if lagged(session, message):
                later(session, "out", control, self, session, message)
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


def rough_from_environment():
    """(jitter_ms, stall_every, stall_ms) the environment asks for; all off when unset."""
    return (float(os.environ.get("PROOF_JITTER_MS") or 0), float(os.environ.get("PROOF_STALL_EVERY") or 0),
            float(os.environ.get("PROOF_STALL_MS") or 0))


async def apply_environment(current, record):
    """launcher_proof, once the first phase's players are ready: the environment's PC and internet (none by default).
    `current[0]` is the host's launcher worker (its player is the one --remote-only spares)."""
    latency_ms, remote_only, everything, disk_ms = from_environment()
    jitter_ms, stall_every, stall_ms = rough_from_environment()
    if not (latency_ms or disk_ms or jitter_ms or (stall_every and stall_ms) or os.environ.get("PROOF_FSYNC_TRACE")):
        return
    host_player = None
    if remote_only:
        from qualify_admission_cleanup import on_worker

        async def player(s):
            return s._companion.config.player_id
        host_player = await on_worker(current[0], player)
    simulate_internet(latency_ms, host_player=host_player, everything=everything, jitter_ms=jitter_ms,
                      stall_every=stall_every, stall_ms=stall_ms)
    simulate_disk(disk_ms)
    record("simulated-network", latency_ms=latency_ms, remote_only=remote_only, everything=everything,
           disk_ms=disk_ms, jitter_ms=jitter_ms, stall_every=stall_every, stall_ms=stall_ms)
