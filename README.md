# PiNova System Studio v5.1 — Cross-platform project

PiNova is a Tkinter desktop system monitor intended for Raspberry Pi OS, Linux, Windows, and macOS.

## What this bundle contains

- `app/pinova_system_studio.py` — main app source.
- `requirements.txt` — `psutil`, used for CPU, RAM, process, disk, uptime, and network information on Windows/macOS/Linux.
- `run_windows.bat` / `run_mac_linux.sh` — run from source for testing.
- `build_*.sh` / `build_windows.bat` — local PyInstaller build helpers.
- `.github/workflows/build-release.yml` — builds OS-specific downloads on GitHub when you push a `v*` tag.
- `website/` — a small responsive product/download website, ready for GitHub Pages or other static hosting.

## Important sensor notes

Temperature is platform/hardware dependent. Linux and Raspberry Pi commonly expose a thermal zone. Windows and many Mac models do not expose a temperature sensor through a standard API, so the app will show `N/A` there rather than inventing a value. This limitation is normal for general-purpose monitoring utilities.

## Run on Raspberry Pi OS / Linux

Install system Tk support first if needed:

```bash
sudo apt update
sudo apt install python3-tk python3-venv
```

In this project folder:

```bash
chmod +x run_mac_linux.sh
./run_mac_linux.sh
```

## Run on Windows

Install Python 3.11+ from python.org and ensure the Tcl/Tk option is included. Double-click `run_windows.bat`. The first run creates a `.venv` and installs the `psutil` dependency.

## Run on macOS

Install a Python build that includes Tkinter (the python.org installer is a straightforward choice), open Terminal in this folder, then run:

```bash
chmod +x run_mac_linux.sh
./run_mac_linux.sh
```

## Build a local app package

Build on the operating system you are targeting. PyInstaller does not cross-compile: Windows builds should be made on Windows, macOS builds on macOS, and Linux builds on Linux.

- Windows: `build_windows.bat`
- macOS: `./build_macos.sh`
- Linux/Raspberry Pi: `./build_linux.sh`

For end-user release downloads across all OSes, use GitHub Actions as described below.

## Create your download site and automatic release builds

1. Create a GitHub repository named `PiNova-System-Studio`.
2. Upload/push the entire project folder, including the hidden `.github` directory.
3. Edit `website/site-config.js` and replace `YOUR-GITHUB-USERNAME/PiNova-System-Studio` with your exact GitHub `owner/repository`.
4. In GitHub repo settings, open **Pages** and set the build source to **GitHub Actions**.
5. Push a version tag from your computer after uploading the code:

```bash
git tag v5.1.0
git push origin v5.1.0
```

The build workflow compiles Windows x64, macOS Apple Silicon, macOS Intel, Linux x64, and Raspberry Pi/Linux ARM64 assets, then attaches them to a GitHub Release. The website buttons link to those release assets.

The Pages workflow publishes the contents of `website/` on each push to the default branch. Once GitHub Pages is enabled, the Pages URL appears under Settings → Pages.

## Existing history safety

On Raspberry Pi/Linux, this version continues using `~/raspberry_pi_monitor/monitor_history.db` so existing history is preserved. Windows and macOS use their conventional per-user app-data locations and start their own local history database.
