<p align="center">
  <img src="mergbw-linux/assets/mergbw.png" width="128" alt="MeRGBW icon">
</p>

<h1 align="center">MeRGBW for Linux</h1>

<p align="center">
  Control MeRGBW LED strips and bulbs over Bluetooth LE.
</p>
# MeRGBW for Linux

Functional rewrite of **MeRGBW 1.6.3 Android** (`com.mergbw.android`,
APKPure XAPK, 29 MB) to control MeRGBW LED strips/bulbs over
**Bluetooth LE** from Linux.

> On "decrypting": the `.xapk` **is not encrypted**. It is a ZIP holding the
> base APK plus language/density/ABI splits. Just `unzip` it.
> Verified contents:
> - `manifest.json`: package `com.mergbw.android`, versionCode 35, minSdk 23.
> - Base `com.mergbw.android.apk` (~28 MB): 5 dex files, Kotlin, no proprietary
>   `.so` (only `libdatastore_shared_counter.so` in the arm64 split).
> - Bundled Telink firmware: `TG201 / TG609 / TG610` (`assets/firmware/*.hex16`).

## What this Linux version does

- BLE scan with probable-MeRGBW highlighting.
- BLE connection (service `FFF0`, write `FFF3` with response, notify `FFF4`;
  the firmware answers with a `0x56` header).
- Power on/off, status, clock sync, firmware query, color (HSV for type 1 /
  RGB for the rest), brightness, scenes + speed, music + sensitivity,
  LED count, white, timer, fragmented part-color (MTU).
- Dark Qt6 GUI in OpenRGB style (`mergbw-gui`): devices, status, color with
  presets and custom colors, scenes, music, white, timer.
  It remembers the last device and can pin one as default (★).
- No cloud, no ads, no login: only local BLE control, which is all you
  need on Linux.

## Requirements

- Linux with Bluetooth (BlueZ), Python 3.10+.
- `pip install -e .` (installs `bleak` + `PySide6`).

```bash
cd ~/Projects/mergbw-linux
python3 -m venv .venv && .venv/bin/pip install -e .
```

The `mergbw.desktop` launcher and icon are already installed to
`~/.local/share/applications` and `~/.local/share/icons`.

You must be allowed to use the adapter: usually belonging to the
`bluetooth` group or having used `bluetoothctl` once is enough. If `scan`
reports permission denied, try once with `sudo` to rule out permissions.

## CLI usage

```bash
mergbw scan
mergbw --mac AA:BB:CC:DD:EE:FF --type 1 status
mergbw --mac AA:BB:CC:DD:EE:FF --type 1 on
mergbw --mac AA:BB:CC:DD:EE:FF --type 6 color --rgb FF8000
mergbw --mac AA:BB:CC:DD:EE:FF --type 1 color --rgb FF8000
mergbw --mac AA:BB:CC:DD:EE:FF brightness --value 80
mergbw --mac AA:BB:CC:DD:EE:FF scene --index 4 --speed 50
mergbw --mac AA:BB:CC:DD:EE:FF music --mode 2 --sens 80
mergbw --mac AA:BB:CC:DD:EE:FF lednum --value 60
mergbw --mac AA:BB:CC:DD:EE:FF white --value 70
mergbw --mac AA:BB:CC:DD:EE:FF timer --open 07:30 --close 23:00 --days lun,mar,mie,jue,vie
mergbw --mac AA:BB:CC:DD:EE:FF sync-time
mergbw --mac AA:BB:CC:DD:EE:FF firmware
```

`--type` is the app's deviceType (1 letters/addressable, 2 RGB line,
3 star, 4 handle, 5 sunset, 6 bulb, 7/8 ceiling). It changes the
color/brightness encoding. See `PROTOCOL.md`.

GUI (also from the app launcher as **MeRGBW**):

```bash
.venv/bin/mergbw-gui
```

The GUI remembers the last device in `~/.config/mergbw/device.json`, and
**☆ Mark as default** pins it so it is prefilled (and its status auto-read)
on launch — you can still scan and switch devices freely.

## Tests

```bash
python -m pytest tests/ -q
```

## Layout

- `mergbw/protocol.py` — byte-level protocol (port of `CommandUtils`,
  `CommandList`, `ColorUtils`, `ViewDataUtils.analyseSyncData`).
- `mergbw/device.py` — bleak scan/connection (port of `RGBDeviceManager`,
  `AddDeviceViewModel.scanDevice`).
- `mergbw/cli.py` — CLI.
- `mergbw/gui.py` — Qt6 GUI (PySide6) in OpenRGB style.
- `PROTOCOL.md` — full forensic analysis of the APK (Spanish).

## Honest limitations

- No firmware OTA, no login/cloud (`47.251.33.234:7788`), no full DIY/subcolor
  persistence: the protocol is implemented (`cmd_subcolor_61`), but the GUI
  exposes the essentials.
- The bind (CMD 14) with `android_id` is not required on most types
  (2/3/5 mark themselves bound); `cmd_check_bind_*` is included anyway.
- If your device does not show up as `*`, connect by MAC anyway: scan
  filtering on Linux is best-effort because BlueZ does not expose the raw
  scanRecord.
