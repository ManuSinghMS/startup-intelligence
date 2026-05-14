"""
Company-specific news ingester.
Instead of scraping general feeds and hoping to match,
this searches Google News for EACH company by name.
This guarantees all results are mapped to a specific startup.

CLI Options:
  --sleep-seconds N       Sleep N seconds between companies (default: 30)
  --batch-size N         Process N companies per batch (default: 10)
  --max-search-requests N  Maximum search requests per run (default: 50)
  --disable-web-search   Skip DuckDuckGo generic web search
  --resume               Skip companies already ingested recently
"""
import argparse
import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus

import feedparser
import httpx

from src.db.database import get_db
from src.ingestion.html_scraper import scrape_and_store


# ---------------------------------------------------------------------------
# CLI Configuration
# ---------------------------------------------------------------------------

# Default configuration values
DEFAULT_SLEEP_SECONDS = 30
DEFAULT_BATCH_SIZE = 10
DEFAULT_MAX_SEARCH_REQUESTS = 50

# Global rate limit state
_rate_limited = False
_rate_limit_expiry = None
_search_request_count = 0


def parse_cli_args():
    """Parse command-line arguments for ingestion control."""
    parser = argparse.ArgumentParser(
        description="Company news ingester CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--sleep-seconds", type=int, default=DEFAULT_SLEEP_SECONDS,
        help=f"Sleep N seconds between companies (default: {DEFAULT_SLEEP_SECONDS})"
    )
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"Process N companies per batch (default: {DEFAULT_BATCH_SIZE})"
    )
    parser.add_argument(
        "--max-search-requests", type=int, default=DEFAULT_MAX_SEARCH_REQUESTS,
        help=f"Maximum search requests per run (default: {DEFAULT_MAX_SEARCH_REQUESTS})"
    )
    parser.add_argument(
        "--disable-web-search", action="store_true",
        help="Skip DuckDuckGo generic web search (use only RSS/Google News)"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip companies ingested within the last 24 hours"
    )
    return parser.parse_args()




# ---------------------------------------------------------------------------
# Search Result Caching
# ---------------------------------------------------------------------------

def _get_cache_dir():
    """Get or create the search cache directory."""
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "search_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _get_cache_key(query: str) -> str:
    """Generate a cache key from a search query."""
    return hashlib.sha256(query.encode()).hexdigest()


def get_cached_results(query: str) -> Optional[list]:
    """Get cached search results if they exist and are not expired."""
    cache_dir = _get_cache_dir()
    cache_key = _get_cache_key(query)
    cache_file = os.path.join(cache_dir, f"{cache_key}.json")
    
    if not os.path.exists(cache_file):
        return None
    
    try:
        with open(cache_file, "r") as f:
            cache_data = json.load(f)
        
        # Check if cache is expired (24 hours)
        cached_at = datetime.fromisoformat(cache_data.get("cached_at", "2000-01-01"))
        if datetime.utcnow() - cached_at > timedelta(hours=24):
            return None
        
        return cache_data.get("results")
    except Exception:
        return None


def cache_results(query: str, results: list):
    """Cache search results for future use."""
    cache_dir = _get_cache_dir()
    cache_key = _get_cache_key(query)
    cache_file = os.path.join(cache_dir, f"{cache_key}.json")
    
    try:
        with open(cache_file, "w") as f:
            json.dump({
                "query": query,
                "results": results,
                "cached_at": datetime.utcnow().isoformat()
            }, f)
    except Exception:
        pass  # Cache failures are non-fatal


# ---------------------------------------------------------------------------
# Rate Limit Handling
# ---------------------------------------------------------------------------

def is_rate_limited() -> bool:
    """Check if we're currently rate-limited."""
    global _rate_limited, _rate_limit_expiry
    
    if _rate_limited and _rate_limit_expiry:
        if datetime.utcnow() < _rate_limit_expiry:
            return True
        # Rate limit expired, reset state
        _rate_limited = False
        _rate_limit_expiry = None
    
    return False


def handle_rate_limit(error_msg: str):
    """Handle DuckDuckGo rate limiting."""
    global _rate_limited, _rate_limit_expiry
    
    if "202" in error_msg or "ratelimit" in error_msg.lower():
        _rate_limited = True
        # Default to 1 hour cooldown
        _rate_limit_expiry = datetime.utcnow() + timedelta(hours=1)
        print(f"\n[Search] DuckDuckGo rate-limited. Stopping web search for this run.")
        print(f"[Search] Try again later or use manual/Monday URLs.")
        return True
    
    return False


