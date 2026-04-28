"""
LinkedIn & social media API routes.
"""
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/social", tags=["social"])


# --------------- LinkedIn ---------------

@router.get("/linkedin/status")
async def linkedin_status():
    """Check if LinkedIn post ingestion is configured and ready."""
    from src.ingestion.linkedin_ingester import check_connection
    return await check_connection()


@router.post("/linkedin/ingest")
async def ingest_linkedin(
    dry_run: bool = Query(False, description="Log only, don't write to DB"),
    limit: int = Query(0, description="Max companies (0=all)"),
    batch_size: int = Query(0, description="Companies per batch (0=no batching)"),
    sleep_seconds: int = Query(10, description="Seconds between batches"),
    max_requests: int = Query(0, description="Max search requests (0=unlimited)"),
    curated: bool = Query(False, description="Only startups with LinkedIn URLs"),
    resume: bool = Query(False, description="Skip recently ingested"),
    demo: bool = Query(False, description="Use demo fixture data"),
):
    """
    Run LinkedIn POST ingestion for all active startups.
    Only collects actual posts, not profile pages or directories.
    """
    from src.ingestion.linkedin_ingester import ingest_all_companies
    results = await ingest_all_companies(
        dry_run=dry_run, limit=limit, batch_size=batch_size,
        sleep_seconds=sleep_seconds, max_requests=max_requests,
        curated=curated, resume=resume, demo=demo,
    )
    total_posts = sum(r.get("valid_posts", 0) for r in results)
    total_activity = sum(r.get("activity_pages", 0) for r in results)
    total_skipped = sum(r.get("skipped", 0) for r in results)
    total_duplicate = sum(r.get("duplicate", 0) for r in results)
    total_discovery = sum(r.get("discovery_updates", 0) for r in results)
    return {
        "status": "completed",
        "dry_run": dry_run,
        "total_valid_posts": total_posts,
        "total_activity_pages": total_activity,
        "total_skipped": total_skipped,
        "total_duplicate": total_duplicate,
        "total_discovery_updates": total_discovery,
        "results": results,
    }


@router.post("/linkedin/ingest/{startup_id}")
async def ingest_linkedin_company(
    startup_id: str,
    dry_run: bool = Query(False, description="Log only, don't write to DB"),
):
    """Run LinkedIn post ingestion for a single company."""
    from src.ingestion.linkedin_ingester import ingest_for_company
    from src.db.database import get_db

    db = get_db()
    startup = db.execute("SELECT * FROM startups WHERE id = ?", (startup_id,)).fetchone()
    if not startup:
        raise HTTPException(status_code=404, detail="Startup not found")

    startup = dict(startup)
    stats = await ingest_for_company(startup, dry_run=dry_run)
    return {"startup": startup["name"], "dry_run": dry_run, **stats}


class ManualPostInput(BaseModel):
    url: Optional[str] = None
    title: Optional[str] = None
    text: Optional[str] = None
    author: Optional[str] = None
    posted_at: Optional[str] = None


class ManualPostsRequest(BaseModel):
    startup_id: str
    posts: list[ManualPostInput]


@router.post("/linkedin/import-posts")
def import_linkedin_posts(request: ManualPostsRequest):
    """
    Manually import LinkedIn post URLs/text for a startup.
    Use this when automated scraping isn't reliable.
    """
    from src.ingestion.linkedin_ingester import import_manual_posts
    from src.db.database import get_db

    db = get_db()
    startup = db.execute(
        "SELECT id, name FROM startups WHERE id = ?", (request.startup_id,)
    ).fetchone()
    if not startup:
        raise HTTPException(status_code=404, detail="Startup not found")

    posts_dicts = [p.dict() for p in request.posts]
    stats = import_manual_posts(request.startup_id, posts_dicts)
    return {"startup": dict(startup)["name"], **stats}


# --------------- Newsletter ---------------

@router.get("/newsletter/status")
def newsletter_status():
    """Check if newsletter email ingestion is configured."""
    from src.ingestion.email_ingester import check_connection
    return check_connection()


@router.post("/newsletter/ingest")
def ingest_newsletters():
    """Poll the newsletter inbox and ingest new emails."""
    from src.ingestion.email_ingester import is_configured, ingest_newsletters as do_ingest
    if not is_configured():
        raise HTTPException(
            status_code=400,
            detail="Newsletter email not configured. Set NEWSLETTER_EMAIL and NEWSLETTER_APP_PASSWORD in .env"
        )
    return do_ingest()
