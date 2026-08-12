import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException

from database import get_db
from models import AnnotationCreate

router = APIRouter(prefix="/api/annotations", tags=["annotations"])


@router.post("", status_code=201)
def create_annotation(body: AnnotationCreate):
    db = get_db()
    # verify doc exists
    if not db.execute("SELECT 1 FROM documents WHERE id=?", (body.doc_id,)).fetchone():
        db.close()
        raise HTTPException(status_code=404, detail="Document not found")

    aid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO annotations VALUES (?,?,?,?,?,?,?)",
        (aid, body.doc_id, body.chunk_id, body.kind,
         body.note, body.colour, int(time.time())),
    )
    db.commit()
    db.close()
    return {"id": aid, "doc_id": body.doc_id, "kind": body.kind, "note": body.note}


@router.get("")
def list_annotations(doc_id: Optional[str] = None, collection_id: Optional[str] = None):
    db = get_db()
    if doc_id:
        rows = db.execute(
            "SELECT * FROM annotations WHERE doc_id=? ORDER BY created_at DESC",
            (doc_id,),
        ).fetchall()
    elif collection_id:
        rows = db.execute(
            """SELECT a.* FROM annotations a
               JOIN documents d ON d.id = a.doc_id
               WHERE d.collection_id=?
               ORDER BY a.created_at DESC""",
            (collection_id,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM annotations ORDER BY created_at DESC LIMIT 500"
        ).fetchall()
    db.close()
    return [dict(r) for r in rows]


@router.delete("/{ann_id}", status_code=204)
def delete_annotation(ann_id: str):
    db = get_db()
    db.execute("DELETE FROM annotations WHERE id=?", (ann_id,))
    db.commit()
    db.close()
