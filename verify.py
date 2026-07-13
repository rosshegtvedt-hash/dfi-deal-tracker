"""
verify.py — quick sanity checks after a load.

Prints row counts and committed USD by institution, country, and sector,
plus any logged data-quality issues. Run:
    python verify.py
"""

from database import get_connection


def show(conn, title, sql, limit=None):
    print(f"\n=== {title} ===")
    rows = conn.execute(sql).fetchall()
    shown = rows[:limit] if limit else rows
    for r in shown:
        label = str(r[0]) if r[0] is not None else "(blank)"
        # amounts printed in USD millions for readability
        amount_m = (r[2] or 0) / 1_000_000
        print(f"  {label:<55} {r[1]:>5} projects   ${amount_m:>10,.1f}M")
    if limit and len(rows) > limit:
        print(f"  ... and {len(rows) - limit} more")


def main():
    conn = get_connection()

    total = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    print(f"Total projects in database: {total}")

    show(conn, "By institution",
         "SELECT institution, COUNT(*), SUM(amount_usd) FROM projects "
         "GROUP BY institution ORDER BY 3 DESC")

    show(conn, "Top 20 countries by committed USD (harmonized)",
         "SELECT canonical_country, COUNT(*), SUM(amount_usd) FROM projects "
         "GROUP BY canonical_country ORDER BY 3 DESC", limit=20)

    show(conn, "By region (harmonized)",
         "SELECT canonical_region, COUNT(*), SUM(amount_usd) FROM projects "
         "GROUP BY canonical_region ORDER BY 3 DESC")

    show(conn, "By canonical sector (harmonized)",
         "SELECT canonical_sector, COUNT(*), SUM(amount_usd) FROM projects "
         "GROUP BY canonical_sector ORDER BY 3 DESC")

    dup_groups, dup_projects = conn.execute(
        "SELECT COUNT(DISTINCT probable_duplicate_group), COUNT(*) FROM projects "
        "WHERE probable_duplicate_group IS NOT NULL"
    ).fetchone()
    print(f"\n=== Probable co-financed duplicates ===")
    print(f"  {dup_projects} projects flagged across {dup_groups} groups "
          f"(see: python dedupe.py)")

    issues = conn.execute(
        "SELECT institution, issue_type, COUNT(*) FROM quality_issues "
        "GROUP BY institution, issue_type ORDER BY institution"
    ).fetchall()
    print("\n=== Data-quality issues ===")
    if issues:
        for institution, issue_type, n in issues:
            print(f"  {institution} / {issue_type}: {n}")
    else:
        print("  none logged")

    conn.close()


if __name__ == "__main__":
    main()
