"""test_ifc_envelopes.py — proves IFC's programme envelopes stay off partner deals.

Run:
    python test_ifc_envelopes.py

IFC's trade-finance programmes (GTFP, GTSF, GSCF) publish every partner bank
as its own record stamped with the WHOLE programme's envelope. Left alone
that is USD 7bn on each of 55 GTFP records. The loader NULLs the envelope on
partner records and lets the programme's own record keep it.

Until 2026-09-24 it recognised the programme's record as "any record booked
to World Region". That let GSCF's two World Region partners (Citi, SMBC)
keep USD 3,115m each where Citi's page says IFC's investment is up to
USD 250m, and six named GTSF participations keep USD 1bn each. The rule now
exempts a World Region record only when it is the ONLY one in its group.

Builds a throwaway in-memory database; never reads or writes the real
tracker. Exits non-zero if any check fails.

Checks:
  1. GTFP shape: one World Region record keeps the envelope, every partner
     booked to a country is NULLed;
  2. GSCF shape: two World Region partners and no programme record — every
     record is NULLed, World Region or not;
  3. GTSF shape: several World Region records — none keeps the envelope;
  4. each NULLed record is logged exactly once, with the envelope amount in
     the detail, and a World Region record says why it was not exempted;
  5. the rule does not over-reach: two records sharing an amount (below the
     three-record threshold), amounts under USD 500m, the same amount on
     different dates, and undated records are all left alone;
  6. load() actually applies it: the stored amount_usd is NULL for partners
     and intact for the programme record.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from database import MIGRATIONS, SCHEMA  # noqa: E402
from scrapers import ifc  # noqa: E402

failures = []

WR = "World Region"


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        if detail:
            print(f"          {detail}")
        failures.append(label)


def build_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for table, column, sql_type in MIGRATIONS:
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
    return conn


class KeepOpen:
    """Forwards everything except close(): load() closes its connection in a
    finally block, which would discard the in-memory database."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


def raw(number, name, country, amount_m, approved):
    """One record as IFC's API publishes it (amounts in USD millions)."""
    return {"project_number": number, "project_name": name, "country": country,
            "total_ifc_investment_as_approved_by_boardmillion__usd": amount_m,
            "ifc_approval_date": approved, "date_disclosed": "01-Jan-2020",
            "project_url": f"https://disclosures.ifc.org/test/{number}",
            "industry": "Financial Markets", "product_line": "Guarantee"}


# (number, name, country, USD millions, approval date)
RAW = [
    # GTFP shape: the programme's own record + partners booked to countries.
    (1, "Global Trade Finance Program (GTFP)", WR, 7000, "11-Nov-2004"),
    (2, "GTFP Bank Egypt", "Egypt, Arab Republic of", 7000, "11-Nov-2004"),
    (3, "GTFP Bank Nepal", "Nepal", 7000, "11-Nov-2004"),
    (4, "GTFP Bank Yemen", "Yemen, Republic of", 7000, "11-Nov-2004"),
    # GSCF shape: two World Region PARTNERS, no programme record.
    (10, "GSCF Citi II", WR, 3115, "15-Dec-2022"),
    (11, "GSCF-SMBC", WR, 3115, "15-Dec-2022"),
    (12, "GSCF HSBC Mexico", "Mexico", 3115, "15-Dec-2022"),
    (13, "ABSA AMSA Trade Finance II", "South Africa", 3115, "15-Dec-2022"),
    # GTSF shape: the programme and participants all booked to World Region.
    (20, "Global Trade Supplier Finance", WR, 1000, "21-Sep-2010"),
    (21, "GTSF-McCormick", WR, 1000, "21-Sep-2010"),
    (22, "GTSF Hugo Boss", WR, 1000, "21-Sep-2010"),
    (23, "GTSF Brazil Partner", "Brazil", 1000, "21-Sep-2010"),
    # Must be left alone.
    (30, "Two Of A Kind A", "India", 900, "01-Mar-2019"),          # only two
    (31, "Two Of A Kind B", "India", 900, "01-Mar-2019"),
    (40, "Small Stamp A", "Kenya", 400, "05-May-2018"),            # < $500m
    (41, "Small Stamp B", "Kenya", 400, "05-May-2018"),
    (42, "Small Stamp C", "Kenya", 400, "05-May-2018"),
    (50, "Big Round Deal 2016", "Turkey", 600, "10-Jun-2016"),     # same amount,
    (51, "Big Round Deal 2017", "Turkey", 600, "10-Jun-2017"),     # different
    (52, "Big Round Deal 2018", "Turkey", 600, "10-Jun-2018"),     # dates
    (60, "Undated A", "Peru", 800, None),                          # no date
    (61, "Undated B", "Peru", 800, None),
    (62, "Undated C", "Peru", 800, None),
]

