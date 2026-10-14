"""Graphics mode (3D Diorama / Classic 2D): the preference, the 3D check, the launch
decision, the runtime bundle with two games, and what must NOT change when the mode does.

The games themselves are not run here (the engine's own checks and the Windows CI
job run the real executables); the children below are Python stand-ins."""
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from emerald_multiplayer.graphics_mode import (EXIT_GRAPHICS_UNAVAILABLE, GraphicsPreference, ProbeResult,
                                               choose_launch, explain_failure, parse_probe_output, probe_graphics)
from emerald_multiplayer.launcher_graphics import GraphicsGate
from emerald_multiplayer.player_runtime import PlayerRuntime, PlayerRuntimeError, RuntimeBundle
from process_fixture import direct_python
from test_cold_start import ClosedCompanion
from test_companion import make_files

SUPPORTED = b'{"graphics":"3d","supported":true,"reason":"ok","detail":"","renderer":"Test GPU","version":"4.6"}\n'
UNSUPPORTED = (b'{"graphics":"3d","supported":false,"reason":"functions","detail":"glActiveTexture is missing",'
               b'"renderer":"GDI Generic","version":"1.1.0"}\n')


def write_bundle(root, rom_sha256, *, classic=True, mutate=None):
    """A native runtime bundle with the 3D game and (optionally) the Classic 2D game."""
    (root / "pokeemerald-mp-diorama.exe").write_bytes(b"3d fixture, never executed")
    if classic:
        (root / "pokeemerald-mp.exe").write_bytes(b"2d fixture, never executed")
    (root / "SDL2.dll").write_bytes(b"dependency")
    names = ["pokeemerald-mp-diorama.exe", "SDL2.dll"] + (["pokeemerald-mp.exe"] if classic else [])
    manifest = dict(format="emerald-native-runtime-v1", executable="pokeemerald-mp-diorama.exe",
                    rom_sha256=rom_sha256,
                    files={name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names})
    if classic:
        manifest["classic_executable"] = "pokeemerald-mp.exe"
    if mutate:
        mutate(manifest)
    raw = json.dumps(manifest).encode()
    (root / "runtime.json").write_bytes(raw)
    return RuntimeBundle(root, hashlib.sha256(raw).hexdigest())


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_3d_is_the_default(self):
        self.assertEqual(GraphicsPreference(self.directory).mode, "3d")
        self.assertEqual(GraphicsPreference(None).mode, "3d")

    def test_the_choice_is_saved_and_restored_on_the_next_launch(self):
        self.assertTrue(GraphicsPreference(self.directory).set("2d"))
        self.assertEqual(GraphicsPreference(self.directory).mode, "2d")
        self.assertTrue(GraphicsPreference(self.directory).set("3d"))
        self.assertEqual(GraphicsPreference(self.directory).mode, "3d")

    def test_an_unreadable_file_is_kept_and_the_default_used(self):
        path = self.directory / "graphics-mode.json"
        path.write_text("not json")
        preference = GraphicsPreference(self.directory)
        self.assertEqual((preference.mode, preference.available), ("3d", False))
        self.assertFalse(preference.set("2d"))            # applies to this window only
        self.assertEqual(preference.mode, "2d")
        self.assertEqual(path.read_text(), "not json")     # never overwritten

    def test_unknown_modes_and_files_are_refused(self):
        with self.assertRaises(ValueError):
            GraphicsPreference(self.directory).set("vulkan")
        (self.directory / "graphics-mode.json").write_text(json.dumps(dict(format="emerald-graphics-mode-v1", mode="x")))
        self.assertFalse(GraphicsPreference(self.directory).available)


