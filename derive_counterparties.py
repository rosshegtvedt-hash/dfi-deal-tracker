"""
derive_counterparties.py — fills in who each deal was actually WITH.

Run after the loaders, any time:
    python derive_counterparties.py

Why this exists
---------------
"Which DFIs are active where" is answerable from what the loaders already
collect. "Who do they back, and who has backed the same company twice" is not:
only IFC, Proparco, ADB and IDB Invest publish a sponsor/client field, which
leaves about 70% of the database with no named counterparty.

Every other source was checked for a client field before this was written, and
NONE has one — unlike AfDB's instrument, which really was published elsewhere:
  * EBRD's investments spreadsheet has ten columns and the only name in it is
    "Operation Name".
  * BII's IATI activities do name a participating org, but it is CDC Group Plc
    — BII itself, as funder. There is no implementing or extending org.
  * FMO's world-map records carry `title` and nothing client-like.
  * DFC's table has "Project Name" and no borrower column.

So this is DERIVED, and is labelled as such on every row it writes.

What it does
------------
1. Where the source published a sponsor, that is used verbatim:
   counterparty_provenance = 'disclosed'.
2. Where it did not, and the institution is one whose name field IS a client
   name (see NAME_IS_COUNTERPARTY below), the project name is cleaned using
   counterparty_rules.csv and used:
   counterparty_provenance = 'derived_from_project_name'.
3. Both get a `counterparty_key` — uppercased, legal form removed, punctuation
   collapsed — which is what makes "who appears in two institutions' books"
   answerable.

What it deliberately does NOT do
--------------------------------
* No fuzzy matching. The key is a normalisation, not a similarity score. Two
  spellings that still differ after normalising stay separate, so a real
  relationship is missed rather than a false one invented. Matching across
  institutions is left to report_counterparties.py, where agreement between
  two independent sources is itself the confidence signal.
* AfDB and EIB Global are excluded outright: their name fields hold project and
  asset names ("Ethiopia - Agri-MSMES Development for Jobs Project",
  "ISTANBUL-ANKARA RAILWAY"), not clients. Deriving counterparties from those
  would manufacture thousands of companies that do not exist.
* A name that is only a country ("Republic of Indonesia") is not a company.
  Those are caught using country_mapping.csv rather than a second list.
"""

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection, log_quality_issue

RULES_CSV = Path(__file__).parent / "counterparty_rules.csv"
COUNTRY_CSV = Path(__file__).parent / "country_mapping.csv"

# Whether an institution's project-name field names the CLIENT or the PROJECT.
# Decided by reading samples from each source directly (2026-08-19) rather than
# assumed, with the evidence kept here so it can be re-argued from data.
NAME_IS_COUNTERPARTY = {
    "FMO": True,          # world-map titles are investees: "Banco Macro Sociedad Anonima"
    "BII": True,          # IATI titles are investees: "Aavas Financiers Limited"
    "DFC": True,          # "AgDevCo Limited", "Stichting Cordaid"; sovereigns filtered below
    "EBRD": True,         # "Operation Name" is the client, usually behind a programme code
    "AfDB": False,        # "Ethiopia - Agri-MSMES Development for Jobs (AMD4J) Project"
    "EIB Global": False,  # "ISTANBUL-ANKARA RAILWAY", "GOKCEKAYA - SEYITOMER - IZMIR"
}

# An institution naming ITSELF is not a client relationship. IFC's sponsor
# field says "INTERNATIONAL FINANCE CORPORATION" on 20 of its own rows. Only
# SELF-references are dropped: FMO naming ADB, or IDB Invest naming Proparco,
# is a real disclosure about a co-investor and is kept.
SELF_ALIASES = {
    "IFC": {"IFC", "INTERNATIONAL FINANCE CORPORATION"},
    "EBRD": {"EBRD", "EUROPEAN BANK FOR RECONSTRUCTION AND DEVELOPMENT"},
    "FMO": {"FMO", "NEDERLANDSE FINANCIERINGS MAATSCHAPPIJ VOOR ONTWIKKELINGSLANDEN"},
    "Proparco": {"PROPARCO", "PROPARCO FR", "PROPARCO SA"},
    "BII": {"BII", "CDC GROUP", "CDC GROUP PLC", "BRITISH INTERNATIONAL INVESTMENT",
            "BRITISH INTERNATIONAL INVESTMENT PLC"},
    "ADB": {"ADB", "ASIAN DEVELOPMENT BANK"},
    "AfDB": {"AFDB", "AFRICAN DEVELOPMENT BANK"},
    "DFC": {"DFC", "US INTERNATIONAL DEVELOPMENT FINANCE CORPORATION"},
    "IDB Invest": {"IDB INVEST", "INTER AMERICAN INVESTMENT CORPORATION"},
    "EIB Global": {"EIB", "EIB GLOBAL", "EUROPEAN INVESTMENT BANK"},
}

