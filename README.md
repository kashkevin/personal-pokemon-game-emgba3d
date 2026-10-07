# Pokémon Emerald private multiplayer

This project targets a private adventure for one to four friends using Emerald as its foundation, with independent exploration and saves, Gen 1–5 Pokémon, Gen 5 mechanics, and intentional Mega Evolution support.

Current milestone: **Phase 1 baseline verification.** The pinned, unmodified engine has compiled twice from clean builds with identical ROM, ELF, and map hashes. The upstream automated suite completed with exit code 0 and its declared exceptions recorded; mGBA gameplay and save-isolation checks are pending. No multiplayer implementation or accepted playable checkpoint exists yet.

Read [the technical foundation](docs/technical-foundation.md) for the recommended stack, evidence, multiplayer and save architecture, constraints, and Phase 1 acceptance criteria. [The original project brief](docs/project-brief.txt) preserves the requested gameplay and phase order.

The requested delivery is a downloadable Windows game with **Host Game / Join Game**, for four players total including the host. The owner's PC hosts over home Wi-Fi, with direct Internet connections through port forwarding. Friends should need no compiler, Python installation, VPN, or manual emulator script setup. [Local PC setup](docs/local-pc-setup.md) records the packaging target, hosting setup, and development downloads. The game package and server have not been implemented yet.

The baseline is RHH `pokeemerald-expansion` at `expansion/1.17.1`, commit `bb1093a7c72d3961d9a37d8e02ad2abc2c866682`, built in Ubuntu 24.04 under WSL2. Windows mGBA 0.10.5 is installed for the pending [gameplay and save checks](docs/baseline-playtest.md). [The build record](docs/baseline-build.md) records versions, artifacts, and acceptance status; [the dependency ledger](docs/dependency-ledger.md) records provenance. A ROM mailbox, mGBA Lua bridge, local companion, and small persistent server remain proposed networking work.

Development must preserve small commits, repeatable tests, and known-good checkpoints. `RESEARCH_FOUNDATION_V1` records documentation only. `BASELINE_BUILD` may be created only after the unmodified source compiles reproducibly and passes gameplay and save checks.

ROMs, player saves, server databases, and private backups are excluded from Git. No ROM download or distribution is part of this repository.
