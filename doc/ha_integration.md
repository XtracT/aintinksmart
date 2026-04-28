# Ain't Ink Smart Home Assistant Integration

Send images to BLE e-ink displays from Home Assistant.

## Installation

### HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed.
2. Go to **HACS > Integrations > Custom Repositories**.
3. Add this repository URL with category **Integration**.
4. Install **"Ain't Ink Smart E-Ink Display"**.
5. Restart Home Assistant.

### Manual

1. Copy `custom_components/aintinksmart/` into `config/custom_components/`.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings > Devices & Services > Add Integration**.
2. Search for **"Ain't Ink Smart E-Ink Display"**.
3. Select your display from BLE discovery, or enter the MAC address manually.

## Entities

*   **Status Sensor** — `idle` / `connecting` / `sending_image` / `success` / `error` / `unavailable`
*   **Packet Delay Number** — BLE packet delay in ms (default: 20)

## Service: `aintinksmart.send_image`

| Field | Required | Description |
|-------|----------|-------------|
| `image_path` | No | Local file path or URL |
| `image_data` | No | Base64 encoded image |
| `image_entity_id` | No | HA `camera` or `image` entity ID |
| `mode` | Yes | `bw` or `bwr` |

Provide exactly one image source.

```yaml
action: aintinksmart.send_image
target:
  device_id: 1234567890abcdef
data:
  image_path: "/media/dashboard.png"
  mode: "bwr"
```

## Error Handling

The status sensor shows error states with details in the `last_error` attribute.
