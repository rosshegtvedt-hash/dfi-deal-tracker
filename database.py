"""
database.py — creates and connects to the DFI Deal Tracker SQLite database.

Run directly to (re)create the schema:
    python database.py

Import from other modules to get a connection or log a data-quality issue:
    from database import get_connection, log_quality_issue
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# The database lives in /data next to the raw source files.
# Path(__file__).parent = the folder this file is in, so paths work
# no matter which directory you run the scripts from.
DB_PATH = Path(__file__).parent / "data" / "dfi_tracker.db"

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
    amount_original REAL,               -- amount in the source's own currency
    currency        TEXT,               -- ISO code of amount_original, e.g. 'USD'
    amount_usd      REAL,               -- amount in plain US dollars (not millions)
    approval_date   TEXT,               -- ISO format 'YYYY-MM-DD'; NULL if unknown
    fiscal_year     INTEGER,            -- source's fiscal year when no exact date is disclosed
    status          TEXT,
    es_category     TEXT,               -- environmental & social risk category
    sponsor         TEXT,
    description     TEXT,
    source_url      TEXT NOT NULL,      -- where this record came from
    scraped_at      TEXT NOT NULL,      -- ISO timestamp of the load run
    canonical_sector    TEXT,           -- harmonized sector (set by harmonize.py)
    canonical_subsector TEXT,           -- harmonized subsector (set by harmonize.py)
    probable_duplicate_group TEXT,      -- group ID for likely co-financed deals (set by dedupe.py)
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

CREATE INDEX IF NOT EXISTS idx_projects_institution ON projects (institution);
CREATE INDEX IF NOT EXISTS idx_projects_country     ON projects (country);
CREATE INDEX IF NOT EXISTS idx_projects_sector      ON projects (sector);
"""


# Columns added after the first release. get_connection() adds any that are
# missing, so an existing database upgrades in place without losing data.
MIGRATIONS = [
    ("fiscal_year", "INTEGER"),
    ("canonical_sector", "TEXT"),
    ("canonical_subsector", "TEXT"),
    ("probable_duplicate_group", "TEXT"),
    ("canonical_country", "TEXT"),
    ("canonical_region", "TEXT"),
]


def get_connection() -> sqlite3.Connection:
    """Open a connection, creating the database and schema if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # lets us access columns by name
    conn.executescript(SCHEMA)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    for column, sql_type in MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE projects ADD COLUMN {column} {sql_type}")
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
