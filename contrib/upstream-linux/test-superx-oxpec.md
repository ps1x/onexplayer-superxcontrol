# Local test of patched `oxpec` on Fedora

This is a practical way to test the Super X mainline patch on the current
Fedora kernel without rebuilding the whole kernel.

## 1. Build the external test module

```bash
cd /path/to/oxp-platform-dkms
chmod +x contrib/upstream-linux/build-test-oxpec-superx.sh
./contrib/upstream-linux/build-test-oxpec-superx.sh
```

Expected output module:

```text
contrib/upstream-linux/test-module/oxpec_superx.ko
```

## 2. Unload the out-of-tree DKMS module

Your current fan hwmon node is provided by `oxp_sensors`, not by the in-tree
`oxpec`, so unload it first:

```bash
sudo systemctl stop oxp-fan-control.service
sudo modprobe -r oxp_sensors
```

## 3. Load the patched test module

```bash
sudo insmod "$PWD/contrib/upstream-linux/test-module/oxpec_superx.ko"
```

## 4. Verify that the new module created the hwmon node

```bash
lsmod | grep oxpec_superx
grep . /sys/class/hwmon/hwmon*/name
```

You want to see an `oxpec` hwmon device appear again.

## 5. Verify fan RPM

```bash
grep . /sys/class/hwmon/hwmon*/fan1_input 2>/dev/null
sensors
```

## 6. Verify manual fan control

Find the `hwmon` path with `name=oxpec`, then:

```bash
OXP_HWMON="$(for d in /sys/class/hwmon/hwmon*; do [[ \"$(cat \"$d/name\" 2>/dev/null)\" == \"oxpec\" ]] && echo \"$d\" && break; done)"
echo "$OXP_HWMON"

echo 1 | sudo tee "$OXP_HWMON/pwm1_enable"
echo 120 | sudo tee "$OXP_HWMON/pwm1"
cat "$OXP_HWMON/fan1_input"
echo 0 | sudo tee "$OXP_HWMON/pwm1_enable"
```

## 7. Verify turbo toggle, if exposed

```bash
test -e "$OXP_HWMON/tt_toggle" && cat "$OXP_HWMON/tt_toggle"
```

## 8. Cleanup

```bash
sudo rmmod oxpec_superx
sudo modprobe oxp_sensors
sudo systemctl start oxp-fan-control.service
```

If all of the above works, the upstream patch is much safer to send.
