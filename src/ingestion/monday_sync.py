"""
Monday.com API integration — sync startups from a Monday.com board.

Monday.com uses a GraphQL API (v2). This module:
1. Fetches all items from a specified board
2. Maps Monday.com columns to the startups schema
3. Upserts: updates existing startups or creates new ones
4. Preserves the existing CSV/Excel import path

Setup:
  1. Get an API token from monday.com → Profile → Admin → API
  2. Set MONDAY_API_TOKEN in .env
  3. Set MONDAY_BOARD_ID in .env (find it in the board URL)
  4. Optionally set MONDAY_COLUMN_MAP in .env (JSON) to customize column mapping

Usage:
  # CLI
  python -m src.ingestion.monday_sync
  python -m src.ingestion.monday_sync --dry-run
  python -m src.ingestion.monday_sync --preview-columns

  # API
  POST /api/startups/sync-monday
"""
from __future__ import annotations

import os
import sys
import json
import uuid
import logging
from datetime import datetime
from typing import Optional

import httpx

from src.db.database import get_db

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("monday_sync")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [Monday] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MONDAY_API_URL = "https://api.monday.com/v2"

# Default column mapping: Monday.com column title → startups DB field.
# Users can override via MONDAY_COLUMN_MAP env var (JSON).
DEFAULT_COLUMN_MAP = {
    "Name": "name",
    "Legal Name": "legal_name",
    "Email": "contact_email",
    "Contact": "contact_name",
    "Founder": "founder_name",
    "Co-Founder": "cofounder_name",
    "Founder LinkedIn": "founder_linkedin_url",
    "Co-Founder LinkedIn": "cofounder_linkedin_url",
    "Website": "website",
    "LinkedIn": "linkedin_url",
    "Twitter": "twitter_handle",
    "Instagram": "instagram_handle",
    "Industry": "industry",
    "Secondary Industry": "secondary_industry",
    "Stage": "stage",
    "Status": "status",
    "Program Stream": "program_stream",
    "Description": "description",
    "Founder Posts": "founder_posts",
    "Company Posts": "company_posts",
    "Co-Founder Posts": "cofounder_posts",
}


def _get_config() -> dict:
    return {
        "api_token": os.getenv("MONDAY_API_TOKEN", ""),
        "board_id": os.getenv("MONDAY_BOARD_ID", ""),
    }


def is_configured() -> bool:
    """Check if Monday.com credentials are set."""
    cfg = _get_config()
    return bool(cfg["api_token"] and cfg["board_id"])


def _get_column_map() -> dict:
    """Get the column mapping (default or custom from env)."""
    custom = os.getenv("MONDAY_COLUMN_MAP", "")
    if custom:
        try:
            return json.loads(custom)
        except json.JSONDecodeError:
            logger.warning("Invalid MONDAY_COLUMN_MAP JSON, using defaults")
    return DEFAULT_COLUMN_MAP.copy()


# ---------------------------------------------------------------------------
# GraphQL queries
# ---------------------------------------------------------------------------

