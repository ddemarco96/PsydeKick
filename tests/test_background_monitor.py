# tests/test_background_monitor.py
import unittest
from unittest.mock import patch, MagicMock, call, mock_open
from datetime import datetime, timedelta
from pathlib import Path
import pytz
import json

# Mock streamlit before importing the module
import sys

sys.modules['streamlit'] = MagicMock()

from utils.background_monitor import (
    init_background_monitor,
    extend_auto_quit_timer,
    get_quit_time,
    get_time_until_auto_quit,
    render_auto_quit_status,
    render_auto_delete_buttons,
    render_auto_quit_buttons,
    render_settings,
    _check_deadlines_from_file,
    _write_state_to_file,
    data_exist_anywhere
)


class TestBackgroundMonitor(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.mock_session_state = {}
        self.base_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=pytz.utc)
        self.data_root = Path("/test/data")

        # Reset mocks
        sys.modules['streamlit'].reset_mock()

    def tearDown(self):
        """Clean up after each test method."""
        self.mock_session_state.clear()

    @patch('utils.background_monitor.st')
    @patch('utils.background_monitor.datetime')
    @patch('utils.background_monitor.start_background_thread')
    @patch('utils.background_monitor._write_state_to_file')
    def test_init_background_monitor_first_time(self, mock_write_state, mock_start_thread, mock_datetime, mock_st):
        """Test initialization when session state is empty."""
        mock_datetime.now.return_value = self.base_time
        mock_st.session_state = self.mock_session_state

        init_background_monitor()

        # Check auto-delete settings
        self.assertEqual(self.mock_session_state["auto_delete_minutes"], 30)
        self.assertIsNone(self.mock_session_state["delete_deadline"])

        # Check auto-quit settings (now in minutes)
        self.assertEqual(self.mock_session_state["app_start_time"], self.base_time)
        self.assertTrue(self.mock_session_state["auto_quit_enabled"])
        self.assertEqual(self.mock_session_state["auto_quit_minutes"], 720)  # 12 hours = 720 minutes

        mock_start_thread.assert_called_once()
        mock_write_state.assert_called_once()

    @patch('utils.background_monitor.st')
    def test_init_background_monitor_already_initialized(self, mock_st):
        """Test initialization when session state already has values."""
        existing_time = self.base_time - timedelta(hours=2)
        self.mock_session_state.update({
            "auto_delete_minutes": 60,
            "delete_deadline": None,
            "app_start_time": existing_time,
            "auto_quit_enabled": False,
            "auto_quit_minutes": 480  # 8 hours
        })
        mock_st.session_state = self.mock_session_state

        with patch('utils.background_monitor.start_background_thread'), \
                patch('utils.background_monitor._write_state_to_file'):
            init_background_monitor()

        # Should not overwrite existing values
        self.assertEqual(self.mock_session_state["auto_delete_minutes"], 60)
        self.assertEqual(self.mock_session_state["app_start_time"], existing_time)
        self.assertFalse(self.mock_session_state["auto_quit_enabled"])
        self.assertEqual(self.mock_session_state["auto_quit_minutes"], 480)

    @patch('utils.background_monitor.st')
    @patch('utils.background_monitor.datetime')
    @patch('utils.background_monitor._write_state_to_file')
    def test_extend_auto_quit_timer(self, mock_write_state, mock_datetime, mock_st):
        """Test extending auto-quit timer resets start time."""
        old_start_time = self.base_time - timedelta(hours=5)
        self.mock_session_state["app_start_time"] = old_start_time
        mock_st.session_state = self.mock_session_state
        mock_datetime.now.return_value = self.base_time

        extend_auto_quit_timer()

        self.assertEqual(self.mock_session_state["app_start_time"], self.base_time)
        mock_write_state.assert_called_once()

    @patch('utils.background_monitor.st')
    def test_get_quit_time_default_timeout(self, mock_st):
        """Test calculating quit time with default timeout."""
        start_time = self.base_time
        self.mock_session_state.update({
            "app_start_time": start_time,
            "auto_quit_minutes": 720  # 12 hours
        })
        mock_st.session_state = self.mock_session_state

        result = get_quit_time()

        expected = start_time + timedelta(minutes=720)
        self.assertEqual(result, expected)

    @patch('utils.background_monitor.st')
    def test_get_quit_time_custom_timeout(self, mock_st):
        """Test calculating quit time with custom timeout."""
        start_time = self.base_time
        self.mock_session_state.update({
            "app_start_time": start_time,
            "auto_quit_minutes": 480  # 8 hours
        })
        mock_st.session_state = self.mock_session_state

        result = get_quit_time()

        expected = start_time + timedelta(minutes=480)
        self.assertEqual(result, expected)

    @patch('utils.background_monitor.st')
    @patch('utils.background_monitor.datetime')
    def test_get_time_until_auto_quit_with_time_remaining(self, mock_datetime, mock_st):
        """Test calculating time remaining when there's time left."""
        start_time = self.base_time - timedelta(minutes=480)  # 8 hours ago
        self.mock_session_state.update({
            "app_start_time": start_time,
            "auto_quit_minutes": 720  # 12 hours total
        })
        mock_st.session_state = self.mock_session_state
        mock_datetime.now.return_value = self.base_time

        result = get_time_until_auto_quit()

        expected = timedelta(minutes=240)  # 720 - 480 = 240 minutes remaining
        self.assertEqual(result, expected)

    @patch('utils.background_monitor.st')
    @patch('utils.background_monitor.datetime')
    def test_get_time_until_auto_quit_overdue(self, mock_datetime, mock_st):
        """Test calculating time remaining when already overdue."""
        start_time = self.base_time - timedelta(minutes=900)  # 15 hours ago
        self.mock_session_state.update({
            "app_start_time": start_time,
            "auto_quit_minutes": 720  # 12 hours
        })
        mock_st.session_state = self.mock_session_state
        mock_datetime.now.return_value = self.base_time

        result = get_time_until_auto_quit()

        expected = timedelta(minutes=-180)  # Negative means overdue
        self.assertEqual(result, expected)

    @patch('utils.background_monitor.os.kill')
    @patch('utils.background_monitor.shutil.rmtree')
    @patch('utils.background_monitor.os.getpid')
    @patch('utils.background_monitor.datetime')
    def test_check_deadlines_from_file_auto_quit_timeout(self, mock_datetime, mock_getpid, mock_rmtree, mock_kill):
        """Test auto-quit execution from background thread."""
        mock_getpid.return_value = 12345

        # Set up the current time properly
        current_time = self.base_time
        mock_datetime.now.return_value = current_time

        # Create state data for an overdue app (started 800 minutes ago, should quit after 720)
        start_time = current_time - timedelta(minutes=800)
        state_data = {
            "auto_quit_enabled": True,
            "auto_quit_minutes": 720,  # Should quit after 720 minutes
            "app_start_time": start_time.isoformat()  # Use real datetime's isoformat()
        }

        # Mock the fromisoformat to return the actual start_time
        mock_datetime.fromisoformat.return_value = start_time

        with patch('builtins.open', mock_open(read_data=json.dumps(state_data))), \
                patch('utils.background_monitor._get_internal_dir') as mock_get_dir:
            # Mock the path operations
            mock_state_file = MagicMock()
            mock_state_file.exists.return_value = True
            mock_get_dir.return_value.__truediv__.return_value = mock_state_file

            _check_deadlines_from_file()

        # Should kill the process
        mock_kill.assert_called_once_with(12345, unittest.mock.ANY)

    @patch('utils.background_monitor.st')
    @patch('utils.background_monitor.get_time_until_auto_quit')
    @patch('utils.background_monitor.get_quit_time')
    def test_render_auto_quit_status_with_time_remaining(self, mock_get_quit_time, mock_get_time, mock_st):
        """Test auto-quit status UI with time remaining."""
        self.mock_session_state["auto_quit_enabled"] = True
        mock_st.session_state = self.mock_session_state
        mock_get_time.return_value = timedelta(minutes=270)  # 4.5 hours remaining

        # Mock quit time in UTC
        quit_time_utc = datetime(2025, 1, 2, 0, 0, 0, tzinfo=pytz.utc)
        mock_get_quit_time.return_value = quit_time_utc

        render_auto_quit_status()

        # Should render with Eastern Time conversion - note the <br> instead of separate <p>
        expected_html = (
            "<div class='auto-quit-status '>"
            "<p><b>App will quit at:</b></p>"
            "Jan 01, 2025 07:00:00 PM (ET)"
            "</div>"
        )
        mock_st.sidebar.markdown.assert_called_once_with(expected_html, unsafe_allow_html=True)

    @patch('utils.background_monitor.st')
    @patch('utils.background_monitor.get_time_until_auto_quit')
    @patch('utils.background_monitor.get_quit_time')
    def test_render_auto_quit_status_warning_threshold(self, mock_get_quit_time, mock_get_time, mock_st):
        """Test auto-quit status UI with warning when less than 1 hour remaining."""
        self.mock_session_state["auto_quit_enabled"] = True
        mock_st.session_state = self.mock_session_state
        mock_get_time.return_value = timedelta(minutes=45)  # 45 minutes remaining

        quit_time_utc = datetime(2025, 1, 1, 13, 0, 0, tzinfo=pytz.utc)
        mock_get_quit_time.return_value = quit_time_utc

        render_auto_quit_status()

        # Should render warning status
        expected_html = (
            "<div class='auto-quit-status auto-quit-warning'>"
            "<p><b>App will quit at:</b></p>"
            "Jan 01, 2025 08:00:00 AM (ET)"
            "</div>"
        )
        mock_st.sidebar.markdown.assert_called_once_with(expected_html, unsafe_allow_html=True)

    @patch('utils.background_monitor.st')
    @patch('utils.background_monitor.get_time_until_auto_quit')
    @patch('utils.background_monitor.data_exist_anywhere')
    def test_render_control_buttons_hours_display(self, mock_data_exist, mock_get_time, mock_st):
        """Test control buttons show hours when minutes >= 60."""
        self.mock_session_state.update({
            "auto_quit_enabled": True,
            "auto_quit_minutes": 720  # 12 hours
        })
        mock_st.session_state = self.mock_session_state
        mock_get_time.return_value = timedelta(minutes=300)  # Time remaining
        mock_data_exist.return_value = False  # No data exists

        # Mock button returns False (not clicked)
        mock_st.button.return_value = False
        mock_st.sidebar.columns.return_value = [MagicMock(), MagicMock()]

        render_auto_quit_buttons(self.data_root)

        # Check that button text shows hours
        button_calls = mock_st.button.call_args_list
        extend_button_call = next(call for call in button_calls if "Add" in str(call))
        self.assertIn("Add 12h", str(extend_button_call))

    @patch('utils.background_monitor.st')
    @patch('utils.background_monitor.update_auto_quit_settings')
    @patch('utils.background_monitor._write_state_to_file')
    def test_render_settings_enable_disable(self, mock_write_state, mock_update_settings, mock_st):
        """Test enabling/disabling auto-quit in settings."""
        self.mock_session_state = {
            "auto_quit_enabled": True,
            "auto_delete_minutes": 30,  # Add this required key
            "auto_quit_minutes": 720
        }
        mock_st.session_state = self.mock_session_state
        mock_st.checkbox.return_value = False  # User unchecks the auto-quit box

        # Mock number_input to return different values for different calls
        # First call is for auto-quit minutes, second is for auto-delete minutes
        mock_st.number_input.side_effect = [720, 30]  # auto-quit: 720, auto-delete: 30 (no change)

        render_settings()

        # Should update session state and call update function
        self.assertFalse(self.mock_session_state["auto_quit_enabled"])
        mock_update_settings.assert_called_once()

        # Check that the success message for auto-quit disable was called
        # The function might call success multiple times, so check all calls
        success_calls = [call[0][0] for call in mock_st.success.call_args_list]
        self.assertIn("Auto-quit disabled.", success_calls)
        mock_st.rerun.assert_called()

    @patch('utils.background_monitor.st')
    @patch('utils.background_monitor.json.dump')
    @patch('builtins.open', new_callable=mock_open)
    @patch('utils.background_monitor._get_internal_dir')
    def test_write_state_to_file(self, mock_get_dir, mock_file, mock_json_dump, mock_st):
        """Test writing session state to file."""
        self.mock_session_state.update({
            "auto_delete_minutes": 30,
            "delete_deadline": None,
            "app_start_time": self.base_time,
            "auto_quit_enabled": True,
            "auto_quit_minutes": 720
        })
        mock_st.session_state = self.mock_session_state

        # Mock Path operations
        mock_internal_dir = MagicMock()
        mock_get_dir.return_value = mock_internal_dir
        mock_internal_dir.__truediv__.return_value = mock_internal_dir  # For path / operations

        _write_state_to_file()

        # Verify directory creation and file writing
        mock_internal_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_file.assert_called_once()

        # Verify the data passed to json.dump
        json_dump_call = mock_json_dump.call_args
        state_data = json_dump_call[0][0]  # First argument to json.dump

        self.assertEqual(state_data["auto_quit_minutes"], 720)
        self.assertEqual(state_data["auto_quit_enabled"], True)
        self.assertEqual(state_data["app_start_time"], self.base_time.isoformat())

    def test_data_exist_anywhere_ignores_internal_files(self):
        """Test that data_exist_anywhere ignores .internal directory files."""
        # Mock data directory with CSV files in different locations
        data_root = MagicMock()

        # Mock CSV files - one in .internal (should be ignored), one outside (should be detected)
        csv_files = [
            MagicMock(parts=("data", ".internal", "monitor_state.csv")),  # Should be ignored
            MagicMock(parts=("data", "Study1", "sessions.csv"))  # Should be detected
        ]

        data_root.exists.return_value = True
        data_root.rglob.return_value = csv_files

        result = data_exist_anywhere(data_root)

        self.assertTrue(result)  # Should return True because of sessions.csv

    def test_data_exist_anywhere_only_internal_files(self):
        """Test that data_exist_anywhere returns False when only .internal files exist."""
        data_root = MagicMock()

        # Mock only .internal CSV files
        csv_files = [
            MagicMock(parts=("data", ".internal", "monitor_state.csv")),
            MagicMock(parts=("data", ".internal", "some_other.csv"))
        ]

        data_root.exists.return_value = True
        data_root.rglob.return_value = csv_files

        result = data_exist_anywhere(data_root)

        self.assertFalse(result)  # Should return False since only .internal files exist

    @patch('utils.background_monitor.st')
    @patch('utils.background_monitor.update_auto_quit_settings')
    @patch('utils.background_monitor._write_state_to_file')
    def test_render_settings_change_timeout(self, mock_write_state, mock_update_settings, mock_st):
        """Test changing timeout value in settings."""
        self.mock_session_state = {
            "auto_quit_enabled": True,
            "auto_quit_minutes": 720,
            "auto_delete_minutes": 30
        }
        mock_st.session_state = self.mock_session_state
        mock_st.checkbox.return_value = True  # Keep auto-quit enabled

        # Mock number_input: auto-quit changes from 720 to 480, auto-delete stays 30
        mock_st.number_input.side_effect = [480, 30]

        render_settings()

        # Should update timeout and show success message
        self.assertEqual(self.mock_session_state["auto_quit_minutes"], 480)
        mock_update_settings.assert_called_once()

        # Check for the timeout change success message
        success_calls = [call[0][0] for call in mock_st.success.call_args_list]
        self.assertIn("Auto-quit timeout set to 480 minutes (8 hours).", success_calls)
        mock_st.rerun.assert_called()


