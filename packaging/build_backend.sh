#!/bin/bash
set -e

# Navigate to backend directory
cd "$(dirname "$0")/../backend"

# Check if .venv exists and pyinstaller is available
if [ ! -f ".venv/bin/pyinstaller" ]; then
    echo "Installing PyInstaller..."
    .venv/bin/python -m pip install pyinstaller
fi

# Run PyInstaller
echo "Building komvos_backend executable..."
.venv/bin/pyinstaller --name komvos_backend --onefile --hidden-import uvicorn --hidden-import fastapi --hidden-import pydantic --hidden-import pydantic_core --hidden-import httpx --hidden-import keyring --hidden-import jinja2 --distpath ../packaging/dist --workpath ../packaging/build --specpath ../packaging komvos_api_entry.py

echo "Build complete: packaging/dist/komvos_backend"
