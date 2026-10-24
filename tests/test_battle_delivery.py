"""KNOWN_ISSUES MS-62, battle speed: the delivering router (journal v6) on a synthetic controller exchange.

The network tests (test_battle_execution.py) run the routers over each core's startup blocks only. Here every core also
plays a short battle after them, as the games' link battles do: the master (slot 0) sends a script of commands; every
core renders each command it takes (the master its own too) for a few frames, the owner of a battler answers a choice
before its DONE, and the master starts a step only once every core's DONE of the last one is in; the end command's DONEs
end the battle and every core restores. Each core has one outbound block at a time (the next goes once it is
acknowledged) and one receive slot per other core, emptied into its link buffer a frame later (at once by a DELIVER that
needs it, as the PC game does). The same battles run on the observed router (journal v5) for comparison.

What it shows: the battle ends on both routers; on the delivering one a slave core takes fewer commands, blocks from one
core travel together and acknowledgements ride with deliveries; every core receives the blocks in one global order; no
core ever needed the liveness rule (its deadline running low) to get a held-back block. Synthetic: not a game, not a
network, no timing claims.
"""
import struct
from unittest.mock import patch
from uuid import UUID
import zlib

from emerald_multiplayer import battle_execution
from emerald_multiplayer.battle_mailbox import Status
from emerald_multiplayer.native_battle import Opcode, battler_owner, deliver_entries, receive_many_entries
import test_battle_execution as execution
from test_battle_execution import NativeFixture

PLAYSE, CHOOSE, END = 38, 17, 50


def wire(payload, *, role=0, battler=0):
    padded = len(payload) - len(payload) % 4 + 4
    return struct.pack("<BBBBHBB", role, battler, 0, 1, padded, 0, 0) + payload + bytes(padded - len(payload))


def command(battler, command_id):
    return wire(bytes((END, 1, 0, 0, 0, 0)) if command_id == END else bytes((command_id, 1 if command_id == PLAYSE else 0, 0, 0)),
                battler=battler)


def reply(battler):
    return wire(bytes((32, 0, 0, 0, 0, 0)), role=1, battler=battler)


def done(source, battler):
    return wire(bytes((source, 0, 0, 0)), role=2, battler=battler)


