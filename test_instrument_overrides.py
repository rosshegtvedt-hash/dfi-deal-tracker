"""test_instrument_overrides.py — proves the per-deal instrument overrides behave.

Run:
    python test_instrument_overrides.py

A third sibling to test_instruments.py and test_es_categories.py. The override
layer is its own mechanism and gets its own file: it is keyed on source_url
rather than a raw label, it REPLACES what the label mapping concluded instead
of adding to it, and it is the only mapping input that can stop the run.

Builds a throwaway in-memory database and throwaway CSVs, so it never reads or
writes the real tracker. Exits non-zero if any check fails.

Checks:
  1. an override fills in a deal whose label mapped to nothing;
  2. capitalisation is forgiven ("Senior Debt" -> "Senior debt") but an
     unrecognised value STOPS the run rather than minting a sixth instrument;
  3. a blank override is silent — nothing written, nothing logged;
  4. one override can write several canonical values;
  5. overriding a value the label mapping already produced replaces it AND
     logs 'instrument_overridden', so it never happens quietly;
  6. an override whose URL matches no project logs 'stale_instrument_override';
  7. the key is (institution, source_url) — the same URL under a different
     institution is untouched;
  8. the key is NOT projects.id: after a reload hands out different ids, the
     overrides still land on the right deals;
  9. a rerun changes nothing;
 10. removing a row from the CSV reverts that deal to the label mapping.
"""

import csv
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import harmonize  # noqa: E402
from database import SCHEMA  # noqa: E402

URL = "https://example.test/projects/"

MAP_ROWS = [
    ("IDB Invest", "Loan", "Senior debt", ""),
    ("IDB Invest", "Not Specified", "", "declines to state the instrument"),
    # IFC's collision project must map to something OTHER than what the
    # IDB Invest override writes, or a URL-only key would be invisible here.
    ("IFC", "Equity", "Equity", ""),
]

OVERRIDE_ROWS = [
    # institution, source_url, canonical, notes
    ("IDB Invest", URL + "alpha", "Senior Debt", "wrong case on purpose"),
    ("IDB Invest", URL + "beta", "", "reviewed, deliberately unmapped"),
    ("IDB Invest", URL + "gamma", "Equity", "contradicts the label mapping"),
    ("IDB Invest", URL + "delta", "Senior debt", "one of two"),
    ("IDB Invest", URL + "delta", "Equity", "two of two"),
    ("IDB Invest", URL + "eta", "", "reviewed: the label is wrong for this deal"),
    ("IDB Invest", URL + "zeta", "Equity", "no project carries this URL"),
]

