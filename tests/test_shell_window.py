"""The real menu window: the game's own executable running ``--shell`` on a virtual X display (software rendering, no GPU).

Skipped, and reported as skipped, when the engine binary or Xvfb is missing: a skip is not a pass. Set EMERALD_ENGINE_BINARY to the
native Classic or 3D game built from the engine branch that contains src/platform/shell_menu.c.
"""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import unittest
import zlib

from emerald_multiplayer.shell_protocol import Screen, ShellClosed, ShellProcess

ENGINE = Path(os.environ.get("EMERALD_ENGINE_BINARY", "/home/user/personal-pokemon-game-emgba3d-engine/pokeemerald-mp"))


def read_png(path):
    """(width, height, rows of RGB bytes) for the engine's 8-bit RGB PNG."""
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, width = 8, b"", 0
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", chunk[:10])
            assert depth == 8 and color == 2
        elif kind == b"IDAT":
            idat += chunk
        pos += 12 + length
    raw, stride, rows, prior = zlib.decompress(idat), width * 3, [], bytearray(width * 3)
    for y in range(height):
        kind, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - 3] if i >= 3 else 0
            b = prior[i]
            c = prior[i - 3] if i >= 3 else 0
            if kind == 1:
                line[i] = (line[i] + a) & 255
            elif kind == 2:
                line[i] = (line[i] + b) & 255
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        prior = line
    return width, height, rows


def pixel(image, x, y):
    return tuple(image[2][y][x * 3:x * 3 + 3])


