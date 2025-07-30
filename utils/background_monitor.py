"""utils/background_monitor.py

Streamlit only runs code in the main thread based on user interaction. So, to handle background tasks like
auto-deletion and auto-quitting, especially when the tab is closed, we use a background process/thread.
"""
import os
import shutil
import signal
import time
import threading
import json
from datetime import datetime, timedelta
from pathlib import Path
import streamlit as st
import pytz

# Global thread management
_monitor_thread = None
_thread_lock = threading.Lock()
_stop_monitoring = threading.Event()


def init_background_monitor():
    """Initialize session state and start background monitoring thread."""
    # Auto-delete settings
    if "auto_delete_minutes" not in st.session_state:
        st.session_state["auto_delete_minutes"] = 30
    if "delete_deadline" not in st.session_state:
        st.session_state["delete_deadline"] = None

    # Auto-quit settings (now in minutes)
    if "app_start_time" not in st.session_state:
        st.session_state["app_start_time"] = datetime.now(pytz.utc)
    if "auto_quit_enabled" not in st.session_state:
        st.session_state["auto_quit_enabled"] = True
    if "auto_quit_minutes" not in st.session_state:
        st.session_state["auto_quit_minutes"] = 720  # 12 hours = 720 minutes

    # Start the background thread
    start_background_thread()

    # Write initial state to file for background thread
    _write_state_to_file()


def start_background_thread():
    """Start the background monitoring thread."""
    global _monitor_thread

    with _thread_lock:
        # Only start one thread
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _stop_monitoring.clear()
            _monitor_thread = threading.Thread(target=_monitoring_loop, daemon=True)
            _monitor_thread.start()


def _monitoring_loop():
    """Background monitoring loop - doesn't call any Streamlit commands."""
    while not _stop_monitoring.wait(30):  # Check every 30 seconds
        try:
            _check_deadlines_from_file()
        except Exception:
            # Continue monitoring even if there are errors
            continue


def _get_internal_dir():
    """Get the internal directory for monitoring files."""
    return Path("data") / ".internal"


def _check_deadlines_from_file():
    """Check deadlines by reading from file (no Streamlit commands)."""
    state_file = _get_internal_dir() / "monitor_state.json"
    if not state_file.exists():
        return

    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return

    now_utc = datetime.now(pytz.utc)
    data_root = Path("data")

    # Check auto-delete deadline
    if state.get("delete_deadline"):
        delete_deadline = datetime.fromisoformat(state["delete_deadline"])
        if now_utc >= delete_deadline:
            # Execute auto-delete
            if data_root.exists():
                shutil.rmtree(data_root, ignore_errors=True)
            _write_action_signal("auto_delete_executed")
            return  # Data directory deleted, state file is gone

    # Check auto-quit deadline
    if state.get("auto_quit_enabled", True):
        start_time = datetime.fromisoformat(state.get("app_start_time", now_utc.isoformat()))
        timeout_minutes = state.get("auto_quit_minutes", 720)

        time_running = now_utc - start_time
        timeout_duration = timedelta(minutes=timeout_minutes)

        if time_running >= timeout_duration:
            # Execute auto-quit
            if data_root.exists():
                shutil.rmtree(data_root, ignore_errors=True)

            # Kill the process directly
            os.kill(os.getpid(), signal.SIGKILL)


def _write_state_to_file():
    """Write current session state to file for background thread."""
    try:
        internal_dir = _get_internal_dir()
        internal_dir.mkdir(parents=True, exist_ok=True)

        state = {
            "auto_delete_minutes": st.session_state.get("auto_delete_minutes", 30),
            "delete_deadline": st.session_state.get("delete_deadline").isoformat() if st.session_state.get(
                "delete_deadline") else None,
            "app_start_time": st.session_state.get("app_start_time", datetime.now(pytz.utc)).isoformat(),
            "auto_quit_enabled": st.session_state.get("auto_quit_enabled", True),
            "auto_quit_minutes": st.session_state.get("auto_quit_minutes", 720),
            "last_updated": datetime.now(pytz.utc).isoformat()
        }

        state_file = internal_dir / "monitor_state.json"
        with open(state_file, 'w') as f:
            json.dump(state, f)

    except Exception:
        pass  # Ignore write errors


def _write_action_signal(action):
    """Write an action signal for the main thread to pick up."""
    try:
        internal_dir = _get_internal_dir()
        internal_dir.mkdir(parents=True, exist_ok=True)
        signal_file = internal_dir / "action_signal"
        signal_file.write_text(action)
    except Exception:
        pass


def check_and_handle_signals():
    """Check for signals from background thread and handle them."""
    signal_file = _get_internal_dir() / "action_signal"
    if signal_file.exists():
        try:
            action = signal_file.read_text().strip()
            signal_file.unlink()

            if action == "auto_delete_executed":
                st.session_state["delete_deadline"] = None
                st.toast("Data auto-deleted by background monitor.", icon="✅")
                st.rerun()

        except Exception:
            pass


