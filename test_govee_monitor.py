import unittest
from unittest.mock import MagicMock, patch, mock_open
import os
import threading
import time
from datetime import datetime
from govee_monitor import GoveeMonitor


class TestGoveeMonitor(unittest.TestCase):

    def setUp(self):
        self.log_dir = "/tmp/logs"
        self.api_url = "http://test.com/api"
        self.monitor = GoveeMonitor(self.log_dir, self.api_url)
        # Ensure intervals are small, though we will mock sleep anyway
        self.monitor.check_interval = 0.01
        self.monitor.scan_interval = 0.01
        self.monitor.retry_interval = 0.01

    def test_parse_line_valid(self):
        line = "2023-10-27 10:00:00 22.5 45 88"
        result = self.monitor.parse_line(line)
        self.assertEqual(result["date"], "2023-10-27")
        self.assertEqual(result["temperature"], "22.5")

    def test_parse_line_invalid(self):
        line = "2023-10-27 10:00:00"  # Too short
        result = self.monitor.parse_line(line)
        self.assertIsNone(result)

    def test_get_log_filename(self):
        mock_date = datetime(2023, 5, 15)
        filename = self.monitor.get_log_filename("A1", now=mock_date)
        expected = os.path.join(self.log_dir, "gvh-A1-2023-05.txt")
        self.assertEqual(filename, expected)
        self.assertTrue(self.monitor.get_log_filename("A1").startswith(self.log_dir))

    @patch("requests.post")
    def test_send_record_success(self, mock_post):
        mock_post.return_value.status_code = 200
        record = {
            "date": "2023-01-01",
            "time": "12:00",
            "temperature": "20",
            "humidity": "50",
            "battery": "100",
        }
        success = self.monitor.send_record("SENS1", record)
        self.assertTrue(success)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["id"], "SENS1")

    @patch("requests.post")
    def test_send_record_api_error(self, mock_post):
        mock_post.return_value.status_code = 500
        mock_post.return_value.text = "Server Error"
        record = {
            "date": "2023-01-01",
            "time": "12:00",
            "temperature": "20",
            "humidity": "50",
            "battery": "100",
        }
        success = self.monitor.send_record("SENS1", record)
        self.assertFalse(success)

    @patch("requests.post")
    def test_send_record_exception(self, mock_post):
        mock_post.side_effect = Exception("Connection error")
        record = {
            "date": "2023-01-01",
            "time": "12:00",
            "temperature": "20",
            "humidity": "50",
            "battery": "100",
        }
        success = self.monitor.send_record("SENS1", record)
        self.assertFalse(success)

    @patch("glob.glob")
    def test_scan_sensors(self, mock_glob):
        mock_glob.return_value = [
            "/tmp/logs/gvh-A111-2023-10.txt",
            "/tmp/logs/gvh-B222-2023-10.txt",
            "/tmp/logs/readme.txt",
        ]
        new = self.monitor.scan_sensors()
        self.assertIn("A111", new)
        self.assertIn("B222", new)
        self.assertEqual(len(new), 2)

        self.monitor.monitored_sensors.update(new)
        new_again = self.monitor.scan_sensors()
        self.assertEqual(new_again, [])

    @patch("govee_monitor.time.sleep")
    @patch("govee_monitor.GoveeMonitor.scan_sensors")
    @patch("threading.Thread")
    def test_discovery_loop(self, mock_thread, mock_scan, mock_sleep):
        # 1. First call: returns "S1"
        # 2. Second call: we force the loop to stop by checking stop_event or raising exception?
        # A clean way is to make scan_sensors trigger the stop event after returning data.
        def side_effect():
            if not self.monitor.monitored_sensors:  # First run
                return ["S1"]
            else:
                self.monitor.stop()  # Stop the loop
                return []

        mock_scan.side_effect = side_effect

        # We don't need a separate thread because we've mocked sleep and the exit condition.
        # But discovery_loop catches KeyboardInterrupt? No, start() does.
        # We can just run it directly.
        self.monitor.discovery_loop()

        self.assertTrue(mock_thread.called)
        self.assertIn("S1", self.monitor.monitored_sensors)

    @patch("govee_monitor.time.sleep")
    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open)
    @patch("govee_monitor.GoveeMonitor.send_record")
    def test_monitor_loop_flow(self, mock_send, mock_file, mock_exists, mock_sleep):
        sensor_id = "TEST_SENS"
        mock_exists.return_value = True

        # Define lifecycle:
        # 1. Open file (success)
        # 2. Read line (success) -> send
        # 3. Read line (empty) -> loop -> sleep -> STOP

        handle = mock_file.return_value
        handle.readline.side_effect = ["2023-01-01 12:00 20 50 100\n", None]

        # When sleep is called (end of loop), we stop the loop to prevent infinite run
        def sleep_effect(seconds):
            self.monitor.stop()

        mock_sleep.side_effect = sleep_effect

        self.monitor.monitor_loop(sensor_id)

        mock_file.assert_called()
        mock_send.assert_called_once()

    @patch("govee_monitor.time.sleep")
    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open)
    def test_monitor_loop_file_not_found_initially(
        self, mock_file, mock_exists, mock_sleep
    ):
        """Test waiting for file to appear."""
        # 1. exists -> False (Missing) -> sleep (retry)
        # 2. exists -> True (Found) -> open -> sleep (end of loop) -> STOP
        mock_exists.side_effect = [False, True, True]

        # We use a counter to decide when to stop the loop via sleep side effect
        # Call 1: Retry sleep (do nothing)
        # Call 2: Loop interval sleep (Stop)

        call_count = 0

        def sleep_logic(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                self.monitor.stop()

        mock_sleep.side_effect = sleep_logic

        self.monitor.monitor_loop("S2")

        # Verify open was eventually called
        self.assertTrue(mock_file.called)

    @patch("govee_monitor.time.sleep")
    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open)
    def test_monitor_loop_open_exception(self, mock_file, mock_exists, mock_sleep):
        mock_exists.return_value = True
        mock_file.side_effect = PermissionError("Boom")

        # 1. Open -> Exception -> Sleep(retry) -> STOP
        mock_sleep.side_effect = lambda x: self.monitor.stop()

        self.monitor.monitor_loop("S3")

        self.assertTrue(mock_file.called)

    @patch("govee_monitor.time.sleep")
    @patch("govee_monitor.GoveeMonitor.get_log_filename")
    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open)
    def test_monitor_loop_rollover(
        self, mock_file, mock_exists, mock_get_filename, mock_sleep
    ):
        sensor_id = "ROLL"
        old_file = "/tmp/logs/gvh-ROLL-2023-01.txt"
        new_file = "/tmp/logs/gvh-ROLL-2023-02.txt"

        mock_get_filename.side_effect = [
            old_file,
            old_file,
            new_file,
            new_file,
            new_file,
        ]
        mock_exists.return_value = True

        # Stop after a few loops
        mock_sleep.side_effect = lambda x: (
            self.monitor.stop() if mock_file.return_value.close.called else None
        )

        # Safety break if logic fails
        loop_limit = 0
        original_sleep = mock_sleep.side_effect

        def safety_wrapper(x):
            nonlocal loop_limit
            loop_limit += 1
            if loop_limit > 5:
                self.monitor.stop()
            if original_sleep:
                original_sleep(x)

        mock_sleep.side_effect = safety_wrapper

        self.monitor.monitor_loop(sensor_id)

        self.assertTrue(mock_file.return_value.close.called)


if __name__ == "__main__":
    unittest.main()
