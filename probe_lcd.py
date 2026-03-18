#!/usr/bin/env python3
"""Probe the LANCOOL 207 display using the TL LCD protocol."""
import sys
import time
import usb.core
import usb.util

VID = 0x1CBE
PID = 0xA065
LCD_REPORT_ID = 0x02
OUTPUT_PACKET_SIZE = 512
MAX_CHUNK = 501


def build_packet(command, data=b""):
    """Build a TL LCD protocol packet (or list of packets for chunked data)."""
    if len(data) == 0:
        packet = bytearray(OUTPUT_PACKET_SIZE)
        packet[0] = LCD_REPORT_ID
        packet[1] = command
        return [bytes(packet)]

    packets = []
    packet_number = 0
    offset = 0
    while offset < len(data):
        chunk = data[offset:offset + MAX_CHUNK]
        packet = bytearray(OUTPUT_PACKET_SIZE)
        packet[0] = LCD_REPORT_ID
        packet[1] = command
        packet[2:6] = len(data).to_bytes(4, "big")
        packet[6:9] = packet_number.to_bytes(3, "big")
        packet[9:11] = len(chunk).to_bytes(2, "big")
        packet[11:11 + len(chunk)] = chunk
        packets.append(bytes(packet))
        offset += MAX_CHUNK
        packet_number += 1
    return packets


def main():
    print("=== LANCOOL 207 LCD Protocol Probe ===", flush=True)

    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print("ERROR: Device not found", flush=True)
        return 1
    print(f"Found: {dev.idVendor:04x}:{dev.idProduct:04x} bus={dev.bus} addr={dev.address}", flush=True)

    # Get active configuration (avoid set_configuration EBUSY)
    try:
        cfg = dev.get_active_configuration()
        print(f"Active config: {cfg.bConfigurationValue}", flush=True)
    except usb.core.USBError:
        print("No active config, setting...", flush=True)
        dev.set_configuration()
        cfg = dev.get_active_configuration()

    # Detach kernel driver
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
            print("Detached kernel driver", flush=True)
        else:
            print("No kernel driver active", flush=True)
    except Exception as e:
        print(f"Kernel driver: {e}", flush=True)

    # Claim interface with retry
    claimed = False
    for attempt in range(10):
        try:
            usb.util.claim_interface(dev, 0)
            claimed = True
            print(f"Claimed interface (attempt {attempt+1})", flush=True)
            break
        except usb.core.USBError as e:
            print(f"Claim attempt {attempt+1}: {e}", flush=True)
            time.sleep(0.1 * (attempt + 1))

    if not claimed:
        print("FAILED to claim interface - trying direct write anyway", flush=True)

    # === Protocol probes ===

    def try_write_read(label, packets, read_count=1, read_timeout=1000):
        print(f"\n--- {label} ---", flush=True)
        for i, pkt in enumerate(packets):
            try:
                written = dev.write(0x01, pkt, timeout=1000)
                print(f"  Write #{i}: {written} bytes OK", flush=True)
            except Exception as e:
                print(f"  Write #{i} error: {e}", flush=True)
                return

        for i in range(read_count):
            try:
                resp = dev.read(0x81, OUTPUT_PACKET_SIZE, timeout=read_timeout)
                resp_bytes = bytes(resp)
                print(f"  Read #{i}: {len(resp_bytes)} bytes", flush=True)
                print(f"  Hex[0:32]: {resp_bytes[:32].hex()}", flush=True)
                if resp_bytes[0] == LCD_REPORT_ID:
                    cmd = resp_bytes[1]
                    length = (resp_bytes[9] << 8) | resp_bytes[10]
                    payload = resp_bytes[11:11 + length]
                    text = payload.split(b"\x00", 1)[0].decode("ascii", errors="ignore")
                    print(f"  -> cmd=0x{cmd:02x}, payload_len={length}, text='{text}'", flush=True)
                else:
                    print(f"  -> raw first byte: 0x{resp_bytes[0]:02x}", flush=True)
            except usb.core.USBError as e:
                print(f"  Read #{i} timeout/error: {e}", flush=True)
                break

    # 1) Handshake (0x3C)
    try_write_read("Handshake (0x3C)", build_packet(0x3C))

    # 2) Firmware version (0x3D) - expects 2 responses
    try_write_read("Firmware Version (0x3D)", build_packet(0x3D), read_count=2)

    # 3) LCD Test - white screen
    control = bytearray(11)
    control[0] = 6    # LCD_TEST mode
    control[4] = 100  # brightness
    control[5] = 30   # fps
    control[6] = 0    # rotation
    control[7] = 1    # enable_test
    control[8] = 255  # R
    control[9] = 255  # G
    control[10] = 255 # B
    try_write_read("LCD Test White (0x40)", build_packet(0x40, bytes(control)))

    # 4) LCD_SETTING mode with brightness
    control2 = bytearray(11)
    control2[0] = 5    # LCD_SETTING
    control2[4] = 100  # brightness
    control2[6] = 0    # rotation
    try_write_read("LCD Setting (0x40 mode=5)", build_packet(0x40, bytes(control2)))

    # 5) Try SHOW_JPG mode
    control3 = bytearray(11)
    control3[0] = 1    # SHOW_JPG
    control3[4] = 100  # brightness
    control3[6] = 0    # rotation
    try_write_read("Show JPG Mode (0x40 mode=1)", build_packet(0x40, bytes(control3)))

    # 6) Try raw bytes - maybe the device needs simpler framing
    print("\n--- Raw byte probes ---", flush=True)
    for label, raw in [
        ("0x00 zero", bytes(512)),
        ("0xA5 header", b"\xA5\x5A" + bytes(510)),
        ("0x01 cmd", b"\x01" + bytes(511)),
    ]:
        try:
            written = dev.write(0x01, raw, timeout=500)
            print(f"  {label}: wrote {written}", flush=True)
            try:
                resp = dev.read(0x81, 512, timeout=500)
                print(f"    response: {bytes(resp[:16]).hex()}", flush=True)
            except usb.core.USBError:
                print(f"    no response", flush=True)
        except Exception as e:
            print(f"  {label}: write error {e}", flush=True)

    # Cleanup
    try:
        usb.util.release_interface(dev, 0)
    except Exception:
        pass
    print("\n=== Probe complete ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
