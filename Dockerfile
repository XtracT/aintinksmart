# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies for BLE and image processing
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
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
COPY ./app /app/app

# Define environment variables for configuration (defaults can be overridden at runtime)
ENV MQTT_BROKER=""
ENV MQTT_PORT="1883"
ENV MQTT_USERNAME=""
ENV EINK_PACKET_DELAY_MS="20"

# Timeout for CLI scripts waiting for status
ENV MQTT_STATUS_TIMEOUT_SEC="60"
ENV BLE_ENABLED="true"
ENV USE_GATEWAY="false"

# Run the Python application module
CMD ["python", "-m", "app.main"]

# See README.md for build and run instructions.