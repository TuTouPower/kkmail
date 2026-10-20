#!/usr/bin/env bash
# Bundle the Flask backend for Electron. Requires PyInstaller.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m pip install pyinstaller
pyinstaller --noconfirm --onefile --name outlookemail-backend \
  --add-data "outlook_web:outlook_web" \
  --hidden-import flask \
  web_outlook_app.py
mkdir -p desktop/resources
cp "dist/outlookemail-backend" desktop/resources/outlookemail-backend
echo "sidecar: desktop/resources/outlookemail-backend"
