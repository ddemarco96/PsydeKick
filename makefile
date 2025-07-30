.PHONY: activate build-mac build-win clean dist-mac verify-mac check-apps build-arm64-app build-intel-app

# --- Configuration ---
SPEC_FILE     := PsydeKick.spec
APP_NAME      := PsydeKick
PYTHON_INTERPRETER := python3.10
VENV_DIR_ARM64 := .venv-arm64
VENV_DIR_X86_64 := .venv-x86_64
APP_BUNDLE_ARM64 := $(APP_NAME)-AppleSilicon.app
APP_BUNDLE_INTEL := $(APP_NAME)-Intel.app
APP_BUNDLE_PATH_ARM64 := dist/$(APP_BUNDLE_ARM64)
APP_BUNDLE_PATH_INTEL := dist/$(APP_BUNDLE_INTEL)
DMG_NAME_ARM64 := $(APP_NAME)-AppleSilicon.dmg
DMG_NAME_INTEL := $(APP_NAME)-Intel.dmg
DMG_OUTPUT_PATH_ARM64 := dist/$(DMG_NAME_ARM64)
DMG_OUTPUT_PATH_INTEL := dist/$(DMG_NAME_INTEL)
REQUIREMENTS  := requirements.txt
DEPLOYMENT_TARGET := 11.0

# --- Load environment variables from .env file ---
ifneq (,$(wildcard .env))
    include .env
    export
endif

# --- Constants ---
ifndef DEV_ID_APP
    $(error DEV_ID_APP is not set. Please create a .env file with DEV_ID_APP variable)
endif

# -----------------------------------------------------------------
# Setup ARM64 Virtual Environment
# -----------------------------------------------------------------
setup-venv-arm64:
	@echo "▶ Setting up ARM64 virtual environment..."
	@if [ -d "$(VENV_DIR_ARM64)" ]; then \
	    echo "▶ Removing existing ARM64 virtual environment: $(VENV_DIR_ARM64)"; \
	    rm -rf "$(VENV_DIR_ARM64)"; \
	fi
	@echo "▶ Creating ARM64 virtual environment..."
	@arch -arm64 $(PYTHON_INTERPRETER) -m venv "$(VENV_DIR_ARM64)"
	@echo "▶ Installing dependencies for ARM64..."
	@MACOSX_DEPLOYMENT_TARGET=$(DEPLOYMENT_TARGET) \
	 arch -arm64 $(VENV_DIR_ARM64)/bin/pip install --upgrade pip
	@MACOSX_DEPLOYMENT_TARGET=$(DEPLOYMENT_TARGET) \
	 arch -arm64 $(VENV_DIR_ARM64)/bin/pip install -r "$(REQUIREMENTS)"
	@echo "✔ ARM64 environment ready."

# -----------------------------------------------------------------
# Setup x86_64 Virtual Environment
# -----------------------------------------------------------------
setup-venv-x86_64:
	@echo "▶ Setting up x86_64 virtual environment..."
	@if [ -d "$(VENV_DIR_X86_64)" ]; then \
	    echo "▶ Removing existing x86_64 virtual environment: $(VENV_DIR_X86_64)"; \
	    rm -rf "$(VENV_DIR_X86_64)"; \
	fi
	@echo "▶ Creating x86_64 virtual environment..."
	@arch -x86_64 $(PYTHON_INTERPRETER) -m venv "$(VENV_DIR_X86_64)"
	@echo "▶ Installing dependencies for x86_64..."
	@MACOSX_DEPLOYMENT_TARGET=$(DEPLOYMENT_TARGET) \
	 arch -x86_64 $(VENV_DIR_X86_64)/bin/pip install --upgrade pip
	@MACOSX_DEPLOYMENT_TARGET=$(DEPLOYMENT_TARGET) \
	 arch -x86_64 $(VENV_DIR_X86_64)/bin/pip install -r "$(REQUIREMENTS)"
	@echo "✔ x86_64 environment ready."