PROGRAMME_KEEPS = {"Global Trade Finance Program (GTFP)"}
NULLED = {"GTFP Bank Egypt", "GTFP Bank Nepal", "GTFP Bank Yemen",
          "GSCF Citi II", "GSCF-SMBC", "GSCF HSBC Mexico",
          "ABSA AMSA Trade Finance II", "Global Trade Supplier Finance",
          "GTSF-McCormick", "GTSF Hugo Boss", "GTSF Brazil Partner"}
UNTOUCHED = {r[1] for r in RAW} - NULLED - PROGRAMME_KEEPS


def main():
    rows = [raw(*r) for r in RAW]
    conn = build_db()
    real = ifc.get_connection
    ifc.get_connection = lambda: KeepOpen(conn)
    try:
        ifc.load(rows)
    finally:
        ifc.get_connection = real

    stored = {r["project_name"]: r["amount_usd"] for r in
              conn.execute("SELECT project_name, amount_usd FROM projects")}
    issues = {}
    for r in conn.execute("SELECT project_name, detail FROM quality_issues "
                          "WHERE issue_type = 'program_envelope_amount'"):
        issues.setdefault(r["project_name"], []).append(r["detail"])

    print("1. GTFP: the single World Region record is the programme's")
    check("programme record keeps its USD 7bn",
          stored["Global Trade Finance Program (GTFP)"] == 7_000_000_000,
          f"got {stored['Global Trade Finance Program (GTFP)']}")
    check("partners booked to countries are NULLed",
          all(stored[n] is None for n in
              ("GTFP Bank Egypt", "GTFP Bank Nepal", "GTFP Bank Yemen")))

    print("\n2. GSCF: two World Region partners, no programme record")
    check("GSCF Citi II is NULLed (was USD 3,115m; its page says up to 250m)",
          stored["GSCF Citi II"] is None, f"got {stored['GSCF Citi II']}")
    check("GSCF-SMBC is NULLed", stored["GSCF-SMBC"] is None,
          f"got {stored['GSCF-SMBC']}")
    check("the country-booked GSCF partners are NULLed too",
          stored["GSCF HSBC Mexico"] is None
          and stored["ABSA AMSA Trade Finance II"] is None)

    print("\n3. GTSF: several World Region records, none exempt")
    wr_gtsf = ["Global Trade Supplier Finance", "GTSF-McCormick", "GTSF Hugo Boss"]
    check("no World Region GTSF record keeps USD 1bn",
          all(stored[n] is None for n in wr_gtsf),
          f"got {[stored[n] for n in wr_gtsf]}")

    print("\n4. logging")
    check("every NULLed record logged exactly once",
          set(issues) == NULLED and all(len(v) == 1 for v in issues.values()),
          f"logged {sorted(issues)} vs expected {sorted(NULLED)}")
    check("the programme record is NOT logged",
          "Global Trade Finance Program (GTFP)" not in issues)
    check("detail carries the envelope amount",
          "$3,115,000,000" in issues.get("GSCF Citi II", [""])[0],
          f"got {issues.get('GSCF Citi II')}")
    check("a World Region record says why it was not exempted",
          "World Region" in issues.get("GSCF-SMBC", [""])[0],
          f"got {issues.get('GSCF-SMBC')}")
    check("a country-booked record does not claim to be World Region",
          "World Region" not in issues.get("GSCF HSBC Mexico", ["World Region"])[0])

    print("\n5. the rule does not over-reach")
    wrongly = sorted(n for n in UNTOUCHED if stored[n] is None)
    check("two-record groups, sub-USD-500m groups, different dates and "
          "undated records keep their amounts", not wrongly,
          f"NULLed: {wrongly}")
    check("none of them is logged as an envelope",
          not (UNTOUCHED & set(issues)), f"{sorted(UNTOUCHED & set(issues))}")

    print("\n6. totals")
    total = sum(v for v in stored.values() if v)
    expected = 7_000_000_000 + 2 * 900e6 + 3 * 400e6 + 3 * 600e6 + 3 * 800e6
    check("stored IFC total is the programme record plus the untouched rows",
          total == expected, f"got {total:,.0f}, expected {expected:,.0f}")

    if failures:
        print(f"\n{len(failures)} CHECK(S) FAILED: {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
