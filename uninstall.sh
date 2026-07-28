#!/usr/bin/env bash
set -euo pipefail

TARGET_USER="${SUDO_USER:-$USER}"
TARGET_HOME="$(eval echo "~$TARGET_USER")"
TARGET_GROUP="$(id -gn "$TARGET_USER")"
EXTENSION_UUID="oxp-fan-profiles@ps1x"
EXTENSION_DIR="$TARGET_HOME/.local/share/gnome-shell/extensions/$EXTENSION_UUID"
PURGE=0

if [[ "${1:-}" == "--purge" ]]; then
    PURGE=1
elif [[ $# -gt 0 ]]; then
    echo "Usage: $0 [--purge]" >&2
    exit 1
fi

echo "Stopping OXP fan service..."
sudo systemctl disable --now oxp-fan-control.service 2>/dev/null || true
sudo systemctl disable --now oxp-turbo-tdp.service 2>/dev/null || true
sudo systemctl disable --now oxp-idle-power.service 2>/dev/null || true
if [[ -x /usr/local/bin/oxp-cpu-profile ]]; then
    sudo /usr/local/bin/oxp-cpu-profile set balanced 2>/dev/null || true
fi

echo "Removing installed binaries..."
for path in \
    /usr/local/bin/oxp-fan-control.py \
    /usr/local/bin/oxp-fan-profile \
    /usr/local/bin/oxp-rgb-hid \
    /usr/local/bin/oxp-rgb \
    /usr/local/bin/oxp-tdp \
    /usr/local/bin/oxp-turbo-tdp \
    /usr/local/bin/oxp-cpu-profile \
    /usr/local/sbin/oxp-idle-power \
    /usr/local/sbin/oxp-disable-fingerprint \
    /usr/local/bin/oxp-battery-probe \
    /usr/local/bin/oxp-battery-ec-probe
do
    sudo rm -f "$path"
done

echo "Removing service and rules..."
for path in \
    /etc/systemd/system/oxp-fan-control.service \
    /etc/systemd/system/oxp-turbo-tdp.service \
    /etc/systemd/system/oxp-idle-power.service \
    /usr/lib/systemd/system-sleep/oxp-idle-power \
    /etc/modules-load.d/oxp-sensors.conf \
    /etc/polkit-1/rules.d/49-oxp-fan-profile.rules \
    /etc/udev/rules.d/99-oxp-rgb-hid.rules \
    /etc/udev/rules.d/80-oxp-disable-fingerprint.rules \
    /etc/NetworkManager/conf.d/10-wifi-powersave.conf \
    /etc/udev/hwdb.d/61-sensor-onexplayer-super-x.hwdb
do
    sudo rm -f "$path"
done

echo "Removing GNOME extension..."
if [[ -d "$EXTENSION_DIR" ]]; then
    sudo rm -rf "$EXTENSION_DIR"
fi

if [[ $PURGE -eq 1 ]]; then
    echo "Purging local configuration..."
    sudo rm -f /etc/oxp-fan-control.conf
    sudo rm -f "$TARGET_HOME/.config/oxp-control.json"
    sudo rm -f /var/lib/oxp-power-mode
fi

sudo systemctl daemon-reload
sudo systemd-hwdb update
if command -v nmcli >/dev/null 2>&1; then
    sudo nmcli general reload conf || true
fi
sudo udevadm control --reload-rules || true
sudo udevadm trigger --subsystem-match=iio --action=change || true
sudo udevadm trigger --attr-match=idVendor=1a2c --attr-match=idProduct=b001 || true
sudo systemctl try-restart iio-sensor-proxy.service
sudo modprobe -r oxp-sensors 2>/dev/null || true

if command -v gnome-extensions >/dev/null 2>&1; then
    sudo -u "$TARGET_USER" gnome-extensions disable "$EXTENSION_UUID" 2>/dev/null || true
fi

echo
echo "Uninstall complete."
if [[ $PURGE -eq 0 ]]; then
    echo "User config and /etc/oxp-fan-control.conf were kept."
else
    echo "User config and /etc/oxp-fan-control.conf were removed."
fi
