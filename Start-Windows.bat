@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\streamlit.exe" (
  echo First run Install-Windows.ps1.
  echo.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Windows.ps1"
  if errorlevel 1 pause & exit /b 1
)

start "" "http://127.0.0.1:8501"
".venv\Scripts\streamlit.exe" run streamlit_app.py --server.address 127.0.0.1 --server.port 8501

pause
