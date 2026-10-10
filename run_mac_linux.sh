#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" == "Linux" ]]; then
  if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
    echo "Tkinter missing. Debian/Raspberry Pi OS: sudo apt install python3-tk python3-venv"
    exit 1
  fi
fi
python3 -m venv .venv || { echo "Could not create venv. Install python3-venv first."; exit 1; }
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
exec .venv/bin/python app/pinova_system_studio.py
