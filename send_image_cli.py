import argparse
import paho.mqtt.client as mqtt
import time
import json
import base64
import sys
import threading

# --- Configuration ---
DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
DEFAULT_REQUEST_TOPIC = "aintinksmart/service/request/send_image"
DEFAULT_STATUS_TOPIC = "aintinksmart/service/status/default" # Default status topic
DEFAULT_MODE = "bwr"
DEFAULT_TIMEOUT = 60 # Default seconds to wait for status/response

# --- Global Variables ---
response_received = None
response_lock = threading.Lock()
stop_event = threading.Event()

# --- MQTT Callbacks ---
# Add properties argument for CallbackAPIVersion.VERSION2
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("CLI: Connected to MQTT Broker!")
        # Subscribe to response topic if provided
        # Always subscribe to default status topic
        default_status_topic = userdata['default_status_topic']
        subscriptions = [(default_status_topic, 0)]
        print(f"CLI: Subscribed to default status topic {default_status_topic}")

        # Subscribe to specific response topic if provided
        response_topic = userdata.get('response_topic')
        if response_topic:
            subscriptions.append((response_topic, 1)) # Use QoS 1 for specific response
            print(f"CLI: Subscribed to response topic {response_topic}")

        client.subscribe(subscriptions)

        # Publish the request
        request_topic = userdata['request_topic']
        payload = userdata['payload']
        print(f"CLI: Publishing image request to {request_topic}")
        client.publish(request_topic, payload=payload, qos=1)

        # If not waiting for response, disconnect shortly after publish
        # Don't stop immediately even if no response topic, wait for default status / timeout
        # if not userdata.get('response_topic'):
        #      print("CLI: Request published. No response topic specified.")
        #      # Give a moment for publish to complete?
        #      time.sleep(0.5)
        #      stop_event.set()

    else:
        print(f"CLI: Failed to connect, return code {rc}")
        stop_event.set()

def on_message(client, userdata, msg):
    global response_received
    # Removed verbose "Received message" log
    try:
        payload_data = json.loads(msg.payload.decode())
        target_mac = userdata['target_mac'] # Get target MAC for filtering default status
        default_status_topic = userdata['default_status_topic']
        response_topic = userdata.get('response_topic')

        # Handle specific response
        if response_topic and msg.topic == response_topic:
            # Process final response/status
            status = payload_data.get('status', '')
            print(f"Status ({target_mac}): {status} (Final Response)") # Indicate it's the final response
            with response_lock:
                response_received = payload_data
            # Stop if the status indicates completion
            if status == 'success' or status.startswith('error'):
                stop_event.set()
        # Handle default status updates
        elif msg.topic == default_status_topic:
            # Check if the status update is for our target MAC
            if payload_data.get("mac_address") == target_mac:
                 status = payload_data.get('status', 'N/A')
                 print(f"Status ({target_mac}): {status}")
                 # Check if this status is final and store/stop if needed
                 if status == 'success' or status.startswith('error'):
                      print(f"Status ({target_mac}): Final status received on default topic.")
                      with response_lock:
                           response_received = payload_data # Store it
                      stop_event.set() # Stop on final status
            # else: # Ignore status updates for other MACs (can be verbose)
                 # logger.debug(f"Ignoring status for other MAC: {payload_data.get('mac_address')}")
        else:
             print(f"CLI: Received message on unexpected topic: {msg.topic}")

    except json.JSONDecodeError:
        print(f"CLI: Received non-JSON message on {msg.topic}: {msg.payload.decode()}")
    except Exception as e:
        print(f"CLI: Error processing message on {msg.topic}: {e}")

# Update signature for CallbackAPIVersion.VERSION2
# Correct signature for CallbackAPIVersion.VERSION2
def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    print("CLI: Disconnected from MQTT Broker.")
    stop_event.set() # Ensure exit if disconnected unexpectedly

# --- Main Script ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send an image to the BLE E-Ink service via MQTT.")
    parser.add_argument("--broker", default=DEFAULT_BROKER, help=f"MQTT broker address (default: {DEFAULT_BROKER})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"MQTT broker port (default: {DEFAULT_PORT})")
    parser.add_argument("--user", default=None, help="MQTT username")
    parser.add_argument("--pass", default=None, help="MQTT password", dest='password')
    parser.add_argument("--request-topic", default=DEFAULT_REQUEST_TOPIC, help=f"MQTT topic to send image request (default: {DEFAULT_REQUEST_TOPIC})")
    parser.add_argument("--response-topic", default=None, help="MQTT topic to listen for the final response (optional)")
    parser.add_argument("--default-status-topic", default=DEFAULT_STATUS_TOPIC, help=f"MQTT topic for intermediate status updates (default: {DEFAULT_STATUS_TOPIC})")
    parser.add_argument("--mac", required=True, help="Target device MAC address (XX:XX:XX:XX:XX:XX)")
    parser.add_argument("--image", required=True, help="Path to the image file")
    parser.add_argument("--mode", choices=['bwr', 'bw'], default=DEFAULT_MODE, help=f"Image color mode (default: {DEFAULT_MODE})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"Seconds to wait for status/response (default: {DEFAULT_TIMEOUT})")

    args = parser.parse_args()

    # Read and encode image
    try:
        with open(args.image, "rb") as f:
            image_bytes = f.read()
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
    except FileNotFoundError:
        print(f"Error: Image file not found at {args.image}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading image file: {e}")
        sys.exit(1)

    # Construct payload
    payload_dict = {
        "mac_address": args.mac,
        "image_data": image_b64,
        "mode": args.mode,
    }
    if args.response_topic:
        payload_dict["response_topic"] = args.response_topic

    payload_json = json.dumps(payload_dict)

    userdata = {
        'request_topic': args.request_topic,
        'response_topic': args.response_topic,
        'default_status_topic': args.default_status_topic,
        'target_mac': args.mac.upper(), # Store target MAC for filtering
        'payload': payload_json
    }

    # Use latest Callback API version to avoid DeprecationWarning
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata=userdata)
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

    # Wait for timeout, or until stop_event is set (by response on response_topic or disconnect or final status on default)
    print(f"CLI: Waiting up to {args.timeout} seconds for status updates/response...")
    stop_event.wait(timeout=args.timeout)

    client.loop_stop()
    client.disconnect()

    print("\n--- Result ---")
    # Check if a final response/status was received
    with response_lock:
        if response_received:
            # Print a simpler final message instead of the full JSON
            final_status = response_received.get("status", "unknown")
            final_message = response_received.get("message", "")
            print(f"Final Result: {final_status.upper()}")
            if final_message:
                print(f"Message: {final_message}")
            # Optionally exit with success/error code based on status
            if response_received.get("status") == "success":
                 sys.exit(0) # Success exit code
            else:
                 sys.exit(1) # Error exit code
        else:
            print("No final status/response received within timeout.")
            sys.exit(1) # Error exit code on timeout
    print("--------------")