def data_exist_anywhere(data_root: Path) -> bool:
    """Return True if **any** CSV exists under data_root (excluding internal monitoring files)."""
    if not data_root.exists():
        return False

    # Check for CSV files, but exclude the .internal directory
    for csv_file in data_root.rglob("*.csv"):
        # Skip files in the .internal directory
        if ".internal" not in csv_file.parts:
            return True

    return False


def manage_auto_delete_timer(data_root: Path):
    """Manage auto-delete timer setup."""
    now_utc = datetime.now(pytz.utc)
    have_csv_data = data_exist_anywhere(data_root)

    # Start the clock if CSV data exists and no deadline is set
    if have_csv_data and st.session_state.get("delete_deadline") is None:
        st.session_state["delete_deadline"] = now_utc + timedelta(
            minutes=st.session_state["auto_delete_minutes"]
        )
        _write_state_to_file()


def extend_auto_delete_timer():
    """Extend the auto-delete deadline."""
    st.session_state["delete_deadline"] = datetime.now(pytz.utc) + timedelta(
        minutes=st.session_state["auto_delete_minutes"]
    )
    _write_state_to_file()


def delete_data_now(data_root: Path):
    """Delete data immediately."""
    if data_root.exists():
        shutil.rmtree(data_root, ignore_errors=True)
    st.session_state["delete_deadline"] = None
    _write_state_to_file()


def extend_auto_quit_timer():
    """Reset the auto-quit timer."""
    st.session_state["app_start_time"] = datetime.now(pytz.utc)
    _write_state_to_file()


def update_auto_quit_settings():
    """Update auto-quit settings and sync to file."""
    _write_state_to_file()


def get_quit_time():
    """Get the datetime when the app will auto-quit."""
    start_time = st.session_state.get("app_start_time", datetime.now(pytz.utc))
    timeout_minutes = st.session_state.get("auto_quit_minutes", 720)
    return start_time + timedelta(minutes=timeout_minutes)


def get_time_until_auto_quit():
    """Get time remaining before auto-quit."""
    now_utc = datetime.now(pytz.utc)
    quit_time = get_quit_time()
    return quit_time - now_utc


def render_auto_delete_status():
    """Render auto-delete status display."""
    if st.session_state.get("delete_deadline") is not None:
        deadline_utc = st.session_state["delete_deadline"]
        remaining_seconds = (deadline_utc - datetime.now(pytz.utc)).total_seconds()

        deadline_text_class = ""
        if 0 < remaining_seconds < 300:  # Less than 5 minutes
            deadline_text_class = "auto-delete-deadline-urgent"

        try:
            deadline_et = deadline_utc.astimezone(pytz.timezone("America/New_York"))
            formatted_time = deadline_et.strftime('%b %d, %Y %I:%M:%S %p')

            st.sidebar.markdown(
                f"<div class='auto-delete-status {deadline_text_class}'>"
                f"<p><b>Data will auto-delete at:</b></p>"
                f"{formatted_time} (ET)"
                f"</div>",
                unsafe_allow_html=True,
            )
        except Exception as e:
            st.sidebar.warning(f"Could not display delete deadline: {e}")


def render_auto_quit_status():
    """Render auto-quit status display."""
    if not st.session_state.get("auto_quit_enabled", True):
        return

    time_remaining = get_time_until_auto_quit()

    if time_remaining.total_seconds() > 0:
        quit_time_utc = get_quit_time()
        minutes_remaining = time_remaining.total_seconds() / 60

        status_class = ""
        if minutes_remaining < 60:  # Less than 1 hour
            status_class = "auto-quit-warning"

        try:
            quit_time_et = quit_time_utc.astimezone(pytz.timezone("America/New_York"))
            formatted_time = quit_time_et.strftime('%b %d, %Y %I:%M:%S %p')

            st.sidebar.markdown(
                f"<div class='auto-quit-status {status_class}'>"
                f"<p><b>App will quit at:</b></p>"
                f"{formatted_time} (ET)"
                f"</div>",
                unsafe_allow_html=True
            )
        except Exception as e:
            st.sidebar.warning(f"Could not display quit time: {e}")

