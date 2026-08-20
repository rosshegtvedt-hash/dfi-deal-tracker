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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection, log_quality_issue

MAPPING_CSV = Path(__file__).parent / "sector_mapping.csv"
COUNTRY_CSV = Path(__file__).parent / "country_mapping.csv"
INSTRUMENT_CSV = Path(__file__).parent / "instrument_mapping.csv"
INSTRUMENT_OVERRIDE_CSV = Path(__file__).parent / "instrument_overrides.csv"
ES_CATEGORY_CSV = Path(__file__).parent / "es_category_mapping.csv"

# The instrument vocabulary, in two levels, declared once. Both instrument
# CSVs are checked against it, so a typo cannot quietly mint a new value.
#
# FAMILY is the level every source can actually support. It says "Debt", not
# "Senior debt", and that is the point: EBRD's "Debt" and IFC's "Loan" do not
# distinguish senior from subordinated, and the old vocabulary asserted a
# seniority the sources never disclosed. Two rows proved the harm - IFC's
# "Ecobank Ghana Tier II Subordinated Debt" and EBRD's "Koudia Al Baida -
# Subordinated loan" were both stored as senior debt, and a Tier II
# instrument is subordinated by definition.
#
# Adding a family is a two-project decision: this vocabulary is shared with
# the DFI Mandate Match project. (That project reads the RAW instrument
# column and applies its own mapping, so it is decoupled from this change.)
CANONICAL_INSTRUMENTS = (
    "Debt",
    "Equity",
    "Guarantee",
    "Political risk insurance",
    "Technical assistance / grant",
)

# DETAIL is optional and is populated ONLY where a source states it. A NULL
# detail means "not disclosed" - it does NOT mean senior. Roughly 97% of rows
# have no seniority signal anywhere in their text, so NULL is the normal case
# and backfilling it with a guess would recreate the bug this replaced.
INSTRUMENT_DETAILS = {
    "Debt": ("senior", "subordinated", "mezzanine", "shareholder_loan",
             "bridge", "receivables_facility"),
    "Equity": ("common", "preferred"),
}

_CANONICAL_BY_LOWER = {value.lower(): value for value in CANONICAL_INSTRUMENTS}
_DETAILS_BY_LOWER = {d.lower(): (family, d)
                     for family, ds in INSTRUMENT_DETAILS.items() for d in ds}


def canonical_detail(value, family, where):
    """Normalise one instrument detail, or stop the run.

    Also checks the detail belongs to the family: "preferred" is an equity
    detail and "subordinated" a debt one, and crossing them is a mistake
    worth catching rather than storing.
    """
    match = _DETAILS_BY_LOWER.get(value.strip().lower())
    if match is None:
        allowed = ", ".join(sorted(_DETAILS_BY_LOWER))
        raise ValueError(
            f"{where}: {value!r} is not a known instrument detail. "
            f"Expected one of: {allowed}. Leave the cell BLANK if the source "
            "does not state it - blank means 'not disclosed', which is the "
            "honest and by far the commonest case.")
    detail_family, detail = match
    if family and detail_family != family:
        raise ValueError(
            f"{where}: detail {detail!r} belongs to family {detail_family!r}, "
            f"but the row's family is {family!r}.")
    return detail


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
            f"{where}: {value!r} is not a canonical instrument FAMILY. Expected "
            f"one of: {', '.join(CANONICAL_INSTRUMENTS)}. Note that "
            "'Senior debt' is no longer a family — seniority is a DETAIL, and "
            "only where a source states it. Fix the spelling, or add the value "
            "to CANONICAL_INSTRUMENTS in harmonize.py if the vocabulary really "
            "is meant to grow.")
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
                where = f"instrument_mapping.csv, {institution} {raw!r}"
                family = canonical_instrument(canonical, where)
                detail_cell = (row.get("canonical_detail") or "").strip()
                detail = canonical_detail(detail_cell, family, where) if detail_cell else None
                pair = (family, detail)
                if pair not in mapping[(institution, raw)]:
                    mapping[(institution, raw)].append(pair)
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
                where = f"instrument_overrides.csv, {url}"
                family = canonical_instrument(canonical, where)
                detail_cell = (row.get("canonical_detail") or "").strip()
                detail = canonical_detail(detail_cell, family, where) if detail_cell else None
                pair = (family, detail)
                if pair not in overrides[(institution, url)]:
                    overrides[(institution, url)].append(pair)
    return overrides


INSTRUMENT_DETAIL_CSV = Path(__file__).parent / "instrument_detail_rules.csv"


