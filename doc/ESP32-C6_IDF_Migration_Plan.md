# ESP32-C6 Firmware Migration Plan: Arduino to ESP-IDF

This document outlines a plan to migrate the existing ESP32 firmware, currently written using the Arduino framework in the `src/` directory, to the ESP-IDF framework. The target hardware is the ESP32-C6 (specifically the Seeed Studio XIAO ESP32-C6), and the new ESP-IDF code will reside in a parallel directory structure (`src_idf/`) to preserve the original Arduino project.

The goal is to replicate the exact functionality of the current firmware using ESP-IDF APIs and best practices, enabling successful compilation and operation on the ESP32-C6.

## Current Firmware Functionality (Arduino)

Based on the analysis of `src/main.cpp`, `src/globals.h`, `src/globals.cpp`, `src/config.h`, `src/wifi_utils.cpp`, `src/mqtt_utils.cpp`, and `src/ble_utils.cpp`, the key features are:

*   **Initialization:** Serial communication, WiFi, MQTT, and BLE (NimBLE).
*   **Connectivity Management:** Automatic reconnection for WiFi and MQTT.
*   **MQTT Communication:**
    *   Connect to a specified broker with optional authentication.
    *   Subscribe to wildcard topics for `start`, `packet`, and `scan` commands.
    *   Handle incoming messages in a callback function (`mqttCallback`).
    *   Parse JSON payload from the `start` command to get the expected packet count.
    *   Extract target BLE MAC address from the MQTT topic.
    *   Queue incoming data packets.
    *   Publish status updates (connecting, idle, writing, success, error states) to display-specific or general bridge topics.
*   **BLE Communication (Client):**
    *   Initialize the BLE subsystem (NimBLE).
    *   Connect to a target BLE device by MAC address.
    *   Discover a specific service and characteristic by UUID.
    *   Write data packets to the discovered characteristic.
    *   Manage BLE connection state and handle disconnects.
    *   Implement retry logic for BLE connection attempts.
    *   Implement a timeout for receiving packets.
*   **BLE Scanning:**
    *   Perform a BLE scan upon receiving an MQTT command.
    *   Report scan results (details from `scan_utils.cpp` are needed for full understanding).
*   **State Management:** Use global variables and a packet queue (`std::queue<std::vector<uint8_t>>`) to manage the transfer process state.
*   **Utilities:** Convert hex strings to byte vectors.

## Phase 1: Project Setup (PlatformIO & ESP-IDF Structure)

This phase focuses on configuring PlatformIO and setting up the basic directory structure and build files required for an ESP-IDF project.

1.  **Modify `platformio.ini`:**
    *   Add a new environment section for the ESP-IDF build targeting the ESP32-C6. We will name it `[env:seeed_xiao_esp32c6_idf]`.
    *   Configure this environment to use the official `espressif32` platform and the `espidf` framework.
    *   Specify the board as `seeed_xiao_esp32c6`.
    *   Crucially, define `src_dir` to point to the main application code directory within `src_idf/` (e.g., `src_idf/main`) and `board_build.cmake_project_path` to the root of the ESP-IDF project within `src_idf/`.
    *   Remove `lib_deps` and `lib_ignore` from this new environment, as dependencies will be managed by ESP-IDF's build system (CMake and `idf_component.yml`).

    ```ini
    [env:seeed_xiao_esp32c6_idf]
    platform = espressif32
    board = seeed_xiao_esp32c6
    framework = espidf

    # Point to the main application component within src_idf
    src_dir = src_idf/main
    # Point to the root of the ESP-IDF project within src_idf
    board_build.cmake_project_path = src_idf

    monitor_speed = 115200

    # Dependencies are managed via ESP-IDF components (CMakeLists.txt / idf_component.yml)
    # lib_deps =
    # lib_ignore =
    ```

2.  **Create `src_idf/` Directory Structure:**
    *   Create a new directory at the project root: `/home/albert/code/aintinksmart/src_idf/`.
    *   Inside `src_idf/`, create a subdirectory for the main application component: `/home/albert/code/aintinksmart/src_idf/main/`.

3.  **Create `src_idf/CMakeLists.txt`:**
    *   This is the top-level CMake file for the ESP-IDF project. It's typically minimal.

    ```cmake
    cmake_minimum_required(VERSION 3.16)
    include($ENV{IDF_PATH}/tools/cmake/project.cmake)
    project(eink_bridge_idf) # Replace with your desired project name
    ```

