"""
derive_thematic_bonds.py — tags green, social, blue and gender bonds.

Run after the loaders, any time:
    python derive_thematic_bonds.py

Why this is a dimension of its own, not an instrument
-----------------------------------------------------
A green bond is a senior bond that happens to be green. The theme is a
USE-OF-PROCEEDS label sitting on top of an instrument, not an instrument. Put
these in the instrument vocabulary and every "what share of X is equity"
denominator breaks, because one deal would be both Senior debt and Green bond
in the same one-to-many table. So themes get their own child table.

It is a child table rather than a column because one bond is routinely two
things at once: IDB Invest's "Social Bond with a Gender Focus" is genuinely
both social and gender, and a single column would drop half of that.

Why deriving this is safe, when deriving instruments was not
------------------------------------------------------------
This project refuses to infer an instrument from a description, because
structure has to be disclosed to be known. A theme is different in kind: the
issuer NAMES the bond. "Banco Pichincha - Green Bond" is not our reading of a
green bond, it is what the thing is called. We are recording a label, not
deducing a structure.

Two guards keep that honest:

  * Only literal phrases from thematic_bond_rules.csv match. No fuzzy
    matching, no stemming, no "looks environmental" scoring.
  * A phrase only counts on a row that is ALREADY a bond - the text must also
    say bond, note or sukuk. Without this, "gender focus" would tag equity
    deals and technical assistance as gender bonds.

Every tag records whether it came from the project name or the description,
in project_themes.provenance, because a name is the issuer's own label while
a description is prose that mentions it.

Out of scope, deliberately: thematic LOANS. There are 28 "green loan" and 6
"sustainability-linked loan" mentions in the data. They are a real and
growing market, but they are a different instrument and would need their own
decision about whether to sit in this table.
"""

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection, log_quality_issue

RULES_CSV = Path(__file__).parent / "thematic_bond_rules.csv"

# The row must look like a bond for any theme phrase to count. Deliberately
# narrow: these are the words issuers use for a debt security.
BOND_RE = re.compile(r"\b(bonds?|notes?|sukuk|debentures?)\b", re.I)


def read_rules():
    """thematic_bond_rules.csv -> ({theme: [phrase, ...]}, [excluded phrase, ...]).

    `exclude_phrase` rows are framework and organisation names that CONTAIN a
    theme phrase without saying anything about this deal - "Climate Bonds
    Initiative" is a certifier, "Social Bond Principles" is the ICMA standard.
    They are removed from the text before any theme is looked for. Without
    this, an explicit green LOAN certified by the Climate Bonds Initiative
    gets tagged as a green bond.
    """
    rules: dict = {}
    excluded: list = []
    with open(RULES_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            theme = (row["theme"] or "").strip()
            phrase = (row["phrase"] or "").strip().lower()
            if not phrase:
                continue
            if theme == "exclude_phrase":
                excluded.append(phrase)
            elif theme:
                rules.setdefault(theme, []).append(phrase)
    for theme in rules:
        rules[theme].sort(key=len, reverse=True)
    excluded.sort(key=len, reverse=True)
    return rules, excluded


def themes_in(text, rules, excluded):
    """Themes whose phrase appears in `text`, if `text` is about a bond."""
    if not text:
        return set()
    lowered = text.lower()
    for phrase in excluded:               # framework names first, so a theme
        lowered = lowered.replace(phrase, " ")   # cannot be read out of one
    if not BOND_RE.search(lowered):
        return set()                      # not a bond: no theme can apply
    return {theme for theme, phrases in rules.items()
            if any(p in lowered for p in phrases)}


def derive(conn):
    """Rebuild project_themes. Returns {(theme, provenance): count}."""
    rules, excluded = read_rules()

    conn.execute("DELETE FROM project_themes")
    conn.execute("DELETE FROM quality_issues WHERE issue_type = 'thematic_bonds_derived'")

    counts: dict = {}
    for row in conn.execute(
            "SELECT id, project_name, description FROM projects").fetchall():
        # The project name is the issuer's own label and wins; the description
        # is prose that mentions it, and only fills in what the name missed.
        from_name = themes_in(row["project_name"], rules, excluded)
        from_desc = themes_in(row["description"], rules, excluded) - from_name
        for theme, provenance in ([(t, "project_name") for t in from_name]
                                  + [(t, "description") for t in from_desc]):
            conn.execute(
                "INSERT OR IGNORE INTO project_themes (project_id, theme, provenance) "
                "VALUES (?, ?, ?)", (row["id"], theme, provenance))
            counts[(theme, provenance)] = counts.get((theme, provenance), 0) + 1

    tagged = conn.execute(
        "SELECT COUNT(DISTINCT project_id) FROM project_themes").fetchone()[0]
    if tagged:
        log_quality_issue(
            conn, "ALL", None, "thematic_bonds_derived",
            f"{tagged} deals carry a thematic bond label, derived from the "
            "issuer's own wording in the project name or description "
            "(thematic_bond_rules.csv). These are use-of-proceeds LABELS, not "
            "instruments, and live in project_themes. A phrase only counts on "
            "a row whose text also says bond, note or sukuk.")
    return counts


def main():
    conn = get_connection()
    counts = derive(conn)
    conn.commit()

    themes = sorted({t for t, _ in counts})
    print(f"{'theme':<30}{'from name':>11}{'from desc':>11}{'total':>8}")
    print("-" * 60)
    for theme in themes:
        n = counts.get((theme, "project_name"), 0)
        d = counts.get((theme, "description"), 0)
        print(f"{theme:<30}{n:>11}{d:>11}{n + d:>8}")
    tagged = conn.execute(
        "SELECT COUNT(DISTINCT project_id) FROM project_themes").fetchone()[0]
    both = conn.execute(
        "SELECT COUNT(*) FROM (SELECT project_id FROM project_themes "
        "GROUP BY project_id HAVING COUNT(*) > 1)").fetchone()[0]
    print("-" * 60)
    print(f"{'DEALS TAGGED':<30}{'':>11}{'':>11}{tagged:>8}")
    print(f"  of which carry more than one label: {both}")

    print("\nby institution:")
    # Aggregate over DISTINCT PROJECTS, not over the join: a deal with two
    # themes appears twice in the join, and SUM(DISTINCT amount) would also be
    # wrong because it collapses two deals that happen to be the same size.
    for r in conn.execute(
            "SELECT institution, COUNT(*) n, "
            "ROUND(SUM(COALESCE(amount_usd,0))/1e9, 2) bn FROM projects "
            "WHERE id IN (SELECT project_id FROM project_themes) "
            "GROUP BY 1 ORDER BY n DESC").fetchall():
        print(f"   {r['institution']:<12} {r['n']:>4} deals   ${r['bn']:>6,.2f}bn")
    conn.close()


if __name__ == "__main__":
    main()
