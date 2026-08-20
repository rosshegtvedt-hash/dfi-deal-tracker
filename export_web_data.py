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

`counterparty` replaces the raw `sponsor` field: it carries the disclosed
sponsor verbatim where a source published one, and a name derived from the
project title where none did, so searching it reaches 66% of deals rather
than 30%. `cp_key` is the normalised form, shipped so the page can group
"who has been banked by more than one DFI" without redoing the
normalisation in JavaScript. `cp_derived` is 1 when the name was derived
rather than disclosed, so the page can mark it. `themes` is a pipe-joined
list of thematic bond labels (Green bond|Social bond), NULL for the vast
majority of deals that carry none.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection

OUT_PATH = Path(__file__).parent / "web" / "public" / "data.json"

COLUMNS = ["institution", "name", "country", "region", "sector", "instrument",
           "amount_usd", "year", "status", "counterparty", "cp_key",
           "cp_derived", "themes", "url", "dup"]


def main():
    conn = get_connection()
    rows = conn.execute(
        """SELECT institution, project_name, canonical_country, canonical_region,
                  canonical_sector, instrument,
                  CAST(ROUND(amount_usd) AS INTEGER),
                  COALESCE(CAST(strftime('%Y', approval_date) AS INTEGER), fiscal_year),
                  status, counterparty, counterparty_key,
                  CASE WHEN counterparty_provenance = 'derived_from_project_name'
                       THEN 1 ELSE 0 END,
                  (SELECT GROUP_CONCAT(t.theme, '|') FROM project_themes t
                    WHERE t.project_id = projects.id),
                  source_url, probable_duplicate_group
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
