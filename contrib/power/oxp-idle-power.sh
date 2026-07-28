#!/bin/sh
# Apply the selected OXP CPU policy and common idle-power savings.
set -eu

state_file=/var/lib/oxp-power-mode
mode=${1:-}
if [ -n "$mode" ]; then
	case "$mode" in
		power-saver|balanced|performance|adaptive|ultra) ;;
		*) echo "Unknown OXP power mode: $mode" >&2; exit 2 ;;
	esac
	printf '%s\n' "$mode" > "$state_file"
elif [ -r "$state_file" ]; then
	mode=$(cat "$state_file")
else
	mode=adaptive
fi

# Performance is the only firmware profile that exposes the full CPPC boost
# range needed by Adaptive. Ultra starts from the standard saver profile.
case "$mode" in
	adaptive) powerprofilesctl set performance ;;
	ultra) powerprofilesctl set power-saver ;;
	*) powerprofilesctl set "$mode" ;;
esac

# The unsupported internal FocalTech fingerprint reader otherwise remains on
# the USB bus. Disable its dedicated port; udev applies the same rule at boot.
for fingerprint in /sys/bus/usb/devices/*; do
	[ -r "$fingerprint/idVendor" ] || continue
	[ "$(cat "$fingerprint/idVendor")" = 2808 ] || continue
	[ "$(cat "$fingerprint/idProduct")" = 5952 ] || continue
	/usr/local/sbin/oxp-disable-fingerprint "${fingerprint#/sys}"
done

# Let every PCI driver runtime-suspend its device when the driver considers it
# idle. Active devices remain awake and resume automatically on demand.
for control in /sys/bus/pci/devices/*/power/control; do
	[ -w "$control" ] && printf '%s\n' auto > "$control"
done

for policy in /sys/devices/system/cpu/cpufreq/policy*; do
	[ -d "$policy" ] || continue

	# power-profiles-daemon does not reset cpufreq limits previously written by
	# Ultra Saver. Restore the hardware range on every profile transition before
	# applying any custom ceiling, otherwise Performance can remain stuck at
	# 2 GHz (or lower) indefinitely.
	if [ -r "$policy/amd_pstate_max_freq" ]; then
		cat "$policy/amd_pstate_max_freq" > "$policy/scaling_max_freq"
	else
		cat "$policy/cpuinfo_max_freq" > "$policy/scaling_max_freq"
	fi
	cat "$policy/cpuinfo_min_freq" > "$policy/scaling_min_freq"

	if [ "$mode" = adaptive ] || [ "$mode" = ultra ]; then
		# amd-pstate's powersave governor is dynamic, not a fixed low frequency.
		printf '%s\n' powersave > "$policy/scaling_governor"
		if [ "$mode" = adaptive ]; then
			printf '%s\n' balance_power > "$policy/energy_performance_preference"
		else
			# This is the efficient ceiling; lower clocks can increase total
			# energy by making work take disproportionately longer.
			cat "$policy/amd_pstate_lowest_nonlinear_freq" > "$policy/scaling_max_freq"
			printf '%s\n' power > "$policy/energy_performance_preference"
		fi
	fi
done

# Batch periodic dirty-page writeback to reduce otherwise needless wakeups.
sysctl -q -w vm.dirty_writeback_centisecs=1500
