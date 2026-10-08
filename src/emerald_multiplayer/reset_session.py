"""One bound native pre-generation admission, with idempotent timed retries."""
import asyncio
from uuid import uuid4
from .reset_mailbox import ResetRequest, ResetReceipt
from .protocol import ProtocolError


class ResetSession:
    def __init__(self, companion, bridge):
        self.companion, self.bridge = companion, bridge
        self.sequence = 0
        self.task = None
        self.closed = False
        self.draining = False
        self.request = self.receipt = None
        self.receipt_changed = asyncio.Event()

    def feed(self, payload):
        request = ResetRequest.unpack(payload)
        if (self.closed or self.draining or request.sequence <= self.sequence or request.session != self.companion.session_epoch
                or request.incarnation != self.bridge.incarnation or not self.companion.connected
                or self.companion._bridge is not self.bridge or (self.task is not None and not self.task.done())):
            raise ValueError("personal encounter request is stale, overlapping or foreign")
        self.sequence = request.sequence
        self.request, self.receipt = request, None
        self.task = asyncio.create_task(self._admit(request), name="native-personal-attempt")

    def _same(self, request):
        return (not self.closed and not self.draining and self.companion.connected and self.companion._bridge is self.bridge
                and self.companion.session_epoch == request.session and self.bridge.incarnation == request.incarnation)

    async def _admit(self, request):
        identity = str(uuid4())
        try:
            # One authority owner prevents a checkpoint/trade dispatch from
            # interleaving the native admission and its host receipt.
            async with self.companion.live_checkpoint_lock:
                self.companion._guard_pending_trade_mutation()
                for _ in range(3):
                    if not self._same(request):
                        return
                    try:
                        reply = await self.companion.reset_rpc(request_id=identity,
                            encounter_id=request.encounter, incarnation=request.incarnation,
                            sequence=request.sequence, observed_count=request.observed_count)
                    except asyncio.TimeoutError:
                        continue  # Same request ID, never another attempt.
                    if self._same(request):
                        self.bridge.outbox.put_control(b"U" + request.reply(reply["result"]["attempt"]))
                    return
        except ProtocolError:
            if self._same(request):
                self.bridge.outbox.put_control(b"U" + request.reply(0, denied=True))
        except (ValueError, ConnectionError, OSError):
            # Unknown transport/store outcome stays stopped; never manufacture
            # an ACK, save, ordinary encounter, or local counter rollback.
            return

    async def close(self):
        self.closed = True
        self.receipt_changed.set()
        if self.task is not None:
            await asyncio.gather(self.task, return_exceptions=True)

    def observe(self, payload):
        if self.companion.config.reset_abi_version != 2:
            raise ValueError("native cancellation receipts require reset ABI2")
        receipt = ResetReceipt.unpack(payload)
        if self.closed or self.request is None or not receipt.matches(self.request):
            raise ValueError("personal encounter receipt names a different request")
        previous = self.receipt
        if previous is not None:
            if previous.state != 1 and receipt.state != previous.state:
                raise ValueError("personal encounter terminal receipt changed")
            if previous.attempt != receipt.attempt and previous.state != 1:
                raise ValueError("personal encounter receipt changed its count")
        self.receipt = receipt
        self.receipt_changed.set()

    async def drain_before_emergency(self, retained_session, *, timeout=2.5):
        """Neutralize only this retained pre-generation script before freezing.

        The emergency controller owns live_checkpoint_lock. This callback never
        acquires it or awaits an admission task that may be waiting for it.
        False means the caller must still execute the native emergency hold.
        """
        c, bridge = self.companion, self.bridge
        if (c.connected or not c._reconnect_blocked or c._bridge is not bridge
                or getattr(c, "_live_binding", None) != retained_session
                or c._live_save_owner is not asyncio.current_task()
                or not c.live_checkpoint_lock.locked()):
            return False
        self.draining = True
        request = self.request
        if request is None:
            return True
        if ((request.session, request.incarnation) != retained_session[1:3]
                or c.config.reset_abi_version != 2 or self.closed):
            return False
        deadline = asyncio.get_running_loop().time() + timeout
        while (not self.closed and c._bridge is bridge and not c.connected
               and getattr(c, "_live_binding", None) == retained_session):
            self.receipt_changed.clear()
            receipt = self.receipt
            if receipt is not None:
                if receipt.state == 2:
                    return False  # An ACK already released generation: never undo it.
                if receipt.state in (3, 4) and receipt.field_ready:
                    return True
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            try:
                bridge.outbox.put_control(b"U" + request.cancel())
                await asyncio.wait_for(self.receipt_changed.wait(), min(1.0, remaining))
            except asyncio.TimeoutError:
                continue
            except Exception:
                return False
        return False
