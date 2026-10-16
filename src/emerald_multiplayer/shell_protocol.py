"""The application's side of the pre-game menu (engine ``src/platform/shell_menu.c``, ``include/platform/shell_menu.h``).

A ``Screen`` is a description - title, rows, text fields, buttons, a status line - and ``ShellProcess.show`` sends it to the menu
window and waits for what the person chose (an ``Event``). The window draws and reports; every decision stays here. The same
interface is implemented by ``ScriptedShell`` for tests, so the whole menu logic runs with no window.

Line protocol: one command a line, fields separated by TAB; text escapes ``\\\\``, ``\\t``, ``\\n``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
import queue
import subprocess
import threading
import time

PROTOCOL = 1
MAX_ITEMS = 48


def escape(text):
    text = str(text).replace("\r", "")
    return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def unescape(text):
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            i += 1
            out.append({"t": "\t", "n": "\n"}.get(text[i], text[i]))
        else:
            out.append(c)
        i += 1
    return "".join(out)


@dataclass
class Item:
    kind: str                 # "row", "field", "button"
    id: str
    label: str
    detail: str = ""          # rows: the text on the right (or the second line); fields: the value
    flags: str = ""


@dataclass
class Screen:
    id: str
    title: str
    sub: str = ""
    notes: list = field(default_factory=list)
    items: list = field(default_factory=list)
    status: tuple | None = None       # (kind, text)
    hint: str = ""

    def row(self, id, label, detail="", flags=""):
        self.items.append(Item("row", id, label, detail, flags))
        return self

    def field(self, id, label, value="", flags=""):
        self.items.append(Item("field", id, label, value, flags))
        return self

    def button(self, id, label, flags=""):
        self.items.append(Item("button", id, label, "", flags))
        return self

    def note(self, text):
        self.notes.append(text)
        return self

    def set_status(self, kind, text):
        self.status = (kind, text)
        return self

    def lines(self, token):
        out = [f"screen\t{escape(self.id)}\t{token}", f"title\t{escape(self.title)}"]
        if self.sub:
            out.append(f"sub\t{escape(self.sub)}")
        for note in self.notes:
            out.append(f"note\t{escape(note)}")
        for item in self.items[:MAX_ITEMS]:
            if item.kind == "row":
                out.append(f"row\t{escape(item.id)}\t{escape(item.label)}\t{escape(item.detail)}\t{item.flags}")
            elif item.kind == "field":
                out.append(f"field\t{escape(item.id)}\t{escape(item.label)}\t{escape(item.detail)}\t{item.flags}")
            else:
                out.append(f"button\t{escape(item.id)}\t{escape(item.label)}\t{item.flags}")
        if self.status:
            out.append(f"status\t{escape(self.status[0])}\t{escape(self.status[1])}")
        if self.hint:
            out.append(f"hint\t{escape(self.hint)}")
        out.append("end")
        return out


@dataclass
class Event:
    kind: str                 # "select", "back", "closed", "tick", "gone"
    id: str = ""
    fields: dict = field(default_factory=dict)
    value: object = None      # a tick's result


class ShellClosed(Exception):
    """The window was closed or the menu process ended: the application should quit."""


@dataclass
class Done:
    """What a ``tick`` returns to make ``show`` return (a background job finished)."""
    value: object = None


def parse_event(line, token):
    """An 'event' line for the screen with this token, or None for any other (a late event of an earlier screen)."""
    parts = line.split("\t")
    if len(parts) < 4 or parts[0] != "event":
        return None
    try:
        if int(parts[1]) != token:
            return None
    except ValueError:
        return None
    rest = [unescape(part) for part in parts[4:]]
    fields = {rest[i]: rest[i + 1] for i in range(0, len(rest) - 1, 2)}
    return Event(parts[2], unescape(parts[3]), fields)


class ShellProcess:
    """The menu window as a child process of the game's own executable (``pokeemerald-mp --shell``)."""

    def __init__(self, command, *, environment=None, cwd=None):
        env = dict(os.environ)
        env.update(environment or {})
        options = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, cwd=cwd, bufsize=0)
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        self.process = subprocess.Popen(list(command), **options)
        self.lines = queue.Queue()
        self.token = 0
        self._screen = None
        self.ready = threading.Event()
        self.error = None
        self._reader = threading.Thread(target=self._read, name="shell-menu-reader", daemon=True)
        self._reader.start()
        if not self.ready.wait(20) or self.error is not None:
            self.close()
            raise ShellClosed(self.error or "the menu window did not start")

    def _read(self):
        try:
            for raw in iter(self.process.stdout.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("ready\t"):
                    self.ready.set()
                elif line.startswith("error\t"):
                    self.error = line.split("\t", 2)[-1]
                    self.ready.set()
                else:
                    self.lines.put(line)
        finally:
            self.lines.put(None)
            self.ready.set()

    def send(self, *lines):
        try:
            self.process.stdin.write(("\n".join(lines) + "\n").encode("utf-8"))
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise ShellClosed("the menu window closed") from None

    def show(self, screen, tick=None, interval=0.2):
        self.token += 1
        token = self.token
        self._screen = screen
        self.send(*screen.lines(token))
        while True:
            try:
                line = self.lines.get(timeout=interval)
            except queue.Empty:
                line = ""
            if line is None:
                raise ShellClosed("the menu window closed")
            if line:
                event = parse_event(line, token)
                if event is not None:
                    if event.kind == "closed":
                        raise ShellClosed("the menu window was closed")
                    return event
                continue
            if tick is not None:
                result = tick()
                if isinstance(result, Done):
                    return Event("tick", value=result.value)
                if isinstance(result, Screen):
                    self.send(*result.lines(token))

    def request(self, command, timeout=10):
        """A test-only command (PKMN_SHELL_TEST=1) and its one-line answer."""
        self.send(command)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                raise ShellClosed("the menu window closed")
            if line.startswith(("shot\t", "state\t")):
                return line
        raise TimeoutError(command)

    def copy_text(self, text):
        self.send(f"clipboard\t{escape(text)}")

    def window(self, width, height, x=-1, y=-1):
        self.send(f"window\t{int(width)}\t{int(height)}\t{int(x)}\t{int(y)}")

    def close(self):
        try:
            self.send("quit")
        except ShellClosed:
            pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


class ScriptedShell:
    """The same interface with no window: ``responder(screen)`` returns what the person does on that screen.

    The responder returns ``(kind, id, fields)`` (or a bare ``(kind, id)``), may inspect ``screen`` to find a row's id, and raises
    ``ShellClosed`` to close the window. Every screen shown is kept in ``shown``. A tick runs once per screen so background jobs
    complete; when it returns ``Done`` the responder is not asked.
    """

    def __init__(self, responder):
        self.responder = responder
        self.shown = []
        self.copied = []
        self.windows = []
        self.max_screens = 500

    def show(self, screen, tick=None, interval=0.2):
        self.shown.append(screen)
        if len(self.shown) > self.max_screens:
            raise ShellClosed("the scripted menu ran too long")
        if tick is not None:
            for _ in range(6000):
                result = tick()
                if isinstance(result, Done):
                    return Event("tick", value=result.value)
                if isinstance(result, Screen):
                    self.shown.append(result)
                    screen = result
                if getattr(self, "tick_once", False):
                    break
                answer = self.responder(screen, waiting=True) if _accepts_waiting(self.responder) else None
                if answer is not None:
                    return _event(answer)
                time.sleep(0.01)
            raise ShellClosed("background work never finished")
        answer = self.responder(screen) if not _accepts_waiting(self.responder) else self.responder(screen, waiting=False)
        return _event(answer)

    def copy_text(self, text):
        self.copied.append(text)

    def window(self, width, height, x=-1, y=-1):
        self.windows.append((width, height, x, y))

    def close(self):
        pass


def _accepts_waiting(function):
    try:
        import inspect
        return "waiting" in inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False


def _event(answer):
    if isinstance(answer, Event):
        return answer
    kind, *rest = answer
    identifier = rest[0] if rest else ""
    fields = rest[1] if len(rest) > 1 else {}
    return Event(kind, identifier, dict(fields))

