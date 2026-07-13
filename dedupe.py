"""
dedupe.py — flags probable co-financed deals that appear in more than one
institution's database.

Run after loaders:
    python dedupe.py

How it works, in plain language:
  * Two records are compared only if they are from DIFFERENT institutions,
    in the same country, and within 1 year of each other (fiscal years
    differ between institutions, so exact-year matching would miss real
    co-financings).
  * Project names are normalized first — lowercased, punctuation removed,
    legal suffixes like 'Ltd'/'S.A.' dropped — then compared with Python's
    built-in fuzzy matcher (difflib). Similarity >= 0.80 counts as a match;
    if either record has no usable year, we demand >= 0.90 instead.
  * Matches are chained into groups (if A~B and B~C, all three share one
    group) and each group gets an ID like 'DUP-0001' written to the
    probable_duplicate_group column. Nothing is deleted or merged —
    the column is a flag for your review.
  * Rerunning clears and rebuilds all groups, so it stays in sync after
    every load.

Caveat: name matching can't catch co-financings where institutions use
completely different names for the same deal, and it can false-positive on
generic names ('XYZ Bank SME Facility'). Treat flags as leads, not verdicts.
"""

import re
import sys
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection

SIMILARITY_THRESHOLD = 0.80
SIMILARITY_THRESHOLD_NO_YEAR = 0.90
YEAR_TOLERANCE = 1

# Legal/boilerplate tokens that carry no identity ("Acme Ltd" == "Acme LLC"),
# plus deal-description filler ADB puts in names ("LOAN TO KHAN BANK").
STOP_TOKENS = {
    "ltd", "limited", "llc", "plc", "inc", "corp", "corporation", "co",
    "sa", "sarl", "srl", "pte", "pvt", "bv", "nv", "ag", "gmbh", "as",
    "jsc", "cjsc", "ojsc", "pjsc", "the",
    "loan", "to", "of", "and", "project",
}

# Institutions spell country names differently; normalize before blocking.
COUNTRY_ALIASES = {
    "turkiye": "turkey",
    "trkiye": "turkey",  # 'Türkiye' after non-ASCII chars are stripped
    "viet nam": "vietnam",
    "cote d'ivoire": "ivory coast",
    "cote divoire": "ivory coast",
    "democratic republic of the congo": "dr congo",
    "congo, democratic republic of": "dr congo",
    "congo, democratic republic": "dr congo",
    "egypt, arab republic of": "egypt",
    "russian federation": "russia",
    "kyrgyz republic": "kyrgyzstan",
    "lao people's democratic republic": "laos",
    "lao pdr": "laos",
    "myanmar (burma)": "myanmar",
    "burma": "myanmar",
    "west bank and gaza": "palestine",
}


def normalize_name(name: str) -> str:
    name = name.lower()
    # ADB prefixes names with a country/region code ('IND: DAHEJ LNG...');
    # strip it so the prefix doesn't drag down similarity scores.
    name = re.sub(r"^\s*[a-z]{2,4}\s*:\s*", "", name)
    tokens = re.sub(r"[^a-z0-9 ]", " ", name).split()
    return " ".join(t for t in tokens if t not in STOP_TOKENS)


def normalize_country(country) -> str:
    if not country:
        return ""
    c = re.sub(r"[^a-z' ,]", "", str(country).lower()).strip()
    return COUNTRY_ALIASES.get(c, c)


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def tokens_contained(a: str, b: str) -> bool:
    """True when the shorter name's words all appear in the longer name's
    (e.g. 'khan bank' within 'loan to khan bank' after stop-word removal).
    Requires 2+ meaningful words so single generic words can't match."""
    ta, tb = set(a.split()), set(b.split())
    if len(ta) > len(tb):
        ta, tb = tb, ta
    return len(ta) >= 2 and ta <= tb


def main():
    conn = get_connection()

    # Prefer the harmonized country (set by harmonize.py) for blocking, so
    # 'Türkiye'/'Turkiye'/'Turkey' records land in the same comparison block;
    # fall back to the raw label if harmonization hasn't run.
    rows = conn.execute(
        """SELECT id, institution, project_name,
                  COALESCE(canonical_country, country) AS country,
                  COALESCE(CAST(strftime('%Y', approval_date) AS INTEGER), fiscal_year) AS year
           FROM projects WHERE project_name IS NOT NULL"""
    ).fetchall()

    # Block by country: only records in the same country are ever compared.
    blocks = {}
    for r in rows:
        blocks.setdefault(normalize_country(r["country"]), []).append({
            "id": r["id"],
            "institution": r["institution"],
            "name": normalize_name(r["project_name"]),
            "raw_name": r["project_name"],
            "year": r["year"],
        })
    blocks.pop("", None)  # records with no country can't be safely matched

    # Union-find so chained matches (A~B, B~C) end up in one group.
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    compared = matched = 0
    for country, items in blocks.items():
        for a, b in combinations(items, 2):
            if a["institution"] == b["institution"]:
                continue
            if not a["name"] or not b["name"]:
                continue
            both_years = bool(a["year"] and b["year"])
            if both_years:
                if abs(a["year"] - b["year"]) > YEAR_TOLERANCE:
                    continue
                threshold = SIMILARITY_THRESHOLD
            else:
                threshold = SIMILARITY_THRESHOLD_NO_YEAR
            compared += 1
            # Containment only counts when both years are known — it is a
            # looser test, so it needs the tighter time window to back it up.
            if (similar(a["name"], b["name"]) >= threshold
                    or (both_years and tokens_contained(a["name"], b["name"]))):
                union(a["id"], b["id"])
                matched += 1

    # Collect groups of 2+ records and write group IDs.
    groups = {}
    for row_id in parent:
        groups.setdefault(find(row_id), []).append(row_id)
    groups = [ids for ids in groups.values() if len(ids) > 1]

    conn.execute("UPDATE projects SET probable_duplicate_group = NULL")
    for n, ids in enumerate(sorted(groups, key=min), start=1):
        group_id = f"DUP-{n:04d}"
        conn.executemany(
            "UPDATE projects SET probable_duplicate_group = ? WHERE id = ?",
            [(group_id, i) for i in ids],
        )
    conn.commit()

    flagged = sum(len(ids) for ids in groups)
    print(f"Compared {compared:,} cross-institution pairs; "
          f"flagged {flagged} projects in {len(groups)} probable duplicate groups.")

    if groups:
        print("\nGroups for review:")
        detail = conn.execute(
            """SELECT probable_duplicate_group, institution, project_name, country,
                      COALESCE(strftime('%Y', approval_date), CAST(fiscal_year AS TEXT)) AS yr,
                      amount_usd
               FROM projects WHERE probable_duplicate_group IS NOT NULL
               ORDER BY probable_duplicate_group, institution"""
        ).fetchall()
        current = None
        for r in detail:
            if r[0] != current:
                current = r[0]
                print(f"  {current}:")
            amount_m = (r[5] or 0) / 1_000_000
            print(f"    [{r[1]}] {r[2]} | {r[3]} | {r[4]} | ${amount_m:,.1f}M")

    conn.close()


if __name__ == "__main__":
    main()
