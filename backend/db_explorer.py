"""
AEGIS Database Explorer
========================
Interactive SQLite shell with pre-built queries for the AEGIS schema.

Usage:
  python db_explorer.py              - interactive menu
  python db_explorer.py --sql "..."  - run a single query and print results
  python db_explorer.py --table docs - dump a table (docs|chunks|entities|annotations|audit|collections)

Run from C:\\AEGIS\\backend\\ with the venv active.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DB_PATH

# ── Connection ────────────────────────────────────────────────────────────────

def connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        print(f"[ERROR] Database not found at {DB_PATH}")
        print("        Start AEGIS at least once to initialise the database.")
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Display helpers ───────────────────────────────────────────────────────────

def _col_widths(rows, headers, max_col=50):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = min(max_col, max(widths[i], len(str(val or ""))))
    return widths


def print_table(rows, headers=None):
    if not rows:
        print("  (no rows)")
        return
    if headers is None:
        headers = list(rows[0].keys())
    data = [[str(r[h] or "") for h in headers] for r in rows]
    widths = _col_widths(data, headers)
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    fmt = "| " + " | ".join(f"{{:<{w}}}" for w in widths) + " |"
    print(sep)
    print(fmt.format(*headers))
    print(sep)
    for row in data:
        clipped = [v[:w] + "…" if len(v) > w else v for v, w in zip(row, widths)]
        print(fmt.format(*clipped))
    print(sep)
    print(f"  {len(rows)} row(s)")


def run_query(conn, sql, params=()):
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        if rows:
            print_table(rows)
        else:
            affected = conn.total_changes
            print(f"  Query OK - {affected} row(s) affected")
    except sqlite3.Error as e:
        print(f"  [SQL Error] {e}")


# ── Pre-built queries ─────────────────────────────────────────────────────────

QUERIES = {

    "1": {
        "label": "All collections with document counts",
        "sql": """
            SELECT c.id, c.name, c.owner,
                   datetime(c.created_at, 'unixepoch') AS created,
                   COUNT(d.id) AS doc_count
            FROM collections c
            LEFT JOIN documents d ON d.collection_id = c.id
            GROUP BY c.id ORDER BY c.created_at DESC
        """,
    },

    "2": {
        "label": "All documents (status summary)",
        "sql": """
            SELECT d.filename, d.doc_type, d.ingest_status,
                   d.page_count, d.word_count,
                   d.manufacturer, d.part_number,
                   datetime(d.created_at,'unixepoch') AS imported
            FROM documents d
            ORDER BY d.created_at DESC
            LIMIT 100
        """,
    },

    "3": {
        "label": "Documents by ingest status",
        "sql": """
            SELECT ingest_status, COUNT(*) AS count
            FROM documents
            GROUP BY ingest_status
        """,
    },

    "4": {
        "label": "Failed / errored documents",
        "sql": """
            SELECT filename, ingest_error,
                   datetime(created_at,'unixepoch') AS imported
            FROM documents
            WHERE ingest_status = 'error'
            ORDER BY created_at DESC
        """,
    },

    "5": {
        "label": "Top 50 entities by frequency",
        "sql": """
            SELECT entity_type, value, COUNT(*) AS mentions,
                   COUNT(DISTINCT doc_id) AS in_docs
            FROM entities
            GROUP BY entity_type, value
            ORDER BY mentions DESC
            LIMIT 50
        """,
    },

    "6": {
        "label": "All CVEs found across documents",
        "sql": """
            SELECT e.value AS cve_id,
                   COUNT(DISTINCT e.doc_id) AS in_docs,
                   GROUP_CONCAT(DISTINCT d.filename, ' | ') AS sources
            FROM entities e
            JOIN documents d ON d.id = e.doc_id
            WHERE e.entity_type = 'CVE'
            GROUP BY e.value
            ORDER BY in_docs DESC
        """,
    },

    "7": {
        "label": "Manufacturers mentioned",
        "sql": """
            SELECT value AS manufacturer, COUNT(*) AS mentions,
                   COUNT(DISTINCT doc_id) AS in_docs
            FROM entities WHERE entity_type = 'MANUFACTURER'
            GROUP BY value ORDER BY mentions DESC
        """,
    },

    "8": {
        "label": "Protocols mentioned",
        "sql": """
            SELECT value AS protocol, COUNT(*) AS mentions,
                   COUNT(DISTINCT doc_id) AS in_docs
            FROM entities WHERE entity_type = 'PROTOCOL'
            GROUP BY value ORDER BY mentions DESC
        """,
    },

    "9": {
        "label": "Part numbers / component IDs",
        "sql": """
            SELECT value AS part_number, COUNT(*) AS mentions,
                   COUNT(DISTINCT doc_id) AS in_docs
            FROM entities
            WHERE entity_type IN ('PART_NUMBER','COMPONENT')
            GROUP BY value ORDER BY mentions DESC LIMIT 50
        """,
    },

    "10": {
        "label": "All annotations",
        "sql": """
            SELECT a.kind, a.note, d.filename,
                   datetime(a.created_at,'unixepoch') AS created
            FROM annotations a
            JOIN documents d ON d.id = a.doc_id
            ORDER BY a.created_at DESC
        """,
    },

    "11": {
        "label": "Audit log (last 50 events)",
        "sql": """
            SELECT datetime(ts,'unixepoch') AS time, action, payload
            FROM audit_log
            ORDER BY ts DESC LIMIT 50
        """,
    },

    "12": {
        "label": "Chunk count per document",
        "sql": """
            SELECT d.filename, COUNT(c.id) AS chunks,
                   MAX(c.page_number) AS max_page
            FROM documents d
            LEFT JOIN chunks c ON c.doc_id = d.id
            GROUP BY d.id
            ORDER BY chunks DESC
            LIMIT 50
        """,
    },

    "13": {
        "label": "Database storage summary",
        "sql": """
            SELECT 'collections' AS tbl, COUNT(*) AS rows FROM collections
            UNION ALL
            SELECT 'documents',  COUNT(*) FROM documents
            UNION ALL
            SELECT 'chunks',     COUNT(*) FROM chunks
            UNION ALL
            SELECT 'entities',   COUNT(*) FROM entities
            UNION ALL
            SELECT 'annotations',COUNT(*) FROM annotations
            UNION ALL
            SELECT 'audit_log',  COUNT(*) FROM audit_log
        """,
    },

    "14": {
        "label": "Search: entities for a specific document (enter filename)",
        "prompt": "Enter filename (or part of it): ",
        "sql": """
            SELECT e.entity_type, e.value, e.confidence, e.context
            FROM entities e
            JOIN documents d ON d.id = e.doc_id
            WHERE d.filename LIKE ?
            ORDER BY e.entity_type, e.value
        """,
        "param_fn": lambda p: (f"%{p}%",),
    },

    "15": {
        "label": "Search: all documents mentioning a CVE",
        "prompt": "Enter CVE ID (e.g. CVE-2023-44487): ",
        "sql": """
            SELECT d.filename, d.doc_type, d.ingest_status,
                   e.context
            FROM entities e
            JOIN documents d ON d.id = e.doc_id
            WHERE e.entity_type = 'CVE' AND e.value LIKE ?
        """,
        "param_fn": lambda p: (f"%{p}%",),
    },

    "16": {
        "label": "Search: all documents mentioning a manufacturer",
        "prompt": "Enter manufacturer name: ",
        "sql": """
            SELECT d.filename, d.doc_type,
                   COUNT(e.id) AS mentions
            FROM entities e
            JOIN documents d ON d.id = e.doc_id
            WHERE e.entity_type = 'MANUFACTURER' AND e.value LIKE ?
            GROUP BY d.id ORDER BY mentions DESC
        """,
        "param_fn": lambda p: (f"%{p}%",),
    },

    "17": {
        "label": "CVE severity breakdown",
        "sql": """
            SELECT e.value AS severity, COUNT(DISTINCT d.id) AS cve_docs
            FROM entities e
            JOIN documents d ON d.id = e.doc_id
            WHERE e.entity_type = 'VULNERABILITY_CLASS'
            GROUP BY e.value ORDER BY cve_docs DESC
        """,
    },

    "c": {
        "label": "Custom SQL query",
        "prompt": "Enter SQL: ",
        "sql": None,  # dynamic
    },
}


# ── Interactive menu ──────────────────────────────────────────────────────────

def interactive(conn):
    print("\n" + "=" * 62)
    print("  AEGIS Database Explorer")
    print(f"  Database: {DB_PATH}")
    print("=" * 62)

    while True:
        print("\n  Pre-built queries:")
        for key, q in QUERIES.items():
            print(f"    [{key:>2}]  {q['label']}")
        print("\n    [q]   Quit")
        print()
        choice = input("  Select: ").strip().lower()

        if choice == "q":
            print("  Goodbye.")
            break

        if choice not in QUERIES:
            print("  Invalid choice.")
            continue

        q = QUERIES[choice]
        sql = q["sql"]

        if choice == "c":
            sql = input("  SQL> ").strip()
            if not sql:
                continue
            run_query(conn, sql)
            continue

        params = ()
        if "prompt" in q:
            user_input = input(f"  {q['prompt']}").strip()
            if not user_input:
                continue
            params = q["param_fn"](user_input)

        print()
        run_query(conn, sql, params)


# ── CLI mode ──────────────────────────────────────────────────────────────────

TABLE_QUERIES = {
    "docs":        "SELECT id, filename, doc_type, ingest_status, page_count, word_count FROM documents LIMIT 200",
    "collections": "SELECT * FROM collections",
    "chunks":      "SELECT id, doc_id, chunk_index, page_number, substr(text,1,80) AS text_preview FROM chunks LIMIT 200",
    "entities":    "SELECT entity_type, value, confidence FROM entities ORDER BY entity_type LIMIT 200",
    "annotations": "SELECT kind, note, doc_id, datetime(created_at,'unixepoch') AS created FROM annotations",
    "audit":       "SELECT datetime(ts,'unixepoch') AS time, action, payload FROM audit_log ORDER BY ts DESC LIMIT 100",
}


def main():
    parser = argparse.ArgumentParser(description="AEGIS Database Explorer")
    parser.add_argument("--sql",   help="Run a single SQL statement and exit")
    parser.add_argument("--table", choices=list(TABLE_QUERIES), help="Dump a table")
    args = parser.parse_args()

    conn = connect()
    try:
        if args.sql:
            run_query(conn, args.sql)
        elif args.table:
            run_query(conn, TABLE_QUERIES[args.table])
        else:
            interactive(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
