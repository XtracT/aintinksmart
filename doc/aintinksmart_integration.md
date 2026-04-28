# Ain't Ink Smart Home Assistant Integration

A BLE-only Home Assistant integration for e-ink displays. Receives an image via service call, converts it to the display protocol, and sends it over Bluetooth.

## Structure

- `__init__.py`: Entry point. Registers the `send_image` service and sets up platforms.
- `config_flow.py`: BLE discovery and manual MAC address entry.
- `device.py`: State machine (idle → sending → success/error). Resolves image sources and sends via BLE.
- `ble_comms.py`: BLE connection and packet writing via `bleak`.
- `helpers.py`: Image processing (Pillow), protocol formatting (RLE/packed), packet building (CRC + XOR).
- `sensor.py`: Status sensor entity.
- `number.py`: Packet delay entity.
- `entity.py`: Base entity class.
- `services.yaml`: `send_image` service definition.
- `strings.json`: Config flow UI strings.
- `manifest.json`: Integration metadata.

## Usage

1. Install via HACS or copy to `custom_components/aintinksmart/`.
2. Add the integration and configure via BLE discovery or manual MAC entry.
3. Call `aintinksmart.send_image` with an image source and mode.

```yaml
action: aintinksmart.send_image
target:
  device_id: 1234567890abcdef
data:
  image_path: "/media/dashboard.png"
  mode: "bwr"
```
