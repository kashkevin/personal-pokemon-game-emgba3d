# Local PC hosting and downloads

Hosting target: the project owner's Windows PC, connected through home Wi-Fi. Initial development still begins with the unchanged Emerald baseline; the custom game server and emulator bridge have not been implemented.

For local players on the same home network, the future server can use a LAN connection. For friends in other homes, use Windows Tailscale to provide a private connection. Run the server natively on Windows alongside Tailscale; retain WSL2 for compiling Emerald. The host PC must remain awake, connected, and running the server during shared sessions.

## Downloads

1. [mGBA official downloads](https://mgba.io/downloads.html): choose **Windows 64-bit installer**, stable version **0.10.5**. This is the emulator for the initial clients.
2. [Tailscale for Windows](https://tailscale.com/download/windows): needed for remote testing. Each player uses their own account. The current [free Personal plan](https://tailscale.com/pricing) supports six users, enough for this project. Router port forwarding is normally unnecessary; restrictive networks can use a relay. [Firewall guidance](https://tailscale.com/docs/reference/faq/firewall-ports)

Links and current versions were checked October 7, 2026. No registered mGBA or Tailscale installation was found in the Windows uninstall registry; portable installations were not ruled out.

## Existing development tools

Ubuntu 24.04 under WSL2, Git, build-essential, and Python are already installed. The remaining baseline packages are installed through Ubuntu rather than separate Windows downloads:

```bash
sudo apt update
sudo apt install binutils-arm-none-eabi gcc-arm-none-eabi libnewlib-arm-none-eabi libpng-dev
```

Run these in the Ubuntu terminal. Enter any Ubuntu password locally. These commands have not been executed for this project. [Official pinned build dependencies](https://github.com/rh-hideout/pokeemerald-expansion/blob/expansion/1.17.1/docs/install/windows/WSL.md)

The engine source will be cloned with Git at the pinned revision. No commercial ROM download is required for the source build, and no paid hosting is needed for the initial setup. Friends need the client tools later, not the development compiler packages.

After setup, compile and verify the untouched baseline before implementing the server or opening the game service to other clients.