class ProbeTests(unittest.TestCase):
    def test_supported_3d(self):
        result = parse_probe_output(SUPPORTED, 0)
        self.assertEqual((result.supported, result.renderer, result.version), (True, "Test GPU", "4.6"))

    def test_unsupported_3d_reports_the_reason(self):
        result = parse_probe_output(UNSUPPORTED, EXIT_GRAPHICS_UNAVAILABLE)
        self.assertFalse(result.supported)
        self.assertEqual((result.reason, result.detail), ("functions", "glActiveTexture is missing"))

    def test_a_pass_needs_a_clean_exit_and_garbage_is_a_failure(self):
        self.assertFalse(parse_probe_output(SUPPORTED, 3).supported)       # crashed after printing
        for output in (b"", b"hello", b"[1]", b'{"supported":"yes","graphics":"3d"}', b"x" * 5000):
            with self.subTest(output=output[:10]):
                result = parse_probe_output(output, 0)
                self.assertFalse(result.supported)
                self.assertEqual(result.reason, "probe_failed")

    def test_the_probe_never_raises_and_asks_the_game_only_to_check(self):
        calls = []

        def run(arguments, **options):
            calls.append((arguments, options))
            return subprocess.CompletedProcess(arguments, 0, stdout=SUPPORTED, stderr=b"")

        self.assertTrue(probe_graphics("game.exe", run=run).supported)
        self.assertEqual(calls[0][0], ["game.exe", "--probe-graphics"])
        self.assertIs(calls[0][1]["stdin"], subprocess.DEVNULL)

        def hang(arguments, **options):
            raise subprocess.TimeoutExpired(arguments, 1)

        def missing(arguments, **options):
            raise FileNotFoundError()

        for run in (hang, missing):
            result = probe_graphics("game.exe", run=run)
            self.assertEqual((result.supported, result.reason), (False, "probe_failed"))

    def test_the_explanation_is_plain_and_offers_2d_without_blame(self):
        text = explain_failure(parse_probe_output(UNSUPPORTED, 78))
        self.assertIn("missing OpenGL features", text)
        self.assertIn("Classic 2D", text)
        self.assertIn("saves, Pokémon, items", text)
        self.assertIn("glActiveTexture is missing", text)


class ChooseLaunchTests(unittest.TestCase):
    def test_supported_3d_starts_3d_without_asking(self):
        choice = choose_launch("3d", lambda: ProbeResult(True, renderer="GPU"))
        self.assertEqual((choice.mode, choice.ask), ("3d", False))

    def test_unsupported_3d_asks_and_does_not_start_anything_itself(self):
        choice = choose_launch("3d", lambda: ProbeResult(False, "functions", "x"))
        self.assertEqual((choice.mode, choice.ask), (None, True))

    def test_manual_2d_never_runs_the_3d_check(self):
        def probe():
            raise AssertionError("2D was chosen: 3D must not be probed")

        choice = choose_launch("2d", probe)
        self.assertEqual((choice.mode, choice.ask), ("2d", False))


class FakeRoot:
    """Tk's after(): callbacks run when the test pumps them."""
    def __init__(self):
        self.pending = []

    def after(self, _ms, callback):
        self.pending.append(callback)

    def pump(self, limit=500):
        import time
        deadline = time.monotonic() + 5
        while self.pending and time.monotonic() < deadline and limit:
            self.pending.pop(0)()
            limit -= 1
            time.sleep(0.005)


class FakeBundle:
    def __init__(self, classic):
        self.classic = classic

    def has_classic(self):
        return self.classic

    def verify(self, graphics=None):
        return Path("game.exe"), None


