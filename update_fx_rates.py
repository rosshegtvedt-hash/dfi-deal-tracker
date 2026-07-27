"""
update_fx_rates.py — regenerates fx_rates.csv with annual average exchange
rates against the US dollar.

Run once a year (or whenever you add a currency):
    python update_fx_rates.py

Rates come from the European Central Bank's official daily reference rates,
served by the free frankfurter.app API (no key needed). For each currency and
year we average all daily rates — the standard convention for converting
annual commitment flows. The result is a plain CSV you can inspect or
hand-edit; loaders read the CSV, never the API, so day-to-day pipeline runs
work offline and are reproducible.

ECB data starts in 1999 (the euro's introduction), so earlier years have no
row; fx.py falls back to the earliest available year and loaders log that
approximation per record.
"""

import csv
import time
from datetime import date
from pathlib import Path

import requests

OUT_PATH = Path(__file__).parent / "fx_rates.csv"
# EUR/GBP for EBRD & future BII; MXN/BRL for IDB Invest local-currency deals.
# (The ECB publishes reference rates for ~30 currencies; smaller LAC
# currencies like COP/PEN/PYG are not covered — loaders log those as
# fx_rate_missing rather than guessing.)
CURRENCIES = ["EUR", "GBP", "MXN", "BRL"]
START_YEAR = 1999            # ECB reference rates begin here
SOURCE_NOTE = "ECB reference rates via frankfurter.app, annual average of daily rates"


def fetch_annual_averages(currency: str) -> dict[int, float]:
    """One API call per currency: all daily rates since 1999, averaged by year."""
    url = f"https://api.frankfurter.app/{START_YEAR}-01-04..{date.today().isoformat()}"
    resp = requests.get(url, params={"from": currency, "to": "USD"}, timeout=120)
    resp.raise_for_status()
    daily = resp.json()["rates"]  # {'1999-01-04': {'USD': 1.1789}, ...}

    by_year: dict[int, list[float]] = {}
    for day, rates in daily.items():
        by_year.setdefault(int(day[:4]), []).append(rates["USD"])
    return {year: sum(vals) / len(vals) for year, vals in sorted(by_year.items())}


# --- XDR (IMF Special Drawing Rights = AfDB's Unit of Account) -------------
# The ECB doesn't publish SDR rates; the IMF's own monthly archive does
# (from 2003). One request per sampled month, so already-fetched years are
# cached in the existing CSV and never re-fetched.
XDR_START_YEAR = 2003
XDR_SAMPLE_MONTHS = ["03-31", "06-30", "09-30", "12-31"]
XDR_SOURCE_NOTE = ("IMF 'Currency units per SDR' monthly archive (rms_mth.aspx), "
                   "average of daily rates in Mar/Jun/Sep/Dec")
IMF_URL = "https://www.imf.org/external/np/fin/data/rms_mth.aspx"
UA_HEADER = {"User-Agent": "RCFH-Advisory DFI tracker (contact: rosshegtvedt@gmail.com)"}


def read_existing_xdr() -> dict[int, float]:
    """XDR rows already in fx_rates.csv — kept so we never re-fetch history."""
    if not OUT_PATH.exists():
        return {}
    with open(OUT_PATH, newline="", encoding="utf-8-sig") as f:
        return {int(r["year"]): float(r["usd_per_unit"])
                for r in csv.DictReader(f) if r["currency"] == "XDR"}


def fetch_xdr_year(year: int) -> float | None:
    """Average the IMF's daily USD-per-SDR values across four sample months."""
    values = []
    for month_day in XDR_SAMPLE_MONTHS:
        resp = requests.get(
            IMF_URL, headers=UA_HEADER, timeout=60,
            params={"SelectDate": f"{year}-{month_day}", "reportType": "CVSDR",
                    "tsvflag": "Y"})
        resp.raise_for_status()
        for line in resp.text.splitlines():
            if line.startswith("U.S. dollar"):
                values += [float(v) for v in line.split("\t")[1:] if v.strip()]
        time.sleep(0.6)
    return sum(values) / len(values) if values else None


def main():
    rows = []
    for currency in CURRENCIES:
        print(f"Fetching {currency}/USD daily rates from frankfurter.app...")
        averages = fetch_annual_averages(currency)
        for year, rate in averages.items():
            rows.append({"currency": currency, "year": year,
                         "usd_per_unit": round(rate, 6), "source": SOURCE_NOTE})
        print(f"  {currency}: {len(averages)} years "
              f"({min(averages)}-{max(averages)})")
        time.sleep(1)

    xdr = read_existing_xdr()
    current_year = date.today().year
    for year in range(XDR_START_YEAR, current_year + 1):
        if year in xdr and year != current_year:  # current year refreshed each run
            continue
        print(f"Fetching XDR/USD {year} from IMF archive...")
        rate = fetch_xdr_year(year)
        if rate is not None:
            xdr[year] = round(rate, 6)
    for year, rate in sorted(xdr.items()):
        rows.append({"currency": "XDR", "year": year,
                     "usd_per_unit": rate, "source": XDR_SOURCE_NOTE})
    print(f"  XDR: {len(xdr)} years ({min(xdr)}-{max(xdr)})")

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["currency", "year", "usd_per_unit", "source"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rates to {OUT_PATH.name}")


if __name__ == "__main__":
    main()
