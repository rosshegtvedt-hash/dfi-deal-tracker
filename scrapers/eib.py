"""
scrapers/eib.py — loads EIB Global (the European Investment Bank's operations
outside the EU) from EIB's own financed-projects service.

Source: the JSON service behind https://www.eib.org/en/projects/loans/ —
keyless, no bot protection, paginated. Refreshed continuously by EIB, so the
loader fetches it live each run; nothing to update by hand.

Run:
    python -m scrapers.eib

=========================== SCOPE: EIB GLOBAL ONLY =========================
EIB's full book is 29,696 loan parts, of which 22,863 are inside the
European Union — ordinary European infrastructure lending, not development
finance. Loading those would swamp every chart in this tracker.

This loader therefore requests only the eight non-EU regions EIB Global
operates in (REGIONS below), giving ~4,700 loan parts. EFTA countries
(Norway, Switzerland, Iceland, Liechtenstein) are excluded too: high-income
and outside any development mandate.

The institution is stored as 'EIB Global' rather than 'EIB' precisely
because it is a deliberate subset — calling it 'EIB' would misrepresent an
institution whose lending is overwhelmingly European.
============================================================================

GRAIN — one row is a LOAN PART, not a project. EIB publishes each signed
tranche separately, so a project number repeats when it was signed in
tranches: 4,722 loan parts span 3,346 project numbers, and the biggest
(the Global Green Bond Initiative) has 24 tranches across Africa, Asia,
Central Asia and Latin America with different amounts each. Summing rows is
correct — they are separate signatures, not repeated records — but counts of
"deals" are counts of tranches. Verified: the multi-region query does not
duplicate rows, and identical tranches recur inside single-region queries
too, so the repetition is EIB's data rather than an artefact of our request.

Field mapping (service response -> our schema):
    title                              -> project_name
    description                        -> description
    primaryTags[subType=countries]     -> country
    primaryTags[subType=regions]       -> region (EIB's own mandate region)
    primaryTags[subType=sectors]       -> sector
    additionalInformation[0] ('€44,000,000')
                                       -> amount_original, currency EUR,
                                          converted via fx.py on the signature
                                          year
    startDate (epoch ms)               -> approval_date (SIGNATURE date — EIB
                                          publishes no board-approval date)
    id                                 -> source_url
                                          (eib.org/en/projects/loans/all/<id>)

Not published in this service, left NULL rather than inferred: sponsor,
instrument, status, es_category.
"""

import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import get_connection, log_quality_issue, utc_now  # noqa: E402
from fx import to_usd  # noqa: E402

INSTITUTION = "EIB Global"
API_URL = "https://www.eib.org/provider-eib-plr/app/loans/list"
PROJECT_URL = "https://www.eib.org/en/projects/loans/all/{}"
LIST_PAGE = "https://www.eib.org/en/projects/loans/"
UA_HEADER = {"User-Agent": "RCFH-Advisory DFI tracker (contact: rosshegtvedt@gmail.com)"}

# EIB Global's operating regions — everything except the EU and EFTA.
REGIONS = ["eu-enlargement-countries", "western-balkans", "eastern-neighbourhood",
           "southern-neighbourhood", "sub-saharan-africa", "latin-america-caribbean",
           "asia-pacific", "overseas-countries-territories"]

PAGE_SIZE = 1000
DELAY_SECONDS = 1
MIN_EXPECTED_ROWS = 2000  # guard against a truncated/failed fetch

AMOUNT_RE = re.compile(r"^€\s*([\d,]+(?:\.\d+)?)$")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def fetch_all() -> list[dict]:
    """Page through the service for EIB Global's regions."""
    rows, page = [], 0
    while True:
        params = [("sortColumn", "loanParts.loanPartStatus.statusDate"),
                  ("sortDir", "desc"), ("pageable", "true"),
                  ("language", "EN"), ("defaultLanguage", "EN"),
                  ("pageNumber", page), ("itemPerPage", PAGE_SIZE),
                  ("orCountries.region", "true"),
                  *[("countries.region", r) for r in REGIONS]]
        resp = requests.get(API_URL, headers=UA_HEADER, timeout=300, params=params)
        resp.raise_for_status()
        payload = resp.json()
        batch = payload.get("data") or []
        if not batch:
            break
        rows.extend(batch)
        print(f"  fetched {len(rows)}/{payload.get('totalItems', '?')} loan parts...")
        page += 1
        time.sleep(DELAY_SECONDS)
    return rows


def clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return None if value in ("", "None", "null") else value


def tag_label(row, subtype):
    """First primaryTag of the given subType, e.g. 'countries' -> 'Kenya'."""
    for tag in row.get("primaryTags") or []:
        if tag.get("subType") == subtype:
            return clean(tag.get("label"))
    return None


