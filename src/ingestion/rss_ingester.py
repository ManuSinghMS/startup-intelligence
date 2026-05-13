"""
RSS feed ingester — fetches and parses RSS/Atom feeds,
matches articles to startups, and stores new content.
"""
import hashlib
import uuid
from datetime import datetime
from typing import Optional

import feedparser
import httpx

from src.db.database import get_db


def hash_content(url: str, title: str) -> str:
    """Generate a deduplication hash from URL + title."""
    raw = f"{url.strip().lower()}|{title.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def parse_date(entry) -> Optional[str]:
    """Extract and normalize publication date from a feed entry."""
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6]).isoformat()
            except Exception:
                pass
    for attr in ("published", "updated"):
        val = getattr(entry, attr, None)
        if val:
            return val
    return datetime.utcnow().isoformat()


def get_entry_content(entry) -> str:
    """Extract the main text content from a feed entry."""
    # Try content field first (full text)
    if hasattr(entry, "content") and entry.content:
        return entry.content[0].get("value", "")
    # Fall back to summary
    if hasattr(entry, "summary"):
        return entry.summary or ""
    # Fall back to description
    if hasattr(entry, "description"):
        return entry.description or ""
    return ""


_DOMAIN_SUFFIXES = (".ai", ".io", ".com", ".co", ".app", ".inc", " inc.", " inc", " corp.", " corp", " llc", " ltd")


def _name_variants(name: str) -> list:
    """Return matching variants of a company name (strip domain suffixes, etc.)."""
    variants = [name]
    lower = name.lower()
    for suffix in _DOMAIN_SUFFIXES:
        if lower.endswith(suffix):
            variants.append(name[: -len(suffix)].strip(" .,"))
            break
    return variants


def match_startup(text: str, startups: list) -> Optional[dict]:
    """
    Check if any startup name appears in the text.
    Returns the matched startup or None.
    """
    text_lower = text.lower()
    for startup in startups:
        for variant in _name_variants(startup["name"]):
            if len(variant) >= 3 and variant.lower() in text_lower:
                return startup
        if startup.get("legal_name"):
            for variant in _name_variants(startup["legal_name"]):
                if len(variant) >= 3 and variant.lower() in text_lower:
                    return startup
    return None


async def fetch_feed(feed_url: str, timeout: float = 30.0) -> Optional[feedparser.FeedParserDict]:
    """Fetch and parse an RSS/Atom feed."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(feed_url, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
            return feedparser.parse(resp.text)
    except Exception as e:
        print(f"Error fetching feed {feed_url}: {e}")
        return None


async def ingest_feed(source: dict, max_items: int = 50, fallback_startup_id: str = None) -> dict:
    """
    Ingest articles from a single RSS feed source.
    Returns stats about what was ingested.
    """
    db = get_db()
    stats = {"found": 0, "new": 0, "duplicate": 0, "matched": 0}

    feed_url = source.get("rss_feed_url")
    if not feed_url:
        return stats

    feed = await fetch_feed(feed_url)
    if not feed or not feed.entries:
        return stats

    # Load all startups for matching
    startups = [dict(row) for row in db.execute("SELECT * FROM startups").fetchall()]

    for entry in feed.entries[:max_items]:
        stats["found"] += 1

        title = getattr(entry, "title", "Untitled")
        url = getattr(entry, "link", "")
        content = get_entry_content(entry)
        published = parse_date(entry)

        # Deduplication check
        content_hash = hash_content(url, title)
        existing = db.execute(
            "SELECT id FROM content_items WHERE content_hash = ?",
            (content_hash,)
        ).fetchone()

        if existing:
            stats["duplicate"] += 1
            continue

        # Try to match to a startup
        full_text = f"{title} {content}"
        matched_startup = match_startup(full_text, startups)

        item_id = str(uuid.uuid4())
        startup_id = matched_startup["id"] if matched_startup else fallback_startup_id

        if matched_startup:
            stats["matched"] += 1

        # Only use source_id if it actually exists in the sources table
        db_source = db.execute("SELECT id FROM sources WHERE id = ?", (source["id"],)).fetchone()
        source_id = db_source["id"] if db_source else None

        db.execute(
            """INSERT INTO content_items
            (id, startup_id, source_id, source_type, source_name, url, title,
             published_at, raw_content, content_hash, classification)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, startup_id, source_id, source["type"], source["name"],
             url, title, published, content, content_hash, "unclassified")
        )
        stats["new"] += 1

    db.commit()

    # Update source last_fetched_at
    db.execute(
        "UPDATE sources SET last_fetched_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), source["id"])
    )
    db.commit()

    return stats


async def ingest_all_rss_feeds() -> list:
    """Ingest from all active RSS-enabled sources."""
    db = get_db()
    sources = [dict(row) for row in db.execute(
        "SELECT * FROM sources WHERE rss_feed_url IS NOT NULL AND is_active = 1"
    ).fetchall()]

    results = []
    for source in sources:
        log_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO ingestion_logs (id, source_id, status) VALUES (?, ?, 'running')",
            (log_id, source["id"])
        )
        db.commit()

        try:
            stats = await ingest_feed(source)
            db.execute(
                """UPDATE ingestion_logs
                SET completed_at = ?, items_found = ?, items_new = ?,
                    items_duplicate = ?, status = 'completed'
                WHERE id = ?""",
                (datetime.utcnow().isoformat(), stats["found"], stats["new"],
                 stats["duplicate"], log_id)
            )
        except Exception as e:
            db.execute(
                """UPDATE ingestion_logs
                SET completed_at = ?, status = 'error', error_message = ?
                WHERE id = ?""",
                (datetime.utcnow().isoformat(), str(e), log_id)
            )
            stats = {"source": source["name"], "error": str(e)}

        db.commit()
        results.append({"source": source["name"], **stats})
        print(f"  [{source['name']}] found={stats.get('found',0)}, "
              f"new={stats.get('new',0)}, dupes={stats.get('duplicate',0)}, "
              f"matched={stats.get('matched',0)}")

    return results
