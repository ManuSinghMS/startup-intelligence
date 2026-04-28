"""
Content item routes — list, filter, and manage collected content.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from src.db.database import get_db
from src.llm.classifier import classify_content_item

router = APIRouter(prefix="/api/content", tags=["content"])


class ManualContentCreate(BaseModel):
    """For manually adding content (newsletter paste, social post, etc.)."""
    startup_id: Optional[str] = None
    source_type: str = "press"
    source_name: str = "Manual"
    url: Optional[str] = ""
    title: str
    content: str
    published_at: Optional[str] = None


@router.get("")
def list_content(
    startup_id: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    classification: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    is_relevant: Optional[bool] = Query(True),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0)
):
    """List content items with filters."""
    db = get_db()
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
    if keyword:
        conditions.append("(ci.title LIKE ? OR ci.raw_content LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if is_relevant is not None:
        conditions.append("ci.is_relevant = ?")
        params.append(1 if is_relevant else 0)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count = db.execute(
        f"SELECT COUNT(*) as c FROM content_items ci {where}", params
    ).fetchone()["c"]

    items = db.execute(f"""
        SELECT ci.id, ci.startup_id, ci.source_type, ci.source_name, ci.url,
               ci.canonical_url, ci.external_source, ci.title, ci.author_name,
               ci.published_at, ci.post_date, ci.discovered_at,
               ci.summary, ci.classification, ci.sentiment, ci.impact_score,
               ci.topics, ci.is_relevant, ci.confidence_score,
               ci.ingestion_status, ci.metadata_json, ci.created_at,
               s.name as startup_name
        FROM content_items ci
        LEFT JOIN startups s ON ci.startup_id = s.id
        {where}
        ORDER BY ci.published_at DESC
        LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()

    return {
        "total": count,
        "items": [dict(item) for item in items]
    }


@router.get("/stats/overview")
def content_stats():
    """Get overview statistics across all content."""
    db = get_db()

    total = db.execute("SELECT COUNT(*) as c FROM content_items").fetchone()["c"]
    by_type = db.execute("""
        SELECT source_type, COUNT(*) as count
        FROM content_items GROUP BY source_type
    """).fetchall()
    by_class = db.execute("""
        SELECT classification, COUNT(*) as count
        FROM content_items GROUP BY classification
    """).fetchall()
    by_sentiment = db.execute("""
        SELECT sentiment, COUNT(*) as count
        FROM content_items WHERE sentiment IS NOT NULL GROUP BY sentiment
    """).fetchall()

    return {
        "total": total,
        "by_source_type": {r["source_type"]: r["count"] for r in by_type},
        "by_classification": {r["classification"]: r["count"] for r in by_class},
        "by_sentiment": {r["sentiment"]: r["count"] for r in by_sentiment}
    }


@router.get("/{content_id}")
def get_content_item(content_id: str):
    """Get a single content item with full text."""
    db = get_db()
    item = db.execute("""
        SELECT ci.*, s.name as startup_name
        FROM content_items ci
        LEFT JOIN startups s ON ci.startup_id = s.id
        WHERE ci.id = ?
    """, (content_id,)).fetchone()

    if not item:
        raise HTTPException(status_code=404, detail="Content item not found")

    return dict(item)


@router.post("", status_code=201)
def create_content(data: ManualContentCreate):
    """Manually add a content item."""
    from src.ingestion.company_search import hash_content
    db = get_db()

    content_hash = hash_content(data.url or data.title, data.title)
    existing = db.execute(
        "SELECT id FROM content_items WHERE content_hash = ?", (content_hash,)
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Duplicate content")

    item_id = str(uuid.uuid4())
    published = data.published_at or datetime.utcnow().isoformat()

    db.execute(
        """INSERT INTO content_items
        (id, startup_id, source_type, source_name, url, title,
         published_at, raw_content, content_hash, classification)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (item_id, data.startup_id, data.source_type, data.source_name,
         data.url, data.title, published, data.content, content_hash, "unclassified")
    )
    db.commit()

    return {"id": item_id}


@router.post("/{content_id}/classify")
async def classify_item(content_id: str):
    """Classify a specific content item using LLM."""
    result = await classify_content_item(content_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{content_id}/irrelevant")
def mark_irrelevant(content_id: str):
    """Mark a content item as irrelevant."""
    db = get_db()
    existing = db.execute(
        "SELECT id FROM content_items WHERE id = ?", (content_id,)
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Content item not found")

    db.execute(
        "UPDATE content_items SET is_relevant = 0 WHERE id = ?", (content_id,)
    )
    db.commit()
    return {"id": content_id, "is_relevant": False}


@router.delete("/all")
def delete_all_content():
    """Permanently delete ALL content items."""
    db = get_db()
    db.execute("DELETE FROM content_items")
    db.commit()
    return {"deleted": "all"}


@router.delete("/{content_id}")
def delete_content_item(content_id: str):
    """Permanently delete a content item."""
    db = get_db()
    existing = db.execute(
        "SELECT id FROM content_items WHERE id = ?", (content_id,)
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Content item not found")

    db.execute("DELETE FROM content_items WHERE id = ?", (content_id,))
    db.commit()
    return {"deleted": content_id}
