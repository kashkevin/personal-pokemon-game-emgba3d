# Actual native battle history proof

`native-battle-archive-run-1` passed seven checks on four actual headless cores using the frozen native Players build `84a4d1c1e906bd7340b9d08b231e485b0fa5c07c` and application source `fc509d022553c8ad300efc0bd677ea9dd16201f4`. The four independent, ordinarily prepared parties contained **6/1/1/1 Pokémon**. The native battle completed normally with fixed-side outcome **1**, after **1,078 routed blocks** and **21 sets of screenshots**. This is a short integration check for [durable completed history](battle-results.md); the retained [full-party battle proof](native-full-multi.md) covers the separate four-trainer, six-per-trainer case.

## Observed behavior

The private development coordinator used the production native battle mailbox, typed routing and trusted `BattleDesk`. Battle choices came from ordinary joypad input. Diagnostic reads observed core state and Flash; the controller used neither savestates nor arbitrary gameplay-memory writes.

- All four games continued their own saves, enrolled their canonical parties, and prepared the exact authenticated trainer rosters.
- The battle returned the same normalized outcome on all four cores. Each core restored its original party, party count, RNG states and save counter exactly. Flash remained byte-identical before the intentional post-battle checkpoints; ordinary elapsed playtime was not rewound.
- Authenticated history was empty after each of the first three native RELEASE receipts. The fourth successful release published exactly one result, with the original battle/generation IDs, ordered participants, format, outcome and canonical party counts. Publication left every canonical checkpoint unchanged.
- Replaying the exact final validated RELEASE receipt to the trusted Desk returned the existing result without duplication. This retry sent no additional native command.
- All four players returned to their original maps and completed ordinary native checkpoint revision 2 while preserving owned inventories. Fresh cores then continued those checkpoints with matching parties and locations.
- The server and character store closed, then reopened from the same private files with new battle admission disabled. Four newly authenticated companions read the same single historical result. Canonical revisions, hashes and payloads remained unchanged by restart/history reads.
- All eight initial/fresh core processes closed. The four immutable source saves retained their original hashes. The controller exited successfully with no recorded error.

This qualifies actual-core publication, exact retry and authenticated loopback history across a clean host restart. It does not qualify automatic menu-to-battle handoff, interruption settlement, wagers/rewards, packaged Windows history presentation, separate PCs, Wi-Fi/Internet or gameplay performance. New battle execution remains development gated. The later home-menu history shortcut when challenges are disabled is separately tested application behavior and was not part of the frozen `fc509d0` controller run.

## Frozen evidence

The host package, proof helpers and production bridge were exported from the exact application commit with `git archive`. A private controller and per-file SHA-256 manifest complete the snapshot. Every recorded input was verified before launch; imports used the private snapshot rather than the changing working checkout.

| Artifact | SHA-256 |
| --- | --- |
| Native ROM | `bb322038d761cd04b9a525b058c953b8b479402054e895a7ea8a19664d344435` |
| Native ELF | `51674d14225522a14d6379fe509927d15e2704e00d31ab4b775db2e766f1c993` |
| Native build manifest | `1d1d89070b503acdda9238cb66bafe365d10f813fc96d967379aebefe63d49c7` |
| Frozen host-source manifest | `44e58857d3d69766f3a142fb56665ef7a1ab161fa2d8c475912a140dd1056956` |
| Actual-core controller | `6a6dd6a5243378353b37d64a3a22973d0d841a347d646067856d5817e95416ce` |
| Production bridge source | `2ca0ebaf228f5636b93fd130346606e4d86748770d94bc85f998e8ac903bf8de` |
| Complete private evidence | `061dce39a22cabbb7f9e4f0bc934089bfaea40b230b509633c2b228a58cfd930` |
| Run log | `a172c9f8c1506dc68ec4d0ba515cd7e938030e81019163f2fc0acb5e0dd61313` |
| Private copy verification | `c69d8bff45e853762cf0318838eec1e0d38379a2fa98dcce2a6406766a4f27d4` |

The exact native build is frozen under `/home/kevin/src/pokemon/multiplayer-proof/native-players-menu-dev0-build-84a4d1c`. Host source and actual evidence are under `native-battle-archive-host-fc509d0` and `native-battle-archive-run-1`. Physical Windows private archives retain all **83 host snapshot files**, **161 run files**, the run log and complete C regression log, with every copied file hash-verified. The copy-verification JSON was also copied and byte-verified. ROMs, save files, credentials and databases remain outside Git.

The same native source's complete C regression passed **5,493 cases**, with no unexpected failures; [native Players menu qualification](native-players-menu.md) records the baseline known failures, TODOs, focused tests and exact log hash separately.
