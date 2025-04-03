import argparse
import paho.mqtt.client as mqtt
import time
import json
import sys
import threading

# --- Configuration ---
DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
DEFAULT_REQUEST_TOPIC = "eink_sender/request/scan"
DEFAULT_RESULT_TOPIC = "eink_sender/scan/result" # Topic for results from service (Direct BLE mode)
DEFAULT_GATEWAY_RESULT_TOPIC = "eink_display/scan/result" # Topic for results from ESP32 (Gateway mode)
DEFAULT_TIMEOUT = 20 # seconds

# --- Global Variables ---
found_devices = []
message_lock = threading.Lock()
stop_event = threading.Event()

# --- MQTT Callbacks ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("CLI: Connected to MQTT Broker!")
        # Subscribe to both potential result topics
        result_topic = userdata['result_topic']
        gateway_result_topic = userdata['gateway_result_topic']
        client.subscribe([(result_topic, 0), (gateway_result_topic, 0)])
        print(f"CLI: Subscribed to {result_topic} and {gateway_result_topic}")
        # Publish the scan request after successful connection and subscription
        request_topic = userdata['request_topic']
        payload = json.dumps({"action": "scan", "response_topic": result_topic})
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
        # Handle results from the service (Direct BLE)
        if msg.topic == userdata['result_topic']:
            if payload_data.get("status") == "success" and payload_data.get("method") == "ble":
                devices = payload_data.get("devices", [])
                print(f"CLI: Received {len(devices)} device(s) from service (Direct BLE Scan):")
                with message_lock:
                    found_devices.extend(devices) # Assuming list format
            elif payload_data.get("status") == "success" and payload_data.get("method") == "mqtt":
                 print(f"CLI: Service confirmed MQTT Gateway scan triggered. Listening on {userdata['gateway_result_topic']}...")
                 # We are already subscribed, just wait
            elif payload_data.get("status") == "error":
                 print(f"CLI: Service reported error: {payload_data.get('message', 'Unknown error')}")
                 stop_event.set() # Stop on error from service
            else:
                 print(f"CLI: Received unexpected response from service: {payload_data}")

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
    parser.add_argument("--result-topic", default=DEFAULT_RESULT_TOPIC, help=f"MQTT topic to listen for service results (default: {DEFAULT_RESULT_TOPIC})")
    parser.add_argument("--gateway-result-topic", default=DEFAULT_GATEWAY_RESULT_TOPIC, help=f"MQTT topic to listen for gateway results (default: {DEFAULT_GATEWAY_RESULT_TOPIC})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"Seconds to wait for results (default: {DEFAULT_TIMEOUT})")

    args = parser.parse_args()

    userdata = {
        'result_topic': args.result_topic,
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