# AEGIS - Automated Expert Guidance & Intelligence System

An **entirely offline**, on-premises RAG (Retrieval-Augmented Generation)
assistant built for HMGCC's requirement: ingest heterogeneous engineering
data (datasheets, manuals, schematics, corporate databases, firmware/code
archives, scanned/handwritten notes...), answer natural-language questions
about it with citations and a calibrated confidence score, and never phone
home. Local inference via [Ollama](https://ollama.com) (`llama3.1:8b` +
`nomic-embed-text`), local vector/keyword search (ChromaDB + Whoosh), local
SQLite for structured state - no cloud API calls anywhere.

## Repository layout

```
backend/            FastAPI application (routers/, services/, models.py, database.py, config.py)
frontend/            Vanilla JS/HTML/CSS UI (served by the backend)
tests/               pytest suite + tests/sample_data/ (generated fixtures for every supported input type)
installer/           Single-file offline installers for Windows + Linux (see installer/README.md)
docs/                Interactive setup+navigation guide (AEGIS_Guide.html), ethics notes,
                     and the original HMGCC requirement/Q&A PDFs
scripts/             Small standalone admin utilities (clear_stuck.py, install_translation_packages.py)
pitch_deck/          Marketing/pitch-day materials (deck, speaker notes, mockups) - not part of the app
data/                Runtime state (SQLite DB, Chroma/Whoosh indexes, uploads) - gitignored, created on first run
requirements.txt     Python dependencies
setup.bat / setup.sh Create the venv, install deps, pull Ollama models
start.bat / start.sh Run the app (http://127.0.0.1:7430)
```

> **New here?** Open [`docs/AEGIS_Guide.html`](docs/AEGIS_Guide.html) in a browser for an
> interactive setup guide + full UI navigation tour (filterable, with copy-paste-ready
> commands and collapsible troubleshooting).

## Quick start (development)

```bash
# Windows
setup.bat
start.bat

# Linux / macOS
./setup.sh
./start.sh
```

This creates `.venv`, installs `requirements.txt`, pulls the two Ollama
models if Ollama is already installed, and installs the offline
translation language packages (see below). Then open
`http://127.0.0.1:7430`.

## Offline installer (for a machine with nothing pre-installed)

`installer/` builds single-file, fully offline installers that bundle
Python, every dependency, Ollama + both models, Tesseract OCR, and the
Argos Translate language packages - no admin rights and **no internet
connection** needed on the target machine. See `installer/README.md` for
build instructions and `installer/VERIFICATION_REPORT.md` for a real
uninstall/reinstall + network-monitoring test proving it makes zero
outbound network calls.

- Windows: `installer/windows/AEGIS_Setup.exe` (+ sibling `AEGIS_Setup.dat`)
- Linux: `installer/linux/AEGIS_Setup.run`

## Key capabilities

- **Multi-format ingestion**: PDF, DOCX, PPTX, XLSX, HTML, TXT/MD/CSV,
  images (JPEG/PNG/BMP/TIFF) with OCR, corporate databases
  (SQLite/`.sql` dumps), code/firmware archives, and `.zip` bundles of any
  of the above.
- **Confidence-scored answers**: every RAG response is scored from
  retrieval strength + cross-source agreement, classifies each claim as
  **Known / Inferred / Uncertain**, and says "not enough information"
  instead of guessing when evidence is weak.
- **Persistent conversation memory**: conversations survive restarts and
  feed prior turns back into context.
- **Architecture/code insight extraction**: firmware modules, comm
  interfaces (UART/I2C/SPI/CAN/Modbus/...), dependency manifests, and
  best-effort attack-surface flags for uploaded code.
- **Handwritten-annotation detection**: diffs a PDF's embedded text layer
  against re-OCR'd page images to isolate likely handwritten overlays.
- **Cultural/language bias coverage**: per-document language detection,
  a corpus-wide coverage audit, and an OFF/SUGGESTIVE/PROACTIVE policy.
- **Offline translation**: German/French/Japanese/Chinese -> English via
  bundled Argos Translate packages, with source provenance. `setup.bat`/
  `setup.sh` install the language packages automatically (needs internet
  once, to download them); after that, translation runs fully offline.
  If you skipped setup or need to (re)install them manually, run
  `python scripts/install_translation_packages.py`. The offline installer
  instead bundles pre-downloaded packages so the target machine never
  needs a connection at all.
- **User profile adaptation**: tracks preferred answer style and frequent
  topics, and can proactively suggest related material.
- **Best-effort schematic grounding**: OCR label boxes + Hough-transform
  line detection clustered into a simple component-adjacency graph.
- Existing from the original build: hybrid search, entity/NER extraction,
  a knowledge graph view, an audit log, CVE/NVD import, and HTML report
  export.

## Testing

```bash
.venv\Scripts\python -m pytest tests/ -q      # Windows
.venv/bin/python -m pytest tests/ -q          # Linux/macOS
```

`tests/sample_data/generate_samples.py` programmatically generates a small
fixture file for every supported input type (PDF, DOCX, PPTX, XLSX, CSV,
TXT/MD, HTML, JPEG/PNG/BMP/TIFF including a synthetic schematic and a
handwritten-note-style scan, a SQLite DB, a `.sql` dump, and a code `.zip`)
so the full pipeline can be exercised with no network access.
