# Plan: BLE Image Sender API Service with Web UI

## 1. Introduction &amp; Goal

The goal is to refactor the existing `send_bwr_ble.py` script and transform it into a robust, maintainable, and extensible service running inside a Docker container. This service will expose both a JSON API for programmatic use and a simple web UI for manual image uploads to send images to BLE e-ink displays. The refactoring will adhere to SOLID, KISS, and DRY principles.

## 2. Analysis of Current Script (`send_bwr_ble.py`)

*   **Monolithic Structure:** Combines image processing, protocol encoding (RLE, bit packing, CRC, XOR), and BLE communication in one file, violating SRP.
*   **Magic Numbers/Strings:** Uses many unnamed constants (UUIDs, SECRET_STR, CRC_TABLE, packet sizes, protocol identifiers), hindering readability and maintainability (violates KISS).
*   **Complexity:** Functions like `convert_image_to_bitplanes`, `run_length_encode`, and `build_ble_packets` are long and complex (violates KISS).
*   **Repetition (DRY):** Coordinate formatting, XOR encryption logic, and payload section definitions are repeated or very similar in different places.
*   **Limited Extensibility (OCP):** Adding support for different devices or protocol variations would be difficult.
*   **Testability:** Hard to unit-test core logic without physical hardware.

## 3. Proposed Architecture &amp; Plan

The plan involves refactoring the core logic into classes and building a FastAPI application around it, deployable via Docker.

### Step 3.1: Refactor Core Logic (Python Classes)

Break down the script into distinct classes based on responsibility:

*   **`DeviceConstants` (or `config.py`):**
    *   Holds all protocol-specific constants: UUIDs, `SECRET_STR`, `CRC_TABLE`, packet sizes, magic bytes (`0xFF`, `0xFC`, `"easyTag"` etc.).
*   **`ImageProcessor`:**
    *   Responsibility: Load, validate, pad, and convert images (from bytes or file paths) into black/red bitplanes.
    *   Methods: `load_image_from_bytes`, `_pad_image`, `to_bitplanes`.
*   **`ProtocolFormatter`:**
    *   Responsibility: Handle protocol-specific encoding (RLE, bit packing), choose the optimal format (FC/FE).
    *   Methods: `_run_length_encode`, `_pack_bits`, `format_payload` (takes bitplanes, returns hex string).
*   **`PacketBuilder`:**
    *   Responsibility: Construct BLE packets (header, data) from the formatted payload, applying CRC and XOR.
    *   Methods: `_calculate_crc16`, `_apply_xor`, `build_packets` (takes hex payload, MAC).
*   **`BleCommunicator`:**
    *   Responsibility: Manage BLE connection, discovery, sending packets, handling notifications using `bleak`.
    *   Methods: `connect`, `disconnect`, `send_data` (async), `start_notifications`, `_notification_handler`.

### Step 3.2: Design &amp; Implement Web API (FastAPI)

*   **Framework:** FastAPI (for speed, async support, auto-docs, validation).
*   **Dependencies:** `fastapi`, `uvicorn[standard]`, `bleak`, `Pillow`, `python-multipart` (for file uploads), `jinja2`.
*   **API Endpoint:**
    *   `POST /send_image`: Accepts JSON payload for programmatic use.
        *   Request Body (JSON): `{ "mac_address": "...", "image_data": "base64_encoded_string...", "mode": "bwr" }`
        *   Response (Success): `{ "status": "success", "message": "..." }`
        *   Response (Error): `{ "status": "error", "message": "..." }`
*   **Web UI Endpoint:**
    *   `GET /`: Serves the main HTML page.

### Step 3.3: Implement Web UI

*   **Templating:** Use Jinja2 for `index.html`.
*   **Static Files:** Serve CSS (`static/style.css`) and JS (`static/script.js`) via `StaticFiles`.
*   **HTML (`templates/index.html`):**
    *   Form with file input (`type="file"`), text input for MAC address (`pattern` for validation), optional mode selector, and submit button.
    *   Status display area.
