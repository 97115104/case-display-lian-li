#!/usr/bin/env python3
"""Quick USB probe for the Lian Li LANCOOL 207 Digital display."""

import usb.core

VID = 0x1CBE
PID = 0xA065

print('looking for', hex(VID), hex(PID))
dev = usb.core.find(idVendor=VID, idProduct=PID)
print('device:', dev)
if not dev:
    raise SystemExit(1)

try:
    cfg = dev.get_active_configuration()
    print('active config:', cfg)
except Exception as e:
    print('config error:', type(e).__name__, e)

try:
    # Attempt to detach kernel driver if present
    if hasattr(dev, 'is_kernel_driver_active') and dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)
        print('detached kernel driver (0)')
except Exception as e:
    print('detach error:', type(e).__name__, e)

print('done')
