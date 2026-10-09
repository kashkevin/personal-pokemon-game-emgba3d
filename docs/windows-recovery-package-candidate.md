# Private Windows recovery package candidate 7

October 8, 2026. A new private package at `%LOCALAPPDATA%/PokemonPrivate/artifacts/windows-runtime/launcher-package-7-recovery-1` builds the current 81 production Python modules, the production Lua bridge and corrected input-guard runtime against the cleanup-capable native game pins. The earlier accepted packages and original sources are unchanged. **This is not a friend-ready download:** it has no real own-dump BPS patch and cannot import a new player's game.

The existing pinned Windows build environment was reused; no dependency was installed. A separate 101-file source freeze and 140 original-input hashes are retained in sibling `launcher-package7-preparation-1`. Only that freeze's readable `RELEASE-LIMITS.txt` was adapted to describe this candidate. Production code, the repository's historical guide and earlier packages were not rewritten. The prepared runtime retains the candidate executable/DLL/source/relink bytes; its manifest and provenance now bind the exact current production bridge, without any proof input/diagnostic suffix.

The existing `build_launcher.py` completed in **35.499 seconds** at BelowNormal priority. Its recursive audit inspected 6,473 tree members/files across 14 nested archives and 537,878,066 expanded bytes; the ZIP audit inspected 6,570 members/files across 15 archives and 596,035,882 bytes. This is the existing bounded format/content audit, not a guarantee about every asset's distribution rights. [Audit implementation](../scripts/windows-runtime/package_audit.py), [dependency ledger](dependency-ledger.md).

Root independently verified all 1,086 packaged file hashes, ZIP CRCs and exact ZIP member bytes, all 81 current/frozen application modules, all 101 frozen sources and all 140 original inputs. The ZIP is **58,157,816 bytes**. `import_enabled` is false and no `game.bps` is present. The included runtime passed four no-ROM command checks: version, no-ROM help, missing-save refusal and missing-script refusal. Runtime manifests verified before and after those checks.

The actual packaged `EmeraldTogether.exe` also opened in a fresh isolated process-local `LOCALAPPDATA` sandbox. Computer-use observation confirmed the candidate label, Host Game/Join Game tabs, disabled Import my game with its missing-patch explanation, and the inactive Save now/autosave/recovery/cancellation controls. No world or invitation was selected, no game started, and no network session connected. Title-bar Close ended this exact process normally with exit code 0. The frozen package guide describes qualification status at build time; this later startup-only observation does not qualify packaged gameplay.

| Artifact | SHA-256 |
| --- | --- |
| `EmeraldTogether.zip` | `8827a6a2b6f87da7e501a758bdd41cca393a749120665b0de9de3b71747c5c70` |
| `EmeraldTogether.exe` | `3901365753f80abbab3869857a760f4bbceff9396898c99c2e3a190d09f4752a` |
| `package-hashes.json` | `ab5d262fa15a8d6da97ff49eb3a301b9343efd21f691e47851869a3ab3decaee` |
| `package-provenance.json` | `23ec199efc288e1d8bd53adfdf994df55f1e4da21f50332acf5dd2a6424dfa7a` |
| `package-audit.json` | `a9e52a21e2373f7c9118b85b46456dc0b957bce5bb097063f4bca210fa8381d1` |
| Frozen source index | `fe08a9c7110a4b31366e2233dbac24cc3f6d15e80f0f9e4cc57386b1c4a7e026` |
| Current production runtime manifest | `6b32f0bf1aef24fa75cb32413cce1c1585f349a9903cc986d4617e7c6c49212f` |
| Required native ROM, not included | `a46cb8ae950d6fcf15f15fd065d5fa2cd9be4daa6a69e113e9a48651716974a8` |
| Included game manifest | `6d117095cffcb40c4f2f6d60a6a7f869b1fd3497de123c11ae1c1808df17c766` |

Source-launched [Windows 1v1](windows-menu-battle-proof.md), [neutral cancellation](windows-admission-cleanup-proof.md), [timed saving](windows-controls-audit.md) and [four-core recovery](native-battle-resume-proof.md) retain their separate exact inputs and scopes. They do not automatically qualify the frozen executable. Complete own-dump import, clean-machine setup, first-character flow, packaged gameplay/recovery, physical controls and four-PC Wi-Fi/Internet acceptance remain open. No ROM, save, invitation, certificate or player database is distributed in this candidate.

## Copied-world Host button check — gameplay unqualified

The later private `PokemonPrivate/wp7` check used the actual packaged executable with a separate process-local `LOCALAPPDATA` directory and 73 copied files from the closed, passing `wqb1` world. Every original file was hashed before copying and rehashed unchanged afterward; no original player world or accepted package was modified. The copy index SHA-256 is `1fa375a7d041594f9e612eecd00502738386ee517be5b6a915026606dd26a5da`.

Computer use selected the copied world and pressed the real **Host Game** button. The package accepted its copied records, launched its bundled runtime and reached the native title screen. Automated Return/X input did not establish ordinary Continue; the cause is **UNKNOWN**, and no physical keyboard or controller result was supplied. This is a failed gameplay qualification step, not proof that human controls are broken. No friend joined. **Save now** at the title screen correctly refused to checkpoint outside a safe field.

The game was closed through its title bar, the launcher returned to its closed-game status, and the launcher then exited normally with code 0 after 402.949 seconds. The native process exit code was not captured and remains **UNKNOWN**. Both exact test processes were independently absent afterward. Read-only SQLite inspection found unchanged revision-2 canonical heads for both characters, a passing integrity check and released leases. This check does not earn Host/Join gameplay, field saving, first-install or physical-input acceptance. Its complete private record is `wp7/limited-host-evidence.json`, SHA-256 `c83482d969f3322e298172b53deb3205a4fdb6f2fdd06a944eb1e73af867da33`.
