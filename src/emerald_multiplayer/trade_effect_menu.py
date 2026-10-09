"""Explicit native screens for gated held trade-effect preparation.

This owner runs inside the original MenuSession task after the ordinary dialog
has closed. It returns a private candidate or a paused hold, never a commit,
release or accepted-trade receipt. The public coordinator calls it only for a
negotiated native-effect plan; exact-swap menus preserve their existing flow.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from textwrap import wrap

from .player_menu import MenuRow, MenuScreen
from .species_labels import species_label
from .trade_inspection import item_label, move_label, summarize_record

# Pinned constants/pokemon.h enum, presentation only. This does not enable a type.
_TYPE_NAMES = ("None", "Normal", "Fighting", "Flying", "Poison", "Ground", "Rock", "Bug", "Ghost",
               "Steel", "Mystery", "Fire", "Water", "Grass", "Electric", "Psychic", "Ice", "Dragon",
               "Dark", "Fairy", "Stellar")


@dataclass(frozen=True)
class EffectMenuResult:
    state: str  # "paused" or "prepared"; neither is a published trade.
    candidate: object | None = None


class HeldTradeEffectMenu:
    def __init__(self, client, menu_session):
        self.client, self.menu = client, menu_session
        self.companion = client.companion
        self.bridge = self.companion._bridge
        self.owner = asyncio.current_task()
        if (self.owner is None or menu_session._task is not self.owner
                or menu_session.companion is not self.companion or menu_session.bridge is not self.bridge
                or getattr(self.bridge, "menu_session", None) is not menu_session
                or menu_session._closed or menu_session.open or menu_session._dialog_queue is not None
                or menu_session._last_request is None or menu_session._last_request.kind != 3):
            raise ValueError("effect presentation needs its original relinquished native menu owner")
        self.revision = max(1, menu_session.menu.screen.revision, menu_session._last_request.screen)
        self.screen, self.snapshot = None, None
        self.actions = {}
        self.page, self.detail_page, self.move_index, self.selection = "overview", 0, 4, None
        self.detail_return = "moves"
        self.notice = ""

    def _same_owner(self):
        if (self.menu._task is not self.owner or asyncio.current_task() is not self.owner
                or self.menu._closed or self.companion._bridge is not self.bridge
                or self.menu.bridge is not self.bridge or not self.companion.connected):
            raise ConnectionError("native effect presentation lost its original core/menu/session")

    def _screen(self, title, status, rows, back):
        if len(rows) > 6:
            raise ValueError("effect presentation exceeds six native rows")
        self.revision += 1
        if self.revision > 0xFFFFFFFF:
            raise ValueError("native effect screen revisions exhausted")
        self.actions = {index + 1: (op, arg) for index, (_, op, arg) in enumerate(rows) if op}
        self.actions[7] = back
        self.screen = MenuScreen(self.revision, title[:23], status[:31],
            tuple(MenuRow(index + 1 if op else 0, label[:25]) for index, (label, op, _) in enumerate(rows)), 7)
        return self.screen

    def _render(self):
        record, view = self.snapshot.record, self.snapshot.view
        if self.page == "moves":
            rows = []
            for slot, move in enumerate(view.moves[:4]):
                # A protected slot remains inspectable, never selectable for forgetting.
                prefix = "[LOCK] " if move.protected else f"{slot + 1}. "
                rows.append((prefix + move_label(move.move), "slot", slot))
            rows.extend((("New move details", "move_details", 4), ("Decline this move", "confirm_move", 4)))
            return self._screen("Learn " + move_label(view.pending_move), "Select a slot to review", rows, ("overview", None))
        if self.page == "slot":
            move = view.moves[self.selection]
            rows = [("Move details", "move_details", self.selection), ("Back to move list", "moves", None)]
            if view.replace_mask & (1 << self.selection):
                rows.append(("Replace this move", "confirm_move", self.selection))
            return self._screen(move_label(move.move), "Cannot forget" if move.protected else "Review before replacing", rows, ("moves", None))
        if self.page == "move_details":
            move = view.moves[self.move_index]
            category = ("None", "Physical", "Special", "Status")[move.category]
            kind = _TYPE_NAMES[move.type_id] if move.type_id < len(_TYPE_NAMES) else f"Type #{move.type_id}"
            facts = (move_label(move.move), f"PP {move.pp}/{move.max_pp}",
                     f"Power {move.power or '--'}; accuracy {move.accuracy or '--'}", f"{category}; {kind}",
                     "Cannot forget this move" if move.protected else "Move can be replaced" if self.move_index < 4 else "New evolution move")
            lines = [line for fact in facts for line in wrap(fact, 25)]
            pages = [lines[start:start + 4] for start in range(0, len(lines), 4)]
            self.detail_page %= len(pages)
            rows = [(line, "", None) for line in pages[self.detail_page]]
            rows.extend((("Previous page", "detail_page", -1), ("Next page", "detail_page", 1)))
            return self._screen(f"Move details {self.detail_page + 1}/{len(pages)}", "Pinned native move data", rows,
                                (self.detail_return, None))
        if self.page == "pokemon":
            pages = summarize_record(record.candidate).pages()
            self.detail_page %= len(pages)
            title, facts = pages[self.detail_page]
            rows = [(fact, "", None) for fact in facts]
            rows.extend((("Previous page", "detail_page", -1), ("Next page", "detail_page", 1)))
            return self._screen(f"Candidate {self.detail_page + 1}/{len(pages)}", title, rows, ("overview", None))
        if self.page == "confirm_move":
            declining = self.selection == 4
            facts = (["Do not learn " + move_label(view.pending_move)] if declining else
                     ["Forget " + move_label(view.moves[self.selection].move), "Learn " + move_label(view.pending_move)])
            lines = [line for fact in facts for line in wrap(fact, 25)]
            if len(lines) > 4:
                raise ValueError("exact move names exceed the bounded decision review")
            rows = [("Back", "moves", None)] + [(line, "", None) for line in lines]
            rows.append(("Continue to confirmation", "apply_confirm", None))
            return self._screen("Review move decision", "Review the complete names", rows, ("moves", None))
        if self.page == "apply_confirm":
            # The preceding Continue is at index >=2. This two-row screen
            # therefore resets the pinned native cursor to Back (index0).
            return self._screen("Apply reviewed choice?", "Only this explicit choice", [
                ("Back", "confirm_move", self.selection),
                ("Confirm decline" if self.selection == 4 else "Confirm replacement", "apply_move", self.selection)],
                ("moves", None))
        if self.page == "confirm_save":
            return self._screen("Prepare candidate?", "Private copy; no trade yet", [
                ("Back to review", "overview", None), ("Prepare private copy", "prepare", None)], ("overview", None))
        rows = [(species_label(record.received_species) + (" -> " + species_label(record.evolved_species) if record.evolved_species else ""), "", None),
                ("Review Pokemon", "pokemon", None)]
        if record.item_before != record.item_after:
            rows.append(("Item used: " + item_label(record.item_before), "", None))
        full_save = (getattr(self.companion.config, "trade_effect_save_abi_version", 0) == 1
                     and getattr(self.bridge, "trade_effect_save_capable", False)
                     and getattr(self.bridge, "window_capable", False))
        rows.append(("Choose evolution move", "moves", None) if record.state == 1 else
                    ("Prepare candidate", "confirm_save", None) if full_save else ("Full copy unavailable", "", None))
        rows.append(("Pause preparation", "pause", None))
        return self._screen("Trade preparation", self.notice or "Private; not yet traded", rows, ("pause", None))

    async def run(self):
        try:
            return await self._run()
        finally:
            # Closing presentation never releases the native trade hold. A
            # failed/uncertain decision stays in the existing durable journal.
            if (self.screen is not None and self.menu.open and self.menu._dialog_queue is not None
                    and not self.menu._closed and self.companion._bridge is self.bridge
                    and self.menu._task is self.owner):
                try:
                    await self.menu.close_dialog(self.screen)
                except (ValueError, ConnectionError, OSError, TimeoutError):
                    pass  # Disconnected native hold remains; no fabricated CLOSE receipt.
            if (self.menu._dialog_queue is not None and not self.menu.open and not self.menu._closed
                    and self.companion._bridge is self.bridge and self.menu._task is self.owner
                    and self.menu._last_request is not None and self.menu._last_request.kind == 3):
                # An unsolicited exact CLOSE may have arrived while an RPC was
                # pending. Feed already authenticated it; retire only its UI queue.
                self.menu._dialog_queue = None

    async def _run(self):
        self._same_owner()
        self.snapshot = await self.client.choice_view()
        self._same_owner()
        await self.menu.open_trade_dialog(self._render())
        while True:
            self._same_owner()
            await self.client.coordinator.keepalive()
            try:
                request = await self.menu.dialog_choice(timeout=1)
            except TimeoutError:
                continue
            self._same_owner()
            if request.screen != self.screen.revision or request.action not in self.actions:
                self.menu.show_dialog(self._render())
                continue
            op, arg = self.actions.pop(request.action)
            self.actions.clear()  # Consume every displayed action before an await.
            if op == "pause":
                await self.menu.close_dialog(self.screen)
                return EffectMenuResult("paused")
            if op == "apply_move":
                await self.client.choose_presented(self.snapshot, arg, screen=request.screen, request_sequence=request.sequence)
                self.snapshot = await self.client.choice_view()
                self.page = "moves" if self.snapshot.record.state == 1 else "overview"
                self.notice = "Decision recorded"
            elif op == "prepare":
                candidate = await self.client.prepare_presented(self.snapshot, screen=request.screen, request_sequence=request.sequence)
                self._same_owner()
                await self.menu.close_dialog(self.screen)
                return EffectMenuResult("prepared", candidate)
            elif op == "slot":
                self.selection, self.page = arg, "slot"
            elif op == "confirm_move":
                self.selection, self.page = arg, "confirm_move"
            elif op == "move_details":
                self.detail_return = self.page
                self.move_index, self.detail_page, self.page = arg, 0, "move_details"
            elif op == "detail_page":
                self.detail_page += arg
            else:
                self.page, self.detail_page = op, 0
            self.menu.show_dialog(self._render())
