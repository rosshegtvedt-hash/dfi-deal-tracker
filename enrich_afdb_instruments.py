"""
enrich_afdb_instruments.py — recovers AfDB's instrument from its IATI feed.

Run after scrapers.afdb, before harmonize.py:
    python enrich_afdb_instruments.py

Why this exists
---------------
AfDB's MapAfrica bulk export — the file `scrapers/afdb.py` reads — has no
instrument column at all, so all 5,949 AfDB rows carry no instrument. But AfDB
also publishes the same projects to IATI, where the finance type IS stated.

This is NOT third-party data: it is the same institution disclosing the same
projects through a second channel. It is still kept apart from
`projects.instrument`, which by rule holds only what the source we loaded
published, and lands in `projects.instrument_enriched` instead. The canonical
values harmonize.py derives from it are tagged `provenance='iati_enrichment'`
in project_instruments, so any chart can tell the two apart.

The join is exact, not fuzzy
----------------------------
Both sides carry AfDB's own project code:

    ours   https://mapafrica.afdb.org/en/projects/46002-P-MG-FA0-023
    theirs 46002-P-MG-FA0-023   (the iati-identifier)

So this matches on an identifier, never on a project title. That matters —
title matching is what produced the Dominica / Dominican Republic class of bug
this project has already been bitten by.

What is deliberately NOT done here
----------------------------------
* No row is created, deleted or renamed. This only ever fills one column.
* An AfDB project with no IATI counterpart is left NULL and logged, never
  guessed from a similar project.
* A finance type this file has not seen before is loaded verbatim and left for
  instrument_mapping.csv to decide on; it is not bucketed by resemblance.
* ADB was checked the same way and REJECTED: its IATI feed is current and does
  contain our projects, but nothing in it reliably distinguishes ADB's
  nonsovereign book from its sovereign lending, and a flow-type/finance-type
  filter would have swept in roughly 1,400 activities to capture ~325 real
  ones. EIB Global was rejected too — only 21% of our loan parts appear, and
  its feed stops in 2025 while our existing source runs to 2026.
"""

import csv
import io
import json
import re
import sys
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection, log_quality_issue

INSTITUTION = "AfDB"
REPORTING_ORG = "XM-DAC-46002"
DATA_URL = "https://datastore.codeforiati.org/api/1/access/activity.csv"
RAW_DIR = Path(__file__).parent / "data" / "raw"

# AfDB project codes look like 46002-P-MG-FA0-023 on both sides of the join.
# The leading 46002 is AfDB's own DAC number and is part of the code.
CODE_RE = re.compile(r"46002-[A-Z]-[A-Z0-9]{2}-[A-Z0-9]{3}-[A-Z0-9]{3}")

TIMEOUT = 300

# AfDB populates the finance-type CODE but leaves the accompanying name blank,
# so these come from the IATI FinanceType codelist itself
# (codelists.codeforiati.org/api/json/en/FinanceType.json, read 2026-08-19).
# Naming them here keeps instrument_mapping.csv readable: a row saying
# "421 Standard loan" can be reviewed by a human, "421" cannot.
#
# A code that is NOT in this dict is stored as the bare number and will surface
# as an unmapped label in harmonize.py — which is the correct prompt to go and
# look it up, rather than to guess from the number.
FINANCE_TYPE_NAMES = {
    "110": "Standard grant",
    "421": "Standard loan",
    "912": "Purchase of securities from issuing agencies",
}


def fetch_iati_rows():
    """Download AfDB's IATI activity export and archive it date-stamped."""
    print(f"Fetching {REPORTING_ORG} from the Code for IATI datastore")
    resp = requests.get(DATA_URL,
                        params={"stream": "True", "reporting-org": REPORTING_ORG},
                        timeout=TIMEOUT)
    resp.raise_for_status()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    archive = RAW_DIR / f"afdb_iati_activities_{date.today().isoformat()}.csv"
    archive.write_text(resp.text, encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    print(f"  {len(rows)} activities, archived to {archive.name}")
    return rows


def build_finance_type_index(rows):
    """{project code: 'code name'} for activities that state a finance type.

    An activity with no finance type is simply absent from the index — the
    project then keeps a NULL instrument, which is the truthful outcome.
    """
    index, unstated, no_code = {}, 0, 0
    for row in rows:
        match = CODE_RE.search(row.get("iati-identifier") or "")
        if not match:
            no_code += 1
            continue
        code = (row.get("default-finance-type-code") or "").strip()
        name = ((row.get("default-finance-type") or "").strip()
                or FINANCE_TYPE_NAMES.get(code, ""))
        if not code:
            unstated += 1
            continue
        # Stored as "421 Standard loan" rather than a bare number so the rows
        # this produces in instrument_mapping.csv are readable by a human.
        index[match.group(0)] = f"{code} {name}".strip()
    return index, unstated, no_code


def main():
    rows = fetch_iati_rows()
    index, unstated, no_code = build_finance_type_index(rows)
    print(f"  {len(index)} activities state a finance type; "
          f"{unstated} state none; {no_code} carry no AfDB project code")

    conn = get_connection()

    # Own exactly one column and this run's own issues, nothing else.
    conn.execute("UPDATE projects SET instrument_enriched = NULL WHERE institution = ?",
                 (INSTITUTION,))
    for issue in ("afdb_instrument_enriched", "afdb_no_iati_match"):
        conn.execute("DELETE FROM quality_issues WHERE issue_type = ?", (issue,))

    matched, unmatched, no_url_code = 0, [], 0
    counts: dict = {}
    for row in conn.execute(
            "SELECT id, project_name, source_url FROM projects WHERE institution = ?",
            (INSTITUTION,)).fetchall():
        match = CODE_RE.search(row["source_url"] or "")
        if not match:
            no_url_code += 1
            continue
        value = index.get(match.group(0))
        if value is None:
            unmatched.append(row["project_name"])
            continue
        conn.execute("UPDATE projects SET instrument_enriched = ? WHERE id = ?",
                     (value, row["id"]))
        counts[value] = counts.get(value, 0) + 1
        matched += 1

    log_quality_issue(
        conn, INSTITUTION, None, "afdb_instrument_enriched",
        f"Instrument recovered for {matched} AfDB projects from AfDB's own IATI "
        f"publication ({REPORTING_ORG}), joined on the AfDB project code. "
        "MapAfrica, the source these rows are loaded from, publishes no "
        "instrument column. Values live in projects.instrument_enriched, never "
        "in projects.instrument, and the canonical values derived from them "
        "carry provenance='iati_enrichment'.",
        raw_row={"finance_types": counts})

    if unmatched:
        log_quality_issue(
            conn, INSTITUTION, None, "afdb_no_iati_match",
            f"{len(unmatched)} AfDB projects have no activity with a stated "
            "finance type in AfDB's IATI publication, so their instrument stays "
            "NULL. Not inferred from similar projects.",
            raw_row={"examples": unmatched[:20]})

    conn.commit()
    conn.close()

    print(f"\nEnriched {matched} of {matched + len(unmatched) + no_url_code} AfDB projects.")
    for value, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>5}  {value}")
    if unmatched:
        print(f"  {len(unmatched):>5}  (no IATI activity with a stated finance type)")
    if no_url_code:
        print(f"  {no_url_code:>5}  (no AfDB project code in our source_url)")
    print("\nNow run: python harmonize.py")


if __name__ == "__main__":
    main()
