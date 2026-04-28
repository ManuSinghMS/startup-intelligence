"""
HTML scraper — scrapes web pages for article content.
Used for press releases, blog posts, and pages without RSS feeds.
"""
import hashlib
import uuid
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from src.db.database import get_db
from src.ingestion.rss_ingester import match_startup, hash_content


async def scrape_page(url: str, timeout: float = 30.0) -> Optional[dict]:
    """
    Scrape a web page and extract article content.
    Returns dict with title, content, date, and url.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                timeout=timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": "StartupIntelBot/1.0 (Research Tool)"
                }
            )
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return None

    soup = BeautifulSoup(html, "lxml")

    # Extract title
    title = None
    for selector in ["h1", "title", 'meta[property="og:title"]']:
        el = soup.select_one(selector)
        if el:
            title = el.get("content") if el.name == "meta" else el.get_text(strip=True)
            break
    if not title:
        title = "Untitled"

    # Extract published date
    published = None
    for attr in ['meta[property="article:published_time"]', 'meta[name="date"]',
                 'time[datetime]', 'meta[property="og:updated_time"]']:
        el = soup.select_one(attr)
        if el:
            published = el.get("content") or el.get("datetime")
            break
    if not published:
        published = datetime.utcnow().isoformat()

    # Extract main content
    content = ""
    # Try common article selectors
    for selector in ["article", '[role="main"]', ".post-content",
                     ".article-body", ".entry-content", "main"]:
        el = soup.select_one(selector)
        if el:
            # Remove script and style tags
            for tag in el.find_all(["script", "style", "nav", "footer"]):
                tag.decompose()
            content = el.get_text(separator="\n", strip=True)
            break

    # Fallback: get all paragraph text
    if not content:
        paragraphs = soup.find_all("p")
        content = "\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30)

    # Extract description/meta
    description = ""
    meta_desc = soup.select_one('meta[property="og:description"]') or soup.select_one('meta[name="description"]')
    if meta_desc:
        description = meta_desc.get("content", "")

    return {
        "title": title,
        "content": content,
        "description": description,
        "published_at": published,
        "url": url
    }


async def scrape_and_store(url: str, source_name: str = "manual",
                           source_type: str = "press") -> Optional[str]:
    """
    Scrape a URL and store the content in the database.
    Returns the content_item id if stored, None if duplicate.
    """
    db = get_db()

    page = await scrape_page(url)
    if not page:
        return None

    # Dedup check
    content_hash = hash_content(url, page["title"])
    existing = db.execute(
        "SELECT id FROM content_items WHERE content_hash = ?",
        (content_hash,)
    ).fetchone()
    if existing:
        return None

    # Match to startup
    startups = [dict(row) for row in db.execute("SELECT * FROM startups").fetchall()]
    full_text = f"{page['title']} {page['content']}"
    matched = match_startup(full_text, startups)

    item_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO content_items
        (id, startup_id, source_type, source_name, url, title,
         published_at, raw_content, content_hash, classification)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (item_id, matched["id"] if matched else None, source_type, source_name,
         url, page["title"], page["published_at"], page["content"],
         content_hash, "unclassified")
    )
    db.commit()
    return item_id
