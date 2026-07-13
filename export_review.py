"""
export_review.py — dumps the database into one Excel workbook for review.

Run:
    python export_review.py

Creates data/review_export.xlsx with four sheets:
    all_projects     — every record, all columns
    duplicates       — only records flagged with a probable_duplicate_group,
                       sorted so each group's members sit together
    quality_issues   — everything the loaders logged (raw_row JSON omitted
                       for readability; it stays in the database)
    sector_rollup    — canonical sector x institution, with project counts
                       and committed USD millions
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection, DB_PATH

OUT_PATH = DB_PATH.parent / "review_export.xlsx"


def main():
    conn = get_connection()

    projects = pd.read_sql_query(
        "SELECT * FROM projects ORDER BY institution, country, project_name", conn)

    duplicates = pd.read_sql_query(
        """SELECT probable_duplicate_group, institution, project_name,
                  COALESCE(canonical_country, country) AS country,
                  COALESCE(strftime('%Y', approval_date), CAST(fiscal_year AS TEXT)) AS year,
                  amount_usd / 1e6 AS amount_usd_millions, instrument, status, source_url
           FROM projects
           WHERE probable_duplicate_group IS NOT NULL
           ORDER BY probable_duplicate_group, institution""", conn)

    issues = pd.read_sql_query(
        """SELECT institution, issue_type, project_name, detail, logged_at
           FROM quality_issues ORDER BY institution, issue_type, project_name""", conn)

    rollup = pd.read_sql_query(
        """SELECT canonical_sector, institution,
                  COUNT(*) AS projects,
                  ROUND(SUM(amount_usd) / 1e6, 1) AS committed_usd_millions
           FROM projects
           GROUP BY canonical_sector, institution
           ORDER BY SUM(amount_usd) DESC""", conn)

    conn.close()

    with pd.ExcelWriter(OUT_PATH, engine="openpyxl") as writer:
        projects.to_excel(writer, sheet_name="all_projects", index=False)
        duplicates.to_excel(writer, sheet_name="duplicates", index=False)
        issues.to_excel(writer, sheet_name="quality_issues", index=False)
        rollup.to_excel(writer, sheet_name="sector_rollup", index=False)

    print(f"Wrote {OUT_PATH}")
    print(f"  all_projects:   {len(projects):,} rows")
    print(f"  duplicates:     {len(duplicates):,} rows")
    print(f"  quality_issues: {len(issues):,} rows")
    print(f"  sector_rollup:  {len(rollup):,} rows")


if __name__ == "__main__":
    main()
