# Ain't Ink Smart

Control BLE e-ink displays (Electronic Shelf Labels) from Home Assistant or standalone scripts. Tested on EasyTag displays.

## Compatibility

| Size  | Resolution | Colors | Part Number | Tested |
| :---- | :--------- | :----- | :---------- | :----- |
| 7.5"  | 800x480    | BWR    | AES0750     | Yes    |

## Home Assistant Integration

A custom component that lets you send images to e-ink displays directly from Home Assistant via Bluetooth.

### Installation via HACS

1. Ensure [HACS](https://hacs.xyz/) is installed.
2. Go to **HACS > Integrations > Custom Repositories**.
3. Add this repository URL with category **Integration**.
4. Search for **"Ain't Ink Smart E-Ink Display"** and install.
5. Restart Home Assistant.

### Manual Installation

1. Copy `custom_components/aintinksmart/` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

### Features

- **Camera entity** showing the last sent image.
- **Status sensor** (idle / connecting / sending / success / error).
- **Source entity select** — pick any `camera` or `image` entity to mirror.
- **Update mode** — black & white or black, white & red.
- **Auto-update switch** — automatically push when the source changes.
- **Force update button** — manually trigger a send.
- **Packet delay control** — tune BLE packet timing.
- **Services** — `aintinksmart.send_image` and `aintinksmart.force_update` for automations.

For full documentation see [doc/home_assistant_integration.md](doc/home_assistant_integration.md).

## Standalone Script

`scripts/send_bwr_ble.py` is a self-contained script that demonstrates the core BLE protocol used to communicate with the displays. It was the original proof-of-concept used during protocol reverse engineering.

```
python scripts/send_bwr_ble.py --image path/to/image.png --mac AA:BB:CC:DD:EE:FF --mode bwr
```

Requires `bleak` and `Pillow`.

## License
