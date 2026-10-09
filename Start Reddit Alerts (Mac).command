#!/bin/bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed. Opening the download page..."
  open "https://www.python.org/downloads/"
  read -p "Press Enter to close."
  exit 1
fi
python3 -m pip install --quiet --disable-pip-version-check --user -r requirements.txt >/dev/null 2>&1
python3 run.py
