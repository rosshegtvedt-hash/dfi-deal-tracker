"""
scrapers/dfc.py — loads DFC's Annual Project Data spreadsheet into the tracker.

DFC (U.S. International Development Finance Corporation) publishes an official
Excel file of all active transactions on its transparency page:
https://www.dfc.gov/our-impact/transaction-data
This is published data intended for public use — downloading it is not scraping.

When DFC posts a new release (typically ~45 days after fiscal quarter/year end),
update DATA_URL below and rerun:
    python -m scrapers.dfc

Column mapping (source file -> our schema), based on the file's own Read Me sheet:
    Project Name                            -> project_name
    Country                                 -> country
    Region                                  -> region
    NAICS Sector                            -> sector
    Support Type (fallback: Project Type)   -> instrument
    Committed  (always USD per Read Me)     -> amount_original, amount_usd
    Fiscal Year                             -> fiscal_year (no exact date disclosed,
                                               so approval_date stays NULL)
    Environmental and Social Risk Category  -> es_category
    Project Description                     -> description
    Project Profile URL (fallback: file URL)-> source_url

Notes:
  * The source's "Currency" column is the disbursement currency of the loan,
    NOT the units of "Committed" — Committed is always USD, so currency='USD'.
  * status is set to 'Active' for every row: the file is by definition a
    snapshot of active transactions only.
  * The sheet ends with an "End of Table" accessibility footer row, which is
    skipped (it is formatting, not data).
"""

import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests

# Allow running as "python scrapers/dfc.py" as well as "python -m scrapers.dfc"
sys.path.insert(0, str(Path(__file__).parent.parent))
from database import get_connection, log_quality_issue, utc_now  # noqa: E402

INSTITUTION = "DFC"
DATA_URL = (
    "https://www.dfc.gov/sites/default/files/media/documents/"
    "FY24%20DFC%20Annual%20Project%20Data_508.xlsx"
)
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
SHEET = "Project Data"
HEADER_ROW = 1  # row 0 is a sheet title; real headers are on the second row


def download() -> Path:
    """Download the source file into data/raw/ with today's date in the name."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / f"dfc_annual_project_data_{date.today().isoformat()}.xlsx"
    print(f"Downloading {DATA_URL}")
    resp = requests.get(
        DATA_URL,
        headers={"User-Agent": "RCFH-Advisory DFI tracker (contact: rosshegtvedt@gmail.com)"},
        timeout=120,
    )
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"Saved {len(resp.content):,} bytes to {dest.name}")
    return dest


def clean(value):
    """Turn pandas NaN/empty strings into None so SQLite stores real NULLs."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def parse_amount(value):
    """Return (amount_or_None, error_message_or_None)."""
    value = clean(value)
    if value is None:
        return None, "missing"
    try:
        return float(value), None
    except (TypeError, ValueError):
        return None, f"unparseable value: {value!r}"


def parse_fiscal_year(value):
    """Return (year_or_None, error_message_or_None)."""
    value = clean(value)
    if value is None:
        return None, "missing"
    try:
        year = int(value)
        if not 1900 <= year <= 2100:
            return None, f"out of plausible range: {value!r}"
        return year, None
    except (TypeError, ValueError):
        return None, f"unparseable value: {value!r}"


def load(path: Path) -> None:
    """Parse the Excel file and replace DFC's rows in the database."""
    df = pd.read_excel(path, sheet_name=SHEET, header=HEADER_ROW)
    scraped_at = utc_now()

    conn = get_connection()
    inserted = issues = skipped_footer = 0
    try:
        # Replace-don't-duplicate: clear previous DFC rows and their old issues.
        conn.execute("DELETE FROM projects WHERE institution = ?", (INSTITUTION,))
        conn.execute("DELETE FROM quality_issues WHERE institution = ?", (INSTITUTION,))

        for _, row in df.iterrows():
            # Skip the "End of Table" accessibility footer (formatting, not data).
            if str(row.get("Fiscal Year")).strip() == "End of Table" and clean(row.get("Project Name")) is None:
                skipped_footer += 1
                continue

            raw = row.to_dict()
            name = clean(row.get("Project Name"))

            amount, amount_err = parse_amount(row.get("Committed"))
            if amount_err:
                log_quality_issue(conn, INSTITUTION, name, "missing_amount",
                                  f"Committed amount {amount_err}", raw)
                issues += 1

            fiscal_year, fy_err = parse_fiscal_year(row.get("Fiscal Year"))
            if fy_err:
                log_quality_issue(conn, INSTITUTION, name, "unparseable_fiscal_year",
                                  f"Fiscal Year {fy_err}", raw)
                issues += 1

            if name is None:
                log_quality_issue(conn, INSTITUTION, None, "missing_project_name",
                                  "Project Name is blank", raw)
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
                    clean(row.get("Country")),
                    clean(row.get("Region")),
                    clean(row.get("NAICS Sector")),
                    None,  # subsector: DFC does not disclose one
                    clean(row.get("Support Type")) or clean(row.get("Project Type")),
                    amount,
                    "USD" if amount is not None else None,
                    amount,  # Committed is already USD per the file's Read Me
                    None,    # approval_date: DFC discloses fiscal year only
                    fiscal_year,
                    "Active",  # the file is a snapshot of active transactions
                    clean(row.get("Environmental and Social Risk Category")),
                    None,  # sponsor: not disclosed
                    clean(row.get("Description")) or clean(row.get("Project Description")),
                    clean(row.get("Project Profile URL")) or DATA_URL,
                    scraped_at,
                ),
            )
            inserted += 1

        conn.commit()
    finally:
        conn.close()

    print(f"Inserted {inserted} DFC projects "
          f"({issues} quality issues logged, {skipped_footer} footer row(s) skipped).")


if __name__ == "__main__":
    load(download())