class GateTests(unittest.TestCase):
    """What the window does before any game starts."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.root = FakeRoot()
        self.events = []

    def gate(self, preference_mode, *, supported, classic=True, answer=None):
        preference = GraphicsPreference(self.directory)
        if preference_mode != preference.mode:
            preference.set(preference_mode)
        self.probes, self.asked = [], []

        def probe(executable):
            self.probes.append(executable)
            return ProbeResult(True) if supported else ProbeResult(False, "functions", "glActiveTexture is missing")

        def ask(root, text, can_2d):
            self.asked.append((text, can_2d))
            return answer

        return GraphicsGate(self.root, preference, lambda: FakeBundle(classic), probe=probe, ask=ask,
                            message=lambda code: self.events.append(("message", code)),
                            busy=lambda value: self.events.append(("busy", value)))

    def run_gate(self, gate):
        outcome = []
        gate.resolve(lambda mode: outcome.append(mode), lambda: outcome.append("cancelled"))
        self.root.pump()
        return outcome

    def test_supported_3d_starts_in_3d(self):
        gate = self.gate("3d", supported=True)
        self.assertEqual(self.run_gate(gate), ["3d"])
        self.assertEqual(len(self.probes), 1)
        self.assertEqual(self.asked, [])

    def test_unsupported_3d_explains_and_launch_in_2d_starts_2d_for_this_time_only(self):
        gate = self.gate("3d", supported=False, answer="2d")
        self.assertEqual(self.run_gate(gate), ["2d"])
        self.assertEqual(len(self.asked), 1)
        self.assertTrue(self.asked[0][1])
        self.assertIn("Classic 2D", self.asked[0][0])
        # Never forced into 2D for good: the saved preference is still 3D, on disk too.
        self.assertEqual(gate.preference.mode, "3d")
        self.assertEqual(GraphicsPreference(self.directory).mode, "3d")
        self.assertFalse((self.directory / "graphics-mode.json").exists())

    def test_unsupported_3d_cancel_starts_nothing_and_changes_nothing(self):
        gate = self.gate("3d", supported=False, answer=None)
        self.assertEqual(self.run_gate(gate), ["cancelled"])
        self.assertEqual(GraphicsPreference(self.directory).mode, "3d")
        self.assertIn(("message", "graphics_cancelled"), self.events)

    def test_a_package_without_a_2d_game_cannot_be_talked_into_2d(self):
        gate = self.gate("3d", supported=False, classic=False, answer="2d")
        self.assertEqual(self.run_gate(gate), ["cancelled"])
        self.assertFalse(self.asked[0][1])          # the prompt says so and offers only Cancel

    def test_manual_2d_starts_2d_even_on_a_pc_that_supports_3d(self):
        gate = self.gate("2d", supported=True)
        self.assertEqual(self.run_gate(gate), ["2d"])
        self.assertEqual(self.probes, [])           # no 3D check at all
        self.assertEqual(self.asked, [])

    def test_a_saved_2d_choice_without_a_2d_game_runs_the_3d_check_and_keeps_the_choice(self):
        gate = self.gate("2d", supported=True, classic=False)
        self.assertEqual(self.run_gate(gate), ["3d"])
        self.assertEqual(GraphicsPreference(self.directory).mode, "2d")

    def test_a_broken_package_falls_through_to_the_normal_start_checks(self):
        gate = self.gate("3d", supported=True)

        class Broken:
            def has_classic(self):
                return False

            def verify(self, graphics=None):
                raise PlayerRuntimeError("runtime_hash", "x")

        gate._bundle_source = lambda: Broken()
        self.assertEqual(self.run_gate(gate), ["3d"])
        self.assertEqual(self.probes, [])


class RuntimeBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom = "cd" * 32

    def test_both_games_are_pinned_and_the_mode_picks_one(self):
        bundle = write_bundle(self.root, self.rom)
        self.assertTrue(bundle.has_classic())
        self.assertEqual(bundle.verify()[0].name, "pokeemerald-mp-diorama.exe")
        self.assertEqual(bundle.verify("3d")[0].name, "pokeemerald-mp-diorama.exe")
        self.assertEqual(bundle.verify("2d")[0].name, "pokeemerald-mp.exe")
        from dataclasses import replace
        self.assertEqual(replace(bundle, graphics="2d").verify()[0].name, "pokeemerald-mp.exe")

    def test_the_rom_pairing_is_the_same_in_both_modes(self):
        bundle = write_bundle(self.root, self.rom)
        self.assertEqual(bundle.verify("3d")[1], bundle.verify("2d")[1])

    def test_a_bundle_without_a_2d_game_still_works_and_refuses_2d(self):
        bundle = write_bundle(self.root, self.rom, classic=False)
        self.assertFalse(bundle.has_classic())
        self.assertEqual(bundle.verify()[0].name, "pokeemerald-mp-diorama.exe")
        with self.assertRaises(PlayerRuntimeError) as caught:
            bundle.verify("2d")
        self.assertEqual(caught.exception.code, "classic_unavailable")

    def test_malformed_2d_records_are_refused(self):
        mutations = [
            lambda m: m.update(classic_executable="pokeemerald-mp-diorama.exe"),   # same file as the 3D game
            lambda m: m.update(classic_executable="missing.exe"),                  # not pinned
            lambda m: m.update(classic_executable="SDL2.dll"),                     # not an .exe
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                with self.assertRaises(PlayerRuntimeError):
                    write_bundle(self.root, self.rom, mutate=mutate).verify()

    def test_a_changed_2d_game_is_refused_even_when_3d_is_chosen(self):
        bundle = write_bundle(self.root, self.rom)
        (self.root / "pokeemerald-mp.exe").write_bytes(b"tampered")
        for mode in ("3d", "2d"):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(PlayerRuntimeError, "pinned hash"):
                    bundle.verify(mode)

    def test_an_unknown_mode_is_refused(self):
        with self.assertRaises(PlayerRuntimeError):
            write_bundle(self.root, self.rom).verify("vulkan")


class SwitchingKeepsEverythingTests(unittest.IsolatedAsyncioTestCase):
    """Starting the game in the other mode changes only which program runs: the save,
    the bridge file, the settings file and the verified ROM pairing are the same, and
    no launcher step reads or writes the save when the mode changes."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.c = ClosedCompanion(self.root)
        self.c.config.rom_path, self.c.config.manifest_path = make_files(self.root)
        manifest = json.loads(self.c.config.manifest_path.read_text())
        self.identity = patch("emerald_multiplayer.player_runtime.verify_rom_manifest",
                              return_value=(self.c.config.build_id, manifest))
        self.identity.start()
        self.c.config.token = bytes(range(32))
        self.c.ipc_address = ("127.0.0.1", 8870)
        (self.root / "bundle").mkdir()
        self.bundle = write_bundle(self.root / "bundle", self.c.config.build_id)
        self.save = self.root / "character.sav"
        self.save.write_bytes(b"canonical save bytes " * 100)
        self.launches = self.root / "launcher" / "launches"
        self.real_spawn = asyncio.create_subprocess_exec
        self.children, self.arguments = [], []

    async def asyncTearDown(self):
        for child in self.children:
            if child.returncode is None:
                child.kill()
            await child.wait()
        self.identity.stop()
        self.c.close()
        self.temp.cleanup()

    async def spawn(self, *args, **kwargs):
        self.arguments.append(args)
        child = await self.real_spawn(direct_python(), "-c", "import time; time.sleep(60)", **kwargs)
        self.children.append(child)
        return child

    async def start(self, mode):
        from dataclasses import replace
        runtime = PlayerRuntime(self.c, replace(self.bundle, graphics=mode), self.root / "private", self.save,
                                launch_root=self.launches)
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with runtime.open():
                pass

    async def test_the_two_modes_start_different_programs_with_the_same_save_and_settings(self):
        await self.start("3d")
        # The first start of any mode reconciles the save with its verified checkpoint, as it always has;
        # after that no start, in either mode, changes it.
        before = hashlib.sha256(self.save.read_bytes()).hexdigest()
        await self.start("2d")
        await self.start("3d")
        names = [Path(args[0]).name for args in self.arguments]
        self.assertEqual(names, ["pokeemerald-mp-diorama.exe", "pokeemerald-mp.exe", "pokeemerald-mp-diorama.exe"])
        self.assertEqual(hashlib.sha256(self.save.read_bytes()).hexdigest(), before)
        for args in self.arguments:
            self.assertEqual(args[1::2], ("--save", "--bridge", "--config"))
        # --save and --config name the same files in every mode; only the per-launch bridge file differs.
        self.assertEqual({args[2] for args in self.arguments}, {str(self.save.resolve())})
        self.assertEqual({args[6] for args in self.arguments}, {str((self.root / "launcher" / "game-settings.cfg").resolve())})
        self.assertEqual(hashlib.sha256(self.save.read_bytes()).hexdigest(), before)

    async def test_switching_modes_does_not_touch_the_save_or_other_private_files(self):
        private = self.root / "private"
        private.mkdir(exist_ok=True)
        (private / "ownership.sqlite3").write_bytes(b"world data")
        snapshot = {path: path.read_bytes() for path in (self.save, private / "ownership.sqlite3")}
        GraphicsPreference(private).set("2d")
        GraphicsPreference(private).set("3d")
        for path, data in snapshot.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(sorted(p.name for p in private.iterdir()), ["graphics-mode.json", "ownership.sqlite3"])


