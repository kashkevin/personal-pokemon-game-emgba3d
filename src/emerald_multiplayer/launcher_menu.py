"""The launcher's main menu and its shared look (Update 28).

One window, one flow: Continue Adventure, My Worlds, Host Multiplayer, Join Friend, Settings, Exit Game. This module is only
the widgets (theme, the menu card list, the page header, the confirmation bar); what each choice does stays in
launcher_gui.LauncherWindow, which already owns the session worker, the graphics check and the recovery state. Mouse and
keyboard work everywhere (Up/Down/Enter, the highlighted letters, Esc to go back). A game controller is not read by the
launcher; it works in the game once that opens.
"""
from __future__ import annotations

PALETTE = dict(
    ink="#14261E", muted="#52635C", paper="#F2F6F0", panel="#FFFFFF", header="#0E5A3F", header_dark="#093F2C",
    accent="#1FA463", accent_dark="#15804C", highlight="#E3F3E8", edge="#CFE0D4", warn="#B3261E", warn_bg="#FCE9E7",
    gold="#F2C14E", ball_red="#D8433A",
)


def fonts():
    """(title, heading, body, small) as Tk font tuples; Segoe UI on Windows, Tk's own default elsewhere."""
    family = "Segoe UI"
    return (family, 26, "bold"), (family, 14, "bold"), (family, 10), (family, 9)


def apply_theme(root):
    """The launcher's colours on the ttk widgets every page uses. Safe to call again."""
    from tkinter import ttk
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    p = PALETTE
    root.configure(background=p["paper"])
    style.configure(".", background=p["paper"], foreground=p["ink"])
    style.configure("TFrame", background=p["paper"])
    style.configure("TLabel", background=p["paper"], foreground=p["ink"])
    style.configure("TCheckbutton", background=p["paper"], foreground=p["ink"])
    style.configure("TRadiobutton", background=p["paper"], foreground=p["ink"])
    style.configure("TNotebook", background=p["paper"], bordercolor=p["edge"])
    style.configure("TNotebook.Tab", padding=(12, 6), background=p["highlight"], foreground=p["ink"])
    style.map("TNotebook.Tab", background=[("selected", p["panel"])])
    style.configure("TSeparator", background=p["edge"])
    style.configure("TButton", padding=(10, 5))
    style.configure("Accent.TButton", background=p["accent"], foreground="white", padding=(14, 7))
    style.map("Accent.TButton", background=[("active", p["accent_dark"]), ("disabled", p["edge"])],
              foreground=[("disabled", p["muted"])])
    style.configure("Muted.TLabel", foreground=p["muted"])
    style.configure("Heading.TLabel", font=fonts()[1])
    style.configure("Warn.TLabel", foreground=p["warn"])
    style.configure("Treeview", background=p["panel"], fieldbackground=p["panel"])
    return style


