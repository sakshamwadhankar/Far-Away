@echo off
setlocal EnableDelayedExpansion

:: ============================================================
::  NeuralFlow — Full Stack Startup Script  (Windows)
:: ============================================================

title NeuralFlow Launcher

echo.
echo  ^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=
echo   NeuralFlow — Full Stack Launcher
echo  ^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=
echo.

:: ── Resolve repo root (the folder this script lives in) ──────────────────────
set "REPO_ROOT=%~dp0"
:: Strip trailing backslash
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

set "BACKEND_DIR=%REPO_ROOT%\backend"
set "FRONTEND_DIR=%REPO_ROOT%\apps\desktop"
set "VENV_PYTHON=%BACKEND_DIR%\.venv\Scripts\python.exe"

:: ── 1. Check Python venv exists ───────────────────────────────────────────────
echo [1/4] Checking Python virtual environment...
if not exist "%VENV_PYTHON%" (
    echo  [ERROR] Python venv not found at: %VENV_PYTHON%
    echo.
    echo  Please run the following commands first:
    echo    cd backend
    echo    python -m venv .venv
    echo    .venv\Scripts\python.exe -m pip install -e ".[dev]"
    echo.
    pause
    exit /b 1
)
echo  [OK] Python venv found.
echo.

:: ── 2. Check Node / npm exists ────────────────────────────────────────────────
echo [2/4] Checking Node.js...
where node >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] node.exe not found in PATH.
    echo  Please install Node.js from https://nodejs.org/
    pause
    exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] npm not found in PATH.
    echo  Please install Node.js from https://nodejs.org/
    pause
    exit /b 1
)
echo  [OK] Node.js found.
echo.

:: ── 3. Start Ollama (optional — skip gracefully if not installed) ─────────────
echo [3/4] Starting Ollama...
where ollama >nul 2>&1
if errorlevel 1 (
    echo  [WARN] ollama not found in PATH — skipping.
    echo         Install from https://ollama.com if you want local model support.
    echo.
) else (
    :: Check if Ollama is already running
    curl -s --max-time 2 http://127.0.0.1:11434 >nul 2>&1
    if errorlevel 1 (
        echo  Starting Ollama server in a new window...
        start "NeuralFlow - Ollama" /MIN cmd /c "ollama serve"
        :: Give Ollama a moment to bind its port
        timeout /t 3 /nobreak >nul
        echo  [OK] Ollama started.
    ) else (
        echo  [OK] Ollama already running on port 11434 — skipping.
    )
    echo.
)

:: ── 4. Install backend deps if jinja2 is missing ─────────────────────────────
echo [4/4] Verifying backend dependencies...
"%VENV_PYTHON%" -c "import jinja2" >nul 2>&1
if errorlevel 1 (
    echo  Missing packages detected — running pip install...
    "%VENV_PYTHON%" -m pip install -e "%BACKEND_DIR%" --quiet
    if errorlevel 1 (
        echo  [ERROR] pip install failed. Check your internet connection.
        pause
        exit /b 1
    )
    echo  [OK] Dependencies installed.
) else (
    echo  [OK] Backend dependencies are up to date.
)
echo.

:: ── 5. Install frontend deps if node_modules is missing ──────────────────────
if not exist "%FRONTEND_DIR%\node_modules" (
    echo  node_modules missing — running npm install...
    pushd "%FRONTEND_DIR%"
    call npm install --prefer-offline
    if errorlevel 1 (
        echo  [ERROR] npm install failed.
        popd
        pause
        exit /b 1
    )
    popd
    echo  [OK] Frontend dependencies installed.
    echo.
)

:: ── 6. Start FastAPI backend ──────────────────────────────────────────────────
echo  Starting FastAPI backend on http://127.0.0.1:8000 ...
:: KOMVOS_DEV=1 is required when running the backend without Electron: auth
:: fails closed without a session token, and the Vite dev origin is only
:: allowed through CORS in dev mode. Never set this for a packaged build.
set "KOMVOS_DEV=1"
start "NeuralFlow - Backend" /D "%BACKEND_DIR%" /MIN cmd /k "set KOMVOS_DEV=1&& %VENV_PYTHON% -m uvicorn neuralflow.api.main:app --host 127.0.0.1 --port 8000"
:: Give the backend a moment to bind before the frontend tries to connect
timeout /t 3 /nobreak >nul
echo  [OK] Backend window launched (minimized).
echo.

:: ── 7. Start Electron + Vite frontend ────────────────────────────────────────
echo  Starting Electron desktop app...
start "NeuralFlow - Desktop" /D "%FRONTEND_DIR%" /MIN cmd /k "npm run dev"
echo  [OK] Frontend window launched (minimized — Electron opens automatically).
echo.

echo  ^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=
echo   All services started!
echo  ^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=^=
echo.
echo  Backend   : http://127.0.0.1:8000  (minimized terminal)
echo  Frontend  : http://localhost:5173   (minimized terminal — Electron launching)
echo  Ollama    : http://127.0.0.1:11434  (if installed)
echo.
echo  This window will close in 5 seconds...
timeout /t 5 /nobreak >nul
