"""Worker threads started from Tk code pause the cyclic collector during Thread.start() (emerald_multiplayer/tk_threads.py).

The app suite once hung for good in test_launcher_menu: the Tk thread waited in Thread.start() inside a Tk callback while the
starting thread, running the cyclic collector, freed a tkinter Variable whose __del__ needed the Tk thread. The deadlock depends
on when the collector happens to run, so it cannot be forced reliably; these tests pin the guard and keep every Tk module on it.
"""
import ast
import gc
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from emerald_multiplayer.tk_threads import start_thread

SRC = Path(__file__).resolve().parents[1] / "src" / "emerald_multiplayer"


class StartThreadTests(unittest.TestCase):
    def tearDown(self):
        gc.enable()

    def test_the_collector_is_paused_while_the_thread_starts_and_enabled_again(self):
        seen = []
        original = threading.Thread.start

        def start(thread):
            seen.append(gc.isenabled())
            original(thread)

        done = threading.Event()
        with patch.object(threading.Thread, "start", start):
            thread = start_thread(threading.Thread(target=done.set))
        thread.join(5)
        self.assertEqual(seen, [False])
        self.assertTrue(done.is_set())
        self.assertTrue(gc.isenabled())

    def test_a_collector_already_disabled_stays_disabled(self):
        gc.disable()
        start_thread(threading.Thread(target=lambda: None)).join(5)
        self.assertFalse(gc.isenabled())

    def test_a_failing_start_still_restores_the_collector(self):
        thread = threading.Thread(target=lambda: None)
        thread.start()
        thread.join(5)
        with self.assertRaises(RuntimeError):
            start_thread(thread)  # a thread can only be started once
        self.assertTrue(gc.isenabled())


class TkModulesUseTheGuardTests(unittest.TestCase):
    def test_no_tk_module_starts_a_thread_directly(self):
        offenders = []
        for path in sorted(SRC.glob("*.py")):
            text = path.read_text()
            if "tkinter" not in text or path.name == "tk_threads.py":
                continue
            for node in ast.walk(ast.parse(text)):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "start"
                        and not node.args and not node.keywords):
                    target = node.func.value
                    names = ast.unparse(target)
                    if "Thread(" in names or "thread" in names.lower():
                        offenders.append(f"{path.name}:{node.lineno}: {names}.start()")
        self.assertEqual(offenders, [], "start worker threads from Tk code with tk_threads.start_thread")


if __name__ == "__main__":
    unittest.main()
