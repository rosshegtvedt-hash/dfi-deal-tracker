"""
harmonize.py — applies the mapping CSVs that translate each institution's own
labels into canonical taxonomies:
  * sector_mapping.csv  : institution + sector label -> canonical_sector
                          (+ optional canonical_subsector)
  * country_mapping.csv : country label -> canonical_country + canonical_region
                          (institution-agnostic — 'Turkiye', 'Türkiye' and
                          'Turkey' all become 'Türkiye')
  * instrument_mapping.csv : institution + instrument label -> one or MORE
                          canonical instruments, written to the
                          project_instruments child table

Run after any loader:
    python harmonize.py

How it works, in plain language:
  * The CSVs are the single source of truth — edit them in Excel or a text
    editor, then rerun this script. No code changes needed.
  * Any label found in the database but NOT in its CSV is reported here and
    logged to quality_issues ('unmapped_sector' / 'unmapped_country', one
    issue per distinct label, not per project), so new labels from future
    data releases can't slip through unnoticed.
  * Projects whose source field is blank get 'Unclassified' so they remain
    visible in charts rather than vanishing.

Instruments differ from the other two in three ways, all deliberate:
  * they are one-to-MANY. EBRD's "Debt + Equity" is evidence for senior debt
    AND equity, so the mapping CSV carries one row per canonical value and
    the result goes to the project_instruments child table, not a column.
  * `projects.instrument` keeps the raw source value and is never modified.
  * a BLANK canonical cell means "we looked at this and deliberately did not
    map it" and is NOT logged; a raw value ABSENT from the CSV means "never
    seen before" and IS logged. Collapsing those two would hide new labels
    behind old decisions, so read_instrument_mapping() keeps blank keys
    present with an empty list.

Instruments also have a second, narrower input:
  * instrument_overrides.csv : institution + source_url -> canonical
    instruments for ONE named deal, applied after the label mapping.
    It exists because some sources publish an instrument field that says
    nothing ("Not Specified", "Fund") while the project description names the
    instrument plainly. Overriding is per-deal and hand-reviewed; where it
    contradicts a conclusion the label mapping already reached, the run says
    so and logs 'instrument_overridden' rather than swapping values silently.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection, log_quality_issue

MAPPING_CSV = Path(__file__).parent / "sector_mapping.csv"
COUNTRY_CSV = Path(__file__).parent / "country_mapping.csv"
INSTRUMENT_CSV = Path(__file__).parent / "instrument_mapping.csv"
INSTRUMENT_OVERRIDE_CSV = Path(__file__).parent / "instrument_overrides.csv"
ES_CATEGORY_CSV = Path(__file__).parent / "es_category_mapping.csv"

# The whole instrument vocabulary, in one place. Both instrument CSVs are
# checked against it, so a typo cannot quietly mint a sixth instrument and
# split every instrument chart in two.
#
# Adding a value here is a bigger decision than it looks: this vocabulary is
# shared with the DFI Mandate Match project, whose mandate rules match on
# these exact strings. Candidates already discussed and NOT adopted are
# 'Non-senior debt' (only four deals state it in an instrument field, while
# ~200 announce it in their project name, so the category would look measured
# while being ~2% populated) and 'Fund participation' (a real gap, ~12 deals,
# but still a two-project decision). See data_dictionary.md.
CANONICAL_INSTRUMENTS = (
    "Senior debt",
    "Equity",
    "Guarantee",
    "Political risk insurance",
    "Technical assistance / grant",
)

_CANONICAL_BY_LOWER = {value.lower(): value for value in CANONICAL_INSTRUMENTS}


def canonical_instrument(value: str, where: str) -> str:
    """Normalise one canonical instrument value, or stop the run.

    Case is forgiven — "Senior Debt" becomes "Senior debt" — because these
    CSVs are edited by hand in Excel and capitalisation drift is not a
    decision anyone made. An unrecognised value is not forgiven: it is either
    a typo or an unannounced change to a shared vocabulary, and both should
    be seen rather than absorbed.
    """
    normalised = _CANONICAL_BY_LOWER.get(value.strip().lower())
    if normalised is None:
        raise ValueError(
            f"{where}: {value!r} is not a canonical instrument. Expected one of: "
            f"{', '.join(CANONICAL_INSTRUMENTS)}. Fix the spelling — or, if the "
            "vocabulary really is meant to grow, add the value to "
            "CANONICAL_INSTRUMENTS in harmonize.py and check "
            "../DFI Mandate Match/mandate_rules.csv, which matches on these "
            "same strings.")
    return normalised


def read_mapping() -> dict:
    """Load the CSV into {(institution, source_sector): (sector, subsector)}."""
    mapping = {}
    with open(MAPPING_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row["institution"].strip(), row["source_sector"].strip())
            subsector = row["canonical_subsector"].strip() or None
            mapping[key] = (row["canonical_sector"].strip(), subsector)
    return mapping


def read_country_mapping() -> dict:
    """Load country_mapping.csv into {source_country: (country, region)}."""
    mapping = {}
    with open(COUNTRY_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            mapping[row["source_country"].strip()] = (
                row["canonical_country"].strip(), row["canonical_region"].strip())
    return mapping


def harmonize_countries(conn):
    """Apply country_mapping.csv; returns (mapped_count, unmapped_labels)."""
    conn.execute("UPDATE projects SET canonical_country = NULL, canonical_region = NULL")
    conn.execute("DELETE FROM quality_issues WHERE issue_type = 'unmapped_country'")

    mapped = 0
    for source, (country, region) in read_country_mapping().items():
        cur = conn.execute(
            "UPDATE projects SET canonical_country = ?, canonical_region = ? "
            "WHERE country = ?",
            (country, region, source),
        )
        mapped += cur.rowcount

    conn.execute(
        "UPDATE projects SET canonical_country = 'Unclassified', "
        "canonical_region = 'Unclassified' WHERE country IS NULL"
    )

    unmapped = conn.execute(
        "SELECT institution, country, COUNT(*) FROM projects "
        "WHERE canonical_country IS NULL GROUP BY institution, country"
    ).fetchall()
    for institution, country, n in unmapped:
        log_quality_issue(
            conn, institution, None, "unmapped_country",
            f"Country label {country!r} ({n} projects) has no row in country_mapping.csv",
        )
    return mapped, unmapped


def read_instrument_mapping() -> dict:
    """Load instrument_mapping.csv into {(institution, raw): [canonical, ...]}.

    Several CSV rows can share one (institution, raw) key — that is how a
    combined instrument like "Debt + Equity" produces two canonical values.

    The empty list matters: a key present with no canonical values means the
    label was reviewed and deliberately left unmapped, which is a different
    thing from a key that is absent because the label has never been seen.
    Only the absent case is worth telling anyone about.
    """
    mapping: dict = {}
    with open(INSTRUMENT_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            institution = (row["institution"] or "").strip()
            raw = (row["raw_instrument"] or "").strip()
            canonical = (row["canonical_instrument"] or "").strip()
            if not institution or not raw:
                continue
            mapping.setdefault((institution, raw), [])
            if canonical:
                value = canonical_instrument(
                    canonical, f"instrument_mapping.csv, {institution} {raw!r}")
                if value not in mapping[(institution, raw)]:
                    mapping[(institution, raw)].append(value)
    return mapping


def read_instrument_overrides() -> dict:
    """Load instrument_overrides.csv into {(institution, source_url): [canonical]}.

    Per-DEAL decisions, for projects whose instrument field is uninformative
    ("Not Specified", "Fund") while the published description names the
    instrument plainly. Reviewed by hand, one row per canonical value, same
    one-to-many shape as the label mapping.

    Keyed on source_url, not projects.id: ids are handed out afresh every time
    a loader replaces its institution's rows, so an id-keyed override would
    silently attach itself to a different deal after the next refresh.

    Blank vs absent works as it does everywhere else here: a row with a blank
    canonical means "this specific deal was reviewed and deliberately left
    unmapped" and is silent; a deal with no row at all is simply untouched.
    """
    if not INSTRUMENT_OVERRIDE_CSV.exists():
        return {}
    overrides: dict = {}
    with open(INSTRUMENT_OVERRIDE_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            institution = (row["institution"] or "").strip()
            url = (row["source_url"] or "").strip()
            canonical = (row["canonical_instrument"] or "").strip()
            if not institution or not url:
                continue
            overrides.setdefault((institution, url), [])
            if canonical:
                value = canonical_instrument(
                    canonical, f"instrument_overrides.csv, {url}")
                if value not in overrides[(institution, url)]:
                    overrides[(institution, url)].append(value)
    return overrides


def apply_instrument_overrides(conn):
    """Apply instrument_overrides.csv on top of the label mapping.

    Runs AFTER harmonize_instruments, which rebuilds the whole child table.
    Returns (changed, replaced, stale).

    Two things are deliberately noisy. If an override contradicts a value the
    label mapping already produced, that is logged as 'instrument_overridden'
    — a hand-written file quietly overruling the systematic one is exactly the
    kind of thing that should leave a trace. And if an override names a
    source_url no project carries, it is logged as
    'stale_instrument_override': the deal was probably renamed or withdrawn at
    source, and an override that matches nothing is worth knowing about rather
    than being a line in a file that does nothing.
    """
    overrides = read_instrument_overrides()
    conn.execute("DELETE FROM quality_issues WHERE issue_type = 'instrument_overridden'")
    conn.execute(
        "DELETE FROM quality_issues WHERE issue_type = 'stale_instrument_override'")

    changed, replaced, stale = 0, [], []
    for (institution, url), values in sorted(overrides.items()):
        rows = conn.execute(
            "SELECT id FROM projects WHERE institution = ? AND source_url = ?",
            (institution, url)).fetchall()
        if not rows:
            stale.append((institution, url))
            log_quality_issue(
                conn, institution, None, "stale_instrument_override",
                f"instrument_overrides.csv carries a row for {url}, but no "
                "project has that source_url. The deal may have been renamed or "
                "withdrawn at source; this override currently does nothing.")
            continue
        for row in rows:
            previous = [r[0] for r in conn.execute(
                "SELECT canonical_instrument FROM project_instruments "
                "WHERE project_id = ? ORDER BY canonical_instrument",
                (row["id"],)).fetchall()]
            if previous == sorted(values):
                continue                    # override agrees; nothing to do
            if previous:
                replaced.append((institution, url, previous, sorted(values)))
                log_quality_issue(
                    conn, institution, None, "instrument_overridden",
                    f"{url}: instrument_mapping.csv produced "
                    f"{previous}, overridden to {sorted(values) or 'nothing'} "
                    "by instrument_overrides.csv.")
            conn.execute("DELETE FROM project_instruments WHERE project_id = ?",
                         (row["id"],))
            for value in values:
                conn.execute(
                    "INSERT OR IGNORE INTO project_instruments "
                    "(project_id, canonical_instrument) VALUES (?, ?)",
                    (row["id"], value))
            changed += 1
    return changed, replaced, stale


def read_es_category_mapping() -> dict:
    """{(institution, raw): canonical_or_None} from es_category_mapping.csv.

    E&S is ONE-TO-ONE, unlike instruments: one raw grade means exactly one
    risk level, so this returns a value rather than a list and the result is
    written to a column on projects. The blank-vs-absent distinction is the
    same though — None means "reviewed, deliberately unmapped" and stays
    quiet; a key that is missing entirely gets reported.
    """
    mapping: dict = {}
    with open(ES_CATEGORY_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            institution = (row["institution"] or "").strip()
            raw = (row["raw_es_category"] or "").strip()
            canonical = (row["canonical_es_category"] or "").strip()
            if not institution or not raw:
                continue
            mapping[(institution, raw)] = canonical or None
    return mapping


def harmonize_es_categories(conn):
    """Fill canonical_es_category. Returns (mapped, unmapped)."""
    mapping = read_es_category_mapping()
    conn.execute("UPDATE projects SET canonical_es_category = NULL")
    conn.execute("DELETE FROM quality_issues WHERE issue_type = 'unmapped_es_category'")

    mapped = 0
    unmapped: dict = {}
    for row in conn.execute(
            "SELECT id, institution, es_category FROM projects "
            "WHERE es_category IS NOT NULL AND TRIM(es_category) <> ''").fetchall():
        key = (row["institution"], (row["es_category"] or "").strip())
        if key not in mapping:
            unmapped[key] = unmapped.get(key, 0) + 1
            continue
        canonical = mapping[key]
        if canonical is None:       # deliberately unmapped — silent by design
            continue
        conn.execute("UPDATE projects SET canonical_es_category = ? WHERE id = ?",
                     (canonical, row["id"]))
        mapped += 1

    for (institution, raw), n in sorted(unmapped.items()):
        log_quality_issue(
            conn, institution, None, "unmapped_es_category",
            f"E&S category {raw!r} ({n} projects) has no row in "
            "es_category_mapping.csv")
    return mapped, unmapped


# Four institutions carry no instrument at all. These findings come from
# checking each source directly (2026-08-17) and are re-logged on every run,
# but ONLY for institutions that still have zero instrument coverage — so if a
# loader is later taught to capture the field, the issue disappears by itself.
# Each says where we looked, so "the source does not publish it" is never
# confused with "our loader does not collect it".
NO_INSTRUMENT_SOURCES = {
    "AfDB": (
        "No instrument recorded. The MapAfrica bulk export this loader reads has "
        "no instrument-like column at all (its 29 columns cover sector, status, "
        "dates, amounts, safeguards and funding window). Absent from the source "
        "we read; whether AfDB publishes instrument elsewhere has not been "
        "established."),
    "BII": (
        "No instrument recorded. IATI carries instrument in the finance-type "
        "fields, and BII leaves them empty: default-finance-type-code and "
        "transaction_finance-type_code are blank on all 2,926 transactions, "
        "though BII does populate flow-type and aid-type. Absent from the source "
        "we read; bii.co.uk could not be checked because it returns HTTP 403 to "
        "automated requests."),
    "EIB Global": (
        "No instrument recorded. The loans/list service returns only country, "
        "region and sector tags per loan part, and the public project page "
        "(eib.org/en/projects/loans/all/<id>) gives total cost and signature "
        "amounts but names no finance type. Absent from both the service and the "
        "project page."),
    "FMO": (
        "No instrument recorded. Checked directly: neither the world-map card nor "
        "the project-detail page names an instrument. The detail page's "
        "structured fields are region, country, sector, publication date, "
        "effective date, total FMO financing, funding fund and E&S category. "
        "This is NOT a gap in our loader for instrument. Note separately that the "
        "detail page DOES publish an E&S category, which this loader does not "
        "capture — that one is a loader gap."),
}


# Institutions carrying no E&S grade at all. Checked directly 2026-08-18.
# Re-logged each run, but only while the institution still has zero coverage.
NO_ES_SOURCES = {
    "EBRD": (
        "No E&S category recorded. The investments-overview spreadsheet this "
        "loader reads has ten columns and none of them is an E&S category. EBRD "
        "does publish per-project Project Summary Documents, which this loader "
        "does not fetch — so this is very likely OUR GAP rather than EBRD "
        "withholding it. Not stated as 'not disclosed': an attempt to confirm the "
        "PSD page format returned HTTP 404 on the URL tried, so the PSD's exact "
        "contents were not verified here."),
    "ADB": (
        "No E&S category recorded. The Nonsovereign Products spreadsheet this "
        "loader reads has no safeguard or category column. ADB publishes "
        "safeguard categories on its per-project pages, which this loader does "
        "not fetch and which could not be checked here because adb.org returns "
        "HTTP 403 to automated requests. Treat as OUR GAP, unconfirmed."),
    "BII": (
        "No E&S category recorded. BII is loaded from IATI, and the IATI activity "
        "standard has no environmental & social category element at all — there "
        "is no field for BII to populate. Absent from the source we read; whether "
        "BII publishes a grade elsewhere was not established (bii.co.uk returns "
        "HTTP 403 to automated requests)."),
    "EIB Global": (
        "No E&S category recorded, and none published in structured form. The "
        "loans/list service returns only country, region and sector tags, and the "
        "public project page carries an Environmental and Social Data Sheet "
        "document plus an 'Environmental aspects' prose section but states no "
        "category. Verified on a project page directly."),
}


def flag_institutions_without_es_categories(conn):
    """Record why an institution has no E&S data. Returns the list."""
    conn.execute("DELETE FROM quality_issues "
                 "WHERE issue_type = 'es_category_absent_from_source'")
    flagged = []
    for institution, finding in sorted(NO_ES_SOURCES.items()):
        has_any = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE institution = ? "
            "AND es_category IS NOT NULL AND TRIM(es_category) <> ''",
            (institution,)).fetchone()[0]
        if has_any:
            continue
        log_quality_issue(conn, institution, None,
                          "es_category_absent_from_source", finding)
        flagged.append(institution)
    return flagged


def flag_institutions_without_instruments(conn):
    """Record why an institution has no instrument data. Returns the list."""
    conn.execute("DELETE FROM quality_issues "
                 "WHERE issue_type = 'instrument_absent_from_source'")
    flagged = []
    for institution, finding in sorted(NO_INSTRUMENT_SOURCES.items()):
        has_any = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE institution = ? "
            "AND instrument IS NOT NULL AND TRIM(instrument) <> ''",
            (institution,)).fetchone()[0]
        if has_any:
            continue        # a loader now captures it; the finding is stale
        log_quality_issue(conn, institution, None,
                          "instrument_absent_from_source", finding)
        flagged.append(institution)
    return flagged


def harmonize_instruments(conn):
    """Rebuild project_instruments from the CSV.

    Returns (rows_written, unmapped) where unmapped maps
    (institution, raw label) -> number of projects carrying it.
    """
    mapping = read_instrument_mapping()

    # Own only these: the child table in full, and the issues this run raises.
    conn.execute("DELETE FROM project_instruments")
    conn.execute("DELETE FROM quality_issues WHERE issue_type = 'unmapped_instrument'")

    unmapped: dict = {}
    for row in conn.execute(
            "SELECT id, institution, instrument FROM projects "
            "WHERE instrument IS NOT NULL AND TRIM(instrument) <> ''").fetchall():
        key = (row["institution"], (row["instrument"] or "").strip())
        if key not in mapping:
            unmapped[key] = unmapped.get(key, 0) + 1
            continue
        for canonical in mapping[key]:      # empty list -> nothing written
            conn.execute(
                "INSERT OR IGNORE INTO project_instruments "
                "(project_id, canonical_instrument) VALUES (?, ?)",
                (row["id"], canonical))

    for (institution, raw), n in sorted(unmapped.items()):
        log_quality_issue(
            conn, institution, None, "unmapped_instrument",
            f"Instrument label {raw!r} ({n} projects) has no row in "
            "instrument_mapping.csv")

    written = conn.execute("SELECT COUNT(*) FROM project_instruments").fetchone()[0]
    return written, unmapped


def main():
    mapping = read_mapping()
    conn = get_connection()

    # Start from a clean slate so removed CSV rows don't leave stale values,
    # and clear previous unmapped_sector issues (this run re-detects them).
    conn.execute("UPDATE projects SET canonical_sector = NULL, canonical_subsector = NULL")
    conn.execute("DELETE FROM quality_issues WHERE issue_type = 'unmapped_sector'")

    mapped = 0
    for (institution, source_sector), (sector, subsector) in mapping.items():
        cur = conn.execute(
            "UPDATE projects SET canonical_sector = ?, canonical_subsector = ? "
            "WHERE institution = ? AND sector = ?",
            (sector, subsector, institution, source_sector),
        )
        mapped += cur.rowcount

    # Blank source sector -> 'Unclassified' (kept visible, not hidden).
    cur = conn.execute(
        "UPDATE projects SET canonical_sector = 'Unclassified' WHERE sector IS NULL"
    )
    unclassified = cur.rowcount

    # Anything still NULL has a sector label missing from the CSV.
    unmapped = conn.execute(
        "SELECT institution, sector, COUNT(*) FROM projects "
        "WHERE canonical_sector IS NULL GROUP BY institution, sector"
    ).fetchall()
    for institution, sector, n in unmapped:
        log_quality_issue(
            conn, institution, None, "unmapped_sector",
            f"Sector label {sector!r} ({n} projects) has no row in sector_mapping.csv",
        )

    countries_mapped, countries_unmapped = harmonize_countries(conn)
    instrument_rows, instruments_unmapped = harmonize_instruments(conn)
    overridden, replaced, stale_overrides = apply_instrument_overrides(conn)
    instrument_rows = conn.execute(
        "SELECT COUNT(*) FROM project_instruments").fetchone()[0]
    es_mapped, es_unmapped = harmonize_es_categories(conn)
    no_instrument = flag_institutions_without_instruments(conn)
    no_es = flag_institutions_without_es_categories(conn)

    conn.commit()
    conn.close()

    print(f"Sectors:   harmonized {mapped} projects; "
          f"{unclassified} had no source sector (-> 'Unclassified').")
    if unmapped:
        print("UNMAPPED sector labels — add these to sector_mapping.csv:")
        for institution, sector, n in unmapped:
            print(f"  {institution}: {sector!r} ({n} projects)")
    else:
        print("           all sector labels mapped.")

    print(f"Countries: harmonized {countries_mapped} projects.")
    if countries_unmapped:
        print("UNMAPPED country labels — add these to country_mapping.csv:")
        for institution, country, n in countries_unmapped:
            print(f"  {institution}: {country!r} ({n} projects)")
    else:
        print("           all country labels mapped.")

    print(f"Instruments: wrote {instrument_rows} project_instruments rows.")
    if instruments_unmapped:
        print("UNMAPPED instrument labels — add these to instrument_mapping.csv:")
        for (institution, raw), n in sorted(instruments_unmapped.items()):
            print(f"  {institution}: {raw!r} ({n} projects)")
    else:
        print("             all instrument labels mapped.")

    print(f"             {overridden} deal(s) set from instrument_overrides.csv.")
    if replaced:
        print("             OVERRODE a label-mapped value (logged as "
              "'instrument_overridden'):")
        for institution, url, previous, values in replaced:
            print(f"               {institution}: {url}")
            print(f"                 {previous} -> {values or 'nothing'}")
    if stale_overrides:
        print("             STALE overrides — no project carries these URLs:")
        for institution, url in stale_overrides:
            print(f"               {institution}: {url}")

    print(f"E&S:       harmonized {es_mapped} projects.")
    if es_unmapped:
        print("UNMAPPED E&S categories — add these to es_category_mapping.csv:")
        for (institution, raw), n in sorted(es_unmapped.items()):
            print(f"  {institution}: {raw!r} ({n} projects)")
    else:
        print("           all E&S categories mapped.")

    if no_es:
        print("           no E&S category from: " + ", ".join(no_es)
              + " (see quality_issues 'es_category_absent_from_source')")

    if no_instrument:
        print("             no instrument published by: "
              + ", ".join(no_instrument)
              + " (see quality_issues 'instrument_absent_from_source')")


if __name__ == "__main__":
    main()
