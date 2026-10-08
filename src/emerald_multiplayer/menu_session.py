"""One bounded native menu session on one authenticated bridge incarnation."""
import asyncio

from .bridge_protocol import BridgeError
from .menu_mailbox import MenuRequest, pack_screen
from .player_menu import MenuScreen, PlayerMenu


class MenuSession:
    def __init__(self, companion, bridge):
        self.companion, self.bridge = companion, bridge
        self.menu = PlayerMenu(companion)
        self.sequence = 0
        self.open = False
        self._task = None
        self._closed = False
        self._queued_open = None
        self._last_request = None
        self._poll_task = asyncio.create_task(self._poll(), name="native-players-status")
        self._cleanup_task = None
        self._close_waiter = None
        self._dialog_queue = None

    def feed(self, payload):
        request = MenuRequest.unpack(payload)
        if self._closed or request.sequence <= self.sequence:
            raise ValueError("native menu request was repeated or regressed")
        self.sequence = request.sequence
        self._last_request = request
        if self._dialog_queue is not None:
            if request.kind == 3:
                self.open = False
                if self._close_waiter is not None and not self._close_waiter.done():
                    self._close_waiter.set_result(request)
            elif request.kind == 1:
                self.open = True
            elif not self.open:
                raise ValueError("trade menu choice has no open session")
            try:
                self._dialog_queue.put_nowait(request)
            except asyncio.QueueFull:
                raise ValueError("native trade menu issued overlapping requests") from None
            return
        if request.kind == 3:
            self.open = False
            self._queued_open = None
            if self._close_waiter is not None and not self._close_waiter.done():
                self._close_waiter.set_result(request)
            return
        if request.kind == 1:
            self.open = True
        elif not self.open:
            raise ValueError("native menu choice has no open session")
        if self._task is not None and not self._task.done():
            if request.kind != 1:
                raise ValueError("native menu cannot issue overlapping choices")
            self._queued_open = request
            return
        self._task = asyncio.create_task(self._handle(request), name="native-players-menu")

    def _send(self, request, screen, *, close=False):
        if (not self._closed and self.open and request.sequence == self.sequence
                and self.companion._bridge is self.bridge):
            try:
                self.bridge.outbox.put_control(b"M" + pack_screen(request.sequence, screen, close=close))
            except BridgeError:
                self.open = False
                self.bridge.writer.close()

    async def _handle(self, request):
        try:
            while request is not None:
                try:
                    if request.kind == 1:
                        screen = await self.menu.refresh()
                    else:
                        screen = await self.menu.choose(request.screen, request.action)
                    handoff = getattr(self.menu, "handoff", None)
                    if handoff is None:
                        self._send(request, screen)
                    else:
                        # Consumption precedes all awaits. Neither a delayed
                        # CLOSE nor a reconnect may repeat this user action.
                        self.menu.handoff = None
                        await self.close_for_handoff(request, screen)
                        callback = getattr(self.companion, "_native_menu_handoff", None)
                        if callback is None:
                            raise ConnectionError("native operation owner is unavailable")
                        await callback(*handoff, self)
                except (ValueError, ConnectionError, OSError, asyncio.TimeoutError):
                    # A lost reply does not authorize replay, rollback, consent
                    # or battle settlement. Close locally, then reopen to query.
                    revision = max(1, self.menu.screen.revision)
                    self._send(request, MenuScreen(revision, "Players", "Reopen to check server status", (), 0), close=True)
                request, self._queued_open = self._queued_open, None
        except Exception:
            # A failed UI cannot leave an unobserved task exception or close the
            # authoritative save/battle channel on an unrelated rendering bug.
            self.open = False
            self.bridge.writer.close()

    async def close_for_handoff(self, request, screen, *, timeout=5):
        """Wait for the native window to relinquish its field ownership.

        Sending CLOSE is not acknowledgment. Only a newer request from this
        very bridge may cross the barrier. Failure never starts the operation.
        """
        if (self._closed or not self.open or request.sequence != self.sequence
                or self.companion._bridge is not self.bridge or self._close_waiter is not None):
            raise ConnectionError("menu ownership changed before handoff")
        waiter = self._close_waiter = asyncio.get_running_loop().create_future()
        try:
            self._send(request, screen, close=True)
            closed = await asyncio.wait_for(asyncio.shield(waiter), timeout)
            if (self._closed or self.open or self.companion._bridge is not self.bridge
                    or closed.sequence <= request.sequence):
                raise ConnectionError("menu close acknowledgment changed")
        finally:
            self._close_waiter = None
            if not waiter.done():
                waiter.cancel()

    async def open_trade_dialog(self, screen):
        """Reopen this menu only through the ABI2 native trade-hold gate."""
        if (self._dialog_queue is not None or self.open or self._closed
                or self.companion._bridge is not self.bridge
                or getattr(self.companion.config, "menu_abi_version", 1) != 2
                or self._last_request is None or self._last_request.kind != 3):
            raise ConnectionError("native held-trade menu is unavailable")
        self._dialog_queue = asyncio.Queue(maxsize=2)
        self.bridge.outbox.put_control(b"M" + pack_screen(self.sequence, screen, reopen_trade=True))
        request = await asyncio.wait_for(self._dialog_queue.get(), 5)
        if request.kind != 1 or not self.open or self.companion._bridge is not self.bridge:
            raise ConnectionError("native trade menu did not acknowledge OPEN")
        self._send(request, screen)

    def show_dialog(self, screen):
        if self._dialog_queue is None or not self.open:
            raise ConnectionError("native trade dialog closed")
        self._send(self._last_request, screen)

    async def dialog_choice(self, *, timeout=1):
        if self._dialog_queue is None or self._closed:
            raise ConnectionError("native trade dialog is unavailable")
        request = await asyncio.wait_for(self._dialog_queue.get(), timeout)
        if request.kind != 2 or not self.open:
            raise ConnectionError("native trade dialog lost its frozen core")
        return request

    async def close_dialog(self, screen):
        if self._dialog_queue is None:
            raise ConnectionError("native trade dialog is unavailable")
        await self.close_for_handoff(self._last_request, screen)
        self._dialog_queue = None

    async def _poll(self):
        while not self._closed:
            await asyncio.sleep(2)
            if not self.open or (self._task is not None and not self._task.done()):
                continue
            request = self._last_request
            try:
                previous = self.menu.screen
                screen = await self.menu.refresh()
                if screen != previous:
                    self._send(request, screen)
            except (ValueError, ConnectionError, OSError, asyncio.TimeoutError):
                if request is not None:
                    self._send(request, MenuScreen(max(1, self.menu.screen.revision),
                        "Players", "Reopen to check server status", (), 0), close=True)
            except Exception:
                self.open = False
                self.bridge.writer.close()
                return

    async def _cleanup(self):
        self._closed, self.open, self._queued_open = True, False, None
        if self._close_waiter is not None and not self._close_waiter.done():
            self._close_waiter.set_exception(ConnectionError("menu bridge closed during handoff"))
        self._poll_task.cancel()
        await asyncio.gather(self._poll_task, return_exceptions=True)
        if self._task is not None:
            # Never cancel an already dispatched consent. Its bounded RPC must
            # drain and will still require authoritative status on next open.
            await self._task

    async def close(self):
        from .player_runtime import _finish_even_if_cancelled
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup(), name="native-players-close")
        _, canceled = await _finish_even_if_cancelled(self._cleanup_task)
        if canceled:
            raise asyncio.CancelledError()
