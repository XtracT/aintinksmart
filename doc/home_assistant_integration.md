# Ain't Ink Smart Home Assistant Integration

A Home Assistant custom integration for controlling BLE e-ink displays (Electronic Shelf Labels). Send images to the display via a service call — the integration is a dumb pipe: receive image, convert, blast over BLE.

## Installation

### HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed.
2. Go to **HACS > Integrations > Custom Repositories**.
3. Add this repository URL with category **Integration**.
4. Search for **"Ain't Ink Smart E-Ink Display"** and install.
5. Restart Home Assistant.

### Manual

1. Copy `custom_components/aintinksmart/` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings > Devices & Services > Add Integration**.
2. Search for **"Ain't Ink Smart E-Ink Display"**.
3. Select your display from the BLE discovery list, or enter the MAC address manually.

## Entities

Each configured display creates:

*   **Status Sensor** — Shows `idle`, `connecting`, `sending_image`, `success`, `error`, or `unavailable`.
*   **Packet Delay Number** — Delay in milliseconds between BLE packets (default: 20ms). Tune for stability.

## Service: `aintinksmart.send_image`

The only service. Sends an image to the display. Provide **one** image source:

| Field | Type | Description |
|-------|------|-------------|
| `image_path` | string | Local file path (`/media/dashboard.png`) or URL (`https://...`) |
| `image_data` | string | Base64 encoded image data |
| `image_entity_id` | string | Entity ID of a `camera` or `image` entity |
| `mode` | string | **Required.** `bw` (black/white) or `bwr` (black/white/red) |

### Example (Automation)

```yaml
action: aintinksmart.send_image
target:
  device_id: 1234567890abcdef
data:
  image_path: "/media/dashboard.png"
  mode: "bwr"
```

The integration does not monitor entities or compare images. Use Home Assistant Automations to decide **when** to push an update.

## How It Works

```
Service call → read image → process pixels → format protocol → build BLE packets → send
```

1. **Read**: File path, URL, base64 data, or HA entity.
2. **Process**: Convert to black/red bitplanes (via Pillow).
3. **Format**: Generate FC (RLE) or FE (packed) hex payload, whichever is shorter.
4. **Build**: Chunk into BLE packets with CRC16 + XOR encryption.
5. **Send**: Connect via `bleak`, write packets, disconnect.