# (id, institution, instrument, url_suffix)
PROJECTS = [
    (1, "IDB Invest", "Not Specified", "alpha"),    # -> Senior debt by override
    (2, "IDB Invest", "Not Specified", "beta"),     # -> blank on an unmapped deal
    (3, "IDB Invest", "Loan", "gamma"),             # -> Senior debt, overridden to Equity
    (4, "IDB Invest", "Not Specified", "delta"),    # -> two canonical values
    (5, "IDB Invest", "Loan", "epsilon"),           # -> untouched by any override
    (6, "IFC", "Equity", "alpha"),                  # -> same URL, other institution
    (7, "IDB Invest", "Loan", "eta"),               # -> blank override CLEARS a mapped value
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
        w.writerow(["institution", "raw_instrument", "canonical_instrument", "notes"])
        w.writerows(rows)


def write_overrides(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["institution", "source_url", "canonical_instrument", "notes"])
        w.writerows(rows)


def build_db(projects=PROJECTS):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for pid, institution, instrument, suffix in projects:
        conn.execute(
            "INSERT INTO projects (id, institution, instrument, source_url, "
            "scraped_at) VALUES (?, ?, ?, ?, '2026-01-01')",
            (pid, institution, instrument, URL + suffix))
    return conn


def instruments_for(conn, url, institution="IDB Invest"):
    return [r[0] for r in conn.execute(
        "SELECT pi.canonical_instrument FROM project_instruments pi "
        "JOIN projects p ON p.id = pi.project_id "
        "WHERE p.source_url = ? AND p.institution = ? "
        "ORDER BY pi.canonical_instrument", (url, institution)).fetchall()]


def issues(conn, issue_type):
    return conn.execute("SELECT COUNT(*) FROM quality_issues WHERE issue_type = ?",
                        (issue_type,)).fetchone()[0]


def run(conn):
    harmonize.harmonize_instruments(conn)
    return harmonize.apply_instrument_overrides(conn)


def main():
    tmp = Path(tempfile.mkdtemp())
    harmonize.INSTRUMENT_CSV = tmp / "instrument_mapping.csv"
    harmonize.INSTRUMENT_OVERRIDE_CSV = tmp / "instrument_overrides.csv"
    write_map(harmonize.INSTRUMENT_CSV, MAP_ROWS)
    write_overrides(harmonize.INSTRUMENT_OVERRIDE_CSV, OVERRIDE_ROWS)

    conn = build_db()
    changed, replaced, stale = run(conn)

    print("\n1. an override fills a deal the label mapping left empty")
    check("'Not Specified' + override -> Senior debt",
          instruments_for(conn, URL + "alpha") == ["Senior debt"],
          f"got {instruments_for(conn, URL + 'alpha')}")

    print("\n2. case is forgiven, an unknown value is not")
    check("'Senior Debt' was normalised to 'Senior debt'",
          instruments_for(conn, URL + "alpha") == ["Senior debt"])
    write_overrides(harmonize.INSTRUMENT_OVERRIDE_CSV,
                    OVERRIDE_ROWS + [("IDB Invest", URL + "alpha", "Mezzanine", "")])
    raised = False
    try:
        harmonize.read_instrument_overrides()
    except ValueError as exc:
        raised = "Mezzanine" in str(exc)
    check("an unrecognised instrument stops the run", raised,
          "read_instrument_overrides() accepted a value outside the vocabulary")
    write_overrides(harmonize.INSTRUMENT_OVERRIDE_CSV, OVERRIDE_ROWS)

    print("\n3. a blank override is silent on a deal that mapped to nothing")
    check("blank wrote no instrument", instruments_for(conn, URL + "beta") == [],
          f"got {instruments_for(conn, URL + 'beta')}")
    check("blank on an unmapped deal reported nothing",
          URL + "beta" not in [u for _, u, _, _ in replaced],
          f"replaced: {replaced}")

    print("\n4. one override can carry several canonical values")
    check("'delta' got both Senior debt and Equity",
          instruments_for(conn, URL + "delta") == ["Equity", "Senior debt"],
          f"got {instruments_for(conn, URL + 'delta')}")

    print("\n5. overriding a mapped value replaces it, loudly")
    check("'gamma' is now Equity, not Senior debt",
          instruments_for(conn, URL + "gamma") == ["Equity"],
          f"got {instruments_for(conn, URL + 'gamma')}")
    check("a BLANK override CLEARS a value the label mapping produced",
          instruments_for(conn, URL + "eta") == [],
          f"got {instruments_for(conn, URL + 'eta')} - 'Loan' mapped to Senior "
          "debt and the blank override did not clear it")
    check("both replacements were reported, and only those two",
          sorted(u for _, u, _, _ in replaced) == [URL + "eta", URL + "gamma"],
          f"replaced: {replaced}")
    check("and both were logged as 'instrument_overridden'",
          issues(conn, "instrument_overridden") == 2,
          f"logged: {issues(conn, 'instrument_overridden')}")

    print("\n6. an override matching no project is reported")
    check("'zeta' was flagged stale", [u for _, u in stale] == [URL + "zeta"],
          f"stale: {stale}")
    check("and logged as 'stale_instrument_override'",
          issues(conn, "stale_instrument_override") == 1)

    print("\n7. the key includes the institution, not just the URL")
    check("IFC's project at the same URL kept Equity, not the override",
          instruments_for(conn, URL + "alpha", "IFC") == ["Equity"],
          f"got {instruments_for(conn, URL + 'alpha', 'IFC')} - the IDB Invest "
          "override reached across institutions")
    check("a deal with no override keeps its label mapping",
          instruments_for(conn, URL + "epsilon") == ["Senior debt"])

    print("\n8. the key is the URL, NOT projects.id")
    idb = [p for p in PROJECTS if p[1] == "IDB Invest"]
    before = {s: instruments_for(conn, URL + s) for _, _, _, s in idb}
    # Simulate a reload: same deals, brand-new ids, inserted in another order.
    reloaded = [(100 + i, inst, instrument, suffix)
                for i, (_, inst, instrument, suffix) in enumerate(reversed(PROJECTS))]
    conn2 = build_db(reloaded)
    run(conn2)
    after = {s: instruments_for(conn2, URL + s) for _, _, _, s in idb}
    check("every deal kept its instrument after ids were reassigned",
          before == after, f"before={before}\n          after={after}")

    print("\n9. the run is idempotent")
    def snapshot_of(c):
        return sorted(tuple(r) for r in c.execute(
            "SELECT p.source_url, p.institution, pi.canonical_instrument "
            "FROM project_instruments pi JOIN projects p ON p.id = pi.project_id"))

    snapshot = snapshot_of(conn)
    run(conn)
    check("a second run changes nothing", snapshot_of(conn) == snapshot)

    print("\n10. the CSV is the source of truth")
    write_overrides(harmonize.INSTRUMENT_OVERRIDE_CSV,
                    [r for r in OVERRIDE_ROWS if not r[1].endswith("gamma")])
    run(conn)
    check("dropping the override reverts the deal to its label mapping",
          instruments_for(conn, URL + "gamma") == ["Senior debt"],
          f"got {instruments_for(conn, URL + 'gamma')} - the override did not clear")
    check("and that override is no longer reported as a replacement",
          issues(conn, "instrument_overridden") == 1,
          "only the 'eta' override should remain, got "
          f"{issues(conn, 'instrument_overridden')}")

    print(f"\ndeals set by override on the first run: {changed}")
    if failures:
        print(f"\n{len(failures)} CHECK(S) FAILED: {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
