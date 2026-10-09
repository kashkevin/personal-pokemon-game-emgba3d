"""Personal encounter availability and retry of one retained admission only."""
from copy import deepcopy
from uuid import uuid4

from .reset_catalogue import reset_controls, reset_source_catalogue
from .reset_session import reset_status, retry_reset_admission


class ResetPanelError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ResetPanelController:
    def __init__(self, session):
        self.session = session
        self._binding = self._snapshot_id = self._retry_id = self._status = None
        self._busy = False

    def _identity(self):
        s, c = self.session, self.session.companion
        if (c is None or not c.connected or not s._open or s._closing or s._game is None
                or s._game.process.returncode is not None or s._signature() != s._binding):
            raise ResetPanelError("connection_lost")
        return (c, s._signature(), s._game, c._bridge, getattr(c._bridge, "incarnation", None),
                getattr(c._bridge, "reset_session", None))

    async def dispatch(self, snapshot_id=None, action_id=None):
        if self._busy:
            raise ResetPanelError("busy")
        self._busy = True
        try:
            original = self._identity()
            c = self.session.companion
            if snapshot_id is not None or action_id is not None:
                status = reset_status(c)
                token = self._retry_id
                self._retry_id = None
                if (snapshot_id != self._snapshot_id or not token or action_id != token
                        or original != self._binding or status != self._status):
                    raise ResetPanelError("stale")
                if not status["can_retry"] or not self.session.can_manage_players:
                    raise ResetPanelError("not_ready")
                await retry_reset_admission(c)
                if self._identity() != original:
                    raise ResetPanelError("connection_lost")
            self._binding = original
            self._status = reset_status(c)
            self._snapshot_id = str(uuid4())
            self._retry_id = str(uuid4()) if self._status["can_retry"] and self.session.can_manage_players else None
            return deepcopy(dict(snapshot_id=self._snapshot_id, retry_action=self._retry_id,
                status=self._status, sources=reset_source_catalogue(c.config), controls=reset_controls(c.config)))
        except BaseException:
            self._retry_id = None
            raise
        finally:
            self._busy = False


STATE_TEXT = {
    "unavailable": "No verified native admission session is available.",
    "idle": "No personal encounter admission is pending.",
    "queued": "The exact personal admission is queued.",
    "requesting": "Waiting for the host to acknowledge this admission.",
    "awaiting_native": "Host admitted the attempt; waiting for the native acknowledgment.",
    "retry_wait": "The host outcome is uncertain. Retry is available only for this same retained admission.",
    "blocked": "Another lifecycle or retained evidence blocks this admission. Keep the original game open.",
    "generation_released": "Native acknowledged release for generation. Generated, shiny and capture outcomes remain UNKNOWN.",
    "denied": "This admission was denied; the authored game script handles its ordinary return.",
    "cancelled": "Native canceled this pre-generation admission. Field readiness is shown separately.",
    "retained": "This original admission is retained after its authenticated session changed. Follow the main recovery status.",
}


