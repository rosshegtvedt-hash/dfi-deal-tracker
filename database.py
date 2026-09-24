"""
database.py — creates and connects to the DFI Deal Tracker SQLite database.

Run directly to (re)create the schema:
    python database.py

Import from other modules to get a connection or log a data-quality issue:
    from database import get_connection, log_quality_issue
"""

import json
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# The database lives in /data next to the raw source files.
# Path(__file__).parent = the folder this file is in, so paths work
# no matter which directory you run the scripts from.
DB_PATH = Path(__file__).parent / "data" / "dfi_tracker.db"

# The database is not in git (too big, rebuilt by the pipeline), so these
# snapshots are its only history besides OneDrive's. They sit OUTSIDE the
# repo on purpose: a checkout can silently overwrite an ignored file inside
# it, which is how the 2026-09-24 copy was lost. Newest BACKUPS_KEPT kept,
# counted by file rather than by age so a month away doesn't empty the folder.
BACKUP_DIR = Path(__file__).parent.parent / "DFI Deal Tracker Backups"
BACKUPS_KEPT = 14

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    institution     TEXT NOT NULL,      -- 'DFC', 'IFC', 'EBRD', ...
    project_name    TEXT,
    country         TEXT,
    region          TEXT,
    sector          TEXT,
    subsector       TEXT,
    instrument      TEXT,               -- loan, equity, guarantee, insurance, ...
    instrument_enriched TEXT,           -- instrument from a DIFFERENT publication by the
                                        -- same institution, used only where the source we
                                        -- load publishes none (AfDB: its IATI finance-type).
                                        -- Never overwrites `instrument`; see harmonize.py.
    amount_original REAL,               -- amount in the source's own currency
    currency        TEXT,               -- ISO code of amount_original, e.g. 'USD'
    amount_usd      REAL,               -- amount in plain US dollars (not millions)
    approval_date   TEXT,               -- ISO format 'YYYY-MM-DD'; NULL if unknown
    fiscal_year     INTEGER,            -- source's fiscal year when no exact date is disclosed
    status          TEXT,
    es_category     TEXT,               -- environmental & social risk category
    sponsor         TEXT,
    counterparty    TEXT,               -- the client/investee/borrower, for BD analysis
    counterparty_key TEXT,              -- normalised form of counterparty, for matching across institutions
    counterparty_provenance TEXT,       -- 'disclosed' (the source named it) or 'derived_from_project_name'
    mobilised_original REAL,            -- third-party capital raised alongside this deal,
    mobilised_usd      REAL,            -- in the deal's currency and in USD. NOT part of
                                        -- amount_usd: it is other people's money.
    description     TEXT,
    source_url      TEXT NOT NULL,      -- where this record came from
    scraped_at      TEXT NOT NULL,      -- ISO timestamp of the load run
    canonical_sector    TEXT,           -- harmonized sector (set by harmonize.py)
    canonical_subsector TEXT,           -- harmonized subsector (set by harmonize.py)
    probable_duplicate_group TEXT,      -- group ID for likely co-financed deals (set by dedupe.py)
    canonical_es_category TEXT,         -- harmonized E&S risk level (set by harmonize.py)
    canonical_country   TEXT,           -- harmonized country name (set by harmonize.py)
    canonical_region    TEXT            -- harmonized region (set by harmonize.py)
);

-- Rows with problems still go into projects (with NULLs where data was bad);
-- this table records what was wrong so nothing fails silently.
CREATE TABLE IF NOT EXISTS quality_issues (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    institution  TEXT NOT NULL,
    project_name TEXT,
    issue_type   TEXT NOT NULL,         -- 'missing_amount', 'unparseable_date', ...
    detail       TEXT,                  -- human-readable explanation
    raw_row      TEXT,                  -- JSON snapshot of the offending source row
    logged_at    TEXT NOT NULL
);

