#!/usr/bin/env python3
"""Create an online, integrity-checked SQLite backup without overwriting files."""
import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path


def backup_database(database, destination):
    source = database.resolve(strict=True)
    # Exclusive creation prevents replacing an existing backup or the live database.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db:
            with closing(sqlite3.connect(destination)) as backup:
                db.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise RuntimeError("backup integrity check failed")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("backup", type=Path)
    parser.add_argument("--metrics-database", type=Path)
    parser.add_argument("--metrics-backup", type=Path)
    args = parser.parse_args()
    if bool(args.metrics_database) != bool(args.metrics_backup):
        parser.error("--metrics-database and --metrics-backup must be supplied together")
    backup_database(args.database, args.backup)
    if args.metrics_database:
        backup_database(args.metrics_database, args.metrics_backup)
    print("Backup integrity check: ok")


if __name__ == "__main__":
    main()
