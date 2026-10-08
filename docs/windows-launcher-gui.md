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

Nine focused tests pass on Windows Python 3.14.4 with real Tk widgets and no display skips. They cover host/join option isolation, one-worker admission, cancellation waiting for cleanup, ordinary game closure, enrollment gating, sanitized error/status messages, passive connection observation, compiled release pins and disabled preview controls. Session behavior uses controlled lifecycle doubles; this is not native gameplay acceptance.

Executable packaging, import fixtures, visible UI review, first-time character setup, actual keyboard/audio/gamepad checks, clean-machine qualification and LAN/Internet friend acceptance are separate checks. The initial package must identify the exact qualified Windows trade build rather than advertise later native Multi/Local Reset ROMs that have not been requalified with this Windows runtime.
