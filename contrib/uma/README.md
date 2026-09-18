# GPU memory allocation

OXP Control's **GPU Memory (UMA)** menu uses amdgpu's
`device/uma/carveout_options` and `device/uma/carveout` interface. Options come
from firmware; sizes and indices are not hardcoded. GPU discovery does not
assume `card0` or `card1`. Unsupported or ambiguous devices cannot be written.

Selecting a size opens a confirmation dialog. Apply writes the selected index
through a root-owned helper, authorized by the existing local, active wheel-user
polkit rule. No automatic reboot. The menu reports active VRAM separately from
the last request in `/run/oxp-vram.json`. This receipt expires on reboot and is
not proof that firmware applied a request. External requests are not tracked.
After reboot, check active VRAM. The reservation reduces ordinary system RAM;
it does not change the shared GTT limit.

```sh
/usr/local/bin/oxp-vram status
pkexec /usr/local/bin/oxp-vram set INDEX
```

Install with `install.sh`, then log out/in to load updated extension code.
Uninstall removes the helper but does not reset firmware allocation.

## Research: Super X, BIOS V1.01

Live inspection on 2026-09-18, kernel `7.2.4-100.fc43.x86_64`: 512 MiB,
1, 2, 4, 8, 16 and 32 GiB advertised; active VRAM 16 GiB (index 5).

The local OneXConsole bundle routes this platform to
`/hardware/setVideoMemory370PlatformPlus`. Its protected native backend contains
`UMAInterface`, `GetUMASize`, `SetUMASize`, and `UmaSizeID` references; method
bodies were not recovered.

ACPI BMOF describes GUID `1F72B0F1-BFEA-4472-9877-6E62937AB616`, method 1 to read
size and method 2 to set it. DSDT `\\_SB.UMAA.WMBB` method 2 and SSDT4 `ATCA`
(AMD ATCS function 0xA) both unpack bytes 2/3 and call
`M232(M23A, packed_value, One)`. The existing amdgpu interface therefore reaches
the same firmware setter. No additional WMI module, raw EC writes, or EFI
patching is needed. Proprietary binaries and dumps stay under ignored `local/`.

Reference: [kernel UMA documentation](https://www.kernel.org/doc/html/latest/gpu/amdgpu/driver-misc.html#uma-carveout).

Tests: `python3 -m unittest discover -s tests -p 'test_vram.py'` covers discovery,
validation, write failures and pending state using temporary fixtures. Live
read-only status is checked separately.

An isolated GNOME Shell 49 headless session loaded the updated extension,
displayed all seven live options and 16 GiB active VRAM, and opened/cancelled the
confirmation dialog without extension errors. The installed helper's status
also passed through polkit. No firmware allocation was changed during that
initial automated validation.

The user subsequently confirmed successful operation after changing the
allocation and rebooting. A live follow-up verified `current_index = 0`,
`active_bytes = 536870912` (512 MiB), and no pending receipt, compared with the
initial 16 GiB. This confirms the complete GNOME-to-firmware path on this
machine. It does not establish that every advertised size or other firmware
versions have been tested.
