"""test_backup.py — proves the daily database snapshot works and prunes safely.

Run:
    python test_backup.py

The database stopped being versioned in git on 2026-09-14, so these snapshots
are its only local history. A backup that silently fails, or a pruning rule
that deletes the wrong file, would not show up until the day it was needed.

Points database.DB_PATH and database.BACKUP_DIR at a throwaway directory;
never reads or writes the real tracker or the real backup folder. Exits
non-zero if any check fails.

Checks:
  1. no database yet -> no snapshot, and no backup folder is created;
  2. the first call of a day writes a snapshot whose rows match the source;
  3. a second call the same day does NOT overwrite it — the snapshot must
     keep the state the day STARTED from, before the pipeline wrote to it;
  4. a new day writes a new snapshot;
  5. only the newest BACKUPS_KEPT snapshots survive, oldest pruned first,
     and files that are not snapshots are never touched;
  6. get_connection() takes the snapshot itself, so no pipeline step can
     forget to;
  7. a failure warns and returns None instead of raising, and leaves no
     half-written file that could pass for a good snapshot.
"""

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent))
import database  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        if detail:
            print(f"          {detail}")
        failures.append(label)


def rows_in(path):
    """The snapshot's rows, or an error string, so an empty or broken
    snapshot FAILS a check by name instead of crashing the suite."""
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT name FROM t ORDER BY name").fetchall()
    except sqlite3.Error as exc:
        return f"unreadable snapshot: {exc}"
    finally:
        conn.close()


def write_db(path, names):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (name TEXT)")
    conn.execute("DELETE FROM t")
    conn.executemany("INSERT INTO t VALUES (?)", [(n,) for n in names])
    conn.commit()
    conn.close()


def main():
    real_db, real_dir, real_kept = (database.DB_PATH, database.BACKUP_DIR,
                                    database.BACKUPS_KEPT)
    with TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        database.DB_PATH = tmp / "data" / "dfi_tracker.db"
        database.BACKUP_DIR = tmp / "backups"
        database.BACKUPS_KEPT = 3
        day = date(2026, 9, 24)
        try:
            print("1. no database yet")
            check("returns None", database.backup_database(day) is None)
            check("creates no backup folder", not database.BACKUP_DIR.exists())

            print("\n2. first call of the day")
            database.DB_PATH.parent.mkdir(parents=True)
            write_db(database.DB_PATH, ["alpha", "beta"])
            first = database.backup_database(day)
            check("returns the snapshot path",
                  first == database.BACKUP_DIR / "dfi_tracker_2026-09-24.db",
                  f"got {first}")
            check("snapshot holds the source's rows",
                  first is not None and rows_in(first) == [("alpha",), ("beta",)])

            print("\n3. second call the same day")
            write_db(database.DB_PATH, ["changed by the pipeline"])
            check("returns None", database.backup_database(day) is None)
            check("snapshot still holds the start-of-day state",
                  rows_in(first) == [("alpha",), ("beta",)],
                  f"got {rows_in(first)} - the morning copy was overwritten")

            print("\n4. a new day")
            second = database.backup_database(day + timedelta(days=1))
            check("writes a new snapshot",
                  second is not None and second.name == "dfi_tracker_2026-09-25.db",
                  f"got {second}")
            check("new snapshot holds the current state",
                  second is not None
                  and rows_in(second) == [("changed by the pipeline",)])

            print("\n5. pruning")
            bystander = database.BACKUP_DIR / "notes.txt"
            bystander.write_text("not a snapshot")
            manual = database.BACKUP_DIR / "dfi_tracker_before_rebuild.db"
            manual.write_text("a copy someone named by hand")
            for offset in range(2, 6):
                database.backup_database(day + timedelta(days=offset))
            kept = sorted(p.name for p in
                          database.BACKUP_DIR.glob("dfi_tracker_????-??-??.db"))
            check("keeps exactly BACKUPS_KEPT snapshots", len(kept) == 3,
                  f"got {kept}")
            check("keeps the NEWEST ones",
                  kept == ["dfi_tracker_2026-09-27.db", "dfi_tracker_2026-09-28.db",
                           "dfi_tracker_2026-09-29.db"], f"got {kept}")
            check("never deletes a file that is not a dated snapshot",
                  bystander.exists() and manual.exists())

            print("\n6. get_connection takes the snapshot")
            for p in database.BACKUP_DIR.glob("dfi_tracker_????-??-??.db"):
                p.unlink()
            conn = database.get_connection()
            conn.close()
            today = database.BACKUP_DIR / f"dfi_tracker_{date.today().isoformat()}.db"
            check("today's snapshot exists after get_connection()", today.exists())

            print("\n7. failures warn instead of raising")

            def attempt(on):
                try:
                    return database.backup_database(on), None
                except Exception as exc:  # noqa: BLE001 - it must not raise
                    return None, exc

            # (a) a FILE where the folder should be: mkdir fails.
            blocked = tmp / "blocked"
            blocked.write_text("in the way")
            good_dir, database.BACKUP_DIR = database.BACKUP_DIR, blocked
            result, exc = attempt(day)
            check("unwritable folder: does not raise", exc is None, f"raised {exc!r}")
            check("unwritable folder: returns None", result is None, f"got {result!r}")
            database.BACKUP_DIR = good_dir

            # (b) a corrupt source: fails AFTER the partial file is opened,
            # which is the case that could leave a half-written snapshot.
            database.DB_PATH.write_bytes(b"not a database " * 1000)
            broken_day = day + timedelta(days=30)
            result, exc = attempt(broken_day)
            check("corrupt source: does not raise", exc is None, f"raised {exc!r}")
            check("corrupt source: returns None", result is None, f"got {result!r}")
            check("corrupt source: no snapshot under the dated name",
                  not (good_dir / f"dfi_tracker_{broken_day.isoformat()}.db").exists())
            leftovers = list(good_dir.glob("*.partial"))
            check("corrupt source: no half-written file left behind",
                  not leftovers, f"found {leftovers}")
        finally:
            database.DB_PATH, database.BACKUP_DIR, database.BACKUPS_KEPT = (
                real_db, real_dir, real_kept)

    if failures:
        print(f"\n{len(failures)} CHECK(S) FAILED: {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