class ScriptFixture(NativeFixture):
    ANIMATION = 3       # frames a core renders a command for
    SCRIPT = ()         # the master's steps: each a tuple of (battler, command) sent together

    def __init__(self, battle, slot):
        super().__init__(battle, slot)
        self.count = len(battle.players)
        self.sendq = []          # blocks waiting for the outbound slot (the game's send buffer)
        self.slots = {}          # source -> (block sequence, bytes) received, not yet in the link buffer
        self.linkbuf = []        # (source, block sequence, bytes) in the link buffer, in order
        self.rendering = []      # [frames left, battler, command] this core renders
        self.order = []          # (source, block sequence) of other cores' controller blocks, as taken
        self.startup_done = False
        self.step = -1           # the master: the step in progress
        self.done_from = {}      # battler -> cores whose DONE of the step is in (the master)
        self.end_seen = False
        self.end_done = set()    # cores whose DONE of the end command this core has
        self.lowest = 600        # the lowest deadline seen while the battle ran (the liveness rule never needed)

    # ---- the game's frame
    def frame(self):
        if self.started and not self.startup_done and self.out_index >= 6 and all(
                self.received.get(p, (0, 0))[0] >= 6 for p in range(self.count) if p != self.slot):
            self.startup_done = True
            if self.slot == 0:
                self.next_step()
        self.drain()
        for source, sequence, data in self.linkbuf:
            self.take(source, sequence, data)
        self.linkbuf = []
        for item in list(self.rendering):
            item[0] -= 1
            if item[0] <= 0:
                self.rendering.remove(item)
                _, battler, command_id = item
                if command_id == CHOOSE and battler_owner(self.battle.mode, battler) == self.slot:
                    self.sendq.append(reply(battler))
                self.sendq.append(done(self.slot, battler))
        if self.startup_done and self.out_index == len(self.blocks) and self.sendq:
            block = self.sendq.pop(0)
            self.blocks.append(block)                       # the outbound block (SendBlock) ...
            self.linkbuf.append((self.slot, len(self.blocks), block))   # ... which reception includes (the sender's own)
        if self.startup_done and not self.end_seen:
            self.lowest = min(self.lowest, 600 - self.frames_used)

    def drain(self):
        for source in sorted(self.slots):
            sequence, data = self.slots.pop(source)
            self.linkbuf.append((source, sequence, data))

    def take(self, source, sequence, data):
        role, battler = data[0], data[1]
        if source != self.slot:
            self.order.append((source, sequence))
        if role == 0:
            self.rendering.append([self.ANIMATION, battler, data[8]])
            if data[8] == END:
                self.end_seen = True
        elif role == 2:
            if self.end_seen and battler == 0:
                self.end_done.add(source)
            if self.slot == 0:
                self.done_from.setdefault(battler, set()).add(source)
                step = self.SCRIPT[self.step]
                if all(len(self.done_from.get(b, ())) == self.count for b, _ in step):
                    self.next_step()

    def next_step(self):
        self.step += 1
        self.done_from = {}
        if self.step < len(self.SCRIPT):
            for battler, command_id in self.SCRIPT[self.step]:
                self.sendq.append(command(battler, command_id))

    def restored_now(self):
        return (self.end_seen and len(self.end_done) == self.count and not self.sendq and not self.slots
                and not self.linkbuf and not self.rendering and self.out_index == len(self.blocks))

    def query(self):
        outbound = self.prepared and self.out_index < len(self.blocks) and not (self.started and self.idle_left)
        restored = self.started and self.restored_now()
        flags = (0 if self.released else 1) | (8 if self.prepared and not self.released else 0)
        flags |= 16 if self.started and not self.released else 0
        flags |= 32 if restored and not self.released else 0
        flags |= 4 if outbound else 0
        flags |= 2 if self.frames_used >= 600 + self.GRACE and not self.released else 0
        data = self.blocks[self.out_index] if outbound else b""
        return struct.pack("<I16sBBBB10I", flags, UUID(self.battle.generation).bytes,
            len(self.battle.players), self.slot, self.battle.mode, 0,
            self.sequence, self.out_index + 1 if outbound else 0, min(8, self.out_index + 2) if outbound else 0,
            len(data), zlib.crc32(data) if data else 0, self.offset if outbound else 0, 0,
            max(0, 600 - self.frames_used) if not self.released else 0,
            self.battle.roster[self.slot].revision if self.prepared and not self.released else 0,
            2 if restored and not self.released else 0)

    # ---- the mailbox
    async def rpc(self, command):
        self.frame()
        if command.opcode not in (Opcode.RECEIVE, Opcode.RECEIVE_MANY, Opcode.DELIVER):
            return await super().rpc(command)
        command.validate_command()
        if command.sequence != self.sequence + 1:
            raise AssertionError("native mutation sequence changed")
        if command.opcode == Opcode.RECEIVE:
            parts = [(command.source_slot, command.block_sequence, command.offset, command.data)]
        elif command.opcode == Opcode.RECEIVE_MANY:
            parts = [(s, q, 0, d) for s, _, q, d in receive_many_entries(command.data, self.count, self.slot)]
        else:
            parts = [(s, q, 0, d) for s, _, q, d in deliver_entries(command.data, self.count, self.slot,
                                                                  ack=bool(command.block_sequence))]
        acknowledged = applied = 0
        if command.opcode == Opcode.DELIVER and command.block_sequence:
            if command.block_sequence != self.out_index + 1 or self.offset not in (0, len(self.blocks[self.out_index])):
                raise AssertionError("acknowledged another or a partly read outbound block")
            self.out_index += 1
            self.offset = 0
            acknowledged = 1
        for source, sequence, offset, data in parts:
            if sequence > 6:                         # a controller block: one receive slot for each other core
                if source in self.slots and command.opcode == Opcode.DELIVER:
                    self.drain()                     # the PC game's DELIVER empties a full slot first
                if source in self.slots:
                    break                            # busy until the game takes the last one
                if sequence != self.received.get(source, (0, 0))[0] + 1:
                    raise AssertionError("a core's blocks out of its order")
                self.slots[source] = (sequence, data)
                if command.opcode == Opcode.DELIVER:
                    self.drain()                     # each battle block into the link buffer at once, in its order
            self.received[source] = (sequence, offset + len(data))
            applied += 1
        if not applied and not acknowledged:
            return command.__class__(**{**command.__dict__, "status": Status.BUSY, "data": b""})
        self.sequence += 1
        if self.frames_used < 600 + self.GRACE:
            self.frames_used = 0
        if command.opcode == Opcode.DELIVER:
            self.delivers += 1
            data = bytes((acknowledged, applied, Status.OK if applied == len(parts) else Status.BUSY))
        elif command.opcode == Opcode.RECEIVE_MANY:
            self.many += 1
            data = bytes((applied, Status.OK if applied == len(parts) else Status.BUSY))
        else:
            data = b""
        return command.__class__(**{**command.__dict__, "data": data})


