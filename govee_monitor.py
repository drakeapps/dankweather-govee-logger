import os
import time
import glob
import re
import json
import requests
import threading
from datetime import datetime

# --- Configuration ---
LOG_DIR = "/var/log/goveebttemplogger/"
API_URL = "https://api.dankweather.com/log"
USERNAME = "admin"  # Set your default username here or leave empty
CHECK_INTERVAL = 1.0  # How often to check for new lines (seconds)
SCAN_INTERVAL = 60.0  # How often to check for NEW sensors (seconds)

# --- API Sender ---
def send_to_api(sensor_id, line):
    """Parses the log line and sends it to the API."""
    try:
        # Split by whitespace (handles both tabs and spaces robustly)
        # Structure: Date Time Temp Humidity Battery
        parts = line.strip().split()
        
        if len(parts) < 5:
            return # Skip malformed lines

        date_str = parts[0]
        time_str = parts[1]
        temperature = parts[2]
        humidity = parts[3]
        battery = parts[4]

        payload = {
            "id": sensor_id,
            "user": USERNAME,
            "datetime": f"{date_str} {time_str}",
            "temperature": temperature,
            "humidity": humidity,
            "battery": battery
        }

        # Send request with timeout
        response = requests.post(
            API_URL, 
            json=payload, 
            timeout=5,
            headers={"Content-Type": "application/json"}
        )
        
        # Check for HTTP errors
        if response.status_code != 200:
            print(f"[!] Error sending {sensor_id}: {response.status_code} - {response.text}")
        else:
            print(f"[+] Sent {sensor_id}: {payload['datetime']}")

    except Exception as e:
        print(f"[!] Exception sending data for {sensor_id}: {e}")

# --- File Follower Logic ---
def get_current_filename(sensor_id):
    """Generates the filename expected for the current month."""
    now = datetime.utcnow()
    # Template: gvh-{SENSOR_ID}-{YYYY}-{MM}.txt
    return os.path.join(LOG_DIR, f"gvh-{sensor_id}-{now.year}-{now.month:02d}.txt")

def monitor_sensor(sensor_id):
    """
    Thread worker that tails the log file for a specific sensor.
    Handles month rollover automatically.
    """
    print(f"[*] Started monitoring thread for: {sensor_id}")
    
    current_file_path = get_current_filename(sensor_id)
    current_file = None

    while True:
        # 1. Ensure file is open
        if current_file is None:
            if os.path.exists(current_file_path):
                try:
                    current_file = open(current_file_path, 'r')
                    # Seek to end (Tail behavior - only new data)
                    current_file.seek(0, 2) 
                    print(f"[*] Tailing: {current_file_path}")
                except Exception as e:
                    print(f"[!] Error opening {current_file_path}: {e}")
                    time.sleep(5)
                    continue
            else:
                # File doesn't exist yet (maybe new month just started and no logs yet)
                time.sleep(10)
                # Re-check what the current file SHOULD be (in case month changed while waiting)
                current_file_path = get_current_filename(sensor_id)
                continue

        # 2. Read new lines
        line = current_file.readline()
        if line:
            send_to_api(sensor_id, line)
            continue # Try to read another line immediately

        # 3. No new lines? Check if we need to rotate files (Month Rollover)
        expected_file_path = get_current_filename(sensor_id)
        
        if expected_file_path != current_file_path:
            # The month has changed. 
            # Check if the NEW file actually exists before switching.
            if os.path.exists(expected_file_path):
                print(f"[*] Rollover detected. Switching from {current_file_path} to {expected_file_path}")
                current_file.close()
                current_file = None
                current_file_path = expected_file_path
                continue

        # 4. Sleep briefly to reduce CPU usage
        time.sleep(CHECK_INTERVAL)

# --- Main Discovery Loop ---
def main():
    print("--- Govee Log Monitor Started ---")
    monitored_sensors = set()

    while True:
        # Find all files matching the pattern to discover Sensor IDs
        # Pattern: gvh-{ID}-{YYYY}-{MM}.txt
        files = glob.glob(os.path.join(LOG_DIR, "gvh-*.txt"))
        
        for filepath in files:
            filename = os.path.basename(filepath)
            # Regex to extract Sensor ID (assumes ID is between 'gvh-' and the date)
            match = re.match(r"gvh-(.+)-\d{4}-\d{2}\.txt", filename)
            
            if match:
                sensor_id = match.group(1)
                
                if sensor_id not in monitored_sensors:
                    # Found a new sensor! Start a thread for it.
                    monitored_sensors.add(sensor_id)
                    t = threading.Thread(target=monitor_sensor, args=(sensor_id,), daemon=True)
                    t.start()
        
        # Scan for new sensors occasionally
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    # Ensure requests is installed: pip install requests
    main()