def render_auto_delete_buttons(data_root: Path):
    """Render auto-delete control buttons in the sidebar."""
    if st.session_state.get("delete_deadline") is not None:
        col1, col2 = st.sidebar.columns(2)

        with col1:
            if st.button(
                    f"Add {st.session_state['auto_delete_minutes']} min",
                    type="secondary",
                    use_container_width=True,
                    key="btn_extend_timer_sidebar"
            ):
                extend_auto_delete_timer()
                st.rerun()

        with col2:
            if st.button(
                    "🗑️ Delete now",
                    type="secondary",
                    use_container_width=True,
                    key="btn_delete_now_sidebar"
            ):
                delete_data_now(data_root)
                st.toast("Data directory deleted manually.", icon="✅")
                st.rerun()

    elif data_exist_anywhere(data_root):  # Use the updated function
        # Show delete button even when no timer is active
        if st.sidebar.button(
                "🗑️ Delete data now",
                type="secondary",
                use_container_width=True,
                key="btn_delete_now_sidebar_notimer"
        ):
            delete_data_now(data_root)
            st.toast("Data directory deleted manually.", icon="✅")
            st.rerun()

def render_auto_quit_buttons(data_root: Path):
    if st.session_state.get("auto_quit_enabled", True):
        time_remaining = get_time_until_auto_quit()

        if time_remaining.total_seconds() > 0:
            col1, col2 = st.sidebar.columns(2)

            extension_minutes = st.session_state.get("auto_quit_minutes", 720)
            # Convert to hours for display if >= 60 minutes
            if extension_minutes >= 60:
                display_text = f"Add {extension_minutes // 60}h"
                help_text = f"Reset timer - give {extension_minutes // 60} more hours from now"
            else:
                display_text = f"Add {extension_minutes} min"
                help_text = f"Reset timer - give {extension_minutes} more minutes from now"

            with col1:
                if st.button(
                        display_text,
                        type="secondary",
                        use_container_width=True,
                        key="btn_extend_quit_timer",
                        help=help_text
                ):
                    extend_auto_quit_timer()
                    hours = extension_minutes // 60
                    if hours > 0:
                        st.toast(f"Timer reset! {hours} hours from now.", icon="✅")
                    else:
                        st.toast(f"Timer reset! {extension_minutes} minutes from now.", icon="✅")
                    st.rerun()

            with col2:
                if st.button(
                        "⛔ Quit now",
                        type="secondary",
                        use_container_width=True,
                        key="btn_quit_now"
                ):
                    if data_exist_anywhere(data_root):  # Use the updated function
                        st.sidebar.warning("Delete data before quitting.")
                    else:
                        st.sidebar.info("Shutting down...")
                        st.balloons()
                        time.sleep(1.5)
                        os.kill(os.getpid(), signal.SIGKILL)


def render_settings():
    """Render settings for both auto-delete and auto-quit."""
    st.markdown("### Auto-quit after runtime")
    st.markdown(
        "The application will automatically delete local data and quit after running for "
        "the specified number of minutes to prevent indefinite background execution. "
        "**This works even if the browser tab is closed.**"
    )

    enabled = st.checkbox(
        "Enable auto-quit",
        value=st.session_state.get("auto_quit_enabled", True),
        help="Automatically quit the application after specified runtime"
    )

    if enabled != st.session_state.get("auto_quit_enabled", True):
        st.session_state["auto_quit_enabled"] = enabled
        update_auto_quit_settings()
        st.success(f"Auto-quit {'enabled' if enabled else 'disabled'}.")
        st.rerun()

    if enabled:
        new_minutes = st.number_input(
            "Auto-quit timeout (minutes)",
            min_value=1,
            max_value=1440,  # 24 hours
            step=30,
            value=st.session_state.get("auto_quit_minutes", 720),
            help="How many minutes the application will run before automatically quitting (720 min = 12 hours)"
        )

        if new_minutes != st.session_state.get("auto_quit_minutes", 720):
            st.session_state["auto_quit_minutes"] = new_minutes
            update_auto_quit_settings()
            hours = new_minutes // 60
            if hours > 0:
                st.success(f"Auto-quit timeout set to {new_minutes} minutes ({hours} hours).")
            else:
                st.success(f"Auto-quit timeout set to {new_minutes} minutes.")
            st.rerun()

    st.markdown("---")

    st.markdown("### Auto-delete timer")
    st.markdown(
        "The application will attempt to automatically delete any csv in the *data/* folder after the chosen "
        "period has elapsed since the most recent download or since the application started. "
        "If the application is refreshed, the timer will reset."
    )

    new_val = st.number_input(
        "Auto-delete timer (minutes)",
        min_value=1,
        max_value=240,
        step=1,
        value=st.session_state["auto_delete_minutes"],
        help="How long the data will be kept locally before being purged automatically.",
    )

    if new_val != st.session_state["auto_delete_minutes"]:
        st.session_state["auto_delete_minutes"] = new_val
        if st.session_state.get("delete_deadline") is not None:
            st.session_state["delete_deadline"] = datetime.now(pytz.utc) + timedelta(
                minutes=new_val
            )
        _write_state_to_file()
        st.success(f"Auto-delete timer set to {new_val} minutes.")
        st.rerun()
