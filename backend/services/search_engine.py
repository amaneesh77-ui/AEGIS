"""
Hybrid search: BM25 (Whoosh) + semantic (ChromaDB) merged via RRF.
"""

from __future__ import annotations
from typing import List, Optional
import re

import chromadb
import httpx
from whoosh import index as whoosh_index
from whoosh.qparser import MultifieldParser, OrGroup, AndGroup
from whoosh.query import Term, And

from config import (
    CHROMA_DIR, WHOOSH_DIR,
    OLLAMA_BASE_URL, EMBEDDING_MODEL,
)
from services.ingest import _get_whoosh_index, _get_chroma, WHOOSH_SCHEMA

_CVE_ID_RE = re.compile(r'^CVE-\d{4}-\d{4,7}$', re.IGNORECASE)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _embed_query(query: str) -> Optional[List[float]]:
    try:
        r = httpx.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": query},
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json()["embedding"]
    except Exception:
        return None


def _rrf(lists: List[List[dict]], k: int = 60) -> List[dict]:
    """Reciprocal Rank Fusion across multiple ranked lists keyed by chunk_id."""
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}
    for lst in lists:
        for rank, hit in enumerate(lst):
            cid = hit["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            if cid not in items:
                items[cid] = hit
    merged = sorted(items.values(), key=lambda h: scores[h["chunk_id"]], reverse=True)
    for h in merged:
        h["score"] = round(scores[h["chunk_id"]], 6)
    return merged


# ── Exact CVE ID lookup ───────────────────────────────────────────────────────

def _exact_cve_lookup(cve_id: str, collection_id: Optional[str] = None) -> List[dict]:
    """Direct DB lookup when query is a bare CVE ID. Returns empty list if not found."""
    from database import get_db
    db = get_db()
    sql = "SELECT d.id, d.title, d.filename FROM documents d WHERE d.part_number=?"
    params: list = [cve_id.upper()]
    if collection_id:
        sql += " AND d.collection_id=?"
        params.append(collection_id)
    doc = db.execute(sql, params).fetchone()
    if not doc:
        db.close()
        return []
    chunks = db.execute(
        "SELECT id, text, chunk_index, page_number FROM chunks WHERE doc_id=? ORDER BY chunk_index",
        (doc["id"],),
    ).fetchall()
    db.close()
    return [
        {
            "chunk_id":   c["id"],
            "doc_id":     doc["id"],
            "doc_title":  doc["title"] or doc["filename"],
            "filename":   doc["filename"],
            "page_number": c["page_number"],
            "text":       c["text"][:500],
            "score":      1.0,
            "source":     "exact",
        }
        for c in chunks
    ]


# ── Keyword search ────────────────────────────────────────────────────────────

def keyword_search(
    query: str,
    collection_id: Optional[str] = None,
    limit: int = 30,
    doc_type: Optional[str] = None,
) -> List[dict]:
    try:
        ix = _get_whoosh_index()
        # Try AND first (all terms must match) - fall back to OR if no results
        results = []
        with ix.searcher() as s:
            for group in (AndGroup, OrGroup):
                parser = MultifieldParser(
                    ["title", "body", "manufacturer", "part_number"],
                    schema=ix.schema,
                    group=group,
                )
                hits = s.search(parser.parse(query), limit=limit * 2)
                for hit in hits:
                    if collection_id and hit.get("collection_id") != collection_id:
                        continue
                    if doc_type and hit.get("doc_type") != doc_type:
                        continue
                    results.append({
                        "chunk_id": hit["chunk_id"],
                        "doc_id": hit["doc_id"],
                        "doc_title": hit.get("title", hit.get("filename", "")),
                        "filename": hit.get("filename", ""),
                        "page_number": hit.get("page_number", 0),
                        "text": hit.highlights("body") or "",
                        "score": hit.score or 0.0,
                        "source": "keyword",
                    })
                if results:
                    break   # AND had results - no need for OR fallback
        return results[:limit]
    except Exception:
        return []


# ── Semantic search ───────────────────────────────────────────────────────────

def semantic_search(
    query: str,
    collection_id: Optional[str] = None,
    limit: int = 30,
    doc_type: Optional[str] = None,
) -> List[dict]:
    embedding = _embed_query(query)
    if not embedding:
        return []

    try:
        chroma = _get_chroma()
        where: Optional[dict] = None
        if collection_id:
            where = {"collection_id": {"$eq": collection_id}}

        col_name = f"col_{collection_id.replace('-', '')[:40]}" if collection_id else "aegis_default"
        try:
            col = chroma.get_collection(col_name)
        except Exception:
            return []

        results = col.query(
            query_embeddings=[embedding],
            n_results=min(limit * 2, 100),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        hits = []
        ids      = results.get("ids", [[]])[0]
        docs     = results.get("documents", [[]])[0]
        metas    = results.get("metadatas", [[]])[0]
        dists    = results.get("distances", [[]])[0]

        # Discard results with cosine similarity below threshold (irrelevant noise)
        MIN_SIMILARITY = 0.35
        for cid, doc_text, meta, dist in zip(ids, docs, metas, dists):
            similarity = float(1 - dist)
            if similarity < MIN_SIMILARITY:
                continue
            if doc_type and meta.get("doc_type") != doc_type:
                continue
            hits.append({
                "chunk_id": cid,
                "doc_id": meta.get("doc_id", ""),
                "doc_title": meta.get("filename", ""),
                "filename": meta.get("filename", ""),
                "page_number": meta.get("page_number", 0),
                "text": doc_text[:500],
                "score": similarity,
                "source": "semantic",
            })
        return hits[:limit]
    except Exception:
        return []


# ── Hybrid search (RRF) ───────────────────────────────────────────────────────

def hybrid_search(
    query: str,
    collection_id: Optional[str] = None,
    limit: int = 20,
    doc_type: Optional[str] = None,
    mode: str = "hybrid",
) -> List[dict]:
    # Exact CVE ID match - bypass all fuzzy search
    if _CVE_ID_RE.match(query.strip()):
        exact = _exact_cve_lookup(query.strip(), collection_id)
        if exact:
            return exact[:limit]
        # Not in DB - return empty with clear signal rather than junk results
        return []

    if mode == "keyword":
        results = keyword_search(query, collection_id, limit, doc_type)
        for r in results:
            r["source"] = "keyword"
        return results

    if mode == "semantic":
        results = semantic_search(query, collection_id, limit, doc_type)
        for r in results:
            r["source"] = "semantic"
        return results

    kw  = keyword_search(query,  collection_id, limit * 2, doc_type)
    sem = semantic_search(query, collection_id, limit * 2, doc_type)

    merged = _rrf([kw, sem])[:limit]
    for r in merged:
        r["source"] = "hybrid"
    return merged


# ── Full chunk text retrieval for RAG ─────────────────────────────────────────

def get_chunks_for_rag(
    query: str,
    collection_id: Optional[str] = None,
    max_chunks: int = 8,
) -> List[dict]:
    """Return full chunk text (not highlights) for RAG context assembly."""
    from database import get_db
    hits = hybrid_search(query, collection_id, limit=max_chunks * 2)

    db = get_db()
    enriched = []
    for h in hits[:max_chunks]:
        row = db.execute(
            "SELECT c.text, d.title, d.filename FROM chunks c "
            "JOIN documents d ON d.id = c.doc_id WHERE c.id=?",
            (h["chunk_id"],),
        ).fetchone()
        if row:
            enriched.append({
                **h,
                "text": row["text"],
                "doc_title": row["title"] or row["filename"],
            })
    db.close()
    return enriched