# Words that describe a STATE rather than name a company. Stripping them and
# re-testing against country_mapping.csv catches sovereign borrowers whose
# full style is not a country spelling we have on file: "Democratic Republic
# Of The Sudan" is Sudan, "Islamic Republic of Pakistan" is Pakistan. Without
# this they survive as clients and, worse, match each other across
# institutions as if a country were a repeat customer.
#
# This only ever REMOVES a name. "Development Bank of Ghana" reduces to
# "DEVELOPMENT BANK GHANA", which is not a country, so it is kept.
STATE_WORDS = r"(?<![A-Z])(THE|OF|REPUBLIC|DEMOCRATIC|ISLAMIC|FEDERAL|FEDERATIVE|KINGDOM|STATE|STATES|UNITED|PEOPLES|ARAB|COMMONWEALTH|PLURINATIONAL|BOLIVARIAN|SOCIALIST|GOVERNMENT|MINISTRY|TREASURY)(?![A-Z])"

MIN_LENGTH = 3            # anything shorter identifies nobody

SEPARATORS = "-:–—"     # hyphen, colon, en dash, em dash


def read_rules():
    """counterparty_rules.csv -> (prefixes, suffixes, legal_suffixes, excludes)."""
    # 'not_a_prefix' rows are read and ignored on purpose: they record
    # leading acronyms that look like programme codes but are real clients
    # (OTP Bank, TBC Bank, NLB), so nobody re-adds them from the data.
    buckets = {"prefix": [], "suffix": [], "legal_suffix": [], "exclude": []}
    with open(RULES_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            kind = (row["rule_type"] or "").strip()
            pattern = (row["pattern"] or "").strip()
            if kind in buckets and pattern:
                buckets[kind].append(pattern)
    # Longest first, so "SME CREDIT LINE" is tried before "CREDIT LINE" and
    # "PRIVATE LIMITED" before "LIMITED".
    for key in buckets:
        buckets[key].sort(key=len, reverse=True)
    return (buckets["prefix"], buckets["suffix"],
            buckets["legal_suffix"], {e.upper() for e in buckets["exclude"]})


def read_country_names():
    """Every country spelling we already know, reused as an exclusion list."""
    names = set()
    with open(COUNTRY_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            for key in ("source_country", "canonical_country"):
                value = (row.get(key) or "").strip()
                if value:
                    names.add(value.upper())
                    names.add(f"REPUBLIC OF {value}".upper())
    return names


def strip_prefixes(name, prefixes):
    """Remove leading programme codes, repeatedly: 'FIF - RSF - Bank' -> 'Bank'."""
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            # A programme code is followed by a separator OR just a space
            # ("RSF - TBC Bank" and "RSF TSKB - Sapro II" are both prefixed).
            # Only codes listed in the CSV are stripped - stripping every
            # leading acronym would eat OTP Bank, TBC Bank and NLB.
            pattern = rf"^\s*{re.escape(prefix)}\s*[IVX0-9]*\s*(?:[{SEPARATORS}]|\s)\s*"
            new = re.sub(pattern, "", name, flags=re.I)
            if new != name:
                name, changed = new.strip(), True
    return name


def strip_suffixes(name, suffixes):
    """Remove trailing product words: 'NOA Agribusiness Credit Line' -> 'NOA Agribusiness'."""
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            pattern = rf"[\s,{SEPARATORS}]*{re.escape(suffix)}\s*$"
            new = re.sub(pattern, "", name, flags=re.I)
            if new != name and len(new.strip()) >= MIN_LENGTH:
                name, changed = new.strip(), True
    return name


def make_key(name, legal_suffixes):
    """Normalise for matching across institutions. A normalisation, not a score."""
    key = name.upper()
    changed = True
    while changed:
        changed = False
        for suffix in legal_suffixes:
            pattern = rf"[\s.,{SEPARATORS}]*{re.escape(suffix)}\s*$"
            new = re.sub(pattern, "", key)
            if new != key and len(new.strip()) >= MIN_LENGTH:
                key, changed = new.strip(), True
    key = re.sub(r"[^A-Z0-9 ]+", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def sovereign_core(name):
    """A name with its state-describing words removed, for country testing."""
    core = re.sub("[^A-Z ]", " ", name.upper())
    return " ".join(re.sub(STATE_WORDS, " ", core).split())


def clean(name, prefixes, suffixes, excludes, countries):
    """Project name -> counterparty, or None if it identifies no company."""
    if not name:
        return None
    cleaned = strip_suffixes(strip_prefixes(name.strip(), prefixes), suffixes)
    cleaned = cleaned.strip(" .,;" + SEPARATORS)
    if len(cleaned) < MIN_LENGTH:
        return None
    upper = cleaned.upper()
    if upper in excludes or upper in countries:
        return None
    if sovereign_core(cleaned) in countries:   # a state, however it is styled
        return None
    if not re.search(r"[A-Za-z]", cleaned):        # digits/punctuation only
        return None
    return cleaned


def derive(conn):
    """Fill counterparty / key / provenance. Returns per-institution counts."""
    prefixes, suffixes, legal_suffixes, excludes = read_rules()
    countries = read_country_names()

    conn.execute("UPDATE projects SET counterparty = NULL, counterparty_key = NULL, "
                 "counterparty_provenance = NULL")
    for issue in ("counterparty_not_derivable", "counterparty_name_not_a_client"):
        conn.execute("DELETE FROM quality_issues WHERE issue_type = ?", (issue,))

    stats = {}
    for row in conn.execute(
            "SELECT id, institution, project_name, sponsor FROM projects").fetchall():
        institution = row["institution"]
        counts = stats.setdefault(institution,
                                  {"disclosed": 0, "derived": 0, "none": 0})

        sponsor = (row["sponsor"] or "").strip()
        if sponsor:
            # A disclosed sponsor is used verbatim - no prefix or suffix
            # stripping, because rewriting what a source stated would be
            # reinterpreting it. Only the "identifies nobody" list is applied:
            # "UNKNOWN" is not a name in either mode.
            #
            # Note the deliberate asymmetry with derived names. A sovereign the
            # source NAMES is a real client ("Government of the Province of
            # Cordoba" borrowed from IFC), so it is kept. A country-looking
            # name we DERIVED is evidence the name field is recording a place
            # rather than a client, so it is dropped.
            name = None if sponsor.upper() in excludes else sponsor
            provenance = "disclosed"
        elif NAME_IS_COUNTERPARTY.get(institution):
            name = clean(row["project_name"], prefixes, suffixes, excludes, countries)
            provenance = "derived_from_project_name"
        else:
            name, provenance = None, None

        if not name:
            counts["none"] += 1
            continue
        key = make_key(name, legal_suffixes)
        if key in SELF_ALIASES.get(institution, set()):
            counts["none"] += 1     # the institution naming itself, not a client
            continue
        conn.execute(
            "UPDATE projects SET counterparty = ?, counterparty_key = ?, "
            "counterparty_provenance = ? WHERE id = ?",
            (name, key, provenance, row["id"]))
        counts["disclosed" if provenance == "disclosed" else "derived"] += 1

    for institution, counts in sorted(stats.items()):
        if NAME_IS_COUNTERPARTY.get(institution) is False:
            log_quality_issue(
                conn, institution, None, "counterparty_name_not_a_client",
                f"No counterparty derived for {institution}. Its project-name field "
                "names the PROJECT or the ASSET, not the client (checked against "
                "samples 2026-08-19), and the source publishes no sponsor field. "
                "Deriving companies from these names would invent them.")
        elif counts["none"]:
            log_quality_issue(
                conn, institution, None, "counterparty_not_derivable",
                f"{counts['none']} {institution} projects have no counterparty: the "
                "source published no sponsor, and the project name did not survive "
                "cleaning (a country, a programme name, or too generic to identify "
                "anyone). Left NULL rather than guessed.")
    return stats


def main():
    conn = get_connection()
    stats = derive(conn)
    conn.commit()

    print(f"{'institution':<13}{'disclosed':>10}{'derived':>9}{'none':>8}   coverage")
    print("-" * 54)
    named_total = 0
    for institution, counts in sorted(stats.items(),
                                      key=lambda kv: -sum(kv[1].values())):
        named = counts["disclosed"] + counts["derived"]
        total = named + counts["none"]
        named_total += named
        print(f"{institution:<13}{counts['disclosed']:>10}{counts['derived']:>9}"
              f"{counts['none']:>8}   {100 * named // total:>3}%")
    grand = sum(sum(v.values()) for v in stats.values())
    print("-" * 54)
    print(f"{'ALL':<13}{'':>10}{'':>9}{'':>8}   {100 * named_total // grand:>3}%"
          f"  ({named_total:,} of {grand:,})")
    conn.close()


if __name__ == "__main__":
    main()
