#!/usr/bin/env python3
"""
Lian Li Uni Hub SL V2 RGB Controller for Linux.

Sets fan LED colors via direct HID writes to /dev/hidraw*.

Usage:
  # All fans static red
  python3 unihub_rgb.py --color FF0000

  # All fans static blue at 50% brightness
  python3 unihub_rgb.py --color 0000FF --brightness 50

  # Channel 0 only, green
  python3 unihub_rgb.py --color 00FF00 --channel 0

  # Rainbow mode
  python3 unihub_rgb.py --mode rainbow

  # Breathing purple
  python3 unihub_rgb.py --color 8000FF --mode breathing

The SL V2 controller declares a 352-byte HID output report and has no
Interrupt OUT endpoint, so all writes go via USB SET_REPORT control
transfers. The device firmware validates the transfer size and silently
discards anything shorter than the declared report. This script pads all
packets to 353 bytes (1 byte Report ID + 352 bytes data), matching the
HID descriptor exactly.
"""

import argparse
import os
import sys
import time

# Protocol constants (from OpenRGB LianLiUniHubSLV2Controller)
REPORT_ID = 0xE0
PACKET_SIZE = 353  # 1 (report ID) + 352 (output report data)
LEDS_PER_FAN = 16
MAX_FANS_PER_CHANNEL = 6
NUM_CHANNELS = 4

# Default device path
DEFAULT_HIDRAW = "/dev/hidraw7"

# Mode IDs
MODES = {
    "static":       0x01,
    "breathing":    0x02,
    "rainbow_morph": 0x04,
    "rainbow":      0x05,
    "staggered":    0x18,
    "tide":         0x1A,
    "runway":       0x1C,
    "mixing":       0x1E,
    "stack":        0x20,
    "neon":         0x22,
    "color_cycle":  0x23,
    "meteor":       0x24,
    "groove":       0x27,
    "render":       0x28,
    "tunnel":       0x29,
}

# Speed: 0=very slow ... 4=very fast
SPEED_VALUES = [0x02, 0x01, 0x00, 0xFF, 0xFE]

# Brightness: 0=off, 25, 50, 75, 100
BRIGHTNESS_VALUES = {
    0:   0x08,
    25:  0x03,
    50:  0x02,
    75:  0x01,
    100: 0x00,
}

# Direction
DIR_LTR = 0x00
DIR_RTL = 0x01


def build_packet(data: bytes) -> bytes:
    """Build a 353-byte packet: report ID + data, zero-padded."""
    pkt = bytearray(PACKET_SIZE)
    pkt[0] = REPORT_ID
    end = min(len(data), PACKET_SIZE - 1)
    pkt[1:1 + end] = data[:end]
    return bytes(pkt)


def send_start_action(fd: int, channel: int, num_fans: int):
    """Step 1: Initialize channel for color update."""
    data = bytes([0x10, 0x60, (channel << 4) | num_fans])
    os.write(fd, build_packet(data))
    time.sleep(0.005)


def send_color_data(fd: int, channel: int, led_colors: list[tuple[int, int, int]]):
    """Step 2: Send RGB data. Colors are (R, G, B) tuples; wire order is R-B-G."""
    data = bytearray(1 + len(led_colors) * 3)
    data[0] = 0x30 + channel
    for i, (r, g, b) in enumerate(led_colors):
        offset = 1 + i * 3
        data[offset + 0] = r
        data[offset + 1] = b  # wire order: R, B, G
        data[offset + 2] = g
    os.write(fd, build_packet(bytes(data)))
    time.sleep(0.005)


def send_commit_action(fd: int, channel: int, mode: int, speed: int,
                       direction: int, brightness: int):
    """Step 3: Commit the mode and settings."""
    data = bytes([0x10 + channel, mode, speed, direction, brightness])
    os.write(fd, build_packet(data))
    time.sleep(0.005)


def brightness_limit(r: int, g: int, b: int) -> float:
    """Apply brightness limiter when R+G+B > 460 (matches stock firmware)."""
    total = r + g + b
    if total > 460:
        return 460.0 / total
    return 1.0


def set_static_color(fd: int, channels: list[int], num_fans: int,
                     r: int, g: int, b: int, brightness_pct: int):
    """Set all specified channels to a static color."""
    bright_code = BRIGHTNESS_VALUES.get(brightness_pct, 0x00)
    scale = brightness_limit(r, g, b)
    sr = int(r * scale)
    sg = int(g * scale)
    sb = int(b * scale)

    num_leds = num_fans * LEDS_PER_FAN
    colors = [(sr, sg, sb)] * num_leds

    for ch in channels:
        send_start_action(fd, ch, num_fans)
        send_color_data(fd, ch, colors)
        send_commit_action(fd, ch, MODES["static"], SPEED_VALUES[2],
                           DIR_LTR, bright_code)


