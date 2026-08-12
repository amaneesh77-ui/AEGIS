#!/usr/bin/env bash
set -e

echo ""
echo "  ============================================================"
echo "    AEGIS Setup - Automated Expert Guidance & Intelligence"
echo "  ============================================================"
echo ""

# ── Python check ──────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "  [ERROR] python3 not found. Install Python 3.11+ and try again."
    exit 1
fi
PYVER=$(python3 --version 2>&1 | awk '{print $2}')
echo "  [OK] Python $PYVER found."

# ── Virtual environment ───────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "  [..] Creating virtual environment..."
    python3 -m venv .venv
    echo "  [OK] Virtual environment created."
else
    echo "  [OK] Virtual environment already exists."
fi

source .venv/bin/activate

# ── Dependencies ──────────────────────────────────────────────────────
echo "  [..] Installing Python dependencies..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "  [OK] Dependencies installed."

# ── spaCy model ───────────────────────────────────────────────────────
echo "  [..] Downloading spaCy English model..."
python3 -m spacy download en_core_web_sm --quiet
echo "  [OK] spaCy model ready."

# ── Data directories ──────────────────────────────────────────────────
mkdir -p data/uploads data/chroma data/whoosh
echo "  [OK] Data directories ready."

# ── Ollama ────────────────────────────────────────────────────────────
echo ""
if command -v ollama &>/dev/null; then
    echo "  [OK] Ollama found. Pulling models..."
    ollama pull llama3.1:8b
    ollama pull nomic-embed-text
    echo "  [OK] Models ready."
else
    echo "  [WARN] Ollama not found."
    echo "         Install from: https://ollama.com/download"
    echo "         Then run:  ollama pull llama3.1:8b"
    echo "                    ollama pull nomic-embed-text"
fi

# ── Offline translation language packages (DE/FR/JA/ZH → EN) ──────────
echo ""
echo "  [..] Installing offline translation packages (needs internet once)..."
if python3 scripts/install_translation_packages.py; then
    echo "  [OK] Offline translation packages ready."
else
    echo "  [WARN] Some translation packages failed to install - the"
    echo "         translate feature will report \"unavailable\" for those"
    echo "         languages. Re-run scripts/install_translation_packages.py"
    echo "         later if you have internet access."
fi

echo ""
echo "  ============================================================"
echo "    Setup complete!  Run:  ./start.sh"
echo "  ============================================================"
echo ""
