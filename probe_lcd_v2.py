#!/usr/bin/env python3
"""Probe the LANCOOL 207 display with multiple protocol candidates."""
import sys
import time
import struct
import datetime
import usb.core
import usb.util

VID = 0x1CBE
PID = 0xA065
OUTPUT_PACKET_SIZE = 512

def open_device():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print("ERROR: Device not found")
        sys.exit(1)

    try:
        dev.get_active_configuration()
    except usb.core.USBError:
        dev.set_configuration()

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except Exception:
        pass

    usb.util.claim_interface(dev, 0)
    return dev


def try_write_read(dev, label, data, read_timeout=1000, read_size=512):
    print(f"\n--- {label} ---")
    try:
        written = dev.write(0x01, data, timeout=1000)
        print(f"  Wrote {written} bytes, first 20: {data[:20].hex()}")
    except Exception as e:
        print(f"  Write error: {e}")
        return None

    try:
        resp = bytes(dev.read(0x81, read_size, timeout=read_timeout))
        print(f"  Read {len(resp)} bytes")
        print(f"  First 32: {resp[:32].hex()}")
        # Look for non-zero content
        nz = sum(1 for b in resp if b != 0)
        print(f"  Non-zero bytes: {nz}")
        return resp
    except usb.core.USBError as e:
        print(f"  Read: {e}")
        return None


def try_des_encrypted_protocol(dev):
    """Try the wireless LCD DES-encrypted protocol from uni-wireless-sync."""
    try:
        from Cryptodome.Cipher import DES
        from Cryptodome.Util import Padding
    except ImportError:
        try:
            from Crypto.Cipher import DES
            from Crypto.Util import Padding
        except ImportError:
            print("\n=== Skipping DES protocol (pycryptodome not installed) ===")
            return

    KEY = b"slv3tuzx"

    def encrypt(data):
        padded = Padding.pad(data, 8, style="pkcs7")
        cipher = DES.new(KEY, DES.MODE_CBC, iv=KEY)
        return cipher.encrypt(padded)

    def build_wireless_packet(command, payload=None, single_byte=None):
        header = bytearray(504)
        header[0] = command & 0xFF
        header[2] = 26
        header[3] = 109
        utc_midnight = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        epoch = utc_midnight - datetime.timedelta(days=1)
        delta = datetime.datetime.utcnow() - epoch
        ts = int(delta.total_seconds() * 1000) & 0xFFFFFFFF
        header[4:8] = ts.to_bytes(4, "little", signed=False)
        if payload is not None:
            header[8:12] = len(payload).to_bytes(4, "big", signed=False)
        elif single_byte is not None:
            header[8] = single_byte & 0xFF

        encrypted = encrypt(bytes(header))
        if payload is None:
            packet = bytearray(512)
            packet[:len(encrypted)] = encrypted
            return bytes(packet)
        else:
            buf_size = max(102400, 512 + len(payload))
            packet = bytearray(buf_size)
            packet[:len(encrypted)] = encrypted
            packet[512:512 + len(payload)] = payload
            return bytes(packet)

    # GET_POS_INDEX = 201 (handshake)
    print("\n=== DES Encrypted Wireless Protocol ===")
    pkt = build_wireless_packet(201)
    try_write_read(dev, "Wireless Handshake (GET_POS_INDEX=201)", pkt)

    # GET_VER = 10
    pkt = build_wireless_packet(10)
    try_write_read(dev, "Wireless GET_VER (10)", pkt)

    # BRIGHTNESS = 14, value = 100
    pkt = build_wireless_packet(14, single_byte=100)
    try_write_read(dev, "Wireless BRIGHTNESS (14)", pkt)


