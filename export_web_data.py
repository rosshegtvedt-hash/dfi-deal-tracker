"""
export_web_data.py — writes the compact JSON snapshot the Next.js dashboard
reads (web/public/data.json).

Run after the pipeline, before deploying:
    python export_web_data.py

Format: {"as_of": "...", "columns": [...], "rows": [[...], ...]} — a
list-of-lists rather than list-of-objects to keep the file small (field
names aren't repeated 20,000 times). Amounts are rounded to whole dollars;
description and other long fields are deliberately excluded to keep the
public payload lean.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection

OUT_PATH = Path(__file__).parent / "web" / "public" / "data.json"

COLUMNS = ["institution", "name", "country", "region", "sector", "instrument",
           "amount_usd", "year", "status", "sponsor", "url", "dup"]


def main():
    conn = get_connection()
    rows = conn.execute(
        """SELECT institution, project_name, canonical_country, canonical_region,
                  canonical_sector, instrument,
                  CAST(ROUND(amount_usd) AS INTEGER),
                  COALESCE(CAST(strftime('%Y', approval_date) AS INTEGER), fiscal_year),
                  status, sponsor, source_url, probable_duplicate_group
           FROM projects"""
    ).fetchall()
    as_of = conn.execute("SELECT MAX(scraped_at) FROM projects").fetchone()[0]
    conn.close()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"as_of": (as_of or "")[:10], "columns": COLUMNS,
               "rows": [list(r) for r in rows]}
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False,
                                   separators=(",", ":")), encoding="utf-8")
    size_mb = OUT_PATH.stat().st_size / 1e6
    print(f"Wrote {len(rows):,} rows to {OUT_PATH} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
