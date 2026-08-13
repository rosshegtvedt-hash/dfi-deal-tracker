"""
scrapers/iati_common.py — helpers shared by the loaders that read IATI
publications through the Code for IATI Datastore Classic (currently BII and
FMO).

Only the genuinely identical mechanics live here — fetching, the truncation
guard, dates, the country fallback and the d-portal link. Each institution's
own quirks (sector vocabularies, currency handling, description fields) stay
in its own loader, because that is where they differ most and where the
per-source reasoning belongs.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import requests

DATASTORE_URL = ("https://datastore.codeforiati.org/api/1/access/{resource}.csv"
                 "?stream=True&reporting-org={org}")


def datastore_url(reporting_org: str, resource: str = "activity") -> str:
    """Datastore export URL. `resource` is 'activity' (one row per activity,
    with lifetime totals) or 'transaction' (one row per transaction, each
    with its own date and value)."""
    return DATASTORE_URL.format(resource=resource, org=reporting_org)
UA_HEADER = {"User-Agent": "RCFH-Advisory DFI tracker (contact: rosshegtvedt@gmail.com)"}

# Without stream=True the API silently returns exactly 50 rows. Any export
# near that size means the parameter was ignored, and loading it would wipe
# good data and replace it with a fragment.
MIN_EXPECTED_ROWS = 200

# IATI ActivityStatus codelist (stable, 6 entries — hardcoded so a codelist
# outage can't stall a load).
ACTIVITY_STATUS = {
    "1": "Pipeline/identification",
    "2": "Implementation",
    "3": "Finalisation",
    "4": "Closed",
    "5": "Cancelled",
    "6": "Suspended",
}


def download_activity_csv(reporting_org: str, filename_stem: str,
                          raw_dir: Path, resource: str = "activity") -> Path:
    """Fetch one publisher's CSV export, archived date-stamped in data/raw/."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{filename_stem}_{date.today().isoformat()}.csv"
    url = datastore_url(reporting_org, resource)
    print(f"Downloading {url}")
    resp = requests.get(url, headers=UA_HEADER, timeout=300)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"Saved {len(resp.content):,} bytes to {dest.name}")
    return dest


def read_activity_csv(path: Path) -> pd.DataFrame:
    """Read an archived export, refusing anything that looks truncated."""
    df = pd.read_csv(path, dtype=str, low_memory=False)
    if len(df) < MIN_EXPECTED_ROWS:
        raise SystemExit(
            f"Only {len(df)} rows in {path.name} — the API likely ignored "
            "stream=True and truncated the export. Refusing to load; check the "
            "source URL before rerunning.")
    print(f"{len(df)} activities in export")
    return df


def clean(value):
    """Blank/NaN/'nan'/'None' -> None, so SQLite stores real NULLs."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    value = str(value).strip()
    return None if value in ("", "nan", "None") else value


def activity_date(row):
    """Activity start date (actual, else planned) as ISO. IATI publishes no
    board-approval date, so this is the closest available anchor."""
    value = clean(row.get("start-actual")) or clean(row.get("start-planned"))
    return value[:10] if value else None


def resolve_country(row):
    """Return (country_value, note_or_None).

    Uses recipient-country; falls back to the disclosed recipient-region so
    regional operations keep the 'Regional — ...' treatment the other
    institutions get. Never invents a country — the note explains any
    fallback so the caller can log it.
    """
    country = clean(row.get("recipient-country"))
    if country:
        return country, None
    region = clean(row.get("recipient-region"))
    if region:
        return region, (f"no recipient-country; using disclosed "
                        f"recipient-region {region!r} instead")
    return None, "no recipient-country and no recipient-region disclosed"


def dportal_url(identifier, fallback):
    """Public activity page for an IATI identifier."""
    return f"https://d-portal.org/q.html?aid={identifier}" if identifier else fallback


def snapshot_row(row) -> dict:
    """Trimmed copy of a source row for the quality_issues audit trail."""
    return {k: (str(v)[:300] if pd.notna(v) else None) for k, v in row.items()}