@unittest.skipUnless(ENGINE.is_file() and shutil.which("Xvfb"), "the engine binary or Xvfb is not available (skipped, not passed)")
class ShellWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        number = 90 + os.getpid() % 100
        self.xvfb = subprocess.Popen(["Xvfb", f":{number}", "-screen", "0", "1280x800x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.xvfb.terminate)
        time.sleep(1.0)
        runtime = Path(self.temp.name) / "xdg"
        runtime.mkdir(mode=0o700)
        self.shell = ShellProcess([str(ENGINE), "--shell", "--shell-size", "1280x720"], environment={
            "DISPLAY": f":{number}", "PKMN_SHELL_TEST": "1", "XDG_RUNTIME_DIR": str(runtime), "SDL_AUDIODRIVER": "dummy",
            "SDL_RENDER_DRIVER": "software"})
        self.addCleanup(self.shell.close)

    def main_screen(self):
        screen = Screen("main", "Main menu", "EmeraldTogether test")
        for identifier, label in (("continue", "Continue Adventure"), ("new", "New Game"), ("host", "Host Server"),
                                  ("join", "Join Server"), ("settings", "Settings"), ("exit", "Exit")):
            screen.row(identifier, label, "detail " + identifier, "s" if identifier == "continue" else "")
        screen.set_status("info", "Game files verified.")
        return screen

    def show_async(self, screen):
        """Send a screen without waiting for the player's answer (the test plays the player)."""
        self.shell.token += 1
        self.shell.send(*screen.lines(self.shell.token))
        return self.shell.token

    def wait_event(self, token, timeout=10):
        from emerald_multiplayer.shell_protocol import parse_event
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.shell.lines.get(timeout=0.2)
            except Exception:
                continue
            if line is None:
                raise ShellClosed("closed")
            event = parse_event(line, token)
            if event is not None:
                return event
        raise TimeoutError("no event")

    def shot(self, name):
        path = Path(self.temp.name) / name
        self.assertEqual(self.shell.request(f"shot\t{path}"), "shot\tok")
        if os.environ.get("EMERALD_SHELL_SHOTS"):
            shutil.copy(path, Path(os.environ["EMERALD_SHELL_SHOTS"]) / name)
        return read_png(path)

    def test_the_menu_draws_in_the_games_window_with_the_custom_theme(self):
        token = self.show_async(self.main_screen())
        time.sleep(0.8)
        image = self.shot("main.png")
        self.assertEqual(image[:2], (1280, 720))
        self.assertEqual(pixel(image, 20, 20), (0x0E, 0x5A, 0x3F))             # the launcher's green header band
        self.assertEqual(pixel(image, 640, 700), (0xF2, 0xF6, 0xF0))           # the paper background
        # A white card with the accent border under the focused first row.
        self.assertEqual(pixel(image, 700, 250), (0xE3, 0xF3, 0xE8))
        self.assertEqual(self.shell.request("state").split("\t")[3], "continue")

    def test_keyboard_navigation_selects_the_row_and_reports_it_once(self):
        token = self.show_async(self.main_screen())
        time.sleep(0.5)
        self.shell.send("inject\tkey\tDown")
        self.shell.send("inject\tkey\tDown")
        time.sleep(0.3)
        self.assertEqual(self.shell.request("state").split("\t")[3], "host")
        self.shell.send("inject\tkey\tReturn")
        event = self.wait_event(token)
        self.assertEqual((event.kind, event.id), ("select", "host"))
        # Input is locked until the application answers: a second Enter does nothing.
        self.shell.send("inject\tkey\tReturn")
        self.assertEqual(self.shell.request("state").split("\t")[4], "1")
        token = self.show_async(self.main_screen())
        self.shell.send("inject\tkey\tEscape")
        self.assertEqual(self.wait_event(token).kind, "back")

    def test_text_fields_take_typing_and_a_pasted_invite_code_and_report_their_values(self):
        screen = Screen("join_new", "Join New Server")
        screen.field("code", "Invite code", "", "m")
        screen.field("name", "Name", "", "l12")
        screen.field("port", "Port", "", "n")
        screen.button("join", "Check and join", "a")
        token = self.show_async(screen)
        time.sleep(0.5)
        code = "ET1-ABCDE-FGHIJ-KLMNO " * 20
        self.shell.copy_text(code)
        time.sleep(0.3)
        self.shell.send("inject\tkey\tv\tctrl")
        self.shell.send("inject\tkey\tTab")
        self.shell.send("inject\ttext\tMy friend's server is long")
        self.shell.send("inject\tkey\tTab")
        self.shell.send("inject\ttext\t77x77")
        time.sleep(0.3)
        image = self.shot("fields.png")
        self.shell.send("inject\tkey\tTab")
        self.shell.send("inject\tkey\tReturn")
        event = self.wait_event(token)
        self.assertEqual((event.kind, event.id), ("select", "join"))
        self.assertEqual(event.fields["code"], code.replace(" ", ""))             # spaces and line breaks of a paste are dropped
        self.assertEqual(len(event.fields["name"]), 12)                            # the field's own limit
        self.assertEqual(event.fields["port"], "7777")                             # digits only

    def test_a_long_list_scrolls_and_the_window_can_be_made_small_for_the_session(self):
        screen = Screen("list", "Many")
        for index in range(30):
            screen.row(f"r{index}", f"Row number {index}", "d", "s" if index == 0 else "")
        token = self.show_async(screen)
        time.sleep(0.4)
        for _ in range(20):
            self.shell.send("inject\tkey\tDown")
        time.sleep(0.4)
        self.assertEqual(self.shell.request("state").split("\t")[3], "r20")
        self.shell.window(560, 420, 40, 40)
        time.sleep(0.5)
        image = self.shot("small.png")
        self.assertEqual(image[:2], (560, 420))

    def test_a_key_row_captures_the_next_key_and_esc_cancels_it(self):
        screen = Screen("controls", "Controls")
        screen.row("a_a", "A button", "Z", "ks")
        screen.row("a_b", "B button", "X", "k")
        token = self.show_async(screen)
        time.sleep(0.4)
        self.shell.send("inject\tkey\tReturn")        # start capturing on the first row
        time.sleep(0.2)
        self.shell.send("inject\tkey\tEscape")        # cancelled: nothing reported, the screen is still live
        time.sleep(0.2)
        self.assertEqual(self.shell.request("state").split("\t")[4], "0")
        self.shell.send("inject\tkey\tReturn")
        time.sleep(0.2)
        self.shell.send("inject\tkey\tx")
        event = self.wait_event(token)
        self.assertEqual((event.kind, event.id, event.fields.get("key")), ("select", "a_a", "X"))

    def test_the_menu_ends_when_the_application_goes_away(self):
        self.show_async(self.main_screen())
        self.shell.process.stdin.close()
        self.assertEqual(self.shell.process.wait(timeout=10), 3)

    def test_closing_the_window_is_reported(self):
        token = self.show_async(self.main_screen())
        self.shell.send("quit")
        self.assertEqual(self.wait_event(token).kind, "closed")
        self.assertEqual(self.shell.process.wait(timeout=10), 0)


if __name__ == "__main__":
    unittest.main()