class CollectBundleTests(unittest.TestCase):
    """scripts/windows-runtime/collect_native_bundle.py pins both games for the launcher."""

    def setUp(self):
        import importlib.util
        script = Path(__file__).resolve().parents[1] / "scripts/windows-runtime/collect_native_bundle.py"
        spec = importlib.util.spec_from_file_location("collect_native_bundle", script)
        self.collect = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.collect)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, data in (("3d.exe", b"3d"), ("2d.exe", b"2d"), ("SDL2.dll", b"dll"), ("rom.gba", b"rom")):
            (self.root / name).write_bytes(data)

    def collect_bundle(self, **options):
        return self.collect.collect(self.root / "3d.exe", self.root / "SDL2.dll", self.root / "rom.gba",
                                    self.root / "out", **options)

    def test_both_games_are_pinned_and_verify_in_each_mode(self):
        result = self.collect_bundle(classic_game=self.root / "2d.exe")
        record = json.loads((self.root / "out" / "runtime.json").read_text())
        self.assertEqual((record["executable"], record["classic_executable"]), ("3d.exe", "2d.exe"))
        self.assertEqual(result["files"], 3)
        bundle = RuntimeBundle(self.root / "out", result["manifest_sha256"])
        self.assertEqual(bundle.verify("2d")[0].name, "2d.exe")
        self.assertEqual(bundle.verify("3d")[0].name, "3d.exe")

    def test_without_a_2d_game_the_record_is_the_old_one(self):
        self.collect_bundle()
        record = json.loads((self.root / "out" / "runtime.json").read_text())
        self.assertNotIn("classic_executable", record)

    def test_the_2d_game_must_be_an_exe_with_its_own_name(self):
        (self.root / "notes.txt").write_bytes(b"x")
        with self.assertRaises(ValueError):
            self.collect_bundle(classic_game=self.root / "notes.txt")
        with self.assertRaises(ValueError):
            self.collect_bundle(classic_game=self.root / "3d.exe")