4.  **Create `src_idf/main/CMakeLists.txt`:**
    *   This CMake file defines the `main` component. It specifies the source files to compile, include directories, and dependencies on other components.

    ```cmake
    idf_component_register(SRCS "main.cpp" # Or main.c, list all your .c/.cpp files here
                           INCLUDE_DIRS "." # Include the current directory
                           REQUIRES "esp_wifi" "esp_event" "nvs_flash" "mqtt" "cjson" "esp_ble_mesh" # Example dependencies - adjust based on actual needs
                           PRIV_REQUIRES "ble" # Example private dependencies
                           )
    ```
    *   *Note:* The `REQUIRES` and `PRIV_REQUIRES` lists are examples. You'll need to identify the specific ESP-IDF components your refactored code will depend on (e.g., `esp_wifi`, `esp_event`, `nvs_flash`, `mqtt`, `cjson`, `esp_ble_mesh` or `esp_nimble_hci` for BLE).

5.  **Create `src_idf/main/idf_component.yml` (Recommended):**
    *   This file explicitly declares dependencies on managed components from the ESP-IDF Component Registry (like `esp-mqtt`).

    ```yaml
    dependencies:
      # Example: Dependency on the esp-mqtt component
      # espressif/esp-mqtt: "^1.0.0" # Use the appropriate version specifier
      # Example: Dependency on cJSON
      # espressif/cjson: "*"
    ```
    *   You'll need to find the correct component names and version specifiers for the libraries you'll use (e.g., for MQTT and JSON).

6.  **Create `src_idf/sdkconfig.defaults` (Optional):**
    *   This file allows you to set default values for ESP-IDF configuration options. These can be overridden by the full `sdkconfig` generated by `menuconfig`.

    ```ini
    # Example: Enable BLE
    CONFIG_BT_ENABLED=y
    CONFIG_BT_BLE_ENABLED=y
    CONFIG_BT_NIMBLE_ENABLED=y # If using NimBLE port
    # Example: Set MQTT buffer size
    CONFIG_MQTT_BUFFER_SIZE=2048
    ```

7.  **Initial Code Entry Point:**
    *   Create a placeholder file for your main application code: `/home/albert/code/aintinksmart/src_idf/main/main.cpp` (or `main.c`).
    *   Add the basic ESP-IDF entry point:

    ```cpp
    #include <stdio.h>
    #include "freertos/FreeRTOS.h"
    #include "freertos/task.h"
    #include "esp_log.h" // For logging

    extern "C" void app_main(void)
    {
        ESP_LOGI("MAIN", "ESP-IDF App Starting");
        // Your initialization and task creation will go here
    }
    ```

