"""
report_counterparties.py — who the DFIs actually bank, and who they share.

Run after derive_counterparties.py:
    python report_counterparties.py

Writes data/counterparty_report.xlsx and prints the headlines.

The business-development question this answers is not "who is active in
Kenya" — the loaders already answer that — but "who has raised money from a
DFI before, from which ones, and who keeps going back to the same client".

Matching is EXACT on `counterparty_key`, the normalised name. There is no
fuzzy matching here on purpose: an invented relationship is far more damaging
than a missed one, and the whole point of a cross-institution match is that
two independent sources agreed. Where a spelling differs after normalisation
the link is simply missed, and the counts below are therefore a FLOOR.

Two caveats travel with every number:
  * AfDB and EIB Global contribute nothing — their name fields are project
    names, so no counterparty is derived for them at all.
  * A derived counterparty came from a project-name field, not a client field.
    `counterparty_provenance` distinguishes the two, and the sheets carry it.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection

OUT = Path(__file__).parent / "data" / "counterparty_report.xlsx"

CROSS_DFI = """
SELECT counterparty_key                                   AS client_key,
       MIN(counterparty)                                  AS client,
       COUNT(DISTINCT institution)                        AS dfis,
       GROUP_CONCAT(DISTINCT institution)                 AS which_dfis,
       COUNT(*)                                           AS deals,
       ROUND(SUM(COALESCE(amount_usd, 0)) / 1e6, 1)       AS total_usd_m,
       MIN(COALESCE(approval_date, ''))                   AS first_seen,
       MAX(COALESCE(approval_date, ''))                   AS last_seen,
       GROUP_CONCAT(DISTINCT canonical_country)           AS countries,
       GROUP_CONCAT(DISTINCT canonical_sector)            AS sectors,
       GROUP_CONCAT(DISTINCT counterparty_provenance)     AS provenance
FROM projects
WHERE counterparty_key IS NOT NULL AND counterparty_key <> ''
GROUP BY counterparty_key
HAVING COUNT(DISTINCT institution) >= 2
ORDER BY dfis DESC, total_usd_m DESC
"""

REPEAT = """
SELECT institution,
       MIN(counterparty)                             AS client,
       COUNT(*)                                      AS deals,
       ROUND(SUM(COALESCE(amount_usd, 0)) / 1e6, 1)  AS total_usd_m,
       MIN(COALESCE(approval_date, ''))              AS first_seen,
       MAX(COALESCE(approval_date, ''))              AS last_seen,
       MIN(counterparty_provenance)                  AS provenance
FROM projects
WHERE counterparty_key IS NOT NULL AND counterparty_key <> ''
GROUP BY institution, counterparty_key
HAVING COUNT(*) >= 3
ORDER BY deals DESC, total_usd_m DESC
"""

BY_SIZE = """
SELECT MIN(counterparty)                             AS client,
       COUNT(DISTINCT institution)                   AS dfis,
       COUNT(*)                                      AS deals,
       ROUND(SUM(COALESCE(amount_usd, 0)) / 1e6, 1)  AS total_usd_m,
       GROUP_CONCAT(DISTINCT canonical_country)      AS countries
FROM projects
WHERE counterparty_key IS NOT NULL AND counterparty_key <> ''
GROUP BY counterparty_key
ORDER BY SUM(COALESCE(amount_usd, 0)) DESC
LIMIT 250
"""

COVERAGE = """
SELECT institution,
       COUNT(*)                                                          AS projects,
       SUM(counterparty_provenance = 'disclosed')                        AS disclosed,
       SUM(counterparty_provenance = 'derived_from_project_name')        AS derived,
       SUM(counterparty_key IS NULL)                                     AS none
FROM projects GROUP BY institution ORDER BY projects DESC
"""


def main():
    conn = get_connection()
    cross = pd.read_sql_query(CROSS_DFI, conn)
    repeat = pd.read_sql_query(REPEAT, conn)
    by_size = pd.read_sql_query(BY_SIZE, conn)
    coverage = pd.read_sql_query(COVERAGE, conn)
    conn.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUT, engine="openpyxl") as writer:
        cross.to_excel(writer, sheet_name="cross_dfi_clients", index=False)
        repeat.to_excel(writer, sheet_name="repeat_clients", index=False)
        by_size.to_excel(writer, sheet_name="largest_clients", index=False)
        coverage.to_excel(writer, sheet_name="coverage", index=False)

    print(f"Clients appearing at 2+ institutions: {len(cross):,}")
    if not cross.empty:
        print(f"  ...at 3 or more:                    "
              f"{int((cross['dfis'] >= 3).sum()):,}")
        print("\n  Most widely banked clients")
        print("  " + "-" * 74)
        for _, r in cross.head(12).iterrows():
            print(f"  {r['client'][:34]:<34} {int(r['dfis'])} DFIs  "
                  f"{int(r['deals']):>3} deals  ${r['total_usd_m']:>9,.0f}m  "
                  f"{r['which_dfis'][:26]}")

    print(f"\nClients with 3+ deals from ONE institution: {len(repeat):,}")
    if not repeat.empty:
        print("  " + "-" * 74)
        for _, r in repeat.head(10).iterrows():
            print(f"  {r['institution']:<11} {r['client'][:36]:<36} "
                  f"{int(r['deals']):>3} deals  ${r['total_usd_m']:>9,.0f}m")

    print(f"\nWrote {OUT}")
    print("  sheets: cross_dfi_clients, repeat_clients, largest_clients, coverage")


if __name__ == "__main__":
    main()
