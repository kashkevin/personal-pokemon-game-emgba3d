"""Starting worker threads from Tk code without the cyclic-GC deadlock.

tkinter objects that sit in reference cycles (a ``StringVar`` kept by a closure, a widget kept by a bound method, ...) are
freed by whichever thread happens to run Python's cyclic garbage collector. Their ``__del__`` runs a Tcl command, and with a
threaded Tcl that command is handed to the Tk thread and waited for. If the collector runs in a thread that is still
starting up while the Tk thread is itself blocked in ``Thread.start()`` inside a Tk callback (a button handler), each waits
for the other forever. The app suite hung exactly so in ``launcher_gui`` (``LauncherController.start`` -> ``Thread.start``,
the new thread in ``Variable.__del__`` during its bootstrap).

``start_thread`` pauses the cyclic collector for the duration of ``Thread.start()`` only. Once ``start()`` has returned
the Tk thread runs its event loop again and serves any such Tcl call, so nothing can wait forever.
"""
from __future__ import annotations

import gc
import threading


def start_thread(thread: threading.Thread) -> threading.Thread:
    """``thread.start()`` with the cyclic garbage collector paused for the call; the previous GC state is restored."""
    enabled = gc.isenabled()
    gc.disable()
    try:
        thread.start()
    finally:
        if enabled:
            gc.enable()
    return thread
