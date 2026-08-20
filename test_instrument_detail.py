"""test_instrument_detail.py — proves we never assert a seniority nobody stated.

Run:
    python test_instrument_detail.py

This suite exists because of a real defect. The canonical vocabulary used to
carry "Senior debt", and IFC's "Loan" and EBRD's "Debt" were both mapped to
it — even though neither source distinguishes senior from subordinated. Two
rows proved the harm:

    IFC   "Ecobank Ghana Tier II Subordinated Debt"  raw='Loan' -> Senior debt
    EBRD  "Koudia Al Baida - Subordinated loan"      raw='Debt' -> Senior debt

A Tier II instrument is subordinated by definition. Both said "Subordinated"
in their own project names and were stored as senior.

The replacement is two levels: a FAMILY that every source can support (Debt),
and an optional DETAIL populated only where a source states it. **A NULL
detail means "not disclosed". It does not mean senior**, and the checks below
exist mostly to keep it that way.

Builds a throwaway in-memory database and throwaway CSVs. Exits non-zero if
any check fails.

Checks:
  1. a coarse raw label ("Loan", "Debt") gives family=Debt and detail NULL —
     the defect, stated as a test;
  2. seniority in the PROJECT NAME is recovered, tagged 'project_name';
  3. the Ecobank Tier II regression: subordinated, not senior;
  4. word boundaries hold — "Frontier II" is not Tier II, "Lionbridge Loan"
     is not a bridge loan, "SeniorAssist" is not senior;
  5. non-financial senses are excluded — a senior secondary school and a
     junior mining fund are not tranches;
  6. a name stating TWO seniorities is logged as ambiguous, not resolved;
  7. a detail belonging to another family is refused — a "Mezzanine Fund"
     held as equity is not mezzanine debt;
 7b. a detail stated by the raw LABEL is never overwritten by the name;
  8. an override still wins, and can set family and detail together;
  9. a rerun changes nothing.
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
    # institution, raw, family, detail, notes
    ("IFC", "Loan", "Debt", "", "coarse: no seniority stated"),
    ("EBRD", "Debt", "Debt", "", "coarse: no seniority stated"),
    ("IFC", "Equity", "Equity", "", ""),
    ("IFC", "Subordinated Loan", "Debt", "subordinated",
     "this raw label states seniority on its own"),
]

DETAIL_RULES = [
    ("senior", "senior", ""),
    ("senior loan", "senior", ""),
    ("subordinated", "subordinated", ""),
    ("tier ii", "subordinated", "Tier 2 capital is subordinated by definition"),
    ("mezzanine loan", "mezzanine", ""),
    ("bridge loan", "bridge", ""),
    ("exclude", "senior secondary", "a school"),
    ("exclude", "junior mining", "a small-cap miner"),
    ("exclude", "mezzanine fund", "a vehicle, not the DFI's own instrument"),
]

OVERRIDE_ROWS = [
    ("IFC", URL + "over", "Debt", "subordinated", "hand-reviewed"),
]

# (id, institution, raw instrument, project_name, url_suffix)
PROJECTS = [
    (1, "IFC", "Loan", "Kabul Bank Working Capital", "a"),        # coarse -> NULL
    (2, "EBRD", "Debt", "Some Ordinary Facility", "b"),           # coarse -> NULL
    (3, "IFC", "Loan", "SHL Senior Loan", "c"),                   # -> senior
    (4, "IFC", "Loan", "Ecobank Ghana Tier II Subordinated Debt", "d"),
    (5, "EBRD", "Debt", "Koudia Al Baida - Subordinated loan", "e"),
    (6, "IFC", "Loan", "Frontier II", "f"),                       # NOT tier ii
    (7, "IFC", "Loan", "Lionbridge Loan", "g"),                   # NOT bridge loan
    (8, "IFC", "Loan", "SeniorAssist LAC", "h"),                  # NOT senior
    (9, "IFC", "Loan", "Ghana Senior Secondary School Facility", "i"),
    (10, "IFC", "Equity", "South Africa Junior Mining Fund", "j"),
    (11, "IFC", "Loan", "Promerica - Senior and Subordinated Loan", "k"),
    (12, "IFC", "Equity", "Vantage Mezzanine Fund IV", "l"),      # excluded anyway
    (13, "IFC", "Equity", "Accession Mezzanine Loan Vehicle", "m"),  # wrong family
    (14, "IFC", "Loan", "Anything At All", "over"),               # override wins
    # The label says subordinated; the NAME says senior. The label wins,
    # because enrichment from a name must not overwrite a stated fact.
    (15, "IFC", "Subordinated Loan", "Acme Senior Loan Facility", "n"),
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
    for table, column, sql_type in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
    for pid, institution, instrument, name, suffix in PROJECTS:
        conn.execute(
            "INSERT INTO projects (id, institution, instrument, project_name, "
            "source_url, scraped_at) VALUES (?, ?, ?, ?, ?, '2026-01-01')",
            (pid, institution, instrument, name, URL + suffix))
    return conn


def got(conn, pid):
    """(family, detail, detail_provenance) tuples for one project."""
    return sorted(tuple(r) for r in conn.execute(
        "SELECT canonical_instrument, instrument_detail, detail_provenance "
        "FROM project_instruments WHERE project_id = ?", (pid,)).fetchall())


def issues(conn, kind):
    return conn.execute("SELECT COUNT(*) FROM quality_issues WHERE issue_type = ?",
                        (kind,)).fetchone()[0]


def run(conn):
    harmonize.harmonize_instruments(conn)
    result = harmonize.derive_instrument_details(conn)
    harmonize.apply_instrument_overrides(conn)
    return result


def main():
    tmp = Path(tempfile.mkdtemp())
    harmonize.INSTRUMENT_CSV = tmp / "instrument_mapping.csv"
    harmonize.INSTRUMENT_DETAIL_CSV = tmp / "instrument_detail_rules.csv"
    harmonize.INSTRUMENT_OVERRIDE_CSV = tmp / "instrument_overrides.csv"
    write_csv(harmonize.INSTRUMENT_CSV,
              ["institution", "raw_instrument", "canonical_instrument",
               "canonical_detail", "notes"], MAP_ROWS)
    write_csv(harmonize.INSTRUMENT_DETAIL_CSV,
              ["pattern", "detail", "notes"], DETAIL_RULES)
    write_csv(harmonize.INSTRUMENT_OVERRIDE_CSV,
              ["institution", "source_url", "canonical_instrument",
               "canonical_detail", "notes"], OVERRIDE_ROWS)

    conn = build_db()
    filled, ambiguous, mismatch = run(conn)

    print("\n1. a coarse label states no seniority, and we do not invent one")
    check("IFC 'Loan' -> Debt with detail NULL",
          got(conn, 1) == [("Debt", None, None)], f"got {got(conn, 1)}")
    check("EBRD 'Debt' -> Debt with detail NULL",
          got(conn, 2) == [("Debt", None, None)], f"got {got(conn, 2)}")

    print("\n2. seniority stated in the project name is recovered")
    check("'SHL Senior Loan' -> Debt/senior from the name",
          got(conn, 3) == [("Debt", "senior", "project_name")], f"got {got(conn, 3)}")

    print("\n3. THE REGRESSION: Tier II is subordinated, not senior")
    check("'Ecobank Ghana Tier II Subordinated Debt' -> subordinated",
          got(conn, 4) == [("Debt", "subordinated", "project_name")],
          f"got {got(conn, 4)} - this row was stored as SENIOR before the fix")
    check("'Koudia Al Baida - Subordinated loan' -> subordinated",
          got(conn, 5) == [("Debt", "subordinated", "project_name")],
          f"got {got(conn, 5)}")

    print("\n4. word boundaries: a substring is not a match")
    check("'Frontier II' is not Tier II", got(conn, 6) == [("Debt", None, None)],
          f"got {got(conn, 6)}")
    check("'Lionbridge Loan' is not a bridge loan",
          got(conn, 7) == [("Debt", None, None)], f"got {got(conn, 7)}")
    check("'SeniorAssist LAC' is not senior",
          got(conn, 8) == [("Debt", None, None)], f"got {got(conn, 8)}")

    print("\n5. non-financial senses are excluded")
    check("a senior secondary SCHOOL is not a senior tranche",
          got(conn, 9) == [("Debt", None, None)], f"got {got(conn, 9)}")
    check("a junior MINING fund is not junior debt",
          got(conn, 10) == [("Equity", None, None)], f"got {got(conn, 10)}")

    print("\n6. two seniorities in one name is ambiguous, not a coin toss")
    check("'Senior and Subordinated Loan' set no detail",
          got(conn, 11) == [("Debt", None, None)], f"got {got(conn, 11)}")
    check("and was logged as ambiguous",
          issues(conn, "ambiguous_instrument_detail") == 1 and len(ambiguous) == 1,
          f"logged={issues(conn, 'ambiguous_instrument_detail')}, "
          f"returned={len(ambiguous)}")

    print("\n7. a detail from the wrong family is refused")
    check("a mezzanine LOAN name on an EQUITY deal sets nothing",
          got(conn, 13) == [("Equity", None, None)], f"got {got(conn, 13)}")
    check("and was logged as a family mismatch",
          issues(conn, "instrument_detail_family_mismatch") == 1 and len(mismatch) == 1,
          f"logged={issues(conn, 'instrument_detail_family_mismatch')}")
    check("an excluded 'Mezzanine Fund' never even gets that far",
          got(conn, 12) == [("Equity", None, None)], f"got {got(conn, 12)}")

    print("\n7b. a name never overwrites a detail the source label stated")
    check("label says subordinated, name says senior - label wins",
          got(conn, 15) == [("Debt", "subordinated", "source_label")],
          f"got {got(conn, 15)} - the project-name pass overwrote a stated fact")

    print("\n8. an override still wins, and carries its own provenance")
    check("override set family AND detail, tagged manual_override",
          got(conn, 14) == [("Debt", "subordinated", "manual_override")],
          f"got {got(conn, 14)}")

    print("\n9. the run is idempotent")
    def snap():
        return sorted(tuple(r) for r in conn.execute(
            "SELECT project_id, canonical_instrument, instrument_detail, "
            "detail_provenance FROM project_instruments"))
    before = snap()
    run(conn)
    check("a second run changes nothing", snap() == before)

    print(f"\ndetails recovered from names on the first run: {filled}")
    if failures:
        print(f"\n{len(failures)} CHECK(S) FAILED: {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