SINGLES = (((0, PLAYSE),), ((1, PLAYSE),), ((1, CHOOSE),), ((0, CHOOSE),), ((0, PLAYSE), (1, PLAYSE)),
           ((1, CHOOSE), (0, CHOOSE)), ((0, PLAYSE),), ((0, END),))
MULTI = tuple(((b, PLAYSE),) for b in range(4)) + (((1, CHOOSE), (2, CHOOSE)), ((3, CHOOSE),), ((0, CHOOSE),),
                                                   tuple((b, PLAYSE) for b in range(4)), ((0, END),))


class ObservedScriptTests(execution.BattleExecutionNetworkTests):
    """The scripted battles on the observed router (journal v5): the reference."""
    peek = receive_many = True
    fixture = ScriptFixture

    async def battle(self, multi):
        commands = []
        original = ScriptFixture.rpc

        async def counted(model, command):
            if command.opcode not in (Opcode.PEEK, Opcode.QUERY):
                commands.append((model.slot, command))
            return await original(model, command)
        with patch.object(ScriptFixture, "SCRIPT", MULTI if multi else SINGLES), patch.object(ScriptFixture, "rpc", counted):
            await self.run_clients(multi=multi, use_journal=True)
        models = sorted(self.native_models.values(), key=lambda model: model.slot)
        for model in models:
            self.assertTrue(model.end_seen and model.restored_now() and model.released)
        # One global order: any two cores took the blocks both received in the same order.
        for a in models:
            for b in models:
                common = [block for block in a.order if block[0] not in (a.slot, b.slot)]
                self.assertEqual(common, [block for block in b.order if block[0] not in (a.slot, b.slot)])
        steps = len(MULTI if multi else SINGLES)
        self.assertEqual(models[0].step, steps)
        return models, commands

    async def test_singles(self):
        await self.battle(False)

    async def test_multi(self):
        await self.battle(True)

    # Everything else of the network tests runs in test_battle_execution.py; these battles are the point here.
    for _name in dir(execution.BattleExecutionNetworkTests):
        if _name.startswith("test_"):
            locals()[_name] = None
    del _name


class DeliverScriptTests(ObservedScriptTests):
    """The scripted battles on the delivering router (journal v6)."""
    deliver = True

    async def compare(self, multi):
        import asyncio
        with patch.object(self, "deliver", False):
            _, observed = await self.battle(multi)
        self.battle_id = None
        await self.asyncTearDown()
        await self.asyncSetUp()
        # Without the liveness rule (a core whose deadline runs low gets everything held back for it): the battle must
        # end anyway, so no held-back block or acknowledgement was ever needed before the command that carried it.
        with patch.object(battle_execution._NativeRoute, "_liveness", lambda route, slot: False):
            async with asyncio.timeout(600):
                models, delivered = await self.battle(multi)
        self.assertTrue(self.server.battle_execution.rooms[self.battle_id].route.deliver)
        self.assertFalse([c for _, c in delivered if c.opcode in (Opcode.ACK_OUT, Opcode.RECEIVE_MANY)])
        for slot in range(1, len(models)):
            slave = lambda cs: sum(1 for s, _ in cs if s == slot)
            self.assertLess(slave(delivered), slave(observed), f"slot {slot}")
        deliveries = [(s, c) for s, c in delivered if c.opcode == Opcode.DELIVER]
        entries = [(s, c, deliver_entries(c.data, len(models), c.source_slot, ack=bool(c.block_sequence)))
                   for s, c in deliveries]
        # A slave took the master's held-back blocks with its next command (several from one core in one command),
        # and acknowledgements rode with deliveries.
        self.assertTrue(any(s and len([e for e in es if e[0] == 0]) > 1 for s, _, es in entries))
        self.assertTrue(any(c.block_sequence and es for _, c, es in entries))
        return observed, delivered

    async def test_singles(self):
        await self.compare(False)

    async def test_multi(self):
        await self.compare(True)

    async def test_a_held_back_block_still_reaches_a_core_whose_deadline_runs_low(self):
        # The liveness rule: if a slave would wait for held-back blocks with no command coming (here the master never
        # sends another step: the script stops early and the battle cannot end), the slave's report of its deadline
        # running low makes the route hand it everything it is owed instead of a KEEP.
        import asyncio
        script = SINGLES[:3]
        with patch.object(ScriptFixture, "SCRIPT", script):
            task = asyncio.create_task(self.run_clients(use_journal=True))
            try:
                async with asyncio.timeout(240):
                    while True:
                        await asyncio.sleep(.1)
                        models = sorted(getattr(self, "native_models", {}).values(), key=lambda model: model.slot)
                        if len(models) == 2 and models[0].step == len(script):
                            master = [(0, n + 1) for n in range(6, len(models[0].blocks))]
                            if [b for b in models[1].order if b[0] == 0] == master and models[0].out_index == len(
                                    models[0].blocks):
                                break
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        # The master's last DONE reached the slave although no command followed it, once the slave's deadline ran low.
        self.assertLess(models[1].lowest, battle_execution.KEEP_OBSERVED_FRAMES)