def set_mode(fd: int, channels: list[int], num_fans: int, mode_name: str,
             r: int, g: int, b: int, brightness_pct: int, speed: int,
             direction: int):
    """Set channels to a specific mode with optional color."""
    mode_id = MODES[mode_name]
    bright_code = BRIGHTNESS_VALUES.get(brightness_pct, 0x00)
    speed_code = SPEED_VALUES[min(speed, 4)]

    scale = brightness_limit(r, g, b)
    sr = int(r * scale)
    sg = int(g * scale)
    sb = int(b * scale)

    num_leds = num_fans * LEDS_PER_FAN
    colors = [(sr, sg, sb)] * num_leds

    for ch in channels:
        send_start_action(fd, ch, num_fans)
        send_color_data(fd, ch, colors)
        send_commit_action(fd, ch, mode_id, speed_code, direction, bright_code)


def find_hidraw_device() -> str:
    """Auto-detect the Lian Li Uni Hub hidraw device."""
    for entry in sorted(os.listdir("/sys/class/hidraw/")):
        uevent_path = f"/sys/class/hidraw/{entry}/device/uevent"
        try:
            with open(uevent_path) as f:
                content = f.read()
            if "00000CF2" in content and ("0000A105" in content or "0000A103" in content):
                path = f"/dev/{entry}"
                if os.access(path, os.R_OK | os.W_OK):
                    return path
        except (OSError, IOError):
            continue
    return DEFAULT_HIDRAW


def parse_color(s: str) -> tuple[int, int, int]:
    """Parse hex color like 'FF0000' or '#FF0000'."""
    s = s.lstrip("#")
    if len(s) != 6:
        raise argparse.ArgumentTypeError(f"Color must be 6 hex digits: '{s}'")
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid hex color: '{s}'")


def main():
    parser = argparse.ArgumentParser(
        description="Control Lian Li Uni Hub SL V2 fan LEDs on Linux",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  %(prog)s --color FF0000          # All fans red\n"
               "  %(prog)s --color 00FF00 -c 0     # Channel 0 green\n"
               "  %(prog)s --mode rainbow           # Rainbow effect\n"
               "  %(prog)s --color 0000FF -b 50    # Blue at 50%%\n"
               "  %(prog)s --off                    # Turn off all LEDs\n")

    parser.add_argument("--color", "-C", type=parse_color, default=(255, 0, 0),
                        metavar="RRGGBB",
                        help="Hex color (default: FF0000)")
    parser.add_argument("--mode", "-m", choices=sorted(MODES.keys()),
                        default="static",
                        help="LED mode (default: static)")
    parser.add_argument("--channel", "-c", type=int, choices=[0, 1, 2, 3],
                        default=None,
                        help="Single channel (default: all channels)")
    parser.add_argument("--fans", "-f", type=int, default=MAX_FANS_PER_CHANNEL,
                        choices=range(1, MAX_FANS_PER_CHANNEL + 1),
                        help=f"Fans per channel (default: {MAX_FANS_PER_CHANNEL})")
    parser.add_argument("--brightness", "-b", type=int, default=100,
                        choices=[0, 25, 50, 75, 100],
                        help="Brightness %% (default: 100)")
    parser.add_argument("--speed", "-s", type=int, default=2,
                        choices=range(5), metavar="0-4",
                        help="Effect speed 0=slow 4=fast (default: 2)")
    parser.add_argument("--direction", "-d", type=int, default=0,
                        choices=[0, 1],
                        help="Direction 0=LTR 1=RTL (default: 0)")
    parser.add_argument("--device", default=None,
                        help=f"HID device path (default: auto-detect)")
    parser.add_argument("--off", action="store_true",
                        help="Turn off all LEDs")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress output")

    args = parser.parse_args()

    if args.off:
        args.color = (0, 0, 0)
        args.brightness = 0

    r, g, b = args.color
    device = args.device or find_hidraw_device()
    channels = [args.channel] if args.channel is not None else list(range(NUM_CHANNELS))

    if not args.quiet:
        print(f"Device:     {device}")
        print(f"Color:      #{r:02X}{g:02X}{b:02X}")
        print(f"Mode:       {args.mode}")
        print(f"Channels:   {channels}")
        print(f"Fans/ch:    {args.fans}")
        print(f"Brightness: {args.brightness}%")

    try:
        fd = os.open(device, os.O_RDWR)
    except OSError as e:
        print(f"Error: Cannot open {device}: {e}", file=sys.stderr)
        print("Check udev rules and device permissions.", file=sys.stderr)
        sys.exit(1)

    try:
        set_mode(fd, channels, args.fans, args.mode, r, g, b,
                 args.brightness, args.speed, args.direction)
    except OSError as e:
        print(f"Error writing to device: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        os.close(fd)

    if not args.quiet:
        print("Done.")


if __name__ == "__main__":
    main()
