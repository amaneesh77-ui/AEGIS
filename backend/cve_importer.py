"""
CVE JSON Importer for AEGIS
============================
Handles the NIST NVD JSON feed format:
  - NVD JSON 1.1  (CVE_Items array)
  - NVD JSON 2.0  (vulnerabilities array)
  - Single CVE JSON objects
  - Arrays of CVE objects

Run standalone:
  python cve_importer.py --file nvdcve-1.1-2023.json --collection-id <id>

Or import and call from other scripts:
  from cve_importer import import_cve_file
"""

import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# Allow running from project root or backend/
sys.path.insert(0, str(Path(__file__).parent))

from config import UPLOADS_DIR
from database import get_db, init_db
from services.ingest import (
    _chunk_text, _embed_texts, _extract_entities,
    _get_chroma, _get_whoosh_index,
)
from whoosh.writing import AsyncWriter


# ── CVE text extraction ───────────────────────────────────────────────────────

def _parse_nvd_v1(item: dict) -> dict:
    """Parse a single CVE_Items entry (NVD JSON 1.1)."""
    cve   = item.get("cve", {})
    cve_id = cve.get("CVE_data_meta", {}).get("ID", "Unknown")

    # Description
    descs = cve.get("description", {}).get("description_data", [])
    desc  = next((d["value"] for d in descs if d.get("lang") == "en"), "")

    # CVSS scores
    impact = item.get("impact", {})
    cvss3  = impact.get("baseMetricV3", {}).get("cvssV3", {})
    cvss2  = impact.get("baseMetricV2", {}).get("cvssV2", {})
    severity = (cvss3.get("baseSeverity") or cvss2.get("baseSeverity") or "").upper()
    score    = cvss3.get("baseScore") or cvss2.get("baseScore") or ""
    vector   = cvss3.get("vectorString") or cvss2.get("vectorString") or ""

    # Affected products (CPE)
    cpe_nodes = item.get("configurations", {}).get("nodes", [])
    products: list[str] = []
    for node in cpe_nodes:
        for match in node.get("cpe_match", []):
            uri = match.get("cpe23Uri", "")
            parts = uri.split(":")
            if len(parts) > 5:
                vendor  = parts[3].replace("_", " ").title()
                product = parts[4].replace("_", " ").title()
                version = parts[5] if parts[5] not in ("-", "*") else ""
                entry   = f"{vendor} {product}"
                if version:
                    entry += f" {version}"
                if entry.strip() not in products:
                    products.append(entry.strip())

    # References
    refs = cve.get("references", {}).get("reference_data", [])
    ref_urls = [r["url"] for r in refs[:5]]

    published  = item.get("publishedDate", "")[:10]
    modified   = item.get("lastModifiedDate", "")[:10]

    return {
        "cve_id":    cve_id,
        "published": published,
        "modified":  modified,
        "severity":  severity,
        "score":     str(score),
        "vector":    vector,
        "description": desc,
        "products":  products,
        "references": ref_urls,
    }


def _parse_nvd_v2(item: dict) -> dict:
    """Parse a single vulnerabilities entry (NVD JSON 2.0)."""
    cve    = item.get("cve", {})
    cve_id = cve.get("id", "Unknown")

    # Description
    descs = cve.get("descriptions", [])
    desc  = next((d["value"] for d in descs if d.get("lang") == "en"), "")

    # CVSS
    metrics  = cve.get("metrics", {})
    cvss31   = metrics.get("cvssMetricV31", [{}])[0].get("cvssData", {}) if metrics.get("cvssMetricV31") else {}
    cvss30   = metrics.get("cvssMetricV30", [{}])[0].get("cvssData", {}) if metrics.get("cvssMetricV30") else {}
    cvss2    = metrics.get("cvssMetricV2",  [{}])[0].get("cvssData", {}) if metrics.get("cvssMetricV2")  else {}
    cvss_data = cvss31 or cvss30 or cvss2
    severity  = cvss_data.get("baseSeverity", "").upper()
    score     = cvss_data.get("baseScore", "")
    vector    = cvss_data.get("vectorString", "")

    # Affected products
    affected = cve.get("configurations", [])
    products: list[str] = []
    for config in affected:
        for node in config.get("nodes", []):
            for cpe in node.get("cpeMatch", []):
                criteria = cpe.get("criteria", "")
                parts = criteria.split(":")
                if len(parts) > 5:
                    vendor  = parts[3].replace("_", " ").title()
                    product = parts[4].replace("_", " ").title()
                    version = parts[5] if parts[5] not in ("-", "*") else ""
                    entry   = f"{vendor} {product}"
                    if version:
                        entry += f" {version}"
                    if entry.strip() not in products:
                        products.append(entry.strip())

    refs     = [r["url"] for r in cve.get("references", [])[:5]]
    published = cve.get("published", "")[:10]
    modified  = cve.get("lastModified", "")[:10]

    return {
        "cve_id":     cve_id,
        "published":  published,
        "modified":   modified,
        "severity":   severity,
        "score":      str(score),
        "vector":     vector,
        "description": desc,
        "products":   products,
        "references": refs,
    }