# -----------------------------------------------------------------
# Build ARM64 version (Apple Silicon)
# -----------------------------------------------------------------
build-arm64-app: setup-venv-arm64
	@echo "▶ Building ARM64 (Apple Silicon) version..."
	@mkdir -p dist
	@MACOSX_DEPLOYMENT_TARGET=$(DEPLOYMENT_TARGET) \
	 arch -arm64 $(VENV_DIR_ARM64)/bin/pyinstaller $(SPEC_FILE) \
	 --clean --distpath temp-arm64 --workpath build-arm64
	@# Rename the app to include architecture in the name
	@mv "temp-arm64/$(APP_NAME).app" "$(APP_BUNDLE_PATH_ARM64)"
	@rm -rf temp-arm64 build-arm64
	@echo "✔ ARM64 (Apple Silicon) build complete: $(APP_BUNDLE_PATH_ARM64)"

# -----------------------------------------------------------------
# Build x86_64 version (Intel)
# -----------------------------------------------------------------
build-intel-app: setup-venv-x86_64
	@echo "▶ Building x86_64 (Intel) version..."
	@mkdir -p dist
	@MACOSX_DEPLOYMENT_TARGET=$(DEPLOYMENT_TARGET) \
	 arch -x86_64 $(VENV_DIR_X86_64)/bin/pyinstaller $(SPEC_FILE) \
	 --clean --distpath temp-x86_64 --workpath build-x86_64
	@# Rename the app to include architecture in the name
	@mv "temp-x86_64/$(APP_NAME).app" "$(APP_BUNDLE_PATH_INTEL)"
	@rm -rf temp-x86_64 build-x86_64
	@echo "✔ x86_64 (Intel) build complete: $(APP_BUNDLE_PATH_INTEL)"

# -----------------------------------------------------------------
# Build both versions
# -----------------------------------------------------------------
build-mac: clean build-arm64-app build-intel-app
	@echo "✔ Both versions built successfully:"
	@echo "  📱 Apple Silicon: $(APP_BUNDLE_PATH_ARM64)"
	@echo "  💻 Intel:        $(APP_BUNDLE_PATH_INTEL)"
	@$(MAKE) check-apps

# -----------------------------------------------------------------
# Check both applications
# -----------------------------------------------------------------
check-apps:
	@echo "▶ Checking both applications..."
	@if [ -d "$(APP_BUNDLE_PATH_ARM64)" ]; then \
	    echo "📱 Apple Silicon app:"; \
	    echo "   Main executable: $$(file "$(APP_BUNDLE_PATH_ARM64)/Contents/MacOS/PsydeKick")"; \
	    echo "   Size: $$(du -sh "$(APP_BUNDLE_PATH_ARM64)" | cut -f1)"; \
	else \
	    echo "❌ Apple Silicon app not found"; \
	fi
	@echo ""
	@if [ -d "$(APP_BUNDLE_PATH_INTEL)" ]; then \
	    echo "💻 Intel app:"; \
	    echo "   Main executable: $$(file "$(APP_BUNDLE_PATH_INTEL)/Contents/MacOS/PsydeKick")"; \
	    echo "   Size: $$(du -sh "$(APP_BUNDLE_PATH_INTEL)" | cut -f1)"; \
	else \
	    echo "❌ Intel app not found"; \
	fi

# -----------------------------------------------------------------
# Test Apple Silicon version (launch like double-clicking)
# -----------------------------------------------------------------
test-silicon:
	@echo "▶ Launching Apple Silicon version..."
	@if [ ! -d "$(APP_BUNDLE_PATH_ARM64)" ]; then \
	    echo "❌ Apple Silicon app not found: $(APP_BUNDLE_PATH_ARM64)"; \
	    echo "   Run 'make build-mac' or 'make build-arm64-app' first."; \
	    exit 1; \
	fi
	@echo "🚀 Starting PsydeKick (Apple Silicon)..."
	@echo "   The app will open and Streamlit should start in your browser."
	@echo "   Press Ctrl+C in this terminal to stop the app when done testing."
	@echo ""
	@open "$(APP_BUNDLE_PATH_ARM64)"
	@echo "✅ Apple Silicon app launched!"
	@echo "   Check your browser for the Streamlit interface."
	@echo "   To stop: Close the browser tab and quit the app from the dock/menu."

