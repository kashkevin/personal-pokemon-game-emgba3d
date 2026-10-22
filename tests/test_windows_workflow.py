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
        for name, scenario in (("solo", "solo"), ("milestone", "solo"), ("duo", "duo"), ("join", "join"), ("mega", "mega"),
                               ("forfeit", "forfeit")):
            self.assertIn(f"{{name: {name}, scenario: {scenario},", proof)
        # join: co-op progression - the player who climbed higher (three level-10 Mewtwo) joins the other's lower floor
        self.assertIn('{name: join, scenario: join, a: tower-join-a, b: tower-join-b, extra: "--party-counts 3 6"}', proof)
        self.assertIn("b: tower-weak25-b", proof)          # player 2 loses the special boss (floor 25)
        self.assertIn("scripts/multiplayer/make_tower_saves.py", proof)
        self.assertIn("scripts/multiplayer/native_launcher_tower_proof.py --scenario ${{ matrix.scenario }}", proof)
        self.assertIn("a: tower-strong25-a", proof)        # the milestone Pokemon of floor 25
        self.assertIn("b: tower-forfeit-b", proof)         # the joiner forfeits: the host's world stays up
        self.assertIn('--pe-symbols "symbols/$name.nm.txt"', proof)
        self.assertIn("game=\"${{ matrix.game || 'inputs/pokeemerald-mp.exe' }}\"", proof)     # the Classic 2D game by default
        # ui: the 3D game's native Tower pages through Mesa (the pinned archive, as graphics-3d), its symbols from the
        # engine job, Mesa added to the proof's runtime only
        self.assertIn("{name: ui, scenario: ui,", proof)
        self.assertIn("game: inputs/pokeemerald-mp-diorama.exe, mesa: \"yes\"}", proof)
        # climb: floors 1-100 in the test build through the launcher, its symbols from before the strip, a longer limit
        self.assertIn("{name: climb, scenario: climb, a: tower-fast-a, b: tower-fast-b,", proof)   # fast text, no animations
        self.assertIn("--test-env PKMN_TEST_TOWER_WIN=1\", game: mega-check-inputs/pokeemerald-mp-bfxtest.exe}", proof)
        self.assertNotIn("PKMN_TEST_SPEED", proof)          # the whole game faster than the harness's presses
        self.assertIn("timeout-minutes: ${{ matrix.name == 'climb' && 330 || 120 }}", proof)
        self.assertIn("MESA_SHA256: 351fc8c8b695878ffb3eaa044b3ead08672a48b1a045e3c3e3975811df0f6695", proof)
        self.assertIn("if ($hash -ne $env:MESA_SHA256) { throw", proof)
        self.assertIn('runtime_extra+=(--runtime-extra "$dll")', proof)
        engine = job("engine")
        self.assertIn("i686-w64-mingw32-nm -n pokeemerald-mp-diorama.exe > ../classic-pe-symbols/pokeemerald-mp-diorama.nm.txt",
                      engine)
        self.assertLess(engine.index("i686-w64-mingw32-nm -n pokeemerald-mp-diorama.exe"),
                        engine.index("i686-w64-mingw32-strip --strip-all pokeemerald-mp-diorama.exe"))
        self.assertLess(engine.index("i686-w64-mingw32-nm -n pokeemerald-mp-bfxtest.exe > ../classic-pe-symbols/"),
                        engine.index("i686-w64-mingw32-strip --strip-all pokeemerald-mp-bfxtest.exe"))

    def test_the_engines_self_tests_run_in_the_windows_build(self):
        tests = job("selftests")
        self.assertIn("runs-on: windows-2022", tests)
        self.assertIn('-ArgumentList "--selftest-$test"', tests)
        for name in ("tower", "breeding", "shiny", "rewards", "coop-exp"):
            self.assertIn(f'"{name}"', tests)
        self.assertIn('throw "self-tests failed in the Windows build', tests)
        # their output in files (the Windows game's own console is slow and unreadable: run 129's update32 timed out)
        self.assertIn("$env:PKMN_DEBUG_LOG = $log", tests)
        self.assertIn("selftests/*.log", tests)

    def test_the_3d_game_is_drawn_in_windows_game_processes(self):
        graphics = job("graphics-3d")
        self.assertIn("runs-on: windows-2022", graphics)
        self.assertIn("GALLIUM_DRIVER: llvmpipe", graphics)
        self.assertIn("pokeemerald-mp-diorama-bfxtest.exe --probe-graphics", graphics)
        self.assertIn('-notmatch "llvmpipe"', graphics)                         # never Windows' own OpenGL 1.1
        self.assertIn('MESA_SHA256: 351fc8c8b695878ffb3eaa044b3ead08672a48b1a045e3c3e3975811df0f6695', graphics)
        self.assertIn("if ($hash -ne $env:MESA_SHA256) { throw", graphics)    # the pinned archive or nothing
        self.assertNotIn("releases/latest", graphics)
        # the 3D view's frame rate through Mesa, informational (the game's own benchmark; not a player's GPU)
        self.assertIn("--benchmark 10 --bench-heights 720", graphics)
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

    def test_the_rival_checkpoint_battle_runs_in_windows_game_processes(self):
        rival = job("rival-proof")
        self.assertIn("runs-on: windows-2022", rival)
        self.assertIn("needs: [engine, symbol-sizes]", rival)
        self.assertIn("make_tower_saves.py --exe mega-check-inputs/pokeemerald-mp-bfxtest.exe", rival)
        self.assertIn("--only rival-a,rival-b", rival)                       # Route 110, south of the rival line
        self.assertIn("native_launcher_rival_proof.py", rival)
        self.assertIn("--game inputs/pokeemerald-mp.exe", rival)             # the packaged Classic 2D game
        self.assertIn("--pe-symbols symbols/pokeemerald-mp.nm.txt", rival)

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
        self.assertIn("'[\"pairs-crash\", \"multi-network\", \"ffa-exit\", \"ffa-host-crash\", \"ffa-knockout\", "
                      "\"multi-knockout\", \"stale-save\"]'", abandon)
        self.assertIn("make_intro_saves.py --exe mega-check-inputs/pokeemerald-mp-bfxtest.exe", abandon)
        self.assertIn("--count 4", abandon)
        self.assertIn("--only abandon-a,abandon-b,abandon-c,abandon-d,knockout-a,knockout-b,knockout-c,knockout-d", abandon)
        # MS-57's regression: the knockout fixtures for ffa-knockout and multi-knockout, the abandon ones for the others
        self.assertIn("fixture=${{ endsWith(matrix.scenario, '-knockout') && 'knockout' || 'abandon' }}", abandon)
        self.assertIn('--source "$RUNNER_TEMP/abandon-saves/$fixture-a.sav"', abandon)
        self.assertIn("native_launcher_abandon_proof.py --scenario ${{ matrix.scenario }}", abandon)
        self.assertIn("--pe-symbols symbols/pokeemerald-mp.nm.txt", abandon)
        # KNOWN_ISSUES MS-60: a game with progress its host has not saved is turned away at Enter (two players).
        stale = abandon.index('if [ "${{ matrix.scenario }}" = stale-save ]; then')
        branch = abandon[stale:abandon.index("fi\n", stale)]
        self.assertIn("native_launcher_stale_save_proof.py", branch)
        self.assertIn('--source-a "$RUNNER_TEMP/abandon-saves/abandon-a.sav"', branch)
        self.assertIn('--source-b "$RUNNER_TEMP/abandon-saves/abandon-b.sav"', branch)
        self.assertIn("--pe-symbols symbols/pokeemerald-mp.nm.txt", branch)
        self.assertIn("exit\n", branch)

    def test_one_check_runs_on_its_own_and_a_release_run_runs_everything(self):
        # `only` names check jobs (comma-separated): the builds and those jobs run, nothing else (no installer). Blank (a
        # release run, a push) runs every job as before.
        self.assertIn("      only:\n", WORKFLOW)
        checks = [name for name in re.findall(r"^  ([a-z0-9-]+):\n", WORKFLOW, re.M)
                  if name not in ("push", "engine", "symbol-sizes", "install-check")]
        self.assertIn("abandon-check", checks)
        self.assertIn("package", checks)
        for name in checks:
            with self.subTest(job=name):
                key = "gameplay-check" if name == "gameplay-report" else name
                condition = re.search(r"^    if: (.*)$", job(name), re.M).group(1)
                self.assertTrue(condition.endswith(
                    f"&& (!inputs.only || contains(format(',{{0}},', inputs.only), ',{key},')) }}}}"), condition)
        for name in ("engine", "symbol-sizes"):
            self.assertNotIn("inputs.only", job(name))
        self.assertIn("needs: package", job("install-check"))

    def test_the_interrupted_battle_check_repeats_a_scenario_on_request(self):
        abandon = job("abandon-check")
        self.assertIn("options: [all, pairs-crash, multi-network, ffa-exit, ffa-host-crash, ffa-knockout, multi-knockout, "
                      "stale-save]", WORKFLOW)
        self.assertIn("format('[\"{0}\"]', inputs.abandon_scenario)", abandon)
        self.assertIn("inputs.attempts == '4' && '[1, 2, 3, 4]'", abandon)
        self.assertIn("|| '[1]') }}", abandon)                                 # the default: once
        # Attempt 1 keeps a release run's job and artifact names.
        self.assertIn("${{ matrix.attempt > 1 && format(', attempt {0}', matrix.attempt) || '' }}", abandon)
        self.assertIn("EmeraldTogether-abandon-check-${{ matrix.scenario }}${{ matrix.attempt > 1 && "
                      "format('-{0}', matrix.attempt) || '' }}", abandon)

    def test_a_failed_launcher_proof_prints_its_diagnosis_in_the_log(self):
        # Run 138's ffa-exit: the evidence went to an artifact a session reading the log could not fetch.
        for name in ("tower-proof", "rival-proof", "mega-proof", "abandon-check", "multiplayer-check"):
            with self.subTest(job=name):
                steps = job(name)
                summary = steps.index("proof_failure_summary.py \"$RUNNER_TEMP/multiplayer-proof\"")
                self.assertIn("if: failure()", steps[steps.rindex("- name:", 0, summary):summary])
                self.assertLess(summary, steps.index("- name: Upload the proof's record"))

    def test_breeding_and_egg_hatching_run_in_windows_game_processes(self):
        breed = job("breed-check")
        self.assertIn("runs-on: windows-2022", breed)
        self.assertIn("needs: engine", breed)
        self.assertIn("breed_check.py --exe mega-check-inputs\\pokeemerald-mp-bfxtest.exe --make-save", breed)
        self.assertIn('throw "the breeding check failed', breed)                # a failed check fails the job
        self.assertIn("tools/battle_env/breed_check.py ../mega-check-inputs/", job("engine"))

    def test_evolutions_run_in_windows_game_processes(self):
        evolve = job("evolve-check")
        self.assertIn("runs-on: windows-2022", evolve)
        self.assertIn("needs: engine", evolve)
        self.assertIn("evolve_check.py --exe mega-check-inputs\\pokeemerald-mp-bfxtest.exe --make-save", evolve)
        self.assertIn('throw "the evolution check failed', evolve)              # a failed step fails the job
        self.assertIn("tools/battle_env/evolve_check.py ../mega-check-inputs/", job("engine"))

    def test_a_poke_mart_runs_in_windows_game_processes(self):
        shop = job("shop-check")
        self.assertIn("runs-on: windows-2022", shop)
        self.assertIn("shop_check.py --exe mega-check-inputs\\pokeemerald-mp-bfxtest.exe --make-save", shop)
        self.assertIn('throw "the shop check failed', shop)
        self.assertIn("tools/battle_env/shop_check.py ../mega-check-inputs/", job("engine"))

    def test_catching_runs_in_windows_game_processes(self):
        catch = job("catch-check")
        self.assertIn("runs-on: windows-2022", catch)
        self.assertIn("needs: engine", catch)
        self.assertIn("catch_check.py --exe mega-check-inputs\\pokeemerald-mp-bfxtest.exe --make-save", catch)
        self.assertIn('throw "the catch check failed', catch)                  # a failed step fails the job
        self.assertIn("tools/battle_env/catch_check.py ../mega-check-inputs/", job("engine"))

    def test_the_rival_checkpoints_run_in_windows_game_processes(self):
        rival = job("rival-check")
        self.assertIn("runs-on: windows-2022", rival)
        self.assertIn("needs: engine", rival)
        self.assertIn("rival_check.py --binary native-inputs\\pokeemerald-mp.exe", rival)    # the player build
        self.assertIn("--facts mega-check-inputs\\rival-facts.json", rival)
        self.assertIn('throw "the rival check failed', rival)                  # a failed scene fails the job
        self.assertIn("rival-check/*.log", rival)                              # logs only: never the scenes' saves
        engine = job("engine")
        self.assertIn("rival_check.py --write-facts ../mega-check-inputs/rival-facts.json", engine)

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
