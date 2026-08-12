from fastapi import APIRouter
from database import get_db

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def get_audit_log(limit: int = 100, offset: int = 0, action: str = None):
    db = get_db()
    sql = "SELECT * FROM audit_log WHERE 1=1"
    params: list = []
    if action:
        sql += " AND action=?"
        params.append(action)
    sql += " ORDER BY ts DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = db.execute(sql, params).fetchall()
    db.close()
    return [dict(r) for r in rows]
