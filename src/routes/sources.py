"""
Source management routes.
"""
import uuid
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from src.db.database import get_db

router = APIRouter(prefix="/api/sources", tags=["sources"])


class SourceCreate(BaseModel):
    name: str
    url: Optional[str] = None
    rss_feed_url: Optional[str] = None
    type: str = "news"
    priority: int = 3


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    rss_feed_url: Optional[str] = None
    type: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


@router.get("")
def list_sources(
    source_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    min_priority: Optional[int] = Query(None)
):
    """List all sources with optional filters."""
    db = get_db()
    conditions = []
    params = []

    if source_type:
        conditions.append("type = ?")
        params.append(source_type)
    if is_active is not None:
        conditions.append("is_active = ?")
        params.append(1 if is_active else 0)
    if min_priority:
        conditions.append("priority >= ?")
        params.append(min_priority)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sources = db.execute(f"""
        SELECT s.*,
            (SELECT COUNT(*) FROM content_items ci WHERE ci.source_id = s.id) as item_count
        FROM sources s
        {where}
        ORDER BY s.priority DESC, s.name
    """, params).fetchall()

    return {"sources": [dict(s) for s in sources]}


@router.post("", status_code=201)
def create_source(data: SourceCreate):
    """Add a new source."""
    db = get_db()
    source_id = str(uuid.uuid4())

    db.execute(
        """INSERT INTO sources (id, name, url, rss_feed_url, type, priority)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (source_id, data.name, data.url, data.rss_feed_url, data.type, data.priority)
    )
    db.commit()

    return {"id": source_id, "name": data.name}


@router.put("/{source_id}")
def update_source(source_id: str, data: SourceUpdate):
    """Update a source."""
    db = get_db()
    existing = db.execute(
        "SELECT * FROM sources WHERE id = ?", (source_id,)
    ).fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="Source not found")

    updates = {}
    for k, v in data.model_dump().items():
        if v is not None:
            if k == "is_active":
                updates["is_active"] = 1 if v else 0
            else:
                updates[k] = v

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [source_id]

    db.execute(f"UPDATE sources SET {set_clause} WHERE id = ?", values)
    db.commit()

    return {"id": source_id, "updated": list(updates.keys())}


@router.delete("/{source_id}")
def delete_source(source_id: str):
    """Delete a source."""
    db = get_db()
    existing = db.execute(
        "SELECT id FROM sources WHERE id = ?", (source_id,)
    ).fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="Source not found")

    db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    db.commit()

    return {"deleted": source_id}
