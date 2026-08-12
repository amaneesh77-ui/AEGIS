import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH  = DATA_DIR / "aegis.db"
CHROMA_DIR  = DATA_DIR / "chroma"
WHOOSH_DIR  = DATA_DIR / "whoosh"
UPLOADS_DIR = DATA_DIR / "uploads"
MODELS_DIR  = DATA_DIR / "models"          # bundled offline models (translation, etc.)
TRANSLATE_MODELS_DIR = MODELS_DIR / "translate"

OLLAMA_BASE_URL    = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DEFAULT_LLM_MODEL  = os.getenv("AEGIS_LLM_MODEL", "llama3.1:8b")
EMBEDDING_MODEL    = os.getenv("AEGIS_EMBED_MODEL", "nomic-embed-text")

MAX_CHUNK_TOKENS = 512
CHUNK_OVERLAP    = 64
MAX_CONTEXT_CHUNKS = 4

# ── Confidence / validation thresholds ────────────────────────────────────────
CONFIDENCE_HIGH_THRESHOLD   = float(os.getenv("AEGIS_CONF_HIGH", "0.62"))
CONFIDENCE_MEDIUM_THRESHOLD = float(os.getenv("AEGIS_CONF_MEDIUM", "0.42"))
MIN_SOURCES_FOR_HIGH        = 2

# ── Conversation memory ────────────────────────────────────────────────────────
MAX_HISTORY_TURNS = int(os.getenv("AEGIS_MAX_HISTORY_TURNS", "6"))

# ── Cultural / language bias detection ────────────────────────────────────────
# off | suggestive | proactive  (per HMGCC Q&A Q16)
DEFAULT_BIAS_POLICY = os.getenv("AEGIS_BIAS_POLICY", "suggestive")
SUPPORTED_TRANSLATE_LANGS = ["de", "fr", "ja", "zh"]   # German, French, Japanese, Chinese (Q114)

for _d in [DATA_DIR, CHROMA_DIR, WHOOSH_DIR, UPLOADS_DIR, MODELS_DIR, TRANSLATE_MODELS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# Argos Translate reads ARGOS_PACKAGES_DIR at import time, so it must be set
# (here, or via .env / a real env var, which take precedence since they're
# already in os.environ before this runs) before anything imports
# `argostranslate`. Defaulting it to TRANSLATE_MODELS_DIR means offline
# translation self-configures for local dev with no .env required; the
# installer overrides this explicitly with its own install-dir path.
os.environ.setdefault("ARGOS_PACKAGES_DIR", str(TRANSLATE_MODELS_DIR / "packages"))
Path(os.environ["ARGOS_PACKAGES_DIR"]).mkdir(parents=True, exist_ok=True)
