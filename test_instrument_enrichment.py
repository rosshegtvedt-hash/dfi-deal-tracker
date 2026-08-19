"""test_instrument_enrichment.py — proves the enrichment pass behaves.

Run:
    python test_instrument_enrichment.py

The fourth instrument-related suite, and its own file for the usual reason:
this mechanism has a rule none of the others has — enrichment may only fill
SILENCE. An instrument recovered from an institution's second publication must
never overwrite what the source we actually load published, or the database
starts disagreeing with its own citations.

Builds a throwaway in-memory database and throwaway CSVs. Exits non-zero if
any check fails.

Checks:
  1. an enriched value fills a project whose source published no instrument;
  2. enrichment NEVER overwrites a source label, even when they disagree;
  3. provenance is recorded: 'source_label' vs 'iati_enrichment';
  4. a blank canonical on an enriched value is silent, like anywhere else;
  5. an enriched value absent from the CSV is reported, like any raw label;
  6. an override still beats enrichment, and is tagged 'override';
  7. "this institution publishes no instrument" clears once enrichment covers
     it — the finding must not outlive the gap it describes;
  8. a rerun changes nothing.
"""

import csv
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import harmonize  # noqa: E402
from database import SCHEMA, MIGRATIONS  # noqa: E402

URL = "https://example.test/projects/"

MAP_ROWS = [
    ("AfDB", "421 Standard loan", "Senior debt", ""),
    ("AfDB", "110 Standard grant", "Technical assistance / grant", ""),
    ("AfDB", "912 Securities", "", "too vague to place"),
    ("IFC", "Loan", "Senior debt", ""),
]

OVERRIDE_ROWS = [
    ("AfDB", URL + "over", "Equity", "hand-reviewed, beats the enrichment"),
]

# (id, institution, instrument, instrument_enriched, url_suffix)
PROJECTS = [
    (1, "AfDB", None, "421 Standard loan", "alpha"),    # silence -> filled
    (2, "AfDB", None, "110 Standard grant", "beta"),    # silence -> filled
    (3, "AfDB", None, "912 Securities", "gamma"),       # blank canonical -> silent
    (4, "AfDB", None, "999 Brand New", "delta"),        # unseen -> reported
    (5, "IFC", "Loan", "110 Standard grant", "eps"),    # source wins over enrichment
    (6, "AfDB", None, None, "zeta"),                    # nothing at all
    (7, "AfDB", None, "421 Standard loan", "over"),     # override beats enrichment
]

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        if detail:
            print(f"          {detail}")
        failures.append(label)


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def build_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    # Apply migrations so the suite exercises the same shape a real upgraded
    # database has, not just the freshly-created one.
    for table, column, sql_type in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
    for pid, institution, instrument, enriched, suffix in PROJECTS:
        conn.execute(
            "INSERT INTO projects (id, institution, instrument, instrument_enriched,"
            " source_url, scraped_at) VALUES (?, ?, ?, ?, ?, '2026-01-01')",
            (pid, institution, instrument, enriched, URL + suffix))
    return conn


def rows_for(conn, pid):
    return [(r[0], r[1]) for r in conn.execute(
        "SELECT canonical_instrument, provenance FROM project_instruments "
        "WHERE project_id = ? ORDER BY canonical_instrument", (pid,)).fetchall()]


def main():
    tmp = Path(tempfile.mkdtemp())
    harmonize.INSTRUMENT_CSV = tmp / "instrument_mapping.csv"
    harmonize.INSTRUMENT_OVERRIDE_CSV = tmp / "instrument_overrides.csv"
    write_csv(harmonize.INSTRUMENT_CSV,
              ["institution", "raw_instrument", "canonical_instrument", "notes"],
              MAP_ROWS)
    write_csv(harmonize.INSTRUMENT_OVERRIDE_CSV,
              ["institution", "source_url", "canonical_instrument", "notes"],
              OVERRIDE_ROWS)

    conn = build_db()
    written, unmapped, enriched = harmonize.harmonize_instruments(conn)
    harmonize.apply_instrument_overrides(conn)

    print("\n1. enrichment fills a project whose source published nothing")
    check("'421 Standard loan' -> Senior debt",
          rows_for(conn, 1) == [("Senior debt", "iati_enrichment")],
          f"got {rows_for(conn, 1)}")
    check("'110 Standard grant' -> Technical assistance / grant",
          rows_for(conn, 2) == [("Technical assistance / grant", "iati_enrichment")],
          f"got {rows_for(conn, 2)}")

    print("\n2. enrichment never overwrites what the source published")
    check("IFC kept its own 'Loan', not the enriched grant",
          rows_for(conn, 5) == [("Senior debt", "source_label")],
          f"got {rows_for(conn, 5)} - enrichment overwrote a real disclosure")

    print("\n3. provenance distinguishes the two")
    kinds = {r[0] for r in conn.execute(
        "SELECT DISTINCT provenance FROM project_instruments")}
    check("both 'source_label' and 'iati_enrichment' are present",
          {"source_label", "iati_enrichment"} <= kinds, f"got {kinds}")
    # 3, not 2: the override target is enriched first and only replaced after,
    # so this is the count as harmonize_instruments leaves it.
    check("the enriched row count is reported", enriched == 3, f"got {enriched}")

    print("\n4. a blank canonical is silent")
    check("'912 Securities' wrote nothing", rows_for(conn, 3) == [],
          f"got {rows_for(conn, 3)}")
    check("and was not reported as unmapped",
          ("AfDB", "912 Securities") not in unmapped, f"unmapped: {sorted(unmapped)}")

    print("\n5. an unseen enriched value is reported like any raw label")
    check("'999 Brand New' was reported",
          ("AfDB", "999 Brand New") in unmapped, f"unmapped: {sorted(unmapped)}")
    check("and logged as 'unmapped_instrument'",
          conn.execute("SELECT COUNT(*) FROM quality_issues WHERE issue_type="
                       "'unmapped_instrument'").fetchone()[0] == 1)

    print("\n6. an override beats enrichment")
    check("the hand-reviewed value won, tagged 'override'",
          rows_for(conn, 7) == [("Equity", "override")], f"got {rows_for(conn, 7)}")
    check("a project with nothing at all stayed empty", rows_for(conn, 6) == [])

    print("\n7. the 'publishes no instrument' finding clears once enriched")
    harmonize.NO_INSTRUMENT_SOURCES = {
        "AfDB": "no instrument", "IFC": "no instrument"}
    flagged = harmonize.flag_institutions_without_instruments(conn)
    check("AfDB is no longer flagged — enrichment counts as coverage",
          "AfDB" not in flagged, f"flagged: {flagged}")
    conn.execute("UPDATE projects SET instrument_enriched = NULL WHERE institution='AfDB'")
    check("but it IS flagged again when the enrichment is removed",
          "AfDB" in harmonize.flag_institutions_without_instruments(conn))
    conn.execute("UPDATE projects SET instrument_enriched = ? WHERE id = 1",
                 ("421 Standard loan",))

    print("\n8. the run is idempotent")
    def snapshot():
        return sorted(tuple(r) for r in conn.execute(
            "SELECT project_id, canonical_instrument, provenance FROM project_instruments"))
    harmonize.harmonize_instruments(conn)
    harmonize.apply_instrument_overrides(conn)
    before = snapshot()
    harmonize.harmonize_instruments(conn)
    harmonize.apply_instrument_overrides(conn)
    check("a second run changes nothing", snapshot() == before)

    print(f"\nrows written: {written}, of which enriched: {enriched}")
    if failures:
        print(f"\n{len(failures)} CHECK(S) FAILED: {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
