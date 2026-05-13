from __future__ import annotations
"""
LinkedIn Post Ingester — URL-First Strategy

Architecture:
  Primary focus: Capture, validate, and store actual LinkedIn post URLs so 
  users can click through to read the posts.

  Phase 1: DISCOVERY — Find LinkedIn URLs for founders/companies (not stored as content)
  Phase 2: POST URL INGESTION — Search for actual LinkedIn posts from known people/companies

Search engine: Google News RSS only (free, reliable, no rate limits).
All post URLs are validated by `classify_linkedin_url()`.
Non-post results (profile directories, search results, etc.) are ignored.

Batch processing:
  --batch-size N        Process N companies per batch, pause between batches
  --sleep-seconds S     Seconds to wait between batches (default 10)
  --max-requests N      Hard cap on search requests per run
  --resume              Skip companies already ingested recently

Demo modes:
  --demo                Use hardcoded fixture data (no network calls)
  --curated             Process only startups that have LinkedIn URLs populated
  --dry-run             Log what would happen, no DB writes
"""
import os
import sys
import re
import uuid
import json
import hashlib
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from urllib.parse import quote_plus, urlparse

import feedparser
import httpx

from src.db.database import get_db

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("linkedin_ingester")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [LinkedIn] %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def is_configured() -> bool:
    """Always True — uses free Google News RSS, no keys needed."""
    return True


def _hash(text1: str, text2: str) -> str:
    raw = f"{text1.strip().lower()}|{text2.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()

_request_count = 0


# ---------------------------------------------------------------------------
# Post URL validation
# ---------------------------------------------------------------------------

_REJECT_URL_PATTERNS = [
    "/dir/", "/pub/", "/search/", "/jobs/", "/job/",
    "/login", "/signup", "/authwall", "/school/", "/learning/",
]


def is_linkedin_post_url(url: str) -> bool:
    """True only for actual single LinkedIn post URLs:
        linkedin.com/posts/<slug>
        linkedin.com/feed/update/<urn>
        linkedin.com/pulse/<slug>

    Returns False for company/profile post-feed pages like
    linkedin.com/company/<slug>/posts/ — those are activity pages.
    """
    if not url:
        return False
    u = url.lower()
    if "linkedin.com" not in u:
        return False
    if any(p in u for p in _REJECT_URL_PATTERNS):
        return False
    try:
        path = urlparse(u).path or ""
    except Exception:
        path = u
    if not path.startswith("/"):
        path = "/" + path.split("linkedin.com", 1)[-1]
    # The post-prefix patterns must appear at the start of the path
    return (
        path.startswith("/posts/")
        or path.startswith("/feed/update/")
        or path.startswith("/pulse/")
    )


def is_linkedin_activity_page(url: str) -> bool:
    """True for /recent-activity/ and /company/<slug>/posts/ pages.
    Useful but not a single post.
    """
    if not url:
        return False
    u = url.lower()
    if "linkedin.com" not in u:
        return False
    if "/recent-activity/" in u:
        return True
    if "/company/" in u and "/posts" in u:
        return True
    return False


def is_linkedin_profile_url(url: str) -> bool:
    """True for personal profile URLs (linkedin.com/in/<slug>) excluding
    activity/posts/recent-activity sub-pages.
    """
    if not url:
        return False
    u = url.lower()
    if "linkedin.com/in/" not in u:
        return False
    if any(s in u for s in ["/posts/", "/activity/", "/recent-activity/"]):
        return False
    if any(p in u for p in _REJECT_URL_PATTERNS):
        return False
    return True


def is_linkedin_company_page_url(url: str) -> bool:
    """True for company directory pages (linkedin.com/company/<slug>) excluding
    /posts and /activity sub-pages.
    """
    if not url:
        return False
    u = url.lower()
    if "linkedin.com/company/" not in u:
        return False
    if any(s in u for s in ["/posts/", "/activity/", "/recent-activity/"]):
        return False
    if any(p in u for p in _REJECT_URL_PATTERNS):
        return False
    return True