def read_instrument_detail_rules():
    """instrument_detail_rules.csv -> ([(phrase, detail)], [excluded phrase]).

    `exclude` rows are phrases that contain seniority words in a non-financial
    sense — "senior secondary" is a school, "junior mining" is a small-cap
    miner, "mezzanine fund" is a vehicle the DFI holds an LP interest in
    rather than mezzanine debt it extended. They are removed from the name
    before any detail is looked for.
    """
    rules, excluded = [], []
    with open(INSTRUMENT_DETAIL_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            pattern = (row["pattern"] or "").strip().lower()
            detail = (row["detail"] or "").strip().lower()
            if not pattern:
                continue
            if pattern == "exclude":
                excluded.append(detail)          # the phrase sits in `detail`
            else:
                rules.append((pattern, detail))
    rules.sort(key=lambda r: len(r[0]), reverse=True)      # longest first
    excluded.sort(key=len, reverse=True)
    return rules, excluded


def _boundary(phrase):
    """Regex for `phrase` that will not match inside a longer word.

    This matters more than it looks: "Frontier II" contains the substring
    "tier II", and a plain `in` test would read it as Tier 2 capital. Same for
    "Lionbridge Loan" against "bridge loan".
    """
    return re.compile(r"(?<![A-Za-z])" + re.escape(phrase) + r"(?![A-Za-z])")


def details_in_name(name, rules, excluded):
    """Every distinct detail stated in a project name. Usually none."""
    if not name:
        return set()
    text = name.lower()
    for phrase in excluded:
        text = text.replace(phrase, " ")
    return {detail for phrase, detail in rules if _boundary(phrase).search(text)}


def derive_instrument_details(conn):
    """Fill instrument_detail from seniority stated in the PROJECT NAME.

    Runs after the label mapping and before the overrides, so a hand-reviewed
    override still wins. Only ever fills a detail that is currently NULL — it
    never argues with one a source label already stated.

    Three things make this safe enough to do automatically:
      * only literal phrases from the rules CSV match, with word boundaries;
      * a name that states TWO different seniorities is ambiguous and is
        logged rather than resolved ("Senior and Subordinated Loan" is
        genuinely both, and picking one would be a coin toss);
      * the detail must belong to the row's family. "Mezzanine" is a debt
        detail, so a mezzanine FUND that mapped to Equity is skipped
        automatically rather than mislabelled.

    Returns (filled, ambiguous, family_mismatch).
    """
    rules, excluded = read_instrument_detail_rules()
    for issue in ("ambiguous_instrument_detail", "instrument_detail_family_mismatch"):
        conn.execute("DELETE FROM quality_issues WHERE issue_type = ?", (issue,))

    filled, ambiguous, mismatch = 0, [], []
    for row in conn.execute(
            """SELECT p.id, p.institution, p.project_name, pi.canonical_instrument fam
               FROM projects p JOIN project_instruments pi ON pi.project_id = p.id
               WHERE pi.instrument_detail IS NULL
                 AND p.project_name IS NOT NULL""").fetchall():
        found = details_in_name(row["project_name"], rules, excluded)
        if not found:
            continue
        if len(found) > 1:
            ambiguous.append((row["institution"], row["project_name"], sorted(found)))
            continue
        detail = found.pop()
        allowed = INSTRUMENT_DETAILS.get(row["fam"], ())
        if detail not in allowed:
            mismatch.append((row["institution"], row["project_name"],
                             detail, row["fam"]))
            continue
        conn.execute(
            "UPDATE project_instruments SET instrument_detail = ?, "
            "detail_provenance = 'project_name' "
            "WHERE project_id = ? AND canonical_instrument = ?",
            (detail, row["id"], row["fam"]))
        filled += 1

    for institution, name, found in ambiguous:
        log_quality_issue(
            conn, institution, name, "ambiguous_instrument_detail",
            f"The project name states more than one seniority ({', '.join(found)}), "
            "so no detail was recorded. Splitting one row across two rankings "
            "would be a guess; naming it as one of them would be wrong.")
    for institution, name, detail, family in mismatch:
        log_quality_issue(
            conn, institution, name, "instrument_detail_family_mismatch",
            f"The project name suggests {detail!r}, which is a detail of a "
            f"different family, while this deal maps to {family!r}. Not applied. "
            "The usual cause is a fund vehicle whose NAME describes what the "
            "fund does: a 'Mezzanine Fund' the DFI holds equity in is not "
            "mezzanine debt the DFI extended.")
    return filled, ambiguous, mismatch


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
            previous = [(r[0], r[1]) for r in conn.execute(
                "SELECT canonical_instrument, instrument_detail "
                "FROM project_instruments WHERE project_id = ? "
                "ORDER BY canonical_instrument", (row["id"],)).fetchall()]
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
            for family, detail in values:
                conn.execute(
                    "INSERT OR IGNORE INTO project_instruments "
                    "(project_id, canonical_instrument, instrument_detail, "
                    " detail_provenance, provenance) VALUES (?, ?, ?, ?, ?)",
                    (row["id"], family, detail,
                     "manual_override" if detail else None, "override"))
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
        "dates, amounts, safeguards and funding window). AfDB DOES publish a "
        "finance type in its own IATI feed (XM-DAC-46002), and "
        "enrich_afdb_instruments.py recovers it by joining on the AfDB project "
        "code — so if this issue is showing, that step has not been run."),
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
        "project page. EIB's IATI feed (XM-DAC-918-3) was checked on 2026-08-19 "
        "and REJECTED as a source for this: it states a finance type on all "
        "1,395 of its activities, but only ~21% of our 3,241 loan-part names "
        "appear in it (different grain — activities, not loan parts) and it "
        "stops in 2025 while our existing source runs to 2026. Enriching from it "
        "would join a fifth of our rows against a feed 18 months behind."),
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
        # Enrichment counts as coverage: once AfDB's IATI finance types are in,
        # "AfDB publishes no instrument" is no longer the useful thing to say.
        has_any = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE institution = ? AND ("
            "(instrument IS NOT NULL AND TRIM(instrument) <> '') OR "
            "(instrument_enriched IS NOT NULL AND TRIM(instrument_enriched) <> ''))",
            (institution,)).fetchone()[0]
        if has_any:
            continue        # a loader now captures it; the finding is stale
        log_quality_issue(conn, institution, None,
                          "instrument_absent_from_source", finding)
        flagged.append(institution)
    return flagged


