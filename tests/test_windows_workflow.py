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


def fixtures():
    """scripts/multiplayer/make_tower_saves.py, whose FIXTURES the jobs ask for by name."""
    import importlib.util
    import sys
    if str(ROOT / "scripts/multiplayer") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts/multiplayer"))
    spec = importlib.util.spec_from_file_location("make_tower_saves", ROOT / "scripts/multiplayer/make_tower_saves.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        # join-reset: the same with player 2's soft reset in place of the close (L tower-join-reset-1)
        self.assertIn('{name: join-reset, scenario: join, a: tower-join-a, b: tower-join-b, '
                      'extra: "--party-counts 3 6 --rejoin reset"}', proof)
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
        for name in ("tower", "breeding", "shiny", "rewards", "coop-exp", "rotom-catalog", "tm-catalogue", "item-hub",
                     "megas", "start-menu", "netlink", "minigame-partners", "frontier-saves", "trade-evolution", "tickets"):
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
        # KNOWN_ISSUES MS-118: the chunk cache's walk across four map seams with its terrain check, a failed check failing
        # the job (a chunk kept that differs, a stale skipped sync, or no chunk brought back at all)
        self.assertIn('PKMN_DIORAMA_TERRAIN_CHECK="1"', graphics)
        self.assertIn('PKMN_DEBUG_HERE="0,2,20,8"', graphics)
        self.assertIn('raise SystemExit("a chunk the cache kept differs from the one it would build")', graphics)
        self.assertIn("the walk did not cross the seams", graphics)
        # the same switch's buildings check (engine c8ba843f): reported, and a buffer that differs fails the job
        self.assertIn('buildings check: (\\d+) rebuilds checked, (\\d+) differed', graphics)
        self.assertIn('raise SystemExit("the buildings\' vertex buffer or generation differs from the triangles built")',
                      graphics)
        # a chunk kept though its cells' gameplay elevation changed (its signature leaves that out) is built again:
        # reported, and one that differs fails the job
        self.assertIn('terrain check: (\\d+) chunks kept with another gameplay elevation checked, (\\d+) differed',
                      graphics)
        self.assertIn("or any(differed for _, differed in kept)", graphics)

    def test_mr_brineys_sail_is_timed_and_checked_in_windows_game_processes(self):
        # KNOWN_ISSUES MS-82: the sail from Dewford to Route 104 (the game's own script, three map seams) timed with the
        # animated tiles' waits off and on, then sailed again with the terrain check: a sail that does not finish, or a
        # chunk kept that differs or is left stale, fails the job
        graphics = job("graphics-3d")
        self.assertIn("Mr. Briney's sail timed and checked (KNOWN_ISSUES MS-82)", graphics)
        self.assertIn('PKMN_DEBUG_HERE="0,11,11,9"', graphics)
        self.assertIn('PKMN_DEBUG_RIVAL_SET="f2e4=0,f2e7=0,fbd=1,f132=1"', graphics)
        self.assertIn('{"PKMN_DIORAMA_ANIMATED_WAITS": "0"} if kind == "off"', graphics)
        self.assertIn('sail(root / "check", {"PKMN_DIORAMA_TERRAIN_CHECK": "1"})', graphics)
        self.assertIn('"0.19" not in seams', graphics)                      # the boat reached Route 104
        self.assertIn('raise SystemExit("Mr. Briney\'s sail: " + "; ".join(failures))', graphics)

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

    def test_the_wireless_minigames_between_players_run_in_windows_game_processes(self):
        minigames = job("minigame-proof")
        self.assertIn("runs-on: windows-2022", minigames)
        self.assertIn("needs: [engine, symbol-sizes]", minigames)
        for activity, fixtures in (("berry_crush", "crush-a,crush-b"), ("pokemon_jump", "jump-a,jump-b"),
                                   ("dodrio", "dodrio-a,dodrio-b,dodrio-c"),
                                   # and each with four players, a world's most
                                   ("berry_crush", "crush-a,crush-b,crush-c,crush-d"),
                                   ("pokemon_jump", "jump-a,jump-b,jump-c,jump-d"),
                                   ("dodrio", "dodrio-a,dodrio-b,dodrio-c,dodrio-d")):
            self.assertIn(f"activity: {activity},", minigames)
            self.assertIn(f'fixtures: "{fixtures}"', minigames)
        self.assertIn("--only ${{ matrix.fixtures }}", minigames)
        self.assertIn("native_launcher_minigame_proof.py --activity ${{ matrix.activity }}", minigames)
        self.assertIn("--players ${{ matrix.count }}", minigames)
        self.assertIn('--source-d "$RUNNER_TEMP/intro/girl-2.sav"', minigames)
        self.assertIn("--game inputs/pokeemerald-mp.exe", minigames)             # the packaged Classic 2D game
        self.assertIn("--minigame-facts symbols/minigame-facts.json", minigames)
        # the facts of the very build, written before its strip (as the Mega proof's)
        engine = job("engine")
        facts = engine.index("minigame_facts.py --game pokeemerald-mp.exe --pe")
        self.assertLess(facts, engine.index("i686-w64-mingw32-strip --strip-all pokeemerald-mp.exe"))

    def test_world_trades_of_forms_and_a_trade_evolution_run_in_windows_game_processes(self):
        # KNOWN_ISSUES MS-194 (the reviewed forms) and MS-151 (the receiving game's trade evolution), on Windows
        trade = job("trade-proof")
        self.assertIn("runs-on: windows-2022", trade)
        self.assertIn("needs: [engine, symbol-sizes]", trade)
        self.assertIn("make_tower_saves.py", trade)
        self.assertIn("--only ${{ matrix.a }},${{ matrix.b }}", trade)
        self.assertIn('{name: forms, scenario: trade-forms, expect: "1071,1155", a: trade-forms-a, b: trade-forms-b}', trade)
        self.assertIn('{name: evolve, scenario: trade-evolve, expect: "1161,1160", a: trade-evolve-a, b: trade-evolve-b}',
                      trade)
        self.assertIn("native_launcher_newcomers_proof.py --scenario ${{ matrix.scenario }}", trade)
        # the species after the trade, for the entries that name them (the Mail and Egg entries name none)
        self.assertIn('if [ -n "${{ matrix.expect }}" ]; then expect=(--expect-species "${{ matrix.expect }}"); fi', trade)
        self.assertIn('"${expect[@]}" --game "$game"', trade)
        self.assertIn("game=\"${{ matrix.game || 'inputs/pokeemerald-mp.exe' }}\"", trade)   # the packaged Classic 2D game
        self.assertIn('--pe-symbols "symbols/$name.nm.txt"', trade)
        # the fixtures it asks for exist
        names = {fixture[0]: fixture[2] for fixture in fixtures().FIXTURES}
        self.assertEqual([names[n] for n in ("trade-forms-a", "trade-forms-b", "trade-evolve-a", "trade-evolve-b")],
                         ["1155:30", "1071:50:i403", "1157:30", "1158:30"])

    def test_world_trades_of_mail_and_eggs_run_in_windows_game_processes(self):
        # Owner decision 39: a Pokemon holding Mail and an Egg traded between two Windows games (the newcomers proof's
        # trade-mail and trade-egg, which ran on Linux first: TEST_LEDGER 2026-11-05)
        trade = job("trade-proof")
        self.assertIn("{name: mail, scenario: trade-mail, a: trade-mail-a, b: trade-mail-b}", trade)
        for where in ("party", "box"):
            self.assertIn(f'{{name: egg-{where}, scenario: trade-egg, a: trade-egg-a, b: trade-egg-b, '
                          f'extra: "--hatch-in {where}", game: mega-check-inputs/pokeemerald-mp-bfxtest.exe}}', trade)
        self.assertIn("--slow 1.5 ${{ matrix.extra }}", trade)
        # every entry's flags are ones the proof takes
        proof = (ROOT / "scripts" / "multiplayer" / "native_launcher_newcomers_proof.py").read_text(encoding="utf-8")
        taken = set(re.findall(r'parser\.add_argument\("(--[a-z0-9-]+)"', proof))
        extras = re.findall(r'extra: "([^"]*)"', trade)
        self.assertEqual(len(extras), 2)
        self.assertEqual(sorted({flag for extra in extras for flag in re.findall(r"--[a-z0-9-]+", extra)} - taken), [])
        # the Egg entries run the test build (its breed log through PKMN_TEST_LOG, its PKMN_TEST_EGG_TO_PC) with the
        # symbol table the engine job wrote before its strip; the proof no longer refuses Windows
        engine = job("engine")
        self.assertLess(engine.index("i686-w64-mingw32-nm -n pokeemerald-mp-bfxtest.exe > ../classic-pe-symbols/"),
                        engine.index("i686-w64-mingw32-strip --strip-all pokeemerald-mp-bfxtest.exe"))
        self.assertNotIn('require(not WINDOWS, "--scenario trade-egg', proof)
        self.assertIn('PKMN_TEST_LOG=str(Path(options["cwd"]) / TEST_LOG)', proof)
        # an engine whose game does not hatch a traded Egg right: its Egg entries say so and pass
        gate = trade[trade.index("id: feature"):trade.index("- name: Two new characters")]
        self.assertIn('[ "${{ matrix.scenario }}" = trade-egg ]', gate)
        self.assertIn("get('trade_egg_abi_version') != 1", gate)
        self.assertIn("::notice::", gate)
        self.assertEqual(trade.count("if: ${{ steps.feature.outputs.run == 'yes' }}"), 2)    # the fixtures, the trade
        # the fixtures it asks for exist
        names = {fixture[0]: fixture[2] for fixture in fixtures().FIXTURES}
        self.assertEqual([names[n] for n in ("trade-mail-a", "trade-mail-b", "trade-egg-a", "trade-egg-b")],
                         ["278:20:M204", "252:20:M203,263:20", "263:5,175:1:sI3.7.11.19.23.29g1", "258:5,263:5"])

    def test_the_legendary_tickets_run_in_windows_game_processes(self):
        # Owner decision 40 (docs/legendary-tickets.md 6.6): the ticket proof, which ran on Linux first (TEST_LEDGER)
        tickets = job("tickets-proof")
        self.assertIn("runs-on: windows-2022", tickets)
        self.assertIn("needs: [engine, symbol-sizes]", tickets)
        self.assertIn("make_intro_saves.py --exe mega-check-inputs/pokeemerald-mp-bfxtest.exe", tickets)
        self.assertIn("--only tickets-a,tickets-b", tickets)
        self.assertIn("scripts/multiplayer/native_launcher_ticket_proof.py", tickets)
        self.assertIn("--game inputs/pokeemerald-mp.exe", tickets)           # the packaged Classic 2D game
        self.assertIn("--pe-symbols symbols/pokeemerald-mp.nm.txt", tickets)
        self.assertIn("--sizes symbols/pokeemerald-mp.sizes.txt", tickets)
        self.assertIn('--source-a "$RUNNER_TEMP/tickets-saves/tickets-a.sav"', tickets)
        self.assertIn('--source-b "$RUNNER_TEMP/tickets-saves/tickets-b.sav"', tickets)
        # an engine without the tickets (no ticket_abi_version in its manifest): the job says so and passes
        gate = tickets[tickets.index("id: tickets"):tickets.index("- name: Two new characters")]
        self.assertIn("get('ticket_abi_version') != 1", gate)
        self.assertIn("::notice::", gate)
        self.assertEqual(tickets.count("if: ${{ steps.tickets.outputs.present == 'yes' }}"), 2)
        self.assertIn("name: EmeraldTogether-tickets-proof", tickets)
        self.assertIn("retention-days: 7", tickets)
        # the proof takes the Windows harness's arguments and the fixtures exist
        proof = (ROOT / "scripts" / "multiplayer" / "native_launcher_ticket_proof.py").read_text(encoding="utf-8")
        for flag in ("--pe-symbols", "--sizes", "--sdl", "--slow"):
            self.assertIn(f'parser.add_argument("{flag}"', proof)
        names = {fixture[0]: fixture[2:] for fixture in fixtures().FIXTURES}
        self.assertEqual(names["tickets-a"], ("252:30", None))
        self.assertEqual(names["tickets-b"][-1], "0x1BB,0x1BC,0x1BD,0x864")

    def test_a_coop_award_survives_a_game_closed_during_it_in_windows_game_processes(self):
        coop = job("coop-proof")
        self.assertIn("runs-on: windows-2022", coop)
        self.assertIn("needs: [engine, symbol-sizes]", coop)
        self.assertIn("make_tower_saves.py", coop)
        self.assertIn("--only coop-a,coop-b", coop)
        self.assertIn("native_launcher_coop_proof.py --close-during-award 1", coop)
        self.assertIn("--game inputs/pokeemerald-mp.exe", coop)             # the packaged Classic 2D game
        self.assertIn("--pe-symbols symbols/pokeemerald-mp.nm.txt", coop)

    def test_world_loading_with_many_saves_is_timed_on_windows(self):
        bench = job("world-open-bench")
        self.assertIn("runs-on: windows-2022", bench)
        self.assertNotIn("needs:", bench)                                 # no game: every mode, smoke runs too
        self.assertIn("tools/perf/world_open_bench.py --saves 300 --repeat 3 --max-seconds 60", bench)
        # KNOWN_ISSUES NU-7: a friend's code replaced, on Windows, by the host world's and the stored invite's own tests
        self.assertIn('"test_host_world.CredentialReplacementTests", "test_shell_records.InvitationReplacementTests"', bench)
        self.assertIn("result.wasSuccessful() and result.testsRun >= 8", bench)
        # Save integrity: the world server's process killed mid-upload or mid-commit, on Windows (TerminateProcess)
        self.assertIn('loadTestsFromNames(["test_server_killed_mid_save"])', bench)
        self.assertIn("result.wasSuccessful() and result.testsRun >= 1", bench)
        # The save path's own tests on Windows: the store (MS-195), ownership, checkpoints, battle journals, autosave
        for name in ("test_storage", "test_ownership_storage", "test_checkpoint_server", "test_battle_journal",
                     "test_live_checkpoint", "test_autosave", "test_launcher_save", "test_shared_world"):
            self.assertIn(f'"{name}"', bench)
        self.assertIn('os.environ["PYTHONPATH"] = os.pathsep.join(paths)', bench)   # their child processes import the app
        self.assertIn("result.testsRun >= 300 and not other", bench)          # only the two checkout-dependent skips

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
        # (app-tests: in every full run and alone when asked in any mode: test_the_apps_whole_suite_...)
        checks = [name for name in re.findall(r"^  ([a-z0-9-]+):\n", WORKFLOW, re.M)
                  if name not in ("push", "engine", "symbol-sizes", "install-check", "app-tests")]
        self.assertIn("abandon-check", checks)
        self.assertIn("package", checks)
        for name in checks:
            with self.subTest(job=name):
                key = {"gameplay-report": "gameplay-check", "gameplay-report-3d": "gameplay-check-3d"}.get(name, name)
                condition = re.search(r"^    if: (.*)$", job(name), re.M).group(1)
                self.assertTrue(condition.endswith(
                    f"&& (!inputs.only || contains(format(',{{0}},', inputs.only), ',{key},')) }}}}"), condition)
        for name in ("engine", "symbol-sizes"):
            # The builds always run: `only` never gates them (only: package merely leaves the check jobs' test builds
            # and their uploads out of the engine job, for an installer alone).
            self.assertNotIn("inputs.only", re.search(r"^    if: (.*)$", job(name), re.M).group(1))
        steps = [line.strip() for line in job("engine").splitlines() if "inputs.only" in line]
        self.assertEqual(steps, ["QUICK: ${{ inputs.only == 'package' && '1' || '' }}"]
                         + ["if: ${{ inputs.only != 'package' }}"] * 3)
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

    def test_apt_never_holds_a_build_for_good(self):
        # Runs 153 and 156 (2026-10-22): the engine build's apt-get update hung with no output for an hour.
        gameplay = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "gameplay-check.yml").read_text()
        for text in (job("engine"), job("symbol-sizes"), gameplay):
            self.assertIn("99ci-timeouts", text)
            self.assertIn("timeout 300", text)
            self.assertIsNone(re.search(r"^\s+(sudo )?apt-get update", text, re.M))
        # Runs 280 and 282 (2026-11-04): the engine build's install stalled three times with no output: the packages
        # are fetched, then installed, each part with its own tries, and a part out of time shows apt's state first.
        engine = job("engine")
        fetch = engine.index("--download-only")
        self.assertLess(fetch, engine.index("--no-download"))
        self.assertIn("DPkg::Lock::Timeout=120", engine)
        self.assertEqual(engine.count('apt_state "$attempt'), 2)
        self.assertNotIn("apt-get install -y -qq", engine)

    def test_a_failed_launcher_proof_prints_its_diagnosis_in_the_log(self):
        # Run 138's ffa-exit: the evidence went to an artifact a session reading the log could not fetch.
        for name in ("tower-proof", "rival-proof", "mega-proof", "minigame-proof", "coop-proof", "trade-proof",
                     "tickets-proof", "abandon-check", "multiplayer-check"):
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

    def test_the_crash_report_runs_in_windows_game_processes(self):
        crash = job("crash-check")
        self.assertIn("runs-on: windows-2022", crash)
        self.assertIn("needs: engine", crash)
        self.assertIn("crash_check.py --exe mega-check-inputs\\pokeemerald-mp-bfxtest.exe --out", crash)
        self.assertIn('throw "the crash report check failed', crash)            # a failed step fails the job
        self.assertIn("tools/battle_env/crash_check.py ../mega-check-inputs/", job("engine"))
        # the packaged games' symbol tables stay for their crash reports
        self.assertIn("name: EmeraldTogether-release-symbols", job("engine"))
        self.assertIn("retention-days: 90", job("engine"))

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

    def test_every_multiplayer_entrys_flags_are_ones_the_proof_takes(self):
        proof = (ROOT / "scripts" / "multiplayer" / "native_launcher_newcomers_proof.py").read_text()
        taken = set(re.findall(r'parser\.add_argument\("(--[a-z0-9-]+)"', proof))
        extras = re.findall(r'\{name: ([a-z0-9-]+), scenario: [a-z-]+, players: \d, format: [0-9v]+(?:, extra: "([^"]*)")?'
                            r'(?:, [a-z]+: [^,}]+)*\}', job("multiplayer-check"))
        names = {name for name, _ in extras}
        self.assertTrue({"trade-lag", "trade-rough", "battle-rough", "battle-trade-3d"} <= names, names)
        for name, extra in extras:
            with self.subTest(entry=name):
                self.assertEqual(sorted(set(re.findall(r"--[a-z0-9-]+", extra)) - taken), [])
        rough = dict(extras)["trade-rough"]
        self.assertIn("--jitter-ms 80", rough)
        self.assertIn("--stall-every 45 --stall-ms 2500", rough)

    def test_the_apps_whole_suite_runs_on_windows_in_every_full_run_and_when_asked(self):
        tests = job("app-tests")
        self.assertIn("runs-on: windows-2022", tests)
        # asked alone in any mode (a smoke run builds no game: the quickest way to it), and every full run's package
        self.assertIn("if: ${{ contains(format(',{0},', inputs.only), ',app-tests,') "
                      "|| ((inputs.mode || 'smoke') == 'full' && !inputs.only) }}", tests)
        self.assertNotIn("needs:", tests)                                   # no game: it needs no build
        self.assertIn("--require-hashes --only-binary=:all: -r requirements-host-provisioning.txt", tests)
        self.assertIn("pytest==9.1.1 pytest-timeout", tests)                # as python-tests installs them
        self.assertIn('.venv/Scripts/python -m pytest -rfE --junitxml="$RUNNER_TEMP/pytest-windows.xml"', tests)

    def test_the_gameplay_plan_runs_in_the_3d_game_on_windows_with_the_gameplay_check(self):
        check = job("gameplay-check-3d")
        self.assertIn("runs-on: windows-2022", check)
        self.assertIn("needs: engine", check)
        # As gameplay-check: a full run with gameplay_qa (Windows run 308 passed all eight shards when asked alone).
        self.assertIn("if: ${{ (inputs.mode || 'smoke') == 'full' && inputs.gameplay_qa == 'yes' && (!inputs.only || "
                      "contains(format(',{0},', inputs.only), ',gameplay-check-3d,')) }}", check)
        self.assertIn("shard: [0, 1, 2, 3, 4, 5, 6, 7]", check)
        self.assertIn("GALLIUM_DRIVER: llvmpipe", check)
        self.assertIn("MESA_SHA256: 351fc8c8b695878ffb3eaa044b3ead08672a48b1a045e3c3e3975811df0f6695", check)
        self.assertIn("if ($hash -ne $env:MESA_SHA256) { throw", check)      # the pinned archive or nothing
        self.assertIn("--probe-graphics", check)
        self.assertIn("--exe diorama-check-inputs\\pokeemerald-mp-diorama-bfxtest.exe", check)   # the 3D test build
        self.assertIn("--shard ${{ matrix.shard }} --shards 8 --jobs 1 --speed 4 --process-timeout 10800", check)
        self.assertIn("Remove-Item -Force", check)                         # no save in the uploads
        self.assertIn("name: gameplay-windows-3d-shard-${{ matrix.shard }}", check)
        report = job("gameplay-report-3d")
        self.assertIn("needs: [engine, gameplay-check-3d]", report)
        self.assertIn("inputs.gameplay_qa == 'yes' && needs.engine.result == 'success'", report)
        self.assertIn("contains(format(',{0},', inputs.only), ',gameplay-check-3d,')", report)
        self.assertIn("pattern: gameplay-windows-3d-shard-*", report)
        self.assertIn("merge_gameplay_shards.py --shards shards --expected 8", report)

    def test_giving_up_a_battle_between_players_runs_on_windows(self):
        # KNOWN_ISSUES MS-126: the give-up from the waiting screen, with the other player away and once the master has
        # begun the turn (the newcomers proof's give-up scenarios), in real Windows game processes.
        mp = job("multiplayer-check")
        self.assertIn("- {name: give-up, scenario: give-up, players: 2, format: 1v1v1v1}", mp)
        self.assertIn("- {name: give-up-mid-turn, scenario: give-up-mid-turn, players: 2, format: 1v1v1v1}", mp)
        proof = (ROOT / "scripts" / "multiplayer" / "native_launcher_newcomers_proof.py").read_text(encoding="utf-8")
        self.assertIn('GIVE_UPS = ("give-up", "give-up-mid-turn", "give-up-knockout", "give-up-switch", "give-up-2v2")',
                      proof)
        self.assertIn("delay_battle_messages_to(", proof)        # the giver's game hears of the turn late
        self.assertIn('require(before_notice, f"{label}: the notice reached the host before the master began the turn")',
                      proof)

    def test_the_give_ups_never_run_before_run_on_windows(self):
        # KNOWN_ISSUES MS-126's cases first run on Linux on 2026-11-06: a give-up in a turn that would end the battle,
        # the battle ending another way after the notice, a 2v2, a co-op Gym battle and a Tower Duo battle given up.
        mp = job("multiplayer-check")
        self.assertIn("- {name: give-up-knockout, scenario: give-up-knockout, players: 2, format: 1v1v1v1, "
                      "a: giveup-ko-a, b: giveup-ko-b}", mp)
        self.assertIn("- {name: give-up-switch, scenario: give-up-switch, players: 2, format: 1v1v1v1, "
                      "a: giveup-switch-a, b: giveup-switch-b}", mp)
        self.assertIn("- {name: give-up-2v2, scenario: give-up-2v2, players: 4, format: 2v2}", mp)
        # an entry's fixtures are made from the first two characters and are that entry's sources
        self.assertIn("if: ${{ matrix.a && (!contains(inputs.only, 'mp:')", mp)
        self.assertIn('--source-b "$RUNNER_TEMP/intro/girl-1.sav" --out "$RUNNER_TEMP/fixture-saves" '
                      '--only ${{ matrix.a }},${{ matrix.b }}', mp)
        self.assertIn('sources=(--source "$RUNNER_TEMP/fixture-saves/${{ matrix.a }}.sav" '
                      '--source "$RUNNER_TEMP/fixture-saves/${{ matrix.b }}.sav")', mp)
        self.assertLess(mp.index('for n in $(seq 0'), mp.index('if [ -n "${{ matrix.a }}" ]; then'))
        names = {fixture[0]: fixture[2] for fixture in fixtures().FIXTURES}
        self.assertEqual([names[n] for n in ("giveup-ko-a", "giveup-ko-b", "giveup-switch-a", "giveup-switch-b")],
                         ["150:100:v605", "150:100:v605", "76:50:v153,292:20", "291:30:v191,263:5"])
        coop = job("coop-proof")
        self.assertIn("native_launcher_coop_proof.py --give-up 1", coop)
        self.assertIn('--output "$RUNNER_TEMP/multiplayer-proof/coop-give-up"', coop)
        self.assertIn("if: ${{ !cancelled() }}", coop)          # also after the award's step failed
        coop_proof = (ROOT / "scripts" / "multiplayer" / "native_launcher_coop_proof.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--give-up"', coop_proof)
        tower = job("tower-proof")
        self.assertIn('- {name: duo-give-up, scenario: duo-give-up, a: tower-forfeit-a, b: tower-forfeit-b, '
                      'extra: "--party-counts 6 6 --give-up 2"}', tower)
        tower_proof = (ROOT / "scripts" / "multiplayer" / "native_launcher_tower_proof.py").read_text(encoding="utf-8")
        self.assertIn('"championship", "duo-give-up"),', tower_proof)
        self.assertIn('parser.add_argument("--give-up"', tower_proof)

    def test_a_battle_and_trades_between_players_run_in_the_3d_game_on_windows(self):
        mp = job("multiplayer-check")
        self.assertIn('{name: battle-trade-3d, scenario: battle-trade, players: 2, format: 1v1v1v1, extra: "--light-3d", '
                      'game: inputs/pokeemerald-mp-diorama.exe, mesa: "yes"}', mp)
        self.assertIn("Mesa's software OpenGL (32-bit) for the 3D game (pinned; the 3D entry)", mp)
        self.assertIn("matrix.mesa == 'yes'", mp)
        self.assertIn("MESA_SHA256: 351fc8c8b695878ffb3eaa044b3ead08672a48b1a045e3c3e3975811df0f6695", mp)
        self.assertIn("GALLIUM_DRIVER: llvmpipe", mp)
        self.assertIn("game=\"${{ matrix.game || 'inputs/pokeemerald-mp.exe' }}\"", mp)   # the Classic game otherwise
        self.assertIn('--pe-symbols "symbols/$name.nm.txt"', mp)
        self.assertIn('"${runtime_extra[@]}"', mp)
        engine = job("engine")
        self.assertIn("pokeemerald-mp-diorama.exe > ../classic-pe-symbols/pokeemerald-mp-diorama.nm.txt", engine)

    def test_move_switching_shiny_spawns_and_the_game_corner_run_in_windows_game_processes(self):
        checks = job("feature-checks")
        self.assertIn("runs-on: windows-2022", checks)
        self.assertIn("needs: engine", checks)
        self.assertIn("mega_check.py --exe $exe --make-save $save", checks)    # a save of the short introduction
        for check in ("move_switch_check", "shiny_check", "acro_check", "flymap_check"):
            self.assertIn(f'{check} = "mega-check-inputs\\{check}.py"', checks)
        # The RARE GOODS check beside the engine files it reads (run 219: none on the runner).
        self.assertIn('casino_check = "mega-check-inputs\\casino\\tools\\battle_env\\casino_check.py"', checks)
        self.assertIn('throw "failed:', checks)                                # any failed check fails the job
        self.assertIn("if (-not (Test-Path $save))", checks)                   # the save is made (mega_check exits 1 on 0 of 0)
        self.assertNotIn(".sav", checks.split("upload-artifact")[1])           # reports and pictures, never the save
        engine = job("engine")
        self.assertIn("for check in move_switch_check shiny_check; do", engine)
        # The Acro Bike's check beside the mega_check it imports (MS-171).
        self.assertIn("cp tools/battle_env/acro_check.py ../mega-check-inputs/", engine)
        self.assertIn("cp tools/battle_env/flymap_check.py ../mega-check-inputs/", engine)    # Fly from the Town Map
        for file in ("tools/battle_env/casino_check.py", "tools/battle_env/mega_check.py", "include/constants/items.h",
                     "src/platform/mp_rare_goods_prices.h", "data/scripts/mp_rare_goods_shop.inc"):
            self.assertIn(file, engine)
        self.assertIn('cp "$file" "../mega-check-inputs/casino/$file"', engine)
        # The TM catalogue's check (2026-10-31) beside the catalogue's lists and the move numbers it reads.
        self.assertIn('tm_catalogue_check = "mega-check-inputs\\casino\\tools\\battle_env\\tm_catalogue_check.py"', checks)
        for file in ("tools/battle_env/tm_catalogue_check.py", "include/constants/moves.h",
                     "data/scripts/mp_tm_catalogue_lists.inc"):
            self.assertIn(file, engine)
        # The item hub (2026-10-31): its check, and the lists the RARE GOODS and Rotom Catalog checks read since then.
        self.assertIn('item_hub_check = "mega-check-inputs\\casino\\tools\\battle_env\\item_hub_check.py"', checks)
        for file in ("data/scripts/mp_item_hub_lists.inc", "src/platform/mp_item_hub.h", "tools/battle_env/item_hub_check.py"):
            self.assertIn(file, engine)
        # The reset-guarded static encounters offline (MS-156): their plan made by the engine job, run from that save.
        self.assertIn("--plan-only --static-encounters", engine)
        self.assertIn("--out ../gameplay-inputs/static-plan", engine)
        self.assertIn("name: gameplay-inputs", checks)
        self.assertIn("--plan gameplay-inputs\\static-plan\\plan.json", checks)
        self.assertIn("--static-encounters --save $save", checks)
        self.assertIn('$failed += "static encounters (exit $LASTEXITCODE)"', checks)

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
        uploads = re.findall(r"uses: actions/upload-artifact@v\d+\n\s+with:\n(.*?)(?=\n      - |\n  [a-z-]+:\n|\Z)",
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
