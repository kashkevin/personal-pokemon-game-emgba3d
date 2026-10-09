"""Same-core held record preparation, with durable explicit move decisions.

The authenticated preparation descriptor supplies incoming bytes and consent.
This client has no import, release or canonical-commit operation. The public
coordinator publishes a receipt only after retaining its complete reviewed copy.
Eggs, Mail and unsupported records remain ineligible.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import struct
import zlib

from .flash import FLASH_SIZE, SAVED_PARTY_OFFSET, inspect_flash
from .gen6_friendship import TABLE_ID, VALUES_SHA256, base_friendship
from .live_checkpoint import _atomic, _json_bytes
from .live_trade import LiveTradeError, _unique
from .ownership import OWNERSHIP_PROFILE, inspect_ownership
from .protocol import MAX_COUNTER
from .save_mailbox import Opcode, SaveControl, State
from .trade_effect_mailbox import OPS, PreparedRecord, context_bytes
from .trade_effect_witness import (
    LUCKY_BIT, EffectContext, EvolutionMoveChoice, _history, _record, _protected, lucky_conversion_ok,
)
from .trade_flash import _party_record
from .trade_friendship import FriendshipHistory, TrainerIdentity, transform_received_party_record

_FORMAT = "emerald-held-trade-record-preparation-v1"
_LIMIT = 16384


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _bytes(value, size):
    result = base64.b64decode(value, validate=True)
    if len(result) != size or _b64(result) != value:
        raise ValueError("noncanonical preparation bytes")
    return result


class HeldTradeEffectClient:
    """Internal explicit-choice API; all public calls retain the original hold.

    ``begin`` obtains the actual mutually confirmed host descriptor. ``choose``
    replaces slot 0..3 or explicitly declines with slot 4. ``resume`` reconciles
    a lost response on the same retained core while the original uncommitted
    host preparation still exists. Lost host consent cannot be reconstructed.
    ``discard`` discards only private computation, never the ordinary trade.
    Complete incoming handler history and an explicit geographic adaptation
    decision are mandatory. This class does not fabricate legacy history.
    """

    def __init__(self, coordinator, history, *, refresh_handler, profile_game_version, engine_source_sha256):
        if type(history) is not FriendshipHistory or type(refresh_handler) is not bool:
            raise ValueError("complete typed history and explicit handler-refresh policy required")
        history.validate()
        if type(profile_game_version) is not int or not 0 <= profile_game_version <= 15:
            raise ValueError("explicit pinned origin game version required")
        if (type(engine_source_sha256) is not str or len(engine_source_sha256) != 64
                or any(c not in "0123456789abcdef" for c in engine_source_sha256)):
            raise ValueError("exact native source provenance required")
        self.coordinator, self.companion = coordinator, coordinator.companion
        self.history, self.refresh = history, refresh_handler
        self.game_version, self.engine_source_sha256 = profile_game_version, engine_source_sha256
        self._active = None
        self.path = None
        self.binding = None
        self._save_context = None
        self._choice_snapshot = None
        self._presentation_running = False
        self._presentation_owner = None
        self.review = None

    async def _context(self):
        co, c = self.coordinator, self.companion
        if (getattr(c.config, "trade_effect_prepare_abi_version", 0) != 1
                or not getattr(c._bridge, "trade_effect_prepare_capable", False)):
            raise LiveTradeError("effect_preparation_unavailable", "this build has no verified private record preparation transport")
        session = co._session()
        intent = co._load(session)
        if intent["phase"] != "prepared" or not intent["export_ended"] or intent["fate"] is not None:
            raise LiveTradeError("effect_preparation_unavailable", "record preparation requires the original uncommitted trade hold")
        await co._held(intent, session)
        hold = await co._query(intent, session)
        if (hold.phase != State.TRADE_HELD or hold.import_started or hold.expired
                or hold.revision != intent["expected_revision"]+1 or hold.next_offset != FLASH_SIZE
                or hold.session_epoch != session[1]):
            raise LiveTradeError("effect_preparation_unavailable", "the original completed trade export is not held")
        view = (await co._rpc(session, "prepare", transaction_id=intent["transaction_id"],
                              generation=intent["generation"]))["trade"]
        if view["state"] != "recipient_preparation":
            raise LiveTradeError("trade_changed", "the host has no uncommitted recipient preparation")
        description = view["preparation"]
        self.bind_description(intent, session, description, hold.crc32)
        return session, intent, _bytes(self.binding["begin"], 192)

    def bind_description(self, intent, session, description, held_crc):
        """Bind exact retained evidence without native or network activity."""
        co = self.coordinator
        retained = co._recipient_record(intent, session, description)
        own = next(p for p in description["players"] if p["player_id"] == intent["player_id"])
        peer = next(p for p in description["players"] if p["player_id"] != intent["player_id"])
        source = co._bytes(intent["prepare_id"] + ".flash", intent["frozen_sha256"], FLASH_SIZE)
        if zlib.crc32(source) != held_crc:
            raise LiveTradeError("effect_source_mismatch", "held native export differs from the retained canonical source")
        snapshot = inspect_flash(source, save_profile=OWNERSHIP_PROFILE)
        ownership = inspect_ownership(snapshot)
        if (ownership.world_id, ownership.player_id) != (session[0], intent["player_id"]):
            raise ValueError("record preparation source ownership changed")
        offset, sent = _party_record(snapshot, ownership, own["serial"])
        incoming = _bytes(description["incoming_record"], 100)
        lucky = False
        if "effects" in description:
            from .trade_effect_preparation import decode_effect_plan
            effects = description["effects"]
            plan = decode_effect_plan(next(p for p in effects["offers"] if p["player_id"] == peer["player_id"]))
            if (self.history != plan.history or self.refresh != plan.refresh_handler
                    or self.game_version != effects["profile_game_version"]
                    or self.engine_source_sha256 != effects["engine_source_sha256"]):
                raise ValueError("native preparation differs from the authenticated effect history/policy")
            lucky = plan.lucky  # the host's Lucky Trade decision for the Pokémon this player receives
        if (hashlib.sha256(sent).hexdigest() != own["record_sha256"]
                or hashlib.sha256(incoming).hexdigest() != peer["record_sha256"]
                or _record(incoming)[0][0] != peer["serial"]):
            raise ValueError("record preparation differs from the confirmed offered records")
        recipient = TrainerIdentity(snapshot.metadata.name, snapshot.metadata.gender,
                                    snapshot.metadata.trainer_id, self.game_version)
        original, _, _ = _record(incoming)
        _, transition = transform_received_party_record(incoming, self.history, recipient,
            base_friendship=base_friendship(original[3]), refresh_handler=self.refresh)
        context = EffectContext(session[0], intent["transaction_id"], intent["generation"], intent["player_id"],
            intent["prepare_id"], own["lease_epoch"], own["revision"], own["sha256"],
            description["preparation_id"], intent["build_id"], intent["ruleset_id"], self.engine_source_sha256)
        key = context_bytes(intent["generation"], description["preparation_id"])
        data = (key + bytes.fromhex(intent["frozen_sha256"]) + struct.pack("<II", (offset-SAVED_PARTY_OFFSET)//100,
            transition.friendship | (LUCKY_BIT if lucky else 0)) + incoming + struct.pack("<I", held_crc))
        binding = dict(format=_FORMAT, recipient=retained, context=context.values(),
            incoming_history=_history(self.history), resulting_history=_history(transition.history),
            refresh_handler=self.refresh, profile_game_version=self.game_version,
            friendship_table=[TABLE_ID, VALUES_SHA256], begin=_b64(data), sent=_b64(sent))
        path = co.directory / (intent["transaction_id"] + "." + intent["generation"] + ".native-record.json")
        if self.binding is not None and (self.binding != binding or self.path != path):
            raise ValueError("retained native preparation context changed")
        self.binding, self.path = binding, path
        return data

    def _load(self):
        if not self.path.exists():
            return dict(binding=self.binding, choices=[], presentations=[], response=None, phase="active", command=None)
        with self.path.open("rb") as stream:
            raw = stream.read(_LIMIT+1)
        envelope = json.loads(raw, object_pairs_hook=_unique)
        if (len(raw) > _LIMIT or type(envelope) is not dict or set(envelope) != {"record", "sha256"}
                or raw != _json_bytes(envelope)
                or hashlib.sha256(_json_bytes(envelope["record"])).hexdigest() != envelope["sha256"]):
            raise ValueError("native preparation journal is malformed")
        record = envelope["record"]
        if type(record) is dict and set(record) == {"binding", "choices", "response", "phase", "command"}:
            # Historical decisions remain valid, but never gain fabricated UI evidence.
            record["presentations"] = [None] * len(record["choices"]) if type(record["choices"]) is list else None
        if (type(record) is not dict or set(record) != {"binding", "choices", "presentations", "response", "phase", "command"}
                or record["binding"] != self.binding or record["phase"] not in {"active", "discarding", "discarded"}
                or type(record["choices"]) is not list or len(record["choices"]) > 16
                or type(record["presentations"]) is not list or len(record["presentations"]) != len(record["choices"])):
            raise ValueError("native preparation journal changed its authority")
        from .trade_effect_choice import validate_presentation
        for index, choice in enumerate(record["choices"]):
            if type(choice) is not list or len(choice) != 2:
                raise ValueError("invalid retained evolution decision")
            EvolutionMoveChoice(*choice).validate()
            validate_presentation(record["presentations"][index], *choice, index)
            if record["presentations"][index] is not None:
                displayed = self._result(_bytes(record["presentations"][index]["record"], 192))
                if list(map(list, displayed.choices)) != record["choices"][:index]:
                    raise ValueError("retained screen does not follow the prior explicit decisions")
        if record["response"] is not None:
            result = self._result(_bytes(record["response"], 192))
            if list(map(list, result.choices)) != record["choices"][:len(result.choices)] or not 0 <= len(record["choices"])-len(result.choices) <= 1:
                raise ValueError("native response contradicts retained explicit decisions")
        elif record["choices"]:
            raise ValueError("move decisions require the retained original preparation")
        if record["command"] is not None:
            command = SaveControl.unpack(_bytes(record["command"], 240)).validate_command()
            if command.opcode not in OPS or command.data[:48] != _bytes(self.binding["begin"], 192)[:48]:
                raise ValueError("retained command has another preparation context")
        return record

    def _save(self, record):
        raw = _json_bytes(dict(record=record, sha256=hashlib.sha256(_json_bytes(record)).hexdigest()))
        if len(raw) > _LIMIT:
            raise ValueError("native preparation journal exceeds its fixed bound")
        _atomic(self.path, raw)

    def _result(self, raw):
        result = PreparedRecord.parse(raw)
        begin = _bytes(self.binding["begin"], 192)
        incoming, sent = begin[88:188], _bytes(self.binding["sent"], 100)
        original, before, held = _record(incoming)
        current, after, item = _record(result.candidate)
        evolved = current[3] != original[3]
        word = struct.unpack_from("<I", begin, 84)[0]
        lucky = bool(word & LUCKY_BIT)
        if (result.received_serial != original[0] or result.sent_serial != _record(sent)[0][0]
                or result.received_species != original[3] or current[:3] != original[:3]
                or current[3] != (result.evolved_species or original[3])
                or result.friendship != word & 0xFF or after[9] != result.friendship
                or result.lucky != lucky or (lucky and not lucky_conversion_ok(before, after))
                or result.item_before != held or result.item_after != item or item not in {held, 0}
                or _protected(incoming, before, evolved, lucky) != _protected(result.candidate, after, evolved, lucky)
                or (not evolved and (result.choices or result.pending_move))):
            raise ValueError("native private record changed protected or resolved fields")
        return result

    def authorizes(self, companion, control):
        active = self._active
        if (active is None or companion is not self.companion or active[0] is not asyncio.current_task()
                or companion._live_save_owner is not active[0] or active[3] != control):
            return False
        session, intent = active[1:3]
        self.coordinator._same_session(session)
        current = self.coordinator._load(session)
        if control.opcode in (Opcode.BEGIN_EFFECT_SAVE, Opcode.READ_EFFECT_WINDOW):
            if self._save_context is None:
                return False
            expected = _json_bytes(self._save_context)
            with self.path.with_suffix(".save-context.json").open("rb") as stream:
                if stream.read(len(expected)+1) != expected:
                    return False
            begin = _bytes(self._save_context["begin"], 88)
            if control.data != (begin if control.opcode == Opcode.BEGIN_EFFECT_SAVE else begin[:48]):
                return False
        return (current == intent and self._load()["command"] == _b64(control.pack())
                and (control.incarnation, control.session_epoch, control.request_id, control.revision) ==
                    (session[2], session[1], intent["transaction_id"], intent["prepared"]["revision"]))

    async def _command(self, session, intent, record, opcode, data, *, offset=0):
        c = self.companion
        self.coordinator._same_session(session)
        if c._live_binding != session or c._live_sequence >= MAX_COUNTER:
            raise ValueError("original held command cursor is unavailable")
        c._live_sequence += 1
        control = SaveControl(session[2], session[1], intent["transaction_id"], c._live_sequence,
                              offset, FLASH_SIZE, intent["prepared"]["revision"], opcode, data=data).validate_command()
        record["command"] = _b64(control.pack())
        self._save(record)  # Exact command and any decision reach disk before dispatch.
        self._active = (asyncio.current_task(), session, intent, control)
        try:
            response = await c.trade_effect_rpc(self, control)
            self.coordinator._same_session(session)
            self.coordinator._ok(response[0] if opcode == Opcode.READ_EFFECT_WINDOW else response)
            return response
        finally:
            self._active = None

    async def _resume(self, session, intent, record, begin):
        if record["phase"] != "active":
            raise ValueError("this preparation was discarded; resume the ordinary trade separately")
        # Identical BEGIN is native idempotent and returns the current scratch.
        # It never restarts evolution or overwrites an already pending choice.
        response = await self._command(session, intent, record, Opcode.BEGIN_EFFECT_RECORD, begin)
        result = self._result(response.data)
        desired = tuple(map(tuple, record["choices"]))
        if result.choices != desired[:len(result.choices)] or len(desired)-len(result.choices) not in (0, 1):
            raise ValueError("native transcript cannot reconcile the retained decision")
        if len(result.choices) < len(desired):
            move, slot = desired[-1]
            if result.state != 1 or result.pending_move != move:
                raise ValueError("retained decision names a different pending evolution move")
            response = await self._command(session, intent, record, Opcode.CHOOSE_EFFECT_MOVE,
                begin[:48] + struct.pack("<IHBB", len(result.choices), move, slot, 0))
            result = self._result(response.data)
        if result.choices != desired:
            raise ValueError("native preparation did not acknowledge the exact decision transcript")
        record["response"], record["command"] = _b64(response.data), None
        self._save(record)
        return result

    async def begin(self):
        async with self.coordinator._own():
            session, intent, begin = await self._context()
            return await self._resume(session, intent, self._load(), begin)

    async def resume(self):
        return await self.begin()

    async def choice_view(self):
        """Read native facts for the exact current private record, without choosing."""
        from .trade_effect_choice import NativeChoiceView, ChoiceSnapshot
        c = self.companion
        if (getattr(c.config, "trade_effect_choice_abi_version", 0) != 1
                or not getattr(c._bridge, "trade_effect_choice_capable", False)):
            raise LiveTradeError("effect_choice_unavailable", "this build has no verified native move presentation")
        async with self.coordinator._own():
            self._choice_snapshot = None
            session, intent, begin = await self._context()
            record = self._load()
            result = await self._resume(session, intent, record, begin)
            response = await self._command(session, intent, record, Opcode.QUERY_EFFECT_CHOICE, begin[:48])
            view = NativeChoiceView.parse(response.data)
            raw = _bytes(record["response"], 192)
            view.match(raw)
            record["command"] = None
            self._save(record)
            snapshot = ChoiceSnapshot(result, view, raw, response.data,
                (session, intent["transaction_id"], intent["generation"], hashlib.sha256(_json_bytes(self.binding)).hexdigest()))
            self._choice_snapshot = snapshot
            return snapshot

    async def choose_presented(self, snapshot, slot, *, screen, request_sequence):
        """Consume an exact native-screen choice once, recording it before dispatch."""
        from .trade_effect_choice import validate_presentation
        self._presented_request(screen, request_sequence)
        if snapshot is not self._choice_snapshot or snapshot is None:
            raise ValueError("move choice no longer owns its displayed snapshot")
        self._choice_snapshot = None  # Consume before the first await.
        choice = EvolutionMoveChoice(snapshot.record.pending_move, slot).validate()
        evidence = dict(record=_b64(snapshot.record_bytes), view=_b64(snapshot.view_bytes),
                        screen=screen, request_sequence=request_sequence, slot=slot)
        validate_presentation(evidence, choice.move, choice.slot, len(snapshot.record.choices))
        async with self.coordinator._own():
            session, intent, begin = await self._context()
            if snapshot.binding != (session, intent["transaction_id"], intent["generation"],
                    hashlib.sha256(_json_bytes(self.binding)).hexdigest()):
                raise ValueError("displayed move decision lost its original trade/session")
            record = self._load()
            await self._resume(session, intent, record, begin)
            if _bytes(record["response"], 192) != snapshot.record_bytes:
                raise ValueError("displayed move decision differs from the current native record")
            record["choices"].append([choice.move, choice.slot])
            record["presentations"].append(evidence)
            self._save(record)
            return await self._resume(session, intent, record, begin)

    async def prepare_in_game(self, menu_session):
        """Explicit held-native-menu preparation, still without any publication.

        Its public owner supplies the mutually confirmed v2 history and adapter.
        """
        from .trade_effect_menu import HeldTradeEffectMenu
        if self._presentation_running:
            raise ValueError("this retained preparation already owns a presentation")
        self._presentation_running = True
        self._presentation_owner = (menu_session, asyncio.current_task())
        try:
            return await HeldTradeEffectMenu(self, menu_session).run()
        finally:
            self._presentation_running = False
            self._presentation_owner = None
            self._choice_snapshot = None

    def _presented_request(self, screen, request_sequence):
        owner = self._presentation_owner
        if owner is None or owner[1] is not asyncio.current_task():
            raise ValueError("native-screen evidence requires the active presentation owner")
        menu = owner[0]
        request = menu._last_request
        if (menu._task is not owner[1] or not menu.open or menu._closed or menu._dialog_queue is None
                or menu.companion is not self.companion or self.companion._bridge is not menu.bridge
                or request is None or request.kind != 2 or request.screen != screen or request.sequence != request_sequence):
            raise ValueError("native-screen evidence differs from the current authenticated menu event")

    async def prepare_presented(self, snapshot, *, screen, request_sequence):
        """Retain an explicit READY review before full private save computation."""
        self._presented_request(screen, request_sequence)
        if snapshot is None or snapshot is not self._choice_snapshot or snapshot.record.state != 2:
            raise ValueError("candidate review no longer owns its displayed READY record")
        self._choice_snapshot = None
        if (type(screen) is not int or not 1 <= screen <= 0xFFFFFFFF
                or type(request_sequence) is not int or not 1 <= request_sequence <= 0xFFFFFFFF):
            raise ValueError("candidate review lacks its exact native screen/request")
        async with self.coordinator._own():
            session, intent, begin = await self._context()
            if snapshot.binding != (session, intent["transaction_id"], intent["generation"],
                    hashlib.sha256(_json_bytes(self.binding)).hexdigest()):
                raise ValueError("candidate review lost its original trade/session")
            record = self._load()
            await self._resume(session, intent, record, begin)
            if _bytes(record["response"], 192) != snapshot.record_bytes:
                raise ValueError("candidate review differs from current native preparation")
            review = dict(format="emerald-held-trade-candidate-review-v1", binding=self.binding,
                record=_b64(snapshot.record_bytes), view=_b64(snapshot.view_bytes),
                screen=screen, request_sequence=request_sequence, session_epoch=session[1])
            self.coordinator._immutable(self.path.with_suffix(f".review.{session[1]}.{screen}.{request_sequence}.json").name,
                                        _json_bytes(review))
            self.review = review
        candidate = await self.prepare_save()
        if candidate.record_sha256 != hashlib.sha256(snapshot.record_bytes).hexdigest():
            raise ValueError("private candidate differs from the reviewed READY record")
        return candidate

    async def prepare_save(self):
        """Stream and retain a complete private candidate; never publish it.

        A repeated call restarts readback from the same native/source context.
        Missing choices remain explicit; host loss never fabricates old consent.
        """
        from .trade_effect_source import validate_effect_source
        from .trade_effect_candidate import validate_streamed_candidate
        co, c = self.coordinator, self.companion
        async with co._own():
            if (getattr(c.config, "trade_effect_save_abi_version", 0) != 1
                    or not getattr(c._bridge, "trade_effect_save_capable", False)):
                raise LiveTradeError("effect_save_unavailable", "this build has no verified full candidate transport")
            session, intent, begin = await self._context()
            record = self._load()
            ready = await self._resume(session, intent, record, begin)
            if ready.state != 2:
                raise LiveTradeError("effect_move_required", "record the pending evolution move decision before preparing the save")
            # Probe only an existing operation. An older host may reject the
            # optional status field, but never receives an unknown RPC type.
            description = self.binding["recipient"]["preparation"]
            if "effects" in description:
                from .trade_effect_source import effect_source_from_plan
                peer_source = effect_source_from_plan(description)
            else:
                support = await co._rpc(session, "status", transaction_id=intent["transaction_id"], effect_source_version=1)
                if support.get("effect_source_version") != 1:
                    raise LiveTradeError("effect_source_unavailable", "host did not negotiate original effect-source metadata")
                source_view = (await co._rpc(session, "effect_source", transaction_id=intent["transaction_id"],
                    generation=intent["generation"], preparation_id=description["preparation_id"]))["trade"]
                peer_source = source_view["source"]
            gifts = validate_effect_source(peer_source, intent["player_id"], description)
            native_begin = begin[:48] + bytes.fromhex(peer_source["sha256"]) + gifts + b"\0"
            evidence = dict(format="emerald-held-trade-save-context-v1", record_binding=self.binding,
                            ready_record=record["response"], peer_source=peer_source, begin=_b64(native_begin))
            context_path = self.path.with_suffix(".save-context.json")
            co._immutable(context_path.name, _json_bytes(evidence))
            self._save_context = evidence
            source = co._bytes(intent["prepare_id"] + ".flash", intent["frozen_sha256"], FLASH_SIZE)
            snapshot = inspect_flash(source, save_profile=OWNERSHIP_PROFILE)
            first = snapshot.metadata.bank * 14 * 4096
            rotation = (-struct.unpack_from("<H", source, first + 4084)[0]) % 14
            response = await self._command(session, intent, record, Opcode.BEGIN_EFFECT_SAVE, native_begin)
            if struct.unpack("<II", response.data) != (snapshot.metadata.counter, rotation):
                raise ValueError("native full candidate no longer names the original active bank")
            output = bytearray()
            while len(output) < FLASH_SIZE:
                # Streaming all32 sectors may exceed one native hold interval.
                # Renew through the existing exact trade owner, never by
                # extending deadlines or bypassing an expired/foreign hold.
                await co._held(intent, session)
                await co._command(session, intent["transaction_id"], intent["prepared"]["revision"], Opcode.KEEP_TRADE)
                response, window = await self._command(session, intent, record, Opcode.READ_EFFECT_WINDOW,
                                                       begin[:48], offset=len(output))
                if response.offset != len(output) or len(window) != 4096 or struct.unpack("<I", response.data)[0] != zlib.crc32(window):
                    raise ValueError("native candidate window lost its exact offset/CRC")
                output.extend(window)
            candidate = validate_streamed_candidate(source, description, peer_source,
                                                   _bytes(record["response"], 192), bytes(output))
            co._same_session(session)
            candidate_path = self.path.with_suffix(".candidate.flash")
            co._immutable(candidate_path.name, candidate.payload)
            completion = dict(format="emerald-held-trade-save-candidate-v1", preparation_id=candidate.preparation_id,
                effect_source_sha256=candidate.effect_source_sha256, record_sha256=candidate.record_sha256,
                context_sha256=hashlib.sha256(_json_bytes(evidence)).hexdigest(),
                candidate_sha256=candidate.sha256, size=len(candidate.payload))
            co._immutable(self.path.with_suffix(".candidate.json").name, _json_bytes(completion))
            record["command"] = None
            self._save(record)
            return candidate

    async def resume_save(self):
        return await self.prepare_save()

    async def choose(self, move, slot):
        choice = EvolutionMoveChoice(move, slot).validate()
        async with self.coordinator._own():
            session, intent, begin = await self._context()
            record = self._load()
            result = await self._resume(session, intent, record, begin)
            if result.state != 1 or result.pending_move != choice.move or len(result.choices) >= 16:
                raise ValueError("this exact evolution move is not awaiting a decision")
            record["choices"].append([choice.move, choice.slot])
            record["presentations"].append(None)
            self._save(record)
            return await self._resume(session, intent, record, begin)

    async def discard(self):
        async with self.coordinator._own():
            session, intent, begin = await self._context()
            record = self._load()
            if record["phase"] == "discarded":
                return
            if record["phase"] == "active":
                await self._resume(session, intent, record, begin)
            record["phase"] = "discarding"
            self._save(record)
            await self._command(session, intent, record, Opcode.DISCARD_EFFECT_RECORD, begin[:48])
            record["phase"], record["command"] = "discarded", None
            self._save(record)
