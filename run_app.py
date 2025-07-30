# run_app.py

import os
import sys
from pathlib import Path
import time
import webbrowser
import threading
import socket

import streamlit.web.cli as stcli

# ──────────────────────────────────────────────────────────────
# 1. Function to check if port is in use
# ──────────────────────────────────────────────────────────────
def is_port_in_use(host='localhost', port=8501):
    """Check if a port is already in use."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)  # 1 second timeout
            result = sock.connect_ex((host, port))
            return result == 0  # 0 means connection successful (port in use)
    except Exception:
        return False

# ──────────────────────────────────────────────────────────────
# 2. Function to open browser
# ──────────────────────────────────────────────────────────────
def open_browser_immediately():
    """Open browser immediately (for existing app)."""
    webbrowser.open_new_tab("http://localhost:8501")

def open_browser_delayed():
    """Open browser after delay (for new app)."""
    time.sleep(2)
    webbrowser.open_new_tab("http://localhost:8501")

# ──────────────────────────────────────────────────────────────
# 3. Check if app is already running
# ──────────────────────────────────────────────────────────────
if is_port_in_use():
    print("App already running on port 8501. Opening browser...")
    open_browser_immediately()
    sys.exit(0)

# ──────────────────────────────────────────────────────────────
# 4. App not running - start it up
# ──────────────────────────────────────────────────────────────
print("Starting new app on port 8501...")

# Determine paths and set Current Working Directory
try:
    # Inside PyInstaller bundle
    bundle_root = Path(sys._MEIPASS)
except AttributeError:
    # Running as a normal script
    bundle_root = Path(__file__).parent.resolve()

streamlit_script_to_run = str(bundle_root / "main.py")
os.chdir(bundle_root)

# ──────────────────────────────────────────────────────────────
# 5. Construct sys.argv for Streamlit
# ──────────────────────────────────────────────────────────────
sys.argv = [
    "streamlit",
    "run",
    streamlit_script_to_run,
    "--server.port", "8501",
    "--server.headless", "true",
    "--global.developmentMode", "false",
    "--server.fileWatcherType", "none",
    "--server.runOnSave", "false",
    "--browser.gatherUsageStats", "false",
    "--browser.serverAddress", "localhost",
    "--theme.primaryColor", "#339999",
    "--theme.backgroundColor", "#f5f5f5",
    "--theme.secondaryBackgroundColor", "#e7e9e9",
]

# ──────────────────────────────────────────────────────────────
# 6. Execute Streamlit
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Set environment variables
    os.environ['STREAMLIT_SERVER_PORT'] = '8501'
    os.environ['STREAMLIT_SERVER_HEADLESS'] = 'true'
    os.environ['STREAMLIT_GLOBAL_DEVELOPMENTMODE'] = 'false'
    os.environ['STREAMLIT_SERVER_FILE_WATCHER_TYPE'] = 'none'

    # Open the browser in a separate thread after delay
    threading.Thread(target=open_browser_delayed).start()

    stcli.main()
