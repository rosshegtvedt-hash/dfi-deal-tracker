"""
harmonize.py — applies the mapping CSVs that translate each institution's own
labels into canonical taxonomies:
  * sector_mapping.csv  : institution + sector label -> canonical_sector
                          (+ optional canonical_subsector)
  * country_mapping.csv : country label -> canonical_country + canonical_region
                          (institution-agnostic — 'Turkiye', 'Türkiye' and
                          'Turkey' all become 'Türkiye')

Run after any loader:
    python harmonize.py

How it works, in plain language:
  * The CSVs are the single source of truth — edit them in Excel or a text
    editor, then rerun this script. No code changes needed.
  * Any label found in the database but NOT in its CSV is reported here and
    logged to quality_issues ('unmapped_sector' / 'unmapped_country', one
    issue per distinct label, not per project), so new labels from future
    data releases can't slip through unnoticed.
  * Projects whose source field is blank get 'Unclassified' so they remain
    visible in charts rather than vanishing.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection, log_quality_issue

MAPPING_CSV = Path(__file__).parent / "sector_mapping.csv"
COUNTRY_CSV = Path(__file__).parent / "country_mapping.csv"


def read_mapping() -> dict:
    """Load the CSV into {(institution, source_sector): (sector, subsector)}."""
    mapping = {}
    with open(MAPPING_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row["institution"].strip(), row["source_sector"].strip())
            subsector = row["canonical_subsector"].strip() or None
            mapping[key] = (row["canonical_sector"].strip(), subsector)
    return mapping


def read_country_mapping() -> dict:
    """Load country_mapping.csv into {source_country: (country, region)}."""
    mapping = {}
    with open(COUNTRY_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            mapping[row["source_country"].strip()] = (
                row["canonical_country"].strip(), row["canonical_region"].strip())
    return mapping


def harmonize_countries(conn):
    """Apply country_mapping.csv; returns (mapped_count, unmapped_labels)."""
    conn.execute("UPDATE projects SET canonical_country = NULL, canonical_region = NULL")
    conn.execute("DELETE FROM quality_issues WHERE issue_type = 'unmapped_country'")

    mapped = 0
    for source, (country, region) in read_country_mapping().items():
        cur = conn.execute(
            "UPDATE projects SET canonical_country = ?, canonical_region = ? "
            "WHERE country = ?",
            (country, region, source),
        )
        mapped += cur.rowcount

    conn.execute(
        "UPDATE projects SET canonical_country = 'Unclassified', "
        "canonical_region = 'Unclassified' WHERE country IS NULL"
    )

    unmapped = conn.execute(
        "SELECT institution, country, COUNT(*) FROM projects "
        "WHERE canonical_country IS NULL GROUP BY institution, country"
    ).fetchall()
    for institution, country, n in unmapped:
        log_quality_issue(
            conn, institution, None, "unmapped_country",
            f"Country label {country!r} ({n} projects) has no row in country_mapping.csv",
        )
    return mapped, unmapped


def main():
    mapping = read_mapping()
    conn = get_connection()

    # Start from a clean slate so removed CSV rows don't leave stale values,
    # and clear previous unmapped_sector issues (this run re-detects them).
    conn.execute("UPDATE projects SET canonical_sector = NULL, canonical_subsector = NULL")
    conn.execute("DELETE FROM quality_issues WHERE issue_type = 'unmapped_sector'")

    mapped = 0
    for (institution, source_sector), (sector, subsector) in mapping.items():
        cur = conn.execute(
            "UPDATE projects SET canonical_sector = ?, canonical_subsector = ? "
            "WHERE institution = ? AND sector = ?",
            (sector, subsector, institution, source_sector),
        )
        mapped += cur.rowcount

    # Blank source sector -> 'Unclassified' (kept visible, not hidden).
    cur = conn.execute(
        "UPDATE projects SET canonical_sector = 'Unclassified' WHERE sector IS NULL"
    )
    unclassified = cur.rowcount

    # Anything still NULL has a sector label missing from the CSV.
    unmapped = conn.execute(
        "SELECT institution, sector, COUNT(*) FROM projects "
        "WHERE canonical_sector IS NULL GROUP BY institution, sector"
    ).fetchall()
    for institution, sector, n in unmapped:
        log_quality_issue(
            conn, institution, None, "unmapped_sector",
            f"Sector label {sector!r} ({n} projects) has no row in sector_mapping.csv",
        )

    countries_mapped, countries_unmapped = harmonize_countries(conn)

    conn.commit()
    conn.close()

    print(f"Sectors:   harmonized {mapped} projects; "
          f"{unclassified} had no source sector (-> 'Unclassified').")
    if unmapped:
        print("UNMAPPED sector labels — add these to sector_mapping.csv:")
        for institution, sector, n in unmapped:
            print(f"  {institution}: {sector!r} ({n} projects)")
    else:
        print("           all sector labels mapped.")

    print(f"Countries: harmonized {countries_mapped} projects.")
    if countries_unmapped:
        print("UNMAPPED country labels — add these to country_mapping.csv:")
        for institution, country, n in countries_unmapped:
            print(f"  {institution}: {country!r} ({n} projects)")
    else:
        print("           all country labels mapped.")


if __name__ == "__main__":
    main()