def parse_amount(value):
    """'€44,000,000' -> (44000000.0, None). Anything else -> (None, note)."""
    value = clean(value)
    if value is None:
        return None, "signed amount is blank"
    match = AMOUNT_RE.match(value)
    if not match:
        return None, (f"signed amount {value!r} is not a plain euro figure; "
                      "amount left NULL rather than guessed")
    return float(match.group(1).replace(",", "")), None


def parse_epoch_ms(value):
    """Epoch milliseconds -> ISO date. Handles pre-1970 (negative) values,
    which datetime.fromtimestamp cannot represent on Windows."""
    if value in (None, ""):
        return None, "no signature date given"
    try:
        return (EPOCH + timedelta(milliseconds=int(value))).date().isoformat(), None
    except (TypeError, ValueError, OverflowError):
        return None, f"unparseable signature date {value!r}"


def load(rows) -> None:
    if len(rows) < MIN_EXPECTED_ROWS:
        raise SystemExit(
            f"Only {len(rows)} loan parts returned — the service response looks "
            "truncated or the region filter changed. Refusing to load; check the "
            "API before rerunning.")
    print(f"{len(rows)} loan parts across "
          f"{len({r.get('id') for r in rows})} project numbers")

    # Exactly-identical tranches can't be told apart from a repeated record, so
    # they are loaded as disclosed and flagged once each.
    def signature(row):
        return (row.get("id"), (row.get("additionalInformation") or [None])[0],
                row.get("startDate"), tag_label(row, "countries"))

    repeated = {sig for sig, n in Counter(signature(r) for r in rows).items() if n > 1}

    conn = get_connection()
    scraped_at = utc_now()
    inserted = issues = 0
    flagged_signatures = set()
    try:
        conn.execute("DELETE FROM projects WHERE institution = ?", (INSTITUTION,))
        conn.execute("DELETE FROM quality_issues WHERE institution = ?", (INSTITUTION,))

        for row in rows:
            raw = {k: (str(v)[:300] if v is not None else None) for k, v in row.items()}
            name = clean(row.get("title"))
            if name is None:
                log_quality_issue(conn, INSTITUTION, None, "missing_project_name",
                                  "title is blank", raw)
                issues += 1

            description = clean(row.get("description"))
            if description is None:
                log_quality_issue(conn, INSTITUTION, name, "missing_description",
                                  "no project description published", raw)
                issues += 1

            approval_date, date_note = parse_epoch_ms(row.get("startDate"))
            if date_note:
                log_quality_issue(conn, INSTITUTION, name, "unparseable_date",
                                  date_note, raw)
                issues += 1

            info = row.get("additionalInformation") or []
            amount, amount_note = parse_amount(info[0] if info else None)
            amount_usd = None
            if amount_note:
                log_quality_issue(conn, INSTITUTION, name, "missing_amount",
                                  amount_note, raw)
                issues += 1
            else:
                year = int(approval_date[:4]) if approval_date else None
                amount_usd, fx_note = to_usd(amount, "EUR", year)
                if fx_note and amount_usd is None:
                    log_quality_issue(conn, INSTITUTION, name, "fx_rate_missing",
                                      fx_note, raw)
                    issues += 1
                elif fx_note:
                    log_quality_issue(conn, INSTITUTION, name, "fx_rate_approximated",
                                      fx_note, raw)
                    issues += 1

            sig = signature(row)
            if sig in repeated and sig not in flagged_signatures:
                flagged_signatures.add(sig)
                log_quality_issue(
                    conn, INSTITUTION, name, "identical_loan_parts",
                    f"project {row.get('id')} has more than one loan part with the "
                    "same amount, date and country; all are loaded as disclosed "
                    "because EIB publishes no tranche identifier to tell a genuine "
                    "repeat signature from a duplicated record", raw)
                issues += 1

            identifier = clean(row.get("id"))
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
                    tag_label(row, "countries"),
                    tag_label(row, "regions"),   # EIB's own mandate region
                    tag_label(row, "sectors"),
                    None,
                    None,   # instrument: not published in this service
                    amount,
                    "EUR" if amount is not None else None,
                    amount_usd,
                    approval_date,
                    None,
                    None,   # status: not published in this service
                    None,   # es_category: not published in this service
                    None,   # sponsor: not published in this service
                    description,
                    PROJECT_URL.format(identifier) if identifier else LIST_PAGE,
                    scraped_at,
                ),
            )
            inserted += 1

        conn.commit()
    finally:
        conn.close()

    print(f"Inserted {inserted} EIB Global loan parts ({issues} quality issues logged).")


if __name__ == "__main__":
    print(f"Fetching EIB Global loan parts from {LIST_PAGE}")
    load(fetch_all())
