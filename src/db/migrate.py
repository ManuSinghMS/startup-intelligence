"""
Database migration helper.

Adds new columns to existing tables without losing data, and (when needed)
rebuilds content_items to drop the old strict CHECK constraint on
`classification` so URL-typed values like 'founder_post_url' can be stored.

Run this to upgrade an existing database after schema changes.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from src.db.database import get_db


def _table_columns(db, table: str) -> set[str]:
    rows = db.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _content_items_needs_rebuild(db) -> bool:
    """
    Detect whether content_items still carries the strict CHECK constraint
    on classification (which rejects URL-typed values like 'founder_post_url').
    """
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='content_items'"
    ).fetchone()
    if not row:
        return False
    sql = row[0] or ""
    # Old CHECK explicitly listed news categories. New schema has no CHECK
    # on classification at all.
    return "classification TEXT CHECK" in sql or "'unclassified'" in sql


def _rebuild_content_items(db):
    """
    Recreate content_items without the CHECK on classification, and add new
    columns: external_source, canonical_url, author_name, post_date,
    discovered_at, metadata_json. Preserves all existing data.

    Carefully recreates the FTS5 virtual table and triggers.
    """
    print("  ! Rebuilding content_items to drop CHECK constraint and add new columns...")

    old_cols = _table_columns(db, "content_items")

    # Build the SELECT list mapping new columns to old (preserve data; default NULLs).
    new_cols = [
        "id", "startup_id", "source_id", "source_type", "source_name",
        "external_source", "url", "canonical_url", "title", "author_name",
        "published_at", "post_date", "discovered_at", "raw_content", "summary",
        "classification", "sentiment", "impact_score", "topics",
        "metadata_json", "content_hash", "confidence_score", "is_relevant",
        "hired_count", "ingestion_status", "created_at",
    ]
    select_terms = []
    for col in new_cols:
        if col in old_cols:
            select_terms.append(col)
        elif col == "discovered_at":
            # Backfill discovered_at from created_at if it didn't exist before
            select_terms.append(
                "created_at AS discovered_at" if "created_at" in old_cols else "NULL AS discovered_at"
            )
        else:
            select_terms.append(f"NULL AS {col}")
    select_sql = ", ".join(select_terms)

    db.executescript(f"""
        DROP TRIGGER IF EXISTS content_ai;
        DROP TRIGGER IF EXISTS content_ad;
        DROP TRIGGER IF EXISTS content_au;
        DROP TABLE IF EXISTS content_fts;
        ALTER TABLE content_items RENAME TO content_items_old;

        CREATE TABLE content_items (
            id TEXT PRIMARY KEY,
            startup_id TEXT,
            source_id TEXT,
            source_type TEXT NOT NULL,
            source_name TEXT,
            external_source TEXT,
            url TEXT,
            canonical_url TEXT,
            title TEXT,
            author_name TEXT,
            published_at TIMESTAMP,
            post_date TIMESTAMP,
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            raw_content TEXT,
            summary TEXT,
            classification TEXT,
            sentiment TEXT,
            impact_score REAL DEFAULT 0.0,
            topics TEXT,
            metadata_json TEXT,
            content_hash TEXT UNIQUE,
            confidence_score REAL DEFAULT 1.0,
            is_relevant INTEGER DEFAULT 1,
            hired_count INTEGER DEFAULT 0,
            ingestion_status TEXT DEFAULT 'full_content',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (startup_id) REFERENCES startups(id),
            FOREIGN KEY (source_id) REFERENCES sources(id)
        );

        INSERT INTO content_items ({", ".join(new_cols)})
        SELECT {select_sql} FROM content_items_old;

        DROP TABLE content_items_old;

        CREATE VIRTUAL TABLE content_fts USING fts5(
            title, raw_content, summary, source_name,
            content='content_items', content_rowid='rowid'
        );
        INSERT INTO content_fts(rowid, title, raw_content, summary, source_name)
            SELECT rowid, title, raw_content, summary, source_name FROM content_items;

        CREATE TRIGGER content_ai AFTER INSERT ON content_items BEGIN
            INSERT INTO content_fts(rowid, title, raw_content, summary, source_name)
            VALUES (new.rowid, new.title, new.raw_content, new.summary, new.source_name);
        END;
        CREATE TRIGGER content_ad AFTER DELETE ON content_items BEGIN
            INSERT INTO content_fts(content_fts, rowid, title, raw_content, summary, source_name)
            VALUES ('delete', old.rowid, old.title, old.raw_content, old.summary, old.source_name);
        END;
        CREATE TRIGGER content_au AFTER UPDATE ON content_items BEGIN
            INSERT INTO content_fts(content_fts, rowid, title, raw_content, summary, source_name)
            VALUES ('delete', old.rowid, old.title, old.raw_content, old.summary, old.source_name);
            INSERT INTO content_fts(rowid, title, raw_content, summary, source_name)
            VALUES (new.rowid, new.title, new.raw_content, new.summary, new.source_name);
        END;

        CREATE INDEX IF NOT EXISTS idx_content_startup ON content_items(startup_id);
        CREATE INDEX IF NOT EXISTS idx_content_published ON content_items(published_at);
        CREATE INDEX IF NOT EXISTS idx_content_classification ON content_items(classification);
        CREATE INDEX IF NOT EXISTS idx_content_source_type ON content_items(source_type);
        CREATE INDEX IF NOT EXISTS idx_content_hash ON content_items(content_hash);
        CREATE INDEX IF NOT EXISTS idx_content_canonical ON content_items(canonical_url);
    """)
    db.commit()


def migrate():
    """Apply schema migrations to an existing database."""
    db = get_db()

    migrations = [
        # startups columns
        {
            "check": "SELECT * FROM pragma_table_info('startups') WHERE name='tag'",
            "sql": "ALTER TABLE startups ADD COLUMN tag TEXT DEFAULT 'active'",
            "desc": "Added 'tag' column to startups",
        },
        {
            "check": "SELECT * FROM pragma_table_info('startups') WHERE name='last_ingested_at'",
            "sql": "ALTER TABLE startups ADD COLUMN last_ingested_at TIMESTAMP",
            "desc": "Added 'last_ingested_at' column to startups",
        },
        {
            "check": "SELECT * FROM pragma_table_info('startups') WHERE name='founder_name'",
            "sql": "ALTER TABLE startups ADD COLUMN founder_name TEXT",
            "desc": "Added 'founder_name' column to startups",
        },
        {
            "check": "SELECT * FROM pragma_table_info('startups') WHERE name='cofounder_name'",
            "sql": "ALTER TABLE startups ADD COLUMN cofounder_name TEXT",
            "desc": "Added 'cofounder_name' column to startups",
        },
        {
            "check": "SELECT * FROM pragma_table_info('startups') WHERE name='founder_linkedin_url'",
            "sql": "ALTER TABLE startups ADD COLUMN founder_linkedin_url TEXT",
            "desc": "Added 'founder_linkedin_url' column to startups",
        },
        {
            "check": "SELECT * FROM pragma_table_info('startups') WHERE name='cofounder_linkedin_url'",
            "sql": "ALTER TABLE startups ADD COLUMN cofounder_linkedin_url TEXT",
            "desc": "Added 'cofounder_linkedin_url' column to startups",
        },
        {
            "check": "SELECT * FROM pragma_table_info('startups') WHERE name='sales_nav_checked_at'",
            "sql": "ALTER TABLE startups ADD COLUMN sales_nav_checked_at TIMESTAMP",
            "desc": "Added 'sales_nav_checked_at' column to startups",
        },
        {
            "check": "SELECT * FROM pragma_table_info('startups') WHERE name='sales_nav_status'",
            "sql": "ALTER TABLE startups ADD COLUMN sales_nav_status TEXT",
            "desc": "Added 'sales_nav_status' column to startups",
        },
        # content_items columns
        {
            "check": "SELECT * FROM pragma_table_info('content_items') WHERE name='confidence_score'",
            "sql": "ALTER TABLE content_items ADD COLUMN confidence_score REAL DEFAULT 1.0",
            "desc": "Added 'confidence_score' column to content_items",
        },
        {
            "check": "SELECT * FROM pragma_table_info('content_items') WHERE name='ingestion_status'",
            "sql": "ALTER TABLE content_items ADD COLUMN ingestion_status TEXT DEFAULT 'full_content'",
            "desc": "Added 'ingestion_status' column to content_items",
        },
        # indexes
        {
            "check": "SELECT * FROM sqlite_master WHERE type='index' AND name='idx_startups_tag'",
            "sql": "CREATE INDEX IF NOT EXISTS idx_startups_tag ON startups(tag)",
            "desc": "Added index on startups.tag",
        },
    ]

    applied = 0
    for m in migrations:
        result = db.execute(m["check"]).fetchone()
        if not result:
            try:
                db.execute(m["sql"])
                db.commit()
                print(f"  + {m['desc']}")
                applied += 1
            except Exception as e:
                print(f"  - {m['desc']}: {e}")
        else:
            print(f"  = {m['desc']} (already applied)")

    # Rebuild content_items if the strict CHECK is still in place.
    # This also adds canonical_url, author_name, post_date, discovered_at,
    # metadata_json, external_source.
    if _content_items_needs_rebuild(db):
        try:
            _rebuild_content_items(db)
            print("  + content_items rebuilt without CHECK constraint")
            applied += 1
        except Exception as e:
            print(f"  ! content_items rebuild failed: {e}")
    else:
        print("  = content_items already in current shape")

    # Set existing startups without a tag to 'active'
    try:
        db.execute("UPDATE startups SET tag = 'active' WHERE tag IS NULL")
        db.commit()
    except Exception:
        pass

    print(f"Migration complete: {applied} changes applied")


if __name__ == "__main__":
    migrate()
