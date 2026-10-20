"""One bounded native menu session on one authenticated bridge incarnation."""
import asyncio
from dataclasses import replace

from .battle_admission_session import BattleAdmissionRefused
from .bridge_protocol import BridgeError
from .menu_mailbox import MenuRequest, pack_screen
from .player_menu import MenuScreen, PlayerMenu, battle_admission_enabled, refusal_text


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
        self._admission_display = None
        self._admission_selection = None
        self._admission_identity = None
        self._battle_latched = False
        self._battle_preparing = False
        self._battle_admission_failed = False

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
            if not self._battle_latched:
                self._admission_display = None
            if self._close_waiter is not None and not self._close_waiter.done():
                self._close_waiter.set_result(request)
            return
        if self._battle_latched:
            raise ValueError("native battle admission still owns this menu")
        if request.kind == 1:
            self.open = True
        elif not self.open:
            raise ValueError("native menu choice has no open session")
        if self._task is not None and not self._task.done():
            if request.kind != 1:
                raise ValueError("native menu cannot issue overlapping choices")
            self._queued_open = request
            return
        if (request.kind == 2 and self._admission_display is not None
                and (request.screen, request.action) == self._admission_display):
            # The native joypad handler has already latched. Consume the
            # authenticated displayed descriptor synchronously, before a host
            # disconnect can clear live authentication or another task polls.
            self._battle_latched = self._battle_preparing = True
            try:
                descriptor = self.menu.claim_battle_admission(request.screen, request.action)
                self._admission_identity = (descriptor["battle_id"], descriptor["generation"])
                self.companion._native_menu_capture_battle(descriptor, self)
                self._admission_selection = (descriptor, None)
            except Exception as error:
                self._admission_selection = (None, error)
        else:
            self._admission_display = None
        self._task = asyncio.create_task(self._handle(request), name="native-players-menu")

    def _send(self, request, screen, *, close=False):
        if (not self._closed and not self._battle_latched and self.open and request.sequence == self.sequence
                and self.companion._bridge is self.bridge):
            try:
                self.bridge.outbox.put_control(b"M" + pack_screen(request.sequence, screen, close=close,
                    allow_battle_admission=battle_admission_enabled(self.companion)
                        and getattr(self.bridge, "battle_capable", False)))
                self._admission_display = ((screen.revision, screen.admission_action)
                    if screen.admission_action and not close else None)
            except BridgeError:
                self.open = False
                self.bridge.writer.close()

    async def _handle(self, request):
        try:
            while request is not None:
                try:
                    if self._battle_latched:
                        try:
                            await self.admit_for_handoff(request)
                        except BattleAdmissionRefused as error:
                            if not self._release_capable():
                                raise
                            await self._release_refused(request, error)
                        request, self._queued_open = self._queued_open, None
                        continue
                    elif request.kind == 1:
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
                        if (handoff[0] == "battle" and
                                getattr(getattr(self.companion, "config", None), "battle_resume_abi_version", 0) == 1):
                            raise ValueError("resumable battle requires its displayed native admission latch")
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
            if not self._battle_latched:
                self.open = False
                self.bridge.writer.close()

    def _release_capable(self):
        """The game ends a latched Enter window on a release screen (menu_release_abi_version 1)."""
        return (getattr(getattr(self.companion, "config", None), "menu_release_abi_version", 0) == 1
                and getattr(self.bridge, "battle_capable", False))

    async def _release_refused(self, request, error):
        """Enter refused before any ADMIT: the latched window shows why, with its rows usable again (Cancel challenge,
        a new Enter once the reason is gone, B: Back). Never a wait that cannot end."""
        settle = getattr(self.companion, "_native_menu_refused_battle", None)
        if callable(settle):
            settle(self)
        text = refusal_text(getattr(error, "code", None))
        self.menu.notice(text)
        try:
            screen = await self.menu.refresh()
        except (ValueError, ConnectionError, OSError, asyncio.TimeoutError):
            screen = MenuScreen(self.menu.screen.revision + 1, "Players", text, (), 0)
        if (self._closed or not self.open or request.sequence != self.sequence
                or self.companion._bridge is not self.bridge):
            return
        self._battle_latched = self._battle_preparing = self._battle_admission_failed = False
        self._admission_display = self._admission_selection = self._admission_identity = None
        try:
            self.bridge.outbox.put_control(b"M" + pack_screen(request.sequence, replace(screen, admission_action=0),
                                                              release=True))
        except BridgeError:
            self.open = False
            self.bridge.writer.close()
            return
        if screen.admission_action:
            self._send(request, screen)   # the usual screen: its Enter row works again

    async def admit_for_handoff(self, request, *, timeout=5):
        """ADMIT transfers the native Enter latch; ordinary CLOSE never does."""
        waiter = None
        succeeded = False
        failure = None
        try:
            selection, self._admission_selection = self._admission_selection, None
            if (not self._battle_preparing or not self._battle_latched or self._battle_admission_failed
                    or selection is None or self._closed or not self.open
                    or request.sequence != self.sequence or self.companion._bridge is not self.bridge
                    or not battle_admission_enabled(self.companion) or self._close_waiter is not None):
                raise ConnectionError("native battle admission lost its original menu ownership")
            descriptor, error = selection
            if error is not None:
                raise error
            waiter = self._close_waiter = asyncio.get_running_loop().create_future()
            await self.companion._native_menu_prepare_battle(descriptor, self)
            # The exact ADMIT receipt and its durable intent precede this
            # return. Its atomic native transfer may have emitted CLOSE while
            # preparation was still awaiting its receipt or durable write.
            closed = await asyncio.wait_for(asyncio.shield(waiter), timeout)
            if (self._closed or self.open or self.companion._bridge is not self.bridge
                    or closed.kind != 3 or closed.sequence <= request.sequence):
                raise ConnectionError("native battle admission close acknowledgment changed")
            await self.companion._native_menu_handoff("battle", descriptor, self)
            succeeded = True
        except BaseException as error:
            failure = error
            raise
        finally:
            if waiter is not None:
                self._close_waiter = None
                if not waiter.done():
                    waiter.cancel()
                elif not waiter.cancelled():
                    waiter.exception()  # Observe cleanup failure even if preparation failed first.
            if not succeeded and isinstance(failure, BattleAdmissionRefused) and self._release_capable():
                # Refused before any ADMIT: _handle releases the window (_release_refused); nothing to retain.
                self._queued_open = None
            elif not succeeded:
                self._battle_admission_failed = True
                self._queued_open = None
                abandon = getattr(self.companion, "_native_menu_abandon_battle_preparation", None)
                if callable(abandon):
                    abandon(self)
            else:
                self._battle_latched = False
                self._admission_display = None
            self._battle_preparing = False

    def finish_battle_admission(self, battle_id, generation):
        """Forget UI ownership only after the launcher verifies terminal HANDOFF.

        This changes no native state and grants no save or battle authority.
        Headless/public-RPC battles never acquired this menu's Enter latch.
        """
        if self._admission_identity is None and not self._battle_latched:
            return
        if (self._admission_identity != (battle_id, generation)
                or self.companion._bridge is not self.bridge
                or self._closed or self._battle_preparing and asyncio.current_task() is not self._task):
            raise ConnectionError("completed battle does not own this native menu latch")
        self._battle_latched = self._battle_admission_failed = False
        self._admission_display = self._admission_selection = self._queued_open = None
        self._admission_identity = None

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
            # Until another native request acknowledges a choice/close, this
            # exact marked screen may still be displayed or its Enter input
            # may already be latched with its IPC event in transit. A status
            # refresh must not discard that authenticated original descriptor.
            if (self._battle_latched or self._admission_display is not None or not self.open
                    or (self._task is not None and not self._task.done())):
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