def _cve_to_text(c: dict) -> str:
    """Convert a parsed CVE dict to human-readable indexable text."""
    lines = [
        f"CVE ID: {c['cve_id']}",
        f"Published: {c['published']}  Last modified: {c['modified']}",
    ]
    if c.get("severity") or c.get("score"):
        lines.append(f"Severity: {c['severity']}  CVSS Score: {c['score']}")
    if c.get("vector"):
        lines.append(f"Vector: {c['vector']}")
    lines.append("")
    lines.append(f"Description:\n{c['description']}")

    if c.get("products"):
        lines.append("")
        lines.append("Affected products:")
        for p in c["products"][:20]:
            lines.append(f"  - {p}")

    if c.get("references"):
        lines.append("")
        lines.append("References:")
        for r in c["references"]:
            lines.append(f"  - {r}")

    return "\n".join(lines)


def _detect_schema(data: dict | list) -> str:
    """Return 'v1', 'v2', 'single', or 'array'."""
    if isinstance(data, list):
        return "array"
    if "CVE_Items" in data:
        return "v1"
    if "vulnerabilities" in data:
        return "v2"
    if "cve" in data or "CVE_data_meta" in data:
        return "single"
    return "unknown"


def _iter_cves(data: dict | list):
    """Yield parsed CVE dicts from any supported JSON structure."""
    schema = _detect_schema(data)
    if schema == "v1":
        for item in data.get("CVE_Items", []):
            yield _parse_nvd_v1(item)
    elif schema == "v2":
        for item in data.get("vulnerabilities", []):
            yield _parse_nvd_v2(item)
    elif schema == "single":
        # Wrap in v2-style envelope if needed
        if "cve" in data:
            yield _parse_nvd_v2(data)
        else:
            yield _parse_nvd_v1({"cve": data})
    elif schema == "array":
        for item in data:
            if isinstance(item, dict):
                if "CVE_data_meta" in item.get("cve", {}):
                    yield _parse_nvd_v1(item)
                else:
                    yield _parse_nvd_v2(item)
    else:
        raise ValueError(
            "Unrecognised JSON schema. Expected NVD JSON 1.1 (CVE_Items), "
            "NVD JSON 2.0 (vulnerabilities), or an array of CVE objects."
        )


# ── Main import function ──────────────────────────────────────────────────────

