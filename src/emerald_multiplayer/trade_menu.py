"""Explicit native offer/consent screens over the existing durable exchange.

The current exact-record capability still excludes unaudited native trade
effects. UI availability does not widen that eligibility policy.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .flash import FLASH_SIZE, POKEMON_SIZE, SAVED_PARTY_OFFSET, inspect_flash
from .live_trade import LiveTradeCoordinator
from .ownership import OWNERSHIP_PROFILE, inspect_ownership
from .player_menu import MenuRow, MenuScreen
from .trade_eligibility import TradeEligibilityError, validate_party_offer


@dataclass(frozen=True)
class PartyChoice:
    serial: int
    species: int
    level: int
    eligible: bool


def prepared_choices(coordinator):
    session = coordinator._session()
    intent = coordinator._load(session)
    if intent["prepared"] is None or not intent["export_ended"] or intent["fate"] is not None:
        raise ValueError("trade choice requires an unchanged prepared party")
    payload = coordinator._bytes(intent["prepare_id"] + ".flash", intent["frozen_sha256"], FLASH_SIZE)
    snapshot = inspect_flash(payload, save_profile=OWNERSHIP_PROFILE)
    records = sorted((r for r in inspect_ownership(snapshot).records if r.location.startswith("party:")),
                     key=lambda r: int(r.location.split(":")[1]))
    result = []
    for record in records:
        slot = int(record.location.split(":")[1])
        try:
            validate_party_offer(payload, record.serial)
            eligible = True
        except TradeEligibilityError:
            eligible = False
        result.append(PartyChoice(record.serial, record.species,
            snapshot.save_block1[SAVED_PARTY_OFFSET + slot * POKEMON_SIZE + 84], eligible))
    return tuple(result)


class NativeTradeMenu:
    def __init__(self, companion, directory, menu_session):
        self.companion = companion
        self.coordinator = LiveTradeCoordinator(companion, directory)
        self.menu_session = menu_session
        self.revision = menu_session.menu.screen.revision
        self.screen = None
        self.signature = None
        self.actions = {}
        self.page = "party"

    def _render(self, view, choices):
        actions = []
        actor = self.companion.config.player_id
        if self.page == "party":
            status = "Choose Pokemon; B: cancel"
            for mon in choices:
                label = f"No.{mon.species} Lv{mon.level}"
                actions.append((label if mon.eligible else label + " (unavailable)",
                                "offer" if mon.eligible else "", mon.serial))
        else:
            own = next((o for o in view["offers"] if o["player_id"] == actor), None)
            peer = next((o for o in view["offers"] if o["player_id"] != actor), None)
            status = "Review both offers"
            actions.append(("Yours: " + (f"No.{own['species']}" if own else "Choose Pokemon"), "", None))
            actions.append(("Theirs: " + (f"No.{peer['species']}" if peer else "Waiting"), "", None))
            if view["fingerprint"] is not None and actor not in view["confirmations"]:
                actions.append(("Confirm this trade", "confirm", view["fingerprint"]))
            if actor in view["confirmations"]:
                status = "Confirmed; waiting for friend"
            actions.extend((("Change your Pokemon", "party", None), ("Cancel trade", "cancel", None)))
        signature = (self.page, status, tuple(actions))
        if signature != self.signature:
            self.revision += 1
            self.actions = {i + 1: (op, arg) for i, (_, op, arg) in enumerate(actions) if op}
            self.actions[7] = ("cancel", None)
            self.screen = MenuScreen(self.revision, "Trade Pokemon", status,
                tuple(MenuRow(i + 1 if op else 0, label[:25]) for i, (label, op, _) in enumerate(actions)), 7)
            self.signature = signature
        return self.screen

    async def run(self, proposal, expected_revision):
        if proposal["state"] != "offering" or self.companion.config.player_id not in proposal["players"]:
            raise ValueError("trade menu requires this actor's live proposal")
        tx, generation = proposal["transaction_id"], proposal["generation"]
        await self.coordinator.prepare(tx, generation, expected_revision)
        choices = prepared_choices(self.coordinator)
        view = await self.coordinator.status()
        if view["state"] != "offering":
            return await self.coordinator.resume()
        await self.menu_session.open_trade_dialog(self._render(view, choices))
        while True:
            await self.coordinator.keepalive()
            view = await self.coordinator.status()
            if view["state"] != "offering":
                # Native import/reload can only begin after its UI relinquishes
                # the window and field locks, even when the other actor commits.
                await self.menu_session.close_dialog(self.screen)
                return await self.coordinator.resume()
            if view["generation"] != generation:
                raise ValueError("trade proposal generation changed")
            prior = self.screen
            screen = self._render(view, choices)
            if screen != prior:
                self.menu_session.show_dialog(screen)
            try:
                choice = await self.menu_session.dialog_choice()
            except TimeoutError:
                continue
            if choice.screen != self.screen.revision or choice.action not in self.actions:
                # Stale consent is never replayed against a newer pair of offers.
                self.signature = None
                self.menu_session.show_dialog(self._render(view, choices))
                continue
            op, value = self.actions.pop(choice.action)
            self.signature = None
            if op == "offer":
                view = await self.coordinator.offer(value)
                self.page = "review"
            elif op == "confirm":
                view = await self.coordinator.confirm(value)
            elif op == "cancel":
                # The coordinator owns both the durable pending intent and
                # native terminal release. Relinquish this window first, then
                # let that owner resolve cancellation versus a concurrent commit.
                await self.menu_session.close_dialog(self.screen)
                return await self.coordinator.cancel()
            else:
                self.page = "party"
            if view["state"] == "offering":
                self.menu_session.show_dialog(self._render(view, choices))