class TestBackgroundMonitorIntegration(unittest.TestCase):
    """Integration tests for background monitor functionality."""

    @patch('utils.background_monitor.st')
    @patch('utils.background_monitor.datetime')
    @patch('utils.background_monitor.start_background_thread')
    @patch('utils.background_monitor._write_state_to_file')
    def test_full_initialization_and_calculation_flow(self, mock_write_state, mock_start_thread,
                                                      mock_datetime, mock_st):
        """Test the complete flow from initialization to quit time calculation."""
        base_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=pytz.utc)
        session_state = {}

        # Step 1: Initialize
        mock_st.session_state = session_state
        mock_datetime.now.return_value = base_time
        init_background_monitor()

        # Verify initialization with minutes
        self.assertEqual(session_state["app_start_time"], base_time)
        self.assertTrue(session_state["auto_quit_enabled"])
        self.assertEqual(session_state["auto_quit_minutes"], 720)  # 12 hours in minutes

        # Step 2: Calculate quit time
        quit_time = get_quit_time()
        expected_quit_time = base_time + timedelta(minutes=720)
        self.assertEqual(quit_time, expected_quit_time)

        # Step 3: Test extension
        mock_datetime.now.return_value = base_time + timedelta(minutes=600)  # 10 hours later
        extend_auto_quit_timer()

        # New quit time should be 720 minutes from the extension time
        new_quit_time = get_quit_time()
        expected_new_quit_time = (base_time + timedelta(minutes=600)) + timedelta(minutes=720)
        self.assertEqual(new_quit_time, expected_new_quit_time)


if __name__ == '__main__':
    unittest.main()