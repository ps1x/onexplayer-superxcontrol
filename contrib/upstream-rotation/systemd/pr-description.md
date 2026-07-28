## Summary

Add the accelerometer mounting matrix for the One-Netbook OneXPlayer Super X.

The device contains a BMI260 accelerometer exposed using the ACPI `BMI0160`
identifier. Firmware does not provide a mount matrix, and the sensor X/Y axes
do not match the built-in display axes. Without this entry,
`iio-sensor-proxy` reports incorrect screen orientations.

The entry uses the exact system vendor and product DMI fields:

```text
svnONE-NETBOOK:pnONEXPLAYERSUPERX
```

The tested matrix is:

```text
0, -1, 0; 1, 0, 0; 0, 0, 1
```

## Validation

- Passed `test/hwdb-test.sh` using systemd-hwdb 258.
- Passed strict hwdb compilation.
- Queried the compiled database with the complete machine modalias and
  received the expected `ACCEL_MOUNT_MATRIX`.
- Tested with iio-sensor-proxy 3.8 and Mutter 49.7.
- Verified native landscape and both portrait orientations on the hardware.

## AI assistance disclosure

Development of this patch used assistance from ChatGPT 5.6 sol.
