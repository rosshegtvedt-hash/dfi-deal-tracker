"""
scrapers/proparco.py — loads Proparco (AFD Group's private-sector arm) from
AFD's open-data portal.

Source: the "Données de l'aide au développement de Proparco" dataset on
opendata.afd.fr, fetched through the Opendatasoft export API as
semicolon-delimited UTF-8 (with BOM). No API key. The source refreshes
roughly monthly, so the loader fetches it live each run — nothing to update
by hand.

Proparco does NOT publish to IATI (AFD's own IATI feed, FR-3, contains only
a handful of activities that even mention Proparco), which is why this
loader reads AFD's open-data portal instead of reusing scrapers/iati_common.

Run:
    python -m scrapers.proparco

======================= CRITICAL COVERAGE CAVEAT ===========================
This dataset covers ONLY projects signed since 1 January 2014, AND only
those for which the client granted disclosure authorisation. It is therefore
SYSTEMATICALLY INCOMPLETE in a way the other institutions' feeds are not:
deals whose clients declined publication simply do not appear, at any size.

Proparco totals from this database are a FLOOR, never a complete picture,
and must never be compared like-for-like with IFC / EBRD / AfDB totals
without stating this. (One 2009 signature does appear despite the stated
2014 cut-off; it is loaded as disclosed and logged.)
============================================================================

Column mapping (French source -> our schema):
    titre_du_projet                       -> project_name
    resume_du_projet, else
      description_du_projet               -> description
    pays_de_realisation                   -> country (French; every spelling
                                             gets an explicit row in
                                             country_mapping.csv — nothing is
                                             fuzzy-matched)
    secteur_s_concerne_s_par_le_projet    -> sector (French free text; likewise
                                             mapped explicitly)
    montant_du_financement_en_euro        -> amount_original, currency 'EUR',
                                             converted via fx.py on the
                                             signature year
    date_de_signature                     -> approval_date (signature date)
    type_de_financement_1                 -> instrument (French, kept as the
                                             source's own terms)
    etat_en_cours_ou_cloture              -> status (only 186 of 899 rows
                                             carry one; the rest stay NULL)
    nom_du_client                         -> sponsor
    ces                                   -> es_category (see below)
    lien_vers_la_fiche_projet             -> source_url

es_category: `ces` is confirmed to be Proparco's environmental & social
categorisation — its values spell it out ("IF-B : projet à risque E&S
modéré", "A : projet à risque E&S très élevé"). The loader keeps the code
before the colon (A, B+, B, C, IF-A, IF-B, IF-C, Z, "Pas de classement")
and leaves the French wording out. Two rows contain free-text commentary
instead of a category; those are stored NULL and logged rather than guessed.

AMOUNTS — one row in the source is not euros. Activity CUG110502 (Centenary
Bank EURIZ guarantee, Uganda) carries 20,040,609,850 in the euro column,
which alone would be 56% of Proparco's whole total and larger than the
institution's annual commitments. The source's own text gives it away:
description_du_projet reads "une garantie EURIZ de 5 millions d'UGX
(20 millions d'euros)" — i.e. a EUR 20 MILLION guarantee recorded as EUR
20 billion, the amount evidently left in Ugandan shillings.

Because the source is self-contradictory about the true figure (it cites
both "5 millions d'UGX" and "20 millions d'euros"), the loader does NOT
correct the number — it stores NULL and logs 'implausible_amount' with the
original value preserved. The test is a magnitude threshold rather than a
hardcoded row id: Proparco's largest genuine financing here is EUR 156m, so
anything above IMPLAUSIBLE_AMOUNT_EUR is a units error, not a megadeal.

FISEA note: organisme_financeur is Proparco/PROPARCO on 891 rows and FISEA
(the Africa-focused fund Proparco manages) on the remaining 8. All are
loaded under 'Proparco'.
"""

import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import get_connection, log_quality_issue, utc_now  # noqa: E402
from fx import to_usd  # noqa: E402

INSTITUTION = "Proparco"
DATA_URL = ("https://opendata.afd.fr/api/explore/v2.1/catalog/datasets/"
            "donnees-de-laide-au-developpement-de-proparco/exports/csv"
            "?limit=-1&delimiter=%3B")
DATASET_PAGE = ("https://opendata.afd.fr/explore/dataset/"
                "donnees-de-laide-au-developpement-de-proparco/")
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
UA_HEADER = {"User-Agent": "RCFH-Advisory DFI tracker (contact: rosshegtvedt@gmail.com)"}

# Guard against a truncated export (the full dataset is ~899 rows).
MIN_EXPECTED_ROWS = 500

# Proparco's largest genuine single financing in this dataset is EUR 156m;
# anything an order of magnitude beyond that is a currency/units error, not
# a real commitment. See the AMOUNTS note above.
IMPLAUSIBLE_AMOUNT_EUR = 500_000_000

# Accepted E&S category codes (the part before " : " in the `ces` column).
ES_CATEGORY_RE = re.compile(r"^(A|B\+|B|C|Z|IF-A|IF-B|IF-C)$")
ES_NOT_CLASSIFIED = "pas de classement"

# The dataset states coverage from this date; earlier rows are flagged.
COVERAGE_START = "2014-01-01"


def download() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / f"proparco_opendata_{date.today().isoformat()}.csv"
    print(f"Downloading {DATA_URL}")
    resp = requests.get(DATA_URL, headers=UA_HEADER, timeout=300)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"Saved {len(resp.content):,} bytes to {dest.name}")
    return dest


