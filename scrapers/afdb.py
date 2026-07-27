"""
scrapers/afdb.py — loads AfDB (African Development Bank Group) projects from
a manually downloaded MapAfrica CSV export.

MANUAL DOWNLOAD REQUIRED (afdb.org sits behind bot protection):
  1. Open https://mapafrica.afdb.org/en in a browser and use its export to
     download the full projects CSV.
  2. Save it into data/raw/ with a name starting 'afdb_mapafrica'
     (e.g. afdb_mapafrica_projects_2026-07-14.csv).
  3. Run:  python -m scrapers.afdb
     The loader picks the newest matching file, or pass a path explicitly.

Column mapping (source -> our schema):
    title                       -> project_name
    country                     -> country ('Multinational' kept as-is and
                                   mapped to 'Regional — Africa' by
                                   country_mapping.csv)
    AfDB Sector                 -> sector (rolled up via sector_mapping.csv)
    activity_status             -> status (Approved/Ongoing/Completion/Cancelled)
    Approval Date               -> approval_date
    total_commitments (UA)      -> amount_original with currency='XDR'
                                   (AfDB's Unit of Account = IMF SDR, 1:1);
                                   amount_usd via fx.py XDR annual averages
    environmental_safeguards    -> es_category ('Category 1..4' or FI-A/B/C)
    sovereign / afdb_status     -> description (e.g. 'Sovereign operation;
                                   window: ADF') — same treatment as EBRD's
                                   private/state flag
    identifier                  -> source_url
                                   (https://mapafrica.afdb.org/en/projects/46002-<id>)

Notes:
  * Covers the ENTIRE AfDB Group history (1967→) and BOTH sovereign and
    non-sovereign operations, like our EBRD load (which includes state
    operations). The sovereign flag is preserved in description.
  * UA amounts before 2003 convert at the 2003 XDR rate (the IMF's online
    archive starts there) and are logged as 'fx_rate_approximated'.
  * No sponsor, prose description, or instrument in this export — NULL.
  * region column holds AfDB's internal region codes (RDGW etc.); we leave
    region NULL and rely on canonical_region from country harmonization.
"""

import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import get_connection, log_quality_issue, utc_now  # noqa: E402
from fx import to_usd  # noqa: E402

INSTITUTION = "AfDB"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
FILE_PATTERN = "afdb_mapafrica*.csv"
PORTAL = "https://mapafrica.afdb.org/en"


def find_source_file(cli_arg: str | None) -> Path:
    if cli_arg:
        path = Path(cli_arg)
        if not path.exists():
            sys.exit(f"File not found: {path}")
        return path
    candidates = sorted(RAW_DIR.glob(FILE_PATTERN), key=lambda p: p.stat().st_mtime)
    if not candidates:
        sys.exit(f"No {FILE_PATTERN} file in {RAW_DIR}.\n"
                 f"Download the projects CSV from {PORTAL} (see docstring) and rerun.")
    return candidates[-1]


def clean(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    value = str(value).strip()
    return None if value in ("", "None", "nan") else value


def parse_es_category(value):
    """AfDB categorizes 1-4 (1 = highest risk) plus FI-A/B/C for financial
    intermediaries. Numeric codes get a 'Category ' prefix for readability."""
    value = clean(value)
    if value is None:
        return None
    if value in {"1", "2", "3", "4"}:
        return f"Category {value}"
    return value.replace("IF-", "FI-")  # source typo: 'IF-B' appears alongside 'FI-B'


def load(path: Path) -> None:
    print(f"Reading {path.name}")
    df = pd.read_csv(path, dtype=str)

    conn = get_connection()
    scraped_at = utc_now()
    inserted = issues = 0
    try:
        conn.execute("DELETE FROM projects WHERE institution = ?", (INSTITUTION,))
        conn.execute("DELETE FROM quality_issues WHERE institution = ?", (INSTITUTION,))

        for _, row in df.iterrows():
            raw = row.to_dict()
            name = clean(row.get("title"))
            if name is None:
                log_quality_issue(conn, INSTITUTION, None, "missing_project_name",
                                  "title is blank", raw)
                issues += 1

            approval_date = clean(row.get("Approval Date"))
            if approval_date is None:
                log_quality_issue(conn, INSTITUTION, name, "unparseable_date",
                                  "Approval Date missing", raw)
                issues += 1

            amount_ua = clean(row.get("total_commitments (UA)"))
            amount_usd = None
            if amount_ua is None:
                log_quality_issue(conn, INSTITUTION, name, "missing_amount",
                                  "total_commitments (UA) is blank", raw)
                issues += 1
            else:
                amount_ua = float(amount_ua)
                year = int(approval_date[:4]) if approval_date else None
                amount_usd, fx_note = to_usd(amount_ua, "XDR", year)
                if fx_note and amount_usd is None:
                    log_quality_issue(conn, INSTITUTION, name, "fx_rate_missing",
                                      fx_note, raw)
                    issues += 1
                elif fx_note:
                    log_quality_issue(conn, INSTITUTION, name, "fx_rate_approximated",
                                      fx_note, raw)
                    issues += 1

            sovereign = clean(row.get("sovereign"))
            window = clean(row.get("afdb_status"))
            bits = []
            if sovereign is not None:
                bits.append("Sovereign operation" if sovereign == "True"
                            else "Non-sovereign operation")
            if window:
                bits.append(f"window: {window}")
            description = "; ".join(bits) or None

            identifier = clean(row.get("identifier"))
            source_url = (f"https://mapafrica.afdb.org/en/projects/46002-{identifier}"
                          if identifier else PORTAL)

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
                    None,  # region: AfDB internal codes only; canonical_region covers it
                    clean(row.get("AfDB Sector")),
                    None,
                    None,  # instrument: not in this export
                    amount_ua,
                    "XDR" if amount_ua is not None else None,
                    amount_usd,
                    approval_date,
                    None,
                    clean(row.get("activity_status")),
                    parse_es_category(row.get("environmental_safeguards")),
                    None,  # sponsor: not in this export
                    description,
                    source_url,
                    scraped_at,
                ),
            )
            inserted += 1

        conn.commit()
    finally:
        conn.close()

    print(f"Inserted {inserted} AfDB projects ({issues} quality issues logged).")


if __name__ == "__main__":
    load(find_source_file(sys.argv[1] if len(sys.argv) > 1 else None))
