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
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
# Copy the 'app' directory and its contents
COPY ./app /app/app

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Define environment variables (optional, can be set at runtime)
# ENV BLE_DEVICE_MAC="AA:BB:CC:DD:EE:FF" # Example

# Run the application using uvicorn
# Use 0.0.0.0 to bind to all interfaces inside the container
# The user will need to map the host port (e.g., 8000) to the container port 8000 when running
# e.g., docker run -p 8000:8000 ...
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- Reminder on Running ---
# Build: docker build -t ble-sender-service .
# Run (Requires host network or D-Bus volume mount for BLE access):
#   Option 1 (Host Network): docker run --rm -it --net=host ble-sender-service
#   Option 2 (D-Bus Mount): docker run --rm -it -p 8000:8000 -v /var/run/dbus:/var/run/dbus ble-sender-service
#   (May require additional privileges depending on the host system)