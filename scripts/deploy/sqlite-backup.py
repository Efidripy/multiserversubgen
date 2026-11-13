#!/usr/bin/env python3
"""Create an online, integrity-checked SQLite backup without overwriting files."""
import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    source = args.database.resolve(strict=True)
    # Exclusive creation prevents replacing an existing backup or the live database.
    fd = os.open(args.backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db:
            with closing(sqlite3.connect(args.backup)) as backup:
                db.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise RuntimeError("backup integrity check failed")
    except BaseException:
        args.backup.unlink(missing_ok=True)
        raise
    print("Backup integrity check: ok")


if __name__ == "__main__":
    main()
