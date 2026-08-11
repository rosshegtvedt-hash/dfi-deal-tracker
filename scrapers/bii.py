"""
scrapers/bii.py — loads BII (British International Investment, formerly CDC
Group) activities from its IATI publication.

Source: Code for IATI Datastore Classic, serving BII's own IATI data
(reporting org GB-COH-03877777, publisher 'bii' on the IATI Registry).
No API key, no bot protection, refreshed continuously from BII's published
IATI files — nothing to update by hand between runs.

Run:
    python -m scrapers.bii

NOTE: the `stream=True` query parameter is REQUIRED. Without it the API
silently returns only the first 50 rows — a silent truncation, so the
loader asserts a plausible row count before touching the database.

Field mapping (source column -> our schema):
    title                             -> project_name (BII titles are the
                                         investee company / fund name)
    description                       -> description
    recipient-country, else
      recipient-region                -> country (see 'Countries' below)
    sector-code + sector-vocabulary   -> sector (see 'Sectors' below)
    total-Commitment                  -> amount_original
    default-currency                  -> currency (read from the column;
                                         verified USD on all rows, so
                                         amount_usd = amount_original, but
                                         non-USD rows would convert via fx.py)
    start-actual, else start-planned  -> approval_date
    activity-status-code              -> status (IATI ActivityStatus codelist)
    iati-identifier                   -> source_url (d-portal activity page)

IMPORTANT — what this source does NOT contain, left NULL rather than inferred:
  * es_category: IATI's activity CSV has no environmental & social category.
  * instrument: no instrument field. (`default-finance-type-code`, which
    might have served as a proxy, is empty on all 1,258 rows anyway.)
  * sponsor: `participating-org (Implementing)` is EMPTY on every row, and
    `participating-org (Funding)` is BII/CDC itself — the funder, not the
    investee. Putting that in `sponsor` would stamp "British International
    Investment plc" on all 1,258 rows, so sponsor stays NULL. The investee
    name is carried by project_name instead.

AMOUNTS: `total-Commitment` is the activity's LIFETIME commitment total
(the sum of all commitment transactions ever reported for it), not a single
approval amount. It is therefore not exactly comparable to the
single-approval amounts of the other institutions in this database.

COUNTRIES: 334 of 1,258 activities have no recipient-country. Most of those
do disclose a recipient-region (e.g. 'Africa, regional'), so the region
label is used as the country value and country_mapping.csv resolves it to
the same 'Regional — ...' labels used for DFC/IFC/AfDB/ADB regional deals.
Nothing is guessed: every row without a recipient-country is logged to
quality_issues saying which region (if any) stood in for it, and rows with
neither land on 'Undisclosed'.

SECTORS: BII publishes sectors under three different vocabularies, so the
code alone is ambiguous and the vocabulary must be read alongside it:
  * vocabulary 1  (364 rows) — OECD DAC 5-digit purpose codes; names
    resolved from the DAC codelist.
  * vocabulary 2  (43 rows)  — DAC 3-digit category codes; names resolved
    from the SectorCategory codelist.
  * vocabulary 99 (851 rows) — BII's OWN scheme, which is not documented in
    any published codelist. Its codes are 2/4/6/8 digits with GICS
    structure and GICS semantics (551050 on Globeleq/Gridworks; 4010 on NMB
    Bank/Tyme; 302020 on Africa Improved Foods; 15101030 on Indorama
    Fertilizer), so they are labelled with the corresponding GICS names
    below. The identification is ours, not BII's: the raw code is always
    kept in the stored value, and every mapping is reviewable in
    sector_mapping.csv.
"""

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import get_connection, log_quality_issue, utc_now  # noqa: E402
from fx import to_usd  # noqa: E402
from scrapers.iati_common import (  # noqa: E402
    ACTIVITY_STATUS, DATASTORE_URL, UA_HEADER, activity_date, clean,
    download_activity_csv, dportal_url, read_activity_csv, resolve_country,
    snapshot_row)