class ResetPanel:
    def __init__(self, parent, worker):
        import tkinter as tk
        from tkinter import ttk
        from .launcher_display import scrollable_frame
        self.worker = worker
        self._connected = self._eligible = self._pending = self._closed = self._suspended = False
        self._snapshot = None
        self.frame = scrollable_frame(parent)
        actions = ttk.Frame(self.frame)
        actions.pack(fill="x")
        self.refresh_button = ttk.Button(actions, text="Refresh reset status", command=self.refresh, state="disabled")
        self.refresh_button.pack(side="left")
        self.retry_button = ttk.Button(actions, text="Retry pending admission", command=self.retry, state="disabled")
        self.retry_button.pack(side="left", padx=8)
        self.message = tk.StringVar(value="Open your character, then read its compiled catalogue and current admission.")
        ttk.Label(self.frame, textvariable=self.message, wraplength=550).pack(anchor="w", pady=8)
        self.status = tk.StringVar()
        ttk.Label(self.frame, textvariable=self.status, wraplength=550).pack(anchor="w", pady=8)
        self.controls = tk.StringVar()
        ttk.Label(self.frame, textvariable=self.controls, wraplength=550).pack(anchor="w", pady=8)
        table_frame = ttk.Frame(self.frame)
        table_frame.pack(fill="x")
        self.sources = ttk.Treeview(table_frame, columns=("source", "available", "eligible"), show="headings", height=10, selectmode="browse")
        for name, label, width in (("source", "Personal encounter", 290), ("available", "Compiled adapter", 125), ("eligible", "Eligible now?", 110)):
            self.sources.heading(name, text=label)
            self.sources.column(name, width=width, minwidth=50)
        bar = ttk.Scrollbar(table_frame, orient="vertical", command=self.sources.yview)
        bar.pack(side="right", fill="y")
        self.sources.configure(yscrollcommand=bar.set)
        self.sources.pack(fill="x")
        ttk.Label(self.frame, text="Enabled means this exact ROM declares its adapter; tickets, progression, object visibility and first-action guards still apply. Unknown means an older build does not advertise the catalogue. Retry resends one exact retained request ID. It never creates a new encounter roll, resets the emulator or changes shiny odds. Use normal encounter interaction and in-game reset confirmation.", wraplength=550).pack(anchor="w", pady=10)

    def refresh(self):
        self._request()

    def retry(self):
        if self._snapshot and self._snapshot["retry_action"]:
            self._request(self._snapshot["retry_action"])

    def _request(self, token=None):
        if self._closed or self._suspended or self._pending or not self._connected or self.worker is None:
            return
        snapshot = self._snapshot["snapshot_id"] if token else None
        if self.worker.request_reset_panel(snapshot, token):
            self._pending = True
            self._enable()

    def _enable(self):
        available = self._connected and not (self._pending or self._closed or self._suspended)
        self.refresh_button.configure(state="normal" if available else "disabled")
        self.retry_button.configure(state="normal" if available and self._eligible and self._snapshot
            and self._snapshot["retry_action"] else "disabled")

    def _render(self, snapshot):
        self._snapshot = snapshot
        status, controls = snapshot["status"], snapshot["controls"]
        self.message.set(STATE_TEXT[status["state"]])
        self.status.set(("Source: " + status["source_name"] + "\n" if status["source_name"] else "")
            + "Observed prior count: " + str(status["observed_count"] if status["observed_count"] is not None else "UNKNOWN")
            + " · Host attempt: " + str(status["host_attempt"] if status["host_attempt"] is not None else "UNKNOWN")
            + " · Native attempt: " + str(status["native_attempt"] if status["native_attempt"] is not None else "UNKNOWN")
            + "\nField-ready receipt: " + ("UNKNOWN" if status["field_ready"] is None else "Yes" if status["field_ready"] else "No"))
        self.controls.set("Compiled reset controls: " + controls["status"].upper() + "\n"
            + "\n".join(controls[k] for k in ("entry", "select", "chord", "confirmation", "window", "exclusions")))
        for item in self.sources.get_children():
            self.sources.delete(item)
        for row in snapshot["sources"]:
            self.sources.insert("", "end", values=(row["name"], row["availability"].capitalize(), row["eligibility"]))

    def handle_event(self, event):
        if self._closed:
            return event.kind == "reset_panel"
        if event.kind == "reset_panel":
            self._pending = False
            if event.code == "ready" and self._connected and event.reset_snapshot is not None:
                self._render(event.reset_snapshot)
            else:
                if self._snapshot:
                    self._snapshot["retry_action"] = None
                self.message.set("Reset status changed or could not be read. Refresh the exact pending admission; keep the original game open and follow the main recovery status.")
            self._enable()
            return True
        if event.kind in {"status", "complete"}:
            connected = event.kind == "status" and event.state == "running" and event.connected
            if self._connected and not connected:
                if self._snapshot:
                    self._snapshot["retry_action"] = None
                self.message.set("Connection ended. Displayed reset facts are an earlier snapshot; follow the main recovery status.")
            self._connected = connected
            self._eligible = connected and event.player_actions_available
            self._enable()
        return False

    def set_closing(self, value):
        self._suspended = bool(value)
        self._enable()

    def close(self):
        self._closed = True
        self._enable()
