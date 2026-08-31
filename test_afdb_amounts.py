"""test_afdb_amounts.py — proves AfDB loads its own commitment, not the
programme envelope.

Run:
    python test_afdb_amounts.py

Its own file because this is a LOADER-level column choice, not a mapping and
not a derivation, so a failure should name the loader and nothing else.

Why it earns a suite. MapAfrica publishes two commitment figures that disagree
on 37% of rows, and the wrong one is the LARGER, so choosing it produces
numbers that look impressive rather than broken. Loading the envelope put a
single USD 7.79bn row into the database (Ethiopia's Basic Services
Transformation Programme: UA 5,580m committed against UA 180m disbursed on a
project marked Completion) and carried Ethiopia into the top fifteen
recipients on that one row. Nothing about that reads as a bug from the
outside, which is exactly why it needs a regression test.

Builds a throwaway in-memory database and a throwaway CSV; never reads or
writes the real tracker. Exits non-zero if any check fails.

Checks:
  1. where the two columns AGREE, the shared value loads unchanged and
     nothing is logged;
  2. where they DIVERGE, the narrower `nongov` figure wins;
  3. every divergence is logged as `programme_envelope_amount`, one per row,
     and the detail names both figures so the correction is auditable;
  4. a MISSING nongov column falls back to the envelope rather than dropping
     the amount, and a row with neither logs `missing_amount`;
  5. currency and amount_original stay consistent with the amount chosen, so
     the UA figure and the USD figure can never describe different columns;
  6. the regression itself: the Ethiopia BSTP shape never loads at envelope
     size again.
"""

import csv
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent))
from database import MIGRATIONS, SCHEMA  # noqa: E402
from scrapers import afdb  # noqa: E402

COLUMNS = ["identifier", "title", "country", "activity_status", "Approval Date",
           "AfDB Sector", "environmental_safeguards", "total_commitments (UA)",
           "total_commitments_nongov (UA)", "sovereign", "afdb_status"]

# identifier, title, envelope, nongov
ROWS = [
    ("P-001", "Kenya - Ordinary Road Project", "100000000", "100000000"),
    ("P-002", "Ethiopia - Basic Services Transformation Programme (BSTP)",
     "5580000000", "180000000"),
    ("P-003", "South Africa - Medupi Power Project", "6694477072", "1254477072"),
    ("P-004", "Morocco - Education Emergency Support", "3009163547", "63968067"),
    ("P-005", "Ghana - Nongov Column Empty", "250000000", ""),
    ("P-006", "Chad - No Amount At All", "", ""),
]

DIVERGENT = ["Ethiopia - Basic Services Transformation Programme (BSTP)",
             "South Africa - Medupi Power Project",
             "Morocco - Education Emergency Support"]

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        if detail:
            print(f"          {detail}")
        failures.append(label)


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for identifier, title, envelope, nongov in rows:
            w.writerow([identifier, title, "Kenya", "Completion", "2015-12-17",
                        "Social", "2", envelope, nongov, "True", "ADF"])


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
    """Forwards everything but close(); see test_sovereign_exposure.py."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


def run_load(conn, tmpdir, rows):
    path = Path(tmpdir) / "afdb_mapafrica_test.csv"
    write_csv(path, rows)
    real = afdb.get_connection
    afdb.get_connection = lambda: KeepOpen(conn)
    try:
        afdb.load(path)
    finally:
        afdb.get_connection = real


def stored(conn):
    return {r["project_name"]: r for r in conn.execute(
        "SELECT project_name, amount_original, currency, amount_usd "
        "FROM projects WHERE institution = 'AfDB'")}


def issues(conn, kind):
    return {r["project_name"]: r["detail"] for r in conn.execute(
        "SELECT project_name, detail FROM quality_issues WHERE issue_type = ?",
        (kind,))}


def main():
    conn = build_db()
    with TemporaryDirectory() as tmpdir:
        run_load(conn, tmpdir, ROWS)
        got = stored(conn)
        envelopes = issues(conn, "programme_envelope_amount")

        print("1. agreeing columns load unchanged")
        check("the shared figure is loaded",
              got["Kenya - Ordinary Road Project"]["amount_original"] == 100_000_000,
              f"got {got['Kenya - Ordinary Road Project']['amount_original']!r}")
        check("and nothing is logged for it",
              "Kenya - Ordinary Road Project" not in envelopes)

        print("\n2. where they diverge, the NARROWER figure wins")
        check("Ethiopia BSTP loads UA 180m, not UA 5,580m",
              got[DIVERGENT[0]]["amount_original"] == 180_000_000,
              f"got {got[DIVERGENT[0]]['amount_original']!r}")
        check("Medupi loads UA 1,254m, not UA 6,694m",
              got[DIVERGENT[1]]["amount_original"] == 1_254_477_072,
              f"got {got[DIVERGENT[1]]['amount_original']!r}")
        check("Morocco loads UA 64m, not UA 3,009m",
              got[DIVERGENT[2]]["amount_original"] == 63_968_067,
              f"got {got[DIVERGENT[2]]['amount_original']!r}")

        print("\n3. every divergence is logged, once, with both figures")
        check("exactly the three divergent rows are logged",
              sorted(envelopes) == sorted(DIVERGENT), f"got {sorted(envelopes)}")
        detail = envelopes.get(DIVERGENT[0], "")
        check("the detail names the envelope it replaced",
              "5,580,000,000" in detail, f"got {detail!r}")
        check("and the figure it used instead",
              "180,000,000" in detail, f"got {detail!r}")

        print("\n4. a missing nongov column falls back rather than dropping")
        check("blank nongov falls back to the envelope",
              got["Ghana - Nongov Column Empty"]["amount_original"] == 250_000_000,
              f"got {got['Ghana - Nongov Column Empty']['amount_original']!r}")
        check("the fallback is not logged as a replacement",
              "Ghana - Nongov Column Empty" not in envelopes)
        check("neither column present logs missing_amount",
              "Chad - No Amount At All" in issues(conn, "missing_amount"))
        check("and leaves the amount NULL",
              got["Chad - No Amount At All"]["amount_original"] is None)

        print("\n5. currency and USD stay tied to the chosen figure")
        for title in DIVERGENT + ["Kenya - Ordinary Road Project"]:
            row = got[title]
            if row["amount_original"] is None:
                continue
            check(f"{title.split(' - ')[0]}: currency set with an amount",
                  row["currency"] == "XDR", f"got {row['currency']!r}")
        bstp, medupi = got[DIVERGENT[0]], got[DIVERGENT[1]]
        check("USD tracks the narrow figure, so BSTP stays below Medupi",
              bstp["amount_usd"] < medupi["amount_usd"],
              f"BSTP {bstp['amount_usd']!r} vs Medupi {medupi['amount_usd']!r}")

        print("\n6. the regression, stated as the defect it replaces")
        biggest = max(r["amount_usd"] for r in got.values()
                      if r["amount_usd"] is not None)
        check("no operation loads at envelope scale (USD 7.79bn)",
              biggest < 3e9, f"largest loaded USD {biggest:,.0f}")

    if failures:
        print(f"\n{len(failures)} CHECK(S) FAILED: {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
