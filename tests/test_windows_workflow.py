"""Text checks of .github/workflows/windows-package.yml: the installer path and its privacy rules stay wired.

The workflow itself only runs on GitHub; these checks keep the pieces this repository relies on
from silently disappearing (game facts in the bundle, the installer build, the player artifact,
the installation check on a fresh runner, no game data in any upload)."""
from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/windows-package.yml").read_text(encoding="utf-8")


def job(name):
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [a-z-]+:\n|\Z)", WORKFLOW, re.M | re.S)
    assert match, name
    return match.group(1)


class WindowsWorkflowTests(unittest.TestCase):
    def test_bundle_pins_game_facts_and_the_build_makes_the_installer(self):
        package = job("package")
        self.assertIn("--manifest inputs/manifest.json", package)
        self.assertIn("--installer --iscc \"$ISCC\"", package)
        self.assertIn('INNO_SETUP_VERSION: "6.7.1"', WORKFLOW)
        self.assertIn('choco install innosetup --version="$INNO_SETUP_VERSION"', package)
        self.assertIn('"_internal/runtime/game-facts.json" in hashes', package)

    def test_player_artifact_holds_only_the_setup_and_the_guide(self):
        package = job("package")
        self.assertIn("name: ${{ env.INSTALLER_ARTIFACT }}\n          path: ${{ env.WORK }}/launcher/player/", package)
        self.assertIn("'EmeraldTogether-Windows-Installer'", WORKFLOW)
        self.assertIn("name: EmeraldTogether-windows-${{ env.MODE }}", package)    # the developer artifact stays
        self.assertIn('assert player == sorted([installer["setup"], "QUICK-START.txt"])', package)

    def test_installation_check_runs_on_a_fresh_github_runner(self):
        check = job("install-check")
        self.assertIn("needs: package", check)
        self.assertIn("runs-on: windows-2022", check)
        self.assertIn("scripts/windows-runtime/ci_installer_check.py", check)
        self.assertIn("--expect-shell", check)
        script = (ROOT / "scripts/windows-runtime/ci_installer_check.py").read_text(encoding="utf-8")
        for switch in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/CURRENTUSER", "/DIR=", "LOCALAPPDATA"):
            self.assertIn(switch, script)

    def test_existing_checks_remain(self):
        for name in ("Check the package contents", "Verify the packaged game files",
                     "Start the frozen launcher and watch it stay up", "Graphics mode check on the real packaged games",
                     "In-game menu check on the real packaged games"):
            self.assertIn(f"- name: {name}", WORKFLOW)

    def test_battle_tower_runs_in_windows_game_processes(self):
        floors = job("tower-check")
        self.assertIn("runs-on: windows-2022", floors)
        self.assertIn('floors: ["1-25", "26-50", "51-75", "76-100"]', floors)
        self.assertIn("tower_check.py --exe mega-check-inputs\\pokeemerald-mp-bfxtest.exe", floors)
        extras = job("tower-extras")
        self.assertIn("runs-on: windows-2022", extras)
        self.assertIn("--caps", extras)
        self.assertIn("train_check.py --exe $exe --save $save", extras)
        self.assertIn("tools/battle_env/train_check.py ../mega-check-inputs/", job("engine"))
        proof = job("tower-proof")
        self.assertIn("runs-on: windows-2022", proof)
        self.assertIn("needs: [engine, symbol-sizes]", proof)
        for name, scenario in (("solo", "solo"), ("milestone", "solo"), ("duo", "duo"), ("mega", "mega"),
                               ("forfeit", "forfeit")):
            self.assertIn(f"{{name: {name}, scenario: {scenario},", proof)
        self.assertIn("b: tower-weak25-b", proof)          # player 2 loses the special boss (floor 25)
        self.assertIn("scripts/multiplayer/make_tower_saves.py", proof)
        self.assertIn("scripts/multiplayer/native_launcher_tower_proof.py --scenario ${{ matrix.scenario }}", proof)
        self.assertIn("a: tower-strong25-a", proof)        # the milestone Pokemon of floor 25
        self.assertIn("b: tower-forfeit-b", proof)         # the joiner forfeits: the host's world stays up
        self.assertIn("--pe-symbols symbols/pokeemerald-mp.nm.txt", proof)

    def test_the_3d_game_is_drawn_in_windows_game_processes(self):
        graphics = job("graphics-3d")
        self.assertIn("runs-on: windows-2022", graphics)
        self.assertIn("GALLIUM_DRIVER: llvmpipe", graphics)
        self.assertIn("pokeemerald-mp-diorama-bfxtest.exe --probe-graphics", graphics)
        self.assertIn('-notmatch "llvmpipe"', graphics)                         # never Windows' own OpenGL 1.1
        self.assertIn("--only wild --only trainer --series --parade", graphics)
        engine = job("engine")
        self.assertIn("DIORAMA=1 BFX_TEST=1", engine)
        self.assertIn("../diorama-check-inputs/", engine)
        # Mesa is a test tool: the packaged game never carries it
        self.assertNotIn("opengl32", job("package").lower())

    def test_the_whole_games_gameplay_check_runs_in_windows_game_processes(self):
        check = job("gameplay-check")
        self.assertIn("runs-on: windows-2022", check)
        self.assertIn("inputs.gameplay_qa == 'yes'", check)
        self.assertIn("shard: [0, 1, 2, 3, 4, 5, 6, 7]", check)
        self.assertIn("gameplay_check.py --exe mega-check-inputs\\pokeemerald-mp-bfxtest.exe", check)
        self.assertIn("--plan gameplay-inputs\\plan\\plan.json", check)
        self.assertIn("throw", check)                                           # a failed target fails the job
        self.assertIn("gameplay_check.py --exe pokeemerald-mp-bfxtest.exe --plan-only", job("engine"))
        report = job("gameplay-report")
        self.assertIn("merge_gameplay_shards.py --shards shards --expected 8 --platform windows-2022", report)

    def test_multiplayer_mega_evolution_runs_in_windows_game_processes(self):
        mega = job("mega-proof")
        self.assertIn("runs-on: windows-2022", mega)
        self.assertIn("{scenario: two, b: mega2-b}", mega)
        self.assertIn("{scenario: no-ring, b: mega2-noring-b}", mega)
        self.assertIn("native_launcher_mega_proof.py --scenario ${{ matrix.scenario }}", mega)
        self.assertIn("--facts symbols/mega-facts.json", mega)
        engine = job("engine")
        self.assertIn("mega_facts.py --game pokeemerald-mp.exe --out ../classic-pe-symbols/mega-facts.json", engine)
        # the offsets come from the build before its strip (no debug information after it)
        self.assertLess(engine.index("mega_facts.py --game pokeemerald-mp.exe"),
                        engine.index("i686-w64-mingw32-strip --strip-all pokeemerald-mp.exe"))

    def test_interrupted_battles_run_in_windows_game_processes(self):
        abandon = job("abandon-check")
        self.assertIn("runs-on: windows-2022", abandon)
        self.assertIn("needs: [engine, symbol-sizes]", abandon)
        self.assertIn("scenario: [pairs-crash, multi-network, ffa-exit, ffa-host-crash]", abandon)
        self.assertIn("make_intro_saves.py --exe mega-check-inputs/pokeemerald-mp-bfxtest.exe", abandon)
        self.assertIn("--count 4", abandon)
        self.assertIn("--only abandon-a,abandon-b,abandon-c,abandon-d", abandon)
        self.assertIn("native_launcher_abandon_proof.py --scenario ${{ matrix.scenario }}", abandon)
        self.assertIn("--pe-symbols symbols/pokeemerald-mp.nm.txt", abandon)

    def test_breeding_and_egg_hatching_run_in_windows_game_processes(self):
        breed = job("breed-check")
        self.assertIn("runs-on: windows-2022", breed)
        self.assertIn("needs: engine", breed)
        self.assertIn("breed_check.py --exe mega-check-inputs\\pokeemerald-mp-bfxtest.exe --make-save", breed)
        self.assertIn('throw "the breeding check failed', breed)                # a failed check fails the job
        self.assertIn("tools/battle_env/breed_check.py ../mega-check-inputs/", job("engine"))

    def test_no_upload_carries_game_data(self):
        uploads = re.findall(r"uses: actions/upload-artifact@v4\n\s+with:\n(.*?)(?=\n      - |\n  [a-z-]+:\n|\Z)",
                             WORKFLOW, re.S)
        self.assertGreaterEqual(len(uploads), 5)
        for upload in uploads:
            paths = " ".join(re.findall(r"\$\{\{[^}]+\}\}/\S+|native-inputs", upload))
            if "native-inputs" in paths:
                self.assertIn("retention-days: 1", upload)          # the engine job's private hand-off only
                continue
            self.assertNotRegex(paths.lower(), r"\.(gba|sav|db|sqlite3)\b")
            self.assertNotIn("inputs/", paths)


if __name__ == "__main__":
    unittest.main()
