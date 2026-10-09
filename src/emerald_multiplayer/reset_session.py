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
        self.request_id = None
        self.authority = None
        self.host_attempt = None
        self.phase = "idle"
        self.error_code = None
        self.receipt_changed = asyncio.Event()

    def feed(self, payload):
        request = ResetRequest.unpack(payload)
        if (self.closed or self.draining or request.sequence <= self.sequence or request.session != self.companion.session_epoch
                or request.incarnation != self.bridge.incarnation or not self.companion.connected
                or self.companion._bridge is not self.bridge or (self.task is not None and not self.task.done())):
            raise ValueError("personal encounter request is stale, overlapping or foreign")
        self.sequence = request.sequence
        self.request, self.receipt = request, None
        self.request_id, self.host_attempt = str(uuid4()), None
        self.authority = (getattr(self.companion, "world_id", None), getattr(self.companion, "server_epoch", None))
        self.phase, self.error_code = "queued", None
        self.task = asyncio.create_task(self._admit(request), name="native-personal-attempt")

    def _same(self, request):
        return (request is self.request and not self.closed and not self.draining
                and self.companion.connected and self.companion._bridge is self.bridge
                and self.companion.session_epoch == request.session and self.bridge.incarnation == request.incarnation
                and self.authority == (getattr(self.companion, "world_id", None), getattr(self.companion, "server_epoch", None)))

    async def _admit(self, request):
        # Retained for the lifetime of this exact native request. A user retry
        # after lost host replies must not mint a second ledger identity.
        identity = self.request_id
        try:
            # One authority owner prevents a checkpoint/trade dispatch from
            # interleaving the native admission and its host receipt.
            async with self.companion.live_checkpoint_lock:
                self.companion._guard_pending_trade_mutation()
                if (getattr(self.companion, "_live_battle_owner", None) is not None
                        or (self.companion._live_save_owner is not None
                            and self.companion._live_save_owner is not asyncio.current_task())):
                    raise ValueError("another operation owns the live character")
                self.phase, self.error_code = "requesting", None
                for _ in range(3):
                    if not self._same(request) or (self.receipt is not None and self.receipt.state != 1):
                        return
                    try:
                        reply = await self.companion.reset_rpc(request_id=identity,
                            encounter_id=request.encounter, incarnation=request.incarnation,
                            sequence=request.sequence, observed_count=request.observed_count)
                    except asyncio.TimeoutError:
                        continue  # Same request ID, never another attempt.
                    attempt = reply["result"]["attempt"]
                    if self.host_attempt is not None and attempt != self.host_attempt:
                        raise ValueError("same personal admission changed its host receipt")
                    self.host_attempt = attempt
                    if self._same(request) and (self.receipt is None or self.receipt.state == 1):
                        self.bridge.outbox.put_control(b"U" + request.reply(reply["result"]["attempt"]))
                        self.phase = "awaiting_native"
                    return
                self.phase, self.error_code = "retry_wait", "host_reply_timeout"
        except ProtocolError as error:
            self.phase, self.error_code = "denied", error.code
            if self._same(request) and (self.receipt is None or self.receipt.state == 1):
                self.bridge.outbox.put_control(b"U" + request.reply(0, denied=True))
        except (ValueError, ConnectionError, OSError) as error:
            self.phase = "blocked" if isinstance(error, ValueError) else "retry_wait"
            self.error_code = "local_authority_blocked" if isinstance(error, ValueError) else "transport_unknown"
            # Unknown transport/store outcome stays stopped; never manufacture
            # an ACK, save, ordinary encounter, or local counter rollback.
            return

    def can_retry(self):
        request, receipt, c = self.request, self.receipt, self.companion
        if (request is None or receipt is None or receipt.state != 1 or not self._same(request)
                or c.config.reset_abi_version != 2 or self.phase == "denied"
                or (self.task is not None and not self.task.done())
                or c.live_checkpoint_lock.locked() or c._live_save_owner is not None
                or getattr(c, "_live_battle_owner", None) is not None):
            return False
        try:
            c._guard_pending_trade_mutation()
        except ValueError:
            return False
        return True

    async def retry(self):
        if not self.can_retry():
            raise ValueError("only the same connected, idle, waiting personal admission can be retried")
        self.phase, self.error_code = "queued", None
        self.task = asyncio.create_task(self._admit(self.request), name="retry-native-personal-attempt")
        # Canceling a UI request must not cancel its authority owner after send.
        await asyncio.shield(self.task)
        return reset_status(self.companion)

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
        if receipt.state == 2 and self.host_attempt is not None and receipt.attempt != self.host_attempt:
            raise ValueError("native personal receipt differs from its host admission")
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
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        next_cancel_at = loop.time()
        while (not self.closed and c._bridge is bridge and not c.connected
               and getattr(c, "_live_binding", None) == retained_session):
            self.receipt_changed.clear()
            receipt = self.receipt
            if receipt is not None:
                if receipt.state == 2:
                    return False  # An ACK already released generation: never undo it.
                if receipt.state in (3, 4) and receipt.field_ready:
                    return True
            now = loop.time()
            remaining = deadline - now
            if remaining <= 0:
                return False
            try:
                # A cancellation receipt may precede the authored script's
                # safe field return. Repeated interim receipts must not turn
                # retries into a tight loop that floods the reliable outbox
                # or starves the very native return we are waiting for.
                if now >= next_cancel_at:
                    bridge.outbox.put_control(b"U" + request.cancel())
                    next_cancel_at = now + 1.0
                await asyncio.wait_for(self.receipt_changed.wait(),
                                       min(next_cancel_at - now, remaining))
            except asyncio.TimeoutError:
                continue
            except Exception:
                return False
        return False


def reset_status(companion):
    """Observe only; never starts a native request or claims a generated outcome."""
    from .reset_protocol import SOURCES
    bridge = getattr(companion, "_bridge", None)
    session = getattr(bridge, "reset_session", None)
    result = dict(state="unavailable", encounter_id=None, source_name=None, request_id=None,
        observed_count=None, host_attempt=None, native_attempt=None, field_ready=None,
        can_retry=False, error_code=None)
    if session is None:
        return result
    request, receipt = session.request, session.receipt
    state = session.phase
    if request is not None:
        result.update(encounter_id=request.encounter, source_name=SOURCES[request.encounter],
            request_id=session.request_id, observed_count=request.observed_count,
            host_attempt=session.host_attempt)
        if receipt is not None:
            state = {1: state, 2: "generation_released", 3: "denied", 4: "cancelled"}[receipt.state]
            result.update(native_attempt=receipt.attempt if receipt.state == 2 else None,
                          field_ready=receipt.field_ready)
        if not session._same(request):
            state = "retained"
    result.update(state=state, can_retry=session.can_retry(), error_code=session.error_code)
    return result


async def retry_reset_admission(companion):
    bridge = getattr(companion, "_bridge", None)
    session = getattr(bridge, "reset_session", None)
    if session is None:
        raise ValueError("no retained personal admission is available")
    return await session.retry()
