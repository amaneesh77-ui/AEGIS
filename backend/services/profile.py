"""
User profile adaptation.

Desirable requirement: "Build a profile of the user and adapt to their
needs, for example to present information in preferred formats and even
proactively provide information that is frequently requested."

Deliberately lightweight (a single researcher uses the laptop at a time,
per HMGCC Q&A Q48/Q50): tracks a couple of explicit preferences plus a
frequency count of topics/entities mentioned in queries, used to surface
proactive suggestions.
"""

from __future__ import annotations

import re
import time
from typing import List, Optional

from database import get_db

DEFAULTS = {"answer_style": "concise", "proactive_suggestions": "true"}
_STOPWORDS = {
    "the", "a", "an", "is", "are", "of", "and", "or", "to", "in", "on", "for",
    "what", "how", "does", "do", "can", "which", "with", "this", "that", "it",
    "was", "were", "be", "been", "has", "have", "had", "as", "at", "by", "from",
    "you", "me", "my", "please", "tell", "about", "there", "any",
}


def get_profile() -> dict:
    db = get_db()
    rows = db.execute("SELECT key, value FROM user_profile").fetchall()
    db.close()
    profile = dict(DEFAULTS)
    profile.update({r["key"]: r["value"] for r in rows})
    profile["proactive_suggestions"] = str(profile["proactive_suggestions"]).lower() == "true"
    return profile


def update_profile(answer_style: Optional[str] = None, proactive_suggestions: Optional[bool] = None) -> dict:
    db = get_db()
    if answer_style is not None:
        db.execute(
            "INSERT INTO user_profile (key, value) VALUES ('answer_style', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (answer_style,),
        )
    if proactive_suggestions is not None:
        db.execute(
            "INSERT INTO user_profile (key, value) VALUES ('proactive_suggestions', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(bool(proactive_suggestions)).lower(),),
        )
    db.commit()
    db.close()
    return get_profile()


def record_query_topics(question: str) -> None:
    """Increment frequency counters for meaningful words in a query, used to
    proactively resurface frequently-asked topics later."""
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", question.lower())
    topics = {w for w in words if w not in _STOPWORDS}
    if not topics:
        return
    now = int(time.time())
    db = get_db()
    for t in topics:
        db.execute(
            "INSERT INTO topic_frequency (topic, count, last_seen) VALUES (?, 1, ?) "
            "ON CONFLICT(topic) DO UPDATE SET count = count + 1, last_seen = excluded.last_seen",
            (t, now),
        )
    db.commit()
    db.close()


def frequent_topics(limit: int = 10) -> List[dict]:
    db = get_db()
    rows = db.execute(
        "SELECT topic, count, last_seen FROM topic_frequency ORDER BY count DESC LIMIT ?",
        (limit,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def proactive_suggestion() -> Optional[str]:
    """Surface a proactive suggestion based on the researcher's most
    frequently asked topic, if the feature is enabled."""
    profile = get_profile()
    if not profile.get("proactive_suggestions"):
        return None
    top = frequent_topics(limit=1)
    if not top or top[0]["count"] < 3:
        return None
    return (
        f"You've frequently asked about '{top[0]['topic']}' - would you like a "
        f"summary of everything currently indexed on that topic?"
    )