def clean(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    value = str(value).strip()
    return None if value in ("", "nan", "None") else value


def parse_es_category(value):
    """Return (category_or_None, note_or_None). `ces` looks like
    'IF-B : projet à risque E&S modéré'; keep only the code."""
    value = clean(value)
    if value is None:
        return None, None  # simply not disclosed — not an anomaly worth logging
    code = value.split(":")[0].strip()
    if ES_CATEGORY_RE.match(code):
        return code, None
    if code.lower() == ES_NOT_CLASSIFIED:
        return code, None
    return None, (f"`ces` value {value[:120]!r} is not an E&S category code; "
                  "es_category left NULL rather than guessed")


def load(path: Path) -> None:
    # Opendatasoft exports UTF-8 with a BOM; utf-8-sig strips it.
    df = pd.read_csv(path, sep=";", dtype=str, encoding="utf-8-sig")
    if len(df) < MIN_EXPECTED_ROWS:
        raise SystemExit(
            f"Only {len(df)} rows in {path.name} — the export looks truncated. "
            "Refusing to load; check DATA_URL before rerunning.")
    print(f"{len(df)} records in export")

    conn = get_connection()
    scraped_at = utc_now()
    inserted = issues = 0
    seen_concours = set()
    try:
        conn.execute("DELETE FROM projects WHERE institution = ?", (INSTITUTION,))
        conn.execute("DELETE FROM quality_issues WHERE institution = ?", (INSTITUTION,))

        for _, row in df.iterrows():
            raw = {k: (str(v)[:300] if pd.notna(v) else None) for k, v in row.items()}
            name = clean(row.get("titre_du_projet"))
            if name is None:
                log_quality_issue(conn, INSTITUTION, None, "missing_project_name",
                                  "titre_du_projet is blank", raw)
                issues += 1

            # --- country / sector: stored raw, mapped explicitly in the CSVs
            country = clean(row.get("pays_de_realisation"))
            if country is None:
                log_quality_issue(conn, INSTITUTION, name, "missing_country",
                                  "pays_de_realisation is blank", raw)
                issues += 1
            sector = clean(row.get("secteur_s_concerne_s_par_le_projet"))
            if sector is None:
                log_quality_issue(conn, INSTITUTION, name, "missing_sector",
                                  "secteur_s_concerne_s_par_le_projet is blank", raw)
                issues += 1

            # --- signature date ---------------------------------------------
            approval_date = clean(row.get("date_de_signature"))
            if approval_date is None:
                log_quality_issue(conn, INSTITUTION, name, "unparseable_date",
                                  "date_de_signature is blank", raw)
                issues += 1
            else:
                approval_date = approval_date[:10]
                if approval_date > date.today().isoformat():
                    log_quality_issue(
                        conn, INSTITUTION, name, "future_dated_signature",
                        f"date_de_signature {approval_date} is in the future; "
                        "loaded as disclosed", raw)
                    issues += 1
                elif approval_date < COVERAGE_START:
                    log_quality_issue(
                        conn, INSTITUTION, name, "outside_stated_coverage",
                        f"date_de_signature {approval_date} predates the dataset's "
                        "stated 2014-01-01 coverage start; loaded as disclosed", raw)
                    issues += 1

            # --- amount ------------------------------------------------------
            amount = clean(row.get("montant_du_financement_en_euro"))
            amount_usd = None
            if amount is None:
                log_quality_issue(conn, INSTITUTION, name, "missing_amount",
                                  "montant_du_financement_en_euro is blank", raw)
                issues += 1
            else:
                amount = float(amount)
                if amount > IMPLAUSIBLE_AMOUNT_EUR:
                    log_quality_issue(
                        conn, INSTITUTION, name, "implausible_amount",
                        f"montant_du_financement_en_euro is {amount:,.0f} EUR — far "
                        "beyond Proparco's largest genuine financing here (EUR 156m) "
                        "and evidently a local-currency figure left in the euro "
                        "column. Amount stored as NULL rather than corrected; the "
                        "original value is preserved in this record.", raw)
                    issues += 1
                    amount = None
                else:
                    year = int(approval_date[:4]) if approval_date else None
                    amount_usd, fx_note = to_usd(amount, "EUR", year)
                    if fx_note and amount_usd is None:
                        log_quality_issue(conn, INSTITUTION, name, "fx_rate_missing",
                                          fx_note, raw)
                        issues += 1
                    elif fx_note:
                        log_quality_issue(conn, INSTITUTION, name,
                                          "fx_rate_approximated", fx_note, raw)
                        issues += 1

            # --- E&S category -------------------------------------------------
            es_category, es_note = parse_es_category(row.get("ces"))
            if es_note:
                log_quality_issue(conn, INSTITUTION, name, "unresolved_es_category",
                                  es_note, raw)
                issues += 1

            # --- one financing facility should appear once ---------------------
            concours = clean(row.get("id_concours"))
            if concours and concours in seen_concours:
                log_quality_issue(
                    conn, INSTITUTION, name, "duplicate_financing_id",
                    f"id_concours {concours} appears on more than one row; all rows "
                    "kept", raw)
                issues += 1
            if concours:
                seen_concours.add(concours)

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
                    None,   # region: canonical_region comes from country harmonization
                    sector,
                    None,
                    clean(row.get("type_de_financement_1")),
                    amount,
                    "EUR" if amount is not None else None,
                    amount_usd,
                    approval_date,
                    None,
                    clean(row.get("etat_en_cours_ou_cloture")),
                    es_category,
                    clean(row.get("nom_du_client")),
                    clean(row.get("resume_du_projet"))
                    or clean(row.get("description_du_projet")),
                    clean(row.get("lien_vers_la_fiche_projet")) or DATASET_PAGE,
                    scraped_at,
                ),
            )
            inserted += 1

        conn.commit()
    finally:
        conn.close()

    print(f"Inserted {inserted} Proparco financings ({issues} quality issues logged).")


if __name__ == "__main__":
    load(download())
