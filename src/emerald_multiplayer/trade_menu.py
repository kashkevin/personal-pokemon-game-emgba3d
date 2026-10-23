"""Explicit native offer/consent screens over the existing durable exchange.

Exact swaps remain available separately. Native effects require both the local
verified transport and the host's authenticated versioned effect capability.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from textwrap import wrap

from .companion import TradeError
from .flash import FLASH_SIZE, POKEMON_SIZE, SAVED_PARTY_OFFSET, inspect_flash
from .live_trade import LiveTradeCoordinator
from .ownership import OWNERSHIP_PROFILE, inspect_ownership
from .player_menu import MenuRow, MenuScreen
from .trade_eligibility import TradeEligibilityError, validate_party_offer
from .species_labels import species_label


@dataclass(frozen=True)
class PartyChoice:
    serial: int
    species: int
    level: int
    eligible: bool
    reason: str = ""


BLOCKED_REASONS = {
    "egg_unsupported": "Eggs cannot be traded yet.",
    "mail_unsupported": "Pokemon carrying Mail cannot be traded yet.",
    "trade_evolution_unsupported": "Trade evolution is not enabled for this build.",
    "species_unsupported": "This species or form is not supported for trading yet.",
}


def prepared_choices(coordinator, *, effects=False):
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
        reason = ""
        try:
            if effects:
                from .trade_effect_witness import _record
                start = SAVED_PARTY_OFFSET + slot * POKEMON_SIZE
                _record(snapshot.save_block1[start:start + POKEMON_SIZE])
            else:
                validate_party_offer(payload, record.serial)
            eligible = True
        except TradeEligibilityError as error:
            eligible = False
            reason = BLOCKED_REASONS.get(error.code, "This Pokemon cannot be offered from this saved party.")
        except ValueError:
            eligible = False
            reason = "This Pokemon needs unsupported egg, Mail, form or move handling."
        result.append(PartyChoice(record.serial, record.species,
            snapshot.save_block1[SAVED_PARTY_OFFSET + slot * POKEMON_SIZE + 84], eligible, reason))
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
        self.inspection_supported = None
        self.inspection = None
        self.detail_player = None
        self.detail_page = 0
        self.blocked_serial = None
        self.notice = ""
        self.effect_paused = False
        self.peer_species = None      # the friend's offered species, as last seen (the banner's "You received ...")
        self.cancelled_here = False   # this player chose Cancel trade

    async def _inspect(self, view, player):
        """Negotiate through a known operation before sending the new request."""
        c = self.companion
        binding = (c.world_id, c.server_epoch, c.session_epoch)
        self.notice = ""
        try:
            if self.inspection_supported is None:
                reply = await c.trade_rpc("status", transaction_id=view["transaction_id"], inspection_version=1)
                if not c.connected or binding != (c.world_id, c.server_epoch, c.session_epoch):
                    raise ConnectionError("offer inspection lost its authenticated session")
                self.inspection_supported = reply.get("inspection_version") == 1
            if not self.inspection_supported:
                self.notice = "Host has no offer details"
                return
            reply = await c.trade_rpc("inspect", transaction_id=view["transaction_id"],
                generation=view["generation"], fingerprint=view["fingerprint"])
        except TradeError as error:
            if error.code in {"invalid_field", "invalid_fields", "trade_preparation_unsupported"}:
                self.inspection_supported = False
                self.notice = "Host has no offer details"
                return
            if error.code in {"trade_offer_changed", "trade_aborted", "trade_generation_mismatch"}:
                self.notice = "Offers changed; review again"
                return
            raise
        except TimeoutError:
            self.notice = "Details timed out; select again"
            return
        if not c.connected or binding != (c.world_id, c.server_epoch, c.session_epoch):
            raise ConnectionError("offer inspection lost its authenticated session")
        from .trade_inspection import summaries_for_view
        summaries = summaries_for_view(reply["trade"], view, c.config.player_id)
        if player not in summaries:
            raise ValueError("offer details name another participant")
        self.inspection = (view["fingerprint"], summaries)
        self.detail_player, self.detail_page, self.page = player, 0, "details"

    def _render(self, view, choices):
        actions = []
        actor = self.companion.config.player_id
        title = "Trade Pokemon"
        back = ("cancel", None)
        if self.inspection is not None and view.get("fingerprint") != self.inspection[0]:
            self.inspection = None
            if self.page == "details":
                self.page = "review"
                self.notice = "Offers changed; review again"
        if view["state"] == "preparing":
            status = "Preparing trade" if actor not in view["prepared"] else "Ready; waiting for friend"
            if self.effect_paused and actor not in view["prepared"]:
                status = "Evolution review paused"
                actions.append(("Resume evolution review", "resume_effect", None))
            actions.append(("Cancel trade", "cancel", None))
        elif self.page == "party":
            status = "Pick; [X] blocked; B: cancel"
            for mon in choices:
                label = f"{species_label(mon.species)} Lv{mon.level}"
                actions.append((label if mon.eligible else "[X] " + label,
                                "offer" if mon.eligible else "blocked", mon.serial))
        elif self.page == "blocked":
            mon = next(mon for mon in choices if mon.serial == self.blocked_serial)
            title, status = species_label(mon.species), "Trade unavailable"
            actions.extend((line, "", None) for line in wrap(mon.reason, 25))
            actions.append(("Back to your party", "party", None))
            back = ("party", None)
        elif self.page == "details" and self.inspection is not None:
            summary = self.inspection[1][self.detail_player]
            pages = summary.pages()
            category, rows = pages[self.detail_page]
            title = ("Yours" if self.detail_player == actor else "Theirs") + f" {self.detail_page + 1}/{len(pages)}"
            status = category
            actions.extend((row, "", None) for row in rows)
            actions.extend((("Previous page", "detail_page", (self.detail_page - 1) % len(pages)),
                            ("Next page", "detail_page", (self.detail_page + 1) % len(pages))))
            back = ("review", None)
        else:
            own = next((o for o in view["offers"] if o["player_id"] == actor), None)
            peer = next((o for o in view["offers"] if o["player_id"] != actor), None)
            if peer is not None:
                self.peer_species = peer["species"]
            status = self.notice or "Select offers for details"
            for label, offer in (("Yours", own), ("Theirs", peer)):
                actions.append((label + ": " + (species_label(offer["species"]) if offer else "Waiting"),
                    "inspect" if offer and view["fingerprint"] is not None else "",
                    offer["player_id"] if offer else None))
            if view["fingerprint"] is not None and actor not in view["confirmations"]:
                actions.append(("Confirm this trade", "confirm", view["fingerprint"]))
            if actor in view["confirmations"]:
                status = "Confirmed; waiting for friend"
            actions.extend((("Change your Pokemon", "party", None), ("Cancel trade", "cancel", None)))
        signature = (self.page, title, status, tuple(actions), back, view.get("fingerprint"))
        if signature != self.signature:
            if len(actions) > 6:
                raise ValueError("trade menu exceeds native capacity")
            self.revision += 1
            if self.revision > 0xFFFFFFFF:
                raise ValueError("trade menu generation exhausted")
            self.actions = {i + 1: (op, arg) for i, (_, op, arg) in enumerate(actions) if op}
            self.actions[7] = back
            self.screen = MenuScreen(self.revision, title[:23], status[:31],
                tuple(MenuRow(i + 1 if op else 0, label[:25]) for i, (label, op, _) in enumerate(actions)), 7)
            self.signature = signature
        return self.screen

    async def run(self, proposal, expected_revision):
        if proposal["state"] not in {"offering", "preparing"} or self.companion.config.player_id not in proposal["players"]:
            raise ValueError("trade menu requires this actor's live proposal")
        tx, generation = proposal["transaction_id"], proposal["generation"]
        if self.coordinator.trade_path.exists():
            async with self.coordinator._own():
                session = self.coordinator._session()
                retained = self.coordinator._load(session)
                if ((retained["transaction_id"], retained["generation"]) != (tx, generation)
                        or retained["prepared"] is None or not retained["export_ended"]
                        or expected_revision not in (retained["expected_revision"], retained["prepared"]["revision"])):
                    raise ValueError("native trade menu does not own this retained prepared party")
                await self.coordinator._held(retained, session)
        else:
            await self.coordinator.prepare(tx, generation, expected_revision)
        effects = proposal.get("capability") == "native-recipient-save-effects-v1"
        if effects:
            from .trade_capability import native_effects_available
            if not native_effects_available(self.companion):
                raise ValueError("this original game cannot present and prepare native trade effects")
        choices = prepared_choices(self.coordinator, effects=effects)
        view = await self.coordinator.status()
        if view["state"] not in {"offering", "preparing"}:
            return await self._resume()
        await self.menu_session.open_trade_dialog(self._render(view, choices))
        while True:
            await self.coordinator.keepalive()
            view = await self.coordinator.status()
            if (view["state"] in {"offering", "preparing"}
                    and (view.get("capability") == "native-recipient-save-effects-v1") != effects):
                raise ValueError("trade capability changed after preparing the original party")
            if (view["state"] == "preparing" and self.companion.config.player_id not in view["prepared"]
                    and not self.effect_paused):
                prior = self.screen
                screen = self._render(view, choices)
                if screen != prior:
                    self.menu_session.show_dialog(screen)
                if effects:
                    await self.menu_session.close_dialog(self.screen)
                    result = await self.coordinator.prepare_effect_recipient(self.menu_session)
                    self.effect_paused = result is None
                    view = await self.coordinator.status() if result is None else result
                    if view["state"] not in {"offering", "preparing"}:
                        return await self._resume()
                    self.revision = max(self.revision, self.menu_session._last_request.screen,
                                        self.menu_session.menu.screen.revision)
                    self.signature = None
                    await self.menu_session.open_trade_dialog(self._render(view, choices))
                else:
                    view = await self.coordinator.prepare_recipient()
            if view["state"] not in {"offering", "preparing"}:
                # Native import/reload can only begin after its UI relinquishes
                # the window and field locks, even when the other actor commits.
                await self.menu_session.close_dialog(self.screen)
                return await self._resume()
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
            elif op == "inspect":
                await self._inspect(view, value)
            elif op == "detail_page":
                self.detail_page = value
            elif op == "blocked":
                self.blocked_serial, self.page = value, "blocked"
            elif op == "review":
                self.page = "review"
            elif op == "confirm":
                view = await self.coordinator.confirm(value)
            elif op == "resume_effect":
                self.effect_paused = False
            elif op == "cancel":
                # The coordinator owns both the durable pending intent and
                # native terminal release. Relinquish this window first, then
                # let that owner resolve cancellation versus a concurrent commit.
                await self.menu_session.close_dialog(self.screen)
                self.cancelled_here = True
                return self._completion(await self.coordinator.cancel())
            else:
                self.page = "party"
            if view["state"] in {"offering", "preparing"}:
                self.menu_session.show_dialog(self._render(view, choices))

    def _completion(self, result):
        if isinstance(result, dict) and result.get("state") == "applied":
            received = result.get("received")
            if received is not None:
                label = species_label(received["species"])
                self.menu_session.menu._notice = (("Evolved: " if received["evolved"] else "Received: ") + label)[:31]
            else:
                self.menu_session.menu._notice = "Trade completed and saved"
        return result

    async def _resume(self):
        return self._completion(await self.coordinator.resume())
