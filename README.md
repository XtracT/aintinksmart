# Ain't Ink Smart

Control BLE e-ink displays (Electronic Shelf Labels) from Home Assistant or standalone scripts. Tested on EasyTag displays.

## Compatibility

| Size  | Resolution | Colors | Part Number | Tested |
| :---- | :--------- | :----- | :---------- | :----- |
| 7.5"  | 800x480    | BWR    | AES0750     | Yes    |

## Home Assistant Integration

A dumb pipe integration: receives an image via service call, converts it to the display protocol, and sends it over Bluetooth. No polling, no image comparison, no auto-update logic. Use HA Automations to decide when to push.

### Installation via HACS

1. Ensure [HACS](https://hacs.xyz/) is installed.
2. Go to **HACS > Integrations > Custom Repositories**.
3. Add this repository URL with category **Integration**.
4. Search for **"Ain't Ink Smart E-Ink Display"** and install.
5. Restart Home Assistant.

### Manual Installation

1. Copy `custom_components/aintinksmart/` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

### Usage

```yaml
action: aintinksmart.send_image
target:
  device_id: 1234567890abcdef
data:
  image_path: "/media/dashboard.png"
  mode: "bwr"
```

The service accepts one image source: `image_path` (file or URL), `image_data` (base64), or `image_entity_id` (HA entity).

### Entities

- **Status Sensor** — Shows idle / connecting / sending / success / error.
- **Packet Delay Number** — BLE packet timing in ms (default: 20).

For full documentation see [doc/home_assistant_integration.md](doc/home_assistant_integration.md).

## Standalone Script

`scripts/send_bwr_ble.py` is a self-contained script that demonstrates the core BLE protocol used to communicate with the displays. It was the original proof-of-concept used during protocol reverse engineering.

```
python scripts/send_bwr_ble.py --image path/to/image.png --mac AA:BB:CC:DD:EE:FF --mode bwr
```

Requires `bleak` and `Pillow`.

## License