def canonicalize_linkedin_url(url: str) -> str:
    """Normalize a LinkedIn URL for deduplication.

    - lowercase scheme and host
    - drop query string and fragment
    - drop trailing slash
    - normalize host to www.linkedin.com
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return url.strip().lower()

    host = (parsed.netloc or "").lower()
    if host in ("linkedin.com", "m.linkedin.com", "ca.linkedin.com"):
        host = "www.linkedin.com"
    if not host and parsed.path.startswith("linkedin.com"):
        # No scheme provided
        host = "www.linkedin.com"
        path = "/" + parsed.path.split("linkedin.com", 1)[1].lstrip("/")
    else:
        path = parsed.path
    path = path.rstrip("/").lower() or "/"
    scheme = (parsed.scheme or "https").lower()
    if scheme not in ("http", "https"):
        scheme = "https"
    return f"{scheme}://{host}{path}"


def classify_linkedin_url(url: str, role_prefix: str = "general") -> str:
    """
    Classify a LinkedIn URL into predefined categories.
    Return 'invalid' if it's a generic page.
    Role prefix is usually 'founder', 'cofounder', or 'company'.
    """
    url_lower = (url or "").lower()

    # Reject non-actionable or generic noise URLs
    if any(p in url_lower for p in _REJECT_URL_PATTERNS):
        return "invalid"

    # Exact post URLs
    if is_linkedin_post_url(url):
        return f"{role_prefix}_post_url"

    # Recent activity pages (not single posts)
    if is_linkedin_activity_page(url):
        return f"{role_prefix}_activity_page"

    # Standard company pages
    if is_linkedin_company_page_url(url):
        if role_prefix == "company":
            return "company_page_url"
        return "invalid"

    # Standard profile pages
    if is_linkedin_profile_url(url):
        if role_prefix == "founder":
            return "founder_profile_url"
        if role_prefix == "cofounder":
            return "cofounder_profile_url"
        return "invalid"

    return "invalid"


# Title patterns that indicate NOT a post
_REJECT_TITLE_PATTERNS = [
    re.compile(r"\d+\+?\s+.*profiles?\b", re.IGNORECASE),
    re.compile(r"people\s+named\b", re.IGNORECASE),
    re.compile(r"\bsign\s+in\b", re.IGNORECASE),
    re.compile(r"\blog\s+in\b", re.IGNORECASE),
    re.compile(r"\bjoin\s+now\b", re.IGNORECASE),
    re.compile(r"\bjoin\s+linkedin\b", re.IGNORECASE),
    re.compile(r"\blinkedin.*?\blogin\b", re.IGNORECASE),
    re.compile(r"^\s*linkedin\s*$", re.IGNORECASE),
    re.compile(r"\d+\+?\s+.*connections?\b", re.IGNORECASE),
    re.compile(r"\bsee who you know\b", re.IGNORECASE),
]

_POST_CONTENT_SIGNALS = [
    "posted on linkedin", "shared on linkedin", "wrote on linkedin",
    "linkedin post", "announced on linkedin", "linkedin article",
    "published on linkedin", "said on linkedin", "commented on linkedin",
    "via linkedin", "linkedin update",
]

def is_valid_search_result(result: dict, role_prefix: str) -> tuple[bool, str, str]:
    """
    Validate whether a search result is valid, returning (is_valid, classification, reason).
    """
    title = (result.get("title") or "").strip()
    url = (result.get("url") or "").strip()
    snippet = (result.get("snippet") or "").strip()

    if not title or len(title) < 10:
        return False, "invalid", "title too short or empty"

    for pattern in _REJECT_TITLE_PATTERNS:
        if pattern.search(title):
            return False, "invalid", f"rejected title pattern: {pattern.pattern}"

    classification = classify_linkedin_url(url, role_prefix)
    
    # If it is a clean post URL
    if classification != "invalid":
        return True, classification, "valid linkedin URL"

    # Fallback to news mentions if the URL isn't natively LinkedIn but discusses a post
    combined = f"{title} {snippet}".lower()
    if "linkedin.com" not in url.lower():
        if any(s in combined for s in ["linkedin", "posted", "shared"]):
            if any(s in combined for s in _POST_CONTENT_SIGNALS[:5]):
                return True, "news_mention", "news about LinkedIn activity"

    return False, "invalid", "no post indicators found"


# ---------------------------------------------------------------------------
# Founder / name helpers
# ---------------------------------------------------------------------------

def _get_search_names(startup: Dict) -> List[Dict]:
    names = []
    founder = (startup.get("founder_name") or "").strip()
    if founder:
        names.append({
            "name": founder, "role": "founder",
            "linkedin_url": startup.get("founder_linkedin_url", ""),
        })

    cofounder = (startup.get("cofounder_name") or "").strip()
    if cofounder:
        names.append({
            "name": cofounder, "role": "cofounder",
            "linkedin_url": startup.get("cofounder_linkedin_url", ""),
        })

    if not names:
        contact = (startup.get("contact_name") or "").strip()
        if contact:
            for sep in [";", ",", "&", " and "]:
                if sep in contact:
                    parts = [p.strip() for p in contact.split(sep) if p.strip()]
                    for i, p in enumerate(parts):
                        names.append({
                            "name": p,
                            "role": "founder" if i == 0 else "cofounder",
                            "linkedin_url": "",
                        })
                    break
            if not names and len(contact) > 2:
                names.append({"name": contact, "role": "founder", "linkedin_url": ""})

    return names

def _extract_slug(linkedin_url: str, path_prefix: str = "company") -> Optional[str]:
    if not linkedin_url:
        return None
    url = linkedin_url.rstrip("/")
    parts = url.split("/")
    for i, part in enumerate(parts):
        if part == path_prefix and i + 1 < len(parts):
            return parts[i + 1]
    return None


# ---------------------------------------------------------------------------
# Google News RSS search
# ---------------------------------------------------------------------------

async def _search_google_news(query: str, timeout: float = 20.0) -> List[Dict]:
    global _request_count
    _request_count += 1
    encoded = quote_plus(query)
    feed_url = f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                feed_url, timeout=timeout, follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()

        feed = feedparser.parse(resp.text)
        if not feed or not feed.entries:
            return []

        results = []
        for entry in feed.entries[:10]:
            title = getattr(entry, "title", "")
            link = getattr(entry, "link", "")
            published = None
            for attr in ("published_parsed", "updated_parsed"):
                parsed = getattr(entry, attr, None)
                if parsed:
                    try:
                        published = datetime(*parsed[:6]).isoformat()
                    except Exception:
                        pass
                    break
            if not published:
                published = datetime.utcnow().isoformat()
            snippet = getattr(entry, "summary", "") or ""
            source_name = getattr(entry, "source", {})
            if hasattr(source_name, "title"):
                source_name = source_name.title
            elif isinstance(source_name, dict):
                source_name = source_name.get("title", "Google News")
            else:
                source_name = "Google News"

            results.append({
                "title": title, "url": link, "published_at": published,
                "snippet": snippet, "source_name": source_name,
            })
        return results
    except Exception as e:
        logger.warning("Google News search failed for '%s': %s", query, e)
        return []


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

async def _discover_linkedin_url(person_name: str, role: str, company_name: str) -> Optional[str]:
    query = f'site:linkedin.com/in/ "{person_name}" "{company_name}"'
    results = await _search_google_news(query)
    for r in results:
        classification = classify_linkedin_url(r.get("url", ""), role)
        if "profile_url" in classification:
            parsed = urlparse(r["url"])
            return f"https://www.linkedin.com{parsed.path.rstrip('/')}"
    return None

async def _discover_company_url(company_name: str) -> Optional[str]:
    query = f'site:linkedin.com/company/ "{company_name}"'
    results = await _search_google_news(query)
    for r in results:
        classification = classify_linkedin_url(r.get("url", ""), "company")
        if "company_page_url" in classification:
            parsed = urlparse(r["url"])
            return f"https://www.linkedin.com{parsed.path.rstrip('/')}"
    return None


# ---------------------------------------------------------------------------
# Post Ingestion
# ---------------------------------------------------------------------------

async def _search_posts(query: str, checkpoint: Optional[str] = None) -> List[Dict]:
    results = await _search_google_news(query)
    if checkpoint:
        results = [r for r in results if _is_after_checkpoint(r["published_at"], checkpoint)]
    return results

def _is_after_checkpoint(published_at: str, checkpoint: Optional[str]) -> bool:
    if not checkpoint:
        return True
    try:
        pub = datetime.fromisoformat(published_at.replace("Z", "+00:00").split("+")[0])
        chk = datetime.fromisoformat(checkpoint.replace("Z", "+00:00").split("+")[0])
        return pub > chk
    except (ValueError, TypeError):
        return True


# ---------------------------------------------------------------------------
# Demo fixtures
# ---------------------------------------------------------------------------

DEMO_POSTS = [
    {
        "title": "Excited to announce our Series A! 🚀",
        "url": "https://www.linkedin.com/posts/demo-founder_startup-fundraising-activity-123456",
        "published_at": datetime.utcnow().isoformat(),
        "snippet": "We've raised $5M to scale our AI-powered platform. Grateful to our investors and team.",
        "source_name": "LinkedIn",
    },
    {
        "title": "Our team is growing! We're hiring engineers in Toronto 🇨🇦",
        "url": "https://www.linkedin.com/posts/demo-company_hiring-engineering-activity-789012",
        "published_at": datetime.utcnow().isoformat(),
        "snippet": "Join our mission to transform healthcare. Open roles: Backend, ML, DevOps.",
        "source_name": "LinkedIn",
    },
    {
        "title": "Checking out our recent activity on LinkedIn",
        "url": "https://www.linkedin.com/in/demo-founder/recent-activity/",
        "published_at": datetime.utcnow().isoformat(),
        "snippet": "See recent activity here.",
        "source_name": "LinkedIn",
    },
]


# ---------------------------------------------------------------------------
# Core ingestion pipeline
# ---------------------------------------------------------------------------

def _store_content_item(
    db,
    *,
    startup_id: str,
    url: str,
    title: str,
    classification: str,
    author_name: str,
    person_role: str,
    published_at: str,
    raw_content: str,
    external_source: str,
    extra_metadata: Optional[Dict] = None,
) -> tuple[bool, str]:
    """
    Insert a LinkedIn URL-only content item with full field population.
    Returns (inserted, content_hash). Raises on DB error.
    """
    canonical = canonicalize_linkedin_url(url) if url else ""
    content_hash = _hash(f"linkedin_url:{canonical}", canonical or url)
    metadata = {
        "person_role": person_role,
        "url_kind": classification,
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    item_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO content_items
        (id, startup_id, source_type, source_name, external_source, url, canonical_url,
         title, author_name, published_at, post_date, raw_content, content_hash,
         classification, ingestion_status, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item_id, startup_id, "social", f"LinkedIn — {author_name or 'Manual'}",
            external_source, url, canonical, title or url,
            author_name, published_at, published_at, raw_content,
            content_hash, classification, "url_only", json.dumps(metadata),
        ),
    )
    return True, content_hash


async def ingest_for_company(
    startup: dict, dry_run: bool = False, max_requests: int = 0,
) -> dict:
    global _request_count

    stats = {
        "valid_posts": 0,
        "activity_pages": 0,
        "skipped": 0,
        "duplicate": 0,
        "discovery_updates": 0,
    }

    name = startup["name"]
    checkpoint = startup.get("last_ingested_at")
    found_posts = False

    logger.info("Processing %s", name)
    logger.info("Checking manual/Monday post URLs (handled by Monday sync / API)...")

    if max_requests > 0 and _request_count >= max_requests:
        logger.warning("Reached max-requests limit. Stopping.")
        return stats

    # DISCOVERY (URL-only — never stored as content items)
    people = _get_search_names(startup)
    db = get_db()
    for person in people:
        if not person["linkedin_url"] and len(person["name"]) >= 4:
            logger.info(
                "Founder URL missing for %s. Running discovery only.",
                person["name"],
            )
            discovered = await _discover_linkedin_url(person["name"], person["role"], name)
            if discovered:
                logger.info(
                    "Discovery found possible %s profile: %s",
                    person["role"], discovered,
                )
                logger.info("Not storing discovery result as content item.")
                if not dry_run:
                    field = f"{person['role']}_linkedin_url"
                    db.execute(
                        f"UPDATE startups SET {field} = ? WHERE id = ?",
                        (discovered, startup["id"]),
                    )
                    db.commit()
                person["linkedin_url"] = discovered
                stats["discovery_updates"] += 1

    company_url = startup.get("linkedin_url", "")
    if not company_url:
        logger.info("Company LinkedIn URL missing. Running discovery only.")
        discovered = await _discover_company_url(name)
        if discovered:
            logger.info("Discovery found possible company page: %s", discovered)
            logger.info("Not storing discovery result as content item.")
            if not dry_run:
                db.execute(
                    "UPDATE startups SET linkedin_url = ? WHERE id = ?",
                    (discovered, startup["id"]),
                )
                db.commit()
            company_url = discovered
            stats["discovery_updates"] += 1

    # POST URL SEARCH (best effort — only stored if URL passes post validation)
    all_candidates = []

    for person in people:
        if len(person["name"]) < 4:
            continue
        if max_requests > 0 and _request_count >= max_requests:
            break

        logger.info("Searching for recent LinkedIn post URLs for %s", person["name"])
        q1 = f'site:linkedin.com/posts/ "{person["name"]}"'
        res1 = await _search_posts(q1, checkpoint)
        for r in res1:
            r["_role"] = person["role"]
            r["_person"] = person["name"]
            all_candidates.append(r)

        await asyncio.sleep(1.0)

    if max_requests == 0 or _request_count < max_requests:
        logger.info("Searching for recent LinkedIn post URLs for company %s", name)
        slug = _extract_slug(company_url) if company_url else None
        q = f'site:linkedin.com/posts/ "{slug}"' if slug else f'site:linkedin.com/posts/ "{name}"'
        res_company = await _search_posts(q, checkpoint)
        for r in res_company:
            r["_role"] = "company"
            r["_person"] = name
            all_candidates.append(r)

    logger.info("Found %d candidate result(s)", len(all_candidates))

    valid_count = 0
    activity_count = 0
    skipped_count = 0

    seen_canonical = set()
    for result in all_candidates:
        role_prefix = result["_role"]
        is_valid, classification, reason = is_valid_search_result(result, role_prefix)

        if not is_valid:
            skipped_count += 1
            continue

        title = (result.get("title") or "").strip()
        url = (result.get("url") or "").strip()
        canonical = canonicalize_linkedin_url(url)

        # Profile/company-page URLs from search are discovery hints — they
        # update the startup row but are NOT stored as content items.
        if classification in ("founder_profile_url", "cofounder_profile_url", "company_page_url"):
            logger.info("Discovery found %s: %s confidence=low", classification, url)
            logger.info("Not storing discovery result as content item.")
            if not dry_run:
                field = {
                    "founder_profile_url":   "founder_linkedin_url",
                    "cofounder_profile_url": "cofounder_linkedin_url",
                    "company_page_url":      "linkedin_url",
                }[classification]
                try:
                    db.execute(
                        f"UPDATE startups SET {field} = COALESCE(NULLIF({field}, ''), ?) WHERE id = ?",
                        (url, startup["id"]),
                    )
                    db.commit()
                    stats["discovery_updates"] += 1
                except Exception as e:
                    logger.error("Error updating %s: %s", field, e)
            continue

        # Dedupe within this run
        if canonical in seen_canonical:
            stats["duplicate"] += 1
            continue
        seen_canonical.add(canonical)

        # Dedupe via DB (canonical hash)
        candidate_hash = _hash(f"linkedin_url:{canonical}", canonical or url)
        existing = db.execute(
            "SELECT id FROM content_items WHERE content_hash = ?",
            (candidate_hash,),
        ).fetchone()
        if existing:
            stats["duplicate"] += 1
            continue

        if "activity_page" in classification:
            activity_count += 1
        elif classification != "invalid":
            valid_count += 1

        if dry_run:
            logger.info("DRY-RUN would store %s: %s", classification, url or title)
            found_posts = True
            continue

        try:
            _store_content_item(
                db,
                startup_id=startup["id"],
                url=url,
                title=title,
                classification=classification,
                author_name=result["_person"],
                person_role=role_prefix,
                published_at=result.get("published_at") or datetime.utcnow().isoformat(),
                raw_content=result.get("snippet", ""),
                external_source="google_news_rss" if "linkedin.com" in url.lower() else "news_search",
                extra_metadata={"discovery_reason": reason},
            )
            found_posts = True
            logger.info("Stored %s: %s", classification, url)
        except Exception as e:
            logger.error("Error storing: %s", e)

    stats["valid_posts"] = valid_count
    stats["activity_pages"] = activity_count
    stats["skipped"] = skipped_count

    logger.info("Valid post URLs: %d", valid_count)
    logger.info("Activity pages: %d", activity_count)
    logger.info("Invalid/profile-only URLs skipped: %d", skipped_count)

    if not dry_run and found_posts:
        db.commit()

    return stats


# ---------------------------------------------------------------------------
# Batch processing & Manual Import
# ---------------------------------------------------------------------------

async def ingest_all_companies(
    dry_run: bool = False,
    limit: int = 0,
    batch_size: int = 0,
    sleep_seconds: int = 10,
    max_requests: int = 0,
    resume: bool = False,
    curated: bool = False,
    demo: bool = False,
) -> list:
    global _request_count
    _request_count = 0

    if demo:
        stats = {"valid_posts": 0, "activity_pages": 0, "skipped": 0, "duplicate": 0, "discovery_updates": 0}
        logger.info("DEMO MODE: Using %d sample URLs", len(DEMO_POSTS))
        for p in DEMO_POSTS:
            is_valid, classification, _ = is_valid_search_result(p, "founder")
            if is_valid:
                logger.info("DRY-RUN would store %s: %s", classification, p.get("url"))
                if "activity_page" in classification:
                    stats["activity_pages"] += 1
                else:
                    stats["valid_posts"] += 1
        return [{"startup": "Demo", **stats, "demo_mode": True}]

    db = get_db()
    query = "SELECT * FROM startups WHERE (tag IS NULL OR tag != 'not_active')"
    if curated:
        query += """ AND (linkedin_url IS NOT NULL AND linkedin_url != ''
                     OR founder_linkedin_url IS NOT NULL AND founder_linkedin_url != ''
                     OR cofounder_linkedin_url IS NOT NULL AND cofounder_linkedin_url != '')"""
    if resume:
        cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        query += f" AND (last_ingested_at IS NULL OR last_ingested_at < '{cutoff}')"
        
    query += " ORDER BY last_ingested_at ASC NULLS FIRST"

    if limit > 0: query += f" LIMIT {limit}"
    startups = [dict(row) for row in db.execute(query).fetchall()]

    results = []
    for i, startup in enumerate(startups):
        if max_requests > 0 and _request_count >= max_requests:
            break
        if batch_size > 0 and i > 0 and i % batch_size == 0:
            for remaining in range(sleep_seconds, 0, -1):
                if remaining % 5 == 0 or remaining <= 3:
                    logger.info("Resuming in %d seconds...", remaining)
                await asyncio.sleep(1.0)

        stats = await ingest_for_company(startup, dry_run=dry_run, max_requests=max_requests)
        results.append({"startup": startup["name"], **stats})
        
        if not dry_run and (stats["valid_posts"] > 0 or stats["activity_pages"] > 0):
            db.execute("UPDATE startups SET last_ingested_at = CURRENT_TIMESTAMP WHERE id = ?", (startup["id"],))
            db.commit()

        if i < len(startups) - 1:
            await asyncio.sleep(1.0)

    return results

def parse_url_field(raw: Optional[str]) -> List[str]:
    """Parse a Monday/CSV cell containing one or many URLs.
    Splits on newlines, commas, semicolons, and whitespace; dedupes.
    """
    if not raw:
        return []
    text = str(raw).replace("\r", "\n")
    for sep in [",", ";", "|"]:
        text = text.replace(sep, "\n")
    candidates = [p.strip() for p in text.split("\n") if p.strip()]
    seen = set()
    out = []
    for c in candidates:
        # Strip trailing punctuation like '.' or ')' that survives wrapping
        c = c.strip().strip(".,;:)(\"'")
        if not c or c.lower() in seen:
            continue
        seen.add(c.lower())
        out.append(c)
    return out


_STORABLE_AS_CONTENT = (
    "founder_post_url", "cofounder_post_url", "company_post_url",
    "founder_activity_page", "cofounder_activity_page", "company_activity_page",
    "news_mention", "web_mention",
)


def import_manual_posts(startup_id: str, posts: List[Dict], startup_name: str = "Unknown") -> Dict:
    """Manually import LinkedIn post URLs via API, Monday sync, or CSV.

    Each `posts` entry is a dict with at least `url`. Optional:
      - title, text, posted_at, author, author_role (founder|cofounder|company),
        notes, sales_nav_status

    Behaviors:
      - Valid post URLs and activity pages are stored as content items.
      - Bare profile / company-page URLs update the startup row instead
        (founder_linkedin_url / cofounder_linkedin_url / linkedin_url),
        and are NOT stored as content.
      - Anything else (jobs, login, search, profile directories) is skipped.
    """
    db = get_db()
    stats = {"imported": 0, "duplicate": 0, "errors": 0,
             "valid_posts": 0, "activity_pages": 0, "skipped": 0,
             "profile_updates": 0}

    logger.info("Processing %s", startup_name)
    logger.info("Checking manual/Monday post URLs...")
    logger.info("Found %d provided LinkedIn URL(s)", len(posts))

    seen_canonical = set()

    for post in posts:
        raw_url = (post.get("url") or "").strip()
        role = post.get("author_role") or "founder"
        if role not in ("founder", "cofounder", "company"):
            role = "founder"

        classification = classify_linkedin_url(raw_url, role)
        if classification == "invalid":
            stats["skipped"] += 1
            continue

        # Profile/company-page URLs update the startup row but never become
        # content items. This mirrors the auto-discovery behavior.
        if classification in ("founder_profile_url", "cofounder_profile_url", "company_page_url"):
            field = {
                "founder_profile_url":   "founder_linkedin_url",
                "cofounder_profile_url": "cofounder_linkedin_url",
                "company_page_url":      "linkedin_url",
            }[classification]
            try:
                db.execute(
                    f"UPDATE startups SET {field} = COALESCE(NULLIF({field}, ''), ?) WHERE id = ?",
                    (raw_url, startup_id),
                )
                db.commit()
                stats["profile_updates"] += 1
                logger.info("Updated startup.%s = %s (not stored as content)", field, raw_url)
            except Exception as e:
                stats["errors"] += 1
                logger.error("Error updating profile URL %s: %s", raw_url, e)
            continue

        if classification not in _STORABLE_AS_CONTENT:
            # Defensive fallback; should not normally hit here.
            stats["skipped"] += 1
            continue

        canonical = canonicalize_linkedin_url(raw_url)
        if canonical in seen_canonical:
            stats["duplicate"] += 1
            continue
        seen_canonical.add(canonical)

        content_hash = _hash(f"linkedin_url:{canonical}", canonical or raw_url)
        existing = db.execute(
            "SELECT id FROM content_items WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if existing:
            stats["duplicate"] += 1
            continue

        try:
            extra = {}
            if post.get("notes"):
                extra["notes"] = post["notes"]
            if post.get("sales_nav_status"):
                extra["sales_nav_status"] = post["sales_nav_status"]

            _store_content_item(
                db,
                startup_id=startup_id,
                url=raw_url,
                title=post.get("title") or raw_url,
                classification=classification,
                author_name=post.get("author") or startup_name,
                person_role=role,
                published_at=post.get("posted_at") or datetime.utcnow().isoformat(),
                raw_content=post.get("text", ""),
                external_source="manual",
                extra_metadata=extra or None,
            )
            stats["imported"] += 1
            if "activity_page" in classification:
                stats["activity_pages"] += 1
            else:
                stats["valid_posts"] += 1
            logger.info("Stored %s: %s", classification, raw_url)
        except Exception as e:
            stats["errors"] += 1
            logger.error("Error importing %s: %s", raw_url, e)

    logger.info("Valid post URLs: %d", stats["valid_posts"])
    logger.info("Activity pages: %d", stats["activity_pages"])
    logger.info("Profile/company URL updates (not stored as content): %d", stats["profile_updates"])
    logger.info("Invalid URLs skipped: %d", stats["skipped"])

    db.commit()
    return stats


def import_from_csv(csv_path: str, dry_run: bool = False) -> dict:
    """
    Import LinkedIn post URLs from a CSV.

    Expected columns (case-insensitive; missing columns are skipped):
      - startup_name OR startup_id           (one is required to match a row)
      - founder_post_urls                    (any number of URLs, comma- or newline-separated)
      - cofounder_post_urls
      - company_post_urls
      - linkedin_post_notes                  (optional, attached to all URLs in the row)
      - linkedin_post_date                   (optional ISO date)
      - sales_nav_status                     (optional)

    Each URL becomes one content item with role attribution.
    """
    import csv

    db = get_db()
    totals = {"rows": 0, "matched_startups": 0, "imported": 0,
              "duplicate": 0, "skipped": 0, "errors": 0,
              "valid_posts": 0, "activity_pages": 0,
              "missing_startup": 0}

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        # Normalize header keys to lowercase
        for raw_row in reader:
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw_row.items()}
            totals["rows"] += 1

            startup = None
            if row.get("startup_id"):
                startup = db.execute(
                    "SELECT id, name FROM startups WHERE id = ?",
                    (row["startup_id"],),
                ).fetchone()
            if not startup and row.get("startup_name"):
                startup = db.execute(
                    "SELECT id, name FROM startups WHERE LOWER(name) = LOWER(?)",
                    (row["startup_name"],),
                ).fetchone()

            if not startup:
                totals["missing_startup"] += 1
                logger.warning("Row %d: no matching startup for '%s'",
                               totals["rows"], row.get("startup_name") or row.get("startup_id"))
                continue
            totals["matched_startups"] += 1

            posted_at = row.get("linkedin_post_date") or datetime.utcnow().isoformat()
            notes = row.get("linkedin_post_notes") or ""
            sales_nav_status = row.get("sales_nav_status") or ""

            posts = []
            for col, role in [
                ("founder_post_urls", "founder"),
                ("cofounder_post_urls", "cofounder"),
                ("company_post_urls", "company"),
            ]:
                for url in parse_url_field(row.get(col)):
                    posts.append({
                        "url": url,
                        "author_role": role,
                        "posted_at": posted_at,
                        "notes": notes,
                        "sales_nav_status": sales_nav_status,
                    })

            # Also update startup's sales_nav columns if provided
            if not dry_run and (sales_nav_status or row.get("sales_nav_checked_at")):
                db.execute(
                    "UPDATE startups SET sales_nav_status = COALESCE(NULLIF(?, ''), sales_nav_status), "
                    "sales_nav_checked_at = COALESCE(NULLIF(?, ''), sales_nav_checked_at) WHERE id = ?",
                    (
                        sales_nav_status,
                        row.get("sales_nav_checked_at") or "",
                        dict(startup)["id"],
                    ),
                )
                db.commit()

            if dry_run:
                logger.info("DRY-RUN [%s] would import %d posts from CSV row",
                            dict(startup)["name"], len(posts))
                for p in posts:
                    cls = classify_linkedin_url(p["url"], p["author_role"])
                    logger.info("  %s: %s", cls, p["url"])
                totals["imported"] += sum(
                    1 for p in posts
                    if classify_linkedin_url(p["url"], p["author_role"]) != "invalid"
                )
                totals["skipped"] += sum(
                    1 for p in posts
                    if classify_linkedin_url(p["url"], p["author_role"]) == "invalid"
                )
                continue

            stats = import_manual_posts(
                dict(startup)["id"], posts, startup_name=dict(startup)["name"],
            )
            for k in ("imported", "duplicate", "errors",
                      "valid_posts", "activity_pages", "skipped"):
                totals[k] += stats.get(k, 0)

    logger.info("CSV import done: %d row(s), %d matched, %d posts stored, "
                "%d duplicate, %d skipped, %d unmatched startup(s)",
                totals["rows"], totals["matched_startups"], totals["imported"],
                totals["duplicate"], totals["skipped"], totals["missing_startup"])
    return totals

async def check_connection() -> dict:
    return {
        "status": "configured",
        "message": "LinkedIn ingester focuses on URLs. Best approach: Provide manual post URLs via Monday.",
        "method": "google_news_rss (url-focused)",
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LinkedIn Post URL Ingester")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--demo", action="store_true",
                        help="Use bundled fixture data; no network calls")
    parser.add_argument("--curated", action="store_true",
                        help="Only process startups that have any LinkedIn URL set")
    parser.add_argument("--resume", action="store_true",
                        help="Skip startups ingested in the last 24h")
    parser.add_argument("--company", type=str, default="",
                        help="Run for a single startup by name (case-insensitive)")
    parser.add_argument("--csv", type=str, default="",
                        help="Import LinkedIn post URLs from a CSV file (manual path)")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--sleep-seconds", type=int, default=10)
    parser.add_argument("--max-requests", type=int, default=0)
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from src.db.database import init_db
    from src.db.migrate import migrate
    try:
        migrate()
    except Exception as e:
        print(f"Migration note: {e}")
    init_db()

    if args.csv:
        result = import_from_csv(args.csv, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))
    elif args.company:
        db = get_db()
        startup = db.execute("SELECT * FROM startups WHERE LOWER(name) = LOWER(?)", (args.company,)).fetchone()
        if startup:
            result = asyncio.run(ingest_for_company(dict(startup), dry_run=args.dry_run, max_requests=args.max_requests))
            print(json.dumps(result, indent=2, default=str))
        else:
            print(json.dumps({"error": f"No startup matched name='{args.company}'"}, indent=2))
    else:
        results = asyncio.run(ingest_all_companies(
            dry_run=args.dry_run, limit=args.limit, batch_size=args.batch_size,
            sleep_seconds=args.sleep_seconds, max_requests=args.max_requests,
            resume=args.resume, curated=args.curated, demo=args.demo
        ))
        print(json.dumps(results, indent=2, default=str))
