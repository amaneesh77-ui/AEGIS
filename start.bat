@echo off
title AEGIS - Starting...

if not exist ".venv" (
    echo  [ERROR] Virtual environment not found. Run setup.bat first.
    pause & exit /b 1
)

call .venv\Scripts\activate.bat

echo.
echo  ============================================================
echo    AEGIS is starting...
echo    Open your browser at:  http://127.0.0.1:7430
echo    Press Ctrl+C to stop.
echo  ============================================================
echo.

cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 7430 --reload
