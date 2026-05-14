"""
Health check, ingestion triggers, analytics, and system status routes.

Ingestion design notes
----------------------
The Fly.io trial tier kills machines after 5 minutes of activity. To keep
ingestion responsive and resilient to that timeout:

* POST /api/ingest returns immediately with status="started" and kicks off
  a background asyncio task.
* The background task processes 25 companies (configurable via
  INGEST_BATCH_LIMIT) using the oldest-first rolling batch order, so
  repeated clicks cycle through the full portfolio.
* Each company's items are classified immediately after that company is
  ingested. If the trial timeout kills the machine mid-batch, all already-
  processed companies remain fully classified — no items stuck in the
  'unclassified' state.
* GET /api/ingest/status returns live progress (current company, X of Y,
  new items so far, classified so far) which the dashboard polls.
"""
import asyncio
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter
from pydantic import BaseModel

from src.db.database import get_db, count_records

router = APIRouter(prefix="/api", tags=["system"])


# Module-level state for the currently running ingestion job. There is at
# most one job at a time per process; clicking the button while a job is
# already running returns the existing progress instead of starting a new one.
_ingestion_state: dict = {
    "status": "idle",          # idle | running | completed | error
    "started_at": None,
    "finished_at": None,
    "current_company": None,
    "completed": 0,
    "total": 0,
    "new_items": 0,
    "classified": 0,
    "mode": None,              # "all" | "selected"
    "error": None,
    "recent_log": [],          # last N log lines, for the UI
}

# In-memory log ring buffer for the UI ("View Logs" panel).
_log_buffer: List[str] = []
_LOG_BUFFER_MAX = 200


def _log(msg: str):
    """Append a line to both stdout and the in-memory log buffer."""
    stamped = f"{datetime.utcnow().strftime('%H:%M:%S')} {msg}"
    print(stamped, flush=True)
    _log_buffer.append(stamped)
    if len(_log_buffer) > _LOG_BUFFER_MAX:
        del _log_buffer[: len(_log_buffer) - _LOG_BUFFER_MAX]


class IngestRequest(BaseModel):
    startup_ids: Optional[List[str]] = None


@router.get("/health")
def health_check():
    """System health check."""
    try:
        db = get_db()
        db.execute("SELECT 1").fetchone()
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "db": db_status,
        "counts": {
            "startups": count_records("startups"),
            "sources": count_records("sources"),
            "content_items": count_records("content_items"),
            "summaries": count_records("summaries"),
        }
    }


@router.get("/stats")
def system_stats():
    """Detailed system statistics."""
    db = get_db()

    recent_logs = db.execute("""
        SELECT il.*, s.name as source_name
        FROM ingestion_logs il
        LEFT JOIN sources s ON il.source_id = s.id
        ORDER BY il.started_at DESC
        LIMIT 20
    """).fetchall()

    timeline = db.execute("""
        SELECT DATE(published_at) as date, COUNT(*) as count
        FROM content_items
        WHERE published_at >= DATE('now', '-30 days')
        GROUP BY DATE(published_at)
        ORDER BY date
    """).fetchall()

    top_startups = db.execute("""
        SELECT s.name, COUNT(ci.id) as content_count
        FROM startups s
        LEFT JOIN content_items ci ON ci.startup_id = s.id
        GROUP BY s.id
        ORDER BY content_count DESC
        LIMIT 10
    """).fetchall()

    return {
        "recent_ingestion": [dict(l) for l in recent_logs],
        "content_timeline": [dict(t) for t in timeline],
        "top_startups": [dict(s) for s in top_startups]
    }


