#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install --upgrade -r requirements-build.txt
python3 -c 'import tkinter, psutil'
python3 -m PyInstaller --noconfirm --clean --windowed --name PiNovaSystemStudio app/pinova_system_studio.py
tar -czf PiNova-System-Studio-Linux-$(uname -m).tar.gz -C dist PiNovaSystemStudio
echo "Build ready: PiNova-System-Studio-Linux-$(uname -m).tar.gz"
