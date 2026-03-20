# lianli-unihub-rgb

Control Lian Li Uni Hub SL V2 fan LEDs on Linux. Single Python script, zero dependencies, no sudo required.

Works around an [OpenRGB bug on Linux](https://gitlab.com/CalcProgrammer1/OpenRGB/-/issues/5539) where the SL V2 is detected but color commands are silently ignored. An [upstream fix](https://gitlab.com/CalcProgrammer1/OpenRGB/-/merge_requests/3229) has been submitted.

## Quick Start

```bash
python3 unihub_rgb.py --color FF0000           # all fans red
python3 unihub_rgb.py --color 0000FF -b 50     # blue at 50% brightness
python3 unihub_rgb.py --mode rainbow            # rainbow effect
python3 unihub_rgb.py --off                     # turn off LEDs
```

## Requirements

- Python 3.8+
- Linux with udev rules granting HID device access (OpenRGB's rules work)
- No pip packages — uses raw `/dev/hidraw` file I/O

## Why OpenRGB Doesn't Work

OpenRGB sends 65-byte HID packets for two of three protocol steps (`SendStartAction`, `SendCommitAction`), but the SL V2's HID report descriptor declares a **352-byte output report**.

The device has no Interrupt OUT endpoint, so all writes go via USB `SET_REPORT` control transfers. The device firmware validates `wLength` against the descriptor and **silently discards undersized packets**. No error is returned.

The fix is simple: pad all packets to 353 bytes (1 byte Report ID + 352 bytes data).

A [two-line upstream OpenRGB patch](#openrgb-patch) is included below.

## Usage

```
python3 unihub_rgb.py [OPTIONS]

Options:
  --color, -C RRGGBB    Hex color (default: FF0000)
  --mode, -m MODE        static, breathing, rainbow, rainbow_morph, meteor,
                         neon, color_cycle, tide, runway, mixing, stack,
                         groove, render, tunnel, staggered
  --channel, -c {0-3}    Single channel (default: all)
  --fans, -f {1-6}       Fans per channel (default: 6)
  --brightness, -b       0, 25, 50, 75, or 100 (default: 100)
  --speed, -s {0-4}      Effect speed, 0=slow 4=fast (default: 2)
  --direction, -d {0,1}  0=LTR, 1=RTL (default: 0)
  --device PATH          HID device (default: auto-detect)
  --off                  Turn off all LEDs
  --quiet, -q            Suppress output
```

## Auto-Start at Login

Create a systemd user service:

```ini
# ~/.config/systemd/user/fan-rgb.service
[Unit]
Description=Set fan LEDs

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 2
ExecStart=/path/to/unihub_rgb.py --color FF0000 --brightness 75 -q
RemainAfterExit=yes

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable fan-rgb.service
```

## Confirmed Hardware

| Field | Value |
|-------|-------|
| Product | Lian Li Uni Hub SL V2 |
| USB VID:PID | `0CF2:A105` |
| Firmware | v0.7 |
| LEDs per fan | 16 |
| Max fans per channel | 6 |
| Channels | 4 |

Should also work with PID `0xA103`.

## OpenRGB Patch

The upstream fix is two lines in `LianLiUniHubSLV2Controller.cpp` — change the buffer size from 65 to 353 in `SendStartAction` and `SendCommitAction`:

```diff
 void LianLiUniHubSLV2Controller::SendStartAction(...)
 {
-    unsigned char usb_buf[65];
+    unsigned char usb_buf[353];
     ...
 }

 void LianLiUniHubSLV2Controller::SendCommitAction(...)
 {
-    unsigned char usb_buf[65];
+    unsigned char usb_buf[353];
     ...
 }
```

## License

MIT
