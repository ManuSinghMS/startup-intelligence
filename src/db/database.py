"""
Database connection and initialization module.
"""
import sqlite3
import os
from pathlib import Path


DB_PATH = os.getenv("DATABASE_PATH", "data/startup_intel.db")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_connection = None


def get_db() -> sqlite3.Connection:
    """Get or create a database connection."""
    global _connection
    if _connection is None:
        # Ensure data directory exists
        db_dir = os.path.dirname(DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        _connection = sqlite3.connect(DB_PATH, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA journal_mode=WAL")
        _connection.execute("PRAGMA foreign_keys=ON")
    return _connection


def init_db():
    """Initialize the database with the schema."""
    db = get_db()
    with open(SCHEMA_PATH, "r") as f:
        schema_sql = f.read()
    db.executescript(schema_sql)
    db.commit()
    print(f"Database initialized at {DB_PATH}")


def close_db():
    """Close the database connection."""
    global _connection
    if _connection:
        _connection.close()
        _connection = None


def query_db(sql: str, params: tuple = (), one: bool = False):
    """Execute a query and return results as list of dicts."""
    db = get_db()
    cursor = db.execute(sql, params)
    results = cursor.fetchall()
    if one:
        return dict(results[0]) if results else None
    return [dict(row) for row in results]


def execute_db(sql: str, params: tuple = ()):
    """Execute a write operation and return lastrowid."""
    db = get_db()
    cursor = db.execute(sql, params)
    db.commit()
    return cursor.lastrowid


def count_records(table: str) -> int:
    """Count records in a table."""
    result = query_db(f"SELECT COUNT(*) as count FROM {table}", one=True)
    return result["count"] if result else 0