def _tk_root():
    try:
        import tkinter
        root = tkinter.Tk()
    except Exception as error:  # no display
        raise unittest.SkipTest(f"no Tk display: {error}")
    root.withdraw()
    return root


def _buttons(widget):
    found = []
    for child in widget.winfo_children():
        found.extend(_buttons(child))
        if child.winfo_class() == "TButton":
            found.append(child)
    return found


class PromptTests(unittest.TestCase):
    """The real Tk prompt shown when 3D cannot start."""

    def click(self, root, label, *, can_launch_2d=True):
        from emerald_multiplayer.launcher_graphics import ask_fallback
        seen = {}

        def press():
            window = [w for w in root.winfo_children() if w.winfo_class() == "Toplevel"][0]
            buttons = {b.cget("text"): b for b in _buttons(window)}
            seen["labels"] = sorted(buttons)
            seen["launch_state"] = str(buttons["Launch in Classic 2D"].cget("state"))
            seen["title"] = window.title()
            buttons[label].invoke()

        root.after(100, press)
        return ask_fallback(root, "explanation text", can_launch_2d), seen

    def test_launch_in_classic_2d(self):
        root = _tk_root()
        self.addCleanup(root.destroy)
        answer, seen = self.click(root, "Launch in Classic 2D")
        self.assertEqual(answer, "2d")
        self.assertEqual(seen["labels"], ["Cancel", "Launch in Classic 2D"])
        self.assertIn("3D graphics are not available", seen["title"])

    def test_cancel(self):
        root = _tk_root()
        self.addCleanup(root.destroy)
        answer, _ = self.click(root, "Cancel")
        self.assertIsNone(answer)

    def test_without_a_2d_game_only_cancel_is_possible(self):
        root = _tk_root()
        self.addCleanup(root.destroy)
        answer, seen = self.click(root, "Cancel", can_launch_2d=False)
        self.assertIsNone(answer)
        self.assertEqual(seen["launch_state"], "disabled")
