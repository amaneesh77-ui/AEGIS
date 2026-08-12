"""
Tests for the Phase 2-4 gap-fill features: confidence scoring/validation,
conversation memory, corporate DB ingestion, code/architecture insight
extraction, cultural/language bias detection, offline translation, and the
best-effort schematic vision heuristic.

Run from the project root:  pytest tests/ -v
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from pathlib import Path

import pytest

SAMPLE_DIR = Path(__file__).parent / "sample_data"


# ── Confidence / validation ──────────────────────────────────────────────────

def test_retrieval_confidence_empty():
    from services.confidence import retrieval_confidence
    result = retrieval_confidence([])
    assert result["level"] == "insufficient"
    assert result["need_more_data"] is True


def test_retrieval_confidence_strong_agreement():
    from services.confidence import retrieval_confidence
    chunks = [
        {"doc_id": "d1", "score": 0.9},
        {"doc_id": "d2", "score": 0.85},
        {"doc_id": "d3", "score": 0.8},
    ]
    result = retrieval_confidence(chunks)
    assert result["level"] in ("high", "medium-high")
    assert result["distinct_sources"] == 3


def test_retrieval_confidence_weak():
    from services.confidence import retrieval_confidence
    chunks = [{"doc_id": "d1", "score": 0.1}]
    result = retrieval_confidence(chunks)
    assert result["level"] == "low"
    assert result["need_more_data"] is True


def test_validate_answer_known_vs_uncertain():
    from services.confidence import validate_answer
    chunks = [{"chunk_id": "c1", "text": "The STM32F407VGT6 is manufactured by STMicroelectronics."}]
    answer = ("The STM32F407VGT6 is manufactured by STMicroelectronics. "
              "The device also secretly controls a nuclear reactor on Mars.")
    result = validate_answer(answer, chunks)
    statuses = [c["status"] for c in result["claims"]]
    assert "known" in statuses
    assert "uncertain" in statuses
    assert result["uncertain_count"] >= 1


def test_validate_answer_refusal_is_known():
    from services.confidence import validate_answer
    result = validate_answer("I cannot find this information in the indexed documents.", [])
    assert result["claims"][0]["status"] == "known"


# ── Conversations ─────────────────────────────────────────────────────────────

def test_conversation_crud(client):
    r = client.post("/api/conversations", json={"title": "Test convo"})
    assert r.status_code == 201
    conv_id = r.json()["id"]

    r2 = client.get(f"/api/conversations/{conv_id}")
    assert r2.status_code == 200
    assert r2.json()["messages"] == []

    r3 = client.get("/api/conversations")
    assert r3.status_code == 200
    assert any(c["id"] == conv_id for c in r3.json())

    r4 = client.patch(f"/api/conversations/{conv_id}", json={"title": "Renamed"})
    assert r4.status_code == 200

    r5 = client.delete(f"/api/conversations/{conv_id}")
    assert r5.status_code == 204

    r6 = client.get(f"/api/conversations/{conv_id}")
    assert r6.status_code == 404


def test_conversation_memory_service_roundtrip(tmp_data_dir):
    from services import conversations as conv_service
    conv = conv_service.create_conversation(title="Service-level test")
    conv_service.add_message(conv["id"], "user", "What protocols does this device use?")
    conv_service.add_message(conv["id"], "assistant", "It uses Modbus.", sources=[{"doc_id": "d1"}])
    history = conv_service.get_recent_history(conv["id"])
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


# ── Corporate database ingestion ─────────────────────────────────────────────

def test_db_ingest_sqlite():
    from services.db_ingest import extract_database_text
    text, table_count = extract_database_text(SAMPLE_DIR / "corporate_assets.db")
    assert table_count >= 2
    assert "devices" in text
    assert "Mitsubishi Electric" in text


def test_db_ingest_sql_dump():
    from services.db_ingest import extract_database_text
    text, _ = extract_database_text(SAMPLE_DIR / "legacy_export.sql")
    assert "CREATE TABLE" in text.upper()
    assert "LPC1768FBD100" in text


def test_db_ingest_via_api(client, collection_id):
    with open(SAMPLE_DIR / "corporate_assets.db", "rb") as f:
        r = client.post(
            "/api/documents/ingest",
            data={"collection_id": collection_id},
            files=[("files", ("corporate_assets.db", f.read(), "application/x-sqlite3"))],
        )
    assert r.status_code == 202


# ── Code / architecture insight extraction ───────────────────────────────────

def test_code_analysis_detects_signals():
    from services.code_analysis import analyse_source
    src = (SAMPLE_DIR / "_code_src" / "server.py").read_text()
    report = analyse_source(src, "server.py")
    assert "Open network listener" in report["attack_surfaces"]
    assert "Possible hardcoded secret" in report["attack_surfaces"]


def test_code_analysis_comm_interfaces():
    from services.code_analysis import analyse_source
    src = (SAMPLE_DIR / "_code_src" / "main.c").read_text()
    report = analyse_source(src, "main.c")
    assert "UART" in report["comm_interfaces"]
    assert "I2C" in report["comm_interfaces"]


def test_code_analysis_manifest_dependencies():
    from services.code_analysis import analyse_source
    text = (SAMPLE_DIR / "_code_src" / "requirements.txt").read_text()
    report = analyse_source(text, "requirements.txt")
    assert "flask" in report["external_dependencies"]


def test_code_archive_ingest_via_api(client, collection_id):
    with open(SAMPLE_DIR / "firmware_src.zip", "rb") as f:
        r = client.post(
            "/api/documents/ingest",
            data={"collection_id": collection_id},
            files=[("files", ("firmware_src.zip", f.read(), "application/zip"))],
        )
    assert r.status_code == 202


# ── Cultural / language bias detection ───────────────────────────────────────

def test_detect_text_language_english():
    from services.bias import detect_text_language
    result = detect_text_language(
        "This is a technical datasheet describing the electrical characteristics "
        "of an industrial control system component manufactured in Germany."
    )
    assert result["language"] in ("en", "unknown")


def test_bias_policy_api(client, collection_id):
    r = client.put("/api/bias/policy", json={
        "collection_id": collection_id, "bias_policy": "proactive", "vendor_country": "Germany",
    })
    assert r.status_code == 200
    assert r.json()["bias_policy"] == "proactive"

    r2 = client.get(f"/api/bias/policy/{collection_id}")
    assert r2.status_code == 200
    assert r2.json()["vendor_country"] == "Germany"


def test_bias_audit_api(client, collection_id):
    r = client.get(f"/api/bias/audit/{collection_id}")
    assert r.status_code == 200
    assert "coverage_pct" in r.json()


def test_bias_audit_not_found(client):
    r = client.get("/api/bias/audit/no-such-collection")
    assert r.status_code == 404


# ── Offline translation ──────────────────────────────────────────────────────

def test_translate_gracefully_degrades():
    from services.translate import translate_text
    result = translate_text("Hallo Welt", target_lang="en", source_lang="de")
    assert "translated" in result
    assert result["engine"] in ("argos", "unavailable", "noop") or result["engine"].startswith("error")


def test_translate_api(client):
    r = client.post("/api/bias/translate", json={"text": "Bonjour", "target_lang": "en", "source_lang": "fr"})
    assert r.status_code == 200
    assert "translated" in r.json()


# ── Best-effort schematic vision ─────────────────────────────────────────────

def test_schematic_vision_runs_without_crashing():
    from services.schematic_vision import analyse_schematic
    from services.ingest import _find_tesseract
    tess = _find_tesseract()
    if not tess:
        pytest.skip("Tesseract not installed in this environment")
    result = analyse_schematic(SAMPLE_DIR / "sample_schematic.png", tess)
    assert "labels" in result and "connections" in result
    assert result["method"] == "heuristic-hough-ocr-proximity"


# ── User profile ──────────────────────────────────────────────────────────────

def test_profile_api(client):
    r = client.put("/api/profile", json={"answer_style": "detailed", "proactive_suggestions": True})
    assert r.status_code == 200
    r2 = client.get("/api/profile")
    assert r2.status_code == 200
    assert r2.json()["answer_style"] == "detailed"


def test_profile_topic_tracking(tmp_data_dir):
    from services import profile as profile_service
    for _ in range(4):
        profile_service.record_query_topics("What protocols does the widget-controller support?")
    topics = profile_service.frequent_topics()
    values = {t["topic"] for t in topics}
    assert "widget-controller" in values or "protocols" in values


# ── End-to-end ingest smoke test across every sample input type ─────────────

@pytest.mark.parametrize("filename", [
    "datasheet_stm32f407.pdf",
    "manual_plc_operations.docx",
    "briefing_ics_overview.pptx",
    "asset_register.xlsx",
    "forum_thread.txt",
    "release_notes.md",
    "sensor_log.csv",
    "advisory.html",
    "sample_schematic.png",
    "sample_scanned_note.png",
    "sample_photo.jpg",
    "sample_photo.bmp",
    "sample_photo.tiff",
])
def test_ingest_every_sample_type(client, collection_id, filename):
    path = SAMPLE_DIR / filename
    with open(path, "rb") as f:
        r = client.post(
            "/api/documents/ingest",
            data={"collection_id": collection_id},
            files=[("files", (filename, f.read()))],
        )
    assert r.status_code == 202
    assert r.json()["queued"] == 1
