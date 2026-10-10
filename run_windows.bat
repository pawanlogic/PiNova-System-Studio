@echo off
cd /d "%~dp0"
py -3 -m venv .venv
call .venv\Scripts\python.exe -m pip install --upgrade pip
call .venv\Scripts\python.exe -m pip install -r requirements.txt
call .venv\Scripts\python.exe app\pinova_system_studio.py
pause