-- Harmonized instruments, set by harmonize_instruments.py from
-- instrument_mapping.csv. A CHILD TABLE rather than a column on projects,
-- because the mapping is one-to-many: EBRD's "Debt + Equity" is evidence for
-- BOTH debt and equity, and a single column would silently drop half of
-- every combined instrument. projects.instrument keeps the raw source value
-- and is never modified.
CREATE TABLE IF NOT EXISTS project_instruments (
    project_id           INTEGER NOT NULL,
    -- The FAMILY level: Debt, Equity, Guarantee, Political risk insurance,
    -- Technical assistance / grant. Always assignable from what a source
    -- publishes. It deliberately says "Debt", not "Senior debt": almost no
    -- source discloses seniority, and asserting it was a real bug -- IFC's
    -- "Ecobank Ghana Tier II Subordinated Debt" was stored as senior.
    canonical_instrument TEXT    NOT NULL,
    -- The DETAIL level, and NULL is the normal case. NULL means "the source
    -- did not state it", NOT "senior". Never backfill it with a guess.
    --   debt:   senior, subordinated, mezzanine, shareholder_loan, bridge,
    --           receivables_facility
    --   equity: common, preferred
    instrument_detail    TEXT,
    -- Where the detail came from, mirroring `provenance` below:
    --   'source_label'  -- the raw instrument field said it
    --   'project_name'  -- the project's own title said it
    --   'iati_enrichment' / 'manual_override'
    detail_provenance    TEXT,
    -- Where this canonical value came from, so a chart can always tell an
    -- institution's own instrument field from one recovered elsewhere:
    --   'source_label'    -- projects.instrument, the field the loaded source published
    --   'iati_enrichment' -- projects.instrument_enriched, the same institution's IATI feed
    --   'override'        -- instrument_overrides.csv, a hand-reviewed per-deal decision
    provenance           TEXT    NOT NULL DEFAULT 'source_label',
    UNIQUE (project_id, canonical_instrument),
    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
);

