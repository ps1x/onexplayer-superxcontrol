# OneXPlayer idle-power tuning

This host policy combines aggressive runtime idle power management with full
AMD CPU boost availability. The three locally identified USB input devices are
left alone so the built-in controller, keyboard, and receiver wake instantly.

The system service applies PCI runtime PM, a 625 MHz CPU floor, the full 5.19
GHz boost ceiling, `balance_power` EPP, and less frequent dirty-page wakeups.
The resume hook reapplies those settings after suspend.

Power Profiles reports `performance` because that firmware profile is required
to expose the full boost ceiling. The service then replaces its CPU floor and
EPP values, so the effective policy is the custom low-idle configuration above.

The NetworkManager drop-in enables Wi-Fi power saving by default. Installation
reloads NetworkManager configuration; reconnect Wi-Fi to apply it to an
already-active connection.

`oxp-cpu-profile` exposes the effective custom mode as `adaptive` and is used
by the OXP Control GNOME extension's CPU Power menu. Selecting Adaptive asks
for administrator authorization and reapplies `oxp-idle-power.service`.

Ultra Saver keeps the 625 MHz floor, caps the CPU at its 2.0 GHz lowest
non-linear (most efficient) frequency, and selects the `power` EPP hint. The
other modes restore the CPU's full hardware frequency range before applying
their profile, so leaving Ultra Saver cannot retain its 2.0 GHz ceiling.
The selected OXP mode is stored in `/var/lib/oxp-power-mode` and restored at boot
and after resume.

The internal unsupported FocalTech `2808:5952` fingerprint reader is disabled
at its dedicated USB port. A device-specific udev rule reapplies the setting
after USB controller re-enumeration; the power service also reapplies it after
resume.
