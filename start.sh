#!/usr/bin/env bash
set -e

if [ ! -d ".venv" ]; then
    echo "[ERROR] Virtual environment not found. Run ./setup.sh first."
    exit 1
fi

source .venv/bin/activate

echo ""
echo "  ============================================================"
echo "    AEGIS is starting..."
echo "    Open your browser at:  http://127.0.0.1:7430"
echo "    Press Ctrl+C to stop."
echo "  ============================================================"
echo ""

cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 7430 --reload
