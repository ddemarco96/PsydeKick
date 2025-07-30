# PsydeKick 
a Streamlit app with a handful of useful tools for research teams

This project contains everything needed to run the **PsydeKick** Streamlit app.

## Contents

-  `requirements.txt` ‑ your venv environment requirements
-  `run_app.py` ‑ launcher script for Streamlit
-  `makefile` ‑ for rebuilding the packed environment
-  `main.py` - handles the UI and routing
- `/workflows` ‑ contains the modules for each workflow
- `/utils` ‑ contains utility functions and classes used by the application broadly
- `/config`, - contains study-specific configuration files
- `/tests` ‑ contains unit tests for the workflows

## Researchers: Run the app (default usage)

The default and recommended way to use PsydeKick is to run it from the terminal. This works for both Intel and M-series Macs, and is the most up-to-date method for researchers.

### macOS
1. Ensure you have Python 3.10 or later installed.
2. Open a terminal and navigate to the project directory.
3. For Intel Macs:
   ```bash
   make setup-venv-x86_64
   source .venv-x86_64/bin/activate
   ```
   For M-series Macs:
   ```bash
   make setup-venv-arm64
   source .venv-arm64/bin/activate
   ```
4. Run the app:
   ```bash
   python run_app.py
   ```
5. The app will open in your browser at http://localhost:8501.

### Windows
Windows is not officially supported, but you may run the app from the terminal if you have Python 3.10+ and install dependencies from `requirements.txt`.

## Common troubleshooting steps
If you encounter any issues running the app, try the following steps:
1. Check the operating system requirements:
   - macOS 11 or later (Intel and M-series Macs are supported with their respective virtual environments/builds)
   - The earliest supported MacOS we've tested is Sonoma
2. Ensure you have the latest version of the app. And are not trying to run an old version.

### I'm clicking the app and it doesn't open
1. If the app doesn't open in your browser, try manually navigating to http://localhost:8501.
2. If you see a message about being unable to connect, the app may be having trouble starting for some reason.
   1. Try moving the app to your Desktop and then running `~Desktop/PsydeKick.app/Contents/MacOS/PsydeKick` in the terminal. The terminal output should give you more error information.
   2. If you see an error about another process using port 8501, it's possible that a previous run of the app or another streamlit app has failed to exit. You can try to stop that existing process by running:
      ```bash
      kill $(lsof -t -i:8501)
      ```
3. You can also try running the app from the terminal as described in the "Run the app" section above. This will give you more detailed error messages if something goes wrong. 
   1. If you see an error about missing dependencies, make sure you have the correct virtual environment activated and that you've run `make setup-venv-x86_64` or `make setup-venv-arm64` as appropriate.

## Issues?
If you encounter any issues, after trying the troubleshooting steps, please open a ticket in the [GitHub repository](https://github.com/ddemarco96/research-helpers)

## Feedback and feature requests
If you have any feedback or feature requests, please open a ticket in the [GitHub repository](https://github.com/ddemarco96/research-helpers)

---

## Optional: One-click app and distribution (may be applicable for some users)

Some users may receive a bundled one-click version of PsydeKick (macOS only). These instructions are for those cases, but are not the default use case.

### macOS One-click App
You may receive a zipped folder containing the app as a dmg file.
1. Double-click the dmg file to mount it.
2. Drag the PsydeKick app to your Applications folder, Desktop, etc.
3. Double-click the app to run it.
   - You may need to right-click and select "Open" if you get a warning about it being from an unidentified developer.
4. The app will open in your browser at http://localhost:8501.
5. If the browser doesn't open automatically, manually navigate to http://localhost:8501.

### Building, Signing, and Notarizing the App (for maintainers)
If you need to rebuild, sign, or notarize the app for distribution:
1. A Mac with Xcode installed
2. An Apple Developer account (paid)
3. A `Developer ID Application` certificate
4. An `App-Specific Password` for the Apple NotaryTool

Update the makefile's `DEV_APP_ID` variable as needed, then run:
```bash
make dist-mac
make notarize-both
```
This will create new dmg files for both Intel and Silicon architectures in the `dist` folder.

Testing before distribution:
```bash
make build-mac
```

**Note:** If you are self-distributing, you may need to update the icon files in the `icons/` folder to match your branding or requirements.

---

## Contributing
Contributions are welcome via pull requests! If you have improvements, bug fixes, or new features, please fork the repository and submit a pull request. Make sure your code is well-documented and passes all existing tests.

### Roadmap and contribution ideas:
- [ ] Add pattern rendering to the tagging charts for improved accessibility
- [ ] Implement an in-app config editor
- [ ] Extend the config explorer with information about study settings
- [ ] Implement control of the auto-delete and quit behaviors with config options
- [ ] Implement the ability to drop an entire config file/zip into the app to load it
- [ ] Implement the ability to download data for specific participants by alias/regex
- [ ] Extend typed Python coverage
- [ ] Add a workflow for participant account credential generation/management
- [ ] Add a workflow for variable naming
- [ ] Add additional data source compatibility