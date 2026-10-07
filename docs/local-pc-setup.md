# Downloadable Windows game and PC hosting

The delivery target is a downloadable Windows game for **four players total: the host and three friends**. The owner's PC hosts through home Wi-Fi and router port forwarding. The player package and launcher remain future work. Actual two-ROM multiplayer movement and local save/reload now pass on localhost through the server, companions, and bridge. Windows GUI/LAN and Internet hosting still need testing. The unchanged engine also builds reproducibly and passed ordinary gameplay/save checks. See [the baseline build record](baseline-build.md) and [Phase 2 evidence](phase2-presence.md).

## Player experience

1. Download and extract the game ZIP, then open `Game.exe`. An installer can come later.
2. Import each player's own Emerald dump once through the launcher, then create or select a player profile.
3. The owner selects **Host Game**. The application starts the server and owner's game automatically.
4. Friends select **Join Game** and enter the host's address/invitation and room credentials.
5. Each player runs their own game, with independent exploration and progression. The server coordinates shared multiplayer and durable checkpoints.

Bundle the runtime and emulator integration so friends need no Python installation, WSL, Git, compiler, required VPN, or manually loaded Lua scripts. The proposed Python companion/server can be packaged as a self-contained Windows application. Stock mGBA 0.10.5 needs a packaging integration change to automatically load the multiplayer bridge; this is not an existing plug-and-play feature. [PyInstaller packaging documentation](https://pyinstaller.org/en/stable/operating-mode.html), [pinned mGBA command-line options](https://github.com/mgba-emu/mgba/blob/0.10.5/src/platform/qt/ConfigController.cpp)

Keep profiles, saves, settings, and the host database in local application data rather than the downloaded folder or OneDrive. Replacing the game ZIP must not erase player data. Distribute our application/runtime and modification patch, with the proposed one-time game import; the original instruction against distributing commercial ROMs remains in force. Review included code and asset permissions before packaging, since a patch can contain inserted data.

## Hosting setup

Once the server exists and local tests pass, configure the owner's router and PC:

- Reserve a stable LAN address for the host PC.
- Forward the game's chosen TCP port to that address and permit that port in Windows Firewall. The port is not assigned yet.
- Use encrypted, authenticated game sessions and a private room invitation.
- Give friends the public address/invitation. They normally do not need to forward their own ports.
- Keep the host PC awake, connected, and running the hosting session while friends play.

Wi-Fi can carry the connection; Ethernet is an optional way to reduce local wireless interruptions. No paid server is needed. The router model and ISP determine the exact forwarding steps. Carrier-grade NAT at the ISP can prevent a normal router forward from reaching the PC; check reachability from another Internet connection when setting up the actual host. [Router forwarding guidance and public-WAN requirement](https://www.tp-link.com/us/support/faq/1379/)

Tailscale is an optional fallback if direct hosting is unavailable. It is not required for the selected delivery. No router or firewall changes have been made.

## Development downloads

For the owner/development PC, [mGBA official downloads](https://mgba.io/downloads.html) provides stable **0.10.5**. The installed copy was verified October 7, 2026, at `C:\Program Files\mGBA\mGBA.exe`, file version `0.10.5.0`. It is the Windows 32-bit build, which is usable for the baseline on this PC; a replacement download is unnecessary. Friends will receive the integrated runtime in the later game package.

Ubuntu 24.04 under WSL2, Git, build-essential, and Python were already installed. The missing baseline packages have now been installed through Ubuntu, using the official upstream dependency list:

```bash
sudo apt update
sudo apt install binutils-arm-none-eabi gcc-arm-none-eabi libnewlib-arm-none-eabi libpng-dev
```

These are the equivalent setup commands for another development machine; they need not be repeated here. Installation also brought in newlib development files and the matching libpng runtime dependency. [Official pinned build dependencies](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/docs/install/windows/WSL.md)

The engine source is cloned at the pinned revision on WSL's Linux filesystem, `/home/kevin/src/pokemon/engine`, branch `codex/baseline`. No commercial ROM download was required for the source build.

The baseline gameplay and independent save/reload checks passed and `BASELINE_BUILD` is preserved. Multiplayer ROM integration is now underway in a separate worktree. Packaging and opening the game service to friends follow the real networking proof.
