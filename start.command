#!/bin/sh
set -eu
cd "$(dirname "$0")"
py=python3
for candidate in .venv/bin/python "$HOME/iphone-station/.venv/bin/python" python3; do
  if "$candidate" -c 'import aiohttp,PIL,dotenv,certifi,pymobiledevice3' 2>/dev/null; then
    py="$candidate"
    break
  fi
done
if [ ! -x build/phone-capture ] || [ capture/main.swift -nt build/phone-capture ]; then ./build-capture.sh; fi
exec "$py" serve.py
