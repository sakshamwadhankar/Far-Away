#!/bin/bash
set -e

# Navigate to backend directory
cd "$(dirname "$0")/../backend"

# Check if .venv exists, otherwise use global python/pyinstaller
if [ -d ".venv" ]; then
    PYTHON_CMD=".venv/bin/python"
    PYINSTALLER_CMD=".venv/bin/pyinstaller"
else
    PYTHON_CMD="python"
    PYINSTALLER_CMD="pyinstaller"
fi

# Ensure pyinstaller is available
if ! command -v $PYINSTALLER_CMD &> /dev/null; then
    echo "Installing PyInstaller..."
    $PYTHON_CMD -m pip install pyinstaller
fi

# Run PyInstaller
echo "Building komvos_backend executable..."
$PYINSTALLER_CMD --name komvos_backend --onefile --add-data "../templates:templates" --hidden-import uvicorn --hidden-import fastapi --hidden-import pydantic --hidden-import pydantic_core --hidden-import httpx --hidden-import keyring --hidden-import jinja2 --distpath ../packaging/dist --workpath ../packaging/build --specpath ../packaging komvos_api_entry.py

echo "Build complete: packaging/dist/komvos_backend"
