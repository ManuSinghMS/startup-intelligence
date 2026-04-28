"""
Newsletter ingester — handles Substack RSS + manual paste uploads.
"""
import uuid
from datetime import datetime
from typing import Optional

from src.db.database import get_db
from src.ingestion.rss_ingester import hash_content, match_startup, fetch_feed, parse_date, get_entry_content


async def ingest_substack(substack_url: str, source_name: str = "Substack") -> dict:
    """
    Ingest posts from a Substack publication's RSS feed.
    Substack feeds are at: https://<name>.substack.com/feed
    """
    db = get_db()
    stats = {"found": 0, "new": 0, "duplicate": 0, "matched": 0}

    # Ensure we have the /feed URL
    if not substack_url.endswith("/feed"):
        substack_url = substack_url.rstrip("/") + "/feed"

    feed = await fetch_feed(substack_url)
    if not feed or not feed.entries:
        return stats

    startups = [dict(row) for row in db.execute("SELECT * FROM startups").fetchall()]

    for entry in feed.entries:
        stats["found"] += 1

        title = getattr(entry, "title", "Untitled")
        url = getattr(entry, "link", "")
        content = get_entry_content(entry)
        published = parse_date(entry)

        content_hash = hash_content(url, title)
        existing = db.execute(
            "SELECT id FROM content_items WHERE content_hash = ?",
            (content_hash,)
        ).fetchone()

        if existing:
            stats["duplicate"] += 1
            continue

        full_text = f"{title} {content}"
        matched = match_startup(full_text, startups)

        item_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO content_items
            (id, startup_id, source_type, source_name, url, title,
             published_at, raw_content, content_hash, classification)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, matched["id"] if matched else None, "newsletter", source_name,
             url, title, published, content, content_hash, "unclassified")
        )
        stats["new"] += 1
        if matched:
            stats["matched"] += 1

    db.commit()
    return stats


def store_manual_newsletter(title: str, content: str, source_name: str,
                            published_at: Optional[str] = None) -> Optional[str]:
    """
    Store manually pasted newsletter content.
    Returns the content_item id if stored.
    """
    db = get_db()

    if not published_at:
        published_at = datetime.utcnow().isoformat()

    content_hash = hash_content(source_name + title, title)
    existing = db.execute(
        "SELECT id FROM content_items WHERE content_hash = ?",
        (content_hash,)
    ).fetchone()
    if existing:
        return None

    startups = [dict(row) for row in db.execute("SELECT * FROM startups").fetchall()]
    full_text = f"{title} {content}"
    matched = match_startup(full_text, startups)

    item_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO content_items
        (id, startup_id, source_type, source_name, url, title,
         published_at, raw_content, content_hash, classification)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (item_id, matched["id"] if matched else None, "newsletter", source_name,
         "", title, published_at, content, content_hash, "unclassified")
    )
    db.commit()
    return item_id