async def _run_ingestion_job(startup_ids: Optional[List[str]]):
    """Background coroutine — drives the ingestion and updates _ingestion_state."""
    from src.ingestion.company_search import (
        ingest_all_companies,
        ingest_selected_companies,
    )

    _ingestion_state["status"] = "running"
    _ingestion_state["started_at"] = datetime.utcnow().isoformat()
    _ingestion_state["finished_at"] = None
    _ingestion_state["current_company"] = None
    _ingestion_state["completed"] = 0
    _ingestion_state["new_items"] = 0
    _ingestion_state["classified"] = 0
    _ingestion_state["error"] = None
    _ingestion_state["mode"] = "selected" if startup_ids else "all"
    # Reuse progress dict shared with the worker
    progress = _ingestion_state

    try:
        if startup_ids:
            _log(f"[Ingest] Started: {len(startup_ids)} selected companies")
            await ingest_selected_companies(startup_ids, progress=progress)
        else:
            _log(f"[Ingest] Started: rolling batch (oldest-first)")
            await ingest_all_companies(progress=progress)
        _ingestion_state["status"] = "completed"
        _log(f"[Ingest] Completed: {_ingestion_state['completed']}/{_ingestion_state['total']} "
             f"companies, {_ingestion_state['new_items']} new items, "
             f"{_ingestion_state['classified']} classified")
    except asyncio.CancelledError:
        _ingestion_state["status"] = "cancelled"
        _log("[Ingest] Cancelled (machine likely shutting down)")
        raise
    except Exception as e:
        _ingestion_state["status"] = "error"
        _ingestion_state["error"] = str(e)
        _log(f"[Ingest] Error: {e}")
    finally:
        _ingestion_state["finished_at"] = datetime.utcnow().isoformat()


@router.post("/ingest")
async def trigger_ingestion(body: IngestRequest = None):
    """
    Kick off ingestion in the background and return immediately.

    The browser shouldn't wait for a multi-minute request to finish: it
    returns instantly, then polls GET /api/ingest/status.
    """
    if _ingestion_state["status"] == "running":
        return {
            "status": "already_running",
            "message": "An ingestion job is already in progress.",
            "progress": _public_progress(),
        }

    startup_ids = body.startup_ids if (body and body.startup_ids) else None
    asyncio.create_task(_run_ingestion_job(startup_ids))
    return {
        "status": "started",
        "mode": "selected" if startup_ids else "all",
        "batch_size": len(startup_ids) if startup_ids else None,
        "message": "Ingestion started. Poll /api/ingest/status for progress.",
    }


def _public_progress() -> dict:
    """Build the JSON-safe progress payload (skip noisy fields)."""
    skip = {"recent_log"}
    return {k: v for k, v in _ingestion_state.items() if k not in skip}


@router.get("/ingest/status")
def get_ingestion_status():
    """
    Live progress for the in-flight ingestion job + rolling batch summary.

    The dashboard polls this every few seconds while a job is running.
    """
    db = get_db()

    total = db.execute(
        "SELECT COUNT(*) as c FROM startups WHERE tag IS NULL OR tag != 'not_active'"
    ).fetchone()

    # Companies whose last_ingested_at is within the last 24h, for the
    # "cycle so far" indicator on the UI.
    cycle = db.execute("""
        SELECT COUNT(*) as c FROM startups
        WHERE last_ingested_at > datetime('now', '-24 hour')
          AND (tag IS NULL OR tag != 'not_active')
    """).fetchone()

    # Names of companies processed in the last hour (this run / recent run).
    recently_ingested = db.execute("""
        SELECT name, last_ingested_at FROM startups
        WHERE last_ingested_at > datetime('now', '-1 hour')
        ORDER BY last_ingested_at DESC
        LIMIT 50
    """).fetchall()

    return {
        "job": _public_progress(),
        "total_companies": total["c"],
        "cycled_24h": cycle["c"],
        "remaining_24h": max(0, total["c"] - cycle["c"]),
        "recently_ingested": [dict(r) for r in recently_ingested],
    }


@router.get("/ingest/logs")
def get_ingestion_logs():
    """Recent in-memory log lines, for the dashboard log panel."""
    return {"lines": list(_log_buffer)}


@router.post("/ingest/forge-feed")
async def ingest_forge_feed():
    """
    One-off: pull The Forge's incubator RSS feed.

    Kept separate from /api/ingest so it doesn't eat into the 5-minute
    Fly.io trial budget on every batch click.
    """
    try:
        from src.ingestion.rss_ingester import ingest_feed
        master_source = {
            "id": "the-forge-master",
            "name": "The Forge McMaster",
            "type": "blog",
            "rss_feed_url": "https://theforge.mcmaster.ca/feed/",
        }
        stats = await ingest_feed(master_source, fallback_startup_id="the-forge-mcmaster")
        return {"status": "completed", **stats}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/classify")
