# Native Players menu

Engine `84a4d1c1e906bd7340b9d08b231e485b0fa5c07c` adds an in-game Players menu on top of the qualified six-slot preview source. The normal and debug Start menus retain their original number of rows: the player's name opens **CARD / PLAYERS / BACK**. CARD uses the original Trainer Card/Frontier Pass callback. Special native link and facility menus retain their existing entry behavior.

The [native source patch](../engine-patches/phase5-native-players-menu.patch), based on `bcb8ff837fcb333e72d5d84894bce7421e781ef2`, has SHA-256 `a788a870e50952c998976b060002a9ab258f6a674f7552a60b0cfdcf82e4ca4c`; its reverse-apply check passed. Local Soft Reset remains disabled in this normal build. This menu supports explicit team and challenge choices; it does not yet hand an accepted challenge to the automatic native battle coordinator or display trade consent during a native save hold.

## Reuse and bounded interface

The implementation reuses the pinned engine's Start menu, windows, border, fonts, text printing, field locks and key input. The existing [reuse audit](customization-and-reuse.md) identified these components and the absence of a compatible complete authenticated persistent-world interaction system in the reviewed sources. Current official [Start menu](https://github.com/rh-hideout/pokeemerald-expansion/blob/6057b187f946094d614e9c34bc12731ea6a5b7bb/src/start_menu.c) and [window/menu implementation](https://github.com/rh-hideout/pokeemerald-expansion/blob/6057b187f946094d614e9c34bc12731ea6a5b7bb/src/menu.c) at maintained master `6057b187f946094d614e9c34bc12731ea6a5b7bb` retain the same reusable foundation. No upstream source or third-party library is newly imported; existing provenance remains in the [dependency ledger](dependency-ledger.md).

Menu ABI 1 owns a separate 512-byte EWRAM mailbox, marked by `gMultiplayerMenuAbiVersion`. Its 16-byte native request identifies a monotonically increasing request sequence, displayed screen, action and Open/Choose/Close kind. Its 240-byte external screen carries the acknowledged request, screen revision, up to six indexed rows, and Back action 0 or 7. Stable even generations fence both directions. Text is bounded, NUL-padded printable ASCII and is explicitly translated into native glyphs; unsupported printable punctuation becomes `?`. External strings cannot inject native formatting or script controls. The bridge and manifest resolve exact allocated addresses from the matching ELF.

Only a connected, enrolled, idle bound character at the native safe field point can open. While the menu owns the screen, ordinary callbacks, playtime and frame RNG advancement pause for that core; presence reports unavailable and save/battle preparation sees an unsafe field point. Existing native save/battle holds cannot coexist with this first menu implementation. Audio, VBlank processing and the bounded bridge continue. Other cores continue independently.

Choices wait for the exact current request's new screen revision. Disabled rows cannot send actions. B chooses a subpage's Back action or closes locally; B also remains available while waiting for a response. Closing releases the window and field locks before publishing a newer Close request. A disconnect or changed native binding follows the same cleanup. The sequence survives menu reopen and only resets with the ROM incarnation, preventing a late response from reopening an old interaction. A local close does not fabricate server cancellation or rollback an already dispatched consent.

The normal build uses **233,428 bytes of EWRAM** and **28,376 bytes of IWRAM**, including the mailbox, accepted screen and small runtime state. This is an allocation measurement, not a frame-rate/performance qualification. No save-block layout or native battle packet ABI changes.

## Qualification

All **79 focused multiplayer C tests passed**, including six new menu cases covering canonical text/padding, action bounds, stable generations, request/screen ordering, blocked duplicate input, disabled rows, Back/Close distinctions, host close, reopen, disconnect and safe character translation. Normal build and focused logs contain no warnings. The complete native regression on this exact clean source then finished with exit code 0: **5,493 passed**, 18 known failing, 421 TODO and nine expected failing cases, 5,941 total, with no unexpected failures. Its complete private log was copied to the physical Windows artifact archive and hash-verified. These fixtures supplement the actual-core evidence below.

`native-players-menu-run-2` passed **nine checks** across four actual headless cores with legitimately prepared six-Pokémon parties. Its **159 ordinary joypad operations** and **13 sets of four screenshots** exercise:

- Visible Player submenu and Players screens, with another character's ordinary Start menu opening/closing while the first character's party, RNG and playtime stay unchanged.
- Team invitation, recipient acceptance, leaving, and forming both teams through native menu selections.
- A four-player full-party challenge: all four native menu consents match the same authoritative checkpoint fingerprint, followed by explicit cancellation before BIND. Every native battle mailbox remains idle; no battle completion is fabricated.
- A captured old UI response delivered through the allocated production UI mailbox after close/reopen. It cannot replace the current screen or replay a choice.
- An intentionally dropped bridge connection. Native cleanup publishes a newer Close request, and the authenticated bridge reconnects.
- Unchanged party and Flash bytes for all four characters before intentional checkpoints; four ordinary checkpoint revisions 2; fresh Continue with matching canonical parties and maps; unchanged original source saves and all eight initial/fresh core processes closed.

The home and four-player challenge screenshots were visually inspected: labels, counts, disabled participant rows, cursor and Back/Close text are visible and contained inside the native window. This is functional headless acceptance of the menu boundary and authenticated team/challenge service path. Automatic battle handoff, trade consent, Windows presentation, separate PCs, Wi-Fi/Internet behavior and performance remain separate acceptance work.

The first run is preserved as **failed**, not playable acceptance. Its renderer drew the border after the text, and the native frame function cleared the printed pixels. Actual screenshots exposed that defect even though the typed menu state and ordinary buttons progressed. The corrected source draws the frame before text. The first proof also read several diagnostics across the instant of native disconnect cleanup; the second controller takes one bounded read-only snapshot instead. Both runs closed their processes and retained original saves.

| Corrected artifact | SHA-256 |
| --- | --- |
| Normal ROM | `bb322038d761cd04b9a525b058c953b8b479402054e895a7ea8a19664d344435` |
| ELF | `51674d14225522a14d6379fe509927d15e2704e00d31ab4b775db2e766f1c993` |
| Build manifest | `1d1d89070b503acdda9238cb66bafe365d10f813fc96d967379aebefe63d49c7` |
| Focused C log | `239e77896d249d5f63e1126a2cce30c0ca01552f03881d93b21ca84a0ed6b7a7` |
| Complete C regression log | `f7c0442d6a33442a1a41b456d9ebb5f4e80a110aa87272f664dcaee9e98ed118` |
| Complete private run-2 evidence | `e2312df5019f021c9f11f3aa8b348d35098b7db1d5a88779388fcfa7a7f2955b` |
| Frozen run-2 controller | `0fc28eebf1583c3086e1afcd761ddf1af68f3cfaf69f8515651e20e44c4c0950` |
| Frozen production bridge source | `2ca0ebaf228f5636b93fd130346606e4d86748770d94bc85f998e8ac903bf8de` |

The corrected build is frozen at `/home/kevin/src/pokemon/multiplayer-proof/native-players-menu-dev0-build-84a4d1c`; proof evidence is under `native-players-menu-run-2`. Physical private Windows archives retain six files for each build, 88 files for failed run 1 and 129 files for accepted run 2, with every copied file hash-verified. ROMs, credentials, private save sources and databases are excluded from Git.
