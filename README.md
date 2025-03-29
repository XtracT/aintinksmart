# BLE E-Ink Image Sender Service

This project provides a Dockerized web service (using FastAPI) to send black/white or black/white/red images to certain types of Bluetooth Low Energy (BLE) e-ink displays. It offers both a simple Web UI for manual uploads and a JSON API for programmatic use.

## Description

The service implements a communication protocol based on reverse engineering of the original device communication. It takes an image file (via upload or Base64 data), processes it into the required format, and transmits it to the specified display via BLE.

The core logic is separated into distinct Python classes within the `app/` directory for better maintainability and testability.

## Disclaimer

This service is unofficial and based on reverse engineering efforts. It is provided "as is" without warranty of any kind. While it aims to replicate the necessary protocol steps, there might be subtle differences compared to the official application, particularly in how images are dithered or converted to the display's color format. Use at your own discretion. Ensure you comply with any relevant terms of service for your device.

## Requirements

*   **Docker:** Required to build and run the service container.
*   **Host System:**
    *   A compatible BLE adapter (e.g., BlueZ on Linux, WinRT on Windows 10+, CoreBluetooth on macOS).
    *   Working Bluetooth stack accessible by Docker (see Running the Service).
*   **(For Development):** Python 3.7+ and the libraries listed in `requirements.txt`.

## Setup & Running the Service

1.  **Build the Docker Image:**
    Navigate to the project's root directory (where the `Dockerfile` is located) and run:
    ```bash
    docker build -t ble-sender-service .
    ```

2.  **Run the Docker Container:**
    The container needs access to the host's Bluetooth hardware. Choose **one** of the following methods:

    *   **Option 1: Host Network Mode (Simpler, Less Isolated)**
        ```bash
        docker run --rm -it --net=host ble-sender-service
        ```
        *(Note: With `--net=host`, the service will be accessible via `http://localhost:8000` on the host machine.)*

    *   **Option 2: D-Bus Mount (Recommended for Linux with BlueZ)**
        This maps the host's D-Bus socket into the container, allowing communication with the BlueZ daemon.
        ```bash
        docker run --rm -it -p 8000:8000 -v /var/run/dbus:/var/run/dbus ble-sender-service
        ```
        *(Note: You might need additional privileges depending on your host system and Docker setup, such as `--cap-add=NET_ADMIN`, `--cap-add=SYS_ADMIN`, or even `--privileged`. Try without them first.)*

    The service should now be running and accessible.

## Usage

### Web UI

1.  Open your web browser and navigate to `http://localhost:8000` (or the IP address of your Docker host if applicable).
2.  Use the form to:
    *   Select an image file.
    *   Enter the target display's BLE MAC address (format: `AA:BB:CC:DD:EE:FF`) **OR** click the "Discover" button.
        *   Clicking "Discover" scans for nearby devices advertising "easyTag".
        *   If devices are found, select the desired one from the dropdown list that appears. Its MAC address will automatically populate the input field.
    *   Choose the color mode (`bwr` or `bw`).
    *   Click "Send Image".
3.  Status messages will appear below the form.

### JSON API

Send a `POST` request to the `/send_image` endpoint (e.g., `http://localhost:8000/send_image`).

> **Note:** Interactive API documentation (Swagger UI) is available at `/docs` and alternative documentation (ReDoc) is at `/redoc` when the service is running.

*   **Method:** `POST`
*   **URL:** `/send_image`
*   **Headers:** `Content-Type: application/json`
*   **Body (JSON):**
    ```json
    {
      "mac_address": "AA:BB:CC:DD:EE:FF",
      "image_data": "base64_encoded_image_string_here...",
      "mode": "bwr" // Optional, defaults to "bwr"
    }
    ```
    *   `mac_address`: (Required) Target device MAC address.
    *   `image_data`: (Required) Base64 encoded string of the image file content.
    *   `mode`: (Optional) `"bwr"` or `"bw"`. Defaults to `"bwr"`.

*   **Responses:**
    *   **Success (200 OK):**
        ```json
        {
          "status": "success",
          "message": "Image successfully sent to AA:BB:CC:DD:EE:FF"
        }
        ```
    *   **Error (4xx or 5xx):**
        ```json
        {
          "status": "error",
          "message": "Detailed error message (e.g., Invalid MAC address, BLE connection failed, ...)"
        }
        ```
        *(Note: FastAPI might return errors in a slightly different format, often including a `detail` field, e.g., `{"detail": "Error message"}` for validation errors)*

## Compatibility

This service uses the same underlying protocol logic as the original script. Compatibility has been tested with:

| Size  | Resolution | Colors | Part Number | Tested Status | Notes |
| :---- | :--------- | :----- | :---------- | :------------ | :---- |
| 7.5"  | 800x480    | BWR    | AES0750     | Yes           |       |

*Feel free to report success or failure with other models via issues or pull requests.*

## Troubleshooting

*   **Docker Build Issues:** Ensure you have Docker installed correctly and network access during the build process (for `apt-get` and `pip`).
*   **Container Won't Start/BLE Errors:** The most common issue is Docker not having access to the host's Bluetooth.
    *   Verify your host's Bluetooth is enabled and working (`bluetoothctl` on Linux).
    *   Ensure the `bluetooth` service/daemon is running on the host.
    *   Try both `--net=host` and the D-Bus volume mount methods.
    *   If using the D-Bus mount, ensure permissions are correct. You might need to run the container with elevated privileges (use with caution).
    *   Check container logs (`docker logs <container_id>`) for specific errors from `bleak` or the application.
*   **Connection Issues:** Ensure the display is powered on, within range, and not connected to another device (like a phone). Double-check the MAC address.
*   **Image Appearance:** The service uses basic thresholding for color conversion. Results may vary. Pre-processing images might yield better results.

## Contributing

(Optional: Add guidelines if you accept contributions)

## License

(Optional: Add license information, e.g., MIT License)