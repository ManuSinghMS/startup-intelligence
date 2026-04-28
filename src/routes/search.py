"""
Full-text search routes using SQLite FTS5.
"""
from fastapi import APIRouter, Query
from typing import Optional

from src.db.database import get_db

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search_content(
    q: str = Query(..., description="Search query"),
    startup_id: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    classification: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0)
):
    """
    Full-text search across all content items.
    Uses SQLite FTS5 for fast, ranked results.
    """
    db = get_db()

    # Build FTS query — escape special characters
    fts_query = q.replace('"', '""')

    # Build filter conditions
    conditions = []
    params = []

    if startup_id:
        conditions.append("ci.startup_id = ?")
        params.append(startup_id)
    if source_type:
        conditions.append("ci.source_type = ?")
        params.append(source_type)
    if classification:
        conditions.append("ci.classification = ?")
        params.append(classification)
    if date_from:
        conditions.append("ci.published_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("ci.published_at <= ?")
        params.append(date_to)

    extra_where = (" AND " + " AND ".join(conditions)) if conditions else ""

    try:
        # Use FTS5 match with rank
        results = db.execute(f"""
            SELECT ci.id, ci.startup_id, ci.source_type, ci.source_name,
                   ci.url, ci.title, ci.published_at, ci.summary,
                   ci.classification, ci.sentiment, ci.created_at,
                   s.name as startup_name,
                   rank
            FROM content_fts fts
            JOIN content_items ci ON ci.rowid = fts.rowid
            LEFT JOIN startups s ON ci.startup_id = s.id
            WHERE content_fts MATCH ?
            {extra_where}
            ORDER BY rank
            LIMIT ? OFFSET ?
        """, [fts_query] + params + [limit, offset]).fetchall()

        # Get total count
        count_result = db.execute(f"""
            SELECT COUNT(*) as c
            FROM content_fts fts
            JOIN content_items ci ON ci.rowid = fts.rowid
            WHERE content_fts MATCH ?
            {extra_where}
        """, [fts_query] + params).fetchone()

        return {
            "query": q,
            "total": count_result["c"],
            "results": [dict(r) for r in results]
        }

    except Exception as e:
        # Fallback to LIKE search if FTS fails
        results = db.execute(f"""
            SELECT ci.id, ci.startup_id, ci.source_type, ci.source_name,
                   ci.url, ci.title, ci.published_at, ci.summary,
                   ci.classification, ci.sentiment, ci.created_at,
                   s.name as startup_name
            FROM content_items ci
            LEFT JOIN startups s ON ci.startup_id = s.id
            WHERE (ci.title LIKE ? OR ci.raw_content LIKE ? OR ci.summary LIKE ?)
            {extra_where}
            ORDER BY ci.published_at DESC
            LIMIT ? OFFSET ?
        """, [f"%{q}%", f"%{q}%", f"%{q}%"] + params + [limit, offset]).fetchall()

        return {
            "query": q,
            "total": len(results),
            "results": [dict(r) for r in results],
            "fallback": True
        }