def try_raw_jpeg(dev):
    """Try sending a small JPEG directly."""
    # Generate a tiny 10x10 red JPEG
    try:
        from PIL import Image
        import io
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=50)
        jpg_data = buf.getvalue()
        print(f"\n=== Raw JPEG (100x100 red, {len(jpg_data)} bytes) ===")

        # Try sending the JPEG as-is
        try_write_read(dev, "Raw JPEG data", jpg_data, read_timeout=500)

        # Try with HID framing (cmd 0x41 = send_jpg)
        LCD_REPORT_ID = 0x02
        max_chunk = 501
        offset = 0
        packet_number = 0
        print(f"\n--- HID-framed JPEG (cmd=0x41, {len(jpg_data)} bytes) ---")
        while offset < len(jpg_data):
            chunk = jpg_data[offset:offset + max_chunk]
            packet = bytearray(512)
            packet[0] = LCD_REPORT_ID
            packet[1] = 0x41
            packet[2:6] = len(jpg_data).to_bytes(4, "big")
            packet[6:9] = packet_number.to_bytes(3, "big")
            packet[9:11] = len(chunk).to_bytes(2, "big")
            packet[11:11 + len(chunk)] = chunk
            try:
                written = dev.write(0x01, bytes(packet), timeout=1000)
                print(f"  Packet #{packet_number}: wrote {written}")
            except Exception as e:
                print(f"  Packet #{packet_number} write error: {e}")
                break
            offset += max_chunk
            packet_number += 1

        # Try reading response after all packets
        try:
            resp = bytes(dev.read(0x81, 512, timeout=1000))
            print(f"  Response: {len(resp)} bytes, first 20: {resp[:20].hex()}")
        except usb.core.USBError as e:
            print(f"  Response: {e}")

    except ImportError:
        print("\n=== Skipping JPEG test (Pillow not installed) ===")


def try_various_report_ids(dev):
    """Try different report IDs to see if the device expects something other than 0x02."""
    print("\n=== Trying various report IDs and commands ===")
    for report_id in [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x10, 0x20, 0xFF]:
        for cmd in [0x3C, 0x3D, 0x40, 0x41, 0x00, 0x01]:
            packet = bytearray(512)
            packet[0] = report_id
            packet[1] = cmd
            try:
                dev.write(0x01, bytes(packet), timeout=200)
            except Exception:
                continue
            try:
                resp = bytes(dev.read(0x81, 512, timeout=300))
                nz = sum(1 for b in resp if b != 0)
                if nz > 0:
                    print(f"  RESPONSE! report=0x{report_id:02x} cmd=0x{cmd:02x}: {resp[:32].hex()} ({nz} non-zero)")
            except usb.core.USBError:
                pass


def try_control_transfers(dev):
    """Try USB control transfers to see if the device accepts them."""
    print("\n=== USB Control Transfer Probes ===")
    # Standard GET_DESCRIPTOR
    for req_type in [0x80, 0xC0, 0xA1]:  # standard device-in, vendor device-in, hid class interface-in
        for req in [0x06, 0x01, 0x00, 0x3C, 0x3D]:
            for value in [0x0000, 0x0100, 0x0200, 0x0300]:
                try:
                    resp = dev.ctrl_transfer(req_type, req, value, 0, 512, timeout=300)
                    if len(resp) > 0:
                        nz = sum(1 for b in resp if b != 0)
                        if nz > 0:
                            print(f"  Response: type=0x{req_type:02x} req=0x{req:02x} val=0x{value:04x}: {bytes(resp[:32]).hex()} ({nz} nz)")
                except Exception:
                    pass


def try_simple_text(dev):
    """Try sending plain text as the device might accept it directly as a framebuffer."""
    print("\n=== Simple text / raw framebuffer probes ===")
    # Some displays accept raw framebuffer data (RGB565 or RGB888)
    # For a 720x1600 display, one line of RGB565 = 1440 bytes
    # Try writing a single line worth of white pixels
    line_rgb565 = b"\xFF\xFF" * 720  # 1440 bytes of white
    try_write_read(dev, "RGB565 white line (1440 bytes)", line_rgb565, read_timeout=300)


def main():
    print("=== LANCOOL 207 LCD Protocol Probe v2 ===", flush=True)
    dev = open_device()
    print(f"Device claimed: {dev.idVendor:04x}:{dev.idProduct:04x}")

    # 1) Try different report IDs and commands
    try_various_report_ids(dev)

    # 2) Try control transfers
    try_control_transfers(dev)

    # 3) Try DES encrypted wireless protocol
    try_des_encrypted_protocol(dev)

    # 4) Try sending JPEG
    try_raw_jpeg(dev)

    # 5) Try raw framebuffer
    try_simple_text(dev)

    # 6) Drain anything from device
    print("\n=== Final drain attempt ===")
    for i in range(5):
        try:
            resp = bytes(dev.read(0x81, 512, timeout=500))
            print(f"  Drained #{i}: {len(resp)} bytes, first 20: {resp[:20].hex()}")
        except usb.core.USBError:
            print(f"  Drain #{i}: nothing")
            break

    usb.util.release_interface(dev, 0)
    print("\n=== Probe v2 complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
