"""
Persistent conversation memory.

Essential requirement: "Keep a memory of queries so conversations can be
continued over several weeks without repetition of prompts." Backed by
SQLite (WAL mode) so it survives restarts/power cycles, per HMGCC Q&A Q63.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import List, Optional

from config import MAX_HISTORY_TURNS
from database import get_db


def create_conversation(collection_id: Optional[str] = None, title: str = "New conversation") -> dict:
    db = get_db()
    cid = str(uuid.uuid4())
    now = int(time.time())
    db.execute(
        "INSERT INTO conversations (id, collection_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
        (cid, collection_id, title[:120], now, now),
    )
    db.commit()
    row = db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
    db.close()
    return dict(row)


def get_conversation(conversation_id: str) -> Optional[dict]:
    db = get_db()
    row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    db.close()
    return dict(row) if row else None


def get_or_create_conversation(conversation_id: Optional[str], collection_id: Optional[str],
                                fallback_title: str) -> dict:
    if conversation_id:
        conv = get_conversation(conversation_id)
        if conv:
            return conv
    return create_conversation(collection_id, title=fallback_title)


def list_conversations(collection_id: Optional[str] = None, limit: int = 100) -> List[dict]:
    db = get_db()
    q = """
        SELECT c.*,
               (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count,
               (SELECT content FROM messages m WHERE m.conversation_id = c.id
                ORDER BY m.created_at DESC LIMIT 1) AS last_message
        FROM conversations c
        WHERE 1=1
    """
    params: list = []
    if collection_id:
        q += " AND c.collection_id=?"
        params.append(collection_id)
    q += " ORDER BY c.updated_at DESC LIMIT ?"
    params.append(limit)
    rows = db.execute(q, params).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_messages(conversation_id: str, limit: int = 200) -> List[dict]:
    db = get_db()
    rows = db.execute(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    db.close()
    out = []
    for r in rows:
        d = dict(r)
        for key in ("sources_json", "confidence_json"):
            if d.get(key):
                try:
                    d[key.replace("_json", "")] = json.loads(d[key])
                except Exception:
                    pass
        out.append(d)
    return out


def get_recent_history(conversation_id: str, max_turns: int = MAX_HISTORY_TURNS) -> List[dict]:
    """Return the last N user/assistant turns for RAG context continuity.

    Ordered by SQLite's implicit rowid (insertion order) rather than
    created_at, since multiple messages can share the same integer
    timestamp and created_at DESC + reverse is not a stable sort in that
    case.
    """
    db = get_db()
    rows = db.execute(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY rowid ASC",
        (conversation_id,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows][-max_turns * 2:]


def add_message(conversation_id: str, role: str, content: str,
                 sources: Optional[list] = None, confidence: Optional[dict] = None) -> dict:
    db = get_db()
    mid = str(uuid.uuid4())
    now = int(time.time())
    db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, sources_json, confidence_json, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (mid, conversation_id, role, content,
         json.dumps(sources) if sources is not None else None,
         json.dumps(confidence) if confidence is not None else None,
         now),
    )
    db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
    db.commit()
    db.close()
    return {"id": mid, "conversation_id": conversation_id, "role": role, "content": content, "created_at": now}


def delete_conversation(conversation_id: str) -> None:
    db = get_db()
    db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
    db.commit()
    db.close()


def rename_conversation(conversation_id: str, title: str) -> None:
    db = get_db()
    db.execute("UPDATE conversations SET title=? WHERE id=?", (title[:120], conversation_id))
    db.commit()
    db.close()
