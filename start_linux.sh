#!/bin/bash
cd "$(dirname "$0")"
python3 -m pip install --quiet --disable-pip-version-check --user -r requirements.txt >/dev/null 2>&1
exec python3 run.py "$@"
