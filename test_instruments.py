"""test_instruments.py — proves the instrument harmonization does the four
things it is supposed to do, and none of the things it must not.

Run:
    python test_instruments.py

It builds a small throwaway database in memory and a throwaway mapping CSV,
so it never reads or writes the real tracker. Exits non-zero if any check
fails, so it can be used as a gate before committing.

The four behaviours under test:
  1. a COMBINED instrument produces one row per canonical value, not one row
     with half the meaning thrown away;
  2. a BLANK canonical cell writes nothing and logs nothing — it means "we
     looked at this and chose not to map it";
  3. a raw value ABSENT from the CSV logs exactly ONE issue however many
     projects carry it — the distinction blank-vs-absent is the whole point;
  4. running it twice leaves the database exactly as it was after once;
  5. and — the one that catches a missing wipe — EDITING the CSV takes effect,
     so a mapping removed from the CSV disappears from the database instead of
     lingering. Idempotence alone does not prove this: INSERT OR IGNORE plus
     the uniqueness constraint keeps a rerun stable even with no wipe at all.
"""

import csv
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import harmonize  # noqa: E402
from database import SCHEMA  # noqa: E402

# --- the throwaway mapping ------------------------------------------------
MAP_ROWS = [
    ("EBRD", "Debt + Equity", "Senior debt", "combined - paired row"),
    ("EBRD", "Debt + Equity", "Equity", "combined - paired row"),
    ("EBRD", "Debt", "Senior debt", ""),
    ("IFC", "Risk Management", "", "deliberately unmapped, on purpose"),
]

# --- the throwaway projects ----------------------------------------------
#   id, institution, raw instrument
PROJECTS = [
    (1, "EBRD", "Debt + Equity"),      # -> two canonical rows
    (2, "EBRD", "Debt"),               # -> one
    (3, "IFC", "Risk Management"),     # -> none, and no complaint
    (4, "IFC", "Brand New Thing"),     # -> never seen, must be reported
    (5, "IFC", "Brand New Thing"),     # -> same label, still ONE report
    (6, "AfDB", None),                 # -> no instrument at all, ignored
]

failures = []


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
    for pid, institution, instrument in PROJECTS:
        conn.execute(
            "INSERT INTO projects (id, institution, instrument, source_url, "
            "scraped_at) VALUES (?, ?, ?, 'http://example.test', '2026-01-01')",
            (pid, institution, instrument))
    return conn


def instruments_of(conn, pid):
    return sorted(r[0] for r in conn.execute(
        "SELECT canonical_instrument FROM project_instruments WHERE project_id = ?",
        (pid,)))


def unmapped_issues(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM quality_issues "
        "WHERE issue_type = 'unmapped_instrument'").fetchone()[0]


def write_map(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["institution", "raw_instrument", "canonical_instrument", "notes"])
        w.writerows(rows)


def main():
    tmp = Path(tempfile.mkdtemp()) / "instrument_mapping.csv"
    write_map(tmp, MAP_ROWS)
    harmonize.INSTRUMENT_CSV = tmp          # point the module at the fake CSV

    conn = build_db()
    written, unmapped = harmonize.harmonize_instruments(conn)

    print("\n1. a combined instrument produces one row per canonical value")
    check("'Debt + Equity' yields both senior debt and equity",
          instruments_of(conn, 1) == ["Equity", "Senior debt"],
          f"got {instruments_of(conn, 1)}")
    check("a simple instrument yields exactly one row",
          instruments_of(conn, 2) == ["Senior debt"],
          f"got {instruments_of(conn, 2)}")

    print("\n2. a blank canonical writes nothing and logs nothing")
    check("blank mapping wrote no instrument rows",
          instruments_of(conn, 3) == [], f"got {instruments_of(conn, 3)}")
    check("blank mapping was NOT reported as unmapped",
          ("IFC", "Risk Management") not in unmapped,
          f"unmapped keys: {sorted(unmapped)}")

    print("\n3. an unseen raw value is reported exactly once")
    check("the unseen label was reported",
          ("IFC", "Brand New Thing") in unmapped, f"unmapped keys: {sorted(unmapped)}")
    check("reported once, not once per project (2 projects carry it)",
          unmapped.get(("IFC", "Brand New Thing")) == 2 and unmapped_issues(conn) == 1,
          f"count={unmapped.get(('IFC', 'Brand New Thing'))}, "
          f"issues={unmapped_issues(conn)}")

    print("\n4. the run is idempotent")
    before = (conn.execute("SELECT COUNT(*) FROM project_instruments").fetchone()[0],
              unmapped_issues(conn))
    harmonize.harmonize_instruments(conn)
    after = (conn.execute("SELECT COUNT(*) FROM project_instruments").fetchone()[0],
             unmapped_issues(conn))
    check("a second run changes nothing", before == after, f"{before} -> {after}")

    print("\n5. the CSV is the source of truth — removing a row removes the data")
    write_map(tmp, [r for r in MAP_ROWS
                    if not (r[0] == "EBRD" and r[1] == "Debt + Equity"
                            and r[2] == "Equity")])
    harmonize.harmonize_instruments(conn)
    check("dropping the paired row leaves only senior debt",
          instruments_of(conn, 1) == ["Senior debt"],
          f"got {instruments_of(conn, 1)} - stale rows were not cleared")
    write_map(tmp, MAP_ROWS)          # restore for the remaining checks
    harmonize.harmonize_instruments(conn)
    check("restoring the row brings it back",
          instruments_of(conn, 1) == ["Equity", "Senior debt"],
          f"got {instruments_of(conn, 1)}")

    print("\n6. the raw source value is never modified")
    raw = {r[0]: r[1] for r in conn.execute(
        "SELECT id, instrument FROM projects")}
    check("projects.instrument still holds the original labels",
          raw == {pid: instrument for pid, _, instrument in PROJECTS},
          f"got {raw}")
    check("a project with no instrument produced no rows",
          instruments_of(conn, 6) == [])

    print(f"\nrows written on the first run: {written}")
    if failures:
        print(f"\n{len(failures)} CHECK(S) FAILED: {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
