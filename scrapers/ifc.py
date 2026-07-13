"""
scrapers/ifc.py — loads IFC investment projects from the World Bank Group's
official open-data API.

Source: "IFC Investment Services Projects" dataset (DS00499) on WBG Finances One,
https://financesone.worldbank.org/ifc-investment-services-projects/DS00499
Updated daily, licensed CC-BY — an official machine-readable feed, so this is
the robust choice over scraping IFC's JavaScript disclosure portal. The API
serves at most 1,000 records per request; we paginate with a polite 1-second
delay between pages.

Run:
    python -m scrapers.ifc

Field mapping (API field -> our schema):
    project_name                                      -> project_name
    company_name                                      -> sponsor
    country                                           -> country
    industry                                          -> sector
    product_line                                      -> instrument
    total_ifc_investment_as_approved_by_boardmillion__usd
        (in USD MILLIONS; fallback: sum of the loan/equity/guarantee/
         risk-management component fields)            -> amount_* (x 1,000,000)
    ifc_approval_date ('13-Jul-2000')                 -> approval_date (ISO)
    status                                            -> status
    environmental_category                            -> es_category
    project_url                                       -> source_url

Notes:
  * All IFC amounts are USD, so currency='USD' and amount_original=amount_usd.
  * ~17 projects appear twice (disclosed under both the 2006 Disclosure Policy
    and the 2012 Access-to-Information Policy). We keep the most recently
    disclosed record per project_number and log each collapsed duplicate to
    quality_issues — visible, never silent.
  * The dataset has no region or description fields; those stay NULL.
  * Umbrella trade-finance programs (GTFP, GTSF, GSCF) list every partner
    bank as its own record but stamp each with the PROGRAM-level envelope
    (e.g. $7,000M on 55 GTFP records) — which would wildly inflate country
    totals. The partner-bank participation size is not disclosed, so those
    amounts are set to NULL and logged as 'program_envelope_amount' issues
    (original value preserved in the log). The program-level record itself,
    booked to 'World Region', keeps the envelope amount.
"""

import json
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import get_connection, log_quality_issue, utc_now  # noqa: E402

INSTITUTION = "IFC"
API_URL = "https://datacatalogapi.worldbank.org/dexapps/fone/api/apiservice"
DATASET_PARAMS = {"datasetId": "DS00499", "resourceId": "RS00448", "type": "json"}
DATASET_PAGE = "https://financesone.worldbank.org/ifc-investment-services-projects/DS00499"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
PAGE_SIZE = 1000
DELAY_SECONDS = 1

AMOUNT_COMPONENT_FIELDS = [
    "ifc_investment_for_loanmillion__usd",
    "ifc_investment_for_equitymillion__usd",
    "ifc_investment_for_guaranteemillion__usd",
    "ifc_investment_for_risk_managementmillion__usd",
]


def fetch_all() -> list[dict]:
    """Page through the API until exhausted; archive the raw JSON in data/raw/."""
    rows, skip = [], 0
    while True:
        params = {**DATASET_PARAMS, "top": PAGE_SIZE, "skip": skip}
        resp = requests.get(
            API_URL, params=params, timeout=120,
            headers={"User-Agent": "RCFH-Advisory DFI tracker (contact: rosshegtvedt@gmail.com)"},
        )
        resp.raise_for_status()
        batch = resp.json()["data"]
        if not batch:
            break
        rows.extend(batch)
        print(f"  fetched {len(rows)} records...")
        skip += PAGE_SIZE
        time.sleep(DELAY_SECONDS)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    archive = RAW_DIR / f"ifc_projects_{date.today().isoformat()}.json"
    archive.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"Archived raw JSON to {archive.name}")
    return rows


def parse_api_date(value):
    """API dates look like '13-Jul-2000'. Return (iso_date_or_None, error_or_None)."""
    if not value or not str(value).strip():
        return None, "missing"
    try:
        return datetime.strptime(str(value).strip(), "%d-%b-%Y").date().isoformat(), None
    except ValueError:
        return None, f"unparseable value: {value!r}"


def parse_amount_usd(row):
    """Return (amount_in_plain_usd_or_None, error_or_None).

    Prefers the board-approved total; falls back to summing the per-product
    component fields when the total is absent.
    """
    total = row.get("total_ifc_investment_as_approved_by_boardmillion__usd")
    if total is not None:
        return float(total) * 1_000_000, None
    components = [row.get(f) for f in AMOUNT_COMPONENT_FIELDS if row.get(f) is not None]
    if components:
        return float(sum(components)) * 1_000_000, None
    return None, "board-approved total and all component amounts missing"


