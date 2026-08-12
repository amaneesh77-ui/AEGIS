import hashlib
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, BackgroundTasks

from config import UPLOADS_DIR
from database import get_db
from models import DocumentOut
from services.ingest import ingest_document, remove_document_from_indexes

router = APIRouter(prefix="/api/documents", tags=["documents"])
_executor = ThreadPoolExecutor(max_workers=4)


def _mime_from_suffix(suffix: str) -> str:
    m = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".ppt": "application/vnd.ms-powerpoint",
        ".html": "text/html", ".htm": "text/html",
        ".txt": "text/plain", ".md": "text/plain",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv": "text/csv",
        ".png": "image/png",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff", ".tif": "image/tiff",
        ".webp": "image/webp",
        ".db": "application/x-sqlite3", ".sqlite": "application/x-sqlite3",
        ".sqlite3": "application/x-sqlite3", ".sql": "application/sql",
        ".zip": "application/zip",
    }
    return m.get(suffix.lower(), "application/octet-stream")


@router.post("/ingest", status_code=202)
async def ingest_files(
    background_tasks: BackgroundTasks,
    collection_id: str = Form(...),
    files: List[UploadFile] = File(...),
):
    db = get_db()
    # verify collection exists
    if not db.execute("SELECT 1 FROM collections WHERE id=?", (collection_id,)).fetchone():
        db.close()
        raise HTTPException(status_code=404, detail="Collection not found")

    created_ids = []
    for upload in files:
        doc_id = str(uuid.uuid4())
        dest_dir = UPLOADS_DIR / collection_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{doc_id}_{upload.filename}"

        content = await upload.read()
        dest.write_bytes(content)

        file_hash = hashlib.sha256(content).hexdigest()
        suffix = Path(upload.filename).suffix
        mime = _mime_from_suffix(suffix)
        title = Path(upload.filename).stem.replace("_", " ").replace("-", " ").title()

        db.execute(
            """INSERT INTO documents
               (id,collection_id,filename,file_path,file_hash,file_size,
                mime_type,title,doc_type,ingest_status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, collection_id, upload.filename, str(dest),
             file_hash, len(content), mime, title,
             _guess_doc_type(upload.filename), "pending", int(time.time())),
        )
        created_ids.append(doc_id)

    db.commit()
    db.close()

    # Kick off background ingest for each doc
    for did in created_ids:
        background_tasks.add_task(_run_ingest, did)

    return {"queued": len(created_ids), "doc_ids": created_ids}


def _run_ingest(doc_id: str):
    ingest_document(doc_id)


def _guess_doc_type(filename: str) -> str:
    name = filename.lower()
    suffix = Path(filename).suffix.lower()
    if any(k in name for k in ("datasheet", "ds_", "_ds")):
        return "datasheet"
    if any(k in name for k in ("manual", "user_guide", "ug_")):
        return "manual"
    if any(k in name for k in ("schematic", "pcb", "brd", "diagram", "layout")):
        return "schematic"
    if any(k in name for k in ("forum", "thread", "discussion")):
        return "forum"
    if any(k in name for k in ("cve", "advisory", "vulnerability", "vuln")):
        return "advisory"
    if any(k in name for k in ("spec", "specification")):
        return "specification"
    if any(k in name for k in ("screenshot", "capture", "photo", "scan")) or \
       suffix in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp"):
        return "image"
    if suffix in (".db", ".sqlite", ".sqlite3", ".sql"):
        return "database"
    from services.code_analysis import is_code_file
    if is_code_file(suffix, filename) or suffix == ".zip":
        return "code"
    return "document"


@router.get("", response_model=List[DocumentOut])
def list_documents(
    collection_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    db = get_db()
    q = "SELECT * FROM documents WHERE 1=1"
    params: list = []
    if collection_id:
        q += " AND collection_id=?"
        params.append(collection_id)
    if status:
        q += " AND ingest_status=?"
        params.append(status)
    q += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = db.execute(q, params).fetchall()
    db.close()
    return [dict(r) for r in rows]


@router.get("/count")
def count_documents(collection_id: Optional[str] = None, status: Optional[str] = None):
    db = get_db()
    q = "SELECT COUNT(*) FROM documents WHERE 1=1"
    params: list = []
    if collection_id:
        q += " AND collection_id=?"
        params.append(collection_id)
    if status:
        q += " AND ingest_status=?"
        params.append(status)
    total = db.execute(q, params).fetchone()[0]
    db.close()
    return {"total": total}


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return dict(row)


@router.get("/{doc_id}/chunks")
def get_document_chunks(doc_id: str, limit: int = 50, offset: int = 0):
    db = get_db()
    rows = db.execute(
        "SELECT id,chunk_index,page_number,text FROM chunks "
        "WHERE doc_id=? ORDER BY chunk_index LIMIT ? OFFSET ?",
        (doc_id, limit, offset),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


@router.get("/{doc_id}/entities")
def get_document_entities(doc_id: str):
    db = get_db()
    rows = db.execute(
        "SELECT entity_type,value,confidence,context FROM entities WHERE doc_id=?",
        (doc_id,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


@router.delete("", status_code=200)
def delete_documents_by_collection(collection_id: str):
    """Delete all documents (and their chunks/entities/vectors) for a given collection."""
    db = get_db()
    rows = db.execute(
        "SELECT id, file_path FROM documents WHERE collection_id=?", (collection_id,)
    ).fetchall()
    for row in rows:
        try:
            Path(row["file_path"]).unlink(missing_ok=True)
        except Exception:
            pass
        remove_document_from_indexes(row["id"], collection_id)
    result = db.execute("DELETE FROM documents WHERE collection_id=?", (collection_id,))
    db.commit()
    db.close()
    return {"deleted": result.rowcount}


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: str):
    db = get_db()
    row = db.execute(
        "SELECT file_path, collection_id FROM documents WHERE id=?", (doc_id,)
    ).fetchone()
    if row:
        try:
            Path(row["file_path"]).unlink(missing_ok=True)
        except Exception:
            pass
        remove_document_from_indexes(doc_id, row["collection_id"])
        db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        db.commit()
    db.close()
