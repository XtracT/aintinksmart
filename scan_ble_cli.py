import argparse
import paho.mqtt.client as mqtt
import time
import json
import sys
import threading

# --- Configuration ---
DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
DEFAULT_REQUEST_TOPIC = "aintinksmart/service/request/scan"
# The service now publishes results (including direct BLE) to the default status topic
# We still need a topic for the *gateway's* scan results
DEFAULT_GATEWAY_RESULT_TOPIC = "aintinksmart/gateway/bridge/scan_result"
# We'll also listen on the service's default status topic for direct BLE results or errors
DEFAULT_SERVICE_STATUS_TOPIC = "aintinksmart/service/status/default"
DEFAULT_TIMEOUT = 20 # seconds

# --- Global Variables ---
found_devices = []
message_lock = threading.Lock()
stop_event = threading.Event()

# --- MQTT Callbacks ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("CLI: Connected to MQTT Broker!")
        # Subscribe to the service status topic and the gateway result topic
        service_status_topic = userdata['service_status_topic']
        gateway_result_topic = userdata['gateway_result_topic']
        client.subscribe([(service_status_topic, 0), (gateway_result_topic, 0)])
        print(f"CLI: Subscribed to {service_status_topic} and {gateway_result_topic}")
        # Publish the scan request after successful connection and subscription
        # Include response_topic so service knows where to send final confirmation/error if needed
        # (though results for direct BLE now come via status topic)
        request_topic = userdata['request_topic']
        # Use service_status_topic as the nominal response topic for service confirmation/errors
        payload = json.dumps({"action": "scan", "response_topic": service_status_topic})
        print(f"CLI: Publishing scan request to {request_topic}")
        client.publish(request_topic, payload=payload, qos=1)
    else:
        print(f"CLI: Failed to connect, return code {rc}")
        stop_event.set() # Signal main thread to exit if connection fails

def on_message(client, userdata, msg):
    global found_devices
    print(f"CLI: Received message on {msg.topic}")
    try:
        payload_data = json.loads(msg.payload.decode())
        # Handle messages from the service status topic
        if msg.topic == userdata['service_status_topic']:
            # Check if it's a successful BLE scan result
            if payload_data.get("status") == "success" and payload_data.get("method") == "ble" and "devices" in payload_data:
                devices = payload_data.get("devices", [])
                print(f"CLI: Received {len(devices)} device(s) from service (Direct BLE Scan):")
                with message_lock:
                    # Add devices, avoiding duplicates based on address
                    for dev in devices:
                        if not any(d.get("address") == dev.get("address") for d in found_devices):
                            found_devices.append(dev)
                # Consider stopping here for direct BLE scan? Or wait for timeout? Let's wait for timeout for now.
            # Check if it's a confirmation of gateway trigger
            elif payload_data.get("status") == "success" and payload_data.get("method") == "mqtt":
                 print(f"CLI: Service confirmed MQTT Gateway scan triggered. Listening on {userdata['gateway_result_topic']}...")
                 # We are already subscribed, just wait for gateway results
            # Check if it's an error message from the service
            elif payload_data.get("status") == "error":
                 print(f"CLI: Service reported error: {payload_data.get('message', 'Unknown error')}")
                 stop_event.set() # Stop on error from service
            # Ignore other intermediate status messages from the service on this topic
            # else:
            #     print(f"CLI: Ignoring intermediate status from service: {payload_data.get('status')}")

        # Handle results directly from the gateway
        elif msg.topic == userdata['gateway_result_topic']:
             # Assume gateway publishes device info directly as JSON objects
             if isinstance(payload_data, dict) and "name" in payload_data and "address" in payload_data:
                  print(f"CLI: Received device from gateway: {payload_data}")
                  with message_lock:
                       # Avoid duplicates if service also reports gateway results (though it shouldn't now)
                       if not any(d.get("address") == payload_data["address"] for d in found_devices):
                            found_devices.append(payload_data)
             else:
                  print(f"CLI: Received unexpected message on gateway topic: {payload_data}")

    except json.JSONDecodeError:
        print(f"CLI: Received non-JSON message on {msg.topic}: {msg.payload.decode()}")
    except Exception as e:
        print(f"CLI: Error processing message on {msg.topic}: {e}")

def on_disconnect(client, userdata, rc):
    print("CLI: Disconnected from MQTT Broker.")
    stop_event.set() # Signal exit on disconnect

# --- Main Script ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trigger BLE scan via MQTT service and display results.")
    parser.add_argument("--broker", default=DEFAULT_BROKER, help=f"MQTT broker address (default: {DEFAULT_BROKER})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"MQTT broker port (default: {DEFAULT_PORT})")
    parser.add_argument("--user", default=None, help="MQTT username")
    parser.add_argument("--pass", default=None, help="MQTT password", dest='password')
    parser.add_argument("--request-topic", default=DEFAULT_REQUEST_TOPIC, help=f"MQTT topic to send scan request (default: {DEFAULT_REQUEST_TOPIC})")
    # Remove --result-topic as direct results now come via status topic
    parser.add_argument("--service-status-topic", default=DEFAULT_SERVICE_STATUS_TOPIC, help=f"MQTT topic for service status/results (default: {DEFAULT_SERVICE_STATUS_TOPIC})")
    parser.add_argument("--gateway-result-topic", default=DEFAULT_GATEWAY_RESULT_TOPIC, help=f"MQTT topic to listen for gateway scan results (default: {DEFAULT_GATEWAY_RESULT_TOPIC})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"Seconds to wait for results (default: {DEFAULT_TIMEOUT})")

    args = parser.parse_args()

    userdata = {
        'service_status_topic': args.service_status_topic, # Use the new argument
        'gateway_result_topic': args.gateway_result_topic,
        'request_topic': args.request_topic
    }

    client = mqtt.Client(userdata=userdata)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    if args.user:
        client.username_pw_set(args.user, args.password)

    try:
        print(f"CLI: Connecting to {args.broker}:{args.port}...")
        client.connect(args.broker, args.port, 60)
    except Exception as e:
        print(f"CLI: Connection failed: {e}")
        sys.exit(1)

    client.loop_start()

    # Wait for timeout or stop event
    stop_event.wait(timeout=args.timeout)

    client.loop_stop()
    client.disconnect()

    print("\n--- Scan Results ---")
    if found_devices:
        # Basic duplicate removal just in case
        unique_devices = {d['address']: d for d in found_devices}.values()
        print(f"Found {len(unique_devices)} unique device(s):")
        for device in unique_devices:
            print(f"  Name: {device.get('name', 'N/A')}, Address: {device.get('address', 'N/A')}")
    else:
        print("No devices found.")

    print("--------------------")