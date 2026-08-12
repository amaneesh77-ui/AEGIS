from typing import List

from fastapi import APIRouter

from models import SearchRequest, SearchHit
from services.search_engine import hybrid_search

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("", response_model=List[SearchHit])
def search(body: SearchRequest):
    hits = hybrid_search(
        query=body.query,
        collection_id=body.collection_id,
        limit=body.limit,
        doc_type=body.doc_type,
        mode=body.mode,
    )
    return hits


@router.get("/suggest")
def suggest(q: str, collection_id: str = None, limit: int = 8):
    """Simple prefix suggestions from entity values."""
    from database import get_db
    db = get_db()
    params: list = [f"%{q}%", limit]
    sql = "SELECT DISTINCT value, entity_type FROM entities WHERE value LIKE ?"
    if collection_id:
        sql += " AND doc_id IN (SELECT id FROM documents WHERE collection_id=?)"
        params.insert(1, collection_id)
    sql += " LIMIT ?"
    rows = db.execute(sql, params).fetchall()
    db.close()
    return [{"value": r["value"], "type": r["entity_type"]} for r in rows]


@router.get("/entities")
def list_entities(
    collection_id: str = None,
    entity_type: str = None,
    limit: int = 100,
):
    from database import get_db
    db = get_db()
    sql = """
        SELECT e.entity_type, e.value, COUNT(*) as freq
        FROM entities e
        JOIN documents d ON d.id = e.doc_id
        WHERE 1=1
    """
    params: list = []
    if collection_id:
        sql += " AND d.collection_id=?"
        params.append(collection_id)
    if entity_type:
        sql += " AND e.entity_type=?"
        params.append(entity_type)
    sql += " GROUP BY e.entity_type, e.value ORDER BY freq DESC LIMIT ?"
    params.append(limit)
    rows = db.execute(sql, params).fetchall()
    db.close()
    return [dict(r) for r in rows]
