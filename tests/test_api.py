"""
AEGIS backend test suite.
Run from the project root:  pytest tests/ -v
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest


# Shared fixtures (tmp_data_dir, client, collection_id) now live in
# tests/conftest.py so they can be reused by tests/test_features.py too.


# ── Health ────────────────────────────────────────────────────────────────────

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── Collections ───────────────────────────────────────────────────────────────

def test_create_collection(client):
    r = client.post("/api/collections", json={"name": "Alpha", "description": "test"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Alpha"
    assert "id" in data


def test_list_collections(client):
    r = client.get("/api/collections")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_collection(client, collection_id):
    r = client.get(f"/api/collections/{collection_id}")
    assert r.status_code == 200
    assert r.json()["id"] == collection_id


def test_get_collection_not_found(client):
    r = client.get("/api/collections/nonexistent-id")
    assert r.status_code == 404


def test_delete_collection(client):
    r = client.post("/api/collections", json={"name": "ToDelete"})
    cid = r.json()["id"]
    r2 = client.delete(f"/api/collections/{cid}")
    assert r2.status_code == 204
    r3 = client.get(f"/api/collections/{cid}")
    assert r3.status_code == 404


# ── Documents ─────────────────────────────────────────────────────────────────

def test_ingest_txt_file(client, collection_id):
    content = b"This document discusses the Siemens S7-1500 PLC CVE-2023-44487 vulnerability."
    r = client.post(
        "/api/documents/ingest",
        data={"collection_id": collection_id},
        files=[("files", ("test_doc.txt", content, "text/plain"))],
    )
    assert r.status_code == 202
    data = r.json()
    assert data["queued"] == 1
    assert len(data["doc_ids"]) == 1
    return data["doc_ids"][0]


def test_list_documents(client, collection_id):
    r = client.get(f"/api/documents?collection_id={collection_id}")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_document(client, collection_id):
    # ingest a doc and fetch it
    content = b"STM32F407VGT6 microcontroller datasheet from STMicroelectronics."
    r = client.post(
        "/api/documents/ingest",
        data={"collection_id": collection_id},
        files=[("files", ("stm32.txt", content, "text/plain"))],
    )
    doc_id = r.json()["doc_ids"][0]
    r2 = client.get(f"/api/documents/{doc_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == doc_id


def test_get_document_not_found(client):
    r = client.get("/api/documents/does-not-exist")
    assert r.status_code == 404


def test_ingest_wrong_collection(client):
    r = client.post(
        "/api/documents/ingest",
        data={"collection_id": "bad-collection-id"},
        files=[("files", ("x.txt", b"hello", "text/plain"))],
    )
    assert r.status_code == 404


# ── Search ────────────────────────────────────────────────────────────────────

def test_search_keyword(client, collection_id):
    r = client.post("/api/search", json={
        "query": "Siemens",
        "collection_id": collection_id,
        "mode": "keyword",
        "limit": 10,
    })
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_search_semantic_no_ollama(client, collection_id):
    """Semantic search falls back gracefully if Ollama is offline."""
    r = client.post("/api/search", json={
        "query": "microcontroller vulnerability",
        "collection_id": collection_id,
        "mode": "semantic",
        "limit": 5,
    })
    assert r.status_code == 200   # returns empty list, not 500


def test_search_hybrid(client, collection_id):
    r = client.post("/api/search", json={
        "query": "STM32 microcontroller",
        "collection_id": collection_id,
        "mode": "hybrid",
        "limit": 10,
    })
    assert r.status_code == 200


def test_suggest(client, collection_id):
    r = client.get(f"/api/search/suggest?q=Siem&collection_id={collection_id}")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_entities_endpoint(client, collection_id):
    r = client.get(f"/api/search/entities?collection_id={collection_id}")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── AI status ─────────────────────────────────────────────────────────────────

def test_ai_status(client):
    r = client.get("/api/ai/status")
    assert r.status_code == 200
    data = r.json()
    assert "ollama_online" in data


def test_ai_models(client):
    r = client.get("/api/ai/models")
    assert r.status_code == 200
    assert "models" in r.json()


# ── Annotations ───────────────────────────────────────────────────────────────

def test_create_annotation(client, collection_id):
    # Need a real doc_id
    content = b"PROFINET protocol implementation notes."
    r = client.post(
        "/api/documents/ingest",
        data={"collection_id": collection_id},
        files=[("files", ("proto.txt", content, "text/plain"))],
    )
    doc_id = r.json()["doc_ids"][0]

    r2 = client.post("/api/annotations", json={
        "doc_id": doc_id,
        "kind": "note",
        "note": "Important finding about PROFINET",
        "colour": "yellow",
    })
    assert r2.status_code == 201
    data = r2.json()
    assert data["kind"] == "note"
    return data["id"]


def test_list_annotations(client, collection_id):
    r = client.get(f"/api/annotations?collection_id={collection_id}")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_annotation_bad_doc(client):
    r = client.post("/api/annotations", json={
        "doc_id": "nonexistent-doc",
        "kind": "bookmark",
    })
    assert r.status_code == 404


# ── Graph ─────────────────────────────────────────────────────────────────────

def test_graph_nodes(client, collection_id):
    r = client.get(f"/api/graph/nodes?collection_id={collection_id}")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_graph_edges(client, collection_id):
    r = client.get(f"/api/graph/edges?collection_id={collection_id}")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_graph_export_json(client, collection_id):
    r = client.get(f"/api/graph/export?fmt=json&collection_id={collection_id}")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data
    assert "edges" in data


# ── Reports ───────────────────────────────────────────────────────────────────

def test_report_export(client, collection_id):
    r = client.get(f"/api/reports/collection/{collection_id}")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "AEGIS" in r.text


def test_report_not_found(client):
    r = client.get("/api/reports/collection/no-such-collection")
    assert r.status_code == 404


# ── Audit ─────────────────────────────────────────────────────────────────────

def test_audit_log(client):
    r = client.get("/api/audit?limit=20")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── Chunking unit test ────────────────────────────────────────────────────────

def test_chunk_text():
    from services.ingest import _chunk_text
    long_text = " ".join(["word"] * 2000)
    chunks = _chunk_text(long_text, max_tokens=100, overlap=10)
    assert len(chunks) > 1
    for c in chunks:
        words = c.split()
        assert len(words) <= 120   # max_tokens + overlap tolerance


def test_chunk_short_text():
    from services.ingest import _chunk_text
    text = "This is a short sentence."
    chunks = _chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0] == text


# ── NER unit test ────────────────────────────────────────────────────────────

def test_ner_cve_extraction():
    from services.ingest import _extract_entities
    text = "The device is affected by CVE-2023-44487 and CVE-2021-34527."
    entities = _extract_entities(text)
    cves = [e["value"] for e in entities if e["entity_type"] == "CVE"]
    assert "CVE-2023-44487" in cves
    assert "CVE-2021-34527" in cves


def test_ner_manufacturer():
    from services.ingest import _extract_entities
    text = "This Texas Instruments chip uses Modbus protocol."
    entities = _extract_entities(text)
    types = {e["entity_type"] for e in entities}
    assert "MANUFACTURER" in types
    assert "PROTOCOL" in types


def test_ner_part_number():
    from services.ingest import _extract_entities
    text = "Install component STM32F407VGT6 on the PCB."
    entities = _extract_entities(text)
    parts = [e["value"] for e in entities if e["entity_type"] == "PART_NUMBER"]
    assert any("STM32" in p for p in parts)


# ── RRF unit test ─────────────────────────────────────────────────────────────

def test_rrf_merge():
    from services.search_engine import _rrf
    list_a = [
        {"chunk_id": "A", "doc_id": "d1", "doc_title": "t", "filename": "f",
         "page_number": 1, "text": "x", "score": 0.9, "source": "keyword"},
        {"chunk_id": "B", "doc_id": "d2", "doc_title": "t", "filename": "f",
         "page_number": 1, "text": "x", "score": 0.8, "source": "keyword"},
    ]
    list_b = [
        {"chunk_id": "B", "doc_id": "d2", "doc_title": "t", "filename": "f",
         "page_number": 1, "text": "x", "score": 0.95, "source": "semantic"},
        {"chunk_id": "C", "doc_id": "d3", "doc_title": "t", "filename": "f",
         "page_number": 1, "text": "x", "score": 0.7, "source": "semantic"},
    ]
    merged = _rrf([list_a, list_b])
    # B appears in both lists so should rank highest
    assert merged[0]["chunk_id"] == "B"
    assert len(merged) == 3
