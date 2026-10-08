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

    def feed(self, payload):
        request = MenuRequest.unpack(payload)
        if self._closed or request.sequence <= self.sequence:
            raise ValueError("native menu request was repeated or regressed")
        self.sequence = request.sequence
        self._last_request = request
        if request.kind == 3:
            self.open = False
            self._queued_open = None
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
                    self._send(request, screen)
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
