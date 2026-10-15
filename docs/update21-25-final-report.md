# Updates 21-25: final report (quality and polish phase)

Branches: app `claude/dev-update21-25`, engine `claude/dev-update21-25-engine` (`677821af`). Private Windows build: run 38757166230, artifact
**EmeraldTogether-windows-full** (ID 11984854602, expires 2026-10-22). Nothing merged into a default branch. **Not a release claim:** nothing was run on real
hardware or over a real network; bios.c licensing is unresolved.

1. **Completed.** 21 four-player battle screen (names, tags, FOE plates, OUT tag, facing sprite, text) + visual regression check; 22 visual/audio audit tools and results (29 maps in 3D, quality presets,
   all 558 song numbers), loudness fix; 23 save-compatibility fixtures and tests (Update 14 databases open, exactly-once, no growth); 24 PokeNav location privacy, Xbox B, balance/controls review; 25 integration, tests, Windows build.
2. **Remains.** Real-PC and real-network testing of everything; 3D fallback for multi-piece vehicles (trucks, cable car, ferry); the sweep of interiors/caves and the other ~800 maps; BP shop/rate decisions; loudness by ear; a launcher checkbox for the privacy setting; Classic 2D target names; old real-run journals/saves as fixtures.
3. **Visual evidence.** Session scratch folder `evidence21/` (not in Git): four-player 2D and 3D screens, move/target/elimination states, 2v2 comparisons, 29-map 3D contact sheet, Low/Medium quality.
4. **Automated results.** GBA release ROM sha256 f214735b…3387 unchanged (rebuilt after the last engine change); GBA test ROM full run 5532 passed, 39 failed = expected list, 0 new; FFA subset 25/25; PC selftests 0 failures (`check-native` 28,217; keybinds 30; 20 more targets); ABI parity 172 types; app suite: all pass (one load-dependent timing test passed on its own); new tests: privacy (9), save compatibility (6), pad table (9 checks); visual check signatures.
5. **Commits.** See `DEVELOPMENT_LEDGER.md` Updates 21-25.
6. **Artifact.** As above (private to the repository, 7 days).
7. **Owner decisions.** `docs/owner-decisions.md` "Added by Updates 21-25" (Xbox B, 3D vehicles, loudness, BP prices, privacy surface).
8. **Real-PC checklist.** `docs/windows-test-update21-25.md`.
