"""
update_macro_series.py — regenerates macro_series.csv with the World Bank
national-accounts series the denominator exhibits divide by.

Run when the World Bank refreshes its aggregates (roughly every July):
    python update_macro_series.py

Series come from the World Bank's free Indicators API (no key needed). Two
groups land in one long-format CSV:

  AGGREGATES, for exhibit 10
    WLD  NY.GDP.MKTP.CD   world GDP, current USD
    HIC  NY.GNP.MKTP.CD   high-income GNI, current USD
    HIC  NY.GDP.MKTP.KD   high-income GDP, constant 2015 USD
    LMY  NY.GDP.MKTP.CD   low- and middle-income GDP, current USD
    LMY  NY.GDP.MKTP.KD   low- and middle-income GDP, constant 2015 USD

  COUNTRIES, for exhibit 12
    NY.GDP.MKTP.CD   GDP, current USD
    NE.GDI.FTOT.CD   gross fixed capital formation, current USD

WHY CURRENT USD, AND WHY NO DEFLATOR
Exhibit 10 divides commitments by GDP rather than deflating either side.
Commitments and GDP both arrive as current USD, so the ratio needs no price
index at all. This matters more than it sounds: deflating commitments by US
CPI while comparing them to a global output series puts two different
yardsticks on one chart and reverses the finding. The constant-USD series
below serve only the real-growth figures quoted in the deks, never the ratios.

GNI, NOT GDP, FOR THE FUNDER SIDE
The high-income line divides by GNI because that is the denominator the
official-finance world already uses for burden-sharing, including the 0.7 per
cent ODA target. It keeps the exhibit legible to a DAC-literate reader.

COUNTRY CODES
The tracker stores canonical country names, not ISO codes, so ISO3 lives in
the explicit table below rather than in a fuzzy match. Hand-maintained, which
is the point: a name that fails to map raises rather than silently dropping a
recipient out of the exhibit.
"""

import csv
import json
import urllib.request
from pathlib import Path

OUT_PATH = Path(__file__).parent / "macro_series.csv"
API = "https://api.worldbank.org/v2"
YEARS = (2015, 2024)

AGGREGATES = {
    "WLD": ["NY.GDP.MKTP.CD"],
    "HIC": ["NY.GNP.MKTP.CD", "NY.GDP.MKTP.KD"],
    "LMY": ["NY.GDP.MKTP.CD", "NY.GDP.MKTP.KD"],
}

COUNTRY_INDICATORS = ["NY.GDP.MKTP.CD", "NE.GDI.FTOT.CD"]

# Canonical tracker name -> ISO3. Covers every single-country recipient that
# clears roughly USD 6bn over 2015-2024; regional and global rows have no
# national denominator and are excluded from exhibit 12 by construction.
ISO3 = {
    "Türkiye": "TUR", "India": "IND", "Egypt": "EGY", "Brazil": "BRA",
    "Morocco": "MAR", "South Africa": "ZAF", "Ukraine": "UKR",
    "Nigeria": "NGA", "China": "CHN", "Poland": "POL", "Greece": "GRC",
    "Ethiopia": "ETH", "Serbia": "SRB", "Kenya": "KEN", "Tunisia": "TUN",
    "Romania": "ROU", "Uzbekistan": "UZB", "Colombia": "COL",
    "Georgia": "GEO", "Kazakhstan": "KAZ",
}


def fetch(entity, indicator):
    """One indicator for one entity or semicolon-joined list of entities."""
    rows, page = [], 1
    while True:
        url = (f"{API}/country/{entity}/indicator/{indicator}"
               f"?date={YEARS[0]}:{YEARS[1]}&format=json&per_page=300&page={page}")
        with urllib.request.urlopen(url, timeout=60) as fh:
            payload = json.load(fh)
        if len(payload) < 2 or not payload[1]:
            break
        rows.extend(payload[1])
        if page >= payload[0]["pages"]:
            break
        page += 1
    return rows


def income_groups(codes):
    """WB income classification, the grouping exhibit 12 colours by."""
    out = {}
    for page in (1, 2):
        url = f"{API}/country/{';'.join(codes)}?format=json&per_page=300&page={page}"
        with urllib.request.urlopen(url, timeout=60) as fh:
            payload = json.load(fh)
        if len(payload) < 2 or not payload[1]:
            break
        for rec in payload[1]:
            out[rec["id"]] = rec["incomeLevel"]["value"]
    return out


def main():
    records = []

    for entity, indicators in AGGREGATES.items():
        for indicator in indicators:
            for row in fetch(entity, indicator):
                if row["value"] is None:
                    continue
                records.append({
                    "entity": entity, "iso3": entity, "name": entity,
                    "indicator": indicator, "year": int(row["date"]),
                    "value": row["value"], "income_group": "",
                })

    codes = sorted(ISO3.values())
    groups = income_groups(codes)
    by_iso = {v: k for k, v in ISO3.items()}

    for indicator in COUNTRY_INDICATORS:
        for row in fetch(";".join(codes), indicator):
            if row["value"] is None:
                continue
            iso = row["countryiso3code"]
            records.append({
                "entity": "country", "iso3": iso, "name": by_iso.get(iso, iso),
                "indicator": indicator, "year": int(row["date"]),
                "value": row["value"], "income_group": groups.get(iso, ""),
            })

    records.sort(key=lambda r: (r["entity"], r["iso3"], r["indicator"], r["year"]))
    with OUT_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "entity", "iso3", "name", "indicator", "year", "value",
            "income_group"])
        writer.writeheader()
        writer.writerows(records)

    missing = sorted(set(codes) - {r["iso3"] for r in records})
    print(f"Wrote {len(records):,} rows to {OUT_PATH.name} "
          f"({YEARS[0]}-{YEARS[1]}).")
    if missing:
        print(f"WARNING: no data returned for {', '.join(missing)}")


if __name__ == "__main__":
    main()
