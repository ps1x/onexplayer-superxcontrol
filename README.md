# onexplayer-superxcontrol

Linux control stack for **OneXPlayer Super X** with:

- in-tree `oxpec` kernel driver integration
- fan control service
- GNOME Shell extension
- RGB control
- TDP control
- display rotation calibration for sensors and camera
- selectable CPU power policies
- battery charge-limit and bypass backend

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

- userspace stack for the in-tree `oxpec` platform driver
- legacy `oxp-sensors` DKMS module for older kernels
- fan-control daemon and profile manager
- GNOME Shell extension
- client helpers for RGB, TDP, and battery controls used by the extension

Local reverse-engineering artifacts, dumps, and experimental tools are kept
under `local/` and are excluded from Git.

## Features

- fan and EC-backed controls through the in-tree `oxpec` driver
- systemd fan-control daemon with switchable profiles
- GNOME Shell top-bar plugin for daily use
- RGB preset and color control helpers
- TDP presets through `ryzenadj`
- configurable Turbo-button commands or two-state power/TDP/LED switching
- Adaptive and Ultra Saver CPU power modes
- detachable-keyboard tablet-mode reporting (legacy module only; the
  tablet-mode patch is still pending upstream)
- accelerometer and camera mounting calibration for automatic rotation
- battery status and charge-limit backend used by the plugin

## Compatibility

This repository is focused on **OneXPlayer Super X**.

Other OneXPlayer, AOKZOE, AYANEO, mini, or older board variants are not the
target of this public tree.

## Upstream Base

This project is based on the original `oxp-sensors` work:

- <https://gitlab.com/Samsagax/oxp-sensors>

## Included Components

