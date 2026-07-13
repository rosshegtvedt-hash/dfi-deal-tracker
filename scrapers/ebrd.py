"""
scrapers/ebrd.py — loads EBRD's official investments overview spreadsheet.

Source: "Projects overview" Excel published on EBRD's project finance page,
https://www.ebrd.com/work-with-us/project-finance/project-summary-documents.html
The 'List' sheet is a complete dump of every signed EBRD operation since 1991
with country, sector, signing date, and EBRD finance in EUR — published
deliberately as a download, so no scraping concerns.

The filename embeds the coverage period, so the URL changes with each annual
release — update DATA_URL below when EBRD posts a new edition and rerun:
    python -m scrapers.ebrd

Column mapping ('List' sheet -> our schema):
    Operation Name                    -> project_name
    Country (SHOUTING CASE -> Title)  -> country
    Sector                            -> sector
    Original Signing Date             -> approval_date  (note: SIGNING date;
                                         EBRD does not publish board dates here)
    EBRD Finance (EUR, plain units)   -> amount_original; converted to USD
                                         with fx.py annual-average rates
    Debt/Equity/Guarantee components  -> instrument (derived: whichever
                                         components are non-zero)
    Portfolio Class + Direct/Regional -> description (e.g. 'EBRD portfolio
                                         class: PRIVATE; Direct operation')

Notes:
  * Amounts are cumulative net bank investment per signed operation, in EUR
    "at reported rates" (EBRD's own restatement). USD conversion uses the
    annual average ECB rate for the signing year; pre-1999 signings (before
    ECB euro rates exist) fall back to the 1999 rate and are logged as
    'fx_rate_approximated' — flagged, never silent.
  * Every row is a signed operation, so status = 'Signed'. The sheet does not
    say whether an operation is still active or repaid.
  * es_category, sponsor, region: not in this file -> NULL. Deeper detail
    (status, descriptions, E&S category) lives in EBRD's per-project PSD
    pages — a possible future enrichment.
  * The sheet ends with an 'Overall - Total' footer row, which is skipped
    (formatting, not data).
"""

import math
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import get_connection, log_quality_issue, utc_now  # noqa: E402
from fx import to_usd  # noqa: E402

INSTITUTION = "EBRD"
DATA_URL = (
    "https://www.ebrd.com/content/dam/ebrd_dxp/assets/pdfs/publications/"
    "ebrd-investments-1991-2025.xlsx"
)
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
SHEET = "List"
HEADER_ROW = 5  # rows 0-4 are titles/notes; real headers on the sixth row

# Words kept lowercase when prettifying EBRD's ALL-CAPS country names.
LOWERCASE_WORDS = {"and", "of", "the"}


def download() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / f"ebrd_investments_{date.today().isoformat()}.xlsx"
    print(f"Downloading {DATA_URL}")
    resp = requests.get(
        DATA_URL, timeout=180,
        headers={"User-Agent": "RCFH-Advisory DFI tracker (contact: rosshegtvedt@gmail.com)"},
    )
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"Saved {len(resp.content):,} bytes to {dest.name}")
    return dest


def clean(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def title_case_country(value):
    """'BOSNIA AND HERZEGOVINA' -> 'Bosnia and Herzegovina' (cosmetic only)."""
    value = clean(value)
    if value is None:
        return None
    words = str(value).strip().lower().split()
    out = [w if (i > 0 and w in LOWERCASE_WORDS) else w.capitalize()
           for i, w in enumerate(words)]
    return " ".join(out)


def parse_signing_date(value):
    """Return (iso_date_or_None, error_or_None). Values are datetimes or junk like '-'."""
    value = clean(value)
    if value is None:
        return None, "missing"
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.date().isoformat(), None
    return None, f"unparseable value: {value!r}"


def derive_instrument(row):
    """Name the instrument from whichever finance components are non-zero."""
    parts = []
    for column, label in [("EBRD Finance - Debt", "Debt"),
                          ("EBRD Finance - Equity", "Equity"),
                          ("EBRD Finance - Guarantee", "Guarantee")]:
        value = clean(row.get(column))
        if value and float(value) > 0:
            parts.append(label)
    return " + ".join(parts) if parts else None


def load(path: Path) -> None:
    df = pd.read_excel(path, sheet_name=SHEET, header=HEADER_ROW)
    scraped_at = utc_now()

    conn = get_connection()
    inserted = issues = skipped_footer = 0
    try:
        conn.execute("DELETE FROM projects WHERE institution = ?", (INSTITUTION,))
        conn.execute("DELETE FROM quality_issues WHERE institution = ?", (INSTITUTION,))

        for _, row in df.iterrows():
            if str(row.get("Country")).strip() == "Overall - Total":
                skipped_footer += 1
                continue

            raw = row.to_dict()
            name = clean(row.get("Operation Name"))

            if name is None:
                log_quality_issue(conn, INSTITUTION, None, "missing_project_name",
                                  "Operation Name is blank", raw)
                issues += 1

            signing_date, date_err = parse_signing_date(row.get("Original Signing Date"))
            if date_err:
                log_quality_issue(conn, INSTITUTION, name, "unparseable_date",
                                  f"Original Signing Date {date_err}", raw)
                issues += 1

            amount_eur = clean(row.get("EBRD Finance"))
            if amount_eur is None:
                log_quality_issue(conn, INSTITUTION, name, "missing_amount",
                                  "EBRD Finance is blank", raw)
                issues += 1
                amount_usd = None
            else:
                amount_eur = float(amount_eur)
                signing_year = int(signing_date[:4]) if signing_date else None
                amount_usd, fx_note = to_usd(amount_eur, "EUR", signing_year)
                if fx_note:
                    log_quality_issue(conn, INSTITUTION, name, "fx_rate_approximated",
                                      fx_note, raw)
                    issues += 1

            portfolio_class = clean(row.get("Portfolio Class"))
            direct_regional = clean(row.get("Direct/Regional"))
            description = None
            if portfolio_class or direct_regional:
                bits = []
                if portfolio_class:
                    bits.append(f"EBRD portfolio class: {portfolio_class}")
                if direct_regional:
                    bits.append(f"{direct_regional} operation")
                description = "; ".join(bits)

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
                    title_case_country(row.get("Country")),
                    None,  # region: not in this file
                    clean(row.get("Sector")),
                    None,  # subsector: harmonization derives one from Sector
                    derive_instrument(row),
                    amount_eur,
                    "EUR" if amount_eur is not None else None,
                    amount_usd,
                    signing_date,
                    None,  # fiscal_year: EBRD's FY is the calendar year of the date
                    "Signed",  # every row in this file is a signed operation
                    None,  # es_category: not in this file
                    None,  # sponsor: not in this file
                    description,
                    DATA_URL,
                    scraped_at,
                ),
            )
            inserted += 1

        conn.commit()
    finally:
        conn.close()

    print(f"Inserted {inserted} EBRD operations "
          f"({issues} quality issues logged, {skipped_footer} footer row(s) skipped).")


if __name__ == "__main__":
    load(download())