async def trigger_classification():
    """Manually trigger classification of remaining unclassified items."""
    from src.llm.classifier import classify_unclassified
    result = await classify_unclassified(limit=100)
    return result


@router.post("/reclassify")
async def reclassify_all():
    """Re-classify ALL content items (including already classified ones)."""
    from src.llm.classifier import classify_content_item
    db = get_db()
    items = db.execute(
        "SELECT id FROM content_items ORDER BY published_at DESC LIMIT 500"
    ).fetchall()

    stats = {"reclassified": 0, "errors": 0}
    for item in items:
        try:
            await classify_content_item(item["id"])
            stats["reclassified"] += 1
        except Exception as e:
            print(f"Reclassify error for {item['id']}: {e}")
            stats["errors"] += 1

    return stats


@router.get("/analytics")
def get_analytics():
    """Analytics data for KPIs and charts."""
    db = get_db()

    total_items = db.execute("SELECT COUNT(*) as c FROM content_items").fetchone()["c"]
    total_startups = db.execute(
        "SELECT COUNT(*) as c FROM startups WHERE tag IS NULL OR (tag != 'not_active' AND tag != 'forge')"
    ).fetchone()["c"]

    by_classification = db.execute("""
        SELECT classification, COUNT(*) as count
        FROM content_items
        WHERE classification IS NOT NULL
        GROUP BY classification
        ORDER BY count DESC
    """).fetchall()

    by_source_type = db.execute("""
        SELECT source_type, COUNT(*) as count
        FROM content_items
        GROUP BY source_type
        ORDER BY count DESC
    """).fetchall()

    by_sentiment = db.execute("""
        SELECT sentiment, COUNT(*) as count
        FROM content_items
        WHERE sentiment IS NOT NULL
        GROUP BY sentiment
        ORDER BY count DESC
    """).fetchall()

    content_timeline = db.execute("""
        SELECT DATE(published_at) as date, COUNT(*) as count
        FROM content_items
        WHERE published_at >= DATE('now', '-30 days')
        GROUP BY DATE(published_at)
        ORDER BY date
    """).fetchall()

    top_companies = db.execute("""
        SELECT s.name, COUNT(ci.id) as count
        FROM startups s
        JOIN content_items ci ON ci.startup_id = s.id
        GROUP BY s.id
        ORDER BY count DESC
        LIMIT 10
    """).fetchall()

    category_by_company = {}
    for category in ["funding", "hiring", "product_launch", "milestone", "partnership", "customer_win"]:
        rows = db.execute("""
            SELECT s.name, COUNT(ci.id) as count
            FROM content_items ci
            JOIN startups s ON ci.startup_id = s.id
            WHERE ci.classification = ?
            GROUP BY s.id
            ORDER BY count DESC
            LIMIT 10
        """, (category,)).fetchall()
        category_by_company[category] = [dict(r) for r in rows]

    kpi_hiring = db.execute(
        "SELECT COALESCE(SUM(hired_count), 0) as c FROM content_items WHERE classification = 'hiring'"
    ).fetchone()["c"]
    kpi_funding = db.execute(
        "SELECT COUNT(*) as c FROM content_items WHERE classification = 'funding'"
    ).fetchone()["c"]
    kpi_partnerships = db.execute(
        "SELECT COUNT(*) as c FROM content_items WHERE classification = 'partnership'"
    ).fetchone()["c"]
    kpi_products = db.execute(
        "SELECT COUNT(*) as c FROM content_items WHERE classification = 'product_launch'"
    ).fetchone()["c"]

    return {
        "total_items": total_items,
        "total_startups": total_startups,
        "kpis": {
            "hiring": kpi_hiring,
            "funding": kpi_funding,
            "partnerships": kpi_partnerships,
            "products": kpi_products,
        },
        "by_classification": {r["classification"]: r["count"] for r in by_classification},
        "by_source_type": {r["source_type"]: r["count"] for r in by_source_type},
        "by_sentiment": {r["sentiment"]: r["count"] for r in by_sentiment},
        "content_timeline": [dict(r) for r in content_timeline],
        "top_companies": [dict(r) for r in top_companies],
        "category_by_company": category_by_company,
    }