- `oxp-sensors.c`: legacy out-of-tree driver for older kernels
- `oxp-fan-control.py`: fan-control daemon
- `oxp-fan-profile.py`: profile CLI used by the daemon and the plugin
- `gnome-extension/`: GNOME Shell top-bar plugin
- `oxp-rgb`, `oxp-rgb-hid.py`: RGB control helpers
- `oxp-tdp`: TDP helper based on `ryzenadj`
- `contrib/power/`: CPU policy, configurable Turbo-button, and idle-power helpers
- `contrib/sensors/`: Super X accelerometer hardware database entry
- `contrib/camera/`: Super X camera mounting quirk for libcamera
- `oxp-battery-probe.py`, `oxp-battery-ec-probe.c`: battery status /
  charge-limit backend for the plugin (see
  [Battery Charge Control](#battery-charge-control))

## Kernel Driver

Fan and EC controls are provided by the in-tree `oxpec` platform driver, which
auto-loads on kernels that carry the Super X DMI match (Fedora kernel 7.2.4
here). It registers the fan hwmon device as `oxp_ec` with `fan1_input`, `pwm1`,
and `pwm1_enable`, where `pwm1_enable` accepts `0` (manual full speed), `1`
(manual PWM), and `2` (EC automatic control). The fan daemon detects both the
in-tree `oxp_ec` and the legacy `oxpec` hwmon names.

### Legacy DKMS module (older kernels)

For kernels without the Super X `oxpec` DMI match, the out-of-tree
`oxp-sensors` module in this repository can still be built and installed:

```shell
make          # build for the running kernel
make dkms     # install through DKMS
```

### Secure Boot

DKMS signs `oxp-sensors`, but Secure Boot will reject it until the DKMS Machine
Owner Key is enrolled. On Fedora, check the key after `make dkms` with:

```shell
sudo mokutil --test-key /var/lib/dkms/mok.pub
```

If it is not enrolled, queue it with `sudo mokutil --import
/var/lib/dkms/mok.pub`, reboot, and choose **Enroll MOK** in the firmware screen.
The one-time password entered at the `mokutil` prompt is required there. The OXP
services limit their retries if the key is missing, so this condition does not
create a boot-time restart storm.

## Install On Linux

Install the client tools, fan-control service, and GNOME extension:

```shell
./install.sh
```

The TDP helpers require `ryzenadj` to be installed and available in `PATH`.
Under Secure Boot, kernel lockdown blocks `ryzenadj`'s direct hardware access,
so the `ryzen_smu` DKMS module must also be built, signed, and loaded
(`ryzen_smu` 0.1.7 currently needs `#include <asm/cpuid/api.h>` added to
`smu.c` to build on recent kernels).
The CPU power menu requires `power-profiles-daemon` and `powerprofilesctl`.

## Turbo Button Configuration

The system service reads `/etc/oxp-turbo-button.conf`. The installer creates
this file only when it does not already exist, so later installs and upgrades
preserve local changes. Open **OXP Control → Settings…** from the top-bar menu
to edit the button behavior graphically. The preferences window validates and
saves the system configuration through polkit, then restarts the Turbo service.

For manual edits, validate and activate the file with:

```shell
sudo /usr/local/bin/oxp-turbo-tdp --check-config
sudo systemctl restart oxp-turbo-tdp.service
```

`behavior = toggle` alternates exactly two user-named states. Each state can
select any standard or custom OXP CPU power profile, set independent STAPM,
fast, and slow TDP limits, select an RGB preset, and run an optional command:

```ini
[general]
behavior = toggle
firmware_action = true
states = battery, boost
initial_state = battery

[state battery]
power_profile = power-saver
tdp = 10, 15, 10
led = blue
command = logger -t oxp-turbo "battery mode"

[state boost]
power_profile = performance
tdp = 45, 45, 45
led = red
command = logger -t oxp-turbo "boost mode"
```

Valid power profiles are `power-saver`, `balanced`, `performance`, `adaptive`,
`ultra`, and `unchanged`. TDP accepts three values from 3 through 80 watts, or
`unchanged`. `led` accepts any preset supported by `/usr/local/bin/oxp-rgb`, or
`unchanged`. The selected state persists in
`/var/lib/oxp-turbo-button-state`. State commands run after the power profile,
TDP, and LED have been applied; they do not run merely because the service was
restarted.

To use the button only as a command launcher:

```ini
[general]
behavior = command
firmware_action = false
command = /usr/local/bin/my-turbo-action
```

Commands run as root through `/bin/sh`. Toggle-state commands receive
`OXP_TURBO_STATE`, `OXP_TURBO_POWER_PROFILE`, `OXP_TURBO_LED`, and the three
`OXP_TURBO_TDP_*` environment variables. Only put root-owned, trusted commands
in this configuration.

When `firmware_action = true`, the factory firmware TDP/Turbo-LED action occurs
first and the configured action then overrides the requested software limits.
Set it to `false` for complete software ownership of the button; in that mode
the factory Turbo LED does not change unless a configured LED preset or command
changes lighting. (With the legacy module, the button still reaches userspace
as a `KEY_PROG1` event either way.)

On kernels with the in-tree `oxpec` driver there is no Turbo button input
device (only the legacy `oxp-sensors` module created one), so `behavior =
toggle` cannot react to button presses. There, `firmware_action` maps to the
driver's `tt_toggle` attribute: `true` gives the EC firmware full ownership of
the button (factory Turbo TDP/LED behavior), while the service still restores
the saved state's power profile, TDP, and LED at boot. Keep the legacy module
installed if you need software toggle states.

## Battery Charge Control

The setuid helper `oxp-battery-ec-probe` backs the plugin's battery menu. On
kernels with the in-tree `oxpec` driver it goes through the standard
power-supply attributes on `BAT0`:

- `charge_control_end_threshold` — charge limit in percent
- `charge_behaviour` — `auto`, `inhibit-charge`, or `inhibit-charge-awake`

This path works under Secure Boot kernel lockdown, where the helper's legacy
direct EC memory access (`/dev/mem`) is denied even to root. The widget's
bypass modes map onto the charge behaviours as `off` → `auto`,
`mode1` → `inhibit-charge`, and `mode2` → `inhibit-charge-awake`. On kernels
without the driver attributes the helper falls back to direct EC access.

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
- CPU power modes
- RGB presets and custom color
- TDP presets
- battery charge-limit / bypass controls when the backend is available
- a settings window for configurable Turbo-button behavior

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