# -----------------------------------------------------------------
# Test Intel version (launch like double-clicking)
# -----------------------------------------------------------------
test-intel:
	@echo "▶ Launching Intel version..."
	@if [ ! -d "$(APP_BUNDLE_PATH_INTEL)" ]; then \
	    echo "❌ Intel app not found: $(APP_BUNDLE_PATH_INTEL)"; \
	    echo "   Run 'make build-mac' or 'make build-intel-app' first."; \
	    exit 1; \
	fi
	@echo "🚀 Starting PsydeKick (Intel)..."
	@echo "   The app will open and Streamlit should start in your browser."
	@echo "   Press Ctrl+C in this terminal to stop the app when done testing."
	@echo ""
	@open "$(APP_BUNDLE_PATH_INTEL)"
	@echo "✅ Intel app launched!"
	@echo "   Check your browser for the Streamlit interface."
	@echo "   To stop: Close the browser tab and quit the app from the dock/menu."
# -----------------------------------------------------------------
# Create DMGs for both versions
# -----------------------------------------------------------------
dist-mac: build-mac
	@echo "▶ Creating distribution packages..."
	@echo "▶ Signing Apple Silicon app..."
	@codesign --force --deep --options=runtime \
	    --sign "$(DEV_ID_APP)" \
	    "$(APP_BUNDLE_PATH_ARM64)"
	@echo "▶ Signing Intel app..."
	@codesign --force --deep --options=runtime \
	    --sign "$(DEV_ID_APP)" \
	    "$(APP_BUNDLE_PATH_INTEL)"
	@echo "▶ Creating Apple Silicon DMG..."
	@hdiutil create -volname "$(APP_NAME) (Apple Silicon)" \
	    -srcfolder "$(APP_BUNDLE_PATH_ARM64)" \
	    -ov -format UDZO \
	    -size 200m \
	    "$(DMG_OUTPUT_PATH_ARM64)"
	@echo "▶ Creating Intel DMG..."
	@hdiutil create -volname "$(APP_NAME) (Intel)" \
	    -srcfolder "$(APP_BUNDLE_PATH_INTEL)" \
	    -ov -format UDZO \
	    -size 200m \
	    "$(DMG_OUTPUT_PATH_INTEL)"
	@echo "✔ Distribution packages created:"
	@echo "  📱 Apple Silicon: $(DMG_OUTPUT_PATH_ARM64)"
	@echo "  💻 Intel:        $(DMG_OUTPUT_PATH_INTEL)"
	@echo ""
	@echo "🎉 Ready for distribution! Users can download the appropriate version for their Mac."

# -----------------------------------------------------------------
# Notarize both DMGs (optional - run separately)
# -----------------------------------------------------------------
notarize-both:
	@echo "▶ Notarizing both DMGs..."
	@read -p "Enter Apple ID (email for notarization): " apple_id_input; \
	 read -p "Enter Team ID: " team_id_input; \
	 read -s -p "Enter App-Specific Password: " app_specific_password_input; \
	 echo ""; \
	 echo "▶ Notarizing Apple Silicon DMG..."; \
	 xcrun notarytool submit "$(DMG_OUTPUT_PATH_ARM64)" \
	    --apple-id "$$apple_id_input" \
	    --team-id "$$team_id_input" \
	    --password "$$app_specific_password_input" \
	    --wait; \
	 echo "▶ Notarizing Intel DMG..."; \
	 xcrun notarytool submit "$(DMG_OUTPUT_PATH_INTEL)" \
	    --apple-id "$$apple_id_input" \
	    --team-id "$$team_id_input" \
	    --password "$$app_specific_password_input" \
	    --wait; \
	 unset app_specific_password_input
	@echo "▶ Stapling notarization tickets..."
	@xcrun stapler staple "$(DMG_OUTPUT_PATH_ARM64)"
	@xcrun stapler staple "$(DMG_OUTPUT_PATH_INTEL)"
	@echo "✔ Both DMGs notarized and stapled."