def dedupe_disclosures(rows, conn):
    """Keep one record per project_number (the most recently disclosed)."""
    by_number = {}
    for row in rows:
        key = row.get("project_number")
        prev = by_number.get(key)
        if prev is None:
            by_number[key] = row
            continue
        # Same project disclosed twice (2006 policy + 2012 policy documents).
        prev_date, _ = parse_api_date(prev.get("date_disclosed"))
        this_date, _ = parse_api_date(row.get("date_disclosed"))
        keep, drop = (row, prev) if (this_date or "") >= (prev_date or "") else (prev, row)
        by_number[key] = keep
        log_quality_issue(
            conn, INSTITUTION, keep.get("project_name"), "duplicate_disclosure_collapsed",
            f"Project {key} has two disclosure records; kept the one disclosed "
            f"{keep.get('date_disclosed')} ({keep.get('document_type')}), collapsed the one "
            f"disclosed {drop.get('date_disclosed')} ({drop.get('document_type')})",
            drop,
        )
    return list(by_number.values())


def clean(value):
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


# Three or more records sharing an identical approval date AND an identical
# amount of $500M+ is the signature of an umbrella program's envelope stamped
# onto its partner-bank records (verified: no legitimate IFC deal pattern
# matches this in the dataset).
ENVELOPE_MIN_USD = 500_000_000
ENVELOPE_MIN_COUNT = 3


def flag_program_envelopes(records, conn):
    """NULL out program-envelope amounts on partner-bank records; log each."""
    groups = defaultdict(list)
    for rec in records:
        if rec["amount"] and rec["amount"] >= ENVELOPE_MIN_USD and rec["approval_date"]:
            groups[(rec["approval_date"], rec["amount"])].append(rec)

    nulled = 0
    for (approved, amount), members in groups.items():
        if len(members) < ENVELOPE_MIN_COUNT:
            continue
        for rec in members:
            if (rec["country"] or "").strip().lower() == "world region":
                continue  # the program-level record legitimately keeps the envelope
            log_quality_issue(
                conn, INSTITUTION, rec["name"], "program_envelope_amount",
                f"Amount ${amount:,.0f} appears identically on {len(members)} records "
                f"approved {approved} — this is the program-level envelope, not this "
                f"participation's own size, so amount is set to NULL", rec["raw"],
            )
            rec["amount"] = None
            nulled += 1
    return nulled


def load(rows) -> None:
    conn = get_connection()
    scraped_at = utc_now()
    inserted = issues = 0
    try:
        conn.execute("DELETE FROM projects WHERE institution = ?", (INSTITUTION,))
        conn.execute("DELETE FROM quality_issues WHERE institution = ?", (INSTITUTION,))

        unique_rows = dedupe_disclosures(rows, conn)
        collapsed = len(rows) - len(unique_rows)

        # First pass: parse the fields that envelope detection needs.
        records = []
        for row in unique_rows:
            amount, amount_err = parse_amount_usd(row)
            approval_date, date_err = parse_api_date(row.get("ifc_approval_date"))
            records.append({
                "raw": row,
                "name": clean(row.get("project_name")),
                "country": clean(row.get("country")),
                "amount": amount, "amount_err": amount_err,
                "approval_date": approval_date, "date_err": date_err,
            })

        enveloped = flag_program_envelopes(records, conn)
        issues += enveloped

        for rec in records:
            row, name = rec["raw"], rec["name"]
            amount, approval_date = rec["amount"], rec["approval_date"]

            if rec["amount_err"]:
                log_quality_issue(conn, INSTITUTION, name, "missing_amount",
                                  rec["amount_err"], row)
                issues += 1

            if rec["date_err"]:
                log_quality_issue(conn, INSTITUTION, name, "unparseable_date",
                                  f"ifc_approval_date {rec['date_err']}", row)
                issues += 1

            if name is None:
                log_quality_issue(conn, INSTITUTION, None, "missing_project_name",
                                  "project_name is blank", row)
                issues += 1

            conn.execute(
                """INSERT INTO projects
                   (institution, project_name, country, region, sector, subsector,
                    instrument, amount_original, currency, amount_usd,
                    approval_date, fiscal_year, status, es_category, sponsor,
                    description, source_url, scraped_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    INSTITUTION,
                    name,
                    clean(row.get("country")),
                    None,  # region: not in this dataset
                    clean(row.get("industry")),
                    None,  # subsector: not disclosed
                    clean(row.get("product_line")),
                    amount,
                    "USD" if amount is not None else None,
                    amount,
                    approval_date,
                    None,  # fiscal_year: exact approval_date is available instead
                    clean(row.get("status")),
                    clean(row.get("environmental_category")),
                    clean(row.get("company_name")),
                    None,  # description: not in this dataset
                    clean(row.get("project_url")) or DATASET_PAGE,
                    scraped_at,
                ),
            )
            inserted += 1

        conn.commit()
    finally:
        conn.close()

    print(f"Inserted {inserted} IFC projects "
          f"({collapsed} duplicate disclosure record(s) collapsed and logged, "
          f"{issues} quality issues logged).")


if __name__ == "__main__":
    print(f"Fetching IFC projects from {DATASET_PAGE}")
    load(fetch_all())