def increment_search_count():
    """Increment the search request counter."""
    global _search_request_count
    _search_request_count += 1


def get_search_count() -> int:
    """Get the current search request count."""
    return _search_request_count


def reset_search_count():
    """Reset the search request counter."""
    global _search_request_count
    _search_request_count = 0


async def ddgs_search_with_backoff(query: str, max_results: int = 5) -> Optional[list]:
    """Run a DuckDuckGo search with exponential backoff on rate limits."""
    delays = [30, 60, 120]
    for attempt, delay in enumerate(delays, start=1):
        try:
            from duckduckgo_search import DDGS
            results = DDGS().text(query, max_results=max_results)
            return results
        except Exception as e:
            msg = str(e)
            if "202" in msg or "ratelimit" in msg.lower() or "Ratelimit" in msg:
                print(f"    [DDGS] Rate limited. Waiting {delay}s before retry {attempt}/{len(delays)}...")
                await asyncio.sleep(delay)
            else:
                print(f"    duckduckgo_search error: {e}")
                return None
    print(f"    [DDGS] Giving up after {len(delays)} retries.")
    return None


def hash_content(url: str, title: str) -> str:
    """Generate a deduplication hash."""
    raw = f"{url.strip().lower()}|{title.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def parse_date(entry) -> Optional[str]:
    """Extract and normalize publication date."""
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
    """Extract text from a feed entry."""
    if hasattr(entry, "content") and entry.content:
        return entry.content[0].get("value", "")
    if hasattr(entry, "summary"):
        return entry.summary or ""
    if hasattr(entry, "description"):
        return entry.description or ""
    return ""


async def search_google_news(query: str, timeout: float = 30.0):
    """
    Search Google News RSS for a specific query.
    Google News provides RSS feeds at:
    https://news.google.com/rss/search?q=QUERY&hl=en
    """
    encoded_query = quote_plus(query)
    feed_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en&gl=US&ceid=US:en"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                feed_url,
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; StartupIntel/1.0)"}
            )
            resp.raise_for_status()
            return feedparser.parse(resp.text)
    except Exception as e:
        print(f"  Error searching Google News for '{query}': {e}")
        return None


def is_relevant_result(title: str, content: str, company_name: str,
                       legal_name: str = None,
                       founder_names: str = None,
                       cofounder_names: str = None) -> tuple:
    """
    Check if a search result is relevant to a startup.
    Delegates to the scoring module which weights founders > company names.

    Returns (is_relevant: bool, confidence: float) where confidence
    is between 0.0 and 1.0.
    """
    from src.scoring.relevance import score_relevance
    return score_relevance(
        title=title,
        content=content,
        company_name=company_name,
        legal_name=legal_name,
        founder_names=founder_names,
        cofounder_names=cofounder_names,
    )


async def verify_relevance_with_llm(title: str, content: str,
                                     startup: dict) -> bool:
    """
    Use the LLM to verify whether an article is genuinely about this
    specific startup from The Forge (McMaster University incubator).

    This catches false positives where a company name like "Take Care"
    matches generic phrases in unrelated articles.

    Returns True if the article IS about this company, False if not.
    Falls back to True (permissive) if LLM is not configured.
    """
    try:
        from src.llm.provider import get_llm_client, get_model_name, is_configured
        if not is_configured():
            return True  # No LLM = fallback to string matching only

        client = get_llm_client()
        if not client:
            return True

        model = get_model_name()

        # Build company context
        company_info = f"Company: {startup['name']}"
        if startup.get("legal_name"):
            company_info += f" (legal name: {startup['legal_name']})"
        if startup.get("industry"):
            company_info += f"\nIndustry: {startup['industry']}"
        if startup.get("description"):
            company_info += f"\nDescription: {startup['description'][:200]}"
        if startup.get("website"):
            company_info += f"\nWebsite: {startup['website']}"

        # Truncate article content to save tokens
        article_snippet = content[:800] if content else ""

        prompt = f"""You are a relevance filter for a startup intelligence platform.

I need you to determine if this news article is ACTUALLY about this specific startup company, or if it's a false positive match (e.g. the company name appears as a common phrase in an unrelated article).

COMPANY INFORMATION:
{company_info}
This company is part of The Forge, a startup incubator at McMaster University in Hamilton, Ontario, Canada.

ARTICLE:
Title: {title}
Content snippet: {article_snippet}

QUESTION: Is this article genuinely about the startup "{startup['name']}" described above?

Think carefully:
- Does the article discuss this specific company, its products, founders, or industry?
- Or does the company name just happen to appear as a common English phrase?
- Would someone tracking this startup find this article useful?

Reply with ONLY a JSON object: {{"relevant": true}} or {{"relevant": false}}"""

        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=50,
        )

        result_text = response.choices[0].message.content.strip()
        # Parse the JSON response
        try:
            result = json.loads(result_text)
            return result.get("relevant", True)
        except json.JSONDecodeError:
            # Try to extract from text
            lower = result_text.lower()
            if '"relevant": false' in lower or '"relevant":false' in lower:
                return False
            if '"relevant": true' in lower or '"relevant":true' in lower:
                return True
            return True  # Default to permissive

    except Exception as e:
        print(f"    [LLM verify] Error: {e}")
        return True  # Fallback: allow the article through


