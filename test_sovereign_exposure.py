"""test_sovereign_exposure.py — proves AfDB's sovereign flag lands correctly.

Run:
    python test_sovereign_exposure.py

Its own file rather than an extension of any existing suite, for the usual
reason: this is a LOADER-level parse of a flag the source publishes, not a
mapping CSV and not a derivation, so a failure here should name the loader
and nothing else.

What makes this field worth a suite of its own is that it is the field that
decides whether AfDB belongs in a given chart. Roughly 92% of AfDB's
infrastructure operations are sovereign, so a wrong value here does not
produce a visibly broken number — it produces a plausible one that puts a
road ministry loan beside a solar IPP.

Builds a throwaway in-memory database and a throwaway CSV; never reads or
writes the real tracker. Exits non-zero if any check fails.

Checks:
  1. True -> 'sovereign', False -> 'non-sovereign', and every emitted value
     is in CANONICAL_SOVEREIGN_EXPOSURE;
  2. an UNEXPECTED encoding ('1', 'yes', 'Sovereign') is NOT guessed at — the
     column stays NULL and one issue is logged per row. This is the guard
     that matters: if MapAfrica ever switches the export to 1/0, a lenient
     parse would silently relabel the whole bank;
  3. a BLANK flag is logged too, and left NULL;
  4. provenance is set if and only if a value is;
  5. NULL means "the source does not say", never "private" — no other
     institution's rows are touched;
  6. the description prose the dashboards read is unchanged by any of this;
  7. changing the source value CHANGES the stored value (idempotence alone
     would pass even if the loader never wiped the old row).
"""

import csv
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent))
from database import CANONICAL_SOVEREIGN_EXPOSURE, MIGRATIONS, SCHEMA  # noqa: E402
from scrapers import afdb  # noqa: E402

COLUMNS = ["identifier", "title", "country", "activity_status", "Approval Date",
           "AfDB Sector", "environmental_safeguards", "total_commitments (UA)",
           "sovereign", "afdb_status"]

# identifier, title, sovereign-as-published, afdb_status
ROWS = [
    ("P-001", "Kenya - Road Modernization", "True", "ADF"),
    ("P-002", "South Africa -Transnet III", "False", "ADB"),
    ("P-003", "Egypt - Suez Wind Farm", "False", ""),
    ("P-004", "Mali - Water Supply", "True", ""),
    ("P-005", "Ghana - Encoding Changed", "1", "ADF"),       # unexpected encoding
    ("P-006", "Togo - Encoding Changed Too", "yes", "ADF"),  # unexpected encoding
    ("P-007", "Benin - Word Not Boolean", "Sovereign", ""),  # looks right, isn't
    ("P-008", "Chad - Flag Missing", "", "ADF"),             # blank
]

REFUSED = ["Ghana - Encoding Changed", "Togo - Encoding Changed Too",
           "Benin - Word Not Boolean", "Chad - Flag Missing"]

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
        for identifier, title, sovereign, window in rows:
            w.writerow([identifier, title, "Kenya", "Ongoing", "2020-01-15",
                        "Transport", "2", "100000000", sovereign, window])


def build_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for table, column, sql_type in MIGRATIONS:
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
    # A row from another institution, present throughout: it must never
    # acquire a sovereign_exposure value, and the AfDB wipe must not touch it.
    conn.execute(
        "INSERT INTO projects (institution, project_name, source_url, scraped_at) "
        "VALUES ('IFC', 'Private Sector Deal', 'http://example.test/ifc', '2026-01-01')")
    return conn


class KeepOpen:
    """Forwards everything to the connection except close().

    load() closes its connection in a finally block, which would discard an
    in-memory database before we could inspect it. sqlite3.Connection.close
    is read-only, so the substitution has to happen one level up.
    """

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


def run_load(conn, tmpdir, rows):
    """Run the real loader against a throwaway CSV and our in-memory database."""
    path = Path(tmpdir) / "afdb_mapafrica_test.csv"
    write_csv(path, rows)
    real_get_connection = afdb.get_connection
    afdb.get_connection = lambda: KeepOpen(conn)
    try:
        afdb.load(path)
    finally:
        afdb.get_connection = real_get_connection


