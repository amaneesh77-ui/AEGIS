@echo off
setlocal enabledelayedexpansion
title AEGIS Setup

echo.
echo  ============================================================
echo    AEGIS Setup - Automated Expert Guidance ^& Intelligence
echo  ============================================================
echo.

:: ── Check Python ──────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install Python 3.11+ from python.org
    echo          Ensure "Add Python to PATH" is checked during install.
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  [OK] Python %PYVER% found.

:: ── Create virtual environment ────────────────────────────────────────
if not exist ".venv" (
    echo  [..] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 ( echo  [ERROR] Failed to create venv & pause & exit /b 1 )
    echo  [OK] Virtual environment created.
) else (
    echo  [OK] Virtual environment already exists.
)

:: ── Activate and install dependencies ────────────────────────────────
echo  [..] Installing Python dependencies (this may take a few minutes)...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 ( echo  [ERROR] pip install failed & pause & exit /b 1 )
echo  [OK] Python dependencies installed.

:: ── Download spaCy model ──────────────────────────────────────────────
echo  [..] Downloading spaCy English model...
python -m spacy download en_core_web_sm --quiet
echo  [OK] spaCy model ready.

:: ── Create data directories ───────────────────────────────────────────
if not exist "data\uploads"  mkdir data\uploads
if not exist "data\chroma"   mkdir data\chroma
if not exist "data\whoosh"   mkdir data\whoosh
echo  [OK] Data directories created.

:: ── Check Ollama ──────────────────────────────────────────────────────
echo.
echo  [..] Checking for Ollama...
where ollama >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [WARN] Ollama not found in PATH.
    echo         Download from: https://ollama.com/download
    echo         Install it, then run this setup again, OR
    echo         manually pull models after installing:
    echo           ollama pull llama3.1:8b
    echo           ollama pull nomic-embed-text
    echo.
) else (
    echo  [OK] Ollama found.
    echo  [..] Pulling LLM model (llama3.1:8b ~4.9GB - may take a while)...
    ollama pull llama3.1:8b
    echo  [..] Pulling embedding model (nomic-embed-text ~274MB)...
    ollama pull nomic-embed-text
    echo  [OK] Ollama models ready.
)

:: ── Offline translation language packages (DE/FR/JA/ZH → EN) ──────────
echo.
echo  [..] Installing offline translation packages (needs internet once)...
python scripts\install_translation_packages.py
if errorlevel 1 (
    echo  [WARN] Some translation packages failed to install - the
    echo         translate feature will report "unavailable" for those
    echo         languages. Re-run scripts\install_translation_packages.py
    echo         later if you have internet access.
) else (
    echo  [OK] Offline translation packages ready.
)

echo.
echo  ============================================================
echo    Setup complete!
echo    Run start.bat to launch AEGIS.
echo  ============================================================
echo.
pause
