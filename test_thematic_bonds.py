"""test_thematic_bonds.py — proves the thematic bond tagging behaves.

Run:
    python test_thematic_bonds.py

Its own suite because the failure modes here are specific. This is a
use-of-proceeds LABEL, not an instrument, and the two ways to get it wrong
are tagging something that is not a bond at all (an explicit green LOAN), and
reading a theme out of a framework's NAME ("Climate Bonds Initiative",
"Social Bond Principles") rather than out of what the deal is called.

Builds a throwaway in-memory database and a throwaway rules CSV. Exits
non-zero if any check fails.

Checks:
  1. a themed bond named in the project title is tagged, provenance
     'project_name';
  2. one named only in the description is tagged, provenance 'description';
  3. the name wins - a theme found in both is recorded once, from the name;
  4. a NON-bond is never tagged, however green it sounds - including
     when a theme phrase genuinely matches but nothing is a bond;
  5. a framework name does not create a theme - the green-loan-certified-by-
     the-Climate-Bonds-Initiative case that this guard was added for;
  6. one bond can carry two themes, because "Social Bond with a Gender Focus"
     genuinely is both;
  7. a sustainability bond and a sustainability-LINKED bond are different
     things and never collapse;
  8. a rerun changes nothing;
  9. the rules CSV is the source of truth.
"""

import csv
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import derive_thematic_bonds as dtb  # noqa: E402
from database import SCHEMA, MIGRATIONS  # noqa: E402

RULES = [
    ("Green bond", "green bond", ""),
    ("Green bond", "green note", ""),
    ("Social bond", "social bond", ""),
    ("Sustainability bond", "sustainable bond", ""),
    ("Sustainability-linked bond", "sustainability-linked bond", ""),
    ("Blue bond", "blue bond", ""),
    ("Gender bond", "gender focus", ""),
    ("exclude_phrase", "climate bonds initiative", "a certifier, not a label"),
    ("exclude_phrase", "social bond principles", "an ICMA standard, not a label"),
]

# (id, project_name, description)
PROJECTS = [
    (1, "Banco Pichincha - Green Bond", None),
    (2, "Virtuo Finance SARL", "DFC will participate in a green note purchase."),
    (3, "Acme Green Bond", "the green bond will be issued in June"),
    (4, "Green Loan for Renewable Energy",
     "the first green loan certified by the Climate Bonds Initiative"),
    (5, "Solar Park Equity Investment", "a very green project indeed"),
    (6, "Banistmo Social Bond with a Gender Focus", None),
    (7, "BBVA - Subordinated Sustainable Bond", None),
    (8, "Enel - Sustainability-Linked Bond", None),
    (9, "Promerica Bond",
     "a bond aligned with the Social Bond Principles issued by ICMA"),
    (10, "Ocean Fund Blue Bond", None),
    # Exercises the bond guard specifically: "gender focus" is a theme
    # phrase and matches, but nothing here is a bond. Without the guard
    # this equity deal becomes a "Gender bond".
    (11, "Women's Banking Equity Investment",
     "an equity investment made with a gender focus"),
]

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        if detail:
            print(f"          {detail}")
        failures.append(label)


def write_rules(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["theme", "phrase", "notes"])
        w.writerows(rows)


def build_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for table, column, sql_type in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
    for pid, name, desc in PROJECTS:
        conn.execute(
            "INSERT INTO projects (id, project_name, description, institution, "
            "source_url, scraped_at) VALUES (?, ?, ?, 'TEST', 'http://x.test', "
            "'2026-01-01')", (pid, name, desc))
    return conn


def themes(conn, pid):
    return {(r[0], r[1]) for r in conn.execute(
        "SELECT theme, provenance FROM project_themes WHERE project_id = ?",
        (pid,)).fetchall()}


def main():
    tmp = Path(tempfile.mkdtemp())
    dtb.RULES_CSV = tmp / "thematic_bond_rules.csv"
    write_rules(dtb.RULES_CSV, RULES)

    conn = build_db()
    counts = dtb.derive(conn)

    print("\n1. a theme in the project name")
    check("'Banco Pichincha - Green Bond' -> Green bond, from the name",
          themes(conn, 1) == {("Green bond", "project_name")},
          f"got {themes(conn, 1)}")

    print("\n2. a theme only in the description")
    check("'green note purchase' in prose -> Green bond, from the description",
          themes(conn, 2) == {("Green bond", "description")},
          f"got {themes(conn, 2)}")

    print("\n3. the name wins when both mention it")
    check("tagged once, from the name", themes(conn, 3) == {("Green bond", "project_name")},
          f"got {themes(conn, 3)} - the same theme was recorded twice")
    # The stored row cannot reveal double-counting on its own: INSERT OR
    # IGNORE absorbs the duplicate silently. The reported counts can, and
    # the counts are what a person actually reads, so assert on those.
    desc_greens = counts.get(("Green bond", "description"), 0)
    check("and counted once - the reported total is not inflated",
          desc_greens == 1,
          "only project 2 is description-sourced; got " + str(desc_greens))

    print("\n4. a non-bond is never tagged")
    check("an explicit green LOAN is not a green bond", themes(conn, 4) == set(),
          f"got {themes(conn, 4)}")
    check("a 'very green' equity deal is not a green bond", themes(conn, 5) == set(),
          f"got {themes(conn, 5)}")
    check("a matching phrase on a NON-bond tags nothing",
          themes(conn, 11) == set(),
          f"got {themes(conn, 11)} - 'gender focus' tagged an equity deal")

    print("\n5. a framework name does not create a theme")
    check("'Climate Bonds Initiative' alone tags nothing", themes(conn, 4) == set())
    check("'Social Bond Principles' alone tags nothing", themes(conn, 9) == set(),
          f"got {themes(conn, 9)} - a standard's name was read as a label")

    print("\n6. one bond, two themes")
    check("'Social Bond with a Gender Focus' is both",
          themes(conn, 6) == {("Social bond", "project_name"),
                              ("Gender bond", "project_name")},
          f"got {themes(conn, 6)}")

    print("\n7. sustainability and sustainability-LINKED never collapse")
    check("'Sustainable Bond' -> Sustainability bond only",
          themes(conn, 7) == {("Sustainability bond", "project_name")},
          f"got {themes(conn, 7)}")
    check("'Sustainability-Linked Bond' -> the linked theme only",
          themes(conn, 8) == {("Sustainability-linked bond", "project_name")},
          f"got {themes(conn, 8)}")

    print("\n8. the run is idempotent")
    def snap():
        return sorted(tuple(r) for r in conn.execute(
            "SELECT project_id, theme, provenance FROM project_themes"))
    before = snap()
    dtb.derive(conn)
    check("a second run changes nothing", snap() == before)

    print("\n9. the rules CSV is the source of truth")
    write_rules(dtb.RULES_CSV, [r for r in RULES if r[1] != "blue bond"])
    dtb.derive(conn)
    check("removing the blue rule untags the blue bond", themes(conn, 10) == set(),
          f"got {themes(conn, 10)}")
    write_rules(dtb.RULES_CSV, RULES)
    dtb.derive(conn)
    check("restoring it tags again",
          themes(conn, 10) == {("Blue bond", "project_name")})

    if failures:
        print(f"\n{len(failures)} CHECK(S) FAILED: {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