INSTITUTION = "BII"
REPORTING_ORG = "GB-COH-03877777"
DATA_URL = DATASTORE_URL.format(org=REPORTING_ORG)
CODELIST_URL = "https://codelists.codeforiati.org/api/json/en/{}.json"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"

# GICS names for BII's vocabulary-99 codes (see SECTORS in the docstring).
GICS_NAMES = {
    # Sectors (2-digit) — BII tags fund commitments at this level
    "10": "Energy", "15": "Materials", "20": "Industrials",
    "25": "Consumer Discretionary", "30": "Consumer Staples",
    "35": "Health Care", "40": "Financials",
    "45": "Information Technology", "50": "Communication Services",
    "55": "Utilities", "60": "Real Estate",
    # Industry groups (4-digit)
    "3010": "Consumer Staples Distribution & Retail",
    "4010": "Banks",
    "6020": "Real Estate Management & Development",
    # Industries (6-digit)
    "151010": "Chemicals",
    "151020": "Construction Materials",
    "151050": "Paper & Forest Products",
    "201050": "Industrial Conglomerates",
    "201060": "Machinery",
    "203040": "Ground Transportation",
    "203050": "Transportation Infrastructure",
    "251020": "Automobiles",
    "252030": "Textiles, Apparel & Luxury Goods",
    "253020": "Diversified Consumer Services",
    "302020": "Food Products",
    "303010": "Household Products",
    "351020": "Health Care Providers & Services",
    "351030": "Health Care Technology",
    "352020": "Pharmaceuticals",
    "402020": "Consumer Finance",
    "451020": "IT Services",
    "451030": "Software",
    "452020": "Technology Hardware, Storage & Peripherals",
    "501010": "Diversified Telecommunication Services",
    "501020": "Wireless Telecommunication Services",
    "551010": "Electric Utilities",
    "551040": "Water Utilities",
    "551050": "Independent Power and Renewable Electricity Producers",
    # Sub-industries (8-digit)
    "15101030": "Fertilizers & Agricultural Chemicals",
    "20201050": "Environmental & Facilities Services",
    "20202010": "Human Resource & Employment Services",
    "20304040": "Passenger Ground Transportation",
    "25302010": "Education Services",
    "30202010": "Agricultural Products & Services",
    "40101010": "Diversified Banks",
    "40201020": "Diversified Financial Services",
    "40201040": "Specialized Finance",
    "40201060": "Transaction & Payment Processing Services",
    "55105010": "Independent Power Producers & Energy Traders",
    "55105020": "Renewable Electricity",
}


def download() -> Path:
    return download_activity_csv(REPORTING_ORG, "bii_iati_activities", RAW_DIR)


def fetch_codelist(name: str) -> dict:
    """{code: name} from a Code for IATI codelist; {} if unreachable."""
    try:
        resp = requests.get(CODELIST_URL.format(name), headers=UA_HEADER, timeout=120)
        resp.raise_for_status()
        return {d["code"]: d["name"] for d in resp.json()["data"]}
    except Exception as exc:  # network/format problem -> fall back to bare codes
        print(f"  WARNING: could not fetch {name} codelist ({exc}); "
              "sector codes will be stored without names")
        return {}


def build_sector(code, vocabulary, dac, dac_category):
    """Return (readable_sector_or_None, note_or_None).

    Keeps the raw code in the value so a wrong name is always traceable.
    """
    code = clean(code)
    vocabulary = clean(vocabulary)
    if code is None or code == "0":
        return None, ("sector-code is '0' (source's unclassified placeholder)"
                      if code == "0" else "sector-code missing")

    if vocabulary == "1":
        name = dac.get(code)
        return (f"{code} {name}" if name else f"{code}",
                None if name else f"DAC code {code} not in Sector codelist")
    if vocabulary == "2":
        name = dac_category.get(code)
        return (f"{code} {name}" if name else f"{code}",
                None if name else f"DAC category {code} not in SectorCategory codelist")
    if vocabulary == "99":
        name = GICS_NAMES.get(code)
        return (f"GICS {code} {name}" if name else f"GICS {code}",
                None if name else
                f"BII vocabulary-99 code {code} has no GICS name in this loader")
    return f"{code} (vocabulary {vocabulary})", \
           f"unexpected sector vocabulary {vocabulary!r}"


