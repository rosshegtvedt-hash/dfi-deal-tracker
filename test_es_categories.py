"""test_es_categories.py — proves the E&S category harmonization behaves.

Run:
    python test_es_categories.py

A sibling of test_instruments.py rather than an extension of it: instruments
are one-to-many and land in a child table, E&S is one-to-one and lands in a
column, so keeping them apart means a failure names the right mechanism.

Builds a throwaway in-memory database and a throwaway mapping CSV, so it
never reads or writes the real tracker. Exits non-zero if any check fails.

Checks:
  1. a mapped grade fills canonical_es_category, and different dialects
     ("B - Limited", "Category 2", "B+") land on the right shared level;
  2. a BLANK canonical is silent — no value written, nothing logged;
  3. a raw grade ABSENT from the CSV logs exactly ONE issue however many
     projects carry it;
  4. a rerun changes nothing;
  5. editing the CSV takes effect — the check that a missing wipe fails;
  6. projects.es_category, the raw source value, is never modified.
"""

import csv
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import harmonize  # noqa: E402
from database import SCHEMA  # noqa: E402

MAP_ROWS = [
    # institution, raw, canonical, source_url, notes
    ("IFC", "B - Limited", "Moderate", "http://example.test/ifc", ""),
    ("IFC", "FI", "", "", "generic FI, deliberately unmapped"),
    ("AfDB", "Category 2", "Moderate", "http://example.test/afdb", ""),
    ("Proparco", "B+", "Substantial", "http://example.test/afd", ""),
]

PROJECTS = [
    (1, "IFC", "B - Limited"),        # -> Moderate
    (2, "AfDB", "Category 2"),        # -> Moderate, different dialect
    (3, "Proparco", "B+"),            # -> Substantial, a level only AFD uses
    (4, "IFC", "FI"),                 # -> blank: no value, no complaint
    (5, "IFC", "Brand New Grade"),    # -> unseen, must be reported
    (6, "IFC", "Brand New Grade"),    # -> same label, still ONE report
    (7, "EBRD", None),                # -> no grade at all, ignored
]

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        if detail:
            print(f"          {detail}")
        failures.append(label)


def write_map(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["institution", "raw_es_category", "canonical_es_category",
                    "source_url", "notes"])
        w.writerows(rows)


def build_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for pid, institution, es in PROJECTS:
        conn.execute(
            "INSERT INTO projects (id, institution, es_category, source_url, "
            "scraped_at) VALUES (?, ?, ?, 'http://example.test', '2026-01-01')",
            (pid, institution, es))
    return conn


def canon(conn, pid):
    return conn.execute("SELECT canonical_es_category FROM projects WHERE id = ?",
                        (pid,)).fetchone()[0]


def issues(conn):
    return conn.execute("SELECT COUNT(*) FROM quality_issues "
                        "WHERE issue_type = 'unmapped_es_category'").fetchone()[0]


def main():
    tmp = Path(tempfile.mkdtemp()) / "es_category_mapping.csv"
    write_map(tmp, MAP_ROWS)
    harmonize.ES_CATEGORY_CSV = tmp

    conn = build_db()
    mapped, unmapped = harmonize.harmonize_es_categories(conn)

    print("\n1. mapped grades fill the canonical column")
    check("IFC 'B - Limited' -> Moderate", canon(conn, 1) == "Moderate",
          f"got {canon(conn, 1)!r}")
    check("AfDB 'Category 2' -> the same Moderate", canon(conn, 2) == "Moderate",
          f"got {canon(conn, 2)!r}")
    check("Proparco 'B+' -> Substantial", canon(conn, 3) == "Substantial",
          f"got {canon(conn, 3)!r}")

    print("\n2. a blank canonical is silent")
    check("blank wrote no canonical value", canon(conn, 4) is None,
          f"got {canon(conn, 4)!r}")
    check("blank was NOT reported as unmapped",
          ("IFC", "FI") not in unmapped, f"unmapped: {sorted(unmapped)}")

    print("\n3. an unseen grade is reported exactly once")
    check("the unseen grade was reported",
          ("IFC", "Brand New Grade") in unmapped, f"unmapped: {sorted(unmapped)}")
    check("reported once, not once per project (2 carry it)",
          unmapped.get(("IFC", "Brand New Grade")) == 2 and issues(conn) == 1,
          f"count={unmapped.get(('IFC', 'Brand New Grade'))}, issues={issues(conn)}")

    print("\n4. the run is idempotent")
    before = (sorted((r[0], r[1]) for r in conn.execute(
        "SELECT id, canonical_es_category FROM projects")), issues(conn))
    harmonize.harmonize_es_categories(conn)
    after = (sorted((r[0], r[1]) for r in conn.execute(
        "SELECT id, canonical_es_category FROM projects")), issues(conn))
    check("a second run changes nothing", before == after)

    print("\n5. the CSV is the source of truth — removing a row clears the data")
    write_map(tmp, [r for r in MAP_ROWS if r[1] != "B - Limited"])
    harmonize.harmonize_es_categories(conn)
    check("dropping the mapping clears the canonical value",
          canon(conn, 1) is None,
          f"got {canon(conn, 1)!r} - the previous value was not cleared")
    check("and the now-unmapped grade is reported",
          issues(conn) == 2, f"issues={issues(conn)}")
    write_map(tmp, MAP_ROWS)
    harmonize.harmonize_es_categories(conn)
    check("restoring the row brings the value back", canon(conn, 1) == "Moderate")

    print("\n6. the raw source value is never modified")
    raw = {r[0]: r[1] for r in conn.execute("SELECT id, es_category FROM projects")}
    check("projects.es_category still holds the original grades",
          raw == {pid: es for pid, _, es in PROJECTS}, f"got {raw}")
    check("a project with no grade got no canonical value", canon(conn, 7) is None)

    print(f"\nprojects mapped on the first run: {mapped}")
    if failures:
        print(f"\n{len(failures)} CHECK(S) FAILED: {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
