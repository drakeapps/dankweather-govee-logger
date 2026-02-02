#!/usr/bin/env python3

import os
import time
import glob
import re
import json
import requests
import threading
from datetime import datetime


class GoveeMonitor:
    def __init__(self, log_dir, api_url, username="admin"):
        self.log_dir = log_dir
        self.api_url = api_url
        self.username = username
        self.check_interval = 1.0  # Sleep at end of loop
        self.retry_interval = 1.0  # Sleep on error/missing file
        self.scan_interval = 60.0
        self.stop_event = threading.Event()
        self.monitored_sensors = set()

    def parse_line(self, line):
        """Parses a log line into a dictionary. Returns None if invalid."""
        parts = line.strip().split()
        if len(parts) < 5:
            return None

        return {
            "date": parts[0],
            "time": parts[1],
            "temperature": parts[2],
            "humidity": parts[3],
            "battery": parts[4],
        }

    def send_record(self, sensor_id, record):
        """Sends a parsed record to the API."""
        payload = {
            "id": sensor_id,
            "user": self.username,
            "datetime": f"{record['date']} {record['time']}",
            "temperature": record["temperature"],
            "humidity": record["humidity"],
            "battery": record["battery"],
        }

        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=5,
                headers={"Content-Type": "application/json"},
            )
            if response.status_code != 200:
                print(
                    f"[!] Error sending {sensor_id}: {response.status_code} - {response.text}"
                )
                return False
            else:
                print(f"[+] Sent {sensor_id}: {payload['datetime']}")
                return True
        except Exception as e:
            print(f"[!] Exception sending data for {sensor_id}: {e}")
            return False

    def get_log_filename(self, sensor_id, now=None):
        """Generates the expected filename. 'now' can be injected for testing."""
        if now is None:
            now = datetime.utcnow()
        return os.path.join(
            self.log_dir, f"gvh-{sensor_id}-{now.year}-{now.month:02d}.txt"
        )

    def monitor_loop(self, sensor_id):
        """Worker thread logic for a single sensor."""
        print(f"[*] Started monitoring thread for: {sensor_id}")

        current_file_path = self.get_log_filename(sensor_id)
        current_file = None

        while not self.stop_event.is_set():
            # 1. Ensure file is open
            if current_file is None:
                if os.path.exists(current_file_path):
                    try:
                        current_file = open(current_file_path, "r")
                        current_file.seek(0, 2)  # Tail
                        print(f"[*] Tailing: {current_file_path}")
                    except Exception as e:
                        print(f"[!] Error opening {current_file_path}: {e}")
                        time.sleep(self.retry_interval)
                        continue
                else:
                    time.sleep(self.retry_interval)
                    # Re-check filename in case of month rollover while waiting
                    current_file_path = self.get_log_filename(sensor_id)
                    continue

            # 2. Read new lines
            line = current_file.readline()
            if line:
                record = self.parse_line(line)
                if record:
                    self.send_record(sensor_id, record)
                continue

            # 3. Check for Rollover
            expected_file_path = self.get_log_filename(sensor_id)
            if expected_file_path != current_file_path:
                if os.path.exists(expected_file_path):
                    print(
                        f"[*] Rollover detected: {current_file_path} -> {expected_file_path}"
                    )
                    current_file.close()
                    current_file = None
                    current_file_path = expected_file_path
                    continue

            # 4. Sleep
            time.sleep(self.check_interval)

        # Cleanup on exit
        if current_file:
            current_file.close()

    def scan_sensors(self):
        """Scans the directory for sensor files and returns a list of new sensor IDs."""
        files = glob.glob(os.path.join(self.log_dir, "gvh-*.txt"))
        new_sensors = []

        for filepath in files:
            filename = os.path.basename(filepath)
            match = re.match(r"gvh-(.+)-\d{4}-\d{2}\.txt", filename)

            if match:
                sensor_id = match.group(1)
                if sensor_id not in self.monitored_sensors:
                    new_sensors.append(sensor_id)
        return new_sensors

    def discovery_loop(self):
        """Main loop that looks for new sensors."""
        print("--- Govee Log Monitor Started ---")
        while not self.stop_event.is_set():
            new_sensors = self.scan_sensors()
            for sensor_id in new_sensors:
                self.monitored_sensors.add(sensor_id)
                t = threading.Thread(
                    target=self.monitor_loop, args=(sensor_id,), daemon=True
                )
                t.start()

            time.sleep(self.scan_interval)

    def start(self):
        """Starts the discovery loop."""
        try:
            self.discovery_loop()
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        """Signals all threads to stop."""
        self.stop_event.set()


if __name__ == "__main__":
    config = {
        "log_dir": "/var/log/goveebttemplogger/",
        "api_url": "https://api.dankweather.com/log",
        "username": "admin",
    }

    monitor = GoveeMonitor(**config)
    monitor.start()
