"""test_mobilisation.py — proves mobilised capital stays out of the totals.

Run:
    python test_mobilisation.py

Mobilisation is third-party money raised alongside a DFI's own commitment.
It is the single easiest number in this database to add to the wrong total:
doing so would inflate IDB Invest by $28bn and would look entirely plausible.
This suite guards the two rules that stop that.

Checks:
  1. USD mobilisation passes through untouched;
  2. a local-currency figure is converted at the DEAL's own rate, not a rate
     looked up separately, so the pair can never disagree;
  3. it is NULL - never an unconverted number - when there is no rate to
     reuse, no currency, or nothing to convert;
  4. a known-value regression on the Cardal B Bond, the deal that raised
     the question: own account $14.0m, mobilised $55.5m, kept apart;
  5. and a zero is preserved as a zero ("reported, none"), which is not the
     same thing as absent.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scrapers.idbinvest import mobilised_in_usd  # noqa: E402
from database import DB_PATH  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        if detail:
            print(f"          {detail}")
        failures.append(label)


def main():
    print("\n1. USD passes through")
    check("5,000,000 USD stays 5,000,000",
          mobilised_in_usd(5_000_000, "USD", 1_000_000, 1_000_000) == 5_000_000)

    print("\n2. local currency uses the deal's own rate")
    # The deal: 200 local = 10 USD, so the rate is 0.05. 100 local -> 5 USD.
    check("100 local at the deal's 0.05 rate -> 5",
          mobilised_in_usd(100, "MXN", 200, 10) == 5)
    check("the rate really is the deal's, not a constant",
          mobilised_in_usd(100, "MXN", 400, 10) == 2.5,
          "a different deal rate must give a different answer")

    print("\n3. NULL rather than an unconverted number")
    check("no rate to reuse -> None", mobilised_in_usd(100, "MXN", None, None) is None)
    check("deal amount present but unconverted -> None",
          mobilised_in_usd(100, "MXN", 200, None) is None)
    check("no currency -> None", mobilised_in_usd(100, None, 200, 10) is None)
    check("nothing to convert -> None", mobilised_in_usd(None, "USD", 1, 1) is None)

    if not Path(DB_PATH).exists():
        print("\n(4 and 5 need the real database; skipped)")
    else:
        conn = sqlite3.connect(DB_PATH)
        print("\n4. mobilisation is not inside the commitment totals")
        # A known-value regression on the deal that raised the question in
        # the first place. IDB Invest's own account on the Cardal-Punta del
        # Tigre B Bond is USD 14,000,000; the mobilised B tranche is USD
        # 55,539,300. If a future change ever folds the two together this row
        # becomes 69,539,300 and this check fails loudly.
        row = conn.execute(
            "SELECT amount_usd, mobilised_usd FROM projects "
            "WHERE source_url LIKE '%cardal-punta-del-tigre%'").fetchone()
        check("the Cardal B Bond books only IDB Invest's own $14.0m",
              row is not None and abs((row[0] or 0) - 14_000_000) < 1,
              f"got {row}")
        check("with the $55.5m B tranche recorded separately",
              row is not None and abs((row[1] or 0) - 55_539_300) < 1,
              f"got {row}")
        rows, mob, own = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(mobilised_usd),0), COALESCE(SUM(amount_usd),0) "
            "FROM projects WHERE mobilised_usd > 0").fetchone()
        check("and mobilisation is reported on many deals, not just that one",
              rows > 100, f"rows reporting mobilisation: {rows}")
        print(f"        {rows} projects, ${mob/1e9:,.2f}bn mobilised "
              f"against ${own/1e9:,.2f}bn own")

        print("\n5. a reported zero is kept as zero, not blanked")
        zeros = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE mobilised_original = 0").fetchone()[0]
        check("zeros are preserved ('reported, none' != 'not reported')", zeros > 0,
              f"rows with mobilised_original = 0: {zeros}")
        conn.close()

    if failures:
        print(f"\n{len(failures)} CHECK(S) FAILED: {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