def load(path: Path) -> None:
    df = read_activity_csv(path)
    dac = fetch_codelist("Sector")
    dac_category = fetch_codelist("SectorCategory")

    conn = get_connection()
    scraped_at = utc_now()
    inserted = issues = 0
    try:
        conn.execute("DELETE FROM projects WHERE institution = ?", (INSTITUTION,))
        conn.execute("DELETE FROM quality_issues WHERE institution = ?", (INSTITUTION,))

        for _, row in df.iterrows():
            raw = snapshot_row(row)
            name = clean(row.get("title"))
            if name is None:
                log_quality_issue(conn, INSTITUTION, None, "missing_project_name",
                                  "title is blank", raw)
                issues += 1

            # --- country: recipient-country, else the disclosed region ------
            country, country_note = resolve_country(row)
            if country_note:
                log_quality_issue(conn, INSTITUTION, name, "missing_country",
                                  country_note, raw)
                issues += 1

            # --- sector -----------------------------------------------------
            sector, sector_note = build_sector(
                row.get("sector-code"), row.get("sector-vocabulary-code"),
                dac, dac_category)
            if sector_note:
                log_quality_issue(conn, INSTITUTION, name, "unresolved_sector_code",
                                  sector_note, raw)
                issues += 1

            # --- date: actual start, else planned ---------------------------
            approval_date = activity_date(row)
            if approval_date is None:
                log_quality_issue(conn, INSTITUTION, name, "unparseable_date",
                                  "neither start-actual nor start-planned given", raw)
                issues += 1

            # --- amount -----------------------------------------------------
            amount = clean(row.get("total-Commitment"))
            currency = clean(row.get("default-currency"))
            amount_usd = None
            if amount is None:
                log_quality_issue(conn, INSTITUTION, name, "missing_amount",
                                  "total-Commitment is blank", raw)
                issues += 1
            else:
                amount = float(amount)
                if amount == 0:
                    log_quality_issue(
                        conn, INSTITUTION, name, "zero_amount",
                        "source reports a lifetime commitment total of 0 — kept as "
                        "disclosed, but almost certainly an unreported amount", raw)
                    issues += 1
                if currency is None:
                    log_quality_issue(conn, INSTITUTION, name, "missing_currency",
                                      f"amount {amount:,.0f} has no default-currency; "
                                      "amount_usd left NULL", raw)
                    issues += 1
                else:
                    year = int(approval_date[:4]) if approval_date else None
                    amount_usd, fx_note = to_usd(amount, currency, year)
                    if fx_note and amount_usd is None:
                        log_quality_issue(conn, INSTITUTION, name, "fx_rate_missing",
                                          fx_note, raw)
                        issues += 1
                    elif fx_note:
                        log_quality_issue(conn, INSTITUTION, name,
                                          "fx_rate_approximated", fx_note, raw)
                        issues += 1

            source_url = dportal_url(clean(row.get("iati-identifier")), DATA_URL)

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
                    country,
                    None,   # region: canonical_region comes from country harmonization
                    sector,
                    None,
                    None,   # instrument: not in IATI's activity CSV
                    amount,
                    currency,
                    amount_usd,
                    approval_date,
                    None,
                    ACTIVITY_STATUS.get(clean(row.get("activity-status-code"))),
                    None,   # es_category: not in IATI's activity CSV
                    None,   # sponsor: see docstring — no investee org published
                    clean(row.get("description")),
                    source_url,
                    scraped_at,
                ),
            )
            inserted += 1

        conn.commit()
    finally:
        conn.close()

    print(f"Inserted {inserted} BII activities ({issues} quality issues logged).")


if __name__ == "__main__":
    load(download())
