# onexplayer-superxcontrol

Linux control stack for **OneXPlayer Super X** with:

- DKMS kernel module
- fan control service
- GNOME Shell extension
- RGB control
- TDP control
- battery charge-limit backend

If you are searching for **OneXPlayer Super X Linux fan control**, **OneXPlayer
Super X RGB control**, **OneXPlayer Super X TDP control**, or a **GNOME
extension for OneXPlayer Super X**, this repository is intended for that use
case.

## WARNING

**THIS SOFTWARE CAN CHANGE LOW-LEVEL HARDWARE BEHAVIOR. IT MAY CAUSE SYSTEM
INSTABILITY, OVERHEATING, DATA LOSS, OR PERMANENT HARDWARE DAMAGE.**

**YOU USE THIS PROJECT ENTIRELY AT YOUR OWN RISK. I ACCEPT NO RESPONSIBILITY
OR LIABILITY FOR ANY DAMAGE, FAILURE, OR LOSS CAUSED BY ITS USE, MISUSE, OR
MODIFICATION.**

**ANYTHING ABOVE 75W TDP IS STRICTLY AT YOUR OWN RISK AND SHOULD ONLY BE USED
WITH ADEQUATE THERMAL HEADROOM AND, IN PRACTICE, A WATER COOLER.**

Public repository scope:

- DKMS kernel module for the `oxp-sensors` platform driver
- fan-control daemon and profile manager
- GNOME Shell extension
- client helpers for RGB, TDP, and battery controls used by the extension

Local reverse-engineering artifacts, dumps, and experimental tools are kept
under `local/` and are excluded from Git.

## Features

- `oxp-sensors` DKMS module for fan and EC-backed controls
- systemd fan-control daemon with switchable profiles
- GNOME Shell top-bar plugin for daily use
- RGB preset and color control helpers
- TDP presets through `ryzenadj`
- battery status and charge-limit backend used by the plugin

## Compatibility

This repository is focused on **OneXPlayer Super X**.

Other OneXPlayer, AOKZOE, AYANEO, mini, or older board variants are not the
target of this public tree.

## Upstream Base

This project is based on the original `oxp-sensors` work:

- <https://gitlab.com/Samsagax/oxp-sensors>

I could not find a working way to contact Joaquín Ignacio Aramendía
(`@Samsagax`) directly. If the upstream author wants this repository or any
part of it to be removed from public distribution, they are welcome to open an
issue in this repository.

## Included Components

- `oxp-sensors.c`: kernel driver
- `oxp-fan-control.py`: fan-control daemon
- `oxp-fan-profile.py`: profile CLI used by the daemon and the plugin
- `gnome-extension/`: GNOME Shell top-bar plugin
- `oxp-rgb`, `oxp-rgb-hid.py`: RGB control helpers
- `oxp-tdp`: TDP helper based on `ryzenadj`
- `oxp-battery-probe.py`, `oxp-battery-ec-probe.c`: battery status / charge-limit backend for the plugin

## Build DKMS Module

To build the kernel module for the running kernel:

```shell
make
```

To install through DKMS:

```shell
make dkms
```

## Install On Linux

Install the client tools, fan-control service, and GNOME extension:

```shell
./install.sh
```

## Uninstall

Remove the installed userland components with:

```shell
./uninstall.sh
```

Full removal including `/etc/oxp-fan-control.conf` and user plugin state:

```shell
./uninstall.sh --purge
```

## Fan Control Profiles

The fan daemon uses `/etc/oxp-fan-control.conf` and supports named profiles.
Stock profiles are:

- `silent`
- `balanced`
- `watercool`
- `aggressive`

Useful commands:

```shell
/usr/local/bin/oxp-fan-profile list
/usr/local/bin/oxp-fan-profile current
sudo /usr/local/bin/oxp-fan-profile set balanced
```

## GNOME Shell Extension

The GNOME Shell extension adds a top-bar menu for:

- fan profile switching
- RGB presets and custom color
- TDP presets
- battery charge-limit / bypass controls when the backend is available

Enable it after install:

```shell
gnome-extensions enable oxp-fan-profiles@ps1x
```

## RGB And TDP Commands

Examples:

```shell
/usr/local/bin/oxp-rgb rainbow
/usr/local/bin/oxp-rgb red
sudo /usr/local/bin/oxp-tdp 15
sudo /usr/local/bin/oxp-tdp 20
```

## License

This repository is distributed under **GPL-2.0-or-later**. See `LICENSE`.
