# Downloadable Windows game and PC hosting

The delivery target is a downloadable Windows game for **four players total: the host and three friends**. The owner's PC hosts through home Wi-Fi and router port forwarding. The package, launcher, and multiplayer server have not been built yet; development still starts with the unchanged Emerald baseline.

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

For the owner/development PC, use [mGBA official downloads](https://mgba.io/downloads.html): **Windows 64-bit installer**, stable **0.10.5**. This is for baseline development and playtesting; friends will receive the integrated runtime in the later game package. Links and current versions were checked October 7, 2026. No registered mGBA installation was found in the Windows uninstall registry; portable installations were not ruled out.

Ubuntu 24.04 under WSL2, Git, build-essential, and Python are already installed. The remaining baseline packages are installed through Ubuntu rather than separate Windows downloads:

```bash
sudo apt update
sudo apt install binutils-arm-none-eabi gcc-arm-none-eabi libnewlib-arm-none-eabi libpng-dev
```

Run these in the Ubuntu terminal. Enter any Ubuntu password locally. These commands have not been executed for this project. [Official pinned build dependencies](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/docs/install/windows/WSL.md)

The engine source will be cloned with Git at the pinned revision. No commercial ROM download is required for the source build.

Compile and verify the untouched baseline before implementing multiplayer, packaging the client, or opening the game service to other clients.
