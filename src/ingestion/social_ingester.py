"""
Social media ingester — handles LinkedIn, X/Twitter, Instagram.
Currently supports manual import and placeholder for API integrations.
"""
import uuid
from datetime import datetime
from typing import Optional

from src.db.database import get_db
from src.ingestion.rss_ingester import hash_content, match_startup


def store_social_post(startup_name: str, platform: str, content: str,
                      url: str = "", published_at: Optional[str] = None) -> Optional[str]:
    """
    Store a social media post (manually imported or via API).
    Platform: 'linkedin', 'twitter', 'instagram'
    """
    db = get_db()

    if not published_at:
        published_at = datetime.utcnow().isoformat()

    # Auto-generate title from content
    title = content[:100] + "..." if len(content) > 100 else content

    content_hash = hash_content(f"{platform}:{url or content}", title)
    existing = db.execute(
        "SELECT id FROM content_items WHERE content_hash = ?",
        (content_hash,)
    ).fetchone()
    if existing:
        return None

    # Try to match to startup by name
    startups = [dict(row) for row in db.execute("SELECT * FROM startups").fetchall()]
    matched = None
    for s in startups:
        if s["name"].lower() == startup_name.lower():
            matched = s
            break
    if not matched:
        matched = match_startup(content, startups)

    item_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO content_items
        (id, startup_id, source_type, source_name, url, title,
         published_at, raw_content, content_hash, classification)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (item_id, matched["id"] if matched else None, "social",
         f"{platform.capitalize()}", url, title, published_at, content,
         content_hash, "unclassified")
    )
    db.commit()
    return item_id


def bulk_import_social(posts: list) -> dict:
    """
    Bulk import social media posts.
    Each post should be a dict with:
    - startup_name, platform, content, url (optional), published_at (optional)
    """
    stats = {"imported": 0, "duplicate": 0, "errors": 0}

    for post in posts:
        try:
            result = store_social_post(
                startup_name=post.get("startup_name", ""),
                platform=post.get("platform", "unknown"),
                content=post.get("content", ""),
                url=post.get("url", ""),
                published_at=post.get("published_at")
            )
            if result:
                stats["imported"] += 1
            else:
                stats["duplicate"] += 1
        except Exception as e:
            print(f"Error importing social post: {e}")
            stats["errors"] += 1

    return stats
