@echo off
setlocal
cd /d "%~dp0"
py -3 -m pip install --upgrade -r requirements-build.txt
py -3 -m PyInstaller --noconfirm --clean --windowed --name PiNovaSystemStudio app\pinova_system_studio.py
powershell -NoProfile -Command "Compress-Archive -Path 'dist\PiNovaSystemStudio' -DestinationPath 'PiNova-System-Studio-Windows-x64.zip' -Force"
echo Build ready: PiNova-System-Studio-Windows-x64.zip
