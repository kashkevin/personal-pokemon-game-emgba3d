"""KNOWN_ISSUES MS-62: a launcher reports its battle core's state and each new block to the host as they happen.

Battles over the internet were far too slow: the host learned of a core's new block only by asking for it (QUERY) and
then reading it (READ_OUT), two round trips over the network for every block, before it could route it. With the PC
game's battle PEEK (opcode 25: QUERY plus the outbound block's bytes, changing nothing) the launcher looks at its own
core every few milliseconds while it holds no host command, and sends what changed to the host at once (the "observe"
battle operation; the host's observed router, battle_execution._NativeRoute.run_observed). The host takes a report only
while it has no command outstanding for this core and says so; one it did not take is sent again (soon after this
launcher's next command, else at most every RESEND_SECONDS).

The executing session holds `lock` around every command it runs, so a PEEK never interleaves with one, and calls
`holding` when the host hands it a command and `executed` once that command ran.
"""
from __future__ import annotations

import asyncio

from .battle_execution_protocol import encode_control
from .native_battle import NativeControl, Opcode, ordinary_route, peek_parts
from .protocol import ProtocolError

OBSERVE_SECONDS = .004
RESEND_SECONDS = .25
# battle_execution.KEEP_OBSERVED_FRAMES: the host sends KEEP when a report says fewer frames are left.
KEEP_FRAMES = 240


class BattleObserver:
    def __init__(self, companion, battle_id, generation, incarnation, slot, phase):
        self.companion = companion
        self.battle_id, self.generation, self.incarnation = battle_id, generation, incarnation
        self.slot, self.phase = slot, phase
        self.lock = asyncio.Lock()
        self.command = None   # a host command this launcher holds and has not answered yet
        self.base = None      # (lease, sequence) of the core's last accepted mutating command
        self.accepted = self.sent = None
        self.sent_at = 0.0
        self.stopped = False
        self.task = None

    @staticmethod
    def enabled(companion):
        return getattr(companion.config, "battle_peek_abi_version", 0) == 1

    def holding(self, command):
        self.command = command

    def executed(self, command, response):
        # Only an ordinary command moves the core's sequence (suspension and renewal are out of band).
        ordinary = not response.status and command.opcode not in (Opcode.QUERY, Opcode.PEEK) and ordinary_route(command.opcode)
        if ordinary:
            self.base = (command.session_epoch, command.sequence)
            if command.opcode == Opcode.RELEASE:
                self.stopped = True   # the core is released; nothing more to report
        self.sent = None   # a report the host refused while it waited for this command goes again at once
        self.command = None
        # From the first accepted command after BIND (a fresh core is prepared then; a recovered one already runs).
        if self.task is None and not self.stopped and ordinary and command.opcode != Opcode.BIND:
            self.task = asyncio.create_task(self._run(), name="native-battle-observer")

    async def stop(self):
        self.stopped = True
        task, self.task = self.task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _key(self, query):
        return (query.flags, query.outbound_sequence, query.outbound_kind, query.outbound_size, query.read_offset,
                query.outcome, query.remaining_frames < KEEP_FRAMES)

    async def _run(self):
        c, loop = self.companion, asyncio.get_running_loop()
        while not self.stopped:
            await asyncio.sleep(OBSERVE_SECONDS)
            if self.command is not None or self.base is None:
                continue
            async with self.lock:
                if self.command is not None or self.stopped:
                    continue
                lease, sequence = self.base
                peek = NativeControl(self.incarnation, lease, self.battle_id, sequence + 1, Opcode.PEEK,
                                     source_slot=self.slot, phase=self.phase)
                try:
                    response = await c.battle_rpc(peek)
                    response.validate_response(peek)
                except (ValueError, ConnectionError, OSError, asyncio.TimeoutError):
                    continue
            if response.status:
                continue
            try:
                query, _ = peek_parts(response)
            except ValueError:
                continue
            key = self._key(query)
            if key == self.accepted or (key == self.sent and loop.time() - self.sent_at < RESEND_SECONDS):
                continue
            self.sent, self.sent_at = key, loop.time()
            try:
                view = (await c.battle_challenge_rpc("observe", battle_id=self.battle_id, generation=self.generation,
                    incarnation=self.incarnation, observation_b64=encode_control(response)))["result"]
            except (ProtocolError, ConnectionError, OSError, ValueError, asyncio.TimeoutError):
                continue
            if view["accepted"]:
                self.accepted = key