async def ingest_for_company(startup: dict, max_items: int = 8, fast: bool = True) -> dict:
    """
    Search Google News for a specific company and store results.
    Only keeps results that genuinely mention the company name.

    fast=True (default for Fly.io trial / time-constrained runs):
      - Skips LLM relevance verification (relies on scoring)
      - Skips website scraping
      - Limits to one Google News query per company
    """
    db = get_db()
    stats = {"found": 0, "new": 0, "duplicate": 0, "filtered": 0, "new_item_ids": []}

    name = startup["name"]
    legal_name = startup.get("legal_name", "")

    # Build search queries — use exact phrase match with quotes
    # and add Forge incubator context to reduce false positives
    forge_context = 'OR "The Forge" OR "McMaster" OR "Hamilton" OR "startup" OR "incubator"'

    search_queries = [f'"{name}"']
    if legal_name and legal_name.lower() != name.lower():
        search_queries.append(f'"{legal_name}"')

    # For short/generic names, ALWAYS add contextual terms
    name_words = name.replace("Inc.", "").replace("Inc", "").replace("Corp.", "").strip().split()
    if len(name_words) <= 2:
        search_queries = [f'"{name}" ({forge_context})']

    # If the company has a website, add the domain as context
    website = startup.get("website", "")
    if website:
        domain = website.replace("https://", "").replace("http://", "").split("/")[0]
        domain = domain.replace("www.", "")
        if domain:
            search_queries.append(f'"{name}" OR site:{domain}')

    # If the company has a description, use key terms
    description = startup.get("description", "")
    if description and len(name_words) <= 2:
        desc_words = [w for w in description.split()[:5]
                      if len(w) > 3 and w.lower() not in ("the", "and", "for", "with", "from")]
        if desc_words:
            desc_context = " OR ".join(f'"{w}"' for w in desc_words[:3])
            search_queries = [f'"{name}" ({desc_context} {forge_context})']

    # In fast mode, only use the first (most targeted) query to save time
    queries_to_run = search_queries[:1] if fast else search_queries

    for query in queries_to_run:
        feed = await search_google_news(query)
        if not feed or not feed.entries:
            continue

        for entry in feed.entries[:max_items]:
            stats["found"] += 1

            title = getattr(entry, "title", "Untitled")
            url = getattr(entry, "link", "")
            content = get_entry_content(entry)
            published = parse_date(entry)
            source_name = getattr(entry, "source", {})
            if hasattr(source_name, "title"):
                source_name = source_name.title
            elif isinstance(source_name, dict):
                source_name = source_name.get("title", "Google News")
            else:
                source_name = "Google News"

            # RELEVANCE CHECK: Only keep if company name actually appears
            relevant, confidence = is_relevant_result(
                title, content, name, legal_name,
                founder_names=startup.get("contact_name", "")
            )
            if not relevant:
                stats["filtered"] += 1
                continue

            # Skip low confidence results for generic company names
            if confidence < 0.5 and len(name_words) <= 2:
                stats["filtered"] += 1
                continue

            # LLM VERIFICATION: only run in slow/precise mode — too slow for trial runs.
            if not fast and (len(name_words) <= 3 or confidence < 0.8):
                llm_relevant = await verify_relevance_with_llm(
                    title, content, startup
                )
                if not llm_relevant:
                    stats["filtered"] += 1
                    print(f"    [LLM FILTER] Rejected: '{title[:60]}...' for {name}")
                    continue
            elif fast and confidence < 0.45:
                # In fast mode, raise the scoring bar a bit to compensate
                # for skipping the LLM verifier.
                stats["filtered"] += 1
                continue

            # Dedup check
            content_hash = hash_content(url, title)
            existing = db.execute(
                "SELECT id FROM content_items WHERE content_hash = ?",
                (content_hash,)
            ).fetchone()

            if existing:
                stats["duplicate"] += 1
                continue

            item_id = str(uuid.uuid4())
            db.execute(
                """INSERT INTO content_items
                (id, startup_id, source_type, source_name, url, title,
                 published_at, raw_content, content_hash, classification,
                 confidence_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item_id, startup["id"], "news", source_name,
                 url, title, published, content, content_hash, "unclassified",
                 confidence)
            )
            stats["new"] += 1
            stats["new_item_ids"].append(item_id)

    # Direct website scraping — skipped in fast mode (slow, error-prone on Fly.io trial)
    website = startup.get("website", "")
    if website and not fast:
        try:
            print(f"  [{name}] Scraping website: {website}")
            item_id = await scrape_and_store(website, source_name=f"{name} Website", source_type="blog")
            stats["found"] += 1
            if item_id:
                stats["new"] += 1
            else:
                stats["duplicate"] += 1
        except Exception as e:
            print(f"    Error scraping website {website}: {e}")

    # Generic Web Search (disabled by default — DDG rate-limits aggressively on free tier)
    # Set ENABLE_DDGS=true in environment to enable
    if os.environ.get("ENABLE_DDGS", "").lower() != "true":
        db.commit()
        return stats

    try:
        from duckduckgo_search import DDGS
        search_query = f"{name} startup news"
        if startup.get("industry"):
            search_query += f" {startup['industry']}"

        print(f"  [{name}] Running generic web search for '{search_query}'")
        
        top_links = []
        try:
            results = await ddgs_search_with_backoff(search_query, max_results=5)
            if results:
                # Strip common corporate suffixes for a cleaner, full-name match
                clean_name = name.lower()
                for suffix in [" inc.", " inc", " corp.", " corp", " llc", " ltd.", " ltd", " group"]:
                    if clean_name.endswith(suffix):
                        clean_name = clean_name[:-len(suffix)]
                clean_name = clean_name.strip("., ")

                for r in results:
                    r_title = r.get("title", "").lower()
                    r_body = r.get("body", "").lower()
                    r_href = r.get("href", "").lower()
                    if clean_name in r_title or clean_name in r_body or clean_name in r_href:
                        top_links.append(r.get("href"))
                        if len(top_links) >= 2:
                            break
                    else:
                        print(f"    [DDGS Filter] Rejected irrelevant result: {r.get('href')}")
        except Exception as e:
            print(f"    duckduckgo_search error: {e}")

        for link in top_links:
            # Skip domains that heavily block basic scrapers or aren't articles
            if any(domain in link for domain in ["linkedin.com", "twitter.com", "facebook.com", "youtube.com", "instagram.com"]):
                continue
                
            print(f"    Scraping generic link: {link}")
            
            # Manually scrape page so we can enforce strict confidence checks
            from src.ingestion.html_scraper import scrape_page
            page = await scrape_page(link)
            if not page:
                continue

            # Verify relevance using our robust string matching
            relevant, confidence = is_relevant_result(
                page["title"], page["content"], name, legal_name,
                founder_names=startup.get("contact_name", "")
            )

            # Strict Generic Search Filter: If confidence < 0.6, the article is heavily scrutinized
            if not relevant or confidence < 0.6:
                llm_relevant = await verify_relevance_with_llm(page["title"], page["content"], startup)
                if not llm_relevant:
                    stats["filtered"] += 1
                    print(f"    [DDGS Filter] Rejected low confidence ({confidence}): '{page['title'][:60]}...'")
                    continue

            # Dedup check
            content_hash = hash_content(link, page["title"])
            existing = db.execute(
                "SELECT id FROM content_items WHERE content_hash = ?",
                (content_hash,)
            ).fetchone()

            stats["found"] += 1
            if existing:
                stats["duplicate"] += 1
                continue

            item_id = str(uuid.uuid4())
            db.execute(
                """INSERT INTO content_items
                (id, startup_id, source_type, source_name, url, title,
                 published_at, raw_content, content_hash, classification, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item_id, startup["id"], "news", "Google Search",
                 link, page["title"], page["published_at"], page["content"],
                 content_hash, "unclassified", confidence)
            )
            stats["new"] += 1
                
    except Exception as e:
        print(f"    Error during generic web search: {e}")

    db.commit()
    return stats


