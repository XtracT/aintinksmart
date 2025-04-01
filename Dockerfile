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
# This now includes paho-mqtt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
# Copy the 'app' directory and its contents
COPY ./app /app/app

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Define environment variables for configuration (defaults can be overridden at runtime)
ENV MQTT_BROKER=""
ENV MQTT_PORT="1883"
ENV MQTT_USERNAME=""
ENV MQTT_PASSWORD=""
# Default topic for publishing commands to ESPHome gateway
ENV MQTT_COMMAND_TOPIC="ble_sender/command/send_image"
# Attempt direct BLE by default if container has access
ENV BLE_ENABLED="true"
# MQTT_ENABLED defaults to true if MQTT_BROKER is set at runtime, unless explicitly set to false via -e MQTT_ENABLED=false

# Run the application using uvicorn
# Use 0.0.0.0 to bind to all interfaces inside the container
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

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