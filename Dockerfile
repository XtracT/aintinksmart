# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required for BLE communication (Debian/Ubuntu based)
# and image processing (libgl1 is often needed by Pillow/OpenCV)
# Using --no-install-recommends reduces image size
RUN apt-get update && apt-get install -y --no-install-recommends \
    bluetooth \
    bluez \
    libdbus-1-dev \
    libgl1-mesa-glx \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Using --no-cache-dir reduces image size
# This now includes aiomqtt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
# Copy the 'app' directory and its contents
COPY ./app /app/app

# Make port 8000 available to the world outside this container
# EXPOSE 8000 # No longer a web service

# Define environment variables for configuration (defaults can be overridden at runtime)
ENV MQTT_BROKER=""
ENV MQTT_PORT="1883"
ENV MQTT_USERNAME=""
# ENV MQTT_PASSWORD="" # Removed default, must be provided at runtime if needed
# Base topic for ESP32 commands/status
ENV MQTT_EINK_TOPIC_BASE="eink_display"
# Topic to listen for requests
ENV MQTT_REQUEST_TOPIC="eink_sender/request/send_image"
# Topic to listen for scan requests
ENV MQTT_SCAN_REQUEST_TOPIC="eink_sender/request/scan"
# Default topic for publishing general status updates
ENV MQTT_DEFAULT_STATUS_TOPIC="eink_sender/status/default"
ENV EINK_PACKET_DELAY_MS="20"
# Still relevant for BLE timeout? Maybe remove later.
ENV MQTT_STATUS_TIMEOUT_SEC="60"
# Enable direct BLE attempts by default
ENV BLE_ENABLED="true"
# Use direct BLE by default if BLE_ENABLED=true
ENV USE_GATEWAY="false"

# Run the application using uvicorn
# Use 0.0.0.0 to bind to all interfaces inside the container
# Run the Python module directly
CMD ["python", "-m", "app.main"]

# --- Reminder on Running ---
# Build: docker build -t ble-sender-service .
# Run:
#   - Set MQTT environment variables if needed (e.g., -e MQTT_BROKER=192.168.1.100)
#   - Provide BLE access if direct BLE is desired (--net=host or -v /var/run/dbus:/var/run/dbus)
# Example with MQTT and BLE Host Network:
#   docker run --rm -it --net=host \
#     -e MQTT_BROKER=192.168.1.100 \
#     -e MQTT_USERNAME=user \
#     -e MQTT_PASSWORD=pass \
#     ble-sender-service
# Example with MQTT only (no BLE access needed for container):
#   docker run --rm -it -p 8000:8000 \
#     -e MQTT_BROKER=192.168.1.100 \
#     -e BLE_ENABLED=false \
#     ble-sender-service