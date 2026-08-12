import time
import uuid
from typing import List

from fastapi import APIRouter, HTTPException

from database import get_db
from models import CollectionCreate, CollectionOut
from services import bias as bias_service

router = APIRouter(prefix="/api/collections", tags=["collections"])


@router.get("", response_model=List[CollectionOut])
def list_collections():
    db = get_db()
    rows = db.execute(
        """SELECT c.*,
                  COUNT(d.id) AS doc_count
           FROM collections c
           LEFT JOIN documents d ON d.collection_id = c.id
           GROUP BY c.id
           ORDER BY c.created_at DESC"""
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


@router.post("", response_model=CollectionOut, status_code=201)
def create_collection(body: CollectionCreate):
    cid = str(uuid.uuid4())
    now = int(time.time())
    db = get_db()
    db.execute(
        "INSERT INTO collections VALUES (?,?,?,?,?)",
        (cid, body.name, body.description, now, body.owner),
    )
    db.commit()
    row = db.execute(
        "SELECT *, 0 AS doc_count FROM collections WHERE id=?", (cid,)
    ).fetchone()
    db.close()
    bias_service.set_collection_settings(cid, body.bias_policy, body.vendor_country)
    return dict(row)


@router.get("/{cid}", response_model=CollectionOut)
def get_collection(cid: str):
    db = get_db()
    row = db.execute(
        """SELECT c.*, COUNT(d.id) AS doc_count
           FROM collections c
           LEFT JOIN documents d ON d.collection_id = c.id
           WHERE c.id=? GROUP BY c.id""",
        (cid,),
    ).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail="Collection not found")
    return dict(row)


@router.delete("/{cid}", status_code=204)
def delete_collection(cid: str):
    db = get_db()
    db.execute("DELETE FROM collections WHERE id=?", (cid,))
    db.commit()
    db.close()