async def _run_ingestion(startups: list, progress: Optional[dict] = None) -> list:
    """
    Internal helper — run company-specific news search for a list of startups.

    Per-company flow (tuned to fit a Fly.io trial 5-minute window):
      1. Fast Google News ingest for the company
      2. Immediately classify the company's new items (so partial work survives
         even if the machine is killed by Fly's trial timeout)
      3. Stamp last_ingested_at and update the progress dict
    """
    db = get_db()
    results = []
    log_id = str(uuid.uuid4())

    db.execute(
        "INSERT INTO ingestion_logs (id, status) VALUES (?, 'running')",
        (log_id,)
    )
    db.commit()

    total_new = 0
    total_found = 0
    total_classified = 0

    for idx, startup in enumerate(startups):
        if progress is not None:
            progress["current_company"] = startup["name"]
            progress["completed"] = idx
            progress["total"] = len(startups)

        try:
            stats = await ingest_for_company(startup, fast=True)
            total_new += stats["new"]
            total_found += stats["found"]

            # Per-company classification — catches up the items just inserted.
            # Doing this inline (instead of in one big batch at the end) means
            # if the Fly.io trial kills the machine mid-batch, every company
            # we've already processed is fully classified, not stuck in
            # 'unclassified' limbo.
            classified_here = 0
            if stats["new_item_ids"]:
                try:
                    from src.llm.classifier import classify_content_item
                    for item_id in stats["new_item_ids"]:
                        try:
                            await classify_content_item(item_id)
                            classified_here += 1
                        except Exception as ce:
                            print(f"    [Classify] {item_id} error: {ce}")
                except Exception as e:
                    print(f"  [Classify import] {e}")
            total_classified += classified_here

            results.append({
                "startup": startup["name"],
                **{k: v for k, v in stats.items() if k != "new_item_ids"},
                "classified": classified_here,
            })
            print(f"  [{startup['name']}] found={stats['found']}, "
                  f"new={stats['new']}, classified={classified_here}, "
                  f"dupes={stats['duplicate']}")
        except Exception as e:
            print(f"  [{startup['name']}] Error: {e}")
            results.append({
                "startup": startup["name"],
                "error": str(e)
            })

        # Record ingestion time to support round-robin batching
        db.execute(
            "UPDATE startups SET last_ingested_at = CURRENT_TIMESTAMP WHERE id = ?",
            (startup["id"],)
        )
        db.commit()

        if progress is not None:
            progress["completed"] = idx + 1
            progress["new_items"] = total_new
            progress["classified"] = total_classified

        # Small breather between companies — keeps us well under Groq's
        # free-tier RPM ceiling without burning the 5-minute Fly trial budget.
        await asyncio.sleep(0.5)

    # Update log
    db.execute(
        """UPDATE ingestion_logs
        SET completed_at = ?, items_found = ?, items_new = ?,
            status = 'completed'
        WHERE id = ?""",
        (datetime.utcnow().isoformat(), total_found, total_new, log_id)
    )
    db.commit()

    if progress is not None:
        progress["status"] = "completed"
        progress["finished_at"] = datetime.utcnow().isoformat()

    return results


