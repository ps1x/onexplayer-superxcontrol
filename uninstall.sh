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

echo "Removing installed binaries..."
for path in \
    /usr/local/bin/oxp-fan-control.py \
    /usr/local/bin/oxp-fan-profile \
    /usr/local/bin/oxp-rgb-hid \
    /usr/local/bin/oxp-rgb \
    /usr/local/bin/oxp-tdp \
    /usr/local/bin/oxp-battery-probe \
    /usr/local/bin/oxp-battery-ec-probe
do
    sudo rm -f "$path"
done

echo "Removing service and rules..."
for path in \
    /etc/systemd/system/oxp-fan-control.service \
    /etc/modules-load.d/oxp-sensors.conf \
    /etc/polkit-1/rules.d/49-oxp-fan-profile.rules \
    /etc/udev/rules.d/99-oxp-rgb-hid.rules
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
fi

sudo systemctl daemon-reload
sudo udevadm control --reload-rules || true
sudo udevadm trigger --attr-match=idVendor=1a2c --attr-match=idProduct=b001 || true
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
