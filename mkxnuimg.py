#!/usr/bin/env python3
"""
Pack a device-specific UEFI build and an optional XNUP payload into an Android boot image
for `fastboot boot`.

  kernel = gzip(BootShim + UEFI FD + ["XNUP" container]) + DTB

The boot shim copies the FD to its base and the payload to PAYLOAD_BASE.

The UEFI pieces are taken from a local Mu-Silicium tree. Redwood retains its upstream prebuilt
fallback; fogos requires the user's own local UEFI build and device tree.

usage: mkxnuimg.py --device fogos --mu-path ../Mu-Silicium [-p payload.bin] [-o out.img]
"""
import argparse, gzip, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAYLOAD_BASE, PAYLOAD_MAX = 0xF0000000, 0x04000000
DEVICES = {
    'redwood': {'fd_base': 0x9FD00000, 'fd_size': 0x200000, 'pkg': 'redwoodPkg', 'dtb': 'redwood.dtb',
                'prebuilt': os.path.join(HERE, 'devices', 'poco-x5-pro', 'prebuilt')},
    'fogos': {'fd_base': 0x9FC00000, 'fd_size': 0x300000, 'pkg': 'fogosPkg', 'dtb': 'fogos.dtb',
              'prebuilt': None},
}

ap = argparse.ArgumentParser()
ap.add_argument('--device', choices=sorted(DEVICES), default='redwood')
ap.add_argument('--mu-path', default=os.environ.get('MU', os.path.join(HERE, 'Mu-Silicium')),
                help='path to the local Mu-Silicium checkout/build (or set MU)')
ap.add_argument('-p', '--payload')
ap.add_argument('-o', '--output')
ap.add_argument('--mode', default='RELEASE')
args = ap.parse_args()

device = DEVICES[args.device]
MU = os.path.abspath(args.mu_path)
PREBUILT = device['prebuilt']
FD_BASE, FD_SIZE = device['fd_base'], device['fd_size']
if args.output is None:
    args.output = os.path.join(HERE, f'xnu-{args.device}.img')

fd_path = os.path.join(MU, f"Build/{device['pkg']}/{args.mode}_CLANGPDB/FV/SILICIUM_UEFI.fd")
if os.path.isfile(fd_path):
    shim_dir = os.path.join(MU, 'BootShim')
    for f in ('BootShim.elf', 'BootShim.bin'):
        try: os.unlink(os.path.join(shim_dir, f))
        except FileNotFoundError: pass
    subprocess.check_call(['make', 'REQUIRES_KERNEL_HEADER=1', f'FD_BASE={FD_BASE:#x}', f'FD_SIZE={FD_SIZE:#x}',
                           f'CFLAGS=--target=aarch64-linux-gnu -DPAYLOAD_BASE={PAYLOAD_BASE:#x}'],
                          cwd=shim_dir, stdout=subprocess.DEVNULL)
    parts = {'shim': os.path.join(shim_dir, 'BootShim.bin'), 'fd': fd_path,
             'dtb': os.path.join(MU, 'Resources/DTBs', device['dtb']), 'ramdisk': os.path.join(MU, 'Resources/ramdisk'),
             'mkbootimg': os.path.join(MU, 'Resources/Scripts/mkbootimg.py')}
else:
    if PREBUILT is None:
        sys.exit(f"no {args.device} UEFI build at {fd_path}; build Mu-Silicium for {args.device} first")
    parts = {'shim': os.path.join(PREBUILT, 'BootShim.bin'), 'fd': os.path.join(PREBUILT, 'SILICIUM_UEFI.fd'),
             'dtb': os.path.join(PREBUILT, 'device-tree.dtb'), 'ramdisk': os.path.join(PREBUILT, 'ramdisk'),
             'mkbootimg': os.path.join(PREBUILT, 'mkbootimg.py')}
shim = open(parts['shim'], 'rb').read()
fd = open(parts['fd'], 'rb').read()
assert len(fd) == FD_SIZE, hex(len(fd))

blob = shim + fd
if args.payload:
    data = open(args.payload, 'rb').read()
    # the payload file is a complete "XNUP" container (see xnuloader/mkpayload.py)
    assert data[:4] == b'XNUP' and len(data) <= PAYLOAD_MAX - 0x1000, 'bad or oversized payload'
    blob += data
    blob += b'\0' * (-len(blob) % 16)
    print(f'payload: {len(data)} bytes, bytesum={sum(data) & 0xffffffff:08x}')

dtb = open(parts['dtb'], 'rb').read()
kernel = args.output + '.kernel~'
open(kernel, 'wb').write(gzip.compress(blob, 6) + dtb)
try:
    subprocess.check_call([sys.executable, parts['mkbootimg'], '--kernel', kernel, '--ramdisk', parts['ramdisk'],
                           '--header_version', '1', '-o', args.output])
finally:
    os.unlink(kernel)
print(f'{args.output}: {os.path.getsize(args.output)} bytes (shim {len(shim)}, uncompressed {len(blob)})')
