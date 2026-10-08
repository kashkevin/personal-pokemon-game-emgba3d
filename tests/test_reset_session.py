"""Retained cancellation authority and exact admission retries, without gameplay claims."""
import asyncio
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from emerald_multiplayer.reset_mailbox import ResetRequest, ResetReceipt
from emerald_multiplayer.reset_session import ResetSession
from emerald_multiplayer.protocol import ProtocolError


class Outbox:
    def __init__(self):
        self.packets = []
        self.event = asyncio.Event()

    def put_control(self, packet):
        self.packets.append(packet)
        self.event.set()


class ResetSessionTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, version=2):
        bridge = SimpleNamespace(incarnation=3, outbox=Outbox())
        session = ("world", 2, 3, "profile", "player", "build", "rules")
        c = SimpleNamespace(connected=True, session_epoch=2, _bridge=bridge,
            config=SimpleNamespace(reset_abi_version=version), live_checkpoint_lock=asyncio.Lock(),
            _guard_pending_trade_mutation=lambda: None, _reconnect_blocked=False,
            _live_binding=session, _live_save_owner=None,
            reset_rpc=AsyncMock(return_value={"result": {"attempt": 1}}))
        reset = ResetSession(c, bridge)
        request = ResetRequest(1, 2, 3, 0x1001, 0)
        return c, bridge, reset, request, session

    def receipt(self, request, state, ready=0):
        return struct.pack("<8I", request.sequence, request.session, request.incarnation,
                           request.encounter, 1 if state == 2 else 0, state, ready, 0)

    async def test_timeout_retries_keep_one_request_id_and_send_one_ack(self):
        c, bridge, reset, request, _ = self.fixture()
        c.reset_rpc.side_effect = [asyncio.TimeoutError(), {"result": {"attempt": 1}}]
        reset.feed(request.pack())
        await reset.task
        calls = c.reset_rpc.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].kwargs, calls[1].kwargs)
        self.assertEqual(bridge.outbox.packets, [b"U" + request.reply(1)])
        await reset.close()

    async def test_host_error_refuses_but_unknown_outcome_does_not_release(self):
        for error, expected in ((ProtocolError("denied", "refused"), True), (ConnectionError(), False)):
            c, bridge, reset, request, _ = self.fixture()
            c.reset_rpc.side_effect = error
            reset.feed(request.pack())
            await reset.task
            self.assertEqual(bridge.outbox.packets, [b"U" + request.reply(0, denied=True)] if expected else [])
            await reset.close()

    async def test_exact_cancel_waits_for_native_safe_field_and_fences_queued_admission(self):
        c, bridge, reset, request, session = self.fixture()
        async with c.live_checkpoint_lock:
            reset.feed(request.pack())  # _admit is queued behind the lifecycle owner.
            c.connected = False; c._reconnect_blocked = True
            c._live_save_owner = asyncio.current_task()
            async def respond():
                await bridge.outbox.event.wait()
                reset.observe(self.receipt(request, 4))
                await asyncio.sleep(0)
                reset.observe(self.receipt(request, 4, 1))
            responder = asyncio.create_task(respond())
            self.assertTrue(await reset.drain_before_emergency(session))
            await responder
            self.assertTrue(bridge.outbox.packets)
            self.assertTrue(all(packet == b"U" + request.cancel() for packet in bridge.outbox.packets))
        await reset.task
        c.reset_rpc.assert_not_awaited()
        await reset.close()

    async def test_cancel_timeout_old_abi_or_applied_ack_never_claims_safe_drain(self):
        for variant in ("timeout", "abi1", "ack"):
            c, bridge, reset, request, session = self.fixture(1 if variant == "abi1" else 2)
            async with c.live_checkpoint_lock:
                reset.feed(request.pack())
                c.connected = False; c._reconnect_blocked = True
                c._live_save_owner = asyncio.current_task()
                if variant == "ack":
                    reset.observe(self.receipt(request, 2))
                self.assertFalse(await reset.drain_before_emergency(session, timeout=.02))
                if variant != "timeout": self.assertEqual(bridge.outbox.packets, [])
            await reset.task
            c.reset_rpc.assert_not_awaited()
            await reset.close()

    async def test_foreign_bridge_session_and_owner_cannot_send_cancel(self):
        for field in ("owner", "bridge", "session", "online", "unblocked"):
            c, bridge, reset, request, session = self.fixture()
            async with c.live_checkpoint_lock:
                reset.feed(request.pack())
                c.connected = False; c._reconnect_blocked = True
                c._live_save_owner = asyncio.current_task()
                if field == "owner": c._live_save_owner = None
                elif field == "bridge": c._bridge = object()
                elif field == "session": c._live_binding = ("other", *session[1:])
                elif field == "online": c.connected = True
                else: c._reconnect_blocked = False
                self.assertFalse(await reset.drain_before_emergency(session, timeout=.01))
                self.assertEqual(bridge.outbox.packets, [])
                c.connected = False
            await reset.task
            await reset.close()

    async def test_foreign_or_changed_terminal_receipt_is_rejected(self):
        c, bridge, reset, request, _ = self.fixture()
        reset.feed(request.pack()); await reset.task
        with self.assertRaises(ValueError):
            reset.observe(self.receipt(ResetRequest(2, 2, 3, 0x1001, 0), 4))
        reset.observe(self.receipt(request, 4))
        reset.observe(self.receipt(request, 4, 1))
        with self.assertRaises(ValueError): reset.observe(self.receipt(request, 2))
        for invalid in (self.receipt(request, 2, 1), self.receipt(request, 5), self.receipt(request, 4)[:-1]+b"x"):
            with self.assertRaises(ValueError): ResetReceipt.unpack(invalid)
        await reset.close()
