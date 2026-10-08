# Windows launcher and game import

`src/emerald_multiplayer/launcher_gui.py` provides visible Host Game and Join Game tabs over `LauncherSession`. The first window opens existing worlds and enrolled characters. It exposes world/invitation file selection and a local host address, with an explicit Internet setting. It does not expose developer credentials, receipt endpoints, runtime paths or release hashes. Invitations remain private files.

The session worker owns one asyncio loop on a background thread. Tk widgets are updated only on the creating thread through a queue of fixed status codes. Host/Join actions cannot overlap. Cancel startup waits for context cleanup; repeated cancellation does not interrupt that cleanup. Closing the launcher during play asks the player to close the game window, then waits for child/session cleanup. This does not select the pending disconnect or interrupted-battle policy. A connection change is displayed without silently terminating, reconnecting or merging progress.

Application entry points supply `LauncherRelease` pins; arbitrary installation files and invitations cannot select them. Per-user game files live under `%LOCALAPPDATA%/PokemonPrivate/launcher/games/<ROM SHA-256>/game.gba`. No current-directory storage fallback exists. Running the module without a compiled release displays a disabled development preview. First-time enrollment is honestly reported as unavailable in this window until its backend and host approval flow are integrated.

## Reuse review, October 8, 2026

| Component | Review and decision |
| --- | --- |
| Existing project runtime | Reuse `LauncherSession`, `GameInstallation`, `RuntimeBundle`, host invitations and the qualified SDL runtime. GUI code adds no alternate native launch or recovery route. |
| Python/Tk | Installed Windows Python 3.14.4 includes Tcl/Tk 8.6. Reuse stdlib `tkinter.ttk`; no additional GUI library is incorporated. The official [Tkinter documentation](https://docs.python.org/3/library/tkinter.html) describes its event loop and thread constraints. Keep network/recovery work outside Tk handlers. Python has [PSF notices](https://docs.python.org/3/license.html), and Tcl/Tk has [permissive license terms](https://www.tcl-lang.org/software/tcltk/license.html); packaged copies must retain relevant notices. |
| Qt/PySide alternative | The official [PyInstaller deployment guidance](https://doc.qt.io/qtforpython-6/deployment/deployment-pyinstaller.html) establishes a compatible alternative. This two-tab window does not justify adding another GUI runtime alongside the existing SDL game frontend. No Qt source is incorporated. |
| PyInstaller | Official [operation documentation](https://pyinstaller.org/en/stable/operating-mode.html) supports bundling the interpreter and Tk into a Windows application. Use a Windows `onedir`, windowed build before considering one-file mode. Its [license exception](https://pyinstaller.org/en/stable/license.html) permits application bundling subject to included dependency licenses. The executable still requires clean-machine qualification; build success is insufficient. |
| BPS import | Existing project delivery requires an owner's dump plus input/output verification. [byuu's public-domain format specification](https://github.com/Sir-Walrus/Flips/blob/master/bps_spec.md) covers the four commands and CRC footer. The archived Flips project is a potential developer patch generator, not a maintained runtime dependency. [RomPatcher.js](https://github.com/marcrobledo/RomPatcher.js/tree/3183884086825c3a57c72026234debcef1e2240c) supplies an MIT browser/Node implementation, but embedding JavaScript would add another runtime and still require strict release pinning and bounds. A small bounded Python reader is being integrated against the format, without copying either project's implementation. |

Research references are not incorporated dependencies. The pinned engine and SDL runtime audit remain in [Windows runtime](windows-runtime.md) and [customization/reuse](customization-and-reuse.md). These changes do not alter engine saves or multiplayer ABI.

## Verification and remaining acceptance

Twenty focused tests pass on Windows Python 3.14.4 with real Tk widgets and no display skips: eleven GUI/worker cases and nine BPS/import cases. They cover host/join option isolation, one-worker admission, cancellation waiting for cleanup, ordinary game closure, enrollment gating, sanitized error/status messages, passive connection observation, compiled release pins and disabled preview controls. Session behavior uses controlled lifecycle doubles; this is not native gameplay acceptance.

`game_import.py` supports all four BPS commands, signed relative offsets and overlapping target copies. It rejects corrupt CRCs, out-of-bounds reads/writes, truncated/trailing commands, excessive integers, metadata and action counts. ROM/output size is capped at 32 MiB and patch size at 64 MiB. Metadata is inert. `GameImporter` separately checks package-supplied SHA-256 pins for original dump, patch and reconstructed output. It writes a complete private temporary file, flushes it, publishes it without overwriting an existing file, and removes its own temporary file. The original dump is never modified. Fixtures use synthetic bytes, including a 2 MiB overlap run; no real base dump or release patch was available for full-game import acceptance.

## Actual standalone package preview

`scripts/windows-runtime/build_launcher.py` builds a Windows `onedir` package using the exact wheel hashes in `requirements-launcher-build.txt` plus the existing host provisioning pins. It requires explicit trusted ROM/manifest/runtime hashes, verifies all inputs and freezes Python sources before PyInstaller analysis. Only verified runtime manifest entries are copied. Python, Tk and dependency notices accompany the existing native runtime source/relink material. A new private output directory outside the repository is mandatory. No ROM, save, world database, certificate or invitation enters the package. Every resulting file is hashed.

Optional import requires all four developer inputs: `--base`, `--base-sha256`, `--patch` and `--patch-sha256`. The builder must reconstruct the pinned output before enabling the own-dump chooser. Without them it builds a development package with import visibly disabled and an explicit missing-patch notice. No fabricated patch or inferred base hash is substituted. Documented setup/source records and private baseline/runtime build artifacts contain compiled expansion builds, not an owner-supplied original dump.

The first actual package is under private `artifacts/windows-runtime/launcher-package-1/dist/EmeraldTogether`, labelled **Private trade preview**. It has 1,078 files and these real pins:

| Input | SHA-256 |
| --- | --- |
| Qualified trade ROM, not included | `ee71194973092c9ccc395dd7ffeb203447e8854a13404c470b26e8f6235df7c8` |
| Game manifest | `07ffdfd786c453952fde577a41884676498886803db64a390bff7ecbaf77f363` |
| Runtime manifest | `98d6273bd87b277a69d46b1e8195204c3285d148571355a8899df66d83677c2f` |
| Standalone executable | `d1234359925a8a0e35aa891861ae5579102161659297ef01c95dc591bea96662` |

The executable launched with its bundled Python/Tk on the development PC. The Windows computer-use skill verified visible Host/Join layouts, missing-selection guidance and the disabled import/no-patch notice; ordinary window close exited the process. Tk's accessibility tree exposes generic panes here, so screen-reader qualification is still outstanding. This does not establish clean-machine installation, gameplay from the executable, keyboard/audio/gamepad quality or separate-PC networking.

First-time character setup, full-game import with a real release patch, actual keyboard/audio/gamepad checks, clean-machine qualification and LAN/Internet friend acceptance remain separate checks. The initial package identifies the exact qualified Windows trade build rather than advertising later native Multi/Local Reset ROMs that have not been requalified with this Windows runtime.
