document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('upload-form');
    const imageInput = document.getElementById('image-file');
    const macInput = document.getElementById('mac-address');
    const modeSelect = document.getElementById('mode');
    const statusMessage = document.getElementById('status-message');
    const submitButton = document.getElementById('submit-button');
    const discoverButton = document.getElementById('discover-button');
    const discoverResultsDiv = document.getElementById('discover-results');
    const discoveredDevicesSelect = document.getElementById('discovered-devices');

    // --- Send Image Form Submission ---
    form.addEventListener('submit', async (event) => {
        event.preventDefault(); // Prevent default form submission

        const file = imageInput.files[0];
        const macAddress = macInput.value;
        const mode = modeSelect.value;

        if (!file) {
            setStatus('Please select an image file.', 'error');
            return;
        }
        if (!macAddress) {
            setStatus('Please enter or select a MAC address.', 'error');
            return;
        }
        if (!/^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$/.test(macAddress)) {
             setStatus('Invalid MAC address format (use XX:XX:XX:XX:XX:XX).', 'error');
             return;
        }

        setStatus('Processing and sending image...', 'info');
        submitButton.disabled = true;
        discoverButton.disabled = true; // Disable discovery during send

        try {
            const formData = new FormData();
            formData.append('image_file', file);
            formData.append('mac_address', macAddress);
            formData.append('mode', mode);

            const response = await fetch('/send_image', {
                method: 'POST',
                body: formData,
            });

            const result = await response.json();

            if (response.ok && result.status === 'success') {
                setStatus(`Success: ${result.message}`, 'success');
            } else {
                const errorMessage = result.detail || result.message || 'An unknown error occurred.';
                setStatus(`Error: ${errorMessage}`, 'error');
                console.error('API Error:', result);
            }

        } catch (error) {
            console.error('Fetch Error:', error);
            setStatus(`Network or client-side error: ${error.message}`, 'error');
        } finally {
            submitButton.disabled = false;
            discoverButton.disabled = false; // Re-enable discovery
        }
    });

    // --- Device Discovery ---
    discoverButton.addEventListener('click', async () => {
        // Determine potential scan time (longer if MQTT might be used)
        // We don't know for sure if MQTT *will* be used, but we can guess based on config if needed
        // For simplicity, just use a longer message if MQTT *could* be enabled server-side.
        // A better approach might involve the backend telling the frontend the expected duration.
        const potentialScanTime = 18; // Matches the backend wait time
        setStatus(`Scanning for devices (up to ${potentialScanTime}s)...`, 'info');
        discoverButton.disabled = true;
        discoverButton.textContent = 'Scanning...'; // Update button text
        discoveredDevicesSelect.innerHTML = '<option value="">-- Scanning... --</option>'; // Clear previous options
        discoverResultsDiv.style.display = 'block'; // Show the dropdown area

        try {
            const response = await fetch('/discover_devices');
            if (!response.ok) {
                // Try to get error details from response body if possible
                let errorDetail = `HTTP error ${response.status}`;
                try {
                    const errorJson = await response.json();
                    errorDetail = errorJson.detail || errorJson.message || errorDetail;
                } catch (e) { /* Ignore if response is not JSON */ }
                throw new Error(errorDetail);
            }

            const devices = await response.json();

            discoveredDevicesSelect.innerHTML = ''; // Clear "Scanning..."

            if (devices.length > 0) {
                setStatus('Discovery complete. Select a device.', 'info');
                // Add a default placeholder option
                const defaultOption = document.createElement('option');
                defaultOption.value = "";
                defaultOption.textContent = "-- Select a device --";
                discoveredDevicesSelect.appendChild(defaultOption);

                // Populate dropdown
                devices.forEach(device => {
                    const option = document.createElement('option');
                    option.value = device.address;
                    option.textContent = `${device.name} (${device.address})`;
                    discoveredDevicesSelect.appendChild(option);
                });
            } else {
                setStatus('No "easyTag" devices found nearby.', 'info');
                 const noDeviceOption = document.createElement('option');
                 noDeviceOption.value = "";
                 noDeviceOption.textContent = "-- No devices found --";
                 discoveredDevicesSelect.appendChild(noDeviceOption);
            }

        } catch (error) {
            console.error('Discovery Error:', error);
            setStatus(`Discovery failed: ${error.message}`, 'error');
            discoveredDevicesSelect.innerHTML = '<option value="">-- Error --</option>';
        } finally {
            discoverButton.disabled = false; // Re-enable button
            discoverButton.textContent = 'Discover'; // Restore button text
        }
    });

    // --- Update MAC Input when Device is Selected ---
    discoveredDevicesSelect.addEventListener('change', (event) => {
        const selectedMac = event.target.value;
        if (selectedMac) {
            macInput.value = selectedMac;
            // Optional: Trigger validation styling if needed
            macInput.dispatchEvent(new Event('input'));
        }
    });


    // --- Helper to Set Status Messages ---
    function setStatus(message, type) {
        statusMessage.textContent = message;
        statusMessage.className = ''; // Clear previous classes
        statusMessage.classList.add(type); // Add 'success', 'error', or 'info'
        statusMessage.style.display = 'block'; // Make sure it's visible
    }
});