class DeliverJournalTests(execution.unittest.TestCase):
    """The route journal's v6 (the delivering router): DELIVER commands and observations taken while a command to the
    same core is outstanding; the observed router's journals (v4, v5) still refuse both."""

    def journal(self, format):
        import tempfile
        from pathlib import Path
        from uuid import uuid4
        from emerald_multiplayer.battle_execution_journal import RouteJournal
        self.players = [str(uuid4()), str(uuid4())]
        self.battle, self.generation = str(uuid4()), str(uuid4())
        header = dict(record={}, battle_id=self.battle, generation=self.generation, players=self.players,
                      leases=[3, 4], incarnations=[7, 8], mode=2, initial_sequences=[0, 0])
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return RouteJournal(Path(directory.name) / "battle.events.jsonl", header, create=True, format=format)

    def control(self, slot, opcode, sequence, **fields):
        from emerald_multiplayer.native_battle import NativeControl
        return NativeControl((7, 8)[slot], (3, 4)[slot], self.battle, sequence, opcode, source_slot=slot, **fields)

    def peek(self, slot, sequence):
        query = struct.pack("<I16sBBBB10I", 1 | 8 | 16, UUID(self.generation).bytes, 2, slot, 2, 0,
                            sequence, 0, 0, 0, 0, 0, 0, 400, 1, 0)
        return self.control(slot, Opcode.PEEK, sequence + 1, data=query)

    def test_v6_takes_deliveries_and_observations_while_a_command_is_outstanding(self):
        from emerald_multiplayer.battle_execution_journal import DELIVER_FORMAT, MANY_FORMAT, OBSERVED_FORMAT
        from emerald_multiplayer.native_battle import pack_deliver
        journal = self.journal(DELIVER_FORMAT)
        deliver = self.control(1, Opcode.DELIVER, 6, data=pack_deliver(((0, 8, 7, bytes(range(16))),)))
        journal.append("command", self.players[1], 1, deliver)
        journal.observe(self.players[1], self.peek(1, 5))        # outstanding DELIVER: v6 takes it
        journal.append("response", self.players[1], 1, self.control(1, Opcode.DELIVER, 6,
            data=pack_deliver(((0, 8, 7, bytes(range(16))),))).__class__(**{**deliver.__dict__, "data": bytes((0, 1, 0))}))
        self.assertTrue(journal.deliver and journal.observed and not journal.receive_many)
        self.assertEqual([event[0] for event in journal.routed], ["observation", "response"])
        for format in (OBSERVED_FORMAT, MANY_FORMAT):
            older = self.journal(format)
            with self.assertRaises(ValueError):
                older.append("command", self.players[1], 1, deliver)
            older.append("command", self.players[1], 1, self.control(1, Opcode.KEEP, 6))
            with self.assertRaises(ValueError):
                older.observe(self.players[1], self.peek(1, 5))