-- Thematic bond labels (green, social, blue, ...), set by
-- derive_thematic_bonds.py from thematic_bond_rules.csv. A CHILD TABLE for
-- the same reason as instruments: one bond is routinely two things at once,
-- e.g. a "Social Bond with a Gender Focus" is both social and gender.
--
-- This is a USE-OF-PROCEEDS label, NOT an instrument. A green bond is a
-- senior bond that happens to be green; putting these in the instrument
-- vocabulary would corrupt every "what share is equity" denominator.
CREATE TABLE IF NOT EXISTS project_themes (
    project_id  INTEGER NOT NULL,
    theme       TEXT    NOT NULL,
    provenance  TEXT    NOT NULL,   -- 'project_name' or 'description'
    labelled_instrument TEXT,       -- 'bond' or 'loan': what the LABELLED
                                    -- instrument is. The theme itself is
                                    -- instrument-agnostic.
    UNIQUE (project_id, theme),
    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_project_themes_theme ON project_themes (theme);

CREATE INDEX IF NOT EXISTS idx_project_instruments_instrument
    ON project_instruments (canonical_instrument);

CREATE INDEX IF NOT EXISTS idx_projects_institution ON projects (institution);
CREATE INDEX IF NOT EXISTS idx_projects_country     ON projects (country);
CREATE INDEX IF NOT EXISTS idx_projects_sector      ON projects (sector);
"""


# Columns added after the first release, as (table, column, type).
# get_connection() adds any that are missing, so an existing database upgrades
# in place without losing data.
# Whether the DFI's exposure is to the state. Populated ONLY from a flag the
# source itself publishes; never inferred from a borrower's name.
#
# THIS IS DELIBERATELY NOT THE SIBLING'S THREE-VALUE `ownership` VOCABULARY
# (sovereign / sub-sovereign / private, in ../DFI Mandate Match/config.py).
# AfDB publishes a BINARY, and its non-sovereign window carries state-owned
# enterprises and private project companies side by side - Transnet, Eskom,
# Cahora Bassa and Ethiopian Airlines sit in the same bucket as Scatec, Lake
# Turkana Wind and Xina Solar One. Mapping "non-sovereign" onto "private"
# would assert an ownership the source never stated. Splitting this field
# into the sibling's three values needs a separate state-owned-enterprise
# identification pass; until then the honest value set is the one AfDB uses.
#
# NULL means the source we loaded publishes no such flag. It does NOT mean
# private: eight of the ten institutions simply do not say.
CANONICAL_SOVEREIGN_EXPOSURE = (
    "sovereign",       # the state, or state-guaranteed
    "non-sovereign",   # not state-guaranteed; may still be a state-owned entity
)


MIGRATIONS = [
    ("projects", "fiscal_year", "INTEGER"),
    ("projects", "canonical_sector", "TEXT"),
    ("projects", "canonical_subsector", "TEXT"),
    ("projects", "probable_duplicate_group", "TEXT"),
    ("projects", "canonical_es_category", "TEXT"),
    ("projects", "canonical_country", "TEXT"),
    ("projects", "canonical_region", "TEXT"),
    ("projects", "instrument_enriched", "TEXT"),
    # harmonize.py rebuilds project_instruments in full on every run, so
    # existing rows taking the default here are corrected on the next run.
    ("project_instruments", "provenance", "TEXT NOT NULL DEFAULT 'source_label'"),
    ("projects", "counterparty", "TEXT"),
    ("projects", "counterparty_key", "TEXT"),
    ("projects", "counterparty_provenance", "TEXT"),
    ("projects", "mobilised_original", "REAL"),
    ("projects", "mobilised_usd", "REAL"),
    ("project_themes", "labelled_instrument", "TEXT"),
    ("project_instruments", "instrument_detail", "TEXT"),
    ("project_instruments", "detail_provenance", "TEXT"),
    ("projects", "sovereign_exposure", "TEXT"),
    ("projects", "sovereign_provenance", "TEXT"),
]


def backup_database(today: date | None = None) -> Path | None:
    """Snapshot the database once per day, before anything writes to it.

    Uses SQLite's backup API rather than a file copy, so the snapshot is
    consistent even if another connection is mid-write. Returns the new
    snapshot's path, or None when there was nothing to do (no database yet,
    or today's snapshot already exists). A failure warns and returns None:
    a full disk should not stop the pipeline, but it must not pass silently.
    """
    if not DB_PATH.exists():
        return None
    target = BACKUP_DIR / f"dfi_tracker_{(today or date.today()).isoformat()}.db"
    if target.exists():
        return None
    partial = target.with_suffix(".db.partial")
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(partial)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        # Rename last, so an interrupted backup never looks like a good one.
        partial.replace(target)
        snapshots = sorted(BACKUP_DIR.glob("dfi_tracker_????-??-??.db"))
        for old in snapshots[:-BACKUPS_KEPT]:
            old.unlink()
        return target
    except (OSError, sqlite3.Error) as exc:
        print(f"WARNING: database backup to {target} failed: {exc}",
              file=sys.stderr)
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def get_connection() -> sqlite3.Connection:
    """Open a connection, creating the database and schema if needed.

    The first connection of each day snapshots the database first (see
    backup_database), so every pipeline run has a copy of what it started from.
    """
    backup_database()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # lets us access columns by name
    # SQLite ignores foreign keys unless asked, per connection. With this on,
    # a loader wiping its institution's projects also clears that institution's
    # project_instruments rows (ON DELETE CASCADE) instead of orphaning them.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for table, column, sql_type in MIGRATIONS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
    # Indexes on migrated columns must come AFTER the migrations: on an
    # existing database CREATE TABLE is a no-op, so a column added by
    # MIGRATIONS does not exist yet while SCHEMA is running.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_cpty_key "
                 "ON projects (counterparty_key)")
    return conn


def utc_now() -> str:
    """Current UTC time as an ISO string, used for scraped_at / logged_at."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_quality_issue(conn, institution, project_name, issue_type, detail, raw_row=None):
    """Record a data-quality problem. raw_row can be a dict; stored as JSON."""
    conn.execute(
        "INSERT INTO quality_issues (institution, project_name, issue_type, detail, raw_row, logged_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            institution,
            project_name,
            issue_type,
            detail,
            json.dumps(raw_row, default=str) if raw_row is not None else None,
            utc_now(),
        ),
    )


if __name__ == "__main__":
    conn = get_connection()
    conn.close()
    print(f"Database ready at {DB_PATH}")
