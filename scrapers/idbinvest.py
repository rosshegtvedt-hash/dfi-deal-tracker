"""
scrapers/idbinvest.py — loads IDB Invest (IDB Group private-sector arm)
projects from its official XML feed.

Source: https://idbinvest.org/en/projects.xml — a complete machine-readable
dump of the project disclosure portal (https://idbinvest.org/en/projects),
published by IDB Invest for exactly this purpose. Covers IIC/IDB Invest
operations back to 1989.

Run:
    python -m scrapers.idbinvest

Field mapping (XML tag -> our schema):
    project_name                    -> project_name
    company                         -> sponsor
    country                         -> country ('Regional' -> 'Latin America
                                       Regional', since IDB Invest operates
                                       only in LAC)
    sector                          -> sector
    Investment_instrument           -> instrument
    iic_financing_amount (fallback:
      project_idb_fin_amount)       -> amount_original (see note below)
    currency                        -> currency; USD conversion via fx.py
    approval_date                   -> approval_date
    status                          -> status
    environment_social_category     -> es_category
    description (HTML stripped)     -> description
    project_url                     -> source_url

Notes:
  * The feed is BILINGUAL: every project appears once in English and once in
    Spanish (same project_number). We keep the English record per project.
  * Amounts: iic_financing_amount is IDB Invest's own-account financing and
    is present for ~87% of records; project_idb_fin_amount (broader IDB
    Group financing) is used as a fallback when it's absent. Documented
    because the two are not identical concepts.
  * Local-currency deals (MXN, COP, BRL, ...) are converted with ECB annual
    average rates where available (fx_rates.csv); currencies the ECB does
    not publish (COP, PEN, PYG, ...) get amount_usd = NULL and a logged
    'fx_rate_missing' issue — never guessed.
  * An amount with no currency stated is stored in amount_original with
    currency and amount_usd NULL, logged as 'missing_currency'.
"""

import html
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import get_connection, log_quality_issue, utc_now  # noqa: E402
from fx import to_usd  # noqa: E402

INSTITUTION = "IDB Invest"
FEED_URL = "https://idbinvest.org/en/projects.xml"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"


def download() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / f"idbinvest_projects_{date.today().isoformat()}.xml"
    print(f"Downloading {FEED_URL}")
    resp = requests.get(
        FEED_URL, timeout=300,
        headers={"User-Agent": "RCFH-Advisory DFI tracker (contact: rosshegtvedt@gmail.com)"},
    )
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"Saved {len(resp.content):,} bytes to {dest.name}")
    return dest


def text(item, tag):
    value = item.findtext(tag)
    if value is None:
        return None
    value = html.unescape(value).strip()
    return value or None


def strip_html(value):
    if value is None:
        return None
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip() or None


def parse_amount(value):
    if value is None:
        return None, None
    try:
        return float(value), None
    except (TypeError, ValueError):
        return None, f"unparseable value: {value!r}"


def is_english(item) -> bool:
    lang = (text(item, "Language") or "").lower()
    if lang.startswith("en"):
        return True
    if lang.startswith("es") or lang.startswith("sp"):
        return False
    # No language tag: fall back to the URL path (/en/ vs /es/).
    return "/es/" not in (text(item, "project_url") or "/en/")


def select_english(items):
    """The feed carries each project in English and Spanish; keep one record
    per project_number, preferring the English one."""
    groups = {}
    for item in items:
        key = text(item, "project_number") or (
            text(item, "project_name"), text(item, "approval_date"))
        groups.setdefault(key, []).append(item)

    selected = []
    for candidates in groups.values():
        english = [c for c in candidates if is_english(c)]
        selected.append(english[0] if english else candidates[0])
    return selected


def load(path: Path) -> None:
    root = ET.parse(path).getroot()
    all_items = root.findall("item")
    items = select_english(all_items)
    print(f"{len(all_items)} feed records -> {len(items)} unique projects "
          f"(bilingual duplicates collapsed)")

    conn = get_connection()
    scraped_at = utc_now()
    inserted = issues = 0
    try:
        conn.execute("DELETE FROM projects WHERE institution = ?", (INSTITUTION,))
        conn.execute("DELETE FROM quality_issues WHERE institution = ?", (INSTITUTION,))

        for item in items:
            raw = {c.tag: (c.text or "").strip()[:400] for c in item}
            name = text(item, "project_name")

            country = text(item, "country")
            if country == "Regional":
                # IDB Invest operates only in Latin America & the Caribbean.
                country = "Latin America Regional"

            amount, amount_err = parse_amount(text(item, "iic_financing_amount"))
            if amount is None and amount_err is None:
                amount, amount_err = parse_amount(text(item, "project_idb_fin_amount"))
            if amount is None:
                log_quality_issue(conn, INSTITUTION, name, "missing_amount",
                                  amount_err or "no financing amount in feed", raw)
                issues += 1

            currency = text(item, "currency")
            approval_date = text(item, "approval_date")
            if approval_date is None:
                log_quality_issue(conn, INSTITUTION, name, "unparseable_date",
                                  "approval_date missing from feed", raw)
                issues += 1

            amount_usd = None
            if amount is not None:
                if currency is None:
                    log_quality_issue(conn, INSTITUTION, name, "missing_currency",
                                      f"amount {amount:,.0f} has no currency stated; "
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
                        log_quality_issue(conn, INSTITUTION, name, "fx_rate_approximated",
                                          fx_note, raw)
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
                    None,  # region: not in the feed (all LAC)
                    text(item, "sector"),
                    None,
                    text(item, "Investment_instrument"),
                    amount,
                    currency,
                    amount_usd,
                    approval_date,
                    None,
                    text(item, "status"),
                    text(item, "environment_social_category"),
                    text(item, "company"),
                    strip_html(text(item, "description")),
                    text(item, "project_url") or FEED_URL,
                    scraped_at,
                ),
            )
            inserted += 1

        conn.commit()
    finally:
        conn.close()

    print(f"Inserted {inserted} IDB Invest projects ({issues} quality issues logged).")


if __name__ == "__main__":
    load(download())
