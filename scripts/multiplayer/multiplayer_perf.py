"""Measurements for the multiplayer lag report (2026-10-20): nothing in the games, launchers or host changes.

- game frames: each game's gMultiplayerMenuMailbox.frame goes up once per game frame (main.c calls
  MultiplayerMenu_Tick every frame); it is read through /proc every 4 ms, so a gap is a stall of the game process
  (drawing, CPU, a blocking call). gMultiplayerBattleHoldFlags says when the field is frozen on purpose.
- loops: every launcher's event loop (the host's also runs the world server) gets a 10 ms heartbeat; a late beat is a
  blocked loop, and one over 100 ms is recorded with the stack that blocked it.
- fsync: every os.fsync of the proof process (the launchers' journals run there), timed per thread.
- requests: each companion's battle, trade, team and checkpoint requests and native battle controls, timed end to
  end (the client latency); the host's battle, trade and checkpoint handlers, timed (the server's processing).
- CPU: user+system seconds of each game process and of the proof process (launchers, companions, host), per phase.

`PerfRecorder.mark(phase)` splits everything by phase; `summary()` gives counts, percentiles and maxima per phase.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import traceback
from collections import defaultdict

TICKS = os.sysconf("SC_CLK_TCK")


def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(fraction * len(ordered)))], 2)


def _cpu_seconds(pid):
    try:
        with open(f"/proc/{pid}/stat") as source:
            fields = source.read().rsplit(")", 1)[1].split()
        return (int(fields[11]) + int(fields[12])) / TICKS
    except (OSError, IndexError, ValueError):
        return None


class PerfRecorder:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.phase = "start"
        self.phases = []                       # (name, start monotonic)
        self.frames = defaultdict(list)        # (player, phase) -> frame intervals ms
        self.stalls = []                       # game frame gaps over 50 ms
        self.lags = []                         # late loop beats over 50 ms
        self.fsyncs = defaultdict(list)        # (thread, phase) -> ms
        self.requests = defaultdict(list)      # (player, operation, phase) -> ms
        self.handlers = defaultdict(list)      # (handler, phase) -> ms
        self.cpu = []                          # (phase, {process: seconds})
        self.processes = {"proof": os.getpid()}
        self.stopping = threading.Event()
        self._fsync = None

    # Phases ------------------------------------------------------------------------------------------------------
    def mark(self, phase):
        with self.lock:
            self.phase = phase
            self.phases.append((phase, time.monotonic()))
            self.cpu.append((phase, {name: _cpu_seconds(pid) for name, pid in self.processes.items()}))

    def _write(self, kind, **fields):
        with self.lock:
            fields.update(kind=kind, phase=self.phase, wall=time.strftime("%H:%M:%S"))
            with open(self.path, "a") as out:
                out.write(json.dumps(fields) + "\n")

    # Game frames -------------------------------------------------------------------------------------------------
    def watch_game(self, player, pid, symbols):
        frame_address = symbols["gMultiplayerMenuMailbox"][0] + 8
        hold_address = symbols["gMultiplayerBattleHoldFlags"][0]
        self.processes[player] = pid

        def sample():
            try:
                memory = open(f"/proc/{pid}/mem", "rb", buffering=0)
            except OSError:
                return
            last_frame, last_change = None, time.monotonic()
            with memory:
                while not self.stopping.is_set():
                    try:
                        memory.seek(frame_address)
                        frame = int.from_bytes(memory.read(4), "little")
                        memory.seek(hold_address)
                        hold = int.from_bytes(memory.read(4), "little")
                    except OSError:
                        return
                    now = time.monotonic()
                    if frame != last_frame:
                        if last_frame is not None:
                            gap = (now - last_change) * 1000 / max(1, (frame - last_frame) & 0xFFFFFFFF)
                            with self.lock:
                                self.frames[(player, self.phase)].append(gap)
                            if (now - last_change) * 1000 > 50:
                                self._write("game-stall", player=player, ms=round((now - last_change) * 1000, 1),
                                            frames=(frame - last_frame) & 0xFFFFFFFF, hold=hold)
                                with self.lock:
                                    self.stalls.append((player, self.phase, (now - last_change) * 1000, hold))
                        last_frame, last_change = frame, now
                    time.sleep(.004)
        threading.Thread(target=sample, name=f"perf-frames-{player}", daemon=True).start()

    # Event loops ---------------------------------------------------------------------------------------------------
    def watch_loop(self, player, loop, thread):
        beat = [time.monotonic()]

        async def heartbeat():
            while not self.stopping.is_set():
                expected = time.monotonic() + .01
                await asyncio.sleep(.01)
                late = (time.monotonic() - expected) * 1000
                beat[0] = time.monotonic()
                if late > 50:
                    with self.lock:
                        self.lags.append((player, self.phase, late))
        asyncio.run_coroutine_threadsafe(heartbeat(), loop)

        def watchdog():
            reported = None
            while thread.is_alive() and not self.stopping.is_set():
                time.sleep(.02)
                last = beat[0]
                if time.monotonic() - last > .1 and reported != last:
                    frame = sys._current_frames().get(thread.ident)
                    stack = traceback.format_stack(frame)[-12:] if frame is not None else []
                    self._write("loop-blocked", player=player, after_ms=round((time.monotonic() - last) * 1000),
                                stack=[line.strip() for line in stack])
                    reported = last
        threading.Thread(target=watchdog, name=f"perf-loop-{player}", daemon=True).start()

    # fsync -------------------------------------------------------------------------------------------------------
    def watch_fsync(self):
        if self._fsync is not None:
            return
        original = self._fsync = os.fsync

        def timed(fd):
            started = time.monotonic()
            try:
                return original(fd)
            finally:
                ms = (time.monotonic() - started) * 1000
                with self.lock:
                    self.fsyncs[(threading.current_thread().name, self.phase)].append(ms)
        os.fsync = timed

    # Requests ------------------------------------------------------------------------------------------------------
    def time_companion(self, player, companion):
        for name in ("battle_challenge_rpc", "trade_rpc", "team_rpc", "battle_rpc", "checkpoint_rpc"):
            method = getattr(companion, name, None)
            if method is None or getattr(method, "_perf_timed", False):
                continue

            def wrap(method, name):
                async def timed(*args, **kwargs):
                    started = time.monotonic()
                    try:
                        return await method(*args, **kwargs)
                    finally:
                        operation = name if not args or not isinstance(args[0], str) else f"{name}:{args[0]}"
                        with self.lock:
                            self.requests[(player, operation, self.phase)].append((time.monotonic() - started) * 1000)
                timed._perf_timed = True
                return timed
            setattr(companion, name, wrap(method, name))

    def time_server(self, server):
        for name in ("_battle", "_trade", "_checkpoint", "_team"):
            method = getattr(server, name, None)
            if method is None or getattr(method, "_perf_timed", False) or asyncio.iscoroutinefunction(method):
                continue

            def wrap(method, name):
                def timed(*args, **kwargs):
                    started = time.monotonic()
                    try:
                        return method(*args, **kwargs)
                    finally:
                        with self.lock:
                            self.handlers[(name, self.phase)].append((time.monotonic() - started) * 1000)
                timed._perf_timed = True
                return timed
            setattr(server, name, wrap(method, name))

    # The report ----------------------------------------------------------------------------------------------------
    def summary(self):
        self.mark("end")
        with self.lock:
            phases = [name for name, _ in self.phases if name != "end"]
            durations = {name: round(self.phases[i + 1][1] - start, 1) for i, (name, start) in enumerate(self.phases[:-1])}
            cpu = {}
            for (name, before), (_, after) in zip(self.cpu, self.cpu[1:]):
                cpu[name] = {process: (None if before.get(process) is None or after.get(process) is None
                                       else round(after[process] - before[process], 2)) for process in before}
            report = {}
            for phase in phases:
                frames = {player: dict(frames=len(v), p50=_percentile(v, .5), p99=_percentile(v, .99),
                                       max=round(max(v), 1) if v else None)
                          for (player, p), v in self.frames.items() if p == phase}
                stalls = [dict(player=pl, ms=round(ms, 1), hold=hold) for pl, p, ms, hold in self.stalls if p == phase]
                lags = defaultdict(list)
                for player, p, late in self.lags:
                    if p == phase:
                        lags[player].append(late)
                fsync = {thread: dict(count=len(v), total_ms=round(sum(v), 1), max_ms=round(max(v), 1))
                         for (thread, p), v in self.fsyncs.items() if p == phase}
                requests = {f"{player} {operation}": dict(count=len(v), p50=_percentile(v, .5), max=round(max(v), 1))
                            for (player, operation, p), v in self.requests.items() if p == phase}
                handlers = {name: dict(count=len(v), p50=_percentile(v, .5), max=round(max(v), 1))
                            for (name, p), v in self.handlers.items() if p == phase}
                report[phase] = dict(
                    seconds=durations.get(phase), cpu_seconds=cpu.get(phase), game_frames=frames,
                    game_stalls_over_50ms=dict(count=len(stalls), held=sum(1 for s in stalls if s["hold"]),
                                               worst=sorted(stalls, key=lambda s: -s["ms"])[:5]),
                    loop_lag_over_50ms={player: dict(count=len(v), max_ms=round(max(v), 1)) for player, v in lags.items()},
                    fsync=fsync, requests=requests, server_handlers=handlers)
        return report

    def stop(self):
        self.stopping.set()
        if self._fsync is not None:
            os.fsync = self._fsync
