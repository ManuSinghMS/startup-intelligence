"""
Health check, ingestion triggers, analytics, and system status routes.
"""
from typing import Optional, List

from fastapi import APIRouter
from pydantic import BaseModel
from src.db.database import get_db, count_records

router = APIRouter(prefix="/api", tags=["system"])


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


@router.post("/ingest")
async def trigger_ingestion(body: IngestRequest = None):
    """Manually trigger ingestion — all companies or selected ones."""
    if body and body.startup_ids and len(body.startup_ids) > 0:
        from src.ingestion.company_search import ingest_selected_companies
        results = await ingest_selected_companies(body.startup_ids)
    else:
        from src.ingestion.company_search import ingest_all_companies
        results = await ingest_all_companies()

    total_new = sum(r.get("new", 0) for r in results)

    # Auto-classify new items
    try:
        from src.llm.classifier import classify_unclassified
        classify_stats = await classify_unclassified(limit=200)
        print(f"[Ingest] Auto-classified {classify_stats.get('classified', 0)} items")
    except Exception as e:
        print(f"[Ingest] Auto-classify error (non-critical): {e}")
        classify_stats = {}

    return {
        "status": "completed",
        "total_new": total_new,
        "total_matched": total_new,
        "classified": classify_stats.get("classified", 0),
        "sources": results
    }


@router.get("/ingest/status")
def get_ingestion_status():
    """Get ingestion progress and history."""
    db = get_db()
    
    # Total active companies
    total = db.execute("SELECT COUNT(*) as c FROM startups WHERE tag IS NULL OR tag != 'not_active'").fetchone()
    
    # Companies ingested in the last hour (this batch cycle)
    recently_ingested = db.execute("""
        SELECT name, last_ingested_at FROM startups 
        WHERE last_ingested_at > datetime('now', '-1 hour')
        ORDER BY last_ingested_at DESC
    """).fetchall()
    
    recent_list = [dict(row) for row in recently_ingested]
    recent_count = len(recent_list)
    
    return {
        "total_companies": total["c"],
        "recently_ingested": recent_count,
        "remaining": max(0, total["c"] - recent_count),
        "companies_this_batch": recent_list
    }


@router.post("/classify")
async def trigger_classification():
    """Manually trigger classification of unclassified items."""
    from src.llm.classifier import classify_unclassified
    result = await classify_unclassified()
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

    # Category breakdown per company
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
