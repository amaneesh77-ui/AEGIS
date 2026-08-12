"""
Corporate database ingestion connector.

Essential requirement: characterise multimedia inputs "including ...
corporate databases". Supports SQLite files (.db/.sqlite/.sqlite3) directly
and generic SQL dump files (.sql) via text parsing, producing a readable,
indexable text representation (schema, row counts, a bounded sample of
rows per table) that flows through the normal chunk -> embed -> index
pipeline like any other document.

Per HMGCC Q&A Q70/Q112: there is no preferred DB format or connection
method, and databases have not featured in past test corpora, only a
"desirable" capability. Live network database connections are
intentionally out of scope here - that would conflict with the air-gapped
operating requirement; file-based exports (the realistic researcher
workflow: a DBA hands over a dump/backup) are supported instead.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Tuple

MAX_SAMPLE_ROWS = 5
MAX_TABLES = 200


def is_database_file(suffix: str) -> bool:
    return suffix.lower() in (".db", ".sqlite", ".sqlite3", ".sql")


def extract_database_text(file_path: Path) -> Tuple[str, int]:
    """Return (text_representation, table_count)."""
    if file_path.suffix.lower() == ".sql":
        return _extract_sql_dump(file_path)
    return _extract_sqlite_file(file_path)


def _extract_sqlite_file(file_path: Path) -> Tuple[str, int]:
    parts = [f"[Corporate database: {file_path.name}]\n"]
    try:
        conn = sqlite3.connect(str(file_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = cur.fetchall()[:MAX_TABLES]

        for t in tables:
            name, ddl = t["name"], t["sql"]
            parts.append(f"\n## Table: {name}\n{ddl or ''}")
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{name}"')
                count = cur.fetchone()[0]
                parts.append(f"Row count: {count}")
            except Exception:
                pass
            try:
                cur.execute(f'SELECT * FROM "{name}" LIMIT {MAX_SAMPLE_ROWS}')
                cols = [d[0] for d in cur.description]
                parts.append("Columns: " + ", ".join(cols))
                for row in cur.fetchall():
                    vals = [str(v)[:80] for v in row]
                    parts.append(" | ".join(vals))
            except Exception:
                pass
        conn.close()
        return "\n".join(parts), max(1, len(tables))
    except Exception as exc:
        return f"[Database extraction error: {exc}]", 1


def _extract_sql_dump(file_path: Path) -> Tuple[str, int]:
    """Lightweight text summary of a .sql dump: CREATE TABLE statements plus
    an approximate row-count estimate per table via INSERT statement counts
    (handles MySQL/Postgres/SQLite dialect dumps without a real DB engine)."""
    raw = file_path.read_text(errors="replace")
    create_re = re.compile(r"CREATE TABLE[^;]+;", re.IGNORECASE | re.DOTALL)
    insert_re = re.compile(r"INSERT INTO\s+[`\"\[]?(\w+)[`\"\]]?", re.IGNORECASE)

    creates = create_re.findall(raw)
    insert_counts: dict = {}
    for m in insert_re.finditer(raw):
        insert_counts[m.group(1)] = insert_counts.get(m.group(1), 0) + 1

    parts = [f"[Corporate database dump: {file_path.name}]\n"]
    for c in creates[:MAX_TABLES]:
        parts.append(c.strip())
    if insert_counts:
        parts.append("\nApproximate row counts (INSERT statements observed):")
        for tbl, n in insert_counts.items():
            parts.append(f"{tbl}: ~{n} insert statements")

    # Bounded raw excerpt too, in case CREATE/INSERT parsing missed a
    # non-standard dialect - keeps some signal for keyword/semantic search.
    parts.append("\n--- raw excerpt ---\n" + raw[:20000])
    return "\n".join(parts), max(1, len(creates))
