#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"
TARGET_GROUP="$(id -gn "$TARGET_USER")"
EXTENSION_UUID="oxp-fan-profiles@ps1x"
EXTENSION_DIR="$(eval echo "~$TARGET_USER")/.local/share/gnome-shell/extensions/$EXTENSION_UUID"

echo "Installing OXP fan control daemon..."
sudo install -Dm755 "$REPO_DIR/oxp-fan-control.py" /usr/local/bin/oxp-fan-control.py
sudo install -Dm755 "$REPO_DIR/oxp-fan-profile.py" /usr/local/bin/oxp-fan-profile
sudo install -Dm755 "$REPO_DIR/oxp-rgb-hid.py" /usr/local/bin/oxp-rgb-hid
sudo install -Dm755 "$REPO_DIR/oxp-rgb" /usr/local/bin/oxp-rgb
sudo install -Dm755 "$REPO_DIR/oxp-tdp" /usr/local/bin/oxp-tdp
sudo install -Dm755 "$REPO_DIR/oxp-battery-probe.py" /usr/local/bin/oxp-battery-probe
gcc -O2 -Wall -Wextra -o /tmp/oxp-battery-ec-probe "$REPO_DIR/oxp-battery-ec-probe.c"
sudo install -Dm755 /tmp/oxp-battery-ec-probe /usr/local/bin/oxp-battery-ec-probe
sudo chmod 4755 /usr/local/bin/oxp-battery-ec-probe
sudo install -Dm644 "$REPO_DIR/oxp-fan-control.service" /etc/systemd/system/oxp-fan-control.service
sudo install -Dm644 "$REPO_DIR/oxp-sensors.conf" /etc/modules-load.d/oxp-sensors.conf
sudo install -Dm644 "$REPO_DIR/oxp-fan-profile.rules" /etc/polkit-1/rules.d/49-oxp-fan-profile.rules
sudo install -Dm644 "$REPO_DIR/oxp-rgb-hid.rules" /etc/udev/rules.d/99-oxp-rgb-hid.rules

if ! sudo test -f /etc/oxp-fan-control.conf; then
    echo "Installing fresh profile config..."
    sudo install -Dm644 "$REPO_DIR/oxp-fan-control.conf" /etc/oxp-fan-control.conf
elif ! sudo grep -q '^\[profile ' /etc/oxp-fan-control.conf; then
    echo "Migrating legacy /etc/oxp-fan-control.conf to named profiles..."
    sudo /usr/local/bin/oxp-fan-profile migrate-legacy
fi

echo "Installing GNOME extension for $TARGET_USER..."
sudo install -d -m755 -o "$TARGET_USER" -g "$TARGET_GROUP" "$EXTENSION_DIR"
sudo install -m644 -o "$TARGET_USER" -g "$TARGET_GROUP" \
    "$REPO_DIR/gnome-extension/metadata.json" \
    "$EXTENSION_DIR/metadata.json"
sudo install -m644 -o "$TARGET_USER" -g "$TARGET_GROUP" \
    "$REPO_DIR/gnome-extension/extension.js" \
    "$EXTENSION_DIR/extension.js"

sudo systemctl daemon-reload
sudo udevadm control --reload-rules
sudo udevadm trigger --attr-match=idVendor=1a2c --attr-match=idProduct=b001 || true
sudo modprobe oxp-sensors || true
sudo systemctl enable --now oxp-fan-control.service

if command -v gnome-extensions >/dev/null 2>&1; then
    sudo -u "$TARGET_USER" gnome-extensions enable "$EXTENSION_UUID" 2>/dev/null || true
fi

echo
echo "Installed profiles:"
/usr/local/bin/oxp-fan-profile list || true
echo
echo "Current profile:"
/usr/local/bin/oxp-fan-profile current || true
echo
echo "Enable the GNOME extension with:"
echo "  gnome-extensions enable $EXTENSION_UUID"
echo
echo "Use the experimental RGB HID helper with:"
echo "  /usr/local/bin/oxp-rgb-hid mode rainbow"
echo "  /usr/local/bin/oxp-rgb-hid static 255 0 0"
echo
echo "Use the preset RGB wrapper with:"
echo "  /usr/local/bin/oxp-rgb rainbow"
echo "  /usr/local/bin/oxp-rgb green"
echo
echo "Set TDP presets with:"
echo "  sudo /usr/local/bin/oxp-tdp 15"
echo "  sudo /usr/local/bin/oxp-tdp 20"
echo
echo "Probe the battery EC backend with:"
echo "  sudo /usr/local/bin/oxp-battery-probe --json"
echo "  /usr/local/bin/oxp-battery-ec-probe"
echo
echo "Then restart GNOME Shell or log out/in if the menu does not appear immediately."
echo
echo "Local active users get direct access to the RGB HID interface through udev."
echo "Local active wheel users can switch fan profiles from the GNOME menu without an extra password prompt."
