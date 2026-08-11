"""
scrapers/fmo.py — loads FMO (Nederlandse Financierings-Maatschappij voor
Ontwikkelingslanden) activities from its IATI publication.

Source: FMO's IATI data (reporting org NL-KVK-27078545) via the Code for
IATI Datastore Classic. No API key; refreshed continuously; nothing to
update by hand. Shares its fetching/date/country plumbing with
scrapers/bii.py via scrapers/iati_common.py.

Run:
    python -m scrapers.fmo

=============================== READ THIS ==================================
WHAT THIS PUBLICATION ACTUALLY COVERS — it is NOT FMO's own investment book.

Every one of the 1,294 activities names the *Ministry of Foreign Affairs of
the Netherlands* as the funding organisation, and the activity titles group
into the Dutch government funds FMO manages on the state's behalf:
MASSIF (826), Building Prospects (295), AEF-I (139), Mobilizing Finance for
Forests (20), LUF (13) and DFCD (1). FMO's own ~EUR 12bn balance-sheet
portfolio is NOT in this feed — it is published separately on fmo.nl.

Two consequences worth keeping in mind before quoting these numbers:
  * The implementing organisations are frequently advisers and rating
    agencies (Accion, MicroFinanza Rating, Value for Women, Niras, Frankfurt
    School), i.e. many rows are technical-assistance and consultancy
    contracts rather than investments.
  * The recipient countries are led by the United States, the Netherlands,
    Mauritius, the UK and Luxembourg — fund domiciles and contracting
    locations, not investment destinations.
Treat this institution as "Dutch government funds managed by FMO", and see
data_dictionary.md before using it in published comparisons.
============================================================================

Field mapping (source column -> our schema):
    title                             -> project_name (see title note below)
    description_general               -> description (see description note)
    recipient-country, else
      recipient-region                -> country
    sector-code + sector              -> sector (names populated on all rows)
    total-Commitment                  -> amount_original
    currency  (NOT default-currency)  -> currency (see the currency note)
    start-actual                      -> approval_date (activity start; IATI
                                         publishes no board-approval date)
    activity-status-code              -> status
    participating-org (Implementing)  -> sponsor
    iati-identifier                   -> source_url (d-portal activity page)

CURRENCY — the one thing that must not be taken at face value here.
`default-currency` says EUR on all 1,294 rows, but the amounts are NOT all
euros: the per-transaction `currency` column reports 39 different currencies
(EUR 653, USD 507, then INR, KES, XOF, BDT, VND, KHR, UZS, TZS, UGX and
more). Trusting `default-currency` would read 38.2 billion Vietnamese dong
as EUR 38.2 billion and inflate the whole database by ~USD 170bn — the raw
column sums to EUR 155.94bn against a real programme size two orders of
magnitude smaller. This loader therefore reads the per-transaction
`currency` column and converts with fx.py.

The Datastore's own `total-Commitment-USD` column is no help: it is a
pass-through that equals the raw amount for rows already in USD and is 0 for
every non-USD row, so it cannot be used as a conversion source either.

fx_rates.csv covers EUR, GBP, MXN, BRL and XDR, so EUR/USD/GBP/MXN rows
convert and the ~130 rows in currencies we hold no rate for keep their
amount_original but get amount_usd = NULL plus a logged 'fx_rate_missing'
issue — the same treatment IDB Invest's COP/PEN deals get.

TITLES: 3 in 4 titles are internal fund identifiers ("MASSIF-P00015696-001")
rather than project names. They are loaded verbatim and flagged as
'title_is_internal_identifier'; nothing is prettified or invented.

DESCRIPTIONS: the export's `description` column is the literal string "1" on
all 1,294 rows (a broken field in the publication) and is ignored entirely.
Real text lives in `description_general`, where the placeholder "Description
not provided" is stored as NULL and logged rather than saved as content.

NOT PUBLISHED, left NULL rather than inferred: es_category, instrument.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import get_connection, log_quality_issue, utc_now  # noqa: E402
from fx import to_usd  # noqa: E402
from scrapers.iati_common import (  # noqa: E402
    ACTIVITY_STATUS, DATASTORE_URL, activity_date, clean,
    download_activity_csv, dportal_url, read_activity_csv, resolve_country,
    snapshot_row)

INSTITUTION = "FMO"
REPORTING_ORG = "NL-KVK-27078545"
DATA_URL = DATASTORE_URL.format(org=REPORTING_ORG)
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"

# FMO's internal scheme: "<fund>-P<8 digits>-<seq>", e.g. MASSIF-P00015696-001.
INTERNAL_ID_RE = re.compile(r"-P\d{5,}-\d+$")

DESCRIPTION_PLACEHOLDER = "description not provided"


def download() -> Path:
    return download_activity_csv(REPORTING_ORG, "fmo_iati_activities", RAW_DIR)


def build_sector(row):
    """'24030 Formal sector financial intermediaries' — code kept alongside
    the name, matching the format used for BII's DAC-coded rows."""
    code = clean(row.get("sector-code"))
    name = clean(row.get("sector"))
    if code and name:
        return f"{code} {name}", None
    if code:
        return code, f"sector-code {code} has no name in the export"
    if name:
        return name, "sector name given without a sector-code"
    return None, "no sector code or name given"


