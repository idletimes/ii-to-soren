@echo off
rem
rem Double-click launcher for Windows.
rem
rem On first run this creates a private virtual environment and installs the
rem libraries the app needs. After that it just starts the app. To stop the app,
rem come back to this window and press Ctrl-C, then close it.

rem Always run from the folder this script lives in.
cd /d "%~dp0"

set "VENV_DIR=.venv"

echo Starting ii-to-soren...
echo.

rem 1. Find a usable Python (3.10+). The "py" launcher is preferred on Windows.
set "PYTHON="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if %errorlevel% equ 0 (
  set "PYTHON=py -3"
) else (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
  if %errorlevel% equ 0 set "PYTHON=python"
)

if not defined PYTHON (
  echo [X] Python 3.10 or later was not found.
  echo.
  echo Please install it from https://www.python.org/downloads/
  echo During install, tick "Add Python to PATH", then double-click this file again.
  echo.
  pause
  exit /b 1
)

rem 2. Create the virtual environment if it doesn't exist yet.
if not exist "%VENV_DIR%" (
  echo First-time setup - this only happens once and may take a minute...
  %PYTHON% -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo [X] Could not create the virtual environment.
    pause
    exit /b 1
  )
)

rem 3. Install / update dependencies (fast no-op once they're already present).
"%VENV_DIR%\Scripts\python.exe" -m pip install --quiet --upgrade pip
"%VENV_DIR%\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
  echo [X] Could not install the required libraries. Are you connected to the internet?
  pause
  exit /b 1
)

rem 4. Launch the app. Streamlit opens the browser automatically.
echo.
echo Opening the app in your browser. To stop it, press Ctrl-C here.
echo.
"%VENV_DIR%\Scripts\streamlit.exe" run ui.py
