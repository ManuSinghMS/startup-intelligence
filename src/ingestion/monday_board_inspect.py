"""
Monday.com Board Structure Inspector

Prints:
- Board name
- Column titles, IDs, and types
- Sample item count
- Current column mapping

Usage:
  python -m src.ingestion.monday_board_inspect
"""
import os
import sys
import json
import asyncio
from typing import List, Dict

import httpx
from dotenv import load_dotenv

# Load env BEFORE any local imports
load_dotenv()

from src.db.database import get_db, init_db
from src.ingestion.monday_sync import (
    fetch_board_columns,
    fetch_board_items,
    _get_config,
    _get_column_map,
    is_configured,
)


async def inspect_board() -> None:
    """Fetch and display board structure."""
    if not is_configured():
        print("Monday.com not configured.")
        print("Set MONDAY_API_TOKEN and MONDAY_BOARD_ID in .env")
        sys.exit(1)

    cfg = _get_config()
    board_id = cfg["board_id"]

    print("\n" + "=" * 70)
    print("MONDAY.COM BOARD STRUCTURE")
    print("=" * 70)
    print(f"\nBoard ID: {board_id}\n")

    try:
        # Fetch columns
        columns = await fetch_board_columns(board_id)

        print(f"Columns ({len(columns)}):\n")
        print(f"{'Title':<30} {'Type':<20} {'ID'}")
        print("-" * 70)
        for col in columns:
            title = col.get("title", "")[:29]
            col_type = col.get("type", "")[:19]
            col_id = col.get("id", "")
            print(f"{title:<30} {col_type:<20} {col_id}")

        # Current mapping
        column_map = _get_column_map()
        print(f"\nColumn Mapping:\n")
        print(f"{'Monday Column':<30} -> {'Database Field'}")
        print("-" * 70)
        for col in columns:
            title = col.get("title", "")
            mapped_to = column_map.get(title, "(unmapped)")
            print(f"{title:<30} -> {mapped_to}")

        # Fetch sample items
        items = await fetch_board_items(board_id)
        print(f"\n\nBoard has {len(items)} total items\n")

        if items and len(items) > 0:
            print(f"Sample Item (first):\n")
            item = items[0]
            print(f"  Name: {item.get('name', '(no name)')}")
            print(f"  Item ID: {item.get('id', '?')}")
            print(f"\n  Column Values:")
            for col_val in item.get("column_values", [])[:5]:
                title = col_val.get("title", "")
                text = col_val.get("text", "")
                print(f"    - {title}: {text}")
            if len(item.get("column_values", [])) > 5:
                print(f"    ... and {len(item.get('column_values', [])) - 5} more")

        print("\n" + "=" * 70)
        print("\nTo customize column mapping, set MONDAY_COLUMN_MAP in .env as JSON:")
        print('MONDAY_COLUMN_MAP={"Monday Title":"db_field","Founder":"founder_name"}')
        print("\n" + "=" * 70 + "\n")

    except Exception as e:
        print(f"\nError: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

    try:
        init_db()
    except Exception:
        pass

    asyncio.run(inspect_board())