def build_description(row):
    """Return (description_or_None, note_or_None)."""
    value = clean(row.get("description_general"))
    if value is None:
        return None, "description_general is blank"
    if value.strip().lower() == DESCRIPTION_PLACEHOLDER:
        return None, ("description_general is the placeholder 'Description not "
                      "provided'; stored as NULL rather than as text")
    return value, None


def load(path: Path) -> None:
    df = read_activity_csv(path)

    conn = get_connection()
    scraped_at = utc_now()
    inserted = issues = 0
    try:
        conn.execute("DELETE FROM projects WHERE institution = ?", (INSTITUTION,))
        conn.execute("DELETE FROM quality_issues WHERE institution = ?", (INSTITUTION,))

        for _, row in df.iterrows():
            raw = snapshot_row(row)

            # --- title ------------------------------------------------------
            name = clean(row.get("title"))
            if name is None:
                log_quality_issue(conn, INSTITUTION, None, "missing_project_name",
                                  "title is blank", raw)
                issues += 1
            elif INTERNAL_ID_RE.search(name):
                log_quality_issue(
                    conn, INSTITUTION, name, "title_is_internal_identifier",
                    f"title {name!r} is an internal fund identifier, not a project "
                    "name; loaded verbatim", raw)
                issues += 1

            # --- country ----------------------------------------------------
            country, country_note = resolve_country(row)
            if country_note:
                log_quality_issue(conn, INSTITUTION, name, "missing_country",
                                  country_note, raw)
                issues += 1

            # --- sector -----------------------------------------------------
            sector, sector_note = build_sector(row)
            if sector_note:
                log_quality_issue(conn, INSTITUTION, name, "unresolved_sector_code",
                                  sector_note, raw)
                issues += 1

            # --- description ------------------------------------------------
            description, description_note = build_description(row)
            if description_note:
                log_quality_issue(conn, INSTITUTION, name, "missing_description",
                                  description_note, raw)
                issues += 1

            # --- date -------------------------------------------------------
            approval_date = activity_date(row)
            if approval_date is None:
                log_quality_issue(conn, INSTITUTION, name, "unparseable_date",
                                  "neither start-actual nor start-planned given", raw)
                issues += 1

            # --- amount: per-transaction currency, NOT default-currency -----
            amount = clean(row.get("total-Commitment"))
            currency = clean(row.get("currency"))
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
                        "source reports a commitment total of 0 — kept as disclosed, "
                        "but almost certainly an unreported amount", raw)
                    issues += 1
                if currency is None:
                    log_quality_issue(
                        conn, INSTITUTION, name, "missing_currency",
                        f"amount {amount:,.0f} has no per-transaction currency; "
                        "amount_usd left NULL (default-currency is unreliable in "
                        "this publication and is deliberately not used)", raw)
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
                    clean(row.get("participating-org (Implementing)")),
                    description,
                    dportal_url(clean(row.get("iati-identifier")), DATA_URL),
                    scraped_at,
                ),
            )
            inserted += 1

        conn.commit()
    finally:
        conn.close()

    print(f"Inserted {inserted} FMO activities ({issues} quality issues logged).")


if __name__ == "__main__":
    load(download())
