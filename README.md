# LANCOOL 207 Digital — Linux LCD Driver

Drive the 6" LCD display inside the Lian Li LANCOOL 207 Digital case from Linux.

Protocol reverse-engineered from the Windows L-Connect 3 driver. Based on work
by [deyloop](https://github.com/deyloop/lianli_207_lcd).

## Hardware

- Display: 6" LCD, 720×1472 (portrait), 60 Hz, 500 nits
- USB device: `1cbe:f000` (Luminary Micro / USB-Daemon)
- Protocol: DES-CBC encrypted bulk USB transfers (key/IV: `slv3tuzx`)
- Connection: Type-A USB cable from the case

## Architecture

```
Browser ──► Express (server.js :8008) ──► Python subprocess (display_service.py)
                │                                 │
                ├─ static files (public/)          ├─ display_web_server.py (state + rendering)
                └─ Ollama reverse proxy            └─ display_driver.py (USB protocol)
```

Node.js serves the web UI and proxies Ollama. A persistent Python child process
handles all USB communication and LCD rendering via JSON-over-stdin/stdout IPC.

## Setup

```sh
# Python dependencies
python3 -m venv .venv
.venv/bin/pip install pyusb Pillow pycryptodome

# Node dependencies
npm install

# USB permissions (non-root access)
sudo ./setup-udev.sh
```

On Arch-based distros (CachyOS, etc.):

```sh
sudo pacman -S libusb
```

## Usage

### Web dashboard

```sh
./display-screen.sh
```

Opens the dashboard at `http://localhost:8008`. Type commands in the command bar:

| Command | Effect |
|---------|--------|
| `hello` | Send "Hello World" to the LCD |
| `dictionary` | Cycle random esoteric words (high-contrast) |
| `pictures /path/to/dir` | Slideshow of images from a directory |
| `pictures /path 10` | Slideshow with 10-second interval |
| `ollama` | Start Ollama API request monitor |
| `stop` | Stop the current display mode |
| `restart` | Hard-reset the USB display |
| `reinit` | Force re-initialize the driver |
| `usb_reset` | Kernel-level sysfs USB reset |
| *anything else* | Display that text on the LCD |

### Quick CLI test

```sh
./test-locally.sh hello
./test-locally.sh repeat --text "Hello" --interval 2
./test-locally.sh dictionary --interval 5
```

## Files

| File | Description |
|------|-------------|
| `server.js` | Express server — static files, API routes, Ollama proxy |
| `public/index.html` | Web dashboard (VS Code Dark High Contrast theme) |
| `display_service.py` | Persistent Python subprocess — JSON IPC handler |
| `display_web_server.py` | Display state, LCD renderers (Ollama, dictionary, pictures) |
| `display_driver.py` | Core USB driver (DES-CBC protocol, JPEG/PNG transfer) |
| `display_runner.py` | CLI runner (repeat / dictionary modes) + word list |
| `hello_lcd.py` | Standalone "Hello World" sender |
| `display-screen.sh` | Launch script for the web dashboard |
| `test-locally.sh` | CLI entry point for quick tests |
| `setup-udev.sh` | Install udev rule for non-root USB access |
| `reset-display.sh` | Escalating USB reset (unbind → autoreset → power cycle) |
| `package.json` | Node.js dependencies (express, nodemon) |

## Protocol summary

Commands are sent as 500-byte headers, DES-CBC encrypted, padded to 512 bytes
with trailer `0xA1 0x1A`. Image data follows the header in 4096-byte chunks,
then a StartPlay (`0x79`) command triggers display.

| Command | Byte | Description |
|---------|------|-------------|
| Rotate | `0x0D` | Set display rotation |
| SyncClock | `0x33` | Set RTC time |
| StopClock | `0x34` | Stop RTC |
| JPEG | `0x65` | Send JPEG background (1472×720, rotated −90°) |
| PNG | `0x66` | Send PNG overlay |
| StartPlay | `0x79` | Begin displaying the sent image |

## Troubleshooting

If you see `Resource busy` or `USB device busy`:

```sh
# Unbind the kernel driver (replace 3-2.3 with your device path)
sudo sh -c 'echo 3-2.3 > /sys/bus/usb/drivers/usb/unbind'
```

Or use the web dashboard's **USB Reset** / **Restart** commands, which handle
this automatically.

## License

MIT

---

[built with ai](https://attest.ink/verify/?id=2026-03-19-rlbxos) · Created by [97 115 104](https://github.com/sponsors/97115104) · [Other projects](https://97115104.com/projects/)
