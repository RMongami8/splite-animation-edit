@echo off
setlocal

rem SpriteSheet Studio launcher.
rem Creates the virtual environment and installs dependencies on first run,
rem then starts the app. Server URL: http://127.0.0.1:8420

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [setup] Virtual environment not found. Creating .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [error] Failed to create the virtual environment. Is Python installed and on PATH?
        pause
        exit /b 1
    )

    echo [setup] Installing dependencies from requirements.txt ...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [error] Dependency installation failed. Check the output above.
        pause
        exit /b 1
    )
)

echo [run] Starting SpriteSheet Studio ...
echo [run] Open http://127.0.0.1:8420 in your browser once the server is ready.
".venv\Scripts\python.exe" app.py

echo [run] Server stopped.
pause