async def _graphql(query: str, variables: dict | None = None) -> dict:
    """Execute a Monday.com GraphQL query."""
    cfg = _get_config()
    headers = {
        "Authorization": cfg["api_token"],
        "Content-Type": "application/json",
        "API-Version": "2024-10",
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            MONDAY_API_URL,
            json=payload,
            headers=headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()

        if "errors" in data:
            errors = data["errors"]
            logger.error("GraphQL errors: %s", errors)
            raise RuntimeError(f"Monday.com API error: {errors[0].get('message', errors)}")

        return data.get("data", {})


async def fetch_board_columns(board_id: str) -> list[dict]:
    """Fetch column definitions from a board (for preview/mapping)."""
    query = """
    query ($boardId: [ID!]!) {
        boards(ids: $boardId) {
            name
            columns {
                id
                title
                type
            }
        }
    }
    """
    data = await _graphql(query, {"boardId": [board_id]})
    boards = data.get("boards", [])
    if not boards:
        raise RuntimeError(f"Board {board_id} not found")
    return boards[0].get("columns", [])


async def fetch_board_items(board_id: str) -> list[dict]:
    """
    Fetch all items from a Monday.com board.
    Handles pagination via cursor.
    """
    all_items = []
    cursor = None

    while True:
        if cursor:
            query = """
            query ($cursor: String!) {
                next_items_page(cursor: $cursor, limit: 100) {
                    cursor
                    items {
                        id
                        name
                        column_values {
                            id
                            title
                            text
                            value
                        }
                    }
                }
            }
            """
            data = await _graphql(query, {"cursor": cursor})
            page = data.get("next_items_page", {})
        else:
            query = """
            query ($boardId: [ID!]!) {
                boards(ids: $boardId) {
                    items_page(limit: 100) {
                        cursor
                        items {
                            id
                            name
                            column_values {
                                id
                                title
                                text
                                value
                            }
                        }
                    }
                }
            }
            """
            data = await _graphql(query, {"boardId": [board_id]})
            boards = data.get("boards", [])
            if not boards:
                break
            page = boards[0].get("items_page", {})

        items = page.get("items", [])
        all_items.extend(items)

        cursor = page.get("cursor")
        if not cursor or not items:
            break

    return all_items


# ---------------------------------------------------------------------------
# Mapping and upsert
# ---------------------------------------------------------------------------

def _map_item_to_startup(item: dict, column_map: dict) -> dict:
    """
    Map a Monday.com board item to the startups schema.
    The item 'name' field is always mapped to 'name'.
    Column values are matched by their title.
    """
    startup_data = {"name": item.get("name", "").strip()}

    for col_val in item.get("column_values", []):
        col_title = col_val.get("title", "")
        text = (col_val.get("text") or "").strip()

        if col_title in column_map and text:
            db_field = column_map[col_title]
            startup_data[db_field] = text

    # Ensure name exists
    if not startup_data.get("name"):
        return {}

    return startup_data


def _upsert_startup(startup_data: dict, dry_run: bool = False) -> tuple[str, str]:
    """
    Insert or update a startup. Matches by name (case-insensitive).
    Returns (action: 'created'|'updated'|'skipped', startup_id).
    """
    if not startup_data.get("name"):
        return "skipped", ""

    db = get_db()
    name = startup_data["name"]

    existing = db.execute(
        "SELECT id FROM startups WHERE LOWER(name) = LOWER(?)",
        (name,)
    ).fetchone()

    if dry_run:
        return "would_update" if existing else "would_create"

    now = datetime.utcnow().isoformat()

    if existing:
        # Update existing startup with non-empty fields
        updates = {k: v for k, v in startup_data.items()
                   if k not in ("name", "founder_posts", "company_posts", "cofounder_posts") and v}
        if not updates:
            return "skipped", existing["id"]

        updates["updated_at"] = now
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [existing["id"]]
        db.execute(f"UPDATE startups SET {set_clause} WHERE id = ?", values)
        return "updated", existing["id"]
    else:
        # Create new startup
        startup_id = str(uuid.uuid4())
        fields = ["id", "name", "created_at", "updated_at"]
        values = [startup_id, name, now, now]

        for field in ["legal_name", "contact_email", "contact_name",
                      "founder_name", "cofounder_name",
                      "founder_linkedin_url", "cofounder_linkedin_url",
                      "website", "linkedin_url", "twitter_handle",
                      "instagram_handle", "industry", "secondary_industry",
                      "stage", "status", "program_stream", "description"]:
            if startup_data.get(field):
                fields.append(field)
                values.append(startup_data[field])

        placeholders = ", ".join("?" for _ in fields)
        field_names = ", ".join(fields)
        db.execute(
            f"INSERT INTO startups ({field_names}) VALUES ({placeholders})",
            values,
        )
        return "created", startup_id


# ---------------------------------------------------------------------------
# Main sync function
# ---------------------------------------------------------------------------

async def sync_from_monday(dry_run: bool = False) -> dict:
    """
    Sync startups from Monday.com board.
    Returns stats dict with created/updated/skipped counts.
    """
    if not is_configured():
        return {
            "status": "not_configured",
            "message": "Set MONDAY_API_TOKEN and MONDAY_BOARD_ID in .env"
        }

    cfg = _get_config()
    column_map = _get_column_map()

    logger.info("=" * 50)
    logger.info("Monday.com Sync — %s", "DRY RUN" if dry_run else "LIVE")
    logger.info("Board ID: %s", cfg["board_id"])
    logger.info("=" * 50)

    stats = {"created": 0, "updated": 0, "skipped": 0, "errors": 0, "total": 0}

    try:
        items = await fetch_board_items(cfg["board_id"])
        stats["total"] = len(items)
        logger.info("Found %d items on board", len(items))

        for item in items:
            try:
                startup_data = _map_item_to_startup(item, column_map)
                if not startup_data:
                    stats["skipped"] += 1
                    continue
                    
                db_startup_data = {k: v for k, v in startup_data.items() if k not in ["founder_posts", "company_posts", "cofounder_posts"]}

                result, startup_id = _upsert_startup(db_startup_data, dry_run=dry_run)

                if result in ("created", "would_create"):
                    stats["created"] += 1
                    logger.info("  %s: %s", result.upper(), db_startup_data["name"])
                elif result in ("updated", "would_update"):
                    stats["updated"] += 1
                    logger.info("  %s: %s", result.upper(), db_startup_data["name"])
                else:
                    stats["skipped"] += 1
                    
                # Deal with posts
                if startup_id and not dry_run:
                    from src.ingestion.linkedin_ingester import import_manual_posts
                    posts_to_import = []
                    for k in ["founder_posts", "company_posts", "cofounder_posts"]:
                        if startup_data.get(k):
                            urls = [u.strip() for u in str(startup_data[k]).replace(",", "\n").split("\n") if u.strip()]
                            role = k.split("_")[0]
                            for u in urls:
                                posts_to_import.append({"url": u, "author_role": role})
                                
                    if posts_to_import:
                        import_manual_posts(startup_id, posts_to_import, startup_data["name"])

            except Exception as e:
                stats["errors"] += 1
                logger.error("  Error processing item %s: %s",
                             item.get("name", "?"), e)

        if not dry_run:
            db = get_db()
            db.commit()

        logger.info("-" * 50)
        logger.info("DONE — created=%d, updated=%d, skipped=%d, errors=%d",
                     stats["created"], stats["updated"],
                     stats["skipped"], stats["errors"])

        stats["status"] = "completed"
        stats["dry_run"] = dry_run
        return stats

    except Exception as e:
        logger.error("Monday.com sync error: %s", e)
        return {"status": "error", "message": str(e), **stats}


async def preview_columns() -> dict:
    """Preview the columns on the Monday.com board for mapping."""
    if not is_configured():
        return {"status": "not_configured"}

    cfg = _get_config()
    columns = await fetch_board_columns(cfg["board_id"])
    column_map = _get_column_map()

    return {
        "board_id": cfg["board_id"],
        "columns": [
            {
                "id": c["id"],
                "title": c["title"],
                "type": c["type"],
                "mapped_to": column_map.get(c["title"], "(unmapped)"),
            }
            for c in columns
        ],
        "current_mapping": column_map,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Monday.com Board Sync")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would happen without writing")
    parser.add_argument("--preview-columns", action="store_true",
                        help="Show board columns and current mapping")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

    from src.db.database import init_db
    from src.db.migrate import migrate

    try:
        migrate()
    except Exception:
        pass
    init_db()

    if args.preview_columns:
        result = asyncio.run(preview_columns())
        print(json.dumps(result, indent=2))
    else:
        result = asyncio.run(sync_from_monday(dry_run=args.dry_run))
        print(json.dumps(result, indent=2))
