# LANCOOL 207 Digital -- Linux LCD Driver

Drive the 6" LCD display inside the Lian Li LANCOOL 207 Digital case from Linux.

Protocol reverse-engineered from the Windows L-Connect 3 driver. Based on work
by [deyloop](https://github.com/deyloop/lianli_207_lcd).

## Hardware

- Display: 6" LCD, 720x1472 (portrait), 60Hz, 500 nits
- USB device: `1cbe:f000` (Luminary Micro / USB-Daemon)
- Protocol: DES-CBC encrypted bulk USB transfers
- Connection: Type-A USB cable from the case

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install pyusb Pillow pycryptodome
sudo ./setup-udev.sh          # allow non-root USB access
```

On Arch-based distros (CachyOS, etc.) you also need:

```sh
sudo pacman -S libusb
```

## Usage

### Quick test

```sh
./test-locally.sh hello
```

Sends a "Hello World" image to the LCD.

### Dashboard (web UI)

```sh
./display-screen.sh
```

Opens a web dashboard at `http://localhost:8008` where you can:

- Send custom text to the LCD
- Run the repeat, dictionary, or hello modes
- Monitor Ollama API requests in real-time on the LCD

### Other commands

```sh
./test-locally.sh repeat --text "Hello" --interval 2
./test-locally.sh dictionary --interval 5
```

## Files

| File | Description |
|------|-------------|
| display_driver.py | Core USB driver (DES-CBC protocol) |
| display_web_server.py | Web dashboard server with Ollama monitor |
| display_runner.py | CLI runner (repeat / dictionary modes) |
| hello_lcd.py | Standalone "Hello World" sender |
| display-screen.sh | Launch the web dashboard |
| test-locally.sh | CLI entry point for all commands |
| setup-udev.sh | Install udev rule for non-root access |

## Protocol summary

Commands are sent as 500-byte headers, DES-CBC encrypted (key/IV: `slv3tuzx`),
padded to 512 bytes with trailer `0xA1 0x1A`. Image data is appended after the
header and sent in 4096-byte chunks, followed by a StartPlay (0x79) command.

| Command | Byte | Description |
|---------|------|-------------|
| Rotate | 0x0D | Set display rotation |
| SyncClock | 0x33 | Set RTC time |
| StopClock | 0x34 | Stop RTC |
| JPEG | 0x65 | Send JPEG background (1472x720, rotated -90) |
| PNG | 0x66 | Send PNG overlay |
| StartPlay | 0x79 | Begin displaying the sent image |

## License

MIT

- This script is *not* yet a full working display driver; it is a framework to locate the device and send commands once the protocol is known.

---

If you run the script and share any additional device output (especially `lsusb -v` for the device), I can help reverse-engineer the packet format so the display actually shows text.

## Granting access to the display on Linux

The device is a vendor-specific USB device, so standard non-root users cannot open it by default. You can either run the display scripts with `sudo` or add a udev rule.

To add a udev rule (recommended):

```sh
sudo ./setup-udev.sh
```

Then reconnect the display (unplug/replug the USB cable) or reboot.

After that, run:

```sh
./test-locally.sh repeat --text "Hello" --interval 2
```

If you see an error like `Resource busy` or `USB device busy`, it usually means the kernel / another process has the device claimed. You can unbind it (as root) like this:

```sh
# Replace the device string with the one matching your system (lsusb shows Bus/Device)
sudo sh -c 'echo 3-2.3 > /sys/bus/usb/drivers/usb/unbind'
```

Then retry running the demo (or run it as root to avoid permission issues):

```sh
sudo ./test-locally.sh repeat --text "Hello" --interval 2
```

If it still doesn't work, share the output of the probe command again:

```sh
./lianli_display_probe.py scan
./lianli_display_probe.py info --vid 0x1cbe --pid 0xf000
```
