#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install --upgrade -r requirements-build.txt
python3 -c 'import tkinter, psutil'
python3 -m PyInstaller --noconfirm --clean --windowed --name "PiNova System Studio" app/pinova_system_studio.py
ditto -c -k --sequesterRsrc --keepParent "dist/PiNova System Studio.app" "PiNova-System-Studio-macOS.zip"
echo "Build ready: PiNova-System-Studio-macOS.zip"