def draw_ball(canvas, x, y, r):
    """A plain red-and-white ball for the header (drawn here; no image file)."""
    p = PALETTE
    canvas.create_oval(x - r, y - r, x + r, y + r, fill="white", outline=p["ink"], width=2)
    canvas.create_arc(x - r, y - r, x + r, y + r, start=0, extent=180, fill=p["ball_red"], outline=p["ink"], width=2)
    canvas.create_line(x - r, y, x + r, y, fill=p["ink"], width=3)
    canvas.create_oval(x - r // 3, y - r // 3, x + r // 3, y + r // 3, fill="white", outline=p["ink"], width=2)


class Header:
    """The green band at the top of the main menu."""

    def __init__(self, parent, title, subtitle):
        import tkinter as tk
        p = PALETTE
        self.canvas = tk.Canvas(parent, height=96, highlightthickness=0, background=p["header"])
        self.canvas.pack(fill="x")
        draw_ball(self.canvas, 52, 48, 26)
        self.canvas.create_text(100, 38, text=title, anchor="w", fill="white", font=fonts()[0])
        self.canvas.create_text(102, 70, text=subtitle, anchor="w", fill="#BFE3CF", font=fonts()[2])
        self.canvas.create_rectangle(0, 92, 4000, 96, fill=p["gold"], outline=p["gold"])


class MenuCard:
    """One big choice: a title, a line under it, and a chevron. Clickable and keyboard focusable."""

    def __init__(self, parent, key, letter, title, subtitle, command):
        import tkinter as tk
        p = PALETTE
        self.key, self.letter, self.command, self.enabled = key, letter, command, True
        self.frame = tk.Frame(parent, background=p["panel"], highlightthickness=2, highlightbackground=p["edge"],
                              highlightcolor=p["accent"], cursor="hand2", takefocus=1)
        bar = tk.Frame(self.frame, width=8, background=p["accent"])
        bar.pack(side="left", fill="y")
        self.bar = bar
        text = tk.Frame(self.frame, background=p["panel"])
        text.pack(side="left", fill="both", expand=True, padx=14, pady=5)
        self.title = tk.Label(text, text=title, anchor="w", background=p["panel"], foreground=p["ink"], font=fonts()[1])
        self.title.pack(fill="x")
        self.subtitle = tk.Label(text, text=subtitle, anchor="w", justify="left", background=p["panel"], foreground=p["muted"],
                                 font=fonts()[2], wraplength=520)
        self.subtitle.pack(fill="x")
        self.chevron = tk.Label(self.frame, text="›", background=p["panel"], foreground=p["accent_dark"], font=("Segoe UI", 26))
        self.chevron.pack(side="right", padx=16)
        self.parts = (self.frame, text, self.title, self.subtitle, self.chevron)
        for part in self.parts:
            part.bind("<Enter>", lambda _: self._hover(True))
            part.bind("<Leave>", lambda _: self._hover(False))
            part.bind("<Button-1>", lambda _: self.frame.focus_set())
            part.bind("<ButtonRelease-1>", lambda _: self.invoke())
        self.frame.bind("<FocusIn>", lambda _: self._paint(True))
        self.frame.bind("<FocusOut>", lambda _: self._paint(False))
        self.frame.bind("<Return>", lambda _: self.invoke())
        self.frame.bind("<space>", lambda _: self.invoke())

    def _paint(self, active):
        p = PALETTE
        shade = p["highlight"] if active and self.enabled else p["panel"]
        for part in self.parts[1:]:
            part.configure(background=shade)
        self.frame.configure(background=shade)
        self.bar.configure(background=p["accent"] if self.enabled else p["edge"])

    def _hover(self, inside):
        self._paint(inside or self.frame.focus_get() is self.frame)

    def invoke(self):
        if self.enabled:
            self.command()
        return "break"

    def set(self, title=None, subtitle=None, enabled=None):
        p = PALETTE
        if title is not None:
            self.title.configure(text=title)
        if subtitle is not None:
            self.subtitle.configure(text=subtitle)
        if enabled is not None:
            self.enabled = enabled
            self.title.configure(foreground=p["ink"] if enabled else p["muted"])
            self.chevron.configure(foreground=p["accent_dark"] if enabled else p["edge"])
            self.frame.configure(cursor="hand2" if enabled else "arrow")
            self._paint(False)


class ConfirmBar:
    """An in-window yes/no question (no pop-up window): shown above the menu, answered with a click, Enter or Esc."""

    def __init__(self, parent, before=None):
        import tkinter as tk
        from tkinter import ttk
        p = PALETTE
        self.before = before     # the widget the bar is packed above (None: at the end)
        self.frame = tk.Frame(parent, background=p["warn_bg"], highlightthickness=1, highlightbackground=p["warn"])
        # the buttons first, so a long question never squeezes them
        self.no = ttk.Button(self.frame, text="Cancel", command=self.cancel)
        self.no.pack(side="right", padx=(6, 12), pady=8)
        self.yes = ttk.Button(self.frame, text="Yes", style="Accent.TButton", command=self.accept)
        self.yes.pack(side="right", pady=8)
        self.text = tk.Label(self.frame, background=p["warn_bg"], foreground=p["ink"], justify="left", anchor="w", wraplength=420,
                             font=fonts()[2])
        self.text.pack(side="left", fill="x", expand=True, padx=12, pady=8)
        self.on_yes = self.on_no = None
        self.visible = False
        self.frame.bind("<Escape>", lambda _: self.cancel())

    def ask(self, message, on_yes, on_no=None, yes="Yes", no="Cancel"):
        self.text.configure(text=message)
        self.yes.configure(text=yes)
        self.no.configure(text=no)
        self.on_yes, self.on_no = on_yes, on_no
        if not self.visible:
            options = dict(fill="x", padx=24, pady=(10, 0))
            if self.before is not None:
                options["before"] = self.before
            self.frame.pack(**options)
            self.visible = True
        self.yes.focus_set()

    def _close(self):
        if self.visible:
            self.frame.pack_forget()
            self.visible = False

    def accept(self):
        callback = self.on_yes
        self.on_yes = self.on_no = None
        self._close()
        if callback:
            callback()

    def cancel(self):
        callback = self.on_no
        self.on_yes = self.on_no = None
        self._close()
        if callback:
            callback()


class MainMenu:
    """The first thing the player sees. Cards are looked up by key: continue, worlds, host, join, settings, exit."""

    CARDS = (
        ("continue", "c", "Continue Adventure", "Pick up where you left off."),
        ("worlds", "w", "My Worlds", "Create a world, choose one, and set up the characters in it."),
        ("host", "h", "Host Multiplayer", "Start a world for up to three friends."),
        ("join", "j", "Join Friend", "Open your friend's invitation and join their world."),
        ("settings", "s", "Settings", "Graphics (3D or Classic 2D), controls and game files."),
        ("exit", "x", "Exit Game", "Close Emerald Together."),
    )

    def __init__(self, parent, actions, *, version=""):
        import tkinter as tk
        from tkinter import ttk
        p = PALETTE
        self.frame = ttk.Frame(parent)
        Header(self.frame, "Emerald Together", "Your world. Up to four players." + (f"   ·   {version}" if version else ""))
        self.confirm = ConfirmBar(self.frame)
        self.banner = tk.Label(self.frame, text="", anchor="w", justify="left", wraplength=640, background=p["warn_bg"],
                               foreground=p["ink"], font=fonts()[2], padx=12, pady=8)
        self.banner_shown = False
        self.list = ttk.Frame(self.frame, padding=(24, 14, 24, 6))
        self.list.pack(fill="both", expand=True)
        self.confirm.before = self.list
        self.cards = {}
        for key, letter, title, subtitle in self.CARDS:
            card = MenuCard(self.list, key, letter, title, subtitle, actions[key])
            card.frame.pack(fill="x", pady=5)
            self.cards[key] = card
        self.hint = ttk.Label(self.frame, style="Muted.TLabel", padding=(24, 0, 24, 8),
                              text="↑ ↓ choose   ·   Enter select   ·   Esc back   ·   or press the first letter of a choice")
        self.hint.pack(side="bottom", anchor="w")
        order = [self.cards[key[0]].frame for key in self.CARDS]
        for index, widget in enumerate(order):
            widget.bind("<Up>", lambda _, i=index: self._move(order, i, -1))
            widget.bind("<Down>", lambda _, i=index: self._move(order, i, 1))
        letters = {card.letter: card for card in self.cards.values()}
        self.frame.bind_all("<Key>", lambda event: self._letter(event, letters), add="+")

    def _move(self, order, index, step):
        order[(index + step) % len(order)].focus_set()
        return "break"

    def _letter(self, event, letters):
        # Only while the menu is the visible page, and only for a plain letter (never while typing in an entry).
        if not self.frame.winfo_ismapped() or getattr(event, "state", 0) & 0x4:
            return
        if event.widget.winfo_toplevel() is not self.frame.winfo_toplevel():
            return
        widget = self.frame.focus_get()
        if widget is not None and widget.winfo_class() in {"TEntry", "Entry", "TCombobox", "Text", "Spinbox"}:
            return
        card = letters.get((event.char or "").lower())
        if card is not None:
            card.frame.focus_set()
            card.invoke()

    def show_banner(self, text):
        if text:
            self.banner.configure(text=text)
            if not self.banner_shown:
                self.banner.pack(fill="x", padx=24, pady=(10, 0), before=self.list)
                self.banner_shown = True
        elif self.banner_shown:
            self.banner.pack_forget()
            self.banner_shown = False

    def focus_first(self):
        for key in ("continue", "worlds"):
            if self.cards[key].enabled:
                self.cards[key].frame.focus_set()
                return
        self.cards["worlds"].frame.focus_set()


class PageHeader:
    """‹ Main menu · Title at the top of every page the menu opens; Esc goes back."""

    def __init__(self, parent, title, on_back, *, back_text="‹ Main menu"):
        import tkinter as tk
        from tkinter import ttk
        p = PALETTE
        self.frame = tk.Frame(parent, background=p["header"])
        self.back = tk.Button(self.frame, text=back_text, command=on_back, relief="flat", background=p["header_dark"],
                              foreground="white", activebackground=p["accent_dark"], activeforeground="white", padx=12, pady=4,
                              font=fonts()[2], cursor="hand2", borderwidth=0)
        self.back.pack(side="left", padx=10, pady=8)
        self.title = tk.Label(self.frame, text=title, background=p["header"], foreground="white", font=fonts()[1])
        self.title.pack(side="left", padx=8)
        self.frame.pack(fill="x")
        tk.Frame(parent, height=3, background=p["gold"]).pack(fill="x")
        self.set_back_enabled(True)

    def set_back_enabled(self, enabled):
        self.back.configure(state="normal" if enabled else "disabled")
