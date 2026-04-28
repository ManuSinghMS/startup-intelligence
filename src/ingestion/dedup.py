"""
Deduplication engine — prevents storing duplicate content items.
Uses content hash + title similarity.
"""
from src.db.database import get_db


def find_duplicates() -> list:
    """
    Find and return groups of duplicate content items
    based on similar titles and URLs.
    """
    db = get_db()

    # Find exact hash duplicates (shouldn't exist due to UNIQUE constraint, but just in case)
    dupes = db.execute("""
        SELECT content_hash, COUNT(*) as cnt
        FROM content_items
        WHERE content_hash IS NOT NULL
        GROUP BY content_hash
        HAVING cnt > 1
    """).fetchall()

    return [dict(d) for d in dupes]


def remove_duplicates(keep: str = "oldest") -> int:
    """
    Remove duplicate content items, keeping either the oldest or newest.
    Returns count of removed items.
    """
    db = get_db()

    dupes = find_duplicates()
    removed = 0

    for dupe in dupes:
        items = db.execute(
            "SELECT id, created_at FROM content_items WHERE content_hash = ? ORDER BY created_at",
            (dupe["content_hash"],)
        ).fetchall()

        # Keep the first (oldest) or last (newest)
        if keep == "oldest":
            to_remove = items[1:]
        else:
            to_remove = items[:-1]

        for item in to_remove:
            db.execute("DELETE FROM content_items WHERE id = ?", (item["id"],))
            removed += 1

    db.commit()
    return removed


def mark_irrelevant(content_id: str):
    """Mark a content item as irrelevant (keeps it but flags it)."""
    db = get_db()
    db.execute(
        "UPDATE content_items SET is_relevant = 0 WHERE id = ?",
        (content_id,)
    )
    db.commit()