def stored(conn):
    return {r["project_name"]: (r["sovereign_exposure"], r["sovereign_provenance"])
            for r in conn.execute(
                "SELECT project_name, sovereign_exposure, sovereign_provenance "
                "FROM projects WHERE institution = 'AfDB'")}


def flag_issues(conn):
    return [r["project_name"] for r in conn.execute(
        "SELECT project_name FROM quality_issues "
        "WHERE issue_type = 'unmapped_sovereign_flag'")]


def main():
    conn = build_db()
    with TemporaryDirectory() as tmpdir:
        print("1. the published booleans map to the canonical vocabulary")
        run_load(conn, tmpdir, ROWS)
        got = stored(conn)
        check("True -> 'sovereign'",
              got["Kenya - Road Modernization"][0] == "sovereign",
              f"got {got['Kenya - Road Modernization'][0]!r}")
        check("False -> 'non-sovereign'",
              got["South Africa -Transnet III"][0] == "non-sovereign",
              f"got {got['South Africa -Transnet III'][0]!r}")
        check("a non-sovereign row with no window still maps",
              got["Egypt - Suez Wind Farm"][0] == "non-sovereign")
        values = {v for v, _ in got.values() if v is not None}
        check("every emitted value is in CANONICAL_SOVEREIGN_EXPOSURE",
              values <= set(CANONICAL_SOVEREIGN_EXPOSURE), f"got {values}")

        print("\n2. an unexpected encoding is refused, not guessed")
        for title in REFUSED[:3]:
            check(f"{title.split(' - ')[1]!r} leaves the column NULL",
                  got[title][0] is None, f"got {got[title][0]!r}")
        logged = flag_issues(conn)
        check("each refused row logs exactly one issue",
              sorted(logged) == sorted(REFUSED), f"got {sorted(logged)}")

        print("\n3. a blank flag is left NULL and reported")
        check("blank -> NULL", got["Chad - Flag Missing"][0] is None)
        check("blank is reported, not silent", "Chad - Flag Missing" in logged)

        print("\n4. provenance is set if and only if a value is")
        check("value implies provenance 'afdb_sovereign_flag'",
              all(p == "afdb_sovereign_flag" for v, p in got.values() if v),
              f"got {got}")
        check("no value implies no provenance",
              all(p is None for v, p in got.values() if not v), f"got {got}")

        print("\n5. NULL is 'the source does not say', not 'private'")
        other = conn.execute(
            "SELECT sovereign_exposure, sovereign_provenance FROM projects "
            "WHERE institution = 'IFC'").fetchone()
        check("another institution's row is untouched",
              other["sovereign_exposure"] is None
              and other["sovereign_provenance"] is None, f"got {tuple(other)}")
        check("the AfDB wipe did not delete it",
              conn.execute("SELECT COUNT(*) FROM projects "
                           "WHERE institution = 'IFC'").fetchone()[0] == 1)

        print("\n6. the description prose is unchanged")
        prose = {r["project_name"]: r["description"] for r in conn.execute(
            "SELECT project_name, description FROM projects "
            "WHERE institution = 'AfDB'")}
        check("sovereign row keeps its window suffix",
              prose["Kenya - Road Modernization"] == "Sovereign operation; window: ADF",
              f"got {prose['Kenya - Road Modernization']!r}")
        check("non-sovereign row without a window keeps the bare phrase",
              prose["Egypt - Suez Wind Farm"] == "Non-sovereign operation",
              f"got {prose['Egypt - Suez Wind Farm']!r}")

        print("\n7. changing the source value changes the stored value")
        flipped = [(i, t, ("False" if s == "True" else s), w) for i, t, s, w in ROWS]
        run_load(conn, tmpdir, flipped)
        after = stored(conn)
        check("a row that flipped True->False is now non-sovereign",
              after["Kenya - Road Modernization"][0] == "non-sovereign",
              f"got {after['Kenya - Road Modernization'][0]!r} - the old row survived")
        check("the reload did not duplicate rows",
              conn.execute("SELECT COUNT(*) FROM projects "
                           "WHERE institution = 'AfDB'").fetchone()[0] == len(ROWS))
        check("stale quality issues were cleared too",
              len(flag_issues(conn)) == len(REFUSED),
              f"got {len(flag_issues(conn))}")

    if failures:
        print(f"\n{len(failures)} CHECK(S) FAILED: {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
