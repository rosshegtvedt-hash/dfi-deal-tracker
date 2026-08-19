"""test_counterparties.py — proves the counterparty derivation behaves.

Run:
    python test_counterparties.py

Its own suite because this is the only derivation in the project that INVENTS
a field rather than translating one. The risks are different from the mapping
layers: a bad rule here doesn't mislabel a deal, it manufactures a company
that does not exist, or quietly deletes a real client's name.

Builds a throwaway in-memory database and throwaway CSVs. Exits non-zero if
any check fails.

Checks:
  1. a published sponsor is used verbatim and marked 'disclosed';
  2. where none is published, the project name is cleaned and marked derived;
  3. institutions whose names are PROJECTS, not clients, yield nothing —
     the guard that stops ~10,000 invented companies;
  4. programme codes are stripped whether separated by a dash or a space;
  5. a leading acronym that is a real CLIENT is NOT stripped (OTP, TBC, NLB);
  6. trailing product words are stripped;
  7. a name that is only a country is not a company;
  8. an institution naming itself is not a client relationship;
  9. counterparty_key matches two spellings of one company across institutions;
 10. but does NOT collapse genuinely different fund vintages (II vs III);
 11. a rerun changes nothing;
 12. the rules CSV is the source of truth — removing a rule changes the output.
"""

import csv
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import derive_counterparties as dc  # noqa: E402
from database import SCHEMA, MIGRATIONS  # noqa: E402

RULES = [
    ("prefix", "RSF", "programme code"),
    ("prefix", "AASF", "programme code"),
    ("suffix", "CREDIT LINE", "product"),
    ("suffix", "RISK SHARING FACILITY", "product"),
    ("legal_suffix", "LIMITED", ""),
    ("legal_suffix", "LTD", ""),
    ("legal_suffix", "S.A.", ""),
    ("legal_suffix", "PLC", ""),
    ("exclude", "VARIOUS", "identifies nobody"),
    ("not_a_prefix", "OTP", "OTP Bank is a real client"),
]

COUNTRIES = [("Kenya", "Kenya", "Sub-Saharan Africa"),
             ("Indonesia", "Indonesia", "East Asia & Pacific")]

# (id, institution, project_name, sponsor)
PROJECTS = [
    (1, "IFC", "Some Project", "Acme Holdings Limited"),   # disclosed
    (2, "FMO", "Acme Holdings Ltd", None),                 # derived, same company
    (3, "EBRD", "RSF - Union Bank", None),                 # dash-separated prefix
    (4, "EBRD", "AASF Fondi Besa", None),                  # space-separated prefix
    (5, "EBRD", "NOA Agribusiness Credit Line", None),     # product suffix
    (6, "EBRD", "OTP Bank Hungary", None),                 # client acronym, keep whole
    (7, "AfDB", "Kenya - Road Rehabilitation Project", None),   # names a project
    (8, "EIB Global", "ISTANBUL-ANKARA RAILWAY", None),         # names an asset
    (9, "DFC", "Republic of Indonesia", None),             # a country, not a company
    (10, "IFC", "Some Project", "International Finance Corporation"),  # self-reference
    (11, "EBRD", "Growth Fund II", None),                  # vintage II
    (12, "FMO", "Growth Fund III", None),                  # vintage III - must NOT merge
    (13, "BII", "VARIOUS", None),                          # excluded
]

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        if detail:
            print(f"          {detail}")
        failures.append(label)


