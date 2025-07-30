# PsydeKick.spec
import os
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_submodules,
    collect_data_files,
    copy_metadata,
)

project_root = Path(__name__).parent.resolve()

# Get Developer ID Application identity string from environment variable
CODESIGN_IDENTITY_STRING = os.getenv("DEV_ID_APP")
if not CODESIGN_IDENTITY_STRING:
    raise ValueError("DEV_ID_APP environment variable is not set. Please create a .env file with your Developer ID Application certificate.")

# Helper function to read the VERSION file
def get_app_version_for_spec(root_path):
    version_file = root_path / "VERSION"
    try:
        return version_file.read_text().strip()
    except FileNotFoundError:
        print("WARNING: VERSION file not found. Using '0.0.0'.")
        return "0.0.0"

app_version = get_app_version_for_spec(project_root)

# ── project files & folders ───────────────────────────────
datas = [
    ("main.py", "."),
    ("workflows", "workflows"),
    ("utils", "utils"),
    ("config", "config"),
    (".streamlit", ".streamlit"),
    ("VERSION", "."),
    (str(project_root / 'icons/apoth_a_033.icns'), '.')
]

# ── Streamlit static assets + metadata ─────────────────────────
datas += collect_data_files("streamlit")
datas += copy_metadata("streamlit")

# ── streamlit_option_menu static assets + metadata  ────────────
datas += collect_data_files("streamlit_option_menu")
datas += copy_metadata("streamlit_option_menu")

# ── hidden/lazy imports ────────────────────────────────────────
hiddenimports = (
        ["streamlit.web.cli", "streamlit_option_menu"]
        + collect_submodules("streamlit")
        + ["altair", "pandas", "numpy", "pytz", "requests"]
)

block_cipher = None

a = Analysis(
    ["run_app.py"],
    pathex=[str(project_root)],
    binaries=None,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="PsydeKick",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    console=True,
    codesign_identity=CODESIGN_IDENTITY_STRING,
)

# For macOS .app bundle generation
app = BUNDLE(
    exe,
    name='PsydeKick.app',
    icon=str(project_root / 'icons/apoth_a_033.icns'),
    bundle_identifier='app.apoth.researchhelpers',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': 'True',
        'LSMinimumSystemVersion': '11.0',
        'CFBundleVersion': app_version,
        'CFBundleShortVersionString': app_version,
    },
)
