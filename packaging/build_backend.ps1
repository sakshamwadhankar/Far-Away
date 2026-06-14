$ErrorActionPreference = "Stop"

# Navigate to backend directory
cd $PSScriptRoot\..\backend

# Check if .venv exists and pyinstaller is available
if (-not (Test-Path ".venv\Scripts\pyinstaller.exe")) {
    Write-Host "Installing PyInstaller..."
    .venv\Scripts\python.exe -m pip install pyinstaller
}

# Run PyInstaller
Write-Host "Building komvos_backend executable..."
.venv\Scripts\pyinstaller.exe --name komvos_backend --onefile --hidden-import uvicorn --hidden-import fastapi --hidden-import pydantic --hidden-import pydantic_core --hidden-import httpx --hidden-import keyring --hidden-import jinja2 --distpath ..\packaging\dist --workpath ..\packaging\build --specpath ..\packaging komvos_api_entry.py

Write-Host "Build complete: packaging\dist\komvos_backend.exe"
