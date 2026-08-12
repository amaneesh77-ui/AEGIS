import sqlite3
from config import DB_PATH


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS collections (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        description TEXT,
        created_at  INTEGER NOT NULL,
        owner       TEXT DEFAULT 'researcher'
    );

    CREATE TABLE IF NOT EXISTS documents (
        id             TEXT PRIMARY KEY,
        collection_id  TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
        filename       TEXT NOT NULL,
        file_path      TEXT NOT NULL,
        file_hash      TEXT,
        file_size      INTEGER DEFAULT 0,
        mime_type      TEXT DEFAULT 'application/octet-stream',
        title          TEXT,
        author         TEXT,
        doc_type       TEXT DEFAULT 'unknown',
        manufacturer   TEXT,
        part_number    TEXT,
        page_count     INTEGER DEFAULT 0,
        word_count     INTEGER DEFAULT 0,
        ingest_status  TEXT DEFAULT 'pending',
        ingest_error   TEXT,
        summary        TEXT,
        indexed_at     INTEGER,
        created_at     INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS chunks (
        id          TEXT PRIMARY KEY,
        doc_id      TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        chunk_index INTEGER NOT NULL,
        page_number INTEGER DEFAULT 0,
        text        TEXT NOT NULL,
        embedding_id TEXT
    );

    CREATE TABLE IF NOT EXISTS entities (
        id          TEXT PRIMARY KEY,
        doc_id      TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        entity_type TEXT NOT NULL,
        value       TEXT NOT NULL,
        confidence  REAL DEFAULT 1.0,
        context     TEXT
    );

    CREATE TABLE IF NOT EXISTS annotations (
        id         TEXT PRIMARY KEY,
        doc_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        chunk_id   TEXT,
        kind       TEXT NOT NULL,
        note       TEXT,
        colour     TEXT DEFAULT 'yellow',
        created_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS audit_log (
        id      TEXT PRIMARY KEY,
        action  TEXT NOT NULL,
        payload TEXT,
        ts      INTEGER NOT NULL
    );

    -- Persistent multi-week conversation memory (essential requirement:
    -- "keep a memory of queries so conversations can be continued over
    -- several weeks without repetition of prompts").
    CREATE TABLE IF NOT EXISTS conversations (
        id            TEXT PRIMARY KEY,
        collection_id TEXT REFERENCES collections(id) ON DELETE CASCADE,
        title         TEXT NOT NULL DEFAULT 'New conversation',
        created_at    INTEGER NOT NULL,
        updated_at    INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS messages (
        id              TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role            TEXT NOT NULL,          -- user | assistant
        content         TEXT NOT NULL,
        sources_json    TEXT,
        confidence_json TEXT,
        created_at      INTEGER NOT NULL
    );

    -- User profile / adaptation (desirable requirement).
    CREATE TABLE IF NOT EXISTS user_profile (
        key   TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS topic_frequency (
        topic       TEXT PRIMARY KEY,
        count       INTEGER NOT NULL DEFAULT 0,
        last_seen   INTEGER
    );

    -- Cultural / language coverage bias tracking (desirable requirement).
    CREATE TABLE IF NOT EXISTS document_language (
        doc_id      TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
        language    TEXT,
        confidence  REAL
    );

    CREATE TABLE IF NOT EXISTS collection_settings (
        collection_id  TEXT PRIMARY KEY REFERENCES collections(id) ON DELETE CASCADE,
        bias_policy    TEXT DEFAULT 'suggestive',   -- off | suggestive | proactive
        vendor_country TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_docs_collection ON documents(collection_id);
    CREATE INDEX IF NOT EXISTS idx_docs_status     ON documents(ingest_status);
    CREATE INDEX IF NOT EXISTS idx_chunks_doc      ON chunks(doc_id);
    CREATE INDEX IF NOT EXISTS idx_entities_doc    ON entities(doc_id);
    CREATE INDEX IF NOT EXISTS idx_entities_type   ON entities(entity_type);
    CREATE INDEX IF NOT EXISTS idx_entities_value  ON entities(value);
    CREATE INDEX IF NOT EXISTS idx_messages_conv   ON messages(conversation_id);
    CREATE INDEX IF NOT EXISTS idx_conv_collection ON conversations(collection_id);
    """)
    conn.commit()
    conn.close()