def write_rules(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rule_type", "pattern", "notes"])
        w.writerows(rows)


def write_countries(path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source_country", "canonical_country", "canonical_region"])
        w.writerows(COUNTRIES)


def build_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for table, column, sql_type in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
    for pid, institution, name, sponsor in PROJECTS:
        conn.execute(
            "INSERT INTO projects (id, institution, project_name, sponsor, "
            "source_url, scraped_at) VALUES (?, ?, ?, ?, 'http://x.test', '2026-01-01')",
            (pid, institution, name, sponsor))
    return conn


def cp(conn, pid):
    r = conn.execute("SELECT counterparty, counterparty_key, counterparty_provenance "
                     "FROM projects WHERE id = ?", (pid,)).fetchone()
    return (r[0], r[1], r[2])


def main():
    tmp = Path(tempfile.mkdtemp())
    dc.RULES_CSV = tmp / "counterparty_rules.csv"
    dc.COUNTRY_CSV = tmp / "country_mapping.csv"
    write_rules(dc.RULES_CSV, RULES)
    write_countries(dc.COUNTRY_CSV)

    conn = build_db()
    dc.derive(conn)

    print("\n1. a published sponsor is used verbatim")
    check("IFC kept 'Acme Holdings Limited', marked disclosed",
          cp(conn, 1)[0] == "Acme Holdings Limited"
          and cp(conn, 1)[2] == "disclosed", f"got {cp(conn, 1)}")

    print("\n2. otherwise the project name is cleaned and marked derived")
    check("FMO derived 'Acme Holdings Ltd'",
          cp(conn, 2)[0] == "Acme Holdings Ltd"
          and cp(conn, 2)[2] == "derived_from_project_name", f"got {cp(conn, 2)}")

    print("\n3. institutions whose names are PROJECTS yield nothing")
    check("AfDB derived no counterparty", cp(conn, 7)[0] is None, f"got {cp(conn, 7)}")
    check("EIB Global derived no counterparty", cp(conn, 8)[0] is None,
          f"got {cp(conn, 8)}")

    print("\n4. programme codes are stripped, dash or space separated")
    check("'RSF - Union Bank' -> 'Union Bank'", cp(conn, 3)[0] == "Union Bank",
          f"got {cp(conn, 3)[0]!r}")
    check("'AASF Fondi Besa' -> 'Fondi Besa'", cp(conn, 4)[0] == "Fondi Besa",
          f"got {cp(conn, 4)[0]!r}")

    print("\n5. a leading acronym that is a real CLIENT is left alone")
    check("'OTP Bank Hungary' survives intact", cp(conn, 6)[0] == "OTP Bank Hungary",
          f"got {cp(conn, 6)[0]!r} - a client name was eaten as a programme code")

    print("\n6. trailing product words are stripped")
    check("'NOA Agribusiness Credit Line' -> 'NOA Agribusiness'",
          cp(conn, 5)[0] == "NOA Agribusiness", f"got {cp(conn, 5)[0]!r}")

    print("\n7. a country is not a company")
    check("'Republic of Indonesia' derived nothing", cp(conn, 9)[0] is None,
          f"got {cp(conn, 9)[0]!r}")
    check("an excluded label derived nothing", cp(conn, 13)[0] is None,
          f"got {cp(conn, 13)[0]!r}")

    print("\n8. an institution naming itself is not a client")
    check("IFC's self-reference was dropped", cp(conn, 10)[0] is None,
          f"got {cp(conn, 10)[0]!r}")

    print("\n9. the key matches one company across two institutions")
    check("'Acme Holdings Limited' and 'Acme Holdings Ltd' share a key",
          cp(conn, 1)[1] == cp(conn, 2)[1] and cp(conn, 1)[1],
          f"{cp(conn, 1)[1]!r} vs {cp(conn, 2)[1]!r}")

    print("\n10. but different fund vintages stay apart")
    check("'Growth Fund II' and 'Growth Fund III' do NOT share a key",
          cp(conn, 11)[1] != cp(conn, 12)[1],
          f"both became {cp(conn, 11)[1]!r} - two different funds were merged")

    print("\n11. the run is idempotent")
    def snap():
        return sorted(tuple(r) for r in conn.execute(
            "SELECT id, counterparty, counterparty_key, counterparty_provenance "
            "FROM projects"))
    before = snap()
    dc.derive(conn)
    check("a second run changes nothing", snap() == before)

    print("\n12. the rules CSV is the source of truth")
    write_rules(dc.RULES_CSV, [r for r in RULES if r[1] != "AASF"])
    dc.derive(conn)
    check("removing the AASF rule stops it being stripped",
          cp(conn, 4)[0] == "AASF Fondi Besa", f"got {cp(conn, 4)[0]!r}")
    write_rules(dc.RULES_CSV, RULES)
    dc.derive(conn)
    check("restoring it strips again", cp(conn, 4)[0] == "Fondi Besa")

    if failures:
        print(f"\n{len(failures)} CHECK(S) FAILED: {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