8.  **Configure ESP-IDF (`sdkconfig`):**
    *   After setting up the files above, you will need to run the ESP-IDF configuration tool via PlatformIO:
        ```bash
        pio run -t menuconfig -e seeed_xiao_esp32c6_idf
        ```
    *   This will open an interactive menu where you *must* configure essential settings for your project, including:
        *   **Serial Flasher Config:** Baud rate, flash mode.
        *   **ESP System Settings:** CPU frequency, watchdog timers.
        *   **Component Config:**
            *   **Bluetooth:** Enable Bluetooth, BLE, and choose the host stack (likely NimBLE if you want similar APIs, or Bluedroid). Configure BLE roles (Client).
            *   **Wi-Fi:** Enable WiFi, set country code, configure connection parameters (though you'll handle connection in code).
            *   **LWIP:** Network stack configuration.
            *   **MQTT:** Enable the MQTT component and configure buffer sizes, etc.
            *   **JSON:** Enable the cJSON component.
            *   **FreeRTOS:** Configure task stack sizes, tick rate, etc.
            *   **NVS (Non-Volatile Storage):** Essential for storing WiFi credentials persistently (though your current code doesn't do this, it's good practice in IDF).
        *   **Application Configuration:** Set your WiFi SSID/Password, MQTT Broker/User/Password, BLE UUIDs here or keep them in code/separate config files. Using Kconfig options defined in your component's `CMakeLists.txt` is the IDF way for application-specific config.

## Phase 2: Code Migration (Refactoring `src/` to `src_idf/main/`)

This is the most time-consuming phase, involving rewriting the Arduino-based logic using ESP-IDF APIs.

1.  **Entry Point (`app_main`):**
    *   The `app_main` function is the entry point. It should perform system initializations (NVS flash, network interfaces, event loop) and then create FreeRTOS tasks for different functionalities (e.g., a WiFi task, an MQTT task, a BLE client task, a main application logic task).

2.  **Global State and Configuration:**
    *   Instead of global variables defined in `.cpp` and declared `extern` in `.h`, consider using a more structured approach:
        *   Pass necessary data between tasks using FreeRTOS queues or event groups.
        *   Use a dedicated configuration header file (`config.h` in `src_idf/main/`) for constants like UUIDs, timeouts, etc.
        *   Consider using ESP-IDF's Kconfig system to manage configuration values that can be set via `menuconfig`.

3.  **WiFi Management:**
    *   Replace `WiFi.begin()`, `WiFi.isConnected()`, `WiFi.localIP()` with ESP-IDF WiFi APIs (`esp_wifi_init`, `esp_wifi_set_config`, `esp_wifi_start`, `esp_event_handler_register` for WiFi events like `WIFI_EVENT_STA_CONNECTED`, `IP_EVENT_STA_GOT_IP`, `WIFI_EVENT_STA_DISCONNECTED`).
    *   Implement the reconnection logic within an event handler or a dedicated WiFi task.

4.  **MQTT Management:**
    *   Use the `esp-mqtt` component.
    *   Replace `PubSubClient` initialization and methods (`setServer`, `setCallback`, `subscribe`, `publish`, `loop`, `connected`) with `esp_mqtt_client_init`, `esp_mqtt_client_start`, `esp_mqtt_client_register_event`, `esp_mqtt_client_subscribe`, `esp_mqtt_client_publish`.
    *   Handle incoming messages and connection state changes within the MQTT event handler function.
    *   The logic for parsing the `start` command JSON and extracting the MAC from the topic will need to be adapted to work within the ESP-IDF event handler context.

5.  **BLE Management (Client):**
    *   Replace NimBLE initialization (`NimBLEDevice::init`) and client operations (`createClient`, `connect`, `getService`, `getCharacteristic`, `writeValue`, `disconnect`) with ESP-IDF BLE APIs.
    *   You'll need to initialize the Bluetooth controller and host (`esp_bt_controller_init`, `esp_bt_controller_enable`, `esp_bluedroid_init`, `esp_bluedroid_enable` for Bluedroid, or the corresponding NimBLE port functions).
    *   Register GAP and GATT client event handlers (`esp_gap_ble_cb_register`, `esp_gattc_cb_register`).
    *   Implement the connection logic within the GATT client event handler, triggered by a scan result or a direct connection command.
    *   Service and characteristic discovery will happen within the GATT client event handler after a successful connection.
    *   Writing packets will use `esp_gattc_write_char`.
    *   Manage connection state and handle disconnects within the event handlers.
    *   The retry and timeout logic will need to be implemented using FreeRTOS timers or tasks.

6.  **BLE Scanning:**
    *   Replace NimBLE scanning (`NimBLEDevice::getScan()->start()`) with ESP-IDF GAP scan APIs (`esp_gap_ble_start_scanning`).
    *   Process scan results within the GAP event handler (`esp_gap_ble_cb_t`).
    *   The logic for reporting scan results via MQTT will need to be integrated.

7.  **JSON Parsing:**
    *   Use the `cJSON` component.
    *   Replace `ArduinoJson` parsing (`deserializeJson`) with `cJSON_Parse`, `cJSON_GetObjectItemCaseSensitive`, `cJSON_GetStringValue`, etc. Remember to use `cJSON_Delete` to free memory.

8.  **Packet Queue and State Machine:**
    *   The `std::queue<std::vector<uint8_t>>` can still be used, but access to it must be synchronized if accessed by multiple tasks (e.g., using a FreeRTOS mutex).
    *   The state machine logic currently in `loop()` will need to be implemented within one or more FreeRTOS tasks. Tasks can wait on events (e.g., a packet arriving in the queue, a BLE connection established) using FreeRTOS primitives.

9.  **Utility Functions:**
    *   Port simple functions like `hexStringToBytes` to work with standard C++ strings/vectors or ESP-IDF equivalents.

## Phase 3: Build and Debug

1.  **Build:**
    *   Use PlatformIO to build the ESP-IDF project:
        ```bash
        pio run -e seeed_xiao_esp32c6_idf
        ```
    *   Address any compilation errors related to API changes or missing includes.

2.  **Configure:**
    *   If you need to change ESP-IDF settings, run `menuconfig`:
        ```bash
        pio run -t menuconfig -e seeed_xiao_esp32c6_idf
        ```
    *   Rebuild after changing configuration.

3.  **Upload and Monitor:**
    *   Upload the firmware:
        ```bash
        pio run -e seeed_xiao_esp32c6_idf --target upload
        ```
    *   Monitor serial output:
        ```bash
        pio device monitor -e seeed_xiao_esp32c6_idf
        ```

4.  **Debugging:**
    *   Use ESP-IDF's logging system (`ESP_LOGx` macros) instead of `Serial.println`. Configure log levels in `menuconfig`.
    *   Utilize PlatformIO's debugging features, which can be set up for ESP-IDF projects.

## Conclusion

Migrating from Arduino to ESP-IDF is a significant effort, primarily due to the difference in APIs and the shift to a FreeRTOS-based, event-driven architecture. However, it provides a more robust and flexible foundation for complex applications on ESP32 chips, especially for leveraging advanced features like the ESP32-C6's peripherals.

This plan provides the necessary steps for setting up the project structure and highlights the key areas in your code that will require refactoring using ESP-IDF APIs. The actual code porting will involve consulting the ESP-IDF programming guide and examples for the specific components you need (WiFi, Event Loop, TCP/IP, BLE, MQTT, JSON, FreeRTOS).