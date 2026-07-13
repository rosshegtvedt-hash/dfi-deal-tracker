"""
scrapers/adb.py — loads ADB's Nonsovereign Products dataset from a manually
downloaded Excel file.

MANUAL DOWNLOAD REQUIRED (adb.org sits behind bot protection, so this loader
reads a local file instead of downloading):
  1. Open https://data.adb.org/dataset/adb-nonsovereign-products in a browser.
  2. Download the XLSX and save it into data/raw/ keeping a name that starts
     with 'adb-nonsov-products' (e.g. adb-nonsov-products-202501.xlsx).
  3. Run:  python -m scrapers.adb
     The loader picks the most recently modified matching file, or pass a
     path explicitly:  python -m scrapers.adb "data/raw/somefile.xlsx"

Column mapping (source -> our schema):
    Project Name                  -> project_name (ADB prefixes a country
                                     code, e.g. 'IND: DAHEJ LNG TERMINAL')
    Country                       -> country ('Regional' -> 'Asia Regional',
                                     since ADB operates in Asia-Pacific)
    Subsectors                    -> sector (ADB discloses granular subsector
                                     labels; sector_mapping.csv rolls them up)
    Product Type or Modality      -> instrument
    Product Status                -> status (ACTIVE/CLOSED/APPROVED/...)
    Approval Date                 -> approval_date
    Amount in USD                 -> amount_usd (ADB pre-converts)
    Currency + Amount (when set)  -> currency + amount_original for
                                     local-currency deals; otherwise USD
    Borrower / Company            -> sponsor
    Description                   -> description
    Project Number                -> source_url (https://www.adb.org/projects/<nr>/main)

Notes:
  * 'Financing' is 'Nonsovereign' on every row — asserted at load time so a
    future file accidentally containing sovereign rows can't slip in.
  * A few Approval Numbers appear on more than one row (multi-product
    approvals); all rows are kept and each extra is logged as
    'duplicate_approval_number' for visibility.
"""

import math
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import get_connection, log_quality_issue, utc_now  # noqa: E402

INSTITUTION = "ADB"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
FILE_PATTERN = "adb-nonsov-products*.xlsx"
DATASET_PAGE = "https://data.adb.org/dataset/adb-nonsovereign-products"


def find_source_file(cli_arg: str | None) -> Path:
    if cli_arg:
        path = Path(cli_arg)
        if not path.exists():
            sys.exit(f"File not found: {path}")
        return path
    candidates = sorted(RAW_DIR.glob(FILE_PATTERN), key=lambda p: p.stat().st_mtime)
    if not candidates:
        sys.exit(
            f"No {FILE_PATTERN} file in {RAW_DIR}.\n"
            f"Download it from {DATASET_PAGE} (see docstring) and rerun."
        )
    return candidates[-1]


def clean(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def parse_date(value):
    value = clean(value)
    if value is None:
        return None, "missing"
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.date().isoformat(), None
    return None, f"unparseable value: {value!r}"


def load(path: Path) -> None:
    print(f"Reading {path.name}")
    df = pd.read_excel(path, sheet_name=0, header=0)

    financing = set(df["Financing"].dropna().unique())
    if financing != {"Nonsovereign"}:
        sys.exit(f"Expected only Nonsovereign rows, found {financing} — "
                 "check the file before loading.")

    conn = get_connection()
    scraped_at = utc_now()
    inserted = issues = 0
    seen_approvals = set()
    try:
        conn.execute("DELETE FROM projects WHERE institution = ?", (INSTITUTION,))
        conn.execute("DELETE FROM quality_issues WHERE institution = ?", (INSTITUTION,))

        for _, row in df.iterrows():
            raw = row.to_dict()
            name = clean(row.get("Project Name"))
            if name is None:
                log_quality_issue(conn, INSTITUTION, None, "missing_project_name",
                                  "Project Name is blank", raw)
                issues += 1

            country = clean(row.get("Country"))
            if country == "Regional":
                country = "Asia Regional"  # ADB's operational region

            approval_date, date_err = parse_date(row.get("Approval Date"))
            if date_err:
                log_quality_issue(conn, INSTITUTION, name, "unparseable_date",
                                  f"Approval Date {date_err}", raw)
                issues += 1

            amount_usd = clean(row.get("Amount in USD"))
            if amount_usd is None:
                log_quality_issue(conn, INSTITUTION, name, "missing_amount",
                                  "Amount in USD is blank", raw)
                issues += 1
            else:
                amount_usd = float(amount_usd)

            # Local-currency deals carry the original amount in Currency/Amount;
            # otherwise the deal is USD-denominated.
            original_currency = clean(row.get("Currency"))
            original_amount = clean(row.get("Amount"))
            if original_currency and original_amount is not None:
                currency = original_currency
                amount_original = float(original_amount)
            else:
                currency = "USD" if amount_usd is not None else None
                amount_original = amount_usd

            approval_nr = clean(row.get("Approval Number"))
            if approval_nr in seen_approvals:
                log_quality_issue(conn, INSTITUTION, name, "duplicate_approval_number",
                                  f"Approval Number {approval_nr} appears on multiple "
                                  "rows (multi-product approval); all rows kept", raw)
                issues += 1
            seen_approvals.add(approval_nr)

            project_nr = clean(row.get("Project Number"))
            source_url = (f"https://www.adb.org/projects/{project_nr}/main"
                          if project_nr else DATASET_PAGE)

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
                    None,  # region: not in this file
                    clean(row.get("Subsectors")),  # ADB's most granular sector label
                    None,
                    clean(row.get("Product Type or Modality")),
                    amount_original,
                    currency,
                    amount_usd,
                    approval_date,
                    None,
                    clean(row.get("Product Status")),
                    None,  # es_category: not in this file
                    clean(row.get("Borrower / Company")),
                    clean(row.get("Description")),
                    source_url,
                    scraped_at,
                ),
            )
            inserted += 1

        conn.commit()
    finally:
        conn.close()

    print(f"Inserted {inserted} ADB nonsovereign products "
          f"({issues} quality issues logged).")


if __name__ == "__main__":
    load(find_source_file(sys.argv[1] if len(sys.argv) > 1 else None))
