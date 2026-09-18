#!/usr/bin/python3 -I
"""Expose the amdgpu UMA carveout interface to OXP Control."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile

DRM = Path('/sys/class/drm')
STATE = Path('/run/oxp-vram.json')
LOCK = Path('/run/oxp-vram.lock')


def parse_options(text):
    options = []
    for line in text.splitlines():
        match = re.fullmatch(r'(\d+):\s*[^()]*\((\d+) (MB|GB)\)', line.strip())
        if not match:
            raise ValueError('Unrecognized UMA option from the kernel')
        index, size, unit = match.groups()
        options.append({'index': int(index),
                        'bytes': int(size) * (1024 ** (2 if unit == 'MB' else 3)),
                        'label': f'{size} {"MiB" if unit == "MB" else "GiB"}'})
    if not options or len({o['index'] for o in options}) != len(options):
        raise ValueError('Invalid UMA option list')
    return options


def discover(drm=DRM):
    devices = []
    for card in drm.glob('card[0-9]*'):
        if not re.fullmatch(r'card\d+', card.name):
            continue
        device = card / 'device'
        if ((device / 'driver').resolve().name == 'amdgpu'
                and (device / 'uma/carveout_options').is_file()
                and (device / 'uma/carveout').is_file()):
            devices.append(device.resolve())
    devices = sorted(set(devices))
    if len(devices) != 1:
        raise ValueError('UMA control unavailable: expected one supported AMD GPU')
    return devices[0]


def status(device, state_path=STATE):
    options = parse_options((device / 'uma/carveout_options').read_text())
    current = int((device / 'uma/carveout').read_text().strip())
    active = int((device / 'mem_info_vram_total').read_text().strip())
    requested = None
    try:
        saved = json.loads(state_path.read_text())
        if saved.get('device') == str(device):
            requested = next((o for o in options
                              if o['index'] == saved.get('index')
                              and o['bytes'] == saved.get('bytes')), None)
    except (FileNotFoundError, ValueError, TypeError, AttributeError):
        pass
    return {'supported': True, 'device': str(device), 'options': options,
            'current_index': current, 'active_bytes': active,
            'requested': requested,
            'reboot_required': requested is not None and requested['bytes'] != active}


def set_size(device, index, state_path=STATE):
    before = status(device, state_path)
    choice = next((o for o in before['options'] if o['index'] == index), None)
    if choice is None:
        raise ValueError('Size index is not advertised by this GPU')
    # Prepare the receipt before the hardware write; publish it only on success.
    # /run is cleared on reboot: a receipt is a request, not proof BIOS applied it.
    fd, name = tempfile.mkstemp(prefix='.oxp-vram-', dir=state_path.parent)
    try:
        with os.fdopen(fd, 'w') as receipt:
            json.dump({'device': str(device), **choice}, receipt)
            receipt.flush()
            os.fchmod(receipt.fileno(), 0o644)
        with (device / 'uma/carveout').open('w') as control:
            control.write(f'{index}\n')
        os.replace(name, state_path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return status(device, state_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    setter = commands.add_parser('set')
    setter.add_argument('index', type=int)
    args = parser.parse_args()
    try:
        device = discover()
        if args.command == 'set':
            if os.geteuid() != 0:
                raise PermissionError('Use pkexec to change UMA allocation')
            with LOCK.open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                result = set_size(device, args.index)
        else:
            result = status(device)
        print(json.dumps(result))
    except (OSError, ValueError) as error:
        print(json.dumps({'supported': False, 'error': str(error)}))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