# -----------------------------------------------------------------
# Verification
# -----------------------------------------------------------------
verify-mac:
	@echo "▶ Verifying both applications..."
	@if [ -d "$(APP_BUNDLE_PATH_ARM64)" ]; then \
	    echo "📱 Verifying Apple Silicon app..."; \
	    codesign --verify --verbose=2 "$(APP_BUNDLE_PATH_ARM64)"; \
	    spctl --assess --type execute --verbose "$(APP_BUNDLE_PATH_ARM64)"; \
	fi
	@if [ -d "$(APP_BUNDLE_PATH_INTEL)" ]; then \
	    echo "💻 Verifying Intel app..."; \
	    codesign --verify --verbose=2 "$(APP_BUNDLE_PATH_INTEL)"; \
	    spctl --assess --type execute --verbose "$(APP_BUNDLE_PATH_INTEL)"; \
	fi
	@$(MAKE) check-apps
	@$(MAKE) test-apps
	@echo "✔ Verification complete."

# -----------------------------------------------------------------
# Clean artifacts
# -----------------------------------------------------------------
clean:
	@echo "▶ Attempting to detach possibly lingering DMG mounts..."
	@hdiutil detach "/Volumes/$(APP_NAME) (Apple Silicon)" >/dev/null 2>&1 || true
	@hdiutil detach "/Volumes/$(APP_NAME) (Intel)" >/dev/null 2>&1 || true
	@echo "▶ Cleaning build artifacts..."
	@rm -rf build build-arm64 build-x86_64 dist temp-arm64 temp-x86_64 \
	        __pycache__ *.pyc *.log *.dmg
	@find . -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	@find . -name '*.pyc' -delete 2>/dev/null || true
	@echo "✔ Cleaned."

clean-venv:
	@echo "▶ Removing virtual environments..."
	@rm -rf "$(VENV_DIR_ARM64)" "$(VENV_DIR_X86_64)" .venv
	@echo "✔ Virtual environments removed."

# -----------------------------------------------------------------
# Help/Info
# -----------------------------------------------------------------
info:
	@echo "🏗️  PsydeKick Build System"
	@echo "=================================="
	@echo ""
	@echo "Main targets:"
	@echo "  make build-mac       - Build both Apple Silicon and Intel versions"
	@echo "  make dist-mac        - Build, sign, and create DMGs for both versions"
	@echo "  make check-apps      - Check both applications"
	@echo "  make test-apps       - Test both applications"
	@echo "  make verify-mac      - Verify signatures and compatibility"
	@echo "  make notarize-both   - Notarize both DMGs (run after dist-mac)"
	@echo ""
	@echo "Testing:"
	@echo "  make test-silicon    - Launch Apple Silicon version (like double-clicking)"
	@echo "  make test-intel      - Launch Intel version (like double-clicking)"
	@echo "Individual builds:"
	@echo "  make build-arm64-app - Build only Apple Silicon version"
	@echo "  make build-intel-app - Build only Intel version"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean           - Clean build artifacts"
	@echo "  make clean-venv      - Remove virtual environments"
	@echo ""
	@echo "The build process creates:"
	@echo "  📱 $(APP_BUNDLE_ARM64) - For Apple Silicon Macs (M1, M2, M3+)"
	@echo "  💻 $(APP_BUNDLE_INTEL) - For Intel Macs"
