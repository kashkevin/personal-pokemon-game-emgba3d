# Pokémon Emerald private multiplayer

This project targets a private adventure for one to four players total using Emerald as its foundation, with independent exploration and saves, Gen 1–6 Pokémon, Gen 6 mechanics including Fairy, 18 starters, and all eligible officially released Mega Evolutions, including later additions.

Current checkpoint: **verified localhost two-player movement prototype.** Two actual Emerald cores render each other, move independently, handle menus/maps/battles, and recover from pause, disconnect, and server restart. Ordinary local saving/reload preserves separate parties and excludes remote avatars. The server and companion also pass 44 tests on Windows and WSL. Windows GUI/LAN delivery, four actual game clients, and durable server state remain ahead. [Phase 2 evidence and limits](docs/phase2-presence.md)

Read [the current master specification](docs/master-spec.md) for the accepted gameplay and phase order, [the technical foundation](docs/technical-foundation.md) for the stack and architecture, and [the Gen 6 foundation audit](docs/gen6-foundation-update.md) for configuration requirements and later Mega adaptations. [The original brief](docs/project-brief.txt) and [Generation 6 update](docs/project-update-gen6.txt) are preserved verbatim; the update takes precedence where they differ.

The requested delivery is a downloadable Windows game with **Host Game / Join Game**, for four players total including the host. The owner's PC hosts over home Wi-Fi, with direct Internet connections through port forwarding. Friends should need no compiler, Python installation, VPN, or manual emulator script setup. [Local PC setup](docs/local-pc-setup.md) records the packaging target, hosting setup, and development downloads. The player package remains future work; the current server is a local/LAN presence prototype.

The baseline is RHH `pokeemerald-expansion` at `expansion/1.17.1`, commit `bb1093a7c72d3961d9a37d8e02ad2abc2c866682`, built in Ubuntu 24.04 under WSL2. The [build record](docs/baseline-build.md) records versions, artifacts, and acceptance status; the [dependency ledger](docs/dependency-ledger.md) records provenance. The Lua bridge, companion, transient server, allocated ROM mailbox, remote-avatar adapter, and real-core test tools are implemented. Persistent multiplayer state is the next implementation phase.

Development must preserve small commits, repeatable tests, and known-good checkpoints. `RESEARCH_FOUNDATION_V1` records documentation only. The engine's `BASELINE_BUILD` preserves the accepted unchanged source, and `MULTIPLAYER_POC` records the local movement prototype. Private build artifacts and save evidence remain archived.

ROMs, player saves, server databases, and private backups are excluded from Git. No ROM download or distribution is part of this repository.
