# Private native Windows runtime

The pinned SDL frontend now runs natively on Windows through the multiplayer launcher. This is a development proof for an already enrolled character. Host/Join UI, new-character setup, keyboard/gamepad qualification, audible playback, and clean-machine packaging still have separate acceptance gates.

## Build and retained source

The recipe in `scripts/windows-runtime/` builds mGBA commit `26b7884bc25a5933960f3cdcd98bac1ae14d42e2` with x64 POSIX MinGW 13.2.0, SDL2 2.32.10, Lua 5.4.9 and libepoxy 1.5.10. It changes only the SDL main/event integration and adds `native/windows-runtime/sdl-multiplayer.c/.h`; the emulator core and ROM are unchanged. Official archives must match the hashes recorded in the recipe and dependency ledger. WSL builds use two workers at `nice 15`.

The adapter accepts one explicit save/script pair, initializes Winsock for the Lua bridge, disables rewind/state/reset paths, and attaches the script context once. Duplicate options, incomplete pairs, cheats, state files and patches are refused. The qualified compiler requires `BUILD_LTO=OFF`: the retained initial LTO build compiled but failed Lua bound-object calls in Windows. Disabling LTO fixed them without a core patch. The recipe retains upstream's required Windows libepoxy support and SDL's relocatable CMake configuration.

The collector includes dependency notices, covered-source archives, the frontend patch, build instructions, and static objects/import libraries for relinking. The documented MinGW relink command passed. These materials include the LGPL blip_buf source/notice and relink inputs; see `docs/dependency-ledger.md`. The recipe records repeatable inputs and checks, without claiming byte-identical output across compiler versions, paths or timestamps. Private ROMs, saves, credentials, databases and compiled artifacts remain outside Git.

## Frozen qualified bundle

The private 29-file `bundle-qualified` has `runtime.json` SHA-256:

`98d6273bd87b277a69d46b1e8195204c3285d148571355a8899df66d83677c2f`

| Component | SHA-256 |
| --- | --- |
| `mgba-sdl.exe` | `99db72f9857ee322feaa166268b779e5f7a6523b0bd31b4bb2ad2576226553aa` |
| `SDL2.dll` | `53e8fa7e9ed43c30bd650c39396f0d9d2067d2fff0b926c9433b75202592e4aa` |
| `libwinpthread-1.dll` | `fc9f14551f6609dd51801daec2c194579d35345551ef84fe465cbdb3339c2a6f` |
| `mgba.lua` | `28a078b71e045cfed1a01a4915922a20448cd3140c16590763823b64109748ce` |

`RuntimeBundle.verify()` passes under the launcher Python at `C:\Python314\python.exe`. Its physically resolved Windows directory is `C:\Users\kashh\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\PokemonPrivate\artifacts\windows-runtime\bundle-qualified`. The bridge copy is frozen with this pin; later repository bridge changes require a new collection and qualification. `--version` exits successfully. Upstream `--help` prints usage but exits 1 because of its existing missing-ROM argument check.

## Actual Windows evidence

The simple `smoke-4` proof rendered the native overworld, connected the real Lua/Winsock bridge to a loopback companion/server, loaded a copied save through ordinary Continue, and closed normally. Its private `evidence.json` SHA-256 is `1002cc87aa410c8c2115cb460c4ef9f3062457c4c88e42b17c77747f229f4394`.

`player-runtime-smoke-2` additionally used the actual `PlayerRuntime.open()` lifecycle with a copied, closed consistent world backup. Closed recovery installed the current canonical revision 4 before launch. The save lease blocked a second owner throughout the native core lifetime and was released after normal window closure. Ordinary Continue loaded two Pokémon with IDs 1 and 33; read-only party Box CRC `74e4d2ea` matched the canonical image. The copied database retained its head and passed integrity checks, and every source file hash remained unchanged. The child exited 0 and the evidence records `passed: true`.

That proof used a separate bundle with ordinary timed Start/A inputs and a read-only party diagnostic appended to the Lua template. Its pin is `e361b433439aa49b83a279b20daa125c2afd0a4630525178206c2331c63c01b5`; the normal qualified bundle remained untouched. These scripted GBA inputs establish Continue, not Windows keyboard acceptance. No RAM/save/state injection was used.

The final proof evidence is privately retained at `windows-runtime/player-runtime-smoke-2/evidence.json` under the same artifact root, SHA-256 `c934fa4f4684202bb550f4bcc7edd150921ec3aa160db541cc626b1ddeb1975e`. Earlier failed build/smoke attempts and their logs remain retained. All proof cores, companions, servers and database handles were closed. The tested ROM was the frozen trade foundation, SHA-256 `ee71194973092c9ccc395dd7ffeb203447e8854a13404c470b26e8f6235df7c8`.

This proof covers native startup, canonical restore, actual Continue, bridge presence, save-lock lifetime and normal close. It does not qualify the final interface, native trade effects, audio, gamepads, Internet operation or autosave scheduling. An optional larger read window is being evaluated separately; this frozen bundle retains the previously qualified bridge.