def import_cve_file(
    json_path: str | Path,
    collection_id: str,
    batch_size: int = 100,
    verbose: bool = True,
) -> dict:
    """
    Import a CVE JSON file into AEGIS.

    Returns a summary dict:
      {total, indexed, skipped, errors}
    """
    json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"File not found: {json_path}")

    init_db()
    db = get_db()

    # Verify collection
    if not db.execute("SELECT 1 FROM collections WHERE id=?", (collection_id,)).fetchone():
        db.close()
        raise ValueError(f"Collection '{collection_id}' not found. Create it in AEGIS first.")

    if verbose:
        print(f"\n[AEGIS CVE Importer] Loading {json_path.name} …")

    with open(json_path, encoding="utf-8") as f:
        raw = json.load(f)

    cves     = list(_iter_cves(raw))
    total    = len(cves)
    indexed  = 0
    skipped  = 0
    errors   = 0

    if verbose:
        print(f"[AEGIS CVE Importer] Found {total} CVEs. Starting import …\n")

    ix = _get_whoosh_index()
    chroma = _get_chroma()
    col_name = f"col_{collection_id.replace('-','')[:40]}"
    try:
        chroma_col = chroma.get_or_create_collection(
            name=col_name, metadata={"hnsw:space": "cosine"}
        )
    except Exception:
        chroma_col = chroma.get_or_create_collection(name="aegis_default")

    # Collect batch buffers
    chunk_rows:    list = []
    chroma_ids:    list = []
    chroma_docs:   list = []
    chroma_metas:  list = []
    chroma_embeds: list = []
    entity_rows:   list = []

    def _flush_batch():
        nonlocal indexed
        if not chunk_rows:
            return
        db.executemany(
            "INSERT OR IGNORE INTO chunks VALUES (?,?,?,?,?,?)", chunk_rows
        )
        writer = AsyncWriter(ix)
        for (cid, doc_id, ci, page, text, _) in chunk_rows:
            writer.add_document(
                chunk_id=cid, doc_id=doc_id,
                collection_id=collection_id,
                filename="CVE Database",
                title=text[:80],
                body=text,
                manufacturer="", part_number="",
                doc_type="advisory", page_number=page,
            )
        writer.commit()
        if any(e[0] != 0.0 for e in chroma_embeds):
            chroma_col.add(
                ids=chroma_ids, documents=chroma_docs,
                metadatas=chroma_metas, embeddings=chroma_embeds,
            )
        else:
            chroma_col.add(
                ids=chroma_ids, documents=chroma_docs, metadatas=chroma_metas,
            )
        if entity_rows:
            db.executemany(
                "INSERT OR IGNORE INTO entities VALUES (?,?,?,?,?,?)", entity_rows
            )
        db.commit()
        indexed += len(set(r[1] for r in chunk_rows))  # distinct doc_ids
        chunk_rows.clear()
        chroma_ids.clear(); chroma_docs.clear()
        chroma_metas.clear(); chroma_embeds.clear()
        entity_rows.clear()

    for i, c in enumerate(cves):
        try:
            cve_id = c["cve_id"]
            text   = _cve_to_text(c)

            # Check if already imported (by CVE ID stored as part_number)
            exists = db.execute(
                "SELECT id FROM documents WHERE part_number=? AND collection_id=?",
                (cve_id, collection_id),
            ).fetchone()
            if exists:
                skipped += 1
                continue

            # Insert document record
            doc_id    = str(uuid.uuid4())
            file_hash = hashlib.sha256(text.encode()).hexdigest()
            now       = int(time.time())

            db.execute(
                """INSERT INTO documents
                   (id,collection_id,filename,file_path,file_hash,file_size,
                    mime_type,title,doc_type,manufacturer,part_number,
                    word_count,ingest_status,indexed_at,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (doc_id, collection_id,
                 f"{cve_id}.json", f"[CVE:{cve_id}]",
                 file_hash, len(text.encode()),
                 "application/json",
                 f"{cve_id} - {c['description'][:80]}",
                 "advisory",
                 "",           # manufacturer
                 cve_id,       # part_number reused for CVE ID lookup
                 len(text.split()),
                 "indexed", now, now),
            )

            # Chunk and embed
            chunks = _chunk_text(text, max_tokens=400, overlap=40)
            if not chunks:
                chunks = [text[:2000]]

            embeddings = _embed_texts(chunks)

            for ci, (chunk_text, emb) in enumerate(zip(chunks, embeddings)):
                cid = str(uuid.uuid4())
                chunk_rows.append((cid, doc_id, ci, 1, chunk_text, cid))
                chroma_ids.append(cid)
                chroma_docs.append(chunk_text)
                chroma_metas.append({
                    "doc_id": doc_id,
                    "collection_id": collection_id,
                    "chunk_index": ci,
                    "page_number": 1,
                    "doc_type": "advisory",
                    "filename": f"{cve_id}.json",
                })
                chroma_embeds.append(emb)

            # Entities - always add the CVE ID itself
            entity_rows.append((
                str(uuid.uuid4()), doc_id, "CVE", cve_id, 1.0,
                c["description"][:200],
            ))
            # Severity as entity
            if c.get("severity"):
                entity_rows.append((
                    str(uuid.uuid4()), doc_id, "VULNERABILITY_CLASS",
                    f"CVSS {c['severity']}", 0.9, cve_id,
                ))
            # Affected products as COMPONENT entities
            for p in c.get("products", [])[:5]:
                entity_rows.append((
                    str(uuid.uuid4()), doc_id, "COMPONENT",
                    p, 0.85, cve_id,
                ))

            # Flush in batches
            if len(chunk_rows) >= batch_size:
                _flush_batch()

            if verbose and (i + 1) % 500 == 0:
                print(f"  … processed {i+1}/{total} CVEs")

        except Exception as exc:
            errors += 1
            if verbose:
                print(f"  [WARN] Skipped CVE {i}: {exc}")

    _flush_batch()
    db.close()

    summary = {
        "total":   total,
        "indexed": indexed,
        "skipped": skipped,
        "errors":  errors,
    }
    if verbose:
        print(f"\n[AEGIS CVE Importer] Complete.")
        print(f"  Total CVEs in file : {total}")
        print(f"  Newly indexed      : {indexed}")
        print(f"  Already existed    : {skipped}")
        print(f"  Errors             : {errors}")
    return summary


# ── Router endpoint ───────────────────────────────────────────────────────────

from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form
from fastapi import HTTPException
import tempfile, os

cve_router = APIRouter(prefix="/api/cve", tags=["cve"])


@cve_router.post("/import")
async def import_cve_endpoint(
    background_tasks: BackgroundTasks,
    collection_id: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload a CVE JSON file and import it into a collection."""
    db = get_db()
    if not db.execute("SELECT 1 FROM collections WHERE id=?", (collection_id,)).fetchone():
        db.close()
        raise HTTPException(status_code=404, detail="Collection not found")
    db.close()

    content = await file.read()
    dest = UPLOADS_DIR / collection_id
    dest.mkdir(parents=True, exist_ok=True)
    tmp_path = dest / f"cve_import_{int(time.time())}_{file.filename}"
    tmp_path.write_bytes(content)

    # Run import in background
    background_tasks.add_task(_bg_import, str(tmp_path), collection_id)

    return {
        "message": f"CVE import queued for '{file.filename}'",
        "file_size_mb": round(len(content) / 1_048_576, 2),
        "collection_id": collection_id,
    }


def _bg_import(path: str, collection_id: str):
    try:
        import_cve_file(path, collection_id, verbose=False)
    except Exception as e:
        print(f"[CVE Import Error] {e}")


@cve_router.get("/stats")
def cve_stats(collection_id: str = None):
    """Summary statistics for CVE entities in the database."""
    db = get_db()
    sql = """
        SELECT
            COUNT(DISTINCT e.value)   AS unique_cves,
            COUNT(DISTINCT e.doc_id)  AS cve_documents,
            COUNT(*)                  AS total_mentions
        FROM entities e
        JOIN documents d ON d.id = e.doc_id
        WHERE e.entity_type = 'CVE'
    """
    params: list = []
    if collection_id:
        sql += " AND d.collection_id=?"
        params.append(collection_id)

    row = db.execute(sql, params).fetchone()

    severity_rows = db.execute("""
        SELECT e.value, COUNT(*) as cnt
        FROM entities e
        JOIN documents d ON d.id = e.doc_id
        WHERE e.entity_type = 'VULNERABILITY_CLASS'
        GROUP BY e.value ORDER BY cnt DESC
    """).fetchall()

    db.close()
    return {
        "unique_cves":     row["unique_cves"],
        "cve_documents":   row["cve_documents"],
        "total_mentions":  row["total_mentions"],
        "by_severity":     [dict(r) for r in severity_rows],
    }


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import a CVE JSON file into an AEGIS collection"
    )
    parser.add_argument("--file",          required=True, help="Path to CVE JSON file")
    parser.add_argument("--collection-id", required=True, help="AEGIS collection UUID")
    parser.add_argument("--batch-size",    type=int, default=100,
                        help="Flush to DB every N CVEs (default 100)")
    args = parser.parse_args()

    result = import_cve_file(
        json_path=args.file,
        collection_id=args.collection_id,
        batch_size=args.batch_size,
        verbose=True,
    )
    sys.exit(0 if result["errors"] == 0 else 1)
