#!/bin/bash
#
# Double-click launcher for Mac.
#
# On first run this creates a private virtual environment and installs the
# libraries the app needs. After that it just starts the app. To stop the app,
# come back to this window and press Ctrl-C, then close it.

# Always run from the folder this script lives in, no matter where it's launched
# from (double-clicking in Finder starts in the home directory otherwise).
cd "$(dirname "$0")" || exit 1

VENV_DIR=".venv"

echo "Starting ii-to-soren…"
echo

# 1. Find a usable Python (3.10+).
PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo "❌ Python 3.10 or later was not found."
  echo
  echo "Please install it from https://www.python.org/downloads/ and then"
  echo "double-click this file again."
  echo
  read -r -p "Press Enter to close."
  exit 1
fi

# 2. Create the virtual environment if it doesn't exist yet.
if [ ! -d "$VENV_DIR" ]; then
  echo "First-time setup — this only happens once and may take a minute…"
  if ! "$PYTHON" -m venv "$VENV_DIR"; then
    echo "❌ Could not create the virtual environment."
    read -r -p "Press Enter to close."
    exit 1
  fi
fi

# 3. Install / update dependencies (fast no-op once they're already present).
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
if ! "$VENV_DIR/bin/python" -m pip install --quiet -r requirements.txt; then
  echo "❌ Could not install the required libraries. Are you connected to the internet?"
  read -r -p "Press Enter to close."
  exit 1
fi

# 4. Launch the app. Streamlit opens the browser automatically.
echo
echo "Opening the app in your browser. To stop it, press Ctrl-C here."
echo
exec "$VENV_DIR/bin/streamlit" run ui.py
