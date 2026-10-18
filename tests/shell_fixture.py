"""Shared pieces for the in-game menu tests: a scripted player, a fake session worker, and real worlds on a temporary private folder."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import queue
import socket
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from emerald_multiplayer.launcher_gui import UiEvent
from emerald_multiplayer.launcher_session import GameInstallation
from emerald_multiplayer.shell_app import ShellApp
from emerald_multiplayer.shell_protocol import Screen, ScriptedShell
from test_host_world import make_trade_files
from test_player_runtime import write_bundle


def label_id(screen, label):
    """The id of the row or button with this label (or label prefix)."""
    for item in screen.items:
        if item.label == label or item.label.startswith(label):
            return item.id
    raise AssertionError(f"no '{label}' on {screen.id}: {[i.label for i in screen.items]}")


def labels(screen):
    return [item.label for item in screen.items]


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def fake_drafter(calls, personality=7):
    """The game's New Game: a valid new-character save in drafts/ (what DraftRuntime leaves after the player saved)."""
    async def drafter(installation, private_root, *, on_status=None):
        from uuid import uuid4
        from test_ownership_storage import source_flash
        calls.append("draft")
        if on_status:
            on_status("draft_running")
        folder = Path(private_root) / "drafts" / str(uuid4())
        folder.mkdir(parents=True)
        path = folder / "character.sav"
        path.write_bytes(source_flash(personalities=(personality + len(calls),)))
        return SimpleNamespace(source_path=path, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), party_count=1)
    return drafter


def fake_register(calls, *, error=None):
    """Bringing a character into a world account: the account's save becomes an ownership save of that world (what the real
    registration leaves, character_play.register_character), and the character's latest save is that one."""
    async def register(installation, private_root, library, character, *, role, world_id, player_id, on_status=None, **options):
        from uuid import uuid4
        from emerald_multiplayer.character_links import profile_directory
        from emerald_multiplayer.character_play import record_after_session
        from emerald_multiplayer.ownership_storage import AllocationGrant
        from test_ownership_storage import owned_flash
        calls.append(dict(role=role, world_id=world_id, player_id=player_id, character_id=character.character_id, options=options))
        if error is not None:
            raise error
        if on_status:
            on_status("choose_continue")
        folder = profile_directory(private_root, world_id, player_id)
        folder.mkdir(parents=True, exist_ok=True)
        grant = AllocationGrant(world_id, player_id, str(uuid4()), 1, 33, 1, 1, 0)
        (folder / "character.sav").write_bytes(owned_flash(grant, personalities=(7,)))
        (folder / "enrollment-completed.json").write_text("{}")
        return record_after_session(private_root, library, character.character_id, world_id, player_id)
    return register


class Driver:
    """A strict script: each step is (screen id, answer). An answer is ('select', id[, fields]) / ('back',) or a function of the screen."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.log = []

    def __call__(self, screen):
        self.log.append((screen.id, screen.title))
        if not self.steps:
            raise AssertionError(f"unexpected screen {screen.id!r} ({screen.title!r}); items {labels(screen)}; notes {screen.notes}")
        expected, answer = self.steps.pop(0)
        if screen.id != expected:
            raise AssertionError(f"expected {expected!r} but the menu showed {screen.id!r} ({screen.title!r}); items {labels(screen)}")
        return answer(screen) if callable(answer) else answer

    def done(self):
        return not self.steps


def select(identifier, **fields):
    return ("select", identifier, fields)


def choose_label(label, **fields):
    return lambda screen: ("select", label_id(screen, label), fields)


BACK = ("back",)


class FakeWorker:
    """Stands in for SessionWorker: every start is recorded and its outcome comes from ``behaviour(request)``."""

    def __init__(self, behaviour=None):
        self.requests = []
        self.events = queue.SimpleQueue()
        self.behaviour = behaviour or (lambda request: "game_closed")
        self.saves = 0
        self.autosave = []
        self.busy = False

    def start(self, request):
        request.options()                                # the same validation the real worker applies
        self.requests.append(request)
        self.events.put(UiEvent("status", "running", "running", True, save_available=True, is_host=request.mode == "host",
                                connected=True))
        self.events.put(UiEvent("complete", self.behaviour(request)))
        return True

    def request_save(self):
        self.saves += 1
        return True

    def request_autosave(self, enabled):
        self.autosave.append(enabled)
        return True

    def cancel_startup(self):
        return True

    request_battle_recovery = request_host_restart = request_trade_recovery = request_battle_entry_cancel = lambda self: True


class World:
    """A private folder with a verified fake installation, the way tests/test_launcher_setup.py builds one."""

    def __init__(self, test, name="private"):
        self.temp = tempfile.TemporaryDirectory()
        test.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom, self.manifest = make_trade_files(self.root)
        bundle = self.root / "bundle"
        bundle.mkdir()
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.installation = GameInstallation(self.rom, self.manifest, digest(self.rom), digest(self.manifest), write_bundle(bundle))
        self.private = self.root / name

    def peer(self, name):
        """Another PC: the same verified installation, its own private folder."""
        other = World.__new__(World)
        other.temp, other.root, other.rom, other.manifest, other.installation = self.temp, self.root, self.rom, self.manifest, self.installation
        other.private = self.root / name
        return other

    def app(self, driver, *, worker=None, register=None, drafter=None, lan=lambda: ["192.168.1.20"], clock=None, **options):
        ui = ScriptedShell(driver)
        kwargs = dict(worker=worker or FakeWorker(), lan=lan, graphics_gate=lambda: "3d", version="test",
                      register=register or fake_register([]), drafter=drafter or fake_drafter([]))
        if clock is not None:
            kwargs["clock"] = clock
        kwargs.update(options)
        return ShellApp(self.installation, self.private, ui, **kwargs), ui


class ServerThread:
    """A real WorldServer for a host world, on its own event loop and thread (the store must stay on the thread that opened it)."""

    def __init__(self, test, installation, host_world, *, allow_enrollment=True):
        import threading
        self.installation, self.host_world = installation, host_world
        self.allow_enrollment = allow_enrollment
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.failed = None
        self.stopping = None
        self.store = self.server = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.ready.wait(30)
        test.addCleanup(self.stop)
        if self.failed is not None:
            raise self.failed

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main())

    async def _main(self):
        from emerald_multiplayer.companion import verify_rom_manifest
        from emerald_multiplayer.server import ServerConfig, WorldServer
        from emerald_multiplayer.trade_native_replay import host_trade_effect_options
        try:
            self.store = self.host_world.open_store()
            _, manifest = verify_rom_manifest(self.installation.rom_path, self.installation.manifest_path)
            self.server = WorldServer(ServerConfig(self.host_world.build_id, self.host_world.ruleset_id,
                                                   allow_enrollment=self.allow_enrollment), store=self.store,
                                      **host_trade_effect_options(self.installation, self.store, manifest))
            await self.server.start("127.0.0.1", self.host_world.port, tls=self.host_world.server_tls)
        except BaseException as error:                     # noqa: BLE001
            self.failed = error
            self.ready.set()
            return
        self.stopping = asyncio.Event()
        self.ready.set()
        await self.stopping.wait()
        await self.server.close()
        self.store.close()

    def stop(self):
        if self.stopping is not None and self.thread.is_alive():
            self.loop.call_soon_threadsafe(self.stopping.set)
            self.thread.join(10)

    def query(self, sql, *args):
        """Read from the store on its own thread."""
        done = asyncio.run_coroutine_threadsafe(self._query(sql, args), self.loop)
        return done.result(10)

    async def _query(self, sql, args):
        return self.store._connection.execute(sql, args).fetchall()