DEFAULT_BATCH_LIMIT = int(os.environ.get("INGEST_BATCH_LIMIT", "25"))


async def ingest_all_companies(limit: int = DEFAULT_BATCH_LIMIT,
                               progress: Optional[dict] = None) -> list:
    """
    Run ingestion for a rolling batch of companies.
    Selects the `limit` number of companies with the oldest `last_ingested_at`
    timestamps, processes them, and updates their timestamps.

    The Forge RSS feed is intentionally skipped here because it is slow and
    eats into the 5-minute Fly.io trial budget. Run it separately via
    POST /api/ingest/forge-feed when needed.
    """
    db = get_db()

    startups = [dict(row) for row in db.execute(
        """
        SELECT * FROM startups
        WHERE tag IS NULL OR tag != 'not_active'
        ORDER BY last_ingested_at ASC NULLS FIRST
        LIMIT ?
        """, (limit,)
    ).fetchall()]
    return await _run_ingestion(startups, progress=progress)


async def ingest_selected_companies(startup_ids: list,
                                    progress: Optional[dict] = None) -> list:
    """
    Run company-specific news search for SELECTED startups only.
    """
    db = get_db()
    placeholders = ",".join("?" for _ in startup_ids)
    startups = [dict(row) for row in db.execute(
        f"""SELECT * FROM startups
            WHERE id IN ({placeholders})
            ORDER BY name""",
        startup_ids
    ).fetchall()]
    return await _run_ingestion(startups, progress=progress)
