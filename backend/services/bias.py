"""
Cultural / language bias detection and mitigation.

Desirable requirement (HMGCC Q&A Q15/16/34/76): flag when a corpus (or an
answer's supporting sources) is skewed towards a single language relative
to a product's likely country of origin, and let the researcher decide how
proactive the tool should be.

Policy levels (per Q16's example table):
  off         - no bias checking at all.
  suggestive  - flag/banner only; the user decides whether to act.
  proactive   - additionally look for a matching non-English source already
                in the corpus and offer an offline translation of it
                (see services/translate.py), with provenance.
"""

from __future__ import annotations

from collections import Counter
from typing import List, Optional

from database import get_db

try:
    from langdetect import detect_langs, DetectorFactory
    DetectorFactory.seed = 0  # deterministic results across runs
    _LANGDETECT_OK = True
except ImportError:
    _LANGDETECT_OK = False

LANGUAGE_NAMES = {
    "en": "English", "de": "German", "fr": "French", "ja": "Japanese",
    "zh-cn": "Chinese", "zh-tw": "Chinese", "nl": "Dutch", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "ru": "Russian", "ko": "Korean",
    "unknown": "Unknown",
}

# Small, extensible manufacturer -> likely origin-language lookup used to
# flag e.g. "manufacturer is German but all loaded docs are English"
# (mirrors HMGCC's own ThermoCo/Dutch example in Q16). A specific corpus can
# instead set an explicit vendor_country via collection_settings.
MANUFACTURER_ORIGIN_LANG = {
    "siemens": "de", "bosch": "de", "beckhoff": "de", "infineon": "de", "wago": "de",
    "schneider": "fr", "thales": "fr", "dassault": "fr",
    "mitsubishi": "ja", "omron": "ja", "yokogawa": "ja", "keyence": "ja", "fanuc": "ja",
    "huawei": "zh-cn", "hikvision": "zh-cn",
}

COUNTRY_TO_LANG = {
    "germany": "de", "france": "fr", "japan": "ja", "china": "zh-cn",
    "netherlands": "nl", "italy": "it", "spain": "es", "south korea": "ko",
}


def detect_text_language(text: str) -> dict:
    """Best-effort language detection for a document/chunk of text."""
    sample = (text or "").strip()[:2000]
    if not sample or not _LANGDETECT_OK:
        return {"language": "unknown", "confidence": 0.0}
    try:
        langs = detect_langs(sample)
        if not langs:
            return {"language": "unknown", "confidence": 0.0}
        best = langs[0]
        return {"language": best.lang, "confidence": round(float(best.prob), 3)}
    except Exception:
        return {"language": "unknown", "confidence": 0.0}


def tag_document_language(doc_id: str, text: str) -> dict:
    result = detect_text_language(text)
    db = get_db()
    db.execute(
        "INSERT INTO document_language (doc_id, language, confidence) VALUES (?,?,?) "
        "ON CONFLICT(doc_id) DO UPDATE SET language=excluded.language, confidence=excluded.confidence",
        (doc_id, result["language"], result["confidence"]),
    )
    db.commit()
    db.close()
    return result


def get_collection_settings(collection_id: str) -> dict:
    db = get_db()
    row = db.execute(
        "SELECT * FROM collection_settings WHERE collection_id=?", (collection_id,)
    ).fetchone()
    db.close()
    if row:
        return dict(row)
    return {"collection_id": collection_id, "bias_policy": "suggestive", "vendor_country": None}


def set_collection_settings(collection_id: str, bias_policy: str, vendor_country: Optional[str]) -> dict:
    db = get_db()
    db.execute(
        "INSERT INTO collection_settings (collection_id, bias_policy, vendor_country) VALUES (?,?,?) "
        "ON CONFLICT(collection_id) DO UPDATE SET bias_policy=excluded.bias_policy, "
        "vendor_country=excluded.vendor_country",
        (collection_id, bias_policy, vendor_country),
    )
    db.commit()
    db.close()
    return get_collection_settings(collection_id)


def corpus_language_audit(collection_id: str) -> dict:
    """Corpus-level language coverage audit (Q16: 'run a corpus level audit
    on upload producing a summary, including any bias information')."""
    db = get_db()
    rows = db.execute(
        """SELECT dl.language, COUNT(*) AS n
           FROM document_language dl
           JOIN documents d ON d.id = dl.doc_id
           WHERE d.collection_id=?
           GROUP BY dl.language""",
        (collection_id,),
    ).fetchall()
    manufacturers = db.execute(
        "SELECT DISTINCT manufacturer FROM documents WHERE collection_id=? AND manufacturer IS NOT NULL",
        (collection_id,),
    ).fetchall()
    settings = get_collection_settings(collection_id)
    db.close()

    total = sum(r["n"] for r in rows) or 1
    coverage = {
        LANGUAGE_NAMES.get(r["language"], r["language"] or "Unknown"): round(r["n"] / total * 100, 1)
        for r in rows
    }

    expected_lang = None
    if settings.get("vendor_country"):
        expected_lang = COUNTRY_TO_LANG.get(settings["vendor_country"].strip().lower())
    if not expected_lang:
        for m in manufacturers:
            mfr = (m["manufacturer"] or "").strip().lower()
            if mfr in MANUFACTURER_ORIGIN_LANG:
                expected_lang = MANUFACTURER_ORIGIN_LANG[mfr]
                break

    gap = None
    checklist: List[str] = []
    if expected_lang and expected_lang != "en":
        expected_name = LANGUAGE_NAMES.get(expected_lang, expected_lang)
        have_expected = any(r["language"] == expected_lang for r in rows)
        english_pct = coverage.get("English", 0.0)
        if not have_expected and english_pct >= 90:
            gap = (
                f"All uploaded documents for this collection are in English, but the "
                f"product/manufacturer suggests {expected_name}-language sources (e.g. "
                f"advisories, bulletins) may exist and are not yet represented here."
            )
            checklist = [
                f"Add {expected_name} security advisories",
                f"Add {expected_name} vendor bulletins / release notes",
            ]

    return {
        "collection_id": collection_id,
        "coverage_pct": coverage,
        "policy": settings.get("bias_policy", "suggestive"),
        "gap_warning": gap,
        "checklist": checklist,
    }


def coverage_label_for_chunks(chunks: List[dict]) -> Optional[dict]:
    """Per-answer language coverage label (Q16 example: 'Coverage: English 90%/Dutch 0%')."""
    if not chunks:
        return None
    db = get_db()
    doc_ids = list({c.get("doc_id") for c in chunks if c.get("doc_id")})
    if not doc_ids:
        db.close()
        return None
    placeholders = ",".join("?" for _ in doc_ids)
    rows = db.execute(
        f"SELECT language FROM document_language WHERE doc_id IN ({placeholders})",
        doc_ids,
    ).fetchall()
    db.close()
    if not rows:
        return None
    counts = Counter(r["language"] or "unknown" for r in rows)
    total = sum(counts.values()) or 1
    return {
        LANGUAGE_NAMES.get(lang, lang): round(n / total * 100, 1)
        for lang, n in counts.items()
    }