*   **JavaScript (`static/script.js`):**
    *   Intercept form submission.
    *   Read image file using `FileReader.readAsDataURL()`.
    *   Extract Base64 data.
    *   Construct JSON payload.
    *   Use `fetch` to POST to `/send_image`.
    *   Display API response in the status area.

### Step 3.4: Integrate Logic in FastAPI App

*   Create main FastAPI app instance (`main.py`).
*   Mount static files directory.
*   Implement `GET /` endpoint to render `index.html`.
*   Implement `POST /send_image` endpoint:
    1.  Validate input (Pydantic models).
    2.  Decode Base64 image data.
    3.  Instantiate and use `ImageProcessor`, `ProtocolFormatter`, `PacketBuilder`, `BleCommunicator` to process and send the image.
    4.  Handle exceptions and return appropriate JSON responses.

### Step 3.5: Dockerization

*   Create `Dockerfile`:
    *   `FROM python:3.10-slim` (or similar)
    *   `WORKDIR /app`
    *   Install system dependencies: `RUN apt-get update &amp;&amp; apt-get install -y bluetooth bluez libdbus-1-dev libgl1-mesa-glx &amp;&amp; rm -rf /var/lib/apt/lists/*`
    *   Copy `requirements.txt`.
    *   Install Python dependencies: `RUN pip install --no-cache-dir -r requirements.txt`
    *   Copy application code (`*.py`, `templates/`, `static/`).
    *   `EXPOSE 8000`
    *   `CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]`
*   **Critical Note on Bluetooth Access:** Running the container will require granting access to the host's Bluetooth stack. Common methods (test required):
    *   `--net=host`
    *   `-v /var/run/dbus:/var/run/dbus`
    *   Potentially `--privileged` (use cautiously).

## 4. Architecture Diagram (Mermaid)

```mermaid
graph TD
    subgraph User Interaction
        A[Web Browser]
    end

    subgraph External Client
        B[External Service / Script]
    end

    subgraph Docker Container
        C{API Service (FastAPI)}
        subgraph Web Components
            D[HTML/Jinja2 Templates]
            E[Static Files (CSS, JS)]
        end
        subgraph Refactored Core Logic
            F[ImageProcessor]
            G[ProtocolFormatter]
            H[PacketBuilder]
            I[BleCommunicator]
            J(DeviceConstants)
        end
        K[uvicorn Server]
    end

    subgraph Host System
        L((BLE Hardware / BlueZ / D-Bus))
        M((E-Ink Display))
    end

    subgraph External Libraries
        N[Pillow]
        O[bleak]
        P[FastAPI/Uvicorn/Jinja2]
    end

    A -- HTTP GET / --> C; # Request web page
    C -- Serves --> D;
    C -- Serves --> E;
    D --> A; # HTML content
    E --> A; # CSS/JS content

    A -- HTTP POST /send_image (via JS Fetch) --> C; # User uploads via UI
    B -- HTTP POST /send_image (JSON: MAC, Base64 Image) --> C; # Programmatic API call

    C -- Uses --> F;
    C -- Uses --> G;
    C -- Uses --> H;
    C -- Uses --> I;
    C -- Uses --> P; # FastAPI framework
    C -- Runs On --> K;

    F -- Uses --> N; # Pillow
    G -- Uses --> J; # Constants
    H -- Uses --> J; # Constants
    I -- Uses --> O; # Bleak
    I -- Uses --> J; # For UUIDs

    I -- Interacts via Bleak --> L;
    L -- BLE Communication --> M;

    style L fill:#f9f,stroke:#333,stroke-width:2px
    style M fill:#9cf,stroke:#333,stroke-width:2px
    style N fill:#ccf,stroke:#333,stroke-width:1px
    style O fill:#ccf,stroke:#333,stroke-width:1px
    style P fill:#ccf,stroke:#333,stroke-width:1px
    style J fill:#f9f,stroke:#333,stroke-width:2px

```

## 5. Next Steps

Proceed with implementation following this plan, likely starting with the core logic refactoring.