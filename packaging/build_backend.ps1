$ErrorActionPreference = "Stop"

# Navigate to backend directory
cd $PSScriptRoot\..\backend

# Check if .venv exists
if (Test-Path ".venv") {
    $PythonCmd = ".venv\Scripts\python.exe"
    $PyInstallerCmd = ".venv\Scripts\pyinstaller.exe"
} else {
    $PythonCmd = "python"
    $PyInstallerCmd = "pyinstaller"
}

# Check if pyinstaller is available
try {
    $null = Get-Command $PyInstallerCmd -ErrorAction Stop
} catch {
    Write-Host "Installing PyInstaller..."
    & $PythonCmd -m pip install pyinstaller
}

# Run PyInstaller
Write-Host "Building komvos_backend executable..."
& $PyInstallerCmd --name komvos_backend --onefile --noconsole --add-data "..\templates;templates" --hidden-import uvicorn --hidden-import fastapi --hidden-import pydantic --hidden-import pydantic_core --hidden-import httpx --hidden-import keyring --hidden-import jinja2 --distpath ..\packaging\dist --workpath ..\packaging\build --specpath ..\packaging komvos_api_entry.py

Write-Host "Build complete: packaging\dist\komvos_backend.exe"