def harmonize_instruments(conn):
    """Rebuild project_instruments from the CSV, in two passes.

    Pass 1 reads `projects.instrument` — the field the loaded source published.
    Pass 2 reads `projects.instrument_enriched` — the same institution's
    instrument recovered from a different publication of its own (today only
    AfDB, from its IATI feed; see enrich_afdb_instruments.py) — but ONLY for
    projects whose loaded source published nothing. Enrichment fills silence;
    it never argues with a disclosure.

    Both passes share one mapping CSV and one unmapped report, so a finance
    type nobody has classified yet surfaces exactly like an unknown label.
    Rows are tagged with where they came from, so a chart can always separate
    an institution's own instrument field from one recovered elsewhere.

    Returns (rows_written, unmapped, enriched_rows).
    """
    mapping = read_instrument_mapping()

    # Own only these: the child table in full, and the issues this run raises.
    conn.execute("DELETE FROM project_instruments")
    conn.execute("DELETE FROM quality_issues WHERE issue_type = 'unmapped_instrument'")

    unmapped: dict = {}

    def apply(sql, provenance):
        for row in conn.execute(sql).fetchall():
            key = (row["institution"], (row["value"] or "").strip())
            if key not in mapping:
                unmapped[key] = unmapped.get(key, 0) + 1
                continue
            for family, detail in mapping[key]:   # empty list -> nothing written
                conn.execute(
                    "INSERT OR IGNORE INTO project_instruments "
                    "(project_id, canonical_instrument, instrument_detail, "
                    " detail_provenance, provenance) VALUES (?, ?, ?, ?, ?)",
                    (row["id"], family, detail,
                     provenance if detail else None, provenance))

    apply("SELECT id, institution, instrument AS value FROM projects "
          "WHERE instrument IS NOT NULL AND TRIM(instrument) <> ''",
          "source_label")
    apply("SELECT id, institution, instrument_enriched AS value FROM projects "
          "WHERE (instrument IS NULL OR TRIM(instrument) = '') "
          "AND instrument_enriched IS NOT NULL "
          "AND TRIM(instrument_enriched) <> ''",
          "iati_enrichment")

    for (institution, raw), n in sorted(unmapped.items()):
        log_quality_issue(
            conn, institution, None, "unmapped_instrument",
            f"Instrument label {raw!r} ({n} projects) has no row in "
            "instrument_mapping.csv")

    written = conn.execute("SELECT COUNT(*) FROM project_instruments").fetchone()[0]
    enriched = conn.execute(
        "SELECT COUNT(*) FROM project_instruments "
        "WHERE provenance = 'iati_enrichment'").fetchone()[0]
    return written, unmapped, enriched


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
    instrument_rows, instruments_unmapped, enriched_rows = harmonize_instruments(conn)
    detailed, ambiguous, mismatched = derive_instrument_details(conn)
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

    if enriched_rows:
        print(f"             {enriched_rows} of those recovered from an "
              "institution's own IATI feed (provenance='iati_enrichment').")
    print(f"             {detailed} detail(s) recovered from project names "
          f"({len(ambiguous)} ambiguous, {len(mismatched)} wrong family - both logged).")
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
