"""Background work for the in-game menu: one asyncio job on its own thread, polled by the menu loop.

The menu loop is synchronous (it waits for the player's next choice); anything that takes time - checking a server, creating a world,
a character's first-time setup - runs here and reports a status code the menu turns into a message. A job can be cancelled; it then
raises CancelledError inside its coroutine so its ``finally`` blocks release leases and child processes exactly as they do for the
launcher's own workers.
"""
from __future__ import annotations

import asyncio
import threading


class BackgroundJob:
    def __init__(self, factory, name="emerald-menu-job"):
        self.status = ""
        self.detail = None
        self.result = None
        self.error = None
        self.cancelled = False
        self._loop = self._task = None
        self._lock = threading.Lock()
        self._finished = threading.Event()
        self._factory = factory
        self._thread = threading.Thread(target=self._run, name=name, daemon=False)
        self._thread.start()

    def progress(self, status, detail=None):
        self.status, self.detail = status, detail

    @property
    def done(self):
        return self._finished.is_set()

    def _run(self):
        try:
            asyncio.run(self._main())
        except asyncio.CancelledError:
            self.cancelled = True
        except BaseException as error:                    # noqa: BLE001 - reported to the menu, never lost
            self.error = error
        finally:
            self._finished.set()

    async def _main(self):
        with self._lock:
            self._loop, self._task = asyncio.get_running_loop(), asyncio.current_task()
            if self.cancelled:
                raise asyncio.CancelledError()
        self.result = await self._factory(self)

    def cancel(self):
        with self._lock:
            self.cancelled = True
            if self._loop is not None and self._task is not None and not self._finished.is_set():
                self._loop.call_soon_threadsafe(self._task.cancel)

    def wait(self, timeout=None):
        self._finished.wait(timeout)
        return self.done
