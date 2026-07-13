"""
fx.py — converts amounts to US dollars using the rates in fx_rates.csv.

Usage from a loader:
    from fx import to_usd
    amount_usd, note = to_usd(1_000_000, "EUR", 2015)

Returns (amount_usd, note):
    note is None            -> exact year rate was used
    note is a string        -> a fallback was applied (log it as a quality
                               issue so the approximation is never silent)
    amount_usd is None      -> no rate exists for that currency at all
"""

import csv
from pathlib import Path

RATES_CSV = Path(__file__).parent / "fx_rates.csv"

_rates: dict[str, dict[int, float]] | None = None


def _load() -> dict[str, dict[int, float]]:
    global _rates
    if _rates is None:
        _rates = {}
        with open(RATES_CSV, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                _rates.setdefault(row["currency"].strip().upper(), {})[
                    int(row["year"])] = float(row["usd_per_unit"])
    return _rates


def to_usd(amount, currency, year):
    """Convert amount to USD using the annual average rate for `year`."""
    if amount is None:
        return None, None
    currency = (currency or "").strip().upper()
    if currency == "USD":
        return float(amount), None

    rates = _load().get(currency)
    if not rates:
        return None, f"no {currency}/USD rates in fx_rates.csv"

    if year in rates:
        return float(amount) * rates[year], None

    # Fallbacks: years before our rate history (e.g. pre-1999, before the
    # euro) use the earliest rate; missing/future years use the latest.
    if year is not None and year < min(rates):
        used = min(rates)
    else:
        used = max(rates)
    return (float(amount) * rates[used],
            f"no {currency}/USD rate for year {year}; used {used} annual average")
